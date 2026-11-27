"""Read-only details for the conservative difference from an episode baseline."""

import sqlite3

from nicegui import run, ui

from shorts_maker.gui.components.common.safe_ui import safe_refresh
from shorts_maker.services.operating_budget import episode_reservation_breakdown


GOOGLE_STATUS = {
    'reserved': '예약됨',
    'completed': '완료',
    'succeeded': '완료',
    'saved': '저장됨',
    'failed': '실패',
    'unknown': '결과 미확인',
    'provider_limited': '공급자 제한',
    'not_submitted_dns_failure': '제출 전 DNS 실패',
    'no_charge_verified': '미청구 확인',
}


def render_episode_reservation_panel(manager, schedule):
    snapshot = None
    error = ''
    loading = {'value': False}

    @ui.refreshable
    def details():
        if loading['value']:
            ui.label('장부를 읽는 중…').classes('text-xs text-slate-300').props('role=status')
        elif error:
            ui.label(error).classes('text-xs text-amber-200 break-words').props('role=alert')
        elif snapshot is not None:
            for provider, name in (('google', 'Google · 미국 태평양 시간'), ('openai', 'OpenAI · UTC')):
                ui.label(name).classes('text-xs font-semibold text-slate-200')
                rows = snapshot[provider]
                if not rows:
                    ui.label('기준 이후 새 예약 없음').classes('text-xs text-slate-400')
                for row in rows:
                    amount = (f'₩{row["reserved"]:,}' if provider == 'google'
                              else f'${row["reserved"] / 1_000_000:.6f}')
                    status = GOOGLE_STATUS.get(row['status'], row['status']) if provider == 'google' else '결과 미기록'
                    day = row['day'] or '날짜 확인 필요'
                    tail = f'{row["model"]} · {status} · {row["requests"]}건 · {amount}'
                    ui.label(f'장부 월 {row["period"]} · {day} · {tail}').classes('text-xs text-slate-300 break-words')

    async def refresh():
        nonlocal error, snapshot
        if view.is_deleted or loading['value']:
            return
        snapshot, error = None, ''
        loading['value'] = True
        safe_refresh(details)
        try:
            snapshot = await run.io_bound(episode_reservation_breakdown, manager, schedule)
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as failure:
            error = f'예약 내역 확인 필요 · {failure}'
        finally:
            loading['value'] = False
            if not view.is_deleted:
                safe_refresh(details)

    with ui.expansion('회차 예약 내역', icon='list_alt').classes('w-full min-w-0') as view:
        ui.label('이 회차가 시작된 뒤 장부에 추가된 요청입니다. 날짜는 공급자별 시간대로 환산한 예약일입니다. '
                 '다른 앱 작업의 예약도 포함될 수 있습니다. 실제 사용일과 청구액은 공급자 보고서에서 확인하세요.').classes(
                     'text-xs text-slate-400')
        ui.button('예약 내역 조회', on_click=refresh).props('flat icon=refresh').classes(
            'min-h-[44px]').bind_enabled_from(loading, 'value', lambda value: not value)
        details()
    return refresh
