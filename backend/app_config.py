from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:5000,http://localhost:5000"
)
DEFAULT_VIDEO_EXTENSIONS = frozenset({
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".webm",
})


def env_flag(name, default=False, environ=None):
    environment = os.environ if environ is None else environ
    value = environment.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default, environ=None):
    environment = os.environ if environ is None else environ
    value = environment.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def env_float(name, default, environ=None):
    environment = os.environ if environ is None else environ
    value = environment.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def first_existing_path(*paths):
    return next(
        (path for path in paths if path and os.path.exists(path)),
        None,
    )


def _absolute_path(value):
    return os.path.abspath(os.path.expanduser(value))


@dataclass(frozen=True)
class AppConfig:
    base_dir: str
    project_root: str
    dashboard_dir: str
    allowed_origins: tuple
    data_dir: str
    stats_file: str
    session_database_file: str
    evidence_dir: str
    video_extensions: frozenset
    video_source_dirs: tuple
    video_upload_dir: str
    allow_remote_source_control: bool
    allow_any_video_path: bool
    max_history: int
    cache_ttl: float
    max_webcam_index: int
    max_video_upload_mb: int
    annotated_stream_fps: int
    long_video_threshold_seconds: int
    long_video_sample_interval_seconds: int
    long_video_sample_window_seconds: int
    long_video_sample_fps: float
    evidence_enabled: bool
    evidence_behaviors: frozenset
    max_evidence_per_track: int
    evidence_jpeg_quality: int
    evidence_max_dimension: int
    tracking_db_write_interval: float
    realtime_stats_interval: float
    track_max_missing_seconds: float
    host: str
    port: int
    debug: bool


def load_config(base_dir=None, environ=None):
    environment = os.environ if environ is None else environ
    resolved_base = _absolute_path(
        base_dir or os.path.dirname(os.path.abspath(__file__)),
    )
    project_root = _absolute_path(os.path.join(resolved_base, os.pardir))
    data_dir = os.path.join(resolved_base, "data")

    allowed_origins = tuple(
        origin.strip()
        for origin in environment.get(
            "CLASSMOOD_ALLOWED_ORIGINS",
            DEFAULT_ALLOWED_ORIGINS,
        ).split(",")
        if origin.strip()
    )
    source_dirs = tuple(
        _absolute_path(path.strip())
        for path in environment.get(
            "CLASSMOOD_VIDEO_DIRS",
            os.path.join(resolved_base, "video_sources"),
        ).split(os.pathsep)
        if path.strip()
    )
    if not source_dirs:
        source_dirs = (
            _absolute_path(os.path.join(resolved_base, "video_sources")),
        )

    sample_interval = max(
        10,
        env_int(
            "CLASSMOOD_LONG_VIDEO_SAMPLE_INTERVAL_SECONDS",
            60,
            environment,
        ),
    )
    sample_window = min(
        sample_interval,
        max(
            1,
            env_int(
                "CLASSMOOD_LONG_VIDEO_SAMPLE_WINDOW_SECONDS",
                10,
                environment,
            ),
        ),
    )

    return AppConfig(
        base_dir=resolved_base,
        project_root=project_root,
        dashboard_dir=os.path.join(project_root, "dashboard"),
        allowed_origins=allowed_origins,
        data_dir=data_dir,
        stats_file=os.path.join(data_dir, "stats.json"),
        session_database_file=environment.get(
            "CLASSMOOD_DATABASE_PATH",
            os.path.join(data_dir, "classmood.db"),
        ),
        evidence_dir=_absolute_path(environment.get(
            "CLASSMOOD_EVIDENCE_DIR",
            os.path.join(data_dir, "evidence"),
        )),
        video_extensions=DEFAULT_VIDEO_EXTENSIONS,
        video_source_dirs=source_dirs,
        video_upload_dir=source_dirs[0],
        allow_remote_source_control=env_flag(
            "CLASSMOOD_ALLOW_REMOTE_SOURCE_CONTROL",
            False,
            environment,
        ),
        allow_any_video_path=env_flag(
            "CLASSMOOD_ALLOW_ANY_VIDEO_PATH",
            False,
            environment,
        ),
        max_history=max(
            30,
            env_int("CLASSMOOD_MAX_HISTORY", 480, environment),
        ),
        cache_ttl=4.0,
        max_webcam_index=env_int(
            "CLASSMOOD_MAX_WEBCAM_INDEX",
            9,
            environment,
        ),
        max_video_upload_mb=max(
            1,
            env_int("CLASSMOOD_MAX_VIDEO_UPLOAD_MB", 512, environment),
        ),
        annotated_stream_fps=min(
            5,
            max(
                1,
                env_int(
                    "CLASSMOOD_ANNOTATED_STREAM_FPS",
                    5,
                    environment,
                ),
            ),
        ),
        long_video_threshold_seconds=max(
            60,
            env_int(
                "CLASSMOOD_LONG_VIDEO_THRESHOLD_SECONDS",
                30 * 60,
                environment,
            ),
        ),
        long_video_sample_interval_seconds=sample_interval,
        long_video_sample_window_seconds=sample_window,
        long_video_sample_fps=min(
            5.0,
            max(
                0.1,
                env_float(
                    "CLASSMOOD_LONG_VIDEO_SAMPLE_FPS",
                    2.0,
                    environment,
                ),
            ),
        ),
        evidence_enabled=env_flag(
            "CLASSMOOD_EVIDENCE_ENABLED",
            True,
            environment,
        ),
        evidence_behaviors=frozenset(
            value.strip()
            for value in environment.get(
                "CLASSMOOD_EVIDENCE_BEHAVIORS",
                "sleeping,looking_down,hand_raised,standing",
            ).split(",")
            if value.strip()
        ),
        max_evidence_per_track=max(
            1,
            env_int(
                "CLASSMOOD_MAX_EVIDENCE_PER_TRACK",
                50,
                environment,
            ),
        ),
        evidence_jpeg_quality=env_int(
            "CLASSMOOD_EVIDENCE_JPEG_QUALITY",
            86,
            environment,
        ),
        evidence_max_dimension=env_int(
            "CLASSMOOD_EVIDENCE_MAX_DIMENSION",
            900,
            environment,
        ),
        tracking_db_write_interval=max(
            0.5,
            env_float(
                "CLASSMOOD_TRACKING_DB_WRITE_INTERVAL",
                2.0,
                environment,
            ),
        ),
        realtime_stats_interval=max(
            1.0,
            env_float(
                "CLASSMOOD_REALTIME_STATS_INTERVAL",
                4.0,
                environment,
            ),
        ),
        track_max_missing_seconds=max(
            0.5,
            env_float(
                "CLASSMOOD_TRACK_MAX_MISSING_SECONDS",
                4.0,
                environment,
            ),
        ),
        host=environment.get("CLASSMOOD_HOST", "127.0.0.1"),
        port=env_int("CLASSMOOD_PORT", 5000, environment),
        debug=env_flag("CLASSMOOD_DEBUG", False, environment),
    )


CONFIG = load_config()
