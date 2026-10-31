"""Explicit per-script audio choices; never credentials or production approvals."""

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shorts_maker.services.production_service import script_sha256
from shorts_maker.utils.bgm_manager import BGMManager
from shorts_maker.utils.config import settings


class AudioChoices(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    tts_voice: Literal['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer']
    bgm_mood: str = Field(min_length=1, max_length=80)
    bgm_track: str = Field(max_length=255)
    bgm_volume: float = Field(ge=0, le=1, allow_inf_nan=False)


def _path(script) -> Path:
    return settings.output_dir / 'audio_choices' / f'{script_sha256(script.model_dump())}.json'


def save_audio_choices(script, choices: dict) -> Path:
    choices = AudioChoices.model_validate(choices)
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
