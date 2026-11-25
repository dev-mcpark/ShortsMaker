"""Reopen a finished episode edit or attach its confirmed private upload."""

import asyncio
from pathlib import Path

from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.services.episode_review_recovery import (
    attach_recovered_review_copy, recovered_episode_edits, recovered_review_copies,
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
                ui.label('이 회차 대본과 완성본을 작업실에 불러옵니다. 대본 확인 후 완성본·업로드에서 검토를 이어가세요.'
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
                            notice.text = '편집한 완성본을 불러왔습니다. 작업실에서 대본을 확인한 뒤 완성본·업로드에서 검토하세요.'
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
