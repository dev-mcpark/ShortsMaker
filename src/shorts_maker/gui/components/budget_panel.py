"""Read-only local monthly reserves, separate from provider bills and episode authority."""

import asyncio
from datetime import datetime

from nicegui import run, ui

from shorts_maker.gui.components.common.safe_ui import safe_refresh
from shorts_maker.services import google_budget, openai_budget
from shorts_maker.utils.config import settings


def render_budget_panel():
    snapshots = {}
    loading = {'value': False}
    checked_at = {'text': '아직 조회하지 않았습니다.'}

    @ui.refreshable
    def balances():
        ui.label('조회 중…' if loading['value'] else checked_at['text']).classes('text-xs text-slate-400')
        for name, currency, zone in [('Google', 'krw', '미국 태평양 시간'), ('OpenAI', 'usd', 'UTC')]:
            ui.label(f'{name} · {zone} 월 기준').classes('text-sm font-semibold text-slate-200 mt-2')
            snapshot = snapshots.get(name)
            if snapshot is None:
                ui.label('장부 확인 전 · 사용 가능액을 판단할 수 없습니다.').classes('text-xs text-amber-200')
            elif isinstance(snapshot, Exception):
                ui.label('장부 확인 필요 · 잔액을 판단할 수 없습니다.').classes('text-xs text-amber-200')
                ui.label('설정 월·기준 사용액을 확인하고 기존 장부를 복구하세요. 이전 사용액을 확인하지 않고 새 장부를 만들지 마세요.').classes('text-xs text-slate-300')
                with ui.expansion('조회 오류 상세').classes('w-full'):
                    ui.label(str(snapshot)).classes('text-xs text-slate-400 break-all')
            elif not snapshot['enabled']:
                ui.label('월 예산 미설정 · 이 장부의 한도 보호가 꺼져 있습니다. 무료 사용을 뜻하지 않습니다.').classes('text-xs text-amber-200')
            else:
                def money(value):
                    return f'₩{value:,.0f}' if currency == 'krw' else f'${value:.6f}'

                ui.label(f'{snapshot["period"]} · 남은 예약 여유 {money(snapshot[f"remaining_{currency}"])}').classes('text-sm text-teal-200')
                for title, key in [('월 한도', 'budget'), ('기준 사용액', 'opening'), ('새 요청 예약액', 'local_reserved')]:
                    ui.label(f'{title} {money(snapshot[f"{key}_{currency}"])}').classes('text-xs text-slate-300')
                if currency == 'krw':
                    ui.label(f'예약 환산값 $1 = ₩{snapshot["usd_krw_reserve_rate"]:,}').classes('text-xs text-slate-400')
                with ui.expansion('모델별 새 예약액').classes('w-full'):
                    models = snapshot[f'reserved_by_model_{currency}']
                    if not models:
                        ui.label('새 예약 없음').classes('text-xs text-slate-400')
                    for model, amount in models.items():
                        ui.label(f'{model} · {money(amount)}').classes('text-xs text-slate-300 break-all')

    async def refresh():
        if loading['value']:
            return
        loading['value'] = True
        safe_refresh(balances)
        try:
            results = await asyncio.gather(run.io_bound(google_budget.budget_status),
                                           run.io_bound(openai_budget.budget_status), return_exceptions=True)
            snapshots.update(zip(('Google', 'OpenAI'), results))
            checked_at['text'] = f'마지막 조회 {datetime.now().astimezone().strftime("%m-%d %H:%M:%S %Z")}'
        finally:
            loading['value'] = False
            safe_refresh(balances)

    with ui.expansion('예산·예약 현황', icon='account_balance_wallet').classes('w-full'):
        ui.label('프로그램의 보수적인 예약 추정입니다. 공급자 실제 청구액·결제 잔액은 별도로 확인하세요.').classes('text-xs text-slate-400')
        balances()
        ui.button('장부 새로고침', on_click=refresh).props('flat icon=refresh').bind_enabled_from(
            loading, 'value', lambda value: not value)
        ui.label(f'영상 제작의 비주얼 추정 상한 ${settings.max_visual_cost_usd:.2f}').classes('text-xs text-slate-300')
        ui.label('월 여유는 회차 한도나 새 제작 승인이 아닙니다. 예약 운영은 별도 회차 한도를 함께 적용합니다.').classes('text-xs text-amber-200')
        ui.label('이 화면은 조회 시점의 값입니다. 요청 전 실제 잔액은 서비스에서 다시 검사하며 실패·불확실 요청의 예약도 유지됩니다.').classes('text-xs text-slate-400')
    ui.timer(0.1, refresh, once=True)
    return refresh
