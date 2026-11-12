"""Cheap local decode gate shared by clip import and production preflight."""

from pathlib import Path
from moviepy import VideoFileClip


def is_playable_video(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        with VideoFileClip(str(path)) as clip:
            return clip.duration > 0 and clip.get_frame(0) is not None
    except Exception:
        return False
