"""Render the six NASA review diagrams from a local source photo and narration."""

import argparse
import math
import subprocess
from pathlib import Path

from moviepy import AudioFileClip
from moviepy.config import FFMPEG_BINARY
from PIL import Image, ImageDraw, ImageFont, ImageOps

PHOTO = None
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
NAVY, PANEL, WHITE, GOLD, MINT, MUTED = (
    "#081521", "#102536", "#f6f8fa", "#ffc857", "#83dcc6", "#a9bac6"
)
SIZE = (540, 960)
FPS = 12


def label(draw, xy, value, size=24, fill=WHITE, anchor=None):
    draw.text(xy, value, font=ImageFont.truetype(FONT, size), fill=fill, anchor=anchor)


def node(draw, box, title, detail="", color=PANEL):
    draw.rounded_rectangle(box, radius=15, fill=color)
    x1, y1, x2, y2 = box
    label(draw, ((x1 + x2) // 2, y1 + 18), title, 27, anchor="ma")
    if detail:
        label(draw, ((x1 + x2) // 2, y1 + 55), detail, 17, MUTED, "ma")


def photo_panel(image, box, crop=None):
    if PHOTO is None:
        raise RuntimeError("Load the NASA source photo before rendering")
    x1, y1, x2, y2 = box
    sample = PHOTO.crop(crop) if crop else PHOTO
    sample = ImageOps.fit(sample, (x2 - x1, y2 - y1), Image.Resampling.LANCZOS)
    image.paste(sample, (x1, y1))


def moving_dot(draw, start, end, t, onset, color=GOLD):
    """Show which diagram connection is active without inventing progress data."""
    if t < onset:
        return
    phase = ((t - onset) / 1.4) % 1
    x = round(start[0] + (end[0] - start[0]) * phase)
    y = round(start[1] + (end[1] - start[1]) * phase)
    draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=color)


def frame(scene, t, duration):
    image = Image.new("RGB", SIZE, NAVY)
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((26, 30, 514, 75), radius=12, fill=PANEL)
    medium = "현장 사진" if scene in (2, 5) else "설명용 개념도"
    label(d, (42, 42), f"지구 로봇 시험  ·  {medium}  ·  {scene:02d}/06", 17, GOLD)
    d.rounded_rectangle((30, 825, 510, 832), radius=3, fill=PANEL)
    d.rounded_rectangle((30, 825, 30 + int(480 * min(t / duration, 1)), 832), radius=3, fill=GOLD)
    label(d, (34, 851), "출처: NASA Science · 2026.09.15", 16, MUTED)

    if scene == 1:
        label(d, (34, 105), "드론이 새 지점을 발견", 35)
        label(d, (34, 155), "원래 임무는 어떻게 할까?", 23, MUTED)
        node(d, (45, 278, 265, 370), "기존 목표", "진행 중")
        drone_x = 340 + int(80 * min(t / 2, 1))
        d.ellipse((drone_x - 17, 265, drone_x + 17, 299), fill=MINT)
        label(d, (drone_x, 312), "드론", 17, MINT, "ma")
        if t > 1.2:
            d.ellipse((382, 415, 492, 525), outline=GOLD, width=5)
            label(d, (437, 463), "새 지점", 22, GOLD, "mm")
        if t > 2.3:
            d.line((drone_x + 14, 294, 472, 428), fill=GOLD, width=4)
            moving_dot(d, (drone_x + 14, 294), (472, 428), t, 2.3)
    elif scene == 2:
        label(d, (34, 105), "실제 시험: 버지니아", 35)
        label(d, (34, 155), "드론 1대 · 로버 2대", 24, MINT)
        photo_panel(image, (34, 230, 506, 540))
        d = ImageDraw.Draw(image)
        for onset, x, y, target_y, number in ((0.4, 140, 390, 430, "1"), (1.5, 217, 405, 449, "2"), (2.6, 365, 360, 420, "3")):
            if t >= onset:
                radius = 18 + round(3 * math.sin(2 * math.pi * (t - onset)))
                d.line((x, y + radius, x, target_y), fill=GOLD, width=3)
                d.ellipse((x - radius, y - radius, x + radius, y + radius), fill=NAVY, outline=GOLD, width=3)
                label(d, (x, y), number, 20, WHITE, "mm")
        label(d, (38, 557), "① 로버   ② 드론   ③ 로버", 19, MINT)
        label(d, (38, 590), "사진: NASA / Bethany Theiling", 18, MUTED)
    elif scene == 3:
        if t < 3.3:
            label(d, (34, 105), "드론이 잠깐 멈춰", 35)
            label(d, (34, 155), "새 지점을 검토", 23, MUTED)
        elif t < 5.3:
            label(d, (34, 105), "원래 목표는 유지", 35)
            label(d, (34, 155), "임무를 버리지 않음", 23, MUTED)
        else:
            label(d, (34, 105), "다른 로봇도 투입", 35)
            label(d, (34, 155), "새 지점을 조사", 23, MUTED)
        node(d, (110, 252, 430, 337), "새 지점 발견", "드론이 검토")
        if t < 3.3:
            d.rounded_rectangle((106, 248, 434, 341), radius=18, outline=MINT,
                                width=3 + round(2 * (1 + math.sin(t * 6))))
        if t >= 3.3:
            d.line((270, 337, 270, 400), fill=GOLD, width=4)
            d.line((135, 400, 405, 400), fill=GOLD, width=4)
            d.line((135, 400, 135, 443), fill=GOLD, width=4)
            node(d, (35, 443, 250, 565), "원래 임무", "목표는 유지")
            d.rounded_rectangle((35, 443, 250, 565), radius=15, outline=MINT, width=3)
        if t >= 5.3:
            d.line((405, 400, 405, 443), fill=GOLD, width=4)
            node(d, (290, 443, 505, 565), "새 지점", "다른 로봇 투입", PANEL)
            moving_dot(d, (305, 552), (490, 552), t, 5.3)
        if t >= 3.3:
            moving_dot(d, (50, 552), (235, 552), t, 3.3, MINT)
    elif scene == 4:
        label(d, (34, 105), "무엇을 따졌을까?", 35)
        label(d, (34, 155), "기사에 나온 의사결정 요소", 22, MUTED)
        items = [("과학적 가치", MINT), ("위험", GOLD), ("로봇의 거리", MINT), ("로봇의 속도", GOLD)]
        for i, (name, color) in enumerate(items):
            if t >= 0.5 + i * 0.85:
                y = 250 + i * 97
                d.rounded_rectangle((55, y, 485, y + 76), radius=14, fill=PANEL)
                d.ellipse((74, y + 27, 96, y + 49), fill=color)
                label(d, (118, y + 25), name, 26)
    elif scene == 5:
        label(d, (34, 105), "로버마다 다른 역할", 35)
        label(d, (34, 178), "실제 사진: NASA / Bethany Theiling", 17, MUTED)
        photo_panel(image, (32, 220, 258, 500), (60, 250, 850, 1300))
        photo_panel(image, (282, 220, 508, 500), (850, 130, 1930, 1310))
        d = ImageDraw.Draw(image)
        if t > 0.8:
            node(d, (31, 515, 258, 605), "라이다", "길을 살핌")
        if t > 2.0:
            node(d, (282, 515, 508, 605), "로봇 팔", "시료 채집")
        # Keep the rover switch aligned with the second narration phrase at 2.48 s.
        focus = (32, 220, 258, 500) if t < 2.48 else (282, 220, 508, 500)
        d.rounded_rectangle(focus, radius=8, outline=MINT, width=5)
    elif scene == 6:
        label(d, (34, 105), "새 정보 앞에서", 35)
        label(d, (34, 155), "우선순위를 다시 정하다", 26, MINT)
        node(d, (90, 260, 450, 350), "지구 현장 시험", "2026년 버지니아")
        if t > 1:
            d.line((270, 350, 270, 415), fill=GOLD, width=4)
            node(d, (55, 425, 485, 520), "기존 목표 + 새 지점", "서로 다른 로봇으로 조사")
        if t > 2.4:
            d.line((270, 520, 270, 560), fill=GOLD, width=4)
            node(d, (90, 560, 450, 640), "팀 재배치", "사람의 우선순위 반영")
            moving_dot(d, (105, 558), (435, 558), t, 2.4)
    else:
        raise ValueError(f"Unknown NASA scene: {scene}")
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
    assert path.stat().st_size > 10_000, path
    return str(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", type=Path, required=True, help="Local NASA/Bethany Theiling fleet photo")
    parser.add_argument("--audio-dir", type=Path, required=True, help="Retained scene_1.mp3 ... scene_6.mp3")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    global PHOTO
    with Image.open(args.photo) as source_photo:
        PHOTO = source_photo.convert("RGB")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for scene in range(1, 7):
        audio = AudioFileClip(str(args.audio_dir / f"scene_{scene}.mp3"))
        try:
            duration = audio.duration + 0.5
        finally:
            audio.close()
        print(render_scene(scene, duration, args.output_dir))


if __name__ == "__main__":
    main()
