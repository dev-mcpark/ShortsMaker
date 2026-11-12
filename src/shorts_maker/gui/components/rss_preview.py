"""Free editorial RSS browsing through the existing collector, not paid planning."""

import asyncio
from datetime import datetime, timezone

from nicegui import run, ui

from shorts_maker.gui.components.common.safe_ui import safe_refresh
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.utils.source_manager import SourceManager


def collect_candidates(category):
    return ScriptPlanner.for_rss_discovery()._fetch_rss_feeds(category=category, limit_per_category=None)


def render_rss_preview(state, category, catalog, on_select):
    with ui.column().classes('w-full') as root:
        @ui.refreshable
        def panel():
            snapshot = state.rss_preview
            with ui.expansion('무료 RSS 기사 먼저 보기', icon='rss_feed', value=bool(snapshot)).classes('w-full').props('dark') as view:
                ui.label('최근 RSS 제목·요약을 읽습니다. 모델 평가·본문 분석·각본 생성·승인은 실행하지 않습니다. 일부 피드는 누락될 수 있으며 원문과 날짜를 직접 확인하세요.').classes('text-xs text-slate-300')
                ui.label('분야를 바꾼 뒤 아래 조회를 눌러 갱신하세요. 자동 기획은 이 목록을 그대로 채택하거나 전체를 평가한다는 뜻이 아닙니다.').classes('text-xs text-slate-400')

                async def refresh():
                    if root.is_deleted or view.is_deleted or state.is_busy or state.rss_preview.get('loading'):
                        return
                    selected_category = category()
                    if catalog is None or selected_category not in {'전체 분야', *catalog}:
                        state.rss_preview = {'error': 'RSS 설정·선택 분야를 확인하고 소재·출처에서 복구하세요.'}
                        safe_refresh(panel)
                        return
                    state.rss_preview = {'loading': True, 'category': selected_category}
                    safe_refresh(panel)
                    cancelled = False
                    try:
                        job = asyncio.ensure_future(run.io_bound(collect_candidates, None if selected_category == '전체 분야' else selected_category))
                        while not job.done():
                            try:
                                await asyncio.shield(job)
                            except asyncio.CancelledError:
                                cancelled = True
                            except Exception:
                                break
                        items = job.result()
                        state.rss_preview = {'category': selected_category, 'items': items,
                                             'fetched_at': datetime.now(timezone.utc).isoformat()}
                    except Exception:
                        state.rss_preview = {'category': selected_category,
                                             'error': 'RSS 조회를 완료하지 못했습니다. 피드·네트워크·검토 이력을 확인한 뒤 다시 조회하세요.'}
                    except asyncio.CancelledError:
                        state.rss_preview = {'category': selected_category, 'error': 'RSS 조회가 중단됐습니다. 결과를 다시 조회하세요.'}
                        safe_refresh(panel)
                        raise
                    safe_refresh(panel)
                    if cancelled:
                        raise asyncio.CancelledError

                ui.button('현재 분야 RSS 조회 · 모델 비용 없음', on_click=refresh).classes('min-h-[44px] w-full').props('outline').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and not state.rss_preview.get('loading') and catalog is not None)
                if snapshot.get('loading'):
                    ui.label(f'{snapshot["category"]} 조회 중 · 메뉴를 이동해도 중복 조회하지 않습니다.').classes('text-xs text-amber-200')
                elif snapshot.get('error'):
                    ui.label(snapshot['error']).classes('text-xs text-amber-200')
                elif 'items' in snapshot:
                    ui.label(f'{snapshot["category"]} · {len(snapshot["items"])}건 · 조회 UTC {snapshot["fetched_at"]}').classes('text-xs text-slate-400 break-all')
                    items = {str(i): item for i, item in enumerate(snapshot['items']) if SourceManager.is_allowed_url(item.get('url', ''))}
                    if not items:
                        ui.label('표시할 최근 기사가 없습니다. 날짜·요약·이미 검토한 URL 등 수집 조건이나 피드 오류 때문일 수 있습니다. 다른 분야·직접 URL 입력도 사용할 수 있습니다.').classes('text-xs text-slate-300')
                    else:
                        choice = ui.select({key: f'{item["title"]} · {item["source"]}' for key, item in items.items()},
                                           label='RSS 기사 후보 검색', with_input=True).props('outlined dark').classes('w-full')
                        details = ui.column().classes('w-full')

                        def show():
                            if view.is_deleted or choice.value not in items:
                                return
                            item = items[choice.value]
                            details.clear()
                            with details:
                                ui.label(item['title']).classes('font-bold break-all')
                                ui.label(f'{item["category"]} · {item["source"]} · {item.get("published") or "발행일 미표기"}').classes('text-xs text-slate-400 break-all')
                                ui.label(item.get('content', '')[:300]).classes('text-sm text-slate-300 break-all')
                                ui.link('기사 원문 열기', item['url'], new_tab=True).props('rel="noopener noreferrer"').classes('text-teal-300 break-all')

                        choice.on_value_change(lambda _: show())

                        def select():
                            if (not view.is_deleted and not state.is_busy and state.rss_preview is snapshot
                                    and not snapshot.get('loading') and choice.value in items):
                                on_select(items[choice.value]['url'])

                        ui.button('이 기사를 URL 입력으로 선택', on_click=select).classes('min-h-[44px] w-full').props('color=teal').bind_enabled_from(
                            state, 'is_busy', lambda busy: not busy and choice.value in items)
                        ui.label('선택은 입력만 바꿉니다. 각본 생성하기를 별도로 눌러야 유료 기획이 시작됩니다.').classes('text-xs text-slate-400')
            if snapshot.get('loading'):
                def recover():
                    if root.is_deleted or view.is_deleted:
                        timer.cancel()
                    elif not state.rss_preview.get('loading'):
                        timer.cancel()
                        safe_refresh(panel)
                timer = ui.timer(.3, recover)
        panel()
    return root
