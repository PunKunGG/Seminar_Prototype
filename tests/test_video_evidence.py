import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from video_evidence import bind_video_source, open_bound_video


class VideoEvidenceTests(unittest.TestCase):
    def test_binding_survives_reload_but_rejects_changed_or_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "source.mp4")
            with open(path, "wb") as output:
                output.write(b"original-video")
            binding = bind_video_source(path)
            handle, reason = open_bound_video(binding, [directory])
            self.assertIsNone(reason)
            with handle:
                self.assertEqual(handle.read(), b"original-video")
            with open(path, "wb") as output:
                output.write(b"replaced-video-is-different")
            self.assertEqual(open_bound_video(binding, [directory]), (None, "changed"))
            os.remove(path)
            self.assertEqual(open_bound_video(binding, [directory]), (None, "missing"))

    def test_binding_never_allows_paths_outside_roots_or_relative_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "source.mp4")
            with open(path, "wb") as output:
                output.write(b"video")
            binding = bind_video_source(path)
            self.assertEqual(open_bound_video(binding, [os.path.join(directory, "other")]), (None, "invalid_source"))
            self.assertEqual(open_bound_video({**binding, "path": "../source.mp4"}, [directory]), (None, "invalid_source"))
            self.assertEqual(open_bound_video(None, [directory]), (None, "unbound"))
