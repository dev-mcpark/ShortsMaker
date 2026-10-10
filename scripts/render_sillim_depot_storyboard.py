"""Render original Sillim depot diagrams for a zero-API story audition."""

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
BG, INK, PANEL, BLUE, TEAL, MUTED = (
    "#f5f1e8", "#19384a", "#e4e9e6", "#70b7d4", "#328c87", "#68808a"
)


def label(draw, xy, value, size=25, color=INK, anchor=None):
    draw.text(xy, value, font=ImageFont.truetype(FONT, size), fill=color, anchor=anchor)


def bus(draw, x, y, scale=1):
    w, h = int(140 * scale), int(65 * scale)
    draw.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=INK)
    draw.rounded_rectangle((x + 14 * scale, y + 12 * scale,
                            x + w - 14 * scale, y + 37 * scale), radius=5, fill=BG)
    for offset in (29, w - 29):
        draw.ellipse((x + offset - 12, y + h - 6, x + offset + 12, y + h + 18), fill=INK)


def frame(scene, t, duration):
    image = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(image)
    label(d, (30, 27), f"서울시 발표 기반 · 설명용 개념도 · {scene:02d}/05", 17, MUTED)
    d.rounded_rectangle((28, 77, 512, 83), radius=3, fill=PANEL)
    progress = int(484 * min(t / duration, 1))
    if progress:
        d.rounded_rectangle((28, 77, 28 + progress, 83), radius=3, fill=TEAL)

    if scene == 1:
        label(d, (270, 115), "차고지 아래에는?", 39, anchor="ma")
        bus(d, 195, 235)
        d.line((35, 330, 505, 330), fill=INK, width=6)
        d.rounded_rectangle((80, 365, 460, 575), radius=22, outline=MUTED, width=4)
        label(d, (270, 400), "지하 공간", 26, MUTED, "ma")
        if t >= 2.3:
            label(d, (270, 462), "빗물 3만 5천 톤", 33, TEAL, "ma")
        if t >= 5.7:
            label(d, (270, 520), "왜 차고지 아래일까?", 26, INK, "ma")
    elif scene == 2:
        label(d, (270, 115), "한 부지, 두 문제", 37, anchor="ma")
        d.rounded_rectangle((45, 175, 495, 335), radius=20, fill=PANEL)
        bus(d, 80, 230, 0.65)
        label(d, (270, 207), "버스 차고지 부족", 27, INK, "ma")
        if t >= 3.0:
            d.rounded_rectangle((45, 365, 495, 560), radius=20, fill="#dcebf0")
            d.line((78, 468, 462, 468), fill=BLUE, width=18)
            d.line((78, 505, 462, 505), fill=BLUE, width=18)
            label(d, (270, 391), "도림천 주변 침수 위험", 27, INK, "ma")
    elif scene == 3:
        label(d, (270, 115), "위는 버스, 아래는?", 37, anchor="ma")
        for top, bottom in ((183, 302), (306, 425), (429, 575)):
            d.rounded_rectangle((48, top, 492, bottom), radius=14, fill=PANEL, outline=MUTED, width=2)
        bus(d, 91, 215, 0.75)
        label(d, (330, 238), "지상 차고지", 24, INK, "ma")
        bus(d, 91, 337, 0.75)
        label(d, (330, 361), "지하 1층", 24, INK, "ma")
        if t >= 3.3:
            d.rounded_rectangle((58, 438, 482, 566), radius=11, fill=BLUE)
            label(d, (270, 466), "지하 2층", 24, INK, "ma")
            label(d, (270, 510), "빗물저류조", 32, INK, "ma")
    elif scene == 4:
        label(d, (270, 115), "빗물을 잠시 잡아두다", 34, anchor="ma")
        for x in (140, 270, 400):
            d.line((x, 185, x, 285), fill=BLUE, width=8)
            d.polygon((x - 15, 280, x + 15, 280, x, 305), fill=BLUE)
        d.rounded_rectangle((87, 325, 453, 500), radius=17, outline=INK, width=5)
        fill = min(max((t - 1.5) / 3.0, 0), 1)
        if fill:
            d.rounded_rectangle((95, 492 - int(130 * fill), 445, 492), radius=9, fill=BLUE)
        label(d, (270, 425), "일시 저장", 28, INK, "ma")
        if t >= 4.0:
            d.line((120, 554, 420, 554), fill=TEAL, width=8)
            d.polygon((420, 539, 445, 554, 420, 569), fill=TEAL)
            label(d, (270, 584), "하천 수위 급등 완화 목표", 23, TEAL, "ma")
    elif scene == 5:
        label(d, (270, 115), "한 공간의 두 역할", 37, anchor="ma")
        d.rounded_rectangle((55, 188, 485, 316), radius=20, fill=PANEL)
        bus(d, 92, 222, 0.62)
        label(d, (336, 240), "평소 · 교통", 27, INK, "ma")
        if t >= 1.4:
            d.rounded_rectangle((55, 332, 485, 460), radius=20, fill="#dcebf0")
            d.rounded_rectangle((95, 365, 235, 429), radius=8, fill=BLUE)
            label(d, (336, 384), "폭우 · 저장", 27, INK, "ma")
        if t >= 4.0:
            label(d, (270, 510), "약 10cm · 서울시 설명", 25, TEAL, "ma")
        if t >= 5.7:
            label(d, (270, 548), "실제 피해 감소 실측값 아님", 20, MUTED, "ma")
    else:
        raise ValueError(f"Unknown Sillim scene: {scene}")
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
