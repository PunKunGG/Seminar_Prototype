from datetime import datetime
import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from video_source_policy import VideoSourcePolicy, is_path_inside


def simple_filename_sanitizer(value):
    return value.replace(" ", "_")


class VideoSourcePolicyTests(unittest.TestCase):
    def make_policy(self, directory, sanitizer=simple_filename_sanitizer):
        return VideoSourcePolicy(
            max_webcam_index=3,
            video_extensions={".mp4", ".webm"},
            source_directories=[directory],
            upload_directory=directory,
            filename_sanitizer=sanitizer,
        )

    def test_normalizes_webcam_and_rejects_unsafe_source_types(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            policy = self.make_policy(temp_dir)

            self.assertEqual(policy.normalize("2"), (2, None))
            self.assertIsNotNone(policy.normalize(True)[1])
            self.assertIsNotNone(policy.normalize(4)[1])
            self.assertIsNotNone(policy.normalize("https://example.com/a.mp4")[1])

    def test_limits_video_paths_to_configured_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            allowed_dir = os.path.join(temp_dir, "videos")
            sibling_dir = os.path.join(temp_dir, "videos-backup")
            os.makedirs(allowed_dir)
            os.makedirs(sibling_dir)
            allowed_video = os.path.join(allowed_dir, "class.mp4")
            outside_video = os.path.join(sibling_dir, "class.mp4")
            open(allowed_video, "wb").close()
            open(outside_video, "wb").close()
            policy = self.make_policy(allowed_dir)

            self.assertEqual(
                policy.normalize(allowed_video),
                (os.path.abspath(allowed_video), None),
            )
            self.assertIsNotNone(policy.normalize(outside_video)[1])
            self.assertEqual(
                policy.normalize(outside_video, allow_any_path=True),
                (os.path.abspath(outside_video), None),
            )
            self.assertFalse(is_path_inside(outside_video, [allowed_dir]))

    def test_builds_unique_upload_paths_inside_upload_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            policy = self.make_policy(temp_dir)
            timestamp = datetime(2026, 8, 2, 9, 30, 0)

            first, first_error = policy.build_upload_path(
                "../class demo.MP4",
                timestamp=timestamp,
            )
            self.assertIsNone(first_error)
            self.assertTrue(is_path_inside(first, [temp_dir]))
            self.assertTrue(first.endswith("class_demo_20260802_093000.mp4"))

            open(first, "wb").close()
            second, second_error = policy.build_upload_path(
                "class demo.mp4",
                timestamp=timestamp,
            )
            self.assertIsNone(second_error)
            self.assertTrue(second.endswith("class_demo_20260802_093000_1.mp4"))

    def test_rejects_a_filename_sanitizer_that_escapes_upload_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            policy = self.make_policy(
                temp_dir,
                sanitizer=lambda _value: os.path.join("..", "escape"),
            )

            path, error = policy.build_upload_path(
                "class.mp4",
                timestamp=datetime(2026, 8, 2, 9, 30, 0),
            )

            self.assertIsNone(path)
            self.assertEqual(error, "Invalid upload filename")


if __name__ == "__main__":
    unittest.main()
