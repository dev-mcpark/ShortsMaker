"""Browser session to in-memory application state mapping."""

import uuid

from nicegui import app

from shorts_maker.gui.state.app_state import AppState
from shorts_maker.utils.config import settings


class SessionManager:
    # shortcut: sessions stay process-local; recover saved scripts and their audio choices after restart.
    _sessions: dict[str, AppState] = {}

    @classmethod
    def apply_api_settings(cls, state: AppState) -> None:
        changed = ((bool(state.openai_key) and state.openai_key != settings.openai_api_key)
                   or (bool(state.gcp_project) and state.gcp_project != settings.gcp_project_id))
        if not changed:
            return
        # Clients initialize lazily from process settings, including during an active edit.
        if any(other is not state and other.is_busy for other in cls._sessions.values()):
            raise ValueError('다른 Studio 창의 작업이 끝난 뒤 API 연결 설정을 적용하세요.')
        settings.update_api_keys(openai_key=state.openai_key, gcp_project=state.gcp_project)
        for other in cls._sessions.values():
            other.production_service = None
        state.production_service = None

    @classmethod
    def get_state(cls, session_id: str) -> AppState:
        if session_id not in cls._sessions:
            cls._sessions[session_id] = AppState(
                mode=settings.generation_mode,
                openai_key=settings.openai_api_key,
                gcp_project=settings.gcp_project_id,
            )
        return cls._sessions[session_id]


def get_session_state() -> AppState:
    browser = app.storage.browser
    if "session_id" not in browser:
        browser["session_id"] = str(uuid.uuid4())
    return SessionManager.get_state(browser["session_id"])
