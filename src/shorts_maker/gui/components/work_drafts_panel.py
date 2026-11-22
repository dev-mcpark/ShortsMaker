"""Explicit save/reopen controls for unfinished script and first-frame text work."""

import asyncio
import json

from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.services.revision_validation import read_stopped_writer_draft
from shorts_maker.services.work_drafts import read_work_draft, saved_work_drafts


def render_episode_writer_draft(state, manager, schedule):
    """Open the exact stopped episode's writer snapshot through normal draft recovery."""
    working = {'value': False}
    with ui.column().classes('w-full gap-1') as panel:
        notice = ui.label().classes('text-sm text-amber-200 break-words').props('role=alert')
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
            content = ui.column().classes('w-full')

        def work_identity():
            return json.dumps([state.script_editor_key(), state.script_editor_text(), state.first_frame_drafts,
                               state.execution_key(), state.reviewed_script_sha256, state.final_video_path,
                               state.prepared_narration_manifest, state._editor_options(),
                               state.manual_video_mode, state.manual_script_id], sort_keys=True)

        def current():
            return (not panel.is_deleted and not dialog.is_deleted and not state.is_busy
                    and (not state.operating_scope
                         or state.operating_scope.get('episode_id') == schedule.get('last_episode_id')))

        async def preview_writer_draft():
            if panel.is_deleted or working['value'] or dialog.value:
                return
            if not current():
                notice.set_text('현재 작업 또는 회차 연결을 확인한 뒤 저장된 초안을 여세요.')
                return
            opened_work = work_identity()
            working['value'] = True
            notice.set_text('')
            try:
                original = await asyncio.to_thread(read_stopped_writer_draft, manager, schedule)
            except (OSError, ValueError, RuntimeError) as error:
                if not panel.is_deleted:
                    notice.set_text(f'작성 초안 확인 중단: {error}')
                return
            finally:
                working['value'] = False
            if not current() or work_identity() != opened_work:
                return
            content.clear()
            with content:
                ui.label(original['title']).classes('text-lg font-bold break-words')
                ui.label(original['source_url']).classes('text-sm break-all')
                ui.label('작성 당시 원문 발췌').classes('font-semibold')
                with ui.scroll_area().classes('w-full h-48'):
                    ui.label(original['source_excerpt']).classes('text-sm whitespace-pre-wrap break-words')
                ui.label('초안을 열면 현재 대본과 입력을 사본으로 보관하고 편집 중인 완성본 선택을 해제합니다. '
                         '제작 작업실에서 음악 분위기를 수정하고 곡이나 무음 설정을 저장하세요.').classes('text-sm')
                error_label = ui.label().classes('text-sm text-amber-200 break-words').props('role=alert')

                def restore():
                    if (panel.is_deleted or error_label.is_deleted or not dialog.value):
                        return
                    try:
                        if not current() or work_identity() != opened_work or manager.get_schedule(schedule['id']) != schedule:
                            raise ValueError('현재 작업이나 회차 상태가 바뀌었습니다. 작성 초안을 다시 확인하세요.')
                        state.restore_work_draft(original['name'], original['sha256'])
                    except (ValueError, OSError, RuntimeError) as error:
                        error_label.set_text(f'작성 초안 열기 중단: {error}')
                        return
                    dialog.close()
                    safe_notify('작성 초안을 열었습니다. 제작 작업실의 대본·장면 편집에서 이어서 수정하세요.', type='positive')

                with ui.row().classes('flex-wrap'):
                    ui.button('닫기', on_click=dialog.close).props('flat').classes('min-h-[44px]')
                    ui.button('작성 초안을 작업실에서 열기', on_click=restore).props('color=teal').classes('min-h-[44px]')
            dialog.open()

        ui.button('이 회차의 작성 초안 확인', on_click=preview_writer_draft).props('outline').classes(
            'min-h-[44px]').bind_enabled_from(state, 'is_busy', lambda busy: not busy and not working['value'])


def render_work_drafts_panel(state, on_restored):
    opened = {'value': False}
    @ui.refreshable
    def panel():
        key = state.script_editor_key()
        with ui.expansion('저장된 작업 초안', icon='save_as', value=opened['value'],
                          on_value_change=lambda event: opened.update(value=event.value)).classes('w-full') as view:
            ui.label('미완성 JSON과 첫 프레임 경로·검토 메모를 사본당 2 MiB까지 보관합니다. 입력만으로 자동 저장되지는 않습니다.').classes('text-xs text-slate-300')
            ui.label('형식 문제로 중단된 모델 각본도 미적용 초안으로 보관됩니다. 목록을 새로고침한 뒤 대본 제목이나 오류 안내의 끝번호로 찾으세요.').classes('text-xs text-slate-400')
            ui.label('소재 방식·입력 중인 URL·RSS 분야도 함께 저장합니다. 복원해도 기사 조회·기획을 자동 실행하지 않습니다.').classes('text-xs text-slate-400')
            ui.label('열기 전 현재/대상 대본의 미적용 입력도 새 초안으로 보관합니다. 복원 후에는 대본·장면 확인을 다시 진행하세요.').classes('text-xs text-slate-400')

            def current():
                if view.is_deleted or state.is_busy or key != state.script_editor_key():
                    raise ValueError('작업 중이거나 대본이 바뀌었습니다. 현재 화면을 다시 확인하세요.')

            def save():
                try:
                    current()
                    path = state.save_work_draft()
                    safe_refresh(panel)
                    safe_notify(f'작업 초안 사본 저장: {path.name}', type='positive')
                except (ValueError, OSError) as error:
                    safe_notify(f'초안 저장 중단: {error}', type='warning')

            ui.button('작업 초안 새 사본 저장', on_click=save).props('outline icon=save').bind_enabled_from(
                state, 'is_busy', lambda busy: not busy and (state.script is not None or bool(state.script_editor_text().strip())
                                                            or state.has_planning_input()))
            try:
                records, warnings = saved_work_drafts()
            except (ValueError, OSError) as error:
                records, warnings = {}, [str(error)]
            for warning in warnings[:3]:
                ui.label(warning).classes('text-xs text-amber-200 break-all')
            if records:
                choice = ui.select({name: record['label'] for name, record in records.items()},
                                   label='저장된 작업 초안 검색', with_input=True).props('outlined dark clearable').classes('w-full')

                def preview_source():
                    try:
                        current()
                        if choice.value not in records:
                            raise ValueError('확인할 작업 초안을 선택하세요.')
                        record, digest = read_work_draft(choice.value)
                        if digest != records[choice.value]['sha256']:
                            raise ValueError('선택한 초안이 바뀌었습니다. 목록을 새로고침하세요.')
                    except (ValueError, OSError) as error:
                        safe_notify(str(error), type='warning')
                        return
                    source = record.writer_source
                    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
                        ui.label('각본 작성에 사용한 원문 발췌').classes('font-semibold')
                        if source:
                            if source.episode_id:
                                ui.label(f'작성 회차 · {source.episode_id}').classes('break-all')
                            ui.label(source.source_url).classes('text-sm break-all')
                            ui.label(source.excerpt).classes('whitespace-pre-wrap break-words')
                        else:
                            ui.label('이 사본에는 작성 당시의 원문 발췌가 저장되어 있지 않습니다.')
                        ui.button('닫기', on_click=dialog.close).props('flat')
                    dialog.open()

                ui.button('작성 원문 확인', on_click=preview_source).props('outline').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and bool(choice.value))

                def restore():
                    try:
                        current()
                        if choice.value not in records:
                            raise ValueError('복원할 작업 초안을 선택하세요.')
                        backups = state.restore_work_draft(choice.value, records[choice.value]['sha256'])
                        on_restored()
                        if state.script_editor_key() == key:
                            safe_refresh(panel)
                        safe_notify(f'작업 초안 복원 완료 · 기존 미적용 입력 {len(backups)}개 사본 보관. 대본을 다시 확인하세요.', type='positive')
                    except (ValueError, OSError) as error:
                        safe_notify(f'초안 복원 중단: {error}', type='warning')

                ui.button('선택한 작업 초안 열기', on_click=restore).props('color=teal').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and bool(choice.value))
            else:
                ui.label('사용 가능한 초안을 불러오지 못했습니다. 목록 경고를 확인하세요.' if warnings
                         else '저장된 작업 초안이 없습니다.').classes('text-xs text-slate-400')
            ui.button('초안 목록 새로고침', on_click=lambda: safe_refresh(panel)).props('flat').bind_enabled_from(
                state, 'is_busy', lambda busy: not busy)
            ui.label('각본·장면 승인, 게시 입력, 실행·예산 권한은 이 사본에 포함하지 않습니다. 적용한 대본 파일 저장과도 별개입니다.').classes('text-xs text-slate-400')
    panel()
    return panel
