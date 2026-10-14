from datetime import datetime
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from video_source_policy import VideoSourcePolicy, is_path_inside
from video_evidence import bind_video_source, open_bound_video


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

    def test_rejects_escaped_source_links_unless_unrestricted(self):
        with tempfile.TemporaryDirectory() as directory:
            allowed = os.path.join(directory, "allowed")
            os.makedirs(allowed)
            target = os.path.join(directory, "outside.mp4")
            with open(target, "wb") as output:
                output.write(b"video")
            alias = os.path.join(allowed, "link.mp4")
            open(alias, "wb").close()
            policy = self.make_policy(allowed)
            realpath = os.path.realpath
            with patch("video_source_policy.os.path.realpath", side_effect=lambda path: realpath(target if path == alias else path)):
                source, error = policy.normalize(alias)
                self.assertIsNone(source)
                self.assertIn("allowed directories", error)
                source, error = policy.normalize(alias, allow_any_path=True)
                self.assertIsNone(error)
                self.assertEqual(source, realpath(target))
                binding = bind_video_source(source)
                handle, reason = open_bound_video(binding, [allowed], allow_any_path=True)
                self.assertIsNone(reason)
                with handle:
                    self.assertEqual(handle.read(), b"video")

    def test_contained_source_links_use_canonical_path_for_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "source.mp4")
            with open(target, "wb") as output:
                output.write(b"video")
            alias = os.path.join(directory, "link.mp4")
            open(alias, "wb").close()
            policy = self.make_policy(directory)
            realpath = os.path.realpath
            with patch("video_source_policy.os.path.realpath", side_effect=lambda path: realpath(target if path == alias else path)):
                source, error = policy.normalize(alias)
                self.assertIsNone(error)
                self.assertEqual(source, realpath(target))
                binding = bind_video_source(source)
                self.assertEqual(binding["path"], source)
                handle, reason = open_bound_video(binding, [directory])
                self.assertIsNone(reason)
                with handle:
                    self.assertEqual(handle.read(), b"video")

    def test_configured_source_roots_are_resolved_like_evidence_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "source.mp4")
            open(target, "wb").close()
            root_alias = os.path.join(directory, "root-link")
            os.makedirs(root_alias)
            source_alias = os.path.join(root_alias, "source.mp4")
            open(source_alias, "wb").close()
            policy = self.make_policy(root_alias)
            realpath = os.path.realpath
            aliases = {root_alias: directory, source_alias: target}
            with patch("video_source_policy.os.path.realpath", side_effect=lambda path: realpath(aliases.get(path, path))):
                source, error = policy.normalize(source_alias)
                self.assertIsNone(error)
                self.assertEqual(source, realpath(target))
                handle, reason = open_bound_video(bind_video_source(source), [root_alias])
                self.assertIsNone(reason)
                handle.close()

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
