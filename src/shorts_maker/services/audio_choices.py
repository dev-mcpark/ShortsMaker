"""Explicit per-script audio choices; never credentials or production approvals."""

import json
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shorts_maker.services.production_service import script_sha256
from shorts_maker.utils.bgm_manager import BGMManager
from shorts_maker.utils.config import settings


class AudioChoices(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    tts_voice: Literal['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer']
    bgm_mood: str = Field(min_length=1, max_length=80)
    bgm_track: str = Field(max_length=255)
    bgm_volume: float = Field(ge=0, le=1, allow_inf_nan=False)
    prepared_narration_manifest: str | None = Field(default=None, min_length=1, max_length=4096)
    prepared_narration_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def narration_binding(self):
        if (self.prepared_narration_manifest is None) != (self.prepared_narration_sha256 is None):
            raise ValueError('저장할 내레이션 선택과 해시를 함께 확인하세요.')
        return self


def _path(script) -> Path:
    return settings.output_dir / 'audio_choices' / f'{script_sha256(script.model_dump())}.json'


def _recovery_bytes(script) -> bytes:
    path = _path(script)
    if (path.is_symlink() or path.parent.is_symlink()
            or not path.resolve().is_relative_to(settings.output_dir.resolve())):
        raise ValueError('음성 설정 파일의 경로를 확인하세요.')
    with path.open('rb') as stream:
        content = stream.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise ValueError('음성 설정 원본이 너무 커서 안전하게 사본을 보관할 수 없습니다.')
    return content


def audio_choice_fingerprint(script) -> str:
    return hashlib.sha256(_recovery_bytes(script)).hexdigest()


def reset_audio_choices(script, expected_sha256: str) -> Path:
    """Explicit repair preserves the exact previous record before resetting connections."""
    content = _recovery_bytes(script)
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError('음성 설정이 바뀌었습니다. 대본을 다시 불러와 확인하세요.')
    try:
        load_audio_choices(script)
    except ValueError:
        pass
    else:
        raise ValueError('저장된 설정을 다시 읽을 수 있습니다. 복구 대신 대본을 다시 불러오세요.')
    path = _path(script)
    backup = path.with_name(f'{path.stem}.backup_{uuid4().hex}.json')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=path.parent, prefix='.audio_backup_', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, backup)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    save_audio_choices(script, {'tts_voice': 'alloy', 'bgm_mood': 'auto', 'bgm_track': '', 'bgm_volume': 0.0})
    return backup


def save_audio_choices(script, choices: dict) -> Path:
    from shorts_maker.services.prepared_narration import narration_paths

    choices = AudioChoices.model_validate(choices)
    if choices.prepared_narration_manifest:
        narration_paths(script, choices.prepared_narration_manifest, choices.prepared_narration_sha256)
    path = _path(script)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', delete=False) as file:
            temporary = Path(file.name)
            json.dump({'script_sha256': script_sha256(script.model_dump()),
                       'choices': choices.model_dump()}, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return path


def load_audio_choices(script) -> dict | None:
    path = _path(script)
    try:
        if not path.exists():
            return None
        record = json.loads(_recovery_bytes(script).decode('utf-8'))
        if record['script_sha256'] != script_sha256(script.model_dump()):
            raise ValueError('각본 해시 불일치')
        choices = AudioChoices.model_validate(record['choices']).model_dump()
        manager = BGMManager()
        if choices['bgm_track'] and not manager.get_track_path(choices['bgm_track']):
            raise ValueError('선택한 음악 파일과 권한 기록을 확인하세요.')
        if choices['bgm_mood'] != 'auto' and not manager.get_bgm_path(choices['bgm_mood']):
            raise ValueError('선택한 음악 분위기를 확인하세요.')
        return choices
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError('저장된 음성·음악 설정을 확인할 수 없습니다.') from error
