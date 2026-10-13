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

if __package__:
    from scripts.render_sillim_depot_storyboard import BG, MUTED, TEAL, frame, label
else:
    from render_sillim_depot_storyboard import BG, MUTED, TEAL, frame, label


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
    draw = ImageDraw.Draw(artwork)
    if scene == 2 and storyboard_time >= 4:
        # The two pressures must visibly point to the same land-use decision.
        draw.line((170, 461, 270, 492), fill=TEAL, width=5)
        draw.line((370, 461, 270, 492), fill=TEAL, width=5)
        draw.polygon(((260, 486), (280, 486), (270, 501)), fill=TEAL)
        label(draw, (270, 510), "한 부지", 22, TEAL, "ma")
    elif scene == 3:
        label(draw, (270, 510), "설명용 단면", 21, MUTED, "ma")
    elif scene == 4 and storyboard_time >= 5:
        # A later, thinner arrow signals delayed inflow, not measured output.
        draw.rectangle((0, 438, 540, 550), fill=BG)
        draw.ellipse((78, 447, 122, 491), outline=TEAL, width=4)
        draw.line((100, 469, 100, 453), fill=TEAL, width=3)
        draw.line((100, 469, 112, 476), fill=TEAL, width=3)
        draw.line((143, 469, 418, 469), fill=TEAL, width=4)
        draw.polygon(((418, 459), (437, 469), (418, 479)), fill=TEAL)
        label(draw, (270, 492), "유입을 늦추는 설계", 23, TEAL, "ma")
        label(draw, (270, 522), "하천 수위 급등 완화 목표", 19, TEAL, "ma")
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
        if scene == 3:
            # The moving dark wall crosses the subtitle; a soft backing preserves contrast.
            backdrop = Image.new("RGBA", (680, 110))
            ImageDraw.Draw(backdrop).rounded_rectangle(
                (0, 0, 679, 109), radius=24, fill=(245, 241, 232, 208),
            )
            layers.append(ImageClip(np.asarray(backdrop)).with_position((20, 845))
                          .with_duration(background.duration))
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
