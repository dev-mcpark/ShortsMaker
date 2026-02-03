"""Script Planning 탭 컴포넌트"""

from nicegui import ui
import os
import json
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.gui.components.common.card_header import card_with_header
from shorts_maker.gui.config.constants import SCENE_COST_MULTIPLIER
from shorts_maker.gui.config.ui_theme import SCENE_GRADIENTS
from shorts_maker.planner.script_planner import ScriptPlanner, ShortsScript
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)


def render_planning_tab(state: 'AppState') -> None:
    """Script Planning 탭 렌더링"""

    # 스크립트 프리뷰 컨테이너 (나중에 참조)
    script_preview_container = None
    editor_area = None

    def update_script_preview():
        """스크립트 내용을 시각적 카드로 표시"""
        try:
            script_preview_container.clear()
        except RuntimeError:
            return

        if not state.script:
            with script_preview_container:
                with ui.card().classes('w-full p-8 bg-slate-800/50 border border-dashed border-slate-600'):
                    with ui.column().classes('items-center gap-4'):
                        ui.icon('description', size='xl').classes('text-slate-500')
                        ui.label('No Script Generated').classes('text-xl text-slate-400')
                        ui.label('Generate a script from RSS or URL to get started').classes('text-sm text-slate-500')
            return

        script = state.script

        with script_preview_container:
            # === 스크립트 메타 정보 카드 ===
            with ui.card().classes('w-full p-5 bg-gradient-to-r from-pink-900/30 to-purple-900/30 border border-pink-500/30 mb-4'):
                with ui.row().classes('w-full items-start justify-between mb-3'):
                    with ui.column().classes('gap-1 flex-grow'):
                        ui.label(script.title).classes('text-xl font-bold text-white leading-tight')
                        ui.label(script.description).classes('text-sm text-gray-400 mt-1')

                    mode_color = 'bg-purple-600' if getattr(script, 'generation_mode', 'image') == 'video' else 'bg-blue-600'
                    mode_text = 'VIDEO' if getattr(script, 'generation_mode', 'image') == 'video' else 'IMAGE'
                    ui.badge(mode_text).classes(f'{mode_color} text-white px-2 py-1')

                ui.separator().classes('bg-slate-600/50 my-3')

                # 메타 정보
                with ui.row().classes('w-full gap-4 flex-wrap'):
                    if hasattr(script, 'source_name') and script.source_name:
                        with ui.element('div').classes('flex items-center gap-2 bg-slate-800/50 rounded-full px-3 py-1'):
                            ui.icon('link', size='xs').classes('text-pink-400')
                            source_text = script.source_name[:25] + '...' if len(script.source_name) > 25 else script.source_name
                            ui.label(source_text).classes('text-xs text-gray-300')

                    if script.tags:
                        tag_colors = ['bg-pink-600/50 text-pink-200', 'bg-purple-600/50 text-purple-200',
                                      'bg-indigo-600/50 text-indigo-200', 'bg-teal-600/50 text-teal-200']
                        for idx, tag in enumerate(script.tags[:4]):
                            with ui.element('div').classes(f'flex items-center gap-1 {tag_colors[idx % len(tag_colors)]} rounded-full px-3 py-1'):
                                ui.icon('tag', size='xs')
                                ui.label(tag).classes('text-xs font-medium')

                    total_duration = sum(s.duration_seconds for s in script.scenes)
                    with ui.element('div').classes('flex items-center gap-2 bg-teal-600/30 rounded-full px-3 py-1'):
                        ui.icon('timer', size='xs').classes('text-teal-300')
                        ui.label(f'{total_duration:.0f}초 ({total_duration/60:.1f}분)').classes('text-xs text-teal-200 font-medium')

            # === 씬 타임라인 ===
            total_duration = sum(s.duration_seconds for s in script.scenes) if script.scenes else 1

            with ui.row().classes('w-full items-center justify-between mb-3'):
                ui.label('Scene Timeline').classes('text-sm font-bold text-gray-400 uppercase tracking-wider')
                with ui.row().classes('items-center gap-1'):
                    for i, s in enumerate(script.scenes):
                        progress_width = max(20, int(s.duration_seconds / total_duration * 200))
                        colors = ['bg-pink-500', 'bg-purple-500', 'bg-indigo-500', 'bg-blue-500', 'bg-teal-500']
                        ui.element('div').classes(f'h-2 rounded-full {colors[i % len(colors)]}').style(f'width: {progress_width}px')

            # 씬 카드들
            for i, scene in enumerate(script.scenes):
                scene_num = scene.scene_number
                duration = scene.duration_seconds
                progress_pct = (duration / total_duration * 100) if total_duration > 0 else 0

                with ui.card().classes('w-full p-0 bg-slate-800 border border-slate-700 hover:border-pink-500/50 transition-all duration-300 mb-3 overflow-hidden'):
                    with ui.element('div').classes('w-full h-1 bg-slate-700'):
                        gradient = SCENE_GRADIENTS[i % len(SCENE_GRADIENTS)]
                        ui.element('div').classes(f'h-full bg-gradient-to-r {gradient}').style(f'width: {progress_pct}%')

                    with ui.element('div').classes('p-4'):
                        with ui.row().classes('w-full gap-4'):
                            # 씬 번호
                            with ui.column().classes('items-center justify-center'):
                                gradient = SCENE_GRADIENTS[i % len(SCENE_GRADIENTS)]
                                with ui.element('div').classes(f'w-14 h-14 rounded-xl bg-gradient-to-br {gradient} flex items-center justify-center shadow-lg'):
                                    ui.label(str(scene_num)).classes('text-xl font-bold text-white')
                                with ui.element('div').classes('mt-2 px-2 py-1 rounded-full bg-slate-700/80 text-center'):
                                    ui.label(f'{duration:.0f}s').classes('text-xs text-gray-300 font-medium')

                            # 씬 내용
                            with ui.column().classes('flex-grow gap-3'):
                                with ui.element('div').classes('bg-slate-700/30 rounded-lg p-3 border-l-4 border-amber-500'):
                                    with ui.row().classes('items-start gap-2'):
                                        ui.icon('record_voice_over', size='sm').classes('text-amber-400')
                                        ui.label(scene.script_text).classes('text-sm text-white leading-relaxed font-medium')

                                with ui.row().classes('w-full gap-3'):
                                    with ui.expansion(text='Visual', icon='image').classes('flex-grow bg-slate-700/30 rounded-lg').props('dense header-class="text-xs text-gray-400 px-2"'):
                                        ui.label(scene.visual_description).classes('text-xs text-gray-400 leading-relaxed p-3')

                                    if hasattr(scene, 'motion_instruction') and scene.motion_instruction:
                                        with ui.expansion(text='Motion', icon='animation').classes('flex-grow bg-slate-700/30 rounded-lg').props('dense header-class="text-xs text-teal-400 px-2"'):
                                            ui.label(scene.motion_instruction).classes('text-xs text-gray-400 leading-relaxed p-3')

            # === 총 요약 카드 ===
            with ui.card().classes('w-full p-4 bg-gradient-to-r from-slate-800 to-slate-700 border border-slate-600 mt-4'):
                with ui.row().classes('w-full justify-around items-center'):
                    with ui.column().classes('items-center'):
                        ui.label(f'{len(script.scenes)}').classes('text-2xl font-bold text-white')
                        ui.label('Scenes').classes('text-xs text-gray-400 uppercase tracking-wider')

                    ui.element('div').classes('w-px h-10 bg-slate-600')

                    with ui.column().classes('items-center'):
                        ui.label(f'{total_duration:.0f}').classes('text-2xl font-bold text-teal-400')
                        ui.label('Seconds').classes('text-xs text-gray-400 uppercase tracking-wider')

                    ui.element('div').classes('w-px h-10 bg-slate-600')

                    with ui.column().classes('items-center'):
                        ui.label(f'{total_duration/60:.1f}').classes('text-2xl font-bold text-pink-400')
                        ui.label('Minutes').classes('text-xs text-gray-400 uppercase tracking-wider')

                    ui.element('div').classes('w-px h-10 bg-slate-600')

                    with ui.column().classes('items-center'):
                        estimated_cost = len(script.scenes) * SCENE_COST_MULTIPLIER
                        ui.label(f'${estimated_cost:.2f}').classes('text-2xl font-bold text-amber-400')
                        ui.label('Est. Cost').classes('text-xs text-gray-400 uppercase tracking-wider')

    # === Main Layout ===
    with ui.row().classes('w-full h-full gap-6'):
        # === Left Panel: Controls ===
        with ui.column().classes('w-80 min-w-[320px] h-full gap-4'):
            # Topic Discovery Card
            with card_with_header('Topic Discovery', 'explore', 'secondary'):
                with ui.element('div').classes('p-5'):
                    source_mode = ui.radio(
                        ['Auto-Discovery (RSS)', 'Direct URL'],
                        value='Auto-Discovery (RSS)'
                    ).props('color=pink dense').classes('mb-4')

                    url_input = ui.input(
                        'Article URL',
                        placeholder='https://example.com/article'
                    ).bind_visibility_from(source_mode, 'value', value='Direct URL').props('outlined dense dark').classes('w-full mb-2')

                    topic_input = ui.input(
                        'Manual Keyword',
                        placeholder='(Optional) e.g., AI, Technology'
                    ).bind_visibility_from(source_mode, 'value', value='Auto-Discovery (RSS)').props('outlined dense dark').classes('w-full mb-4')

                    ui.separator().classes('bg-slate-600 mb-4')

                    spinner = ui.spinner(size='md').props('color=pink').classes('self-center')
                    spinner.visible = False

                    async def generate_script():
                        if source_mode.value == 'Direct URL' and not url_input.value:
                            safe_notify('Please enter a URL', type='negative')
                            return

                        try:
                            spinner.visible = True
                        except RuntimeError:
                            return

                        try:
                            if state.openai_key or state.gcp_project:
                                settings.update_api_keys(
                                    openai_key=state.openai_key,
                                    gcp_project=state.gcp_project
                                )

                            logger.info(f"Starting Plan: Mode={source_mode.value}")
                            planner = ScriptPlanner(generation_mode=state.mode)

                            script = await planner.plan_content(
                                topic=topic_input.value,
                                direct_url=url_input.value if source_mode.value == 'Direct URL' else None
                            )

                            if script:
                                state.script = script
                                update_script_preview()
                                try:
                                    editor_area.value = script.model_dump_json(indent=2)
                                    safe_notify(f"Script generated: {script.title}", type='positive')
                                except RuntimeError:
                                    pass
                            else:
                                safe_notify("Failed to generate script", type='negative')

                        except Exception as e:
                            safe_notify(f"Error: {str(e)}", type='negative')
                            logger.error(f"Plan Error: {e}")
                        finally:
                            try:
                                spinner.visible = False
                            except RuntimeError:
                                pass

                    ui.button(
                        'Generate Script',
                        on_click=generate_script
                    ).classes('w-full').props('color=pink unelevated icon=psychology size=lg')

            # Load Saved Script Card
            with ui.card().classes('w-full p-4 bg-slate-700 border border-slate-600'):
                with ui.row().classes('items-center gap-2 mb-3'):
                    ui.icon('folder_open', size='sm').classes('text-amber-400')
                    ui.label('Load Saved Script').classes('text-sm font-bold text-amber-300')

                script_dir = "outputs/scripts"
                if os.path.exists(script_dir):
                    script_files = sorted(
                        [f for f in os.listdir(script_dir) if f.endswith('.json')],
                        reverse=True
                    )[:5]

                    if script_files:
                        script_select = ui.select(
                            options={f: f.replace('script_', '').replace('.json', '').replace('_', ' ')[:30] for f in script_files},
                            label='Recent Scripts'
                        ).props('outlined dense dark').classes('w-full mb-2')

                        async def load_selected_script():
                            if script_select.value:
                                try:
                                    with open(f"{script_dir}/{script_select.value}", 'r', encoding='utf-8') as f:
                                        data = json.load(f)
                                    state.script = ShortsScript.model_validate(data)
                                    update_script_preview()
                                    editor_area.value = json.dumps(data, indent=2, ensure_ascii=False)
                                    safe_notify(f"Loaded: {state.script.title}", type='positive')
                                except Exception as e:
                                    safe_notify(f"Load error: {e}", type='negative')

                        ui.button('Load', on_click=load_selected_script).props('flat color=amber icon=download').classes('w-full')
                    else:
                        ui.label('No saved scripts').classes('text-xs text-gray-500')
                else:
                    ui.label('Scripts folder not found').classes('text-xs text-gray-500')

            # JSON Editor (Advanced)
            with ui.expansion('Advanced: JSON Editor', icon='code').classes('w-full bg-slate-700 border border-slate-600').props('header-class="text-sm text-gray-400"'):
                editor_area = ui.textarea().classes('w-full h-64 font-mono text-xs bg-slate-900 text-green-300 p-2 rounded').props('outlined')

                def save_script():
                    try:
                        data = json.loads(editor_area.value)
                        state.script = ShortsScript(**data)
                        update_script_preview()
                        safe_notify("Script saved!", type='positive')
                    except Exception as e:
                        safe_notify(f"Invalid JSON: {e}", type='negative')

                ui.button('Apply Changes', on_click=save_script).props('flat color=green icon=save dense').classes('w-full mt-2')

        # === Right Panel: Script Preview ===
        with ui.column().classes('flex-grow h-full'):
            with ui.row().classes('w-full items-center justify-between mb-4'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('auto_stories', size='sm').classes('text-purple-400')
                    ui.label('Script Preview').classes('text-lg font-bold text-purple-300')

                ui.button(icon='refresh', on_click=update_script_preview).props('flat round color=gray')

            with ui.scroll_area().classes('w-full flex-grow'):
                script_preview_container = ui.column().classes('w-full gap-4 pr-2')

            update_script_preview()

            with ui.row().classes('w-full gap-4 mt-4'):
                def confirm_script():
                    if state.script:
                        safe_notify("Script confirmed! Go to Generation tab.", type='positive')
                        logger.info(f"Script confirmed: {state.script.title}")
                    else:
                        safe_notify("No script to confirm", type='warning')

                ui.button('Confirm Script', on_click=confirm_script).classes('flex-grow').props('color=green unelevated icon=check_circle size=lg')
