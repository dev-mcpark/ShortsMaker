"""Local, source-bound first-frame approval for new Veo scene requests."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from shorts_maker.generator.video_generator import VIDEO_PROMPT_VERSION
from shorts_maker.utils.config import settings
from shorts_maker.utils.media_validation import MAX_FRAME_BYTES, inspect_frame_bytes
from shorts_maker.utils.source_manager import SourceManager


def review_path(script, scene) -> Path:
    script_hash = hashlib.sha256(script.model_dump_json().encode('utf-8')).hexdigest()[:20]
    return settings.output_dir / 'evaluation' / 'visual_reviews' / f'{script_hash}_scene_{scene.scene_number}.json'


def inspect_frame(frame_path: str) -> str:
    path = Path(frame_path).resolve()
    if not path.is_file() or path.stat().st_size > MAX_FRAME_BYTES:
        raise ValueError('첫 프레임은 20 MB 이하의 PNG/JPEG 파일이어야 합니다.')
    with path.open('rb') as stream:
        return inspect_frame_bytes(stream.read(MAX_FRAME_BYTES + 1))[0]


def import_frame(content: bytes) -> Path:
    """Retain a validated local image without replacing a frame or its approval."""
    _, mime = inspect_frame_bytes(content)
    root = settings.output_dir / 'evaluation' / 'imported_frames'
    if (root.is_symlink() or root.parent.is_symlink()
            or not root.resolve().is_relative_to(settings.output_dir.resolve())):
        raise ValueError('이미지 보관 폴더의 경로를 확인하세요.')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=root, prefix='.frame_', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        suffix = '.png' if mime == 'image/png' else '.jpg'
        path = root / f'frame_{uuid4().hex}{suffix}'
        os.link(temporary, path)
        return path
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _binding(script, scene, frame_path: str, frame_sha256: str) -> dict:
    return {
        'scene_number': scene.scene_number,
        'source_urls': [script.source_url, *script.supporting_source_urls],
        'script_text': scene.script_text,
        'visual_description': scene.visual_description,
        'motion_instruction': scene.motion_instruction,
        'prompt_version': VIDEO_PROMPT_VERSION,
        'frame_path': str(Path(frame_path).resolve()),
        'frame_sha256': frame_sha256,
    }


def approve_first_frame(script, scene, frame_path: str, must_show: list[str],
                        must_avoid: list[str], reviewer_note: str,
                        preview_sha256: str) -> Path:
    if any(not SourceManager.is_allowed_url(url)
           for url in [script.source_url, *script.supporting_source_urls]):
        raise ValueError('공개 출처 URL이 확인된 각본만 첫 프레임을 승인할 수 있습니다.')
    if not all(isinstance(items, list) and items and all(
        isinstance(item, str) and item.strip() for item in items
    ) for items in (must_show, must_avoid)) or not isinstance(reviewer_note, str) or not reviewer_note.strip():
        raise ValueError('보여야 할 내용, 피할 내용, 검토 의견이 모두 필요합니다.')
    current_hash = inspect_frame(frame_path)
    if current_hash != preview_sha256:
        raise ValueError('미리보기 이후 첫 프레임이 변경됐습니다. 다시 확인하세요.')
    path = review_path(script, scene)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {**_binding(script, scene, frame_path, current_hash),
              'must_show': must_show, 'must_avoid': must_avoid,
              'reviewer_note': reviewer_note.strip(), 'decision': 'approved'}
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


def verified_first_frame(script, scene) -> tuple[str, str]:
    path = review_path(script, scene)
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
        frame_path = record['frame_path']
        frame_sha256 = inspect_frame(frame_path)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f'FIRST_FRAME_REVIEW_REQUIRED: 씬 {scene.scene_number}의 승인된 첫 프레임이 없습니다.') from error
    if (not isinstance(record, dict) or record.get('decision') != 'approved'
            or any(record.get(key) != value for key, value in _binding(
                script, scene, frame_path, frame_sha256,
            ).items())
            or not all(isinstance(record.get(key), list) and record[key] and all(
                isinstance(item, str) and item.strip() for item in record[key]
            ) for key in ('must_show', 'must_avoid'))
            or not isinstance(record.get('reviewer_note'), str)
            or not record['reviewer_note'].strip()):
        raise ValueError(f'FIRST_FRAME_REVIEW_REQUIRED: 씬 {scene.scene_number}의 검토 기록이 변경됐습니다.')
    return frame_path, frame_sha256
