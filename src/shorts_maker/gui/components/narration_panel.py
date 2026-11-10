"""Select and audition a retained narration set without buying new speech."""

from nicegui import ui

from shorts_maker.gui.components.common.media_preview import media_sources
from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.services.prepared_narration import list_narration_sets


def render_narration_panel(state):
    if state.script is None:
        return
    media_source = media_sources(ui.context.client)
    rendered_script = state.script.model_dump_json()

    @ui.refreshable
    def panel():
        with ui.expansion('내레이션 · 기존 음성 재사용', icon='graphic_eq',
                          value=bool(state.prepared_narration_manifest)).classes('w-full bg-slate-900').props('dark'):
            ui.label('현재 내레이션과 모든 장면의 기록·파일 해시가 일치하는 세트만 표시합니다. 연결 전에 소리·길이도 검사합니다.').classes('text-xs text-slate-300')
            options = {'': '선택하세요', **list_narration_sets(state.script)}
            choice = ui.select(options, value=state.prepared_narration_manifest if state.prepared_narration_manifest in options else '',
                               label='준비된 내레이션 세트').props('dark outlined').classes('w-full')
            choice.bind_enabled_from(state, 'is_busy', lambda busy: not busy)

            def select(use_prepared=True):
                if not state.script or state.script.model_dump_json() != rendered_script:
                    safe_notify('각본이 변경됐습니다. 현재 제작 화면에서 음성을 다시 선택하세요.', type='warning')
                    return
                try:
                    if use_prepared and not choice.value:
                        raise ValueError('연결할 내레이션 세트를 선택하세요.')
                    state.select_prepared_narration(choice.value if use_prepared else None)
                    safe_notify('기존 음성을 연결했습니다. 새 음성 API 호출이 없습니다.' if use_prepared else '다음 편집에서 새 음성을 생성합니다.', type='positive')
                    safe_refresh(panel)
                except (OSError, ValueError, TypeError) as error:
                    safe_notify(f'음성 연결 실패: {error}', type='negative')

            with ui.row():
                ui.button('이 음성 세트 연결', on_click=lambda: select()).bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and bool(choice.value))
                ui.button('새 음성 생성으로 전환', on_click=lambda: select(False)).props('flat').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and bool(state.prepared_narration_manifest))
                ui.button('음성 목록 새로고침', on_click=lambda: safe_refresh(panel)).props('flat').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy)
            if state.prepared_narration_manifest:
                try:
                    paths = state.prepared_audio_paths()
                    ui.label('기존 음성 사용 · 우측 음색 설정으로 재생성하지 않습니다. 새 비주얼 API 비용은 별도입니다.').classes('text-xs text-teal-300')
                    for scene, path in zip(state.script.scenes, paths):
                        ui.label(f'장면 {scene.scene_number} · {scene.script_text}').classes('text-xs text-slate-300')
                        ui.audio(media_source(path)).props('controls').classes('w-full')
                except (OSError, ValueError, TypeError) as error:
                    ui.label(f'연결한 음성을 다시 확인하세요: {error}').classes('text-xs text-amber-300')
            else:
                ui.label('현재 선택: 새 음성 생성 · 편집 시 API 비용이 발생합니다. 목록에 없는 음성은 연결하지 않습니다.').classes('text-xs text-amber-200')
    panel()
    return panel
