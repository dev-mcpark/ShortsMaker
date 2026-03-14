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


def render_manual_panel(state: 'AppState', exporter: VeoPromptExporter,
                        start_edit_btn: ui.button,
                        scene_cards_container: ui.column) -> None:
    """씬별 VEO 프롬프트 + 파일 업로드 패널 렌더링 (Right Panel 영역)"""

    if not state.script:
        try:
            scene_cards_container.clear()
        except RuntimeError:
            return
        with scene_cards_container:
            with ui.card().classes('w-full p-8 bg-slate-800/50 border border-dashed border-slate-600'):
                with ui.column().classes('items-center gap-4'):
                    ui.icon('description', size='xl').classes('text-slate-500')
                    ui.label('스크립트를 먼저 로드해주세요').classes('text-lg text-slate-400')
                    ui.label('Planning 탭에서 스크립트를 생성하거나 로드한 후 수동 모드를 사용하세요.').classes('text-sm text-slate-500 text-center')
        return

    # 스크립트 변경 시 script_id 초기화
    if not state.manual_script_id:
        state.manual_script_id = exporter.get_script_id(state.script)

    scenes_status = exporter.get_scenes_status(state.script, state.manual_script_id)
    ready_count = sum(1 for s in scenes_status if s["exists"])
    total = len(scenes_status)

    try:
        scene_cards_container.clear()
    except RuntimeError:
        return

    with scene_cards_container:
        # 헤더: 진행 현황
        with ui.card().classes('w-full p-3 bg-slate-800 border border-slate-600 mb-2'):
            with ui.row().classes('w-full items-center justify-between'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('video_library', size='sm').classes('text-purple-400')
                    ui.label('VEO 프롬프트 & 영상 업로드').classes('text-sm font-bold text-purple-300')
                ui.badge(f'{ready_count}/{total} 완료').classes(
                    'bg-green-700 text-white' if ready_count == total else 'bg-slate-600 text-gray-300'
                )

            # JSON 전체 복사 버튼
            def copy_all_json():
                json_str = exporter.export_json(state.script, state.manual_script_id)
                ui.run_javascript(
                    f'navigator.clipboard.writeText({repr(json_str)})'
                )
                safe_notify('전체 프롬프트 JSON이 클립보드에 복사되었습니다.', type='positive')

            ui.button(
                '전체 JSON 복사', icon='content_copy', on_click=copy_all_json
            ).classes('mt-2 w-full').props('flat dense color=purple-3 size=sm')

        # 씬별 카드
        for scene_info in scenes_status:
            scene_num = scene_info["scene_number"]
            exists = scene_info["exists"]
            prompt = scene_info["prompt"]

            with ui.card().classes(
                'w-full p-3 border ' +
                ('bg-slate-800/80 border-green-700' if exists else 'bg-slate-900/60 border-slate-600')
            ):
                # 씬 헤더
                with ui.row().classes('w-full items-center justify-between mb-2'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon(
                            'check_circle' if exists else 'hourglass_empty',
                            size='xs'
                        ).classes('text-green-400' if exists else 'text-gray-500')
                        ui.label(f'씬 {scene_num}').classes('text-sm font-bold text-white')

                    status_label = ui.badge(
                        '✅ 업로드 완료' if exists else '⏳ 대기 중'
                    ).classes(
                        'bg-green-700 text-white text-xs' if exists
                        else 'bg-slate-700 text-gray-400 text-xs'
                    )

                # 스크립트 텍스트 (참고용)
                ui.label(scene_info["script_text"]).classes(
                    'text-xs text-gray-400 mb-2 italic'
                )

                # 프롬프트 텍스트 + 복사 버튼
                with ui.card().classes('w-full p-2 bg-black/40 border border-slate-700'):
                    ui.label(prompt).classes('text-xs text-gray-300 leading-relaxed')

                    def make_copy_fn(p=prompt):
                        def copy_prompt():
                            ui.run_javascript(f'navigator.clipboard.writeText({repr(p)})')
                            safe_notify(f'씬 {scene_num} 프롬프트가 복사되었습니다.', type='info')
                        return copy_prompt

                    ui.button(
                        '복사', icon='content_copy', on_click=make_copy_fn()
                    ).classes('mt-1 self-end').props('flat dense color=grey-5 size=xs')

                # 업로드 버튼
                clip_path_display = ui.label(
                    scene_info["clip_path"].split('/')[-1] if exists else ''
                ).classes('text-xs text-green-400 mt-1')

                def make_upload_handler(sn=scene_num, disp=clip_path_display,
                                        stat=status_label):
                    def handle_upload(e):
                        try:
                            saved_path = exporter.save_uploaded_clip(
                                e.content.read(), state.manual_script_id, sn
                            )
                            state.manual_clip_paths[sn] = str(saved_path)
                            disp.text = saved_path.name
                            stat.text = '✅ 업로드 완료'
                            stat.classes(replace='bg-green-700 text-white text-xs')
                            safe_notify(f'씬 {sn} 영상 업로드 완료!', type='positive')
                            # 전체 완료 여부 확인 후 버튼 활성화
                            if len(state.manual_clip_paths) == len(state.script.scenes):
                                start_edit_btn.enable()
                        except Exception as err:
                            safe_notify(f'씬 {sn} 업로드 실패: {err}', type='negative')
                            logger.error(f'씬 {sn} 업로드 오류: {err}')
                    return handle_upload

                ui.upload(
                    on_upload=make_upload_handler(),
                    auto_upload=True,
                    max_file_size=500_000_000,
                ).props('accept=".mp4,.mov,.webm" flat dense color=purple').classes('mt-2 w-full')


def render_generation_tab(state: 'AppState') -> None:
    """Video Generation 탭 렌더링"""

    exporter = VeoPromptExporter()
    phase_labels = {}
    phases = ['ready', 'visuals', 'editing', 'complete']

    def update_progress_ui(phase: str, progress: float, message: str = ""):
        """진행 상태 UI 업데이트"""
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

    with ui.row().classes('w-full h-full gap-6'):
        # === Left Panel: Controls ===
        with ui.column().classes('w-96 min-w-[380px] gap-4'):

            # === Production Control Card ===
            with card_with_header('Production Control', 'movie_creation', 'primary'):
                with ui.element('div').classes('p-5'):
                    # Script Info Card
                    with ui.card().classes('w-full p-4 bg-slate-900/50 border border-slate-600 mb-4'):
                        with ui.row().classes('items-center gap-3'):
                            ui.icon('description', size='sm').classes('text-pink-400')
                            with ui.column().classes('flex-grow gap-1'):
                                ui.label('Selected Script').classes('text-xs text-gray-500 uppercase tracking-wider')
                                ui.label().bind_text_from(
                                    state, 'script',
                                    backward=lambda s: s.title if s else "No script loaded"
                                ).classes('text-sm text-white font-medium truncate')

                            def get_mode_badge():
                                return 'VIDEO' if state.mode == 'video' else 'IMAGE'
                            ui.badge(get_mode_badge()).classes('bg-purple-600 text-white px-2')

                    # ── 생성 방식 선택 ──
                    with ui.card().classes('w-full p-3 bg-slate-900/60 border border-slate-600 mb-4'):
                        ui.label('영상 생성 방식').classes('text-xs text-gray-400 uppercase tracking-wider mb-2')
                        mode_toggle = ui.toggle(
                            {False: '🤖 자동 (VEO API)', True: '✋ 수동 (직접 업로드)'},
                            value=state.manual_video_mode,
                        ).props('color=purple').classes('w-full')

                        def on_mode_change(e):
                            state.manual_video_mode = e.value
                            state.reset_manual_mode()
                            refresh_right_panel()

                        mode_toggle.on_value_change(on_mode_change)

                    # Pipeline Status
                    ui.label('Pipeline Status').classes('text-xs text-gray-400 uppercase tracking-wider mb-3')

                    with ui.element('div').classes('w-full mb-4'):
                        with ui.row().classes('w-full justify-between items-center mb-2'):
                            step_configs = [
                                ('ready', 'hourglass_empty', 'Ready'),
                                ('visuals', 'auto_awesome', 'Visuals'),
                                ('editing', 'movie_edit', 'Editing'),
                                ('complete', 'check_circle', 'Complete')
                            ]

                            for i, (phase_id, icon, label_text) in enumerate(step_configs):
                                with ui.column().classes('items-center gap-1'):
                                    icon_class = 'text-gray-500' if i > 0 else 'text-teal-400'
                                    with ui.element('div').classes('w-10 h-10 rounded-full bg-slate-700 flex items-center justify-center border-2 border-slate-600'):
                                        ui.icon(icon, size='xs').classes(icon_class)
                                    phase_labels[phase_id] = ui.label(label_text).classes('text-xs text-gray-500')

                                if i < len(step_configs) - 1:
                                    ui.element('div').classes('flex-grow h-0.5 bg-slate-600 mx-1 mt-5')

                    # Scene Progress Container
                    scene_progress_container = ui.column().classes('w-full gap-2 mb-4')
                    scene_progress_container.visible = False

                    gen_spinner = ui.spinner(size='lg').props('color=teal').classes('self-center my-4')
                    gen_spinner.visible = False

                    # Video Player Reference
                    video_player = None
                    placeholder_content = None

                    async def _run_production_core(manual_clip_paths=None):
                        """공통 프로덕션 실행 로직 (자동/수동 모드 공유)"""
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
                                        # 수동 모드: 오른쪽 패널 복원
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
                            safe_notify("스크립트를 먼저 로드해주세요.", type='warning')
                            return
                        await _run_production_core(manual_clip_paths=None)

                    async def run_production_with_clips(clips: dict):
                        if not state.script:
                            safe_notify("스크립트를 먼저 로드해주세요.", type='warning')
                            return
                        # 수동 모드에서 편집 시작 시 오른쪽 패널 전환
                        try:
                            if right_manual_panel:
                                right_manual_panel.visible = False
                            if right_preview_panel:
                                right_preview_panel.visible = True
                        except RuntimeError:
                            pass
                        await _run_production_core(manual_clip_paths=clips)

                    # 자동 모드 버튼
                    auto_btn = ui.button(
                        'Start Production',
                        on_click=run_production
                    ).classes('w-full').props('color=teal unelevated size=lg icon=rocket_launch')

                    # 수동 모드 버튼 (초기 비활성)
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

                    # 초기 표시 상태
                    auto_btn.visible = not state.manual_video_mode
                    manual_btn.visible = state.manual_video_mode

            # === Quick Settings ===
            with ui.card().classes('w-full p-4 bg-slate-700 border border-slate-600'):
                with ui.row().classes('items-center gap-2 mb-3'):
                    ui.icon('tune', size='sm').classes('text-amber-400')
                    ui.label('Quick Settings').classes('text-sm font-bold text-amber-300')

                with ui.row().classes('w-full gap-4'):
                    with ui.column().classes('flex-grow gap-1'):
                        ui.label('Voice').classes('text-xs text-gray-400')
                        voice_options = {
                            'alloy': 'Alloy',
                            'nova': 'Nova ♀',
                            'onyx': 'Onyx ♂',
                            'shimmer': 'Shimmer ♀',
                            'echo': 'Echo ♂',
                        }
                        voice_select = ui.select(options=voice_options, value=state.tts_voice).props('outlined dense dark').classes('w-full')
                        voice_select.bind_value(state, 'tts_voice')

                    with ui.column().classes('flex-grow gap-1'):
                        ui.label('BGM').classes('text-xs text-gray-400')
                        bgm_options = ['cinematic', 'upbeat', 'calm', 'mysterious', 'energetic', 'suspense']
                        bgm_select = ui.select(options=bgm_options, value=state.bgm_mood).props('outlined dense dark').classes('w-full')
                        bgm_select.bind_value(state, 'bgm_mood')

                with ui.row().classes('w-full items-center gap-2 mt-3'):
                    ui.icon('volume_up', size='xs').classes('text-gray-400')
                    bgm_volume_slider = ui.slider(min=0, max=50, value=int(state.bgm_volume * 100)).props('color=amber').classes('flex-grow')
                    volume_label = ui.label(f'{int(state.bgm_volume * 100)}%').classes('text-xs text-gray-400 w-10')

                    def update_bgm_volume():
                        state.bgm_volume = bgm_volume_slider.value / 100.0
                        volume_label.text = f'{bgm_volume_slider.value}%'
                    bgm_volume_slider.on('update:model-value', update_bgm_volume)

            # === Advanced Options ===
            with ui.expansion('Advanced Options', icon='settings').classes('w-full bg-slate-700 border border-slate-600').props('header-class="text-gray-300 text-sm"'):
                # Subtitle Settings
                with ui.card().classes('w-full p-3 bg-slate-800/50 mb-3'):
                    ui.label('Subtitles').classes('text-xs text-gray-400 uppercase tracking-wider mb-2')

                    with ui.row().classes('w-full gap-3'):
                        with ui.column().classes('gap-1'):
                            ui.label('Color').classes('text-xs text-gray-500')
                            subtitle_color_input = ui.color_input(value=state.subtitle_color).classes('w-20')
                            subtitle_color_input.bind_value(state, 'subtitle_color')

                        with ui.column().classes('flex-grow gap-1'):
                            ui.label('Size').classes('text-xs text-gray-500')
                            subtitle_size_slider = ui.slider(min=40, max=80, value=state.subtitle_size).props('label-always color=amber dense').classes('w-full')
                            subtitle_size_slider.bind_value(state, 'subtitle_size')

                    with ui.column().classes('w-full gap-1 mt-2'):
                        ui.label('Y Position').classes('text-xs text-gray-500')
                        subtitle_y_slider = ui.slider(min=1000, max=1600, value=state.subtitle_y_position).props('label-always color=amber dense').classes('w-full')
                        subtitle_y_slider.bind_value(state, 'subtitle_y_position')

                # Character Overlay Settings
                with ui.card().classes('w-full p-3 bg-slate-800/50'):
                    with ui.row().classes('w-full items-center justify-between mb-2'):
                        ui.label('Character Overlay').classes('text-xs text-gray-400 uppercase tracking-wider')
                        char_enabled_switch = ui.switch(value=state.character_overlay_enabled).props('color=teal dense')
                        char_enabled_switch.bind_value(state, 'character_overlay_enabled')

                    with ui.column().classes('w-full gap-2'):
                        ui.label('Video Path').classes('text-xs text-gray-500')
                        char_video_input = ui.input(
                            value=state.character_video_path,
                            placeholder='Path to character video file'
                        ).props('outlined dense dark').classes('w-full')
                        char_video_input.bind_value(state, 'character_video_path')

                        with ui.row().classes('w-full gap-3'):
                            with ui.column().classes('flex-grow gap-1'):
                                ui.label('Position').classes('text-xs text-gray-500')
                                position_options = {
                                    'bottom_right': 'Bottom Right',
                                    'bottom_left': 'Bottom Left',
                                    'top_right': 'Top Right',
                                    'top_left': 'Top Left',
                                }
                                char_position_select = ui.select(
                                    options=position_options,
                                    value=state.character_position
                                ).props('outlined dense dark').classes('w-full')
                                char_position_select.bind_value(state, 'character_position')

                            with ui.column().classes('w-24 gap-1'):
                                ui.label('Size').classes('text-xs text-gray-500')
                                char_size_slider = ui.slider(
                                    min=10, max=40,
                                    value=int(state.character_size_ratio * 100)
                                ).props('color=teal dense').classes('w-full')

                                def update_char_size():
                                    state.character_size_ratio = char_size_slider.value / 100.0
                                char_size_slider.on('update:model-value', update_char_size)

                        with ui.row().classes('w-full items-center gap-3 mt-2'):
                            ui.label('Chroma Key').classes('text-xs text-gray-500')
                            chroma_enabled_switch = ui.switch(value=state.chroma_key_enabled).props('color=green dense')
                            chroma_enabled_switch.bind_value(state, 'chroma_key_enabled')

                            chroma_color_select = ui.select(
                                options={'green': 'Green', 'blue': 'Blue'},
                                value=state.chroma_key_color
                            ).props('outlined dense dark').classes('w-24')
                            chroma_color_select.bind_value(state, 'chroma_key_color')

        # === Right Panel: Preview Monitor / Manual Panel ===
        right_preview_panel = None
        right_manual_panel = None

        with ui.column().classes('flex-grow h-full gap-0'):

            # ── 프리뷰 패널 (자동 모드 / 편집 완료 후) ──
            with ui.card().classes('w-full h-full p-0 bg-black rounded-xl border-4 border-slate-800 shadow-2xl overflow-hidden') as right_preview_panel:
                with ui.element('div').classes('w-full h-8 bg-gradient-to-b from-slate-700 to-slate-800 flex items-center px-3 gap-2'):
                    ui.element('div').classes('w-3 h-3 rounded-full bg-red-500')
                    ui.element('div').classes('w-3 h-3 rounded-full bg-yellow-500')
                    ui.element('div').classes('w-3 h-3 rounded-full bg-green-500')
                    ui.label('Preview Monitor').classes('text-xs text-gray-500 ml-4 font-mono')

                with ui.element('div').classes('w-full flex-grow flex items-center justify-center bg-gradient-to-b from-slate-900 to-black relative'):
                    with ui.column().classes('items-center gap-4') as placeholder_content:
                        ui.icon('smart_display', size='xl').classes('text-slate-700')
                        ui.label('No Preview Available').classes('text-lg text-slate-600 font-medium')
                        ui.label('Start production to generate video').classes('text-sm text-slate-700')

                        with ui.card().classes('p-4 bg-slate-800/50 border border-slate-700 mt-4'):
                            ui.label('Quick Guide').classes('text-xs text-gray-500 uppercase tracking-wider mb-2')
                            steps = [
                                ('1', 'Load a script from Planning tab'),
                                ('2', 'Adjust settings if needed'),
                                ('3', 'Click "Start Production"'),
                            ]
                            for num, text in steps:
                                with ui.row().classes('items-center gap-2'):
                                    ui.badge(num).classes('bg-teal-600 text-white')
                                    ui.label(text).classes('text-xs text-gray-400')

                    video_player = ui.video('').classes('max-h-full max-w-full')
                    video_player.visible = False

            # ── 수동 모드 패널 ──
            with ui.scroll_area().classes('w-full h-full') as right_manual_panel:
                scene_cards_container = ui.column().classes('w-full gap-3 p-2')

            # 초기 패널 표시 상태
            right_preview_panel.visible = not state.manual_video_mode
            right_manual_panel.visible = state.manual_video_mode

            def refresh_right_panel():
                """모드 전환 시 Right Panel 업데이트"""
                try:
                    right_preview_panel.visible = not state.manual_video_mode
                    right_manual_panel.visible = state.manual_video_mode
                    auto_btn.visible = not state.manual_video_mode
                    manual_btn.visible = state.manual_video_mode
                    if state.manual_video_mode and state.script:
                        render_manual_panel(state, exporter, manual_btn, scene_cards_container)
                except RuntimeError:
                    pass

            # 초기 수동 패널 렌더링 (수동 모드 기본값이면)
            if state.manual_video_mode and state.script:
                render_manual_panel(state, exporter, manual_btn, scene_cards_container)
