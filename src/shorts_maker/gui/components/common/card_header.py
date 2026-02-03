"""재사용 가능한 카드 헤더 컴포넌트"""

from nicegui import ui
from typing import Optional

from shorts_maker.gui.config.ui_theme import GRADIENTS, CARD_BASE, HEADER_TEXT


def card_with_header(
    title: str,
    icon: str,
    gradient: str = 'primary',
    badge_text: Optional[str] = None
):
    """
    헤더가 있는 카드 컴포넌트 생성.

    Args:
        title: 카드 제목
        icon: Material icon 이름
        gradient: GRADIENTS의 키 또는 직접 지정된 그라디언트
        badge_text: 선택적 뱃지 텍스트

    Returns:
        card: 카드 컨텍스트 (with 문에서 사용)

    Example:
        with card_with_header('Settings', 'settings', 'primary') as card:
            ui.label('Content here')
    """
    gradient_class = GRADIENTS.get(gradient, gradient)

    card = ui.card().classes(CARD_BASE)

    with card:
        with ui.element('div').classes(f'w-full p-4 bg-gradient-to-r {gradient_class}'):
            with ui.row().classes('items-center gap-3'):
                ui.icon(icon, size='md').classes('text-white')
                ui.label(title).classes(HEADER_TEXT)
                if badge_text:
                    ui.badge(badge_text).classes('bg-white/20 text-white text-xs')

    return card


def section_header(title: str, icon: str, color: str = 'teal'):
    """
    섹션 내 작은 헤더.

    Args:
        title: 헤더 제목
        icon: Material icon 이름
        color: 아이콘 색상 (tailwind color name)
    """
    with ui.element('div').classes('w-full p-3 border-b border-slate-700'):
        with ui.row().classes('items-center gap-2'):
            ui.icon(icon, size='xs').classes(f'text-{color}-400')
            ui.label(title).classes(f'text-sm font-bold text-{color}-300')
