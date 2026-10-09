"""Render original door-plug investigation diagrams for a local story audition."""

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
BG, PANEL, WHITE, GOLD, RED, MINT, MUTED = (
    "#101b2c", "#1c3044", "#f5f7fa", "#f6c66e", "#e57475", "#8ed3bd", "#a9b9c7"
)


def label(draw, xy, value, size=25, color=WHITE, anchor=None):
    draw.text(xy, value, font=ImageFont.truetype(FONT, size), fill=color, anchor=anchor)


def card(draw, box, title, detail="", accent=GOLD):
    draw.rounded_rectangle(box, radius=16, fill=PANEL, outline=accent, width=3)
    x1, y1, x2, _ = box
    label(draw, ((x1 + x2) // 2, y1 + 19), title, 24, anchor="ma")
    if detail:
        label(draw, ((x1 + x2) // 2, y1 + 55), detail, 19, MUTED, "ma")


def frame(scene, t, duration):
    image = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((25, 29, 515, 75), radius=12, fill=PANEL)
    label(d, (40, 42), f"NTSB 조사 기반 · 설명용 개념도 · {scene:02d}/06", 17, GOLD)
    d.rounded_rectangle((30, 825, 510, 832), radius=3, fill=PANEL)
    progress = int(480 * min(t / duration, 1))
    if progress:
        d.rounded_rectangle((30, 825, 30 + progress, 832), radius=3, fill=GOLD)
    label(d, (34, 852), "출처: NTSB · AIR-25-04 / 사건 페이지", 16, MUTED)

    if scene == 1:
        label(d, (34, 120), "비행 중 패널이 이탈했다", 31)
        d.rounded_rectangle((65, 270, 475, 440), radius=55, fill=PANEL, outline=MUTED, width=3)
        d.polygon((225, 440, 315, 440, 392, 566, 148, 566), fill=PANEL)
        if t < 2.2:
            d.rounded_rectangle((270, 292, 350, 409), radius=6, outline=GOLD, width=5)
        else:
            d.rounded_rectangle((270, 292, 350, 409), radius=6, outline=RED, width=5)
            d.line((356, 350, 415, 321), fill=RED, width=5)
            label(d, (425, 305), "이탈", 22, RED, "mm")
    elif scene == 2:
        label(d, (34, 120), "고정 볼트 네 개는?", 34)
        d.rounded_rectangle((146, 220, 394, 490), radius=18, fill=PANEL, outline=MUTED, width=4)
        for x in (165, 375):
            for y in (270, 440):
                d.ellipse((x - 17, y - 17, x + 17, y + 17), outline=RED, width=5)
        if t >= 2.2:
            card(d, (94, 510, 446, 602), "사고 전부터 없음", "조사관이 확인한 사실", RED)
    elif scene == 3:
        label(d, (34, 120), "몇 달 전 공장에서는", 32)
        card(d, (47, 275, 493, 388), "2023년 9월 18일", "리벳 수리를 위해 패널 개방")
        if t >= 2.4:
            d.line((270, 388, 270, 457), fill=GOLD, width=5)
            card(d, (47, 458, 493, 573), "다음 날", "패널을 다시 닫음", MINT)
    elif scene == 4:
        label(d, (34, 120), "기록이 빠지자", 34)
        card(d, (47, 275, 493, 390), "필수 작업 기록 없음", "패널을 연 사실이 문서에 남지 않음", RED)
        if t >= 2.0:
            d.line((270, 390, 270, 462), fill=RED, width=5)
            card(d, (47, 465, 493, 585), "닫은 뒤 품질 검사 없음", "NTSB 조사 결과", RED)
    elif scene == 5:
        label(d, (34, 120), "조금씩 움직인 패널", 31)
        d.rounded_rectangle((145, 212, 395, 466), radius=18, fill=PANEL, outline=MUTED, width=4)
        rise = min(int(t * 11), 53)
        d.rounded_rectangle((170, 250 - rise, 370, 439 - rise), radius=14,
                            outline=GOLD if t < 3.4 else RED, width=5)
        if t >= 1.5:
            label(d, (270, 483), "이전 비행들: 위로 이동", 21, GOLD, "ma")
        if t >= 3.4:
            card(d, (75, 515, 465, 605), "2024년 1월 5일: 이탈", "이륙 약 6분 뒤", RED)
    elif scene == 6:
        label(d, (34, 120), "돌아와 안전하게 착륙", 31)
        card(d, (54, 245, 486, 356), "비상 절차 → 출발 공항 복귀", "NTSB 사건 기록", MINT)
        if t >= 3.2:
            d.line((270, 356, 270, 420), fill=GOLD, width=5)
            card(d, (54, 424, 486, 570), "NTSB의 원인 판단", "공장 교육·지침·감독 부족", GOLD)
    else:
        raise ValueError(f"Unknown door-plug scene: {scene}")
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
