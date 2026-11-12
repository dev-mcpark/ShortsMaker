"""Explicit per-script audio choices; never credentials or production approvals."""

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

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
        record = json.loads(path.read_text(encoding='utf-8'))
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
