"""Private, bounded, immutable local text snapshots shared by Studio draft types."""

import hashlib
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from shorts_maker.utils.config import settings


MAX_BYTES = 2 * 1024 * 1024
_NAME = re.compile(r'draft_\d{8}T\d{6}Z_[0-9a-f]{32}\.json')
Folder = Literal['studio_drafts', 'publishing_drafts']


def snapshot_directory(folder: Folder) -> Path:
    if folder not in {'studio_drafts', 'publishing_drafts'}:
        raise ValueError('지원하는 초안 보관 폴더가 아닙니다.')
    root = settings.output_dir / 'evaluation' / folder
    if (root.is_symlink() or root.parent.is_symlink()
            or not root.resolve().is_relative_to(settings.output_dir.resolve())):
        raise ValueError('초안 보관 폴더의 경로를 확인하세요.')
    return root


def publish_snapshot(folder: Folder, content: bytes) -> Path:
    if len(content) > MAX_BYTES:
        raise ValueError('초안은 2 MiB 이하로 저장하세요. 현재 입력은 유지됩니다.')
    root = snapshot_directory(folder)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / f'draft_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid4().hex}.json'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=root, prefix='.draft_', suffix='.tmp', delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.link(temporary, path)  # Publish atomically without replacing an older snapshot.
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return path


def read_snapshot(folder: Folder, name: str) -> tuple[bytes, str]:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError('저장된 초안을 목록에서 선택하세요.')
    path = snapshot_directory(folder) / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('초안 파일의 경로·크기를 확인하세요.')
    with path.open('rb') as file:
        content = file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError('초안 파일은 2 MiB 이하여야 합니다.')
    return content, hashlib.sha256(content).hexdigest()


def snapshot_paths(folder: Folder) -> list[Path]:
    try:
        return [path for path in snapshot_directory(folder).iterdir()
                if path.name.startswith('draft_') and path.suffix == '.json']
    except FileNotFoundError:
        return []
