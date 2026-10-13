"""Place the verified Sillim explanation diagrams over retained Veo shots.

This makes silent local scene clips for a private edit comparison. It never
calls a model or uploads a video. The old five-scene Veo round remains closed.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from moviepy import CompositeVideoClip, ImageClip, VideoFileClip
from PIL import Image, ImageDraw

from render_sillim_depot_storyboard import frame


CARD_WIDTH = 480
CARD_POSITION = (28, 190)
REVEALS = {
    2: ((0.2, 1.0), (2.7, 4.0)),
    3: ((0.2, 1.0), (2.8, 4.0)),
    4: ((0.2, 1.0), (1.5, 2.5), (3.6, 5.0)),
    5: ((0.2, 1.0), (1.5, 2.0), (3.6, 5.0)),
}


def proof_card(scene: int, storyboard_time: float) -> Image.Image:
    """Crop the already source-checked diagram into a rounded editor card."""
    artwork = frame(scene, storyboard_time, 8).crop((0, 100, 540, 650))
    height = round(artwork.height * CARD_WIDTH / artwork.width)
    artwork = artwork.resize((CARD_WIDTH, height), Image.Resampling.LANCZOS)
    mask = Image.new("L", artwork.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, artwork.width - 1, artwork.height - 1), radius=24, fill=245,
    )
    card = artwork.convert("RGBA")
    card.putalpha(mask)
    return card


def render_scene(source: Path, destination: Path, scene: int) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    background = VideoFileClip(str(source))
    layers = [background]
    try:
        if (background.w, background.h) != (720, 1280):
            raise ValueError(f"Expected a 720x1280 Veo scene: {source}")
        for index, (start, storyboard_time) in enumerate(REVEALS[scene]):
            end = (REVEALS[scene][index + 1][0]
                   if index + 1 < len(REVEALS[scene]) else background.duration)
            if end <= start or start >= background.duration:
                raise ValueError(f"Invalid scene {scene} reveal: {start}..{end}")
            card = proof_card(scene, storyboard_time)
            layers.append(
                ImageClip(np.asarray(card)).with_position(CARD_POSITION)
                .with_start(start).with_duration(end - start)
            )
        composite = CompositeVideoClip(layers, size=(720, 1280)).with_duration(background.duration)
        try:
            composite.write_videofile(
                str(destination), fps=24, codec="libx264", audio=False,
                preset="veryfast", ffmpeg_params=["-crf", "20"],
                threads=4, logger=None,
            )
        finally:
            composite.close()
    finally:
        for layer in layers[1:]:
            layer.close()
        background.close()


def render(inputs: Path, outputs: Path) -> Path:
    outputs.mkdir(parents=True, exist_ok=True)
    for scene in range(1, 6):
        source = (inputs / f"scene_{scene}.mp4").resolve(strict=True)
        destination = outputs / f"scene_{scene}.mp4"
        if scene == 1:
            if destination.exists():
                raise FileExistsError(destination)
            destination.symlink_to(source)
        else:
            render_scene(source, destination, scene)
    cues = {
        "1": [
            {"text": "AI 설명용 영상", "start": 0, "x": 60, "y": 75},
            {"text": "서울시 발표 · 빗물 3만 5천 톤", "start": 2.3, "x": 60, "y": 160},
        ],
    }
    for scene in range(2, 6):
        cues[str(scene)] = [{"text": "AI 설명용 영상", "start": 0, "x": 760, "y": 40}]
    cue_path = outputs / "text_overlays.json"
    cue_path.write_text(json.dumps(cues, ensure_ascii=False, indent=2), encoding="utf-8")
    return cue_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, help="Directory of the five retained scene clips")
    parser.add_argument("outputs", type=Path, help="New private directory for explanatory clips")
    args = parser.parse_args()
    print(render(args.inputs, args.outputs))


if __name__ == "__main__":
    main()
