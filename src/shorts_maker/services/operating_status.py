"""Shared read-only schedule handoff facts and agent episode costs for CLI and Studio."""

import hashlib
import json
from pathlib import Path

from shorts_maker.services.operating_budget import episode_environment, episode_path, load_episode


def schedule_sha256(schedule: dict) -> str:
    return hashlib.sha256(json.dumps(schedule, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def operator_status(schedule: dict) -> dict:
    result = {key: schedule.get(key) for key in (
        'id', 'name', 'enabled', 'first_run_at', 'frequency', 'last_result',
        'queued_at', 'scheduled_for', 'skipped_slots', 'run_count', 'last_episode_id',
        'last_video_path', 'last_youtube_id')}
    if schedule.get('review_continuation'):
        result['review_continuation'] = schedule['review_continuation']
    if schedule.get('last_episode_id'):
        try:
            path = episode_path(schedule['last_episode_id'])
            result['operation_pending_unverified'] = path.with_suffix('.operation.pending.json').exists()
            script = path.with_suffix('.script.json')
            result['planned_script_path'] = str(script) if script.is_file() else None
            if schedule.get('review_operator') == 'agent':
                record = load_episode(schedule['last_episode_id'], schedule)
                result['budget'] = episode_environment(record)[1]
        except (ValueError, RuntimeError, OSError) as error:
            result['budget_error'] = str(error)
    if 'last_script_path' in schedule:
        from shorts_maker.services.production_service import script_sha256
        from shorts_maker.utils.config import settings
        result['planned_script_path'] = None
        try:
            script = Path(schedule['last_script_path'])
            if script.is_symlink() or not script.resolve().is_relative_to(settings.output_dir.resolve()):
                raise ValueError('invalid current script path')
            stored = json.loads(script.read_text(encoding='utf-8'))
            if not isinstance(stored, dict) or script_sha256(stored) != script_sha256(schedule['last_script']):
                raise ValueError('current script hash mismatch')
            result['planned_script_path'] = str(script.resolve())
        except (OSError, TypeError, ValueError, KeyError):
            result['planned_script_error'] = '현재 회차의 수정 대본 파일·해시를 확인하세요. 이전 원본 파일로 대체하지 않습니다.'
    return result
