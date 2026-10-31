"""Browser session to in-memory application state mapping."""

import uuid

from nicegui import app

from shorts_maker.gui.state.app_state import AppState
from shorts_maker.utils.config import settings


class SessionManager:
    # shortcut: sessions stay process-local; recover saved scripts and their audio choices after restart.
    _sessions: dict[str, AppState] = {}

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
