"""Render original wind-tunnel concept diagrams for a zero-API story review."""

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
NAVY, PANEL, WHITE, MINT, GOLD, MUTED = (
    "#081521", "#102536", "#f6f8fa", "#83dcc6", "#ffc857", "#a9bac6"
)


def label(draw, xy, text, size=24, color=WHITE, anchor=None):
    draw.text(xy, text, font=ImageFont.truetype(FONT, size), fill=color, anchor=anchor)


def card(draw, box, title, detail="", accent=MINT):
    draw.rounded_rectangle(box, radius=17, fill=PANEL, outline=accent, width=2)
    x1, y1, x2, _ = box
    label(draw, ((x1 + x2) // 2, y1 + 20), title, 24, anchor="ma")
    if detail:
        label(draw, ((x1 + x2) // 2, y1 + 57), detail, 18, MUTED, "ma")


def turbine(draw, x, y, phase=0.0, scale=1.0):
    radius = int(91 * scale)
    draw.line((x, y, x, y + int(250 * scale)), fill=WHITE, width=7)
    for index in range(3):
        angle = phase + index * 2 * math.pi / 3
        endpoint = (x + int(radius * math.cos(angle)), y + int(radius * math.sin(angle)))
        draw.line((x, y, *endpoint), fill=MINT, width=8)
    draw.ellipse((x - 11, y - 11, x + 11, y + 11), fill=GOLD)


def frame(scene, t, duration):
    image = Image.new("RGB", SIZE, NAVY)
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((26, 30, 514, 75), radius=12, fill=PANEL)
    label(d, (40, 42), f"고압 풍동 연구 · 설명용 개념도 · {scene:02d}/06", 17, GOLD)
    d.rounded_rectangle((30, 825, 510, 832), radius=3, fill=PANEL)
    progress = int(480 * min(t / duration, 1))
    if progress:
        d.rounded_rectangle((30, 825, 30 + progress, 832), radius=3, fill=GOLD)
    label(d, (34, 851), "출처: Kurelek et al. · PNAS Nexus 2026", 16, MUTED)

    if scene == 1:
        label(d, (34, 112), "비스듬한 바람, 같은 속도?", 31)
        turbine(d, 305, 370, phase=t * 2.2)
        for offset in (0, 80, 160):
            x = 30 + int(18 * min(t, 1))
            d.line((x, 265 + offset, x + 190, 335 + offset), fill=GOLD, width=6)
            d.polygon((x + 190, 335 + offset, x + 166, 311 + offset,
                       x + 160, 332 + offset), fill=GOLD)
    elif scene == 2:
        label(d, (34, 112), "풍동에서 나온 답", 34)
        card(d, (35, 245, 248, 445), "정면 바람", "회전 조건 A", GOLD)
        card(d, (292, 245, 505, 445), "비스듬한 바람", "회전 조건 B", GOLD)
        if t >= 3.4:
            label(d, (270, 465), "A ≠ B", 38, MINT, "ma")
            card(d, (64, 505, 476, 585), "최대 출력 조건이 달라짐", "풍동 측정 결과")
    elif scene == 3:
        label(d, (34, 112), "작은 터빈, 통제된 시험", 31)
        d.rounded_rectangle((45, 235, 495, 575), radius=20, outline=MUTED, width=4)
        label(d, (270, 257), "고압 풍동", 24, GOLD, "ma")
        turbine(d, 270, 380, phase=t * 2.0, scale=0.68)
        d.line((70, 390, 170, 390), fill=GOLD, width=5)
        d.polygon((170, 390, 150, 380, 150, 400), fill=GOLD)
        if t >= 1.5:
            label(d, (115, 585), "바람 각도 변경", 22, MINT, "ma")
        if t >= 3.2:
            label(d, (405, 585), "회전 조건 변경", 22, MINT, "ma")
    elif scene == 4:
        label(d, (34, 112), "두 조절값을 함께 보면", 32)
        card(d, (35, 265, 245, 420), "터빈 방향", "바람과의 요 각도", GOLD)
        if t >= 1.4:
            card(d, (295, 265, 505, 420), "회전 조건", "날개 끝 속도 비율", MINT)
        if t >= 2.7:
            d.line((140, 420, 230, 470, 270, 490), fill=GOLD, width=4)
            d.line((400, 420, 310, 470, 270, 490), fill=MINT, width=4)
            card(d, (72, 490, 468, 585), "동시 조정 검토", "현장 성과가 확인된 것은 아님")
    elif scene == 5:
        label(d, (34, 112), "측정과 전망을 구분하면", 31)
        card(d, (47, 245, 493, 360), "풍동 실험", "출력과 회전 조건을 측정", MINT)
        if t >= 0.5:
            card(d, (47, 390, 493, 505), "공학 모델", "풍동 결과를 예측", GOLD)
        if t >= 2.8:
            d.line((270, 505, 270, 520), fill=GOLD, width=4)
            card(d, (47, 520, 493, 605), "풍력단지 이득", "현장 측정이 아닌 모델 전망", GOLD)
    elif scene == 6:
        label(d, (34, 112), "남은 질문은 현장", 34)
        card(d, (60, 260, 480, 385), "풍동에서 확인", "각도별 최대 출력 회전 조건", MINT)
        if t >= 3.2:
            d.line((270, 385, 270, 460), fill=GOLD, width=4)
            card(d, (60, 460, 480, 590), "실제 풍력단지", "전력 이득은 현장 시험 필요", GOLD)
    else:
        raise ValueError(f"Unknown wind-tunnel scene: {scene}")
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
