"""Studio starts only the existing, isolated, budget-scoped planning command."""

import asyncio
import subprocess
import sys

from shorts_maker.planner.models import ShortsScript
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.services import google_budget, openai_budget
from shorts_maker.services.monthly_opening import MonthOpeningRequired
from shorts_maker.services.operating_budget import (
    default_episode_caps, episode_new_visual_plan, episode_video_spec, episode_visual_limits,
)
from shorts_maker.services.operating_status import operator_status, schedule_sha256
from shorts_maker.services.visual_cost import minimum_planning_visuals
from shorts_maker.utils.config import PROJECT_ROOT, settings
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.paid_gate import require_paid_production_enabled

logger = get_logger(__name__)


def planning_worker_command(manager, schedule_id: str) -> list[str]:
    return [sys.executable, str(PROJECT_ROOT / 'scripts/operate_schedule.py'),
            '--schedules', str(manager.filename.resolve()), '_plan', schedule_id]


def planning_preflight(manager, expected: dict) -> dict:
    require_paid_production_enabled()
    current = manager.get_schedule(expected['id'])
    if (not current or schedule_sha256(current) != schedule_sha256(expected)
            or current.get('review_operator') != 'agent' or current.get('enabled')
            or current.get('last_result') != 'operator_pending'
            or current.get('last_video_path') or current.get('last_youtube_id')):
        raise ValueError('변경되지 않은 에이전트 제작 대기 회차만 기획할 수 있습니다.')
    manager.pending_planning_source(current)
    status = operator_status(current)
    if status.get('operation_pending_unverified'):
        raise ValueError('이전 실행 결과를 먼저 대조하세요.')
    monthly, failures = {}, []
    for provider, label, budget_status, amount in (
        ('google', 'Google', google_budget.budget_status, 'remaining_krw'),
        ('openai', 'OpenAI', openai_budget.budget_status, 'remaining_usd'),
    ):
        try:
            snapshot = budget_status()
            if not snapshot.get('enabled') or snapshot.get(amount, 0) <= 0:
                raise ValueError('검증된 현재 월 잔여 예산이 필요합니다.')
            monthly[f'{provider}_{amount}'] = snapshot[amount]
        except MonthOpeningRequired as error:
            failures.append(f'{label} {error.period} 기준 사용액을 확인해 저장하세요.')
        except (OSError, ValueError, RuntimeError) as error:
            failures.append(f'{label} · {error}')
    if failures:
        raise ValueError('\n'.join([*failures, '제작 설정 → 예산·예약 현황에서 확인하세요.']))
    if status.get('budget_error'):
        raise ValueError(status['budget_error'])
    caps = status.get('budget') or default_episode_caps()
    room = {key: min(amount, caps[key]) for key, amount in monthly.items()}
    if room['google_remaining_krw'] <= 0 or room['openai_remaining_usd'] <= 0:
        raise ValueError('이 회차의 남은 제작 예산을 확인하세요.')
    mode = current.get('mode', 'image')
    model, seconds = episode_video_spec(mode)
    cost, count = minimum_planning_visuals(
        mode, ScriptPlanner.MIN_SCENES, image_model=settings.image_model_id,
        video_model=model, video_seconds=seconds, video_attempts=1,
    )
    rate, visual_cap = episode_visual_limits(caps['google_remaining_krw'])
    minimum_krw = google_budget.google_batch_reservation_krw(cost, count, usd_krw_rate=rate)
    if cost > visual_cap or minimum_krw > room['google_remaining_krw']:
        raise ValueError(f'최소 {ScriptPlanner.MIN_SCENES}장면의 신규 비주얼 예약에 ₩{minimum_krw:,}가 필요합니다. '
                         f'Google 월·회차 잔여 상한은 ₩{room["google_remaining_krw"]:,}이며 '
                         f'이 회차의 비주얼 상한은 ${visual_cap:.2f}입니다.')
    room['minimum_visual_scenes'] = ScriptPlanner.MIN_SCENES
    room['minimum_visual_reservation_krw'] = minimum_krw
    room['new_visual_reservation_krw'], room['max_fully_new_scenes'] = episode_new_visual_plan(
        mode, range(ScriptPlanner.MIN_SCENES, ScriptPlanner.MAX_SCENES + 1), room['google_remaining_krw'],
        usd_krw_rate=rate, visual_cap=visual_cap,
    )
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
