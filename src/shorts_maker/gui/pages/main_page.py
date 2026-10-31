"""메인 페이지 레이아웃 - Google AI Studio 스타일 개편"""

from nicegui import ui

from shorts_maker.gui.state import get_session_state
from shorts_maker.gui.components import (
    render_pipeline_tab,
    render_sources_tab,
    render_planning_tab,
    render_generation_tab,
    render_publishing_tab,
    render_scheduling_tab,
)
from shorts_maker.gui.config.constants import SIDEBAR_HEIGHT, PHASE_NAMES, PHASE_ICONS
from shorts_maker.gui.config.ui_theme import PHASE_COLORS, SIDEBAR_LEFT, WORKSPACE_CENTER, CONFIG_PANEL_RIGHT
from shorts_maker.services.production_service import ProductionPhase
from shorts_maker.utils.bgm_manager import BGMManager
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger

logger = get_logger(__name__)


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
                container.classes(remove='bg-violet-600 bg-teal-600 bg-pink-600', add='bg-rose-600')
            elif i < current_idx:  # Completed
                container.classes(remove='bg-slate-800 bg-pink-600 bg-rose-600', add='bg-emerald-600')
            elif i == current_idx:  # Current
                container.classes(remove='bg-slate-800 bg-emerald-600 bg-rose-600', add='bg-violet-600')
            else:  # Pending
                container.classes(remove='bg-emerald-600 bg-violet-600 bg-rose-600', add='bg-slate-800')
        except RuntimeError:
            pass


def render_main_page() -> None:
    """메인 페이지 렌더링 - 3단 분할 레이아웃"""
    state = get_session_state()
    step_indicators = []

    # 전체 화면 바인딩
    with ui.column().classes('w-full min-h-screen lg:h-screen bg-slate-950 overflow-y-auto lg:overflow-hidden flex flex-col'):

        # === 1. TOP HEADER ===
        with ui.element('header').classes('w-full bg-slate-900 border-b border-slate-800 px-4 lg:px-6 py-3 flex flex-wrap items-center justify-between gap-3 shrink-0'):
            # 로고 및 타이틀
            with ui.row().classes('items-center gap-3'):
                ui.icon('movie', size='md').classes('text-violet-400')
                with ui.column().classes('gap-0'):
                    ui.label('ShortsMaker Studio').classes('text-lg font-bold text-white leading-none')
                    # 활성화된 스크립트 상태 노출
                    ui.label().bind_text_from(
                        state, 'script', backward=lambda script: f'Project: {script.title}' if script else 'Project: No script selected'
                    ).classes('text-xs text-slate-400 mt-1')

            # 파이프라인 단계 표시기 (헤더 중앙 배치)
            with ui.row().classes('items-center gap-2 max-lg:hidden'):
                for i, (phase_name, phase_icon) in enumerate(zip(PHASE_NAMES, PHASE_ICONS)):
                    container = ui.element('div').classes(
                        'w-7 h-7 rounded-full bg-slate-800 flex items-center justify-center transition-all'
                    )
                    with container:
                        icon = ui.icon(phase_icon, size='xs').classes('text-white')
                    label = ui.label(phase_name).classes('text-xs text-slate-400')

                    step_indicators.append((container, icon, label))
                    if i < len(PHASE_NAMES) - 1:
                        ui.element('div').classes('w-3 h-0.5 bg-slate-800')

            # 파이프라인 퀵 실행 및 취소 버튼
            with ui.row().classes('items-center gap-3'):
                async def run_entire_pipeline():
                    if state.pipeline_running:
                        ui.notify('이미 파이프라인이 구동 중입니다.', type='warning')
                        return
                    ui.notify('출처 기반 각본 기획을 시작합니다...', type='info')
                    state.pipeline_running = True
                    state.final_video_path = None
                    try:
                        service = state.new_production_service()
                        # UI 진행상황 갱신을 위해 콜백 동기화
                        service.set_progress_callback(lambda p: state.sync_from_progress(p))
                        # 백그라운드 태스크로 구동
                        result = await service.full_pipeline(auto_upload=False)
                        if result.script:
                            state.script = result.script
                        if result.ready_for_upload:
                            state.final_video_path = result.video_path
                        if result.clips:
                            state.generated_clips = result.clips
                        if result.review_pending:
                            ui.notify('각본을 만들었습니다. Script Editor에서 장면을 검토하고 확인하세요.', type='info')
                        elif result.success:
                            ui.notify(
                                f'제작 완료 · 예상 비주얼 API 비용 ${result.estimated_visual_cost_usd:.3f}',
                                type='positive',
                            )
                        else:
                            ui.notify(f'제작 실패: {result.error}', type='negative')
                    except Exception as e:
                        ui.notify(f'실행 실패: {e}', type='negative')
                    finally:
                        state.pipeline_running = False

                def stop_pipeline():
                    if not state.pipeline_running:
                        ui.notify('실행 중인 파이프라인이 없습니다.', type='info')
                        return
                    if state.production_service:
                        state.production_service.cancel()
                    state.pipeline_message = '취소 요청됨 — 현재 작업 종료 대기 중'
                    ui.notify('⚠️ 파이프라인 취소가 요청되었습니다.', type='warning')

                ui.button('Plan Script', on_click=run_entire_pipeline).props('color=violet size=sm icon=play_arrow unelevated').classes('rounded font-semibold text-xs')
                ui.button(on_click=stop_pipeline).props('flat round color=red icon=stop size=sm aria-label="파이프라인 중단"').classes('bg-slate-800/80')

        # === 2. MAIN BODY (3단 분할 레이아웃) ===
        with ui.row().classes('w-full flex-1 min-h-0 flex flex-col lg:flex-row overflow-y-auto lg:overflow-hidden no-wrap'):

            # --- 2A. LEFT SIDEBAR RAIL (좌측 메뉴 바) ---
            with ui.element('div').classes(SIDEBAR_LEFT):
                with ui.column().classes('w-full items-center justify-center gap-2 lg:gap-4 flex-row lg:flex-col'):
                    menu_items = [
                        ('workspace', 'edit_document', 'Studio'),
                        ('pipeline', 'rocket_launch', 'Console'),
                        ('sources', 'rss_feed', 'Sources'),
                        ('scheduling', 'schedule', 'Cron'),
                        ('publishing', 'cloud_upload', 'Publish'),
                    ]

                    buttons = {}

                    def make_select_view_fn(view_name):
                        return lambda: select_view(view_name)

                    for view, icon, tooltip in menu_items:
                        btn = ui.button(icon=icon).props(f'flat round color=gray size=md aria-label="{tooltip}"')
                        with ui.tooltip(tooltip).classes('bg-slate-700 text-white'):
                            ui.label(tooltip)
                        btn.on('click', make_select_view_fn(view))
                        buttons[view] = btn

                # 하단 정보 아이콘
                with ui.column().classes('items-center max-lg:hidden'):
                    ui.icon('info', size='xs').classes('text-slate-600')
                    ui.label('v0.3').classes('text-[10px] text-slate-600 font-mono mt-1')

            # --- 2B. CENTER WORKSPACE (중앙 동적 워크스페이스) ---
            center_container = ui.element('div').classes(WORKSPACE_CENTER)

            # --- 2C. RIGHT CONFIG PANEL (우측 설정 패널 - Google AI Studio 스타일) ---
            with ui.element('div').classes(CONFIG_PANEL_RIGHT):
                ui.label('Model Settings').classes('text-xs font-bold text-slate-400 uppercase tracking-widest mb-4')

                # Generation Mode
                ui.label('MODEL TYPE').classes('text-[10px] text-slate-400 font-semibold mb-1')
                mode_select = ui.select(
                    options={
                        'hybrid': 'Hybrid · Veo hook + Gemini images',
                        'image': 'Gemini images',
                        'video': 'Google Veo 3.1 videos',
                    },
                    value=state.mode
                ).props('outlined dense dark aria-label="비주얼 생성 모드"').classes('w-full mb-4')

                def on_mode_change(e):
                    state.mode = e.value
                    ui.notify(f'생성 모드가 {e.value.upper()}로 전환되었습니다.', type='info')
                    if state.current_view == 'workspace' and state.workspace_sub_tab == 'preview':
                        render_active_view()
                mode_select.on_value_change(on_mode_change)

                # Cost/API Mode Toggle
                ui.label('GENERATION SOURCE').classes('text-[10px] text-slate-400 font-semibold mb-1')
                api_source_radio = ui.radio(
                    ['Vertex AI API (Auto)', 'Local File (Manual)'],
                    value='Local File (Manual)' if state.manual_video_mode else 'Vertex AI API (Auto)'
                ).props('color=violet size=32px').classes('w-full text-xs text-slate-300 mb-4')

                def on_api_source_change(e):
                    state.manual_video_mode = (e.value == 'Local File (Manual)')
                    ui.notify(f'소스 모드: {e.value}', type='info')
                    if state.current_view == 'workspace' and state.workspace_sub_tab == 'preview':
                        render_active_view()
                api_source_radio.on_value_change(on_api_source_change)

                ui.separator().classes('bg-slate-800 my-2')

                # Character Overlay Parameter Panel
                ui.label('Character Overlay').classes('text-xs font-bold text-slate-400 uppercase tracking-widest mt-2 mb-3')

                overlay_checkbox = ui.checkbox('Enable Overlay', value=state.character_overlay_enabled).props('color=violet').classes('text-xs text-slate-300 mb-2')
                overlay_checkbox.bind_value(state, 'character_overlay_enabled')

                with ui.column().bind_visibility_from(overlay_checkbox, 'value'):
                    ui.label('POSITION').classes('text-[10px] text-slate-400 font-semibold mb-1')
                    pos_select = ui.select(
                        options={
                            'bottom_right': 'Bottom Right',
                            'bottom_left': 'Bottom Left',
                            'top_right': 'Top Right',
                            'top_left': 'Top Left'
                        },
                        value=state.character_position
                    ).props('outlined dense dark').classes('w-full mb-3')
                    pos_select.bind_value(state, 'character_position')

                    ui.label('SIZE RATIO').classes('text-[10px] text-slate-400 font-semibold mb-1')
                    size_slider = ui.slider(min=0.1, max=0.5, step=0.05, value=state.character_size_ratio).props('color=violet aria-label="캐릭터 크기"')
                    size_label = ui.label(f'{int(state.character_size_ratio * 100)}%').classes('text-xs text-slate-400 self-end -mt-2 mb-3')
                    size_slider.bind_value(state, 'character_size_ratio')
                    size_slider.on('change', lambda e: size_label.set_text(f'{int(e.value * 100)}%'))

                ui.separator().classes('bg-slate-800 my-2')

                # Audio & Subtitle Parameters
                ui.label('Audio & Text Settings').classes('text-xs font-bold text-slate-400 uppercase tracking-widest mt-2 mb-3')

                ui.label('TTS VOICE').classes('text-[10px] text-slate-400 font-semibold mb-1')
                voice_select = ui.select(
                    options={'alloy': 'Alloy (Default)', 'echo': 'Echo (Deep)', 'fable': 'Fable (Narrator)', 'onyx': 'Onyx', 'nova': 'Nova', 'shimmer': 'Shimmer'},
                    value=state.tts_voice
                ).props('outlined dense dark aria-label="TTS 음성"').classes('w-full mb-3')
                voice_select.bind_value(state, 'tts_voice')

                ui.label('BGM MOOD').classes('text-[10px] text-slate-400 font-semibold mb-1')
                bgm_manager = BGMManager()
                mood_options = {'auto': 'Follow Script (matching track needed)'}
                mood_options.update({mood: label for mood, label in {
                    'calm': 'Calm & Soft', 'sci-fi': 'Sci-Fi', 'futuristic': 'Curious Tech',
                    'mysterious': 'Mysterious', 'energetic': 'Energetic Pop',
                    'dark': 'Dark Mystery', 'synthwave': 'Retro Synthwave',
                }.items() if bgm_manager.get_bgm_path(mood)})
                if state.bgm_mood not in mood_options:
                    mood_options[state.bgm_mood] = f'Unavailable: {state.bgm_mood}'
                bgm_select = ui.select(
                    options=mood_options,
                    value=state.bgm_mood
                ).props('outlined dense dark aria-label="BGM 분위기"').classes('w-full mb-3')
                bgm_select.bind_value(state, 'bgm_mood')
                ui.label('Auto stops before narration if no licensed track matches the script mood.') \
                    .classes('text-[10px] text-slate-400 mb-2')

                ui.label('BGM TRACK').classes('text-[10px] text-slate-400 font-semibold mb-1')
                track_options = {'': 'Auto by mood'}
                track_options.update(bgm_manager.list_documented_tracks())
                if state.bgm_track and state.bgm_track not in track_options:
                    track_options[state.bgm_track] = f'Unavailable: {state.bgm_track}'
                bgm_track_select = ui.select(
                    options=track_options,
                    value=state.bgm_track,
                ).props('outlined dense dark aria-label="BGM 트랙"').classes('w-full mb-1')
                bgm_track_select.bind_value(state, 'bgm_track')
                ui.label('Choose an exact licensed track after listening; it overrides the mood.') \
                    .classes('text-[10px] text-slate-400 mb-3')

                ui.label('BGM LEVEL').classes('text-[10px] text-slate-400 font-semibold mb-1')
                bgm_slider = ui.slider(min=0, max=1, step=0.05, value=state.bgm_volume).props('color=violet aria-label="BGM 음량"')
                bgm_label = ui.label(f'{int(state.bgm_volume * 100)}%').classes('text-xs text-slate-400 self-end -mt-2 mb-3')
                bgm_slider.bind_value(state, 'bgm_volume')
                bgm_label.bind_text_from(state, 'bgm_volume', backward=lambda value: f'{int(value * 100)}%')
                def save_audio_choices():
                    try:
                        state.save_audio_choices()
                        ui.notify('현재 각본의 음성·음악 설정을 저장했습니다.', type='positive')
                    except (OSError, ValueError) as error:
                        ui.notify(f'설정 저장 실패: {error}', type='negative')

                ui.button('각본별 음성·음악 설정 저장', on_click=save_audio_choices).props(
                    'flat dense icon=save').classes('w-full').bind_enabled_from(state, 'script', bool)

                ui.separator().classes('bg-slate-800 my-2')

                # API Keys Config (Inline for fast edit)
                ui.label('API Credentials').classes('text-xs font-bold text-slate-400 uppercase tracking-widest mt-2 mb-3')

                openai_input = ui.input('OpenAI Key', value=state.openai_key, password=True, password_toggle_button=True).props('outlined dense dark').classes('w-full mb-2')
                openai_input.bind_value(state, 'openai_key')

                gcp_input = ui.input('GCP Project ID', value=state.gcp_project).props('outlined dense dark').classes('w-full mb-3')
                gcp_input.bind_value(state, 'gcp_project')

                def save_sidebar_settings():
                    if state.openai_key or state.gcp_project:
                        settings.update_api_keys(openai_key=state.openai_key, gcp_project=state.gcp_project)
                        state.production_service = None
                    ui.notify('설정이 성공적으로 로드되었습니다!', type='positive')

                ui.button('Save settings', on_click=save_sidebar_settings).props('color=violet size=sm icon=save unelevated').classes('w-full py-1 text-xs')

            # --- DYNAMIC RENDERING LOGIC (중앙 뷰 스위처) ---
            def select_view(view_name: str):
                """현재 뷰를 갱신하고 활성화된 버튼 하이라이트"""
                state.current_view = view_name

                # 모든 버튼 색상 리셋 및 선택 하이라이트
                for name, btn in buttons.items():
                    if name == view_name:
                        btn.props('color=violet')
                        btn.classes('bg-violet-950/40')
                    else:
                        btn.props('color=gray')
                        btn.classes(remove='bg-violet-950/40')

                render_active_view()

            def render_active_view():
                """중앙 컨테이너 비우고 현재 뷰에 맞춤 렌더링"""
                center_container.clear()

                with center_container:
                    if state.current_view == 'workspace':
                        # Google AI Studio 워크스페이스: 내부 상단에 Prompt Editor / Visual Preview 토글 바 제공
                        with ui.element('div').classes('w-full bg-slate-900 border-b border-slate-800 px-3 lg:px-6 py-2 flex flex-wrap items-center justify-between gap-2 shrink-0'):
                            with ui.row().classes('items-center gap-1'):
                                ui.icon('psychology', size='xs').classes('text-violet-400')
                                ui.label('Workspace Studio').classes('text-sm font-bold text-white mr-4')

                                # 하위 탭 토글
                                with ui.button_group().props('rounded dense size=xs'):
                                    editor_btn = ui.button('1. Script & Prompt Editor').props(
                                        f'{"color=violet" if state.workspace_sub_tab == "editor" else "outline color=gray"}'
                                    )
                                    preview_btn = ui.button('2. Visual & Clip Preview').props(
                                        f'{"color=violet" if state.workspace_sub_tab == "preview" else "outline color=gray"}'
                                    )

                                    def set_sub_tab(tab_name):
                                        state.workspace_sub_tab = tab_name
                                        render_active_view()

                                    editor_btn.on('click', lambda: set_sub_tab('editor'))
                                    preview_btn.on('click', lambda: set_sub_tab('preview'))

                            ui.label('AI Studio Mode').classes('rounded bg-violet-950 text-violet-200 text-[10px] px-2 py-0.5')

                        # 하위 탭 분기 렌더링
                        with ui.element('div').classes('w-full flex-grow overflow-auto p-3 lg:p-6'):
                            if state.workspace_sub_tab == 'editor':
                                render_planning_tab(state)
                            else:
                                render_generation_tab(state)

                    elif state.current_view == 'pipeline':
                        with ui.element('div').classes('w-full bg-slate-900 border-b border-slate-800 px-6 py-3 flex items-center gap-2 shrink-0'):
                            ui.icon('terminal', size='xs').classes('text-teal-400')
                            ui.label('Script Planning Console').classes('text-sm font-bold text-white')
                        with ui.element('div').classes('w-full flex-grow overflow-auto p-3 lg:p-6'):
                            render_pipeline_tab(
                                state,
                                step_indicators=step_indicators,
                                update_step_indicators_fn=update_step_indicators
                            )

                    elif state.current_view == 'sources':
                        with ui.element('div').classes('w-full bg-slate-900 border-b border-slate-800 px-6 py-3 flex items-center gap-2 shrink-0'):
                            ui.icon('rss_feed', size='xs').classes('text-orange-400')
                            ui.label('Content Sources & RSS Management').classes('text-sm font-bold text-white')
                        with ui.element('div').classes('w-full flex-grow overflow-auto p-3 lg:p-6'):
                            render_sources_tab(state)

                    elif state.current_view == 'scheduling':
                        with ui.element('div').classes('w-full bg-slate-900 border-b border-slate-800 px-6 py-3 flex items-center gap-2 shrink-0'):
                            ui.icon('schedule', size='xs').classes('text-amber-400')
                            ui.label('Cron Automation Scheduler').classes('text-sm font-bold text-white')
                        with ui.element('div').classes('w-full flex-grow overflow-auto p-3 lg:p-6'):
                            render_scheduling_tab(state)

                    elif state.current_view == 'publishing':
                        with ui.element('div').classes('w-full bg-slate-900 border-b border-slate-800 px-6 py-3 flex items-center gap-2 shrink-0'):
                            ui.icon('cloud_upload', size='xs').classes('text-rose-400')
                            ui.label('YouTube Publishing & Downloads').classes('text-sm font-bold text-white')
                        with ui.element('div').classes('w-full flex-grow overflow-auto p-3 lg:p-6'):
                            render_publishing_tab(state)

            # 최초 기본 뷰 설정 및 구동
            select_view(state.current_view)
