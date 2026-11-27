"""Shared read-only schedule handoff facts and agent episode costs for CLI and Studio."""

import hashlib
import json
import stat
from pathlib import Path

from shorts_maker.services.operating_budget import episode_environment, episode_path, load_episode
from shorts_maker.services.scheduled_script_history import MissingRevisionCopy, current_revision_copy
from shorts_maker.utils.config import settings


def schedule_sha256(schedule: dict) -> str:
    return hashlib.sha256(json.dumps(schedule, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def episode_source_url(schedule: dict) -> str | None:
    """A choice carried by an older queue host is inert outside its original run."""
    run = schedule.get('episode_source_run_count')
    url = schedule.get('episode_source_url')
    return url if isinstance(url, str) and type(run) is int and run == schedule.get('run_count') else None


def read_episode_object(path: Path) -> tuple[bytes, dict]:
    """Read a bounded local record from an episode's managed output folder."""
    details = path.lstat()
    limit = 2 * 1024 * 1024
    if (not stat.S_ISREG(details.st_mode) or details.st_size > limit
            or not path.resolve().is_relative_to(settings.output_dir.resolve())):
        raise ValueError('회차 기록 파일을 확인할 수 없습니다.')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('회차 기록 파일을 확인할 수 없습니다.')
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError('회차 기록 파일을 확인할 수 없습니다.')
    return raw, document


def operator_status(schedule: dict) -> dict:
    result = {key: schedule.get(key) for key in (
        'id', 'name', 'enabled', 'first_run_at', 'frequency', 'last_result',
        'queued_at', 'scheduled_for', 'skipped_slots', 'run_count', 'last_episode_id',
        'last_video_path', 'last_youtube_id')}
    if schedule.get('review_continuation'):
        result['review_continuation'] = schedule['review_continuation']
    revisions = schedule.get('script_revisions')
    if isinstance(revisions, list) and any(isinstance(row, dict) and row.get('reassessment') for row in revisions):
        result['script_reassessment'] = True
    if schedule.get('planning_auth_required'):
        result['planning_auth_required'] = True
    if source := episode_source_url(schedule):
        result['episode_source_url'] = source
    if schedule.get('last_episode_id'):
        try:
            path = episode_path(schedule['last_episode_id'])
            pending = path.with_suffix('.operation.pending.json')
            result['operation_pending_unverified'] = pending.exists() or pending.is_symlink()
            if result['operation_pending_unverified']:
                try:
                    _, operation = read_episode_object(pending)
                    if operation.get('operation_kind') == 'planning':
                        result['operation_kind'] = 'planning'
                except (OSError, ValueError):
                    pass  # Keep the pending state even when its operation type cannot be read.
            script = path.with_suffix('.script.json')
            result['planned_script_path'] = str(script) if script.is_file() else None
            if schedule.get('review_operator') == 'agent':
                record = load_episode(schedule['last_episode_id'], schedule)
                result['budget'] = episode_environment(record)[1]
        except (ValueError, RuntimeError, OSError) as error:
            result['budget_error'] = str(error)
    if 'last_script_path' in schedule:
        result['planned_script_path'] = None
        try:
            result['planned_script_path'] = str(current_revision_copy(schedule))
        except MissingRevisionCopy as error:
            result.update(planned_script_error=str(error), planned_script_missing=True)
        except (OSError, ValueError, RuntimeError):
            result['planned_script_error'] = '현재 회차의 수정 대본 파일과 해시를 확인하세요.'
    return result
