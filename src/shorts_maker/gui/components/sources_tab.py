"""RSS Sources 관리 탭 컴포넌트 - Google AI Studio 스타일 개편"""
from nicegui import ui
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.utils.source_manager import SourceManager
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)


def render_sources_tab(state: 'AppState') -> None:
    """RSS Sources 탭 렌더링"""
    source_manager = SourceManager()

    # 와이드 2단 레이아웃
    with ui.row().classes('w-full h-full gap-6 bg-slate-950 p-1'):

        # =====================================================================
        # === 1. LEFT PANEL: FEED REGISTRATION & STATS (380px 고정폭) ===
        # =====================================================================
        with ui.column().classes('w-96 min-w-[380px] gap-4 shrink-0'):

            # --- RSS 피드 추가 카드 ---
            with ui.card().classes('w-full p-0 bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-lg'):
                # 카드 헤더
                with ui.element('div').classes('w-full px-5 py-4 bg-slate-900 border-b border-slate-800 flex items-center gap-2.5'):
                    ui.icon('add_circle', size='xs').classes('text-violet-400')
                    ui.label('신규 RSS 피드 연동').classes('text-sm font-bold text-white tracking-wide')

                # 카드 바디
                with ui.column().classes('p-5 w-full gap-4'):
                    # Category 입력
                    with ui.column().classes('w-full gap-1'):
                        ui.label('연동 카테고리').classes('text-[10px] text-slate-500 font-bold uppercase tracking-widest')
                        cat_input = ui.input(
                            placeholder='예: Technology, AI, 경제, 세계 뉴스'
                        ).props('outlined dense dark').classes('w-full text-xs')

                    # 퀵 카테고리 추천 버튼
                    with ui.column().classes('w-full gap-1.5'):
                        ui.label('자주 쓰는 키워드 선택').classes('text-[10px] text-slate-500 font-bold')
                        with ui.row().classes('w-full flex-wrap gap-2'):
                            quick_cats = ['Technology', 'AI', 'Business', 'Science', 'World']
                            for qcat in quick_cats:
                                def make_set_cat_fn(c=qcat):
                                    return lambda: setattr(cat_input, 'value', c)
                                ui.button(qcat, on_click=make_set_cat_fn()).props(
                                    'outline dense size=sm color=violet'
                                ).classes('text-[11px] px-2.5 py-0.5 rounded')

                    # URL 입력
                    with ui.column().classes('w-full gap-1'):
                        ui.label('RSS 피드 XML 주소').classes('text-[10px] text-slate-500 font-bold uppercase tracking-widest')
                        url_input = ui.input(
                            placeholder='https://example.com/rss.xml'
                        ).props('outlined dense dark').classes('w-full text-xs')

                    # 추가 실행 버튼
                    def add_feed():
                        if not cat_input.value:
                            safe_notify('카테고리를 입력해주십시오.', type='warning')
                            return
                        if not url_input.value:
                            safe_notify('RSS 피드 URL 주소를 입력해주십시오.', type='warning')
                            return

                        source_manager.add_source(cat_input.value, url_input.value)
                        safe_notify(f"✅ RSS 소스 추가 성공: {cat_input.value}", type='positive')
                        safe_refresh(sources_list)
                        safe_refresh(stats_card)
                        cat_input.value = ""
                        url_input.value = ""

                    ui.button(
                        'RSS 소스 추가',
                        on_click=add_feed
                    ).classes('w-full font-bold text-xs py-2 bg-gradient-to-r from-violet-600 to-indigo-600').props('unelevated icon=add')

            # --- RSS 통계 상황판 ---
            @ui.refreshable
            def stats_card():
                sources = source_manager.load_sources()
                total_cats = len(sources)
                total_feeds = sum(len(urls) for urls in sources.values())

                with ui.card().classes('w-full p-4 bg-slate-900 border border-slate-800 rounded-xl shadow-md'):
                    with ui.row().classes('items-center gap-2 mb-3 px-1'):
                        ui.icon('analytics', size='xs').classes('text-violet-400')
                        ui.label('RSS 등록 통계').classes('text-xs font-bold text-slate-400 uppercase tracking-widest')

                    with ui.row().classes('w-full justify-around items-center py-2'):
                        # 카테고리 수
                        with ui.column().classes('items-center gap-1'):
                            ui.label(str(total_cats)).classes('text-2xl font-bold text-white font-mono')
                            ui.label('카테고리').classes('text-[10px] text-slate-500 font-semibold uppercase')

                        ui.element('div').classes('w-px h-10 bg-slate-800')

                        # 피드 주소 수
                        with ui.column().classes('items-center gap-1'):
                            ui.label(str(total_feeds)).classes('text-2xl font-bold text-violet-400 font-mono')
                            ui.label('피드 소스').classes('text-[10px] text-slate-500 font-semibold uppercase')

            stats_card()

            # --- 추천 RSS 소스 피드 목록 ---
            with ui.card().classes('w-full p-5 bg-slate-900/60 border border-slate-800/80 rounded-xl'):
                with ui.row().classes('items-center gap-2 mb-3'):
                    ui.icon('star', size='xs').classes('text-violet-400')
                    ui.label('검증된 추천 피드').classes('text-xs font-bold text-slate-400 uppercase tracking-widest')

                recommended = [
                    ('Technology', 'TechCrunch', 'https://techcrunch.com/feed/'),
                    ('AI', 'MIT Tech Review', 'https://www.technologyreview.com/feed/'),
                    ('Business', 'Reuters', 'https://www.reutersagency.com/feed/'),
                ]

                for cat, name, url in recommended:
                    with ui.row().classes(
                        'w-full items-center justify-between py-2 border-b border-slate-800 last:border-0 no-wrap'
                    ):
                        with ui.column().classes('gap-0.5 overflow-hidden'):
                            ui.label(name).classes('text-xs text-white font-semibold')
                            ui.label(cat).classes('text-[10px] text-slate-500')

                        def make_add_rec_fn(c=cat, u=url, n=name):
                            def add_recommended():
                                source_manager.add_source(c, u)
                                safe_notify(f"✅ 추가 완료: {n}", type='positive')
                                safe_refresh(sources_list)
                                safe_refresh(stats_card)
                            return add_recommended

                        ui.button(
                            icon='add',
                            on_click=make_add_rec_fn()
                        ).props('flat round size=xs color=violet').classes('bg-slate-800/80')

        # =====================================================================
        # === 2. RIGHT PANEL: ACTIVE SOURCE LIST (가변폭) ===
        # =====================================================================
        with ui.column().classes('flex-grow gap-4'):

            with ui.card().classes('w-full p-0 bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-lg flex-grow flex flex-col'):
                # 헤더 바
                with ui.element('div').classes('w-full px-5 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900'):
                    with ui.row().classes('items-center gap-2.5'):
                        ui.icon('rss_feed', size='xs').classes('text-violet-400')
                        ui.label('활성화된 RSS 소스 라이브러리').classes('text-sm font-bold text-white tracking-wide')

                    # 새로고침 버튼
                    def refresh_all():
                        safe_refresh(sources_list)
                        safe_refresh(stats_card)
                        safe_notify('🔄 RSS 소스 동기화 완료!', type='info')

                    ui.button(icon='refresh', on_click=refresh_all).props('flat round color=violet size=sm').classes('bg-slate-800/80')

                # 소스 피드 리스트 바디
                @ui.refreshable
                def sources_list():
                    sources = source_manager.load_sources()

                    if not sources:
                        with ui.element('div').classes('w-full py-20 flex-grow flex items-center justify-center'):
                            with ui.column().classes('items-center gap-4'):
                                ui.icon('rss_feed', size='xl').classes('text-slate-700 animate-pulse')
                                ui.label('등록된 RSS 소스가 없습니다').classes('text-base font-bold text-slate-500')
                                ui.label('좌측 추가 패널이나 추천 피드에서 첫 RSS 연동을 시작하십시오.').classes('text-xs text-slate-600')
                        return

                    with ui.scroll_area().classes('w-full flex-grow max-h-[560px]'):
                        with ui.column().classes('p-5 gap-4 w-full'):
                            for category, urls in sources.items():
                                # 카테고리별 디렉토리 카드
                                with ui.card().classes(
                                    'w-full p-0 bg-slate-900/60 border border-slate-800/80 rounded-xl overflow-hidden shadow-sm hover:border-violet-500/20 transition-all duration-300'
                                ):
                                    # 카테고리 헤더
                                    with ui.element('div').classes('w-full px-4 py-3 bg-slate-950/60 border-b border-slate-800 flex items-center justify-between'):
                                        with ui.row().classes('items-center gap-2'):
                                            ui.icon('folder', size='xs').classes('text-violet-400')
                                            ui.label(category).classes('text-xs font-bold text-white')
                                            ui.badge(str(len(urls))).classes('bg-violet-900/30 text-violet-400 text-[10px] border border-violet-500/20 font-bold px-2 py-0.5')

                                        # 카테고리 전체 삭제 버튼
                                        def make_del_cat_fn(c=category):
                                            def delete_category():
                                                source_manager.remove_category(c)
                                                safe_notify(f"🗑️ 카테고리 삭제됨: {c}", type='warning')
                                                safe_refresh(sources_list)
                                                safe_refresh(stats_card)
                                            return delete_category

                                        ui.button(
                                            icon='delete',
                                            on_click=make_del_cat_fn()
                                        ).props('flat round size=xs color=red').classes('bg-slate-900/50')

                                    # 등록된 피드 주소록 목록
                                    with ui.column().classes('p-3 w-full gap-2 bg-slate-900/20'):
                                        for url in urls:
                                            with ui.row().classes(
                                                'w-full items-center justify-between p-2.5 bg-slate-950/40 border border-slate-800/60 hover:bg-slate-900/60 rounded-lg no-wrap transition-colors duration-200'
                                            ):
                                                with ui.row().classes('items-center gap-2 overflow-hidden flex-grow mr-4'):
                                                    ui.icon('link', size='xs').classes('text-slate-500 shrink-0')
                                                    # 긴 URL 말줄임표 처리
                                                    ui.label(url).classes('text-xs text-slate-400 truncate font-mono')

                                                def make_rem_feed_fn(c=category, u=url):
                                                    def remove_feed():
                                                        source_manager.remove_source(c, u)
                                                        safe_notify('RSS 피드 매핑 제거됨', type='info')
                                                        safe_refresh(sources_list)
                                                        safe_refresh(stats_card)
                                                    return remove_feed

                                                ui.button(
                                                    icon='close',
                                                    on_click=make_rem_feed_fn()
                                                ).props('flat round size=xs color=gray').classes('bg-slate-900/50 hover:bg-rose-950/20 shrink-0')

                sources_list()
