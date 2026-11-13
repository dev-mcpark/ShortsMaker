"""Explicit local audition uses the same licensed-track resolution as editing."""

from pathlib import Path

from nicegui import run, ui

from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.gui.components.common.media_preview import media_sources


def render_music_preview(state):
    media_source = media_sources()
    loading = False

    def selection():
        return (state.bgm_track, state.bgm_mood,
                state.script.model_dump_json() if state.script else None)

    with ui.column().classes('w-full gap-1') as view:
        async def audition():
            nonlocal loading
            if loading or view.is_deleted:
                return
            loading = True
            expected = selection()
            area.clear()
            notice.text = '사용 권한과 선택한 곡을 확인 중…'
            try:
                if not state.bgm_track and state.bgm_mood in (None, '', 'auto') and state.script is None:
                    raise ValueError('대본을 열거나 곡·분위기를 먼저 선택하세요.')
                # Audition the original even at mix volume zero; never create a production service.
                editor = VideoEditor(bgm_mood=state.bgm_mood, bgm_track=state.bgm_track or None, bgm_volume=1)
                try:
                    path = await run.io_bound(editor.preflight_music, state.script)
                except ValueError as error:
                    raise ValueError('선택 조건에 맞는 사용 허가 음원이 없습니다. 곡을 다시 선택해 주세요.') from error
                if view.is_deleted:
                    return
                if selection() != expected:
                    notice.text = '음악 설정이나 대본이 바뀌었습니다. 미리듣기를 다시 불러오세요.'
                    return
                source = media_source(path)
                if not source:
                    raise ValueError('음악 파일을 읽을 수 없습니다. 곡을 다시 확인하세요.')
                with area:
                    ui.label(f'불러온 원곡 · {Path(path).name}').classes('text-xs text-slate-300 break-all')
                    ui.audio(source).props('controls').classes('w-full')
                notice.text = '원곡 확인용입니다. 설정 변경 후 다시 불러오세요. 내레이션과 섞인 최종 음량은 완성본에서 확인하세요.'
            except (OSError, ValueError, RuntimeError) as error:
                if not view.is_deleted:
                    notice.text = (f'미리듣기 불가: {error}' if selection() == expected else
                                   '음악 설정이나 대본이 바뀌었습니다. 미리듣기를 다시 불러오세요.')
            finally:
                loading = False

        ui.button('선택 BGM 미리듣기', on_click=audition).props('flat icon=headphones').classes('w-full min-h-[44px]')
        notice = ui.label('무료 로컬 재생 · 설정 변경 후 다시 눌러 곡을 불러오세요.').classes('text-xs text-slate-400 break-all').props('role=status')
        area = ui.column().classes('w-full gap-1')
