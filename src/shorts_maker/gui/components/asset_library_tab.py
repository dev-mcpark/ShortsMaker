"""Local materials, previews and explicit cleanup without provider calls."""

from datetime import datetime
from uuid import uuid4

from nicegui import app, ui

from shorts_maker.gui.state.session_manager import SessionManager
from shorts_maker.services.asset_library import AssetLibrary, MEDIA


def format_bytes(size: int) -> str:
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if size < 1024 or unit == 'TiB':
            return f'{size:.1f} {unit}'
        size /= 1024


def render_asset_library_tab(state) -> None:
    library = AssetLibrary(
        busy=lambda: state.is_busy or any(s.is_busy for s in SessionManager._sessions.values()),
        active_references=lambda: [
            {'video': s.final_video_path, 'clips': s.generated_clips,
             'script': s.script.model_dump(mode='json') if s.script else None}
            for s in SessionManager._sessions.values()
        ],
    )
    snapshot = {'rows': []}
    preview_url = None

    def clear_preview():
        nonlocal preview_url
        preview.clear()
        if preview_url:
            app.remove_route(preview_url)
            preview_url = None

    ui.context.client.on_delete(lambda: app.remove_route(preview_url) if preview_url else None)
    with ui.column().classes('w-full min-w-0 gap-3'):
        ui.label('재료 보관함').classes('text-xl font-bold text-white')
        ui.label('영상·이미지·음성의 위치와 크기를 확인하고, 필요 없는 정리 후보만 선택해 삭제합니다.').classes('text-slate-300')
        summary = ui.label().classes('text-sm text-teal-200')
        folder_sizes = ui.label().classes('text-xs text-slate-300 break-all')
        warnings = ui.label().classes('text-sm text-amber-300 whitespace-pre-wrap break-all')
        ui.label('원본·대본·승인·비용 기록과 업로드된 영상은 보존합니다. 사용처가 있는 파일은 정리를 막습니다. '
                 '파일 크기 합계는 실제 디스크 회수량과 다를 수 있습니다.').classes('text-xs text-slate-400')
        with ui.row().classes('w-full items-center gap-2'):
            search = ui.input('파일명·경로 검색').props('outlined dark clearable').classes('w-full sm:w-64')
            folder = ui.select(['전체', *library.roots], value='전체', label='폴더').props('outlined dark').classes('w-36')
            kind = ui.select(['전체', *dict.fromkeys(MEDIA.values()), '기록·기타', '링크'],
                             value='전체', label='종류').props('outlined dark').classes('w-36')
            only_cleanable = ui.checkbox('정리 후보만 보기').props('aria-label="정리 후보만 보기 · 목록 필터"')
            ui.button('새로고침', on_click=lambda: refresh()).props('flat color=grey-4').classes('min-h-[44px]')

        columns = [
            {'name': 'id', 'label': '폴더 / 파일', 'field': 'id', 'align': 'left', 'sortable': True,
             'classes': 'whitespace-normal break-all', 'style': 'max-width:360px; min-width:180px'},
            {'name': 'kind', 'label': '종류', 'field': 'kind', 'align': 'left'},
            {'name': 'bytes', 'label': '크기', 'field': 'bytes', 'sortable': True, ':format': 'value => (value / 1048576).toFixed(2) + " MiB"'},
            {'name': 'updated', 'label': '수정일', 'field': 'updated', 'sortable': True},
            {'name': 'reason', 'label': '정리 상태 / 사용처', 'field': 'reason', 'align': 'left',
             'classes': 'whitespace-normal break-all', 'style': 'max-width:320px; min-width:180px'},
        ]
        table = ui.table(columns=columns, rows=[], row_key='id', selection='multiple', pagination=15).props(
            'dark flat bordered wrap-cells').classes('w-full min-w-0')
        table.add_slot('header-selection', '''
            <q-checkbox v-model="props.selected" aria-label="표 전체 파일 선택" />
        ''')
        table.add_slot('body-selection', '''
            <q-checkbox v-model="props.selected" :aria-label="'파일 선택: ' + props.row.id" />
        ''')

        def show_preview():
            nonlocal preview_url
            if len(table.selected) != 1:
                ui.notify('미리 볼 파일을 하나만 선택하세요.', type='warning')
                return
            try:
                path = library.preview(table.selected[0]['id'])
                clear_preview()
                url_path = f'/asset-preview/{uuid4().hex}'
                preview_url = (app.add_static_file(local_file=path, url_path=url_path)
                               if MEDIA[path.suffix.lower()] == '이미지'
                               else app.add_media_file(local_file=path, url_path=url_path))
                with preview:
                    ui.label(table.selected[0]['id']).classes('text-xs break-all text-slate-300')
                    if MEDIA[path.suffix.lower()] == '이미지':
                        ui.image(preview_url).classes('w-full max-w-lg')
                    elif MEDIA[path.suffix.lower()] == '영상':
                        ui.video(preview_url).props('controls preload=metadata').classes('w-full max-w-lg max-h-[65vh]')
                    else:
                        ui.audio(preview_url).classes('w-full max-w-lg')
            except (OSError, ValueError) as error:
                ui.notify(str(error), type='warning')

        def review_delete():
            try:
                plan = library.prepare_delete([r['id'] for r in table.selected])
            except (OSError, ValueError) as error:
                ui.notify(str(error), type='warning')
                return
            with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl bg-slate-900 text-white'):
                ui.label(f"{len(plan['files'])}개 · {format_bytes(plan['bytes'])} 영구 삭제 확인").classes('text-lg font-bold')
                ui.label('휴지통을 거치지 않으며 복구할 수 없습니다. 제작·비용 기록은 남고, 선택한 미디어 파일만 삭제합니다.')
                with ui.column().classes('w-full max-h-64 overflow-auto'):
                    for item in plan['files']:
                        ui.label(f"{item['id']} · {format_bytes(item['bytes'])}").classes('text-sm break-all')
                confirm = ui.checkbox('선택한 파일의 영구 삭제를 확인했습니다')

                def delete_confirmed():
                    if not confirm.value:
                        return
                    try:
                        result = library.delete(plan)
                        ui.notify(f"삭제된 파일 크기: {format_bytes(result['deleted_bytes'])} · "
                                  + ('완료' if result['state'] == 'deleted' else '일부 실패 — 삭제 기록 확인'),
                                  type='positive' if result['state'] == 'deleted' else 'warning')
                    except (OSError, ValueError) as error:
                        ui.notify(f'정리를 중단했습니다: {error} · 일부 삭제 여부는 삭제 기록과 새 목록을 확인하세요.', type='negative')
                    finally:
                        dialog.close()
                        refresh()

                with ui.row():
                    ui.button('취소', on_click=dialog.close).props('flat')
                    ui.button('선택 파일 영구 삭제', on_click=delete_confirmed).props('color=red').bind_enabled_from(confirm, 'value')
            dialog.open()

        with ui.row().classes('w-full gap-2'):
            ui.button('선택 파일 미리보기', on_click=show_preview).props('outline color=teal').classes('min-h-[44px]')
            ui.button('선택 파일 정리 검토', on_click=review_delete).props('outline color=red').classes('min-h-[44px]')
        preview = ui.column().classes('w-full min-w-0')

        def apply_filter():
            query = (search.value or '').casefold()
            table.selected = []
            table.rows = [{**r, 'updated': datetime.fromtimestamp(r['mtime']).strftime('%Y-%m-%d %H:%M')}
                          for r in snapshot['rows']
                          if (query in r['id'].casefold() and (folder.value == '전체' or r['folder'] == folder.value)
                              and (kind.value == '전체' or r['kind'] == kind.value)
                              and (not only_cleanable.value or r['cleanable']))]
            table.pagination['page'] = 1
            table.update()

        def refresh():
            nonlocal snapshot
            clear_preview()
            snapshot = library.scan()
            summary.set_text(f"{len(snapshot['rows'])}개 · 합계 {format_bytes(snapshot['bytes'])} · "
                             f"정리 후보 {format_bytes(snapshot['cleanable_bytes'])} · 디스크 여유 {format_bytes(snapshot['free_bytes'])}")
            folder_sizes.set_text(' · '.join(
                f"{group} {format_bytes(sum(r['bytes'] for r in snapshot['rows'] if r['folder'] == group))}"
                for group in library.roots))
            messages = snapshot['warnings'][:5]
            if snapshot['blocked']:
                messages = ['검사 오류 또는 제작·미확인 실행이 있어 삭제를 보류합니다.', *messages]
            elif not snapshot['cleanable_bytes']:
                messages = ['현재 정리 후보가 없습니다. 사용처·업로드·최근 임시 파일 보호 사유를 확인하세요.']
            warnings.set_text('\n'.join(messages))
            apply_filter()

        for control in (search, folder, kind, only_cleanable):
            control.on_value_change(lambda _: apply_filter())
        refresh()
