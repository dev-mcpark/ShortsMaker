"""Read retained script versions; their hashes grant no review or spending authority."""

import json
import os
import stat
from pathlib import Path

from shorts_maker.planner.models import ShortsScript
from shorts_maker.services.production_service import script_sha256
from shorts_maker.services.script_store import save_script_copy
from shorts_maker.services.work_drafts import script_draft_key
from shorts_maker.utils.config import settings


class MissingRevisionCopy(ValueError):
    """The current revision pointer was valid but its local file was missing."""


def _revision_path(schedule: dict) -> Path:
    pointer = schedule.get('last_script_path')
    if not isinstance(pointer, str) or not pointer:
        raise ValueError('현재 회차의 수정 대본 파일 경로를 확인하세요.')
    path = Path(pointer)
    if (not path.is_absolute() or path.suffix != '.json' or path.is_symlink()
            or not path.resolve().is_relative_to(settings.output_dir.resolve())):
        raise ValueError('현재 회차의 수정 대본 파일 경로를 확인하세요.')
    return path


def current_revision_copy(schedule: dict) -> Path | None:
    """Verify an explicit revision pointer with no fallback to an older copy."""
    if 'last_script_path' not in schedule:
        return None
    path = _revision_path(schedule)
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise MissingRevisionCopy('현재 회차의 수정 대본 파일이 없습니다.') from error
    limit = 2 * 1024 * 1024
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise ValueError('현재 회차의 수정 대본 파일 형식을 확인하세요.')
    with path.open('rb') as file:
        content = file.read(limit + 1)
    if len(content) > limit:
        raise ValueError('현재 회차의 수정 대본 파일 크기를 확인하세요.')
    try:
        script = json.loads(content)
    except ValueError as error:
        raise ValueError('현재 회차의 수정 대본 파일을 읽을 수 없습니다.') from error
    if (not isinstance(script, dict) or not isinstance(schedule.get('last_script'), dict)
            or script_sha256(script) != script_sha256(schedule['last_script'])):
        raise ValueError('현재 회차의 수정 대본 파일 해시가 일치하지 않습니다.')
    return path.resolve()


def validated_revisions(current: dict, history: list) -> list[dict]:
    if not isinstance(current, dict) or not isinstance(history, list) or any(not isinstance(row, dict) for row in history):
        raise ValueError('기존 각본 수정 이력을 확인하세요. 덮어쓰지 않습니다.')
    previous = script_sha256(current)
    for row in reversed(history):
        if (not isinstance(row.get('script'), dict) or row.get('replacement_sha256') != previous
                or row.get('script_sha256') != script_sha256(row['script'])):
            raise ValueError('각본 수정 이력의 해시가 일치하지 않습니다. 원래 기록은 유지됩니다.')
        previous = row['script_sha256']
    return history


def restore_missing_revision_copy(manager, expected: dict) -> Path:
    """Restore the exact saved revision without changing any episode references."""
    with manager._review_transition_lock():
        current = manager.get_schedule(expected['id'])
        if (current != expected or current.get('enabled')
                or current.get('last_result') != 'script_review_pending'
                or current.get('last_video_path') or current.get('last_youtube_id')):
            raise ValueError('미첨부 각본 검토 회차가 바뀌었습니다. 예약 화면을 다시 확인하세요.')
        path = _revision_path(current)
        directory = settings.output_dir.resolve() / 'evaluation' / 'scheduled_script_revisions'
        if path.parent != directory or directory.resolve() != directory or not directory.is_dir():
            raise ValueError('Studio에서 관리하는 수정 대본 파일만 복원할 수 있습니다.')
        try:
            current_revision_copy(current)
        except MissingRevisionCopy:
            pass
        else:
            raise ValueError('수정 대본 파일이 이미 있습니다. 기존 파일은 유지합니다.')
        saved = current.get('last_script')
        history = validated_revisions(saved, current.get('script_revisions', []))
        script = ShortsScript.model_validate(saved)
        if (not history or history[-1].get('review_receipt_sha256') != script_draft_key(script)
                or script_sha256(script.model_dump(mode='json')) != script_sha256(saved)):
            raise ValueError('수정 대본과 이전 검토 기록이 일치하지 않아 복원할 수 없습니다.')
        copy = save_script_copy(script, directory)
        try:
            os.link(copy, path)  # Publish the revision only if the original name is still absent.
        except FileExistsError as error:
            raise ValueError('수정 대본 파일이 이미 있습니다. 기존 파일은 유지합니다.') from error
        finally:
            copy.unlink(missing_ok=True)
        return path


def script_versions(run: dict) -> list[dict]:
    current = run.get('last_script')
    history = run.get('script_revisions', [])
    if current is None and history == []:
        return []
    history = validated_revisions(current, history)
    versions = [{'label': '이 회차의 마지막 저장본', 'script': current}, *[
        {'label': f'수정 전 대본 {index + 1} · {row.get("replaced_at") or "변경 시각 기록 없음"}', 'script': row['script']}
        for index, row in reversed(list(enumerate(history)))]]
    for version in versions:
        try:
            version['script'] = ShortsScript.model_validate(version['script'])
        except ValueError as error:
            raise ValueError('보관된 전체 대본 형식을 확인하세요. 일부 기록을 추측해 복구하지 않습니다.') from error
    return versions
