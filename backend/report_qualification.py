"""Report-only qualification; raw detections and legacy reports stay unchanged."""

import math
from collections import defaultdict

from person_tracking import ATTENTIVE_BEHAVIORS, BEHAVIOR_KEYS


REPORT_POLICY = {
    "version": 2,
    "minimum_behavior_seconds": 30,
    "duration_basis": "observed_time",
    "identity_scope": "position_within_session",
}


def _totals():
    return {
        "qualified_seconds": 0.0,
        "attention_seconds": 0.0,
        "behavior_seconds": {key: 0.0 for key in BEHAVIOR_KEYS},
        "event_counts": {key: 0 for key in BEHAVIOR_KEYS},
    }


def _finish(totals):
    seconds = totals["qualified_seconds"]
    return {
        **totals,
        "attention_rate": (
            round(totals["attention_seconds"] / seconds * 100, 1)
            if seconds > 0 else None
        ),
    }


def qualify_tracking(tracking, policy, period_seconds=300):
    minimum = float(policy["minimum_behavior_seconds"])
    overall = _totals()
    by_track = defaultdict(_totals)
    periods = defaultdict(lambda: defaultdict(_totals))
    events = []
    for event in tracking.get("events", []):
        duration = float(event.get("observed_duration_seconds", event["duration_seconds"]))
        behavior = event["behavior"]
        if not math.isfinite(duration) or duration + 1e-9 < minimum:
            continue
        segments = event.get("observed_segments") or []
        if not segments:
            continue
        track_id = int(event["track_id"])
        events.append({**event, "duration_seconds": duration})
        for totals in (overall, by_track[track_id]):
            totals["qualified_seconds"] += duration
            totals["behavior_seconds"][behavior] += duration
            totals["event_counts"][behavior] += 1
            if behavior in ATTENTIVE_BEHAVIORS:
                totals["attention_seconds"] += duration

        counted = False
        for segment in segments:
            start, end, observed = segment
            if observed <= 0:
                continue
            first = int(start // period_seconds)
            last = int(max(start, end - 1e-9) // period_seconds)
            for index in range(first, last + 1):
                overlap = max(0.0, min(end, (index + 1) * period_seconds) - max(start, index * period_seconds))
                seconds = observed * overlap / (end - start) if end > start else observed
                totals = periods[index][track_id]
                totals["qualified_seconds"] += seconds
                totals["behavior_seconds"][behavior] += seconds
                if behavior in ATTENTIVE_BEHAVIORS:
                    totals["attention_seconds"] += seconds
                if not counted:
                    totals["event_counts"][behavior] += 1
                    counted = True

    tracks = []
    for track in tracking.get("tracks", []):
        track_id = int(track["track_id"])
        totals = _finish(by_track[track_id])
        tracks.append({
            **track,
            **totals,
            "excluded_seconds": max(0.0, float(track["visible_seconds"]) - totals["qualified_seconds"]),
        })
    return {
        "summary": _finish(overall),
        "tracks": tracks,
        "events": events,
        "periods": [
            {
                "start_seconds": index * period_seconds,
                "end_seconds": (index + 1) * period_seconds,
                "tracks": [{"track_id": track_id, **_finish(totals)} for track_id, totals in sorted(items.items())],
                **_finish({
                    "qualified_seconds": sum(item["qualified_seconds"] for item in items.values()),
                    "attention_seconds": sum(item["attention_seconds"] for item in items.values()),
                    "behavior_seconds": {key: sum(item["behavior_seconds"][key] for item in items.values()) for key in BEHAVIOR_KEYS},
                    "event_counts": {key: sum(item["event_counts"][key] for item in items.values()) for key in BEHAVIOR_KEYS},
                }),
            }
            for index, items in sorted(periods.items())
        ],
    }
