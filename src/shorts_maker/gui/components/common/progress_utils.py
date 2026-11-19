"""진행률 표시 관련 공통 유틸리티 함수"""

from nicegui import ui
from typing import List

from shorts_maker.gui.config.ui_theme import SCENE_GRADIENTS


def format_time(seconds: float) -> str:
    """시간 포맷팅 (분:초)
    
    Args:
        seconds: 초 단위 시간
        
    Returns:
        "분:초" 형식의 문자열 (예: "1:30")
    """
    if seconds < 0:
        return "--:--"
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}:{secs:02d}"


def update_scene_grid(scene_progresses: List, scene_grid: ui.element) -> None:
    """씬 그리드 UI 업데이트
    
    각 씬의 진행 상황을 카드 형태로 표시합니다.
    
    Args:
        scene_progresses: 씬별 진행 정보 리스트
        scene_grid: 업데이트할 UI 컨테이너
    """
    try:
        scene_grid.clear()
        with scene_grid:
            if not scene_progresses:
                # 플레이스홀더
                with ui.column().classes('w-full items-center justify-center py-6'):
                    ui.icon('burst_mode', size='lg').classes('text-slate-700')
                    ui.label('Scene thumbnails will appear here').classes('text-xs text-gray-600')
                return

            for i, scene_prog in enumerate(scene_progresses):
                status = getattr(scene_prog, 'status', 'pending')
                gradient = SCENE_GRADIENTS[i % len(SCENE_GRADIENTS)]
                icon, color, label = {
                    'pending': ('hourglass_empty', 'text-gray-500', '대기'),
                    'processing': ('autorenew', 'text-amber-400 animate-spin', '처리 중'),
                    'completed': ('check_circle', 'text-green-400', '완료'),
                    'failed': ('error', 'text-red-400', '실패'),
                }.get(status, ('help', 'text-gray-400', '상태 확인 필요'))

                # 씬 카드 생성
                with ui.card().classes(f'w-24 h-28 p-2 bg-gradient-to-br {gradient} rounded-lg'):
                    with ui.column().classes('items-center gap-1'):
                        ui.label(f'장면 {scene_prog.scene_number}').classes('text-xs text-white font-bold')
                        ui.icon(icon, size='sm').classes(color)
                        ui.label(label).classes('text-xs text-white/80')

    except RuntimeError:
        # UI 요소가 삭제된 경우 무시
        pass
