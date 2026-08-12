"""
🧠 Behavior Analyzer v2 - วิเคราะห์พฤติกรรมนักศึกษาจาก Pose Estimation
แก้ไขให้แม่นขึ้นสำหรับห้องแล็บ:
  - Multi-signal scoring แทน single threshold
  - แยกท่าก้มออกจากการตรวจพบโทรศัพท์จริง
  - ใช้วัตถุโทรศัพท์และจอเป็นบริบทประกอบ pose
  - CLAHE preprocessing สำหรับแสงสว่างไม่สม่ำเสมอ
  - ใช้ yolov8s-pose (small) แทน nano ถ้ามี
  - Calibrate threshold สำหรับกล้องมุมสูงห้องแล็บ
"""
from ultralytics import YOLO
import numpy as np
import cv2
import os
import threading

# ──────────────────────────────────────────────
# โมเดล (lazy-loading)
# ──────────────────────────────────────────────
pose_model = None
context_model = None
pose_model_lock = threading.Lock()
_MODEL_NAME = "yolov8s-pose.pt"   # small > nano (ดาวน์โหลดอัตโนมัติถ้ายังไม่มี)
_CONTEXT_MODEL_NAME = "yolov8n.pt"
_SCREEN_CLASS_IDS = frozenset({62, 63})
_PHONE_CLASS_ID = 67

def get_pose_model():
    global pose_model
    if pose_model is None:
        base = os.path.dirname(os.path.abspath(__file__))
        root = os.path.abspath(os.path.join(base, os.pardir))
        small_path = next(
            (p for p in (os.path.join(base, _MODEL_NAME), os.path.join(root, _MODEL_NAME)) if os.path.exists(p)),
            None,
        )
        nano_path = next(
            (p for p in (os.path.join(base, "yolov8n-pose.pt"), os.path.join(root, "yolov8n-pose.pt")) if os.path.exists(p)),
            None,
        )
        if small_path:
            pose_model = YOLO(small_path)
        elif nano_path:
            print("⚠️  yolov8s-pose.pt ไม่พบ — ใช้ yolov8n-pose.pt แทน")
            pose_model = YOLO(nano_path)
        else:
            pose_model = YOLO(_MODEL_NAME)   # ให้ ultralytics ดาวน์โหลดเอง
    return pose_model


def get_context_model():
    global context_model
    if context_model is not None:
        return context_model

    base = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(base, os.pardir))
    model_path = next(
        (
            path
            for path in (
                os.path.join(base, _CONTEXT_MODEL_NAME),
                os.path.join(root, _CONTEXT_MODEL_NAME),
            )
            if os.path.exists(path)
        ),
        None,
    )
    if model_path is None:
        return None
    context_model = YOLO(model_path)
    return context_model


def detect_context_objects(
    frame: np.ndarray,
    *,
    confidence=0.15,
    image_size=960,
) -> list:
    """ตรวจเฉพาะจอคอม/แล็ปท็อป/โทรศัพท์จากโมเดล COCO ในเครื่อง"""
    if frame is None:
        return []

    with pose_model_lock:
        model = get_context_model()
        if model is None:
            return []
        results = model(
            frame,
            verbose=False,
            classes=[*_SCREEN_CLASS_IDS, _PHONE_CLASS_ID],
            conf=max(0.05, min(0.8, float(confidence))),
            iou=0.45,
            imgsz=max(640, min(1280, int(image_size))),
        )

    if not results or results[0].boxes is None:
        return []

    boxes = results[0].boxes
    return [
        {
            "class_id": int(class_id),
            "confidence": round(float(score) * 100, 1),
            "bbox": [round(float(value), 2) for value in bbox],
        }
        for bbox, class_id, score in zip(
            boxes.xyxy.cpu().numpy(),
            boxes.cls.cpu().numpy(),
            boxes.conf.cpu().numpy(),
        )
    ]


# ──────────────────────────────────────────────
# Preprocessing
# ──────────────────────────────────────────────
def preprocess_frame(frame: np.ndarray) -> np.ndarray:
    """CLAHE บน L-channel เพื่อ normalize แสงหลายระดับในห้องเรียน"""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


# ──────────────────────────────────────────────
# Keypoint helpers
# ──────────────────────────────────────────────
KP_CONF_THRESHOLD = 0.40   # keypoint confidence ต่ำกว่านี้ถือว่าไม่น่าเชื่อถือ

_KP_IDX = dict(
    nose=0,
    left_eye=1,  right_eye=2,
    left_ear=3,  right_ear=4,
    left_shoulder=5,  right_shoulder=6,
    left_elbow=7,     right_elbow=8,
    left_wrist=9,     right_wrist=10,
    left_hip=11,      right_hip=12,
    left_knee=13,     right_knee=14,
    left_ankle=15,    right_ankle=16,
)

def _get(kp, name):
    """คืน (x, y) ถ้า confidence ผ่าน threshold, ไม่งั้น None"""
    idx = _KP_IDX.get(name)
    if idx is None or idx >= len(kp):
        return None
    x, y, c = kp[idx]
    if c < KP_CONF_THRESHOLD or (float(x) == 0.0 and float(y) == 0.0):
        return None
    return np.array([float(x), float(y)])


def _has_masked_wrist_candidates(kp):
    masked = 0
    for index in (_KP_IDX["left_wrist"], _KP_IDX["right_wrist"]):
        if index >= len(kp) or len(kp[index]) < 3:
            continue
        x, y, confidence = kp[index]
        if confidence >= 0.25 and float(x) == 0.0 and float(y) == 0.0:
            masked += 1
    return masked == 2

def _midpoint(a, b):
    return (a + b) / 2 if (a is not None and b is not None) else None

def _dist(a, b):
    return float(np.linalg.norm(a - b)) if (a is not None and b is not None) else None

def _angle(a, b, c):
    if a is None or b is None or c is None:
        return None

    v1 = a - b
    v2 = c - b
    denom = float(np.linalg.norm(v1) * np.linalg.norm(v2))
    if denom <= 1e-6:
        return None

    cos_val = float(np.dot(v1, v2) / denom)
    cos_val = max(-1.0, min(1.0, cos_val))
    return float(np.degrees(np.arccos(cos_val)))

def _standing_leg_votes(legs, shoulder_width):
    votes = 0
    for hip, knee, ankle in legs:
        knee_angle = _angle(hip, knee, ankle)
        if knee_angle is None:
            continue

        leg_span = (ankle[1] - hip[1]) / shoulder_width
        upper_dy = (knee[1] - hip[1]) / shoulder_width
        lower_dy = (ankle[1] - knee[1]) / shoulder_width
        upper_dx = abs(knee[0] - hip[0]) / shoulder_width
        lower_dx = abs(ankle[0] - knee[0]) / shoulder_width

        if (
            knee_angle >= 150
            and leg_span > 1.45
            and upper_dy > 0.50
            and lower_dy > 0.55
            and upper_dx < 0.85
            and lower_dx < 0.85
        ):
            votes += 1
    return votes


def _is_hand_raised(kp):
    """ต้องเห็นแขนยกเหนือใบหน้า ไม่ใช่แค่วางมือใกล้แก้มหรือคาง"""
    nose = _get(kp, "nose")
    left_eye = _get(kp, "left_eye")
    right_eye = _get(kp, "right_eye")
    face_center = nose if nose is not None else _midpoint(left_eye, right_eye)
    if face_center is None:
        return False

    left_shoulder = _get(kp, "left_shoulder")
    right_shoulder = _get(kp, "right_shoulder")
    shoulder_width = _dist(left_shoulder, right_shoulder)
    if shoulder_width is None:
        return False

    arms = (
        (
            _get(kp, "left_wrist"),
            _get(kp, "left_elbow"),
            left_shoulder,
        ),
        (
            _get(kp, "right_wrist"),
            _get(kp, "right_elbow"),
            right_shoulder,
        ),
    )
    for wrist, elbow, shoulder in arms:
        if wrist is None or elbow is None or shoulder is None:
            continue
        wrist_above_face = wrist[1] < face_center[1] - (0.08 * shoulder_width)
        elbow_supported = elbow[1] < shoulder[1] + (0.15 * shoulder_width)
        forearm_points_up = wrist[1] < elbow[1] - (0.20 * shoulder_width)
        if wrist_above_face and elbow_supported and forearm_points_up:
            return True
    return False


def _is_sleeping_posture(kp):
    """ต้องเห็นทั้งศีรษะต่ำและลำตัวพับ เพื่อลดการสับสนกับการมองจอ"""
    nose = _get(kp, "nose")
    left_shoulder = _get(kp, "left_shoulder")
    right_shoulder = _get(kp, "right_shoulder")
    left_hip = _get(kp, "left_hip")
    right_hip = _get(kp, "right_hip")
    shoulder_center = _midpoint(left_shoulder, right_shoulder)
    hip_center = _midpoint(left_hip, right_hip)
    shoulder_width = _dist(left_shoulder, right_shoulder)
    if nose is None or shoulder_center is None or hip_center is None:
        return False
    if shoulder_width is None:
        return False

    head_ratio = (shoulder_center[1] - nose[1]) / shoulder_width
    vertical_torso = (hip_center[1] - shoulder_center[1]) / shoulder_width
    horizontal_torso = abs(hip_center[0] - shoulder_center[0]) / shoulder_width
    torso_collapsed = vertical_torso < 0.35 or horizontal_torso > 0.85
    return head_ratio <= 0.10 and torso_collapsed


def _is_phone_hand_posture(kp):
    """จับท่ามือบรรจบต่ำกว่าไหล่เป็นเพียงสัญญาณสงสัยใช้โทรศัพท์"""
    left_shoulder = _get(kp, "left_shoulder")
    right_shoulder = _get(kp, "right_shoulder")
    left_elbow = _get(kp, "left_elbow")
    right_elbow = _get(kp, "right_elbow")
    left_wrist = _get(kp, "left_wrist")
    right_wrist = _get(kp, "right_wrist")
    shoulder_center = _midpoint(left_shoulder, right_shoulder)
    wrist_center = _midpoint(left_wrist, right_wrist)
    shoulder_width = _dist(left_shoulder, right_shoulder)
    wrist_distance = _dist(left_wrist, right_wrist)
    elbow_distance = _dist(left_elbow, right_elbow)
    if (
        shoulder_center is None
        or wrist_center is None
        or shoulder_width is None
        or wrist_distance is None
        or elbow_distance is None
    ):
        return False

    wrists_close = wrist_distance <= shoulder_width * 0.85
    hands_below_shoulders = (
        wrist_center[1] >= shoulder_center[1] + (shoulder_width * 0.35)
    )
    forearms_converge = (
        elbow_distance >= wrist_distance + (shoulder_width * 0.15)
    )
    return wrists_close and hands_below_shoulders and forearms_converge


def _center_inside_expanded(container, item, margin_x, margin_y):
    if not container or not item:
        return False
    x1, y1, x2, y2 = (float(value) for value in container)
    item_x1, item_y1, item_x2, item_y2 = (
        float(value) for value in item
    )
    width = max(1.0, x2 - x1)
    height = max(1.0, y2 - y1)
    center_x = (item_x1 + item_x2) / 2
    center_y = (item_y1 + item_y2) / 2
    return (
        x1 - (width * margin_x) <= center_x <= x2 + (width * margin_x)
        and y1 - (height * margin_y)
        <= center_y
        <= y2 + (height * margin_y)
    )


def _bbox_center_distance_ratio(left, right):
    left_x1, left_y1, left_x2, left_y2 = (float(value) for value in left)
    right_x1, right_y1, right_x2, right_y2 = (
        float(value) for value in right
    )
    left_center = ((left_x1 + left_x2) / 2, (left_y1 + left_y2) / 2)
    right_center = ((right_x1 + right_x2) / 2, (right_y1 + right_y2) / 2)
    scale = max(1.0, left_x2 - left_x1, left_y2 - left_y1)
    return float(np.linalg.norm(np.subtract(left_center, right_center))) / scale


def _person_contexts(person_bboxes, context_objects):
    contexts = [
        {"phone_confidence": 0.0, "screen_detected": False}
        for _ in person_bboxes
    ]
    for item in context_objects or []:
        object_bbox = item.get("bbox")
        class_id = item.get("class_id")
        if not object_bbox:
            continue

        if class_id in _SCREEN_CLASS_IDS:
            for index, person_bbox in enumerate(person_bboxes):
                if not person_bbox:
                    continue
                _, person_y1, _, person_y2 = (
                    float(value) for value in person_bbox
                )
                _, object_y1, _, object_y2 = (
                    float(value) for value in object_bbox
                )
                object_center_y = (object_y1 + object_y2) / 2
                screen_is_near_gaze = object_center_y <= (
                    person_y1 + ((person_y2 - person_y1) * 0.40)
                )
                if _center_inside_expanded(
                    person_bbox,
                    object_bbox,
                    0.90,
                    0.30,
                ) and screen_is_near_gaze:
                    contexts[index]["screen_detected"] = True
            continue

        if class_id != _PHONE_CLASS_ID:
            continue
        candidates = [
            (
                _bbox_center_distance_ratio(person_bbox, object_bbox),
                index,
            )
            for index, person_bbox in enumerate(person_bboxes)
            if _center_inside_expanded(
                person_bbox,
                object_bbox,
                0.25,
                0.20,
            )
        ]
        if not candidates:
            continue
        _, person_index = min(candidates)
        contexts[person_index]["phone_confidence"] = max(
            contexts[person_index]["phone_confidence"],
            float(item.get("confidence") or 0),
        )
    return contexts


def _detect_phones_in_suspected_person_crops(
    frame,
    keypoints_data,
    person_bboxes,
    person_contexts,
    *,
    confidence=0.18,
    image_size=640,
):
    """Recheck likely phone users in tighter crops when full-frame YOLO misses it."""
    if frame is None:
        return []

    frame_height, frame_width = frame.shape[:2]
    crop_candidates = []
    for index, (keypoints, person_bbox, context) in enumerate(
        zip(keypoints_data, person_bboxes, person_contexts)
    ):
        if (
            not person_bbox
            or context.get("phone_confidence", 0) > 0
            or not _is_phone_hand_posture(keypoints)
        ):
            continue

        x1, y1, x2, y2 = (float(value) for value in person_bbox)
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        crop_x1 = max(0, int(round(x1 - (width * 0.15))))
        crop_y1 = max(0, int(round(y1 - (height * 0.15))))
        crop_x2 = min(frame_width, int(round(x2 + (width * 0.15))))
        crop_y2 = min(frame_height, int(round(y2 + (height * 0.15))))
        if crop_x2 - crop_x1 < 16 or crop_y2 - crop_y1 < 16:
            continue
        crop_candidates.append(
            {
                "image": frame[crop_y1:crop_y2, crop_x1:crop_x2],
                "origin": (crop_x1, crop_y1),
                "person_index": index,
            }
        )

    if not crop_candidates:
        return []

    with pose_model_lock:
        model = get_context_model()
        if model is None:
            return []
        results = model(
            [candidate["image"] for candidate in crop_candidates],
            verbose=False,
            classes=[_PHONE_CLASS_ID],
            conf=max(0.05, min(0.8, float(confidence))),
            iou=0.45,
            imgsz=max(480, min(960, int(image_size))),
        )

    detections = []
    for candidate, result in zip(crop_candidates, results or []):
        if result.boxes is None or len(result.boxes) == 0:
            continue
        boxes = result.boxes
        rows = boxes.xyxy.cpu().numpy()
        scores = boxes.conf.cpu().numpy()
        best_index = int(np.argmax(scores))
        offset_x, offset_y = candidate["origin"]
        local_bbox = rows[best_index]
        detections.append(
            {
                "class_id": _PHONE_CLASS_ID,
                "confidence": round(float(scores[best_index]) * 100, 1),
                "bbox": [
                    round(float(local_bbox[0]) + offset_x, 2),
                    round(float(local_bbox[1]) + offset_y, 2),
                    round(float(local_bbox[2]) + offset_x, 2),
                    round(float(local_bbox[3]) + offset_y, 2),
                ],
                "source": "person_crop",
            }
        )
    return detections


def _person_context(person_bbox, context_objects):
    return _person_contexts([person_bbox], context_objects)[0]


# ──────────────────────────────────────────────
# Multi-signal scoring
# ──────────────────────────────────────────────
def _score_behavior(kp) -> dict:
    """
    คำนวณ score สำหรับแต่ละพฤติกรรมจาก keypoints หลายจุด

    Signals ที่ใช้:
      S1  Head elevation ratio   (จมูก vs ไหล่)
      S2  Trunk uprightness      (ไหล่ vs สะโพก)
      S3  Eye separation ratio   (หน้าตรง vs หันข้าง)
      S4  Ear symmetry           (เห็นสองหู vs หูเดียว)
      S5  Confirmed phone object (เพิ่มภายหลังจาก object detector)
      S6  Wrist above face + supported elbow (ยกมือ)
      S7  Full-body verticality   (ยืน/ลุก)
    """
    scores = {"attentive": 0.0, "looking_down": 0.0,
              "phone_use": 0.0, "phone_suspected": 0.0,
              "sleeping": 0.0,
              "hand_raised": 0.0, "standing": 0.0}

    nose           = _get(kp, "nose")
    left_eye       = _get(kp, "left_eye")
    right_eye      = _get(kp, "right_eye")
    left_shoulder  = _get(kp, "left_shoulder")
    right_shoulder = _get(kp, "right_shoulder")
    left_hip       = _get(kp, "left_hip")
    right_hip      = _get(kp, "right_hip")
    left_knee      = _get(kp, "left_knee")
    right_knee     = _get(kp, "right_knee")
    left_ankle     = _get(kp, "left_ankle")
    right_ankle    = _get(kp, "right_ankle")

    shoulder_center = _midpoint(left_shoulder, right_shoulder)
    hip_center      = _midpoint(left_hip, right_hip)
    ankle_center    = _midpoint(left_ankle, right_ankle)
    shoulder_width  = (_dist(left_shoulder, right_shoulder) or 80.0)

    # ── S1: Head elevation ratio ─────────────────────────────────
    # กล้องห้องแล็บมักอยู่สูง ~30-45° calibrate threshold ให้เหมาะ
    if nose is not None and shoulder_center is not None:
        head_elev  = shoulder_center[1] - nose[1]   # บวก = หัวสูงกว่าไหล่ (ปกติ)
        head_ratio = head_elev / shoulder_width

        if   head_ratio > 0.55:                     # นั่งตรง หัวตั้งชัด
            scores["attentive"]    += 2.5
        elif head_ratio > 0.30:                     # นั่งตรงพอสมควร
            scores["attentive"]    += 1.5
            scores["looking_down"] += 0.25
        elif head_ratio > 0.10:                     # ก้มเล็กน้อย
            scores["attentive"]    += 0.75
            scores["looking_down"] += 1.5
        elif head_ratio > -0.10:                    # ก้มมาก
            scores["looking_down"] += 2.0
        else:                                       # หัวต่ำมาก แต่ยังไม่สรุปว่าหลับ
            scores["looking_down"] += 2.5

    # ── S2: Trunk uprightness ────────────────────────────────────
    if shoulder_center is not None and hip_center is not None:
        trunk_dy = shoulder_center[1] - hip_center[1]  # ลบ = ไหล่สูงกว่าสะโพก (ปกติ)
        if trunk_dy < -20:        # ตั้งตรงดี
            scores["attentive"] += 1.0

        torso_ratio = (hip_center[1] - shoulder_center[1]) / shoulder_width
        if ankle_center is not None:
            body_ratio = (ankle_center[1] - shoulder_center[1]) / shoulder_width
            standing_votes = _standing_leg_votes(
                [(left_hip, left_knee, left_ankle),
                 (right_hip, right_knee, right_ankle)],
                shoulder_width,
            )
            strong_two_leg = standing_votes >= 2 and body_ratio > 3.05
            strong_one_leg = standing_votes >= 1 and body_ratio > 3.45
            if torso_ratio > 0.80 and (strong_two_leg or strong_one_leg):
                scores["standing"]  += 3.0
                scores["attentive"] -= 0.75

    # ── S3: Eye separation ratio ─────────────────────────────────
    eye_dist = _dist(left_eye, right_eye)
    if eye_dist is not None:
        eye_ratio = eye_dist / shoulder_width
        if   eye_ratio > 0.25:   scores["attentive"] += 2.0  # หน้าตรง
        elif eye_ratio > 0.12:   scores["attentive"] += 0.5
        else:                    scores["attentive"] += 0.25  # หันข้างไม่แยกเป็นพฤติกรรม

    # ── S4: Ear symmetry ─────────────────────────────────────────
    left_ear_conf  = float(kp[3][2]) if len(kp) > 3 else 0.0
    right_ear_conf = float(kp[4][2]) if len(kp) > 4 else 0.0
    both_ears = (left_ear_conf  >= KP_CONF_THRESHOLD and
                 right_ear_conf >= KP_CONF_THRESHOLD)
    one_ear   = ((left_ear_conf  >= KP_CONF_THRESHOLD) ^
                 (right_ear_conf >= KP_CONF_THRESHOLD))
    if both_ears: scores["attentive"] += 1.0
    elif one_ear: scores["attentive"] += 0.25

    # ── S5/S6: Object context and explicit hand raise ────────────
    if _is_hand_raised(kp):
        scores["hand_raised"] += 4.0
        scores["attentive"] += 0.75

    if _is_sleeping_posture(kp):
        scores["sleeping"] += 4.0

    if _is_phone_hand_posture(kp):
        scores["phone_suspected"] += 3.5

    # คลิปค่าลบออก
    for k in scores:
        scores[k] = max(0.0, scores[k])

    return scores


def analyze_pose(
    keypoints,
    *,
    phone_confidence=0.0,
    screen_detected=False,
) -> dict:
    """
    วิเคราะห์ท่าทางจาก keypoints ด้วย multi-signal scoring

    Returns: {"behavior": str, "confidence": int, "details": dict}
    """
    if keypoints is None or len(keypoints) < 13:
        return {"behavior": "unknown", "confidence": 0, "details": {}}

    scores = _score_behavior(keypoints)
    phone_confidence = max(0.0, min(100.0, float(phone_confidence or 0)))
    phone_hand_posture = _is_phone_hand_posture(keypoints)
    ambiguous_hand_activity = (
        _has_masked_wrist_candidates(keypoints)
        and scores.get("looking_down", 0) >= 1.0
    )
    if phone_confidence > 0:
        scores["phone_use"] = max(4.0, phone_confidence / 20.0)
    elif (
        screen_detected
        and not ambiguous_hand_activity
        and not phone_hand_posture
        and scores.get("looking_down", 0) > 0
    ):
        scores["attentive"] += 2.0
        scores["looking_down"] = max(
            0.0,
            scores["looking_down"] - 1.5,
        )
    total  = sum(scores.values())
    visible_kp = int(sum(
        1
        for kp in keypoints
        if (
            len(kp) >= 3
            and kp[2] >= KP_CONF_THRESHOLD
            and not (float(kp[0]) == 0.0 and float(kp[1]) == 0.0)
        )
    ))

    def _unknown():
        return {"behavior": "unknown", "confidence": 0,
                "details": {
                    "scores": {k: round(v, 2) for k, v in scores.items()},
                    "visible_keypoints": visible_kp,
                }}

    if ambiguous_hand_activity and phone_confidence <= 0:
        return _unknown()

    if visible_kp < 6 and phone_confidence <= 0:
        return _unknown()

    if total < 1.0:
        # signal น้อยเกินไป (keypoints ส่วนใหญ่ confidence ต่ำ / คนถูกบดบังมาก)
        return _unknown()

    priority_best = None
    if phone_confidence > 0:
        priority_best = "phone_use"
    elif phone_hand_posture:
        priority_best = "phone_suspected"
    elif _is_hand_raised(keypoints):
        priority_best = "hand_raised"
    elif scores.get("standing", 0) >= 3.0:
        priority_best = "standing"

    best  = priority_best or max(scores, key=scores.get)
    best_score = scores[best]
    confidence = min(97, int(round((best_score / total) * 100)))
    if priority_best:
        minimum_confidence = 55 if best == "phone_suspected" else 65
        confidence = max(minimum_confidence, confidence)
    if best == "phone_use":
        confidence = max(confidence, int(round(phone_confidence)))
    elif best == "phone_suspected":
        confidence = max(55, confidence)

    # ถ้าคะแนนชนะไม่ชัดเจน ให้เป็น unknown แทนการเดาเป็น attentive
    sorted_vals = sorted(scores.values(), reverse=True)
    margin = best_score - sorted_vals[1] if len(sorted_vals) > 1 else best_score
    if priority_best is None and len(sorted_vals) > 1 and margin < 0.5:
        return _unknown()
    if best == "attentive" and (best_score < 2.0 or confidence < 40):
        return _unknown()

    return {
        "behavior":   best,
        "confidence": confidence,
        "details": {
            "scores":           {k: round(v, 2) for k, v in scores.items()},
            "visible_keypoints": visible_kp,
            "phone_detected": phone_confidence > 0,
            "phone_confidence": round(phone_confidence, 1),
            "phone_hand_posture": phone_hand_posture,
            "screen_detected": bool(screen_detected),
        },
    }


# ──────────────────────────────────────────────
# Frame-level analysis
# ──────────────────────────────────────────────
def analyze_frame(
    frame: np.ndarray,
    context_objects=None,
    *,
    refine_phone_detection=False,
    phone_detection_confidence=0.18,
) -> dict:
    """
    วิเคราะห์ภาพทั้งเฟรม พร้อม preprocessing และ annotated output

    Args:
        frame: BGR numpy array
    Returns:
        dict: total_people, behaviors, summary, attention_rate, annotated_frame
    """
    context_objects = list(context_objects or [])
    processed = preprocess_frame(frame)

    with pose_model_lock:
        model   = get_pose_model()
        results = model(
            processed,
            verbose=False,
            conf=0.35,   # detection confidence ต่ำลงเพื่อจับคนที่ถูกจอบดบัง
            iou=0.45,    # NMS IoU ป้องกัน duplicate detection
            imgsz=640,
        )

    _empty = {
        "total_people": 0,
        "behaviors": [],
        "summary": {"attentive": 0, "sleeping": 0,
                    "looking_down": 0, "phone_use": 0,
                    "phone_suspected": 0,
                    "hand_raised": 0,
                    "standing": 0, "unknown": 0},
        "attention_rate": 0,
        "annotated_frame": frame,
    }

    if not results or results[0].keypoints is None:
        return _empty

    keypoints_data = results[0].keypoints.data.cpu().numpy()
    boxes          = results[0].boxes

    if len(keypoints_data) == 0:
        return _empty

    behaviors      = []
    behavior_counts = {"attentive": 0, "sleeping": 0,
                       "looking_down": 0, "phone_use": 0,
                       "phone_suspected": 0,
                       "hand_raised": 0,
                       "standing": 0, "unknown": 0}

    box_rows = boxes.xyxy.cpu().numpy() if boxes is not None else []
    box_confidences = boxes.conf.cpu().numpy() if boxes is not None else []

    person_bboxes = [
        (
            [round(float(value), 2) for value in box_rows[index]]
            if index < len(box_rows)
            else None
        )
        for index in range(len(keypoints_data))
    ]
    person_contexts = _person_contexts(person_bboxes, context_objects)
    if refine_phone_detection:
        context_objects.extend(
            _detect_phones_in_suspected_person_crops(
                frame,
                keypoints_data,
                person_bboxes,
                person_contexts,
                confidence=phone_detection_confidence,
            )
        )
        person_contexts = _person_contexts(person_bboxes, context_objects)

    for index, kp in enumerate(keypoints_data):
        person_bbox = person_bboxes[index]
        context = person_contexts[index]
        analysis = analyze_pose(kp, **context)
        if index < len(box_rows):
            analysis["bbox"] = person_bbox
        if index < len(box_confidences):
            analysis["detection_confidence"] = round(
                float(box_confidences[index]) * 100,
                1,
            )
        behaviors.append(analysis)
        beh = analysis["behavior"]
        if beh in behavior_counts:
            behavior_counts[beh] += 1

    total_people    = len(behaviors)
    attentive_count = behavior_counts["attentive"] + behavior_counts["hand_raised"]
    attention_rate  = round((attentive_count / total_people) * 100, 1) if total_people else 0

    # ── Annotated frame ──────────────────────────────────────────
    annotated_frame = results[0].plot(conf=False, labels=False)

    _COLOR = {
        "attentive":    ( 50, 205,  50),  # เขียว
        "sleeping":     (  0,   0, 220),  # แดง
        "looking_down": (  0, 140, 255),  # ส้ม
        "phone_use":    ( 30, 105, 210),  # ส้มเข้ม
        "phone_suspected": ( 80, 150, 220),  # เหลืองเข้ม
        "hand_raised":  (235, 180,  20),  # ฟ้า
        "standing":     (170,  80, 210),  # ม่วง
        "unknown":      (180, 180, 180),  # เทา
    }

    if boxes is not None and len(boxes) > 0:
        for box, beh in zip(boxes, behaviors):
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            color  = _COLOR.get(beh["behavior"], (180, 180, 180))
            label  = get_behavior_label_en(beh["behavior"])
            conf_t = beh["confidence"]

            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)

            text = f"{label} {conf_t}%"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
            label_y = max(y1 - 5, th + 5)
            cv2.rectangle(annotated_frame,
                          (x1, label_y - th - 4), (x1 + tw + 4, label_y + 2),
                          color, cv2.FILLED)
            cv2.putText(annotated_frame, text, (x1 + 2, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

    for item in context_objects or []:
        if item.get("class_id") != _PHONE_CLASS_ID or not item.get("bbox"):
            continue
        x1, y1, x2, y2 = map(int, item["bbox"])
        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (30, 105, 210), 2)
        cv2.putText(
            annotated_frame,
            f"Phone {item.get('confidence', 0):.0f}%",
            (x1, max(16, y1 - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (30, 105, 210),
            1,
        )

    # ── HUD bar ──────────────────────────────────────────────────
    h, w = annotated_frame.shape[:2]
    hud = (f"Attention {attention_rate}%  |  "
           f"Students: {total_people}  |  "
           f"Sleeping: {behavior_counts['sleeping']}  |  "
           f"Down: {behavior_counts['looking_down']}  |  "
           f"Phone: {behavior_counts['phone_use']}  |  "
           f"Phone?: {behavior_counts['phone_suspected']}  |  "
           f"Raised: {behavior_counts['hand_raised']}  |  "
           f"Standing: {behavior_counts['standing']}")
    cv2.rectangle(annotated_frame, (0, h - 32), (w, h), (30, 30, 30), cv2.FILLED)
    cv2.putText(annotated_frame, hud, (8, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1)

    analysis_result = {
        "total_people":    total_people,
        "behaviors":       behaviors,
        "summary":         behavior_counts,
        "attention_rate":  attention_rate,
        "annotated_frame": annotated_frame,
    }
    if refine_phone_detection:
        analysis_result["_context_objects"] = context_objects
    return analysis_result


# ──────────────────────────────────────────────
# Label helpers
# ──────────────────────────────────────────────
def get_behavior_label_th(behavior: str) -> str:
    return {
        "attentive":    "ตั้งใจเรียน",
        "sleeping":     "หลับ",
        "looking_down": "ก้มหน้า",
        "phone_use":    "ใช้โทรศัพท์",
        "phone_suspected": "สงสัยใช้โทรศัพท์",
        "hand_raised":  "ยกมือ",
        "standing":     "ยืน/ลุก",
        "unknown":      "ไม่ทราบ",
    }.get(behavior, behavior)


def get_behavior_label_en(behavior: str) -> str:
    return {
        "attentive":    "Attentive",
        "sleeping":     "Sleeping",
        "looking_down": "Looking Down",
        "phone_use":    "Phone Use",
        "phone_suspected": "Phone Suspected",
        "hand_raised":  "Hand Raised",
        "standing":     "Standing",
        "unknown":      "Unknown",
    }.get(behavior, behavior)
