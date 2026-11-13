"""Plain-language script fields sharing the existing explicit-apply JSON draft."""

from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.utils.source_manager import SourceManager


def render_script_form(state, on_change, on_apply, on_discard):
    selected = {'scene': None}

    @ui.refreshable
    def panel():
        key = state.script_editor_key()
        version = {'text': state.script_editor_text()}
        with ui.expansion('대본·장면 편집', icon='edit_note', value=True).classes('w-full bg-slate-900 rounded-lg mb-4').props('dark') as form:
            ui.label('수정은 초안으로 유지됩니다. 적용하면 아래 현재 대본이 바뀌며 각본·장면을 다시 확인해야 합니다. 원문과 대조해 수정하세요.').classes('text-xs text-slate-300')
            ui.label().bind_text_from(state, 'is_busy', lambda _: '미적용 수정 있음 · 적용하거나 되돌린 뒤 제작하세요.'
                                     if state.has_unapplied_script_draft() else '현재 적용된 대본과 같은 내용입니다.').classes('text-xs text-amber-200')

            def change(field, scene_number=None):
                def update(event):
                    if form.is_deleted or event.sender.is_deleted:
                        return
                    try:
                        value = (event.value or None) if field == 'visual_mode' else event.value
                        if value is None and field in {'title', 'description', 'script_text', 'visual_description', 'motion_instruction'}:
                            value = ''
                        if state.update_script_form_field(key, version['text'], field, value, scene_number):
                            version['text'] = state.script_editor_text()
                            on_change()
                    except (ValueError, TypeError) as error:
                        safe_notify(f'수정 내용을 확인하세요: {error}', type='warning')
                return update

            def act(callback):
                if (form.is_deleted or state.is_busy or key != state.script_editor_key()
                        or version['text'] != state.script_editor_text()):
                    safe_notify('작업 중이거나 초안이 바뀌었습니다. 편집 화면을 새로고침하세요.', type='warning')
                    return
                callback()

            try:
                data = state.script_form_data()
            except (ValueError, TypeError) as error:
                ui.label(f'일반 편집을 열 수 없습니다: {error}').classes('text-xs text-amber-200 break-all')
            else:
                ready = lambda busy: not busy and key == state.script_editor_key()
                source = data.get('source_url')
                if isinstance(source, str) and SourceManager.is_allowed_url(source):
                    ui.link('초안 출처 원문 열기', source, new_tab=True).props('rel="noopener noreferrer"').classes('text-teal-300 break-all')
                else:
                    ui.label('초안의 출처 URL을 확인하세요. 일반 폼은 출처를 자동으로 만들거나 바꾸지 않습니다.').classes('text-xs text-amber-200')
                ui.input('대본 제목', value=data.get('title', ''), on_change=change('title')).props('outlined dark').classes('w-full').bind_enabled_from(state, 'is_busy', ready)
                ui.textarea('대본 설명', value=data.get('description', ''), on_change=change('description')).props('outlined dark rows=2').classes('w-full').bind_enabled_from(state, 'is_busy', ready)
                labels = {'calm': '차분하고 부드럽게', 'suspense': '긴장감', 'sci-fi': '기술·호기심',
                          'corporate': '정보 전달', 'emotional': '감성적', 'energetic': '경쾌하게', 'luxury': '우아하게'}
                moods = {mood: labels.get(mood, mood) for mood in ScriptPlanner.SUPPORTED_MOODS}
                ui.select(moods, label='대본 음악 분위기',
                          value=data.get('mood') if data.get('mood') in moods else None,
                          on_change=change('mood')).props('outlined dark').classes('w-full min-h-[44px]').bind_enabled_from(state, 'is_busy', ready)
                if data.get('mood') not in moods:
                    ui.label('초안의 음악 분위기가 미선택이거나 목록 밖의 값입니다. 자동으로 바꾸지 않으므로 내용을 검토한 뒤 선택하세요.').classes('text-xs text-amber-200')
                ui.label('대본의 연출 방향만 정합니다. 실제 곡은 음성·음악 설정에서 따로 고르며, 사용 허가된 곡이 없으면 제작이 중단됩니다.').classes('text-xs text-slate-400')
                modes = {'hybrid': '혼합 · 오프닝 영상 + 이미지', 'image': '이미지 중심', 'video': '장면별 Veo 영상'}
                mode = ui.select(modes, label='대본에 저장할 기본 화면 구성',
                                 value=data.get('generation_mode') if data.get('generation_mode') in modes else None,
                                 on_change=change('generation_mode')).props('outlined dark').classes('w-full')
                mode.bind_enabled_from(state, 'is_busy', ready)
                ui.label('적용하면 우측 화면 구성도 이 기본값으로 바뀝니다. 원본 요청 길이·비용은 장면 생성 화면에서 확인하세요.').classes('text-xs text-slate-400')
                ui.label('장면 추가·순서 변경은 제작량과 혼합 모드의 오프닝을 바꿀 수 있습니다. 적용 후 장면 생성 화면에서 비용을 확인하세요.').classes('text-xs text-slate-400')
                scene_options = {scene['scene_number']: f'{i + 1}번째 · 장면 {scene["scene_number"]}'
                                 for i, scene in enumerate(data['scenes'])}
                if selected['scene'] not in scene_options:
                    selected['scene'] = next(iter(scene_options))

                @ui.refreshable
                def scene_fields():
                    view = object()
                    selected['view'] = view
                    try:
                        current = state.script_form_data()
                        scene = next(s for s in current['scenes'] if s['scene_number'] == selected['scene'])
                    except (ValueError, TypeError, StopIteration):
                        ui.label('초안 구조가 바뀌었습니다. 편집 화면을 새로고침하세요.').classes('text-amber-200')
                        return
                    number = scene['scene_number']
                    position = current['scenes'].index(scene)
                    ui.label(f'재생 순서 {position + 1} / {len(current["scenes"])} · 장면 번호 {number}').classes('text-sm text-teal-200')
                    ui.label('앞으로·뒤로는 재생 순서만 바꿉니다. 장면 번호는 유지되며, 적용 후 기존 재료·음성을 다시 확인하세요.').classes('text-xs text-slate-400')

                    def restructure(action, expected_text=None):
                        if form.is_deleted or selected.get('view') is not view:
                            return
                        try:
                            selected['scene'] = state.change_script_scene(key, expected_text if expected_text is not None else version['text'], action, number)
                            version['text'] = state.script_editor_text()
                            on_change()
                            safe_refresh(panel)
                        except (ValueError, TypeError) as error:
                            safe_notify(f'장면을 바꿀 수 없습니다: {error}', type='warning')

                    def confirm_remove():
                        if (form.is_deleted or selected.get('view') is not view or state.is_busy
                                or version['text'] != state.script_editor_text() or key != state.script_editor_key()):
                            return
                        expected_text = version['text']
                        current_scene = next(s for s in state.script_form_data()['scenes'] if s['scene_number'] == number)
                        with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg bg-slate-900 text-white'):
                            ui.label(f'장면 {number}을 초안에서 삭제할까요?').classes('text-lg font-bold')
                            ui.label(current_scene.get('script_text', '') or '(내레이션 없음)').classes('text-sm whitespace-pre-wrap break-all')
                            ui.label('적용 전 초안만 바뀝니다. 원본 대본 파일과 영상·음성은 삭제하지 않습니다.').classes('text-xs text-slate-300')
                            def remove():
                                if dialog.is_deleted or not dialog.value:
                                    return
                                restructure('remove', expected_text)
                                dialog.close()
                            with ui.row().classes('w-full flex-wrap'):
                                ui.button('취소', on_click=dialog.close).props('flat').classes('min-h-[44px]')
                                ui.button('선택 장면 삭제', on_click=remove).props('color=red').classes('min-h-[44px]').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
                        dialog.open()

                    with ui.row().classes('w-full flex-wrap'):
                        for label, action, possible in [('앞으로 이동', 'earlier', position > 0),
                                                        ('뒤로 이동', 'later', position + 1 < len(current['scenes'])),
                                                        ('이 장면 뒤에 추가', 'add', True)]:
                            ui.button(label, on_click=lambda a=action: restructure(a)).props('outline').classes('min-h-[44px]').bind_enabled_from(
                                state, 'is_busy', lambda busy, allowed=possible: ready(busy) and allowed)
                        ui.button('장면 삭제', on_click=confirm_remove).props('flat color=red').classes('min-h-[44px]').bind_enabled_from(
                            state, 'is_busy', lambda busy: ready(busy) and len(current['scenes']) > 1)
                    for label, field, rows in [('내레이션', 'script_text', 3), ('화면 설명·이미지 프롬프트', 'visual_description', 4),
                                                ('움직임·영상 프롬프트', 'motion_instruction', 3)]:
                        ui.textarea(f'장면 {number} · {label}', value=scene.get(field, ''), on_change=change(field, number)).props(
                            f'outlined dark rows={rows}').classes('w-full').bind_enabled_from(state, 'is_busy', ready)
                    ui.number('장면 예상 길이 (초)', value=scene.get('duration_seconds', 5.0), min=.1,
                              on_change=change('duration_seconds', number)).props('outlined dark step=any').classes('w-full').bind_enabled_from(state, 'is_busy', ready)
                    visual_modes = {'': '기본 모드 따름', 'image': '이미지', 'video': 'Veo 영상'}
                    override = ui.select(visual_modes, label='이 장면의 화면 구성 · 혼합 모드에서 적용',
                                         value=scene.get('visual_mode') if scene.get('visual_mode') in visual_modes else '',
                                         on_change=change('visual_mode', number)).props('outlined dark').classes('w-full')
                    override.bind_enabled_from(state, 'is_busy', lambda busy: ready(busy) and mode.value == 'hybrid')

                def choose_scene(event):
                    if (form.is_deleted or state.is_busy or key != state.script_editor_key()
                            or version['text'] != state.script_editor_text() or event.value not in scene_options):
                        return
                    selected['scene'] = event.value
                    safe_refresh(scene_fields)

                ui.select(scene_options, value=selected['scene'], label='수정할 장면', on_change=choose_scene).props(
                    'outlined dark').classes('w-full').bind_enabled_from(state, 'is_busy', ready)
                scene_fields()

            with ui.row().classes('w-full flex-wrap'):
                ui.button('수정 내용 적용', on_click=lambda: act(on_apply)).props('color=teal').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and key == state.script_editor_key() and state.has_unapplied_script_draft())
                ui.button('수정 내용 되돌리기', on_click=lambda: act(on_discard)).props('flat').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and key == state.script_editor_key() and state.has_unapplied_script_draft())
                ui.button('편집 화면 새로고침', on_click=lambda: safe_refresh(panel)).props('flat').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
    panel()
    return panel
