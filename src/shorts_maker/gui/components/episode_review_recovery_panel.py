"""Find, review and attach a private upload that finished in this episode."""

import asyncio
from pathlib import Path

from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.services.episode_review_recovery import attach_recovered_review_copy, recovered_review_copies


def render_episode_review_recovery(state, manager, schedule, refresh):
    working = {'value': False}
    dialog = None
    with ui.column().classes('w-full gap-1') as panel:
        notice = ui.label().classes('text-sm text-slate-300 break-words').props('role=status')

        def current():
            return not panel.is_deleted and not state.is_busy and not working['value']

        async def find_copies():
            nonlocal dialog
            if not current() or (dialog is not None and not dialog.is_deleted and dialog.value):
                return
            working['value'] = True
            notice.text = '이 회차의 완료된 업로드 기록을 확인하는 중…'
            try:
                copies = await asyncio.to_thread(recovered_review_copies, manager, schedule)
            except (OSError, ValueError, RuntimeError) as error:
                if not panel.is_deleted:
                    notice.text = f'검토본을 찾을 수 없습니다: {error}'
                return
            finally:
                working['value'] = False
            if not current():
                return
            if not copies:
                notice.text = ('이 회차에서 확인된 업로드 영수증이 없습니다. 기존 업로드를 확인하려면 완성본·업로드에서 '
                               '저장된 검토본을 살펴보세요.')
                return
            notice.text = ''
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()
            with ui.dialog() as opened, ui.card().classes('w-full max-w-xl'):
                ui.label('이번 회차에서 비공개 업로드한 검토본').classes('text-lg font-bold')
                ui.label('파일과 YouTube ID를 확인해 이 회차에 연결하세요. 연결 후에는 검토 대기입니다.').classes('text-sm')
                choice = ui.select({path: f'{Path(path).name} · {row["youtube_id"]}' for path, row in copies.items()},
                                   label='완료된 검토본').props('outlined').classes('w-full').bind_enabled_from(
                    working, 'value', lambda value: not value)
                error_label = ui.label().classes('text-sm text-amber-200 break-words').props('role=alert')

                @ui.refreshable
                def selected_link():
                    if row := copies.get(choice.value):
                        video_id = row['youtube_id']
                        ui.link(f'YouTube {video_id}', f'https://www.youtube.com/shorts/{video_id}', new_tab=True)

                selected_link()
                choice.on_value_change(lambda _: selected_link.refresh())

                async def attach():
                    selected = copies.get(choice.value)
                    if not current() or opened.is_deleted or not opened.value or selected is None:
                        return
                    working['value'] = True
                    error_label.text = ''
                    try:
                        await asyncio.to_thread(attach_recovered_review_copy, manager, schedule, selected)
                    except (OSError, ValueError, RuntimeError) as error:
                        if not error_label.is_deleted:
                            error_label.text = f'저장된 검토본 연결 중단: {error}'
                        return
                    finally:
                        working['value'] = False
                    if not panel.is_deleted:
                        opened.close()
                        refresh()
                        safe_notify('저장된 비공개 검토본을 이 회차에 연결했습니다.', type='positive')

                with ui.row().classes('flex-wrap'):
                    ui.button('닫기', on_click=opened.close).props('flat').classes('min-h-[44px]').bind_enabled_from(
                        working, 'value', lambda value: not value)
                    ui.button('선택한 저장 검토본 연결', on_click=attach).props('color=teal').classes(
                        'min-h-[44px]').bind_enabled_from(state, 'is_busy',
                            lambda busy: not busy and not working['value'] and choice.value in copies)
            dialog = opened
            dialog.open()

        ui.button('이 회차의 업로드한 검토본 찾기', on_click=find_copies).props('outline').classes(
            'min-h-[44px]').bind_enabled_from(state, 'is_busy', lambda busy: not busy and not working['value'])
