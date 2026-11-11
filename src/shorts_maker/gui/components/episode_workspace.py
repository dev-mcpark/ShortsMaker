"""Visible, explicit episode binding for the ordinary Studio controls."""

import asyncio
from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.services import google_budget, openai_budget
from shorts_maker.services.operating_budget import episode_environment
from shorts_maker.services.studio_episode_action import EpisodeScope, scope_status


def render_episode_workspace(state, refresh):
    if not state.operating_scope:
        return
    expected = state.execution_key()
    scope = EpisodeScope.model_validate(state.operating_scope)
    with ui.column().classes('w-full p-3 bg-amber-950 border border-amber-700 gap-2 shrink-0') as panel:
        ui.label(f'예약 회차 제작 · {scope.episode_id[:8]}').classes('font-bold text-amber-200')
        ui.label('첫 프레임·원본·편집·비공개 업로드는 같은 회차의 잔여 한도로 실행합니다. '
                 'Veo Lite · 무음 720p · 자동 재시도 없음. 서버에 저장된 API 설정을 사용합니다.').classes('text-xs text-amber-100')
        ui.label('수정 대본은 예약 운영에서 “확인한 수정 대본을 회차에 저장” 후 제작하세요. '
                 '업로드 후에는 예약 운영에서 완성본을 연결합니다. 연결·사용자 채택·공개는 별도입니다.').classes('text-xs text-amber-100')
        status = ui.label('회차 예산은 잔여 확인을 눌러 조회하세요.').classes('text-xs text-amber-200 break-all')

        async def inspect():
            if state.is_busy or expected != state.execution_key() or panel.is_deleted:
                return
            def read():
                _, record = scope_status(scope, state.script)
                _, room = episode_environment(record)
                return (min(room['google_remaining_krw'], google_budget.budget_status()['remaining_krw']),
                        min(room['openai_remaining_usd'], openai_budget.budget_status()['remaining_usd']))
            try:
                google, openai = await asyncio.to_thread(read)
                message = f'월·회차 중 작은 잔여: Google ₩{google:,} · OpenAI ${openai:.6f} (장부 예약 기준)'
            except (OSError, ValueError, KeyError) as error:
                message = f'확인 필요: {error}'
            if expected == state.execution_key() and not panel.is_deleted:
                status.text = message

        def detach():
            with ui.dialog() as dialog, ui.card().classes('max-w-lg'):
                ui.label('이 작업을 수동 제작으로 전환할까요?').classes('text-lg')
                ui.label('이후 직접 실행은 월 예산만 적용하며 이 회차에 자동 연결하지 않습니다. '
                         '회차 장부·승인·결과는 보존합니다. 입력·재료·완성본도 유지합니다.')
                def confirm():
                    if panel.is_deleted or expected != state.execution_key() or state.is_busy:
                        return
                    state.detach_operating_scope()
                    dialog.close()
                    refresh()
                    safe_notify('수동 제작으로 전환했습니다. 회차 일정은 변경하지 않았습니다.', type='info')
                ui.button('수동 제작으로 전환', on_click=confirm).classes('min-h-[44px]')
                ui.button('취소', on_click=dialog.close).props('flat').classes('min-h-[44px]')
            dialog.open()

        with ui.row().classes('flex-wrap'):
            ui.button('회차 잔여 확인', on_click=inspect).props('flat color=amber').classes('min-h-[44px]').bind_enabled_from(state, 'is_busy', backward=lambda value: not value)
            ui.button('회차 연결 해제', on_click=detach).props('flat color=amber').classes('min-h-[44px]').bind_enabled_from(state, 'is_busy', backward=lambda value: not value)
