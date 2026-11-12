"""Startup identity and explicit read-only comparison; no server/provider action."""

import asyncio
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from nicegui import binding, core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui import runtime_info


class RuntimeIdentityTests(TestCase):
    def test_code_digest_tracks_python_content_names_and_missing_or_unsafe_sources(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                runtime_info.code_digest(root)
            source = root / 'one.py';source.write_text('value=1')
            before = source.read_bytes();first = runtime_info.code_digest(root)
            (root / '.env').write_text('PRIVATE=not-part-of-identity')
            (root / 'notes.txt').write_text('documentation')
            self.assertEqual(runtime_info.code_digest(root), first)
            self.assertEqual(source.read_bytes(), before)
            source.write_text('value=2')
            self.assertNotEqual(runtime_info.code_digest(root), first)
            second = runtime_info.code_digest(root)
            source.rename(root / 'two.py')
            self.assertNotEqual(runtime_info.code_digest(root), second)
            (root / 'link.py').symlink_to(root / 'two.py')
            with self.assertRaises(ValueError):
                runtime_info.code_digest(root)

    def test_capture_is_once_per_process_and_does_not_change_with_later_git_or_source(self):
        with patch.object(runtime_info, '_startup', None), \
                patch.object(runtime_info.subprocess, 'run', side_effect=[SimpleNamespace(stdout='a' * 40), SimpleNamespace(stdout='?? new.py')]) as git, \
                patch.object(runtime_info, 'code_digest', return_value='b' * 64) as digest:
            runtime_info.initialize_runtime()
            original = dict(runtime_info._startup)
            runtime_info.initialize_runtime()
            self.assertEqual(runtime_info._startup, original)
            self.assertEqual(git.call_count, 2)
            digest.assert_called_once()
            self.assertIn('aaaaaaa', runtime_info.runtime_label())
            self.assertTrue(original['dirty'])
            self.assertGreater(original['pid'], 0)
            self.assertIsNotNone(original['started_at'])

    def test_missing_git_timeout_or_unreadable_code_never_claim_current_revision(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired('git', 2)):
            with patch.object(runtime_info, '_startup', None), \
                    patch.object(runtime_info.subprocess, 'run', side_effect=error), \
                    patch.object(runtime_info, 'code_digest', side_effect=OSError()):
                runtime_info.initialize_runtime()
                self.assertIsNone(runtime_info._startup['commit'])
                self.assertIsNone(runtime_info._startup['code_sha256'])
                self.assertIn('확인 불가', runtime_info.runtime_label())


class RuntimeUiTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.object(core, 'loop', asyncio.get_running_loop()))
        self.enterContext(patch.object(runtime_info, '_startup', {
            'pid': 123, 'started_at': '2026-11-12T10:00:00+00:00', 'commit': 'a' * 40,
            'dirty': True, 'code_sha256': 'b' * 64}))
        self.client = Client(page('/runtime-info'));self.addCleanup(self.client.delete)

    def render(self):
        with self.client, ui.column() as root:
            compare = runtime_info.render_runtime_info()
        return root, compare

    def text(self, root):
        return '\n'.join(getattr(e, 'text', '') for e in root.descendants())

    async def test_explicit_compare_reports_equal_changed_and_unknown_without_mutating_startup(self):
        root, compare = self.render();before = dict(runtime_info._startup)
        self.assertIn('Studio 프로세스 · 123', self.text(root))
        self.assertIn('수정 포함', self.text(root))
        for digest, message in [('b' * 64, '같습니다'), ('c' * 64, '다릅니다')]:
            with self.client, patch.object(runtime_info, 'code_digest', return_value=digest):
                await compare()
            self.assertIn(message, self.text(root))
        with self.client, patch.object(runtime_info, 'code_digest', side_effect=OSError()):
            await compare()
        self.assertIn('읽기에 실패', self.text(root))
        self.assertNotIn('같습니다', self.text(root))
        self.assertEqual(runtime_info._startup, before)
        with patch.object(runtime_info, '_startup', None):
            empty, compare = self.render()
            self.assertIsNone(compare)
            self.assertIn('기록하지 않았습니다', self.text(empty))

    async def test_duplicate_or_deleted_comparison_is_read_only_and_late_result_is_ignored(self):
        root, compare = self.render()
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(_):
            entered.set();await release.wait();return 'c' * 64
        with self.client, patch.object(runtime_info.run, 'io_bound', side_effect=delayed) as io:
            task = asyncio.create_task(compare())
            await asyncio.wait_for(entered.wait(), 2)
            binding._refresh_step()
            button = next(e for e in root.descendants() if getattr(e, 'text', '') == '현재 저장 코드와 비교')
            self.assertFalse(button.enabled)
            await compare()
            self.assertEqual(io.call_count, 1)
            root.clear();release.set();await task
            await compare()
            self.assertEqual(io.call_count, 1)
