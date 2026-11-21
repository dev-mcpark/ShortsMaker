"""Validate one reviewed correction after a scheduled writer stopped for music."""

import asyncio
import hashlib
import json
import os
import sys
from decimal import Decimal

from shorts_maker.planner.models import ShortsScript
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.planner.script_validator import ScriptValidator
from shorts_maker.services.audio_choices import load_audio_choices
from shorts_maker.services.openai_budget import budget_status, chat_reservation_usd
from shorts_maker.services.openai_models import PRIMARY_CHAT_MODEL
from shorts_maker.services.operating_budget import episode_environment, episode_path, load_episode
from shorts_maker.services.operating_status import schedule_sha256
from shorts_maker.services.script_reviews import read_script_reviews
from shorts_maker.services.work_drafts import read_work_draft
from shorts_maker.utils.config import PROJECT_ROOT, settings


def worker_command(manager, schedule_id, digest):
    return [sys.executable, str(PROJECT_ROOT / 'scripts/operate_schedule.py'),
            '--schedules', str(manager.filename.resolve()), '_validate-revision', schedule_id, digest]


def preflight(manager, schedule_id, digest):
    schedule = manager.get_schedule(schedule_id)
    if (not schedule or schedule.get('review_operator') != 'agent' or schedule.get('enabled')
            or schedule.get('last_result') != 'music_selection_required' or schedule.get('last_script')
            or schedule.get('last_video_path') or schedule.get('last_youtube_id')):
        raise ValueError('음악 선택에서 중단된 미첨부 회차만 수정본을 검증할 수 있습니다.')
    record = load_episode(schedule.get('last_episode_id'), schedule)
    path = episode_path(record['id']).with_suffix('.revision-request.json')
    if (path.is_symlink() or not path.is_file() or path.stat().st_size > 100000
            or os.path.lexists(path.with_suffix('.started')) or os.path.lexists(episode_path(record['id']).with_suffix('.script.json'))):
        raise ValueError('저장된 검증 요청·기존 실행 기록을 먼저 확인하세요.')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('요청이 변경되었습니다.')
    request = json.loads(raw)
    if request['schedule_sha256'] != schedule_sha256(schedule) or request['episode_id'] != record['id']:
        raise ValueError('요청을 준비한 회차가 변경되었습니다.')
    draft, actual = read_work_draft(request['candidate'])
    original, original_sha = read_work_draft(request['original'])
    script = ShortsScript.model_validate_json(draft.editor_text)
    excerpt = request['source_excerpt']
    if (actual != request['candidate_sha256'] or original_sha != request['original_sha256']
            or script.source_url != request['source_url'] or script.source_url != json.loads(original.editor_text)['source_url']
            or (original.writer_source and original.writer_source.episode_id != record['id'])
            or not isinstance(excerpt, str) or not 0 < len(excerpt.strip()) <= 5000
            or script.mood not in ScriptPlanner.SUPPORTED_MOODS
            or not ScriptPlanner.MIN_SCENES <= len(script.scenes) <= ScriptPlanner.MAX_SCENES):
        raise ValueError('회차의 원본·수정 대본·출처·음악 선택을 확인하세요.')
    choices = load_audio_choices(script)
    if not choices or (choices['bgm_volume'] > 0 and not choices['bgm_track']):
        raise ValueError('수정본에 검토한 곡이나 무음 설정을 먼저 저장하세요.')
    messages = ScriptValidator.review_messages(script, excerpt)
    price = chat_reservation_usd(PRIMARY_CHAT_MODEL, messages, ScriptValidator.MAX_COMPLETION_TOKENS)
    env, room = episode_environment(record)
    if (hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest() != request['request_messages_sha256']
            or request['model'] != PRIMARY_CHAT_MODEL or price != Decimal(request['reservation_estimate_usd'])
            or price > Decimal(str(min(room['openai_remaining_usd'], budget_status()['remaining_usd'])))):
        raise ValueError('검증 요청 내용·모델·예약액과 회차 또는 월 잔액을 확인하세요.')
    existing = read_script_reviews(script)
    if existing['records'] or existing['unreadable']:
        raise ValueError('동일한 수정본의 검증 기록을 먼저 대조하세요.')
    return schedule, record, path, script, excerpt, env


def execute(manager, schedule_id, digest):
    with manager._review_transition_lock():
        schedule, record, path, script, excerpt, env = preflight(manager, schedule_id, digest)
        pending = episode_path(record['id']).with_suffix('.operation.pending.json')
        command_sha = hashlib.sha256(json.dumps(worker_command(manager, schedule_id, digest)).encode()).hexdigest()
        if (os.getenv('SHORTSMAKER_EPISODE_ID') != record['id'] or not settings.paid_production_enabled
                or not 0 < Decimal(str(settings.openai_monthly_budget_usd)) <= Decimal(env['OPENAI_MONTHLY_BUDGET_USD'])
                or pending.is_symlink() or json.loads(pending.read_bytes())['command_sha256'] != command_sha):
            raise ValueError('회차 상한과 고정 검증 명령이 적용된 실행만 허용됩니다.')
        planner = ScriptPlanner(generation_mode=script.generation_mode)
        with path.with_suffix('.started').open('x') as marker:
            marker.write(digest)
            marker.flush()
            os.fsync(marker.fileno())
        accepted = asyncio.run(planner._validate_and_save(script, {'content': excerpt}))
        if manager.get_schedule(schedule_id) != schedule:
            raise ValueError('검증 중 일정이 변경되었습니다. 저장한 모델 결과를 먼저 대조하세요.')
        if accepted:
            with episode_path(record['id']).with_suffix('.script.json').open('x', encoding='utf-8') as f:
                f.write(accepted.model_dump_json(indent=2))
                f.flush()
                os.fsync(f.fileno())
        manager.update_schedule(schedule_id, {'last_result': 'script_review_pending' if accepted else 'planning_failed',
            **({'last_script': accepted.model_dump(), 'last_planned_url': accepted.source_url} if accepted else {})})
        print('수정 대본 검증 통과 · 각본·장면 검토 대기' if accepted else '수정 대본 미통과 · 검토 기록 보관')


def prepared_revision(manager, expected):
    schedule = manager.get_schedule(expected['id'])
    if schedule != expected:
        raise ValueError('회차 상태가 바뀌었습니다. 일정을 새로고침하세요.')
    path = episode_path(schedule['last_episode_id']).with_suffix('.revision-request.json')
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100000:
        raise ValueError('이 회차에 준비된 원문 대조 요청이 없습니다.')
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    _, _, _, script, _, _ = preflight(manager, schedule['id'], digest)
    return digest, script, json.loads(content)['reservation_estimate_usd']
