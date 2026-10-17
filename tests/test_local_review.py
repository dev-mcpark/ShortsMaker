"""The local review command must fail before production when an input is incomplete."""

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.local_review import collect_local_inputs, load_subtitle_colors, load_text_overlays, render_local
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.planner.models import ShortsScript, VideoScene


class LocalReviewTests(unittest.TestCase):
    def test_local_text_cues_validate_and_render_within_scene(self):
        script = ShortsScript(
            title="Review", description="", tags=[], mood="calm", style="plain",
            source_name="test", source_url="https://example.com", generation_mode="video",
            scenes=[VideoScene(scene_number=1, visual_description="diagram", script_text="line")],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overlays.json"
            cues = {"1": [{"text": "AI 설명용 영상", "start": 0, "x": 60, "y": 75}]}
            path.write_text(json.dumps(cues), encoding="utf-8")
            overlays = load_text_overlays(path, script, Path(directory))
            editor = VideoEditor(bgm_volume=0, text_overlays=overlays)
            clips = editor._create_text_overlay_clips(1, 2.0)
            try:
                self.assertEqual(len(clips), 1)
                self.assertEqual(clips[0].start, 0)
                self.assertEqual(clips[0].end, 2.0)
                self.assertGreater(clips[0].w, 0)
            finally:
                editor._cleanup_clips(clips)

            cues["1"][0]["end"] = 3
            path.write_text(json.dumps(cues), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "시간 또는 위치"):
                VideoEditor(bgm_volume=0, text_overlays=load_text_overlays(path, script, Path(directory))) \
                    ._create_text_overlay_clips(1, 2.0)
            cues["1"][0]["end"] = 1
            cues["1"][0]["x"] = 1070
            path.write_text(json.dumps(cues), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "화면 밖"):
                VideoEditor(bgm_volume=0, text_overlays=load_text_overlays(path, script, Path(directory))) \
                    ._create_text_overlay_clips(1, 2.0)
            cues["1"][0]["x"] = -1
            path.write_text(json.dumps(cues), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "시간 또는 위치"):
                load_text_overlays(path, script, Path(directory))

    def test_text_cues_reject_a_different_clip_before_render(self):
        script = ShortsScript(
            title="Review", description="", tags=[], mood="calm", style="plain",
            source_name="test", source_url="https://example.com", generation_mode="video",
            scenes=[VideoScene(scene_number=1, visual_description="diagram", script_text="line")],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clip = root / "scene_1.mp4"
            clip.write_bytes(b"reviewed clip")
            path = root / "overlays.json"
            cues = {"_clip_sha256": {"1": hashlib.sha256(clip.read_bytes()).hexdigest()},
                    "1": [{"text": "지하 2층", "start": 0, "x": 60, "y": 1100}]}
            path.write_text(json.dumps(cues), encoding="utf-8")
            self.assertEqual(load_text_overlays(path, script, root), {"1": cues["1"]})
            clip.write_bytes(b"different clip")
            with self.assertRaisesRegex(ValueError, "검토본과 다릅니다"):
                load_text_overlays(path, script, root)
            cues["_clip_sha256"] = {}
            path.write_text(json.dumps(cues), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "모든 표기 씬"):
                load_text_overlays(path, script, root)

    def test_forwards_local_caption_color(self):
        script = ShortsScript(
            title="Review", description="", tags=[], mood="calm", style="plain",
            source_name="test", source_url="https://example.com", generation_mode="video",
            scenes=[VideoScene(scene_number=1, visual_description="diagram", script_text="line")],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scene_1.mp4").touch()
            (root / "scene_1.aiff").touch()
            with patch("scripts.local_review.ProductionService") as service:
                service.return_value.produce_video = AsyncMock(return_value=MagicMock(
                    success=True, video_path="review.mp4", report_path="review.json",
                    estimated_visual_cost_usd=0,
                ))
                asyncio.run(render_local(script, root, root, 0, subtitle_color="#19384a"))
            self.assertEqual(service.call_args.kwargs["editor_options"]["subtitle_color"], "#19384a")
            with patch("scripts.local_review.ProductionService") as invalid_service:
                with self.assertRaises(ValueError):
                    asyncio.run(render_local(script, root, root, 0, subtitle_color="not-a-color"))
                invalid_service.assert_not_called()

    def test_scene_caption_colors_are_validated_and_forwarded(self):
        script = ShortsScript(
            title="Review", description="", tags=[], mood="calm", style="plain",
            source_name="test", source_url="https://example.com", generation_mode="video",
            scenes=[VideoScene(scene_number=1, visual_description="diagram", script_text="line")],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            colors_file = root / "colors.json"
            colors_file.write_text('{"1":"#19384a"}', encoding="utf-8")
            colors = load_subtitle_colors(colors_file, script)
            self.assertEqual(colors, {1: "#19384a"})
            (root / "scene_1.mp4").touch()
            (root / "scene_1.aiff").touch()
            with patch("scripts.local_review.ProductionService") as service:
                service.return_value.produce_video = AsyncMock(return_value=MagicMock(
                    success=True, video_path="review.mp4", report_path="review.json",
                    estimated_visual_cost_usd=0,
                ))
                asyncio.run(render_local(script, root, root, 0, subtitle_colors_by_scene=colors))
            self.assertEqual(service.call_args.kwargs["editor_options"]["subtitle_colors_by_scene"], colors)
            colors_file.write_text('{"2":"#F6F8FA"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_subtitle_colors(colors_file, script)
            colors_file.write_text('{"1":"invalid"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_subtitle_colors(colors_file, script)

    def test_complete_local_inputs_required_before_service(self):
        script = ShortsScript(
            title="Review", description="", tags=[], mood="calm", style="plain",
            source_name="test", source_url="https://example.com", generation_mode="video",
            scenes=[VideoScene(scene_number=n, visual_description="diagram", script_text="line") for n in (1, 2)],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for number in (1, 2):
                (root / f"scene_{number}.mp4").touch()
                (root / f"scene_{number}.aiff").touch()
            clips, audio = collect_local_inputs(script, root, root)
            self.assertEqual(set(clips), {1, 2})
            self.assertEqual([Path(path).name for path in audio], ["scene_1.aiff", "scene_2.aiff"])

            (root / "scene_2.mp4").unlink()
            with patch("scripts.local_review.ProductionService") as service:
                with self.assertRaisesRegex(FileNotFoundError, "scene_2.mp4"):
                    asyncio.run(render_local(script, root, root, 0.4))
                service.assert_not_called()

            (root / "scene_2.mp4").touch()
            (root / "scene_1.aiff").unlink()
            with patch("scripts.local_review.ProductionService") as service:
                with self.assertRaisesRegex(ValueError, "scene 1, found 0"):
                    asyncio.run(render_local(script, root, root, 0.4))
                service.assert_not_called()

            (root / "scene_1.aiff").touch()
            (root / "scene_2.mp3").touch()
            with self.assertRaisesRegex(ValueError, "scene 2, found 2"):
                collect_local_inputs(script, root, root)


if __name__ == "__main__":
    unittest.main()
