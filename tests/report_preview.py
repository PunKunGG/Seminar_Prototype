"""Local-only report fixture server, with isolated data and no cloud writes."""

import argparse
import os
import sys
import tempfile
from dataclasses import replace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--port", type=int, default=5001)
    arguments = parser.parse_args()
    import app_config

    with tempfile.TemporaryDirectory(prefix="classmood-report-preview-") as directory:
        app_config.CONFIG = replace(app_config.CONFIG, supabase_auth_enabled=False,
                                    supabase_server_key="", data_dir=directory,
                                    stats_file=os.path.join(directory, "stats.json"),
                                    session_database_file=os.path.join(directory, "sessions.db"),
                                    evidence_dir=os.path.join(directory, "evidence"))
        import cv2
        import server
        from behavior_analyzer import analyze_frame
        from person_tracking import BEHAVIOR_KEYS
        from report_qualification import REPORT_POLICY

        frame = cv2.imread(arguments.image)
        if frame is None:
            raise ValueError("Cannot read fixture image")
        analysis = analyze_frame(frame)
        if not analysis["behaviors"]:
            raise ValueError("No pose detected in fixture image")
        geometry = analysis["behaviors"][0]
        for session_id, policy in (("preview-new", REPORT_POLICY), ("preview-legacy", None)):
            server.session_database.upsert_session(
                session_id, name="Report preview " + session_id, room_name="Lab 9226", course_name="AI",
                source_type="video", source_label="fixture.mp4",
                recording_started_at="2026-10-09T09:00:00+07:00", report_policy=policy,
            )
            tracks = []
            for track_id in range(1, 25):
                behavior = BEHAVIOR_KEYS[(track_id - 1) % len(BEHAVIOR_KEYS)]
                seconds = 1 if track_id == 24 else 60
                durations = {key: seconds if key == behavior else 0 for key in BEHAVIOR_KEYS}
                counts = {key: 1 if key == behavior else 0 for key in BEHAVIOR_KEYS}
                tracks.append({
                    "track_id": track_id, "first_seen_seconds": 285, "last_seen_seconds": 285 + seconds,
                    "visible_seconds": seconds, "attention_rate": 100 if behavior in ("attentive", "hand_raised") else 0,
                    "current_behavior": behavior, "behavior_seconds": durations, "event_counts": counts, "active": False,
                    "events": [{"event_index": 1, "behavior": behavior, "start_seconds": 285,
                                "end_seconds": 285 + seconds, "duration_seconds": seconds,
                                "avg_confidence": 90, "observed_segments": [[285, 285 + seconds, seconds]]}],
                    "buckets": [{"bucket_start_seconds": 240, "visible_seconds": seconds,
                                 "behavior_seconds": durations, "event_counts": counts}],
                })
            server.session_database.sync_tracking(session_id, tracks)
            detections = [{**geometry, "track_id": item["track_id"], "behavior": item["current_behavior"],
                           "is_new_track": True, "event_started": False} for item in tracks[:23]]
            if policy is None:
                for detection in detections:
                    detection.pop("portrait_bbox", None)
            server._capture_evidence(session_id, 1, frame, detections, 285)
            server.session_database.finish_session(session_id, duration_seconds=600)
            server.stats_history[session_id] = [
                {"time": "09:04", "total_people": 24, "attention_rate": 75, "observation_seconds": 285, "summary": {"attentive": 24}},
                {"time": "09:05", "total_people": 23, "attention_rate": 70, "observation_seconds": 345, "summary": {"sleeping": 23}},
            ]
        print("Fixture data: " + directory, flush=True)
        server.app.run(host="127.0.0.1", port=arguments.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
