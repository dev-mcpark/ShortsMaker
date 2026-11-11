"""Studio starts only the existing, isolated, budget-scoped planning command."""

import asyncio
import subprocess
import sys

from shorts_maker.planner.models import ShortsScript
from shorts_maker.services import google_budget, openai_budget
from shorts_maker.services.operating_budget import default_episode_caps
from shorts_maker.services.operating_status import operator_status, schedule_sha256
from shorts_maker.utils.config import PROJECT_ROOT
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.paid_gate import require_paid_production_enabled

logger = get_logger(__name__)


def planning_preflight(manager, expected: dict) -> dict:
    require_paid_production_enabled()
    current = manager.get_schedule(expected['id'])
    if (not current or schedule_sha256(current) != schedule_sha256(expected)
            or current.get('review_operator') != 'agent' or current.get('enabled')
            or current.get('last_result') != 'operator_pending'
            or current.get('last_video_path') or current.get('last_youtube_id')):
        raise ValueError('변경되지 않은 에이전트 제작 대기 회차만 기획할 수 있습니다.')
    status = operator_status(current)
    if status.get('operation_pending_unverified') or status.get('budget_error'):
        raise ValueError('회차의 비용 또는 이전 실행 결과를 먼저 대조하세요.')
    caps = status.get('budget') or default_episode_caps()
    room = {}
    for provider, snapshot, amount in (
        ('google', google_budget.budget_status(), 'remaining_krw'),
        ('openai', openai_budget.budget_status(), 'remaining_usd'),
    ):
        if not snapshot.get('enabled') or snapshot.get(amount, 0) <= 0:
            raise ValueError('두 공급자의 검증된 현재 월 잔여 예산이 필요합니다.')
        room[f'{provider}_{amount}'] = min(snapshot[amount], caps[f'{provider}_{amount}'])
    if room['google_remaining_krw'] <= 0 or room['openai_remaining_usd'] <= 0:
        raise ValueError('이 회차의 남은 제작 예산을 확인하세요.')
    return room


async def plan_pending_schedule(manager, expected: dict) -> dict:
    await asyncio.to_thread(planning_preflight, manager, expected)
    command = [sys.executable, str(PROJECT_ROOT / 'scripts/operate_schedule.py'),
               '--schedules', str(manager.filename.resolve()), 'plan', expected['id'],
               '--expected-schedule-sha256', schedule_sha256(expected)]
    result = await asyncio.to_thread(subprocess.run, command, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if result.returncode:
        logger.error('Scheduled planning stopped (%s): %s', result.returncode, (result.stderr or '')[-4000:])
        output = (result.stderr or '') + (result.stdout or '')
        if 'YOUTUBE_AUTH_REQUIRED' in output:
            raise RuntimeError('YOUTUBE_AUTH_REQUIRED: 완성본·업로드 → YouTube 업로드 연결에서 계정을 다시 연결한 뒤 회차 상태를 확인하세요. 자동 재시도하지 않습니다.')
        raise RuntimeError(f'예약 기획이 중단됐습니다(종료 {result.returncode}). 회차 상태와 운영 기록을 확인하세요. 자동 재시도하지 않습니다.')
    current = manager.get_schedule(expected['id'])
    if (not current or current.get('last_result') != 'script_review_pending'
            or current.get('run_count') != expected.get('run_count') or not current.get('last_script')):
        raise ValueError('기획 실행 뒤 저장된 각본·회차 상태를 확인해야 합니다. 다시 실행하지 마세요.')
    ShortsScript.model_validate(current['last_script'])
    return current
