"""Make resumable macOS Yuna narration and a local story-audio review page."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from html import escape
from pathlib import Path

from moviepy import AudioFileClip
from moviepy.config import FFMPEG_BINARY

from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.planner.models import ShortsScript
from shorts_maker.utils.config import settings
from shorts_maker.utils.source_manager import SourceManager


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _save_manifest(path: Path, manifest: dict) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".scratch-", suffix=".tmp", delete=False) as file:
        temporary = Path(file.name)
        try:
            json.dump(manifest, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _check_audio(path: Path) -> None:
    with AudioFileClip(str(path)) as audio:
        if audio.duration <= 0.5:
            raise ValueError(f"Scratch narration is too short: {path}")


def prepare(script_path: Path, output_dir: Path) -> list[str]:
    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to(settings.output_dir.resolve()):
        raise ValueError("Scratch narration must stay under the ignored outputs directory")
    script_bytes = script_path.read_bytes()
    script = ShortsScript.model_validate_json(script_bytes)
    expected = {"schema_version": 1, "script_sha256": _hash(script_bytes),
                "model": "macos-say", "voice": "Yuna"}
    manifest_path = output_dir / "narration.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (not isinstance(manifest, dict) or any(manifest.get(key) != value for key, value in expected.items())
                or not isinstance(manifest.get("scenes"), dict)):
            raise ValueError("Scratch narration belongs to a different script or voice")
    else:
        if list(output_dir.glob("scene_*")):
            raise ValueError("Untracked scratch audio exists; choose an empty output directory")
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = {**expected, "scenes": {}}
        _save_manifest(manifest_path, manifest)

    paths = []
    for scene in script.scenes:
        key = str(scene.scene_number)
        text_hash = _hash(scene.script_text.encode("utf-8"))
        destination = output_dir / f"scene_{key}.aiff"
        entry = manifest["scenes"].get(key)
        if entry is None:
            if destination.exists():
                raise ValueError(f"Untracked scratch audio exists: {destination}")
            entry = {"text_sha256": text_hash, "status": "pending"}
            manifest["scenes"][key] = entry
            _save_manifest(manifest_path, manifest)
        if entry.get("text_sha256") != text_hash or entry.get("status") not in {"pending", "complete"}:
            raise ValueError(f"Scratch narration text or state differs for scene {key}")
        if destination.exists():
            if entry.get("status") == "complete" and _hash(destination.read_bytes()) != entry.get("file_sha256"):
                raise ValueError(f"Scratch narration file changed for scene {key}")
            _check_audio(destination)
        elif entry["status"] == "complete":
            raise ValueError(f"Completed scratch narration is missing: {destination}")
        else:
            partial = output_dir / f"scene_{key}.part.aiff"
            partial.unlink(missing_ok=True)
            try:
                subprocess.run(["say", "-v", "Yuna", "-o", str(partial), scene.script_text], check=True)
                _check_audio(partial)
                os.replace(partial, destination)
            finally:
                partial.unlink(missing_ok=True)
        if entry["status"] == "pending":
            entry.update(status="complete", file_sha256=_hash(destination.read_bytes()))
            _save_manifest(manifest_path, manifest)
        paths.append(str(destination))
    VideoEditor.validate_narration(paths, script)
    return paths


def render_story_review(script_path: Path, audio_paths: list[str], output_dir: Path) -> Path:
    script = ShortsScript.model_validate_json(script_path.read_bytes())
    if len(audio_paths) != len(script.scenes):
        raise ValueError("Scratch audio and script scene counts differ")
    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to(settings.output_dir.resolve()):
        raise ValueError("Story review must stay under the ignored outputs directory")
    durations = []
    for path in audio_paths:
        with AudioFileClip(path) as audio:
            durations.append(audio.duration)

    combined = output_dir / "story_audio.m4a"
    partial = output_dir / "story_audio.part.m4a"
    command = [FFMPEG_BINARY, "-hide_banner", "-loglevel", "error"]
    for path in audio_paths:
        command.extend(["-i", path])
    inputs = "".join(f"[{index}:a]" for index in range(len(audio_paths)))
    command.extend(["-filter_complex", f"{inputs}concat=n={len(audio_paths)}:v=0:a=1[a]",
                    "-map", "[a]", "-c:a", "aac", "-b:a", "128k", "-y", str(partial)])
    try:
        subprocess.run(command, check=True)
        _check_audio(partial)
        os.replace(partial, combined)
    finally:
        partial.unlink(missing_ok=True)

    source = (f'<a href="{escape(script.source_url, quote=True)}" target="_blank" '
              f'rel="noopener noreferrer">{escape(script.source_name)}</a>'
              if SourceManager.is_allowed_url(script.source_url) else escape(script.source_name))
    scenes = "".join(
        f'<li><strong>{duration:.1f}초</strong><p>{escape(scene.script_text)}</p>'
        f'<small>{escape(scene.visual_description)}</small></li>'
        for scene, duration in zip(script.scenes, durations)
    )
    page = ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{escape(script.title)} · 이야기 검토</title><style>"
            "body{max-width:760px;margin:32px auto;padding:0 18px;background:#f3f0e9;color:#203746;font:17px/1.6 system-ui,sans-serif}"
            "h1{line-height:1.25}audio{width:100%;margin:18px 0}li{background:white;border:1px solid #cbd5d2;border-radius:12px;margin:12px 0;padding:14px 18px}"
            "li p{margin:6px 0}small{color:#546a75}a{color:#176e80}</style></head><body>"
            f"<h1>{escape(script.title)}</h1><p>임시 Yuna 음성 · {sum(durations):.1f}초 · "
            "음악·영상 없음 · 최종 내레이션 및 게시 문안 미승인</p>"
            "<audio controls preload=\"metadata\" src=\"story_audio.m4a\"></audio>"
            f"<h2>장면별 문안</h2><ol>{scenes}</ol><h2>출처와 검토 범위</h2><p>{source}</p>"
            f"<p>{escape(script.description)}</p>"
            "<p>장면 설명은 화면 계획이며 실제 촬영이나 생성 영상이 아닙니다. 원문과 주장의 시점은 별도로 확인하세요.</p>"
            "</body></html>")
    review_path = output_dir / "story_review.html"
    temporary_page = output_dir / "story_review.part.html"
    try:
        temporary_page.write_text(page, encoding="utf-8")
        os.replace(temporary_page, review_path)
    finally:
        temporary_page.unlink(missing_ok=True)
    return review_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    paths = prepare(args.script, args.output_dir)
    review_path = render_story_review(args.script, paths, args.output_dir)
    print(json.dumps({"audio_paths": paths, "story_review": str(review_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
