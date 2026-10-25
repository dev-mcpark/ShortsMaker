"""Prepare one resumable, locally retained narration set before video editing."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import shutil
import tempfile
from pathlib import Path

from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.services.openai_budget import check_openai_speech_budget
from shorts_maker.planner.models import ShortsScript
from shorts_maker.utils.config import settings
from shorts_maker.utils.paid_gate import require_paid_production_enabled


VOICES = ("alloy", "echo", "fable", "nova", "onyx", "shimmer")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _save_manifest(path: Path, manifest: dict) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".narration-", suffix=".tmp", delete=False) as file:
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


def _manifest(script_path: Path, output_dir: Path, voice: str, rate: float) -> dict:
    expected = {
        "schema_version": 1,
        "script_sha256": _hash(script_path.read_bytes()),
        "model": VideoEditor.TTS_MODEL,
        "voice": voice,
        "usd_per_million_characters": rate,
    }
    path = output_dir / "narration.json"
    if not path.exists():
        return {**expected, "reserved_usd_total": 0.0, "scenes": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or any(data.get(key) != value for key, value in expected.items()):
        raise ValueError("Existing narration set has a different script, model, voice, or price")
    if not isinstance(data.get("scenes"), dict):
        raise ValueError("Invalid narration manifest")
    reserve = data.get("reserved_usd_total")
    if not isinstance(reserve, (int, float)) or not math.isfinite(reserve) or reserve < 0:
        raise ValueError("Invalid cumulative narration reserve")
    return data


def _scene_state(scene, manifest: dict, output_dir: Path) -> str:
    key = str(scene.scene_number)
    entry = manifest["scenes"].get(key)
    destination = output_dir / f"scene_{key}.mp3"
    text_sha256 = _hash(scene.script_text.encode("utf-8"))
    if entry is None:
        if destination.exists():
            raise ValueError(f"Untracked narration file already exists: {destination}")
        return "missing"
    if entry.get("text_sha256") != text_sha256:
        raise ValueError(f"Narration text changed for scene {key}")
    if entry.get("status") == "pending":
        return "recoverable" if destination.is_file() else "missing"
    if entry.get("status") != "complete" or not destination.is_file():
        raise ValueError(f"Incomplete or missing narration for scene {key}")
    if _hash(destination.read_bytes()) != entry.get("file_sha256"):
        raise ValueError(f"Narration file changed for scene {key}")
    VideoEditor.validate_narration([str(destination)])
    return "complete"


async def prepare(script_path: Path, output_dir: Path, voice: str, max_cost_usd: float,
                  usd_per_million_characters: float, plan_only: bool = False) -> dict:
    if voice not in VOICES:
        raise ValueError(f"Unknown TTS voice: {voice}")
    if (not math.isfinite(max_cost_usd) or max_cost_usd < 0
            or not math.isfinite(usd_per_million_characters)
            or usd_per_million_characters <= 0):
        raise ValueError("Cost ceiling and current TTS price must be finite and nonnegative")
    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to(settings.output_dir.resolve()):
        raise ValueError("Private narration output must stay under the ignored outputs directory")
    script = ShortsScript.model_validate_json(script_path.read_text(encoding="utf-8"))
    if len({scene.scene_number for scene in script.scenes}) != len(script.scenes):
        raise ValueError("Scene numbers must be unique")
    manifest = _manifest(script_path, output_dir, voice, usd_per_million_characters)
    states = [_scene_state(scene, manifest, output_dir) for scene in script.scenes]
    missing = [scene for scene, state in zip(script.scenes, states) if state == "missing"]
    def scene_reserve(scene) -> float:
        return (len(scene.script_text) * usd_per_million_characters / 1_000_000
                * VideoEditor.TTS_MAX_ATTEMPTS)

    additional_reserve = sum(scene_reserve(scene) for scene in missing)
    cumulative_reserve = manifest["reserved_usd_total"] + additional_reserve
    if cumulative_reserve > max_cost_usd:
        raise ValueError(f"Cumulative TTS request reserve ${cumulative_reserve:.6f} exceeds ceiling ${max_cost_usd:.6f}")
    result = {"voice": voice, "model": VideoEditor.TTS_MODEL,
              "missing_scenes": [scene.scene_number for scene in missing],
              "additional_request_reserve_usd": round(additional_reserve, 6),
              "cumulative_request_reserve_usd": round(cumulative_reserve, 6),
              "max_cost_usd": max_cost_usd,
              "output_dir": str(output_dir)}
    if plan_only:
        return result
    if missing:
        check_openai_speech_budget(
            VideoEditor.TTS_MODEL, [scene.script_text for scene in missing],
            VideoEditor.TTS_MAX_ATTEMPTS,
        )
    if any(state != "complete" for state in states):
        require_paid_production_enabled()
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required to generate narration")
    output_dir.mkdir(parents=True, exist_ok=True)
    editor = VideoEditor(bgm_volume=0.0)
    try:
        for scene, state in zip(script.scenes, states):
            key = str(scene.scene_number)
            destination = output_dir / f"scene_{key}.mp3"
            if state == "complete":
                continue
            text_sha256 = _hash(scene.script_text.encode("utf-8"))
            if state == "missing":
                manifest["scenes"][key] = {"text_sha256": text_sha256, "status": "pending"}
                manifest["reserved_usd_total"] += scene_reserve(scene)
                _save_manifest(output_dir / "narration.json", manifest)
                generated = await editor._generate_tts(
                    scene.script_text, scene.scene_number, voice, source_url=script.source_url,
                )
                partial = output_dir / f"scene_{key}.part.mp3"
                try:
                    shutil.copyfile(generated, partial)
                    VideoEditor.validate_narration([str(partial)])
                    os.replace(partial, destination)
                finally:
                    partial.unlink(missing_ok=True)
                    editor.cleanup_temp_files()
            else:
                VideoEditor.validate_narration([str(destination)])
            manifest["scenes"][key] = {
                "text_sha256": text_sha256, "status": "complete",
                "file_sha256": _hash(destination.read_bytes()),
            }
            _save_manifest(output_dir / "narration.json", manifest)
        audio_paths = [str(output_dir / f"scene_{scene.scene_number}.mp3") for scene in script.scenes]
        VideoEditor.validate_narration(audio_paths)
        return {**result, "audio_paths": audio_paths}
    finally:
        editor.cleanup_temp_files()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--voice", choices=VOICES, required=True)
    parser.add_argument("--max-cost-usd", type=float, required=True)
    parser.add_argument("--usd-per-million-characters", type=float, required=True,
                        help="Check the current official model price before running")
    parser.add_argument("--plan", action="store_true", help="Inspect missing scenes and reserve; make no API calls")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(prepare(
        args.script, args.output_dir, args.voice, args.max_cost_usd,
        args.usd_per_million_characters, args.plan,
    )), ensure_ascii=False))


if __name__ == "__main__":
    main()
