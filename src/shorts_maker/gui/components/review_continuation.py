"""Continue an RSS cadence explicitly without adopting its private review copy."""
from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.services.operating_status import schedule_sha256


def render_review_continuation(state, manager, schedule, refresh):
    expected = schedule_sha256(schedule)
    with ui.column().classes('gap-1') as view:
        def open_dialog():
            if view.is_deleted or state.is_busy:
                return
            with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg'):
                ui.label('채택을 보류하고 다음 회차를 예약할까요?').classes('text-lg')
                ui.label('기존 대본·검토본·비용과 미채택 상태를 보존합니다. 기존14일/28일 기준을 유지하고 다음 소재를 예약합니다. 공개 전환·즉시 제작·추가 예산 승인은 아닙니다.').classes('text-sm')
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
