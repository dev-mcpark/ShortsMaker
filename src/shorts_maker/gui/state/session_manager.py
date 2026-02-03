"""세션 스토리지 관리"""

from nicegui import app
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class SessionManager:
    """브라우저 세션 스토리지 관리"""

    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        """세션에서 값 가져오기"""
        try:
            return app.storage.browser.get(key, default)
        except Exception as e:
            logger.debug(f"Session get failed: {e}")
            return default

    @staticmethod
    def set(key: str, value: Any) -> bool:
        """세션에 값 저장"""
        try:
            app.storage.browser[key] = value
            return True
        except Exception as e:
            logger.debug(f"Session set failed: {e}")
            return False

    @staticmethod
    def delete(key: str) -> bool:
        """세션에서 값 삭제"""
        try:
            if key in app.storage.browser:
                del app.storage.browser[key]
            return True
        except Exception as e:
            logger.debug(f"Session delete failed: {e}")
            return False

    @staticmethod
    def clear() -> bool:
        """세션 전체 초기화"""
        try:
            app.storage.browser.clear()
            return True
        except Exception as e:
            logger.debug(f"Session clear failed: {e}")
            return False

    @staticmethod
    def exists(key: str) -> bool:
        """키 존재 여부 확인"""
        try:
            return key in app.storage.browser
        except Exception:
            return False


# 편의를 위한 싱글톤
session = SessionManager()
