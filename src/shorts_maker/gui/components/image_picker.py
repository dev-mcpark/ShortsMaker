"""Choose or import an image for the normal first-frame preview/review path."""

import asyncio
from pathlib import Path

from nicegui import run, ui

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.services.asset_library import AssetLibrary
from shorts_maker.services.visual_review import import_frame, MAX_FRAME_BYTES


async def open_image_picker(on_select, can_select):
    if not can_select():
        safe_notify('작업 중이거나 장면이 바뀌었습니다. 현재 장면을 다시 확인하세요.', type='warning')
        return
    library = AssetLibrary()
    importing = False
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl bg-slate-900 text-white'):
        ui.label('첫 프레임 이미지 선택').classes('text-lg font-bold')
        ui.label('파일을 선택하면 장면의 검토 후보로 미리 봅니다. 선택은 승인이 아니며 API를 호출하지 않습니다.').classes('text-sm text-slate-300')
        ui.label('내 컴퓨터의 PNG/JPEG는 보관함에 새 사본으로 저장합니다. 20 MB 이하, 최소360×640의 세로9:16 이미지를 선택하세요.').classes('text-xs text-slate-400')
        message = ui.label('이미지 목록 조회 중…').classes('text-xs text-amber-200 break-all')
        import_error = ui.label('').classes('text-xs text-red-300 break-all').props('role=alert')
        choice = ui.select({}, label='이미지 파일 검색', with_input=True).props('outlined dark clearable').classes('w-full')

        async def upload(event):
            nonlocal importing
            owns_import = False
            try:
                if importing or dialog.is_deleted or not dialog.value or not can_select():
                    safe_notify('작업 중이거나 장면이 바뀌었습니다. 현재 장면을 다시 확인하세요.', type='warning')
                    return
                importing = owns_import = True
                import_error.text = ''
                content = await event.file.read()
                if dialog.is_deleted or not dialog.value or not can_select():
                    return
                job = asyncio.create_task(asyncio.to_thread(import_frame, content))
                cancelled = False
                while not job.done():
                    try:
                        await asyncio.shield(job)
                    except asyncio.CancelledError:
                        cancelled = True
                    except Exception:
                        break
                if cancelled:
                    job.exception()
                    raise asyncio.CancelledError
                path = job.result()
                if dialog.is_deleted or not dialog.value or not can_select():
                    safe_notify('이미지는 보관함에 저장했습니다. 장면이 바뀌어 자동 연결하지 않았습니다.', type='warning')
                    return
                on_select(str(path))
                dialog.close()
            except (OSError, ValueError, RuntimeError) as error:
                if not dialog.is_deleted:
                    import_error.text = f'이미지 가져오기 실패: {error}'
                safe_notify(f'이미지 가져오기 실패: {error}', type='negative')
            finally:
                if owns_import:
                    importing = False
                sender = getattr(event, 'sender', None)
                if sender is not None and not sender.is_deleted:
                    sender.reset()

        ui.upload(label='내 컴퓨터에서 이미지 가져오기', on_upload=upload, auto_upload=True,
                  max_file_size=MAX_FRAME_BYTES,
                  on_rejected=lambda: safe_notify('20 MB 이하의 PNG/JPEG 파일을 선택하세요.', type='warning')).props(
                      'accept=".png,.jpg,.jpeg" flat bordered').classes(
                          'w-full [&_.q-btn]:min-h-[44px] [&_.q-btn]:min-w-[44px]')

        def select():
            if importing or dialog.is_deleted or not dialog.value or not can_select():
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
            ui.button('취소', on_click=dialog.close).props('flat').classes('min-h-[44px]')
            ui.button('선택 이미지 미리보기', on_click=select).props('color=teal').classes('min-h-[44px]').bind_enabled_from(
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
                        if options else '보관함에 PNG/JPEG 이미지가 없습니다. 위에서 내 컴퓨터의 이미지를 가져올 수 있습니다.')
        if snapshot['warnings']:
            message.text += ' 일부 보관함 기록을 읽지 못했습니다. 재료 보관함에서 경고를 확인하세요.'
    except (OSError, ValueError, RuntimeError) as error:
        if not dialog.is_deleted:
            message.text = f'목록을 불러올 수 없습니다: {error}'
