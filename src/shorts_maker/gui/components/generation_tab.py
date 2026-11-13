"""Video Generation 탭 컴포넌트 - Google AI Studio 스타일 중앙 융합 개편"""
import asyncio
import json
from pathlib import Path
from nicegui import ui
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.gui.components.common.media_preview import media_sources
from shorts_maker.gui.components.narration_panel import render_narration_panel
from shorts_maker.gui.components.image_picker import open_image_picker
from shorts_maker.gui.components.existing_scene_picker import open_existing_scene_picker
from shorts_maker.services.first_frame_candidates import retained_candidate
from shorts_maker.services.production_service import ProductionPhase, ProductionProgress
from shorts_maker.services.raw_review import load_raw_verdict, raw_review_status, save_raw_verdict
from shorts_maker.services.visual_cost import estimated_scene_cost, scene_mode
from shorts_maker.services.visual_review import approve_first_frame, inspect_frame, review_path, verified_first_frame
from shorts_maker.gui.components.common.progress_utils import update_scene_grid
from shorts_maker.utils.veo_prompt_exporter import MAX_MANUAL_CLIP_BYTES, VeoPromptExporter
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)

SCENE_ACCENT = [
    ('from-violet-600', 'to-indigo-600', 'border-violet-500/30', 'bg-violet-950/20', 'text-violet-300'),
    ('from-indigo-600', 'to-blue-600', 'border-indigo-500/30', 'bg-indigo-950/20', 'text-indigo-300'),
    ('from-purple-600', 'to-pink-600', 'border-purple-500/30', 'bg-purple-950/20', 'text-purple-300'),
    ('from-teal-600', 'to-emerald-600', 'border-teal-500/30', 'bg-teal-950/20', 'text-teal-300'),
    ('from-fuchsia-600', 'to-rose-600', 'border-fuchsia-500/30', 'bg-fuchsia-950/20', 'text-fuchsia-300'),
]


def _manual_edit_ready(state, exporter) -> bool:
    if state.operating_scope and not settings.paid_production_enabled:
        return False
    if (state.is_busy or not (settings.paid_production_enabled or state.prepared_narration_manifest) or not state.script
            or state.has_unapplied_script_draft() or not state.is_script_reviewed() or not state.manual_script_id):
        return False
    try:
        return exporter.all_clips_ready(state.script, state.manual_script_id)
    except (OSError, ValueError):
        return False


def _auto_edit_ready(state, verdicts) -> bool:
    if state.operating_scope and not settings.paid_production_enabled:
        return False
    return bool(state.script and not state.is_busy and not state.manual_video_mode and state.is_script_reviewed()
                and not state.has_unapplied_script_draft()
                and not state.has_unapplied_first_frame_drafts()
                and (settings.paid_production_enabled or state.prepared_narration_manifest)
                and all(verdicts.get(index) == 'approved' for index, scene in enumerate(state.script.scenes)
                        if scene_mode(state.mode, scene, index) == 'video'))


def _next_edit_step(state, verdicts) -> str:
    if state.is_busy:
        return '작업 진행 중 · 완료 또는 중지 결과를 기다려 주세요.'
    if state.operating_scope and not settings.paid_production_enabled:
        return '회차 실행은 API 활성화가 필요합니다. 무료 수동 편집은 회차 연결을 해제한 뒤 진행하세요.'
    if not state.script:
        return '다음: 대본·장면 검토에서 대본을 기획하거나 불러오세요.'
    if state.has_unapplied_script_draft():
        return '다음: 미적용 대본 수정을 적용하거나 되돌리세요. 이전 대본으로 제작하지 않습니다.'
    if not state.is_script_reviewed():
        return '다음: 대본·장면 검토에서 현재 각본 확인을 완료하세요.'
    if not settings.paid_production_enabled and not state.prepared_narration_manifest:
        return '다음: 기존 내레이션을 연결하거나 API 생성을 활성화하세요.'
    if state.manual_video_mode:
        return '보유 영상: 아래 장면별 파일 연결과 내레이션을 확인한 뒤 편집하세요.'
    if state.has_unapplied_first_frame_drafts():
        return '다음: 미적용 첫 프레임 후보·검토 입력을 승인하거나 되돌리세요.'
    indices = [index for index, scene in enumerate(state.script.scenes) if scene_mode(state.mode, scene, index) == 'video']
    approved = sum(verdicts.get(index) == 'approved' for index in indices)
    if approved < len(indices):
        return f'다음: 아래에서 첫 프레임·무음 원본을 검토하세요. Veo 원본 승인 {approved}/{len(indices)}장면'
    return '장면 검토 완료 · 제작 시작 시 음성·비주얼 비용과 파일을 다시 검사합니다.'


def render_first_frame_reviews(state: 'AppState', on_review_change=None) -> None:
    """Preview and bind locally supplied Veo first frames before a paid scene request."""
    if not state.script or state.manual_video_mode:
        return
    media_source = media_sources(ui.context.client)
    rendered_script = state.script.model_dump_json()
    draft_key = state.script_editor_key()
    video_scenes = [scene for index, scene in enumerate(state.script.scenes)
                    if scene_mode(state.mode, scene, index) == 'video']
    if not video_scenes:
        return
    approved_scenes = set()
    with ui.expansion('Veo 첫 프레임 검토', icon='image_search', value=True).classes(
        'w-full bg-slate-900 border border-amber-700/40 rounded-lg').props('dark') as review_group:
        ui.label('각 장면의 내레이션에 맞는 9:16 이미지를 미리 본 뒤 승인하세요. 승인 기록이 없으면 새 Veo 영상은 생성되지 않습니다.').classes(
            'text-xs text-amber-200')
        ui.label('출처: ' + ' · '.join([state.script.source_url, *state.script.supporting_source_urls])).classes(
            'text-xs text-slate-400 break-all')
        for scene in video_scenes:
            review_record = {}
            current_frame = None
            try:
                current_frame, _ = verified_first_frame(state.script, scene)
                review_record = json.loads(review_path(state.script, scene).read_text(encoding='utf-8'))
                approved_scenes.add(scene.scene_number)
            except (OSError, ValueError):
                current_frame = None
            verdict_label = '첫 프레임 승인됨' if current_frame else '첫 프레임 검토 필요'
            with ui.expansion(f'장면 {scene.scene_number} · {verdict_label}', value=not current_frame).classes(
                'w-full bg-slate-950 border border-slate-700 rounded-lg').props('dark') as scene_panel:
                ui.label(f'내레이션: {scene.script_text}').classes('text-sm text-slate-200')
                ui.label(f'화면: {scene.visual_description}').classes('text-xs text-slate-300')
                ui.label(f'움직임: {scene.motion_instruction or "고정 카메라"}').classes('text-xs text-slate-400')
                if current_frame:
                    status_label = ui.label(f'승인된 첫 프레임: {current_frame}').classes('text-xs text-teal-300 break-all')
                    ui.image(media_source(current_frame)).classes('w-full max-w-[180px]')
                else:
                    status_label = ui.label('첫 프레임 승인 대기').classes('text-xs text-amber-300')
                candidate, candidate_error = None, None
                try:
                    candidate = retained_candidate(state.script, scene)
                except ValueError as error:
                    candidate_error = str(error)
                candidate_notice = ui.label(candidate_error or '').classes('text-xs text-amber-200 break-all')
                candidate_notice.visible = bool(candidate_error)
                draft = state.first_frame_drafts.get(draft_key, {}).get(scene.scene_number, {})
                baseline = {'frame_path': review_record.get('frame_path') or candidate or '',
                            'must_show': '\n'.join(review_record.get('must_show', [])),
                            'must_avoid': '\n'.join(review_record.get('must_avoid', [])),
                            'reviewer_note': review_record.get('reviewer_note', '')}
                draft = {name: value for name, value in draft.items() if value != baseline.get(name)}
                if draft:
                    state.first_frame_drafts[draft_key][scene.scene_number] = draft
                else:
                    state.first_frame_drafts.get(draft_key, {}).pop(scene.scene_number, None)
                path_input = ui.input('첫 프레임 PNG/JPEG 경로', value=draft.get('frame_path', baseline['frame_path'])).classes('w-full').props('dark')
                must_show = ui.textarea('반드시 보여야 할 내용 (한 줄에 하나)', value=draft.get('must_show', baseline['must_show'])).classes('w-full').props('dark')
                must_avoid = ui.textarea('피해야 할 묘사 (한 줄에 하나)', value=draft.get('must_avoid', baseline['must_avoid'])).classes('w-full').props('dark')
                reviewer_note = ui.input('검토 의견', value=draft.get('reviewer_note', baseline['reviewer_note'])).classes('w-full').props('dark')
                inputs = {'frame_path': path_input, 'must_show': must_show, 'must_avoid': must_avoid,
                          'reviewer_note': reviewer_note}
                def remember_frame(field, number=scene.scene_number, fields=inputs, saved=baseline):
                    def remember(event):
                        if not state.is_busy and not fields[field].is_deleted and state.script_editor_key() == draft_key:
                            changed = {key: value.value or '' for key, value in fields.items()
                                       if (value.value or '') != saved[key]}
                            drafts = state.first_frame_drafts.setdefault(draft_key, {})
                            if changed:
                                drafts[number] = changed
                            else:
                                drafts.pop(number, None)
                    return remember
                for field, name in ((path_input, 'frame_path'), (must_show, 'must_show'),
                                    (must_avoid, 'must_avoid'), (reviewer_note, 'reviewer_note')):
                    field.on_value_change(remember_frame(name))
                for field in (path_input, must_show, must_avoid, reviewer_note):
                    field.bind_enabled_from(state, 'is_busy', lambda busy: not busy)
                preview_area = ui.column().classes('w-full')
                previewed = {'path': None, 'sha256': None}

                def preview(frame_input=path_input, area=preview_area, snapshot=previewed):
                    try:
                        path = str(Path(frame_input.value or '').resolve())
                        digest = inspect_frame(path)
                        snapshot.update(path=path, sha256=digest)
                        area.clear()
                        with area:
                            ui.image(media_source(path)).classes('w-full max-w-[230px] max-h-[410px]')
                        safe_notify('이미지를 확인한 뒤 기준과 의견을 적어 승인하세요.', type='info')
                    except (OSError, ValueError) as error:
                        snapshot.update(path=None, sha256=None)
                        safe_notify(f'첫 프레임 미리보기 실패: {error}', type='negative')

                async def pick_image(frame_input=path_input, bound_preview=preview, expected_mode=state.mode):
                    def current():
                        return (not frame_input.is_deleted and not state.is_busy and not state.manual_video_mode and state.mode == expected_mode
                                and state.script is not None and state.script.model_dump_json() == rendered_script)

                    def select(path):
                        inspect_frame(path)
                        frame_input.value = path
                        bound_preview()

                    await open_image_picker(select, current)

                ui.button('보관함에서 이미지 찾기', on_click=pick_image).props('outline icon=folder_open').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy)
                ui.label('후보 경로와 검토 입력은 메뉴 이동 시 유지됩니다. 재시작 전에 검토 입력 초안 저장으로 보관할 수 있습니다. 승인은 검토를 마친 뒤에만 진행하세요.').classes('text-xs text-slate-400')

                def save_frame_draft():
                    try:
                        if state.script_editor_key() != draft_key:
                            raise ValueError('대본이 바뀌었습니다. 현재 화면을 다시 확인하세요.')
                        path = state.save_work_draft()
                        safe_notify(f'검토 입력을 작업 초안으로 저장했습니다: {path.name}. 대본·장면 검토에서 복원할 수 있습니다.', type='positive')
                    except (ValueError, OSError) as error:
                        safe_notify(f'초안 저장 중단: {error}', type='warning')

                ui.button('검토 입력 초안 저장', on_click=save_frame_draft).props('flat icon=save').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy)

                def discard_frame(fields=inputs, saved=baseline, area=preview_area, snapshot=previewed, number=scene.scene_number):
                    if state.is_busy or state.script_editor_key() != draft_key or any(field.is_deleted for field in fields.values()):
                        return
                    for key, field in fields.items():
                        field.value = saved[key]
                    state.first_frame_drafts.get(draft_key, {}).pop(number, None)
                    snapshot.update(path=None, sha256=None)
                    area.clear()

                ui.button('첫 프레임 검토 입력 되돌리기', on_click=discard_frame).props('flat').bind_enabled_from(
                    state, 'is_busy', lambda busy, number=scene.scene_number:
                    not busy and state.has_unapplied_first_frame_draft(number))

                def approve(scene_number=scene.scene_number, frame_input=path_input,
                            show_input=must_show, avoid_input=must_avoid,
                            note_input=reviewer_note, snapshot=previewed, status=status_label,
                            expected_script=rendered_script, panel=scene_panel, fields=inputs, saved=baseline):
                    if not state.script or state.script.model_dump_json() != expected_script:
                        safe_notify('각본이 변경됐습니다. 장면·영상 제작 화면을 다시 열어 주세요.', type='warning')
                        return
                    if state.is_busy:
                        safe_notify('진행 중인 제작·업로드가 끝난 뒤 첫 프레임을 승인하세요.', type='warning')
                        return
                    if not state.is_script_reviewed():
                        safe_notify('현재 각본을 기획 탭에서 먼저 확인하세요.', type='warning')
                        return
                    current = next((item for item in state.script.scenes
                                    if item.scene_number == scene_number), None)
                    if current is None or not snapshot['sha256'] or snapshot['path'] != str(
                        Path(frame_input.value or '').resolve()
                    ):
                        safe_notify('현재 이미지를 다시 미리보세요.', type='warning')
                        return
                    try:
                        approve_first_frame(
                            state.script, current, snapshot['path'],
                            [line.strip() for line in (show_input.value or '').splitlines() if line.strip()],
                            [line.strip() for line in (avoid_input.value or '').splitlines() if line.strip()],
                            note_input.value or '', snapshot['sha256'],
                        )
                        saved.update({key: field.value or '' for key, field in fields.items()})
                        state.first_frame_drafts.get(draft_key, {}).pop(scene_number, None)
                        status.text = f'승인된 첫 프레임: {snapshot["path"]}'
                        status.classes(replace='text-xs text-teal-300 break-all')
                        approved_scenes.add(scene_number)
                        panel.text = f'장면 {scene_number} · 첫 프레임 승인됨'
                        review_group.text = f'Veo 첫 프레임 검토 · 승인 {len(approved_scenes)}/{len(video_scenes)}'
                        if on_review_change:
                            on_review_change()
                        safe_notify(f'장면 {scene_number}의 첫 프레임을 승인했습니다.', type='positive')
                    except (OSError, ValueError) as error:
                        safe_notify(f'첫 프레임 승인 실패: {error}', type='negative')

                def refresh_candidate(current_scene=scene, frame_input=path_input, bound_preview=preview,
                                      notice=candidate_notice):
                    if state.is_busy or not state.script or state.script.model_dump_json() != rendered_script:
                        return
                    try:
                        saved = retained_candidate(state.script, current_scene)
                        if saved:
                            notice.visible = False
                            frame_input.value = saved
                            bound_preview()
                        else:
                            safe_notify('저장된 첫 프레임 후보가 없습니다.', type='info')
                    except (OSError, ValueError) as error:
                        notice.text, notice.visible = str(error), True
                        safe_notify(str(error), type='negative')

                estimate = estimated_scene_cost('image', settings.image_model_id)
                generation = {'done': bool(current_frame or candidate or candidate_error)}

                async def generate_frame(index=state.script.scenes.index(scene), frame_input=path_input,
                                         bound_preview=preview, ceiling=estimate, request=generation,
                                         expected_mode=state.mode, expected_execution=state.execution_key()):
                    if (state.is_busy or state.manual_video_mode or state.mode != expected_mode
                            or not state.script or state.script.model_dump_json() != rendered_script):
                        safe_notify('작업 중이거나 각본·제작 방식이 변경됐습니다. 현재 제작 화면을 다시 확인하세요.', type='warning')
                        return
                    if not state.is_script_reviewed() or not settings.paid_production_enabled:
                        safe_notify('현재 각본 확인과 API 생성 활성화가 필요합니다.', type='warning')
                        return
                    if state.has_unapplied_script_draft():
                        safe_notify('먼저 미적용 대본 수정을 적용하거나 되돌리세요.', type='warning')
                        return
                    try:
                        state.require_execution_context(expected_execution)
                    except (OSError, ValueError, RuntimeError) as error:
                        safe_notify(str(error), type='warning')
                        return
                    state.pipeline_running = True
                    try:
                        service = state.new_production_service()
                        saved = await service.generate_first_frame(state.script, index, request_budget_usd=ceiling)
                        request['done'] = True
                        if service.is_cancelled():
                            safe_notify('첫 프레임 요청 결과는 저장됐지만 취소되어 자동 선택하지 않았습니다.', type='warning')
                            return
                        safe_notify('첫 프레임 후보 저장 완료 · 내용을 검토한 뒤 별도로 승인하세요.', type='positive')
                        if state.script and state.script.model_dump_json() == rendered_script:
                            try:
                                frame_input.value = saved
                                bound_preview()
                            except RuntimeError:
                                pass
                    except Exception as error:
                        safe_notify(f'첫 프레임 생성 중단: {error}', type='negative')
                    finally:
                        state.pipeline_running = False

                ui.label(f'후보 이미지 · {settings.image_model_id} · 출력 예약 추정 ${estimate:.3f} · 장면당 1회, 자동 재시도 없음').classes('text-xs text-slate-400')
                ui.button('첫 프레임 후보 생성', on_click=generate_frame).props('color=amber').bind_enabled_from(
                    state, 'is_busy', lambda busy, request=generation:
                    not busy and not request['done'] and settings.paid_production_enabled and state.is_script_reviewed()
                    and not state.has_unapplied_script_draft())
                ui.label('생성 결과는 자동 승인되지 않습니다. 메뉴 이동 후에는 후보 새로고침으로 이어가세요. 새 후보가 필요하면 장면 설명을 수정한 새 대본에서 진행하세요.').classes('text-xs text-slate-400')
                ui.button('첫 프레임 후보 새로고침', on_click=refresh_candidate).props('flat').bind_enabled_from(state, 'is_busy', lambda busy: not busy)

                with ui.row():
                    ui.button('이미지 미리보기', on_click=preview).props('flat color=amber')
                    ui.button('이 첫 프레임 승인', on_click=approve).props('color=teal').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
        review_group.text = f'Veo 첫 프레임 검토 · 승인 {len(approved_scenes)}/{len(video_scenes)}'


def render_raw_clip_reviews(state: 'AppState') -> dict:
    """Generate and judge one muted Veo scene before the whole-cut production run."""
    media_source = media_sources(ui.context.client)
    if not state.script or state.manual_video_mode:
        return {}
    rendered_script = state.script.model_dump_json()
    video_indices = [index for index, scene in enumerate(state.script.scenes)
                     if scene_mode(state.mode, scene, index) == 'video']
    if not video_indices:
        return {}
    verdicts = {}
    with ui.expansion('Veo 무음 원본 검토', icon='movie_filter', value=True).classes(
        'w-full bg-slate-900 border border-teal-700/40 rounded-lg').props('dark') as review_group:
        ui.label('원본을 소리 없이 끝까지 보고 이야기의 의미와 움직임을 판정하세요. 승인 전에는 전체 편집으로 넘어가지 않습니다.').classes(
            'text-xs text-teal-200')
        for index in video_indices:
            scene = state.script.scenes[index]
            with ui.expansion(f'장면 {scene.scene_number} · 원본 확인 중', value=True).classes(
                'w-full bg-slate-950 border border-slate-700 rounded-lg').props('dark') as scene_panel:
                ui.label(f'내레이션: {scene.script_text}').classes('text-sm text-white')
                criteria_area = ui.column().classes('w-full')
                service = state.get_or_create_service()
                model, duration = service.video_spec()
                reserve = service.max_veo_attempts * estimated_scene_cost('video', model, duration)
                cost_label = ui.label(f'새 원본 요청: {model} · {duration}초 · 예약 추정 ${reserve:.3f}').classes(
                    'text-xs text-amber-200')
                status = ui.label('첫 프레임 승인 후 원본을 생성하세요.').classes('text-xs text-slate-300')
                preview_area = ui.column().classes('w-full')
                note = ui.input('원본 판정 의견').classes('w-full').props('dark')
                displayed_frame = {'sha256': None}
                request_label = cost_label.text
                request_state = {'allowed': False, 'button': None}

                def refresh(scene_index=index, label=status, area=preview_area,
                            criteria_display=criteria_area, note_input=note, cost=cost_label,
                            shown=displayed_frame, new_request_label=request_label,
                            expected_script=rendered_script, panel=scene_panel, request=request_state,
                            scene_number=scene.scene_number):
                    area.clear()
                    criteria_display.clear()
                    shown['sha256'] = None
                    note_input.value = ''
                    request['allowed'] = False
                    verdicts[scene_index] = 'pending'
                    review_group.text = f'Veo 무음 원본 검토 · 승인 {sum(v == "approved" for v in verdicts.values())}/{len(video_indices)}'
                    cost.text = new_request_label
                    if not state.script or state.script.model_dump_json() != expected_script:
                        label.text = '각본이 변경됐습니다. 장면·영상 제작 화면을 다시 열어 주세요.'
                        panel.text = f'장면 {scene_number} · 화면 다시 열기 필요'
                        return
                    try:
                        clip, frame_hash = state.get_or_create_service().review_clip_path(state.script, scene_index)
                        criteria = json.loads(review_path(state.script, state.script.scenes[scene_index]).read_text(encoding='utf-8'))
                    except (OSError, ValueError, KeyError, TypeError) as error:
                        if str(error).startswith('FIRST_FRAME_REVIEW_REQUIRED:'):
                            label.text = '위에서 첫 프레임을 승인하면 무음 원본을 생성할 수 있습니다.'
                            panel.text = f'장면 {scene_number} · 첫 프레임 승인 대기'
                        else:
                            label.text = f'원본 검토 중단: {error}'
                            panel.text = f'장면 {scene_number} · 첫 프레임·요청 기록 확인 필요'
                        return
                    shown['sha256'] = frame_hash
                    with criteria_display:
                        ui.label('보여야 할 내용: ' + ' · '.join(criteria['must_show'])).classes('text-xs text-slate-200')
                        ui.label('피해야 할 묘사: ' + ' · '.join(criteria['must_avoid'])).classes('text-xs text-slate-300')
                    if not clip:
                        label.text = '무음 원본 생성 대기'
                        panel.text = f'장면 {scene_number} · 원본 생성 필요'
                        request['button'].text = '이 장면 Veo 원본 생성'
                        request['allowed'] = settings.paid_production_enabled
                        return
                    cost.text = '저장된 무음 원본 재사용 · 새 API 요청 없음'
                    verdict = raw_review_status(state.script, state.script.scenes[scene_index], clip, frame_hash)
                    verdicts[scene_index] = verdict
                    review_group.text = f'Veo 무음 원본 검토 · 승인 {sum(v == "approved" for v in verdicts.values())}/{len(video_indices)}'
                    label.text = {'approved': '무음 원본 승인됨', 'rejected': '무음 원본 제외됨 · 새 첫 프레임 또는 장면 설명 필요',
                                  'stale': '원본 판정 무효 · 변경된 파일 확인 필요'}.get(verdict, '무음 원본 판정 대기')
                    panel.text = f'장면 {scene_number} · ' + {
                        'approved': '무음 원본 승인됨', 'rejected': '원본 제외 · 수정 필요',
                        'stale': '판정 무효 · 재검토 필요',
                    }.get(verdict, '원본 판정 필요')
                    panel.value = verdict != 'approved'
                    request['button'].text = '저장된 원본 다시 확인'
                    request['allowed'] = True
                    if verdict in {'approved', 'rejected'}:
                        try:
                            note_input.value = load_raw_verdict(
                                state.script, state.script.scenes[scene_index], clip, frame_hash,
                            )['reviewer_note']
                        except (OSError, ValueError, KeyError, TypeError):
                            label.text = '원본 판정 기록을 다시 확인하세요.'
                            verdicts[scene_index] = 'pending'
                            review_group.text = f'Veo 무음 원본 검토 · 승인 {sum(v == "approved" for v in verdicts.values())}/{len(video_indices)}'
                            panel.text = f'장면 {scene_number} · 판정 기록 확인 필요'
                            panel.value = True
                    with area:
                        ui.video(media_source(clip)).props('controls muted').classes('w-full max-w-[230px]')

                async def generate(scene_index=index, update=refresh, request_cap=reserve,
                                   shown=displayed_frame, expected_script=rendered_script, expected_mode=state.mode,
                                   expected_execution=state.execution_key()):
                    if (state.manual_video_mode or state.mode != expected_mode
                            or not state.script or state.script.model_dump_json() != expected_script):
                        safe_notify('각본·제작 방식이 변경됐습니다. 장면·영상 제작 화면을 다시 열어 주세요.', type='warning')
                        return
                    if not state.is_script_reviewed() or state.is_busy:
                        safe_notify('현재 각본 검토를 완료하고 다른 제작이 끝난 뒤 진행하세요.', type='warning')
                        return
                    if state.has_unapplied_script_draft():
                        safe_notify('먼저 미적용 대본 수정을 적용하거나 되돌리세요.', type='warning')
                        return
                    if state.has_unapplied_first_frame_draft(state.script.scenes[scene_index].scene_number):
                        safe_notify('첫 프레임 후보·검토 입력을 승인하거나 되돌린 뒤 원본을 생성하세요.', type='warning')
                        return
                    if not shown['sha256']:
                        try:
                            update()
                        except RuntimeError:
                            pass
                        safe_notify('현재 첫 프레임과 요청 비용을 확인한 뒤 다시 진행하세요.', type='warning')
                        return
                    try:
                        state.require_execution_context(expected_execution)
                        service = state.get_or_create_service()
                        state.pipeline_running = True
                        clip = await service.generate_review_clip(
                            state.script, scene_index, request_budget_usd=request_cap,
                            expected_frame_sha256=shown['sha256'],
                        )
                        safe_notify(f'무음 원본을 저장했습니다: {clip}', type='positive')
                        try:
                            update()
                        except RuntimeError:
                            pass
                    except Exception as error:
                        try:
                            update()
                        except RuntimeError:
                            pass
                        logger.error('Veo 원본 생성 실패: %s', error)
                        safe_notify(f'원본 생성 중단: {error}', type='negative')
                    finally:
                        state.pipeline_running = False

                def decide(decision, scene_index=index, note_input=note, update=refresh,
                           expected_script=rendered_script):
                    if not state.script or state.script.model_dump_json() != expected_script:
                        safe_notify('각본이 변경됐습니다. 장면·영상 제작 화면을 다시 열어 주세요.', type='warning')
                        return
                    if state.is_busy:
                        safe_notify('진행 중인 제작·업로드가 끝난 뒤 원본을 판정하세요.', type='warning')
                        return
                    if not state.is_script_reviewed() or not note_input.value:
                        safe_notify('현재 각본과 원본을 확인하고 판정 의견을 적어 주세요.', type='warning')
                        return
                    try:
                        clip, frame_hash = state.get_or_create_service().review_clip_path(state.script, scene_index)
                        if not clip:
                            raise ValueError('검토할 무음 원본이 없습니다.')
                        save_raw_verdict(state.script, state.script.scenes[scene_index], clip,
                                         frame_hash, decision, note_input.value)
                        update()
                        safe_notify('무음 원본 판정을 저장했습니다.', type='positive')
                    except (OSError, ValueError) as error:
                        safe_notify(f'원본 판정 실패: {error}', type='negative')

                with ui.row():
                    request_state['button'] = ui.button('이 장면 Veo 원본 생성', on_click=generate).props('color=amber').bind_enabled_from(
                    state, 'is_busy', lambda busy, request=request_state, number=scene.scene_number:
                        not busy and request['allowed'] and not state.has_unapplied_script_draft()
                        and not state.has_unapplied_first_frame_draft(number))
                    ui.button('원본 승인', on_click=lambda callback=decide: callback('approved')).props('color=teal').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
                    ui.button('원본 제외', on_click=lambda callback=decide: callback('rejected')).props('flat color=red').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
                refresh()
        if not settings.paid_production_enabled:
            ui.label('검토 모드: 새 원본 생성은 중지되어 있습니다. 저장된 원본 재생·판정은 가능합니다.').classes('text-xs text-amber-200')
    return verdicts


def render_manual_panel(state: 'AppState', exporter: VeoPromptExporter,
                        start_edit_btn: ui.button,
                        scene_cards_container: ui.element) -> None:
    """수동 모드 격자 그리드 씬 업로드 패널 렌더링"""
    media_source = media_sources(ui.context.client)
    try:
        scene_cards_container.clear()
    except RuntimeError:
        return

    # 스크립트 없을 때 처리
    if not state.script:
        start_edit_btn.disable()
        with scene_cards_container:
            with ui.element('div').classes('w-full h-96 flex items-center justify-center col-span-full'):
                with ui.column().classes('items-center gap-4'):
                    ui.icon('description', size='xl').classes('text-slate-600')
                    ui.label('각본을 먼저 로드해주세요').classes('text-lg font-bold text-slate-400')
                    ui.label('제작 작업실 → 1. 대본·장면 검토에서 각본을 만들거나 불러오세요.').classes('text-xs text-slate-500')
        return

    if not state.manual_script_id:
        try:
            state.manual_script_id = exporter.create_workspace(state.script)
        except (OSError, ValueError) as error:
            start_edit_btn.disable()
            with scene_cards_container:
                ui.label(f'보유 영상 작업을 준비할 수 없습니다: {error}').classes('text-amber-200')
            return

    try:
        scenes_status = exporter.get_scenes_status(state.script, state.manual_script_id)
        workspaces = exporter.list_workspaces(state.script)
    except (OSError, ValueError) as error:
        start_edit_btn.disable()
        with scene_cards_container:
            ui.label(f'보유 영상 작업 기록을 확인하세요: {error}').classes('text-amber-200')
        return
    ready_count = sum(1 for s in scenes_status if s["exists"])
    total = len(scenes_status)
    if _manual_edit_ready(state, exporter):
        start_edit_btn.enable()
    else:
        start_edit_btn.disable()

    with scene_cards_container:
        import_status = ui.label('선택한 영상을 확인·저장하는 중입니다. 완료 전에는 기존 클립을 사용합니다.').classes(
            'col-span-full text-sm text-amber-200').bind_visibility_from(state, 'media_import_in_progress')
        if not settings.paid_production_enabled and not state.prepared_narration_manifest:
            ui.label('검토 모드: 클립 연결·복원·재생은 가능합니다. 기존 내레이션을 연결하면 새 음성 없이 편집할 수 있습니다.').classes(
                'col-span-full w-full p-3 border border-amber-700/40 rounded-lg text-sm text-amber-200')
        workspaces.pop(state.manual_script_id, None)
        if workspaces:
            with ui.column().classes('col-span-full w-full p-4 bg-slate-900 border border-slate-700 rounded-lg'):
                ui.label('이 대본으로 연결했던 영상 작업 이어가기').classes('text-sm text-white')
                workspace_select = ui.select(workspaces, label='저장된 보유 영상 작업', with_input=True).classes('w-full').props('outlined dark')
                rendered_script = state.script.model_dump_json()

                def restore_workspace():
                    if not state.script or state.script.model_dump_json() != rendered_script:
                        safe_notify('대본이 변경됐습니다. 장면·영상 제작 화면을 다시 열어 주세요.', type='warning')
                        return
                    try:
                        state.restore_manual_workspace(workspace_select.value or '')
                        render_manual_panel(state, exporter, start_edit_btn, scene_cards_container)
                        safe_notify('연결한 영상 작업을 복원했습니다. 장면을 재생해 확인하세요.', type='positive')
                    except (OSError, ValueError) as error:
                        safe_notify(f'작업 복원 실패: {error}', type='negative')

                ui.button('선택한 작업 이어가기', on_click=restore_workspace).props('icon=restore color=teal').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy)
                ui.label('현재 대본과 정확히 일치하는 기록만 표시합니다. 복원은 파일 연결이며 품질 승인·유료 실행 승인이 아닙니다.').classes('text-xs text-slate-400')

        # ── 상단 진행 정보 (Grid의 가로 한 줄 전체 차지) ──
        with ui.element('div').classes('col-span-full w-full rounded-xl bg-slate-900 border border-slate-800 p-5 mb-2'):
            with ui.row().classes('w-full items-center justify-between mb-3'):
                with ui.row().classes('items-center gap-3'):
                    ui.icon('video_library', size='sm').classes('text-violet-400')
                    ui.label('수동 소스 매핑 및 영상 수집').classes('text-base font-bold text-white')

                # 진행도 표시 뱃지
                progress_badge_cls = 'bg-violet-600 text-white font-bold px-3 py-1 rounded-full text-xs' \
                    if ready_count == total else 'bg-slate-800 text-slate-400 font-bold px-3 py-1 rounded-full text-xs border border-slate-700'
                ui.badge(f'{ready_count} / {total} 장면 연결됨').classes(progress_badge_cls)

            # 전체 진행 바
            with ui.element('div').classes('w-full h-2 rounded-full bg-slate-800 overflow-hidden mb-4'):
                pct = int(ready_count / max(total, 1) * 100)
                bar_color = 'bg-gradient-to-r from-violet-600 to-indigo-600' if ready_count == total else 'bg-violet-600'
                ui.element('div').classes(f'h-full rounded-full {bar_color} transition-all').style(f'width: {pct}%')

            # 안내 가이드 및 일괄 다운로드/복사 도구
            with ui.row().classes('w-full items-stretch gap-4'):
                with ui.element('div').classes('flex-grow rounded-lg bg-violet-950/20 border border-violet-500/20 p-3 flex items-start gap-2'):
                    ui.icon('info', size='xs').classes('text-violet-400 mt-0.5 shrink-0')
                    ui.label('기존 장면 영상 찾기에서 저장된 작업이나 승인 원본을 재사용하거나, 장면 카드에서 보유 파일을 선택하세요. 모든 장면을 연결한 뒤 내레이션·음악·자막을 편집합니다.').classes('text-xs text-slate-300 leading-relaxed')

                with ui.column().classes('justify-center gap-2 w-full sm:w-auto sm:min-w-[240px] sm:border-l border-slate-800 sm:pl-4'):
                    def copy_all_json():
                        json_str = exporter.export_json(state.script, state.manual_script_id)
                        ui.run_javascript(f'navigator.clipboard.writeText({json.dumps(json_str)})')
                        safe_notify('전체 프롬프트 JSON이 클립보드에 복사되었습니다.', type='positive')

                    ui.button(
                        '전체 프롬프트 JSON 복사',
                        icon='content_copy',
                        on_click=copy_all_json
                    ).classes('w-full py-1 text-xs').props('outline color=violet dense size=sm')

        # ── 씬별 카드 (Grid 구조로 각 씬이 격자 배치됨) ──
        for idx, scene_info in enumerate(scenes_status):
            scene_num = scene_info["scene_number"]
            exists = scene_info["exists"]
            prompt = scene_info["prompt"]
            script_text = scene_info["script_text"]

            from_c, to_c, border_c, bg_c, label_c = SCENE_ACCENT[idx % len(SCENE_ACCENT)]
            card_border = 'border-violet-500/50' if exists else 'border-slate-800 hover:border-slate-700'
            card_bg = 'bg-slate-900/80 shadow-md' if exists else 'bg-slate-900/40 hover:bg-slate-900/60'

            with ui.element('div').classes(f'rounded-xl border {card_border} {card_bg} overflow-hidden flex flex-col justify-between transition-all duration-300'):

                # 씬 헤더
                with ui.element('div').classes(f'w-full px-4 py-2.5 bg-gradient-to-r {from_c} {to_c} opacity-90 flex items-center justify-between shrink-0'):
                    with ui.row().classes('items-center gap-2'):
                        with ui.element('div').classes('w-6 h-6 rounded bg-white/20 flex items-center justify-center'):
                            ui.label(str(scene_num)).classes('text-xs font-bold text-white')
                        ui.label(f'씬 {scene_num}').classes('text-xs font-bold text-white')

                    if exists:
                        with ui.row().classes('items-center gap-1 bg-white/20 rounded-full px-2 py-0.5'):
                            ui.icon('check', size='xs').classes('text-white')
                            ui.label('파일 연결됨').classes('text-[10px] text-white font-semibold')
                    else:
                        ui.label('대기').classes('text-[10px] text-white/70 font-semibold bg-white/10 px-2 py-0.5 rounded-full')

                # 카드 바디
                with ui.column().classes('p-4 gap-3 flex-grow'):
                    # 1. 오디오 자막 (내레이션)
                    with ui.column().classes('w-full gap-1'):
                        ui.label('나레이션').classes('text-[10px] text-slate-500 font-bold uppercase tracking-wider')
                        with ui.element('div').classes('w-full rounded-lg bg-slate-950/60 border border-slate-800/80 px-3 py-2 min-h-[50px]'):
                            ui.label(script_text).classes('text-xs text-slate-300 leading-relaxed italic')

                    # 2. 비주얼 프롬프트 복사
                    with ui.column().classes('w-full gap-1'):
                        ui.label('비주얼 프롬프트').classes('text-[10px] text-slate-500 font-bold uppercase tracking-wider')
                        with ui.element('div').classes('w-full rounded-lg bg-slate-950/80 border border-slate-800 p-2.5 min-h-[60px] max-h-[100px] overflow-y-auto font-mono'):
                            ui.label(prompt).classes('text-[11px] text-slate-400 leading-normal')

                        def make_copy_fn(p=prompt, sn=scene_num):
                            def copy_prompt():
                                ui.run_javascript(f'navigator.clipboard.writeText({json.dumps(p)})')
                                safe_notify(f'씬 {sn} 프롬프트 복사 완료!', type='info')
                            return copy_prompt

                        ui.button(
                            '프롬프트 복사',
                            icon='content_copy',
                            on_click=make_copy_fn()
                        ).classes('w-full py-0.5 text-xs mt-1').props('flat dense color=violet size=xs')

                    # 3. 비디오 클립 업로드
                    with ui.column().classes('w-full gap-1 mt-1'):
                        ui.label('비디오 파일 매핑').classes('text-[10px] text-slate-500 font-bold uppercase tracking-wider')
                        error_key = f'{state.manual_script_id}:{scene_num}'
                        import_error = ui.label().classes('text-xs text-amber-200 break-all').bind_text_from(
                            state, 'manual_clip_errors', backward=lambda errors, key=error_key: errors.get(key, ''))

                        # 업로드 완료된 클립명 표시
                        if exists:
                            clip_name = scene_info["clip_path"].split('/')[-1]
                            ui.video(media_source(scene_info['clip_path'])).props('controls muted').classes('w-full max-h-[240px] bg-black')
                            with ui.element('div').classes('w-full rounded-lg bg-violet-950/20 border border-violet-500/20 px-2 py-1.5 flex items-center justify-between mb-1.5'):
                                with ui.row().classes('items-center gap-1.5 overflow-hidden'):
                                    ui.icon('video_file', size='xs').classes('text-violet-400 shrink-0')
                                    ui.label(clip_name).classes('text-[11px] text-violet-300 truncate max-w-[180px]')
                                ui.icon('check_circle', size='xs').classes('text-violet-400')

                        # 업로드 컴포넌트
                        def make_upload_handler(sn=scene_num):
                            bound_script = state.script.model_dump_json()
                            bound_script_id = state.manual_script_id
                            bound_execution = state.execution_key()

                            async def handle_upload(e):
                                import asyncio
                                job = None
                                owns_import = False
                                committed = False
                                try:
                                    if state.is_busy or not state.manual_video_mode:
                                        safe_notify('진행 중인 제작·업로드가 끝난 뒤 클립을 추가하세요.', type='warning')
                                        return
                                    file_bytes = await e.file.read()
                                    if (state.is_busy or not state.script
                                            or not state.manual_video_mode or state.execution_key() != bound_execution
                                            or state.script.model_dump_json() != bound_script
                                            or state.manual_script_id != bound_script_id):
                                        safe_notify('각본이나 작업 상태가 변경됐습니다. 현재 장면에서 파일을 다시 선택하세요.', type='warning')
                                        return
                                    state.media_import_in_progress = True
                                    owns_import = True
                                    state.manual_clip_errors = {key: value for key, value in state.manual_clip_errors.items()
                                                               if key != f'{bound_script_id}:{sn}'}
                                    job = asyncio.create_task(asyncio.to_thread(exporter.save_uploaded_clip, file_bytes, bound_script_id, sn))
                                    cancelled = False
                                    # Keep the editing lock until the atomic save settles, even after task cancellation.
                                    while not job.done():
                                        try:
                                            await asyncio.shield(job)
                                        except asyncio.CancelledError:
                                            cancelled = True
                                        except Exception:
                                            break
                                    committed = not job.cancelled() and job.exception() is None
                                    if cancelled:
                                        raise asyncio.CancelledError
                                    job.result()
                                    state.media_import_in_progress = False
                                    state.invalidate_video_result()
                                    committed = False

                                    safe_notify(f'장면 {sn} 영상 연결 완료!', type='positive')

                                    # 전체 패널 다시 그리기
                                    try:
                                        render_manual_panel(state, exporter, start_edit_btn, scene_cards_container)
                                    except RuntimeError:
                                        pass  # A deleted view cannot turn a completed save into an import failure.
                                    if exporter.all_clips_ready(state.script, state.manual_script_id):
                                        safe_notify('🎉 모든 씬의 영상 매핑 완료! 상단의 [편집 및 자막 믹싱 시작]을 실행하십시오.', type='positive')
                                except Exception as err:
                                    state.manual_clip_errors = {**state.manual_clip_errors, f'{bound_script_id}:{sn}': str(err)}
                                    safe_notify(f'업로드 실패: {err}', type='negative')
                                    logger.error(f'씬 {sn} 수동 로드 오류: {err}')
                                finally:
                                    if owns_import:
                                        state.media_import_in_progress = False
                                        if committed:
                                            state.invalidate_video_result()
                                    sender = getattr(e, 'sender', None)
                                    if sender is not None and not sender.is_deleted:
                                        try:
                                            sender.reset()
                                        except RuntimeError:
                                            pass
                            return handle_upload

                        upload_handler = make_upload_handler()
                        async def pick_existing(sn=scene_num, handler=upload_handler, anchor=import_error,
                                                expected_script=state.script.model_dump_json(),
                                                expected_workspace=state.manual_script_id, expected_execution=state.execution_key()):
                            def current():
                                return (not anchor.is_deleted and not state.is_busy and state.manual_video_mode and state.script
                                        and state.script.model_dump_json() == expected_script
                                        and state.manual_script_id == expected_workspace and state.execution_key() == expected_execution)
                            if current():
                                await open_existing_scene_picker(state.script, sn, state.get_or_create_service(), expected_workspace, handler, current)
                        ui.button('기존 장면 영상 찾기', on_click=pick_existing).props('outline icon=video_library').classes(
                            'w-full min-h-[44px]').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
                        ui.upload(
                            on_upload=upload_handler,
                            auto_upload=True,
                            max_file_size=MAX_MANUAL_CLIP_BYTES,
                        ).props('accept=".mp4,.mov,.webm" flat color=violet dense label="비디오 선택 (mp4, mov)"').classes('w-full border border-dashed border-slate-700 rounded-lg hover:border-violet-500/50 bg-slate-950/20 py-1')

    if state.media_import_in_progress:
        expected_script, expected_workspace = state.script.model_dump_json(), state.manual_script_id
        def finish_import():
            if (import_status.is_deleted or not state.script or state.script.model_dump_json() != expected_script
                    or state.manual_script_id != expected_workspace or not state.manual_video_mode):
                recovery.cancel()
            elif not state.media_import_in_progress:
                recovery.cancel()
                render_manual_panel(state, exporter, start_edit_btn, scene_cards_container)
        recovery = ui.timer(.1, finish_import)


def render_generation_tab(state: 'AppState') -> None:
    """Google AI Studio 스타일의 리팩토링된 Generation 탭 렌더링"""
    exporter = VeoPromptExporter()
    media_source = media_sources(ui.context.client)
    rendered_script = state.script.model_dump_json() if state.script else None
    raw_readiness = {'verdicts': {}}

    # 세션 뷰에 필요한 헬퍼
    phase_labels = {}
    phases = ['ready', 'visuals', 'editing', 'complete']

    def update_progress_ui(phase: str, progress: float, message: str = ""):
        try:
            for p, label in phase_labels.items():
                if p == phase:
                    label.classes(replace='text-violet-400 font-bold')
                elif phases.index(p) < phases.index(phase):
                    label.classes(replace='text-emerald-400')
                else:
                    label.classes(replace='text-slate-600')
        except (ValueError, RuntimeError) as e:
            logger.debug(f"Progress UI sync skipped: {e}")

    # 전체를 아우르는 반응형 컬럼 구조
    with ui.column().classes('w-full gap-0 bg-slate-950'):

        narration_panel = render_narration_panel(state)

        # ── 1. TOP PIPELINE ACTION BAR ──
        with ui.element('div').classes('w-full px-4 lg:px-6 py-4 bg-slate-900 border-b border-slate-800 flex flex-wrap items-center justify-between shrink-0 gap-4'):
            with ui.row().classes('items-center gap-3'):
                ui.icon('smart_display', size='sm').classes('text-violet-400')
                with ui.column().classes('gap-0'):
                    ui.label('영상 프로덕션 모니터').classes('text-sm font-bold text-white')
                    source_label = '보유 영상 연결 → 음성·자막 편집' if state.manual_video_mode else '첫 프레임 → 무음 원본 → 음성·자막 편집'
                    ui.label(source_label).classes('text-[11px] text-slate-300 mt-0.5')
                    ui.label().bind_text_from(state, 'is_busy',
                        backward=lambda _: _next_edit_step(state, raw_readiness['verdicts'])).classes('text-xs text-amber-200')

            # 파이프라인 진행 상태 (자동 / 수동 겸용 액션 바)
            with ui.row().classes('items-center gap-4'):

                # 수동 모드 전용 편집 시작 버튼
                async def run_manual_production():
                    if (state.is_busy or not state.script
                            or state.script.model_dump_json() != rendered_script):
                        safe_notify('작업 중이거나 각본이 변경됐습니다. 현재 장면·영상 제작 화면을 확인하세요.', type='warning')
                        return
                    clip_paths = (
                        exporter.get_ready_clip_paths(state.script, state.manual_script_id)
                        if state.script else None
                    )
                    if not clip_paths:
                        safe_notify('먼저 아래 격자 패널에서 모든 씬의 영상을 업로드해주십시오.', type='warning')
                        return
                    await run_production_with_clips(clip_paths)

                manual_btn = ui.button(
                    '편집 및 자막 믹싱 시작',
                    on_click=run_manual_production
                ).classes('px-4 py-1.5 font-bold text-xs').props('color=violet unelevated size=sm icon=movie_edit')
                manual_btn.visible = state.manual_video_mode
                manual_btn.bind_enabled_from(state, 'is_busy', lambda _: _manual_edit_ready(state, exporter))

                # 자동 모드 전용 Start Production 버튼
                async def run_production_with_notification():
                    if not state.script:
                        safe_notify('로드된 각본이 없습니다. 스크립트 작성 후 실행해주십시오.', type='warning')
                        return
                    if not state.is_script_reviewed():
                        safe_notify('기획 탭에서 현재 각본을 먼저 확인하세요.', type='warning')
                        return
                    for index, scene in enumerate(state.script.scenes):
                        if scene_mode(state.mode, scene, index) == 'video':
                            try:
                                verified_first_frame(state.script, scene)
                                clip, frame_hash = state.get_or_create_service().review_clip_path(state.script, index)
                            except ValueError:
                                safe_notify('Veo 장면의 첫 프레임을 아래에서 미리 보고 승인하세요.', type='warning')
                                return
                            if not clip or raw_review_status(state.script, scene, clip, frame_hash) != 'approved':
                                safe_notify('Veo 무음 원본을 아래에서 생성·검토한 뒤 승인하세요.', type='warning')
                                return
                    ui.notify('검토된 장면과 선택한 내레이션으로 제작을 시작합니다.', type='info')
                    await run_production()

                auto_btn = ui.button(
                    '영상 제작 시작',
                    on_click=run_production_with_notification
                ).classes('px-4 py-1.5 font-bold text-xs bg-gradient-to-r from-violet-600 to-indigo-600').props('color=violet unelevated size=sm icon=rocket_launch').bind_enabled_from(
                    state, 'is_busy', lambda _: _auto_edit_ready(state, raw_readiness['verdicts']))
                auto_btn.visible = not state.manual_video_mode

                # 상태 인디케이터 스피너
                gen_spinner = ui.spinner(size='sm').props('color=violet').classes('my-1')
                gen_spinner.visible = False

        # ── 2. MAIN PRODUCTION WORKSPACE ──
        with ui.row().classes('w-full gap-0'):

            # --- 2A. LEFT SIDE: WIDE PREVIEW MONITOR (자동 모드 시 메인, 수동 모드 시 숨김/작게) ---
            # 자동 모드와 수동 모드 모두의 통합 뷰어
            with ui.column().classes('w-full p-4 lg:p-6 gap-5') as main_workspace_area:

                if not settings.paid_production_enabled and not state.prepared_narration_manifest:
                    ui.label('검토 모드 · 기존 내레이션과 모든 장면 영상을 연결하면 새 API 호출 없이 편집할 수 있습니다.').classes(
                        'w-full p-3 rounded-lg bg-amber-950/20 border border-amber-700/40 text-sm text-amber-200')
                @ui.refreshable
                def raw_reviews():
                    # Keep the live verdict dict; bindings never poll video files to recompute readiness.
                    raw_readiness['verdicts'] = render_raw_clip_reviews(state) or {}

                render_first_frame_reviews(state, on_review_change=lambda: safe_refresh(raw_reviews))
                ui.button('원본 상태 새로고침', on_click=lambda: safe_refresh(raw_reviews)).props(
                    'flat color=teal icon=refresh').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
                ui.label('저장된 요청·원본·판정만 다시 읽습니다. 새 API 요청은 보내지 않습니다.').classes('text-xs text-slate-400')
                raw_reviews()

                # ── 대형 프리뷰 모니터 카드 (자동 생성 시 혹은 수동 편집 완료 시 띄움) ──
                with ui.element('div').classes('w-full rounded-xl bg-slate-900 border border-slate-800 overflow-hidden flex flex-col shadow-xl') as preview_monitor_card:
                    # 모니터 타이틀 바
                    with ui.element('div').classes('w-full bg-slate-900/90 border-b border-slate-800 px-4 py-2.5 flex items-center justify-between'):
                        with ui.row().classes('items-center gap-2'):
                            ui.element('div').classes('w-2 h-2 rounded-full bg-rose-500 animate-pulse')
                            ui.label('완성본 미리보기').classes('text-xs font-bold text-slate-300')

                        # 해상도 정보 등 뱃지
                        ui.badge('9:16 Vertical Shorts').classes('bg-slate-800 text-slate-400 text-[10px] px-2 py-0.5 border border-slate-700')

                    # 모니터 콘텐츠 본체
                    with ui.element('div').classes('w-full h-[360px] flex items-center justify-center bg-black/80 relative overflow-hidden'):
                        video_player = None
                        placeholder_content = None

                        # Gemini 풍의 유려한 그라데이션 광채 플레이스홀더
                        with ui.column().classes('items-center gap-3 z-10 p-6 text-center') as placeholder_content:
                            ui.icon('smart_display', size='lg').classes('text-violet-500/70')
                            ui.label('완성된 영상이 여기에 표시됩니다').classes('text-sm font-bold text-slate-300')
                            ui.label('우측 패널에서 하이브리드, Gemini 이미지, Veo 영상 모드를 고른 뒤 생성하면 여기에 프리뷰가 재생됩니다.').classes('text-xs text-slate-500 max-w-md leading-relaxed')

                            # 만약 API 요금 절감을 원할 시 수동 모드로 돌릴 것을 추천하는 뱃지
                            with ui.row().classes('items-center gap-1.5 mt-2 bg-violet-950/30 rounded-lg border border-violet-500/20 px-3 py-1.5'):
                                ui.icon('offline_bolt', size='xs').classes('text-violet-400')
                            ui.label('기존 장면 영상을 쓰려면 소스를 로컬 파일로 바꾸세요. 새 음성 생성에는 API 비용이 들 수 있습니다.').classes('text-[10px] text-violet-300')

                        # 실제 비디오 컴포넌트 (종횡비 9:16 대응)
                        video_player = ui.video('').classes('max-h-full max-w-[200px] h-full shadow-lg border border-slate-800 rounded bg-slate-950')
                        video_player.bind_source_from(state, 'preview_video_path', backward=media_source)
                        video_player.bind_visibility_from(state, 'preview_video_path', bool)
                        placeholder_content.bind_visibility_from(state, 'preview_video_path', lambda path: not path)
                        ui.label('품질 검사를 통과하지 못한 영상의 미리보기입니다. 이 파일은 업로드할 완성본으로 선택되지 않았습니다.').classes(
                            'text-xs text-amber-200').bind_visibility_from(state, 'failed_video_preview_path',
                                lambda path: bool(path) and not state.final_video_path)

                # ── 파이프라인 진행 상태 모니터 ──
                with ui.element('div').classes('w-full rounded-xl bg-slate-900 border border-slate-800 p-5') as pipeline_status_card:
                    with ui.row().classes('w-full items-center justify-between mb-4'):
                        ui.label('파이프라인 진행 이력').classes('text-xs font-bold text-slate-400 uppercase tracking-widest')
                        ui.label().bind_text_from(state, 'pipeline_message').classes('text-xs text-violet-400 font-semibold')

                    # 파이프라인 단계 로드바
                    with ui.row().classes('w-full justify-between items-center bg-slate-950/60 rounded-xl border border-slate-800/80 p-4 mb-4'):
                        step_configs = [
                            ('ready', 'hourglass_empty', 'Ready'),
                            ('visuals', 'auto_awesome', 'Veo Visuals'),
                            ('editing', 'movie_edit', 'FFmpeg Editing'),
                            ('complete', 'check_circle', 'Finished')
                        ]
                        for i, (phase_id, icon, label_text) in enumerate(step_configs):
                            with ui.column().classes('items-center gap-1.5 flex-grow'):
                                icon_class = 'text-violet-400' if i == 0 else 'text-slate-600'
                                with ui.element('div').classes('w-9 h-9 rounded-full bg-slate-900 border border-slate-800 flex items-center justify-center transition-all duration-300'):
                                    ui.icon(icon, size='xs').classes(icon_class)
                                phase_labels[phase_id] = ui.label(label_text).classes('text-[10px] text-slate-500 font-semibold uppercase tracking-wider')

                            if i < len(step_configs) - 1:
                                ui.element('div').classes('h-px bg-slate-800 flex-grow max-w-[60px] mb-5')

                    # 실시간 생성 씬 격자 모니터 (비디오 생성 상태 확인)
                    scene_progress_container = ui.column().classes('w-full gap-2 mt-2')
                    scene_progress_container.visible = False

            # --- 2B. RIGHT SIDE: SCENE MANUAL GRID UPLOADER (수동 모드 시 화면 가득 활성화) ---
            with ui.element('div').classes('w-full bg-slate-950') as manual_uploader_area:
                with ui.column().classes('w-full p-4 lg:p-6 gap-2') as manual_preview:
                    ui.label('편집 결과 미리보기').classes('text-sm font-bold text-white')
                    manual_video_player = ui.video('').classes('w-full max-w-[220px] max-h-[360px] bg-black')
                    manual_video_player.bind_source_from(state, 'final_video_path', backward=media_source)
                manual_preview.bind_visibility_from(state, 'final_video_path', bool)
                scene_cards_container = ui.grid(columns='repeat(auto-fill, minmax(min(100%, 320px), 1fr))').classes('w-full gap-4 p-4 lg:p-6')

        # ── 3. VISIBILITY SWITCHING LOGIC ──
        def sync_layout_visibility():
            """수동/자동 모드 설정값에 따른 가시성 조율"""
            try:
                # 자동 모드는 프리뷰, 수동 모드는 업로더를 표시
                main_workspace_area.visible = not state.manual_video_mode
                manual_uploader_area.visible = state.manual_video_mode

                auto_btn.visible = not state.manual_video_mode
                manual_btn.visible = state.manual_video_mode

                if state.manual_video_mode:
                    render_manual_panel(state, exporter, manual_btn, scene_cards_container)
            except RuntimeError:
                pass

        # 초기 동기화
        sync_layout_visibility()

        # ── 4. EVENT HANDLERS CORE (동적 렌더러 연동) ──
        async def _run_production_core(manual_clip_paths=None, expected_mode=state.mode,
                                       expected_manual_mode=state.manual_video_mode, expected_execution=state.execution_key()):
            nonlocal video_player, placeholder_content
            if state.is_busy:
                safe_notify('이미 제작이 진행 중입니다.', type='warning')
                return
            if not state.script or state.script.model_dump_json() != rendered_script:
                safe_notify('각본이 변경됐습니다. 장면·영상 제작 화면을 다시 열어 주세요.', type='warning')
                return
            if state.mode != expected_mode or state.manual_video_mode != expected_manual_mode:
                safe_notify('제작 방식이 변경됐습니다. 현재 장면·영상 제작 화면에서 다시 시작하세요.', type='warning')
                return
            if not state.is_script_reviewed():
                safe_notify('기획 탭에서 현재 각본을 확인한 뒤 제작을 시작하세요.', type='warning')
                return
            if state.has_unapplied_script_draft():
                safe_notify('먼저 미적용 대본 수정을 적용하거나 되돌리세요.', type='warning')
                return
            if state.has_unapplied_first_frame_drafts():
                safe_notify('먼저 첫 프레임 후보·검토 입력을 승인하거나 되돌리세요.', type='warning')
                return
            if not settings.paid_production_enabled and not state.prepared_narration_manifest:
                safe_notify('검토 모드입니다. 기존 내레이션을 연결하거나 API 생성을 활성화하세요.', type='warning')
                return
            try:
                state.require_execution_context(expected_execution)
                prepared_audio = state.prepared_audio_paths()
                service = state.new_production_service()
            except (OSError, ValueError, TypeError, RuntimeError) as error:
                safe_notify(f'제작 준비를 다시 확인하세요: {error}', type='negative')
                return
            production_running = True

            try:
                gen_spinner.visible = True
                scene_progress_container.visible = True
                scene_progress_container.clear()
                if video_player:
                    video_player.visible = False
                if placeholder_content:
                    placeholder_content.visible = True
                manual_preview.visible = False
            except RuntimeError:
                return

            try:
                # 상태 초기화
                state.reset_pipeline()
                state.pipeline_running = True
                state.final_video_path = None
                state.failed_video_preview_path = None
                state.generated_clips = []

                def on_progress(progress: ProductionProgress):
                    state.sync_from_progress(progress)

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

                logger.info("=== Production Pipeline Execution Triggered ===")
                options = {'manual_clip_paths': manual_clip_paths, 'retain_narration': True}
                if prepared_audio is not None:
                    options['prepared_audio_paths'] = prepared_audio
                result = await service.produce_video(state.script, **options)

                production_running = False
                await monitor_task

                retained_voice = getattr(result, 'narration_manifest_path', None)
                if retained_voice:
                    state.prepared_narration_manifest = retained_voice
                    safe_refresh(narration_panel)
                if result.success:
                    state.final_video_path = result.video_path
                    state.failed_video_preview_path = None
                    state.generated_clips = result.clips
                    update_progress_ui('complete', 100)
                    safe_notify(
                        f"영상 제작 완료 · 예상 비주얼 API 비용 ${result.estimated_visual_cost_usd:.3f} "
                        f"· 재사용·수동 {result.reused_scenes}장면",
                        type='positive',
                    )

                    logger.info(f"Final output video available at: {state.final_video_path}")
                else:
                    state.generated_clips = result.clips
                    state.failed_video_preview_path = result.video_path
                    safe_notify(f"프로덕션 실패: {result.error}", type='negative')
                    logger.error(f"Production Failed: {result.error}")

            except Exception as e:
                safe_notify(f"실행 도중 오류 발생: {e}", type='negative')
                logger.error(f"Production Error Event: {e}")
            finally:
                production_running = False
                state.pipeline_running = False
                try:
                    gen_spinner.visible = False
                except RuntimeError:
                    pass

        async def run_production():
            if not state.script:
                safe_notify("각본을 먼저 생성/로드해주십시오.", type='warning')
                return
            await _run_production_core(manual_clip_paths=None)

        async def run_production_with_clips(clips: dict):
            if not state.script:
                safe_notify("각본을 먼저 로드해주십시오.", type='warning')
                return
            await _run_production_core(manual_clip_paths=clips)
