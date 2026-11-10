"""Explicit save/reopen controls for unfinished script and first-frame text work."""

from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.services.work_drafts import saved_work_drafts


def render_work_drafts_panel(state, on_restored):
    opened = {'value': False}
    @ui.refreshable
    def panel():
        key = state.script_editor_key()
        with ui.expansion('저장된 작업 초안', icon='save_as', value=opened['value'],
                          on_value_change=lambda event: opened.update(value=event.value)).classes('w-full'):
            ui.label('미완성 JSON과 첫 프레임 경로·검토 메모를 사본당 2 MiB까지 보관합니다. 입력만으로 자동 저장되지는 않습니다.').classes('text-xs text-slate-300')
            ui.label('열기 전 현재/대상 대본의 미적용 입력도 새 초안으로 보관합니다. 복원 후에는 대본·장면 확인을 다시 진행하세요.').classes('text-xs text-slate-400')

            def current():
                if state.is_busy or key != state.script_editor_key():
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
                state, 'is_busy', lambda busy: not busy and (state.script is not None or bool(state.script_editor_text().strip())))
            try:
                records, warnings = saved_work_drafts()
            except (ValueError, OSError) as error:
                records, warnings = {}, [str(error)]
            for warning in warnings[:3]:
                ui.label(warning).classes('text-xs text-amber-200 break-all')
            if records:
                choice = ui.select({name: record['label'] for name, record in records.items()},
                                   label='저장된 작업 초안 검색', with_input=True).props('outlined dark clearable').classes('w-full')

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
