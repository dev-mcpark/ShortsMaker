# GUI Refactoring Design Document

> **Summary**: gui.py 모놀리식 코드 모듈화 상세 설계
>
> **Project**: ShortsMaker Studio
> **Version**: 0.1.0
> **Author**: Claude
> **Date**: 2026-02-03
> **Status**: Draft
> **Planning Doc**: [gui-refactoring.plan.md](../../01-plan/features/gui-refactoring.plan.md)

---

## 1. Overview

### 1.1 Design Goals

- 2,134줄 → 50줄로 gui.py 최소화
- 단일 책임 원칙(SRP) 준수
- 50+ 중복 코드 패턴 제거
- 300줄 이하 모듈 유지

### 1.2 Design Principles

- **Separation of Concerns**: 각 모듈은 하나의 책임만 담당
- **DRY (Don't Repeat Yourself)**: 중복 코드 유틸리티로 추출
- **Single Source of Truth**: 상수와 설정은 한 곳에서 관리
- **Dependency Injection**: 상태는 외부에서 주입

---

## 2. Architecture

### 2.1 현재 구조 (Before)

```
src/shorts_maker/
└── gui.py (2,134 lines - 모든 책임 혼재)
    ├── AppState (Line 23-63)
    ├── SessionManager (Line 65-97)
    ├── Logging Setup (Line 100-128)
    ├── Main Page Layout (Line 145-282)
    ├── Pipeline Tab (Line 297-775)
    ├── Sources Tab (Line 855-1066)
    ├── Planning Tab (Line 1068-1395)
    ├── Generation Tab (Line 1397-1712)
    ├── Publishing Tab (Line 1714-1758)
    └── Scheduling Tab (Line 1760-2108)
```

### 2.2 목표 구조 (After)

```
src/shorts_maker/
├── gui.py                         # Entry point (~50 lines)
│
├── gui/                           # GUI 모듈 패키지
│   ├── __init__.py
│   │
│   ├── state/                     # State Management
│   │   ├── __init__.py
│   │   ├── app_state.py           # AppState dataclass (~70 lines)
│   │   └── session_manager.py     # SessionManager (~40 lines)
│   │
│   ├── components/                # UI Components
│   │   ├── __init__.py
│   │   ├── common/                # Shared utilities
│   │   │   ├── __init__.py
│   │   │   ├── safe_ui.py         # Safe UI operations (~50 lines)
│   │   │   ├── card_header.py     # Card header component (~40 lines)
│   │   │   ├── step_indicator.py  # Step indicator (~60 lines)
│   │   │   └── error_panel.py     # Error panel (~40 lines)
│   │   │
│   │   ├── pipeline_tab.py        # Pipeline tab (~200 lines)
│   │   ├── sources_tab.py         # Sources tab (~150 lines)
│   │   ├── planning_tab.py        # Planning tab (~200 lines)
│   │   ├── generation_tab.py      # Generation tab (~200 lines)
│   │   ├── publishing_tab.py      # Publishing tab (~80 lines)
│   │   └── scheduling_tab.py      # Scheduling tab (~200 lines)
│   │
│   ├── pages/                     # Page compositions
│   │   ├── __init__.py
│   │   └── main_page.py           # Main page (~150 lines)
│   │
│   └── config/                    # Configuration
│       ├── __init__.py
│       ├── constants.py           # Magic numbers (~50 lines)
│       └── ui_theme.py            # CSS classes, colors (~80 lines)
```

### 2.3 Dependencies

```
gui.py (entry)
    │
    └──▶ gui/pages/main_page.py
              │
              ├──▶ gui/components/*_tab.py
              │         │
              │         ├──▶ gui/components/common/*
              │         ├──▶ gui/state/app_state.py
              │         └──▶ gui/config/*
              │
              ├──▶ gui/state/app_state.py
              └──▶ gui/config/constants.py
```

**순환 임포트 방지 규칙**:
- `config/` → 다른 모듈 임포트 금지
- `state/` → `config/`만 임포트 가능
- `components/common/` → `config/`, `state/`만 임포트 가능
- `components/*_tab.py` → 모든 하위 모듈 임포트 가능
- `pages/` → 모든 모듈 임포트 가능

---

## 3. Detailed Design

### 3.1 Phase 1: 공통 유틸리티 추출

#### 3.1.1 `gui/config/constants.py`

```python
"""UI 상수 정의"""

# Display Limits
MAX_HISTORY_ITEMS = 5
MAX_RECENT_VIDEOS = 5
MAX_RECENT_SCRIPTS = 5
MAX_EXECUTION_HISTORY = 10

# Timing
SCHEDULER_REFRESH_INTERVAL = 30.0
PROGRESS_UPDATE_INTERVAL = 0.5

# Cost Estimation
SCENE_COST_MULTIPLIER = 0.05

# UI Dimensions
SIDEBAR_HEIGHT = 'h-[calc(100vh-3rem)]'
CARD_PADDING = 'p-4'

# Phase Names
PHASE_NAMES = ['Script', 'Visuals', 'Edit', 'Compose', 'Upload']
```

#### 3.1.2 `gui/config/ui_theme.py`

```python
"""UI 테마 및 스타일 정의"""

# Gradient Colors
GRADIENTS = {
    'primary': 'from-teal-500 to-cyan-600',
    'secondary': 'from-pink-500 to-rose-600',
    'success': 'from-green-500 to-teal-600',
    'warning': 'from-amber-500 to-orange-600',
    'danger': 'from-red-500 to-pink-600',
    'info': 'from-blue-500 to-indigo-600',
    'purple': 'from-purple-500 to-indigo-600',
}

# Phase Colors (for step indicators)
PHASE_COLORS = ['pink', 'purple', 'indigo', 'blue', 'teal']

# Scene Card Gradients
SCENE_GRADIENTS = [
    'from-pink-500 to-rose-600',
    'from-purple-500 to-indigo-600',
    'from-blue-500 to-cyan-600',
    'from-teal-500 to-green-600',
    'from-amber-500 to-orange-600',
]

# Common CSS Classes
CARD_BASE = 'w-full p-0 bg-slate-800 border border-slate-700 overflow-hidden'
CARD_HEADER = 'w-full p-4'
HEADER_TEXT = 'text-lg font-bold text-white'
LABEL_MUTED = 'text-xs text-gray-400 uppercase tracking-wider'
```

#### 3.1.3 `gui/components/common/safe_ui.py`

```python
"""안전한 UI 작업 유틸리티 - 클라이언트 연결 끊김 처리"""

from nicegui import ui
from typing import Callable, Any, Optional
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
    """UI 요소의 가시성을 안전하게 설정."""
    try:
        element.visible = visible
        return True
    except RuntimeError as e:
        logger.debug(f"Visibility update skipped: {e}")
        return False
```

---

### 3.2 Phase 2: 상태 관리 분리

#### 3.2.1 `gui/state/app_state.py`

```python
"""애플리케이션 상태 관리"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from shorts_maker.services.production_service import ProductionService, ProductionPhase


@dataclass
class AppState:
    """전역 애플리케이션 상태"""

    # API Keys (사용자 입력)
    openai_key: str = ""
    gcp_project: str = ""

    # Production Mode
    mode: str = "video"  # "video" or "image"

    # Pipeline State
    pipeline_running: bool = False
    pipeline_phase: ProductionPhase = ProductionPhase.IDLE
    pipeline_progress: float = 0.0
    pipeline_message: str = ""

    # Scene Progress
    scene_progresses: Dict[int, float] = field(default_factory=dict)
    total_scenes: int = 0
    completed_scenes: int = 0
    current_scene: int = 0

    # Timing
    elapsed_seconds: float = 0.0
    estimated_seconds: float = 0.0
    phase_times: Dict[str, float] = field(default_factory=dict)

    # Results
    script: Any = None
    scene_clips: List[str] = field(default_factory=list)

    # Service Reference
    production_service: Optional[ProductionService] = None

    # Error State
    last_error: Optional[str] = None

    # History
    pipeline_history: List[Dict] = field(default_factory=list)

    def reset_pipeline(self) -> None:
        """파이프라인 상태 초기화"""
        self.pipeline_running = False
        self.pipeline_phase = ProductionPhase.IDLE
        self.pipeline_progress = 0.0
        self.pipeline_message = ""
        self.scene_progresses.clear()
        self.total_scenes = 0
        self.completed_scenes = 0
        self.current_scene = 0
        self.elapsed_seconds = 0.0
        self.estimated_seconds = 0.0
        self.last_error = None

    def add_to_history(self, title: str, success: bool) -> None:
        """실행 이력에 추가"""
        from datetime import datetime
        self.pipeline_history.append({
            'title': title,
            'success': success,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
        })


# 싱글톤 인스턴스
state = AppState()
```

#### 3.2.2 `gui/state/session_manager.py`

```python
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


# 편의를 위한 싱글톤
session = SessionManager()
```

---

### 3.3 Phase 3: 공통 컴포넌트 추출

#### 3.3.1 `gui/components/common/card_header.py`

```python
"""재사용 가능한 카드 헤더 컴포넌트"""

from nicegui import ui
from typing import Optional
from gui.config.ui_theme import GRADIENTS, CARD_BASE, HEADER_TEXT


def card_with_header(
    title: str,
    icon: str,
    gradient: str = 'primary',
    badge_text: Optional[str] = None
):
    """
    헤더가 있는 카드 컴포넌트 생성.

    Args:
        title: 카드 제목
        icon: Material icon 이름
        gradient: GRADIENTS의 키 또는 직접 지정된 그라디언트
        badge_text: 선택적 뱃지 텍스트

    Returns:
        card: 카드 컨텍스트 (with 문에서 사용)

    Example:
        with card_with_header('Settings', 'settings', 'primary') as card:
            ui.label('Content here')
    """
    gradient_class = GRADIENTS.get(gradient, gradient)

    card = ui.card().classes(CARD_BASE)

    with card:
        with ui.element('div').classes(f'w-full p-4 bg-gradient-to-r {gradient_class}'):
            with ui.row().classes('items-center gap-3'):
                ui.icon(icon, size='md').classes('text-white')
                ui.label(title).classes(HEADER_TEXT)
                if badge_text:
                    ui.badge(badge_text).classes('bg-white/20 text-white text-xs')

    return card


def section_header(title: str, icon: str, color: str = 'teal'):
    """
    섹션 내 작은 헤더.

    Args:
        title: 헤더 제목
        icon: Material icon 이름
        color: 아이콘 색상 (tailwind color name)
    """
    with ui.element('div').classes('w-full p-3 border-b border-slate-700'):
        with ui.row().classes('items-center gap-2'):
            ui.icon(icon, size='xs').classes(f'text-{color}-400')
            ui.label(title).classes(f'text-sm font-bold text-{color}-300')
```

#### 3.3.2 `gui/components/common/step_indicator.py`

```python
"""파이프라인 단계 표시기"""

from nicegui import ui
from typing import List, Dict
from gui.config.ui_theme import PHASE_COLORS
from gui.config.constants import PHASE_NAMES


def create_step_indicators() -> Dict[str, ui.element]:
    """
    파이프라인 단계 표시기 생성.

    Returns:
        Dict with 'progress_bars', 'phase_labels', 'phase_time_labels' keys
    """
    progress_bars = {}
    phase_labels = {}
    phase_time_labels = {}

    with ui.row().classes('w-full gap-1 mb-4'):
        for i, (phase, color) in enumerate(zip(PHASE_NAMES, PHASE_COLORS)):
            with ui.column().classes('flex-1 gap-1'):
                # Phase label
                phase_labels[phase] = ui.label('Pending').classes(
                    f'text-[10px] text-gray-400 text-center w-full'
                )

                # Progress bar
                progress_bars[phase] = ui.linear_progress(
                    value=0, show_value=False
                ).props(f'color={color}').classes('h-1')

                # Time label
                with ui.row().classes('items-center justify-center gap-1'):
                    ui.icon(
                        ['edit', 'image', 'movie', 'merge_type', 'upload'][i],
                        size='xs'
                    ).classes(f'text-{color}-400')
                    phase_time_labels[phase] = ui.label('').classes(
                        'text-[10px] text-gray-500'
                    )

    return {
        'progress_bars': progress_bars,
        'phase_labels': phase_labels,
        'phase_time_labels': phase_time_labels
    }


def update_step_indicator(
    phase_labels: Dict[str, ui.label],
    phase: str,
    status: str,
    color_class: str
) -> None:
    """
    특정 단계의 상태 업데이트.

    Args:
        phase_labels: 단계 라벨 딕셔너리
        phase: 단계 이름
        status: 상태 텍스트
        color_class: Tailwind 색상 클래스
    """
    if phase in phase_labels:
        label = phase_labels[phase]
        label.text = status
        label.classes(
            remove='text-gray-400 text-teal-400 text-pink-400 text-red-400',
            add=color_class
        )
```

#### 3.3.3 `gui/components/common/error_panel.py`

```python
"""에러 표시 패널 컴포넌트"""

from nicegui import ui
from typing import Optional


def create_error_panel() -> tuple:
    """
    에러 표시 패널 생성.

    Returns:
        tuple: (error_panel, error_message_label, error_details_label)
    """
    error_panel = ui.card().classes(
        'w-full bg-red-900/30 border border-red-500/50'
    )
    error_panel.visible = False

    with error_panel:
        with ui.row().classes('items-start gap-3 p-4'):
            ui.icon('error', size='md').classes('text-red-400')
            with ui.column().classes('flex-grow gap-1'):
                error_message_label = ui.label('Error').classes(
                    'text-red-300 font-bold'
                )
                error_details_label = ui.label('').classes(
                    'text-red-200/70 text-sm'
                )

    return error_panel, error_message_label, error_details_label


def show_error_panel(
    error_panel: ui.card,
    message_label: ui.label,
    details_label: ui.label,
    error_message: str,
    show_details: bool = True
) -> None:
    """
    에러 패널 표시.

    Args:
        error_panel: 에러 패널 카드
        message_label: 메시지 라벨
        details_label: 상세 정보 라벨
        error_message: 에러 메시지
        show_details: 상세 정보 표시 여부
    """
    error_panel.visible = True
    message_label.text = 'Pipeline Error'

    if show_details:
        # 에러 메시지 잘라서 표시
        short_msg = error_message[:200] + '...' if len(error_message) > 200 else error_message
        details_label.text = short_msg
    else:
        details_label.text = ''


def hide_error_panel(error_panel: ui.card) -> None:
    """에러 패널 숨기기."""
    error_panel.visible = False
```

---

### 3.4 Phase 4: 탭 컴포넌트 분리

#### 3.4.1 탭 컴포넌트 공통 패턴

각 탭 컴포넌트는 다음 패턴을 따릅니다:

```python
"""[Tab Name] 탭 컴포넌트"""

from nicegui import ui
from typing import Optional

from gui.state.app_state import state
from gui.components.common.safe_ui import safe_notify, safe_refresh
from gui.components.common.card_header import card_with_header
from gui.config.constants import *
from gui.config.ui_theme import *


def render_[tab_name]_tab() -> None:
    """[Tab Name] 탭 렌더링"""

    # --- Local helper functions ---
    def _helper_function():
        pass

    # --- UI rendering ---
    with ui.column().classes('w-full gap-4'):
        # Tab content here
        pass
```

#### 3.4.2 `gui/components/pipeline_tab.py` (핵심 예시)

```python
"""Pipeline 실행 탭 컴포넌트"""

from nicegui import ui
import asyncio
from typing import Optional

from gui.state.app_state import state
from gui.components.common.safe_ui import safe_notify, safe_refresh, safe_update
from gui.components.common.card_header import card_with_header, section_header
from gui.components.common.step_indicator import create_step_indicators, update_step_indicator
from gui.components.common.error_panel import create_error_panel, show_error_panel, hide_error_panel
from gui.config.constants import MAX_HISTORY_ITEMS, PHASE_NAMES
from gui.config.ui_theme import GRADIENTS, SCENE_GRADIENTS

from shorts_maker.services.production_service import ProductionService, ProductionPhase, ProductionProgress
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger

logger = get_logger(__name__)


def render_pipeline_tab(
    source_mode: ui.select,
    url_input: ui.input,
    rss_dropdown: ui.select
) -> None:
    """
    Pipeline 탭 렌더링.

    Args:
        source_mode: 소스 모드 선택 UI
        url_input: URL 입력 UI
        rss_dropdown: RSS 드롭다운 UI
    """

    # --- UI Elements (will be populated) ---
    progress_bars = {}
    phase_labels = {}
    phase_time_labels = {}

    # --- Helper Functions ---
    def format_time(seconds: float) -> str:
        """시간 포맷팅"""
        if seconds < 0:
            return "--:--"
        mins, secs = divmod(int(seconds), 60)
        return f"{mins}:{secs:02d}"

    def update_scene_grid(scenes: list) -> None:
        """씬 그리드 업데이트"""
        # Implementation details...
        pass

    # --- Main Pipeline Execution ---
    async def run_full_pipeline():
        """전체 파이프라인 실행"""
        if state.pipeline_running:
            safe_notify('Pipeline is already running!', type='warning')
            return

        # Validation
        if source_mode.value == 'Direct URL' and not url_input.value:
            safe_notify('Please enter a URL', type='negative')
            return

        # Initialize state
        state.pipeline_running = True
        state.pipeline_phase = ProductionPhase.IDLE
        state.last_error = None
        start_btn.disable()
        stop_btn.enable()

        # Reset UI
        for bar in progress_bars.values():
            bar.set_value(0)
        for label in phase_labels.values():
            label.text = 'Pending'
            label.classes(remove='text-teal-400 text-pink-400 text-red-400', add='text-gray-400')

        hide_error_panel(error_panel)

        try:
            # Update API keys
            if state.openai_key or state.gcp_project:
                settings.update_api_keys(
                    openai_key=state.openai_key,
                    gcp_project=state.gcp_project
                )

            # Create service and run
            service = ProductionService(
                mode=state.mode,
                parallel_clips=parallel_clips.value
            )
            state.production_service = service

            # Progress callback
            def on_progress(progress: ProductionProgress):
                state.pipeline_phase = progress.phase
                state.pipeline_progress = progress.progress_percent
                # ... update other state

            # Get source URL
            source_url = (
                url_input.value
                if source_mode.value == 'Direct URL'
                else rss_dropdown.value
            )

            # Execute
            result = await service.run(
                source=source_url,
                on_progress=on_progress,
                auto_upload=auto_upload.value
            )

            # Handle result
            if result.success:
                safe_notify('🎉 Pipeline completed!', type='positive')
                state.add_to_history(result.script.title, True)
            else:
                show_error_panel(error_panel, error_message_label, error_details_label, result.error)
                state.add_to_history('Failed', False)

        except Exception as e:
            state.last_error = str(e)
            show_error_panel(error_panel, error_message_label, error_details_label, str(e))
            safe_notify(f'❌ Error: {e}', type='negative')
            logger.error(f"Pipeline error: {e}")

        finally:
            state.pipeline_running = False
            start_btn.enable()
            stop_btn.disable()

    async def stop_pipeline():
        """파이프라인 중지"""
        if state.production_service:
            state.production_service.cancel()
        state.pipeline_running = False
        state.pipeline_phase = ProductionPhase.FAILED
        safe_notify('⏹️ Pipeline stopped', type='warning')
        logger.warning("Pipeline stopped by user")

    # --- UI Rendering ---
    with ui.column().classes('w-full gap-4'):
        # Control Card
        with card_with_header('Pipeline Control', 'rocket_launch', 'primary'):
            with ui.element('div').classes('p-4'):
                # Options
                with ui.row().classes('w-full gap-4 mb-3'):
                    auto_upload = ui.switch('YouTube Upload').props('color=red dense')
                    parallel_clips = ui.switch('Parallel Gen').props('color=teal dense')

                ui.separator().classes('bg-slate-600 my-3')

                # Buttons
                with ui.row().classes('w-full gap-2'):
                    start_btn = ui.button(
                        'Start Pipeline',
                        on_click=run_full_pipeline
                    ).classes('flex-grow').props('color=teal unelevated icon=play_arrow size=lg')

                    stop_btn = ui.button(
                        icon='stop',
                        on_click=stop_pipeline
                    ).props('color=red unelevated size=lg')
                    stop_btn.disable()

        # Progress Card
        with card_with_header('Progress', 'trending_up', 'secondary'):
            with ui.element('div').classes('p-4'):
                indicators = create_step_indicators()
                progress_bars = indicators['progress_bars']
                phase_labels = indicators['phase_labels']
                phase_time_labels = indicators['phase_time_labels']

        # Error Panel
        error_panel, error_message_label, error_details_label = create_error_panel()

        # Scene Grid
        with card_with_header('Scenes', 'grid_view', 'info'):
            scene_grid = ui.element('div').classes('p-4 grid grid-cols-2 gap-3')
```

---

### 3.5 Phase 5: 메인 진입점 정리

#### 3.5.1 `gui/pages/main_page.py`

```python
"""메인 페이지 레이아웃"""

from nicegui import ui
from typing import Optional

from gui.state.app_state import state
from gui.components.pipeline_tab import render_pipeline_tab
from gui.components.sources_tab import render_sources_tab
from gui.components.planning_tab import render_planning_tab
from gui.components.generation_tab import render_generation_tab
from gui.components.publishing_tab import render_publishing_tab
from gui.components.scheduling_tab import render_scheduling_tab
from gui.config.constants import SIDEBAR_HEIGHT


def render_main_page() -> None:
    """메인 페이지 렌더링"""

    # Shared UI elements (passed to tabs)
    source_mode = None
    url_input = None
    rss_dropdown = None

    with ui.row().classes('w-full h-screen'):
        # === Sidebar ===
        with ui.column().classes(f'w-80 {SIDEBAR_HEIGHT} bg-slate-900 p-4 overflow-y-auto'):
            # Logo
            with ui.row().classes('items-center gap-2 mb-6'):
                ui.icon('movie', size='lg').classes('text-teal-400')
                ui.label('ShortsMaker').classes('text-xl font-bold text-white')

            # Source Selection
            with ui.card().classes('w-full p-4 bg-slate-800'):
                source_mode = ui.select(
                    ['RSS Feed', 'Direct URL'],
                    value='RSS Feed'
                ).classes('w-full')

                url_input = ui.input('Enter URL').classes('w-full')
                url_input.visible = False

                rss_dropdown = ui.select([]).classes('w-full')

                # Toggle visibility
                def on_source_change():
                    url_input.visible = source_mode.value == 'Direct URL'
                    rss_dropdown.visible = source_mode.value == 'RSS Feed'

                source_mode.on('update:model-value', on_source_change)

            # Mode Selection
            with ui.card().classes('w-full p-4 bg-slate-800 mt-4'):
                ui.label('Generation Mode').classes('text-sm text-gray-400 mb-2')
                mode_toggle = ui.toggle(
                    ['Video', 'Image'],
                    value='Video'
                ).classes('w-full')

                def on_mode_change():
                    state.mode = 'video' if mode_toggle.value == 'Video' else 'image'

                mode_toggle.on('update:model-value', on_mode_change)

        # === Main Content ===
        with ui.column().classes('flex-grow h-screen overflow-hidden bg-slate-950'):
            with ui.tabs().classes('w-full bg-slate-900') as tabs:
                pipeline_tab = ui.tab('Pipeline', icon='rocket_launch')
                sources_tab = ui.tab('Sources', icon='rss_feed')
                planning_tab = ui.tab('Planning', icon='edit_note')
                generation_tab = ui.tab('Generation', icon='movie')
                publishing_tab = ui.tab('Publishing', icon='upload')
                scheduling_tab = ui.tab('Schedule', icon='schedule')

            with ui.tab_panels(tabs, value=pipeline_tab).classes('w-full flex-grow overflow-y-auto p-6'):
                with ui.tab_panel(pipeline_tab):
                    render_pipeline_tab(source_mode, url_input, rss_dropdown)

                with ui.tab_panel(sources_tab):
                    render_sources_tab()

                with ui.tab_panel(planning_tab):
                    render_planning_tab()

                with ui.tab_panel(generation_tab):
                    render_generation_tab()

                with ui.tab_panel(publishing_tab):
                    render_publishing_tab()

                with ui.tab_panel(scheduling_tab):
                    render_scheduling_tab()
```

#### 3.5.2 `gui.py` (Entry Point)

```python
#!/usr/bin/env python3
"""ShortsMaker Studio - Entry Point"""

from nicegui import ui, app
from gui.pages.main_page import render_main_page
from gui.state.app_state import state
from shorts_maker.utils.logger import get_logger

logger = get_logger(__name__)


@ui.page('/')
def index():
    """메인 페이지"""
    ui.dark_mode().enable()
    render_main_page()


def main():
    """애플리케이션 시작"""
    logger.info("Starting ShortsMaker Studio...")

    ui.run(
        title='ShortsMaker Studio',
        host='127.0.0.1',
        port=8080,
        reload=False,
        show=True,
        storage_secret='shorts_maker_secret_key'
    )


if __name__ == '__main__':
    main()
```

---

## 4. Implementation Order

### 4.1 구현 순서 체크리스트

| # | Phase | Task | Dependencies | Status |
|---|-------|------|--------------|:------:|
| 1.1 | Phase 1 | `gui/config/__init__.py` 생성 | - | ⬜ |
| 1.2 | Phase 1 | `gui/config/constants.py` 생성 | 1.1 | ⬜ |
| 1.3 | Phase 1 | `gui/config/ui_theme.py` 생성 | 1.1 | ⬜ |
| 1.4 | Phase 1 | `gui/components/common/__init__.py` 생성 | - | ⬜ |
| 1.5 | Phase 1 | `gui/components/common/safe_ui.py` 생성 | 1.4 | ⬜ |
| 2.1 | Phase 2 | `gui/state/__init__.py` 생성 | - | ⬜ |
| 2.2 | Phase 2 | `gui/state/app_state.py` 생성 | 2.1 | ⬜ |
| 2.3 | Phase 2 | `gui/state/session_manager.py` 생성 | 2.1 | ⬜ |
| 3.1 | Phase 3 | `gui/components/common/card_header.py` 생성 | 1.3 | ⬜ |
| 3.2 | Phase 3 | `gui/components/common/step_indicator.py` 생성 | 1.2, 1.3 | ⬜ |
| 3.3 | Phase 3 | `gui/components/common/error_panel.py` 생성 | 1.5 | ⬜ |
| 4.1 | Phase 4 | `gui/components/__init__.py` 생성 | - | ⬜ |
| 4.2 | Phase 4 | `gui/components/pipeline_tab.py` 생성 | 1-3 | ⬜ |
| 4.3 | Phase 4 | `gui/components/sources_tab.py` 생성 | 1-3 | ⬜ |
| 4.4 | Phase 4 | `gui/components/planning_tab.py` 생성 | 1-3 | ⬜ |
| 4.5 | Phase 4 | `gui/components/generation_tab.py` 생성 | 1-3 | ⬜ |
| 4.6 | Phase 4 | `gui/components/publishing_tab.py` 생성 | 1-3 | ⬜ |
| 4.7 | Phase 4 | `gui/components/scheduling_tab.py` 생성 | 1-3 | ⬜ |
| 5.1 | Phase 5 | `gui/pages/__init__.py` 생성 | - | ⬜ |
| 5.2 | Phase 5 | `gui/pages/main_page.py` 생성 | 4.* | ⬜ |
| 5.3 | Phase 5 | `gui/__init__.py` 생성 | - | ⬜ |
| 5.4 | Phase 5 | `gui.py` 최소화 | 5.2 | ⬜ |
| 5.5 | Phase 5 | 기존 gui.py 코드 제거 | 5.4 | ⬜ |

---

## 5. Test Plan

### 5.1 각 Phase별 테스트

| Phase | Test Method | Pass Criteria |
|-------|-------------|---------------|
| Phase 1 | Import 테스트 | 에러 없이 임포트 |
| Phase 2 | State 초기화 테스트 | AppState 인스턴스 생성 |
| Phase 3 | 컴포넌트 렌더링 테스트 | UI 요소 정상 생성 |
| Phase 4 | 탭 렌더링 테스트 | 각 탭 정상 표시 |
| Phase 5 | 전체 통합 테스트 | GUI 정상 동작 |

### 5.2 회귀 테스트

- [ ] 파이프라인 시작/중지
- [ ] 소스 선택 (RSS/URL)
- [ ] 스크립트 생성
- [ ] 비디오 생성
- [ ] YouTube 업로드
- [ ] 스케줄 관리

---

## 6. Rollback Plan

| Phase | Rollback Strategy |
|-------|-------------------|
| Phase 1-3 | 새 파일 삭제, gui.py 원본 유지 |
| Phase 4 | 탭 임포트 제거, 인라인 코드 복원 |
| Phase 5 | gui.py 원본으로 복원 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-03 | Initial draft | Claude |
