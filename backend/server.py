from collections import deque
from datetime import datetime
import ipaddress
import json
import math
import os
import sys
import threading
import time
from urllib.parse import quote

import cv2
from flask import Flask, jsonify, send_from_directory, Response, request
from flask_cors import CORS
from ultralytics import YOLO
from werkzeug.utils import secure_filename

from app_config import CONFIG, first_existing_path
from behavior_analyzer import (
    analyze_frame,
    get_behavior_label_en,
    get_behavior_label_th,
)
from evidence_store import EvidenceStore
from person_tracking import BEHAVIOR_KEYS, SessionTracker
from session_database import SessionDatabase
from video_sampling import (
    aggregate_analyses,
    build_report_periods,
    format_video_time,
    iter_sample_windows,
    iter_sequential_decode_steps,
)
from video_source_policy import VideoSourcePolicy

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

app = Flask(__name__, static_folder=CONFIG.dashboard_dir)
CORS(app, resources={r"/api/*": {"origins": CONFIG.allowed_origins}})

# โหลดโมเดล YOLO สำหรับตรวจจับคน — ลอง yolov8s ก่อน fallback ไป nano
_detection_model_path = first_existing_path(
    os.path.join(CONFIG.base_dir, "yolov8s.pt"),
    os.path.join(CONFIG.project_root, "yolov8s.pt"),
    os.path.join(CONFIG.base_dir, "yolov8n.pt"),
    os.path.join(CONFIG.project_root, "yolov8n.pt"),
)
model = YOLO(_detection_model_path or "yolov8n.pt")
model.classes = [0]  # เฉพาะ class คน
detection_lock = threading.Lock()

# 📊 เก็บสถิติย้อนหลัง
stats_history = {}  # {lab_id: deque of stats}
activity_log = {}   # {lab_id: deque of activities}
session_names = {}  # {lab_id: display name from frontend}
state_lock = threading.RLock()

# 🔄 Inference cache — ป้องกัน double inference (behavior-frame + behavior ต่อ tick เดียวกัน)
analysis_cache = {}   # { (lab_id, cam_id): {"result": dict, "ts": float} }
analysis_locks = {}   # { (lab_id, cam_id): Lock }

# 🔔 Alerts — รายการแจ้งเตือนสำหรับ frontend
alerts_list = []
_alert_id_ctr = [0]  # ใช้ list เพื่อให้ nested function แก้ไขได้

# Runtime services and in-memory state
app.config["MAX_CONTENT_LENGTH"] = (
    CONFIG.max_video_upload_mb * 1024 * 1024
)
session_database = SessionDatabase(CONFIG.session_database_file)
evidence_store = EvidenceStore(
    CONFIG.evidence_dir,
    jpeg_quality=CONFIG.evidence_jpeg_quality,
    max_dimension=CONFIG.evidence_max_dimension,
)
video_source_policy = VideoSourcePolicy(
    max_webcam_index=CONFIG.max_webcam_index,
    video_extensions=CONFIG.video_extensions,
    source_directories=CONFIG.video_source_dirs,
    upload_directory=CONFIG.video_upload_dir,
    filename_sanitizer=secure_filename,
)
session_trackers = {}
tracking_last_persisted = {}
stats_last_recorded = {}
evidence_saved_keys = {}
evidence_event_counts = {}
EVIDENCE_BEHAVIORS = {
    value
    for value in CONFIG.evidence_behaviors
    if value in BEHAVIOR_KEYS
}


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify({
        "error": (
            "Video file is larger than "
            f"{CONFIG.max_video_upload_mb} MB"
        ),
    }), 413


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
    if CONFIG.allow_remote_source_control:
        return None
    if _is_loopback_request():
        return None
    return jsonify({"error": "Source management is limited to localhost"}), 403


def _normalize_video_source(source):
    return video_source_policy.normalize(
        source,
        allow_any_path=CONFIG.allow_any_video_path,
    )


def _build_upload_path(filename):
    return video_source_policy.build_upload_path(filename)


def _get_image_path(lab_id, cam_id):
    """หา path รูปภาพ รองรับ .png/.PNG"""
    for ext in (".png", ".PNG"):
        p = os.path.join(
            CONFIG.base_dir,
            "test_images",
            f"{lab_id}_{cam_id}{ext}",
        )
        if os.path.exists(p):
            return p
    return None


def _get_cached(lab_id, cam_id):
    with state_lock:
        entry = analysis_cache.get((lab_id, cam_id))
        source_state = source_states.get((lab_id, cam_id), {})
        is_sampled_video = source_state.get("processing_mode") == "sampled"
        if entry and (
            is_sampled_video
            or (time.time() - entry["ts"]) < CONFIG.cache_ttl
        ):
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


def _probe_source(cap, source):
    metadata = {
        "processing_mode": "realtime",
        "duration_seconds": None,
        "fps": None,
        "frame_count": None,
    }
    if not isinstance(source, str):
        return metadata

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if fps > 0 and frame_count > 0 else 0
    if not math.isfinite(duration) or duration <= 0:
        duration = None

    metadata.update({
        "duration_seconds": round(duration, 3) if duration is not None else None,
        "fps": round(fps, 3) if fps > 0 else None,
        "frame_count": frame_count if frame_count > 0 else None,
    })
    if (
        duration is not None
        and duration >= CONFIG.long_video_threshold_seconds
    ):
        metadata.update({
            "processing_mode": "sampled",
            "sample_interval_seconds": (
                CONFIG.long_video_sample_interval_seconds
            ),
            "sample_window_seconds": (
                CONFIG.long_video_sample_window_seconds
            ),
            "sample_fps": CONFIG.long_video_sample_fps,
            "total_windows": int(math.ceil(
                duration / CONFIG.long_video_sample_interval_seconds,
            )),
        })
    return metadata


def _capture_is_current(key, buf):
    return buf.get("running", False) and frame_buffers.get(key) is buf


def _store_buffer_frame(
    buf,
    frame,
    annotated_frame=None,
    position_seconds=None,
):
    with buf["lock"]:
        buf["frame"] = frame
        buf["annotated_frame"] = annotated_frame
        if position_seconds is not None:
            buf["position_seconds"] = max(0.0, float(position_seconds))
        buf["frame_token"] += 1
        buf["count_frame"] = None
        buf["count_token"] = -1


def _new_session_tracker(metadata):
    if metadata.get("processing_mode") == "sampled":
        sample_fps = max(0.1, float(metadata.get("sample_fps") or 2.0))
        sample_interval = max(
            10.0,
            float(metadata.get("sample_interval_seconds") or 60),
        )
        return SessionTracker(
            max_missing_seconds=sample_interval + 15,
            observation_step_seconds=1.0 / sample_fps,
            max_observation_gap_seconds=(1.0 / sample_fps) * 1.75,
        )
    return SessionTracker(
        max_missing_seconds=max(
            1.0,
            CONFIG.track_max_missing_seconds,
        ),
        observation_step_seconds=1.0 / CONFIG.annotated_stream_fps,
        max_observation_gap_seconds=max(
            1.0,
            3.0 / CONFIG.annotated_stream_fps,
        ),
    )


def _get_session_tracker(lab_id, cam_id):
    with state_lock:
        return session_trackers.get((lab_id, cam_id))


def _session_tracker_items(session_id):
    with state_lock:
        return [
            (cam_id, tracker)
            for (lab_id, cam_id), tracker in session_trackers.items()
            if lab_id == session_id and tracker is not None
        ]


def _draw_track_labels(frame, detections):
    if frame is None:
        return frame
    for detection in detections:
        bbox = detection.get("bbox")
        track_id = detection.get("track_id")
        if not bbox or track_id is None:
            continue
        x1, y1, _, _ = map(int, bbox)
        label = (
            f"ID {track_id} | "
            f"{get_behavior_label_en(detection.get('behavior', 'unknown'))}"
        )
        (text_width, text_height), _ = cv2.getTextSize(
            label,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            1,
        )
        label_y = max(text_height + 4, y1 - 6)
        cv2.rectangle(
            frame,
            (x1, label_y - text_height - 5),
            (x1 + text_width + 6, label_y + 3),
            (35, 35, 35),
            cv2.FILLED,
        )
        cv2.putText(
            frame,
            label,
            (x1 + 3, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
        )
    return frame


def _persist_tracking(lab_id, cam_id, force=False, full=False):
    key = (lab_id, cam_id)
    tracker = _get_session_tracker(lab_id, cam_id)
    if tracker is None:
        return

    now = time.monotonic()
    with state_lock:
        last_write = tracking_last_persisted.get(key, 0)
        if (
            not force
            and now - last_write < CONFIG.tracking_db_write_interval
        ):
            return
        tracking_last_persisted[key] = now

    try:
        session_database.sync_tracking(
            lab_id,
            tracker.persistence_snapshot(recent_only=not full),
        )
    except Exception as error:
        print(f"Tracking database write failed for {lab_id}/{cam_id}: {error}")


def _evidence_url(session_id, filename):
    return (
        f"/api/evidence/{quote(str(session_id), safe='')}/"
        f"{quote(str(filename), safe='')}"
    )


def _with_evidence_urls(session_id, report):
    for item in report.get("evidence", []):
        item["url"] = _evidence_url(session_id, item.get("filename", ""))
    return report


def _capture_evidence(lab_id, cam_id, frame, detections, timestamp):
    if not CONFIG.evidence_enabled or frame is None:
        return

    source_key = (lab_id, cam_id)
    with state_lock:
        saved_keys = evidence_saved_keys.setdefault(source_key, set())
        event_counts = evidence_event_counts.setdefault(source_key, {})

    pending = []
    for detection in detections:
        track_id = detection.get("track_id")
        event_index = detection.get("event_index")
        behavior = detection.get("behavior", "unknown")
        if track_id is None:
            continue

        candidates = []
        if detection.get("is_new_track"):
            candidates.append(("reference", "reference", None))
        if (
            detection.get("event_started")
            and behavior in EVIDENCE_BEHAVIORS
            and event_counts.get(track_id, 0)
            < CONFIG.max_evidence_per_track
        ):
            candidates.append((
                f"event:{event_index}",
                "event",
                event_index,
            ))

        for evidence_key, kind, evidence_event_index in candidates:
            unique_key = (int(track_id), evidence_key)
            if unique_key in saved_keys:
                continue
            try:
                result = evidence_store.save_crop(
                    session_id=lab_id,
                    track_id=track_id,
                    kind=kind,
                    event_index=evidence_event_index,
                    behavior=behavior,
                    captured_seconds=timestamp,
                    frame=frame,
                    bbox=detection.get("bbox"),
                )
            except Exception as error:
                print(
                    f"Evidence image write failed for "
                    f"{lab_id}/ID {track_id}: {error}",
                )
                continue
            if result is None:
                continue
            pending.append({
                "track_id": int(track_id),
                "evidence_key": evidence_key,
                "event_index": evidence_event_index,
                "kind": kind,
                "behavior": behavior,
                "captured_seconds": timestamp,
                **result,
            })

    if not pending:
        return

    _persist_tracking(lab_id, cam_id, force=True)
    for item in pending:
        try:
            session_database.add_evidence(lab_id, **item)
        except Exception as error:
            path = evidence_store.resolve_file(lab_id, item["filename"])
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            print(
                f"Evidence database write failed for "
                f"{lab_id}/ID {item['track_id']}: {error}",
            )
            continue

        unique_key = (item["track_id"], item["evidence_key"])
        with state_lock:
            evidence_saved_keys.setdefault(source_key, set()).add(unique_key)
            if item["kind"] == "event":
                counts = evidence_event_counts.setdefault(source_key, {})
                counts[item["track_id"]] = counts.get(item["track_id"], 0) + 1


def _finalize_tracking(lab_id, cam_id, timestamp=None):
    key = (lab_id, cam_id)
    tracker = _get_session_tracker(lab_id, cam_id)
    if tracker is None:
        return
    try:
        snapshot = tracker.finalize(timestamp)
        session_database.sync_tracking(lab_id, snapshot)
        session_database.finish_session(lab_id)
    except Exception as error:
        print(f"Tracking finalization failed for {lab_id}/{cam_id}: {error}")
    finally:
        with state_lock:
            tracking_last_persisted.pop(key, None)


def _apply_tracking(
    lab_id,
    cam_id,
    analysis,
    timestamp=None,
    original_frame=None,
):
    tracker = _get_session_tracker(lab_id, cam_id)
    if tracker is None:
        return analysis

    tracking = tracker.update(analysis.get("behaviors", []), timestamp)
    detections = tracking["detections"]
    summary = {key: 0 for key in BEHAVIOR_KEYS}
    for detection in detections:
        behavior = detection.get("behavior", "unknown")
        summary[behavior if behavior in summary else "unknown"] += 1

    total_people = len(detections)
    attentive_people = summary["attentive"] + summary["hand_raised"]
    analysis["behaviors"] = detections
    analysis["track_summaries"] = tracking["active_tracks"]
    analysis["tracking_timestamp_seconds"] = tracking["timestamp_seconds"]
    analysis["summary"] = summary
    analysis["total_people"] = total_people
    analysis["attention_rate"] = round(
        (attentive_people / total_people) * 100,
        1,
    ) if total_people else 0
    analysis["annotated_frame"] = _draw_track_labels(
        analysis.get("annotated_frame"),
        detections,
    )
    _capture_evidence(
        lab_id,
        cam_id,
        original_frame,
        detections,
        tracking["timestamp_seconds"],
    )
    _persist_tracking(lab_id, cam_id)
    return analysis


def _maybe_record_realtime_stats(lab_id, cam_id, analysis):
    key = (lab_id, cam_id)
    with state_lock:
        source_state = source_states.get(key, {})
        if source_state.get("processing_mode") == "sampled":
            return
        now = time.monotonic()
        if (
            now - stats_last_recorded.get(key, 0)
            < CONFIG.realtime_stats_interval
        ):
            return
        stats_last_recorded[key] = now
    record_stats(lab_id, analysis)


def _capture_sampled_video(key, buf, cap, metadata):
    lab_id, cam_id = key
    source_fps = float(metadata.get("fps") or cap.get(cv2.CAP_PROP_FPS) or 30)
    if not math.isfinite(source_fps) or source_fps <= 0:
        source_fps = 30
    windows = list(iter_sample_windows(
        metadata["duration_seconds"],
        metadata["sample_interval_seconds"],
        metadata["sample_window_seconds"],
        metadata["sample_fps"],
    ))
    total_samples = sum(len(sample_times) for _, sample_times in windows)
    processed_samples = 0

    for window_index, (window_start, sample_times) in enumerate(windows, start=1):
        if not _capture_is_current(key, buf):
            return

        window_analyses = []
        latest_analysis = None
        seek_ok = cap.set(cv2.CAP_PROP_POS_MSEC, window_start * 1000)
        if not seek_ok and window_start > 0:
            print(f"⚠️ ข้ามช่วงวิดีโอที่ seek ไม่สำเร็จ: {format_video_time(window_start)}")
            continue

        for sample_time, frames_to_grab in iter_sequential_decode_steps(
            sample_times,
            source_fps,
        ):
            if not _capture_is_current(key, buf):
                return

            grab_ok = True
            for _ in range(frames_to_grab):
                if not cap.grab():
                    grab_ok = False
                    break
            if not grab_ok:
                break

            ok, frame = cap.read()
            if not ok or frame is None:
                break

            analysis = _apply_tracking(
                lab_id,
                cam_id,
                analyze_frame(frame),
                sample_time,
                frame,
            )
            if not _capture_is_current(key, buf):
                return

            latest_analysis = analysis
            window_analyses.append({
                "total_people": analysis["total_people"],
                "summary": analysis["summary"],
                "annotated_frame": None,
            })
            processed_samples += 1
            _store_buffer_frame(
                buf,
                frame,
                analysis.get("annotated_frame"),
                sample_time,
            )
            _set_cached(lab_id, cam_id, analysis)
            _set_source_state(
                key,
                position_seconds=round(sample_time, 1),
                progress_percent=round(
                    (processed_samples / total_samples) * 100,
                    1,
                ) if total_samples else 100,
                processed_samples=processed_samples,
                total_samples=total_samples,
            )

        aggregate = aggregate_analyses(window_analyses)
        if aggregate is not None:
            aggregate["behaviors"] = (
                latest_analysis.get("behaviors", [])
                if latest_analysis
                else []
            )
            aggregate["track_summaries"] = (
                latest_analysis.get("track_summaries", [])
                if latest_analysis
                else []
            )
            aggregate["annotated_frame"] = _get_buffer_frame(
                lab_id,
                cam_id,
                "annotated_frame",
            )
            _set_cached(lab_id, cam_id, aggregate)
            record_stats(
                lab_id,
                aggregate,
                time_label=format_video_time(window_start),
                video_position_seconds=round(window_start, 1),
            )

        _set_source_state(
            key,
            processed_windows=window_index,
            total_windows=len(windows),
        )

    if not _capture_is_current(key, buf):
        return

    buf["running"] = False
    buf["ended"] = True
    _finalize_tracking(
        lab_id,
        cam_id,
        metadata["duration_seconds"],
    )
    _set_source_state(
        key,
        active=False,
        ended=True,
        error=None,
        progress_percent=100,
        position_seconds=metadata["duration_seconds"],
        ended_at=_now_str(),
    )


def _capture_loop(key, metadata):
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
    if metadata.get("processing_mode") == "sampled":
        try:
            _capture_sampled_video(key, buf, cap, metadata)
        except Exception as e:
            if frame_buffers.get(key) is buf:
                buf["running"] = False
                _set_source_state(
                    key,
                    active=False,
                    ended=False,
                    error=f"Long video analysis failed: {e}",
                    ended_at=_now_str(),
                )
            print(f"⚠️ วิเคราะห์คลิปยาวไม่สำเร็จ {key}: {e}")
        finally:
            cap.release()
        print(f"🛑 ปิดวิดีโอ {key}")
        return

    while buf["running"]:
        ok, frame = cap.read()
        if not ok:
            if is_file:
                buf["running"] = False
                buf["ended"] = True
                break
            else:
                time.sleep(0.05)
                continue
        if ok and frame is not None:
            position_seconds = (
                (cap.get(cv2.CAP_PROP_POS_MSEC) or 0) / 1000
                if is_file
                else None
            )
            _store_buffer_frame(
                buf,
                frame,
                position_seconds=position_seconds,
            )
        time.sleep(0.033)  # ~30 FPS max
    cap.release()
    if is_file and buf.get("ended"):
        _finalize_tracking(
            key[0],
            key[1],
            buf.get("position_seconds"),
        )
        _set_source_state(
            key,
            active=False,
            ended=True,
            error=None,
            ended_at=_now_str(),
        )
    print(f"🛑 ปิด {'วิดีโอ' if is_file else 'เว็บแคม'} {key}")


def _start_capture(lab_id, cam_id, source, metadata=None):
    """เริ่ม background thread สำหรับ (lab_id, cam_id)"""
    key = (lab_id, cam_id)
    _stop_capture(lab_id, cam_id)  # หยุด thread เก่าก่อน
    metadata = dict(metadata or {})
    video_sources[key] = source
    buf = {
        "frame": None,
        "annotated_frame": None,
        "count_frame": None,
        "frame_token": 0,
        "count_token": -1,
        "position_seconds": 0.0,
        "lock": threading.Lock(),
        "running": True,
        "thread": None,
        "ended": False,
    }
    frame_buffers[key] = buf
    with state_lock:
        session_trackers[key] = _new_session_tracker(metadata)
        tracking_last_persisted.pop(key, None)
        stats_last_recorded.pop(key, None)
        evidence_saved_keys[key] = set()
        evidence_event_counts[key] = {}
    state = _set_source_state(
        key,
        source=source,
        source_type=_source_type(source),
        active=True,
        ended=False,
        error=None,
        started_at=_now_str(),
        ended_at=None,
        progress_percent=0 if metadata.get("processing_mode") == "sampled" else None,
        position_seconds=0 if metadata.get("processing_mode") == "sampled" else None,
        processed_windows=0 if metadata.get("processing_mode") == "sampled" else None,
        **metadata,
    )
    t = threading.Thread(target=_capture_loop, args=(key, metadata), daemon=True)
    buf["thread"] = t
    t.start()
    return state


def _stop_capture(lab_id, cam_id):
    """หยุด background thread ของ (lab_id, cam_id)"""
    key = (lab_id, cam_id)
    if key in frame_buffers:
        frame_buffers[key]["running"] = False
        t = frame_buffers[key].get("thread")
        if t and t.is_alive():
            t.join(timeout=2.0)
        _finalize_tracking(
            lab_id,
            cam_id,
            frame_buffers[key].get("position_seconds"),
        )
        del frame_buffers[key]
    video_sources.pop(key, None)
    with state_lock:
        source_states.pop(key, None)
        analysis_cache.pop(key, None)
        analysis_locks.pop(key, None)
        session_trackers.pop(key, None)
        tracking_last_persisted.pop(key, None)
        stats_last_recorded.pop(key, None)
        evidence_saved_keys.pop(key, None)
        evidence_event_counts.pop(key, None)


def _get_buffer_frame(lab_id, cam_id, field="frame"):
    buf = frame_buffers.get((lab_id, cam_id))
    if buf:
        with buf["lock"]:
            f = buf.get(field)
        if f is not None:
            return f.copy()
    return None


def get_live_frame(lab_id, cam_id):
    """คืน frame ล่าสุดจาก buffer หรือ None ถ้าไม่มี live source"""
    return _get_buffer_frame(lab_id, cam_id, "frame")


def _source_observation_time(lab_id, cam_id):
    key = (lab_id, cam_id)
    source = video_sources.get(key)
    if not isinstance(source, str):
        return None
    buf = frame_buffers.get(key)
    if not buf:
        return None
    with buf["lock"]:
        return float(buf.get("position_seconds") or 0)


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

    with state_lock:
        source_state = source_states.get((lab_id, cam_id), {})
    if source_state.get("processing_mode") == "sampled":
        return {
            "total_people": 0,
            "behaviors": [],
            "summary": {
                "attentive": 0,
                "sleeping": 0,
                "looking_down": 0,
                "hand_raised": 0,
                "standing": 0,
                "unknown": 0,
            },
            "attention_rate": 0,
            "annotated_frame": None,
        }, False, None

    analysis_lock = _get_analysis_lock(lab_id, cam_id)
    with analysis_lock:
        analysis = _get_cached(lab_id, cam_id)
        if analysis is not None:
            return analysis, False, None

        if frame is None:
            frame, err = _read_frame(lab_id, cam_id)
            if err:
                return None, False, err

        analysis = _apply_tracking(
            lab_id,
            cam_id,
            analyze_frame(frame),
            _source_observation_time(lab_id, cam_id),
            frame,
        )
        _set_cached(lab_id, cam_id, analysis)
        _maybe_record_realtime_stats(lab_id, cam_id, analysis)
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


def _annotate_stream_frame(lab_id, cam_id, frame, mode):
    if mode == "behavior":
        analysis_lock = _get_analysis_lock(lab_id, cam_id)
        with analysis_lock:
            analysis = _apply_tracking(
                lab_id,
                cam_id,
                analyze_frame(frame),
                _source_observation_time(lab_id, cam_id),
                frame,
            )
            _set_cached(lab_id, cam_id, analysis)
            _maybe_record_realtime_stats(lab_id, cam_id, analysis)
        annotated_frame = analysis.get("annotated_frame")
        return annotated_frame if annotated_frame is not None else frame
    return _annotate_count_frame(frame)


def _sampled_stream_frame(lab_id, cam_id, frame, mode):
    key = (lab_id, cam_id)
    buf = frame_buffers.get(key)
    if not buf:
        return frame

    if mode == "behavior":
        annotated_frame = _get_buffer_frame(lab_id, cam_id, "annotated_frame")
        return annotated_frame if annotated_frame is not None else frame

    with buf["lock"]:
        frame_token = buf["frame_token"]
        cached_count_frame = buf.get("count_frame")
        count_token = buf.get("count_token")
    if cached_count_frame is not None and count_token == frame_token:
        return cached_count_frame.copy()

    annotated_frame = _annotate_count_frame(frame)
    with buf["lock"]:
        if buf["frame_token"] == frame_token:
            buf["count_frame"] = annotated_frame
            buf["count_token"] = frame_token
    return annotated_frame


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
    os.makedirs(CONFIG.data_dir, exist_ok=True)
    try:
        with state_lock:
            payload = {
                "stats_history": {k: list(v) for k, v in stats_history.items()},
                "activity_log":  {k: list(v) for k, v in activity_log.items()},
                "session_names": dict(session_names),
            }
            with open(CONFIG.stats_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ บันทึกข้อมูลล้มเหลว: {e}")


def load_stats():
    """โหลดข้อมูลเดิมจาก disk เมื่อ server เริ่ม"""
    if not os.path.exists(CONFIG.stats_file):
        return
    try:
        with open(CONFIG.stats_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        with state_lock:
            for lab_id, items in data.get("stats_history", {}).items():
                stats_history[lab_id] = deque(
                    items,
                    maxlen=CONFIG.max_history,
                )
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
    with state_lock:
        source_state = source_states.get((lab_id, cam_id), {})
    if source_state.get("processing_mode") == "sampled":
        analysis = _get_cached(lab_id, cam_id)
        people_count = round(analysis["total_people"]) if analysis else 0
        return jsonify({
            "lab_id": lab_id,
            "camera_id": cam_id,
            "num_people": people_count,
            "avg_confidence": 0,
            "detected_objects": people_count,
            "processing_mode": "sampled",
        })

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
        "tracks": analysis.get("track_summaries", []),
        "behaviors": [
            {
                "behavior": b["behavior"],
                "behavior_th": get_behavior_label_th(b["behavior"]),
                "raw_behavior": b.get("raw_behavior", b["behavior"]),
                "confidence": b["confidence"],
                "track_id": b.get("track_id"),
                "bbox": b.get("bbox"),
                "track_attention_rate": b.get("track_attention_rate", 0),
            } for b in analysis.get("behaviors", [])
        ]
    })


@app.route("/api/sessions/<session_id>/tracks")
def get_session_tracks(session_id):
    try:
        period_seconds = int(request.args.get("period_seconds", 3600))
    except ValueError:
        period_seconds = 3600
    for cam_id, _tracker in _session_tracker_items(session_id):
        _persist_tracking(session_id, cam_id, force=True)
    return jsonify(
        _with_evidence_urls(
            session_id,
            session_database.tracking_report(
                session_id,
                period_seconds=period_seconds,
            ),
        ),
    )


@app.route("/api/evidence/<session_id>/<path:filename>")
def get_evidence_image(session_id, filename):
    blocked = _require_local_source_access()
    if blocked:
        return blocked

    path = evidence_store.resolve_file(session_id, filename)
    if path is None or not os.path.isfile(path):
        return jsonify({"error": "Evidence image not found"}), 404
    return send_from_directory(
        evidence_store.session_directory(session_id),
        filename,
        mimetype="image/jpeg",
        conditional=True,
        max_age=0,
    )


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
def record_stats(lab_id, analysis, time_label=None, video_position_seconds=None):
    now = datetime.now()
    time_str = time_label or now.strftime("%H:%M:%S")

    summary      = analysis["summary"]
    sleeping     = summary.get("sleeping", 0)
    looking_down = summary.get("looking_down", 0)

    with state_lock:
        session_label = _session_label(lab_id)
        if lab_id not in stats_history:
            stats_history[lab_id] = deque(maxlen=CONFIG.max_history)
        if lab_id not in activity_log:
            activity_log[lab_id] = deque(maxlen=20)

        history_item = {
            "time": time_str,
            "attention_rate": analysis["attention_rate"],
            "total_people": analysis["total_people"],
            "summary": analysis["summary"],
        }
        if video_position_seconds is not None:
            history_item.update({
                "video_position_seconds": video_position_seconds,
                "sampled_frames": analysis.get("sampled_frames", 0),
            })
        stats_history[lab_id].append(history_item)

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
    overall = aggregate_analyses(history)
    periods = build_report_periods(history)
    for cam_id, _tracker in _session_tracker_items(lab_id):
        _persist_tracking(lab_id, cam_id, force=True)
    tracking_report = _with_evidence_urls(
        lab_id,
        session_database.tracking_report(
            lab_id,
            period_seconds=3600,
        ),
    )

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
            },
            "overall_summary": overall["summary"] if overall else {
                "attentive": 0, "sleeping": 0, "looking_down": 0,
                "hand_raised": 0, "standing": 0, "unknown": 0
            },
        },
        "period_seconds": 600 if periods else None,
        "periods": periods,
        "tracking": tracking_report,
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
    delay = 1 / CONFIG.annotated_stream_fps
    mode = "behavior" if mode == "behavior" else "count"

    while True:
        buf_state = frame_buffers.get((lab_id, cam_id))
        if not buf_state:
            break

        frame = get_live_frame(lab_id, cam_id)
        if frame is None:
            time.sleep(0.05)
            with state_lock:
                source_state = source_states.get((lab_id, cam_id), {})
            waiting_for_sample = (
                source_state.get("processing_mode") == "sampled"
                and source_state.get("active", False)
            )
            idle = 0 if waiting_for_sample else idle + 1
            if idle > 100:
                print(f"⏱️ annotated stream หมดเวลารอ frame: {lab_id}/{cam_id}")
                break
            continue

        idle = 0
        try:
            with state_lock:
                source_state = source_states.get((lab_id, cam_id), {})
            if source_state.get("processing_mode") == "sampled":
                annotated_frame = _sampled_stream_frame(lab_id, cam_id, frame, mode)
            else:
                annotated_frame = _annotate_stream_frame(
                    lab_id,
                    cam_id,
                    frame,
                    mode,
                )
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

    os.makedirs(CONFIG.video_upload_dir, exist_ok=True)
    try:
        video_file.save(target_path)
    except Exception as e:
        return jsonify({"error": f"Unable to save video: {e}"}), 500

    return jsonify({
        "ok": True,
        "filename": os.path.basename(target_path),
        "source": target_path,
        "max_upload_mb": CONFIG.max_video_upload_mb,
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
    metadata = _probe_source(test_cap, source)
    test_cap.release()

    _stop_capture(lab_id, cam_id)
    try:
        evidence_store.clear_session(lab_id)
        session_database.upsert_session(
            lab_id,
            name=_session_label(lab_id),
            room_name=body.get("room_name"),
            course_name=body.get("course_name"),
            source_type=_source_type(source),
            source_label=(
                os.path.basename(source)
                if isinstance(source, str)
                else f"Webcam {source}"
            ),
            recording_started_at=body.get("recording_start"),
            reset_tracking=True,
        )
    except Exception as error:
        return jsonify({
            "error": f"Unable to create analysis session: {error}",
        }), 500

    source_state = _start_capture(lab_id, cam_id, source, metadata)
    payload = {
        "ok": True,
        "lab_id": lab_id,
        "cam_id": cam_id,
        "session_name": _session_label(lab_id),
        "source": source,
        "source_type": _source_type(source),
    }
    payload.update({
        key: source_state.get(key)
        for key in (
            "processing_mode",
            "duration_seconds",
            "sample_interval_seconds",
            "sample_window_seconds",
            "sample_fps",
            "total_windows",
        )
        if source_state.get(key) is not None
    })
    return jsonify(payload)


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
        host=CONFIG.host,
        port=CONFIG.port,
        debug=CONFIG.debug,
        threaded=True,
    )
