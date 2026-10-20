"""Render original concept diagrams for a zero-provider-cost composite-bus story audition."""

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
BG, INK, MUTED, PALE, BLUE, GOLD = (
    "#f4f0e9", "#203746", "#66808b", "#e5e9e4", "#5f9eb2", "#cc8e55"
)


def label(draw, xy, value, size=26, color=INK):
    draw.text(xy, value, font=ImageFont.truetype(FONT, size), fill=color, anchor="ma")


def bus(draw, x, y):
    draw.rounded_rectangle((x, y, x + 285, y + 125), radius=28, fill=BLUE, outline=INK, width=3)
    draw.rounded_rectangle((x + 28, y + 20, x + 250, y + 75), radius=10, fill="#d9e9ea")
    for offset in (62, 220):
        draw.ellipse((x + offset - 23, y + 105, x + offset + 23, y + 151), fill=INK)


def shell(draw, box, color):
    draw.rounded_rectangle(box, radius=24, fill=color, outline=INK, width=3)
    x1, y1, x2, y2 = box
    draw.rounded_rectangle((x1 + 17, y1 + 18, x2 - 17, y2 - 36), radius=9, fill=BG)


def frame(scene, t, duration):
    image = Image.new("RGB", SIZE, BG)
    draw = ImageDraw.Draw(image)
    label(draw, (270, 29), f"서울시 자료 기반 · 설명용 개념도 · {scene:02d}/05", 17, MUTED)
    draw.rounded_rectangle((28, 76, 512, 83), radius=3, fill=PALE)
    if t > 0:
        draw.rounded_rectangle((28, 76, 28 + int(484 * min(t / duration, 1)), 83),
                               radius=3, fill=GOLD)

    if scene == 1:
        label(draw, (270, 126), "낚싯대와 전기버스?", 37)
        draw.line((65, 390, 230, 220), fill=INK, width=8)
        draw.arc((49, 355, 105, 435), 25, 180, fill=BLUE, width=4)
        label(draw, (148, 455), "낚싯대", 25, MUTED)
        if t >= 1.2:
            bus(draw, 230, 290)
            label(draw, (369, 490), "남산 전기버스", 25, MUTED)
        if t >= 3.6:
            label(draw, (270, 575), "연결 고리는 무엇일까?", 30, GOLD)
    elif scene == 2:
        label(draw, (270, 126), "2010년, 무게의 문제", 36)
        draw.rounded_rectangle((88, 235, 452, 388), radius=20, fill=PALE)
        for x in (136, 224, 312):
            draw.rounded_rectangle((x, 268, x + 57, 352), radius=8, fill=INK)
        label(draw, (270, 410), "배터리", 25, MUTED)
        if t >= 2.3:
            shell(draw, (130, 468, 410, 587), BLUE)
            label(draw, (270, 615), "가벼운 차체가 필요", 27, GOLD)
    elif scene == 3:
        label(draw, (270, 126), "재료를 다루던 경험", 36)
        draw.rounded_rectangle((58, 214, 482, 347), radius=22, fill=PALE)
        label(draw, (270, 243), "낚싯대 · 헬멧", 30)
        label(draw, (270, 294), "복합소재 기술", 25, MUTED)
        if t >= 2.3:
            for offset in range(6):
                y = 398 + offset * 15
                draw.line((110, y, 430, y + 50), fill=BLUE if offset % 2 else GOLD, width=8)
            shell(draw, (114, 520, 426, 630), BLUE)
            label(draw, (270, 653), "버스 차체에 활용", 25, INK)
    elif scene == 4:
        label(draw, (270, 126), "차체만 비교하면", 37)
        shell(draw, (45, 237, 250, 380), PALE)
        label(draw, (147, 407), "철판 차체", 25, MUTED)
        if t >= 2.0:
            shell(draw, (290, 237, 495, 380), BLUE)
            label(draw, (392, 407), "탄소복합소재", 24, MUTED)
        if t >= 4.1:
            label(draw, (270, 525), "차체 무게 25% 감소", 39, GOLD)
            label(draw, (270, 576), "2010년 서울시 발표", 23, MUTED)
    elif scene == 5:
        label(draw, (270, 126), "차체를 가볍게 만든 이유", 34)
        draw.line((35, 550, 510, 270), fill=INK, width=7)
        bus(draw, 130 + min(int(t * 18), 80), 310)
        if t >= 2.6:
            label(draw, (270, 585), "충전 후 주행거리 연장", 29, GOLD)
            label(draw, (270, 630), "서울시 설명", 21, MUTED)
        label(draw, (270, 191), "남산 노선 · 2010년 투입", 24, MUTED)
    else:
        raise ValueError(f"Unknown composite-bus scene: {scene}")
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
