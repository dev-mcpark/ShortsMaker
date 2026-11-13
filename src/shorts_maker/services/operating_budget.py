"""Episode ceilings for normal provider clients in an isolated operator process."""

import json
import os
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from shorts_maker.services import google_budget, openai_budget
from shorts_maker.utils.config import settings


_OPENAI_EPISODE_CAP_MICRO_USD = 300_000
_OPENAI_INITIAL_EXTENSION_MICRO_USD = 350_000
_OPENAI_TEXT_EXTENSION_MICRO_USD = 450_000
_OPENAI_APPROVED_EXTENSION_MAX_MICRO_USD = 500_000
_OPENAI_PLANNING_VALIDATION_MAX_MICRO_USD = 650_000
_GOOGLE_EPISODE_CAP_KRW = 3000
_GOOGLE_INITIAL_EXTENSION_KRW = 3300
_GOOGLE_APPROVED_EXTENSION_MAX_KRW = 6300


def default_episode_caps() -> dict:
    return {'google_remaining_krw': _GOOGLE_EPISODE_CAP_KRW,
            'openai_remaining_usd': _OPENAI_EPISODE_CAP_MICRO_USD / 1000000}


def episode_video_spec(mode: str) -> tuple[str, int]:
    return 'veo-3.1-lite-generate-001', 6 if mode == 'hybrid' else 8


def episode_path(episode_id: str) -> Path:
    if not isinstance(episode_id, str) or not re.fullmatch(r'[0-9a-f]{32}', episode_id):
        raise ValueError('유효한 제작 회차 ID가 필요합니다.')
    return settings.output_dir / 'evaluation' / 'operating_episodes' / f'{episode_id}.json'


def _reserves(provider: str) -> dict[str, int]:
    path = (google_budget if provider == 'google' else openai_budget)._database_path()
    column = 'reserved_krw' if provider == 'google' else 'reserved_micro_usd'
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        rows = dict(db.execute(f'SELECT id, {column} FROM requests'))
    if any(not isinstance(key, str) or type(value) is not int or value < 0
           for key, value in rows.items()):
        raise ValueError('비용 장부의 요청 ID와 예약액을 확인하세요.')
    return rows


def begin_episode(schedule_id: str, run_count: int) -> dict:
    """Capture all existing reservations once; calendar rollover never refreshes this scope."""
    google = google_budget.budget_status()
    openai = openai_budget.budget_status()
    if not google.get('enabled') or not openai.get('enabled'):
        raise ValueError('두 공급자의 검증된 현재 월 장부가 필요합니다.')
    record = {
        'schema_version': 1, 'id': uuid.uuid4().hex,
        'schedule_id': schedule_id, 'run_count': run_count,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'google_cap_krw': _GOOGLE_EPISODE_CAP_KRW, 'openai_cap_micro_usd': _OPENAI_EPISODE_CAP_MICRO_USD,
        'baseline': {provider: list(_reserves(provider)) for provider in ('google', 'openai')},
        'starting_periods': {'google': google['period'], 'openai': openai['period']},
    }
    path = episode_path(record['id'])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    return record


def load_episode(episode_id: str, schedule: dict) -> dict:
    record = json.loads(episode_path(episode_id).read_text(encoding='utf-8'))
    if (not isinstance(record, dict) or record.get('schema_version') != 1
            or record.get('id') != episode_id or record.get('schedule_id') != schedule['id']
            or record.get('run_count') != schedule['run_count']
            or type(record.get('google_cap_krw')) is not int
            or not 0 < record['google_cap_krw'] <= _GOOGLE_APPROVED_EXTENSION_MAX_KRW
            or type(record.get('openai_cap_micro_usd')) is not int
            or not 0 < record['openai_cap_micro_usd'] <= _OPENAI_APPROVED_EXTENSION_MAX_MICRO_USD
            or not isinstance(record.get('baseline'), dict)):
        raise ValueError('제작 회차와 승인 상한 기록이 일치하지 않습니다.')
    if record['google_cap_krw'] > _GOOGLE_EPISODE_CAP_KRW:
        approval = record.get('google_cap_extension')
        if (not isinstance(approval, dict)
                or approval.get('previous_cap_krw') != _GOOGLE_EPISODE_CAP_KRW
                or approval.get('approved_cap_krw') != min(
                    record['google_cap_krw'], _GOOGLE_INITIAL_EXTENSION_KRW)
                or not isinstance(approval.get('owner_approval'), str)
                or not approval['owner_approval'].strip()):
            raise ValueError('기본 상한을 넘는 회차는 별도 사용자 승인 기록이 필요합니다.')
    if record['openai_cap_micro_usd'] > _OPENAI_EPISODE_CAP_MICRO_USD:
        approval = record.get('openai_cap_extension')
        if (not isinstance(approval, dict)
                or approval.get('previous_cap_micro_usd') != _OPENAI_EPISODE_CAP_MICRO_USD
                or approval.get('approved_cap_micro_usd') != min(
                    record['openai_cap_micro_usd'], _OPENAI_INITIAL_EXTENSION_MICRO_USD)
                or not isinstance(approval.get('owner_approval'), str)
                or not approval['owner_approval'].strip()):
            raise ValueError('기본 상한을 넘는 회차는 별도 사용자 승인 기록이 필요합니다.')
    if record['openai_cap_micro_usd'] > _OPENAI_INITIAL_EXTENSION_MICRO_USD:
        approval = record.get('openai_cap_extension_followup')
        if (not isinstance(approval, dict)
                or approval.get('previous_cap_micro_usd') != _OPENAI_INITIAL_EXTENSION_MICRO_USD
                or approval.get('approved_cap_micro_usd') != min(
                    record['openai_cap_micro_usd'], _OPENAI_TEXT_EXTENSION_MICRO_USD)
                or not isinstance(approval.get('owner_approval'), str)
                or not approval['owner_approval'].strip()):
            raise ValueError('후속 상한 확장에는 이전 승인과 새 사용자 승인 기록이 모두 필요합니다.')
    if (record['google_cap_krw'] > _GOOGLE_INITIAL_EXTENSION_KRW
            or record['openai_cap_micro_usd'] > _OPENAI_TEXT_EXTENSION_MICRO_USD):
        approval = record.get('video_comparison_extension')
        if (not isinstance(approval, dict)
                or record['google_cap_krw'] != _GOOGLE_APPROVED_EXTENSION_MAX_KRW
                or record['openai_cap_micro_usd'] != _OPENAI_APPROVED_EXTENSION_MAX_MICRO_USD
                or approval.get('previous_google_cap_krw') != _GOOGLE_INITIAL_EXTENSION_KRW
                or approval.get('approved_google_cap_krw') != record['google_cap_krw']
                or approval.get('previous_openai_cap_micro_usd') != _OPENAI_TEXT_EXTENSION_MICRO_USD
                or approval.get('approved_openai_cap_micro_usd') != record['openai_cap_micro_usd']
                or not isinstance(approval.get('owner_approval'), str)
                or not approval['owner_approval'].strip()):
            raise ValueError('새 영상 비교에는 기존 승인과 두 공급자의 추가 승인 기록이 필요합니다.')
    if 'planning_validation_extension' in record:
        approval = record.get('planning_validation_extension')
        if (not isinstance(approval, dict)
                or approval.get('previous_cap_micro_usd') != _OPENAI_APPROVED_EXTENSION_MAX_MICRO_USD
                or approval.get('approved_cap_micro_usd') != _OPENAI_PLANNING_VALIDATION_MAX_MICRO_USD
                or record['openai_cap_micro_usd'] != _OPENAI_APPROVED_EXTENSION_MAX_MICRO_USD
                or not isinstance(approval.get('owner_approval'), str)
                or not approval['owner_approval'].strip()):
            raise ValueError('추가 기획 검증에는 이전 상한과 새 사용자 승인 기록이 필요합니다.')
    for provider in ('google', 'openai'):
        ids = record['baseline'].get(provider)
        if (not isinstance(ids, list) or not all(isinstance(key, str) for key in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError('제작 시작 시점의 장부 기록을 확인하세요.')
    return record


def episode_environment(record: dict) -> tuple[dict[str, str], dict]:
    """Lower monthly ceilings around the episode's cumulative reserve, across all periods."""
    record = load_episode(record['id'], {'id': record['schedule_id'], 'run_count': record['run_count']})
    google = google_budget.budget_status()
    openai = openai_budget.budget_status()
    if not google.get('enabled') or not openai.get('enabled'):
        raise ValueError('현재 월 사용 기준이 확인된 두 장부가 필요합니다.')
    spent = {}
    for provider in ('google', 'openai'):
        rows = _reserves(provider)
        baseline = set(record['baseline'][provider])
        if not baseline <= rows.keys():
            raise ValueError('이전 장부 행이 사라졌습니다. 회차 예산을 다시 승인한 것으로 처리하지 않습니다.')
        # Other app requests are conservatively included; never guess an untracked allocation.
        spent[provider] = sum(value for key, value in rows.items() if key not in baseline)
    remaining_google = max(0, record['google_cap_krw'] - spent['google'])
    # Keep the legacy cap readable by the still-running older Studio; it remains more restrictive.
    openai_cap = record.get('planning_validation_extension', {}).get(
        'approved_cap_micro_usd', record['openai_cap_micro_usd'])
    remaining_openai = max(0, openai_cap - spent['openai'])
    google_ceiling = min(10000, google['budget_krw'],
                         google['opening_krw'] + google['local_reserved_krw'] + remaining_google)
    openai_used = (Decimal(str(openai['opening_usd']))
                  + Decimal(str(openai['local_reserved_usd'])))
    openai_ceiling = min(Decimal('1'), Decimal(str(openai['budget_usd'])),
                         openai_used + Decimal(remaining_openai) / 1000000)
    if google_ceiling <= 0 or openai_ceiling <= 0:
        raise ValueError('비용 상한을 구성할 수 없습니다. 월 사용 기준을 확인하세요.')
    env = {
        'SHORTSMAKER_EPISODE_ID': record['id'], 'PAID_PRODUCTION_ENABLED': 'true',
        'GOOGLE_MONTHLY_BUDGET_KRW': str(google_ceiling),
        'OPENAI_MONTHLY_BUDGET_USD': str(openai_ceiling),
        'VEO_MODEL_ID': episode_video_spec('video')[0], 'VEO_DURATION_SECONDS': str(episode_video_spec('video')[1]),
        'HYBRID_VEO_DURATION_SECONDS': str(episode_video_spec('hybrid')[1]),
        'GOOGLE_USD_KRW_RESERVE_RATE': str(max(2000, settings.google_usd_krw_rate)),
        'MAX_VISUAL_COST_USD': str(min(1.5, remaining_google / max(2000, settings.google_usd_krw_rate))),
    }
    status = {'google_new_reserved_krw': spent['google'],
              'openai_new_reserved_usd': spent['openai'] / 1000000,
              'google_remaining_krw': remaining_google,
              'openai_remaining_usd': remaining_openai / 1000000,
              'google_process_ceiling_krw': google_ceiling,
              'openai_process_ceiling_usd': float(openai_ceiling)}
    return env, status
