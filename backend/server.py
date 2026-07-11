from flask import Flask, jsonify, send_from_directory, Response, request
from flask_cors import CORS
from ultralytics import YOLO
from werkzeug.utils import secure_filename
import cv2, os, json, time, threading
import ipaddress
import sys
from datetime import datetime
from collections import deque
from behavior_analyzer import analyze_frame, get_behavior_label_th

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

app = Flask(__name__, static_folder="../dashboard")
_base_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_base_dir, os.pardir))

_default_allowed_origins = "http://127.0.0.1:5000,http://localhost:5000"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CLASSMOOD_ALLOWED_ORIGINS", _default_allowed_origins).split(",")
    if origin.strip()
]
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})


def _env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _first_existing_path(*paths):
    for path in paths:
        if path and os.path.exists(path):
            return path
    return None

# โหลดโมเดล YOLO สำหรับตรวจจับคน — ลอง yolov8s ก่อน fallback ไป nano
_detection_model_path = _first_existing_path(
    os.path.join(_base_dir, "yolov8s.pt"),
    os.path.join(_project_root, "yolov8s.pt"),
    os.path.join(_base_dir, "yolov8n.pt"),
    os.path.join(_project_root, "yolov8n.pt"),
)
model = YOLO(_detection_model_path or "yolov8n.pt")
model.classes = [0]  # เฉพาะ class คน
detection_lock = threading.Lock()

# 📊 เก็บสถิติย้อนหลัง
stats_history = {}  # {lab_id: deque of stats}
activity_log = {}   # {lab_id: deque of activities}
session_names = {}  # {lab_id: display name from frontend}
MAX_HISTORY = 30
state_lock = threading.RLock()

# 🔄 Inference cache — ป้องกัน double inference (behavior-frame + behavior ต่อ tick เดียวกัน)
analysis_cache = {}   # { (lab_id, cam_id): {"result": dict, "ts": float} }
analysis_locks = {}   # { (lab_id, cam_id): Lock }
CACHE_TTL = 4.0       # วินาที (มากกว่า poll interval 2s เล็กน้อย)

# 🔔 Alerts — รายการแจ้งเตือนสำหรับ frontend
alerts_list = []
_alert_id_ctr = [0]  # ใช้ list เพื่อให้ nested function แก้ไขได้

# 💾 Persistence — path สำหรับบันทึกข้อมูลลง disk
DATA_DIR   = os.path.join(_base_dir, "data")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
VIDEO_SOURCE_DIRS = [
    os.path.abspath(os.path.expanduser(path.strip()))
    for path in os.getenv(
        "CLASSMOOD_VIDEO_DIRS",
        os.path.join(_base_dir, "video_sources"),
    ).split(os.pathsep)
    if path.strip()
]
if not VIDEO_SOURCE_DIRS:
    VIDEO_SOURCE_DIRS = [os.path.abspath(os.path.join(_base_dir, "video_sources"))]
MAX_WEBCAM_INDEX = _env_int("CLASSMOOD_MAX_WEBCAM_INDEX", 9)
MAX_VIDEO_UPLOAD_MB = max(1, _env_int("CLASSMOOD_MAX_VIDEO_UPLOAD_MB", 512))
ANNOTATED_STREAM_FPS = min(5, max(1, _env_int("CLASSMOOD_ANNOTATED_STREAM_FPS", 5)))
VIDEO_UPLOAD_DIR = VIDEO_SOURCE_DIRS[0]
app.config["MAX_CONTENT_LENGTH"] = MAX_VIDEO_UPLOAD_MB * 1024 * 1024


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify({"error": f"Video file is larger than {MAX_VIDEO_UPLOAD_MB} MB"}), 413


def _is_loopback_request():
    remote_addr = request.remote_addr or ""
    try:
        addr = ipaddress.ip_address(remote_addr)
        if addr.is_loopback:
            return True
        ipv4_mapped = getattr(addr, "ipv4_mapped", None)
        return bool(ipv4_mapped and ipv4_mapped.is_loopback)
    except ValueError:
        return remote_addr == "localhost"


def _require_local_source_access():
    if _env_flag("CLASSMOOD_ALLOW_REMOTE_SOURCE_CONTROL"):
        return None
    if _is_loopback_request():
        return None
    return jsonify({"error": "Source management is limited to localhost"}), 403


def _is_path_inside(path, roots):
    norm_path = os.path.normcase(os.path.abspath(path))
    for root in roots:
        norm_root = os.path.normcase(os.path.abspath(root))
        try:
            if os.path.commonpath([norm_path, norm_root]) == norm_root:
                return True
        except ValueError:
            continue
    return False


def _normalize_video_source(source):
    if isinstance(source, bool):
        return None, "Source must be a webcam index or a video file path"

    if isinstance(source, int):
        if 0 <= source <= MAX_WEBCAM_INDEX:
            return source, None
        return None, f"Webcam index must be between 0 and {MAX_WEBCAM_INDEX}"

    if not isinstance(source, str):
        return None, "Source must be a webcam index or a video file path"

    raw_source = source.strip()
    if raw_source.isdigit():
        return _normalize_video_source(int(raw_source))

    if "://" in raw_source:
        return None, "Network video URLs are disabled by default"

    path = os.path.abspath(os.path.expanduser(raw_source))
    ext = os.path.splitext(path)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        return None, f"Video file must use one of: {', '.join(sorted(VIDEO_EXTENSIONS))}"
    if not os.path.exists(path):
        return None, f"Video file not found: {path}"
    if not _env_flag("CLASSMOOD_ALLOW_ANY_VIDEO_PATH") and not _is_path_inside(path, VIDEO_SOURCE_DIRS):
        allowed = ", ".join(VIDEO_SOURCE_DIRS)
        return None, f"Video file must be inside allowed directories: {allowed}"
    return path, None


def _build_upload_path(filename):
    original_name = os.path.basename(filename or "")
    original_stem, ext = os.path.splitext(original_name)
    ext = ext.lower()
    if ext not in VIDEO_EXTENSIONS:
        return None, f"Video file must use one of: {', '.join(sorted(VIDEO_EXTENSIONS))}"

    stem = secure_filename(original_stem) or "uploaded_video"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = os.path.abspath(os.path.join(VIDEO_UPLOAD_DIR, f"{stem}_{stamp}{ext}"))
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.abspath(os.path.join(VIDEO_UPLOAD_DIR, f"{stem}_{stamp}_{counter}{ext}"))
        counter += 1

    if not _is_path_inside(candidate, [VIDEO_UPLOAD_DIR]):
        return None, "Invalid upload filename"
    return candidate, None


def _get_image_path(lab_id, cam_id):
    """หา path รูปภาพ รองรับ .png/.PNG"""
    base = os.path.dirname(os.path.abspath(__file__))
    for ext in (".png", ".PNG"):
        p = os.path.join(base, "test_images", f"{lab_id}_{cam_id}{ext}")
        if os.path.exists(p):
            return p
    return None


def _get_cached(lab_id, cam_id):
    with state_lock:
        entry = analysis_cache.get((lab_id, cam_id))
        if entry and (time.time() - entry["ts"]) < CACHE_TTL:
            return entry["result"]
    return None


def _set_cached(lab_id, cam_id, result):
    with state_lock:
        analysis_cache[(lab_id, cam_id)] = {"result": result, "ts": time.time()}


def _get_analysis_lock(lab_id, cam_id):
    key = (lab_id, cam_id)
    with state_lock:
        if key not in analysis_locks:
            analysis_locks[key] = threading.Lock()
        return analysis_locks[key]


# ─── Video Source Manager ─────────────────────────────────────────────────────
# video_sources: { (lab_id, cam_id): source }  source = int (webcam) หรือ str (path วิดีโอ)
video_sources: dict = {}
# frame_buffers: { (lab_id, cam_id): {"frame": ndarray|None, "lock": Lock, "running": bool, "thread": Thread|None} }
frame_buffers: dict = {}
# source_states: { (lab_id, cam_id): status for frontend polling }
source_states: dict = {}


def _source_type(source):
    return "video" if isinstance(source, str) else "webcam"


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _set_source_state(key, **updates):
    with state_lock:
        state = source_states.setdefault(key, {})
        state.update(updates)
        return dict(state)


def _capture_loop(key):
    """Background thread อ่าน frame ต่อเนื่องจาก VideoCapture"""
    buf = frame_buffers[key]
    src = video_sources.get(key)
    cap = cv2.VideoCapture(src)
    is_file = isinstance(src, str)
    if not cap.isOpened():
        print(f"⚠️  VideoCapture เปิดไม่ได้: {src}")
        buf["running"] = False
        _set_source_state(
            key,
            active=False,
            ended=False,
            error=f"Unable to open source: {src}",
            ended_at=_now_str(),
        )
        return
    print(f"🎥 เปิด {'วิดีโอ' if is_file else 'เว็บแคม'} {key} → {src}")
    while buf["running"]:
        ok, frame = cap.read()
        if not ok:
            if is_file:
                buf["running"] = False
                buf["ended"] = True
                _set_source_state(
                    key,
                    active=False,
                    ended=True,
                    error=None,
                    ended_at=_now_str(),
                )
                break
            else:
                time.sleep(0.05)
                continue
        if ok and frame is not None:
            with buf["lock"]:
                buf["frame"] = frame
        time.sleep(0.033)  # ~30 FPS max
    cap.release()
    print(f"🛑 ปิด {'วิดีโอ' if is_file else 'เว็บแคม'} {key}")


def _start_capture(lab_id, cam_id, source):
    """เริ่ม background thread สำหรับ (lab_id, cam_id)"""
    key = (lab_id, cam_id)
    _stop_capture(lab_id, cam_id)  # หยุด thread เก่าก่อน
    video_sources[key] = source
    buf = {"frame": None, "lock": threading.Lock(), "running": True, "thread": None, "ended": False}
    frame_buffers[key] = buf
    _set_source_state(
        key,
        source=source,
        source_type=_source_type(source),
        active=True,
        ended=False,
        error=None,
        started_at=_now_str(),
        ended_at=None,
    )
    t = threading.Thread(target=_capture_loop, args=(key,), daemon=True)
    buf["thread"] = t
    t.start()


def _stop_capture(lab_id, cam_id):
    """หยุด background thread ของ (lab_id, cam_id)"""
    key = (lab_id, cam_id)
    if key in frame_buffers:
        frame_buffers[key]["running"] = False
        t = frame_buffers[key].get("thread")
        if t and t.is_alive():
            t.join(timeout=2.0)
        del frame_buffers[key]
    video_sources.pop(key, None)
    with state_lock:
        source_states.pop(key, None)
        analysis_cache.pop(key, None)
        analysis_locks.pop(key, None)


def get_live_frame(lab_id, cam_id):
    """คืน frame ล่าสุดจาก buffer หรือ None ถ้าไม่มี live source"""
    buf = frame_buffers.get((lab_id, cam_id))
    if buf:
        with buf["lock"]:
            f = buf["frame"]
        if f is not None:
            return f.copy()
    return None


def _read_frame(lab_id, cam_id):
    """
    อ่าน frame สำหรับ API: live buffer → static image
    คืน (frame, error_tuple_or_None)
    """
    frame = get_live_frame(lab_id, cam_id)
    if frame is not None:
        return frame, None
    # fallback สู่รูปนิ่ง
    image_path = _get_image_path(lab_id, cam_id)
    if not image_path:
        return None, (jsonify({"error": "Image not found"}), 404)
    frame = cv2.imread(image_path)
    if frame is None:
        return None, (jsonify({"error": "Unable to read image"}), 400)
    return frame, None


def _get_or_analyze(lab_id, cam_id, frame=None):
    analysis = _get_cached(lab_id, cam_id)
    if analysis is not None:
        return analysis, False, None

    analysis_lock = _get_analysis_lock(lab_id, cam_id)
    with analysis_lock:
        analysis = _get_cached(lab_id, cam_id)
        if analysis is not None:
            return analysis, False, None

        if frame is None:
            frame, err = _read_frame(lab_id, cam_id)
            if err:
                return None, False, err

        analysis = analyze_frame(frame)
        _set_cached(lab_id, cam_id, analysis)
        record_stats(lab_id, analysis)
        return analysis, True, None


def _annotate_count_frame(frame):
    with detection_lock:
        results = model(frame)
    annotated_frame = results[0].plot()
    boxes = results[0].boxes
    people = 0
    if boxes is not None:
        for box in boxes:
            if int(box.cls[0]) == 0:
                people += 1

    h, w = annotated_frame.shape[:2]
    hud = f"People detected: {people}"
    cv2.rectangle(annotated_frame, (0, h - 32), (w, h), (30, 30, 30), cv2.FILLED)
    cv2.putText(
        annotated_frame,
        hud,
        (8, h - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (220, 220, 220),
        1,
    )
    return annotated_frame


def _annotate_stream_frame(frame, mode):
    if mode == "behavior":
        analysis = analyze_frame(frame)
        annotated_frame = analysis.get("annotated_frame")
        return annotated_frame if annotated_frame is not None else frame
    return _annotate_count_frame(frame)


def _push_alert_unlocked(lab_id, alert_type, message):
    _alert_id_ctr[0] += 1
    alerts_list.append({
        "id":      _alert_id_ctr[0],
        "time":    datetime.now().strftime("%H:%M:%S"),
        "lab_id":  lab_id,
        "type":    alert_type,
        "message": message,
    })
    if len(alerts_list) > 50:
        alerts_list.pop(0)


def _set_session_name(lab_id, name):
    clean_name = str(name or "").strip()
    if clean_name:
        session_names[lab_id] = clean_name[:80]
    else:
        session_names.setdefault(lab_id, lab_id)


def _session_label(lab_id):
    return session_names.get(lab_id) or lab_id


def push_alert(lab_id, alert_type, message):
    with state_lock:
        _push_alert_unlocked(lab_id, alert_type, message)


def save_stats():
    """บันทึก stats_history และ activity_log ลง disk"""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with state_lock:
            payload = {
                "stats_history": {k: list(v) for k, v in stats_history.items()},
                "activity_log":  {k: list(v) for k, v in activity_log.items()},
                "session_names": dict(session_names),
            }
            with open(STATS_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ บันทึกข้อมูลล้มเหลว: {e}")


def load_stats():
    """โหลดข้อมูลเดิมจาก disk เมื่อ server เริ่ม"""
    if not os.path.exists(STATS_FILE):
        return
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        with state_lock:
            for lab_id, items in data.get("stats_history", {}).items():
                stats_history[lab_id] = deque(items, maxlen=MAX_HISTORY)
            for lab_id, items in data.get("activity_log", {}).items():
                activity_log[lab_id] = deque(items, maxlen=20)
            session_names.update(data.get("session_names", {}))
            for lab_id in stats_history:
                activity_log.setdefault(lab_id, deque(maxlen=20))
                session_names.setdefault(lab_id, lab_id)
        print(f"📂 โหลดข้อมูลเดิม: {list(data.get('stats_history', {}).keys())}")
    except Exception as e:
        print(f"⚠️ โหลดข้อมูลเดิมล้มเหลว: {e}")


# ✅ API 1: ส่งเฟรมภาพพร้อมกรอบตรวจจับ
@app.route("/api/frame/<lab_id>/<int:cam_id>")
def get_lab_frame(lab_id, cam_id):
    frame, err = _read_frame(lab_id, cam_id)
    if err:
        return err

    with detection_lock:
        results = model(frame)
    annotated_frame = results[0].plot()
    _, buffer = cv2.imencode(".jpg", annotated_frame)
    return Response(buffer.tobytes(), mimetype="image/jpeg")


# ✅ API 2: ส่งข้อมูลการตรวจจับ (จำนวนคน, ความมั่นใจเฉลี่ย)
@app.route("/api/data/<lab_id>/<int:cam_id>")
def get_lab_data(lab_id, cam_id):
    frame, err = _read_frame(lab_id, cam_id)
    if err:
        return err

    with detection_lock:
        results = model(frame)
    boxes = results[0].boxes

    num_people = 0
    confs = []

    for box in boxes:
        cls_id = int(box.cls[0])
        conf = float(box.conf[0])
        confs.append(conf)
        if cls_id == 0:
            num_people += 1

    avg_conf = round(sum(confs) / len(confs) * 100, 2) if confs else 0
    print("🔍 Detections:", [(float(b.conf[0]), int(b.cls[0])) for b in boxes])

    return jsonify({
        "lab_id": lab_id,
        "camera_id": cam_id,
        "num_people": num_people,
        "avg_confidence": avg_conf,
        "detected_objects": len(confs)
    })


# ✅ API 3: วิเคราะห์พฤติกรรมนักศึกษา (Pose Estimation)
@app.route("/api/behavior/<lab_id>/<int:cam_id>")
def get_behavior_analysis(lab_id, cam_id):
    analysis, created, err = _get_or_analyze(lab_id, cam_id)
    if err:
        return err
    if created:
        print(f"🧠 [{lab_id}/{cam_id}] {analysis['summary']} | Attention: {analysis['attention_rate']}%")

    return jsonify({
        "lab_id": lab_id,
        "camera_id": cam_id,
        "total_people": analysis["total_people"],
        "attention_rate": analysis["attention_rate"],
        "summary": analysis["summary"],
        "behaviors": [
            {
                "behavior": b["behavior"],
                "behavior_th": get_behavior_label_th(b["behavior"]),
                "confidence": b["confidence"]
            } for b in analysis["behaviors"]
        ]
    })


# ✅ API 4: ส่งภาพพร้อม behavior annotation
@app.route("/api/behavior-frame/<lab_id>/<int:cam_id>")
def get_behavior_frame(lab_id, cam_id):
    frame, err = _read_frame(lab_id, cam_id)
    if err:
        return err

    analysis, _, err = _get_or_analyze(lab_id, cam_id, frame)
    if err:
        return err

    annotated_frame = analysis.get("annotated_frame")
    if annotated_frame is None:
        annotated_frame = frame
    _, buffer = cv2.imencode(".jpg", annotated_frame)
    return Response(buffer.tobytes(), mimetype="image/jpeg")


# ✅ API 5: ดึงข้อมูลสถิติย้อนหลังสำหรับกราฟ
@app.route("/api/stats/<lab_id>")
def get_stats_history(lab_id):
    with state_lock:
        history = list(stats_history.get(lab_id, []))

    if not history:
        return jsonify({
            "lab_id": lab_id,
            "session_name": _session_label(lab_id),
            "history": [],
            "labels": []
        })

    labels = [item["time"] for item in history]
    attention_rates = [item["attention_rate"] for item in history]
    people_counts = [item["total_people"] for item in history]
    
    # สถิติพฤติกรรมล่าสุด
    latest = history[-1] if history else None
    
    return jsonify({
        "lab_id": lab_id,
        "session_name": _session_label(lab_id),
        "labels": labels,
        "attention_rates": attention_rates,
        "people_counts": people_counts,
        "latest_summary": latest["summary"] if latest else None
    })


# ✅ API 6: ดึง Activity Log
@app.route("/api/activities/<lab_id>")
def get_activities(lab_id):
    with state_lock:
        activities = list(activity_log.get(lab_id, []))

    if not activities:
        return jsonify({
            "lab_id": lab_id,
            "session_name": _session_label(lab_id),
            "activities": [],
        })
    
    return jsonify({
        "lab_id": lab_id,
        "session_name": _session_label(lab_id),
        "activities": activities
    })


# 📝 ฟังก์ชันบันทึกสถิติ (เรียกครั้งเดียวต่อ cache miss)
def record_stats(lab_id, analysis):
    now = datetime.now()
    time_str = now.strftime("%H:%M:%S")

    summary      = analysis["summary"]
    sleeping     = summary.get("sleeping", 0)
    looking_down = summary.get("looking_down", 0)

    with state_lock:
        session_label = _session_label(lab_id)
        if lab_id not in stats_history:
            stats_history[lab_id] = deque(maxlen=MAX_HISTORY)
        if lab_id not in activity_log:
            activity_log[lab_id] = deque(maxlen=20)

        stats_history[lab_id].append({
            "time": time_str,
            "attention_rate": analysis["attention_rate"],
            "total_people": analysis["total_people"],
            "summary": analysis["summary"]
        })

        # • แจ้งเตือนนักศึกษาหลับ
        if sleeping > 0:
            msg = f"รอบวิเคราะห์ {session_label}: ตรวจพบนักศึกษาหลับ {sleeping} คน"
            activity_log[lab_id].appendleft({"time": time_str, "type": "warning", "message": msg})
            _push_alert_unlocked(lab_id, "warning", msg)

        # • แจ้งเตือนความตั้งใจต่ำ
        if analysis["attention_rate"] < 50 and analysis["total_people"] > 0:
            msg = f"รอบวิเคราะห์ {session_label}: ความตั้งใจต่ำ ({analysis['attention_rate']}%)"
            activity_log[lab_id].appendleft({"time": time_str, "type": "alert", "message": msg})
            _push_alert_unlocked(lab_id, "alert", msg)

        # • แจ้งเตือนถือโทรศัพท์จำนวนมาก
        if looking_down >= 3:
            msg = f"รอบวิเคราะห์ {session_label}: นักศึกษาก้มหน้า/โทรศัพท์ {looking_down} คน"
            _push_alert_unlocked(lab_id, "info", msg)

    # • บันทึกลง disk
    save_stats()


# ✅ API 7: ส่งออกข้อมูลรายงานแบบครบถ้วน
@app.route("/api/export/<lab_id>")
def export_lab_data(lab_id):
    with state_lock:
        history = list(stats_history.get(lab_id, []))
        activities = list(activity_log.get(lab_id, []))

    avg_attention = round(sum(h["attention_rate"] for h in history) / len(history), 1) if history else 0
    avg_people = round(sum(h["total_people"] for h in history) / len(history), 1) if history else 0
    max_people = max((h["total_people"] for h in history), default=0)
    latest = history[-1] if history else None

    return jsonify({
        "lab_id": lab_id,
        "session_name": _session_label(lab_id),
        "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "avg_attention_rate": avg_attention,
            "avg_people": avg_people,
            "max_people": max_people,
            "total_records": len(history),
            "latest_attention_rate": latest["attention_rate"] if latest else 0,
            "latest_total_people": latest["total_people"] if latest else 0,
            "latest_summary": latest["summary"] if latest else {
                "attentive": 0, "sleeping": 0, "looking_down": 0,
                "hand_raised": 0, "standing": 0, "unknown": 0
            }
        },
        "history": history,
        "activities": activities
    })


# ✅ API 8: ดึง Alerts ใหม่ (since_id)
@app.route("/api/alerts")
def get_alerts():
    try:
        since_id = int(request.args.get("since_id", 0))
    except ValueError:
        since_id = 0
    with state_lock:
        new_alerts = [a for a in alerts_list if a["id"] > since_id]
        latest_id = _alert_id_ctr[0]
    return jsonify({"alerts": new_alerts, "latest_id": latest_id})


# ✅ API 9: สรุปทุกห้องสำหรับ Overview
@app.route("/api/overview")
def get_overview():
    with state_lock:
        history_by_lab = {lab_id: list(items) for lab_id, items in stats_history.items()}

    all_labs = sorted(history_by_lab.keys())
    result = {}
    for lab_id in all_labs:
        history = history_by_lab.get(lab_id, [])
        latest  = history[-1] if history else None
        result[lab_id] = {
            "total_people":   latest["total_people"]   if latest else 0,
            "attention_rate": latest["attention_rate"] if latest else 0,
            "summary":        latest["summary"]        if latest else None,
            "has_data":       latest is not None,
            "last_updated":   latest["time"]           if latest else "--:--",
        }
    return jsonify({"labs": result})


# ─── MJPEG Streaming ─────────────────────────────────────────────────────────
def _gen_mjpeg(lab_id, cam_id):
    """Generator สำหรับ MJPEG stream (~25 FPS)"""
    idle = 0
    while True:
        # หยุด stream ถ้า source ถูกลบไปแล้ว
        buf_state = frame_buffers.get((lab_id, cam_id))
        if not buf_state:
            break
        frame = get_live_frame(lab_id, cam_id)
        if frame is None:
            time.sleep(0.05)
            idle += 1
            if idle > 100:  # รอ frame นานเกิน 5 วินาที — หยุด
                print(f"⏱️ MJPEG stream หมดเวลารอ frame: {lab_id}/{cam_id}")
                break
            continue
        idle = 0
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
        if buf_state.get("ended"):
            break
        time.sleep(1 / 25)


def _gen_annotated_mjpeg(lab_id, cam_id, mode):
    """Generator สำหรับ MJPEG stream ที่วาด annotation แล้ว"""
    idle = 0
    delay = 1 / ANNOTATED_STREAM_FPS
    mode = "behavior" if mode == "behavior" else "count"

    while True:
        buf_state = frame_buffers.get((lab_id, cam_id))
        if not buf_state:
            break

        frame = get_live_frame(lab_id, cam_id)
        if frame is None:
            time.sleep(0.05)
            idle += 1
            if idle > 100:
                print(f"⏱️ annotated stream หมดเวลารอ frame: {lab_id}/{cam_id}")
                break
            continue

        idle = 0
        try:
            annotated_frame = _annotate_stream_frame(frame, mode)
        except Exception as e:
            print(f"⚠️ annotated stream วิเคราะห์เฟรมไม่สำเร็จ: {e}")
            annotated_frame = frame

        _, buf = cv2.imencode(".jpg", annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")

        if buf_state.get("ended"):
            break
        time.sleep(delay)


@app.route("/api/stream/<lab_id>/<int:cam_id>")
def stream_camera(lab_id, cam_id):
    """MJPEG streaming endpoint — browser แสดงผลแบบ live"""
    return Response(
        _gen_mjpeg(lab_id, cam_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/annotated-stream/<lab_id>/<int:cam_id>")
def stream_annotated_camera(lab_id, cam_id):
    """MJPEG stream ที่วาดกรอบตรวจจับหรือ pose annotation"""
    mode = request.args.get("mode", "behavior").strip().lower()
    return Response(
        _gen_annotated_mjpeg(lab_id, cam_id, mode),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# ─── Source Management APIs ───────────────────────────────────────────────────
@app.route("/api/videos", methods=["POST"])
def upload_video():
    """อัปโหลดวิดีโอเข้าโฟลเดอร์ที่ระบบอนุญาต แล้วส่ง path กลับไปตั้งเป็น source"""
    blocked = _require_local_source_access()
    if blocked:
        return blocked

    video_file = request.files.get("video")
    if not video_file or not video_file.filename:
        return jsonify({"error": "Missing video file"}), 400

    target_path, path_error = _build_upload_path(video_file.filename)
    if path_error:
        return jsonify({"error": path_error}), 400

    os.makedirs(VIDEO_UPLOAD_DIR, exist_ok=True)
    try:
        video_file.save(target_path)
    except Exception as e:
        return jsonify({"error": f"Unable to save video: {e}"}), 500

    return jsonify({
        "ok": True,
        "filename": os.path.basename(target_path),
        "source": target_path,
        "max_upload_mb": MAX_VIDEO_UPLOAD_MB,
    })


@app.route("/api/sources", methods=["GET"])
def get_sources():
    """แสดงรายการ video sources ที่กำหนดไว้"""
    blocked = _require_local_source_access()
    if blocked:
        return blocked

    with state_lock:
        result = {
            f"{lid}/{cid}": dict(source_states.get((lid, cid), {"source": src}))
            for (lid, cid), src in video_sources.items()
        }
    return jsonify(result)


@app.route("/api/sources/<lab_id>/<int:cam_id>/status", methods=["GET"])
def get_source_status(lab_id, cam_id):
    """คืนสถานะแหล่งภาพ เพื่อให้ frontend รู้ว่าคลิปวิดีโอจบแล้วหรือยัง"""
    key = (lab_id, cam_id)
    with state_lock:
        state = source_states.get(key)
        has_buffer = key in frame_buffers

    if not state:
        return jsonify({
            "ok": True,
            "lab_id": lab_id,
            "cam_id": cam_id,
            "active": False,
            "ended": False,
            "source_type": None,
        })

    payload = dict(state)
    payload.update({
        "ok": True,
        "lab_id": lab_id,
        "cam_id": cam_id,
        "has_buffer": has_buffer,
    })
    return jsonify(payload)


@app.route("/api/sources/<lab_id>/<int:cam_id>", methods=["POST"])
def set_source(lab_id, cam_id):
    """ตั้ง video source: {\"source\": 0} สำหรับ webcam หรือ {\"source\": \"path/video.mp4\"}"""
    blocked = _require_local_source_access()
    if blocked:
        return blocked

    body = request.get_json(force=True, silent=True) or {}
    source = body.get("source")
    if source is None:
        return jsonify({"error": "Missing 'source' field"}), 400
    _set_session_name(lab_id, body.get("session_name"))

    source, source_error = _normalize_video_source(source)
    if source_error:
        return jsonify({"error": source_error}), 400

    # ตรวจสอบก่อนว่าเปิดได้จริง — คืน error ทันทีถ้าไม่ได้
    test_cap = cv2.VideoCapture(source)
    if not test_cap.isOpened():
        test_cap.release()
        label = f"webcam {source}" if isinstance(source, int) else source
        return jsonify({"error": f"ไม่สามารถเปิดได้: {label}"}), 400
    test_cap.release()

    _start_capture(lab_id, cam_id, source)
    return jsonify({
        "ok": True,
        "lab_id": lab_id,
        "cam_id": cam_id,
        "session_name": _session_label(lab_id),
        "source": source,
        "source_type": _source_type(source),
    })


@app.route("/api/sources/<lab_id>/<int:cam_id>", methods=["DELETE"])
def delete_source(lab_id, cam_id):
    """ลบ video source ของรอบวิเคราะห์"""
    blocked = _require_local_source_access()
    if blocked:
        return blocked

    _stop_capture(lab_id, cam_id)
    return jsonify({"ok": True})


# ✅ โหลดข้อมูลเดิมเมื่อ server เริ่ม
load_stats()


# ✅ หน้าเว็บหลัก
@app.route("/")
def serve_dashboard():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    app.run(
        host=os.getenv("CLASSMOOD_HOST", "127.0.0.1"),
        port=_env_int("CLASSMOOD_PORT", 5000),
        debug=_env_flag("CLASSMOOD_DEBUG"),
        threaded=True,
    )
