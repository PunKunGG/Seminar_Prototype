import math


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


def iter_sample_windows(duration_seconds, interval_seconds, window_seconds, sample_fps):
    """Yield (window_start, sample_times) for a long video."""
    duration = max(0.0, float(duration_seconds))
    interval = max(0.001, float(interval_seconds))
    window = min(interval, max(0.001, float(window_seconds)))
    step = 1.0 / max(0.001, float(sample_fps))

    window_start = 0.0
    while window_start < duration:
        sample_end = min(duration, window_start + window)
        sample_count = max(1, int(math.ceil((sample_end - window_start) / step)))
        sample_times = [
            min(sample_end, window_start + (index * step))
            for index in range(sample_count)
        ]
        yield window_start, sample_times
        window_start += interval


def iter_sequential_decode_steps(sample_times, source_fps):
    """Yield each sample time and how many frames to grab before reading it."""
    times = list(sample_times)
    if not times:
        return

    fps = max(0.001, float(source_fps))
    base_time = times[0]
    previous_target_frame = 0

    for index, sample_time in enumerate(times):
        target_frame = round((sample_time - base_time) * fps)
        frames_to_grab = 0 if index == 0 else max(
            0,
            target_frame - previous_target_frame - 1,
        )
        yield sample_time, frames_to_grab
        previous_target_frame = target_frame


def aggregate_analyses(analyses):
    """Combine sampled frame results into one representative timeline point."""
    if not analyses:
        return None

    frame_count = len(analyses)
    peak_analysis = max(
        analyses,
        key=lambda item: float(item.get("total_people") or 0),
    )
    summary_totals = {key: 0.0 for key in BEHAVIOR_KEYS}
    person_observations = 0.0

    for analysis in analyses:
        summary = analysis.get("summary") or {}
        person_observations += float(analysis.get("total_people") or 0)
        for key in BEHAVIOR_KEYS:
            summary_totals[key] += float(summary.get(key) or 0)

    behavior_observations = sum(summary_totals.values())
    if behavior_observations <= 0 and person_observations > 0:
        summary_totals["unknown"] = person_observations
        behavior_observations = person_observations

    attentive_observations = (
        summary_totals["attentive"] + summary_totals["hand_raised"]
    )
    attention_rate = (
        round((attentive_observations / behavior_observations) * 100, 1)
        if behavior_observations
        else 0
    )

    average_counts = {
        key: total / frame_count
        for key, total in summary_totals.items()
    }
    total_people = int(math.floor(sum(average_counts.values()) + 0.5))
    integer_summary = {
        key: int(math.floor(value))
        for key, value in average_counts.items()
    }
    remaining = total_people - sum(integer_summary.values())
    ranked_keys = sorted(
        BEHAVIOR_KEYS,
        key=lambda key: (
            average_counts[key] - integer_summary[key],
            average_counts[key],
        ),
        reverse=True,
    )
    for index in range(max(0, remaining)):
        integer_summary[ranked_keys[index % len(ranked_keys)]] += 1

    return {
        "total_people": total_people,
        "max_people": max(
            0,
            int(round(float(peak_analysis.get("total_people") or 0))),
        ),
        "behaviors": [],
        "summary": integer_summary,
        "peak_summary": {
            key: int(round(float(
                (peak_analysis.get("summary") or {}).get(key) or 0
            )))
            for key in BEHAVIOR_KEYS
        },
        "attention_rate": attention_rate,
        "annotated_frame": analyses[-1].get("annotated_frame"),
        "sampled_frames": frame_count,
    }


def summarize_report_history(history):
    """Build a clip-level report without treating the final frame as the clip."""
    records = list(history or [])
    empty_summary = {key: 0 for key in BEHAVIOR_KEYS}
    if not records:
        return {
            "avg_attention_rate": 0,
            "avg_people": 0,
            "max_people": 0,
            "total_records": 0,
            "latest_attention_rate": 0,
            "latest_total_people": 0,
            "latest_summary": empty_summary.copy(),
            "overall_summary": empty_summary.copy(),
            "report_attention_rate": 0,
            "report_total_people": 0,
            "report_summary": empty_summary.copy(),
            "report_summary_scope": "peak_concurrent_people",
            "report_summary_time": None,
            "report_video_position_seconds": None,
        }

    def total_people_count(item):
        return max(0, int(round(float(item.get("total_people") or 0))))

    def peak_people_count(item):
        return max(
            0,
            int(round(float(
                item.get("max_people", item.get("total_people")) or 0
            ))),
        )

    latest = records[-1]
    peak = max(records, key=peak_people_count)
    overall = aggregate_analyses(records)
    avg_attention = round(
        sum(float(item.get("attention_rate") or 0) for item in records)
        / len(records),
        1,
    )
    avg_people = round(
        sum(float(item.get("total_people") or 0) for item in records)
        / len(records),
        1,
    )
    peak_summary = peak.get("peak_summary") or peak.get("summary") or {}

    return {
        "avg_attention_rate": avg_attention,
        "avg_people": avg_people,
        "max_people": peak_people_count(peak),
        "total_records": len(records),
        # Keep the latest-frame fields for existing API consumers and debugging.
        "latest_attention_rate": float(latest.get("attention_rate") or 0),
        "latest_total_people": total_people_count(latest),
        "latest_summary": {
            key: int(round(float((latest.get("summary") or {}).get(key) or 0)))
            for key in BEHAVIOR_KEYS
        },
        "overall_summary": (
            overall["summary"] if overall else empty_summary.copy()
        ),
        "report_attention_rate": avg_attention,
        "report_total_people": peak_people_count(peak),
        "report_summary": {
            key: int(round(float(peak_summary.get(key) or 0)))
            for key in BEHAVIOR_KEYS
        },
        "report_summary_scope": "peak_concurrent_people",
        "report_summary_time": peak.get("time"),
        "report_video_position_seconds": peak.get("video_position_seconds"),
    }


def build_report_periods(history, period_seconds=600):
    """Group sampled-video history into readable report periods."""
    period = max(60, int(period_seconds))
    buckets = {}

    for item in history:
        position = item.get("video_position_seconds")
        try:
            position = float(position)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(position) or position < 0:
            continue

        bucket_index = int(position // period)
        buckets.setdefault(bucket_index, []).append(item)

    periods = []
    for bucket_index in sorted(buckets):
        items = buckets[bucket_index]
        aggregate = aggregate_analyses(items)
        if aggregate is None:
            continue

        start_seconds = bucket_index * period
        end_seconds = start_seconds + period
        periods.append({
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "label": (
                f"{format_video_time(start_seconds)} - "
                f"{format_video_time(end_seconds)}"
            ),
            "avg_attention_rate": round(
                sum(float(item.get("attention_rate") or 0) for item in items)
                / len(items),
                1,
            ),
            "avg_people": round(
                sum(float(item.get("total_people") or 0) for item in items)
                / len(items),
                1,
            ),
            "max_people": max(
                int(round(float(
                    item.get("max_people", item.get("total_people")) or 0
                )))
                for item in items
            ),
            "summary": aggregate["summary"],
            "records": len(items),
        })

    return periods


def format_video_time(seconds):
    total_seconds = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
