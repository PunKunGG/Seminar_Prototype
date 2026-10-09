import os
import math
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from session_database import SessionDatabase
from report_qualification import REPORT_POLICY, qualify_tracking


class SessionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "sessions.db")

    def make_session(self, database, session_id, owner_id, source_type="video", report_policy=None):
        database.upsert_session(
            session_id,
            name=session_id,
            owner_id=owner_id,
            room_name="Lab 9226",
            course_name="AI",
            source_type=source_type,
            source_label="clip.mp4" if source_type == "video" else "Webcam 0",
            recording_started_at="2026-09-20T10:34:00+07:00",
            analysis_interval_seconds=30,
            report_policy=report_policy,
        )

    def store_events(self, database, session_id, specifications):
        events = []
        durations = {}
        counts = {}
        for index, (behavior, seconds, segments) in enumerate(specifications, start=1):
            duration = seconds if math.isfinite(seconds) else 0
            durations[behavior] = durations.get(behavior, 0) + duration
            counts[behavior] = counts.get(behavior, 0) + 1
            events.append({
                "event_index": index, "behavior": behavior, "start_seconds": 0,
                "end_seconds": duration, "duration_seconds": seconds, "avg_confidence": 90,
                "observed_segments": [[0, duration, duration]] if segments is None else segments,
            })
        database.sync_tracking(session_id, [{
            "track_id": 1, "first_seen_seconds": 0, "last_seen_seconds": 900,
            "visible_seconds": sum(durations.values()), "attention_rate": 0,
            "current_behavior": "unknown", "behavior_seconds": durations,
            "event_counts": counts, "active": False, "events": events, "buckets": [],
        }])

    def test_history_is_scoped_to_owner(self):
        database = SessionDatabase(self.path)
        self.make_session(database, "first", "teacher-a")
        self.make_session(database, "second", "teacher-b")

        self.assertEqual(
            [item["id"] for item in database.list_sessions("teacher-a")],
            ["first"],
        )
        self.assertEqual(database.get_session("first")["analysis_interval_seconds"], 30)

    def test_qualified_attention_matches_full_reports_without_changing_legacy_data(self):
        database = SessionDatabase(self.path)
        cases = {
            "mixed": [("attentive", 60, None), ("sleeping", 30, None), ("hand_raised", 29.9, None)],
            "sampled": [("hand_raised", 30, [[0, 15, 15], [600, 615, 15]]), ("standing", 30, None)],
            "short": [("attentive", 29.9, None)],
            "exact": [("attentive", 30, None)],
            "over": [("sleeping", 30.1, None)],
            "no-segments": [("attentive", 60, [])],
            "nonfinite": [("attentive", float("inf"), [[0, 1, 1]]), ("sleeping", 60, None)],
            "tolerance": [("attentive", 30 - 5e-10, None)],
            "empty": [],
        }
        expected = {}
        for session_id, events in cases.items():
            self.make_session(database, session_id, "teacher-a", report_policy=REPORT_POLICY)
            self.store_events(database, session_id, events)
            expected[session_id] = qualify_tracking(database.tracking_report(session_id), REPORT_POLICY)["summary"]["attention_rate"]
        custom_policy = {**REPORT_POLICY, "minimum_behavior_seconds": 60}
        self.make_session(database, "custom", "teacher-a", report_policy=custom_policy)
        self.store_events(database, "custom", [("attentive", 30, None), ("sleeping", 60, None)])
        expected["custom"] = 0
        self.make_session(database, "legacy", "teacher-a")
        self.make_session(database, "foreign", "teacher-b", report_policy=REPORT_POLICY)
        self.store_events(database, "foreign", [("attentive", 60, None)])

        self.assertEqual(database.qualified_attention_rates("teacher-a"), expected)
        self.assertEqual(database.qualified_attention_rates("teacher-b"), {"foreign": 100})
        self.assertEqual(database.qualified_attention_rates("missing-owner"), {})
        self.assertNotIn("legacy", database.qualified_attention_rates())
        self.assertIn("foreign", database.qualified_attention_rates())

    def test_qualified_attention_reads_current_tracking_after_update_and_reset(self):
        database = SessionDatabase(self.path)
        self.make_session(database, "clip", "teacher-a", report_policy=REPORT_POLICY)
        self.store_events(database, "clip", [("attentive", 30, None), ("sleeping", 30, None)])
        self.assertEqual(database.qualified_attention_rates("teacher-a"), {"clip": 50})
        self.store_events(database, "clip", [("attentive", 60, None), ("sleeping", 30, None)])
        self.assertEqual(database.qualified_attention_rates("teacher-a"), {"clip": 66.7})
        database.upsert_session("clip", name="clip", owner_id="teacher-a", room_name="Lab 9226",
                                course_name="AI", source_type="video", source_label="clip.mp4",
                                reset_tracking=True, report_policy=REPORT_POLICY)
        self.assertEqual(database.qualified_attention_rates("teacher-a"), {"clip": None})

    def test_history_queries_stay_batched_as_the_number_of_sessions_grows(self):
        database = SessionDatabase(self.path)
        for index in range(120):
            self.make_session(database, f"round-{index}", "teacher-a", report_policy=REPORT_POLICY)
        self.make_session(database, "foreign", "teacher-b", report_policy=REPORT_POLICY)
        statements = []
        connect = database._connect

        def traced_connect():
            connection = connect()
            connection.set_trace_callback(statements.append)
            return connection

        with patch.object(database, "_connect", side_effect=traced_connect):
            sessions = database.list_sessions("teacher-a")
            rates = database.qualified_attention_rates("teacher-a")

        self.assertEqual(len(sessions), 120)
        self.assertEqual(len(rates), 120)
        queries = [statement.lower() for statement in statements if statement.lstrip().upper().startswith("SELECT")]
        self.assertEqual(len(queries), 2)
        self.assertFalse(any("track_time_buckets" in query or "evidence_images" in query for query in queries))

    def test_video_end_is_recording_start_plus_duration(self):
        database = SessionDatabase(self.path)
        self.make_session(database, "clip", "teacher-a")

        database.finish_session("clip", duration_seconds=600)

        session = database.get_session("clip")
        self.assertEqual(session["recording_ended_at"], "2026-09-20T10:44:00+07:00")
        self.assertEqual(session["status"], "completed")
        self.assertNotEqual(session["ended_at"], session["recording_ended_at"])

    def test_webcam_end_uses_current_time(self):
        database = SessionDatabase(self.path)
        self.make_session(database, "camera", "teacher-a", source_type="webcam")

        database.finish_session("camera")

        self.assertLess(
            abs((datetime.fromisoformat(database.get_session("camera")["recording_ended_at"])
                 - datetime.now().astimezone()).total_seconds()),
            3,
        )

    def test_interrupted_video_is_not_marked_completed(self):
        database = SessionDatabase(self.path)
        self.make_session(database, "partial", "teacher-a")

        database.finish_session("partial", duration_seconds=90, status="cancelled")

        session = database.get_session("partial")
        self.assertEqual(session["status"], "cancelled")
        self.assertEqual(session["recording_ended_at"], "2026-09-20T10:35:30+07:00")

    def test_existing_database_is_extended_without_losing_rows(self):
        connection = sqlite3.connect(self.path)
        connection.execute(
            "CREATE TABLE class_sessions (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "room_id INTEGER, course_id INTEGER, source_type TEXT, "
            "source_label TEXT, recording_started_at TEXT NOT NULL, "
            "created_at TEXT NOT NULL, ended_at TEXT, status TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO class_sessions (id, name, recording_started_at, "
            "created_at, status) VALUES (?, ?, ?, ?, ?)",
            ("legacy", "Older session", "2026-09-01T09:00:00+07:00",
             "2026-09-01T09:00:00+07:00", "completed"),
        )
        connection.commit()
        connection.close()

        database = SessionDatabase(self.path)

        self.assertEqual(database.get_session("legacy")["name"], "Older session")
        self.assertIsNone(database.get_session("legacy")["owner_id"])

    def test_archive_rows_decode_tracking_json_for_supabase(self):
        database = SessionDatabase(self.path)
        self.make_session(database, "clip", "teacher-a")
        database.sync_tracking("clip", [{
            "track_id": 1,
            "first_seen_seconds": 0,
            "last_seen_seconds": 15,
            "visible_seconds": 15,
            "attention_rate": 100,
            "current_behavior": "attentive",
            "behavior_seconds": {"attentive": 15},
            "event_counts": {"attentive": 1},
            "active": False,
            "events": [{
                "event_index": 0, "behavior": "attentive",
                "start_seconds": 0, "end_seconds": 15,
                "duration_seconds": 15, "avg_confidence": 85,
            }],
            "buckets": [{
                "bucket_start_seconds": 0, "visible_seconds": 15,
                "behavior_seconds": {"attentive": 15},
                "event_counts": {"attentive": 1},
            }],
        }])

        rows = database.archive_rows("clip")

        self.assertEqual(rows["session_tracks"][0]["behavior_seconds"], {"attentive": 15})
        self.assertFalse(rows["session_tracks"][0]["active"])
        self.assertEqual(rows["behavior_events"][0]["event_index"], 0)
        self.assertEqual(rows["track_time_buckets"][0]["event_counts"], {"attentive": 1})


if __name__ == "__main__":
    unittest.main()
