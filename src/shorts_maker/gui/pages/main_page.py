"""제작 순서와 검토 경로를 보여주는 Studio 메인 화면."""

from nicegui import ui

from shorts_maker.gui.state import get_session_state
from shorts_maker.gui.components import (
    render_pipeline_tab,
    render_sources_tab,
    render_planning_tab,
    render_generation_tab,
    render_publishing_tab,
    render_scheduling_tab,
    render_asset_library_tab,
)
from shorts_maker.gui.config.ui_theme import SIDEBAR_LEFT, WORKSPACE_CENTER, CONFIG_PANEL_RIGHT
from shorts_maker.utils.bgm_manager import BGMManager
from shorts_maker.utils.config import settings
from shorts_maker.services.openai_models import PRIMARY_CHAT_MODEL


def render_main_page() -> None:
    """메인 페이지 렌더링 - 3단 분할 레이아웃"""
    state = get_session_state()

    # 전체 화면 바인딩
    with ui.column().classes('w-full min-h-screen xl:h-screen bg-slate-950 overflow-y-auto xl:overflow-hidden flex flex-col'):

        # === 1. TOP HEADER ===
        with ui.element('header').classes('w-full bg-slate-900 border-b border-slate-800 px-4 lg:px-6 py-3 flex flex-wrap items-center justify-between gap-3 shrink-0'):
            # 로고 및 타이틀
            with ui.row().classes('items-center gap-3'):
                ui.icon('movie', size='md').classes('text-violet-400')
                with ui.column().classes('gap-0'):
                    ui.label('ShortsMaker Studio').classes('text-lg font-bold text-white leading-none')
                    # 활성화된 스크립트 상태 노출
                    ui.label().bind_text_from(
                        state, 'script', backward=lambda script: f'현재 대본 · {script.title}' if script else '대본을 불러오거나 완성본부터 확인하세요'
                    ).classes('text-xs text-slate-400 mt-1')

            ui.label('대본 검토 → 장면 검토 → 완성본 검토 → 비공개 업로드').classes(
                'text-xs text-slate-400 max-xl:hidden')

            with ui.row().classes('items-center gap-2'):
                ui.badge('직접 제작 · API 과금' if settings.paid_production_enabled else '검토 모드 · API 생성 중지').props(
                    'color=teal' if settings.paid_production_enabled else 'color=blue-grey')
                ui.button('대본 기획', on_click=lambda: select_view('pipeline')).props(
                    'color=violet size=sm icon=edit_note unelevated no-caps')

                def stop_pipeline():
                    if not state.pipeline_running:
                        ui.notify('실행 중인 파이프라인이 없습니다.', type='info')
                        return
                    if state.production_service:
                        state.production_service.cancel()
                    state.pipeline_message = '취소 요청됨 — 현재 작업 종료 대기 중'
                    ui.notify('⚠️ 파이프라인 취소가 요청되었습니다.', type='warning')

                ui.button(on_click=stop_pipeline).props('flat round color=red icon=stop size=sm aria-label="진행 중인 제작 중지 요청"').classes('bg-slate-800/80').bind_enabled_from(state, 'pipeline_running')

        # === 2. MAIN BODY (3단 분할 레이아웃) ===
        with ui.row().classes('w-full flex-1 min-h-0 flex flex-col xl:flex-row overflow-y-auto xl:overflow-hidden no-wrap'):

            # --- 2A. LEFT SIDEBAR RAIL (좌측 메뉴 바) ---
            with ui.element('div').classes(SIDEBAR_LEFT):
                with ui.element('nav').props('aria-label="주 메뉴"').classes('w-full grid grid-cols-3 sm:grid-cols-4 xl:flex xl:flex-col gap-1 px-2'):
                    menu_items = [
                        ('workspace', 'edit_document', '제작 작업실'),
                        ('pipeline', 'playlist_play', '기획·진행 현황'),
                        ('sources', 'rss_feed', '소재·출처'),
                        ('scheduling', 'schedule', '예약 운영'),
                        ('publishing', 'cloud_upload', '완성본·업로드'),
                        ('assets', 'folder_open', '재료 보관함'),
                        ('help', 'help_outline', '사용 안내'),
                    ]

                    buttons = {}

                    def make_select_view_fn(view_name):
                        return lambda: select_view(view_name)

                    for view, icon, tooltip in menu_items:
                        btn = ui.button(tooltip, icon=icon).props('flat no-caps align=left color=gray').classes('w-full min-h-[44px] text-sm text-left')
                        btn.on('click', make_select_view_fn(view))
                        buttons[view] = btn

                # 하단 정보 아이콘
                with ui.column().classes('items-center max-xl:hidden'):
                    ui.icon('info', size='xs').classes('text-slate-600')
                    ui.label('v0.3').classes('text-[10px] text-slate-600 font-mono mt-1')

            # --- 2B. CENTER WORKSPACE (중앙 동적 워크스페이스) ---
            center_container = ui.element('div').classes(WORKSPACE_CENTER)

            # --- 2C. RIGHT CONFIG PANEL (우측 설정 패널 - Google AI Studio 스타일) ---
            with ui.element('div').classes(CONFIG_PANEL_RIGHT):
                ui.label('제작 설정').classes('text-xs font-bold text-slate-400 uppercase tracking-widest mb-4')
                ui.label('음성·음악·화면 변경은 새 편집에 적용됩니다. 완성본 미리보기는 재편집해야 바뀝니다.').classes(
                    'text-xs text-slate-400 leading-relaxed mb-3')

                # Generation Mode
                ui.label('화면 구성 방식').classes('text-[10px] text-slate-400 font-semibold mb-1')
                mode_select = ui.select(
                    options={
                        'hybrid': '혼합 · 오프닝 영상 + 이미지',
                        'image': '이미지 중심',
                        'video': '장면별 Veo 영상',
                    },
                    value=state.mode
                ).props('outlined dense dark aria-label="비주얼 생성 모드"').classes('w-full mb-2').bind_value_from(state, 'mode')
                ui.label(f'대본 모델 · {PRIMARY_CHAT_MODEL}').classes('text-[11px] text-slate-400 break-all')
                ui.label(f'영상 모델 · {settings.veo_model_id}').classes('text-[11px] text-slate-400 break-all mb-3')

                def on_mode_change(e):
                    if state.is_busy:
                        mode_select.value = state.mode
                        return
                    state.mode = e.value
                    ui.notify(f'생성 모드가 {e.value.upper()}로 전환되었습니다.', type='info')
                    if state.current_view == 'workspace' and state.workspace_sub_tab == 'preview':
                        render_active_view()
                mode_select.on_value_change(on_mode_change)
                mode_select.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)

                # Cost/API Mode Toggle
                ui.label('장면 영상 가져오기').classes('text-[10px] text-slate-400 font-semibold mb-1')
                api_source_radio = ui.radio(
                    ['검토 후 API 생성', '보유 영상 직접 연결'],
                    value='보유 영상 직접 연결' if state.manual_video_mode else '검토 후 API 생성'
                ).props('color=violet size=32px').classes('w-full text-xs text-slate-300 mb-4')

                def on_api_source_change(e):
                    if state.is_busy:
                        api_source_radio.value = ('보유 영상 직접 연결' if state.manual_video_mode else '검토 후 API 생성')
                        return
                    state.manual_video_mode = (e.value == '보유 영상 직접 연결')
                    ui.notify(f'소스 모드: {e.value}', type='info')
                    if state.current_view == 'workspace' and state.workspace_sub_tab == 'preview':
                        render_active_view()
                api_source_radio.on_value_change(on_api_source_change)
                api_source_radio.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)

                ui.separator().classes('bg-slate-800 my-2')

                with ui.expansion('고급 · 캐릭터 합성', icon='person').classes('w-full'):
                    # Character Overlay Parameter Panel


                    overlay_checkbox = ui.checkbox('캐릭터 합성 사용', value=state.character_overlay_enabled).props('color=violet').classes('text-xs text-slate-300 mb-2')
                    overlay_checkbox.bind_value(state, 'character_overlay_enabled')
                    overlay_checkbox.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)

                    with ui.column().bind_visibility_from(overlay_checkbox, 'value'):
                        ui.label('위치').classes('text-[10px] text-slate-400 font-semibold mb-1')
                        pos_select = ui.select(
                            options={
                                'bottom_right': '오른쪽 아래',
                                'bottom_left': '왼쪽 아래',
                                'top_right': '오른쪽 위',
                                'top_left': '왼쪽 위'
                            },
                            value=state.character_position
                        ).props('outlined dense dark').classes('w-full mb-3')
                        pos_select.bind_value(state, 'character_position')
                        pos_select.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)

                        ui.label('크기 비율').classes('text-[10px] text-slate-400 font-semibold mb-1')
                        size_slider = ui.slider(min=0.1, max=0.5, step=0.05, value=state.character_size_ratio).props('color=violet aria-label="캐릭터 크기"')
                        size_label = ui.label(f'{int(state.character_size_ratio * 100)}%').classes('text-xs text-slate-400 self-end -mt-2 mb-3')
                        size_slider.bind_value(state, 'character_size_ratio')
                        size_slider.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)
                        size_slider.on('change', lambda e: size_label.set_text(f'{int(e.value * 100)}%'))

                ui.separator().classes('bg-slate-800 my-2')

                # Audio & Subtitle Parameters
                ui.label('음성·음악').classes('text-xs font-bold text-slate-400 uppercase tracking-widest mt-2 mb-3')

                ui.label('내레이션 음성').classes('text-[10px] text-slate-400 font-semibold mb-1')
                voice_select = ui.select(
                    options={'alloy': 'Alloy · 기본 음성', 'echo': 'Echo · 낮은 음색', 'fable': 'Fable · 이야기 음색', 'onyx': 'Onyx', 'nova': 'Nova · 부드러운 음색', 'shimmer': 'Shimmer'},
                    value=state.tts_voice
                ).props('outlined dense dark aria-label="TTS 음성"').classes('w-full mb-3')
                voice_select.bind_value(state, 'tts_voice')
                voice_select.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)

                ui.label('배경음악 분위기').classes('text-[10px] text-slate-400 font-semibold mb-1')
                bgm_manager = BGMManager()
                mood_options = {'auto': '대본 분위기에 맞춰 선택'}
                mood_options.update({mood: label for mood, label in {
                    'calm': 'Calm & Soft', 'sci-fi': 'Sci-Fi', 'futuristic': 'Curious Tech',
                    'mysterious': 'Mysterious', 'energetic': 'Energetic Pop',
                    'dark': 'Dark Mystery', 'synthwave': 'Retro Synthwave',
                }.items() if bgm_manager.get_bgm_path(mood)})
                if state.bgm_mood not in mood_options:
                    mood_options[state.bgm_mood] = f'사용 가능한 곡 없음 · {state.bgm_mood}'
                bgm_select = ui.select(
                    options=mood_options,
                    value=state.bgm_mood
                ).props('outlined dense dark aria-label="BGM 분위기"').classes('w-full mb-3')
                bgm_select.bind_value(state, 'bgm_mood')
                bgm_select.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)
                ui.label('조건에 맞는 사용 허가 음악이 없으면 음성 생성 전에 멈춥니다.') \
                    .classes('text-[10px] text-slate-400 mb-2')

                ui.label('사용할 음악').classes('text-[10px] text-slate-400 font-semibold mb-1')
                track_options = {'': '분위기에 맞춰 선택'}
                track_options.update(bgm_manager.list_documented_tracks())
                if state.bgm_track and state.bgm_track not in track_options:
                    track_options[state.bgm_track] = f'사용할 수 없는 곡 · {state.bgm_track}'
                bgm_track_select = ui.select(
                    options=track_options,
                    value=state.bgm_track,
                ).props('outlined dense dark aria-label="BGM 트랙"').classes('w-full mb-1')
                bgm_track_select.bind_value(state, 'bgm_track')
                bgm_track_select.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)
                ui.label('직접 고른 곡을 우선 사용합니다. 저장하면 대본을 다시 열 때 복원됩니다.') \
                    .classes('text-[10px] text-slate-400 mb-3')

                ui.label('배경음악 음량').classes('text-[10px] text-slate-400 font-semibold mb-1')
                bgm_slider = ui.slider(min=0, max=1, step=0.05, value=state.bgm_volume).props('color=violet aria-label="BGM 음량"')
                bgm_label = ui.label(f'{int(state.bgm_volume * 100)}%').classes('text-xs text-slate-400 self-end -mt-2 mb-3')
                bgm_slider.bind_value(state, 'bgm_volume')
                bgm_slider.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)
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

                with ui.expansion('고급 · API 연결', icon='settings').classes('w-full'):
                    # API Keys Config (Inline for fast edit)
                    ui.label('현재 실행 중인 Studio에만 적용됩니다. 재시작 후에도 유지할 설정은 비공개 환경 파일에서 관리합니다.').classes('text-xs text-slate-400')

                    openai_input = ui.input('OpenAI Key', value=state.openai_key, password=True, password_toggle_button=True).props('outlined dense dark').classes('w-full mb-2')
                    openai_input.bind_value(state, 'openai_key')
                    openai_input.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)

                    gcp_input = ui.input('GCP Project ID', value=state.gcp_project).props('outlined dense dark').classes('w-full mb-3')
                    gcp_input.bind_value(state, 'gcp_project')
                    gcp_input.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)

                    def save_sidebar_settings():
                        if state.is_busy:
                            ui.notify('진행 중인 작업이 끝난 뒤 연결 설정을 적용하세요.', type='warning')
                            return
                        try:
                            settings.update_api_keys(openai_key=state.openai_key, gcp_project=state.gcp_project)
                            state.production_service = None
                            ui.notify('현재 Studio에 연결 설정을 적용했습니다.', type='positive')
                        except (OSError, ValueError) as error:
                            ui.notify(f'연결 설정 적용 실패: {error}', type='negative')

                    ui.button('연결 설정 적용', on_click=save_sidebar_settings).props('color=violet size=sm icon=save unelevated').classes('w-full py-1 text-xs')

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
                                ui.label('제작 작업실').classes('text-sm font-bold text-white mr-4')

                                # 하위 탭 토글
                                with ui.button_group().props('rounded dense size=xs'):
                                    editor_btn = ui.button('1. 대본·장면 검토').props(
                                        f'{"color=deep-purple-6" if state.workspace_sub_tab == "editor" else "outline color=grey-5"} '
                                        f'aria-pressed={str(state.workspace_sub_tab == "editor").lower()}'
                                    ).classes('min-h-[44px]')
                                    preview_btn = ui.button('2. 장면·영상 제작').props(
                                        f'{"color=deep-purple-6" if state.workspace_sub_tab == "preview" else "outline color=grey-5"} '
                                        f'aria-pressed={str(state.workspace_sub_tab == "preview").lower()}'
                                    ).classes('min-h-[44px]')

                                    def set_sub_tab(tab_name):
                                        state.workspace_sub_tab = tab_name
                                        render_active_view()

                                    editor_btn.on('click', lambda: set_sub_tab('editor'))
                                    preview_btn.on('click', lambda: set_sub_tab('preview'))

                            ui.label('대본 → 장면 → 완성본').classes('rounded bg-violet-950 text-violet-200 text-[10px] px-2 py-0.5')

                        # 하위 탭 분기 렌더링
                        with ui.element('div').classes('w-full flex-grow overflow-auto p-3 lg:p-6'):
                            if state.workspace_sub_tab == 'editor':
                                render_planning_tab(state, on_reviewed=lambda: set_sub_tab('preview'))
                            else:
                                render_generation_tab(state)

                    elif state.current_view == 'pipeline':
                        with ui.element('div').classes('w-full bg-slate-900 border-b border-slate-800 px-6 py-3 flex items-center gap-2 shrink-0'):
                            ui.icon('terminal', size='xs').classes('text-teal-400')
                            ui.label('기획·진행 현황').classes('text-sm font-bold text-white')
                        with ui.element('div').classes('w-full flex-grow overflow-auto p-3 lg:p-6'):
                            render_pipeline_tab(state)

                    elif state.current_view == 'sources':
                        with ui.element('div').classes('w-full bg-slate-900 border-b border-slate-800 px-6 py-3 flex items-center gap-2 shrink-0'):
                            ui.icon('rss_feed', size='xs').classes('text-orange-400')
                            ui.label('소재·출처 관리').classes('text-sm font-bold text-white')
                        with ui.element('div').classes('w-full flex-grow overflow-auto p-3 lg:p-6'):
                            render_sources_tab(state)

                    elif state.current_view == 'scheduling':
                        with ui.element('div').classes('w-full bg-slate-900 border-b border-slate-800 px-6 py-3 flex items-center gap-2 shrink-0'):
                            ui.icon('schedule', size='xs').classes('text-amber-400')
                            ui.label('예약 운영').classes('text-sm font-bold text-white')
                        with ui.element('div').classes('w-full flex-grow overflow-auto p-3 lg:p-6'):
                            render_scheduling_tab(state)

                    elif state.current_view == 'publishing':
                        with ui.element('div').classes('w-full bg-slate-900 border-b border-slate-800 px-6 py-3 flex items-center gap-2 shrink-0'):
                            ui.icon('cloud_upload', size='xs').classes('text-rose-400')
                            ui.label('완성본·비공개 업로드').classes('text-sm font-bold text-white')
                        with ui.element('div').classes('w-full flex-grow overflow-auto p-3 lg:p-6'):
                            render_publishing_tab(state)

                    elif state.current_view == 'assets':
                        with ui.element('div').classes('w-full flex-grow overflow-auto p-3 lg:p-6'):
                            render_asset_library_tab(state)

                    elif state.current_view == 'help':
                        with ui.column().classes('w-full overflow-auto p-5 gap-4'):
                            ui.label('ShortsMaker 사용 안내').classes('text-xl font-bold text-white')
                            ui.markdown("""
### 먼저 완성본부터 확인하세요
**완성본·업로드 → 저장된 완성본 → 완성본 불러오기**에서 기존 영상을 재생할 수 있습니다. 이미 업로드한 영상은 기존 YouTube 링크로 확인하며 중복 업로드하지 않습니다.

### 새 영상은 이 순서로 진행합니다
1. **제작 작업실 → 대본·장면 검토**에서 기사 URL/RSS 분야를 정하거나 저장된 대본을 불러옵니다.
2. 출처·내레이션·장면 설명을 읽고 **각본 확인 완료 · 영상 제작으로 →**를 누릅니다.
3. **장면·영상 제작**에서 첫 프레임과 무음 원본을 장면별로 검토합니다. 기존 영상을 쓸 때는 **보유 영상 직접 연결**을 선택합니다.
4. 완성 영상을 끝까지 본 뒤 **완성본·업로드**에서 제목·설명·AI 생성 여부를 확인하고 **YouTube에 비공개 업로드**를 사용합니다. 공개 전환은 YouTube에서 직접 결정합니다.

### 예약 운영과 비용
**예약 운영**에서 제작 주기·현재 대기 사유·검토할 영상을 확인합니다. 현재 운영 목표는 14일 주기이며, 예약 시각은 제작 시작 시각입니다. 검토나 예산 문제로 멈춘 회차가 자동으로 다음 회차로 넘어가지는 않습니다.

로컬 Studio에서는 대본 생성·재생성, 장면 생성, 음성·영상 편집을 직접 실행할 수 있습니다. 버튼을 누르면 API 비용이 발생할 수 있으며, 월 예산·비주얼 비용 상한과 장면 검토 조건은 계속 적용됩니다. 보유 영상을 연결해도 새 음성은 별도 API 비용이 들 수 있습니다. 비공개 업로드 후 공개 전환은 YouTube에서 직접 결정하세요.

명시적으로 `PAID_PRODUCTION_ENABLED=false`를 설정한 경우에만 **검토 모드 · API 생성 중지**로 실행됩니다. 에이전트 예약 제작은 직접 사용과 별도로 기존 회차 한도를 적용합니다.

화면의 임시 입력은 서버 재시작 시 사라질 수 있습니다. 대본 JSON은 **현재 작업에 적용 → 현재 대본 새 파일로 저장** 순서로 수정본을 보관하세요. 보유 영상 연결 화면의 **선택한 작업 이어가기**로 같은 대본의 클립 작업을 복원할 수 있습니다. 음성·음악은 **각본별 음성·음악 설정 저장**으로 보존하세요.

JSON 편집 입력은 같은 서버 세션에서 대본별로 유지되어 메뉴 이동 후에도 복원됩니다. **미적용 수정 되돌리기**로 현재 적용된 대본을 다시 볼 수 있습니다. 이는 디스크 자동 저장이 아니며, 미적용 내용이 있으면 먼저 적용하거나 되돌린 뒤 각본 확인을 진행하세요.

### 재료와 저장 공간
**재료 보관함**에서 폴더·종류·파일명으로 찾고, 미디어 하나를 선택해 재생할 수 있습니다. **정리 후보만 보기 → 파일 선택 → 선택 파일 정리 검토**에서 삭제 목록과 크기를 확인합니다. 영구 삭제는 복구할 수 없습니다. 원본·음악·비용·승인 기록, 업로드된 영상, 검토 문서가 참조하는 파일은 보존합니다. 정리 후보가 없으면 보호 사유를 확인하세요.
""").classes('text-slate-200 leading-relaxed max-w-3xl')

            # 최초 기본 뷰 설정 및 구동
            select_view(state.current_view)
