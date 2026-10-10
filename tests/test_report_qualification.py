import copy
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from person_tracking import BEHAVIOR_KEYS, SessionTracker
from pose_geometry import report_geometry
from report_qualification import REPORT_POLICY, qualify_tracking
from session_database import SessionDatabase


def event(duration, behavior="attentive", start=0, track_id=1, segments=None):
    return {"track_id": track_id, "event_index": 1, "behavior": behavior,
            "start_seconds": start, "end_seconds": start + duration,
            "duration_seconds": round(duration, 1), "observed_duration_seconds": duration,
            "observed_segments": segments if segments is not None else [[start, start + duration, duration]],
            "avg_confidence": 90}


def position(x=0.2, y=0.3, behavior="attentive"):
    return {"bbox": [x * 1000 - 50, y * 1000 - 20, x * 1000 + 50, y * 1000 + 180],
            "position_anchor": [x, y], "position_scale": 0.25,
            "behavior": behavior, "confidence": 90}


class QualificationTests(unittest.TestCase):
    def test_threshold_uses_unrounded_duration(self):
        for seconds, expected in [(29.9, 0), (29.99, 0), (30, 1), (30.1, 1)]:
            with self.subTest(seconds=seconds):
                raw = {"tracks": [{"track_id": 1, "visible_seconds": seconds}], "events": [event(seconds)]}
                original = copy.deepcopy(raw)
                result = qualify_tracking(raw, REPORT_POLICY)
                self.assertEqual(len(result["events"]), expected)
                self.assertEqual(result["tracks"][0]["attention_rate"], 100 if expected else None)
                self.assertEqual(raw, original)

    def test_every_behavior_uses_same_threshold_and_formula_is_time_weighted(self):
        raw = {"tracks": [{"track_id": 1, "visible_seconds": 99.9}],
               "events": [event(60), event(30, "sleeping", start=60), event(9.9, "hand_raised", start=90)]}
        result = qualify_tracking(raw, REPORT_POLICY)
        self.assertEqual(result["summary"]["attention_rate"], 66.7)
        self.assertEqual(result["summary"]["event_counts"]["hand_raised"], 0)
        self.assertAlmostEqual(result["tracks"][0]["excluded_seconds"], 9.9)

    def test_all_behaviors_have_the_same_inclusive_boundary(self):
        for behavior in BEHAVIOR_KEYS:
            for seconds in (29.9, 30, 30.1):
                with self.subTest(behavior=behavior, seconds=seconds):
                    result = qualify_tracking({"tracks": [], "events": [event(seconds, behavior)]}, REPORT_POLICY)
                    self.assertEqual(result["summary"]["event_counts"][behavior], int(seconds >= 30))

    def test_sampling_gaps_are_not_allocated_to_periods(self):
        raw = {"tracks": [{"track_id": 1, "visible_seconds": 30}],
               "events": [event(30, segments=[[0, 15, 15], [600, 615, 15]])]}
        result = qualify_tracking(raw, REPORT_POLICY)
        self.assertEqual([item["start_seconds"] for item in result["periods"]], [0, 600])
        self.assertEqual([item["qualified_seconds"] for item in result["periods"]], [15, 15])
        self.assertEqual(sum(item["event_counts"]["attentive"] for item in result["periods"]), 1)

    def test_qualify_before_splitting_a_five_minute_boundary(self):
        raw = {"tracks": [{"track_id": 1, "visible_seconds": 30}], "events": [event(30, start=285)]}
        result = qualify_tracking(raw, REPORT_POLICY)
        self.assertEqual([item["qualified_seconds"] for item in result["periods"]], [15, 15])
        self.assertEqual(sum(item["event_counts"]["attentive"] for item in result["periods"]), 1)

    def test_short_separate_runs_are_not_combined(self):
        raw = {"tracks": [{"track_id": 1, "visible_seconds": 40}], "events": [event(20), event(20, start=60)]}
        result = qualify_tracking(raw, REPORT_POLICY)
        self.assertEqual(result["summary"]["qualified_seconds"], 0)
        self.assertIsNone(result["tracks"][0]["attention_rate"])


class PersistentPositionTests(unittest.TestCase):
    def make_tracker(self):
        return SessionTracker(persistent_positions=True, record_observed_segments=True,
                              observation_step_seconds=0.5, max_observation_gap_seconds=1,
                              max_missing_seconds=4)

    def establish(self, tracker, detections):
        result = None
        for index in range(7):
            result = tracker.update(detections, timestamp=index * 0.5)
        return result

    def test_new_position_waits_three_observed_seconds(self):
        tracker = self.make_tracker()
        self.assertIsNone(tracker.update([position()], timestamp=0)["detections"][0]["track_id"])
        result = self.establish(tracker, [position()])
        self.assertEqual(result["detections"][0]["track_id"], 1)

    def test_observed_absence_restarts_pending_position_confirmation(self):
        tracker = self.make_tracker()
        for timestamp in (0, 0.5, 1, 1.5, 2):
            tracker.update([position()], timestamp=timestamp)
        tracker.update([], timestamp=2.5)
        self.assertIsNone(tracker.update([position()], timestamp=3)["detections"][0]["track_id"])
        self.assertIsNone(tracker.update([position()], timestamp=3.5)["detections"][0]["track_id"])
        for timestamp in (4, 4.5, 5, 5.5, 6):
            result = tracker.update([position()], timestamp=timestamp)
        self.assertEqual(result["detections"][0]["track_id"], 1)

    def test_new_round_has_a_fresh_position_registry(self):
        first = self.make_tracker()
        self.establish(first, [position()])
        second = self.make_tracker()
        self.assertEqual(second.summaries(), [])
        self.assertIsNone(second.update([position()], timestamp=0)["detections"][0]["track_id"])
        self.assertEqual(self.establish(second, [position()])["detections"][0]["track_id"], 1)

    def test_position_survives_missing_time_and_standing_return(self):
        tracker = self.make_tracker()
        self.establish(tracker, [position()])
        tracker.update([position()], timestamp=3.5)
        tracker.update([], timestamp=4)
        result = tracker.update([position(behavior="standing")], timestamp=25000)
        self.assertEqual(result["detections"][0]["track_id"], 1)
        self.assertTrue(result["detections"][0]["reacquired"])
        self.assertLess(tracker.summaries()[0]["visible_seconds"], 2)
        self.assertEqual(len(tracker.summaries()), 1)

    def test_unobserved_gap_does_not_split_a_run_at_legacy_missing_timeout(self):
        tracker = self.make_tracker()
        self.establish(tracker, [position()])
        tracker.update([position()], timestamp=3.5)
        result = tracker.update([position()], timestamp=600)
        self.assertEqual(result["detections"][0]["track_id"], 1)
        self.assertFalse(result["detections"][0]["event_started"])
        tracker.update([position()], timestamp=600.5)
        events = tracker.persistence_snapshot()[0]["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["observed_segments"], [[3, 3.5, 0.5], [600, 600.5, 0.5]])

    def test_adjacent_positions_and_detection_order_stay_separate(self):
        tracker = self.make_tracker()
        result = self.establish(tracker, [position(0.2), position(0.27)])
        self.assertEqual([item["track_id"] for item in result["detections"]], [1, 2])
        reversed_result = tracker.update([position(0.27), position(0.2)], timestamp=3.5)
        self.assertEqual([item["track_id"] for item in reversed_result["detections"]], [2, 1])

    def test_adjacent_people_keep_ids_when_both_prefer_the_same_position(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                tracker = self.make_tracker()
                self.establish(tracker, [position(0.2), position(0.27)])
                detections = [position(0.205), position(0.22)]
                expected = [1, 2]
                if reverse:
                    detections.reverse()
                    expected.reverse()
                for step in range(8):
                    result = tracker.update(detections, timestamp=3.5 + step * 0.5)
                    self.assertEqual([item["track_id"] for item in result["detections"]], expected)
                self.assertEqual(len(tracker.summaries()), 2)
                self.assertEqual([item["visible_seconds"] for item in tracker.summaries()], [4, 4])

    def test_assignment_can_move_a_match_to_its_valid_alternative(self):
        tracker = self.make_tracker()
        self.establish(tracker, [position(0.2), position(0.3)])
        # The first detection can use either seat; the second can only use ID 1.
        for step in range(8):
            result = tracker.update([position(0.202), position(0.18)], timestamp=3.5 + step * 0.5)
            self.assertEqual([item["track_id"] for item in result["detections"]], [2, 1])
        self.assertEqual(len(tracker.summaries()), 2)

    def test_conflicting_detection_waits_instead_of_creating_a_duplicate_position(self):
        tracker = self.make_tracker()
        self.establish(tracker, [position()])
        for step in range(8):
            result = tracker.update([position(), position(0.23)], timestamp=3.5 + step * 0.5)
            self.assertEqual([item["track_id"] for item in result["detections"]], [1, None])
        self.assertEqual(len(tracker.summaries()), 1)

    def test_active_id_survives_shoulder_motion_without_moving_seat_anchor(self):
        for behavior in ("standing", "looking_down"):
            with self.subTest(behavior=behavior):
                tracker = self.make_tracker()
                self.establish(tracker, [position()])
                moved = position(0.2, 0.45, behavior=behavior)
                moved["bbox"] = [150, 240, 250, 440]
                for step in range(8):
                    result = tracker.update([moved], timestamp=3.5 + step * 0.5)
                    self.assertEqual(result["detections"][0]["track_id"], 1)
                    self.assertFalse(result["detections"][0]["reacquired"])
                self.assertEqual(tracker._tracks[1].position_anchor, (0.2, 0.3))
                self.assertEqual(len(tracker.summaries()), 1)
                self.assertEqual(tracker.summaries()[0]["visible_seconds"], 4)
                returned = tracker.update([position()], timestamp=7.5)
                self.assertEqual(returned["detections"][0]["track_id"], 1)

    def test_posture_overlap_does_not_reacquire_an_inactive_or_stale_id(self):
        moved = position(0.2, 0.45, behavior="standing")
        moved["bbox"] = [150, 240, 250, 440]
        for explicitly_missing in (False, True):
            with self.subTest(explicitly_missing=explicitly_missing):
                tracker = self.make_tracker()
                self.establish(tracker, [position()])
                if explicitly_missing:
                    tracker.update([], timestamp=8)
                result = tracker.update([moved], timestamp=9)
                self.assertIsNone(result["detections"][0]["track_id"])
                self.assertEqual(len(tracker.summaries()), 1)

    def test_ambiguous_position_does_not_create_or_merge_ids(self):
        tracker = self.make_tracker()
        self.establish(tracker, [position(0.2), position(0.27)])
        tracker.update([], timestamp=4)
        for timestamp in (10, 11, 12, 13, 14):
            result = tracker.update([position(0.235)], timestamp=timestamp)
            self.assertIsNone(result["detections"][0]["track_id"])
        self.assertEqual(len(tracker.summaries()), 2)

    def test_visible_shoulders_take_priority_over_occluded_overlap(self):
        tracker = self.make_tracker()
        self.establish(tracker, [position()])
        occluded = position()
        del occluded["position_anchor"]
        result = tracker.update([occluded, position(0.201)], timestamp=3.5)
        self.assertEqual([item["track_id"] for item in result["detections"]], [None, 1])
        self.assertEqual(len(tracker.summaries()), 1)

    def test_disabled_position_matching_keeps_legacy_immediate_ids(self):
        tracker = SessionTracker(persistent_positions=True, position_matching=False)
        self.assertEqual(tracker.update([position()], timestamp=0)["detections"][0]["track_id"], 1)

    def test_sampling_retains_same_run_but_explicit_absence_ends_it(self):
        tracker = SessionTracker(record_observed_segments=True, observation_step_seconds=0.5,
                                 max_observation_gap_seconds=0.9, max_missing_seconds=75)
        person = {"bbox": [0, 0, 100, 200], "behavior": "attentive"}
        for timestamp in [0, 0.5, 1, 60, 60.5, 61]:
            tracker.update([person], timestamp=timestamp)
        event_data = tracker.persistence_snapshot()[0]["events"]
        self.assertEqual(len(event_data), 1)
        self.assertEqual(len(event_data[0]["observed_segments"]), 2)
        self.assertAlmostEqual(event_data[0]["duration_seconds"], 2)
        self.assertEqual(event_data[0]["observed_segments"], [[0, 1, 1], [60, 61, 1]])
        tracker.update([], timestamp=61.5)
        tracker.update([person], timestamp=62)
        self.assertEqual(len(tracker.persistence_snapshot()[0]["events"]), 2)

    def test_three_sampled_windows_qualify_without_counting_gaps(self):
        tracker = SessionTracker(record_observed_segments=True, observation_step_seconds=0.5,
                                 max_observation_gap_seconds=0.9, max_missing_seconds=75)
        person = {"bbox": [0, 0, 100, 200], "behavior": "attentive"}
        for start in (0, 60, 120):
            for index in range(21):
                tracker.update([person], timestamp=start + index * 0.5)
        snapshot = tracker.persistence_snapshot()[0]
        self.assertEqual(snapshot["visible_seconds"], 30)
        observed = snapshot["events"][0]
        self.assertEqual(observed["observed_segments"], [[0, 10, 10], [60, 70, 10], [120, 130, 10]])
        observed["track_id"] = 1
        result = qualify_tracking({"tracks": [snapshot], "events": [observed]}, REPORT_POLICY)
        self.assertEqual(result["summary"]["qualified_seconds"], 30)
        self.assertEqual(result["summary"]["event_counts"]["attentive"], 1)


class ReportStorageTests(unittest.TestCase):
    def test_policy_segments_and_legacy_migration_are_lossless(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "sessions.db")
            database = SessionDatabase(path)
            database.upsert_session("old", name="Legacy", room_name="Lab", course_name="AI",
                                    source_type="video", source_label="old.mp4")
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("ALTER TABLE class_sessions DROP COLUMN report_policy_json")
                connection.execute("ALTER TABLE behavior_events DROP COLUMN observed_segments_json")
            database = SessionDatabase(path)
            self.assertIsNone(database.get_session("old")["report_policy"])
            database.upsert_session("new", name="New", room_name="Lab", course_name="AI",
                                    source_type="video", source_label="new.mp4", report_policy=REPORT_POLICY)
            tracker = SessionTracker(record_observed_segments=True, observation_step_seconds=1,
                                     max_observation_gap_seconds=2)
            for timestamp in range(31):
                tracker.update([{"bbox": [0, 0, 100, 200], "behavior": "attentive"}], timestamp=timestamp)
            database.sync_tracking("new", tracker.persistence_snapshot())
            report = database.tracking_report("new")
            self.assertEqual(report["session"]["report_policy"], REPORT_POLICY)
            self.assertEqual(report["events"][0]["observed_segments"], [[0, 30, 30]])
            self.assertEqual(qualify_tracking(report, REPORT_POLICY)["summary"]["qualified_seconds"], 30)
            self.assertNotIn("observed_segments_json", database.archive_rows("new")["behavior_events"][0])
            database.add_evidence("new", track_id=1, evidence_key="portrait", event_index=None,
                                  kind="reference", behavior="attentive", captured_seconds=3,
                                  filename="portrait.jpg", width=320, height=320, file_size=4)
            representative = database.tracking_report("new")["representative_evidence"][0]
            self.assertEqual(representative["filename"], "portrait.jpg")
            self.assertEqual(representative["thumbnail_filename"], "portrait.jpg")


class PoseGeometryTests(unittest.TestCase):
    def points(self):
        points = [[0, 0, 0] for _ in range(17)]
        for index, point in {0: [100, 70, 0.9], 1: [90, 60, 0.9], 2: [110, 60, 0.9],
                             5: [70, 120, 0.9], 6: [130, 120, 0.9]}.items():
            points[index] = point
        return points

    def test_geometry_scales_with_frame_without_identity_features(self):
        points = self.points()
        small = report_geometry(points, [50, 20, 150, 250], (300, 200, 3), 0.4)
        large = report_geometry([[x * 2, y * 2, conf] for x, y, conf in points],
                                [100, 40, 300, 500], (600, 400, 3), 0.4)
        self.assertEqual(small["position_anchor"], large["position_anchor"])
        self.assertEqual(small["position_scale"], large["position_scale"])
        self.assertAlmostEqual(small["portrait_bbox"][2] - small["portrait_bbox"][0],
                               small["portrait_bbox"][3] - small["portrait_bbox"][1])

    def test_occluded_head_uses_original_picture_without_guessing(self):
        points = self.points()
        for index in range(5):
            points[index][2] = 0
        result = report_geometry(points, [50, 20, 150, 250], (300, 200, 3), 0.4)
        self.assertIn("position_anchor", result)
        self.assertNotIn("portrait_bbox", result)

    def test_side_profile_uses_visible_nose_and_ear_with_shoulders(self):
        points = self.points()
        points[1][2] = points[2][2] = 0
        points[3] = [104, 68, 0.9]
        result = report_geometry(points, [50, 20, 150, 250], (300, 200, 3), 0.4)
        left, top, right, bottom = result["portrait_bbox"]
        self.assertAlmostEqual((left + right) / 2, 102)
        for index in (0, 3):
            self.assertTrue(left <= points[index][0] <= right)
            self.assertTrue(top <= points[index][1] <= bottom)

    def test_square_portrait_at_frame_edge_and_original_are_both_preserved(self):
        import cv2
        import numpy as np
        from evidence_store import EvidenceStore

        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceStore(directory)
            frame = np.full((100, 100, 3), 128, dtype=np.uint8)
            original = store.save_crop(session_id="round", track_id=1, kind="reference",
                                       event_index=None, behavior="attentive", captured_seconds=0,
                                       frame=frame, bbox=[0, 0, 50, 100])
            portrait = store.save_crop(session_id="round", track_id=1, kind="portrait",
                                       event_index=None, behavior="attentive", captured_seconds=0,
                                       frame=frame, bbox=[-20, -20, 40, 40], square_size=320)
            self.assertEqual((portrait["width"], portrait["height"]), (320, 320))
            self.assertNotEqual(original["filename"], portrait["filename"])
            image = cv2.imread(store.resolve_file("round", portrait["filename"]))
            self.assertGreater(int(image[10, 10, 0]), 220)
            self.assertLess(int(image[250, 250, 0]), 160)


if __name__ == "__main__":
    unittest.main()
