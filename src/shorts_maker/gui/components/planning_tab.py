"""Script Planning 탭 컴포넌트 - Premium UI 적용"""

from nicegui import ui
import os
import json
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.gui.config.constants import SCENE_COST_MULTIPLIER
from shorts_maker.gui.config.ui_theme import SCENE_GRADIENTS
from shorts_maker.planner.script_planner import ShortsScript
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)

# Premium AI Studio Accent Palettes
ACCENT_COLORS = [
    ('from-violet-500', 'to-indigo-600', 'border-violet-500/30', 'text-violet-300'),
    ('from-fuchsia-500', 'to-purple-600', 'border-fuchsia-500/30', 'text-fuchsia-300'),
    ('from-blue-500', 'to-indigo-600', 'border-blue-500/30', 'text-blue-300'),
    ('from-teal-500', 'to-emerald-600', 'border-teal-500/30', 'text-teal-300'),
    ('from-amber-500', 'to-orange-600', 'border-amber-500/30', 'text-amber-300'),
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
                        ui.icon('auto_stories', size='xl').classes('text-slate-700')
                        ui.label('각본이 아직 기획되지 않았습니다').classes('text-lg font-bold text-slate-500')
                        ui.label('좌측 패널의 생성 컨트롤러를 통해 새로운 주제로 각본을 기획하세요.').classes('text-xs text-slate-600')
            return

        script = state.script
        total_duration = sum(s.duration_seconds for s in script.scenes) if script.scenes else 0

        with script_preview_container:
            # ── 각본 헤더 ──────────────────────────────────────
            with ui.element('div').classes('w-full p-5 rounded-xl bg-gradient-to-r from-violet-950/20 to-indigo-950/20 border border-violet-500/20 mb-5 backdrop-blur-md'):
                with ui.row().classes('w-full items-start justify-between mb-2'):
                    with ui.column().classes('gap-1 flex-grow mr-4'):
                        ui.label(script.title).classes('text-lg font-bold text-white leading-tight')
                        ui.label(script.description).classes('text-xs text-slate-400 leading-relaxed mt-1')

                    mode_color = 'bg-violet-600' if getattr(script, 'generation_mode', 'image') == 'video' else 'bg-blue-600'
                    mode_text = 'VIDEO (VEO)' if getattr(script, 'generation_mode', 'image') == 'video' else 'IMAGE (IMAGEN)'
                    ui.badge(mode_text).classes(f'{mode_color} text-white text-[10px] font-semibold px-3 py-0.5 rounded shrink-0')

                ui.separator().classes('bg-slate-800/80 my-3')

                with ui.row().classes('w-full gap-5 flex-wrap'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('theaters', size='xs').classes('text-violet-400')
                        ui.label(f'{len(script.scenes)} Scenes').classes('text-xs font-bold text-slate-300')

                    with ui.row().classes('items-center gap-2'):
                        ui.icon('timer', size='xs').classes('text-emerald-400')
                        ui.label(f'{total_duration:.1f} Seconds').classes('text-xs font-bold text-emerald-400')

                    if script.tags:
                        for tag in script.tags[:3]:
                            ui.badge(f'#{tag}').classes('bg-slate-800/80 text-slate-400 text-[10px] px-2')

            # ── 씬 타임라인 바 ──────────────────────────────────
            with ui.element('div').classes('w-full mb-5'):
                with ui.row().classes('w-full items-center gap-1 mb-1'):
                    ui.label('Timeline Flow').classes('text-[10px] text-slate-500 uppercase tracking-widest font-bold')
                    ui.label(f'({len(script.scenes)} Scenes)').classes('text-[10px] text-slate-600 font-semibold ml-1')

                with ui.row().classes('w-full items-center gap-1.5'):
                    for i, s in enumerate(script.scenes):
                        pct = max(4, int(s.duration_seconds / max(total_duration, 1) * 100))
                        grad = SCENE_GRADIENTS[i % len(SCENE_GRADIENTS)]
                        with ui.element('div').style(f'flex: {pct}').classes(f'h-1.5 rounded bg-gradient-to-r {grad} relative group cursor-pointer'):
                            with ui.element('div').classes('absolute bottom-4 left-1/2 -translate-x-1/2 bg-slate-900 text-white text-[10px] px-1.5 py-0.5 border border-slate-800 rounded opacity-0 group-hover:opacity-100 whitespace-nowrap pointer-events-none transition-opacity'):
                                ui.label(f'Scene {s.scene_number}: {s.duration_seconds:.0f}s')

            # ── 씬 카드들 ──────────────────────────────────────
            for i, scene in enumerate(script.scenes):
                from_c, to_c, border_c, label_c = ACCENT_COLORS[i % len(ACCENT_COLORS)]
                duration = scene.duration_seconds

                with ui.element('div').classes(f'w-full rounded-xl border {border_c} bg-slate-900/40 hover:bg-slate-900/60 overflow-hidden mb-4 transition-all duration-300'):
                    # 씬 번호 헤더
                    with ui.element('div').classes(f'w-full px-4 py-2.5 bg-gradient-to-r {from_c} {to_c} bg-opacity-10 flex items-center justify-between border-b {border_c}'):
                        with ui.row().classes('items-center gap-3'):
                            with ui.element('div').classes(f'w-6 h-6 rounded bg-gradient-to-br {from_c} {to_c} flex items-center justify-center shadow'):
                                ui.label(str(scene.scene_number)).classes('text-xs font-bold text-white')
                            ui.label(f'Scene {scene.scene_number}').classes(f'text-xs font-bold {label_c} uppercase tracking-wider')
                        with ui.row().classes('items-center gap-1'):
                            ui.icon('timer', size='xs').classes('text-slate-500')
                            ui.label(f'{duration:.1f}s').classes('text-[11px] text-slate-500 font-mono')

                    with ui.element('div').classes('p-4 flex flex-col gap-3'):
                        # 나레이션 (대사)
                        with ui.element('div').classes('w-full rounded bg-amber-950/10 border border-amber-500/10 p-3'):
                            with ui.row().classes('items-center gap-2 mb-1'):
                                ui.icon('record_voice_over', size='xs').classes('text-amber-400 shrink-0')
                                ui.label('나레이션 (TTS Script)').classes('text-[10px] font-bold text-amber-400 uppercase tracking-widest')
                            ui.label(scene.script_text).classes('text-sm text-slate-200 leading-relaxed pl-1')

                        # 비주얼 묘사
                        with ui.element('div').classes('w-full rounded bg-violet-950/10 border border-violet-500/10 p-3'):
                            with ui.row().classes('items-center gap-2 mb-1'):
                                ui.icon('auto_awesome', size='xs').classes('text-violet-400 shrink-0')
                                ui.label('비주얼 프롬프트 (Visual Prompt)').classes('text-[10px] font-bold text-violet-400 uppercase tracking-widest')
                            ui.label(scene.visual_description).classes('text-sm text-slate-300 leading-relaxed pl-1')

                        # 모션 지시 (있을 때만)
                        if hasattr(scene, 'motion_instruction') and scene.motion_instruction:
                            with ui.element('div').classes('w-full rounded bg-teal-950/10 border border-teal-500/10 p-3'):
                                with ui.row().classes('items-center gap-2 mb-1'):
                                    ui.icon('animation', size='xs').classes('text-teal-400 shrink-0')
                                    ui.label('모션 연출 (Motion Instruction)').classes('text-[10px] font-bold text-teal-400 uppercase tracking-widest')
                                ui.label(scene.motion_instruction).classes('text-sm text-slate-300 leading-relaxed pl-1')

            # ── 요약 카드 ──────────────────────────────────────
            with ui.element('div').classes('w-full rounded-xl bg-slate-900/80 border border-slate-800 p-4 mt-2'):
                with ui.row().classes('w-full justify-around items-center'):
                    for val, label, color in [
                        (str(len(script.scenes)), 'Scenes', 'text-white'),
                        (f'{total_duration:.1f}', 'Seconds', 'text-emerald-400'),
                        (f'{total_duration/60:.1f}', 'Minutes', 'text-violet-400'),
                        (f'${len(script.scenes) * SCENE_COST_MULTIPLIER:.2f}', 'Estimated Cost', 'text-amber-400'),
                    ]:
                        with ui.column().classes('items-center gap-1'):
                            ui.label(val).classes(f'text-xl font-extrabold {color} tracking-tight')
                            ui.label(label).classes('text-[10px] text-slate-500 uppercase tracking-wider font-bold')
                        if label != 'Estimated Cost':
                            ui.element('div').classes('w-px h-6 bg-slate-800')

    # ── 메인 레이아웃 ────────────────────────────────────────
    with ui.row().classes('w-full h-full gap-0 overflow-hidden flex-nowrap'):

        # === Left Panel: 각본 생성 컨트롤 ===
        with ui.column().classes('w-80 min-w-[320px] bg-slate-950/50 border-r border-slate-800 p-5 gap-4 h-full overflow-y-auto shrink-0'):


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
                        service = state.get_or_create_service()
                        script, context = await service.generate_script(
                            topic=topic_input.value,
                            direct_url=url_input.value if source_mode.value == '직접 URL 입력' else None
                        )
                        if script:
                            state.reset_manual_mode()
                            state.script = script
                            state.script_context = context
                            state.topic_candidates = context.candidates if context else []
                            update_script_preview()
                            update_candidates_panel()
                            try:
                                editor_area.value = script.model_dump_json(indent=2)
                                safe_notify(f'각본 생성 완료: {script.title}', type='positive')
                                feedback_section.visible = True
                                regen_counter_label.text = f'재생성: 0/{context.max_attempts if context else 3}회'
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
                                    loaded_script = ShortsScript.model_validate(data)
                                    state.reset_manual_mode()
                                    state.script = loaded_script
                                    state.script_context = None
                                    state.topic_candidates = []
                                    update_script_preview()
                                    update_candidates_panel()
                                    feedback_section.visible = False
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
                        edited_script = ShortsScript(**data)
                        state.reset_manual_mode()
                        state.script = edited_script
                        state.script_context = None
                        state.topic_candidates = []
                        update_script_preview()
                        update_candidates_panel()
                        feedback_section.visible = False
                        safe_notify('각본 적용됨!', type='positive')
                    except Exception as e:
                        safe_notify(f'JSON 오류: {e}', type='negative')

                ui.button('적용', on_click=save_script).props('flat color=green icon=save dense').classes('w-full mt-1')

            # 피드백 섹션 (스크립트 생성 후 표시)
            with ui.element('div').classes('w-full rounded-xl bg-slate-900/60 border border-orange-500/30 p-4') as feedback_section:
                feedback_section.visible = False

                with ui.row().classes('items-center gap-2 mb-3'):
                    ui.icon('feedback', size='xs').classes('text-orange-400')
                    ui.label('피드백으로 재생성').classes('text-xs font-bold text-orange-300 uppercase tracking-wider')
                    regen_counter_label = ui.label('재생성: 0/3회').classes('text-xs text-gray-500 ml-auto')

                feedback_input = ui.textarea(
                    '피드백',
                    placeholder='예: 후크가 약해요. 더 충격적인 사실로 시작해주세요.'
                ).props('outlined dark rows=3').classes('w-full mb-2')

                async def regenerate_with_feedback():
                    if not state.script_context:
                        safe_notify('재생성할 컨텍스트가 없습니다', type='warning')
                        return
                    max_att = state.script_context.max_attempts
                    if state.script_context.attempt_count >= max_att:
                        safe_notify(f'최대 재생성 횟수({max_att}회)를 초과했습니다', type='warning')
                        return
                    if not feedback_input.value.strip():
                        safe_notify('피드백을 입력해주세요', type='warning')
                        return
                    try:
                        spinner.visible = True
                    except RuntimeError:
                        return
                    try:
                        service = state.get_or_create_service()
                        new_script = await service.regenerate_script(
                            context=state.script_context,
                            feedback=feedback_input.value
                        )
                        regen_counter_label.text = f'재생성: {state.script_context.attempt_count}/{max_att}회'
                        if new_script:
                            state.reset_manual_mode()
                            state.script = new_script
                            update_script_preview()
                            try:
                                editor_area.value = new_script.model_dump_json(indent=2)
                                safe_notify(f'재생성 완료: {new_script.title}', type='positive')
                                feedback_input.value = ''
                            except RuntimeError:
                                pass
                        else:
                            safe_notify('재생성 실패', type='negative')
                    except Exception as e:
                        safe_notify(f'재생성 오류: {e}', type='negative')
                        logger.error(f"Regen error: {e}")
                    finally:
                        try:
                            spinner.visible = False
                        except RuntimeError:
                            pass

                ui.button('피드백 반영 재생성', on_click=regenerate_with_feedback).classes('w-full').props('color=orange unelevated icon=refresh')

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

        # === Right Panel: 주제 후보 + 각본 미리보기 ===
        with ui.column().classes('flex-grow h-full overflow-hidden flex flex-col'):

            # 주제 후보 패널 (접힘 가능)
            candidates_container = None

            with ui.element('div').classes('w-full border-b border-slate-700 shrink-0'):
                with ui.expansion('주제 후보 목록', icon='format_list_bulleted').classes('w-full').props('header-class="text-xs text-teal-300 px-4 py-2"') as candidates_expansion:
                    candidates_container = ui.column().classes('w-full gap-2 p-3')

            def update_candidates_panel():
                if not candidates_container:
                    return
                try:
                    candidates_container.clear()
                except RuntimeError:
                    return
                if not state.topic_candidates:
                    with candidates_container:
                        ui.label('후보 없음').classes('text-xs text-gray-600')
                    return
                with candidates_container:
                    for candidate in sorted(state.topic_candidates, key=lambda c: c.score, reverse=True):
                        border_class = 'border-teal-500/50' if candidate.selected else 'border-slate-600'
                        bg_class = 'bg-teal-900/20' if candidate.selected else 'bg-slate-900/40'
                        with ui.element('div').classes(f'w-full rounded-lg border {border_class} {bg_class} p-3'):
                            with ui.row().classes('items-center gap-2 mb-1'):
                                score_color = 'text-green-400' if candidate.score >= 7 else ('text-yellow-400' if candidate.score >= 5 else 'text-red-400')
                                ui.label(f'{candidate.score}/10').classes(f'text-xs font-bold {score_color}')
                                if candidate.selected:
                                    ui.badge('선택됨', color='teal').props('dense')
                                ui.label(candidate.item.get('title', '')[:50]).classes('text-xs text-gray-300 flex-grow')
                            ui.label(candidate.reason).classes('text-xs text-gray-500')

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
            update_candidates_panel()
