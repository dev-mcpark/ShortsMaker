"""안전한 UI 작업 유틸리티 - 클라이언트 연결 끊김 처리"""

from nicegui import ui
from typing import Callable, Any
import logging

logger = logging.getLogger(__name__)


def safe_notify(
    message: str,
    type: str = 'info',
    **kwargs
) -> bool:
    """
    안전하게 알림 표시. 클라이언트 연결 끊김 시 False 반환.

    Args:
        message: 알림 메시지
        type: 알림 타입 ('positive', 'negative', 'warning', 'info')
        **kwargs: ui.notify에 전달할 추가 인자

    Returns:
        bool: 성공 시 True, 실패 시 False
    """
    try:
        ui.notify(message, type=type, **kwargs)
        return True
    except RuntimeError as e:
        logger.debug(f"UI notify skipped: {e}")
        return False


def safe_refresh(refreshable: Callable) -> bool:
    """
    @ui.refreshable 함수를 안전하게 새로고침.

    Args:
        refreshable: @ui.refreshable 데코레이터가 적용된 함수

    Returns:
        bool: 성공 시 True, 실패 시 False
    """
    try:
        refreshable.refresh()
        return True
    except RuntimeError as e:
        logger.debug(f"UI refresh skipped: {e}")
        return False


def safe_update(element: Any, **updates) -> bool:
    """
    UI 요소를 안전하게 업데이트.

    Args:
        element: NiceGUI UI 요소
        **updates: 업데이트할 속성들

    Returns:
        bool: 성공 시 True, 실패 시 False
    """
    try:
        for key, value in updates.items():
            setattr(element, key, value)
        if hasattr(element, 'update'):
            element.update()
        return True
    except RuntimeError as e:
        logger.debug(f"UI update skipped: {e}")
        return False


def safe_set_visibility(element: Any, visible: bool) -> bool:
    """
    UI 요소의 가시성을 안전하게 설정.

    Args:
        element: NiceGUI UI 요소
        visible: 표시 여부

    Returns:
        bool: 성공 시 True, 실패 시 False
    """
    try:
        element.visible = visible
        return True
    except RuntimeError as e:
        logger.debug(f"Visibility update skipped: {e}")
        return False


def safe_set_text(element: Any, text: str) -> bool:
    """
    UI 요소의 텍스트를 안전하게 설정.

    Args:
        element: NiceGUI UI 요소
        text: 설정할 텍스트

    Returns:
        bool: 성공 시 True, 실패 시 False
    """
    try:
        element.text = text
        return True
    except RuntimeError as e:
        logger.debug(f"Text update skipped: {e}")
        return False


def safe_classes(element: Any, remove: str = '', add: str = '') -> bool:
    """
    UI 요소의 CSS 클래스를 안전하게 변경.

    Args:
        element: NiceGUI UI 요소
        remove: 제거할 클래스
        add: 추가할 클래스

    Returns:
        bool: 성공 시 True, 실패 시 False
    """
    try:
        element.classes(remove=remove, add=add)
        return True
    except RuntimeError as e:
        logger.debug(f"Classes update skipped: {e}")
        return False
