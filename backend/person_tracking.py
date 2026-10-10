from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field


BEHAVIOR_KEYS = (
    "attentive",
    "sleeping",
    "looking_down",
    "phone_use",
    "phone_suspected",
    "hand_raised",
    "standing",
    "unknown",
)
ATTENTIVE_BEHAVIORS = {"attentive", "hand_raised"}

DEFAULT_TRANSITION_SECONDS = {
    "attentive": 1.0,
    "sleeping": 8.0,
    "looking_down": 3.0,
    "phone_use": 3.0,
    "phone_suspected": 4.0,
    "hand_raised": 1.2,
    "standing": 1.0,
    "unknown": 1.5,
}

DEBOUNCED_INITIAL_BEHAVIORS = frozenset({
    "sleeping",
    "looking_down",
    "phone_use",
    "phone_suspected",
    "hand_raised",
})


def _clean_bbox(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (x1, y1, x2, y2)) or x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _bbox_iou(left, right):
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if intersection <= 0:
        return 0.0
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def _center_distance_ratio(left, right):
    left_center = ((left[0] + left[2]) / 2, (left[1] + left[3]) / 2)
    right_center = ((right[0] + right[2]) / 2, (right[1] + right[3]) / 2)
    distance = math.hypot(
        left_center[0] - right_center[0],
        left_center[1] - right_center[1],
    )
    left_diag = math.hypot(left[2] - left[0], left[3] - left[1])
    right_diag = math.hypot(right[2] - right[0], right[3] - right[1])
    scale = max(1.0, left_diag, right_diag)
    return distance / scale


def _bottom_center_distance_ratio(left, right):
    left_anchor = ((left[0] + left[2]) / 2, left[3])
    right_anchor = ((right[0] + right[2]) / 2, right[3])
    distance = math.hypot(
        left_anchor[0] - right_anchor[0],
        left_anchor[1] - right_anchor[1],
    )
    left_diag = math.hypot(left[2] - left[0], left[3] - left[1])
    right_diag = math.hypot(right[2] - right[0], right[3] - right[1])
    return distance / max(1.0, left_diag, right_diag)


def _blank_behavior_values():
    return {key: 0.0 for key in BEHAVIOR_KEYS}


def _blank_event_counts():
    return {key: 0 for key in BEHAVIOR_KEYS}


@dataclass
class BehaviorEvent:
    index: int
    behavior: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float = 0.0
    confidence_total: float = 0.0
    observations: int = 0
    observed_segments: list = field(default_factory=list)

    def add_observation(self, timestamp, duration, confidence, record_segments=False):
        self.end_seconds = max(self.end_seconds, timestamp)
        self.duration_seconds += max(0.0, duration)
        self.confidence_total += max(0.0, float(confidence or 0))
        self.observations += 1
        if record_segments and duration > 0:
            start = max(0.0, timestamp - duration)
            if self.observed_segments and start <= self.observed_segments[-1][1] + 1e-8:
                segment = self.observed_segments[-1]
                segment[1] = timestamp
                segment[2] += duration
            else:
                self.observed_segments.append([start, timestamp, duration])

    def to_dict(self):
        confidence = (
            self.confidence_total / self.observations
            if self.observations
            else 0.0
        )
        return {
            "event_index": self.index,
            "behavior": self.behavior,
            "start_seconds": round(self.start_seconds, 3),
            "end_seconds": round(self.end_seconds, 3),
            "duration_seconds": self.duration_seconds,
            "avg_confidence": round(confidence, 1),
            "observed_segments": [list(segment) for segment in self.observed_segments],
        }


@dataclass
class TrackState:
    track_id: int
    bbox: tuple
    first_seen: float
    last_seen: float
    current_behavior: str
    pending_behavior: str | None = None
    pending_since: float | None = None
    visible_seconds: float = 0.0
    behavior_seconds: dict = field(default_factory=_blank_behavior_values)
    event_counts: dict = field(default_factory=_blank_event_counts)
    events: list = field(default_factory=list)
    buckets: dict = field(default_factory=dict)
    active: bool = True
    position_bbox: tuple | None = None
    position_samples: int = 0
    position_anchor: tuple | None = None
    position_scale: float = 1.0
    observed_last_update: bool = True

    def current_event(self):
        return self.events[-1] if self.events else None


class SessionTracker:
    """Anonymous person tracker whose IDs are valid only inside one session."""

    def __init__(
        self,
        *,
        max_missing_seconds=3.0,
        observation_step_seconds=0.2,
        max_observation_gap_seconds=1.0,
        bucket_seconds=60,
        transition_seconds=None,
        min_iou=0.05,
        max_center_distance=0.85,
        position_matching=True,
        position_memory_seconds=21600,
        max_position_distance=0.45,
        require_contiguous_transitions=False,
        persistent_positions=False,
        record_observed_segments=False,
    ):
        self.max_missing_seconds = max(0.1, float(max_missing_seconds))
        self.observation_step_seconds = max(
            0.01,
            float(observation_step_seconds),
        )
        self.max_observation_gap_seconds = max(
            self.observation_step_seconds,
            float(max_observation_gap_seconds),
        )
        self.bucket_seconds = max(1, int(bucket_seconds))
        self.transition_seconds = dict(DEFAULT_TRANSITION_SECONDS)
        if transition_seconds:
            self.transition_seconds.update(transition_seconds)
        self.min_iou = max(0.0, float(min_iou))
        self.max_center_distance = max(0.1, float(max_center_distance))
        self.position_matching = bool(position_matching)
        self.position_memory_seconds = max(
            self.max_missing_seconds,
            float(position_memory_seconds),
        )
        self.max_position_distance = max(
            0.1,
            float(max_position_distance),
        )
        self.require_contiguous_transitions = bool(
            require_contiguous_transitions
        )
        self.persistent_positions = bool(persistent_positions and position_matching)
        self.record_observed_segments = bool(record_observed_segments)
        self._pending_positions = []
        self._ambiguous_positions = set()
        self._tracks = {}
        self._next_track_id = 1
        self._origin = time.monotonic()
        self._lock = threading.RLock()

    def _timestamp(self, timestamp):
        if timestamp is None:
            return max(0.0, time.monotonic() - self._origin)
        return max(0.0, float(timestamp))

    def _new_bucket(self, bucket_start):
        return {
            "bucket_start_seconds": float(bucket_start),
            "visible_seconds": 0.0,
            "behavior_seconds": _blank_behavior_values(),
            "event_counts": _blank_event_counts(),
        }

    def _bucket_for(self, track, timestamp):
        bucket_start = (
            math.floor(timestamp / self.bucket_seconds) * self.bucket_seconds
        )
        if bucket_start not in track.buckets:
            track.buckets[bucket_start] = self._new_bucket(bucket_start)
        return track.buckets[bucket_start]

    def _begin_event(self, track, behavior, timestamp):
        behavior = behavior if behavior in BEHAVIOR_KEYS else "unknown"
        event = BehaviorEvent(
            index=len(track.events) + 1,
            behavior=behavior,
            start_seconds=timestamp,
            end_seconds=timestamp,
        )
        track.events.append(event)
        track.current_behavior = behavior
        track.event_counts[behavior] += 1
        self._bucket_for(track, timestamp)["event_counts"][behavior] += 1
        return event

    def _observation_duration(self, track, timestamp):
        elapsed = timestamp - track.last_seen
        if self.record_observed_segments and (
            elapsed <= 0 or elapsed > self.max_observation_gap_seconds
            or not track.observed_last_update
        ):
            return 0.0
        if elapsed <= 0 or elapsed > self.max_observation_gap_seconds:
            return self.observation_step_seconds
        return elapsed

    def _record_observation(self, track, timestamp, confidence):
        duration = self._observation_duration(track, timestamp)
        behavior = track.current_behavior
        track.visible_seconds += duration
        track.behavior_seconds[behavior] += duration
        bucket = self._bucket_for(track, timestamp)
        bucket["visible_seconds"] += duration
        bucket["behavior_seconds"][behavior] += duration
        event = track.current_event()
        if event is not None:
            event.add_observation(timestamp, duration, confidence, self.record_observed_segments)

    def _update_behavior(self, track, observed_behavior, timestamp):
        observed = (
            observed_behavior
            if observed_behavior in BEHAVIOR_KEYS
            else "unknown"
        )
        if observed == track.current_behavior:
            track.pending_behavior = None
            track.pending_since = None
            return False

        if (
            self.require_contiguous_transitions
            and timestamp - track.last_seen > self.max_observation_gap_seconds
        ):
            track.pending_behavior = observed
            track.pending_since = timestamp
            return False

        if track.pending_behavior != observed:
            track.pending_behavior = observed
            track.pending_since = timestamp
            return False

        required = max(0.0, float(self.transition_seconds.get(observed, 1.0)))
        if timestamp - track.pending_since < required:
            return False

        self._begin_event(track, observed, timestamp)
        track.pending_behavior = None
        track.pending_since = None
        return True

    def _create_track(self, detection, timestamp):
        observed_behavior = detection.get("behavior", "unknown")
        if observed_behavior not in BEHAVIOR_KEYS:
            observed_behavior = "unknown"
        behavior = (
            "unknown"
            if observed_behavior in DEBOUNCED_INITIAL_BEHAVIORS
            else observed_behavior
        )
        track = TrackState(
            track_id=self._next_track_id,
            bbox=detection["bbox"],
            first_seen=timestamp,
            last_seen=timestamp,
            current_behavior=behavior,
            position_bbox=(
                None
                if observed_behavior == "standing"
                else detection["bbox"]
            ),
            position_samples=0 if observed_behavior == "standing" else 1,
            pending_behavior=(
                observed_behavior if behavior != observed_behavior else None
            ),
            pending_since=timestamp if behavior != observed_behavior else None,
            position_anchor=tuple(detection["position_anchor"]) if detection.get("position_anchor") else None,
            position_scale=float(detection.get("position_scale") or 1),
        )
        self._next_track_id += 1
        self._tracks[track.track_id] = track
        self._begin_event(track, behavior, timestamp)
        self._record_observation(
            track,
            timestamp,
            detection.get("confidence", 0),
        )
        return track

    def _update_position(self, track, detection):
        if self.persistent_positions:
            return
        if detection.get("behavior") == "standing":
            return
        if track.position_bbox is None:
            track.position_bbox = detection["bbox"]
            track.position_samples = 1
            return

        weight = min(20, max(1, track.position_samples))
        track.position_bbox = tuple(
            ((old_value * weight) + new_value) / (weight + 1)
            for old_value, new_value in zip(
                track.position_bbox,
                detection["bbox"],
            )
        )
        track.position_samples = min(20, track.position_samples + 1)

    def _match(self, detections, timestamp):
        if self.persistent_positions:
            return self._match_positions(detections, timestamp)
        candidates = []
        for track in self._tracks.values():
            missing_seconds = timestamp - track.last_seen
            if (
                missing_seconds > self.max_missing_seconds
                and (
                    not self.position_matching
                    or missing_seconds > self.position_memory_seconds
                )
            ):
                track.active = False
                continue
            for detection_index, detection in enumerate(detections):
                if missing_seconds > self.max_missing_seconds:
                    track.active = False
                    if detection.get("behavior") == "standing":
                        continue
                    position_bbox = track.position_bbox
                    if position_bbox is None:
                        continue
                    position_distance = _bottom_center_distance_ratio(
                        position_bbox,
                        detection["bbox"],
                    )
                    if position_distance > self.max_position_distance:
                        continue
                    candidates.append((
                        0,
                        max(0.0, 1.0 - position_distance),
                        track.track_id,
                        detection_index,
                    ))
                    continue

                iou = _bbox_iou(track.bbox, detection["bbox"])
                center_ratio = _center_distance_ratio(
                    track.bbox,
                    detection["bbox"],
                )
                if iou < self.min_iou and center_ratio > self.max_center_distance:
                    continue
                score = (iou * 2.0) + max(0.0, 1.0 - center_ratio)
                candidates.append((
                    1,
                    score,
                    track.track_id,
                    detection_index,
                ))

        matches = {}
        used_tracks = set()
        used_detections = set()
        for _, _, track_id, detection_index in sorted(
            candidates,
            reverse=True,
        ):
            if track_id in used_tracks or detection_index in used_detections:
                continue
            matches[detection_index] = self._tracks[track_id]
            used_tracks.add(track_id)
            used_detections.add(detection_index)
        return matches

    def _position_distance(self, track, detection):
        anchor = detection.get("position_anchor")
        if anchor is None or track.position_anchor is None:
            return None
        return math.dist(track.position_anchor, anchor) / max(
            0.001, track.position_scale, float(detection.get("position_scale") or 0),
        )

    def _match_positions(self, detections, timestamp):
        candidates = []
        rankings = {}
        self._ambiguous_positions = set()
        for index, detection in enumerate(detections):
            ranked = []
            for track in self._tracks.values():
                distance = self._position_distance(track, detection)
                if distance is not None and distance <= self.max_position_distance:
                    ranked.append((distance, track.track_id))
                elif (track.active
                      and timestamp - track.last_seen <= self.max_missing_seconds
                      and _bbox_iou(track.bbox, detection["bbox"]) >= 0.5):
                    ranked.append((self.max_position_distance + 1, track.track_id))
            ranked.sort()
            if len(ranked) > 1 and ranked[1][0] - ranked[0][0] <= max(0.01, ranked[1][0] * 0.1):
                self._ambiguous_positions.add(index)
                continue
            if ranked:
                rankings[index] = ranked
                candidates.extend((distance, track_id, index) for distance, track_id in ranked)
        matches = {}
        assigned_tracks = {}

        # Reroute existing matches along valid alternatives before dropping an observation.
        def assign_alternative(index, visited_tracks, maximum_distance):
            for distance, track_id in rankings[index]:
                if distance > maximum_distance or track_id in visited_tracks:
                    continue
                visited_tracks.add(track_id)
                previous_index = assigned_tracks.get(track_id)
                if previous_index is None or assign_alternative(previous_index, visited_tracks, maximum_distance):
                    matches[index] = self._tracks[track_id]
                    assigned_tracks[track_id] = index
                    return True
            return False

        # Finish shoulder-anchor assignment before considering overlapping-box fallbacks.
        ordered_candidates = sorted(candidates)
        for maximum_distance in (self.max_position_distance, float("inf")):
            for distance, track_id, index in ordered_candidates:
                if distance <= maximum_distance and track_id not in assigned_tracks and index not in matches:
                    matches[index] = self._tracks[track_id]
                    assigned_tracks[track_id] = index
            for index in rankings:
                if index not in matches:
                    assign_alternative(index, set(), maximum_distance)
        for index in rankings:
            if index not in matches:
                self._ambiguous_positions.add(index)
        return matches

    def _confirm_position(self, detection, timestamp, used_pending):
        anchor = detection.get("position_anchor")
        if anchor is None:
            return False
        if any(
            (distance := self._position_distance(track, detection)) is not None
            and distance <= 0.1
            for track in self._tracks.values()
        ):
            return False
        scale = max(0.001, float(detection.get("position_scale") or 0.001))
        candidates = [
            (math.dist(item["anchor"], anchor) / max(scale, item["scale"]), index)
            for index, item in enumerate(self._pending_positions)
            if index not in used_pending
        ]
        candidates.sort()
        if candidates and candidates[0][0] <= 0.1:
            index = candidates[0][1]
            pending = self._pending_positions[index]
            elapsed = timestamp - pending["last_seen"]
            pending["observed_seconds"] += (
                elapsed if 0 < elapsed <= self.max_observation_gap_seconds
                else 0
            )
            pending["last_seen"] = timestamp
            used_pending.add(index)
            return pending["observed_seconds"] + 1e-9 >= 3.0
        self._pending_positions.append({
            "anchor": tuple(anchor), "scale": scale,
            "last_seen": timestamp, "observed_seconds": 0.0,
        })
        used_pending.add(len(self._pending_positions) - 1)
        return False

    def update(self, detections, timestamp=None):
        timestamp = self._timestamp(timestamp)
        prepared = []
        for raw_detection in detections or []:
            bbox = _clean_bbox(raw_detection.get("bbox"))
            if bbox is None:
                continue
            detection = dict(raw_detection)
            detection["bbox"] = bbox
            prepared.append(detection)

        with self._lock:
            matches = self._match(prepared, timestamp)
            enriched = []
            used_pending = set()
            for detection_index, detection in enumerate(prepared):
                track = matches.get(detection_index)
                if track is None and self.persistent_positions and (
                    detection_index in self._ambiguous_positions
                    or not self._confirm_position(detection, timestamp, used_pending)
                ):
                    enriched.append({
                        **detection, "raw_behavior": detection.get("behavior", "unknown"),
                        "track_id": None, "track_attention_rate": 0,
                        "is_new_track": False, "reacquired": False,
                        "event_started": False, "event_index": None,
                    })
                    continue
                is_new_track = track is None
                reacquired = (
                    track is not None
                    and (
                        not track.observed_last_update if self.record_observed_segments
                        else timestamp - track.last_seen > self.max_missing_seconds
                    )
                )
                event_started = is_new_track
                if track is None:
                    track = self._create_track(detection, timestamp)
                elif reacquired:
                    observed_behavior = detection.get("behavior", "unknown")
                    if observed_behavior not in BEHAVIOR_KEYS:
                        observed_behavior = "unknown"
                    behavior = (
                        "unknown"
                        if observed_behavior in DEBOUNCED_INITIAL_BEHAVIORS
                        else observed_behavior
                    )
                    self._begin_event(
                        track,
                        behavior,
                        timestamp,
                    )
                    track.pending_behavior = (
                        observed_behavior
                        if behavior != observed_behavior
                        else None
                    )
                    track.pending_since = (
                        timestamp if behavior != observed_behavior else None
                    )
                    self._record_observation(
                        track,
                        timestamp,
                        detection.get("confidence", 0),
                    )
                    event_started = True
                    track.bbox = detection["bbox"]
                    track.last_seen = timestamp
                    track.active = True
                    track.observed_last_update = True
                    self._update_position(track, detection)
                else:
                    self._record_observation(
                        track,
                        timestamp,
                        detection.get("confidence", 0),
                    )
                    event_started = self._update_behavior(
                        track,
                        detection.get("behavior"),
                        timestamp,
                    )
                    track.bbox = detection["bbox"]
                    track.last_seen = timestamp
                    track.active = True
                    track.observed_last_update = True
                    self._update_position(track, detection)

                item = dict(detection)
                item["raw_behavior"] = detection.get("behavior", "unknown")
                item["behavior"] = track.current_behavior
                item["track_id"] = track.track_id
                item["track_attention_rate"] = self._attention_rate(track)
                item["is_new_track"] = is_new_track
                item["reacquired"] = reacquired
                item["event_started"] = event_started
                current_event = track.current_event()
                item["event_index"] = (
                    current_event.index if current_event is not None else None
                )
                enriched.append(item)

            matched_ids = {
                item["track_id"]
                for item in enriched
            }
            for track in self._tracks.values():
                if track.track_id not in matched_ids:
                    track.observed_last_update = False
                if (
                    track.track_id not in matched_ids
                    and timestamp - track.last_seen > self.max_missing_seconds
                ):
                    track.active = False

            self._pending_positions = [
                item for index, item in enumerate(self._pending_positions)
                if index in used_pending
                and timestamp - item["last_seen"] <= self.max_missing_seconds
                and not any(
                    track.position_anchor is not None
                    and math.dist(item["anchor"], track.position_anchor) / max(item["scale"], track.position_scale) <= 0.1
                    for track in self._tracks.values()
                )
            ]

            return {
                "detections": enriched,
                "active_tracks": self.summaries(active_only=True),
                "timestamp_seconds": round(timestamp, 3),
            }

    def _attention_rate(self, track):
        if track.visible_seconds <= 0:
            return 0.0
        attentive_seconds = sum(
            track.behavior_seconds[key]
            for key in ATTENTIVE_BEHAVIORS
        )
        return round((attentive_seconds / track.visible_seconds) * 100, 1)

    def _track_dict(
        self,
        track,
        include_details=False,
        recent_only=False,
    ):
        result = {
            "track_id": track.track_id,
            "current_behavior": track.current_behavior,
            "first_seen_seconds": round(track.first_seen, 3),
            "last_seen_seconds": round(track.last_seen, 3),
            "visible_seconds": round(track.visible_seconds, 3),
            "attention_rate": self._attention_rate(track),
            "behavior_seconds": {
                key: round(track.behavior_seconds[key], 3)
                for key in BEHAVIOR_KEYS
            },
            "event_counts": dict(track.event_counts),
            "active": track.active,
        }
        if include_details:
            events = track.events[-4:] if recent_only else track.events
            bucket_items = sorted(track.buckets.items())
            if recent_only:
                bucket_items = bucket_items[-2:]
            result["events"] = [event.to_dict() for event in events]
            result["buckets"] = [
                {
                    "bucket_start_seconds": round(
                        bucket["bucket_start_seconds"],
                        3,
                    ),
                    "visible_seconds": round(bucket["visible_seconds"], 3),
                    "behavior_seconds": {
                        key: round(bucket["behavior_seconds"][key], 3)
                        for key in BEHAVIOR_KEYS
                    },
                    "event_counts": dict(bucket["event_counts"]),
                }
                for _, bucket in bucket_items
            ]
        return result

    def summaries(self, active_only=False):
        with self._lock:
            return [
                self._track_dict(track)
                for _, track in sorted(self._tracks.items())
                if not active_only or track.active
            ]

    def persistence_snapshot(self, recent_only=False):
        with self._lock:
            return [
                self._track_dict(
                    track,
                    include_details=True,
                    recent_only=recent_only,
                )
                for _, track in sorted(self._tracks.items())
            ]

    def finalize(self, timestamp=None):
        timestamp = self._timestamp(timestamp)
        with self._lock:
            for track in self._tracks.values():
                track.active = False
                event = track.current_event()
                if event is not None:
                    event.end_seconds = max(
                        event.end_seconds,
                        min(timestamp, track.last_seen),
                    )
            return self.persistence_snapshot()
