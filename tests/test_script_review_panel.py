"""Existing paid evidence is readable without repurchasing or inheriting a verdict."""

import asyncio
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace

from nicegui import binding, core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components import script_review_panel
from shorts_maker.gui.components.planning_tab import render_planning_tab
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services.script_reviews import MAX_BYTES, read_script_reviews
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.planner.script_validator import ValidationResult
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script


class ReviewFixture:
    def setUp(self):
        temp = TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.scripts = self.root / 'scripts'
        self.reviews = self.scripts / 'reviews';self.reviews.mkdir(parents=True)
        override = patch.object(settings, 'scripts_dir', self.scripts)
        override.start();self.addCleanup(override.stop)
        self.script = script('Matched review')

    def write(self, name, candidate=None, verdict=False):
        candidate = candidate or self.script
        source = 'A bus. This is the provided excerpt.'
        data = candidate.model_dump()
        request = {'script': data, 'script_json_sha256': hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            'source_excerpt': source, 'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'validator_model': 'recorded-model'}
        path = self.reviews / f'{name}.request.json'
        path.write_text(json.dumps(request))
        if verdict is not None:
            self.verdict_path(name).write_text(json.dumps({'is_valid': verdict, 'score': 65,
                'reason': 'missing_visual_proof' if not verdict else 'valid',
                'feedback': '장면 1에서 앞쪽 전체 공간이 보이지 않습니다.', 'is_advertising': False}))
        return path

    def verdict_path(self, name):
        return self.reviews / f'{name}.verdict.json'


class ScriptReviewTests(ReviewFixture, unittest.TestCase):
    def test_reads_actual_planner_retention_format_after_rejection_without_another_validation(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock();planner.script_output_dir = str(self.scripts)
        planner.validator = SimpleNamespace(validate_script=AsyncMock(return_value=ValidationResult(
            is_valid=False, score=65, reason='missing_visual_proof', feedback='실제 저장 형식의 피드백')))
        self.assertIsNone(asyncio.run(planner._validate_and_save(self.script, {'content': 'A bus.'})))
        result = read_script_reviews(self.script)
        self.assertEqual(len(result['records']), 1)
        self.assertEqual(result['records'][0]['verdict']['feedback'], '실제 저장 형식의 피드백')
        self.assertEqual(result['records'][0]['source_excerpt'], 'A bus.')
        planner.validator.validate_script.assert_awaited_once()

    def test_all_exact_attempts_remain_read_only_and_edits_do_not_inherit_old_pass(self):
        self.write('rejected');self.write('passed', verdict=True);self.write('interrupted', verdict=None)
        self.write('other', self.script.model_copy(update={'title': 'Different'}), verdict=True)
        before = {p.name: p.read_bytes() for p in self.reviews.iterdir()}
        with patch('shorts_maker.planner.script_validator.ScriptValidator.__init__', side_effect=AssertionError('No client')):
            result = read_script_reviews(self.script)
        self.assertEqual(len(result['records']), 3)
        self.assertEqual([r['verdict']['is_valid'] for r in result['records'] if r['verdict']], [True, False])
        self.assertEqual(next(r['state'] for r in result['records'] if r['name'].startswith('interrupted')), 'missing')
        for changed in (self.script.model_copy(update={'title': 'Edited'}), self.script.model_copy(update={'source_url': 'https://example.com/new'})):
            self.assertEqual(read_script_reviews(changed), {'records': [], 'unreadable': []})
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.reviews.iterdir()})

    def test_bad_request_hash_source_size_and_paths_are_not_reported_as_absence_or_pass(self):
        path = self.write('changed')
        data = json.loads(path.read_text());data['script']['title'] = 'Tampered';path.write_text(json.dumps(data))
        path = self.write('source');data = json.loads(path.read_text());data['source_excerpt'] += 'bad';path.write_text(json.dumps(data))
        (self.reviews/'oversized.request.json').write_bytes(b' ' * (MAX_BYTES + 1))
        (self.reviews/'broken.request.json').write_text('{')
        (self.reviews/'linked.request.json').symlink_to(self.write('original'))
        result = read_script_reviews(self.script)
        self.assertEqual(len(result['unreadable']), 5)
        self.assertEqual([r['name'] for r in result['records']], ['original.request.json'])
        self.assertEqual(result['records'][0]['state'], 'completed')

    def test_missing_invalid_and_error_verdicts_never_become_success(self):
        for name, content in [('broken', '{'), ('badtype', '{"is_valid":"false"}'), ('null', 'null')]:
            self.write(name);self.verdict_path(name).write_text(content)
        self.write('link');self.verdict_path('link').unlink();self.verdict_path('link').symlink_to(self.root/'absent')
        self.write('error');self.verdict_path('error').write_text(json.dumps({'is_valid': False, 'reason': 'validation_error'}))
        result = read_script_reviews(self.script)
        self.assertEqual({r['name']: r['state'] for r in result['records']}, {
            'broken.request.json': 'unreadable', 'badtype.request.json': 'unreadable',
            'null.request.json': 'unreadable', 'link.request.json': 'unreadable', 'error.request.json': 'error'})

    def test_missing_folder_is_empty_but_unreadable_or_linked_folder_requires_attention(self):
        self.reviews.rmdir()
        self.assertEqual(read_script_reviews(self.script), {'records': [], 'unreadable': []})
        self.reviews.symlink_to(self.root)
        with self.assertRaises(ValueError):
            read_script_reviews(self.script)
        self.reviews.unlink();self.reviews.write_text('not a folder')
        with self.assertRaises(OSError):
            read_script_reviews(self.script)


class ScriptReviewPanelTests(ReviewFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        loop = patch.object(core, 'loop', asyncio.get_running_loop());loop.start();self.addCleanup(loop.stop)
        self.client = Client(page('/script-review'))
        self.addCleanup(self.client.delete)
        self.state = AppState(script=self.script, final_video_path='existing-final.mp4')
        self.state.confirm_script_review()

    def render(self):
        with self.client, ui.column() as root:
            refresh = script_review_panel.render_script_review_panel(self.state)
        return root, refresh

    def text(self, root):
        return '\n'.join(str(getattr(e, 'text', '')) for e in root.descendants())

    async def refresh(self, refresh):
        with self.client:
            await refresh()
        await asyncio.sleep(0)
        binding._refresh_step()

    async def test_native_verdict_source_warning_and_manual_review_remain_separate(self):
        self.write('rejected');self.write('pending', verdict=None)
        (self.reviews/'bad.request.json').write_text('null')
        root, refresh = self.render();await self.refresh(refresh)
        text = self.text(root)
        for part in ('장면 1에서 앞쪽 전체 공간', 'missing_visual_proof', 'recorded-model',
                     'A bus. This is the provided excerpt.', '재요청하지', '현재 대본과의 일치 여부', '5,000자'):
            self.assertIn(part, text)
        self.assertTrue(self.state.is_script_reviewed())
        self.assertEqual(self.state.final_video_path, 'existing-final.mp4')
        self.state.remember_script_draft(self.state.script_editor_key(), '{incomplete')
        await self.refresh(refresh)
        self.assertIn('미적용 수정은 포함하지', self.text(root))
        self.assertEqual(self.state.script_editor_text(), '{incomplete')

    async def test_read_failure_clears_old_pass_and_retry_has_no_matching_record(self):
        self.write('pass', verdict=True)
        root, refresh = self.render();await self.refresh(refresh)
        self.assertIn('판정 코드: valid', self.text(root))
        with patch.object(script_review_panel, 'read_script_reviews', side_effect=OSError('denied')):
            await self.refresh(refresh)
        self.assertNotIn('판정 코드: valid', self.text(root))
        self.assertIn('읽을 수 없습니다', self.text(root))
        self.verdict_path('pass').unlink();(self.reviews/'pass.request.json').unlink()
        await self.refresh(refresh)
        self.assertIn('정확히 일치하는 모델 검토 기록이 없습니다', self.text(root))

    async def test_concurrent_changed_script_and_deleted_view_do_not_publish_late_result(self):
        root, refresh = self.render()
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(*args):
            entered.set();await release.wait()
            return {'records': [], 'unreadable': ['late.request.json']}
        with patch.object(script_review_panel.asyncio, 'to_thread', side_effect=delayed) as reader:
            with self.client:
                task = asyncio.create_task(refresh())
                await entered.wait();await refresh()
                self.assertEqual(reader.call_count, 1)
                self.state.script = self.script.model_copy(update={'title': 'New script'})
                binding._refresh_step()
                panel = next(e for e in root.descendants() if type(e).__name__ == 'Expansion')
                self.assertFalse(panel.visible)
                release.set();await task
            self.assertNotIn('late.request.json', self.text(root))
        self.state.script = self.script
        root, refresh = self.render()
        entered.clear();release.clear()
        with patch.object(script_review_panel.asyncio, 'to_thread', side_effect=delayed):
            with self.client:
                task = asyncio.create_task(refresh());await entered.wait()
                root.clear();release.set();await task
        self.assertEqual(len(list(root.descendants())), 0)

    async def test_planning_exposes_panel_without_automatic_disk_reads_or_client(self):
        with self.client, ui.column() as root, patch.object(script_review_panel, 'read_script_reviews') as reader:
            render_planning_tab(self.state)
        self.assertIn('저장된 모델 검토 기록 조회', self.text(root))
        reader.assert_not_called()
