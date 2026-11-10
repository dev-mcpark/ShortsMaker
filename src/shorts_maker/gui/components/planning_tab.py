"""Script Planning 탭 컴포넌트 - Premium UI 적용"""

import json
from nicegui import ui
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.gui.components.common.source_access import load_source_catalog
from shorts_maker.gui.components.script_form import render_script_form
from shorts_maker.gui.components.work_drafts_panel import render_work_drafts_panel
from shorts_maker.gui.config.ui_theme import SCENE_GRADIENTS
from shorts_maker.planner.script_planner import ShortsScript
from shorts_maker.services.visual_cost import estimated_scene_cost, scene_mode
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.source_manager import SourceManager

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


def estimate_new_visual_cost(script: ShortsScript, mode: str) -> float:
    """Upper estimate before cache/manual reuse, using the production model and durations."""
    total = 0.0
    for index, scene in enumerate(script.scenes):
        visual_mode = scene_mode(mode, scene, index)
        model = settings.veo_model_id if visual_mode == 'video' else settings.image_model_id
        duration = settings.hybrid_veo_duration_seconds if mode == 'hybrid' else settings.veo_duration_seconds
        total += estimated_scene_cost(visual_mode, model, duration)
    return total


def _saved_script_options() -> dict[str, str]:
    scripts = []
    for path in settings.scripts_dir.glob('*.json'):
        try:
            if not path.resolve().is_relative_to(settings.scripts_dir.resolve()):
                continue
            script = ShortsScript.model_validate_json(path.read_text(encoding='utf-8'))
            scripts.append((path.stat().st_mtime, path.name, f'{script.title} · {path.name}'))
        except (OSError, ValueError):
            continue
    return {name: label for _, name, label in sorted(scripts, reverse=True)}


def render_planning_tab(state: 'AppState', on_reviewed=None) -> None:
    """Script Planning 탭 렌더링"""

    script_preview_container = None
    editor_area = None
    editor_source = {'key': state.script_editor_key()}
    previewed_script = {'json': None}
    form_panel = None
    draft_panel = None
    draft_view_key = {'value': state.script_editor_key()}

    def restore_editor():
        editor_source['key'] = state.script_editor_key()
        editor_area.value = state.script_editor_text()

    def sync_json_from_form():
        editor_area.value = state.script_editor_text()

    def remember_json(event):
        before = state.script_editor_text()
        state.remember_script_draft(editor_source['key'], event.value or '')
        if state.script_editor_text() != before and form_panel is not None:
            safe_refresh(form_panel)

    def apply_script(script, context=None):
        audio = {key: getattr(state, key) for key in ('tts_voice', 'bgm_mood', 'bgm_track', 'bgm_volume')}
        state.load_saved_script(script)
        for key, value in audio.items():
            setattr(state, key, value)
        state.script_context = context
        state.topic_candidates = context.candidates if context else []

    def update_script_preview():
        nonlocal form_panel
        if draft_panel is not None and draft_view_key['value'] != state.script_editor_key():
            draft_view_key['value'] = state.script_editor_key()
            safe_refresh(draft_panel)
        try:
            script_preview_container.clear()
        except RuntimeError:
            return

        if not state.script:
            form_panel = None
            previewed_script['json'] = None
            with script_preview_container:
                with ui.element('div').classes('w-full h-full flex items-center justify-center py-20'):
                    with ui.column().classes('items-center gap-4'):
                        ui.icon('auto_stories', size='xl').classes('text-slate-700')
                        ui.label('각본이 아직 기획되지 않았습니다').classes('text-lg font-bold text-slate-300')
                        ui.label('RSS 분야 또는 기사 URL을 선택해 각본을 기획하세요.').classes('text-xs text-slate-400')
            return

        script = state.script
        previewed_script['json'] = script.model_dump_json()
        total_duration = sum(s.duration_seconds for s in script.scenes) if script.scenes else 0

        with script_preview_container:
            form_panel = render_script_form(state, sync_json_from_form,
                                            lambda: save_script(), lambda: discard_draft())
            ui.label('현재 적용된 대본 · 수정 내용 적용 후 갱신됩니다.').classes('text-xs text-slate-400 mb-2')
            # ── 각본 헤더 ──────────────────────────────────────
            with ui.element('div').classes('w-full p-5 rounded-xl bg-gradient-to-r from-violet-950/20 to-indigo-950/20 border border-violet-500/20 mb-5 backdrop-blur-md'):
                with ui.row().classes('w-full items-start justify-between mb-2'):
                    with ui.column().classes('gap-1 flex-grow mr-4'):
                        ui.label(script.title).classes('text-lg font-bold text-white leading-tight')
                        ui.label(script.description).classes('text-xs text-slate-400 leading-relaxed mt-1')
                        if script.music_direction:
                            ui.label(f'음악 연출: {script.music_direction}').classes(
                                'text-xs text-teal-300 leading-relaxed mt-2'
                            )

                    ui.badge().bind_text_from(
                        state, 'mode', backward=lambda mode: '기본 모드 · ' + {
                            'video': 'Veo 영상', 'hybrid': '영상+이미지', 'image': 'Gemini 이미지',
                        }.get(mode, mode),
                    ).classes('bg-violet-950 text-violet-200 text-[10px] font-semibold px-3 py-0.5 rounded shrink-0')

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
                    ]:
                        with ui.column().classes('items-center gap-1'):
                            ui.label(val).classes(f'text-xl font-extrabold {color} tracking-tight')
                            ui.label(label).classes('text-[10px] text-slate-500 uppercase tracking-wider font-bold')
                        ui.element('div').classes('w-px h-6 bg-slate-800')
                    with ui.column().classes('items-center gap-1'):
                        def cost_label(mode: str) -> str:
                            try:
                                return f'${estimate_new_visual_cost(script, mode):.3f}'
                            except ValueError:
                                return '가격 미등록'
                        ui.label().bind_text_from(state, 'mode', backward=cost_label).classes('text-xl font-extrabold text-amber-400 tracking-tight')
                        ui.label('전체 비주얼 추정 · 저장분 차감 전').classes('text-[10px] text-slate-500 font-bold')
                ui.label('장면에 지정된 모드가 있으면 기본 모드보다 우선합니다.').classes('text-xs text-slate-400 mt-2')

    # ── 메인 레이아웃 ────────────────────────────────────────
    with ui.row().classes('w-full h-auto lg:h-full gap-0 flex flex-col lg:flex-row flex-nowrap overflow-visible lg:overflow-hidden'):

        # === Left Panel: 각본 생성 컨트롤 ===
        with ui.column().classes('w-full lg:w-80 bg-slate-950/50 border-b lg:border-b-0 lg:border-r border-slate-800 p-4 lg:p-5 gap-4 h-auto lg:h-full overflow-visible lg:overflow-y-auto shrink-0'):


            # 타이틀
            with ui.row().classes('items-center gap-2 mb-2'):
                ui.icon('psychology', size='sm').classes('text-pink-400')
                ui.label('각본 생성').classes('text-base font-bold text-pink-300')

            # 소스 선택
            with ui.element('div').classes('w-full rounded-xl bg-slate-900/60 border border-slate-600 p-4'):
                ui.label('소스 방식').classes('text-xs text-gray-300 uppercase tracking-wider mb-3')

                source_mode = ui.radio(
                    ['RSS 자동 발견', '직접 URL 입력'],
                    value='RSS 자동 발견'
                ).props('color=pink size=32px').classes('w-full mb-3')

                url_input = ui.input(
                    '기사 URL',
                    placeholder='https://example.com/article'
                ).bind_visibility_from(
                    source_mode, 'value', value='직접 URL 입력'
                ).props('outlined dense dark').classes('w-full mb-2')

                catalog_manager, catalog = load_source_catalog(SourceManager)
                category_select = ui.select(
                    ['전체 분야', *catalog],
                    value='전체 분야', label='RSS 분야'
                ).bind_visibility_from(
                    source_mode, 'value', value='RSS 자동 발견'
                ).props('outlined dense dark').classes('w-full mb-2')

                spinner = ui.spinner(size='sm').props('color=pink').classes('self-center my-2')
                spinner.visible = False

                async def generate_script():
                    if state.is_busy:
                        safe_notify('진행 중인 제작·업로드가 끝난 뒤 각본을 기획하세요.', type='warning')
                        return
                    if source_mode.value == 'RSS 자동 발견' and catalog_manager is None:
                        safe_notify('RSS 설정을 복구한 뒤 다시 기획하세요. 저장된 대본은 계속 열 수 있습니다.', type='warning')
                        return
                    if source_mode.value == '직접 URL 입력' and not url_input.value:
                        safe_notify('URL을 입력해주세요', type='negative')
                        return
                    try:
                        spinner.visible = True
                    except RuntimeError:
                        return
                    try:
                        logger.info(f"Starting Plan: Mode={source_mode.value}")
                        service = state.get_or_create_service()
                        state.pipeline_running = True
                        script, context = await service.generate_script(
                            topic=(category_select.value if source_mode.value == 'RSS 자동 발견'
                                   and category_select.value != '전체 분야' else None),
                            direct_url=url_input.value if source_mode.value == '직접 URL 입력' else None
                        )
                        if script:
                            state.pipeline_running = False
                            apply_script(script, context)
                            safe_notify(f'각본 생성 완료: {script.title}', type='positive')
                            try:
                                update_script_preview()
                                update_candidates_panel()
                                restore_editor()
                            except RuntimeError:
                                pass
                        else:
                            message = (service.PAID_WORK_DISABLED
                                       if service.progress.error == service.PAID_WORK_DISABLED
                                       else '각본 생성 실패')
                            safe_notify(message, type='negative')
                    except Exception as e:
                        safe_notify(f'오류: {str(e)}', type='negative')
                        logger.error(f"Plan Error: {e}")
                    finally:
                        state.pipeline_running = False
                        try:
                            spinner.visible = False
                        except RuntimeError:
                            pass

                ui.button(
                    '각본 생성하기',
                    on_click=generate_script
                ).classes('w-full mt-2').props('color=pink-9 unelevated icon=auto_awesome size=md').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and settings.paid_production_enabled
                    and (source_mode.value != 'RSS 자동 발견' or catalog_manager is not None))
                if not settings.paid_production_enabled:
                    ui.label('검토 모드: 새 각본 생성은 중지되어 있습니다. 아래에서 저장된 각본을 불러오세요.').classes('text-xs text-amber-200 mt-2')

            # 저장된 각본 불러오기
            with ui.element('div').classes('w-full rounded-xl bg-slate-900/60 border border-slate-600 p-4'):
                with ui.row().classes('items-center gap-2 mb-3'):
                    ui.icon('folder_open', size='xs').classes('text-amber-400')
                    ui.label('저장된 각본').classes('text-xs font-bold text-amber-300 uppercase tracking-wider')

                @ui.refreshable
                def saved_scripts():
                    script_dir = settings.scripts_dir
                    if script_dir.exists():
                        script_files = _saved_script_options()

                        if script_files:
                            script_select = ui.select(
                                options=script_files,
                                label='저장된 각본 검색', with_input=True,
                            ).props('outlined dense dark').classes('w-full mb-2')
                            ui.label('제목·파일명으로 검색 · 파일 최근 수정순').classes('text-xs text-slate-400')

                            async def load_selected_script():
                                if state.is_busy:
                                    safe_notify('진행 중인 제작·업로드가 끝난 뒤 각본을 불러오세요.', type='warning')
                                    return
                                if script_select.value in script_files:
                                    try:
                                        with (script_dir / script_select.value).open('r', encoding='utf-8') as f:
                                            data = json.load(f)
                                        loaded_script = ShortsScript.model_validate(data)
                                        state.load_saved_script(loaded_script)
                                        update_script_preview()
                                        update_candidates_panel()
                                        feedback_section.visible = False
                                        restore_editor()
                                        safe_notify(f'불러옴: {state.script.title}', type='positive')
                                    except Exception as e:
                                        safe_notify(f'로드 오류: {e}', type='negative')

                            ui.button('불러오기', on_click=load_selected_script).props('flat color=amber icon=download dense').classes('w-full').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
                        else:
                            ui.label('저장된 각본 없음').classes('text-xs text-gray-600')
                    else:
                        ui.label(f'{script_dir} 폴더 없음').classes('text-xs text-gray-600')

                saved_scripts()

                def save_current_script():
                    if (not state.script or state.script.model_dump_json() != previewed_script['json']):
                        safe_notify('현재 대본 미리보기를 확인한 뒤 저장하세요.', type='warning')
                        return
                    try:
                        if (not editor_area.value or ShortsScript.model_validate_json(editor_area.value).model_dump_json()
                                != state.script.model_dump_json()):
                            safe_notify('미적용 수정을 먼저 현재 작업에 적용한 뒤 저장하세요.', type='warning')
                            return
                        path = state.save_script_copy()
                        safe_refresh(saved_scripts)
                        safe_notify(f'새 파일로 저장했습니다: {path.name}. 저장은 검토 승인이 아닙니다.', type='positive')
                    except (OSError, ValueError) as error:
                        safe_notify(f'대본 저장 실패: {error}', type='negative')

                ui.button('현재 대본 새 파일로 저장', on_click=save_current_script).props('flat icon=save').classes('w-full').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and state.script is not None)
                ui.label('미적용 수정은 먼저 적용하세요. 저장한 사본은 재시작 후 다시 불러올 수 있으며 원본은 보존됩니다.').classes('text-xs text-slate-400')

            def restore_draft_view():
                restore_editor()
                update_script_preview()
                update_candidates_panel()
                feedback_section.visible = False

            draft_panel = render_work_drafts_panel(state, restore_draft_view)

            # JSON 편집기 (고급)
            with ui.expansion('JSON 편집기', icon='code').classes('w-full').props('header-class="text-xs text-gray-300 px-0"'):
                editor_area = ui.textarea('각본 JSON', value=state.script_editor_text(),
                    on_change=remember_json
                ).classes('w-full font-mono text-xs bg-slate-900 text-green-300 p-2 rounded').props('outlined rows=10').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and editor_source['key'] == state.script_editor_key())

                def save_script():
                    if state.is_busy:
                        safe_notify('진행 중인 제작·업로드가 끝난 뒤 각본을 적용하세요.', type='warning')
                        return
                    if editor_source['key'] != state.script_editor_key():
                        safe_notify('대본이 바뀌었습니다. 편집기를 다시 열어 확인하세요.', type='warning')
                        return
                    try:
                        data = json.loads(editor_area.value)
                        edited_script = ShortsScript(**data)
                        consumed_key = editor_source['key']
                        if state.script and edited_script.model_dump_json() == state.script.model_dump_json():
                            state.script_editor_drafts.pop(consumed_key, None)
                            restore_editor()
                            if form_panel is not None:
                                safe_refresh(form_panel)
                            safe_notify('현재 대본과 같은 내용입니다. 기존 검토·완성본을 유지합니다.', type='info')
                            return
                        apply_script(edited_script)
                        state.script_editor_drafts.pop(consumed_key, None)
                        restore_editor()
                        update_script_preview()
                        update_candidates_panel()
                        feedback_section.visible = False
                        safe_notify('각본 적용됨!', type='positive')
                    except Exception as e:
                        safe_notify(f'대본을 적용할 수 없습니다: {e}', type='negative')

                ui.button('현재 작업에 적용', on_click=save_script).props('flat color=green-4 icon=save dense').classes('w-full mt-1').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
                def discard_draft():
                    if state.is_busy or editor_source['key'] != state.script_editor_key():
                        safe_notify('현재 대본 편집기를 다시 열어 확인하세요.', type='warning')
                        return
                    state.script_editor_drafts.pop(editor_source['key'], None)
                    restore_editor()
                    if form_panel is not None:
                        safe_refresh(form_panel)

                ui.button('미적용 수정 되돌리기', on_click=discard_draft).props('flat color=grey-4').classes('w-full min-h-[44px]').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy)
                ui.label('입력은 메뉴 이동 시 유지됩니다. 재시작 전에는 작업 초안 사본을 저장하거나, 적용 후 대본 새 파일로 저장하세요.').classes('text-xs text-amber-200 mt-1')
                ui.label('적용 후 위의 현재 대본 새 파일로 저장을 누르면 수정본을 보관할 수 있습니다. 출처·각본·장면 검토는 다시 필요합니다.').classes('text-xs text-slate-400 mt-1')

            # 피드백 섹션 (스크립트 생성 후 표시)
            with ui.element('div').classes('w-full rounded-xl bg-slate-900/60 border border-orange-500/30 p-4') as feedback_section:
                feedback_section.bind_visibility_from(state, 'script_context', lambda context: context is not None)

                with ui.row().classes('items-center gap-2 mb-3'):
                    ui.icon('feedback', size='xs').classes('text-orange-400')
                    ui.label('피드백으로 재생성').classes('text-xs font-bold text-orange-300 uppercase tracking-wider')
                    regen_counter_label = ui.label().bind_text_from(state, 'script_context', backward=lambda context:
                        f'재생성: {context.attempt_count}/{context.max_attempts}회' if context else '재생성 컨텍스트 없음'
                    ).classes('text-xs text-gray-500 ml-auto')

                feedback_input = ui.textarea(
                    '피드백',
                    placeholder='예: 후크가 약해요. 더 충격적인 사실로 시작해주세요.'
                ).props('outlined dark rows=3').classes('w-full mb-2').bind_enabled_from(state, 'is_busy', lambda busy: not busy)

                async def regenerate_with_feedback():
                    if state.is_busy:
                        safe_notify('진행 중인 제작·업로드가 끝난 뒤 재생성하세요.', type='warning')
                        return
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
                        context = state.script_context
                        service = state.get_or_create_service()
                        state.pipeline_running = True
                        new_script = await service.regenerate_script(
                            context=context,
                            feedback=feedback_input.value
                        )
                        if new_script:
                            state.pipeline_running = False
                            apply_script(new_script, context)
                            safe_notify(f'재생성 완료: {new_script.title}', type='positive')
                            try:
                                update_script_preview()
                                update_candidates_panel()
                                restore_editor()
                                feedback_input.value = ''
                            except RuntimeError:
                                pass
                        else:
                            message = (service.PAID_WORK_DISABLED
                                       if service.progress.error == service.PAID_WORK_DISABLED
                                       else getattr(service.progress, 'message', '') or '재생성 실패')
                            safe_notify(message, type='negative')
                    except Exception as e:
                        safe_notify(f'재생성 오류: {e}', type='negative')
                        logger.error(f"Regen error: {e}")
                    finally:
                        state.pipeline_running = False
                        try:
                            spinner.visible = False
                        except RuntimeError:
                            pass

                ui.button('피드백 반영 재생성', on_click=regenerate_with_feedback).classes('w-full').props('color=orange unelevated icon=refresh').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and settings.paid_production_enabled)

            # 확인 및 이동 버튼
            with ui.element('div').classes('w-full mt-auto pt-4'):
                ui.label('출처·내레이션·장면 설명을 확인하세요. 영상 첫 프레임과 움직임은 별도 검토가 필요합니다.').classes(
                    'text-xs text-amber-300 mb-2')
                def confirm_script():
                    if state.is_busy:
                        safe_notify('진행 중인 제작·업로드가 끝난 뒤 각본을 확인하세요.', type='warning')
                        return
                    if state.has_unapplied_script_draft():
                        safe_notify('미적용 대본 수정이 있습니다. 먼저 적용하거나 되돌린 뒤 각본을 확인하세요.', type='warning')
                        return
                    if state.script and state.script.model_dump_json() != previewed_script['json']:
                        safe_notify('각본이 변경됐습니다. 미리보기를 새로고침하고 다시 확인하세요.', type='warning')
                        return
                    if state.script:
                        state.confirm_script_review()
                        safe_notify('각본 확인을 기록했습니다. 장면·영상 제작으로 이어가세요.', type='positive')
                        logger.info(f"Script confirmed: {state.script.title}")
                        if on_reviewed:
                            on_reviewed()
                    else:
                        safe_notify('생성된 각본이 없습니다', type='warning')

                ui.button(
                    '각본 확인 완료 · 영상 제작으로 →',
                    on_click=confirm_script
                ).classes('w-full').props('color=green-9 unelevated icon=check_circle size=md').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and state.script is not None)

        # === Right Panel: 주제 후보 + 각본 미리보기 ===
        with ui.column().classes('w-full lg:w-auto lg:flex-grow min-w-0 min-h-[400px] lg:h-full overflow-hidden flex flex-col flex-nowrap'):

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
                                    adopted = state.script and state.script.source_url == candidate.item.get('url')
                                    ui.badge('대본 채택' if adopted else '1차 선별', color='teal').props('dense')
                                ui.label(candidate.item.get('title', '')[:50]).classes('text-xs text-gray-300 flex-grow')
                            ui.label(candidate.reason).classes('text-xs text-gray-500')

            # 미리보기 헤더
            with ui.element('div').classes('w-full px-6 py-3 border-b border-slate-700 bg-slate-800/30 flex items-center justify-between shrink-0'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('auto_stories', size='xs').classes('text-purple-400')
                    ui.label('각본 미리보기').classes('text-sm font-bold text-purple-300')

                    status_dot_class = 'w-2 h-2 rounded-full bg-green-400' if state.script else 'w-2 h-2 rounded-full bg-gray-600'
                    ui.element('div').classes(status_dot_class)

                ui.button(icon='refresh', on_click=update_script_preview).props('flat round color=gray dense size=sm aria-label="각본 미리보기 새로고침"')

            # 미리보기 스크롤 영역 — flex-grow로 남은 높이 모두 차지
            with ui.scroll_area().classes('w-full flex-grow'):
                with ui.element('div').classes('p-6'):
                    script_preview_container = ui.column().classes('w-full gap-0')

            update_script_preview()
            update_candidates_panel()

            if state.is_busy:
                def recover_after_operation():
                    if state.is_busy:
                        return
                    recovery_timer.cancel()
                    try:
                        update_script_preview()
                        update_candidates_panel()
                        restore_editor()
                    except RuntimeError:
                        pass  # This view was closed again; AppState still owns the result.

                recovery_timer = ui.timer(0.2, recover_after_operation)
