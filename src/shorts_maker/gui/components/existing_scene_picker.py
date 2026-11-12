"""Preview one retained scene and feed it into the existing validated import callback."""

from types import SimpleNamespace
from nicegui import run, ui

from shorts_maker.gui.components.common.media_preview import media_sources
from shorts_maker.services.existing_scene_clips import ExistingSceneClips


async def open_existing_scene_picker(script, scene_number, service, current_workspace, on_import, can_select):
    if not can_select():
        return
    reader = ExistingSceneClips(script, scene_number, service, current_workspace)
    media = media_sources(ui.context.client)
    candidates, selected = {}, {}
    loading = {'value': True}
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl bg-slate-900 text-white'):
        ui.label(f'장면 {scene_number} · 기존 영상 찾기').classes('font-bold text-lg')
        ui.label('같은 대본·장면의 보유 영상 작업과 승인된 Veo 원본을 표시합니다. 재생 후 연결하면 원본을 보존하고 현재 작업에 사본을 만듭니다.').classes('text-xs text-slate-300')
        notice = ui.label('재사용할 장면을 찾는 중…').classes('text-xs text-amber-200 break-all')
        choice = ui.select({}, label='기존 장면 영상 검색', with_input=True).props('outlined dark clearable').classes('w-full')
        choice.bind_enabled_from(loading, 'value', backward=lambda value: not value)
        preview = ui.column().classes('w-full')

        def current():
            return not dialog.is_deleted and dialog.value and can_select()

        async def audition():
            key = choice.value
            if not current() or loading['value'] or key not in candidates:
                return
            selected.clear();preview.clear();loading['value'] = True
            try:
                path, identity = await run.io_bound(reader.preview, key, candidates[key])
                if not current() or choice.value != key:
                    return
                selected.update(key=key, identity=identity)
                with preview:
                    ui.label(candidates[key]['label']).classes('text-xs text-slate-300')
                    ui.video(media(path)).props('controls muted').classes('w-full max-w-[220px] max-h-[360px] bg-black')
                notice.text = '영상을 끝까지 확인하고 내레이션과 맞으면 이 장면에 연결하세요.'
            except (OSError, ValueError, RuntimeError) as error:
                if current():
                    notice.text = str(error)
            finally:
                loading['value'] = False

        async def connect():
            key = choice.value
            if not current() or loading['value'] or key not in candidates or selected.get('key') != key:
                return
            loading['value'] = True
            async def read():
                if not current():
                    raise ValueError('현재 장면 화면에서 다시 선택하세요.')
                content = await run.io_bound(reader.read, key, candidates[key], selected['identity'])
                if not current() or choice.value != key:
                    raise ValueError('파일을 읽는 동안 작업이 바뀌었습니다. 다시 선택하세요.')
                return content
            try:
                await on_import(SimpleNamespace(file=SimpleNamespace(read=read)))
                if not dialog.is_deleted:
                    dialog.close()
            finally:
                loading['value'] = False

        with ui.row().classes('w-full flex-wrap'):
            ui.button('닫기', on_click=dialog.close).props('flat').classes('min-h-[44px]')
            ui.button('선택 영상 미리보기', on_click=audition).classes('min-h-[44px]').bind_enabled_from(
                loading, 'value', lambda value: not value and choice.value in candidates)
            ui.button('이 장면에 영상 연결', on_click=connect).props('color=teal').classes('min-h-[44px]').bind_enabled_from(
                loading, 'value', lambda value: not value and choice.value in candidates and selected.get('key') == choice.value)
    dialog.open()
    try:
        candidates.update(await run.io_bound(reader.candidates))
        if not current():
            dialog.close();return
        choice.set_options({key: item['label'] for key, item in candidates.items()})
        notice.text = ('파일을 골라 미리 본 뒤 연결하세요. API 호출·원본 판정 변경은 없습니다.' if candidates else
                       '이 장면에 재사용할 저장 영상이 없습니다. 새 파일은 기존 비디오 선택으로 연결하세요.')
    except (OSError, ValueError, RuntimeError) as error:
        if current():
            notice.text = str(error)
    finally:
        loading['value'] = False
