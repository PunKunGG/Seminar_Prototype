import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app_config import (
    env_flag,
    env_float,
    env_int,
    load_config,
    load_env_file,
)


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

    def test_env_file_loads_values_without_overriding_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = os.path.join(temp_dir, ".env")
            with open(env_path, "w", encoding="utf-8") as env_file:
                env_file.write(
                    "# local settings\n"
                    "SUPABASE_URL=https://example.supabase.co\n"
                    "export SUPABASE_PUBLISHABLE_KEY='sb_publishable_file'\n"
                )

            environment = {"SUPABASE_URL": "https://override.supabase.co"}
            load_env_file(env_path, environment)

            self.assertEqual(
                environment["SUPABASE_URL"],
                "https://override.supabase.co",
            )
            self.assertEqual(
                environment["SUPABASE_PUBLISHABLE_KEY"],
                "sb_publishable_file",
            )

    def test_env_file_rejects_malformed_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = os.path.join(temp_dir, ".env")
            with open(env_path, "w", encoding="utf-8") as env_file:
                env_file.write("NOT VALID\n")

            with self.assertRaises(ValueError):
                load_env_file(env_path, {})


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
                "CLASSMOOD_CONTEXT_DETECTION_ENABLED": "false",
                "CLASSMOOD_CONTEXT_DETECTION_INTERVAL": "0.1",
                "CLASSMOOD_CONTEXT_DETECTION_CONFIDENCE": "9",
                "CLASSMOOD_CONTEXT_DETECTION_IMAGE_SIZE": "100",
                "CLASSMOOD_LONG_VIDEO_SAMPLE_INTERVAL_SECONDS": "30",
                "CLASSMOOD_LONG_VIDEO_SAMPLE_WINDOW_SECONDS": "45",
                "CLASSMOOD_LONG_VIDEO_SAMPLE_FPS": "20",
                "CLASSMOOD_EVIDENCE_ENABLED": "false",
                "CLASSMOOD_TRACK_POSITION_MEMORY_SECONDS": "10",
                "CLASSMOOD_TRACK_POSITION_MAX_DISTANCE": "9",
                "CLASSMOOD_TRACK_POSITION_ENABLED": "false",
                "CLASSMOOD_ALLOW_ANY_VIDEO_PATH": "true",
                "CLASSMOOD_PORT": "invalid",
            }

            config = load_config(temp_dir, environment)

            self.assertEqual(config.max_history, 30)
            self.assertEqual(config.annotated_stream_fps, 5)
            self.assertFalse(config.context_detection_enabled)
            self.assertEqual(config.context_detection_interval, 0.5)
            self.assertEqual(config.context_detection_confidence, 0.8)
            self.assertEqual(config.context_detection_image_size, 640)
            self.assertEqual(config.long_video_sample_interval_seconds, 30)
            self.assertEqual(config.long_video_sample_window_seconds, 30)
            self.assertEqual(config.long_video_sample_fps, 5.0)
            self.assertFalse(config.evidence_enabled)
            self.assertEqual(config.track_position_memory_seconds, 60.0)
            self.assertEqual(config.track_position_max_distance, 2.0)
            self.assertFalse(config.track_position_enabled)
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
            self.assertFalse(config.supabase_auth_enabled)
            self.assertFalse(config.session_cookie_secure)

    def test_supabase_auth_requires_a_complete_valid_pair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                load_config(temp_dir, {
                    "SUPABASE_URL": "https://example.supabase.co",
                })
            with self.assertRaises(ValueError):
                load_config(temp_dir, {
                    "SUPABASE_URL": "http://example.supabase.co",
                    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
                })
            with self.assertRaises(ValueError):
                load_config(temp_dir, {
                    "CLASSMOOD_REQUIRE_AUTH": "true",
                })

    def test_supabase_auth_settings_are_normalized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(temp_dir, {
                "SUPABASE_URL": "https://example.supabase.co/",
                "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
                "CLASSMOOD_SESSION_COOKIE_SECURE": "true",
            })

            self.assertTrue(config.supabase_auth_enabled)
            self.assertEqual(
                config.supabase_url,
                "https://example.supabase.co",
            )
            self.assertTrue(config.session_cookie_secure)


if __name__ == "__main__":
    unittest.main()
