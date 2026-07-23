from __future__ import annotations

import hashlib
import os
import re
import shutil


_SAFE_PART_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_part(value, fallback):
    cleaned = _SAFE_PART_PATTERN.sub("_", str(value or "").strip())
    cleaned = cleaned.strip("._")
    return cleaned or fallback


class EvidenceStore:
    def __init__(
        self,
        root,
        *,
        jpeg_quality=86,
        max_dimension=900,
        padding_ratio=0.15,
    ):
        self.root = os.path.abspath(root)
        self.jpeg_quality = max(50, min(95, int(jpeg_quality)))
        self.max_dimension = max(320, min(1920, int(max_dimension)))
        self.padding_ratio = max(0.0, min(0.5, float(padding_ratio)))
        os.makedirs(self.root, exist_ok=True)

    def session_folder_name(self, session_id):
        session_text = str(session_id or "")
        prefix = _safe_part(session_text, "session")[:64]
        digest = hashlib.sha256(
            session_text.encode("utf-8", errors="replace"),
        ).hexdigest()[:12]
        return f"{prefix}_{digest}"

    def session_directory(self, session_id):
        return os.path.join(
            self.root,
            self.session_folder_name(session_id),
        )

    def clear_session(self, session_id):
        directory = os.path.abspath(self.session_directory(session_id))
        if os.path.commonpath([directory, self.root]) != self.root:
            raise ValueError("Evidence directory is outside the configured root")
        if os.path.isdir(directory):
            shutil.rmtree(directory)

    def resolve_file(self, session_id, filename):
        clean_filename = os.path.basename(str(filename or ""))
        if not clean_filename or clean_filename != filename:
            return None
        path = os.path.abspath(
            os.path.join(self.session_directory(session_id), clean_filename),
        )
        directory = os.path.abspath(self.session_directory(session_id))
        if os.path.commonpath([path, directory]) != directory:
            return None
        return path

    def _filename(
        self,
        *,
        track_id,
        kind,
        event_index,
        behavior,
        captured_seconds,
    ):
        track_part = f"id_{int(track_id):04d}"
        if kind == "reference":
            return f"{track_part}_reference.jpg"
        behavior_part = _safe_part(behavior, "unknown")[:32]
        event_part = max(0, int(event_index or 0))
        time_part = max(0, int(round(float(captured_seconds or 0) * 1000)))
        return (
            f"{track_part}_event_{event_part:04d}_"
            f"{behavior_part}_{time_part:012d}.jpg"
        )

    def save_crop(
        self,
        *,
        session_id,
        track_id,
        kind,
        event_index,
        behavior,
        captured_seconds,
        frame,
        bbox,
    ):
        if frame is None or bbox is None or len(bbox) != 4:
            return None
        try:
            frame_height, frame_width = frame.shape[:2]
            x1, y1, x2, y2 = (float(value) for value in bbox)
        except (AttributeError, TypeError, ValueError):
            return None
        if frame_width <= 0 or frame_height <= 0 or x2 <= x1 or y2 <= y1:
            return None

        pad_x = (x2 - x1) * self.padding_ratio
        pad_y = (y2 - y1) * self.padding_ratio
        left = max(0, int(x1 - pad_x))
        top = max(0, int(y1 - pad_y))
        right = min(frame_width, int(x2 + pad_x))
        bottom = min(frame_height, int(y2 + pad_y))
        if right <= left or bottom <= top:
            return None

        crop = frame[top:bottom, left:right].copy()
        crop_height, crop_width = crop.shape[:2]
        longest = max(crop_height, crop_width)

        import cv2

        if longest > self.max_dimension:
            scale = self.max_dimension / longest
            crop = cv2.resize(
                crop,
                (
                    max(1, int(round(crop_width * scale))),
                    max(1, int(round(crop_height * scale))),
                ),
                interpolation=cv2.INTER_AREA,
            )

        directory = self.session_directory(session_id)
        os.makedirs(directory, exist_ok=True)
        filename = self._filename(
            track_id=track_id,
            kind=kind,
            event_index=event_index,
            behavior=behavior,
            captured_seconds=captured_seconds,
        )
        path = os.path.join(directory, filename)
        temporary_path = f"{path}.tmp.jpg"
        try:
            saved = cv2.imwrite(
                temporary_path,
                crop,
                [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality],
            )
            if not saved:
                return None
            os.replace(temporary_path, path)
        finally:
            if os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass
        return {
            "filename": filename,
            "width": int(crop.shape[1]),
            "height": int(crop.shape[0]),
            "file_size": os.path.getsize(path),
        }
