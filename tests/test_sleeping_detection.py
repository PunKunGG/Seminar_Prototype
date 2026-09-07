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

# TS007 Functional Testing: Sleeping Detection
class TS007SleepingDetection(unittest.TestCase):
    # TC01 sleeping (ศีรษะต่ำ + ลำตัวพับ) 
    def test_tc01_sleeping_head_low_torso_collapsed(self):
        """TC01: กำหนด Keypoints ที่ศีรษะต่ำและลำตัวพับ → sleeping"""
        kp = make_sitting_keypoints()
        # head_ratio <= 0.10
        kp[0] = [60.0, 70.0, 0.95]   # nose (ต่ำมาก)
        kp[1] = [55.0, 68.0, 0.95]   # left_eye
        kp[2] = [65.0, 68.0, 0.95]   # right_eye
        # horizontal_torso > 0.85
        kp[11] = [90.0, 68.0, 0.95]  # left_hip
        kp[12] = [110.0, 68.0, 0.95] # right_hip

        result = analyze_pose(kp)

        self.assertEqual(result["behavior"], "sleeping",
                         f"TC01 ล้มเหลว: คาดหวัง sleeping ได้ {result['behavior']}")
        self.assertGreater(result["confidence"], 0,
                           "TC01 confidence ต้องมากกว่า 0")

    # TC02 looking_down (ศีรษะต่ำ + ลำตัวตั้งตรง) 
    def test_tc02_looking_down_head_low_torso_upright(self):
        """TC02: กำหนด Keypoints ที่ศีรษะต่ำแต่ลำตัวตั้งตรง → looking_down"""
        kp = make_sitting_keypoints()
        # head_ratio อยู่ในช่วง looking_down
        kp[0] = [60.0, 57.0, 0.95]   # nose (ต่ำ)
        kp[1] = [55.0, 55.0, 0.95]   # left_eye
        kp[2] = [65.0, 55.0, 0.95]   # right_eye
        # ปิดหน้าตาออก เพื่อไม่ให้ score attentive เพิ่ม
        for i in (1, 2, 3, 4):
            kp[i][2] = 0.0
        # ลำตัวตรง
        kp[11] = [45.0, 110.0, 0.95]  # left_hip
        kp[12] = [75.0, 110.0, 0.95]  # right_hip

        result = analyze_pose(kp)

        self.assertNotEqual(result["behavior"], "sleeping",
                            f"TC02 ล้มเหลว: ไม่ควรเป็น sleeping ได้ {result['behavior']}")
        self.assertEqual(result["behavior"], "looking_down",
                         f"TC02 ล้มเหลว: คาดหวัง looking_down ได้ {result['behavior']}")

    # TC03: ท่าปกติ
    def test_tc03_not_sleeping_normal_posture(self):
        """TC03: กำหนด Keypoints ท่าปกติ → ไม่ใช่ sleeping"""
        kp = make_sitting_keypoints()

        result = analyze_pose(kp)

        self.assertNotEqual(result["behavior"], "sleeping",
                            f"TC03 ล้มเหลว: ท่าปกติไม่ควรเป็น sleeping ได้ {result['behavior']}")

    # TC04 หัวต่ำมากแต่ลำตัวตรง (ไม่ใช่ sleeping)
    def test_tc04_not_sleeping_head_low_straight_torso(self):
        """TC04: หัวต่ำมากแต่ลำตัวตั้งตรง → ไม่ใช่ sleeping"""
        kp = make_sitting_keypoints()
        # หัวต่ำมาก
        kp[0] = [60.0, 70.0, 0.95]   # nose (ต่ำมาก)
        kp[1] = [55.0, 68.0, 0.95]   # left_eye
        kp[2] = [65.0, 68.0, 0.95]   # right_eye
        # ลำตัวตั้งตรง
        kp[11] = [45.0, 110.0, 0.95]  # left_hip
        kp[12] = [75.0, 110.0, 0.95]  # right_hip

        result = analyze_pose(kp)

        self.assertNotEqual(result["behavior"], "sleeping",
                            f"TC04 ล้มเหลว: หัวต่ำแต่ลำตัวตรง ไม่ควรเป็น sleeping ได้ {result['behavior']}")


if __name__ == "__main__":
    unittest.main()
