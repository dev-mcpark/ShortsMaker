"""Recreate the historical Sillim inset comparison over retained Veo shots.

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
    from scripts.render_sillim_depot_storyboard import BG, INK, MUTED, TEAL, label
else:
    from render_sillim_depot_storyboard import BG, INK, MUTED, TEAL, label


CARD_POSITION = (24, 190)
CARD_SIZES = {2: (360, 196), 3: (360, 268), 4: (350, 210)}
REVEALS = {
    2: ((0.2, 1.0), (2.7, 4.0)),
    3: ((0.2, 1.0), (2.8, 4.0)),
    4: ((0.2, 1.0), (1.5, 2.5)),
}


def proof_card(scene: int, storyboard_time: float) -> Image.Image:
    """Draw only the narrated relationship in a compact, legible inset."""
    width, height = CARD_SIZES[scene]
    artwork = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(artwork)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=20,
                           fill=(245, 241, 232, 224))
    if scene == 2 and storyboard_time >= 4:
        draw.line((208, 77, 270, 153), fill=TEAL, width=4)
        draw.line((208, 119, 270, 153), fill=TEAL, width=4)
        draw.polygon(((264, 143), (278, 153), (260, 157)), fill=TEAL)
        draw.rounded_rectangle((247, 153, 340, 185), radius=9, fill=TEAL)
        label(draw, (293, 160), "한 부지", 21, BG, "ma")
    if scene == 2:
        label(draw, (20, 16), "한 부지, 두 문제", 25)
        label(draw, (24, 62), "차고지 부족", 23)
        if storyboard_time >= 4:
            label(draw, (24, 104), "침수 위험", 23, TEAL)
    elif scene == 3:
        label(draw, (20, 14), "설명용 단면", 23, MUTED)
        for index, title in enumerate(("지상 · 차고지", "지하 1층 · 차고지", "지하 2층 · 빗물저류조")):
            top = 47 + index * 68
            active = index != 2 or storyboard_time >= 4
            draw.rounded_rectangle((16, top, 344, top + 57), radius=10,
                                   fill=(112, 183, 212, 240) if index == 2 and active
                                   else (228, 233, 230, 240), outline=MUTED, width=2)
            if active:
                label(draw, (180, top + 14), title, 23 if index < 2 else 21, INK, "ma")
    elif scene == 4:
        label(draw, (20, 15), "빗물을 잠시 저장", 24)
        for x in (105, 175, 245):
            draw.line((x, 49, x, 82), fill=TEAL, width=4)
            draw.polygon(((x - 7, 78), (x + 7, 78), (x, 88)), fill=TEAL)
        draw.rounded_rectangle((48, 91, 303, 146), radius=10, outline=INK, width=3)
        if storyboard_time >= 2.5:
            draw.rounded_rectangle((53, 116, 298, 141), radius=6, fill=(112, 183, 212, 240))
        label(draw, (175, 94), "일시 저장", 21, INK, "ma")
    return artwork


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
        if scene not in REVEALS:
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
    for scene in range(2, 5):
        cues[str(scene)] = [{"text": "AI 설명용 영상", "start": 0, "x": 760, "y": 40}]
    cues["5"] = [
        {"text": "AI 설명용 영상", "start": 0, "x": 760, "y": 40},
        {"text": "평소 · 교통시설", "start": 0.2, "x": 60, "y": 300},
        {"text": "폭우 · 방재시설", "start": 1.5, "x": 60, "y": 430},
        {"text": "약 10cm · 서울시 설명", "start": 3.6, "x": 60, "y": 560},
    ]
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
