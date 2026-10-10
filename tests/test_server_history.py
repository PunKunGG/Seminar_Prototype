import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
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
        cls.addClassCleanup(cls.directory.cleanup)
        import app_config

        original_config = app_config.CONFIG
        original_modules = {
            name: sys.modules.get(name)
            for name in ("server", "behavior_analyzer", "cv2")
        }

        def restore_module_state():
            app_config.CONFIG = original_config
            for name, module in original_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        cls.addClassCleanup(restore_module_state)
        # The API fixture needs its own server, even if another test imported it.
        sys.modules.pop("server", None)
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

    def test_report_export_time_preserves_the_generation_instant(self):
        generated_at = datetime(2026, 10, 7, 3, 0, 0, tzinfo=timezone.utc)
        with patch.object(self.server, "datetime") as clock:
            clock.now.return_value = generated_at
            response = self.client.get("/api/export/owned")

        self.assertEqual(response.status_code, 200)
        exported_at = datetime.fromisoformat(response.json["export_time"])
        self.assertIsNotNone(exported_at.tzinfo)
        self.assertEqual(exported_at, generated_at)
        clock.now.assert_called_once_with(timezone.utc)

    def test_new_report_and_history_use_qualified_time_but_keep_raw_people(self):
        from person_tracking import SessionTracker
        from report_qualification import REPORT_POLICY

        database = self.server.session_database
        session_id = "new-policy-test"
        database.upsert_session(session_id, name="Qualified", owner_id="teacher-a",
                                room_name="Lab", course_name="AI", source_type="video",
                                source_label="clip.mp4", report_policy=REPORT_POLICY)
        self.addCleanup(lambda: self._delete_test_session(session_id))
        tracker = SessionTracker(record_observed_segments=True, observation_step_seconds=1,
                                 max_observation_gap_seconds=2)
        for timestamp in range(61):
            tracker.update([{"bbox": [0, 0, 100, 200], "behavior": "attentive"}], timestamp=timestamp)
        tracker.update([], timestamp=61)
        for timestamp in range(62, 72):
            tracker.update([{"bbox": [0, 0, 100, 200], "behavior": "attentive"}], timestamp=timestamp)
        database.sync_tracking(session_id, tracker.persistence_snapshot())
        history = [{"total_people": 11, "attention_rate": 70}, {"total_people": 3, "attention_rate": 30}]
        with patch.dict(self.server.stats_history, {session_id: history}):
            report = self.client.get(f"/api/export/{session_id}").json
            with (
                patch.object(database, "tracking_report", side_effect=AssertionError("History must not build full reports")),
                patch.object(database, "qualified_attention_rates", wraps=database.qualified_attention_rates) as aggregate,
            ):
                response = self.client.get("/api/sessions")
            self.assertEqual(response.status_code, 200)
            aggregate.assert_called_once_with("teacher-a")
            item = next(item for item in response.json["sessions"] if item["id"] == session_id)
        self.assertEqual(report["report_policy"], REPORT_POLICY)
        self.assertEqual(report["raw_summary"]["avg_attention_rate"], 50)
        self.assertEqual(report["summary"]["report_total_people"], 11)
        self.assertEqual(report["qualified_analysis"]["summary"]["qualified_seconds"], 60)
        self.assertEqual(report["summary"]["avg_attention_rate"], 100)
        self.assertEqual(item["avg_attention_rate"], 100)
        self.assertEqual(len(report["tracking"]["events"]), 2)
        self.assertEqual(len(report["qualified_analysis"]["events"]), 1)
        self.assertNotIn("report_policy", self.client.get("/api/export/owned").json)

    def _delete_test_session(self, session_id):
        with self.server.session_database._connection() as connection:
            connection.execute("DELETE FROM class_sessions WHERE id = ?", (session_id,))

    def test_history_fetches_qualified_rates_once_for_multiple_rounds(self):
        from report_qualification import REPORT_POLICY

        database = self.server.session_database
        histories = {}
        for index in range(3):
            session_id = f"batch-policy-{index}"
            database.upsert_session(session_id, name=session_id, owner_id="teacher-a",
                                    room_name="Lab", course_name="AI", source_type="video",
                                    source_label="clip.mp4", report_policy=REPORT_POLICY)
            self.addCleanup(self._delete_test_session, session_id)
            histories[session_id] = [{"total_people": 1, "attention_rate": 70}]
        with (
            patch.dict(self.server.stats_history, histories),
            patch.object(database, "tracking_report", side_effect=AssertionError("History must not build full reports")),
            patch.object(database, "qualified_attention_rates", wraps=database.qualified_attention_rates) as aggregate,
        ):
            response = self.client.get("/api/sessions")
        self.assertEqual(response.status_code, 200)
        aggregate.assert_called_once_with("teacher-a")
        returned = {item["id"]: item for item in response.json["sessions"]}
        for session_id in histories:
            self.assertIsNone(returned[session_id]["avg_attention_rate"])
            self.assertEqual(returned[session_id]["report_total_people"], 1)

    def test_history_keeps_persisted_qualified_rates_without_in_memory_observations(self):
        from person_tracking import SessionTracker
        from report_qualification import REPORT_POLICY
        from session_database import SessionDatabase

        database = self.server.session_database
        expected = {}
        for behavior, seconds, rate in (("attentive", 20, None), ("attentive", 30, 100), ("standing", 30, 0)):
            session_id = f"persisted-{behavior}-{seconds}"
            database.upsert_session(session_id, name=session_id, owner_id="teacher-a",
                                    room_name="Lab", course_name="AI", source_type="video",
                                    source_label="clip.mp4", report_policy=REPORT_POLICY)
            self.addCleanup(self._delete_test_session, session_id)
            tracker = SessionTracker(record_observed_segments=True, observation_step_seconds=1,
                                     max_observation_gap_seconds=2)
            for timestamp in range(seconds + 1):
                tracker.update([{"bbox": [0, 0, 100, 200], "behavior": behavior}], timestamp=timestamp)
            database.sync_tracking(session_id, tracker.persistence_snapshot())
            database.finish_session(session_id, duration_seconds=seconds)
            expected[session_id] = rate

        restarted_database = SessionDatabase(database.path)
        unavailable_archive = types.SimpleNamespace(list_sessions=lambda owner: (
            (_ for _ in ()).throw(self.server.ArchiveError("offline"))
        ))
        for archive in (None, unavailable_archive):
            with (
                self.subTest(archive_enabled=archive is not None),
                patch.object(self.server, "session_database", restarted_database),
                patch.object(self.server, "supabase_archive", archive),
                patch.dict(self.server.stats_history, {}, clear=True),
                patch.object(restarted_database, "tracking_report", side_effect=AssertionError("History must not build full reports")),
                patch.object(restarted_database, "qualified_attention_rates", wraps=restarted_database.qualified_attention_rates) as aggregate,
            ):
                response = self.client.get("/api/sessions")
                self.assertEqual(response.status_code, 200)
                aggregate.assert_called_once_with("teacher-a")
                returned = {item["id"]: item for item in response.json["sessions"]}
                for session_id, rate in expected.items():
                    self.assertEqual(returned[session_id]["avg_attention_rate"], rate)
                    self.assertIsNone(returned[session_id]["report_total_people"])
                self.assertIsNone(returned["owned"]["avg_attention_rate"])
                self.assertNotIn("foreign", returned)

    def test_tracker_factory_enables_new_policy_only_for_new_rounds(self):
        from report_qualification import REPORT_POLICY

        for processing_mode in ("realtime", "sampled"):
            for new_policy in (False, True):
                with self.subTest(mode=processing_mode, new_policy=new_policy):
                    metadata = {"processing_mode": processing_mode, "report_policy": REPORT_POLICY if new_policy else None}
                    tracker = self.server._new_session_tracker(metadata)
                    self.assertEqual(tracker.persistent_positions, new_policy)
                    self.assertEqual(tracker.record_observed_segments, new_policy)

    def test_history_metrics_use_whole_round_not_final_frame(self):
        history = [
            {"total_people": 11, "attention_rate": 80},
            {"total_people": 3, "attention_rate": 60},
        ]
        with patch.dict(self.server.stats_history, {"owned": history}):
            item = self.client.get("/api/sessions").json["sessions"][0]
        self.assertEqual(item["report_total_people"], 11)
        self.assertEqual(item["avg_attention_rate"], 70)

    def test_history_without_observations_has_no_measurements(self):
        with patch.dict(self.server.stats_history, {"owned": []}):
            item = self.client.get("/api/sessions").json["sessions"][0]
        self.assertIsNone(item["report_total_people"])
        self.assertIsNone(item["avg_attention_rate"])

    def test_history_prefers_archived_metrics_for_existing_local_round(self):
        archive = types.SimpleNamespace(list_sessions=lambda owner: [{
            "id": "owned", "report_total_people": 11, "avg_attention_rate": 72.5,
        }])
        with patch.object(self.server, "supabase_archive", archive):
            item = self.client.get("/api/sessions").json["sessions"][0]
        self.assertEqual(item["storage"], "supabase")
        self.assertEqual(item["report_total_people"], 11)
        self.assertEqual(item["avg_attention_rate"], 72.5)

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
