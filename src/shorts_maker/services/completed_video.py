"""Verify a finished local video against its production report."""

import hashlib
import json
from pathlib import Path

from shorts_maker.utils.config import settings


def completed_video(path: str) -> dict:
    video = Path(path).resolve()
    root = settings.output_dir.resolve()
    report_path = video.with_suffix('.production.json').resolve()
    if (not video.is_file() or video.suffix.lower() != '.mp4'
            or not video.is_relative_to(root) or not report_path.is_relative_to(root)):
        raise ValueError('출력 폴더 안의 완성 MP4를 선택하세요.')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    with video.open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    if (not isinstance(report, dict) or report.get('schema_version') != 1
            or report.get('video_path') != str(video)
            or report.get('quality_passed') is not True or report.get('video_sha256') != digest):
        raise ValueError('영상과 일치하는 품질 통과 기록·파일 해시가 필요합니다.')
    return report
