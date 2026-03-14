"""Video Generation 탭 컴포넌트"""
import asyncio

from nicegui import ui
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.gui.components.common.card_header import card_with_header
from shorts_maker.services.production_service import ProductionService, ProductionPhase, ProductionProgress
from shorts_maker.gui.components.common.progress_utils import format_time, update_scene_grid
from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.utils.character_overlay import CharacterOverlayConfig
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)


def render_generation_tab(state: 'AppState') -> None:
    """Video Generation 탭 렌더링"""

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

                    async def run_production():
                        nonlocal video_player, placeholder_content

                        if not state.script:
                            safe_notify("Please load a script first!", type='warning')
                            return

                        production_running = True
                        
                        try:
                            gen_spinner.visible = True
                            scene_progress_container.visible = True
                            scene_progress_container.clear()
                        except RuntimeError:
                            return

                        try:
                            # Character Overlay Config 생성
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

                            # ProductionService 생성
                            service = ProductionService(
                                mode=state.mode,
                                character_overlay_config=char_config
                            )

                            # Progress callback 설정
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

                            # Monitor task for real-time UI updates
                            async def monitor_progress():
                                while production_running:
                                    progress = service.progress
                                    
                                    # Update scene grid
                                    try:
                                        update_scene_grid(progress.scene_progresses, scene_progress_container)
                                    except RuntimeError:
                                        pass
                                    
                                    # Update phase labels
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
                                    
                                    # Break on completion or failure
                                    if progress.phase in [ProductionPhase.COMPLETED, ProductionPhase.FAILED]:
                                        break
                                        
                                    await asyncio.sleep(0.3)

                            # Start monitor task
                            monitor_task = asyncio.create_task(monitor_progress())

                            # Run production
                            logger.info("=== Starting Production with ProductionService ===")
                            result = await service.produce_video(state.script)

                            # Stop monitoring
                            production_running = False
                            await monitor_task

                            if result.success:
                                state.final_video_path = result.video_path
                                state.generated_clips = result.clips
                                
                                update_progress_ui('complete', 100)
                                safe_notify("🎬 Production Complete!", type='positive')
                                
                                if video_player and state.final_video_path:
                                    try:
                                        video_player.set_source(state.final_video_path)
                                        video_player.visible = True
                                        if placeholder_content:
                                            placeholder_content.visible = False
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

                    ui.button(
                        'Start Production',
                        on_click=run_production
                    ).classes('w-full').props('color=teal unelevated size=lg icon=rocket_launch')

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

        # === Right Panel: Preview Monitor ===
        with ui.column().classes('flex-grow h-full'):
            with ui.card().classes('w-full h-full p-0 bg-black rounded-xl border-4 border-slate-800 shadow-2xl overflow-hidden'):
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
