"""Validate one reviewed correction after a scheduled writer stopped for music."""

import asyncio
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal

from shorts_maker.planner.models import ShortsScript
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.planner.script_validator import ScriptValidator
from shorts_maker.services.audio_choices import load_audio_choices
from shorts_maker.services.draft_store import snapshot_paths
from shorts_maker.services.openai_budget import budget_status, chat_reservation_usd
from shorts_maker.services.openai_models import PRIMARY_CHAT_MODEL
from shorts_maker.services.operating_budget import episode_environment, episode_path, load_episode
from shorts_maker.services.operating_status import schedule_sha256
from shorts_maker.services.production_service import script_sha256
from shorts_maker.services.scheduled_script_history import validated_revisions
from shorts_maker.services.script_reviews import read_exact_review, read_script_reviews
from shorts_maker.services.script_store import save_script_copy
from shorts_maker.services.work_drafts import read_work_draft, save_work_draft, script_draft_key
from shorts_maker.utils.config import PROJECT_ROOT, settings
from shorts_maker.utils.source_manager import SourceManager
from shorts_maker.utils.scheduler import ScheduleManager
from shorts_maker.services.studio_episode_action import EpisodeScope


def worker_command(manager, schedule_id, digest):
    return [sys.executable, str(PROJECT_ROOT / 'scripts/operate_schedule.py'),
            '--schedules', str(manager.filename.resolve()), '_validate-revision', schedule_id, digest]


def _stopped_episode(schedule):
    if (not schedule or schedule.get('review_operator') != 'agent' or schedule.get('enabled')
            or schedule.get('last_result') != 'music_selection_required' or schedule.get('last_script')
            or schedule.get('last_video_path') or schedule.get('last_youtube_id')):
        raise ValueError('음악 선택에서 중단된 미첨부 회차만 수정본을 검증할 수 있습니다.')
    return load_episode(schedule.get('last_episode_id'), schedule)


def _episode_writer_draft(episode_id):
    originals = []
    for path in snapshot_paths('studio_drafts'):
        try:
            original, digest = read_work_draft(path.name)
        except (OSError, ValueError):
            continue
        if original.writer_source and original.writer_source.episode_id == episode_id:
            originals.append((path.name, original, digest))
    if len(originals) != 1:
        raise ValueError('이 회차에 정확히 연결된 작성 원문 사본 하나가 필요합니다.')
    name, original, digest = originals[0]
    try:
        data = json.loads(original.editor_text)
    except (ValueError, RecursionError) as error:
        raise ValueError('저장된 작성 초안의 내용을 확인할 수 없습니다.') from error
    source = original.writer_source
    if (not isinstance(data, dict) or data.get('source_url') != source.source_url
            or not SourceManager.is_allowed_url(source.source_url)):
        raise ValueError('저장된 작성 초안과 원문 주소가 일치해야 합니다.')
    title = data.get('title')
    return {'name': name, 'sha256': digest, 'source_url': source.source_url,
            'source_excerpt': source.excerpt,
            'title': title.strip()[:100] if isinstance(title, str) and title.strip() else '저장된 작성 초안'}


def read_stopped_writer_draft(manager, expected):
    """Find the exact music-stopped episode's retained draft without a paid quote."""
    schedule = manager.get_schedule(expected['id'])
    if schedule != expected:
        raise ValueError('회차 상태가 바뀌었습니다. 일정을 새로고침하세요.')
    record = _stopped_episode(schedule)
    return _episode_writer_draft(record['id'])


def _validate_candidate(script, excerpt):
    if (not SourceManager.is_allowed_url(script.source_url)
            or not isinstance(excerpt, str) or not 0 < len(excerpt.strip()) <= 5000
            or script.mood not in ScriptPlanner.SUPPORTED_MOODS
            or not ScriptPlanner.MIN_SCENES <= len(script.scenes) <= ScriptPlanner.MAX_SCENES):
        raise ValueError('수정 대본의 출처·음악 분위기·장면 수를 확인하세요.')
    choices = load_audio_choices(script)
    if not choices or (choices['bgm_volume'] > 0 and not choices['bgm_track']):
        raise ValueError('수정본에 검토한 곡이나 무음 설정을 먼저 저장하세요.')


def _quote(script, excerpt, record):
    _validate_candidate(script, excerpt)
    existing = read_script_reviews(script)
    if existing['records'] or existing['unreadable']:
        raise ValueError('동일한 수정본의 검증 기록을 먼저 대조하세요.')
    messages = ScriptValidator.review_messages(script, excerpt)
    price = chat_reservation_usd(PRIMARY_CHAT_MODEL, messages, ScriptValidator.MAX_COMPLETION_TOKENS)
    env, room = episode_environment(record)
    if price > Decimal(str(min(room['openai_remaining_usd'], budget_status()['remaining_usd']))):
        raise ValueError('검증 예약액을 감당할 회차 또는 월 잔액이 필요합니다.')
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest(), price, env


def preview_recovery(manager, expected, script):
    """Quote a correction from the exact episode's saved writer excerpt."""
    schedule = manager.get_schedule(expected['id'])
    if schedule != expected:
        raise ValueError('회차 상태가 바뀌었습니다. 일정을 새로고침하세요.')
    record = _stopped_episode(schedule)
    base = episode_path(record['id'])
    request = base.with_suffix('.revision-request.json')
    if any(os.path.lexists(path) for path in (
            request, request.with_suffix('.started'), base.with_suffix('.operation.pending.json'),
            base.with_suffix('.script.json'))):
        raise ValueError('기존 검증 요청 또는 이전 실행 결과를 먼저 확인하세요.')
    original = _episode_writer_draft(record['id'])
    if original['source_url'] != script.source_url:
        raise ValueError('원래 회차와 같은 출처의 수정 대본을 확인하세요.')
    messages_sha256, amount, _ = _quote(script, original['source_excerpt'], record)
    return {'original': original['name'], 'original_sha256': original['sha256'], 'source_url': original['source_url'],
            'source_excerpt': original['source_excerpt'], 'episode_id': record['id'],
            'schedule_sha256': schedule_sha256(schedule), 'model': PRIMARY_CHAT_MODEL,
            'reservation_estimate_usd': str(amount), 'request_messages_sha256': messages_sha256}


def prepare_recovery(manager, expected, script, preview):
    """Publish a verified, one-use request without invoking a provider."""
    with manager._review_transition_lock():
        current = preview_recovery(manager, expected, script)
        if current != preview:
            raise ValueError('원문이나 검증 견적이 바뀌었습니다. 다시 확인하세요.')
        candidate = save_work_draft(None, script.model_dump_json(indent=2), {})
        _, digest = read_work_draft(candidate.name)
        request = episode_path(current['episode_id']).with_suffix('.revision-request.json')
        payload = {**current, 'candidate': candidate.name, 'candidate_sha256': digest}
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=request.parent) as stream:
            json.dump(payload, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
            os.link(stream.name, request)


def preflight(manager, schedule_id, digest):
    schedule = manager.get_schedule(schedule_id)
    record = _stopped_episode(schedule)
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
    script, excerpt = _request_candidate(request, record)
    messages_sha256, price, env = _quote(script, excerpt, record)
    if (messages_sha256 != request['request_messages_sha256'] or request['model'] != PRIMARY_CHAT_MODEL
            or price != Decimal(request['reservation_estimate_usd'])):
        raise ValueError('검증 요청 내용·모델·예약액을 다시 확인하세요.')
    return schedule, record, path, script, excerpt, env


def _request_candidate(request, record):
    draft, actual = read_work_draft(request['candidate'])
    original, original_sha = read_work_draft(request['original'])
    script = ShortsScript.model_validate_json(draft.editor_text)
    excerpt = request['source_excerpt']
    if (actual != request['candidate_sha256'] or original_sha != request['original_sha256']
            or script.source_url != request['source_url'] or script.source_url != json.loads(original.editor_text)['source_url']
            or (original.writer_source and (original.writer_source.episode_id != record['id']
                or original.writer_source.source_url != script.source_url
                or original.writer_source.excerpt != excerpt))):
        raise ValueError('회차의 원본·수정 대본·출처·음악 선택을 확인하세요.')
    return script, excerpt


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
    base = episode_path(schedule['last_episode_id'])
    if os.path.lexists(base.with_suffix('.operation.pending.json')):
        raise ValueError('이전 회차 실행 결과를 먼저 대조하세요.')
    path = base.with_suffix('.revision-request.json')
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100000:
        raise ValueError('이 회차에 준비된 원문 대조 요청이 없습니다.')
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    _, _, _, script, _, _ = preflight(manager, schedule['id'], digest)
    return digest, script, json.loads(content)['reservation_estimate_usd']


def preview_reassessment(manager, expected, candidate):
    """Read the completed rejection and exact source for the owner's explicit reassessment."""
    schedule = manager.get_schedule(expected['id'])
    if schedule != expected or schedule.get('last_result') != 'planning_failed':
        raise ValueError('검증이 끝난 현재 회차를 다시 확인하세요.')
    stopped = {**schedule, 'last_result': 'music_selection_required'}
    record = _stopped_episode(stopped)
    base = episode_path(record['id'])
    if any(os.path.lexists(path) for path in (base.with_suffix('.operation.pending.json'), base.with_suffix('.script.json'))):
        raise ValueError('이전 실행 또는 대본 기록을 먼저 대조하세요.')
    request, request_sha256 = _started_revision_request(base)
    if (request['episode_id'] != record['id']
            or request['schedule_sha256'] != schedule_sha256(stopped)):
        raise ValueError('검증 요청과 현재 회차 기록이 일치하지 않습니다.')
    rejected, excerpt = _request_candidate(request, record)
    if (candidate.source_url != rejected.source_url
            or script_draft_key(candidate) == script_draft_key(rejected)):
        raise ValueError('같은 출처의 수정된 대본을 먼저 확인하세요.')
    _validate_candidate(candidate, excerpt)
    evidence = read_script_reviews(rejected)
    if (evidence['unreadable'] or len(evidence['records']) != 1
            or evidence['records'][0]['state'] != 'completed'
            or evidence['records'][0]['verdict']['is_valid']
            or evidence['records'][0]['source_excerpt'] != excerpt
            or evidence['records'][0]['model'] != request['model']):
        raise ValueError('완료된 모델 미통과 판정과 원문을 대조해야 합니다.')
    return {'request_sha256': request_sha256, 'review': evidence['records'][0],
            'candidate_sha256': script_draft_key(candidate)}


def _started_revision_request(base):
    request_path = base.with_suffix('.revision-request.json')
    started = request_path.with_suffix('.started')
    if (request_path.is_symlink() or not request_path.is_file() or request_path.stat().st_size > 100000
            or started.is_symlink() or not started.is_file() or started.stat().st_size != 64):
        raise ValueError('이 회차의 수정 대본 검증 요청·실행 기록을 확인하세요.')
    raw = request_path.read_bytes()
    request_sha256 = hashlib.sha256(raw).hexdigest()
    request = json.loads(raw)
    if started.read_text() != request_sha256 or not isinstance(request, dict):
        raise ValueError('저장된 검증 요청과 실행 기록이 일치하지 않습니다.')
    return request, request_sha256


def read_applied_reassessment(scope_data: dict, script: ShortsScript) -> dict | None:
    """Recover the source behind the exact, owner-adopted revision in the open episode."""
    scope = EpisodeScope.model_validate(scope_data)
    manager = ScheduleManager(scope.schedules_file, queue_only=True)
    schedule = manager.get_schedule(scope.schedule_id)
    if (not schedule or schedule.get('review_operator') != 'agent'
            or schedule.get('last_episode_id') != scope.episode_id):
        raise ValueError('현재 작업실과 예약 회차를 다시 확인하세요.')
    current = schedule.get('last_script')
    if not isinstance(current, dict) or script_sha256(current) != script_sha256(script.model_dump(mode='json')):
        return None
    history = validated_revisions(current, schedule.get('script_revisions', []))
    if not history or 'reassessment' not in history[-1]:
        return None
    load_episode(scope.episode_id, schedule)
    decision = history[-1]
    reassessment = decision['reassessment']
    if not isinstance(reassessment, dict) or decision.get('review_receipt_sha256') != script_draft_key(script):
        raise ValueError('원문 대조 이력과 현재 대본이 일치하지 않습니다.')
    request, digest = _started_revision_request(episode_path(scope.episode_id))
    model_review = read_exact_review(reassessment.get('model_review_name'), reassessment.get('model_review_sha256'))
    verdict = model_review['verdict']
    note = reassessment.get('note')
    if (digest != reassessment.get('request_sha256') or request.get('episode_id') != scope.episode_id
            or request.get('source_url') != script.source_url or model_review['script'] != decision['script']
            or model_review['script'].get('source_url') != script.source_url
            or model_review['source_excerpt'] != request.get('source_excerpt') or model_review['model'] != request.get('model')
            or model_review['state'] != 'completed' or verdict['is_valid'] or verdict != reassessment.get('model_verdict')
            or not isinstance(note, str) or not 1 <= len(note.strip()) <= 500):
        raise ValueError('원문·이전 모델 판정·수정 대본 이력이 일치하지 않습니다.')
    if manager.get_schedule(scope.schedule_id) != schedule:
        raise ValueError('원문 조회 중 예약 회차가 바뀌었습니다.')
    return {'excerpt': model_review['source_excerpt'], 'note': note, 'rejected_score': verdict['score']}


def save_reassessment(manager, expected, candidate, preview, note):
    if not isinstance(note, str) or not note.strip() or len(note) > 500:
        raise ValueError('원문 대조 후 수정 대본을 채택하는 이유를 500자 이내로 입력하세요.')
    with manager._review_transition_lock():
        current = preview_reassessment(manager, expected, candidate)
        if current != preview:
            raise ValueError('검토한 대본이나 모델 판정이 바뀌었습니다. 다시 확인하세요.')
        stored = save_script_copy(candidate, settings.output_dir / 'evaluation' / 'scheduled_script_revisions')
        review = current['review']
        selected = candidate.model_dump(mode='json')
        reviewed_at = datetime.now(timezone.utc).isoformat()
        return manager.update_schedule(expected['id'], {
            'last_result': 'script_review_pending',
            'last_script': selected, 'last_script_path': str(stored.resolve()),
            'last_planned_url': candidate.source_url,
            'script_revisions': [{'script': review['script'], 'script_sha256': script_sha256(review['script']),
                'script_path': None, 'replacement_sha256': script_sha256(selected),
                'review_receipt_sha256': current['candidate_sha256'], 'replaced_at': reviewed_at,
                'reassessment': {'note': note.strip(), 'request_sha256': current['request_sha256'],
                    'model_review_name': review['name'], 'model_review_sha256': review['request_sha256'],
                    'model_verdict': review['verdict']}}],
        })
