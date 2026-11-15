"""One explicit notice across the current video's scenes, using the existing editor."""

from nicegui import ui


def render_screen_notice(state):
    with ui.expansion('화면 안내 문구', icon='label').classes('w-full'):
        field = ui.input('전체 장면 안내 문구', value=state.screen_notice,
                         placeholder='예: 설명용 개념 모형').props('outlined dark maxlength=20 clearable').classes('w-full')

        def changed(event):
            if field.is_deleted:
                return
            if state.is_busy:
                field.value = state.screen_notice
                return
            state.screen_notice = event.value or ''

        field.on_value_change(changed)
        field.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)
        ui.label('20자 이내 · 모든 장면 왼쪽 위에 표시합니다. 비워 두면 추가하지 않습니다. '
                 '완성본에 적용하려면 다시 편집하세요.').classes('text-xs text-slate-300')
        ui.label('이 문구는 현재 서버 세션 설정입니다. 음성·음악 설정이나 작업 초안에 저장되지 않으므로 '
                 '재시작 후 재편집할 때 다시 입력하세요.').classes('text-xs text-amber-200')
