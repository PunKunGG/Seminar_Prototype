import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
SITE_PACKAGES = os.path.join(PROJECT_ROOT, "venv", "Lib", "site-packages")
for directory in (SITE_PACKAGES, BACKEND_DIR):
    if directory not in sys.path:
        sys.path.insert(0, directory)


class SessionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        import app_config

        app_config.CONFIG = app_config.load_config(cls.directory.name, {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
            "CLASSMOOD_DATABASE_PATH": os.path.join(cls.directory.name, "data", "db.sqlite"),
        })
        analyzer = types.ModuleType("behavior_analyzer")
        analyzer.PERSON_DETECTION_CONFIDENCE = 0.5
        analyzer.POSE_IMAGE_SIZE = 640
        analyzer.KP_CONF_THRESHOLD = 0.4
        analyzer.analyze_frame = lambda *args, **kwargs: {}
        analyzer.detect_context_objects = lambda *args, **kwargs: []
        analyzer.get_behavior_measurement_criteria = lambda *args: []
        analyzer.get_behavior_label_en = lambda value: value
        analyzer.get_behavior_label_th = lambda value: value
        sys.modules["behavior_analyzer"] = analyzer
        sys.modules["cv2"] = types.ModuleType("cv2")
        import server

        cls.server = server
        cls.client = server.app.test_client()
        for session_id, owner_id in (("owned", "teacher-a"), ("foreign", "teacher-b")):
            server.session_database.upsert_session(
                session_id,
                name=session_id,
                owner_id=owner_id,
                room_name="Lab 9226",
                course_name="AI",
                source_type="video",
                source_label="clip.mp4",
                recording_started_at="2026-09-20T10:34:00+07:00",
            )
            server.session_database.finish_session(session_id, duration_seconds=600)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()
        sys.modules.pop("server", None)
        sys.modules.pop("behavior_analyzer", None)
        sys.modules.pop("cv2", None)

    def setUp(self):
        with self.client.session_transaction() as browser_session:
            browser_session["auth_user"] = {"id": "teacher-a", "email": "teacher@example.com"}

    def test_history_lists_only_owned_rounds(self):
        response = self.client.get("/api/sessions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json["sessions"]],
            ["owned"],
        )

    def test_report_is_available_without_downloading_and_foreign_report_is_hidden(self):
        own = self.client.get("/api/export/owned")
        foreign = self.client.get("/api/export/foreign")

        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.json["tracking"]["session"]["name"], "owned")
        self.assertEqual(foreign.status_code, 404)

    def test_completed_report_prefers_cloud_copy_and_falls_back_to_local(self):
        archive = types.SimpleNamespace(get_report=lambda owner, session_id: {
            "lab_id": session_id,
            "archive_marker": owner,
        })
        with patch.object(self.server, "supabase_archive", archive):
            cloud = self.client.get("/api/export/owned")
        self.assertEqual(cloud.json["archive_marker"], "teacher-a")

        archive.get_report = lambda owner, session_id: (
            (_ for _ in ()).throw(self.server.ArchiveError("offline"))
        )
        with patch.object(self.server, "supabase_archive", archive):
            local = self.client.get("/api/export/owned")
        self.assertEqual(local.status_code, 200)
        self.assertEqual(local.json["tracking"]["session"]["name"], "owned")

    def test_evidence_route_rejects_foreign_session(self):
        response = self.client.get("/api/evidence/foreign/photo.jpg")

        self.assertEqual(response.status_code, 404)

    def test_analysis_interval_rejects_values_outside_bounds(self):
        for interval in (14, 301):
            with self.subTest(interval=interval):
                response = self.client.post(
                    "/api/sources/new-interval/1",
                    json={"source": 0, "analysis_interval_seconds": interval},
                )
                self.assertEqual(response.status_code, 400)

    def test_video_requires_recording_clock_and_saves_selected_interval(self):
        class Capture:
            def isOpened(self):
                return True

            def get(self, property_id):
                return 30 if property_id == 1 else 18000

            def release(self):
                pass

        cv2 = sys.modules["cv2"]
        with (
            patch.object(self.server, "_normalize_video_source", return_value=("clip.mp4", None)),
            patch.object(self.server, "_stop_capture"),
            patch.object(self.server, "_start_capture", return_value={}),
            patch.object(cv2, "VideoCapture", return_value=Capture(), create=True),
            patch.object(cv2, "CAP_PROP_FPS", 1, create=True),
            patch.object(cv2, "CAP_PROP_FRAME_COUNT", 2, create=True),
        ):
            missing = self.client.post(
                "/api/sources/new-video/1",
                json={"source": "clip.mp4", "analysis_interval_seconds": 30},
            )
            valid = self.client.post(
                "/api/sources/new-video/1",
                json={
                    "source": "clip.mp4",
                    "session_name": "Morning",
                    "recording_start": "2026-09-20T10:34:00+07:00",
                    "analysis_interval_seconds": 30,
                },
            )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(valid.status_code, 200)
        metadata = self.server.session_database.get_session("new-video")
        self.assertEqual(metadata["owner_id"], "teacher-a")
        self.assertEqual(metadata["analysis_interval_seconds"], 30)
        self.assertEqual(metadata["recording_started_at"], "2026-09-20T10:34:00+07:00")


if __name__ == "__main__":
    unittest.main()
