"""Select local music only when its no-attribution license is documented."""

import hashlib
import json
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger

logger = get_logger(__name__)

class BGMManager:
    def __init__(self):
        self.bgm_dir = Path(settings.bgm_dir)
        self.bgm_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _documented(track: Path) -> bool:
        record = Path(f"{track}.license.json")
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
            source = urlparse(data["source_url"])
            return (
                bool(data["title"] and data["artist"] and data["license"])
                and source.scheme == "https" and bool(source.netloc)
                and data["attribution_required"] is False
                and hashlib.sha256(track.read_bytes()).hexdigest() == data["sha256"]
            )
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def get_bgm_path(self, mood: str) -> Optional[str]:
        mood = mood.lower()
        category = {
            "luxury": "corporate", "sci-fi": "mysterious",
            "suspense": "mysterious", "emotional": "calm",
        }.get(mood, mood)
        tracks = sorted(self.bgm_dir.glob("*.mp3"))
        for prefix in dict.fromkeys((category, mood)):
            for track in tracks:
                if track.name.startswith(prefix) and self._documented(track):
                    logger.info("Selected documented BGM: %s", track.name)
                    return str(track)
        return None
