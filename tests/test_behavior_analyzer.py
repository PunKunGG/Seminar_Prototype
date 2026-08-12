import os
import sys
import unittest
from unittest.mock import patch

import numpy as np


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from behavior_analyzer import (
    _detect_phones_in_suspected_person_crops,
    _person_context,
    _person_contexts,
    analyze_pose,
)


def keypoints():
    points = [[0.0, 0.0, 0.0] for _ in range(17)]
    values = {
        0: (60, 30),
        1: (55, 28),
        2: (65, 28),
        3: (50, 31),
        4: (70, 31),
        5: (40, 60),
        6: (80, 60),
        7: (45, 80),
        8: (75, 80),
        9: (50, 35),
        10: (70, 35),
        11: (45, 110),
        12: (75, 110),
        13: (45, 150),
        14: (75, 150),
        15: (45, 190),
        16: (75, 190),
    }
    for index, (x, y) in values.items():
        points[index] = [float(x), float(y), 0.95]
    for index in (13, 14, 15, 16):
        points[index][2] = 0.0
    return points


class PoseBehaviorTests(unittest.TestCase):
    def test_hands_near_face_are_not_treated_as_raised(self):
        result = analyze_pose(keypoints())

        self.assertEqual(result["behavior"], "attentive")
        self.assertEqual(result["details"]["scores"]["hand_raised"], 0)

    def test_hand_must_be_above_face_with_supported_elbow(self):
        points = keypoints()
        points[7] = [42.0, 55.0, 0.95]
        points[9] = [42.0, 8.0, 0.95]

        result = analyze_pose(points)

        self.assertEqual(result["behavior"], "hand_raised")

    def test_screen_context_turns_upright_head_down_pose_attentive(self):
        points = keypoints()
        points[0] = [60.0, 57.0, 0.95]
        for index in (1, 2, 3, 4):
            points[index][2] = 0.0

        without_screen = analyze_pose(points)
        with_screen = analyze_pose(points, screen_detected=True)

        self.assertEqual(without_screen["behavior"], "looking_down")
        self.assertEqual(with_screen["behavior"], "attentive")

    def test_ambiguous_masked_hands_do_not_claim_screen_attention(self):
        points = keypoints()
        points[0] = [60.0, 57.0, 0.95]
        for index in (1, 2, 3, 4):
            points[index][2] = 0.0
        points[9] = [0.0, 0.0, 0.35]
        points[10] = [0.0, 0.0, 0.35]

        result = analyze_pose(points, screen_detected=True)

        self.assertEqual(result["behavior"], "unknown")

    def test_sleeping_requires_a_collapsed_torso(self):
        upright = keypoints()
        upright[0] = [60.0, 70.0, 0.95]
        collapsed = keypoints()
        collapsed[0] = [60.0, 70.0, 0.95]
        collapsed[11] = [90.0, 68.0, 0.95]
        collapsed[12] = [110.0, 68.0, 0.95]

        self.assertNotEqual(analyze_pose(upright)["behavior"], "sleeping")
        self.assertEqual(analyze_pose(collapsed)["behavior"], "sleeping")

    def test_confirmed_phone_overrides_pose_only_sleeping(self):
        points = keypoints()
        points[0] = [60.0, 70.0, 0.95]
        points[11] = [90.0, 68.0, 0.95]
        points[12] = [110.0, 68.0, 0.95]

        result = analyze_pose(points, phone_confidence=72)

        self.assertEqual(result["behavior"], "phone_use")
        self.assertTrue(result["details"]["phone_detected"])

    def test_converging_hands_are_only_suspected_phone_use(self):
        points = keypoints()
        points[7] = [45.0, 100.0, 0.95]
        points[8] = [75.0, 100.0, 0.95]
        points[9] = [56.0, 120.0, 0.95]
        points[10] = [66.0, 120.0, 0.95]

        result = analyze_pose(points)

        self.assertEqual(result["behavior"], "phone_suspected")
        self.assertTrue(result["details"]["phone_hand_posture"])
        self.assertFalse(result["details"]["phone_detected"])

    def test_spread_hands_are_not_suspected_phone_use(self):
        points = keypoints()
        points[7] = [42.0, 100.0, 0.95]
        points[8] = [78.0, 100.0, 0.95]
        points[9] = [30.0, 120.0, 0.95]
        points[10] = [90.0, 120.0, 0.95]

        result = analyze_pose(points)

        self.assertNotEqual(result["behavior"], "phone_suspected")

    def test_context_objects_are_associated_with_nearby_person(self):
        context = _person_context(
            [100, 100, 300, 400],
            [
                {"class_id": 67, "confidence": 71, "bbox": [280, 210, 320, 250]},
                {"class_id": 62, "confidence": 60, "bbox": [0, 100, 100, 180]},
            ],
        )

        self.assertEqual(context["phone_confidence"], 71)
        self.assertTrue(context["screen_detected"])

    def test_one_phone_is_assigned_to_only_one_nearby_person(self):
        contexts = _person_contexts(
            [[100, 100, 250, 400], [220, 100, 370, 400]],
            [{"class_id": 67, "confidence": 75, "bbox": [230, 210, 250, 250]}],
        )

        self.assertEqual(
            sum(item["phone_confidence"] > 0 for item in contexts),
            1,
        )

    def test_screen_below_upper_body_is_not_treated_as_viewed_screen(self):
        context = _person_context(
            [100, 100, 300, 400],
            [{"class_id": 63, "confidence": 60, "bbox": [120, 230, 280, 290]}],
        )

        self.assertFalse(context["screen_detected"])

    def test_suspected_person_crop_phone_is_mapped_back_to_full_frame(self):
        class FakeTensor:
            def __init__(self, value):
                self.value = np.asarray(value)

            def cpu(self):
                return self

            def numpy(self):
                return self.value

        class FakeBoxes:
            xyxy = FakeTensor([[5, 6, 20, 30]])
            conf = FakeTensor([0.72])

            def __len__(self):
                return 1

        class FakeModel:
            def __call__(self, images, **kwargs):
                self.images = images
                self.kwargs = kwargs
                return [type("Result", (), {"boxes": FakeBoxes()})()]

        points = keypoints()
        points[7] = [145.0, 210.0, 0.95]
        points[8] = [175.0, 210.0, 0.95]
        points[9] = [156.0, 230.0, 0.95]
        points[10] = [166.0, 230.0, 0.95]
        model = FakeModel()

        with patch("behavior_analyzer.get_context_model", return_value=model):
            detections = _detect_phones_in_suspected_person_crops(
                np.zeros((400, 400, 3), dtype=np.uint8),
                [points],
                [[100, 100, 200, 300]],
                [{"phone_confidence": 0, "screen_detected": False}],
            )

        self.assertEqual(len(model.images), 1)
        self.assertEqual(model.kwargs["classes"], [67])
        self.assertEqual(detections[0]["bbox"], [90.0, 76.0, 105.0, 100.0])
        self.assertEqual(detections[0]["source"], "person_crop")


if __name__ == "__main__":
    unittest.main()
