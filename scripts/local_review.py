"""Render a private review from complete local clips and narration, without paid API calls."""

import argparse
import asyncio
import json
from pathlib import Path

from shorts_maker.planner.models import ShortsScript
from shorts_maker.services.production_service import ProductionService


AUDIO_SUFFIXES = {".aiff", ".wav", ".mp3", ".m4a"}


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
                       subtitle_style: str = "soft"):
    if not 0 <= bgm_volume <= 1:
        raise ValueError("BGM volume must be between 0 and 1")
    clips, audio = collect_local_inputs(script, clips_dir, audio_dir)
    options = {"bgm_mood": "auto", "bgm_volume": bgm_volume,
               "subtitle_style": subtitle_style}
    if bgm_track:
        options["bgm_track"] = bgm_track
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
    args = parser.parse_args()
    script = ShortsScript.model_validate_json(args.script.read_text(encoding="utf-8"))
    asyncio.run(render_local(script, args.clips_dir, args.audio_dir, args.bgm_volume,
                             args.bgm_track, args.subtitle_style))


if __name__ == "__main__":
    main()
