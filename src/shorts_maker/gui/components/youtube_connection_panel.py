"""Upload authorization can be checked/reconnected without producing or uploading media."""

from html import escape

from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_notify


def render_youtube_connection_panel(state):
    connection = state.get_youtube_connection()
    with ui.expansion('YouTube 업로드 연결', icon='vpn_key', value=connection.running).classes('w-full mb-4') as panel:
        ui.label().bind_text_from(connection, 'message').props('role=status aria-live=polite').classes('text-sm text-slate-200')
        ui.label().bind_text_from(connection, 'checked_at', lambda stamp: f'마지막 확인 {stamp}' if stamp else '').classes('text-xs text-slate-400')
        ui.label('계정 연결만 진행합니다. 영상 제작·업로드나 일정 재개는 실행하지 않습니다.').classes('text-xs text-slate-400')
        ui.label('연결할 때 Studio가 실행 중인 Mac의 브라우저에서 기존 채널 계정과 YouTube 업로드 권한을 확인하세요. 로그인 창을 닫으면 대기 취소를 누르세요. 최대 대기는 5분입니다.').classes('text-xs text-slate-400')

        async def connect(interactive):
            if state.is_busy or panel.is_deleted:
                safe_notify('현재 작업이 끝난 뒤 업로드 계정을 확인하세요.', type='warning')
                return
            await connection.run(interactive=interactive)
            safe_notify(connection.message, type='info')

        with ui.row().classes('w-full flex-wrap gap-2'):
            ui.button('저장된 인증 확인', on_click=lambda: connect(False)).props('flat icon=verified_user').style('min-height:44px').bind_enabled_from(
                state, 'is_busy', lambda busy: not busy)
            ui.button('업로드 계정 연결', on_click=lambda: connect(True)).props('outline icon=login').style('min-height:44px').bind_enabled_from(
                state, 'is_busy', lambda busy: not busy)
            ui.button('인증 대기 취소', on_click=lambda: connection.cancel() if not panel.is_deleted else None).props('flat color=amber').style('min-height:44px').bind_visibility_from(connection, 'running')
        # The service allowlists Google's URL; escaping keeps it inside this fixed link attribute.
        ui.html(sanitize=False).bind_content_from(
            connection, 'authorization_url',
            lambda url: (f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer" style="display:inline-flex;align-items:center;min-height:44px">'
                         '로그인 창 직접 열기 ↗</a>') if url else '').classes('text-sm text-blue-300')
        ui.label('확인 결과는 현재 시점 기준입니다. Google 동의·토큰 만료 후에는 다시 연결이 필요할 수 있습니다.').classes('text-xs text-slate-400')
