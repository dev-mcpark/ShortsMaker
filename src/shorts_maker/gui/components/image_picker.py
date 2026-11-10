"""Choose an existing library image for the normal first-frame preview/review path."""

from pathlib import Path

from nicegui import run, ui

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.services.asset_library import AssetLibrary


async def open_image_picker(on_select, can_select):
    if not can_select():
        safe_notify('작업 중이거나 장면이 바뀌었습니다. 현재 장면을 다시 확인하세요.', type='warning')
        return
    library = AssetLibrary()
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl bg-slate-900 text-white'):
        ui.label('보관함에서 첫 프레임 찾기').classes('text-lg font-bold')
        ui.label('파일을 선택하면 장면의 검토 후보로 미리 봅니다. 선택은 승인이 아니며 API를 호출하지 않습니다.').classes('text-sm text-slate-300')
        message = ui.label('이미지 목록 조회 중…').classes('text-xs text-amber-200 break-all')
        choice = ui.select({}, label='이미지 파일 검색', with_input=True).props('outlined dark clearable').classes('w-full')

        def select():
            if not dialog.value or not can_select():
                safe_notify('작업 중이거나 장면이 바뀌었습니다. 현재 장면을 다시 확인하세요.', type='warning')
                return
            try:
                path = library.preview(choice.value or '')
                if path.suffix.lower() not in {'.png', '.jpg', '.jpeg'}:
                    raise ValueError('PNG/JPEG 이미지를 선택하세요.')
                on_select(str(path))
                dialog.close()
            except (OSError, ValueError) as error:
                safe_notify(f'이미지를 선택할 수 없습니다: {error}', type='warning')

        with ui.row().classes('w-full flex-wrap'):
            ui.button('취소', on_click=dialog.close).props('flat')
            ui.button('선택 이미지 미리보기', on_click=select).props('color=teal').bind_enabled_from(
                choice, 'value', lambda value: bool(value))
    dialog.open()
    try:
        snapshot = await run.io_bound(library.scan)
        if dialog.is_deleted or not dialog.value or not can_select():
            dialog.close()
            return
        options = {row['id']: f'{row["id"]} · {row["bytes"] / 1048576:.1f} MiB'
                   for row in snapshot['rows'] if row['kind'] == '이미지' and not row['id'].startswith('logs/')
                   and Path(row['id']).suffix.lower() in {'.png', '.jpg', '.jpeg'}}
        choice.set_options(options)
        message.text = ('파일명·폴더명으로 검색하세요. 20 MB 이하, 세로 9:16 이미지만 첫 프레임으로 사용할 수 있습니다.'
                        if options else '보관함에 PNG/JPEG 이미지가 없습니다. 생성한 후보나 기존 이미지 경로를 사용할 수 있습니다.')
        if snapshot['warnings']:
            message.text += ' 일부 보관함 기록을 읽지 못했습니다. 재료 보관함에서 경고를 확인하세요.'
    except (OSError, ValueError, RuntimeError) as error:
        if not dialog.is_deleted:
            message.text = f'목록을 불러올 수 없습니다: {error}'
