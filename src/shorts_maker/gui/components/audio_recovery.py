"""Explicit, backup-first recovery for a saved script's unavailable audio settings."""

import copy
import json

from nicegui import ui
from shorts_maker.gui.components.common.safe_ui import safe_notify


def render_audio_recovery(state, on_recovered):
    with ui.column().classes('w-full rounded border border-amber-700 p-2 gap-2').bind_visibility_from(
            state, 'audio_recovery', bool) as view:
        ui.label('저장된 음성·음악 설정 복구').classes('text-sm text-amber-200')
        ui.label().bind_text_from(state, 'audio_recovery', lambda record:
                                 f'대상 대본 · {record["script"]["title"]}' if record else '').classes('text-xs break-all')
        ui.label('불러오기 실패로 현재 작업은 변경되지 않았습니다. 원래 설정을 사본으로 남긴 뒤 대본을 열 수 있습니다.').classes('text-xs text-slate-300')

        def work():
            return json.dumps([state.script_editor_key(), state.script_editor_text(), state.first_frame_drafts,
                               state.execution_key(), state.reviewed_script_sha256, state.final_video_path,
                               state.prepared_narration_manifest, state._editor_options(), state.planning_input(),
                               state.manual_video_mode, state.manual_script_id], sort_keys=True)

        def open_repair():
            if view.is_deleted or state.is_busy or not state.audio_recovery:
                return
            expected = copy.deepcopy(state.audio_recovery)
            opened = work()
            with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg bg-slate-900 text-white'):
                ui.label('음성·음악 설정 복구').classes('text-lg font-bold')
                ui.label(expected['script']['title']).classes('text-sm break-all')
                ui.label('현재 대본과 수정 입력, 원래 설정 파일을 먼저 사본으로 보관합니다. '
                         '기본 음성 Alloy·음악 음량0으로 설정하고 저장된 내레이션 연결을 해제합니다. '
                         '보유 음성·음악 파일과 승인/제외 기록은 지우지 않습니다.').classes('text-sm')
                ui.label('이 작업은 API를 호출하지 않습니다. 대본 확인과 보유 음성 재연결부터 진행하세요. '
                         '음성을 연결하지 않고 나중에 편집하면 새 TTS 비용이 발생합니다. 회차 연결은 유지됩니다.').classes('text-sm text-amber-200')
                ui.label('현재 음성·음악 선택은 작업 초안 사본에 포함되지 않습니다. 필요하면 취소 후 각본별 음성·음악 설정을 먼저 저장하세요.').classes('text-xs text-slate-300')

                def confirm():
                    if dialog.is_deleted or not dialog.value or view.is_deleted:
                        return
                    try:
                        if work() != opened:
                            raise ValueError('현재 작업이 바뀌었습니다. 복구 창을 다시 열어 주세요.')
                        backup = state.recover_audio_choices(expected)
                        dialog.close()
                        safe_notify(f'설정을 복구했습니다. 원본 사본: {backup.name}. 대본·음성을 다시 확인하세요.', type='positive')
                        try:
                            on_recovered()
                        except RuntimeError:
                            pass  # A deleted result view cannot undo the saved recovery.
                    except (OSError, ValueError, TypeError) as error:
                        safe_notify(f'설정 복구 중단: {error}', type='negative')
                with ui.row().classes('flex-wrap'):
                    ui.button('취소', on_click=dialog.close).props('flat').classes('min-h-[44px]')
                    ui.button('사본 보관 후 설정 복구·대본 열기', on_click=confirm).props('color=amber').classes('min-h-[44px]')
            dialog.open()
        ui.button('음성·음악 설정 복구 방법', on_click=open_repair).props('flat color=amber').classes(
            'w-full min-h-[44px]').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
