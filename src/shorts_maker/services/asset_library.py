"""Read existing local materials; delete only unreferenced disposable media."""

import hashlib
import html
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

from shorts_maker.utils.config import PROJECT_ROOT, settings


MEDIA = {
    '.mp4': '영상', '.mov': '영상', '.webm': '영상',
    '.png': '이미지', '.jpg': '이미지', '.jpeg': '이미지',
    '.mp3': '음성·음악', '.wav': '음성·음악', '.aiff': '음성·음악',
}
TEXT = {'.json', '.html', '.md', '.csv', '.txt', '.py', '.jsonl', '.srt', '.vtt'}


def file_hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class AssetLibrary:
    def __init__(self, *, roots=None, project_root=None, busy=None, active_references=None):
        self.roots = {key: Path(value).absolute() for key, value in (roots or {
            'outputs': settings.output_dir, 'temp': settings.temp_dir,
            'assets': settings.assets_dir, 'bgm': settings.bgm_dir, 'logs': settings.logs_dir,
        }).items()}
        self.project_root = Path(project_root or PROJECT_ROOT)
        self.busy = busy or (lambda: False)
        self.active_references = active_references or (lambda: [])

    def path(self, key: str) -> Path:
        """Resolve a library key without following even an in-root symlink."""
        group, separator, relative = key.partition('/')
        if not separator or group not in self.roots or not relative:
            raise ValueError('보관함 안의 파일을 선택하세요.')
        parts = Path(relative).parts
        if Path(relative).is_absolute() or any(part in {'.', '..'} for part in parts):
            raise ValueError('잘못된 파일 경로입니다.')
        root = self.roots[group]
        path = root.joinpath(*parts)
        if any(p.is_symlink() for p in [root, path, *path.parents] if p == root or p.is_relative_to(root)):
            raise ValueError('심볼릭 링크는 열거나 삭제할 수 없습니다.')
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError('파일이 없거나 보관함 밖의 경로입니다.')
        return path

    @staticmethod
    def _walk(root: Path, warnings: list) -> list[Path]:
        if root.is_symlink():
            warnings.append(f'링크 폴더 검사 불가: {root.name}')
            return []
        if not root.exists():
            return []
        files = []
        for directory, dirs, names in os.walk(root, followlinks=False,
                                               onerror=lambda e: warnings.append(f'폴더 검사 실패: {e.filename}')):
            for name in dirs[:]:
                if (Path(directory) / name).is_symlink():
                    dirs.remove(name)
                    warnings.append(f'링크 폴더 검사 불가: {name}')
            files.extend(Path(directory) / name for name in names)
        return files

    def scan(self) -> dict:
        warnings, rows, records = [], [], {}
        files = {key: self._walk(root, warnings) for key, root in self.roots.items()}
        reference_files = set(p for key, paths in files.items() if key != 'logs'
                              for p in paths if p.suffix.lower() in TEXT)
        for folder in ('docs', 'scripts'):
            reference_files.update(p for p in self._walk(self.project_root / folder, warnings)
                                   if p.suffix.lower() in TEXT)
        reference_files.update(self.project_root.glob('*.json'))
        reference_files.update(self.project_root.glob('*.md'))
        # A review copy may be a differently named symlink to a root edit.
        for paths in files.values():
            for path in paths:
                if path.is_symlink():
                    records[path] = str(path.resolve()).casefold()
        for path in sorted(reference_files):
            try:
                allowed = [*self.roots.values(), self.project_root / 'docs', self.project_root / 'scripts']
                if (path.is_symlink() and not any(path.resolve().is_relative_to(p.resolve()) for p in allowed)
                        or path.stat().st_size > 4 * 1024 * 1024):
                    raise ValueError('외부 링크 또는 큰 기록')
                content = path.read_text(encoding='utf-8')
                if path.suffix.lower() == '.json':
                    content = json.dumps(json.loads(content), ensure_ascii=False)
                records[path] = records.get(path, '') + unquote(html.unescape(content)).casefold()
            except (OSError, ValueError, UnicodeError):
                warnings.append(f'사용처 기록 검사 실패: {path.name}')
        active = json.dumps(self.active_references(), ensure_ascii=False).casefold()
        pending = any(p.name.endswith('.operation.pending.json') for paths in files.values() for p in paths)
        blocked = bool(warnings) or self.busy() or pending
        for group, paths in files.items():
            for path in paths:
                key = f'{group}/{path.relative_to(self.roots[group]).as_posix()}'
                try:
                    if path.is_symlink():
                        stat = path.lstat()
                        rows.append({'id': key, 'name': path.name, 'folder': group, 'kind': '링크',
                                     'bytes': stat.st_size, 'mtime': stat.st_mtime,
                                     'cleanable': False, 'reason': '링크 — 원본 보존·미리보기 제외'})
                        continue
                    safe = self.path(key)
                    stat = safe.stat()
                    terms = [safe.name.casefold(), *(p.name.casefold() for p in safe.parents
                             if p != self.roots[group] and p.is_relative_to(self.roots[group]))]
                    reason = self._protection(group, safe, stat)
                    if not reason:
                        if blocked:
                            reason = '제작 중·미확인 실행 또는 검사 오류 — 정리 보류'
                        elif any(term in active for term in terms):
                            reason = '현재 브라우저 작업에서 사용 중'
                        else:
                            # shortcut: conservative file/folder names; add a usage index before broader cache deletion.
                            reference = next((p for p, text in records.items()
                                              if not (group == 'outputs' and p == safe.with_suffix('.production.json'))
                                              and any(term in text for term in terms)), None)
                            if reference:
                                owner = reference.relative_to(self.project_root) if reference.is_relative_to(self.project_root) else reference.name
                                reason = f'사용처 기록: {owner}'
                    rows.append({'id': key, 'name': path.name, 'folder': group,
                                 'kind': MEDIA.get(path.suffix.lower(), '기록·기타'),
                                 'bytes': stat.st_size, 'mtime': stat.st_mtime,
                                 'cleanable': not bool(reason), 'reason': reason or '참조 없는 정리 후보'})
                except (OSError, ValueError):
                    warnings.append(f'파일 검사 불가: {key}')
        # A late file error also invalidates candidates already inspected.
        if warnings:
            for row in rows:
                if row['cleanable']:
                    row.update(cleanable=False, reason='검사 오류 — 정리 보류')
        total = sum(row['bytes'] for row in rows)
        disk = next((root for root in self.roots.values() if root.is_dir()), self.project_root)
        return {'rows': sorted(rows, key=lambda row: row['mtime'], reverse=True),
                'bytes': total, 'cleanable_bytes': sum(r['bytes'] for r in rows if r['cleanable']),
                'free_bytes': shutil.disk_usage(disk).free, 'warnings': list(dict.fromkeys(warnings)),
                'blocked': blocked or bool(warnings)}

    def _protection(self, group, path, stat) -> str:
        if stat.st_nlink != 1:
            return '공유 파일(하드링크) — 보존'
        if group == 'temp' and path.suffix.lower() in MEDIA:
            return '' if time.time() - stat.st_mtime > 86400 else '최근 24시간 임시 파일'
        if group != 'outputs' or path.parent != self.roots['outputs'] or path.suffix.lower() != '.mp4':
            return '원본·재사용 재료·기록 보존'
        sidecar = path.with_suffix('.production.json')
        try:
            self.path(f'outputs/{sidecar.name}')
            report = json.loads(sidecar.read_text(encoding='utf-8'))
            if (not isinstance(report, dict) or type(report.get('schema_version')) is not int or report['schema_version'] != 1
                    or report.get('video_path') != str(path) or report.get('quality_passed') is not True
                    or (report.get('video_sha256') is not None
                        and not re.fullmatch(r'[0-9a-f]{64}', str(report['video_sha256'])))):
                return '제작 기록 불완전 — 수동 대조 필요'
            if (report.get('youtube_id') or report.get('youtube_upload_request') is not None
                    or report.get('uploaded_at_utc') or path.with_suffix('.upload-pending.json').exists()):
                return '업로드됨 또는 업로드 결과 대조 필요'
            return ''
        except (OSError, ValueError, TypeError):
            return '제작 기록 없음·손상 — 수동 대조 필요'

    def preview(self, key: str) -> Path:
        path = self.path(key)
        if key.startswith('logs/') or path.suffix.lower() not in MEDIA:
            raise ValueError('이미지·영상·음성 파일만 미리 볼 수 있습니다.')
        return path

    @staticmethod
    def _identity(path: Path) -> dict:
        stat = path.stat()
        return {'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
                'inode': stat.st_ino, 'device': stat.st_dev, 'sha256': file_hash(path)}

    def prepare_delete(self, keys: list[str]) -> dict:
        scan = self.scan()
        rows = {row['id']: row for row in scan['rows']}
        if not keys:
            raise ValueError('정리할 파일을 먼저 선택하세요.')
        if scan['blocked']:
            raise ValueError('제작·업로드 중이거나 기록 검사가 불완전합니다. 종료·대조 후 새로고침하세요.')
        items = []
        for key in dict.fromkeys(keys):
            if key not in rows or not rows[key]['cleanable']:
                raise ValueError(f'보호된 파일은 삭제할 수 없습니다: {key}')
            path = self.path(key)
            identity = self._identity(path)
            if key.startswith('outputs/'):
                report = json.loads(path.with_suffix('.production.json').read_text(encoding='utf-8'))
                if report.get('video_sha256') and identity['sha256'] != report['video_sha256']:
                    raise ValueError(f'제작 기록과 파일 해시가 다릅니다: {key}')
            items.append({'id': key, **identity})
        return {'files': items, 'bytes': sum(item['bytes'] for item in items)}

    @staticmethod
    def _write_receipt(path: Path, record: dict):
        temporary = path.with_suffix('.tmp')
        try:
            with temporary.open('x', encoding='utf-8') as file:
                json.dump(record, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, plan: dict) -> dict:
        fresh = self.prepare_delete([item['id'] for item in plan['files']])
        if fresh != plan:
            raise ValueError('확인 후 파일이 변경됐습니다. 목록을 새로고침하세요.')
        directory = self.roots['outputs'] / 'evaluation' / 'storage_cleanup'
        if any(p.is_symlink() for p in [directory, *directory.parents]):
            raise ValueError('삭제 기록 폴더가 링크입니다.')
        directory.mkdir(parents=True, exist_ok=True)
        receipt = directory / f'{uuid4().hex}.json'
        record = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'state': 'pending',
                  'files': [{**item, 'state': 'pending'} for item in plan['files']], 'deleted_bytes': 0}
        self._write_receipt(receipt, record)
        for item in record['files']:
            try:
                if self.busy():
                    raise ValueError('제작·업로드가 시작되어 정리를 중단했습니다.')
                path = self.path(item['id'])
                if self._identity(path) != {key: item[key] for key in ('bytes', 'mtime_ns', 'inode', 'device', 'sha256')}:
                    raise ValueError('파일이 변경되어 정리를 중단했습니다.')
                path.unlink()
                item['state'] = 'deleted'
                record['deleted_bytes'] += item['bytes']
            except (OSError, ValueError) as error:
                item.update(state='failed', error=str(error))
                record['state'] = 'partial_failure'
                self._write_receipt(receipt, record)
                return record
            self._write_receipt(receipt, record)
        record['state'] = 'deleted'
        self._write_receipt(receipt, record)
        return record
