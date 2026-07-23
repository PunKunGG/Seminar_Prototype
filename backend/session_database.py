from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta

from person_tracking import ATTENTIVE_BEHAVIORS, BEHAVIOR_KEYS


def _utc_now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clean_text(value, fallback="", max_length=120):
    text = str(value or "").strip()
    return (text or fallback)[:max_length]


def _parse_recording_start(value):
    text = _clean_text(value, max_length=40)
    if not text:
        return datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now().astimezone().isoformat(timespec="seconds")
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.isoformat(timespec="seconds")


class SessionDatabase:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self._write_lock = threading.RLock()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        with self._write_lock, self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS rooms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS class_sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    room_id INTEGER,
                    course_id INTEGER,
                    source_type TEXT,
                    source_label TEXT,
                    recording_started_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    FOREIGN KEY (room_id) REFERENCES rooms(id),
                    FOREIGN KEY (course_id) REFERENCES courses(id)
                );

                CREATE TABLE IF NOT EXISTS session_tracks (
                    session_id TEXT NOT NULL,
                    track_id INTEGER NOT NULL,
                    first_seen_seconds REAL NOT NULL,
                    last_seen_seconds REAL NOT NULL,
                    visible_seconds REAL NOT NULL,
                    attention_rate REAL NOT NULL,
                    current_behavior TEXT NOT NULL,
                    behavior_seconds_json TEXT NOT NULL,
                    event_counts_json TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    PRIMARY KEY (session_id, track_id),
                    FOREIGN KEY (session_id)
                        REFERENCES class_sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS behavior_events (
                    session_id TEXT NOT NULL,
                    track_id INTEGER NOT NULL,
                    event_index INTEGER NOT NULL,
                    behavior TEXT NOT NULL,
                    start_seconds REAL NOT NULL,
                    end_seconds REAL NOT NULL,
                    duration_seconds REAL NOT NULL,
                    avg_confidence REAL NOT NULL,
                    PRIMARY KEY (session_id, track_id, event_index),
                    FOREIGN KEY (session_id, track_id)
                        REFERENCES session_tracks(session_id, track_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS evidence_images (
                    session_id TEXT NOT NULL,
                    track_id INTEGER NOT NULL,
                    evidence_key TEXT NOT NULL,
                    event_index INTEGER,
                    kind TEXT NOT NULL,
                    behavior TEXT NOT NULL,
                    captured_seconds REAL NOT NULL,
                    filename TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    file_size INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, track_id, evidence_key),
                    FOREIGN KEY (session_id, track_id)
                        REFERENCES session_tracks(session_id, track_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS track_time_buckets (
                    session_id TEXT NOT NULL,
                    track_id INTEGER NOT NULL,
                    bucket_start_seconds REAL NOT NULL,
                    visible_seconds REAL NOT NULL,
                    behavior_seconds_json TEXT NOT NULL,
                    event_counts_json TEXT NOT NULL,
                    PRIMARY KEY (
                        session_id,
                        track_id,
                        bucket_start_seconds
                    ),
                    FOREIGN KEY (session_id, track_id)
                        REFERENCES session_tracks(session_id, track_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_room_course
                    ON class_sessions(room_id, course_id);
                CREATE INDEX IF NOT EXISTS idx_events_session_time
                    ON behavior_events(session_id, start_seconds);
                CREATE INDEX IF NOT EXISTS idx_evidence_session_time
                    ON evidence_images(session_id, captured_seconds);
                CREATE INDEX IF NOT EXISTS idx_buckets_session_time
                    ON track_time_buckets(session_id, bucket_start_seconds);
                """
            )

    def _catalog_id(self, connection, table, name):
        clean_name = _clean_text(name, "ไม่ระบุ", 100)
        connection.execute(
            f"INSERT OR IGNORE INTO {table}(name) VALUES (?)",
            (clean_name,),
        )
        row = connection.execute(
            f"SELECT id FROM {table} WHERE name = ?",
            (clean_name,),
        ).fetchone()
        return int(row["id"])

    def upsert_session(
        self,
        session_id,
        *,
        name,
        room_name,
        course_name,
        source_type,
        source_label,
        recording_started_at=None,
        reset_tracking=False,
    ):
        session_id = _clean_text(session_id, max_length=160)
        if not session_id:
            raise ValueError("session_id is required")
        with self._write_lock, self._connection() as connection:
            room_id = self._catalog_id(connection, "rooms", room_name)
            course_id = self._catalog_id(connection, "courses", course_name)
            connection.execute(
                """
                INSERT INTO class_sessions(
                    id, name, room_id, course_id, source_type, source_label,
                    recording_started_at, created_at, ended_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'active')
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    room_id = excluded.room_id,
                    course_id = excluded.course_id,
                    source_type = excluded.source_type,
                    source_label = excluded.source_label,
                    recording_started_at = excluded.recording_started_at,
                    ended_at = NULL,
                    status = 'active'
                """,
                (
                    session_id,
                    _clean_text(name, session_id, 120),
                    room_id,
                    course_id,
                    _clean_text(source_type, max_length=20),
                    _clean_text(source_label, max_length=260),
                    _parse_recording_start(recording_started_at),
                    _utc_now(),
                ),
            )
            if reset_tracking:
                connection.execute(
                    "DELETE FROM session_tracks WHERE session_id = ?",
                    (session_id,),
                )

    def sync_tracking(self, session_id, tracks):
        if not tracks:
            return
        with self._write_lock, self._connection() as connection:
            for track in tracks:
                track_id = int(track["track_id"])
                connection.execute(
                    """
                    INSERT INTO session_tracks(
                        session_id, track_id, first_seen_seconds,
                        last_seen_seconds, visible_seconds, attention_rate,
                        current_behavior, behavior_seconds_json,
                        event_counts_json, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id, track_id) DO UPDATE SET
                        first_seen_seconds = excluded.first_seen_seconds,
                        last_seen_seconds = excluded.last_seen_seconds,
                        visible_seconds = excluded.visible_seconds,
                        attention_rate = excluded.attention_rate,
                        current_behavior = excluded.current_behavior,
                        behavior_seconds_json = excluded.behavior_seconds_json,
                        event_counts_json = excluded.event_counts_json,
                        active = excluded.active
                    """,
                    (
                        session_id,
                        track_id,
                        track["first_seen_seconds"],
                        track["last_seen_seconds"],
                        track["visible_seconds"],
                        track["attention_rate"],
                        track["current_behavior"],
                        json.dumps(track["behavior_seconds"]),
                        json.dumps(track["event_counts"]),
                        1 if track.get("active") else 0,
                    ),
                )
                for event in track.get("events", []):
                    connection.execute(
                        """
                        INSERT INTO behavior_events(
                            session_id, track_id, event_index, behavior,
                            start_seconds, end_seconds, duration_seconds,
                            avg_confidence
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(session_id, track_id, event_index)
                        DO UPDATE SET
                            behavior = excluded.behavior,
                            start_seconds = excluded.start_seconds,
                            end_seconds = excluded.end_seconds,
                            duration_seconds = excluded.duration_seconds,
                            avg_confidence = excluded.avg_confidence
                        """,
                        (
                            session_id,
                            track_id,
                            event["event_index"],
                            event["behavior"],
                            event["start_seconds"],
                            event["end_seconds"],
                            event["duration_seconds"],
                            event["avg_confidence"],
                        ),
                    )
                for bucket in track.get("buckets", []):
                    connection.execute(
                        """
                        INSERT INTO track_time_buckets(
                            session_id, track_id, bucket_start_seconds,
                            visible_seconds, behavior_seconds_json,
                            event_counts_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(
                            session_id, track_id, bucket_start_seconds
                        ) DO UPDATE SET
                            visible_seconds = excluded.visible_seconds,
                            behavior_seconds_json =
                                excluded.behavior_seconds_json,
                            event_counts_json = excluded.event_counts_json
                        """,
                        (
                            session_id,
                            track_id,
                            bucket["bucket_start_seconds"],
                            bucket["visible_seconds"],
                            json.dumps(bucket["behavior_seconds"]),
                            json.dumps(bucket["event_counts"]),
                        ),
                    )

    def add_evidence(
        self,
        session_id,
        *,
        track_id,
        evidence_key,
        event_index,
        kind,
        behavior,
        captured_seconds,
        filename,
        width,
        height,
        file_size,
    ):
        with self._write_lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO evidence_images(
                    session_id, track_id, evidence_key, event_index, kind,
                    behavior, captured_seconds, filename, width, height,
                    file_size, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, track_id, evidence_key)
                DO UPDATE SET
                    event_index = excluded.event_index,
                    kind = excluded.kind,
                    behavior = excluded.behavior,
                    captured_seconds = excluded.captured_seconds,
                    filename = excluded.filename,
                    width = excluded.width,
                    height = excluded.height,
                    file_size = excluded.file_size
                """,
                (
                    session_id,
                    int(track_id),
                    _clean_text(evidence_key, max_length=80),
                    int(event_index) if event_index is not None else None,
                    _clean_text(kind, max_length=20),
                    _clean_text(behavior, "unknown", 40),
                    max(0.0, float(captured_seconds or 0)),
                    os.path.basename(str(filename or "")),
                    max(1, int(width)),
                    max(1, int(height)),
                    max(0, int(file_size)),
                    _utc_now(),
                ),
            )

    def finish_session(self, session_id):
        with self._write_lock, self._connection() as connection:
            connection.execute(
                """
                UPDATE class_sessions
                SET status = 'completed', ended_at = ?
                WHERE id = ?
                """,
                (_utc_now(), session_id),
            )

    def _session_metadata(self, connection, session_id):
        row = connection.execute(
            """
            SELECT
                sessions.id,
                sessions.name,
                rooms.name AS room_name,
                courses.name AS course_name,
                sessions.source_type,
                sessions.source_label,
                sessions.recording_started_at,
                sessions.created_at,
                sessions.ended_at,
                sessions.status
            FROM class_sessions AS sessions
            LEFT JOIN rooms ON rooms.id = sessions.room_id
            LEFT JOIN courses ON courses.id = sessions.course_id
            WHERE sessions.id = ?
            """,
            (session_id,),
        ).fetchone()
        return dict(row) if row else None

    def _empty_totals(self):
        return {
            "visible_seconds": 0.0,
            "behavior_seconds": {key: 0.0 for key in BEHAVIOR_KEYS},
            "event_counts": {key: 0 for key in BEHAVIOR_KEYS},
        }

    def _add_bucket(self, totals, row):
        totals["visible_seconds"] += float(row["visible_seconds"] or 0)
        behavior_seconds = json.loads(row["behavior_seconds_json"])
        event_counts = json.loads(row["event_counts_json"])
        for key in BEHAVIOR_KEYS:
            totals["behavior_seconds"][key] += float(
                behavior_seconds.get(key, 0),
            )
            totals["event_counts"][key] += int(event_counts.get(key, 0))

    def _summary(self, track_id, totals, current_behavior=None):
        visible = totals["visible_seconds"]
        attentive = sum(
            totals["behavior_seconds"][key]
            for key in ATTENTIVE_BEHAVIORS
        )
        return {
            "track_id": int(track_id),
            "current_behavior": current_behavior,
            "visible_seconds": round(visible, 1),
            "attention_seconds": round(attentive, 1),
            "attention_rate": round(
                (attentive / visible) * 100,
                1,
            ) if visible > 0 else 0.0,
            "behavior_seconds": {
                key: round(totals["behavior_seconds"][key], 1)
                for key in BEHAVIOR_KEYS
            },
            "event_counts": dict(totals["event_counts"]),
        }

    def _period_label(self, recording_start, start_seconds, end_seconds):
        try:
            base = datetime.fromisoformat(recording_start)
        except (TypeError, ValueError):
            base = None
        if base is not None:
            start = base + timedelta(seconds=start_seconds)
            end = base + timedelta(seconds=end_seconds)
            return f"{start:%H:%M} - {end:%H:%M}"

        def format_offset(value):
            total = max(0, int(value))
            hours, remainder = divmod(total, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        return f"{format_offset(start_seconds)} - {format_offset(end_seconds)}"

    def _timestamp_label(self, recording_start, seconds):
        try:
            base = datetime.fromisoformat(recording_start)
        except (TypeError, ValueError):
            base = None
        if base is not None:
            value = base + timedelta(seconds=float(seconds or 0))
            return value.strftime("%H:%M:%S")

        total = max(0, int(float(seconds or 0)))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def tracking_report(self, session_id, period_seconds=3600):
        period_seconds = max(60, min(86400, int(period_seconds)))
        with self._connection() as connection:
            metadata = self._session_metadata(connection, session_id)
            if metadata is None:
                return {
                    "session": None,
                    "tracks": [],
                    "period_seconds": period_seconds,
                    "periods": [],
                    "evidence": [],
                }
            track_rows = connection.execute(
                """
                SELECT track_id, current_behavior
                FROM session_tracks
                WHERE session_id = ?
                ORDER BY track_id
                """,
                (session_id,),
            ).fetchall()
            bucket_rows = connection.execute(
                """
                SELECT *
                FROM track_time_buckets
                WHERE session_id = ?
                ORDER BY bucket_start_seconds, track_id
                """,
                (session_id,),
            ).fetchall()
            evidence_rows = connection.execute(
                """
                SELECT
                    evidence.*,
                    events.start_seconds AS event_start_seconds,
                    events.end_seconds AS event_end_seconds,
                    events.duration_seconds AS event_duration_seconds,
                    events.avg_confidence AS event_avg_confidence
                FROM evidence_images AS evidence
                LEFT JOIN behavior_events AS events
                    ON events.session_id = evidence.session_id
                    AND events.track_id = evidence.track_id
                    AND events.event_index = evidence.event_index
                WHERE evidence.session_id = ?
                ORDER BY
                    evidence.track_id,
                    CASE evidence.kind
                        WHEN 'reference' THEN 0
                        ELSE 1
                    END,
                    evidence.captured_seconds
                """,
                (session_id,),
            ).fetchall()

        current_behaviors = {
            int(row["track_id"]): row["current_behavior"]
            for row in track_rows
        }
        overall = defaultdict(self._empty_totals)
        grouped = defaultdict(lambda: defaultdict(self._empty_totals))
        for row in bucket_rows:
            track_id = int(row["track_id"])
            period_index = int(
                float(row["bucket_start_seconds"]) // period_seconds,
            )
            self._add_bucket(overall[track_id], row)
            self._add_bucket(grouped[period_index][track_id], row)

        tracks = [
            self._summary(
                track_id,
                totals,
                current_behaviors.get(track_id),
            )
            for track_id, totals in sorted(overall.items())
        ]
        periods = []
        for period_index, track_totals in sorted(grouped.items()):
            start_seconds = period_index * period_seconds
            end_seconds = start_seconds + period_seconds
            periods.append({
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "label": self._period_label(
                    metadata["recording_started_at"],
                    start_seconds,
                    end_seconds,
                ),
                "tracks": [
                    self._summary(track_id, totals)
                    for track_id, totals in sorted(track_totals.items())
                ],
            })

        evidence = []
        for row in evidence_rows:
            item = {
                "track_id": int(row["track_id"]),
                "evidence_key": row["evidence_key"],
                "event_index": row["event_index"],
                "kind": row["kind"],
                "behavior": row["behavior"],
                "captured_seconds": round(
                    float(row["captured_seconds"]),
                    3,
                ),
                "captured_time": self._timestamp_label(
                    metadata["recording_started_at"],
                    row["captured_seconds"],
                ),
                "filename": row["filename"],
                "width": int(row["width"]),
                "height": int(row["height"]),
                "file_size": int(row["file_size"]),
            }
            if row["event_index"] is not None:
                item["event"] = {
                    "start_seconds": round(
                        float(row["event_start_seconds"] or 0),
                        3,
                    ),
                    "end_seconds": round(
                        float(row["event_end_seconds"] or 0),
                        3,
                    ),
                    "duration_seconds": round(
                        float(row["event_duration_seconds"] or 0),
                        3,
                    ),
                    "avg_confidence": round(
                        float(row["event_avg_confidence"] or 0),
                        1,
                    ),
                }
            evidence.append(item)

        return {
            "session": metadata,
            "tracks": tracks,
            "period_seconds": period_seconds,
            "periods": periods,
            "evidence": evidence,
        }
