"""Explicit owner decisions for the attached review copy and cadence."""
import asyncio
from pathlib import Path

from nicegui import ui

from shorts_maker.gui.components.common.media_preview import media_sources
from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.services.operating_status import schedule_sha256
from shorts_maker.utils.scheduler import INTERVAL_WEEKS


def render_review_acceptance(state, manager, schedule, refresh):
    expected = schedule_sha256(schedule)
    deferred = schedule.get('last_result') == 'private_review_deferred'
    saving = {'value': False}
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg'):
        ui.label('이 완성본을 게시 후보로 채택할까요?').classes('text-lg')
        ui.label(Path(schedule['last_video_path']).name).classes('break-all')
        ui.label(f'YouTube ID · {schedule["last_youtube_id"]}').classes('text-sm break-all')
        ui.label('전체 영상과 출처·음악·자막을 확인한 뒤 채택하세요. 공개는 YouTube Studio에서 결정합니다.').classes('text-sm')
        if deferred:
            message = '현재 예약 상태를 유지합니다.' if schedule.get('enabled') else '일정은 일시정지 상태를 유지합니다.'
        elif schedule.get('direct_url'):
            message = '이 URL 일정은 종료 상태로 남습니다.'
        else:
            message = '채택 후 기존 주기의 다음 시각에 새 소재를 예약합니다.'
        ui.label(message).classes('text-sm')
        error_label = ui.label().classes('text-sm text-amber-200 break-words').props('role=alert')

        async def confirm():
            if not current() or not dialog.value:
                return
            saving['value'] = True
            error_label.set_text('')
            try:
                await asyncio.to_thread(manager.accept_pending_video, schedule['id'], schedule['last_video_path'],
                                        expected_schedule_sha256=expected)
            except (OSError, ValueError, RuntimeError) as error:
                if not error_label.is_deleted:
                    error_label.set_text(f'완성본 채택 중단: {error}')
                return
            finally:
                saving['value'] = False
            if not dialog.is_deleted:
                dialog.close()
            if not view.is_deleted:
                refresh()
                safe_notify('완성본 채택을 기록했습니다.', type='positive')

        with ui.row().classes('flex-wrap'):
            ui.button('취소', on_click=dialog.close).props('flat').classes('min-h-[44px]').bind_enabled_from(
                saving, 'value', lambda value: not value)
            ui.button('이 완성본 채택', on_click=confirm).props('color=teal').classes('min-h-[44px]').bind_enabled_from(
                state, 'is_busy', lambda busy: not busy and not saving['value'])

    def current():
        return not view.is_deleted and not dialog.is_deleted and not state.is_busy and not saving['value']

    def open_dialog():
        if current() and not dialog.value:
            error_label.set_text('')
            dialog.open()

    view = ui.button('보류한 완성본 채택' if deferred else '완성본 채택', on_click=open_dialog).props(
        'flat color=teal').classes('min-h-[44px]').bind_enabled_from(state, 'is_busy', lambda busy: not busy)


def render_review_continuation(state, manager, schedule, refresh):
    expected = schedule_sha256(schedule)
    with ui.column().classes('gap-1') as view:
        def open_dialog():
            if view.is_deleted or state.is_busy:
                return
            with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg'):
                ui.label('채택을 보류하고 다음 회차를 예약할까요?').classes('text-lg')
                days = INTERVAL_WEEKS[schedule['frequency']] * 7
                ui.label(f'{days}일마다 반복하는 현재 일정으로 다음 소재를 예약합니다. 기존 대본·검토본·비용과 채택 보류 상태를 보존합니다.').classes('text-sm')
                ui.label('다음 회차는 기준 시각에 대기 상태로 들어가며, 제작은 예산과 인증을 확인한 뒤 시작합니다.').classes('text-sm')
                note = ui.textarea('검토·예약 메모', value='현재 완성본 채택은 보류하고 다음 예약 회차에서 개선을 이어갑니다.').classes('w-full').props('outlined')
                def confirm():
                    if view.is_deleted or dialog.is_deleted or not dialog.value or state.is_busy:
                        return
                    try:
                        manager.resume_after_video_review(schedule['id'], schedule['last_video_path'],
                            expected_schedule_sha256=expected, note=note.value)
                        dialog.close()
                        refresh()
                        safe_notify('미채택 검토본을 보존하고 다음 회차를 예약했습니다.', type='positive')
                    except (OSError, ValueError, TypeError) as error:
                        safe_notify(f'다음 회차 예약 실패: {error}', type='negative')
                ui.button('미채택 유지·다음 회차 예약', on_click=confirm).classes('min-h-[44px]')
                ui.button('취소', on_click=dialog.close).props('flat').classes('min-h-[44px]')
            dialog.open()
        ui.button('채택 보류·다음 회차 예약', on_click=open_dialog).props('flat color=amber').classes('min-h-[44px]').bind_enabled_from(
            state, 'is_busy', lambda busy: not busy)


def render_archived_review_browser(state, manager, runs, refresh):
    available = {str(index): run for index, run in enumerate(runs) if run.get('archived_review_sha256')
                 and type(run.get('run_count')) is int and isinstance(run.get('last_script'), dict)}
    if not available:
        return
    working = {'value': False}
    media_source = media_sources()
    with ui.column().classes('w-full px-4 gap-2') as panel:
        choice = ui.select(
            {key: f'{run["name"]} · 회차 {run["run_count"]} · {run["last_script"].get("title", "완성본")}'
             for key, run in available.items()},
            label='지난 회차 검토본 검색', with_input=True,
        ).props('outlined dark clearable').classes('w-full').bind_enabled_from(working, 'value', lambda value: not value)
        notice = ui.label().classes('text-sm text-amber-200 break-words').props('role=alert')
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg'):
            preview_panel = ui.column().classes('w-full')

        async def preview():
            key = choice.value
            if panel.is_deleted or working['value'] or dialog.value or key not in available:
                return
            run = available[key]
            identity = (run['schedule_id'], run['run_count'])
            expected = run['archived_review_sha256']
            working['value'] = True
            notice.set_text('')
            try:
                info = await asyncio.to_thread(manager.archived_video_info, *identity, expected_run_sha256=expected)
            except (OSError, ValueError, RuntimeError) as error:
                if not panel.is_deleted and choice.value == key:
                    notice.set_text(f'지난 회차 검토본을 열 수 없습니다: {error}')
                return
            finally:
                working['value'] = False
            if panel.is_deleted or dialog.is_deleted or choice.value != key:
                return
            preview_panel.clear()
            with preview_panel:
                deferred = run['last_result'] == 'private_review_deferred'
                ui.label(f'{run["last_script"].get("title", run["name"])} · 회차 {run["run_count"]}').classes(
                    'text-lg font-bold break-words')
                ui.label('채택 보류' if deferred else '채택 완료').classes('text-sm')
                ui.video(media_source(info['video_path'])).props('controls playsinline').classes(
                    'w-full max-w-[220px] max-h-[340px] bg-black')
                youtube_id = info['youtube_id']
                ui.link('YouTube에서 보기', f'https://www.youtube.com/shorts/{youtube_id}', new_tab=True)
                receipt = run.get('review_continuation')
                if isinstance(receipt, dict) and isinstance(receipt.get('note'), str):
                    ui.label(f'당시 검토 메모 · {receipt["note"]}').classes('text-sm break-words')
                if deferred:
                    ui.label('채택하면 지난 회차에만 게시 후보로 기록합니다. 공개는 YouTube Studio에서 결정합니다.').classes('text-sm')
                error_label = ui.label().classes('text-sm text-amber-200 break-words').props('role=alert')

                async def accept():
                    if (panel.is_deleted or error_label.is_deleted or dialog.is_deleted or not dialog.value
                            or choice.value != key or state.is_busy or working['value']):
                        return
                    working['value'] = True
                    error_label.set_text('')
                    try:
                        await asyncio.to_thread(manager.accept_archived_video, *identity, expected_run_sha256=expected)
                    except (OSError, ValueError, RuntimeError) as error:
                        if not error_label.is_deleted:
                            error_label.set_text(f'채택 중단: {error}')
                        return
                    finally:
                        working['value'] = False
                    if not panel.is_deleted:
                        dialog.close()
                        refresh()
                        safe_notify('지난 회차의 완성본 채택을 기록했습니다.', type='positive')

                with ui.row().classes('flex-wrap'):
                    ui.button('닫기', on_click=dialog.close).props('flat').classes('min-h-[44px]').bind_enabled_from(
                        working, 'value', lambda value: not value)
                    if deferred:
                        ui.button('지난 회차 완성본 채택', on_click=accept).props('color=teal').classes(
                            'min-h-[44px]').bind_enabled_from(state, 'is_busy', lambda busy: not busy and not working['value'])
            dialog.open()

        ui.button('선택한 지난 회차 검토본 보기', on_click=preview).props('flat icon=play_circle').classes(
            'min-h-[44px]').bind_enabled_from(working, 'value', lambda value: not value and choice.value in available)
