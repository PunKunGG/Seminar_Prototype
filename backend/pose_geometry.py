"""Geometry derived from existing pose points, not facial identity features."""

import math


def report_geometry(points, bbox, frame_shape, threshold):
    height, width = frame_shape[:2]
    if not bbox or width <= 0 or height <= 0:
        return {}
    visible = {
        index: (float(point[0]), float(point[1]))
        for index, point in enumerate(points)
        if len(point) >= 3 and float(point[2]) >= threshold
        and all(math.isfinite(float(value)) for value in point[:3])
    }
    result = {}
    if 5 in visible and 6 in visible:
        left, right = visible[5], visible[6]
        result["position_anchor"] = [
            (left[0] + right[0]) / (2 * width),
            (left[1] + right[1]) / (2 * height),
        ]
        result["position_scale"] = math.hypot((bbox[2] - bbox[0]) / width, (bbox[3] - bbox[1]) / height)
        head = [visible[index] for index in range(5) if index in visible]
        if len(head) >= 2:
            center_x = (min(point[0] for point in head) + max(point[0] for point in head)) / 2
            center_y = (min(point[1] for point in head) + max(point[1] for point in head)) / 2
            shoulder_width = math.hypot(left[0] - right[0], left[1] - right[1])
            head_width = max(point[0] for point in head) - min(point[0] for point in head)
            size = max(32.0, shoulder_width * 0.95, head_width * 2.2)
            center_y += size * 0.15
            result["portrait_bbox"] = [center_x - size / 2, center_y - size / 2, center_x + size / 2, center_y + size / 2]
    return result
