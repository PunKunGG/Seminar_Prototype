from __future__ import annotations

from datetime import datetime
import os


def is_path_inside(path, roots):
    normalized_path = os.path.normcase(os.path.abspath(path))
    for root in roots:
        normalized_root = os.path.normcase(os.path.abspath(root))
        try:
            if os.path.commonpath([
                normalized_path,
                normalized_root,
            ]) == normalized_root:
                return True
        except ValueError:
            continue
    return False


class VideoSourcePolicy:
    def __init__(
        self,
        *,
        max_webcam_index,
        video_extensions,
        source_directories,
        upload_directory,
        filename_sanitizer,
    ):
        self.max_webcam_index = int(max_webcam_index)
        self.video_extensions = frozenset(
            str(extension).lower()
            for extension in video_extensions
        )
        self.source_directories = tuple(
            os.path.abspath(directory)
            for directory in source_directories
        )
        self.upload_directory = os.path.abspath(upload_directory)
        self.filename_sanitizer = filename_sanitizer

    def normalize(self, source, *, allow_any_path=False):
        if isinstance(source, bool):
            return None, "Source must be a webcam index or a video file path"

        if isinstance(source, int):
            if 0 <= source <= self.max_webcam_index:
                return source, None
            return (
                None,
                "Webcam index must be between "
                f"0 and {self.max_webcam_index}",
            )

        if not isinstance(source, str):
            return None, "Source must be a webcam index or a video file path"

        raw_source = source.strip()
        if raw_source.isdigit():
            return self.normalize(
                int(raw_source),
                allow_any_path=allow_any_path,
            )
        if "://" in raw_source:
            return None, "Network video URLs are disabled by default"

        path = os.path.abspath(os.path.expanduser(raw_source))
        extension = os.path.splitext(path)[1].lower()
        if extension not in self.video_extensions:
            return None, self._extension_error()
        if not os.path.exists(path):
            return None, f"Video file not found: {path}"
        if (
            not allow_any_path
            and not is_path_inside(path, self.source_directories)
        ):
            allowed = ", ".join(self.source_directories)
            return (
                None,
                "Video file must be inside allowed directories: "
                f"{allowed}",
            )
        return path, None

    def build_upload_path(self, filename, *, timestamp=None):
        original_name = os.path.basename(filename or "")
        original_stem, extension = os.path.splitext(original_name)
        extension = extension.lower()
        if extension not in self.video_extensions:
            return None, self._extension_error()

        stem = self.filename_sanitizer(original_stem) or "uploaded_video"
        stamp = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
        candidate = self._upload_candidate(stem, stamp, extension)
        counter = 1
        while os.path.exists(candidate):
            candidate = self._upload_candidate(
                stem,
                f"{stamp}_{counter}",
                extension,
            )
            counter += 1

        if not is_path_inside(candidate, [self.upload_directory]):
            return None, "Invalid upload filename"
        return candidate, None

    def _upload_candidate(self, stem, suffix, extension):
        return os.path.abspath(os.path.join(
            self.upload_directory,
            f"{stem}_{suffix}{extension}",
        ))

    def _extension_error(self):
        extensions = ", ".join(sorted(self.video_extensions))
        return f"Video file must use one of: {extensions}"
