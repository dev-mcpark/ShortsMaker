"""Explicit, private text-work snapshots; no credentials, approvals or provider state."""

import hashlib
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shorts_maker.planner.models import ShortsScript
from shorts_maker.utils.config import settings


_MAX_BYTES = 2 * 1024 * 1024
_NAME = re.compile(r'draft_\d{8}T\d{6}Z_[0-9a-f]{32}\.json')


def script_draft_key(script: ShortsScript | None) -> str:
    return hashlib.sha256((script.model_dump_json() if script else '').encode('utf-8')).hexdigest()


class WorkDraft(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    saved_at: datetime
    script_sha256: str
    applied_script: ShortsScript | None
    editor_text: str
    first_frames: dict[str, dict[str, str]] = Field(default_factory=dict)

    @model_validator(mode='after')
    def verify_binding(self):
        if self.saved_at.tzinfo is None or self.script_sha256 != script_draft_key(self.applied_script):
            raise ValueError('초안의 날짜·원래 대본 해시를 확인하세요.')
        numbers = {str(s.scene_number) for s in self.applied_script.scenes} if self.applied_script else set()
        if (not self.first_frames.keys() <= numbers or any(not values.keys() <= {
                'frame_path', 'must_show', 'must_avoid', 'reviewer_note'} for values in self.first_frames.values())):
            raise ValueError('초안의 장면 번호·검토 입력을 확인하세요.')
        return self


def _directory() -> Path:
    root = settings.output_dir / 'evaluation' / 'studio_drafts'
    if (root.is_symlink() or root.parent.is_symlink()
            or not root.resolve().is_relative_to(settings.output_dir.resolve())):
        raise ValueError('초안 보관 폴더의 경로를 확인하세요.')
    return root


def save_work_draft(script: ShortsScript | None, editor_text: str, first_frames: dict) -> Path:
    record = WorkDraft(saved_at=datetime.now(timezone.utc), script_sha256=script_draft_key(script),
                       applied_script=script, editor_text=editor_text,
                       first_frames={str(number): values for number, values in first_frames.items()})
    content = record.model_dump_json(indent=2).encode('utf-8')
    if len(content) > _MAX_BYTES:
        raise ValueError('작업 초안은 2 MiB 이하로 저장하세요. 현재 입력은 유지됩니다.')
    root = _directory()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / f'draft_{record.saved_at:%Y%m%dT%H%M%SZ}_{uuid4().hex}.json'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=root, prefix='.draft_', suffix='.tmp', delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.link(temporary, path)  # Publish atomically without replacing an older snapshot.
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return path


def read_work_draft(name: str) -> tuple[WorkDraft, str]:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError('저장된 작업 초안을 목록에서 선택하세요.')
    path = _directory() / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_BYTES:
        raise ValueError('초안 파일의 경로·크기를 확인하세요.')
    with path.open('rb') as file:
        content = file.read(_MAX_BYTES + 1)
    if len(content) > _MAX_BYTES:
        raise ValueError('초안 파일은 2 MiB 이하여야 합니다.')
    try:
        record = WorkDraft.model_validate_json(content)
    except ValueError as error:
        raise ValueError('초안 형식·원래 대본 해시·장면 구성을 확인하세요. 원래 파일은 유지됩니다.') from error
    return record, hashlib.sha256(content).hexdigest()


def saved_work_drafts() -> tuple[dict, list]:
    records, warnings = [], []
    try:
        paths = [path for path in _directory().iterdir() if path.name.startswith('draft_') and path.suffix == '.json']
    except FileNotFoundError:
        return {}, []
    for path in paths:
        try:
            record, digest = read_work_draft(path.name)
            title = record.applied_script.title if record.applied_script else '새 대본 입력 초안'
            records.append((path.stat().st_mtime_ns, path.name, {
                'label': f'{title} · {record.saved_at.astimezone():%Y-%m-%d %H:%M:%S} · {path.stem[-8:]}',
                'sha256': digest}))
        except (OSError, ValueError) as error:
            warnings.append(f'{path.name}: 기록 확인 필요 ({type(error).__name__})')
    return {name: value for _, name, value in sorted(records, reverse=True)}, warnings
