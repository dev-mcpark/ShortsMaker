"""Private publishing text snapshots; never alter production or upload records."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shorts_maker.services.draft_store import publish_snapshot, read_snapshot, snapshot_paths
from shorts_maker.utils.config import settings


class PublishingFields(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    title: str
    description: str
    tags: str
    disclosure: Literal['yes', 'no'] | None


class PublishingDraft(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    saved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    video_path: str
    video_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    fields: PublishingFields

    @model_validator(mode='after')
    def validate_identity(self):
        video = Path(self.video_path)
        if (str(video.resolve()) != self.video_path or video.suffix.lower() != '.mp4'
                or not video.resolve().is_relative_to(settings.output_dir.resolve())
                or self.saved_at.tzinfo is None or self.saved_at.utcoffset() is None):
            raise ValueError('게시 초안의 영상 경로·저장 시각을 확인하세요.')
        return self


def publishing_key(report: dict) -> str:
    return f"{report['video_path']}:{report['video_sha256']}"


def save_publishing_draft(report: dict, fields: dict) -> Path:
    record = PublishingDraft(video_path=report['video_path'], video_sha256=report['video_sha256'],
                             fields=PublishingFields.model_validate(fields))
    return publish_snapshot('publishing_drafts', record.model_dump_json(indent=2).encode('utf-8'))


def read_publishing_draft(name: str) -> tuple[PublishingDraft, str]:
    content, digest = read_snapshot('publishing_drafts', name)
    try:
        record = PublishingDraft.model_validate_json(content)
    except ValueError:
        raise ValueError('게시 초안의 형식이 올바르지 않습니다. 파일과 현재 입력은 유지됩니다.') from None
    return record, digest


def saved_publishing_drafts(report: dict) -> tuple[dict[str, str], dict[str, str], list[str]]:
    choices, digests, warnings = {}, {}, []
    records = []
    for path in snapshot_paths('publishing_drafts'):
        try:
            record, digest = read_publishing_draft(path.name)
            if publishing_key(record.model_dump()) == publishing_key(report):
                records.append((record.saved_at, path.name, record, digest))
        except (OSError, ValueError):
            warnings.append(f'{path.name}: 읽을 수 없는 게시 초안은 유지했습니다.')
    for _, name, record, digest in sorted(records, reverse=True):
        choices[name] = f"{record.fields.title or '제목 미입력'} · {record.saved_at.astimezone():%m/%d %H:%M:%S} · {name[-13:-5]}"
        digests[name] = digest
    return choices, digests, warnings


def restore_publishing_draft(report: dict, name: str, expected_digest: str,
                             current: dict, recorded: dict) -> tuple[dict, Path | None]:
    record, digest = read_publishing_draft(name)
    if digest != expected_digest or publishing_key(record.model_dump()) != publishing_key(report):
        raise ValueError('영상 또는 게시 초안이 바뀌었습니다. 목록을 다시 불러오세요.')
    fields = record.fields.model_dump()
    backup = save_publishing_draft(report, current) if current != fields and current != recorded else None
    return fields, backup
