"""Prepare one resumable, locally retained narration set before video editing."""

import asyncio
import hashlib
import json
import math
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from decimal import Decimal, ROUND_CEILING
from typing import Callable

from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.services.openai_budget import check_openai_speech_budget
from shorts_maker.services.openai_models import require_model_active
from shorts_maker.planner.models import ShortsScript
from shorts_maker.utils.config import settings
from shorts_maker.utils.paid_gate import require_paid_production_enabled


VOICES = ("alloy", "echo", "fable", "nova", "onyx", "shimmer")


@contextmanager
def _narration_lock(output_dir: Path):
    lock = output_dir / '.narration.lock.sqlite3'
    if lock.is_symlink():
        raise ValueError('Narration lock must not be a symbolic link')
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    db = sqlite3.connect(lock, timeout=0, isolation_level=None)
    try:
        try:
            db.execute('BEGIN EXCLUSIVE')
        except sqlite3.OperationalError as error:
            if error.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
            raise ValueError('NARRATION_IN_PROGRESS: another process is preparing this set') from error
        yield
    finally:
        db.close()


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


def _manifest(script_content: bytes, output_dir: Path, voice: str, rate: float) -> dict:
    expected = {
        "schema_version": 1,
        "script_sha256": _hash(script_content),
        "model": VideoEditor.TTS_MODEL,
        "voice": voice,
        "usd_per_million_characters": rate,
    }
    path = output_dir / "narration.json"
    if path.is_symlink():
        raise ValueError('Narration manifest must not be a symbolic link')
    if not path.exists():
        return {**expected, "reserved_usd_total": 0.0, "scenes": {}}
    with path.open('rb') as stream:
        content = stream.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise ValueError('Narration manifest is too large')
    data = json.loads(content.decode('utf-8'))
    if not isinstance(data, dict) or any(data.get(key) != value for key, value in expected.items()):
        raise ValueError("Existing narration set has a different script, model, voice, or price")
    if not isinstance(data.get("scenes"), dict):
        raise ValueError("Invalid narration manifest")
    reserve = data.get("reserved_usd_total")
    if isinstance(reserve, bool) or not isinstance(reserve, (int, float)) or not math.isfinite(reserve) or reserve < 0:
        raise ValueError("Invalid cumulative narration reserve")
    return data


def _scene_state(scene, manifest: dict, output_dir: Path) -> str:
    key = str(scene.scene_number)
    entry = manifest["scenes"].get(key)
    destination = output_dir / f"scene_{key}.mp3"
    if destination.is_symlink():
        raise ValueError(f'Narration scene {key} must not be a symbolic link')
    text_sha256 = _hash(scene.script_text.encode("utf-8"))
    if entry is None:
        if destination.exists():
            raise ValueError(f"Untracked narration file already exists: {destination}")
        return "missing"
    if not isinstance(entry, dict):
        raise ValueError(f'Invalid narration entry for scene {key}')
    if entry.get("text_sha256") != text_sha256:
        raise ValueError(f"Narration text changed for scene {key}")
    if entry.get("status") == "pending":
        if not destination.is_file():
            raise ValueError(f'NARRATION_REQUEST_UNVERIFIED: scene {key} has a pending request; '
                             'reconcile the existing provider result before any new submission')
        try:
            VideoEditor.validate_narration([str(destination)])
        except (OSError, ValueError) as error:
            raise ValueError(f'NARRATION_REQUEST_UNVERIFIED: scene {key} has an invalid saved output; '
                             'preserve it and reconcile the existing request') from error
        return "recoverable"
    if entry.get("status") != "complete" or not destination.is_file():
        raise ValueError(f"Incomplete or missing narration for scene {key}")
    if _hash(destination.read_bytes()) != entry.get("file_sha256"):
        raise ValueError(f"Narration file changed for scene {key}")
    VideoEditor.validate_narration([str(destination)])
    return "complete"


def inspect(script_content: bytes, output_dir: Path, voice: str, max_cost_usd: float,
            usd_per_million_characters: float) -> tuple:
    if voice not in VOICES:
        raise ValueError(f"Unknown TTS voice: {voice}")
    if (not math.isfinite(max_cost_usd) or max_cost_usd < 0
            or not math.isfinite(usd_per_million_characters)
            or usd_per_million_characters <= 0):
        raise ValueError("Cost ceiling and current TTS price must be finite and nonnegative")
    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to(settings.output_dir.resolve()):
        raise ValueError("Private narration output must stay under the ignored outputs directory")
    script = ShortsScript.model_validate_json(script_content)
    if len({scene.scene_number for scene in script.scenes}) != len(script.scenes):
        raise ValueError("Scene numbers must be unique")
    manifest = _manifest(script_content, output_dir, voice, usd_per_million_characters)
    states = [_scene_state(scene, manifest, output_dir) for scene in script.scenes]
    missing = [scene for scene, state in zip(script.scenes, states) if state == "missing"]
    if missing:
        require_model_active(VideoEditor.TTS_MODEL)
    def scene_reserve(scene) -> float:
        micro = (Decimal(len(scene.script_text)) * Decimal(str(usd_per_million_characters))).to_integral_value(rounding=ROUND_CEILING)
        return float(micro * VideoEditor.TTS_MAX_ATTEMPTS / 1_000_000)

    additional_reserve = round(sum(scene_reserve(scene) for scene in missing), 6)
    cumulative_reserve = round(manifest["reserved_usd_total"] + additional_reserve, 6)
    if cumulative_reserve > max_cost_usd:
        raise ValueError(f"Cumulative TTS request reserve ${cumulative_reserve:.6f} exceeds ceiling ${max_cost_usd:.6f}")
    result = {"voice": voice, "model": VideoEditor.TTS_MODEL,
              "missing_scenes": [scene.scene_number for scene in missing],
              "additional_request_reserve_usd": round(additional_reserve, 6),
              "cumulative_request_reserve_usd": round(cumulative_reserve, 6),
              "max_cost_usd": max_cost_usd,
              "output_dir": str(output_dir)}
    return script, manifest, states, missing, scene_reserve, result


async def prepare(script_path: Path, output_dir: Path, voice: str, max_cost_usd: float,
                  usd_per_million_characters: float, plan_only: bool = False, *,
                  cancelled: Callable[[], bool] = lambda: False) -> dict:
    script_content = script_path.read_bytes()
    output_dir = output_dir.resolve()
    script, manifest, states, missing, scene_reserve, result = inspect(
        script_content, output_dir, voice, max_cost_usd, usd_per_million_characters)
    if plan_only:
        return result
    if cancelled():
        raise ValueError('내레이션 준비를 중지했습니다. 저장된 음성은 보존합니다.')
    if missing:
        check_openai_speech_budget(
            VideoEditor.TTS_MODEL, [scene.script_text for scene in missing],
            VideoEditor.TTS_MAX_ATTEMPTS,
        )
        require_paid_production_enabled()
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required to generate narration")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with _narration_lock(output_dir):
        if (_hash(script_path.read_bytes()) != _hash(script_content)
                or _manifest(script_content, output_dir, voice, usd_per_million_characters) != manifest
                or [_scene_state(scene, manifest, output_dir) for scene in script.scenes] != states):
            raise ValueError('Narration input or state changed; inspect the existing set again')
        editor = VideoEditor(bgm_volume=0.0)
        try:
            for scene, state in zip(script.scenes, states):
                if cancelled():
                    raise ValueError('내레이션 준비를 중지했습니다. 완료한 장면은 보존하며 다음 장면을 요청하지 않습니다.')
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
            if cancelled():
                raise ValueError('내레이션 준비를 중지했습니다. 완료한 음성은 보존합니다.')
            audio_paths = [str(output_dir / f"scene_{scene.scene_number}.mp3") for scene in script.scenes]
            VideoEditor.validate_narration(audio_paths)
            return {**result, "audio_paths": audio_paths}
        finally:
            editor.cleanup_temp_files()



def _profile(script: ShortsScript, voice: str) -> tuple[bytes, Path]:
    content = script.model_dump_json().encode('utf-8')
    key = _hash(content + b'\0' + VideoEditor.TTS_MODEL.encode() + b'\0' + voice.encode())
    directory = settings.output_dir / 'evaluation' / 'narration_preparation' / key
    if directory.is_symlink() or not directory.resolve().is_relative_to(settings.output_dir.resolve()):
        raise ValueError('내레이션 보관 경로를 확인하세요.')
    return content, directory


def plan_narration(script: ShortsScript, voice: str) -> dict:
    """Read-only quote; reuse matching complete speech before buying a new set."""
    from shorts_maker.services.openai_budget import speech_price
    from shorts_maker.services.prepared_narration import list_narration_sets, narration_paths

    content, directory = _profile(script, voice)
    _, manifest, _, _, _, quote = inspect(content, directory, voice, 1_000_000, speech_price(VideoEditor.TTS_MODEL))
    manifest_path = directory / 'narration.json'
    # A pending profile must pass inspection even if another complete set exists.
    for path in list_narration_sets(script):
        record = json.loads(Path(path).read_text(encoding='utf-8'))
        if record.get('model') == VideoEditor.TTS_MODEL and record.get('voice') == voice:
            paths = narration_paths(script, path)
            VideoEditor.validate_narration(paths)
            return {**quote, 'manifest_path': path, 'missing_scenes': [],
                    'additional_request_reserve_usd': 0.0, 'reusable': True}
    return {**quote, 'manifest_path': str(manifest_path),
            'prior_request_reserve_usd': manifest['reserved_usd_total']}


async def prepare_script_narration(script: ShortsScript, voice: str, request_budget_usd: float,
                                   *, cancelled: Callable[[], bool]) -> str:
    from shorts_maker.services.openai_budget import speech_price

    if isinstance(request_budget_usd, bool) or not math.isfinite(request_budget_usd) or request_budget_usd < 0:
        raise ValueError('내레이션 요청 상한을 확인하세요.')
    quote = await asyncio.to_thread(plan_narration, script, voice)
    if quote['additional_request_reserve_usd'] > request_budget_usd:
        raise ValueError('내레이션 요청 예약액이 확인한 상한을 초과합니다. 다시 확인하세요.')
    if cancelled():
        raise ValueError('내레이션 준비를 중지했습니다. 저장된 음성은 보존합니다.')
    if quote.get('reusable'):
        return quote['manifest_path']
    content, directory = _profile(script, voice)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = directory / 'script.json'
    with _narration_lock(directory):
        if source.is_symlink() or (source.exists() and source.read_bytes() != content):
            raise ValueError('내레이션에 결합된 대본 파일을 확인하세요.')
        if not source.exists():
            # The profile mutex protects this immutable source from other preparers.
            with source.open('xb') as stream:
                os.chmod(source, 0o600)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
    await prepare(source, directory, voice,
                  round(quote.get('prior_request_reserve_usd', 0) + request_budget_usd, 6),
                  speech_price(VideoEditor.TTS_MODEL), cancelled=cancelled)
    return str((directory / 'narration.json').resolve())
