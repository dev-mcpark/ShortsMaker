"""Client-owned local media URLs survive replacement of individual widgets."""

from pathlib import Path
from uuid import uuid4
from urllib.parse import unquote

from nicegui import app, ui


def media_sources(client=None):
    client = client if client is not None else ui.context.client
    urls = {}

    def cleanup():
        for url in urls.values():
            app.remove_route(unquote(url))
        urls.clear()

    client.on_delete(cleanup)

    def source(filename):
        if not filename:
            return ''
        path = Path(filename).resolve()
        if not path.is_file():
            return ''
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        if key not in urls:
            # shortcut: retain this view's URLs until client deletion; bound earlier if sessions grow long.
            urls[key] = app.add_media_file(local_file=path,
                                          url_path=f'/local-media/{uuid4().hex}/{path.name}')
        return urls[key]

    return source
