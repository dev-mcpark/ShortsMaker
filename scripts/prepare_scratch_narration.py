"""Make a resumable, script-bound macOS Yuna narration set without provider calls."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from moviepy import AudioFileClip

from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.planner.models import ShortsScript
from shorts_maker.utils.config import settings


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({"audio_paths": prepare(args.script, args.output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
