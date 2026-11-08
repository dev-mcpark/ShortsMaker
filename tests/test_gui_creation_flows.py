"""Offline callback regressions: no NiceGUI server, paid clients or browser needed."""

import ast
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from shorts_maker.gui.state.app_state import AppState
from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.services import raw_review
from shorts_maker.services.production_service import ProductionPhase
from shorts_maker.services.visual_review import approve_first_frame, inspect_frame
from shorts_maker.utils.config import settings

COMPONENTS = Path(__file__).resolve().parents[1] / 'src/shorts_maker/gui/components'


def script(title='A'):
    return ShortsScript(title=title, description='Sourced', tags=[], mood='calm', style='explainer',
                        source_name='Source', source_url='https://example.com/story', generation_mode='video',
                        scenes=[VideoScene(scene_number=1, visual_description='One bus', script_text='A bus.')])


def callback(filename, name, environment):
    tree = ast.parse((COMPONENTS / filename).read_text())
    names = {'apply_script', name}
    functions = [node for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])), filename, 'exec'), environment)
    return environment[name]


def planning_environment(state, service):
    return {'state': state, 'source_mode': SimpleNamespace(value='RSS 자동 발견'),
            'url_input': SimpleNamespace(value=''), 'category_select': SimpleNamespace(value='전체 분야'),
            'spinner': SimpleNamespace(visible=False), 'safe_notify': Mock(), 'logger': Mock(),
            'update_script_preview': Mock(), 'update_candidates_panel': Mock(),
            'editor_area': SimpleNamespace(value=''), 'feedback_section': SimpleNamespace(visible=False),
            'regen_counter_label': SimpleNamespace(text=''), 'ShortsScript': ShortsScript, 'json': json}


class CreationCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_only_edit_stops_before_clearing_saved_result(self):
        state = AppState(script=script(), final_video_path='reviewed-final.mp4', generated_clips=['old.mp4'])
        state.confirm_script_review()
        state.new_production_service = Mock()
        preview = SimpleNamespace(visible=True)
        env = {'state': state, 'safe_notify': Mock(), 'rendered_script': state.script.model_dump_json(),
               'settings': SimpleNamespace(paid_production_enabled=False),
               'injected_video_player': preview, 'injected_placeholder': SimpleNamespace(visible=False)}
        tree = ast.parse((COMPONENTS / 'generation_tab.py').read_text())
        production = next(node for node in ast.walk(tree)
                          if isinstance(node, ast.AsyncFunctionDef) and node.name == '_run_production_core')
        wrapper = ast.parse('def factory():\n video_player = injected_video_player\n placeholder_content = injected_placeholder\n return _run_production_core\n')
        wrapper.body[0].body.insert(-1, production)
        exec(compile(ast.fix_missing_locations(wrapper), 'generation_tab.py', 'exec'), env)
        await env['factory']()({1: 'local.mp4'})
        self.assertEqual(state.final_video_path, 'reviewed-final.mp4')
        self.assertEqual(state.generated_clips, ['old.mp4'])
        self.assertFalse(state.is_busy)
        self.assertTrue(preview.visible)
        state.new_production_service.assert_not_called()

    async def test_planning_double_click_submits_once_and_clears_busy(self):
        release = asyncio.Event()
        calls = []

        async def generate(**kwargs):
            calls.append(kwargs)
            await release.wait()
            return None, None

        service = SimpleNamespace(generate_script=generate, progress=SimpleNamespace(error=''), PAID_WORK_DISABLED='off')
        state = AppState()
        def get_service():
            self.assertFalse(state.is_busy)
            return service
        state.get_or_create_service = get_service
        env = planning_environment(state, service)
        generate_script = callback('planning_tab.py', 'generate_script', env)
        first = asyncio.create_task(generate_script())
        await asyncio.sleep(0)
        second = asyncio.create_task(generate_script())
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(len(calls), 1)
        self.assertFalse(state.pipeline_running)

    async def test_successful_new_draft_invalidates_old_video_but_retains_audio_choices(self):
        newer = script('B')
        service = SimpleNamespace(generate_script=Mock(), progress=SimpleNamespace(error=''), PAID_WORK_DISABLED='off')

        async def generate(**kwargs):
            return newer, None

        service.generate_script = generate
        state = AppState(script=script(), final_video_path='old.mp4', generated_clips=['old.png'],
                         tts_voice='nova', bgm_track='chosen.mp3', bgm_volume=.18)
        state.get_or_create_service = lambda: service
        env = planning_environment(state, service)
        with patch('shorts_maker.services.audio_choices.load_audio_choices', return_value=None):
            await callback('planning_tab.py', 'generate_script', env)()
        self.assertIs(state.script, newer)
        self.assertIsNone(state.final_video_path)
        self.assertEqual(state.generated_clips, [])
        self.assertEqual((state.tts_voice, state.bgm_track, state.bgm_volume), ('nova', 'chosen.mp3', .18))
        self.assertFalse(state.pipeline_running)

    async def test_json_apply_is_blocked_during_production_or_upload(self):
        for busy_field in ('pipeline_running', 'youtube_upload_in_progress'):
            with self.subTest(busy_field=busy_field):
                original = script()
                state = AppState(script=original, final_video_path='old.mp4')
                setattr(state, busy_field, True)
                env = planning_environment(state, None)
                env['editor_area'].value = script('B').model_dump_json()
                callback('planning_tab.py', 'save_script', env)()
                self.assertIs(state.script, original)
                self.assertEqual(state.final_video_path, 'old.mp4')

    async def test_regeneration_submits_once_and_preserves_context(self):
        entered, release = asyncio.Event(), asyncio.Event()
        context = SimpleNamespace(attempt_count=0, max_attempts=3, candidates=[])
        calls = []
        newer = script('B')

        async def regenerate(**kwargs):
            calls.append(kwargs)
            entered.set()
            await release.wait()
            context.attempt_count += 1
            return newer

        service = SimpleNamespace(regenerate_script=regenerate, progress=SimpleNamespace(error=''), PAID_WORK_DISABLED='off')
        state = AppState(script=script(), script_context=context, final_video_path='old.mp4', tts_voice='nova')
        def get_service():
            self.assertFalse(state.is_busy)
            return service
        state.get_or_create_service = get_service
        env = planning_environment(state, service)
        env['feedback_input'] = SimpleNamespace(value='Clarify the story')
        regenerate_script = callback('planning_tab.py', 'regenerate_with_feedback', env)
        with patch('shorts_maker.services.audio_choices.load_audio_choices', return_value=None):
            first = asyncio.create_task(regenerate_script())
            await entered.wait()
            await regenerate_script()
            release.set()
            await first
        self.assertEqual(len(calls), 1)
        self.assertIs(state.script, newer)
        self.assertIs(state.script_context, context)
        self.assertIsNone(state.final_video_path)
        self.assertEqual(state.tts_voice, 'nova')
        self.assertFalse(state.pipeline_running)

    async def test_planning_exception_releases_busy_state(self):
        async def generate(**kwargs):
            raise RuntimeError('provider failed')

        state = AppState()
        service = SimpleNamespace(generate_script=generate)
        state.get_or_create_service = lambda: service
        env = planning_environment(state, service)
        await callback('planning_tab.py', 'generate_script', env)()
        self.assertFalse(state.pipeline_running)
        self.assertFalse(env['spinner'].visible)

    async def test_manual_upload_never_maps_old_bytes_into_new_script(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def read():
            entered.set()
            await release.wait()
            return b'clip-A'

        state = AppState(script=script(), manual_script_id='script_A')
        exporter = SimpleNamespace(save_uploaded_clip=Mock(), all_clips_ready=Mock(return_value=False))
        env = {'scene_num': 1, 'state': state, 'exporter': exporter, 'safe_notify': Mock(),
               'render_manual_panel': Mock(), 'start_edit_btn': None, 'scene_cards_container': None,
               'logger': Mock()}
        handler = callback('generation_tab.py', 'make_upload_handler', env)()
        task = asyncio.create_task(handler(SimpleNamespace(file=SimpleNamespace(read=read))))
        await entered.wait()
        state.script, state.manual_script_id = script('B'), 'script_B'
        release.set()
        await task
        exporter.save_uploaded_clip.assert_not_called()
        env['render_manual_panel'].assert_not_called()

    async def test_raw_generation_acquires_current_service_before_locking(self):
        state = AppState(script=script())
        state.confirm_script_review()
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def generate(*args, **kwargs):
            calls.append(kwargs)
            self.assertTrue(state.pipeline_running)
            entered.set()
            await release.wait()
            return 'saved.mp4'

        service = SimpleNamespace(generate_review_clip=generate)
        def get_service():
            self.assertFalse(state.is_busy)
            return service
        state.get_or_create_service = get_service
        env = {'state': state, 'index': 0, 'refresh': Mock(), 'reserve': .12,
               'displayed_frame': {'sha256': 'reviewed-frame'},
               'rendered_script': state.script.model_dump_json(), 'safe_notify': Mock(), 'logger': Mock()}
        generate_clip = callback('generation_tab.py', 'generate', env)
        first = asyncio.create_task(generate_clip())
        await entered.wait()
        await generate_clip()
        release.set()
        await first
        self.assertEqual(len(calls), 1)
        self.assertFalse(state.pipeline_running)

    async def test_review_actions_cannot_replace_bindings_during_a_run(self):
        state = AppState(script=script(), pipeline_running=True)
        env = {'state': state, 'scene': state.script.scenes[0], 'path_input': SimpleNamespace(value='frame.png'),
               'must_show': None, 'must_avoid': None, 'reviewer_note': None,
               'previewed': {}, 'status_label': None, 'scene_panel': Mock(), 'safe_notify': Mock(),
               'approve_first_frame': Mock(), 'rendered_script': state.script.model_dump_json()}
        callback('generation_tab.py', 'approve', env)()
        env['approve_first_frame'].assert_not_called()
        env = {'state': state, 'index': 0, 'note': SimpleNamespace(value='Reviewed'),
               'refresh': Mock(), 'safe_notify': Mock(), 'save_raw_verdict': Mock(),
               'rendered_script': state.script.model_dump_json()}
        callback('generation_tab.py', 'decide', env)('approved')
        env['save_raw_verdict'].assert_not_called()

    async def test_stale_raw_panel_cannot_approve_another_script(self):
        original = script('A')
        state = AppState(script=original)
        state.confirm_script_review()
        env = {'state': state, 'index': 0, 'note': SimpleNamespace(value='A looked good'),
               'refresh': Mock(), 'safe_notify': Mock(), 'save_raw_verdict': Mock(),
               'rendered_script': original.model_dump_json()}
        decide = callback('generation_tab.py', 'decide', env)
        state.script = script('B')
        state.confirm_script_review()
        state.get_or_create_service = Mock()
        decide('approved')
        state.get_or_create_service.assert_not_called()
        env['save_raw_verdict'].assert_not_called()

    async def test_stale_manual_start_does_not_read_other_script_clip_mapping(self):
        state = AppState(script=script('B'), manual_script_id='script_B')
        exporter = Mock()
        env = {'state': state, 'exporter': exporter, 'rendered_script': script('A').model_dump_json(),
               'safe_notify': Mock()}
        await callback('generation_tab.py', 'run_manual_production', env)()
        exporter.get_ready_clip_paths.assert_not_called()

    async def test_confirm_routes_only_after_current_preview_is_reviewed(self):
        state = AppState(script=script())
        env = {'state': state, 'safe_notify': Mock(), 'logger': Mock(), 'on_reviewed': Mock(),
               'previewed_script': {'json': state.script.model_dump_json()}}
        callback('planning_tab.py', 'confirm_script', env)()
        self.assertTrue(state.is_script_reviewed())
        env['on_reviewed'].assert_called_once()

    async def test_confirm_does_not_approve_a_script_changed_in_another_tab(self):
        state = AppState(script=script('B'))
        env = {'state': state, 'safe_notify': Mock(), 'logger': Mock(), 'on_reviewed': Mock(),
               'previewed_script': {'json': script('A').model_dump_json()}}
        callback('planning_tab.py', 'confirm_script', env)()
        self.assertFalse(state.is_script_reviewed())
        env['on_reviewed'].assert_not_called()

    async def test_failed_manual_render_does_not_keep_previous_preview_visible(self):
        state = AppState(script=script(), final_video_path='old.mp4')
        state.confirm_script_review()

        async def produce(*args, **kwargs):
            return SimpleNamespace(success=False, clips=[], video_path=None, error='quality failed')

        service = SimpleNamespace(produce_video=produce, set_progress_callback=Mock(),
                                  progress=SimpleNamespace(phase=ProductionPhase.FAILED,
                                                           scene_progresses=[], progress_percent=0))
        state.new_production_service = lambda: service
        manual_preview = SimpleNamespace(visible=True)
        env = {'state': state, 'safe_notify': Mock(), 'logger': Mock(), 'asyncio': asyncio,
               'ProductionPhase': ProductionPhase, 'ProductionProgress': object,
               'gen_spinner': SimpleNamespace(visible=False),
               'scene_progress_container': SimpleNamespace(visible=False, clear=Mock()),
               'manual_preview': manual_preview, 'manual_video_player': Mock(),
               'injected_video_player': SimpleNamespace(visible=True),
               'injected_placeholder': SimpleNamespace(visible=False),
               'update_scene_grid': Mock(), 'update_progress_ui': Mock(),
               'rendered_script': state.script.model_dump_json(),
               'settings': SimpleNamespace(paid_production_enabled=True)}
        tree = ast.parse((COMPONENTS / 'generation_tab.py').read_text())
        production = next(node for node in ast.walk(tree)
                          if isinstance(node, ast.AsyncFunctionDef) and node.name == '_run_production_core')
        wrapper = ast.parse('def factory():\n video_player = injected_video_player\n placeholder_content = injected_placeholder\n return _run_production_core\n')
        wrapper.body[0].body.insert(-1, production)
        exec(compile(ast.fix_missing_locations(wrapper), 'generation_tab.py', 'exec'), env)
        await env['factory']()({1: 'local.mp4'})
        self.assertFalse(manual_preview.visible)
        self.assertIsNone(state.final_video_path)
        self.assertFalse(state.pipeline_running)


class RawVerdictDisplayTests(unittest.TestCase):
    def test_scoped_review_note_loads_and_corruption_cannot_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(settings, 'output_dir', root / 'outputs'), patch.object(
                    settings, 'clips_dir', root / 'outputs/clips'):
                current = script()
                frame = root / 'frame.png'
                Image.new('RGB', (540, 960), 'blue').save(frame)
                digest = inspect_frame(str(frame))
                approve_first_frame(current, current.scenes[0], str(frame), ['one bus'], ['extra bus'], 'Reviewed', digest)
                clip = settings.clips_dir / 'scene/clip.mp4'
                clip.parent.mkdir(parents=True)
                clip.write_bytes(b'saved native clip')
                with patch('shorts_maker.services.raw_review.VideoFileClip') as video:
                    video.return_value.__enter__.return_value = SimpleNamespace(duration=1, audio=None, size=(540, 960))
                    scoped = raw_review.save_raw_verdict(current, current.scenes[0], str(clip), digest, 'approved', 'Current scoped note')
                self.assertFalse(clip.with_suffix('.review.json').exists())
                self.assertEqual(raw_review.load_raw_verdict(current, current.scenes[0], str(clip), digest)['reviewer_note'], 'Current scoped note')
                clip.with_suffix('.review.json').write_text(scoped.read_text())
                scoped.unlink()
                self.assertEqual(raw_review.load_raw_verdict(current, current.scenes[0], str(clip), digest)['reviewer_note'], 'Current scoped note')
                self.assertEqual(raw_review.raw_review_status(current, current.scenes[0], str(clip), 'changed'), 'stale')
                scoped.write_text('{broken')
                with self.assertRaises(ValueError):
                    raw_review.load_raw_verdict(current, current.scenes[0], str(clip), digest)


if __name__ == '__main__':
    unittest.main()
