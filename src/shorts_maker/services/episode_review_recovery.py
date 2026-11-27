"""Recover completed planning, edits and private uploads from the exact Studio episode."""

import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from shorts_maker.planner.models import ShortsScript
from shorts_maker.services.completed_video import completed_video
from shorts_maker.services.operating_budget import episode_path
from shorts_maker.services.operating_status import episode_source_url, read_episode_object, schedule_sha256
from shorts_maker.services.production_service import script_sha256
from shorts_maker.services.scheduled_planning import planning_worker_command
from shorts_maker.services.studio_episode_action import (
    EpisodeScope, action_directory, action_path, read_request, scope_status, validate_receipt, worker_command,
)
from shorts_maker.services.work_drafts import script_draft_key
from shorts_maker.utils.source_manager import SourceManager


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


def _recovered_results(manager, expected_schedule, operations, verify_media, *, reaped_command=None):
    scope = EpisodeScope(schedules_file=str(manager.filename.resolve()), schedule_id=expected_schedule['id'],
                         episode_id=expected_schedule.get('last_episode_id'))
    current, _ = scope_status(scope, child=reaped_command is not None)
    if current != expected_schedule:
        raise ValueError('회차 상태가 변경됐습니다. 예약 화면을 다시 확인하세요.')
    expected = schedule_sha256(current)
    script = ShortsScript.model_validate(current['last_script'])
    content_digest = script_sha256(script.model_dump(mode='json'))
    review_digest = script_draft_key(script)
    commands = {reaped_command} if reaped_command else _completed_commands(scope.episode_id)
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
            if (request.operation not in operations or request.scope != scope or request.schedule_sha256 != expected
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
    return _recovered_uploads(manager, expected_schedule)


def _recovered_uploads(manager, expected_schedule, reaped_command=None):
    def verify_media(request, result):
        if (not request.video_path or result.get('video_path') != request.video_path
                or not result.get('youtube_id')):
            return None
        if reaped_command is None:
            info = manager.pending_video_info(request.scope.schedule_id, request.video_path)
        else:
            video, digest, video_id = manager._verified_uploaded_file(expected_schedule, request.video_path)
            info = {'video_path': str(video), 'video_sha256': digest, 'youtube_id': video_id}
        if (info['youtube_id'] != result['youtube_id']
                or (request.video_sha256 is not None and info['video_sha256'] != request.video_sha256)):
            return None
        return info

    return _recovered_results(manager, expected_schedule, {'upload'}, verify_media, reaped_command=reaped_command)


def _reaped_operation_audit(path: Path, *, planning: bool = False) -> tuple[str, str]:
    raw, audit = read_episode_object(path)
    command, pid = audit.get('command_sha256'), audit.get('studio_parent_pid')
    if planning and audit.get('operation_kind') != 'planning':
        raise ValueError('같은 회차의 기획 실행 기록이 필요합니다.')
    if (type(audit.get('returncode')) is not int or audit['returncode'] != 0
            or type(pid) is not int or not 1 < pid <= 2**31 - 1
            or not isinstance(command, str) or not re.fullmatch(r'[0-9a-f]{64}', command)):
        raise ValueError('정상 종료한 실행 기록이 없습니다. 실행 결과를 먼저 대조하세요.')
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return hashlib.sha256(raw).hexdigest(), command
    except PermissionError:
        pass
    raise ValueError('작업을 실행한 프로세스가 종료됐는지 확인할 수 없습니다.')


def preview_reaped_upload(manager, schedule) -> tuple[str, dict[str, str]]:
    pending = episode_path(schedule.get('last_episode_id')).with_suffix('.operation.pending.json')
    digest, command = _reaped_operation_audit(pending)
    matches = _recovered_uploads(manager, schedule, reaped_command=command)
    if len(matches) != 1:
        raise ValueError('회차의 요청·업로드 결과·영상이 일치하지 않습니다. YouTube Studio에서 결과를 먼저 대조하세요.')
    if _reaped_operation_audit(pending) != (digest, command):
        raise ValueError('회차 대기 기록이 조회 중 변경됐습니다.')
    return digest, next(iter(matches.values()))


def _archive_reaped_operation(manager, schedule, expected, verify) -> None:
    with manager._review_transition_lock():
        if verify(manager, schedule) != expected:
            raise ValueError('회차 실행 기록 또는 결과가 변경됐습니다. 다시 확인하세요.')
        base = episode_path(schedule['last_episode_id'])
        base.with_suffix('.operation.pending.json').rename(base.with_suffix(f'.operation.{uuid4().hex}.json'))


def archive_reaped_upload(manager, schedule, expected: tuple[str, dict[str, str]]) -> None:
    """Move a confirmed, exited upload audit to history, leaving attachment separate."""
    _archive_reaped_operation(manager, schedule, expected, preview_reaped_upload)


def preview_reaped_planning(manager, schedule) -> tuple[str, dict[str, str]]:
    scope = EpisodeScope(schedules_file=str(manager.filename.resolve()), schedule_id=schedule['id'],
                         episode_id=schedule.get('last_episode_id'))
    current, _ = scope_status(scope, child=True)
    if current != schedule:
        raise ValueError('회차 상태가 변경됐습니다. 예약 화면을 다시 확인하세요.')
    base = episode_path(scope.episode_id)
    pending = base.with_suffix('.operation.pending.json')
    digest, command = _reaped_operation_audit(pending, planning=True)
    fixed = planning_worker_command(manager, scope.schedule_id)
    if command != hashlib.sha256(json.dumps(fixed).encode()).hexdigest():
        raise ValueError('같은 회차의 기획 실행 기록이 필요합니다.')
    raw, saved = read_episode_object(base.with_suffix('.script.json'))
    script = ShortsScript.model_validate(saved)
    selected_source = episode_source_url(current)
    if (script_sha256(saved) != script_sha256(current['last_script'])
            or not script.source_url or not SourceManager.is_allowed_url(script.source_url)
            or (selected_source and selected_source != script.source_url)):
        raise ValueError('저장된 기획 대본·출처와 현재 회차가 일치하지 않습니다.')
    if (manager.get_schedule(scope.schedule_id) != current
            or _reaped_operation_audit(pending, planning=True) != (digest, command)):
        raise ValueError('회차 실행 기록이 조회 중 변경됐습니다.')
    return digest, {'title': script.title, 'source_url': script.source_url,
                    'script_file_sha256': hashlib.sha256(raw).hexdigest()}


def archive_reaped_planning(manager, schedule, expected: tuple[str, dict[str, str]]) -> None:
    """Archive confirmed planning while leaving the same script queued for review."""
    _archive_reaped_operation(manager, schedule, expected, preview_reaped_planning)


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

    return _recovered_results(manager, expected_schedule, {'edit', 'local_edit'}, verify_media)


def attach_recovered_review_copy(manager, schedule, expected: dict[str, str]):
    result = recovered_review_copies(manager, schedule).get(expected['video_path'])
    if result != expected:
        raise ValueError('저장된 업로드 기록이 변경됐습니다. 검토본을 다시 확인하세요.')
    return manager.record_private_review_copy(schedule['id'], expected['video_path'],
        expected_schedule_sha256=schedule_sha256(schedule), expected_video_info=expected)
