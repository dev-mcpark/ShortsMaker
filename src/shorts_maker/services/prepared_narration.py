"""Discover retained narration by its scene text and file identities, without TTS."""

import hashlib
import json
import shutil
import uuid
from pathlib import Path

from shorts_maker.utils.config import settings


def retain_narration_set(script, audio_paths: list[str], voice: str) -> str:
    from shorts_maker.editor.video_editor import VideoEditor

    if len(audio_paths) != len(script.scenes):
        raise ValueError('보관할 음성과 장면 수가 일치하지 않습니다.')
    directory = settings.output_dir / 'evaluation' / 'narration_sets' / uuid.uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    record = {'schema_version': 1, 'model': VideoEditor.TTS_MODEL, 'voice': voice, 'scenes': {}}
    for scene, source in zip(script.scenes, audio_paths):
        target = directory / f'scene_{scene.scene_number}.mp3'
        shutil.copyfile(source, target)
        with target.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        record['scenes'][str(scene.scene_number)] = {
            'status': 'complete', 'text_sha256': hashlib.sha256(scene.script_text.encode()).hexdigest(),
            'file_sha256': digest,
        }
    manifest = directory / 'narration.json'
    with manifest.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False)
    return str(manifest.resolve())


def narration_paths(script, manifest_path: str, expected_sha256: str | None = None) -> list[str]:
    manifest = Path(manifest_path).resolve()
    root = settings.output_dir.resolve()
    if manifest.name != 'narration.json' or not manifest.is_relative_to(root):
        raise ValueError('outputs 안의 narration.json을 선택하세요.')
    content = manifest.read_bytes()
    if expected_sha256 is not None and hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError('선택·저장한 뒤 내레이션 기록이 변경됐습니다. 음성을 다시 확인하고 명시적으로 연결하세요.')
    record = json.loads(content)
    if (not isinstance(record, dict) or record.get('schema_version') != 1
            or not isinstance(record.get('scenes'), dict)):
        raise ValueError('내레이션 준비 기록이 올바르지 않습니다.')
    paths = []
    for scene in script.scenes:
        entry = record['scenes'].get(str(scene.scene_number))
        audio = (manifest.parent / f'scene_{scene.scene_number}.mp3').resolve()
        if not audio.is_relative_to(root) or not audio.is_file():
            raise ValueError(f'장면 {scene.scene_number} 음성 파일을 확인하세요.')
        with audio.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if (not isinstance(entry, dict) or entry.get('status') != 'complete'
                or entry.get('text_sha256') != hashlib.sha256(scene.script_text.encode()).hexdigest()
                or entry.get('file_sha256') != digest):
            raise ValueError(f'장면 {scene.scene_number} 음성이 현재 내레이션 또는 기록과 다릅니다.')
        paths.append(str(audio))
    if not paths:
        raise ValueError('내레이션이 있는 대본을 먼저 선택하세요.')
    return paths


def list_narration_sets(script) -> dict[str, str]:
    options = {}
    if script is None:
        return options
    for path in sorted(settings.output_dir.rglob('narration.json')):
        try:
            narration_paths(script, str(path))
            record = json.loads(path.read_text(encoding='utf-8'))
            options[str(path.resolve())] = f'{record.get("voice", "음성")} · {path.parent.relative_to(settings.output_dir)}'
        except (OSError, ValueError, TypeError):
            continue
    return options
