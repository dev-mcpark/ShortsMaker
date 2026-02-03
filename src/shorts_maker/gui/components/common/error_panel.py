"""에러 표시 패널 컴포넌트"""

from nicegui import ui
from typing import Tuple


def create_error_panel() -> Tuple[ui.card, ui.label, ui.label]:
    """
    에러 표시 패널 생성.

    Returns:
        tuple: (error_panel, error_message_label, error_details_label)
    """
    error_panel = ui.card().classes(
        'w-full bg-red-900/30 border border-red-500/50'
    )
    error_panel.visible = False

    with error_panel:
        with ui.row().classes('items-start gap-3 p-4'):
            ui.icon('error', size='md').classes('text-red-400')
            with ui.column().classes('flex-grow gap-1'):
                error_message_label = ui.label('Error').classes(
                    'text-red-300 font-bold'
                )
                error_details_label = ui.label('').classes(
                    'text-red-200/70 text-sm'
                )

    return error_panel, error_message_label, error_details_label


def show_error_panel(
    error_panel: ui.card,
    message_label: ui.label,
    details_label: ui.label,
    error_message: str,
    show_details: bool = True
) -> None:
    """
    에러 패널 표시.

    Args:
        error_panel: 에러 패널 카드
        message_label: 메시지 라벨
        details_label: 상세 정보 라벨
        error_message: 에러 메시지
        show_details: 상세 정보 표시 여부
    """
    error_panel.visible = True
    message_label.text = 'Pipeline Error'

    if show_details:
        # 에러 메시지 잘라서 표시
        short_msg = error_message[:200] + '...' if len(error_message) > 200 else error_message
        details_label.text = short_msg
    else:
        details_label.text = ''


def hide_error_panel(error_panel: ui.card) -> None:
    """에러 패널 숨기기."""
    error_panel.visible = False
