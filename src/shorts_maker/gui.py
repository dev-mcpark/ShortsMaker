"""
ShortsMaker Studio - GUI Entry Point

Minimized entry point for the NiceGUI application.
All UI logic has been modularized into the gui/ package.

Usage:
    python -m shorts_maker.gui
    or
    python src/shorts_maker/gui.py
"""

from nicegui import ui, app
import logging

from shorts_maker.gui.pages import render_main_page
from shorts_maker.utils.logger import setup_logging, get_logger

# --- Logging Setup ---
setup_logging()
logger = get_logger(__name__)


class NiceGuiLogHandler(logging.Handler):
    """Captures logs and stores them for UI display"""

    def __init__(self):
        super().__init__()
        self.logs = []
        self.max_logs = 100

    def emit(self, record):
        log_entry = self.format(record)
        self.logs.append(log_entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)


# Global log handler for UI
log_handler = NiceGuiLogHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(log_handler)


# --- App Configuration ---
@app.on_startup
async def startup():
    """App startup hook"""
    logger.info("ShortsMaker Studio started")


@app.on_shutdown
async def shutdown():
    """App shutdown hook"""
    logger.info("ShortsMaker Studio shutting down")


# --- Main Page Route ---
@ui.page('/')
def main():
    """Main application page"""
    ui.dark_mode().enable()
    render_main_page()


# --- Entry Point ---
if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="ShortsMaker Studio",
        favicon="🎬",
        dark=True,
        reload=True,
        port=8080,
        storage_secret="shortsmaker_secret_key_change_in_production"
    )
