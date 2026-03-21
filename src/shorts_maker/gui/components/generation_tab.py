"""Video Generation 탭 컴포넌트"""
import asyncio

from nicegui import ui
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.gui.components.common.card_header import card_with_header
from shorts_maker.services.production_service import ProductionService, ProductionPhase, ProductionProgress
from shorts_maker.gui.components.common.progress_utils import update_scene_grid
from shorts_maker.utils.character_overlay import CharacterOverlayConfig
from shorts_maker.utils.veo_prompt_exporter import VeoPromptExporter
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)

SCENE_ACCENT = [
    ('from-pink-500', 'to-rose-500', 'border-pink-500/40', 'bg-pink-900/20', 'text-pink-300'),
    ('from-purple-500', 'to-violet-500', 'border-purple-500/40', 'bg-purple-900/20', 'text-purple-300'),
    ('from-indigo-500', 'to-blue-500', 'border-indigo-500/40', 'bg-indigo-900/20', 'text-indigo-300'),
    ('from-teal-500', 'to-cyan-500', 'border-teal-500/40', 'bg-teal-900/20', 'text-teal-300'),
    ('from-amber-500', 'to-orange-500', 'border-amber-500/40', 'bg-amber-900/20', 'text-amber-300'),
]


def render_manual_panel(state: 'AppState', exporter: VeoPromptExporter,
                        start_edit_btn: ui.button,
                        scene_cards_container: ui.element) -> None:
    """수동 모드 전체 패널 렌더링"""

    try:
        scene_cards_container.clear()
    except RuntimeError:
        return

    # 스크립트 없을 때
    if not state.script:
        with scene_cards_container:
            with ui.element('div').classes('w-full h-full flex items-center justify-center py-20'):
                with ui.column().classes('items-center gap-4'):
                    ui.icon('description', size='xl').classes('text-slate-600')
                    ui.label('각본을 먼저 로드해주세요').classes('text-xl font-bold text-slate-500')
                    ui.label('Planning 탭에서 각본을 생성한 뒤 돌아오세요').classes('text-sm text-slate-600')
        return

    if not state.manual_script_id:
        state.manual_script_id = exporter.get_script_id(state.script)

    scenes_status = exporter.get_scenes_status(state.script, state.manual_script_id)
    ready_count = sum(1 for s in scenes_status if s["exists"])
    total = len(scenes_status)

    with scene_cards_container:
        # ── 상단 진행 헤더 ───────────────────────────────────
        with ui.element('div').classes('w-full rounded-xl bg-slate-800 border border-slate-700 p-4 mb-4'):
            with ui.row().classes('w-full items-center justify-between mb-3'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('video_library', size='sm').classes('text-purple-400')
                    ui.label('VEO 수동 생성 모드').classes('text-base font-bold text-purple-300')

                progress_badge_cls = 'bg-green-600 text-white font-bold px-3 py-1 rounded-full text-sm' \
                    if ready_count == total else 'bg-slate-700 text-gray-300 font-bold px-3 py-1 rounded-full text-sm'
                ui.badge(f'{ready_count} / {total} 씬 완료').classes(progress_badge_cls)

            # 전체 진행 바
            with ui.element('div').classes('w-full h-2 rounded-full bg-slate-700 overflow-hidden mb-3'):
                pct = int(ready_count / max(total, 1) * 100)
                bar_color = 'bg-green-500' if ready_count == total else 'bg-purple-500'
                ui.element('div').classes(f'h-full rounded-full {bar_color} transition-all').style(f'width: {pct}%')

            # 안내 메시지
            if ready_count == total and total > 0:
                with ui.element('div').classes('w-full rounded-lg bg-green-900/30 border border-green-500/40 p-3'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('check_circle', size='sm').classes('text-green-400')
                        ui.label('모든 씬 업로드 완료! 아래 [편집 시작] 버튼을 눌러주세요.').classes('text-sm text-green-300 font-medium')
            else:
                with ui.element('div').classes('w-full rounded-lg bg-blue-900/20 border border-blue-500/30 p-3'):
                    with ui.row().classes('items-start gap-2'):
                        ui.icon('info', size='xs').classes('text-blue-400 mt-0.5 shrink-0')
                        ui.label('각 씬의 프롬프트를 복사해 VEO 등 외부 AI 서비스에서 영상을 생성한 뒤, 해당 씬에 업로드하세요.').classes('text-xs text-blue-300 leading-relaxed')

            # 전체 JSON 복사 버튼
            def copy_all_json():
                json_str = exporter.export_json(state.script, state.manual_script_id)
                ui.run_javascript(f'navigator.clipboard.writeText({repr(json_str)})')
                safe_notify('전체 프롬프트 JSON이 클립보드에 복사되었습니다.', type='positive')

            ui.button(
                '전체 프롬프트 JSON 복사',
                icon='content_copy',
                on_click=copy_all_json
            ).classes('w-full mt-2').props('flat dense color=purple size=sm')

        # ── 씬별 카드 ────────────────────────────────────────
        for idx, scene_info in enumerate(scenes_status):
            scene_num = scene_info["scene_number"]
            exists = scene_info["exists"]
            prompt = scene_info["prompt"]
            script_text = scene_info["script_text"]

            from_c, to_c, border_c, bg_c, label_c = SCENE_ACCENT[idx % len(SCENE_ACCENT)]
            card_border = 'border-green-500/60' if exists else border_c
            card_bg = 'bg-slate-800/80' if exists else 'bg-slate-900/50'

            with ui.element('div').classes(f'w-full rounded-xl border {card_border} {card_bg} overflow-hidden mb-4'):

                # 씬 헤더 바
                with ui.element('div').classes(f'w-full px-4 py-3 bg-gradient-to-r {from_c} {to_c} opacity-90'):
                    with ui.row().classes('w-full items-center justify-between'):
                        with ui.row().classes('items-center gap-3'):
                            with ui.element('div').classes('w-7 h-7 rounded-lg bg-white/20 flex items-center justify-center'):
                                ui.label(str(scene_num)).classes('text-sm font-bold text-white')
                            ui.label(f'씬 {scene_num}').classes('text-sm font-bold text-white')

                        if exists:
                            with ui.row().classes('items-center gap-1 bg-green-500/30 rounded-full px-3 py-1'):
                                ui.icon('check_circle', size='xs').classes('text-green-300')
                                ui.label('업로드 완료').classes('text-xs text-green-200 font-medium')
                        else:
                            with ui.element('div').classes('bg-white/20 rounded-full px-3 py-1'):
                                ui.label('대기 중').classes('text-xs text-white/80')

                with ui.element('div').classes('p-4 flex flex-col gap-3'):

                    # STEP 1: 나레이션 확인
                    with ui.element('div').classes('w-full'):
                        with ui.row().classes('items-center gap-2 mb-2'):
                            with ui.element('div').classes('w-5 h-5 rounded-full bg-amber-500/30 border border-amber-500/50 flex items-center justify-center shrink-0'):
                                ui.label('1').classes('text-xs font-bold text-amber-400')
                            ui.label('나레이션 (참고용)').classes('text-xs font-bold text-amber-400 uppercase tracking-wider')

                        with ui.element('div').classes('w-full rounded-lg bg-amber-900/20 border border-amber-500/20 px-3 py-2'):
                            ui.label(script_text).classes('text-sm text-gray-200 leading-relaxed italic')

                    # STEP 2: VEO 프롬프트 복사
                    with ui.element('div').classes('w-full'):
                        with ui.row().classes('items-center gap-2 mb-2'):
                            with ui.element('div').classes('w-5 h-5 rounded-full bg-purple-500/30 border border-purple-500/50 flex items-center justify-center shrink-0'):
                                ui.label('2').classes('text-xs font-bold text-purple-400')
                            ui.label('VEO 프롬프트 복사').classes('text-xs font-bold text-purple-400 uppercase tracking-wider')

                        with ui.element('div').classes('w-full rounded-lg bg-slate-950/60 border border-slate-600 p-3'):
                            ui.label(prompt).classes('text-sm text-gray-200 leading-relaxed font-mono')

                        def make_copy_fn(p=prompt, sn=scene_num):
                            def copy_prompt():
                                ui.run_javascript(f'navigator.clipboard.writeText({repr(p)})')
                                safe_notify(f'씬 {sn} 프롬프트 복사됨', type='info')
                            return copy_prompt

                        ui.button(
                            '이 씬 프롬프트 복사',
                            icon='content_copy',
                            on_click=make_copy_fn()
                        ).classes('w-full mt-2').props('color=purple unelevated size=sm icon=content_copy')

                    # STEP 3: 영상 업로드
                    with ui.element('div').classes('w-full'):
                        with ui.row().classes('items-center gap-2 mb-2'):
                            with ui.element('div').classes(
                                'w-5 h-5 rounded-full flex items-center justify-center shrink-0 ' +
                                ('bg-green-500/30 border border-green-500/50' if exists else 'bg-teal-500/30 border border-teal-500/50')
                            ):
                                ui.label('3').classes('text-xs font-bold ' + ('text-green-400' if exists else 'text-teal-400'))
                            ui.label('영상 업로드').classes('text-xs font-bold ' + ('text-green-400' if exists else 'text-teal-400') + ' uppercase tracking-wider')

                        # 업로드 완료 표시
                        clip_path_display = ui.element('div').classes(
                            'w-full rounded-lg border px-3 py-2 mb-2 flex items-center gap-2 ' +
                            ('bg-green-900/30 border-green-500/40' if exists else 'hidden')
                        )
                        with clip_path_display:
                            ui.icon('video_file', size='xs').classes('text-green-400 shrink-0')
                            clip_name = scene_info["clip_path"].split('/')[-1] if exists else ''
                            clip_name_label = ui.label(clip_name).classes('text-xs text-green-300 truncate')

                        # 업로드 영역
                        upload_area = ui.element('div').classes(
                            'w-full rounded-lg border-2 border-dashed p-4 text-center ' +
                            ('border-green-500/40 bg-green-900/10' if exists else 'border-slate-600 bg-slate-800/30 hover:border-teal-500/50')
                        )
                        with upload_area:
                            if exists:
                                with ui.column().classes('items-center gap-1'):
                                    ui.icon('check_circle', size='sm').classes('text-green-400')
                                    ui.label('업로드 완료 (재업로드 가능)').classes('text-xs text-green-400')
                            else:
                                with ui.column().classes('items-center gap-1'):
                                    ui.icon('cloud_upload', size='md').classes('text-slate-500')
                                    ui.label('영상 파일을 업로드하세요').classes('text-sm text-slate-400')
                                    ui.label('.mp4  .mov  .webm  (최대 500MB)').classes('text-xs text-slate-600')

                        status_label = ui.element('div')  # 상태용 더미 (upload handler에서 참조)

                        def make_upload_handler(sn=scene_num,
                                                c_display=clip_path_display,
                                                u_area=upload_area):
                            async def handle_upload(e):
                                try:
                                    # NiceGUI 3.5+: e.file.read() (async)
                                    file_bytes = await e.file.read()
                                    saved_path = exporter.save_uploaded_clip(
                                        file_bytes, state.manual_script_id, sn
                                    )
                                    state.manual_clip_paths[sn] = str(saved_path)

                                    safe_notify(f'씬 {sn} 업로드 완료!', type='positive')

                                    if len(state.manual_clip_paths) == len(state.script.scenes):
                                        start_edit_btn.enable()
                                        safe_notify('🎉 모든 씬 업로드 완료! 편집을 시작할 수 있습니다.', type='positive')

                                    # 패널 새로고침 (업로드 상태 반영)
                                    render_manual_panel(state, exporter, start_edit_btn,
                                                        scene_cards_container)
                                except Exception as err:
                                    safe_notify(f'씬 {sn} 업로드 실패: {err}', type='negative')
                                    logger.error(f'씬 {sn} 업로드 오류: {err}')
                            return handle_upload

                        ui.upload(
                            on_upload=make_upload_handler(),
                            auto_upload=True,
                            max_file_size=500_000_000,
                        ).props('accept=".mp4,.mov,.webm" flat color=teal').classes('w-full')

        # ── 편집 시작 버튼 (하단 고정) ───────────────────────
        with ui.element('div').classes('w-full pt-2 pb-2'):
            ui.separator().classes('bg-slate-700 mb-4')
            if ready_count == total and total > 0:
                btn_props = 'color=green unelevated size=lg icon=movie_edit'
                btn_text = f'✅ {total}개 씬 모두 준비됨 — 편집 시작'
            else:
                btn_props = 'color=purple unelevated size=lg icon=movie_edit'
                btn_text = f'편집 시작 ({ready_count}/{total} 씬 준비됨)'

            def _start_edit_click():
                pass  # start_edit_btn 클릭은 외부에서 처리

            bottom_start_btn = ui.button(btn_text).classes('w-full').props(btn_props)
            bottom_start_btn.on('click', lambda: start_edit_btn.run_method('click'))
            if ready_count < total:
                bottom_start_btn.disable()

        # scene_cards_container를 outer scope에서 접근하기 위해 저장
        scene_cards_container._manual_panel_rendered = True


def render_generation_tab(state: 'AppState') -> None:
    """Video Generation 탭 렌더링"""

    exporter = VeoPromptExporter()
    phase_labels = {}
    phases = ['ready', 'visuals', 'editing', 'complete']

    def update_progress_ui(phase: str, progress: float, message: str = ""):
        try:
            for p, label in phase_labels.items():
                if p == phase:
                    label.classes(replace='text-teal-400 font-bold')
                elif phases.index(p) < phases.index(phase):
                    label.classes(replace='text-green-400')
                else:
                    label.classes(replace='text-gray-500')
        except (ValueError, RuntimeError) as e:
            logger.debug(f"Phase label update skipped: {e}")

    with ui.column().classes('w-full h-full gap-0'):

        # ── 모드 선택 상단 바 ────────────────────────────────
        with ui.element('div').classes('w-full px-6 py-3 bg-slate-800/80 border-b border-slate-700 flex items-center gap-6 shrink-0'):
            # 각본 상태
            with ui.row().classes('items-center gap-2'):
                script_dot = 'bg-green-400' if state.script else 'bg-gray-600'
                ui.element('div').classes(f'w-2 h-2 rounded-full {script_dot}')
                ui.label().bind_text_from(
                    state, 'script',
                    backward=lambda s: s.title[:30] + ('...' if len(s.title) > 30 else '') if s else '각본 없음'
                ).classes('text-sm text-gray-300')

            ui.element('div').classes('flex-grow')

            # 모드 토글 (상단 중앙)
            with ui.element('div').classes('flex items-center gap-3'):
                ui.label('생성 방식:').classes('text-xs text-gray-500 uppercase tracking-wider')
                mode_toggle = ui.toggle(
                    {False: '🤖 자동 (VEO API)', True: '✋ 수동 (직접 업로드)'},
                    value=state.manual_video_mode,
                ).props('color=purple dense')

        # ── 메인 콘텐츠 ─────────────────────────────────────
        with ui.row().classes('w-full flex-grow gap-0 overflow-hidden'):

            # === Left Panel: 설정 ===
            with ui.column().classes('w-80 min-w-[320px] bg-slate-800/40 border-r border-slate-700 p-4 gap-4 overflow-y-auto'):

                # Pipeline Status
                with ui.element('div').classes('w-full rounded-xl bg-slate-900/60 border border-slate-600 p-4'):
                    ui.label('파이프라인 상태').classes('text-xs text-gray-500 uppercase tracking-wider mb-3')

                    with ui.row().classes('w-full items-center'):
                        step_configs = [
                            ('ready', 'hourglass_empty', 'Ready'),
                            ('visuals', 'auto_awesome', 'Visuals'),
                            ('editing', 'movie_edit', 'Editing'),
                            ('complete', 'check_circle', 'Done')
                        ]
                        for i, (phase_id, icon, label_text) in enumerate(step_configs):
                            with ui.column().classes('items-center gap-1'):
                                icon_class = 'text-teal-400' if i == 0 else 'text-gray-500'
                                with ui.element('div').classes('w-9 h-9 rounded-full bg-slate-700 flex items-center justify-center border border-slate-600'):
                                    ui.icon(icon, size='xs').classes(icon_class)
                                phase_labels[phase_id] = ui.label(label_text).classes('text-xs text-gray-500')
                            if i < len(step_configs) - 1:
                                ui.element('div').classes('flex-grow h-px bg-slate-600 mb-4')

                    scene_progress_container = ui.column().classes('w-full gap-2 mt-3')
                    scene_progress_container.visible = False

                    gen_spinner = ui.spinner(size='md').props('color=teal').classes('self-center my-3')
                    gen_spinner.visible = False

                # 자동 모드 실행 버튼
                auto_btn = ui.button(
                    'Start Production',
                    on_click=lambda: asyncio.ensure_future(run_production())
                ).classes('w-full').props('color=teal unelevated size=lg icon=rocket_launch')
                auto_btn.visible = not state.manual_video_mode

                # 수동 모드 편집 시작 버튼 (Left Panel용 - hidden, right panel의 bottom btn이 trigger)
                async def run_manual_production():
                    if not state.script or not state.manual_clip_paths:
                        safe_notify('먼저 모든 씬의 영상을 업로드해주세요.', type='warning')
                        return
                    await run_production_with_clips(state.manual_clip_paths)

                manual_btn = ui.button(
                    '편집 시작',
                    on_click=run_manual_production
                ).classes('w-full').props('color=purple unelevated size=lg icon=movie_edit')
                manual_btn.disable()
                manual_btn.visible = state.manual_video_mode

                # Quick Settings
                with ui.element('div').classes('w-full rounded-xl bg-slate-900/60 border border-slate-600 p-4'):
                    with ui.row().classes('items-center gap-2 mb-3'):
                        ui.icon('tune', size='xs').classes('text-amber-400')
                        ui.label('빠른 설정').classes('text-xs font-bold text-amber-300 uppercase tracking-wider')

                    with ui.row().classes('w-full gap-3'):
                        with ui.column().classes('flex-grow gap-1'):
                            ui.label('목소리').classes('text-xs text-gray-500')
                            voice_select = ui.select(
                                options={'alloy': 'Alloy', 'nova': 'Nova ♀', 'onyx': 'Onyx ♂', 'shimmer': 'Shimmer ♀', 'echo': 'Echo ♂'},
                                value=state.tts_voice
                            ).props('outlined dense dark').classes('w-full')
                            voice_select.bind_value(state, 'tts_voice')

                        with ui.column().classes('flex-grow gap-1'):
                            ui.label('BGM').classes('text-xs text-gray-500')
                            bgm_select = ui.select(
                                options=['cinematic', 'upbeat', 'calm', 'mysterious', 'energetic', 'suspense'],
                                value=state.bgm_mood
                            ).props('outlined dense dark').classes('w-full')
                            bgm_select.bind_value(state, 'bgm_mood')

                    with ui.row().classes('w-full items-center gap-2 mt-3'):
                        ui.icon('volume_up', size='xs').classes('text-gray-500')
                        bgm_volume_slider = ui.slider(min=0, max=50, value=int(state.bgm_volume * 100)).props('color=amber').classes('flex-grow')
                        volume_label = ui.label(f'{int(state.bgm_volume * 100)}%').classes('text-xs text-gray-400 w-10')

                        def update_bgm_volume():
                            state.bgm_volume = bgm_volume_slider.value / 100.0
                            volume_label.text = f'{bgm_volume_slider.value}%'
                        bgm_volume_slider.on('update:model-value', update_bgm_volume)

                # Advanced Options
                with ui.expansion('고급 옵션', icon='settings').classes('w-full').props('header-class="text-xs text-gray-500 px-0"'):
                    with ui.element('div').classes('flex flex-col gap-3 pt-2'):
                        # 자막 설정
                        with ui.element('div').classes('w-full rounded-lg bg-slate-900/40 border border-slate-700 p-3'):
                            ui.label('자막').classes('text-xs text-gray-500 uppercase tracking-wider mb-2')
                            with ui.row().classes('w-full gap-3'):
                                with ui.column().classes('gap-1'):
                                    ui.label('색상').classes('text-xs text-gray-600')
                                    subtitle_color_input = ui.color_input(value=state.subtitle_color).classes('w-20')
                                    subtitle_color_input.bind_value(state, 'subtitle_color')
                                with ui.column().classes('flex-grow gap-1'):
                                    ui.label('크기').classes('text-xs text-gray-600')
                                    subtitle_size_slider = ui.slider(min=40, max=80, value=state.subtitle_size).props('label-always color=amber dense').classes('w-full')
                                    subtitle_size_slider.bind_value(state, 'subtitle_size')
                            with ui.column().classes('w-full gap-1 mt-2'):
                                ui.label('Y 위치').classes('text-xs text-gray-600')
                                subtitle_y_slider = ui.slider(min=1000, max=1600, value=state.subtitle_y_position).props('label-always color=amber dense').classes('w-full')
                                subtitle_y_slider.bind_value(state, 'subtitle_y_position')

                        # 캐릭터 오버레이
                        with ui.element('div').classes('w-full rounded-lg bg-slate-900/40 border border-slate-700 p-3'):
                            with ui.row().classes('w-full items-center justify-between mb-2'):
                                ui.label('캐릭터 오버레이').classes('text-xs text-gray-500 uppercase tracking-wider')
                                char_enabled_switch = ui.switch(value=state.character_overlay_enabled).props('color=teal dense')
                                char_enabled_switch.bind_value(state, 'character_overlay_enabled')

                            char_video_input = ui.input(
                                value=state.character_video_path,
                                placeholder='캐릭터 영상 파일 경로'
                            ).props('outlined dense dark').classes('w-full mb-2')
                            char_video_input.bind_value(state, 'character_video_path')

                            with ui.row().classes('w-full gap-3'):
                                char_position_select = ui.select(
                                    options={'bottom_right': '우하단', 'bottom_left': '좌하단', 'top_right': '우상단', 'top_left': '좌상단'},
                                    value=state.character_position
                                ).props('outlined dense dark').classes('flex-grow')
                                char_position_select.bind_value(state, 'character_position')

                                char_size_slider = ui.slider(min=10, max=40, value=int(state.character_size_ratio * 100)).props('color=teal dense').classes('w-20')
                                def update_char_size():
                                    state.character_size_ratio = char_size_slider.value / 100.0
                                char_size_slider.on('update:model-value', update_char_size)

                            with ui.row().classes('w-full items-center gap-2 mt-2'):
                                ui.label('크로마키').classes('text-xs text-gray-600')
                                chroma_enabled_switch = ui.switch(value=state.chroma_key_enabled).props('color=green dense')
                                chroma_enabled_switch.bind_value(state, 'chroma_key_enabled')
                                chroma_color_select = ui.select(
                                    options={'green': '초록', 'blue': '파랑'},
                                    value=state.chroma_key_color
                                ).props('outlined dense dark').classes('w-20')
                                chroma_color_select.bind_value(state, 'chroma_key_color')

            # === Right Panel ===
            right_preview_panel = None
            right_manual_panel = None

            with ui.column().classes('flex-grow h-full overflow-hidden'):

                # ── 자동 모드: 프리뷰 모니터 ──
                with ui.card().classes('w-full h-full p-0 bg-black rounded-none border-0 shadow-none overflow-hidden') as right_preview_panel:
                    with ui.element('div').classes('w-full h-7 bg-slate-800 flex items-center px-3 gap-2 border-b border-slate-700'):
                        ui.element('div').classes('w-2.5 h-2.5 rounded-full bg-red-500')
                        ui.element('div').classes('w-2.5 h-2.5 rounded-full bg-yellow-500')
                        ui.element('div').classes('w-2.5 h-2.5 rounded-full bg-green-500')
                        ui.label('Preview Monitor').classes('text-xs text-gray-500 ml-3 font-mono')

                    with ui.element('div').classes('w-full flex-grow flex items-center justify-center bg-gradient-to-b from-slate-900 to-black'):
                        video_player = None
                        placeholder_content = None

                        with ui.column().classes('items-center gap-4') as placeholder_content:
                            ui.icon('smart_display', size='xl').classes('text-slate-700')
                            ui.label('영상 미리보기').classes('text-lg text-slate-600 font-medium')
                            ui.label('Production을 시작하면 여기에 결과가 표시됩니다').classes('text-sm text-slate-700 text-center')
                            with ui.element('div').classes('mt-4 rounded-xl bg-slate-800/50 border border-slate-700 p-4 max-w-xs'):
                                ui.label('사용 방법').classes('text-xs text-gray-500 uppercase tracking-wider mb-2')
                                for num, text in [('1', '왼쪽에서 각본 확인'), ('2', '설정 조정'), ('3', 'Start Production 클릭')]:
                                    with ui.row().classes('items-center gap-2 mb-1'):
                                        ui.badge(num).classes('bg-teal-600 text-white text-xs')
                                        ui.label(text).classes('text-xs text-gray-400')

                        video_player = ui.video('').classes('max-h-full max-w-full')
                        video_player.visible = False

                # ── 수동 모드: 씬별 업로드 패널 ──
                with ui.scroll_area().classes('w-full h-full') as right_manual_panel:
                    scene_cards_container = ui.column().classes('w-full gap-0 p-4')

                # 초기 표시
                right_preview_panel.visible = not state.manual_video_mode
                right_manual_panel.visible = state.manual_video_mode

                # ── 이벤트 핸들러 ──────────────────────────────

                async def _run_production_core(manual_clip_paths=None):
                    nonlocal video_player, placeholder_content
                    production_running = True

                    try:
                        gen_spinner.visible = True
                        scene_progress_container.visible = True
                        scene_progress_container.clear()
                    except RuntimeError:
                        return

                    try:
                        char_config = None
                        if state.character_overlay_enabled:
                            char_config = CharacterOverlayConfig()
                            char_config.enabled = True
                            char_config.character_image = state.character_image_path
                            char_config.character_video = state.character_video_path if state.character_video_path else None
                            char_config.position = state.character_position
                            char_config.size_ratio = state.character_size_ratio
                            try:
                                hex_color = state.character_border_color.lstrip('#')
                                char_config.border_color = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
                            except (ValueError, IndexError):
                                char_config.border_color = (255, 255, 255)
                            char_config.chroma_key_enabled = state.chroma_key_enabled
                            char_config.chroma_key_color = state.chroma_key_color
                            char_config.chroma_key_threshold = state.chroma_key_threshold

                        service = ProductionService(
                            mode=state.mode,
                            character_overlay_config=char_config
                        )

                        def on_progress(progress: ProductionProgress):
                            state.pipeline_phase = progress.phase
                            state.pipeline_progress = progress.progress_percent
                            state.pipeline_message = progress.message
                            state.scene_progresses = progress.scene_progresses
                            state.total_scenes = progress.total_scenes
                            state.completed_scenes = progress.completed_scenes
                            state.elapsed_seconds = progress.elapsed_seconds
                            state.estimated_seconds = progress.remaining_seconds

                        service.set_progress_callback(on_progress)

                        async def monitor_progress():
                            while production_running:
                                progress = service.progress
                                try:
                                    update_scene_grid(progress.scene_progresses, scene_progress_container)
                                except RuntimeError:
                                    pass
                                try:
                                    phase_map = {
                                        ProductionPhase.GENERATING: 'visuals',
                                        ProductionPhase.EDITING: 'editing',
                                        ProductionPhase.COMPLETED: 'complete'
                                    }
                                    if progress.phase in phase_map:
                                        update_progress_ui(phase_map[progress.phase], progress.progress_percent)
                                except (RuntimeError, KeyError):
                                    pass
                                if progress.phase in [ProductionPhase.COMPLETED, ProductionPhase.FAILED]:
                                    break
                                await asyncio.sleep(0.3)

                        monitor_task = asyncio.create_task(monitor_progress())

                        logger.info("=== Starting Production ===")
                        result = await service.produce_video(
                            state.script,
                            manual_clip_paths=manual_clip_paths
                        )

                        production_running = False
                        await monitor_task

                        if result.success:
                            state.final_video_path = result.video_path
                            state.generated_clips = result.clips
                            update_progress_ui('complete', 100)
                            safe_notify("🎬 편집 완료!", type='positive')
                            if video_player and state.final_video_path:
                                try:
                                    video_player.set_source(state.final_video_path)
                                    video_player.visible = True
                                    if placeholder_content:
                                        placeholder_content.visible = False
                                    if right_manual_panel:
                                        right_manual_panel.visible = False
                                    if right_preview_panel:
                                        right_preview_panel.visible = True
                                except RuntimeError:
                                    pass
                            logger.info(f"Video saved to: {state.final_video_path}")
                        else:
                            safe_notify(f"Production failed: {result.error}", type='negative')
                            logger.error(f"Production failed: {result.error}")

                    except Exception as e:
                        safe_notify(f"Production failed: {e}", type='negative')
                        logger.error(f"Production Error: {e}")
                    finally:
                        production_running = False
                        try:
                            gen_spinner.visible = False
                        except RuntimeError:
                            pass

                async def run_production():
                    if not state.script:
                        safe_notify("각본을 먼저 로드해주세요.", type='warning')
                        return
                    await _run_production_core(manual_clip_paths=None)

                async def run_production_with_clips(clips: dict):
                    if not state.script:
                        safe_notify("각본을 먼저 로드해주세요.", type='warning')
                        return
                    try:
                        if right_manual_panel:
                            right_manual_panel.visible = False
                        if right_preview_panel:
                            right_preview_panel.visible = True
                    except RuntimeError:
                        pass
                    await _run_production_core(manual_clip_paths=clips)

                def refresh_right_panel():
                    try:
                        right_preview_panel.visible = not state.manual_video_mode
                        right_manual_panel.visible = state.manual_video_mode
                        auto_btn.visible = not state.manual_video_mode
                        manual_btn.visible = state.manual_video_mode
                        if state.manual_video_mode:
                            render_manual_panel(state, exporter, manual_btn, scene_cards_container)
                    except RuntimeError:
                        pass

                def on_mode_change(e):
                    state.manual_video_mode = e.value
                    state.reset_manual_mode()
                    refresh_right_panel()

                mode_toggle.on_value_change(on_mode_change)

                # 초기 수동 패널 렌더링
                if state.manual_video_mode:
                    render_manual_panel(state, exporter, manual_btn, scene_cards_container)
