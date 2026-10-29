"""Local verdict bound to one silent generated Veo scene clip."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from moviepy import VideoFileClip

from shorts_maker.services.visual_review import verified_first_frame
from shorts_maker.utils.config import settings


def _hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _review_path(clip_path: str) -> Path:
    path = Path(clip_path).resolve()
    if (path.name != 'clip.mp4' or not path.is_relative_to(settings.clips_dir.resolve())):
        raise ValueError('원본 검토는 저장된 Veo 장면 클립에만 적용됩니다.')
    return path.with_suffix('.review.json')


def _binding(script, scene, clip_path: str, frame_sha256: str) -> dict:
    clip = Path(clip_path).resolve()
    return {
        'schema_version': 1,
        'script_sha256': hashlib.sha256(script.model_dump_json().encode('utf-8')).hexdigest(),
        'scene_number': scene.scene_number,
        'first_frame_sha256': frame_sha256,
        'clip_sha256': _hash(clip),
    }


def save_raw_verdict(script, scene, clip_path: str, frame_sha256: str,
                     decision: str, note: str) -> Path:
    path = _review_path(clip_path)
    if decision not in {'approved', 'rejected'} or not isinstance(note, str) or not note.strip():
        raise ValueError('원본 승인 또는 제외 판정과 검토 의견이 필요합니다.')
    if verified_first_frame(script, scene)[1] != frame_sha256:
        raise ValueError('원본 판정에 연결된 첫 프레임이 다릅니다.')
    with VideoFileClip(clip_path) as clip:
        width, height = clip.size
        if (clip.duration <= 0 or clip.audio is not None or width < 360 or height < 640
                or abs(width / height - 9 / 16) > 0.02):
            raise ValueError('검토할 세로 9:16 무음 Veo 원본이 아닙니다.')
    record = {**_binding(script, scene, clip_path, frame_sha256),
              'decision': decision, 'reviewer_note': note.strip()}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', delete=False) as file:
            temporary = Path(file.name)
            json.dump(record, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return path


def raw_review_status(script, scene, clip_path: str, frame_sha256: str) -> str:
    try:
        if verified_first_frame(script, scene)[1] != frame_sha256:
            return 'stale'
        path = _review_path(clip_path)
        record = json.loads(path.read_text(encoding='utf-8'))
        expected = _binding(script, scene, clip_path, frame_sha256)
    except (OSError, ValueError, KeyError, TypeError):
        return 'pending'
    if (not isinstance(record, dict)
            or any(record.get(key) != value for key, value in expected.items())
            or not isinstance(record.get('reviewer_note'), str)
            or not record['reviewer_note'].strip()):
        return 'stale'
    return record.get('decision') if record.get('decision') in {'approved', 'rejected'} else 'pending'


def verified_raw_clip(script, scene, clip_path: str, frame_sha256: str) -> str:
    if raw_review_status(script, scene, clip_path, frame_sha256) != 'approved':
        raise ValueError(f'RAW_CLIP_REVIEW_REQUIRED: 씬 {scene.scene_number}의 무음 원본 판정이 없거나 변경됐습니다.')
    return _hash(Path(clip_path))
