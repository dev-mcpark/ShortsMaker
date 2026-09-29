"""RSS 피드 캐싱 유틸리티 (TTL 기반)"""

import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from shorts_maker.utils.logger import get_logger


class RSSCache:
    """URL 해시 키 기반 TTL 캐시.

    동일 RSS 피드를 짧은 시간 안에 반복 요청할 때 API 호출을 줄입니다.
    스레드 안전성은 보장하지 않으며, 단일 이벤트 루프 환경(NiceGUI)에서만 사용합니다.
    """

    def __init__(self, ttl_minutes: int = 30) -> None:
        self._cache: Dict[str, Tuple[List[Dict], datetime]] = {}
        self._ttl = timedelta(minutes=ttl_minutes)
        self.logger = get_logger(__name__)

    # ── private helpers ───────────────────────────────────────────────────────

    def _key(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()

    # ── public API ────────────────────────────────────────────────────────────

    def get(self, url: str) -> Optional[List[Dict]]:
        """캐시 조회. 만료된 항목은 자동 삭제 후 None 반환."""
        key = self._key(url)
        if key not in self._cache:
            return None
        data, saved_at = self._cache[key]
        if datetime.now() - saved_at < self._ttl:
            self.logger.debug(f"캐시 히트: {url[:60]}")
            return data
        del self._cache[key]
        return None

    def set(self, url: str, data: List[Dict]) -> None:
        """캐시 저장."""
        self._cache[self._key(url)] = (data, datetime.now())
        self.logger.debug(f"캐시 저장: {url[:60]} ({len(data)}건)")

    def clear(self) -> None:
        """전체 캐시 삭제."""
        self._cache.clear()

    def clear_expired(self) -> int:
        """만료 항목만 삭제. 삭제된 항목 수 반환."""
        now = datetime.now()
        expired = [k for k, (_, ts) in self._cache.items() if now - ts >= self._ttl]
        for k in expired:
            del self._cache[k]
        return len(expired)

    def __len__(self) -> int:
        return len(self._cache)
