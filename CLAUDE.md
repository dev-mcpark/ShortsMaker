# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ShortsMaker Studio** is a local AI video production tool built with **NiceGUI**.
It allows users to generate YouTube Shorts from RSS feeds or URLs using a Human-in-the-Loop workflow.

## Essential Commands

### Build & Run
- **Run App:** `python src/shorts_maker/gui.py`
- **Install Dependencies:** `uv sync`
- **Lint:** `ruff check .`

### Environment Setup
Create a `.env` file:
```ini
OPENAI_API_KEY=sk-...
GCP_PROJECT_ID=...
GOOGLE_APPLICATION_CREDENTIALS=service_account.json
```

## Architecture

### Module Structure
```
src/shorts_maker/
├── gui.py                 # NiceGUI Entry Point & UI Logic
├── planner/
│   └── script_planner.py  # Script generation (GPT-4o)
├── generator/
│   └── video_generator.py # Visuals (Veo/Imagen)
├── editor/
│   └── video_editor.py    # Composition (MoviePy)
├── uploader/
│   └── youtube_uploader.py# YouTube API
└── utils/
    └── source_manager.py  # RSS Feed Management
```

### Key Design Patterns
- **Async UI:** Uses NiceGUI's native async support. No separate worker threads/processes needed.
- **State Management:** `AppState` class in `gui.py` holds runtime data (script, clips, video path).
- **Live Logging:** Captures python logging and streams it to a textarea in the UI.

## Development Workflow
1.  Run `python src/shorts_maker/gui.py`.
2.  NiceGUI supports auto-reloading for UI changes.
3.  Core logic changes (planner/generator) may require a restart.