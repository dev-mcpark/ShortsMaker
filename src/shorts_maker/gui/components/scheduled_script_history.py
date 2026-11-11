"""Browse retained run/script versions without resuming or editing an episode."""

import json
from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.services.operating_status import schedule_sha256
from shorts_maker.services.scheduled_script_history import script_versions


def render_script_history_browser(state, manager, runs):
    available = {str(index): run for index, run in enumerate(runs)
                 if run.get('last_script') is not None or run.get('script_revisions')}
    with ui.column().classes('w-full p-4 gap-2') as panel:
        if not available:
            ui.label('보관된 전체 대본이 있는 회차가 없습니다. 요약 기록으로 대본을 재구성하지 않습니다.').classes('text-xs text-slate-400')
            return
        choice = ui.select({key: f'{run["name"]} · 회차 {run.get("run_count", "?")} · '
                           f'{(run["last_script"].get("title") if isinstance(run.get("last_script"), dict) else "대본 확인 필요")} · {run.get("last_run", "시각 기록 없음")}'
                           for key, run in available.items()}, label='회차 대본 검색', with_input=True).props(
                               'outlined dark clearable').classes('w-full')

        def preview():
            try:
                if choice.value not in available or panel.is_deleted:
                    raise ValueError('대본을 확인할 회차를 선택하세요.')
                selected = available[choice.value]
                expected = schedule_sha256(selected)
                identity = tuple(selected.get(k) for k in ('schedule_id', 'run_count', 'last_episode_id', 'last_run'))

                def current():
                    matches = [run for run in manager.get_execution_history()
                               if tuple(run.get(k) for k in ('schedule_id', 'run_count', 'last_episode_id', 'last_run')) == identity]
                    if panel.is_deleted or len(matches) != 1 or schedule_sha256(matches[0]) != expected:
                        raise ValueError('회차 기록이 바뀌었습니다. 목록을 다시 열어 주세요.')
                    return matches[0]

                versions = script_versions(current())
                if not versions:
                    raise ValueError('이 회차에는 보관된 전체 대본이 없습니다.')
                def work_identity():
                    return json.dumps([state.script_editor_key(), state.script_editor_text(), state.first_frame_drafts,
                                       state.execution_key(), state.reviewed_script_sha256, state.final_video_path,
                                       state.prepared_narration_manifest, state._editor_options(),
                                       state.manual_video_mode, state.manual_script_id], sort_keys=True)
                opened_work = work_identity()
            except (ValueError, OSError, TypeError) as error:
                safe_notify(f'대본 이력 확인 중단: {error}', type='warning')
                return

            with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl bg-slate-900 text-white'):
                ui.label(f'{selected["name"]} · 회차 {selected.get("run_count", "?")} 대본 이력').classes('text-lg font-bold')
                ui.label('기록은 읽기 전용입니다. 사본 열기는 회차 재개·이전 버전 복원·승인·API 호출을 실행하지 않습니다.').classes('text-sm text-slate-300')
                version = ui.select({str(index): row['label'] for index, row in enumerate(versions)},
                                    value='0', label='보관된 대본 버전').props('outlined dark').classes('w-full')

                @ui.refreshable
                def details():
                    if version.value not in {str(i) for i in range(len(versions))}:
                        return
                    script = versions[int(version.value)]['script']
                    ui.label(script.title).classes('font-bold')
                    ui.label('출처: ' + ' · '.join([script.source_url, *script.supporting_source_urls])).classes('text-xs break-all text-slate-300')
                    with ui.scroll_area().classes('w-full h-64'):
                        for scene in script.scenes:
                            ui.label(f'장면 {scene.scene_number} · {scene.script_text}').classes('text-sm mt-3')
                            ui.label(f'화면: {scene.visual_description}').classes('text-xs text-slate-300')
                            ui.label(f'움직임: {scene.motion_instruction or "고정 카메라"}').classes('text-xs text-slate-400')
                details()
                version.on_value_change(lambda _: safe_refresh(details))
                ui.label('사본을 열기 전 현재 대본·미적용 입력과 대상 대본의 변경 입력을 작업 초안으로 보관합니다. '
                         '성공하면 현재 완성본·음성 선택을 해제하고 대본 확인부터 진행합니다. 파일은 삭제하지 않습니다.').classes('text-xs text-amber-200')
                if state.operating_scope:
                    ui.label('현재 회차 연결은 유지됩니다. 다른 회차 제작으로 자동 전환되지 않습니다.').classes('text-xs text-amber-200')

                def open_copy():
                    if dialog.is_deleted or not dialog.value:
                        return
                    try:
                        current()
                        if state.is_busy or work_identity() != opened_work:
                            raise ValueError('현재 작업이 바뀌었거나 진행 중입니다. 이력 창을 다시 열어 주세요.')
                        if version.value not in {str(i) for i in range(len(versions))}:
                            raise ValueError('보관된 대본 버전을 선택하세요.')
                        backups = state.open_historical_script(versions[int(version.value)]['script'])
                        dialog.close()
                        safe_notify(f'검토용 사본을 열었습니다. 기존 입력 {len(backups)}개 초안 보관 · 제작 작업실에서 대본을 다시 확인하세요.', type='positive')
                    except (ValueError, OSError, RuntimeError) as error:
                        safe_notify(f'대본 사본 열기 중단: {error}', type='warning')

                with ui.row().classes('w-full flex-wrap'):
                    ui.button('닫기', on_click=dialog.close).props('flat').classes('min-h-[44px]')
                    ui.button('선택 대본을 작업실에서 검토', on_click=open_copy).props('color=teal').classes('min-h-[44px]').bind_enabled_from(
                        state, 'is_busy', backward=lambda value: not value)
            dialog.open()

        ui.button('선택 회차 대본 이력 보기', on_click=preview).props('flat icon=history').classes('min-h-[44px]')
