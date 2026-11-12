"""Free RSS choice precedes and never invokes paid planning."""

import asyncio
from datetime import datetime, timezone
from email.utils import format_datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from nicegui import binding, core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components import planning_tab, rss_preview
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script


ARTICLE = {'title': '<b>기존 다리 설계 변경</b>', 'source': 'City', 'category': 'City',
           'published': 'Today', 'content': '원문을 먼저 확인할 RSS 단서입니다.', 'url': 'https://example.com/story'}


class FreeDiscoveryTests(TestCase):
    def test_real_collector_uses_no_paid_constructor_and_preserves_catalogue_history(self):
        with TemporaryDirectory() as directory:
            root = Path(directory);source = root / 'feeds.json';history = root / 'history.json'
            source.write_text(json.dumps({'City': ['https://example.com/feed']}));history.write_text('[]')
            before = source.read_bytes(), history.read_bytes()
            date = format_datetime(datetime.now(timezone.utc), usegmt=True)
            xml = f'<rss version="2.0"><channel><title>City</title><item><title>Bridge</title><link>https://example.com/story</link><pubDate>{date}</pubDate><description>{"source summary " * 20}</description></item></channel></rss>'.encode()
            response = SimpleNamespace(is_redirect=False, content=xml, raise_for_status=lambda: None)
            with patch.object(settings, 'rss_sources_file', source), patch.object(settings, 'url_history_file', history), \
                    patch.object(settings, 'openai_api_key', ''), patch.object(settings, 'paid_production_enabled', False), \
                    patch.object(ScriptPlanner, '__init__', side_effect=AssertionError('paid planner constructed')), \
                    patch('shorts_maker.planner.script_planner.httpx.get', return_value=response) as get:
                items = rss_preview.collect_candidates('City')
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['url'], ARTICLE['url'])
            get.assert_called_once()
            self.assertEqual(before, (source.read_bytes(), history.read_bytes()))


class RssPreviewUiTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.object(core, 'loop', asyncio.get_running_loop()))
        temporary = TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.enterContext(patch.object(settings, 'output_dir', Path(temporary.name) / 'outputs'))
        self.enterContext(patch.object(settings, 'scripts_dir', Path(temporary.name) / 'scripts'))
        self.enterContext(patch.object(settings, 'paid_production_enabled', False))
        self.client = Client(page('/rss-preview'));self.addCleanup(self.client.delete)
        self.state = AppState(script=script(), final_video_path='keep.mp4')
        self.state.confirm_script_review()
        self.handlers = {}
        self.original_button = ui.button
        def button(text=None, **kwargs):
            if kwargs.get('on_click'):
                self.handlers[text] = kwargs['on_click']
            return self.original_button(text, **kwargs)
        self.enterContext(patch.object(rss_preview.ui, 'button', side_effect=button))
        self.selected = Mock()

    def render(self, category='City', catalog=None):
        with self.client, ui.column() as root:
            rss_preview.render_rss_preview(self.state, lambda: category, {'City': []} if catalog is None else catalog, self.selected)
        return root

    async def fetch(self, result=None, error=None):
        with self.client, patch.object(rss_preview.run, 'io_bound', new=AsyncMock(return_value=[ARTICLE] if result is None else result, side_effect=error)):
            await self.handlers['현재 분야 RSS 조회 · 모델 비용 없음']()
        await asyncio.sleep(0);binding._refresh_step()

    def text(self, root):
        return '\n'.join(getattr(e, 'text', '') for e in root.descendants())

    async def test_select_is_explicit_plain_text_and_preserves_applied_work(self):
        root = self.render();original = self.state.script.model_dump_json(), self.state.reviewed_script_sha256
        scope = self.state.operating_scope = {'episode_id': 'unchanged'}
        await self.fetch(result=[ARTICLE, {**ARTICLE, 'url': 'javascript:alert(1)'}])
        choice = next(e for e in root.descendants() if e._props.get('label') == 'RSS 기사 후보 검색')
        self.assertEqual(len(choice.options), 1)
        self.selected.assert_not_called()
        with self.client:
            choice.set_value('0')
            self.state.pipeline_running = True
            self.handlers['이 기사를 URL 입력으로 선택']()
            self.selected.assert_not_called()
            self.state.pipeline_running = False
            self.handlers['이 기사를 URL 입력으로 선택']()
        self.selected.assert_called_once_with(ARTICLE['url'])
        self.assertIn(ARTICLE['title'], self.text(root))
        link = next(e for e in root.descendants() if getattr(e, 'text', '') == '기사 원문 열기')
        self.assertEqual(link._props['rel'], 'noopener noreferrer')
        self.assertEqual((self.state.script.model_dump_json(), self.state.reviewed_script_sha256), original)
        self.assertEqual(self.state.final_video_path, 'keep.mp4')
        self.assertFalse(self.state.is_busy)
        self.assertIs(self.state.operating_scope, scope)

    async def test_empty_failure_removed_category_and_stale_choice_never_select(self):
        root = self.render()
        await self.fetch(result=[])
        self.assertIn('표시할 최근 기사가 없습니다', self.text(root))
        await self.fetch()
        old_choice = next(e for e in root.descendants() if e._props.get('label') == 'RSS 기사 후보 검색')
        with self.client:
            old_choice.set_value('0')
        old_select = self.handlers['이 기사를 URL 입력으로 선택']
        await self.fetch(error=RuntimeError('feed unavailable'))
        self.assertIn('조회를 완료하지 못했습니다', self.text(root))
        with self.client:
            old_select()
        self.selected.assert_not_called()
        await self.fetch(error=KeyError('unexpected collector failure'))
        self.assertNotIn('loading', self.state.rss_preview)
        self.assertIn('조회를 완료하지 못했습니다', self.text(root))
        root = self.render(category='Removed')
        await self.fetch()
        self.assertIn('설정·선택 분야를 확인', self.text(root))
        self.selected.assert_not_called()

    async def test_loading_reentry_dedup_and_cancel_wait_for_the_same_read_job(self):
        root = self.render();entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(*_):
            entered.set();await release.wait();return [ARTICLE]
        with self.client, patch.object(rss_preview.run, 'io_bound', side_effect=delayed) as io:
            task = asyncio.create_task(self.handlers['현재 분야 RSS 조회 · 모델 비용 없음']())
            await asyncio.wait_for(entered.wait(), 2)
            again = self.render()
            await self.handlers['현재 분야 RSS 조회 · 모델 비용 없음']()
            self.assertEqual(io.call_count, 1)
            task.cancel();await asyncio.sleep(0)
            self.assertTrue(self.state.rss_preview['loading'])
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertNotIn('loading', self.state.rss_preview)
        with self.client:
            root.clear();again.clear()
        result = self.render()
        self.assertIn('1건', self.text(result))
        self.assertEqual(self.state.final_video_path, 'keep.mp4')

    async def test_planning_source_inputs_and_preview_survive_view_reopen_without_planning(self):
        self.state.rss_preview = {'items': [ARTICLE], 'category': 'City', 'fetched_at': 'fixture'}
        def render():
            with self.client, ui.column() as root, patch.object(planning_tab, 'load_source_catalog', return_value=(object(), {'City': []})):
                planning_tab.render_planning_tab(self.state)
            return root
        root = render()
        choice = next(e for e in root.descendants() if e._props.get('label') == 'RSS 기사 후보 검색')
        with self.client:
            choice.set_value('0')
            self.handlers['이 기사를 URL 입력으로 선택']()
        self.assertEqual(self.state.planning_source_mode, '직접 URL 입력')
        self.assertEqual(self.state.planning_url, ARTICLE['url'])
        self.assertEqual(self.state.final_video_path, 'keep.mp4')
        with self.client:
            old_url = next(e for e in root.descendants() if e._props.get('label') == '기사 URL')
            root.clear()
            old_url.set_value('https://example.com/stale-input')
        again = render()
        field = next(e for e in again.descendants() if e._props.get('label') == '기사 URL')
        self.assertEqual(field.value, ARTICLE['url'])
        self.assertIsNone(self.state.production_service)
        self.assertTrue(self.state.is_script_reviewed())
