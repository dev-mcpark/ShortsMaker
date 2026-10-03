"""Build a local music/caption review page from controlled video comparisons."""

import argparse
import html
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote


STREAM_HASH = re.compile(r"^\d+,(v|a),SHA256=([0-9a-f]{64})$")


def stream_hashes(video: Path) -> dict[str, str]:
    if not video.is_file():
        raise FileNotFoundError(video)
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
         "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", "-f", "streamhash",
         "-hash", "sha256", "-"],
        check=True, capture_output=True, text=True,
    )
    hashes = {}
    for line in result.stdout.splitlines():
        match = STREAM_HASH.fullmatch(line.strip())
        if match:
            hashes[match.group(1)] = match.group(2)
    if set(hashes) != {"v", "a"}:
        raise ValueError(f"Expected one video and one audio stream: {video}")
    return hashes


def build_review(baseline: Path, music: Path, captions: Path, output: Path,
                 names: tuple[str, str, str], music_direction: str = "") -> Path:
    output = output.resolve()
    if output.suffix.lower() != ".html" or output in {video.resolve() for video in (baseline, music, captions)}:
        raise ValueError("Output must be an HTML file distinct from the input videos")
    if len(names) != 3:
        raise ValueError("Expected names for the three review cuts")
    baseline_hash = stream_hashes(baseline)
    music_hash = stream_hashes(music)
    caption_hash = stream_hashes(captions)
    if baseline_hash["v"] != music_hash["v"] or baseline_hash["a"] == music_hash["a"]:
        raise ValueError("Music comparison must keep the exact video stream and change audio")
    if baseline_hash["a"] != caption_hash["a"] or baseline_hash["v"] == caption_hash["v"]:
        raise ValueError("Caption comparison must keep the exact audio stream and change video")

    cards = []
    descriptions = (
        "음악·자막 비교 기준",
        "기준과 영상 스트림이 동일하며 오디오만 다릅니다.",
        "기준과 오디오 스트림이 동일하며 영상만 다릅니다.",
    )
    for video, name, description in zip((baseline, music, captions), names, descriptions):
        relative = os.path.relpath(video.resolve(), output.parent).replace(os.sep, "/")
        source = html.escape(quote(relative, safe="/"), quote=True)
        cards.append(
            f'<article><h2>{html.escape(name)}</h2>'
            f'<video controls preload="metadata" src="{source}"></video>'
            f'<p>{description}</p></article>'
        )
    brief = (f'<p><strong>음악 방향:</strong> {html.escape(music_direction)}</p>'
             if music_direction else "")
    page = f"""<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>쇼츠 음악·자막 검토</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
body {{ max-width: 1120px; margin: 0 auto; padding: 24px; background: #101420; color: #f0f2f8; }}
p {{ color: #bdc6d6; line-height: 1.55; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; }}
article {{ padding: 16px; border: 1px solid #38435a; border-radius: 16px; background: #192235; }}
article h2 {{ margin-top: 0; font-size: 1.1rem; }}
video {{ display: block; width: 100%; max-height: 66vh; background: #000; border-radius: 10px; }}
.prompt {{ margin-top: 28px; padding: 16px; border-left: 4px solid #9eaef9; background: #192235; }}
</style></head>
<body><h1>쇼츠 음악·자막 검토</h1>
<p>앞의 두 영상은 음악, 첫째와 셋째 영상은 자막 디자인을 비교합니다. 다른 영상이 재생되면 기존 재생은 멈춥니다.</p>
{brief}
<div class="grid">{''.join(cards)}</div>
<div class="prompt"><strong>검토할 점</strong>
<p>음악의 이야기 적합성과 음성 가림 여부, 자막의 가독성과 디자인 느낌을 각각 판단해 주세요. 어느 대안도 맞지 않을 수 있습니다.</p></div>
<script>
const players = [...document.querySelectorAll('video')];
for (const player of players) player.addEventListener('play', () => {{
  for (const other of players) if (other !== player) other.pause();
}});
</script></body></html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("music_alternative", type=Path)
    parser.add_argument("caption_alternative", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--names", nargs=3, default=("기준", "음악 대안", "자막 대안"),
                        metavar=("BASELINE", "MUSIC", "CAPTIONS"))
    parser.add_argument("--music-direction", default="")
    args = parser.parse_args()
    page = build_review(args.baseline, args.music_alternative, args.caption_alternative,
                        args.output, tuple(args.names), args.music_direction)
    print(page)


if __name__ == "__main__":
    main()
