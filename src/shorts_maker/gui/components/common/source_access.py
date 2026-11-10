"""Surface damaged source settings without replacing the owner's catalogue."""

from nicegui import ui

from shorts_maker.utils.source_manager import SourceManager


def load_source_catalog(factory=SourceManager):
    try:
        manager = factory()
        return manager, manager.load_sources()
    except (OSError, ValueError) as error:
        ui.label('RSS 소스 설정을 읽지 못했습니다.').classes('text-sm text-amber-200')
        ui.label(str(error)).classes('text-xs text-amber-200 break-all')
        ui.label('원본 파일을 확인한 뒤 목록을 새로고침하거나 이 메뉴를 다시 여세요. '
                 '오류 파일은 자동으로 덮어쓰지 않습니다.').classes('text-xs text-slate-400')
        return None, {}
