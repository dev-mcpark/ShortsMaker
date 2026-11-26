"""Preview one retained scene and feed it into the existing validated import callback."""

from types import SimpleNamespace
from nicegui import run, ui

from shorts_maker.gui.components.common.media_preview import media_sources
from shorts_maker.services.existing_scene_clips import APPROVED_FIRST_FRAME, ExistingSceneClips, validate_segment


async def open_existing_scene_picker(script, scene_number, service, current_workspace, on_import, can_select):
    if not can_select():
        return
    reader = ExistingSceneClips(script, scene_number, service, current_workspace)
    media = media_sources(ui.context.client)
    candidates, selected = {}, {}
    loading = {'value': True}
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl bg-slate-900 text-white'):
        ui.label(f'장면 {scene_number} · 기존 영상 찾기').classes('font-bold text-lg')
        ui.label('영상의 움직임이 장면에 맞지 않으면 승인한 첫 프레임을 정지 영상으로 사용할 수 있습니다. 새로 연결하면 현재 작업의 장면 파일이 교체됩니다.').classes('text-xs text-slate-300')
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
                path, identity, duration = await run.io_bound(reader.preview, key, candidates[key])
                if not current() or choice.value != key:
                    return
                selected.update(key=key, identity=identity)
                with preview:
                    ui.label(candidates[key]['label']).classes('text-xs text-slate-300')
                    if key == APPROVED_FIRST_FRAME:
                        ui.image(media(path)).props('fit=contain').classes('w-full max-w-[180px] aspect-[9/16] bg-black')
                    else:
                        ui.video(media(path)).props('controls muted').classes('w-full max-w-[220px] max-h-[360px] bg-black')
                        trim = ui.checkbox('선택한 구간만 연결')
                        trim.bind_enabled_from(loading, 'value', lambda value: not value)
                        with ui.row().classes('w-full flex-wrap').bind_visibility_from(trim, 'value'):
                            start = ui.input('시작 (초)', value='0')
                            end = ui.input('끝 (초)', value=f'{duration:g}')
                            for field in (start, end):
                                field.props('outlined inputmode=decimal maxlength=18').classes(
                                    'w-full sm:w-36').bind_enabled_from(loading, 'value', lambda value: not value)
                        selected.update(trim=trim, start=start, end=end, duration=duration)
                notice.text = ('이 장면은 편집에서 움직임 없이 표시됩니다. 이미지가 내레이션과 맞으면 연결하세요.'
                               if key == APPROVED_FIRST_FRAME else
                               '영상을 끝까지 확인하고 내레이션과 맞으면 이 장면에 연결하세요.')
            except (OSError, ValueError, RuntimeError) as error:
                if current():
                    notice.text = str(error)
            finally:
                loading['value'] = False

        async def connect():
            key = choice.value
            if not current() or loading['value'] or key not in candidates or selected.get('key') != key:
                return
            segment = None
            if selected.get('trim') is not None and selected['trim'].value:
                try:
                    segment = (float(selected['start'].value), float(selected['end'].value))
                    validate_segment(*segment, selected['duration'])
                except (ValueError, TypeError):
                    notice.text = '영상 길이 안에서 시작 시각보다 뒤에 끝 시각을 지정하세요.'
                    return
            loading['value'] = True
            failed = False

            async def read():
                nonlocal failed
                try:
                    if not current():
                        raise ValueError('현재 장면 화면에서 다시 선택하세요.')
                    content = await run.io_bound(reader.read, key, candidates[key], selected['identity'], segment)
                    if not current() or choice.value != key or content is None:
                        raise ValueError('파일을 읽는 동안 작업이 바뀌었습니다. 다시 선택하세요.')
                    return content
                except (OSError, ValueError, RuntimeError) as error:
                    failed = True
                    if current():
                        notice.text = str(error)
                    raise

            try:
                await on_import(SimpleNamespace(file=SimpleNamespace(read=read)))
                if not dialog.is_deleted and not failed:
                    dialog.close()
            finally:
                loading['value'] = False

        with ui.row().classes('w-full flex-wrap'):
            ui.button('닫기', on_click=dialog.close).props('flat').classes('min-h-[44px]')
            ui.button('선택 재료 미리보기', on_click=audition).classes('min-h-[44px]').bind_enabled_from(
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
                       '이 장면에 연결할 보유 영상이나 승인한 첫 프레임이 없습니다. 파일을 직접 연결하려면 비디오 선택을 사용하세요.')
    except (OSError, ValueError, RuntimeError) as error:
        if current():
            notice.text = str(error)
    finally:
        loading['value'] = False
