"""Show local reserves and record the user's verified opening for a new provider month."""

import asyncio
import re
import sqlite3
from datetime import datetime
from decimal import Decimal

from nicegui import run, ui

from shorts_maker.gui.components.common.safe_ui import safe_refresh
from shorts_maker.services import google_budget, openai_budget
from shorts_maker.services.monthly_opening import MonthOpeningRequired
from shorts_maker.utils.config import settings


def render_budget_panel():
    snapshots = {}
    loading = {'value': False}
    checked_at = {'text': '아직 조회하지 않았습니다.'}
    opening_dialog = None

    def open_month(name: str, currency: str, period: str):
        nonlocal opening_dialog
        if (root.is_deleted or loading['value']
                or (opening_dialog is not None and not opening_dialog.is_deleted and opening_dialog.value)):
            return
        latest = snapshots.get(name)
        if not isinstance(latest, MonthOpeningRequired) or latest.period != period:
            return
        if opening_dialog is not None and not opening_dialog.is_deleted:
            opening_dialog.delete()
        saving = {'value': False}
        with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-xl'):
            ui.label(f'{name} · {period} 기준 사용액').classes('text-lg font-bold')
            ui.label('공급자 보고서에서 해당 월 시작부터 이미 발생한 사용액과 미대조 요청을 확인하세요.').classes('text-sm')
            ui.label('확인한 기준 사용액을 기존 장부에 한 번 저장합니다. 월·회차 한도와 이전 예약은 유지합니다.').classes('text-sm')
            amount = ui.input('확인한 사용액 (원)' if currency == 'krw' else '확인한 사용액 (USD)').props(
                'outlined inputmode=decimal maxlength=20').classes('w-full')
            evidence = ui.input('확인한 보고서와 조회 시점').props('outlined maxlength=500').classes('w-full')
            checked = ui.checkbox('해당 공급자 월의 사용액을 확인했습니다.')
            notice = ui.label().classes('text-sm text-amber-200 break-words').props('role=alert')

            async def save():
                if root.is_deleted or dialog.is_deleted or not dialog.value or saving['value']:
                    return
                pattern = r'[0-9]{1,12}' if currency == 'krw' else r'[0-9]{1,12}(?:\.[0-9]{1,6})?'
                entered = (amount.value or '').strip()
                if not checked.value or not re.fullmatch(pattern, entered) or not (evidence.value or '').strip():
                    notice.text = '해당 월을 대조한 뒤 기준 사용액, 보고서와 조회 시점을 입력하세요.'
                    return
                recorder = google_budget.record_google_opening if currency == 'krw' else openai_budget.record_openai_opening
                value = int(entered) if currency == 'krw' else Decimal(entered)
                saving['value'] = True
                try:
                    await asyncio.to_thread(recorder, period, value, evidence.value)
                except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
                    if not notice.is_deleted:
                        notice.text = f'기준 사용액을 저장하지 못했습니다. {error}'
                    return
                finally:
                    saving['value'] = False
                if not root.is_deleted:
                    dialog.close()
                    await refresh()

            with ui.row().classes('flex-wrap w-full'):
                ui.button('취소', on_click=dialog.close).props('flat').classes('min-h-[44px]').bind_enabled_from(
                    saving, 'value', lambda value: not value)
                ui.button('확인한 기준 사용액 저장', on_click=save).props('color=teal').classes(
                    'min-h-[44px]').bind_enabled_from(saving, 'value', lambda value: not value)
        opening_dialog = dialog
        dialog.open()

    @ui.refreshable
    def balances():
        ui.label('조회 중…' if loading['value'] else checked_at['text']).classes('text-xs text-slate-400')
        for name, currency, zone in [('Google', 'krw', '미국 태평양 시간'), ('OpenAI', 'usd', 'UTC')]:
            ui.label(f'{name} · {zone} 월 기준').classes('text-sm font-semibold text-slate-200 mt-2')
            snapshot = snapshots.get(name)
            if snapshot is None:
                ui.label('장부 확인 전 · 사용 가능액을 판단할 수 없습니다.').classes('text-xs text-amber-200')
            elif isinstance(snapshot, MonthOpeningRequired):
                ui.label(f'{snapshot.period} · {snapshot}').classes('text-xs text-amber-200 break-words')
                ui.button(f'{name} 이번 달 기준 사용액 확인',
                          on_click=lambda n=name, c=currency, p=snapshot.period: open_month(n, c, p)).props(
                    'outline').classes('min-h-[44px]')
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
        if root.is_deleted or loading['value']:
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
            if not root.is_deleted:
                safe_refresh(balances)

    with ui.expansion('예산·예약 현황', icon='account_balance_wallet').classes('w-full') as root:
        ui.label('프로그램의 보수적인 예약 추정입니다. 공급자 실제 청구액·결제 잔액은 별도로 확인하세요.').classes('text-xs text-slate-400')
        balances()
        ui.button('장부 새로고침', on_click=refresh).props('flat icon=refresh').bind_enabled_from(
            loading, 'value', lambda value: not value)
        ui.label(f'영상 제작의 비주얼 추정 상한 ${settings.max_visual_cost_usd:.2f}').classes('text-xs text-slate-300')
        ui.label('월 여유는 회차 한도나 새 제작 승인이 아닙니다. 예약 운영은 별도 회차 한도를 함께 적용합니다.').classes('text-xs text-amber-200')
        ui.label('이 화면은 조회 시점의 값입니다. 요청 전 실제 잔액은 서비스에서 다시 검사하며 실패·불확실 요청의 예약도 유지됩니다.').classes('text-xs text-slate-400')
    ui.timer(0.1, refresh, once=True)
    return refresh
