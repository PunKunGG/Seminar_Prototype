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

# TS009 Functional Testing: Hand Raised Detection
class TS009HandRaisedDetection(unittest.TestCase):
    # TC01 hand_raised 
    def test_tc01_hand_raised_wrist_above_face(self):
        """TC01: ข้อมือสูงกว่าใบหน้า + ลักษณะยกมือ → hand_raised"""
        kp = make_sitting_keypoints()
        # แขนซ้าย (wrist สูงเหนือศีรษะ, elbow ระดับไหล่/สูงกว่า)
        kp[7] = [42.0, 40.0, 0.95]    # left_elbow (สูงกว่าระดับไหล่)
        kp[9] = [42.0, 8.0, 0.95]     # left_wrist (สูงมากเหนือใบหน้า)

        result = analyze_pose(kp)

        self.assertEqual(result["behavior"], "hand_raised",
                         f"TC01 ล้มเหลว: คาดหวัง hand_raised ได้ {result['behavior']}")

    # TC02 มือใกล้ใบหน้าแต่ไม่ยก (ไม่ใช่ hand_raised)
    def test_tc02_hand_near_face_not_raised(self):
        """TC02: มืออยู่ใกล้ใบหน้าแต่ไม่สูงกว่าที่กำหนด → ไม่ใช่ hand_raised"""
        kp = make_sitting_keypoints()
        kp[7] = [42.0, 55.0, 0.95]    # left_elbow
        kp[9] = [42.0, 28.0, 0.95]    # left_wrist (ระดับใบหน้า แต่ไม่สูงขึ้น)

        result = analyze_pose(kp)

        self.assertNotEqual(result["behavior"], "hand_raised",
                            f"TC02 ล้มเหลว: มือใกล้หน้าไม่ควรเป็น hand_raised ได้ {result['behavior']}")

    # TC03 แขนปกติ
    def test_tc03_normal_arm_position(self):
        """TC03: แขนอยู่ในตำแหน่งปกติ → จำแนกเป็นพฤติกรรมอื่นที่เหมาะสม"""
        kp = make_sitting_keypoints()

        result = analyze_pose(kp)

        self.assertNotEqual(result["behavior"], "hand_raised",
                            f"TC03 ล้มเหลว: แขนปกติไม่ควรเป็น hand_raised ได้ {result['behavior']}")
        self.assertIn(result["behavior"], ["attentive", "looking_down"],
                      f"TC03 ล้มเหลว: ควรเป็น attentive หรือ looking_down ได้ {result['behavior']}")

    # TC04 elbow ต่ำไป
    def test_tc04_elbow_too_low(self):
        """TC04: ข้อศอกต่ำเกินไป (elbow_supported ล้มเหลว) → ไม่ใช่ hand_raised"""
        kp = make_sitting_keypoints()

        kp[7] = [42.0, 100.0, 0.95]    # left_elbow (ต่ำเกินไป)
        kp[9] = [42.0, 8.0, 0.95]      # left_wrist (สูง)

        result = analyze_pose(kp)

        self.assertNotEqual(result["behavior"], "hand_raised",
                            f"TC04 ล้มเหลว: elbow ต่ำไม่ควรเป็น hand_raised ได้ {result['behavior']}")


if __name__ == "__main__":
    unittest.main()
