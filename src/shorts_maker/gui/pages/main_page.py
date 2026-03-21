"""메인 페이지 레이아웃"""

from nicegui import ui, app
import uuid
from typing import Dict, Any

from shorts_maker.gui.state.app_state import AppState
from shorts_maker.gui.components import (
    render_pipeline_tab,
    render_sources_tab,
    render_planning_tab,
    render_generation_tab,
    render_publishing_tab,
    render_scheduling_tab,
)
from shorts_maker.gui.config.constants import SIDEBAR_HEIGHT, PHASE_NAMES, PHASE_ICONS
from shorts_maker.gui.config.ui_theme import PHASE_COLORS
from shorts_maker.services.production_service import ProductionPhase
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger

logger = get_logger(__name__)


class SessionManager:
    """세션별 상태를 관리하는 매니저 클래스"""
    _sessions: Dict[str, AppState] = {}

    @classmethod
    def get_state(cls, session_id: str) -> AppState:
        """세션 ID에 해당하는 상태 반환 (없으면 생성)"""
        if session_id not in cls._sessions:
            cls._sessions[session_id] = AppState()
            # 초기 설정 로드
            state = cls._sessions[session_id]
            state.mode = settings.generation_mode
            state.openai_key = settings.openai_api_key
            state.gcp_project = settings.gcp_project_id
        return cls._sessions[session_id]

    @classmethod
    def cleanup_session(cls, session_id: str):
        """세션 정리"""
        if session_id in cls._sessions:
            del cls._sessions[session_id]


def get_session_state() -> AppState:
    """현재 세션의 상태를 반환"""
    if 'session_id' not in app.storage.browser:
        app.storage.browser['session_id'] = str(uuid.uuid4())
    session_id = app.storage.browser['session_id']
    return SessionManager.get_state(session_id)


def update_step_indicators(phase: ProductionPhase, step_indicators: list) -> None:
    """헤더의 단계 표시기 업데이트"""
    phase_index_map = {
        ProductionPhase.IDLE: -1,
        ProductionPhase.PLANNING: 0,
        ProductionPhase.GENERATING: 1,
        ProductionPhase.EDITING: 2,
        ProductionPhase.UPLOADING: 3,
        ProductionPhase.COMPLETED: 4,
        ProductionPhase.FAILED: -2,
    }

    current_idx = phase_index_map.get(phase, -1)

    for i, (container, icon, label) in enumerate(step_indicators):
        try:
            if current_idx == -2:  # Failed
                container.classes(remove='bg-teal-600 bg-pink-600', add='bg-red-600')
            elif i < current_idx:  # Completed
                container.classes(remove='bg-slate-700 bg-pink-600', add='bg-teal-600')
            elif i == current_idx:  # Current
                container.classes(remove='bg-slate-700 bg-teal-600', add='bg-pink-600')
            else:  # Pending
                container.classes(remove='bg-teal-600 bg-pink-600', add='bg-slate-700')
        except RuntimeError:
            pass


def render_main_page() -> None:
    """메인 페이지 렌더링"""

    # 현재 세션 상태 가져오기
    state = get_session_state()

    # Step indicators for header
    step_indicators = []

    with ui.column().classes('w-full h-screen bg-slate-900 overflow-hidden flex flex-col'):
        # === Header ===
        with ui.element('header').classes('w-full bg-slate-800 border-b border-slate-700 sticky top-0 z-50'):
            with ui.row().classes('w-full max-w-screen-2xl mx-auto px-6 py-3 items-center justify-between'):
                # Logo
                with ui.row().classes('items-center gap-3'):
                    ui.icon('movie', size='lg').classes('text-teal-400')
                    ui.label('ShortsMaker Studio').classes('text-xl font-bold text-white')
                    ui.badge('v0.2').classes('bg-slate-700 text-gray-400 text-xs')

                # Step Indicators (Pipeline Progress)
                with ui.row().classes('items-center gap-2'):
                    for i, (phase_name, phase_icon, phase_color) in enumerate(
                        zip(PHASE_NAMES, PHASE_ICONS, PHASE_COLORS)
                    ):
                        container = ui.element('div').classes(
                            f'w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center transition-all'
                        )
                        with container:
                            icon = ui.icon(phase_icon, size='xs').classes('text-white')
                        label = ui.label(phase_name).classes('text-xs text-gray-500 hidden md:block')

                        step_indicators.append((container, icon, label))

                        if i < len(PHASE_NAMES) - 1:
                            ui.element('div').classes('w-4 h-0.5 bg-slate-600')

                # Settings & Mode Toggle
                with ui.row().classes('items-center gap-3'):
                    # Mode Toggle
                    with ui.button_group().props('rounded dense'):
                        def set_image_mode():
                            state.mode = 'image'

                        def set_video_mode():
                            state.mode = 'video'

                        img_btn = ui.button('IMG', on_click=set_image_mode).props(
                            f'{"outline" if state.mode == "video" else ""} color=blue size=sm'
                        )
                        vid_btn = ui.button('VID', on_click=set_video_mode).props(
                            f'{"outline" if state.mode == "image" else ""} color=purple size=sm'
                        )

                    # Settings Dialog
                    with ui.dialog() as settings_dialog, ui.card().classes('p-6 bg-slate-800 min-w-[400px]'):
                        ui.label('Settings').classes('text-xl font-bold text-white mb-4')

                        ui.label('API Keys').classes('text-sm font-bold text-gray-400 uppercase tracking-wider mb-2')

                        openai_input = ui.input(
                            'OpenAI API Key',
                            value=state.openai_key,
                            password=True,
                            password_toggle_button=True
                        ).props('outlined dark').classes('w-full mb-3')
                        openai_input.bind_value(state, 'openai_key')

                        gcp_input = ui.input(
                            'GCP Project ID',
                            value=state.gcp_project
                        ).props('outlined dark').classes('w-full mb-4')
                        gcp_input.bind_value(state, 'gcp_project')

                        def save_settings():
                            if state.openai_key or state.gcp_project:
                                settings.update_api_keys(
                                    openai_key=state.openai_key,
                                    gcp_project=state.gcp_project
                                )
                            ui.notify('Settings saved!', type='positive')
                            settings_dialog.close()

                        with ui.row().classes('w-full justify-end gap-2'):
                            ui.button('Cancel', on_click=settings_dialog.close).props('flat color=gray')
                            ui.button('Save', on_click=save_settings).props('color=teal')

                    ui.button(icon='settings', on_click=settings_dialog.open).props('flat round color=gray')

        # === Main Content with Tabs ===
        with ui.element('main').classes('w-full flex-grow flex flex-col overflow-hidden'):
            with ui.tabs().classes('w-full bg-slate-800 border-b border-slate-700 shrink-0') as tabs:
                pipeline_tab = ui.tab('Pipeline', icon='rocket_launch').classes('text-teal-400')
                sources_tab = ui.tab('Sources', icon='rss_feed').classes('text-orange-400')
                planning_tab = ui.tab('Planning', icon='psychology').classes('text-pink-400')
                generation_tab = ui.tab('Generation', icon='movie_creation').classes('text-purple-400')
                publishing_tab = ui.tab('Publishing', icon='cloud_upload').classes('text-red-400')
                scheduling_tab = ui.tab('Scheduling', icon='schedule').classes('text-amber-400')

            with ui.tab_panels(tabs, value=pipeline_tab).classes('w-full flex-grow bg-slate-900 overflow-hidden'):
                with ui.tab_panel(pipeline_tab).classes('p-6 h-full overflow-auto'):
                    render_pipeline_tab(
                        state,
                        step_indicators=step_indicators,
                        update_step_indicators_fn=update_step_indicators
                    )

                with ui.tab_panel(sources_tab).classes('p-6 h-full overflow-auto'):
                    render_sources_tab(state)

                with ui.tab_panel(planning_tab).classes('p-0 h-full overflow-hidden'):
                    render_planning_tab(state)

                with ui.tab_panel(generation_tab).classes('p-0 h-full overflow-hidden'):
                    render_generation_tab(state)

                with ui.tab_panel(publishing_tab).classes('p-6 h-full overflow-auto'):
                    render_publishing_tab(state)

                with ui.tab_panel(scheduling_tab).classes('p-6 h-full overflow-auto'):
                    render_scheduling_tab(state)

        # === Footer ===
        with ui.element('footer').classes('w-full bg-slate-800 border-t border-slate-700 py-3'):
            with ui.row().classes('w-full max-w-screen-2xl mx-auto px-6 items-center justify-between'):
                ui.label('ShortsMaker Studio © 2024').classes('text-xs text-gray-500')
                with ui.row().classes('items-center gap-4'):
                    ui.link('GitHub', 'https://github.com').classes('text-xs text-gray-500 hover:text-teal-400')
                    ui.link('Docs', '#').classes('text-xs text-gray-500 hover:text-teal-400')
