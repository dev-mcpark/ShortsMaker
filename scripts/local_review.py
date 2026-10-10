"""Render a private review from complete local clips and narration, without paid API calls."""

import argparse
import asyncio
import json
import math
from pathlib import Path

from PIL import ImageColor

from shorts_maker.planner.models import ShortsScript
from shorts_maker.services.production_service import ProductionService


AUDIO_SUFFIXES = {".aiff", ".wav", ".mp3", ".m4a"}


def load_text_overlays(path: Path, script: ShortsScript) -> dict:
    overlays = json.loads(path.read_text(encoding="utf-8"))
    valid_scenes = {str(scene.scene_number) for scene in script.scenes}
    if not isinstance(overlays, dict) or not set(overlays) <= valid_scenes:
        raise ValueError("화면 표기에는 대본에 있는 씬 번호만 사용할 수 있습니다.")
    for scene_number, cues in overlays.items():
        if not isinstance(cues, list):
            raise ValueError(f"씬 {scene_number} 화면 표기는 목록이어야 합니다.")
        for cue in cues:
            if (not isinstance(cue, dict) or not {"text", "start", "x", "y"} <= set(cue)
                    or set(cue) - {"text", "start", "end", "x", "y"}):
                raise ValueError(f"씬 {scene_number} 화면 표기 형식이 올바르지 않습니다.")
            if (not isinstance(cue["text"], str) or not cue["text"].strip()
                    or "\n" in cue["text"]):
                raise ValueError(f"씬 {scene_number} 화면 표기 문안이 올바르지 않습니다.")
            numbers = (cue["start"], cue["x"], cue["y"])
            if "end" in cue:
                numbers += (cue["end"],)
            if (not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                        and math.isfinite(value) for value in numbers)
                    or cue["start"] < 0
                    or ("end" in cue and cue["end"] <= cue["start"])
                    or not all(isinstance(cue[key], int) and cue[key] >= 0 for key in ("x", "y"))):
                raise ValueError(f"씬 {scene_number} 화면 표기 시간 또는 위치가 올바르지 않습니다.")
    return overlays


def collect_local_inputs(script: ShortsScript, clips_dir: Path, audio_dir: Path):
    clips = {}
    audio = []
    for scene in script.scenes:
        number = scene.scene_number
        clip = clips_dir / f"scene_{number}.mp4"
        if not clip.is_file():
            raise FileNotFoundError(f"Missing local clip: {clip}")
        matches = sorted(
            path for path in audio_dir.glob(f"scene_{number}.*")
            if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES
        )
        if len(matches) != 1:
            raise ValueError(f"Expected one local narration for scene {number}, found {len(matches)}")
        clips[number] = str(clip)
        audio.append(str(matches[0]))
    return clips, audio


async def render_local(script: ShortsScript, clips_dir: Path, audio_dir: Path,
                       bgm_volume: float, bgm_track: str | None = None,
                       subtitle_style: str = "soft", subtitle_color: str | None = None,
                       text_overlays: dict | None = None):
    if not 0 <= bgm_volume <= 1:
        raise ValueError("BGM volume must be between 0 and 1")
    clips, audio = collect_local_inputs(script, clips_dir, audio_dir)
    options = {"bgm_mood": "auto", "bgm_volume": bgm_volume,
               "subtitle_style": subtitle_style}
    if bgm_track:
        options["bgm_track"] = bgm_track
    if subtitle_color is not None:
        ImageColor.getrgb(subtitle_color)
        options["subtitle_color"] = subtitle_color
    if text_overlays:
        options["text_overlays"] = text_overlays
    service = ProductionService(mode="video", editor_options=options)
    result = await service.produce_video(script, manual_clip_paths=clips, prepared_audio_paths=audio)
    if not result.success:
        raise RuntimeError(result.error)
    print(json.dumps({"video_path": result.video_path, "report_path": result.report_path,
                      "estimated_visual_cost_usd": result.estimated_visual_cost_usd}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("clips_dir", type=Path)
    parser.add_argument("audio_dir", type=Path)
    parser.add_argument("--bgm-volume", type=float, default=0.2)
    parser.add_argument("--bgm-track", help="Exact documented MP3 filename in bgm/")
    parser.add_argument("--subtitle-style", choices=("soft", "card"), default="soft")
    parser.add_argument("--subtitle-color", help="Caption text color for the local background, e.g. #19384a")
    parser.add_argument("--text-overlays", type=Path, help="JSON map of scene numbers to timed local text cues")
    args = parser.parse_args()
    script = ShortsScript.model_validate_json(args.script.read_text(encoding="utf-8"))
    overlays = load_text_overlays(args.text_overlays, script) if args.text_overlays else None
    asyncio.run(render_local(script, args.clips_dir, args.audio_dir, args.bgm_volume,
                             args.bgm_track, args.subtitle_style, args.subtitle_color, overlays))


if __name__ == "__main__":
    main()
