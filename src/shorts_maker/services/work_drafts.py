"""Explicit, private text-work snapshots; no credentials, approvals or provider state."""

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shorts_maker.planner.models import ShortsScript
from shorts_maker.services.draft_store import publish_snapshot, read_snapshot, snapshot_paths


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
    planning_input: dict[str, str] | None = None

    @model_validator(mode='after')
    def verify_binding(self):
        if self.saved_at.tzinfo is None or self.script_sha256 != script_draft_key(self.applied_script):
            raise ValueError('초안의 날짜·원래 대본 해시를 확인하세요.')
        numbers = {str(s.scene_number) for s in self.applied_script.scenes} if self.applied_script else set()
        if (not self.first_frames.keys() <= numbers or any(not values.keys() <= {
                'frame_path', 'must_show', 'must_avoid', 'reviewer_note'} for values in self.first_frames.values())):
            raise ValueError('초안의 장면 번호·검토 입력을 확인하세요.')
        if self.planning_input is not None and (
                set(self.planning_input) != {'mode', 'url', 'category'}
                or self.planning_input['mode'] not in {'RSS 자동 발견', '직접 URL 입력'}):
            raise ValueError('초안의 기획 입력 형식을 확인하세요.')
        return self


def save_work_draft(script: ShortsScript | None, editor_text: str, first_frames: dict,
                    *, planning_input: dict | None = None) -> Path:
    record = WorkDraft(saved_at=datetime.now(timezone.utc), script_sha256=script_draft_key(script),
                       applied_script=script, editor_text=editor_text,
                       first_frames={str(number): values for number, values in first_frames.items()},
                       planning_input=planning_input)
    exclude = {'planning_input'} if planning_input is None else set()
    return publish_snapshot('studio_drafts', record.model_dump_json(indent=2, exclude=exclude).encode('utf-8'))


def read_work_draft(name: str) -> tuple[WorkDraft, str]:
    content, digest = read_snapshot('studio_drafts', name)
    try:
        record = WorkDraft.model_validate_json(content)
    except ValueError as error:
        raise ValueError('초안 형식·원래 대본 해시·장면 구성을 확인하세요. 원래 파일은 유지됩니다.') from error
    return record, digest


def saved_work_drafts() -> tuple[dict, list]:
    records, warnings = [], []
    for path in snapshot_paths('studio_drafts'):
        try:
            record, digest = read_work_draft(path.name)
            title = record.applied_script.title if record.applied_script else '새 대본 입력 초안'
            if record.applied_script is None and not record.editor_text.strip() and record.planning_input:
                title = f'소재 선택 · {(record.planning_input["url"] or record.planning_input["category"])[:100]}'
            records.append((path.stat().st_mtime_ns, path.name, {
                'label': f'{title} · {record.saved_at.astimezone():%Y-%m-%d %H:%M:%S} · {path.stem[-8:]}',
                'sha256': digest}))
        except (OSError, ValueError) as error:
            warnings.append(f'{path.name}: 기록 확인 필요 ({type(error).__name__})')
    return {name: value for _, name, value in sorted(records, reverse=True)}, warnings
