"""Fast checks on the rendered file before it can be uploaded."""

import numpy as np
from moviepy import VideoFileClip

from shorts_maker.utils.config import settings


def check_video_quality(path: str) -> None:
    clip = VideoFileClip(path)
    try:
        duration = clip.duration
        if not duration or duration < 1 or duration > settings.max_shorts_duration + 0.25:
            raise ValueError(f"영상 길이가 유효하지 않습니다: {duration}초")
        if abs(clip.w / clip.h - 9 / 16) > 0.01:
            raise ValueError(f"세로형 9:16 영상이 아닙니다: {clip.w}x{clip.h}")
        if clip.audio is None:
            raise ValueError("오디오 트랙이 없습니다")

        times = [min(duration - 0.01, duration * part) for part in (0.12, 0.25, 0.38, 0.5, 0.62, 0.75, 0.88)]
        if all(np.asarray(clip.get_frame(t)).mean() < 2 for t in times):
            raise ValueError("확인한 프레임이 모두 검은 화면입니다")
        if all(
            np.square(np.asarray(clip.audio.get_frame(t + offset), dtype=float)).mean() < 1e-6
            for t in times for offset in (0, 0.013, 0.029)
        ):
            raise ValueError("확인한 오디오가 모두 무음입니다")
    finally:
        clip.close()
