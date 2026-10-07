"""Render original CW-Net concept diagrams for a zero-API local review."""

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
NAVY, PANEL, WHITE, MINT, GOLD, RED, MUTED = (
    "#081521", "#102536", "#f6f8fa", "#83dcc6", "#ffc857", "#ff777f", "#a9bac6"
)


def label(draw, xy, text, size=24, color=WHITE, anchor=None):
    draw.text(xy, text, font=ImageFont.truetype(FONT, size), fill=color, anchor=anchor)


def card(draw, box, title, detail="", accent=MINT):
    draw.rounded_rectangle(box, radius=17, fill=PANEL, outline=accent, width=2)
    x1, y1, x2, _ = box
    label(draw, ((x1 + x2) // 2, y1 + 20), title, 25, anchor="ma")
    if detail:
        label(draw, ((x1 + x2) // 2, y1 + 59), detail, 18, MUTED, "ma")


def car(draw, x, y, color=MINT):
    draw.rounded_rectangle((x - 35, y - 47, x + 35, y + 47), radius=16, fill=color)
    draw.rounded_rectangle((x - 24, y - 20, x + 24, y + 22), radius=9, fill=NAVY)
    draw.rectangle((x - 44, y - 27, x - 35, y - 10), fill=PANEL)
    draw.rectangle((x + 35, y - 27, x + 44, y - 10), fill=PANEL)


def cyclist(draw, x, y):
    for dx in (-23, 23):
        draw.ellipse((x + dx - 16, y - 16, x + dx + 16, y + 16), outline=GOLD, width=4)
    draw.line((x - 23, y, x, y - 21, x + 23, y, x - 23, y), fill=GOLD, width=4)
    draw.ellipse((x - 8, y - 46, x + 8, y - 30), fill=GOLD)


def road(draw):
    draw.rounded_rectangle((120, 225, 420, 640), radius=20, fill="#142a3b")
    draw.line((140, 225, 140, 640), fill=MUTED, width=3)
    draw.line((400, 225, 400, 640), fill=MUTED, width=3)
    for y in range(245, 630, 70):
        draw.line((270, y, 270, y + 33), fill="#496070", width=3)


def frame(scene, t, duration):
    image = Image.new("RGB", SIZE, NAVY)
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((26, 30, 514, 75), radius=12, fill=PANEL)
    label(d, (40, 42), f"비공개 시험장 · 설명용 개념도 · {scene:02d}/06", 17, GOLD)
    d.rounded_rectangle((30, 825, 510, 832), radius=3, fill=PANEL)
    d.rounded_rectangle((30, 825, 30 + int(480 * min(t / duration, 1)), 832), radius=3, fill=GOLD)
    label(d, (34, 851), "출처: Kenny et al. · Nature 2026", 16, MUTED)

    if scene == 1:
        label(d, (34, 105), "차는 왜 멈췄을까?", 35)
        label(d, (34, 158), "자전거를 알아본 걸까?", 24, MUTED)
        road(d)
        cyclist(d, 270, 320)
        y = 585 - int(115 * min(t / 2.0, 1))
        car(d, 270, y)
        if t >= 2.0:
            d.line((180, 408, 360, 408), fill=RED, width=7)
    elif scene == 2:
        label(d, (34, 105), "멈췄지만 신호는 낮았다", 31)
        if t >= 0.4:
            card(d, (40, 240, 500, 354), "겉으로는 안전한 정지", "자전거 앞에서 멈춤")
        if t >= 2.7:
            card(d, (40, 418, 500, 565), "설명 화면의 자전거 신호", "실제 화면을 단순화한 개념도", GOLD)
            d.rounded_rectangle((70, 525, 470, 540), radius=7, fill="#405363")
            d.rounded_rectangle((70, 525, 75, 540), radius=3, fill=RED)
            label(d, (270, 595), "BIKE <1%", 24, RED, "ma")
    elif scene == 3:
        label(d, (34, 105), "봤지만, 판단에 쓰이지 않았다", 31)
        card(d, (35, 258, 245, 420), "인지 시스템", "자전거 감지")
        cyclist(d, 140, 508)
        if t >= 2.6:
            d.line((245, 334, 300, 334), fill=RED, width=5)
            d.line((262, 316, 282, 352), fill=RED, width=5)
            d.line((282, 316, 262, 352), fill=RED, width=5)
            card(d, (300, 258, 505, 420), "경로 계획 AI", "자전거 입력 없음", RED)
        else:
            card(d, (300, 258, 505, 420), "경로 계획 AI", "입력 확인 중", MUTED)
    elif scene == 4:
        label(d, (34, 105), "계획과 제동은 달랐다", 34)
        road(d)
        cyclist(d, 270, 310)
        car(d, 270, 548)
        if t >= 0.5:
            d.line((315, 505, 348, 460, 335, 414, 286, 360), fill=RED, width=5, joint="curve")
            label(d, (390, 375), "충돌 위험 경로", 19, RED, "ma")
        if t >= 2.7:
            d.line((175, 468, 365, 468), fill=MINT, width=8)
            card(d, (65, 156, 475, 234), "별도 안전 제동", "계획 경로를 막고 정지", MINT)
    elif scene == 5:
        label(d, (34, 105), "설명을 듣고 더 조심하다", 32)
        card(d, (32, 243, 258, 574), "처음 시험", "자율주행 시작", GOLD)
        d.line((145, 455, 145, 366), fill=GOLD, width=5)
        car(d, 145, 478, GOLD)
        if t >= 2.7:
            card(d, (282, 243, 508, 574), "설명 뒤", "더 낮은 속도로 시작", MINT)
            d.line((395, 463, 395, 414), fill=MINT, width=5)
            car(d, 395, 478, MINT)
        if t >= 3.5:
            d.rounded_rectangle((283, 239, 507, 578), radius=17, outline=MINT, width=4)
    elif scene == 6:
        label(d, (34, 105), "설명이 바꾼 것", 35)
        card(d, (65, 250, 475, 365), "차의 행동을 더 잘 예측", "사람의 이해가 개선됨")
        if t >= 3.7:
            d.line((270, 365, 270, 420), fill=GOLD, width=4)
            card(d, (65, 430, 475, 550), "사고 감소는 미측정", "시험 결과를 넘어 단정하지 않기", MUTED)
    else:
        raise ValueError(f"Unknown CW-Net scene: {scene}")
    return image


def render_scene(scene, duration, output_dir):
    path = output_dir / f"scene_{scene}.mp4"
    cmd = [FFMPEG_BINARY, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
           "-pix_fmt", "rgb24", "-s", "540x960", "-r", str(FPS), "-i", "-",
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", str(path)]
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for index in range(math.ceil(duration * FPS)):
            process.stdin.write(frame(scene, index / FPS, duration).tobytes())
    finally:
        process.stdin.close()
    if process.wait() != 0:
        raise RuntimeError(f"Scene {scene} encode failed")
    if path.stat().st_size <= 10_000:
        raise RuntimeError(f"Scene {scene} output is incomplete")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for scene in range(1, 7):
        audio = AudioFileClip(str(args.audio_dir / f"scene_{scene}.aiff"))
        try:
            duration = audio.duration + 0.5
        finally:
            audio.close()
        print(render_scene(scene, duration, args.output_dir))


if __name__ == "__main__":
    main()
