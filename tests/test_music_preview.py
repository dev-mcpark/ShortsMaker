"""Music audition resolves licensed local tracks without changing production state."""

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nicegui import core, ui
from nicegui.client import Client
from nicegui.page import page
from shorts_maker.gui.components import music_preview
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script


class MusicPreviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for target, name, value in ((settings, 'bgm_dir', self.root),
                                    (core, 'loop', asyncio.get_running_loop())):
            p = patch.object(target, name, value);p.start();self.addCleanup(p.stop)
        self.track = self.root / 'calm_fixture.mp3'
        self.track.write_bytes(b'local fixture music')
        self.record = Path(f'{self.track}.license.json')
        self.record.write_text(json.dumps({'title':'Fixture', 'artist':'Test', 'source_url':'https://example.com/music',
                                          'license':'Fixture only', 'attribution_required':False,
                                          'sha256':hashlib.sha256(self.track.read_bytes()).hexdigest()}))
        self.state = AppState(script=script(), bgm_track=self.track.name, bgm_volume=0,
                              final_video_path='kept.mp4', operating_scope={'fixture':'kept'})
        self.state.confirm_script_review()
        self.client = Client(page('/music-audition'))
        self.addCleanup(self.client.delete)
        with self.client:
            music_preview.render_music_preview(self.state)
        self.button = next(e for e in self.client.elements.values() if getattr(e, 'text', '') == '선택 BGM 미리듣기')
        self.handler = next(e.handler for e in self.button._event_listeners.values() if e.type == 'click')

    async def click(self):
        with self.client:
            before = asyncio.all_tasks()
            self.handler(None)
            tasks = asyncio.all_tasks() - before
            if tasks:
                await asyncio.gather(*tasks)

    def audio(self):
        return [e for e in self.client.elements.values() if e.__class__.__name__ == 'Audio']

    def text(self):
        return '\n'.join(getattr(e, 'text', '') for e in self.client.elements.values())

    async def test_exact_track_at_zero_mix_volume_and_busy_does_not_touch_production(self):
        before = self.state.reviewed_script_sha256
        self.state.pipeline_running = True
        with patch.object(self.state, 'new_production_service', side_effect=AssertionError('no service')), \
                patch.object(music_preview.VideoEditor, '_generate_tts', side_effect=AssertionError('no speech')):
            await self.click()
        self.assertEqual(len(self.audio()), 1)
        self.assertIn('calm_fixture.mp3', self.audio()[0].source)
        self.assertIn('원곡 확인용', self.text())
        self.assertEqual(self.state.bgm_volume, 0)
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        self.assertEqual(self.state.reviewed_script_sha256, before)
        self.assertEqual(self.state.operating_scope, {'fixture':'kept'})
        self.assertTrue(self.state.pipeline_running)

    async def test_automatic_mood_uses_editor_rules_and_exact_missing_track_never_falls_back(self):
        self.state.bgm_track = '';self.state.bgm_mood = 'calm'
        await self.click()
        self.assertEqual(len(self.audio()), 1)
        self.state.bgm_track = 'missing.mp3'
        await self.click()
        self.assertEqual(self.audio(), [])
        self.assertIn('미리듣기 불가', self.text())
        self.assertNotIn('음량을 0', self.text())

    async def test_missing_license_or_changed_bytes_clears_old_preview(self):
        await self.click()
        self.track.write_bytes(b'changed bytes')
        await self.click()
        self.assertEqual(self.audio(), [])
        self.assertIn('미리듣기 불가', self.text())
        self.record.unlink()
        await self.click()
        self.assertEqual(self.audio(), [])

    async def test_unresolved_auto_without_script_does_not_guess_music(self):
        self.state.script = None;self.state.bgm_track = '';self.state.bgm_mood = 'auto'
        with patch.object(music_preview, 'VideoEditor') as editor:
            await self.click()
        editor.assert_not_called()
        self.assertIn('대본을 열거나', self.text())
        self.assertEqual(self.audio(), [])

    async def test_duplicate_and_late_changed_selection_cannot_show_another_track(self):
        for failure in (False, True):
            self.state.bgm_track = self.track.name
            started, release = asyncio.Event(), asyncio.Event()
            async def read(function, *args):
                started.set();await release.wait()
                if failure:
                    raise ValueError('old request failure')
                return str(self.track)
            with patch.object(music_preview.run, 'io_bound', side_effect=read) as reader:
                task = asyncio.create_task(self.click())
                await asyncio.wait_for(started.wait(), 2)
                await self.click()
                self.assertEqual(reader.call_count, 1)
                self.state.bgm_track = 'new.mp3'
                release.set();await task
            self.assertEqual(self.audio(), [])
            self.assertIn('바뀌었습니다', self.text())
            self.assertNotIn('미리듣기 불가', self.text())

    async def test_deleted_view_ignores_late_result_and_old_button(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def read(function, *args):
            started.set();await release.wait();return str(self.track)
        with patch.object(music_preview.run, 'io_bound', side_effect=read) as reader:
            task = asyncio.create_task(self.click())
            await asyncio.wait_for(started.wait(), 2)
            self.button.parent_slot.parent.delete()
            release.set();await task
            await self.click()
            self.assertEqual(reader.call_count, 1)
        self.assertEqual(self.audio(), [])
