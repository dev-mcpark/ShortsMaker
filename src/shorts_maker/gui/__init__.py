"""ShortsMaker GUI Package

Modular GUI architecture for ShortsMaker Studio.

Structure:
- config/: Constants and UI theme definitions
- state/: Application state management
- components/: Reusable UI components and tab modules
- pages/: Page-level compositions

Usage:
    from shorts_maker.gui.pages import render_main_page
"""

from .pages import render_main_page
from .state import AppState, state, SessionManager, session

__all__ = [
    'render_main_page',
    'AppState',
    'state',
    'SessionManager',
    'session',
]
