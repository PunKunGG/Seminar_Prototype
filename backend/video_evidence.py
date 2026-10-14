"""Local source bindings; never serialize these records into public report JSON."""

import os
import stat

from video_source_policy import is_path_inside


def file_identity(metadata):
    return {"size": metadata.st_size, "mtime_ns": metadata.st_mtime_ns,
            "inode": metadata.st_ino, "device": metadata.st_dev}


def bind_video_source(path):
    resolved = os.path.realpath(path)
    metadata = os.stat(resolved)
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Video source must be a regular file")
    return {"path": resolved, "identity": file_identity(metadata)}


def open_bound_video(binding, roots):
    """Validate the actual open file, not just its name before a second open."""
    if not binding:
        return None, "unbound"
    path = binding.get("path")
    if not isinstance(path, str) or not os.path.isabs(path):
        return None, "invalid_source"
    resolved = os.path.realpath(path)
    allowed = [os.path.realpath(root) for root in roots]
    if resolved != path or not is_path_inside(resolved, allowed):
        return None, "invalid_source"
    try:
        handle = open(resolved, "rb")
    except (OSError, ValueError):
        return None, "missing"
    metadata = os.fstat(handle.fileno())
    if not stat.S_ISREG(metadata.st_mode) or file_identity(metadata) != binding.get("identity"):
        handle.close()
        return None, "changed"
    return handle, None
