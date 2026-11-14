"""Explicit, quoted speech preparation through the normal or episode service."""

import asyncio
from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.services.narration_preparation import plan_narration
from shorts_maker.services.openai_budget import budget_status
from shorts_maker.services.operating_budget import episode_environment
from shorts_maker.services.studio_episode_action import EpisodeScope, scope_status


def render_narration_prepare(state, refresh):
    rendered = state.script.model_dump_json(), state.execution_key()
    planning = False
    with ui.column().classes('w-full gap-2') as view:
        ui.label('영상·BGM 없이 음성만 준비하고 들어볼 수 있습니다. 완료한 장면은 보존하고, 결과가 불확실한 요청은 다시 보내지 않습니다.').classes('text-xs text-slate-300')
        ui.label().bind_text_from(state, 'narration_preparation_message').classes('text-xs text-amber-200 break-all').props('role=status')

        def context():
            return (state.script.model_dump_json() if state.script else None,
                    state.execution_key(), state.tts_voice, state.mode)

        def require_ready(expected):
            if view.is_deleted or state.is_busy or context() != expected:
                raise ValueError('작업이나 설정이 바뀌었습니다. 현재 제작 화면에서 다시 확인하세요.')
            if (context()[:2] != rendered or not state.is_script_reviewed()
                    or state.has_unapplied_script_draft()):
                raise ValueError('현재 각본의 수정을 적용하거나 되돌린 뒤 각본을 확인하세요.')
            if state.prepared_narration_manifest:
                raise ValueError('연결한 음성을 사용하거나, 새 음성 생성으로 전환을 직접 선택하세요.')
            state.require_execution_context(expected[1])

        async def inspect():
            nonlocal planning
            if planning:
                return
            expected = context()
            try:
                require_ready(expected)
                planning = True
                script = state.script.model_copy(deep=True)
                scope = dict(state.operating_scope) if state.operating_scope else None
                def read():
                    quote = plan_narration(script, expected[2])
                    monthly = budget_status()
                    remaining = monthly['remaining_usd'] if monthly.get('enabled') else None
                    if scope:
                        _, record = scope_status(EpisodeScope.model_validate(scope), script)
                        _, room = episode_environment(record)
                        remaining = min(room['openai_remaining_usd'], remaining) if remaining is not None else room['openai_remaining_usd']
                    return quote, remaining
                quote, remaining = await asyncio.to_thread(read)
                require_ready(expected)
                cost = quote['additional_request_reserve_usd']
                if remaining is not None and cost > remaining:
                    raise ValueError(f'새 요청 예약 ${cost:.6f}이 월·회차 잔여 ${remaining:.6f}을 초과합니다.')
                with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg'):
                    ui.label('내레이션만 준비할까요?').classes('text-lg')
                    ui.label(f'{quote["model"]} / {expected[2]} · 새 음성 {len(quote["missing_scenes"])}장면 · 최대 새 요청 예약 ${cost:.6f}')
                    ui.label(f'월·회차 중 작은 잔여 ${remaining:.6f}' if remaining is not None else '월 예산 보호가 설정되지 않았습니다.')
                    ui.label('음성 요청당 기존 최대 2회 시도를 포함합니다. 완료된 같은 음성은 재사용합니다. 영상·편집·업로드는 실행하지 않습니다. 중지는 진행 중 요청의 저장이 끝난 뒤 적용됩니다.').classes('text-sm')

                    async def confirm():
                        task = None
                        service = None
                        try:
                            if dialog.is_deleted or not dialog.value:
                                return
                            require_ready(expected)
                            service = state.new_production_service()
                            state.pipeline_running = True
                            state.narration_preparing = True
                            state.narration_preparation_message = '내레이션 준비 중 · 중지하면 현재 요청을 저장한 뒤 멈춥니다.'
                            service.set_progress_callback(lambda progress: setattr(state, 'narration_preparation_message', progress.message))
                            dialog.close()
                            task = asyncio.create_task(service.prepare_narration(script, request_budget_usd=cost))
                            try:
                                manifest = await asyncio.shield(task)
                            except asyncio.CancelledError:
                                service.cancel()
                                try:
                                    await task
                                except Exception:
                                    pass
                                state.narration_preparation_message = '내레이션 준비를 중지했습니다. 완료한 장면은 보관했습니다. 비용을 다시 확인한 뒤 이어갈 수 있습니다.'
                                raise
                            if service.is_cancelled() or context() != expected:
                                state.narration_preparation_message = '음성은 보관했습니다. 현재 대본의 음성 목록에서 명시적으로 연결하세요.'
                                return
                            state.pipeline_running = False
                            state.select_prepared_narration(manifest)
                            state.narration_preparation_message = '내레이션을 준비·연결했습니다. 장면별로 재생하고 음성·음악 설정을 저장하세요.'
                            safe_notify('내레이션 준비 완료', type='positive')
                        except Exception as error:
                            state.narration_preparation_message = f'내레이션 준비 중단: {error} · 자동으로 다시 요청하지 않습니다.'
                            safe_notify(state.narration_preparation_message, type='negative')
                        finally:
                            if service is not None:
                                state.pipeline_running = False
                                state.narration_preparing = False
                            if not view.is_deleted:
                                safe_refresh(refresh)

                    ui.button('확인 후 음성만 준비', on_click=confirm).classes('min-h-[44px]')
                    ui.button('취소', on_click=dialog.close).props('flat').classes('min-h-[44px]')
                dialog.open()
            except (OSError, ValueError, TypeError, RuntimeError, KeyError) as error:
                state.narration_preparation_message = f'내레이션 준비 확인: {error}'
                safe_notify(state.narration_preparation_message, type='warning')
            finally:
                planning = False

        ui.button('음성만 준비 · 비용 확인', on_click=inspect, icon='record_voice_over').classes('min-h-[44px]').bind_enabled_from(
            state, 'is_busy', lambda busy: not busy and not state.prepared_narration_manifest)
        def cancel():
            if (not view.is_deleted and context()[:2] == rendered
                    and state.narration_preparing and state.production_service):
                state.production_service.cancel()

        ui.button('음성 준비 중지 요청', on_click=cancel).props('flat').classes('min-h-[44px]').bind_visibility_from(
            state, 'narration_preparing')
