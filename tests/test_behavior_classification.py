import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from behavior_analyzer import analyze_pose

def make_sitting_keypoints():
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
        13: (60, 145),  # left_knee (งอไปข้างหน้า (นั่ง))
        14: (60, 145),  # right_knee
        15: (45, 170),  # left_ankle
        16: (75, 170),  # right_ankle
    }
    for index, (x, y) in values.items():
        kp[index] = [float(x), float(y), 0.95]
    return kp

# TS006 Functional Testing: Behavior Classification
class TS006BehaviorClassification(unittest.TestCase):
    # TC01 attentive
    def test_tc01_attentive(self):
        kp = make_sitting_keypoints()
        result = analyze_pose(kp)

        self.assertEqual(result["behavior"], "attentive",
                         f"TC01 ล้มเหลว: คาดหวัง attentive ได้ {result['behavior']}")
        self.assertGreater(result["confidence"], 0,
                           "TC01 confidence ต้องมากกว่า 0")

    # TC02 looking_down 
    def test_tc02_looking_down(self):
        kp = make_sitting_keypoints()
        # nose อยู่ต่ำกว่าไหล่
        kp[0] = [60.0, 57.0, 0.95]   # nose
        kp[1] = [55.0, 55.0, 0.95]   # left_eye
        kp[2] = [65.0, 55.0, 0.95]   # right_eye
        for i in (1, 2, 3, 4):
            kp[i][2] = 0.0

        result = analyze_pose(kp)

        self.assertEqual(result["behavior"], "looking_down",
                         f"TC02 ล้มเหลว: คาดหวัง looking_down ได้ {result['behavior']}")

    # TC03 sleeping (ศีรษะต่ำ + ลำตัวพับ)
    def test_tc03_sleeping(self):
        kp = make_sitting_keypoints()
        # หัวต่ำมาก + สะโพกเอนไปข้างมาก → torso_collapsed
        kp[0] = [60.0, 70.0, 0.95]   # nose (ต่ำมาก)
        kp[1] = [55.0, 68.0, 0.95]   # left_eye
        kp[2] = [65.0, 68.0, 0.95]   # right_eye
        kp[11] = [90.0, 68.0, 0.95]  # left_hip
        kp[12] = [110.0, 68.0, 0.95] # right_hip

        result = analyze_pose(kp)

        self.assertEqual(result["behavior"], "sleeping",
                         f"TC03 ล้มเหลว: คาดหวัง sleeping ได้ {result['behavior']}")

    # TC04 phone_use (ตรวจพบโทรศัพท์ + ท่าทาง)
    def test_tc04_phone_use(self):
        kp = make_sitting_keypoints()
        # นั่งตรงปกติ แต่ส่ง phone_confidence สูง
        result = analyze_pose(kp, phone_confidence=75)

        self.assertEqual(result["behavior"], "phone_use",
                         f"TC04 ล้มเหลว: คาดหวัง phone_use ได้ {result['behavior']}")
        self.assertTrue(result["details"]["phone_detected"],
                        "TC04 phone_detected ต้องเป็น True")

    # TC05 phone_suspected
    def test_tc05_phone_suspected(self):
        kp = make_sitting_keypoints()
        # มือบรรจบต่ำกว่าไหล่ (ไม่มี object detection)
        kp[7] = [45.0, 100.0, 0.95]   # left_elbow (ต่ำลง)
        kp[8] = [75.0, 100.0, 0.95]   # right_elbow
        kp[9] = [56.0, 120.0, 0.95]   # left_wrist (บรรจบต่ำกว่าไหล่)
        kp[10] = [66.0, 120.0, 0.95]  # right_wrist

        result = analyze_pose(kp)

        self.assertEqual(result["behavior"], "phone_suspected",
                         f"TC05 ล้มเหลว: คาดหวัง phone_suspected ได้ {result['behavior']}")
        self.assertTrue(result["details"]["phone_hand_posture"],
                        "TC05 phone_hand_posture ต้องเป็น True")
        self.assertFalse(result["details"]["phone_detected"],
                         "TC05 phone_detected ต้องเป็น False")

    # TC06 hand_raised
    def test_tc06_hand_raised(self):
        kp = make_sitting_keypoints()
        kp[7] = [42.0, 55.0, 0.95]   # left_elbow (อยู่ในระดับไหล่)
        kp[9] = [42.0, 8.0, 0.95]    # left_wrist (สูงกว่าใบหน้ามาก)

        result = analyze_pose(kp)

        self.assertEqual(result["behavior"], "hand_raised",
                         f"TC06 ล้มเหลว: คาดหวัง hand_raised ได้ {result['behavior']}")

    # TC07 standing
    def test_tc07_standing(self):
        kp = [[0.0, 0.0, 0.0] for _ in range(17)]
        # (knee_angle > 150), body_ratio > 3.05
        kp[0] = [60.0, 30.0, 0.95]    # nose
        kp[1] = [55.0, 28.0, 0.95]    # left_eye
        kp[2] = [65.0, 28.0, 0.95]    # right_eye
        kp[5] = [40.0, 60.0, 0.95]    # left_shoulder
        kp[6] = [80.0, 60.0, 0.95]    # right_shoulder
        kp[7] = [45.0, 80.0, 0.95]    # left_elbow
        kp[8] = [75.0, 80.0, 0.95]    # right_elbow
        kp[9] = [50.0, 35.0, 0.95]    # left_wrist
        kp[10] = [70.0, 35.0, 0.95]   # right_wrist
        kp[11] = [45.0, 110.0, 0.95]  # left_hip
        kp[12] = [75.0, 110.0, 0.95]  # right_hip
        kp[13] = [45.0, 200.0, 0.95]  # left_knee (ขายาวตรง)
        kp[14] = [75.0, 200.0, 0.95]  # right_knee
        kp[15] = [45.0, 290.0, 0.95]  # left_ankle
        kp[16] = [75.0, 290.0, 0.95]  # right_ankle

        result = analyze_pose(kp)

        self.assertEqual(result["behavior"], "standing",
                         f"TC07 ล้มเหลว: คาดหวัง standing ได้ {result['behavior']}")

    # TC08 unknown (keypoints น้อย) 
    def test_tc08_unknown_insufficient_keypoints(self):
        # ส่ง keypoints น้อยกว่า 13 จุด 
        kp = [[0.0, 0.0, 0.0] for _ in range(5)]
        kp[0] = [60.0, 30.0, 0.95]   # nose
        kp[1] = [55.0, 28.0, 0.95]   # left_eye
        kp[2] = [65.0, 28.0, 0.95]   # right_eye

        result = analyze_pose(kp)

        self.assertEqual(result["behavior"], "unknown",
                         f"TC08 ล้มเหลว: คาดหวัง unknown ได้ {result['behavior']}")
        self.assertEqual(result["confidence"], 0,
                         "TC08 confidence ต้องเป็น 0")


if __name__ == "__main__":
    unittest.main()
