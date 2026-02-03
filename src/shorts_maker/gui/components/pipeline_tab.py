"""Full Pipeline 실행 탭 컴포넌트"""

from nicegui import ui
import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Callable

from shorts_maker.gui.components.common.safe_ui import (
    safe_notify, safe_refresh, safe_update, safe_set_visibility
)
from shorts_maker.gui.components.common.card_header import card_with_header
from shorts_maker.gui.config.ui_theme import SCENE_GRADIENTS
from shorts_maker.services.production_service import ProductionService, ProductionPhase, ProductionProgress
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.character_overlay import CharacterOverlayConfig
from shorts_maker.gui.components.common.progress_utils import format_time, update_scene_grid

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)

# format_time과 update_scene_grid는 progress_utils에서 import


def render_pipeline_tab(
    state: 'AppState',
    step_indicators: List = None,
    update_step_indicators_fn: Callable = None
) -> None:
    """Full Pipeline 실행 탭 렌더링"""

    # Progress bar references
    progress_bars: Dict[str, ui.linear_progress] = {}
    phase_labels: Dict[str, ui.label] = {}
    phase_time_labels: Dict[str, ui.label] = {}

    # UI element references
    start_btn = None
    stop_btn = None
    error_panel = None
    error_message_label = None
    error_details_label = None
    video_preview = None
    preview_placeholder = None
    scene_grid = None
    elapsed_label = None
    scenes_label = None
    current_task_label = None
    history_count_badge = None

    # History
    if not hasattr(state, 'pipeline_history'):
        state.pipeline_history = []

    def show_error_panel(message: str):
        """에러 패널 표시"""
        try:
            error_panel.visible = True
            error_message_label.text = 'Pipeline Error'
            short_msg = message[:200] + '...' if len(message) > 200 else message
            error_details_label.text = short_msg
        except RuntimeError:
            pass

    def hide_error_panel():
        """에러 패널 숨기기"""
        try:
            error_panel.visible = False
        except RuntimeError:
            pass

    with ui.row().classes('w-full h-full gap-4'):
        # === Left Column: Controls ===
        with ui.column().classes('w-[320px] min-w-[300px] gap-4'):

            # === Pipeline Control Card ===
            with card_with_header('Pipeline Control', 'play_circle', 'primary'):
                with ui.element('div').classes('p-4'):
                    # Source Mode Selection
                    ui.label('Content Source').classes('text-xs text-gray-400 uppercase tracking-wider mb-2')

                    with ui.element('div').classes('w-full p-3 bg-slate-800/50 rounded-lg mb-3'):
                        source_mode = ui.radio(
                            ['Auto (RSS)', 'Direct URL'],
                            value='Auto (RSS)'
                        ).props('color=teal dense')

                    topic_input = ui.input(
                        'Topic Keyword',
                        placeholder='e.g., AI, Technology'
                    ).props('outlined dense dark').classes('w-full mb-2')
                    topic_input.bind_visibility_from(source_mode, 'value', value='Auto (RSS)')

                    url_input = ui.input(
                        'Article URL',
                        placeholder='https://...'
                    ).props('outlined dense dark').classes('w-full mb-2')
                    url_input.bind_visibility_from(source_mode, 'value', value='Direct URL')

                    ui.separator().classes('bg-slate-600 my-3')

                    # Options
                    ui.label('Options').classes('text-xs text-gray-400 uppercase tracking-wider mb-2')

                    with ui.row().classes('w-full gap-4 mb-3'):
                        with ui.column().classes('gap-2'):
                            auto_upload = ui.switch('YouTube Upload').props('color=red dense')
                        with ui.column().classes('gap-2'):
                            parallel_clips = ui.switch('Parallel Gen').props('color=teal dense')

                    with ui.row().classes('w-full gap-4 mb-3'):
                        with ui.column().classes('gap-2'):
                            character_overlay = ui.switch('Character Overlay').props('color=purple dense')
                            character_overlay.bind_value(state, 'character_overlay_enabled')

                    ui.separator().classes('bg-slate-600 my-3')

                    # Action Functions
                    async def run_full_pipeline():
                        nonlocal start_btn, stop_btn

                        if state.pipeline_running:
                            safe_notify('Pipeline is already running!', type='warning')
                            return

                        if source_mode.value == 'Direct URL' and not url_input.value:
                            safe_notify('Please enter a URL', type='negative')
                            return

                        # Initialize state
                        state.pipeline_running = True
                        state.pipeline_phase = ProductionPhase.IDLE
                        state.last_error = None

                        try:
                            start_btn.disable()
                            stop_btn.enable()
                        except RuntimeError:
                            pass

                        # Reset UI
                        for bar in progress_bars.values():
                            try:
                                bar.set_value(0)
                            except RuntimeError:
                                pass

                        for label in phase_labels.values():
                            try:
                                label.text = 'Pending'
                                label.classes(remove='text-teal-400 text-pink-400 text-red-400', add='text-gray-400')
                            except RuntimeError:
                                pass

                        for label in phase_time_labels.values():
                            try:
                                label.text = ''
                            except RuntimeError:
                                pass

                        try:
                            scene_grid.clear()
                            with scene_grid:
                                with ui.column().classes('w-full items-center justify-center py-6'):
                                    ui.icon('burst_mode', size='lg').classes('text-slate-700')
                                    ui.label('Scene thumbnails will appear here').classes('text-xs text-gray-600')
                        except RuntimeError:
                            pass

                        hide_error_panel()
                        safe_set_visibility(video_preview, False)
                        safe_set_visibility(preview_placeholder, True)

                        try:
                            # Update API keys
                            if state.openai_key or state.gcp_project:
                                settings.update_api_keys(
                                    openai_key=state.openai_key,
                                    gcp_project=state.gcp_project
                                )

                            # Create CharacterOverlayConfig if enabled
                            char_config = None
                            if state.character_overlay_enabled:
                                char_config = CharacterOverlayConfig()
                                char_config.enabled = True
                                char_config.character_image = state.character_image_path
                                char_config.character_video = state.character_video_path if state.character_video_path else None
                                char_config.position = state.character_position
                                char_config.size_ratio = state.character_size_ratio
                                char_config.border_color = tuple(int(state.character_border_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
                                char_config.chroma_key_enabled = state.chroma_key_enabled
                                char_config.chroma_key_color = state.chroma_key_color
                                char_config.chroma_key_threshold = state.chroma_key_threshold

                            # Create ProductionService
                            service = ProductionService(
                                mode=state.mode,
                                parallel_clips=parallel_clips.value,
                                character_overlay_config=char_config
                            )
                            state.production_service = service

                            # Progress callback
                            def on_progress(progress: ProductionProgress):
                                state.pipeline_phase = progress.phase
                                state.pipeline_progress = progress.progress_percent
                                state.pipeline_message = progress.message
                                state.scene_progresses = progress.scene_progresses
                                state.total_scenes = progress.total_scenes
                                state.completed_scenes = progress.completed_scenes
                                state.current_scene = progress.current_scene
                                state.elapsed_seconds = progress.elapsed_seconds
                                state.estimated_seconds = progress.remaining_seconds

                            service.set_progress_callback(on_progress)

                            # Progress monitoring task
                            async def monitor_progress():
                                while state.pipeline_running:
                                    progress = service.progress
                                    phase_key = progress.phase.value

                                    # Update progress bar
                                    if phase_key in progress_bars:
                                        try:
                                            progress_bars[phase_key].set_value(progress.progress_percent / 100)
                                        except RuntimeError:
                                            pass

                                    # Update phase label
                                    if phase_key in phase_labels:
                                        try:
                                            if 0 < progress.progress_percent < 100:
                                                phase_labels[phase_key].text = f'{progress.progress_percent:.0f}%'
                                                phase_labels[phase_key].classes(remove='text-gray-400 text-teal-400', add='text-pink-400')
                                            elif progress.progress_percent >= 100:
                                                phase_labels[phase_key].text = '✓ Done'
                                                phase_labels[phase_key].classes(remove='text-gray-400 text-pink-400', add='text-teal-400')
                                        except RuntimeError:
                                            pass

                                    # Update time label
                                    if phase_key in phase_time_labels:
                                        try:
                                            elapsed = format_time(progress.elapsed_seconds)
                                            if progress.remaining_seconds > 0:
                                                remaining = format_time(progress.remaining_seconds)
                                                phase_time_labels[phase_key].text = f'{elapsed} / ~{remaining} left'
                                            else:
                                                phase_time_labels[phase_key].text = elapsed
                                        except RuntimeError:
                                            pass

                                    # Update scene thumbnails
                                    update_scene_grid(progress.scene_progresses, scene_grid)

                                    # Update global status
                                    try:
                                        elapsed_label.text = f'⏱️ {format_time(progress.elapsed_seconds)}'
                                        if progress.total_scenes > 0:
                                            scenes_label.text = f'📹 {progress.completed_scenes}/{progress.total_scenes} scenes'
                                        current_task_label.text = progress.message
                                    except RuntimeError:
                                        pass

                                    # Update header step indicators
                                    if update_step_indicators_fn and step_indicators:
                                        update_step_indicators_fn(progress.phase, step_indicators)

                                    if progress.phase in [ProductionPhase.COMPLETED, ProductionPhase.FAILED]:
                                        break

                                    await asyncio.sleep(0.3)

                            monitor_task = asyncio.create_task(monitor_progress())

                            logger.info("=== Starting Full Pipeline ===")

                            result = await service.full_pipeline(
                                topic=topic_input.value if source_mode.value == 'Auto (RSS)' else None,
                                direct_url=url_input.value if source_mode.value == 'Direct URL' else None,
                                auto_upload=auto_upload.value
                            )

                            state.pipeline_running = False
                            await monitor_task

                            if result.success:
                                state.final_video_path = result.video_path
                                state.pipeline_phase = ProductionPhase.COMPLETED
                                state.pipeline_message = "Pipeline completed!"
                                safe_notify('🎉 Pipeline completed successfully!', type='positive')

                                if result.video_path:
                                    try:
                                        video_preview.set_source(result.video_path)
                                        video_preview.visible = True
                                        preview_placeholder.visible = False
                                    except (FileNotFoundError, ValueError, RuntimeError) as e:
                                        logger.warning(f"Failed to set video preview: {e}")

                                if result.youtube_id:
                                    safe_notify(f'📺 Uploaded to YouTube: {result.youtube_id}', type='positive')

                                for bar in progress_bars.values():
                                    try:
                                        bar.set_value(1.0)
                                    except RuntimeError:
                                        pass

                                if update_step_indicators_fn and step_indicators:
                                    update_step_indicators_fn(ProductionPhase.COMPLETED, step_indicators)

                                # Add to history
                                state.pipeline_history.append({
                                    'title': state.script.title if state.script else 'Unknown',
                                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
                                    'success': True,
                                    'video_path': result.video_path,
                                    'youtube_id': result.youtube_id
                                })
                                safe_refresh(history_list)

                            else:
                                state.pipeline_phase = ProductionPhase.FAILED
                                state.pipeline_message = f"Failed: {result.error}"
                                state.last_error = result.error
                                show_error_panel(result.error)
                                safe_notify('❌ Pipeline failed', type='negative')

                                state.pipeline_history.append({
                                    'title': state.script.title if state.script else 'Unknown',
                                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
                                    'success': False,
                                    'error': result.error
                                })
                                safe_refresh(history_list)

                        except Exception as e:
                            state.pipeline_phase = ProductionPhase.FAILED
                            state.pipeline_message = f"Error: {str(e)}"
                            state.last_error = str(e)
                            show_error_panel(str(e))
                            safe_notify(f'❌ Error: {e}', type='negative')
                            logger.error(f"Pipeline error: {e}")

                        finally:
                            state.pipeline_running = False
                            try:
                                start_btn.enable()
                                stop_btn.disable()
                            except RuntimeError:
                                pass

                    async def stop_pipeline():
                        """Stop the running pipeline"""
                        if state.production_service:
                            state.production_service.cancel()
                        state.pipeline_running = False
                        state.pipeline_phase = ProductionPhase.FAILED
                        state.pipeline_message = "Stopped by user"
                        safe_notify('⏹️ Pipeline stopped', type='warning')
                        logger.warning("Pipeline stopped by user")

                    with ui.row().classes('w-full gap-2'):
                        start_btn = ui.button(
                            'Start Pipeline',
                            on_click=run_full_pipeline
                        ).classes('flex-grow').props('color=teal unelevated icon=play_arrow size=lg')

                        stop_btn = ui.button(icon='stop', on_click=stop_pipeline).props('color=red unelevated size=lg')
                        stop_btn.disable()

            # === Live Status Card ===
            with ui.card().classes('w-full p-0 bg-slate-800 border border-slate-700 overflow-hidden'):
                with ui.element('div').classes('w-full p-3 border-b border-slate-700'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('monitor_heart', size='xs').classes('text-pink-400')
                        ui.label('Live Status').classes('text-sm font-bold text-pink-300')

                with ui.element('div').classes('p-4'):
                    with ui.row().classes('w-full justify-between mb-3'):
                        with ui.column().classes('items-center'):
                            elapsed_label = ui.label('0:00').classes('text-2xl font-bold text-white')
                            ui.label('Elapsed').classes('text-xs text-gray-500')
                        with ui.column().classes('items-center'):
                            scenes_label = ui.label('0/0').classes('text-2xl font-bold text-teal-400')
                            ui.label('Scenes').classes('text-xs text-gray-500')

                    current_task_label = ui.label('Ready to start').classes(
                        'text-xs text-gray-400 italic truncate w-full text-center p-2 bg-slate-700/50 rounded'
                    )

            # === Execution History Card ===
            with ui.card().classes('w-full p-0 bg-slate-800 border border-slate-700 overflow-hidden'):
                with ui.element('div').classes('w-full p-3 border-b border-slate-700'):
                    with ui.row().classes('items-center justify-between'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('history', size='xs').classes('text-amber-400')
                            ui.label('Recent Runs').classes('text-sm font-bold text-amber-300')
                        history_count_badge = ui.badge('0').classes('bg-slate-600 text-gray-300 text-xs')

                @ui.refreshable
                def history_list():
                    history = getattr(state, 'pipeline_history', [])
                    try:
                        history_count_badge.text = str(len(history))
                    except RuntimeError:
                        pass

                    if not history:
                        with ui.element('div').classes('p-4 text-center'):
                            ui.label('No runs yet').classes('text-xs text-gray-500')
                        return

                    with ui.scroll_area().classes('h-32'):
                        with ui.element('div').classes('p-2 space-y-2'):
                            for run in reversed(history[-5:]):
                                is_success = run.get('success', False)
                                border_color = 'border-green-500' if is_success else 'border-red-500'

                                with ui.element('div').classes(f'p-2 bg-slate-700/50 rounded border-l-2 {border_color}'):
                                    with ui.row().classes('items-center justify-between'):
                                        with ui.column().classes('gap-0'):
                                            title = run.get('title', 'Unknown')[:20]
                                            ui.label(title).classes('text-xs text-white font-medium truncate')
                                            ui.label(run.get('timestamp', '')).classes('text-[10px] text-gray-500')

                                        if is_success:
                                            ui.icon('check_circle', size='xs').classes('text-green-400')
                                        else:
                                            ui.icon('error', size='xs').classes('text-red-400')

                                    if run.get('video_path'):
                                        def play_history_video(path=run['video_path']):
                                            try:
                                                video_preview.set_source(path)
                                                video_preview.visible = True
                                                preview_placeholder.visible = False
                                            except (FileNotFoundError, ValueError, RuntimeError) as e:
                                                logger.warning(f"Video preview failed: {e}")

                                        ui.button('Play', on_click=play_history_video).props('flat dense size=xs color=teal').classes('mt-1')

                history_list()

        # === Center Column: Progress ===
        with ui.column().classes('flex-grow gap-3'):
            # Phase Progress Cards
            with ui.card().classes('w-full p-0 bg-slate-800 border border-slate-600 overflow-hidden'):
                with ui.element('div').classes('w-full p-3 border-b border-slate-700'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('timeline', size='xs').classes('text-purple-400')
                        ui.label('Pipeline Progress').classes('text-sm font-bold text-purple-300')

                with ui.element('div').classes('p-4 space-y-3'):
                    phases_info = [
                        ('planning', 'Script Generation', 'edit_note', 'pink', 'GPT-4o analyzes content'),
                        ('generating', 'Visual Generation', 'auto_fix_high', 'teal', 'Imagen/Veo creates visuals'),
                        ('editing', 'Video Editing', 'movie_edit', 'amber', 'TTS, subtitles, BGM'),
                        ('uploading', 'YouTube Upload', 'upload', 'red', 'Upload to YouTube'),
                    ]

                    for phase_key, phase_name, phase_icon, phase_color, phase_desc in phases_info:
                        with ui.element('div').classes(f'w-full p-3 bg-slate-700/50 rounded-lg border border-slate-600 hover:border-{phase_color}-500/50 transition-colors'):
                            with ui.row().classes('items-center justify-between mb-2'):
                                with ui.row().classes('items-center gap-2'):
                                    with ui.element('div').classes(f'w-8 h-8 rounded-full bg-{phase_color}-900/50 flex items-center justify-center'):
                                        ui.icon(phase_icon, size='xs').classes(f'text-{phase_color}-400')
                                    with ui.column().classes('gap-0'):
                                        ui.label(phase_name).classes('font-medium text-white text-sm')
                                        ui.label(phase_desc).classes('text-[10px] text-gray-500')

                                with ui.row().classes('items-center gap-2'):
                                    phase_time_labels[phase_key] = ui.label('').classes('text-xs text-gray-500')
                                    phase_labels[phase_key] = ui.label('Pending').classes('text-xs text-gray-400 font-medium min-w-[50px] text-right')

                            progress_bars[phase_key] = ui.linear_progress(value=0, show_value=False).props(f'color={phase_color} rounded size=8px')

            # Scene Thumbnails Grid
            with ui.card().classes('w-full p-0 bg-slate-800 border border-slate-600 overflow-hidden'):
                with ui.element('div').classes('w-full p-3 border-b border-slate-700'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('grid_view', size='xs').classes('text-teal-400')
                        ui.label('Scene Progress').classes('text-sm font-bold text-teal-300')

                with ui.element('div').classes('p-4 min-h-[140px]'):
                    scene_grid = ui.row().classes('w-full flex-wrap gap-3 justify-start')
                    with scene_grid:
                        with ui.column().classes('w-full items-center justify-center py-6'):
                            ui.icon('burst_mode', size='lg').classes('text-slate-700')
                            ui.label('Scene thumbnails will appear here').classes('text-xs text-gray-600')

            # Error Panel
            error_panel = ui.card().classes('w-full p-4 bg-red-900/20 border border-red-700/50 rounded-lg')
            error_panel.visible = False
            with error_panel:
                with ui.row().classes('items-start gap-3'):
                    ui.icon('error_outline', size='md').classes('text-red-400')
                    with ui.column().classes('flex-grow gap-2'):
                        error_message_label = ui.label('Error').classes('font-bold text-red-300')
                        error_details_label = ui.label('').classes('text-sm text-red-200/70')

        # === Right Column: Preview ===
        with ui.column().classes('w-[340px] min-w-[320px] gap-3'):
            # Video Preview Card
            with ui.card().classes('w-full p-0 bg-black rounded-xl border border-slate-700 overflow-hidden'):
                with ui.element('div').classes('w-full p-3 bg-gradient-to-r from-slate-800 to-slate-700 border-b border-slate-600'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('smart_display', size='xs').classes('text-purple-400')
                        ui.label('Preview').classes('text-sm font-bold text-white')

                with ui.element('div').classes('w-full aspect-[9/16] bg-gradient-to-b from-slate-900 to-black flex items-center justify-center relative'):
                    # Placeholder
                    with ui.column().classes('items-center gap-3') as preview_placeholder:
                        ui.icon('videocam_off', size='xl').classes('text-slate-700')
                        ui.label('No Preview').classes('text-sm text-slate-600')

                    # Video Player
                    video_preview = ui.video('').classes('w-full h-full object-contain')
                    video_preview.visible = False
