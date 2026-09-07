import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from behavior_analyzer import analyze_pose

def make_sitting_keypoints():
    # keypoints ท่านั่งปกติ
    kp = [[0.0, 0.0, 0.0] for _ in range(17)]
    values = {
        0: (60, 30),    # nose (สูง)
        1: (55, 28),    # left_eye
        2: (65, 28),    # right_eye
        3: (50, 31),    # left_ear
        4: (70, 31),    # right_ear
        5: (40, 60),    # left_shoulder
        6: (80, 60),    # right_shoulder
        7: (45, 80),    # left_elbow
        8: (75, 80),    # right_elbow
        9: (50, 35),    # left_wrist
        10: (70, 35),   # right_wrist
        11: (45, 110),  # left_hip
        12: (75, 110),  # right_hip
        13: (60, 145),  # left_knee (งอ - ท่านั่ง)
        14: (60, 145),  # right_knee
        15: (45, 170),  # left_ankle
        16: (75, 170),  # right_ankle
    }
    for index, (x, y) in values.items():
        kp[index] = [float(x), float(y), 0.95]
    return kp

# TS008 Functional Testing: Phone Detection
class TS008PhoneDetection(unittest.TestCase):
    # TC01 phone_use (object detection + ท่าทาง)
    def test_tc01_phone_use_with_object_detection(self):
        """TC01: ตรวจพบโทรศัพท์ + ท่าทาง → phone_use"""
        kp = make_sitting_keypoints()
        # phone_confidence > 0 (object detector พบโทรศัพท์)
        result = analyze_pose(kp, phone_confidence=80)

        self.assertEqual(result["behavior"], "phone_use",
                         f"TC01 ล้มเหลว: คาดหวัง phone_use ได้ {result['behavior']}")
        self.assertTrue(result["details"]["phone_detected"],
                        "TC01 phone_detected ต้องเป็น True")
        self.assertGreater(result["confidence"], 0,
                           "TC01 confidence ต้องมากกว่า 0")

    # TC02 phone_suspected (ท่าทางคล้าย แต่ไม่มี object) 
    def test_tc02_phone_suspected_pose_only(self):
        """TC02: ท่าทางสงสัยใช้โทรศัพท์ (ไม่มี object detection) → phone_suspected"""
        kp = make_sitting_keypoints()
        kp[7] = [45.0, 100.0, 0.95]   # left_elbow (ต่ำลง)
        kp[8] = [75.0, 100.0, 0.95]   # right_elbow
        kp[9] = [56.0, 120.0, 0.95]   # left_wrist (บรรจบต่ำกว่าไหล่)
        kp[10] = [66.0, 120.0, 0.95]  # right_wrist

        result = analyze_pose(kp)

        self.assertEqual(result["behavior"], "phone_suspected",
                         f"TC02 ล้มเหลว: คาดหวัง phone_suspected ได้ {result['behavior']}")
        self.assertTrue(result["details"]["phone_hand_posture"],
                        "TC02 phone_hand_posture ต้องเป็น True")
        self.assertFalse(result["details"]["phone_detected"],
                         "TC02 phone_detected ต้องเป็น False")

    # TC03 ไม่ใช่ phone_use/suspected (ไม่มีโทรศัพท์ ไม่มีท่าทาง)
    def test_tc03_not_phone_normal_posture(self):
        """TC03: ท่าปกติ ไม่มีโทรศัพท์ → ไม่ใช่ phone_use หรือ phone_suspected"""
        kp = make_sitting_keypoints()
        result = analyze_pose(kp)

        self.assertNotIn(result["behavior"], ["phone_use", "phone_suspected"],
                         f"TC03 ล้มเหลว: ท่าปกติไม่ควรเป็น phone_use หรือ phone_suspected ได้ {result['behavior']}")

    # TC04 มือกางออก
    def test_tc04_spread_hands_not_suspected(self):
        """TC04: ท่ามือกางออก → ไม่ใช่ phone_suspected"""
        kp = make_sitting_keypoints()
        # ท่ามือกางออก
        kp[7] = [42.0, 100.0, 0.95]   # left_elbow
        kp[8] = [78.0, 100.0, 0.95]   # right_elbow
        kp[9] = [30.0, 120.0, 0.95]   # left_wrist (กางออกไปข้าง)
        kp[10] = [90.0, 120.0, 0.95]  # right_wrist (กางออกไปข้าง)

        result = analyze_pose(kp)

        self.assertNotEqual(result["behavior"], "phone_suspected",
                            f"TC04 ล้มเหลว: ท่ามือกางไม่ควรเป็น phone_suspected ได้ {result['behavior']}")

    # TC05 phone_confidence ต่ำแต่มี (เป็น phone_use) 
    def test_tc05_low_confidence_still_phone_use(self):
        """TC05: มี object detection confidence ต่ำ → ยังเป็น phone_use"""
        kp = make_sitting_keypoints()

        result = analyze_pose(kp, phone_confidence=25)

        self.assertEqual(result["behavior"], "phone_use",
                         f"TC05 ล้มเหลว: คาดหวัง phone_use ได้ {result['behavior']}")


if __name__ == "__main__":
    unittest.main()
