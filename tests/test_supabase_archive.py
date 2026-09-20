import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from supabase_archive import SupabaseArchive


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

        self.assertEqual(result, [{"id": "ready", "room_name": None, "course_name": None}])

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


if __name__ == "__main__":
    unittest.main()
