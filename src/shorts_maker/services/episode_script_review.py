"""Retain Studio's explicit confirmation of an exact scheduled script."""

import hashlib
import json

from shorts_maker.planner.models import ShortsScript
from shorts_maker.services.operating_budget import episode_path
from shorts_maker.services.operating_status import read_episode_object
from shorts_maker.services.studio_episode_action import EpisodeScope, scope_status, write_message
from shorts_maker.services.work_drafts import script_draft_key
from shorts_maker.utils.config import settings
from shorts_maker.utils.scheduler import ScheduleManager


def _receipt(scope: EpisodeScope, schedule: dict, script: ShortsScript):
    payload = {
        'schema_version': 1,
        'kind': 'studio_script_confirmation',
        'scope': scope.model_dump(),
        'revision_path': schedule.get('last_script_path'),
        'script_review_sha256': script_draft_key(script),
    }
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    path = episode_path(scope.episode_id).with_suffix(f'.script-review.{identity}.json')
    return path, payload


def saved_episode_script_review(scope: EpisodeScope, schedule: dict, script: ShortsScript) -> str | None:
    """Return only the receipt for the already verified current episode and script."""
    path, expected = _receipt(scope, schedule, script)
    try:
        _, saved = read_episode_object(path)
    except (OSError, ValueError):
        return None
    if saved == expected and type(saved['schema_version']) is int:
        return saved['script_review_sha256']
    return None


def retain_episode_script_review(scope: EpisodeScope, script: ShortsScript, *, expected_schedule: dict | None = None) -> bool:
    """Save a confirmation only for the current saved script, not an unsaved revision."""
    manager = ScheduleManager(scope.schedules_file, queue_only=True)
    with manager._review_transition_lock():
        schedule, _ = scope_status(scope)
        if expected_schedule is not None and schedule != expected_schedule:
            raise ValueError('회차가 바뀌었습니다. 저장한 대본을 다시 확인하세요.')
        if script.model_dump(mode='json') != schedule['last_script']:
            return False
        path, payload = _receipt(scope, schedule, script)
        if path.is_symlink() or not path.parent.resolve().is_relative_to(settings.output_dir.resolve()):
            raise ValueError('각본 확인 기록의 경로를 확인하세요.')
        if saved_episode_script_review(scope, schedule, script) is None:
            write_message(path, payload)
        return True
