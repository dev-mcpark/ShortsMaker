"""Recover completed edits and private uploads from the exact Studio episode."""

import hashlib
import json
from pathlib import Path

from shorts_maker.planner.models import ShortsScript
from shorts_maker.services.completed_video import completed_video
from shorts_maker.services.operating_budget import episode_path
from shorts_maker.services.operating_status import schedule_sha256
from shorts_maker.services.production_service import script_sha256
from shorts_maker.services.studio_episode_action import (
    EpisodeScope, action_directory, action_path, read_request, scope_status, validate_receipt, worker_command,
)
from shorts_maker.services.work_drafts import script_draft_key


def _completed_commands(episode_id: str) -> set[str]:
    base = episode_path(episode_id)
    hashes = set()
    for path in base.parent.glob(f'{base.stem}.operation.*.json'):
        if path.is_symlink() or path.name == f'{base.stem}.operation.pending.json':
            continue
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                continue
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if (isinstance(data, dict) and type(data.get('returncode')) is int and data['returncode'] == 0
                and isinstance(data.get('command_sha256'), str)):
            hashes.add(data['command_sha256'])
    return hashes


def _recovered_results(manager, expected_schedule, operation, verify_media):
    scope = EpisodeScope(schedules_file=str(manager.filename.resolve()), schedule_id=expected_schedule['id'],
                         episode_id=expected_schedule.get('last_episode_id'))
    current, _ = scope_status(scope)
    if current != expected_schedule:
        raise ValueError('회차 상태가 변경됐습니다. 예약 화면을 다시 확인하세요.')
    expected = schedule_sha256(current)
    script = ShortsScript.model_validate(current['last_script'])
    content_digest = script_sha256(script.model_dump(mode='json'))
    review_digest = script_draft_key(script)
    commands = _completed_commands(scope.episode_id)
    matches = {}
    if not commands:
        return matches
    for candidate in sorted(action_directory().glob('*.request.json')):
        try:
            path = action_path(candidate)
            if path.stat().st_size > 2 * 1024 * 1024:
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            command_digest = hashlib.sha256(json.dumps(worker_command(path, digest)).encode()).hexdigest()
            if command_digest not in commands:
                continue
            request = read_request(path, digest)
            if (request.operation != operation or request.scope != scope or request.schedule_sha256 != expected
                    or request.script_sha256 != content_digest or request.review_receipt != review_digest):
                continue
            receipt = validate_receipt(path, digest)
            if receipt['kind'] != 'production' or receipt.get('cancelled', False):
                continue
            result = receipt['value']
            if result['success'] and (info := verify_media(request, result)):
                matches[info['video_path']] = info
        except (OSError, ValueError, RuntimeError):
            continue
    if manager.get_schedule(scope.schedule_id) != current:
        raise ValueError('조회 중 회차 상태가 변경됐습니다. 예약 화면을 다시 확인하세요.')
    return matches


def recovered_review_copies(manager, expected_schedule: dict) -> dict[str, dict[str, str]]:
    """List confirmed local uploads without switching the current Studio workspace."""
    def verify_media(request, result):
        if (not request.video_path or result.get('video_path') != request.video_path
                or not result.get('youtube_id')):
            return None
        info = manager.pending_video_info(request.scope.schedule_id, request.video_path)
        return info if info['youtube_id'] == result['youtube_id'] else None

    return _recovered_results(manager, expected_schedule, 'upload', verify_media)


def recovered_episode_edits(manager, expected_schedule: dict) -> dict[str, dict[str, str]]:
    """List quality-passed local edits awaiting review and upload in this episode."""
    def verify_media(request, result):
        path = result.get('video_path')
        if not path or not result.get('ready_for_upload') or result.get('youtube_id'):
            return None
        video = Path(path).resolve()
        report_path = video.with_suffix('.production.json')
        upload_pending = video.with_suffix('.upload-pending.json')
        if (not result.get('report_path') or Path(result['report_path']).resolve() != report_path
                or report_path.is_symlink() or upload_pending.exists() or upload_pending.is_symlink()):
            return None
        report = completed_video(path)
        if (report.get('script_sha256') != request.script_sha256
                or report.get('source_url') != expected_schedule['last_script'].get('source_url')
                or report.get('youtube_id') or report.get('uploaded_at_utc') or report.get('youtube_upload_request')):
            return None
        return {'video_path': report['video_path'], 'video_sha256': report['video_sha256']}

    return _recovered_results(manager, expected_schedule, 'edit', verify_media)


def attach_recovered_review_copy(manager, schedule, expected: dict[str, str]):
    result = recovered_review_copies(manager, schedule).get(expected['video_path'])
    if result != expected:
        raise ValueError('저장된 업로드 기록이 변경됐습니다. 검토본을 다시 확인하세요.')
    return manager.record_private_review_copy(schedule['id'], expected['video_path'],
        expected_schedule_sha256=schedule_sha256(schedule), expected_video_info=expected)
