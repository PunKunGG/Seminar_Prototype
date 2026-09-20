import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from session_database import SessionDatabase


class SessionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "sessions.db")

    def make_session(self, database, session_id, owner_id, source_type="video"):
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
        )

    def test_history_is_scoped_to_owner(self):
        database = SessionDatabase(self.path)
        self.make_session(database, "first", "teacher-a")
        self.make_session(database, "second", "teacher-b")

        self.assertEqual(
            [item["id"] for item in database.list_sessions("teacher-a")],
            ["first"],
        )
        self.assertEqual(database.get_session("first")["analysis_interval_seconds"], 30)

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
