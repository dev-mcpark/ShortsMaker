"""RSS Sources 관리 탭 컴포넌트"""

from nicegui import ui
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.gui.components.common.card_header import card_with_header
from shorts_maker.utils.source_manager import SourceManager
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)


def render_sources_tab(state: 'AppState') -> None:
    """RSS Sources 탭 렌더링"""
    source_manager = SourceManager()

    with ui.row().classes('w-full h-full gap-6'):
        # === Left Panel: Add & Stats ===
        with ui.column().classes('w-96 min-w-[380px] gap-4'):

            # === Add New Feed Card ===
            with card_with_header('Add RSS Feed', 'add_circle', 'primary'):
                with ui.element('div').classes('p-5'):
                    # Category 입력
                    with ui.column().classes('w-full gap-1 mb-4'):
                        ui.label('Category').classes('text-xs text-gray-400 uppercase tracking-wider')
                        cat_input = ui.input(
                            placeholder='e.g., Technology, Business, AI'
                        ).props('outlined dense dark').classes('w-full')

                    # 인기 카테고리 퀵 버튼
                    ui.label('Quick Select').classes('text-xs text-gray-500 mb-2')
                    with ui.row().classes('w-full flex-wrap gap-2 mb-4'):
                        quick_cats = ['Technology', 'AI', 'Business', 'Science', 'World']
                        for qcat in quick_cats:
                            def set_cat(c=qcat):
                                cat_input.value = c
                            ui.button(qcat, on_click=set_cat).props(
                                'outline dense size=sm color=teal'
                            ).classes('text-xs')

                    # URL 입력
                    with ui.column().classes('w-full gap-1 mb-4'):
                        ui.label('RSS Feed URL').classes('text-xs text-gray-400 uppercase tracking-wider')
                        url_input = ui.input(
                            placeholder='https://example.com/rss.xml'
                        ).props('outlined dense dark').classes('w-full')

                    # 추가 버튼
                    def add_feed():
                        if not cat_input.value:
                            safe_notify('Please enter a category', type='warning')
                            return
                        if not url_input.value:
                            safe_notify('Please enter an RSS URL', type='warning')
                            return

                        source_manager.add_source(cat_input.value, url_input.value)
                        safe_notify(f"✅ Added: {cat_input.value}", type='positive')
                        safe_refresh(sources_list)
                        safe_refresh(stats_card)
                        cat_input.value = ""
                        url_input.value = ""

                    ui.button(
                        'Add Source',
                        on_click=add_feed
                    ).classes('w-full').props('color=teal unelevated icon=add size=lg')

            # === Statistics Card ===
            @ui.refreshable
            def stats_card():
                sources = source_manager.load_sources()
                total_cats = len(sources)
                total_feeds = sum(len(urls) for urls in sources.values())

                with ui.card().classes('w-full p-4 bg-slate-800 border border-slate-600'):
                    with ui.row().classes('items-center gap-2 mb-3'):
                        ui.icon('analytics', size='sm').classes('text-amber-400')
                        ui.label('Statistics').classes('text-sm font-bold text-amber-300')

                    with ui.row().classes('w-full justify-around'):
                        # Categories
                        with ui.column().classes('items-center'):
                            ui.label(str(total_cats)).classes('text-3xl font-bold text-white')
                            ui.label('Categories').classes('text-xs text-gray-400 uppercase')

                        ui.element('div').classes('w-px h-12 bg-slate-600')

                        # Feeds
                        with ui.column().classes('items-center'):
                            ui.label(str(total_feeds)).classes('text-3xl font-bold text-teal-400')
                            ui.label('Feeds').classes('text-xs text-gray-400 uppercase')

            stats_card()

            # === Popular RSS Feeds (추천) ===
            with ui.card().classes('w-full p-4 bg-slate-700 border border-slate-600'):
                with ui.row().classes('items-center gap-2 mb-3'):
                    ui.icon('star', size='sm').classes('text-yellow-400')
                    ui.label('Recommended Feeds').classes('text-sm font-bold text-yellow-300')

                recommended = [
                    ('Technology', 'TechCrunch', 'https://techcrunch.com/feed/'),
                    ('AI', 'MIT Tech Review', 'https://www.technologyreview.com/feed/'),
                    ('Business', 'Reuters', 'https://www.reutersagency.com/feed/'),
                ]

                for cat, name, url in recommended:
                    with ui.row().classes(
                        'w-full items-center justify-between py-2 border-b border-slate-600 last:border-0'
                    ):
                        with ui.column().classes('gap-0'):
                            ui.label(name).classes('text-sm text-white font-medium')
                            ui.label(cat).classes('text-xs text-gray-500')

                        def add_recommended(c=cat, u=url, n=name):
                            source_manager.add_source(c, u)
                            safe_notify(f"✅ Added: {n}", type='positive')
                            safe_refresh(sources_list)
                            safe_refresh(stats_card)

                        ui.button(
                            icon='add',
                            on_click=add_recommended
                        ).props('flat round size=sm color=teal')

        # === Right Panel: Feed List ===
        with ui.column().classes('flex-grow gap-4'):
            # 헤더
            with ui.card().classes('w-full p-0 bg-slate-800 border border-slate-600 overflow-hidden'):
                with ui.element('div').classes('w-full p-4 border-b border-slate-700'):
                    with ui.row().classes('items-center justify-between'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('rss_feed', size='sm').classes('text-orange-400')
                            ui.label('Active Sources').classes('text-lg font-bold text-white')

                        # 새로고침 버튼
                        def refresh_all():
                            safe_refresh(sources_list)
                            safe_refresh(stats_card)
                            safe_notify('🔄 Refreshed', type='info')

                        ui.button(icon='refresh', on_click=refresh_all).props('flat round color=gray')

                @ui.refreshable
                def sources_list():
                    sources = source_manager.load_sources()

                    if not sources:
                        with ui.element('div').classes('p-12'):
                            with ui.column().classes('items-center gap-4'):
                                ui.icon('rss_feed', size='xl').classes('text-slate-600')
                                ui.label('No RSS sources configured').classes('text-lg text-gray-500')
                                ui.label(
                                    'Add your first feed to start discovering content'
                                ).classes('text-sm text-gray-600')
                        return

                    with ui.scroll_area().classes('h-[500px]'):
                        with ui.element('div').classes('p-4 space-y-4'):
                            for category, urls in sources.items():
                                # Category Card
                                with ui.card().classes(
                                    'w-full p-0 bg-slate-700/50 border border-slate-600 overflow-hidden'
                                ):
                                    # Category Header
                                    with ui.element('div').classes(
                                        'w-full p-3 bg-slate-700 border-b border-slate-600'
                                    ):
                                        with ui.row().classes('items-center justify-between'):
                                            with ui.row().classes('items-center gap-2'):
                                                ui.icon('folder', size='xs').classes('text-teal-400')
                                                ui.label(category).classes(
                                                    'text-sm font-bold text-white'
                                                )
                                                ui.badge(str(len(urls))).classes(
                                                    'bg-teal-600 text-white text-xs'
                                                )

                                            # Delete category
                                            def delete_category(c=category):
                                                source_manager.remove_category(c)
                                                safe_notify(f"🗑️ Deleted: {c}", type='warning')
                                                safe_refresh(sources_list)
                                                safe_refresh(stats_card)

                                            ui.button(
                                                icon='delete',
                                                on_click=delete_category
                                            ).props('flat round size=xs color=red')

                                    # Feed URLs
                                    with ui.element('div').classes('p-2'):
                                        for url in urls:
                                            with ui.row().classes(
                                                'w-full items-center gap-2 p-2 hover:bg-slate-600/50 rounded'
                                            ):
                                                ui.icon('link', size='xs').classes('text-gray-500')
                                                ui.label(url[:50] + '...' if len(url) > 50 else url).classes(
                                                    'text-xs text-gray-400 flex-grow truncate'
                                                )

                                                def remove_feed(c=category, u=url):
                                                    source_manager.remove_source(c, u)
                                                    safe_notify('Removed feed', type='info')
                                                    safe_refresh(sources_list)
                                                    safe_refresh(stats_card)

                                                ui.button(
                                                    icon='close',
                                                    on_click=remove_feed
                                                ).props('flat round size=xs color=gray')

                sources_list()
