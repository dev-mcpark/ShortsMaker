"""Local decode gates shared by material review and production preflight."""

import hashlib
from io import BytesIO
from pathlib import Path
from moviepy import VideoFileClip
from PIL import Image

MAX_FRAME_BYTES = 20_000_000


def inspect_frame_bytes(content: bytes) -> tuple[str, str]:
    if not content or len(content) > MAX_FRAME_BYTES:
        raise ValueError('첫 프레임은 20 MB 이하의 PNG/JPEG 파일이어야 합니다.')
    try:
        with Image.open(BytesIO(content)) as image:
            mime = Image.MIME.get(image.format)
            if (mime not in {'image/png', 'image/jpeg'} or image.width < 360 or image.height < 640
                    or abs(image.width / image.height - 9 / 16) > 0.02):
                raise ValueError('첫 프레임은 최소 360×640의 세로 9:16 PNG/JPEG 이미지여야 합니다.')
            image.verify()
        # JPEG verify only checks headers; decode the exact bytes that will be submitted.
        with Image.open(BytesIO(content)) as image:
            image.load()
    except Image.DecompressionBombError as error:
        raise ValueError('이미지 픽셀 크기가 너무 큽니다. 크기를 줄여 다시 선택하세요.') from error
    except (OSError, SyntaxError) as error:
        raise ValueError('이미지를 읽을 수 없습니다. 손상되지 않은 PNG/JPEG를 선택하세요.') from error
    return hashlib.sha256(content).hexdigest(), mime


def is_playable_video(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        with VideoFileClip(str(path)) as clip:
            return clip.duration > 0 and clip.get_frame(0) is not None
    except Exception:
        return False
