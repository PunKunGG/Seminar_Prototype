import os
import sys
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from video_sampling import (
    aggregate_analyses,
    build_report_periods,
    format_video_time,
    iter_sample_windows,
    iter_sequential_decode_steps,
    summarize_report_history,
)


class VideoSamplingTests(unittest.TestCase):
    def test_builds_partial_final_window(self):
        windows = list(iter_sample_windows(125, 60, 10, 2))

        self.assertEqual([start for start, _ in windows], [0.0, 60.0, 120.0])
        self.assertEqual([len(samples) for _, samples in windows], [20, 20, 10])
        self.assertEqual(windows[-1][1][-1], 124.5)

    def test_aggregates_counts_and_weighted_attention(self):
        result = aggregate_analyses([
            {
                "total_people": 2,
                "summary": {"attentive": 1, "hand_raised": 1},
                "attention_rate": 100,
                "annotated_frame": "first",
            },
            {
                "total_people": 4,
                "summary": {"attentive": 1, "sleeping": 3},
                "attention_rate": 25,
                "annotated_frame": "last",
            },
        ])

        self.assertEqual(result["total_people"], 3)
        self.assertEqual(result["max_people"], 4)
        self.assertEqual(result["summary"]["attentive"], 1)
        self.assertEqual(result["summary"]["sleeping"], 2)
        self.assertEqual(result["peak_summary"]["sleeping"], 3)
        self.assertEqual(sum(result["summary"].values()), result["total_people"])
        self.assertEqual(result["attention_rate"], 50.0)
        self.assertEqual(result["annotated_frame"], "last")
        self.assertEqual(result["sampled_frames"], 2)

    def test_aggregate_never_returns_fractional_people(self):
        analyses = [
            {
                "total_people": 8,
                "summary": {"attentive": 8},
                "annotated_frame": None,
            }
            for _ in range(9)
        ]
        analyses.append({
            "total_people": 7,
            "summary": {"attentive": 6, "sleeping": 1},
            "annotated_frame": None,
        })

        result = aggregate_analyses(analyses)

        self.assertEqual(result["total_people"], 8)
        self.assertEqual(result["summary"]["attentive"], 8)
        self.assertEqual(result["summary"]["sleeping"], 0)
        self.assertEqual(sum(result["summary"].values()), 8)

    def test_builds_sequential_decode_steps_without_repeated_seeks(self):
        steps = list(iter_sequential_decode_steps([60, 60.5, 61, 61.5], 30))

        self.assertEqual(steps, [
            (60, 0),
            (60.5, 14),
            (61, 14),
            (61.5, 14),
        ])

    def test_decode_steps_avoid_fractional_fps_drift(self):
        steps = list(iter_sequential_decode_steps([0, 0.5, 1, 1.5], 25))

        self.assertEqual([grabs for _, grabs in steps], [0, 11, 12, 12])

    def test_builds_ten_minute_report_periods_for_sampled_history(self):
        history = []
        for minute in range(21):
            history.append({
                "video_position_seconds": minute * 60,
                "time": f"00:{minute:02d}:00",
                "attention_rate": 80 if minute < 10 else 40,
                "total_people": 8,
                "summary": {"attentive": 8 if minute < 10 else 4,
                            "looking_down": 0 if minute < 10 else 4},
            })
        history[0]["max_people"] = 11

        periods = build_report_periods(history)

        self.assertEqual(len(periods), 3)
        self.assertEqual(periods[0]["label"], "00:00:00 - 00:10:00")
        self.assertEqual(periods[0]["records"], 10)
        self.assertEqual(periods[0]["avg_attention_rate"], 80.0)
        self.assertEqual(periods[0]["max_people"], 11)
        self.assertEqual(periods[1]["avg_attention_rate"], 40.0)
        self.assertEqual(periods[2]["records"], 1)

    def test_report_periods_ignore_realtime_history(self):
        periods = build_report_periods([{
            "time": "12:00:00",
            "attention_rate": 75,
            "total_people": 4,
            "summary": {"attentive": 3, "unknown": 1},
        }])

        self.assertEqual(periods, [])

    def test_report_summary_uses_peak_people_instead_of_last_frame(self):
        history = [
            {
                "time": "09:00:05",
                "attention_rate": 72,
                "total_people": 7,
                "max_people": 11,
                "summary": {"attentive": 5, "standing": 1, "unknown": 1},
                "peak_summary": {
                    "attentive": 8,
                    "standing": 2,
                    "unknown": 1,
                },
            },
            {
                "time": "09:00:10",
                "attention_rate": 50,
                "total_people": 8,
                "summary": {"attentive": 4, "looking_down": 4},
            },
            {
                "time": "09:00:15",
                "attention_rate": 67,
                "total_people": 3,
                "summary": {"attentive": 2, "standing": 1},
            },
        ]

        result = summarize_report_history(history)

        self.assertEqual(result["report_total_people"], 11)
        self.assertEqual(result["max_people"], 11)
        self.assertEqual(result["report_summary"]["attentive"], 8)
        self.assertEqual(sum(result["report_summary"].values()), 11)
        self.assertEqual(result["report_summary_time"], "09:00:05")
        self.assertEqual(result["latest_total_people"], 3)
        self.assertEqual(result["latest_summary"]["attentive"], 2)
        self.assertEqual(result["report_attention_rate"], 63.0)

    def test_report_summary_handles_empty_history(self):
        result = summarize_report_history([])

        self.assertEqual(result["report_total_people"], 0)
        self.assertEqual(sum(result["report_summary"].values()), 0)
        self.assertIsNone(result["report_summary_time"])

    def test_formats_video_timeline(self):
        self.assertEqual(format_video_time(0), "00:00:00")
        self.assertEqual(format_video_time(3661), "01:01:01")


if __name__ == "__main__":
    unittest.main()
