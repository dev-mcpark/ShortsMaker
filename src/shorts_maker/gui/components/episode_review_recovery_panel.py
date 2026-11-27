"""Recover an episode's completed planning, edit, or private upload."""

import asyncio
from pathlib import Path

from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.services.episode_review_recovery import (
    archive_reaped_planning, archive_reaped_upload, attach_recovered_review_copy,
    preview_reaped_planning, preview_reaped_upload, recovered_episode_edits, recovered_review_copies,
)


def render_episode_review_recovery(state, manager, schedule, refresh, *, edit=False):
    find_results = recovered_episode_edits if edit else recovered_review_copies
    working = {'value': False}
    dialog = None
    with ui.column().classes('w-full gap-1') as panel:
        notice = ui.label().classes('text-sm text-slate-300 break-words').props('role=status')

        def current():
            return not panel.is_deleted and not state.is_busy and not working['value']

        def workspace():
            return (state.execution_key(), state.script_editor_key(), state.script_editor_text(),
                    state.final_video_path, state.reviewed_script_sha256)

        async def find_copies():
            nonlocal dialog
            if not current() or (dialog is not None and not dialog.is_deleted and dialog.value):
                return
            working['value'] = True
            notice.text = '이 회차의 편집 완료 기록을 확인하는 중…' if edit else '이 회차의 완료된 업로드 기록을 확인하는 중…'
            try:
                copies = await asyncio.to_thread(find_results, manager, schedule)
            except (OSError, ValueError, RuntimeError) as error:
                if not panel.is_deleted:
                    notice.text = f'검토본을 찾을 수 없습니다: {error}'
                return
            finally:
                working['value'] = False
            if not current():
                return
            if not copies:
                notice.text = ('이 회차에서 다시 열 수 있는 업로드 전 완성본이 없습니다. 업로드까지 마쳤다면 '
                               '이 회차의 업로드한 검토본을 찾아보세요.' if edit else
                               '이 회차에서 확인된 업로드 영수증이 없습니다. 기존 업로드를 확인하려면 완성본·업로드에서 '
                               '저장된 검토본을 살펴보세요.')
                return
            notice.text = ''
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()
            opening_workspace = workspace()
            with ui.dialog() as opened, ui.card().classes('w-full max-w-xl'):
                ui.label('이 회차에서 편집한 완성본' if edit else '이번 회차에서 비공개 업로드한 검토본').classes('text-lg font-bold')
                ui.label('이 회차 대본과 완성본을 작업실에 불러옵니다. 완성본·업로드에서 전체 영상을 검토하세요.'
                         if edit else
                         '파일과 YouTube ID를 확인해 이 회차에 연결하세요. 연결 후에는 검토 대기입니다.').classes('text-sm')
                choice = ui.select({path: Path(path).name if edit else f'{Path(path).name} · {row["youtube_id"]}'
                                    for path, row in copies.items()},
                                   label='편집한 완성본' if edit else '완료된 검토본').props('outlined').classes('w-full').bind_enabled_from(
                    working, 'value', lambda value: not value)
                error_label = ui.label().classes('text-sm text-amber-200 break-words').props('role=alert')

                @ui.refreshable
                def selected_link():
                    if row := copies.get(choice.value):
                        video_id = row['youtube_id']
                        ui.link(f'YouTube {video_id}', f'https://www.youtube.com/shorts/{video_id}', new_tab=True)

                if not edit:
                    selected_link()
                    choice.on_value_change(lambda _: selected_link.refresh())

                async def attach():
                    selected = copies.get(choice.value)
                    if not current() or opened.is_deleted or not opened.value or selected is None:
                        return
                    working['value'] = True
                    error_label.text = ''
                    try:
                        if edit:
                            confirmed = await asyncio.to_thread(find_results, manager, schedule)
                            if opened.is_deleted or not opened.value or panel.is_deleted:
                                return
                            if state.is_busy or workspace() != opening_workspace or choice.value != selected['video_path']:
                                raise ValueError('현재 작업이나 선택이 바뀌었습니다. 완성본을 다시 선택하세요.')
                            if confirmed.get(choice.value) != selected:
                                raise ValueError('저장된 완성본이 변경됐습니다. 완성본을 다시 확인하세요.')
                            state.load_scheduled_script(manager, schedule['id'], expected_schedule=schedule)
                            state.final_video_path = selected['video_path']
                        else:
                            await asyncio.to_thread(attach_recovered_review_copy, manager, schedule, selected)
                    except (OSError, ValueError, RuntimeError) as error:
                        if not error_label.is_deleted:
                            error_label.text = f'{"완성본 열기 중단" if edit else "저장된 검토본 연결 중단"}: {error}'
                        return
                    finally:
                        working['value'] = False
                    if not panel.is_deleted:
                        opened.close()
                        if edit:
                            notice.text = ('편집한 완성본을 불러왔습니다. 완성본·업로드에서 검토하세요.'
                                           if state.is_script_reviewed() else
                                           '편집한 완성본을 불러왔습니다. 작업실에서 대본을 확인한 뒤 완성본·업로드에서 검토하세요.')
                        else:
                            refresh()
                            safe_notify('저장된 비공개 검토본을 이 회차에 연결했습니다.', type='positive')

                with ui.row().classes('flex-wrap'):
                    ui.button('닫기', on_click=opened.close).props('flat').classes('min-h-[44px]').bind_enabled_from(
                        working, 'value', lambda value: not value)
                    ui.button('선택한 완성본 열기' if edit else '선택한 저장 검토본 연결', on_click=attach).props('color=teal').classes(
                        'min-h-[44px]').bind_enabled_from(state, 'is_busy',
                            lambda busy: not busy and not working['value'] and choice.value in copies)
            dialog = opened
            dialog.open()

        ui.button('이 회차의 편집한 완성본 찾기' if edit else '이 회차의 업로드한 검토본 찾기',
                  on_click=find_copies).props('outline').classes(
            'min-h-[44px]').bind_enabled_from(state, 'is_busy', lambda busy: not busy and not working['value'])


def render_pending_result_recovery(state, manager, schedule, refresh, *, planning=False):
    preview_result = preview_reaped_planning if planning else preview_reaped_upload
    archive_result = archive_reaped_planning if planning else archive_reaped_upload
    stage = '기획' if planning else '업로드'
    next_step = '검토할 각본을 다시 불러오세요.' if planning else '업로드한 검토본을 찾아 이 회차에 연결하세요.'
    working = {'value': False}
    current_dialog = None
    with ui.column().classes('w-full gap-1') as panel:
        notice = ui.label().classes('text-sm text-amber-200 break-words').props('role=status')

        async def preview():
            nonlocal current_dialog
            if (panel.is_deleted or state.is_busy or working['value']
                    or (current_dialog is not None and not current_dialog.is_deleted and current_dialog.value)):
                return
            working['value'] = True
            notice.text = '저장된 결과를 대조하고 있습니다…'
            try:
                proof = await asyncio.to_thread(preview_result, manager, schedule)
            except (OSError, ValueError, RuntimeError) as error:
                if not panel.is_deleted:
                    notice.text = f'복구 중단 · {error}'
                return
            finally:
                working['value'] = False
            if panel.is_deleted or state.is_busy:
                return
            notice.text = ''
            if current_dialog is not None and not current_dialog.is_deleted:
                current_dialog.delete()
            with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-xl'):
                info = proof[1]
                ui.label(f'완료된 {stage} 기록 복구').classes('text-lg font-bold')
                if planning:
                    ui.label(info['title']).classes('text-sm break-words')
                    ui.label(info['source_url']).classes('text-xs break-all')
                else:
                    ui.label(Path(info['video_path']).name).classes('text-sm break-all')
                    ui.link(f'YouTube {info["youtube_id"]}', f'https://www.youtube.com/shorts/{info["youtube_id"]}', new_tab=True)
                ui.label(f'대기 기록을 실행 이력에 보관합니다. 이후 {next_step}').classes('text-sm')
                error_label = ui.label().props('role=alert').classes('text-sm text-amber-200 break-words')

                async def archive():
                    if panel.is_deleted or dialog.is_deleted or not dialog.value or state.is_busy or working['value']:
                        return
                    working['value'] = True
                    try:
                        await asyncio.to_thread(archive_result, manager, schedule, proof)
                    except (OSError, ValueError, RuntimeError) as error:
                        if not error_label.is_deleted:
                            error_label.text = f'복구 중단 · {error}'
                        return
                    finally:
                        working['value'] = False
                    if not panel.is_deleted:
                        dialog.close()
                        await refresh()
                        safe_notify(f'실행 기록을 보관했습니다. {next_step}', type='positive')

                with ui.row().classes('flex-wrap'):
                    ui.button('닫기', on_click=dialog.close).props('flat').classes('min-h-[44px]').bind_enabled_from(
                        working, 'value', lambda value: not value)
                    ui.button('이 실행 기록 보관', on_click=archive).props('color=teal').classes(
                        'min-h-[44px]').bind_enabled_from(state, 'is_busy', lambda busy: not busy and not working['value'])
            current_dialog = dialog
            dialog.open()

        ui.button(f'완료된 {stage} 기록 대조', on_click=preview).props('outline').classes('min-h-[44px]').bind_enabled_from(
            state, 'is_busy', lambda busy: not busy and not working['value'])
