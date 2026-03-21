"""Script Planning 탭 컴포넌트"""

from nicegui import ui
import os
import json
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.gui.config.constants import SCENE_COST_MULTIPLIER
from shorts_maker.gui.config.ui_theme import SCENE_GRADIENTS
from shorts_maker.planner.script_planner import ScriptPlanner, ShortsScript
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)

ACCENT_COLORS = [
    ('from-pink-500', 'to-rose-600', 'border-pink-500/50', 'text-pink-300'),
    ('from-purple-500', 'to-violet-600', 'border-purple-500/50', 'text-purple-300'),
    ('from-indigo-500', 'to-blue-600', 'border-indigo-500/50', 'text-indigo-300'),
    ('from-teal-500', 'to-cyan-600', 'border-teal-500/50', 'text-teal-300'),
    ('from-amber-500', 'to-orange-600', 'border-amber-500/50', 'text-amber-300'),
]


def render_planning_tab(state: 'AppState') -> None:
    """Script Planning 탭 렌더링"""

    script_preview_container = None
    editor_area = None

    def update_script_preview():
        try:
            script_preview_container.clear()
        except RuntimeError:
            return

        if not state.script:
            with script_preview_container:
                with ui.element('div').classes('w-full h-full flex items-center justify-center py-20'):
                    with ui.column().classes('items-center gap-4'):
                        ui.icon('auto_stories', size='xl').classes('text-slate-600')
                        ui.label('각본이 없습니다').classes('text-xl font-bold text-slate-500')
                        ui.label('왼쪽에서 RSS 또는 URL로 각본을 생성하세요').classes('text-sm text-slate-600')
            return

        script = state.script
        total_duration = sum(s.duration_seconds for s in script.scenes) if script.scenes else 0

        with script_preview_container:
            # ── 각본 헤더 ──────────────────────────────────────
            with ui.element('div').classes('w-full p-5 rounded-xl bg-gradient-to-r from-pink-900/40 to-purple-900/40 border border-pink-500/30 mb-5'):
                with ui.row().classes('w-full items-start justify-between mb-2'):
                    with ui.column().classes('gap-1 flex-grow mr-4'):
                        ui.label(script.title).classes('text-xl font-bold text-white leading-tight')
                        ui.label(script.description).classes('text-sm text-gray-400 leading-relaxed mt-1')

                    mode_color = 'bg-purple-600' if getattr(script, 'generation_mode', 'image') == 'video' else 'bg-blue-600'
                    mode_text = 'VIDEO' if getattr(script, 'generation_mode', 'image') == 'video' else 'IMAGE'
                    ui.badge(mode_text).classes(f'{mode_color} text-white text-xs px-3 py-1 rounded-full shrink-0')

                ui.separator().classes('bg-pink-500/20 my-3')

                with ui.row().classes('w-full gap-6 flex-wrap'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('theaters', size='xs').classes('text-pink-400')
                        ui.label(f'{len(script.scenes)} 씬').classes('text-sm font-bold text-white')

                    with ui.row().classes('items-center gap-2'):
                        ui.icon('timer', size='xs').classes('text-teal-400')
                        ui.label(f'{total_duration:.0f}초 ({total_duration/60:.1f}분)').classes('text-sm font-bold text-teal-300')

                    if script.tags:
                        for tag in script.tags[:3]:
                            ui.badge(f'#{tag}').classes('bg-slate-700 text-gray-300 text-xs px-2')

            # ── 씬 타임라인 바 ──────────────────────────────────
            with ui.element('div').classes('w-full mb-4'):
                with ui.row().classes('w-full items-center gap-1 mb-1'):
                    ui.label('타임라인').classes('text-xs text-gray-500 uppercase tracking-wider')
                    ui.label(f'{len(script.scenes)} 씬').classes('text-xs text-gray-600 ml-1')

                with ui.row().classes('w-full items-center gap-1'):
                    for i, s in enumerate(script.scenes):
                        pct = max(4, int(s.duration_seconds / max(total_duration, 1) * 100))
                        grad = SCENE_GRADIENTS[i % len(SCENE_GRADIENTS)]
                        with ui.element('div').style(f'flex: {pct}').classes(f'h-2 rounded-full bg-gradient-to-r {grad} relative group'):
                            with ui.element('div').classes('absolute bottom-4 left-1/2 -translate-x-1/2 bg-slate-800 text-white text-xs px-1 rounded opacity-0 group-hover:opacity-100 whitespace-nowrap pointer-events-none'):
                                ui.label(f'씬{s.scene_number} {s.duration_seconds:.0f}s')

            # ── 씬 카드들 ──────────────────────────────────────
            for i, scene in enumerate(script.scenes):
                from_c, to_c, border_c, label_c = ACCENT_COLORS[i % len(ACCENT_COLORS)]
                duration = scene.duration_seconds

                with ui.element('div').classes(f'w-full rounded-xl border {border_c} bg-slate-800/60 overflow-hidden mb-4'):
                    # 씬 번호 헤더
                    with ui.element('div').classes(f'w-full px-4 py-3 bg-gradient-to-r {from_c} {to_c} bg-opacity-20'):
                        with ui.row().classes('w-full items-center justify-between'):
                            with ui.row().classes('items-center gap-3'):
                                with ui.element('div').classes(f'w-8 h-8 rounded-lg bg-gradient-to-br {from_c} {to_c} flex items-center justify-center shadow'):
                                    ui.label(str(scene.scene_number)).classes('text-sm font-bold text-white')
                                ui.label(f'씬 {scene.scene_number}').classes(f'text-sm font-bold {label_c}')
                            with ui.row().classes('items-center gap-2'):
                                ui.icon('timer', size='xs').classes('text-gray-400')
                                ui.label(f'{duration:.0f}초').classes('text-xs text-gray-400')

                    with ui.element('div').classes('p-4 flex flex-col gap-3'):
                        # 나레이션 (대사)
                        with ui.element('div').classes('w-full rounded-lg bg-amber-900/20 border border-amber-500/30 p-3'):
                            with ui.row().classes('items-start gap-2 mb-1'):
                                ui.icon('record_voice_over', size='xs').classes('text-amber-400 mt-0.5 shrink-0')
                                ui.label('나레이션').classes('text-xs font-bold text-amber-400 uppercase tracking-wider')
                            ui.label(scene.script_text).classes('text-sm text-white leading-relaxed pl-1')

                        # 비주얼 묘사
                        with ui.element('div').classes('w-full rounded-lg bg-blue-900/20 border border-blue-500/30 p-3'):
                            with ui.row().classes('items-start gap-2 mb-1'):
                                ui.icon('image', size='xs').classes('text-blue-400 mt-0.5 shrink-0')
                                ui.label('비주얼').classes('text-xs font-bold text-blue-400 uppercase tracking-wider')
                            ui.label(scene.visual_description).classes('text-sm text-gray-300 leading-relaxed pl-1')

                        # 모션 지시 (있을 때만)
                        if hasattr(scene, 'motion_instruction') and scene.motion_instruction:
                            with ui.element('div').classes('w-full rounded-lg bg-teal-900/20 border border-teal-500/30 p-3'):
                                with ui.row().classes('items-start gap-2 mb-1'):
                                    ui.icon('animation', size='xs').classes('text-teal-400 mt-0.5 shrink-0')
                                    ui.label('모션').classes('text-xs font-bold text-teal-400 uppercase tracking-wider')
                                ui.label(scene.motion_instruction).classes('text-sm text-gray-300 leading-relaxed pl-1')

            # ── 요약 카드 ──────────────────────────────────────
            with ui.element('div').classes('w-full rounded-xl bg-slate-800 border border-slate-600 p-4 mt-2'):
                with ui.row().classes('w-full justify-around items-center'):
                    for val, label, color in [
                        (str(len(script.scenes)), '씬', 'text-white'),
                        (f'{total_duration:.0f}', '초', 'text-teal-400'),
                        (f'{total_duration/60:.1f}', '분', 'text-pink-400'),
                        (f'${len(script.scenes) * SCENE_COST_MULTIPLIER:.2f}', '예상 비용', 'text-amber-400'),
                    ]:
                        with ui.column().classes('items-center gap-1'):
                            ui.label(val).classes(f'text-2xl font-bold {color}')
                            ui.label(label).classes('text-xs text-gray-500 uppercase tracking-wider')
                        if label != '예상 비용':
                            ui.element('div').classes('w-px h-8 bg-slate-600')

    # ── 메인 레이아웃 ────────────────────────────────────────
    with ui.row().classes('w-full h-full gap-0 overflow-hidden'):

        # === Left Panel: 각본 생성 컨트롤 ===
        with ui.column().classes('w-72 min-w-[288px] bg-slate-800/50 border-r border-slate-700 p-4 gap-4 h-full overflow-y-auto shrink-0'):

            # 타이틀
            with ui.row().classes('items-center gap-2 mb-2'):
                ui.icon('psychology', size='sm').classes('text-pink-400')
                ui.label('각본 생성').classes('text-base font-bold text-pink-300')

            # 소스 선택
            with ui.element('div').classes('w-full rounded-xl bg-slate-900/60 border border-slate-600 p-4'):
                ui.label('소스 방식').classes('text-xs text-gray-500 uppercase tracking-wider mb-3')

                source_mode = ui.radio(
                    ['RSS 자동 발견', '직접 URL 입력'],
                    value='RSS 자동 발견'
                ).props('color=pink dense').classes('w-full mb-3')

                url_input = ui.input(
                    '기사 URL',
                    placeholder='https://example.com/article'
                ).bind_visibility_from(
                    source_mode, 'value', value='직접 URL 입력'
                ).props('outlined dense dark').classes('w-full mb-2')

                topic_input = ui.input(
                    '키워드 (선택)',
                    placeholder='예: AI, 기술, 과학'
                ).bind_visibility_from(
                    source_mode, 'value', value='RSS 자동 발견'
                ).props('outlined dense dark').classes('w-full mb-2')

                spinner = ui.spinner(size='sm').props('color=pink').classes('self-center my-2')
                spinner.visible = False

                async def generate_script():
                    if source_mode.value == '직접 URL 입력' and not url_input.value:
                        safe_notify('URL을 입력해주세요', type='negative')
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
                            direct_url=url_input.value if source_mode.value == '직접 URL 입력' else None
                        )
                        if script:
                            state.script = script
                            update_script_preview()
                            try:
                                editor_area.value = script.model_dump_json(indent=2)
                                safe_notify(f'각본 생성 완료: {script.title}', type='positive')
                            except RuntimeError:
                                pass
                        else:
                            safe_notify('각본 생성 실패', type='negative')
                    except Exception as e:
                        safe_notify(f'오류: {str(e)}', type='negative')
                        logger.error(f"Plan Error: {e}")
                    finally:
                        try:
                            spinner.visible = False
                        except RuntimeError:
                            pass

                ui.button(
                    '각본 생성하기',
                    on_click=generate_script
                ).classes('w-full mt-2').props('color=pink unelevated icon=auto_awesome size=md')

            # 저장된 각본 불러오기
            with ui.element('div').classes('w-full rounded-xl bg-slate-900/60 border border-slate-600 p-4'):
                with ui.row().classes('items-center gap-2 mb-3'):
                    ui.icon('folder_open', size='xs').classes('text-amber-400')
                    ui.label('저장된 각본').classes('text-xs font-bold text-amber-300 uppercase tracking-wider')

                script_dir = "outputs/scripts"
                if os.path.exists(script_dir):
                    script_files = sorted(
                        [f for f in os.listdir(script_dir) if f.endswith('.json')],
                        reverse=True
                    )[:5]

                    if script_files:
                        script_select = ui.select(
                            options={f: f.replace('script_', '').replace('.json', '').replace('_', ' ')[:28] for f in script_files},
                            label='최근 각본'
                        ).props('outlined dense dark').classes('w-full mb-2')

                        async def load_selected_script():
                            if script_select.value:
                                try:
                                    with open(f"{script_dir}/{script_select.value}", 'r', encoding='utf-8') as f:
                                        data = json.load(f)
                                    state.script = ShortsScript.model_validate(data)
                                    update_script_preview()
                                    editor_area.value = json.dumps(data, indent=2, ensure_ascii=False)
                                    safe_notify(f'불러옴: {state.script.title}', type='positive')
                                except Exception as e:
                                    safe_notify(f'로드 오류: {e}', type='negative')

                        ui.button('불러오기', on_click=load_selected_script).props('flat color=amber icon=download dense').classes('w-full')
                    else:
                        ui.label('저장된 각본 없음').classes('text-xs text-gray-600')
                else:
                    ui.label('outputs/scripts 폴더 없음').classes('text-xs text-gray-600')

            # JSON 편집기 (고급)
            with ui.expansion('JSON 편집기', icon='code').classes('w-full').props('header-class="text-xs text-gray-500 px-0"'):
                editor_area = ui.textarea().classes('w-full font-mono text-xs bg-slate-900 text-green-300 p-2 rounded').props('outlined rows=10')

                def save_script():
                    try:
                        data = json.loads(editor_area.value)
                        state.script = ShortsScript(**data)
                        update_script_preview()
                        safe_notify('각본 적용됨!', type='positive')
                    except Exception as e:
                        safe_notify(f'JSON 오류: {e}', type='negative')

                ui.button('적용', on_click=save_script).props('flat color=green icon=save dense').classes('w-full mt-1')

            # 확인 및 이동 버튼
            with ui.element('div').classes('w-full mt-auto pt-4'):
                def confirm_script():
                    if state.script:
                        safe_notify('✅ 각본 확인 완료! Generation 탭으로 이동하세요.', type='positive')
                        logger.info(f"Script confirmed: {state.script.title}")
                    else:
                        safe_notify('생성된 각본이 없습니다', type='warning')

                ui.button(
                    '각본 확인 완료 →',
                    on_click=confirm_script
                ).classes('w-full').props('color=green unelevated icon=check_circle size=md')

        # === Right Panel: 각본 미리보기 ===
        with ui.column().classes('flex-grow h-full overflow-hidden flex flex-col'):

            # 미리보기 헤더
            with ui.element('div').classes('w-full px-6 py-3 border-b border-slate-700 bg-slate-800/30 flex items-center justify-between shrink-0'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('auto_stories', size='xs').classes('text-purple-400')
                    ui.label('각본 미리보기').classes('text-sm font-bold text-purple-300')

                    status_dot_class = 'w-2 h-2 rounded-full bg-green-400' if state.script else 'w-2 h-2 rounded-full bg-gray-600'
                    ui.element('div').classes(status_dot_class)

                ui.button(icon='refresh', on_click=update_script_preview).props('flat round color=gray dense size=sm')

            # 미리보기 스크롤 영역 — flex-grow로 남은 높이 모두 차지
            with ui.scroll_area().classes('w-full flex-grow'):
                with ui.element('div').classes('p-6'):
                    script_preview_container = ui.column().classes('w-full gap-0')

            update_script_preview()
