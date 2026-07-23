import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from person_tracking import SessionTracker
from evidence_store import EvidenceStore
from session_database import SessionDatabase


def detection(bbox, behavior="attentive", confidence=90):
    return {
        "bbox": bbox,
        "behavior": behavior,
        "confidence": confidence,
    }


class SessionTrackerTests(unittest.TestCase):
    def make_tracker(self):
        return SessionTracker(
            observation_step_seconds=0.5,
            max_observation_gap_seconds=1.0,
            max_missing_seconds=5.0,
        )

    def test_keeps_id_when_person_moves_slightly(self):
        tracker = self.make_tracker()

        first = tracker.update(
            [detection([10, 10, 110, 210])],
            timestamp=0,
        )
        second = tracker.update(
            [detection([18, 12, 118, 212])],
            timestamp=0.5,
        )

        self.assertEqual(first["detections"][0]["track_id"], 1)
        self.assertTrue(first["detections"][0]["is_new_track"])
        self.assertTrue(first["detections"][0]["event_started"])
        self.assertEqual(second["detections"][0]["track_id"], 1)
        self.assertFalse(second["detections"][0]["is_new_track"])
        self.assertFalse(second["detections"][0]["event_started"])
        self.assertEqual(len(tracker.summaries()), 1)

    def test_creates_separate_ids_for_separate_people(self):
        tracker = self.make_tracker()

        result = tracker.update(
            [
                detection([10, 10, 110, 210]),
                detection([300, 10, 400, 210]),
            ],
            timestamp=0,
        )

        self.assertEqual(
            [item["track_id"] for item in result["detections"]],
            [1, 2],
        )

    def test_behavior_transition_is_counted_once_after_debounce(self):
        tracker = self.make_tracker()
        bbox = [10, 10, 110, 210]
        tracker.update([detection(bbox)], timestamp=0)
        tracker.update([detection(bbox, "sleeping")], timestamp=1)
        tracker.update([detection(bbox, "sleeping")], timestamp=2)
        result = tracker.update(
            [detection(bbox, "sleeping")],
            timestamp=3.6,
        )
        tracker.update([detection(bbox, "sleeping")], timestamp=4)

        track = tracker.persistence_snapshot()[0]
        self.assertEqual(result["detections"][0]["behavior"], "sleeping")
        self.assertTrue(result["detections"][0]["event_started"])
        self.assertEqual(result["detections"][0]["event_index"], 2)
        self.assertEqual(track["event_counts"]["sleeping"], 1)
        self.assertEqual(len(track["events"]), 2)
        self.assertGreater(track["behavior_seconds"]["sleeping"], 0)

    def test_long_sampling_gap_does_not_count_as_visible_time(self):
        tracker = SessionTracker(
            observation_step_seconds=0.5,
            max_observation_gap_seconds=0.9,
            max_missing_seconds=75,
        )
        bbox = [10, 10, 110, 210]
        tracker.update([detection(bbox)], timestamp=0)
        tracker.update([detection(bbox)], timestamp=0.5)
        tracker.update([detection(bbox)], timestamp=60)

        track = tracker.summaries()[0]
        self.assertEqual(track["track_id"], 1)
        self.assertAlmostEqual(track["visible_seconds"], 1.5)

    def test_recent_snapshot_limits_repeated_database_work(self):
        tracker = SessionTracker(
            observation_step_seconds=0.5,
            max_observation_gap_seconds=1.0,
            max_missing_seconds=75,
        )
        bbox = [10, 10, 110, 210]
        tracker.update([detection(bbox)], timestamp=0)
        tracker.update([detection(bbox)], timestamp=61)
        tracker.update([detection(bbox)], timestamp=121)

        recent = tracker.persistence_snapshot(recent_only=True)[0]
        complete = tracker.persistence_snapshot()[0]

        self.assertEqual(len(recent["buckets"]), 2)
        self.assertEqual(len(complete["buckets"]), 3)


class SessionDatabaseTests(unittest.TestCase):
    def test_persists_room_course_and_hourly_track_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = SessionDatabase(os.path.join(temp_dir, "test.db"))
            tracker = SessionTracker(
                observation_step_seconds=1,
                max_observation_gap_seconds=2,
                max_missing_seconds=10,
                transition_seconds={"sleeping": 0},
            )
            bbox = [10, 10, 110, 210]
            tracker.update([detection(bbox)], timestamp=0)
            tracker.update([detection(bbox)], timestamp=1)
            tracker.update([detection(bbox, "sleeping")], timestamp=2)
            tracker.update([detection(bbox, "sleeping")], timestamp=3)

            database.upsert_session(
                "session-1",
                name="Morning Lab",
                room_name="Lab 9226",
                course_name="Artificial Intelligence",
                source_type="video",
                source_label="class.mp4",
                recording_started_at="2026-07-23T09:00",
            )
            database.sync_tracking(
                "session-1",
                tracker.persistence_snapshot(),
            )
            database.add_evidence(
                "session-1",
                track_id=1,
                evidence_key="event:2",
                event_index=2,
                kind="event",
                behavior="sleeping",
                captured_seconds=3,
                filename="id_0001_event_0002_sleeping.jpg",
                width=320,
                height=640,
                file_size=12345,
            )

            report = database.tracking_report(
                "session-1",
                period_seconds=3600,
            )

            self.assertEqual(report["session"]["room_name"], "Lab 9226")
            self.assertEqual(
                report["session"]["course_name"],
                "Artificial Intelligence",
            )
            self.assertEqual(report["tracks"][0]["track_id"], 1)
            self.assertEqual(report["periods"][0]["label"], "09:00 - 10:00")
            self.assertEqual(
                report["tracks"][0]["event_counts"]["sleeping"],
                1,
            )
            self.assertEqual(len(report["evidence"]), 1)
            self.assertEqual(report["evidence"][0]["captured_time"], "09:00:03")
            self.assertEqual(
                report["evidence"][0]["event"]["duration_seconds"],
                0.0,
            )


class EvidenceStoreTests(unittest.TestCase):
    def test_session_directory_is_stable_and_blocks_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(os.path.join(temp_dir, "evidence"))

            first = store.session_directory("คาบ 09:00/AI")
            second = store.session_directory("คาบ 09:00/AI")

            self.assertEqual(first, second)
            self.assertTrue(first.startswith(os.path.abspath(temp_dir)))
            self.assertIsNone(store.resolve_file("session-1", "../secret.jpg"))

    def test_failed_image_write_removes_temporary_file(self):
        class FakeFrame:
            shape = (100, 50, 3)

            def __getitem__(self, _key):
                return self

            def copy(self):
                return self

        def fail_after_partial_write(path, _frame, _options):
            with open(path, "wb") as temporary_file:
                temporary_file.write(b"partial")
            raise OSError("disk full")

        fake_cv2 = SimpleNamespace(
            IMWRITE_JPEG_QUALITY=1,
            imwrite=fail_after_partial_write,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(os.path.join(temp_dir, "evidence"))
            with patch.dict(sys.modules, {"cv2": fake_cv2}):
                with self.assertRaisesRegex(OSError, "disk full"):
                    store.save_crop(
                        session_id="session-1",
                        track_id=1,
                        kind="reference",
                        event_index=None,
                        behavior="attentive",
                        captured_seconds=0,
                        frame=FakeFrame(),
                        bbox=[0, 0, 50, 100],
                    )

            directory = store.session_directory("session-1")
            leftovers = (
                os.listdir(directory)
                if os.path.isdir(directory)
                else []
            )
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
