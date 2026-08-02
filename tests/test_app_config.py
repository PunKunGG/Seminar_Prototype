import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app_config import env_flag, env_float, env_int, load_config


class EnvironmentParserTests(unittest.TestCase):
    def test_parsers_use_defaults_for_missing_or_invalid_values(self):
        environment = {
            "ENABLED": "yes",
            "DISABLED": "off",
            "INTEGER": "invalid",
            "FLOAT": "1.25",
        }

        self.assertTrue(env_flag("ENABLED", environ=environment))
        self.assertFalse(env_flag("DISABLED", True, environment))
        self.assertEqual(env_int("INTEGER", 7, environment), 7)
        self.assertEqual(env_float("FLOAT", 0, environment), 1.25)
        self.assertEqual(env_int("MISSING", 9, environment), 9)


class AppConfigTests(unittest.TestCase):
    def test_load_config_normalizes_paths_and_clamps_limits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_source = os.path.join(temp_dir, "videos-a")
            second_source = os.path.join(temp_dir, "videos-b")
            environment = {
                "CLASSMOOD_VIDEO_DIRS": os.pathsep.join([
                    first_source,
                    second_source,
                ]),
                "CLASSMOOD_MAX_HISTORY": "2",
                "CLASSMOOD_ANNOTATED_STREAM_FPS": "99",
                "CLASSMOOD_LONG_VIDEO_SAMPLE_INTERVAL_SECONDS": "30",
                "CLASSMOOD_LONG_VIDEO_SAMPLE_WINDOW_SECONDS": "45",
                "CLASSMOOD_LONG_VIDEO_SAMPLE_FPS": "20",
                "CLASSMOOD_EVIDENCE_ENABLED": "false",
                "CLASSMOOD_ALLOW_ANY_VIDEO_PATH": "true",
                "CLASSMOOD_PORT": "invalid",
            }

            config = load_config(temp_dir, environment)

            self.assertEqual(config.max_history, 30)
            self.assertEqual(config.annotated_stream_fps, 5)
            self.assertEqual(config.long_video_sample_interval_seconds, 30)
            self.assertEqual(config.long_video_sample_window_seconds, 30)
            self.assertEqual(config.long_video_sample_fps, 5.0)
            self.assertFalse(config.evidence_enabled)
            self.assertTrue(config.allow_any_video_path)
            self.assertFalse(config.allow_remote_source_control)
            self.assertEqual(config.port, 5000)
            self.assertEqual(
                config.video_source_dirs,
                (
                    os.path.abspath(first_source),
                    os.path.abspath(second_source),
                ),
            )
            self.assertEqual(
                config.video_upload_dir,
                os.path.abspath(first_source),
            )


if __name__ == "__main__":
    unittest.main()
