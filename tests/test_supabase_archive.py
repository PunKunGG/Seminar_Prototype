import io
import json
import os
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from supabase_archive import ArchiveError, SupabaseArchive


class SupabaseArchiveTests(unittest.TestCase):
    def setUp(self):
        self.requests = []

        def opener(request, timeout):
            self.requests.append(request)
            return io.BytesIO(b"[]")

        self.archive = SupabaseArchive(
            "https://example.supabase.co", "server-only-key", opener=opener,
        )

    def test_archive_writes_report_and_image_but_not_video(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = os.path.join(directory, "reference.jpg")
            with open(image_path, "wb") as image_file:
                image_file.write(b"jpeg")
            report = {
                "lab_id": "round-1",
                "tracking": {
                    "session": {
                        "id": "round-1", "name": "Morning",
                        "source_type": "video", "source_label": "clip.mp4",
                        "recording_started_at": "2026-09-20T10:34:00+07:00",
                        "recording_ended_at": "2026-09-20T10:44:00+07:00",
                        "status": "completed",
                    },
                    "evidence": [{"filename": "reference.jpg"}],
                },
            }

            class Evidence:
                def resolve_file(self, session_id, filename):
                    return image_path if session_id == "round-1" else None

            with patch.object(self.archive, "_catalog_id", return_value=1):
                self.archive.archive_report("teacher-id", report, Evidence())

        urls = [request.full_url for request in self.requests]
        self.assertIn("/rest/v1/class_sessions", urls[0])
        self.assertIn("/storage/v1/object/class-evidence/teacher-id/round-1/reference.jpg", urls[1])
        self.assertIn("/rest/v1/class_sessions", urls[2])
        self.assertIn("/rest/v1/analysis_jobs", urls[3])
        self.assertEqual(self.requests[1].data, b"jpeg")
        self.assertIn(b'"result_summary"', self.requests[3].data)
        self.assertIn(b'"room_id": 1', self.requests[2].data)
        self.assertNotIn(b'"video_object_path"', self.requests[2].data)
        for request in self.requests:
            self.assertEqual(request.get_header("Apikey"), "server-only-key")

    def test_report_lookup_is_filtered_by_owner_and_session(self):
        self.archive.get_report("teacher-id", "round-1")

        url = self.requests[0].full_url
        self.assertIn("owner_id=eq.teacher-id", url)
        self.assertIn("session_id=eq.round-1", url)
        self.assertIn("status=eq.completed", url)

    def test_evidence_requires_membership_in_owned_report(self):
        with patch.object(self.archive, "get_report", return_value=None):
            image = self.archive.get_evidence("teacher-id", "other-round", "face.jpg")

        self.assertIsNone(image)
        self.assertEqual(self.requests, [])

    def test_modern_secret_key_is_not_sent_as_bearer_jwt(self):
        archive = SupabaseArchive(
            "https://example.supabase.co",
            "sb_secret_test",
            opener=lambda request, timeout: self.requests.append(request) or io.BytesIO(b"[]"),
        )

        archive.list_sessions("teacher-id")

        self.assertEqual(self.requests[0].get_header("Apikey"), "sb_secret_test")
        self.assertIsNone(self.requests[0].get_header("Authorization"))

    def test_history_excludes_partially_archived_sessions(self):
        sessions = [{"id": "ready"}, {"id": "partial"}]
        with patch.object(self.archive, "_table", side_effect=[
            sessions, [{"session_id": "ready"}],
        ]):
            result = self.archive.list_sessions("teacher-id")

        self.assertEqual(result, [{
            "id": "ready", "room_name": None, "course_name": None,
            "report_total_people": None, "avg_attention_rate": None,
        }])

    def test_history_reads_lightweight_report_metrics_for_owned_sessions(self):
        with patch.object(self.archive, "_table", side_effect=[
            [{"id": "round-1"}, {"id": "round-2"}],
            [
                {"session_id": "round-1", "summary": {
                    "total_records": 20, "report_total_people": 11,
                    "max_people": 11, "latest_total_people": 3,
                    "avg_attention_rate": 72.5,
                }},
                {"session_id": "round-2", "summary": {
                    "total_records": 1, "max_people": 4, "avg_attention_rate": 0,
                }},
            ],
        ]) as query:
            result = self.archive.list_sessions("teacher-id")

        self.assertEqual(result[0]["report_total_people"], 11)
        self.assertEqual(result[0]["avg_attention_rate"], 72.5)
        self.assertEqual(result[1]["report_total_people"], 4)
        self.assertEqual(result[1]["avg_attention_rate"], 0)
        params = parse_qs(query.call_args_list[1].args[1])
        self.assertEqual(params["select"], ["session_id,summary:result_summary->summary"])
        self.assertEqual(params["owner_id"], ["eq.teacher-id"])
        self.assertEqual(params["session_id"], ["in.(round-1,round-2)"])

    def test_history_restores_room_and_course_names(self):
        sessions = [{"id": "ready", "room_id": 2, "course_id": 3}]
        with patch.object(self.archive, "_table", side_effect=[
            sessions, [{"session_id": "ready"}],
            [{"id": 2, "name": "Lab 9226"}],
            [{"id": 3, "name": "AI"}],
        ]) as query:
            result = self.archive.list_sessions("teacher-id")

        self.assertEqual(result[0]["room_name"], "Lab 9226")
        self.assertEqual(result[0]["course_name"], "AI")
        self.assertIn("owner_id=eq.teacher-id", query.call_args_list[2].args[1])

    def test_history_batches_long_session_ids_without_losing_page_metrics(self):
        for id_length in (87, 160):
            with self.subTest(id_length=id_length):
                sessions = [
                    {"id": f"{index:03d}_" + "x" * (id_length - 4)}
                    for index in range(100)
                ]
                indices = {item["id"]: index for index, item in enumerate(sessions)}
                missing_ids = {sessions[index]["id"] for index in (19, 20, 99)}
                requested_ids = []
                job_urls = []

                def opener(request, timeout):
                    url = urlsplit(request.full_url)
                    params = parse_qs(url.query)
                    self.assertEqual(params["owner_id"], ["eq.teacher-id"])
                    if url.path == "/rest/v1/class_sessions":
                        return io.BytesIO(json.dumps(sessions).encode())
                    self.assertEqual(url.path, "/rest/v1/analysis_jobs")
                    self.assertLess(len(request.full_url.encode("ascii")), 4096)
                    self.assertEqual(params["status"], ["eq.completed"])
                    self.assertEqual(params["select"], ["session_id,summary:result_summary->summary"])
                    batch_ids = params["session_id"][0][4:-1].split(",")
                    self.assertLessEqual(len(batch_ids), 20)
                    requested_ids.extend(batch_ids)
                    job_urls.append(request.full_url)
                    rows = [
                        {"session_id": session_id, "summary": {
                            "total_records": 1,
                            "report_total_people": indices[session_id],
                            "avg_attention_rate": indices[session_id] / 2,
                        }}
                        for session_id in batch_ids if session_id not in missing_ids
                    ]
                    return io.BytesIO(json.dumps(rows).encode())

                archive = SupabaseArchive("https://example.supabase.co", "server-only-key", opener=opener)
                result = archive.list_sessions("teacher-id")
                expected_ids = [item["id"] for item in sessions if item["id"] not in missing_ids]
                self.assertEqual([item["id"] for item in result], expected_ids)
                self.assertEqual(requested_ids, [item["id"] for item in sessions])
                self.assertEqual(len(job_urls), 5)
                for item in result:
                    self.assertEqual(item["report_total_people"], indices[item["id"]])
                    self.assertEqual(item["avg_attention_rate"], indices[item["id"]] / 2)

    def test_history_does_not_silently_return_a_partial_page_if_a_batch_fails(self):
        sessions = [{"id": f"round-{index}"} for index in range(21)]
        with patch.object(self.archive, "_table", side_effect=[
            sessions, [{"session_id": "round-0"}], ArchiveError("unavailable"),
        ]):
            with self.assertRaises(ArchiveError):
                self.archive.list_sessions("teacher-id")


if __name__ == "__main__":
    unittest.main()
