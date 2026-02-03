"""파이프라인 단계 표시기"""

from nicegui import ui
from typing import Dict

from shorts_maker.gui.config.ui_theme import PHASE_COLORS
from shorts_maker.gui.config.constants import PHASE_NAMES, PHASE_ICONS


def create_step_indicators() -> Dict[str, Dict]:
    """
    파이프라인 단계 표시기 생성.

    Returns:
        Dict with 'progress_bars', 'phase_labels', 'phase_time_labels' keys
    """
    progress_bars = {}
    phase_labels = {}
    phase_time_labels = {}

    with ui.row().classes('w-full gap-1 mb-4'):
        for i, (phase, color) in enumerate(zip(PHASE_NAMES, PHASE_COLORS)):
            with ui.column().classes('flex-1 gap-1'):
                # Phase label
                phase_labels[phase] = ui.label('Pending').classes(
                    'text-[10px] text-gray-400 text-center w-full'
                )

                # Progress bar
                progress_bars[phase] = ui.linear_progress(
                    value=0, show_value=False
                ).props(f'color={color}').classes('h-1')

                # Time label
                with ui.row().classes('items-center justify-center gap-1'):
                    ui.icon(
                        PHASE_ICONS[i],
                        size='xs'
                    ).classes(f'text-{color}-400')
                    phase_time_labels[phase] = ui.label('').classes(
                        'text-[10px] text-gray-500'
                    )

    return {
        'progress_bars': progress_bars,
        'phase_labels': phase_labels,
        'phase_time_labels': phase_time_labels
    }


def update_step_indicator(
    phase_labels: Dict[str, ui.label],
    phase: str,
    status: str,
    color_class: str
) -> None:
    """
    특정 단계의 상태 업데이트.

    Args:
        phase_labels: 단계 라벨 딕셔너리
        phase: 단계 이름
        status: 상태 텍스트
        color_class: Tailwind 색상 클래스
    """
    if phase in phase_labels:
        label = phase_labels[phase]
        label.text = status
        label.classes(
            remove='text-gray-400 text-teal-400 text-pink-400 text-red-400',
            add=color_class
        )
