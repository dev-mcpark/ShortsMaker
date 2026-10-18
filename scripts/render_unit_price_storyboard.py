"""Render original unit-price diagrams for a zero-API story audition."""

import argparse
import math
import subprocess
from pathlib import Path

from moviepy import AudioFileClip
from moviepy.config import FFMPEG_BINARY
from PIL import Image, ImageDraw, ImageFont


FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
SIZE = (540, 960)
FPS = 12
BG, INK, PANEL, GOLD, BLUE, MUTED = (
    "#f6f1e7", "#20394a", "#e3e9e7", "#db9555", "#6ca9ba", "#667d86"
)


def label(draw, xy, value, size=25, color=INK, anchor=None):
    draw.text(xy, value, font=ImageFont.truetype(FONT, size), fill=color, anchor=anchor)


def card(draw, box, title, detail="", accent=BLUE):
    draw.rounded_rectangle(box, radius=18, fill=PANEL, outline=accent, width=3)
    x1, y1, x2, _ = box
    label(draw, ((x1 + x2) // 2, y1 + 20), title, 27, INK, "ma")
    if detail:
        label(draw, ((x1 + x2) // 2, y1 + 64), detail, 22, MUTED, "ma")


def packet(draw, x, y, grams):
    draw.rounded_rectangle((x, y, x + 175, y + 220), radius=18, fill=PANEL, outline=INK, width=3)
    draw.rounded_rectangle((x + 18, y + 18, x + 157, y + 73), radius=10, fill=BLUE)
    label(draw, (x + 87, y + 141), grams, 36, INK, "ma")
    label(draw, (x + 87, y + 183), "설명용 포장", 17, MUTED, "ma")


def frame(scene, t, duration):
    image = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(image)
    label(d, (28, 27), f"한국소비자원 2024 자료 기반 · 개념도 · {scene:02d}/05", 16, MUTED)
    d.rounded_rectangle((28, 77, 512, 83), radius=3, fill=PANEL)
    progress = int(484 * min(t / duration, 1))
    if progress:
        d.rounded_rectangle((28, 77, 28 + progress, 83), radius=3, fill=GOLD)

    if scene == 1:
        label(d, (270, 132), "용량이 줄었다면?", 38, INK, "ma")
        packet(d, 83, 250, "150g")
        if t >= 1.6:
            label(d, (270, 350), "→", 34, GOLD, "ma")
            packet(d, 282, 250, "120g")
        if t >= 3.8:
            label(d, (270, 568), "100g당 가격은?", 33, GOLD, "ma")
    elif scene == 2:
        label(d, (270, 132), "봉지 가격이 같다면", 37, INK, "ma")
        label(d, (270, 185), "가정: 둘 다 3,000원", 25, MUTED, "ma")
        card(d, (36, 265, 254, 445), "150g", "100g당 2,000원")
        if t >= 2.0:
            card(d, (286, 265, 504, 445), "120g", "100g당 2,500원", GOLD)
        if t >= 4.5:
            label(d, (270, 545), "+25%", 56, GOLD, "ma")
            label(d, (270, 615), "용량 감소율은 20%", 24, MUTED, "ma")
    elif scene == 3:
        label(d, (270, 132), "2024년 실제 사례", 36, INK, "ma")
        card(d, (47, 230, 493, 345), "반찬 용량", "150g  →  120g")
        if t >= 2.5:
            card(d, (47, 382, 493, 537), "제조사 출고가격", "4,490원  →  3,590원", GOLD)
        label(d, (270, 585), "판매가격 자료가 아닙니다", 22, MUTED, "ma")
    elif scene == 4:
        label(d, (270, 132), "100g당 출고가격", 36, INK, "ma")
        card(d, (38, 237, 502, 370), "변경 전", "4,490 ÷ 150 × 100 ≈ 2,993원")
        if t >= 4.3:
            card(d, (38, 400, 502, 533), "변경 후", "3,590 ÷ 120 × 100 ≈ 2,992원", GOLD)
        if t >= 6.2:
            label(d, (270, 600), "출고 단계에선 거의 같음", 26, INK, "ma")
    elif scene == 5:
        label(d, (270, 132), "그래서 장볼 때는?", 38, INK, "ma")
        card(d, (48, 240, 492, 380), "실제 판매가격", "이 자료로는 알 수 없음", GOLD)
        if t >= 2.8:
            card(d, (48, 420, 492, 560), "가격표 + 용량", "판매가격 ÷ 용량으로 비교")
    else:
        raise ValueError(f"Unknown unit-price scene: {scene}")
    return image


def render_scene(scene, duration, output_dir):
    path = output_dir / f"scene_{scene}.mp4"
    cmd = [FFMPEG_BINARY, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
           "-pix_fmt", "rgb24", "-s", "540x960", "-r", str(FPS), "-i", "-",
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
           "-pix_fmt", "yuv420p", str(path)]
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for index in range(math.ceil(duration * FPS)):
            process.stdin.write(frame(scene, index / FPS, duration).tobytes())
    finally:
        process.stdin.close()
    if process.wait() != 0 or path.stat().st_size <= 10_000:
        raise RuntimeError(f"Scene {scene} encode failed")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for scene in range(1, 6):
        audio = AudioFileClip(str(args.audio_dir / f"scene_{scene}.aiff"))
        try:
            duration = audio.duration + 0.5
        finally:
            audio.close()
        print(render_scene(scene, duration, args.output_dir))


if __name__ == "__main__":
    main()
