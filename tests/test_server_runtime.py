import os
import sys
import threading
import unittest
from unittest.mock import patch

import numpy as np


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from server import (
    CONFIG,
    _analysis_methodology,
    _analyze_frame_with_context,
    _context_objects_for_frame,
    _store_buffer_frame,
)


class FrameBufferTests(unittest.TestCase):
    def make_buffer(self):
        return {
            "frame": None,
            "annotated_frame": "previous-analysis",
            "frame_token": 0,
            "context_objects": [],
            "context_marker": None,
            "position_seconds": 0,
            "lock": threading.Lock(),
        }

    def test_raw_frame_does_not_clear_latest_analysis_frame(self):
        buffer_state = self.make_buffer()

        _store_buffer_frame(buffer_state, "raw-frame")

        self.assertEqual(buffer_state["frame"], "raw-frame")
        self.assertEqual(
            buffer_state["annotated_frame"],
            "previous-analysis",
        )
        self.assertEqual(buffer_state["frame_token"], 1)

    def test_background_worker_records_stats_without_any_browser_request(self):
        import server

        key = ("background-worker-test", 1)
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        buffer_state = {**self.make_buffer(), "frame": frame, "frame_token": 1,
                        "running": True, "position_seconds": 35}
        analysis = {"behaviors": [], "annotated_frame": frame, "total_people": 1,
                    "attention_rate": 100, "summary": {"attentive": 1}}

        def record(*args, **kwargs):
            buffer_state["running"] = False

        with (
            patch.dict(server.frame_buffers, {key: buffer_state}),
            patch.dict(server.video_sources, {key: "source.mp4"}),
            patch.dict(server.source_states, {key: {"source_type": "video", "processing_mode": "realtime", "analysis_interval_seconds": 1}}),
            patch.dict(server.stats_last_recorded, clear=True),
            patch("server._analyze_frame_with_context", return_value=analysis),
            patch("server._apply_tracking", return_value=analysis),
            patch("server._draw_count_frame", return_value=frame),
            patch("server._set_cached") as cache,
            patch("server.record_stats", side_effect=record) as stats,
            patch("server.time.sleep"),
        ):
            server._realtime_analysis_loop(key)
        cache.assert_called_once_with(*key, analysis)
        stats.assert_called_once()
        self.assertEqual(stats.call_args.kwargs["observation_seconds"], 35)
        self.assertEqual(stats.call_args.kwargs["video_position_seconds"], 35)

    def test_sampled_frame_can_replace_analysis_frame(self):
        buffer_state = self.make_buffer()

        _store_buffer_frame(
            buffer_state,
            "raw-frame",
            annotated_frame="new-analysis",
            position_seconds=12.5,
        )

        self.assertEqual(buffer_state["annotated_frame"], "new-analysis")
        self.assertEqual(buffer_state["position_seconds"], 12.5)

    def test_context_detection_reuses_objects_inside_interval(self):
        buffer_state = self.make_buffer()
        detected = [{"class_id": 67, "confidence": 80, "bbox": [1, 2, 3, 4]}]

        with patch("server.detect_context_objects", return_value=detected) as detector:
            first = _context_objects_for_frame(buffer_state, "frame", marker=0)
            cached = _context_objects_for_frame(buffer_state, "frame", marker=1)
            refreshed = _context_objects_for_frame(buffer_state, "frame", marker=6)

        self.assertEqual(first, detected)
        self.assertEqual(cached, detected)
        self.assertEqual(refreshed, detected)
        self.assertEqual(detector.call_count, 2)

    def test_refined_phone_objects_are_kept_in_context_cache(self):
        buffer_state = self.make_buffer()
        initial = [{"class_id": 62, "confidence": 80, "bbox": [1, 2, 3, 4]}]
        refined = initial + [
            {
                "class_id": 67,
                "confidence": 72,
                "bbox": [10, 20, 30, 40],
                "source": "person_crop",
            }
        ]

        with (
            patch("server.detect_context_objects", return_value=initial),
            patch(
                "server.analyze_frame",
                return_value={"behaviors": [], "_context_objects": refined},
            ) as analyzer,
        ):
            result = _analyze_frame_with_context(
                buffer_state,
                "frame",
                marker=0,
            )
            cached = _context_objects_for_frame(
                buffer_state,
                "frame",
                marker=1,
            )

        self.assertEqual(result, {"behaviors": []})
        self.assertEqual(cached, refined)
        self.assertTrue(analyzer.call_args.kwargs["refine_phone_detection"])


class AnalysisMethodologyTests(unittest.TestCase):
    def test_methodology_exposes_active_criteria_and_overview_windows(self):
        methodology = _analysis_methodology()
        criteria = {
            item["behavior"]: item
            for item in methodology["criteria"]
        }

        self.assertEqual(len(criteria), 8)
        self.assertEqual(
            methodology["realtime_summary_interval_seconds"],
            CONFIG.realtime_stats_interval,
        )
        self.assertEqual(
            methodology["long_video_sampling"]["window_seconds"],
            CONFIG.long_video_sample_window_seconds,
        )
        self.assertEqual(
            criteria["sleeping"]["confirmation_seconds"],
            8.0,
        )
        self.assertIn(
            "ลืมตา/หลับตา",
            criteria["sleeping"]["limitation"],
        )


if __name__ == "__main__":
    unittest.main()
