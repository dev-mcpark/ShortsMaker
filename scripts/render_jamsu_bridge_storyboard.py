"""Render original Jamsu Bridge plan diagrams for a free visual story audition."""

import argparse
import math
import subprocess
from pathlib import Path

from moviepy import AudioFileClip
from moviepy.config import FFMPEG_BINARY
from PIL import Image, ImageDraw, ImageFont


SIZE = (540, 960)
FPS = 12
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
BG, INK, MUTED, WATER, PINK, TEAL = (
    "#f4f2ed", "#24394a", "#677d87", "#b5dce3", "#e777ab", "#64aeb1"
)


def label(draw, xy, value, size=26, color=INK):
    draw.text(xy, value, font=ImageFont.truetype(FONT, size), fill=color, anchor="ma")


def bridge(draw, *, x1=55, x2=485, y=455, raised=False, revised=False):
    draw.rounded_rectangle((x1, 600, x2, 625), radius=10, fill=WATER)
    for x in (x1 + 70, x2 - 85):
        draw.rounded_rectangle((x, y + 36, x + 16, 600), radius=5, fill=MUTED)
    draw.rounded_rectangle((x1, y, x2, y + 42), radius=10, fill=TEAL if revised else INK)
    if revised:
        for x in (x1 + 40, x1 + 125, x2 - 145, x2 - 60):
            draw.rounded_rectangle((x, y - 15, x + 42, y + 1), radius=7, fill=TEAL)
    if raised:
        for x in (x1 + 95, x2 - 105):
            draw.line((x, y, x, y - 122), fill=MUTED, width=7)
        draw.rounded_rectangle((x1 + 24, y - 135, x2 - 24, y - 118), radius=8, fill=PINK)


def frame(scene, t, duration):
    image = Image.new("RGB", SIZE, BG)
    draw = ImageDraw.Draw(image)
    label(draw, (270, 30), f"서울시 발표 기반 · 미완공 설계 개념도 · {scene:02d}/05", 17, MUTED)
    draw.rounded_rectangle((28, 76, 512, 83), radius=3, fill="#dde5e2")
    if t > 0:
        draw.rounded_rectangle((28, 76, 28 + int(484 * min(t / duration, 1)), 83),
                               radius=3, fill=PINK)
    if scene == 1:
        label(draw, (270, 132), "분홍 공중길은 어디로?", 36)
        bridge(draw, raised=t < 3)
        label(draw, (270, 275), "2024 당선안" if t < 3 else "2026 수정안", 26,
              PINK if t < 3 else TEAL)
        if t >= 3:
            label(draw, (270, 555), "2026 수정안에서 제외", 28)
    elif scene == 2:
        label(draw, (270, 132), "처음엔 두 높이의 길", 36)
        bridge(draw, raised=t >= 2)
        label(draw, (270, 555), "기존 다리", 26, INK)
        if t >= 2:
            label(draw, (270, 280), "별도 공중 보행길", 26, PINK)
    elif scene == 3:
        label(draw, (270, 132), "수정 설계에서 빠진 길", 34)
        bridge(draw, raised=t < 3.3)
        label(draw, (270, 280 if t < 3.3 else 315),
              "2024 공중 데크" if t < 3.3 else "공중 데크 제외", 28,
              PINK if t < 3.3 else INK)
        label(draw, (270, 555), "서울시: 홍수 시 안전성 등 고려", 24, MUTED)
    elif scene == 4:
        label(draw, (270, 132), "한 높이에서 넓히는 계획", 33)
        bridge(draw, revised=True)
        draw.rounded_rectangle((135, 240, 405, 258), radius=8, fill=MUTED)
        if t >= 1:
            draw.rounded_rectangle((135, 275, 405, 318), radius=9, fill=TEAL)
            label(draw, (270, 355), "넓어진 보행 공간", 27, TEAL)
        if t >= 2:
            label(draw, (270, 185), "조망 공간 22곳", 26)
        if t >= 4:
            for x in (160, 330):
                draw.rounded_rectangle((x, 458, x + 50, 491), radius=5,
                                       fill=WATER, outline=INK, width=2)
            label(draw, (270, 550), "배 통과 구간 투명 데크 2곳", 24, MUTED)
    elif scene == 5:
        label(draw, (270, 132), "위로 올리는 길 → 기존 다리 확장", 29)
        bridge(draw, x1=47, x2=250, y=335, raised=True)
        label(draw, (150, 280), "2024 당선안", 22, PINK)
        bridge(draw, x1=290, x2=493, y=335, revised=True)
        label(draw, (392, 280), "2026 수정안", 22, TEAL)
        if t >= 4:
            label(draw, (270, 525), "개통 목표: 2027년 하반기", 28)
    else:
        raise ValueError(f"Unknown Jamsu scene: {scene}")
    return image


def pilot_seed(raised=True):
    """Unlettered model states for reviewing a possible scene-3 Veo first frame."""
    image = Image.new("RGB", (720, 1280), "#f1eee8")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((64, 210, 656, 930), radius=34, fill="#d9d5cb")
    draw.rounded_rectangle((76, 198, 644, 910), radius=32, fill="#faf8f3")
    draw.polygon(((112, 600), (557, 600), (618, 724), (173, 724)), fill="#99cbd5")
    draw.polygon(((135, 522), (553, 522), (591, 566), (173, 566)), fill="#2d4756")
    draw.polygon(((173, 566), (591, 566), (591, 584), (173, 584)), fill="#1c3442")
    for x in (205, 505):
        draw.polygon(((x, 584), (x + 19, 584), (x + 22, 649), (x + 3, 649)),
                     fill="#667d84")
    if raised:
        for x in (216, 493):
            draw.polygon(((x, 425), (x + 12, 425), (x + 18, 522), (x + 6, 522)),
                         fill="#8f7a86")
        draw.polygon(((146, 397), (531, 397), (567, 433), (182, 433)), fill=PINK)
        draw.polygon(((182, 433), (567, 433), (567, 448), (182, 448)), fill="#b95581")
    return image


def render_scene(scene, duration, output_dir):
    path = output_dir / f"scene_{scene}.mp4"
    command = [FFMPEG_BINARY, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
               "-pix_fmt", "rgb24", "-s", "540x960", "-r", str(FPS), "-i", "-",
               "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
               "-pix_fmt", "yuv420p", str(path)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
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
        with AudioFileClip(str(args.audio_dir / f"scene_{scene}.aiff")) as audio:
            duration = audio.duration + 0.5
        print(render_scene(scene, duration, args.output_dir))


if __name__ == "__main__":
    main()
