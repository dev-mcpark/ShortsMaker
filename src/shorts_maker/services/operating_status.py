"""Shared read-only schedule handoff facts and agent episode costs for CLI and Studio."""

from shorts_maker.services.operating_budget import episode_environment, episode_path, load_episode


def operator_status(schedule: dict) -> dict:
    result = {key: schedule.get(key) for key in (
        'id', 'name', 'enabled', 'first_run_at', 'frequency', 'last_result',
        'queued_at', 'scheduled_for', 'skipped_slots', 'run_count', 'last_episode_id',
        'last_video_path', 'last_youtube_id')}
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
    return result
