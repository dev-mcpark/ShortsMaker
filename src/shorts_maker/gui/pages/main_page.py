"""제작 순서와 검토 경로를 보여주는 Studio 메인 화면."""

from nicegui import ui
from shorts_maker.gui.components.episode_workspace import render_episode_workspace

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
from shorts_maker.gui.components.budget_panel import render_budget_panel
from shorts_maker.gui.components.music_preview import render_music_preview
from shorts_maker.gui.components.audio_recovery import render_audio_recovery
from shorts_maker.gui.runtime_info import runtime_label, render_runtime_info


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
                    ui.label(runtime_label()).classes('text-[10px] text-slate-500 break-all')
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
                    ui.label('로컬 Studio').classes('text-[10px] text-slate-600 mt-1')

            # --- 2B. CENTER WORKSPACE (중앙 동적 워크스페이스) ---
            center_container = ui.element('div').classes(WORKSPACE_CENTER)

            # --- 2C. RIGHT CONFIG PANEL (우측 설정 패널 - Google AI Studio 스타일) ---
            with ui.element('div').classes(CONFIG_PANEL_RIGHT):
                ui.label('제작 설정').classes('text-xs font-bold text-slate-400 uppercase tracking-widest mb-4')
                ui.label('음성·음악·화면 변경은 새 편집에 적용됩니다. 완성본 미리보기는 재편집해야 바뀝니다.').classes(
                    'text-xs text-slate-400 leading-relaxed mb-3')
                render_budget_panel()

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
                ui.label().bind_text_from(state, 'video_model_label').classes('text-[11px] text-slate-400 break-all mb-3')

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

                render_music_preview(state)

                ui.label('배경음악 음량').classes('text-[10px] text-slate-400 font-semibold mb-1')
                bgm_slider = ui.slider(min=0, max=1, step=0.05, value=state.bgm_volume).props('color=violet aria-label="BGM 음량"')
                bgm_label = ui.label(f'{int(state.bgm_volume * 100)}%').classes('text-xs text-slate-400 self-end -mt-2 mb-3')
                bgm_slider.bind_value(state, 'bgm_volume')
                bgm_slider.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)
                bgm_label.bind_text_from(state, 'bgm_volume', backward=lambda value: f'{int(value * 100)}%')
                def save_audio_choices():
                    try:
                        state.save_audio_choices()
                        ui.notify('현재 각본의 음성·음악 설정과 내레이션 선택을 저장했습니다.', type='positive')
                    except (OSError, ValueError) as error:
                        ui.notify(f'설정 저장 실패: {error}', type='negative')

                ui.button('각본별 음성·음악 설정 저장', on_click=save_audio_choices).props(
                    'flat dense icon=save').classes('w-full').bind_enabled_from(
                        state, 'is_busy', lambda busy: not busy and state.script is not None)

                ui.separator().classes('bg-slate-800 my-2')

                render_audio_recovery(state, lambda: render_active_view())

                with ui.expansion('고급 · API 연결', icon='settings').classes('w-full'):
                    # API Keys Config (Inline for fast edit)
                    ui.label('연결 설정은 현재 Studio의 모든 창이 공유합니다. 다른 창이 작업 중이면 연결 변경을 기다려 주세요. 재시작 후 유지할 설정은 비공개 환경 파일에서 관리합니다.').classes('text-xs text-slate-400')

                    openai_input = ui.input('OpenAI Key', value=state.openai_key, password=True, password_toggle_button=True).props('outlined dense dark').classes('w-full mb-2')
                    openai_input.bind_value(state, 'openai_key')
                    openai_input.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)

                    gcp_input = ui.input('GCP Project ID', value=state.gcp_project).props('outlined dense dark').classes('w-full mb-3')
                    gcp_input.bind_value(state, 'gcp_project')
                    gcp_input.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)

                    def save_sidebar_settings():
                        if openai_input.is_deleted or gcp_input.is_deleted:
                            return
                        if state.is_busy:
                            ui.notify('진행 중인 작업이 끝난 뒤 연결 설정을 적용하세요.', type='warning')
                            return
                        try:
                            state.apply_api_settings()
                            ui.notify('현재 Studio에 연결 설정을 적용했습니다.', type='positive')
                        except (OSError, ValueError) as error:
                            ui.notify(f'연결 설정 적용 실패: {error}', type='negative')

                    ui.button('연결 설정 적용', on_click=save_sidebar_settings).props('color=violet size=sm icon=save unelevated').classes('w-full min-h-[44px] py-1 text-xs')

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
                    render_episode_workspace(state, render_active_view)
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
                            render_runtime_info()
                            ui.markdown("""
### 먼저 완성본부터 확인하세요
**완성본·업로드 → 저장된 완성본 → 완성본 불러오기**에서 기존 영상을 재생할 수 있습니다. 이미 업로드한 영상은 기존 YouTube 링크로 확인하며 중복 업로드하지 않습니다.

### 새 영상은 이 순서로 진행합니다
1. **제작 작업실 → 대본·장면 검토**에서 기사 URL/RSS 분야를 정하거나 저장된 대본을 불러옵니다.
2. 출처·내레이션·장면 설명을 읽고 **각본 확인 완료 · 영상 제작으로 →**를 누릅니다.
3. **장면·영상 제작**에서 **첫 프레임 후보 생성 → 미리보기·승인 → 무음 원본 생성·승인** 순서로 진행합니다. 기존 영상을 쓸 때는 **보유 영상 직접 연결**을 선택합니다.
4. 완성 영상을 끝까지 본 뒤 **완성본·업로드**에서 제목·설명·AI 생성 여부를 확인하고 **YouTube에 비공개 업로드**를 사용합니다. 공개 전환은 YouTube에서 직접 결정합니다.

**무료 RSS 기사 먼저 보기 → 현재 분야 RSS 조회 · 모델 비용 없음**에서 유료 기획 전에 최근 기사 제목·요약·출처를 확인할 수 있습니다. **이 기사를 URL 입력으로 선택**은 입력만 바꾸며, 원문 확인 후 **각본 생성하기**를 따로 눌러야 유료 기획이 시작됩니다. 기존 대본·검토·완성본은 유지합니다. 일부 피드가 누락될 수 있고 자동 기획의 후보 표본과는 다를 수 있습니다.

소스 방식·기사 URL·분야와 무료 조회 결과는 메뉴 이동 시 유지됩니다. 아직 서버 재시작용 작업 초안에 포함되지 않으므로 재시작 전 필요한 기사 URL을 따로 보관하세요.

### YouTube 연결만 확인하거나 복구하기
**완성본·업로드 → YouTube 업로드 연결 → 저장된 인증 확인**은 로그인 창을 열지 않고 저장된 인증을 확인·갱신합니다. 연결이 필요하면 **업로드 계정 연결**을 누르고 Studio가 실행 중인 Mac의 브라우저에서 기존 채널 계정과 업로드 권한을 확인하세요. 창이 보이지 않으면 **로그인 창 직접 열기**를 사용하세요.

**인증 대기 취소**로 대기를 끝낼 수 있으며 최대 대기는 5분입니다. 메뉴를 이동해도 진행 상태를 다시 확인할 수 있습니다. 연결은 영상을 업로드하거나 대기 중인 제작을 재개하지 않습니다. OAuth 클라이언트 파일이 없다면 기존 데스크톱 클라이언트의 `client_secrets.json` 설정을 복원하세요. 기본 위치는 `config/credentials/`이며 기존 루트 파일도 탐색합니다. 설치 세부 사항은 저장소 README의 YouTube 설정 안내를 확인하세요.

### 예약 운영과 비용
**예약 운영**에서 제작 주기·현재 대기 사유·검토할 영상을 확인합니다. 현재 운영 목표는 14일 주기이며, 예약 시각은 제작 시작 시각입니다. 검토나 예산 문제로 멈춘 회차가 자동으로 다음 회차로 넘어가지는 않습니다.

에이전트 회차의 **검토할 각본 불러오기**로 작업실을 연결하면 상단에 **예약 회차 제작**이 표시됩니다. 기존 첫 프레임·원본·편집·업로드 버튼은 월·회차 잔여 중 작은 한도로 실행하며, **회차 잔여 확인**으로 조회할 수 있습니다. 서버에 저장된 API 설정과 Lite 무음720p를 사용합니다. 다른 작업은 **회차 연결 해제** 후 수동 전환을 확인하세요. 연결 해제는 기존 회차·입력·재료를 삭제하거나 일정을 재개하지 않습니다. 재시작 후에는 같은 회차의 대본을 다시 불러와 검토하세요. 불확실한 실행은 자동 재시도하지 않습니다.

예약 대본을 작업실에서 다듬었다면 수정 내용을 적용·확인한 뒤 **확인한 수정 대본을 회차에 저장 → 이 수정 대본으로 회차 저장**을 사용하세요. 같은 출처의 검토한 수정본을 별도 사본으로 남기며, 이전 대본·비용·판정은 보존합니다. 이미 영상이 연결됐거나 실행 결과가 미확인이면 저장을 중단합니다. 저장은 API 호출·일정 재개·영상 채택이 아닙니다.

이전 대본은 **실행 이력 → 회차 대본 검색 → 선택 회차 대본 이력 보기**에서 버전을 골라 확인하세요. **선택 대본을 작업실에서 검토**는 현재/대상 대본의 변경 입력을 작업 초안으로 보관한 뒤 검토용 사본을 엽니다. 현재 적용 대본도 보관하며, 저장에 실패하면 열지 않습니다. 사본 열기는 영상 선택과 대본 확인을 초기화하고 대상 대본에 명시 저장된 음성 설정을 복원합니다. 저장하지 않은 음성 선택은 이어지지 않으며 회차 상태·비용·기존 판정은 유지합니다. 보관된 입력은 **저장된 작업 초안**에서 다시 열 수 있습니다.

로컬 Studio에서는 대본 생성·재생성, 장면 생성, 음성·영상 편집을 직접 실행할 수 있습니다. 버튼을 누르면 API 비용이 발생할 수 있으며, 월 예산·비주얼 비용 상한과 장면 검토 조건은 계속 적용됩니다. 보유 영상을 연결해도 새 음성은 별도 API 비용이 들 수 있습니다. 비공개 업로드 후 공개 전환은 YouTube에서 직접 결정하세요.

명시적으로 `PAID_PRODUCTION_ENABLED=false`를 설정한 경우에만 **검토 모드 · API 생성 중지**로 실행됩니다. 에이전트 예약 제작은 직접 사용과 별도로 기존 회차 한도를 적용합니다.

**내레이션 · 기존 음성 재사용 → 이 음성 세트 연결**에서 현재 문장·파일 기록이 일치하는 음성을 재생하고 다시 편집할 수 있습니다. 새로 만든 음성도 보관되며, 음색을 바꾸려면 **새 음성 생성으로 전환**을 누르세요. **각본별 음성·음악 설정 저장**을 누르면 같은 대본을 다시 열 때 음성 선택도 복원됩니다. 저장하지 않은 선택은 세션에만 남습니다. 기록·파일이 바뀌면 새 TTS로 자동 전환하지 않고 재사용을 중단하므로 복구하거나 검토 후 다시 연결하세요.

화면의 임시 입력은 서버 재시작 시 사라질 수 있습니다. 대본 JSON은 **현재 작업에 적용 → 현재 대본 새 파일로 저장** 순서로 수정본을 보관하세요. 보유 영상 연결 화면의 **선택한 작업 이어가기**로 같은 대본의 클립 작업을 복원할 수 있습니다. 음성·음악은 **각본별 음성·음악 설정 저장**으로 보존하세요.

JSON 편집 입력은 같은 서버 세션에서 대본별로 유지되어 메뉴 이동 후에도 복원됩니다. **미적용 수정 되돌리기**로 현재 적용된 대본을 다시 볼 수 있습니다. 이는 디스크 자동 저장이 아니며, 미적용 내용이 있으면 먼저 적용하거나 되돌린 뒤 각본 확인을 진행하세요.

### 재료와 저장 공간
**재료 보관함**에서 폴더·종류·파일명으로 찾고, 미디어 하나를 선택해 재생할 수 있습니다. **정리 후보만 보기 → 파일 선택 → 선택 파일 정리 검토**에서 삭제 목록과 크기를 확인합니다. 영구 삭제는 복구할 수 없습니다. 원본·음악·비용·승인 기록, 업로드된 영상, 검토 문서가 참조하는 파일은 보존합니다. 정리 후보가 없으면 보호 사유를 확인하세요.
""").classes('text-slate-200 leading-relaxed max-w-3xl')

            # 최초 기본 뷰 설정 및 구동
            select_view(state.current_view)
