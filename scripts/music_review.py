"""Build a local music-only comparison from cuts with identical video streams."""

import argparse
import html
import os
from pathlib import Path
from urllib.parse import quote

if __package__:
    from scripts.creative_review import stream_hashes
else:
    from creative_review import stream_hashes


def build_music_review(videos: list[tuple[str, Path]], output: Path,
                       music_direction: str = "") -> Path:
    if len(videos) < 2:
        raise ValueError("At least two cuts are required")
    output = output.resolve()
    if output.suffix.lower() != ".html" or output in {path.resolve() for _, path in videos}:
        raise ValueError("Output must be an HTML file distinct from the input videos")
    hashes = [stream_hashes(path) for _, path in videos]
    if len({item["v"] for item in hashes}) != 1 or len({item["a"] for item in hashes}) != len(videos):
        raise ValueError("Music comparison requires identical video and distinct audio streams")

    cards = []
    for name, video in videos:
        relative = os.path.relpath(video.resolve(), output.parent).replace(os.sep, "/")
        cards.append(
            f'<article><h2>{html.escape(name)}</h2>'
            f'<video controls preload="metadata" playsinline src="{html.escape(quote(relative, safe="/"), quote=True)}"></video>'
            '</article>'
        )
    brief = (f'<p><strong>음악 방향:</strong> {html.escape(music_direction)}</p>'
             if music_direction else "")
    page = f"""<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>쇼츠 음악 비교</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1120px;margin:auto;padding:24px;background:#101420;color:#f0f2f8}}p{{line-height:1.6;color:#bdc6d6}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}}article{{padding:16px;border:1px solid #38435a;border-radius:16px;background:#192235}}video{{display:block;width:100%;max-height:66vh;background:#000;border-radius:10px}}</style>
<h1>쇼츠 음악 비교</h1>
<p>모든 영상의 장면·음성·자막은 같습니다. 음악의 이야기 적합성과 말 가림 여부를 들어보세요. 어느 후보도 맞지 않을 수 있습니다.</p>
{brief}<div class="grid">{''.join(cards)}</div>
<script>for(const player of document.querySelectorAll('video'))player.addEventListener('play',()=>{{for(const other of document.querySelectorAll('video'))if(other!==player)other.pause()}})</script>
</html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cut", nargs=2, action="append", required=True,
                        metavar=("LABEL", "VIDEO"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--music-direction", default="")
    args = parser.parse_args()
    print(build_music_review([(name, Path(path)) for name, path in args.cut],
                             args.output, args.music_direction))


if __name__ == "__main__":
    main()
