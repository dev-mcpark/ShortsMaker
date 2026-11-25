"""Read the local upload claim without clearing or repeating the request."""

import json
import re
import stat
from datetime import datetime
from pathlib import Path


def has_unresolved_upload_claim(video: Path, report: dict, video_sha256: str) -> bool:
    """A retained claim can coexist with an exact private result saved after submission."""
    marker = video.with_suffix('.upload-pending.json')
    try:
        attributes = marker.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if not stat.S_ISREG(attributes.st_mode) or attributes.st_size > 64 * 1024:
        return True
    video_id = report.get('youtube_id')
    request = report.get('youtube_upload_request')
    disclosure = report.get('contains_synthetic_media')
    if (not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{6,64}', video_id)
            or not isinstance(request, dict) or not isinstance(request.get('status'), dict)
            or request['status'].get('privacyStatus') != 'private'
            or type(disclosure) is not bool or request['status'].get('containsSyntheticMedia') is not disclosure
            or report.get('video_sha256') != video_sha256):
        return True
    try:
        with marker.open('rb') as stream:
            data = stream.read(64 * 1024 + 1)
        if len(data) > 64 * 1024:
            return True
        claim = json.loads(data)
        if (not isinstance(claim, dict) or claim.get('video_path') != str(video)
                or claim.get('video_sha256') != video_sha256 or claim.get('youtube_upload_request') != request):
            return True
        started = datetime.fromisoformat(claim['started_at_utc'])
        completed = datetime.fromisoformat(report['uploaded_at_utc'])
        return started.utcoffset() is None or completed.utcoffset() is None or completed <= started
    except (OSError, ValueError, KeyError, TypeError):
        return True
