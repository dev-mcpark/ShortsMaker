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
        label(draw, (270, 210), "설명용 평면도", 24, MUTED)
        draw.rounded_rectangle((70, 370, 470, 495), radius=18, fill="#e4e9e6")
        growth = max(0.0, min((t - 1.0) / 1.0, 1.0))
        draw.rounded_rectangle((int(130 - 45 * growth), int(405 - 18 * growth),
                                int(410 + 45 * growth), int(455 + 18 * growth)),
                               radius=12, fill=TEAL if growth else INK)
        if growth >= 1:
            label(draw, (270, 300), "같은 높이 · 넓어진 보행 공간", 25, TEAL)
        if t >= 2.5:
            for x in (125, 205, 305, 385):
                draw.rounded_rectangle((x, 371, x + 30, 390), radius=6, fill=TEAL)
            label(draw, (270, 545), "조망 공간 22곳 계획", 24, MUTED)
        if t >= 4.5:
            for x in (170, 350):
                draw.rounded_rectangle((x, 405, x + 48, 452), radius=5,
                                       fill=WATER, outline=INK, width=2)
            label(draw, (270, 585), "항로 두 구간에 투명 바닥", 23, MUTED)
    elif scene == 5:
        label(draw, (270, 132), "위로 올리는 길 → 기존 다리 확장", 29)
        bridge(draw, x1=60, x2=240, y=335, raised=True)
        label(draw, (150, 170), "2024 당선안", 22, PINK)
        bridge(draw, x1=275, x2=510, y=335, revised=True)
        label(draw, (392, 170), "2026 수정안", 22, TEAL)
    else:
        raise ValueError(f"Unknown Jamsu scene: {scene}")
    return image


def pilot_seed(raised=True, lift=0.0):
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
    if raised and lift < 1:
        offset = int(460 * lift)
        for x in (216, 493):
            draw.polygon(((x, 425 - offset), (x + 12, 425 - offset),
                          (x + 18, 522 - offset), (x + 6, 522 - offset)),
                         fill="#8f7a86")
        draw.polygon(((146, 397 - offset), (531, 397 - offset),
                      (567, 433 - offset), (182, 433 - offset)), fill=PINK)
        draw.polygon(((182, 433 - offset), (567, 433 - offset),
                      (567, 448 - offset), (182, 448 - offset)), fill="#b95581")
    return image


def pilot_motion_frame(t):
    progress = max(0.0, min((t - 3.0) / 2.0, 1.0))
    return pilot_seed(progress < 1, progress * progress * (3 - 2 * progress))


def render_pilot_motion(duration, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "scene_3.mp4"
    command = [FFMPEG_BINARY, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
               "-pix_fmt", "rgb24", "-s", "720x1280", "-r", "24", "-i", "-",
               "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
               "-pix_fmt", "yuv420p", str(path)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for index in range(math.ceil(duration * 24)):
            process.stdin.write(pilot_motion_frame(index / 24).tobytes())
    finally:
        process.stdin.close()
    if process.wait() != 0 or path.stat().st_size <= 10_000:
        raise RuntimeError("Pilot motion encode failed")
    return path


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
    parser.add_argument("--pilot-scene3", action="store_true", help="render only the free scene-3 motion proof")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.pilot_scene3:
        with AudioFileClip(str(args.audio_dir / "scene_3.aiff")) as audio:
            print(render_pilot_motion(audio.duration + 0.5, args.output_dir))
        return
    for scene in range(1, 6):
        with AudioFileClip(str(args.audio_dir / f"scene_{scene}.aiff")) as audio:
            duration = audio.duration + 0.5
        print(render_scene(scene, duration, args.output_dir))


if __name__ == "__main__":
    main()
