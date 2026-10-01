# Script Feedback Loop Design Document

> **Summary**: 스크립트 피드백 루프 및 Veo 프롬프트 검토 단계 상세 설계
>
> **Project**: ShortsMaker Studio
> **Version**: 0.3.0
> **Author**: Claude
> **Date**: 2026-03-22
> **Status**: Draft

---

## 1. Architecture Overview

```
GUI Layer
  planning_tab.py        ← 피드백 패널 + 주제 후보 패널 추가
  generation_tab.py      ← 프롬프트 검토 패널 추가

Service Layer
  production_service.py  ← regenerate_script(), prepare_generation() 추가

Domain Layer
  script_planner.py      ← _score_topics() 리팩토링, 파일 경로 수정
  planner/models.py      ← TopicCandidate 모델 추가
  video_generator.py     ← generate_scene_clip() public API 추가
```

---

## 2. Data Models

### 2.1 `TopicCandidate` (신규 - `planner/models.py`)

```python
@dataclass
class TopicCandidate:
    """주제 후보 항목 - 선택 점수와 이유 포함"""
    item: Dict[str, Any]     # 원본 RSS 후보 데이터
    score: int               # 1-10점 (GPT-4o 평가)
    reason: str              # 선택/미선택 이유 (한국어 1-2문장)
    selected: bool = False   # 최종 선택 여부
```

### 2.2 `ScriptGenerationContext` (신규 - `planner/models.py`)

```python
@dataclass
class ScriptGenerationContext:
    """스크립트 생성 컨텍스트 - 재생성 시 재사용"""
    source_item: Dict[str, Any]   # 선택된 RSS 후보 (enriched 포함)
    candidates: List[TopicCandidate]  # 전체 후보 목록
    attempt_count: int = 0            # 재생성 횟수
    max_attempts: int = 3             # 최대 재생성 횟수
```

---

## 3. Service Layer Changes

### 3.1 `ProductionService` 변경 (`services/production_service.py`)

#### 추가: `regenerate_script()`

```python
async def regenerate_script(
    self,
    context: ScriptGenerationContext,
    feedback: str
) -> Optional[ShortsScript]:
    """
    피드백을 반영하여 동일 주제로 스크립트 재생성.

    Args:
        context: 이전 생성 컨텍스트 (소스 데이터 재사용)
        feedback: 사용자 피드백 텍스트
    Returns:
        재생성된 ShortsScript 또는 실패 시 None
    """
```

#### 추가: `prepare_generation()`

```python
async def prepare_generation(
    self,
    script: ShortsScript
) -> ShortsScript:
    """
    스크립트의 씬 프롬프트를 준비하되 실제 영상 생성은 하지 않음.
    (현재는 script 그대로 반환. 향후 프롬프트 최적화 레이어 추가 가능)

    Returns:
        프롬프트가 준비된 ShortsScript (편집 가능 상태로 UI에 전달)
    """
```

#### 변경: `generate_script()` 반환 타입 확장

```python
# 기존
async def generate_script(...) -> Optional[ShortsScript]

# 변경 후
async def generate_script(...) -> Tuple[Optional[ShortsScript], Optional[ScriptGenerationContext]]
```

### 3.2 `ScriptPlanner` 변경 (`planner/script_planner.py`)

#### 변경: `_select_best_topic()` → `_score_topics()`

```python
# 기존 - 인덱스 하나만 반환
async def _select_best_topic(candidates: List[Dict]) -> Dict

# 변경 후 - 전체 후보 점수 + 선택된 항목 반환
async def _score_topics(
    candidates: List[Dict]
) -> List[TopicCandidate]:
    """
    각 후보에 점수(1-10)와 선택 이유를 부여.
    GPT-4o 프롬프트 수정: 번호 대신 JSON 배열로 응답.
    """
```

#### 변경: 파일 경로 `settings` 상수 사용

```python
# 기존 (상대 경로 하드코딩)
self.history_file = "topic_history.json"
self.url_history_file = "url_history.json"
self.script_output_dir = "outputs/scripts"

# 변경 후
self.history_file = str(settings.topic_history_file)
self.url_history_file = str(settings.url_history_file)
self.script_output_dir = str(settings.scripts_dir)
```

### 3.3 `VideoGenerator` 변경 (`generator/video_generator.py`)

#### 추가: `generate_scene_clip()` public 메서드

```python
async def generate_scene_clip(self, scene: VideoScene) -> str:
    """
    단일 씬에 대한 클립 생성 (public API).
    내부적으로 mode에 따라 Veo 또는 Imagen 호출.

    Returns:
        생성된 클립 파일 경로
    """
    if self.mode == "video":
        bg_path = await self._generate_background_video(scene)
        if self.character_overlay:
            return await self._composite_character_on_video(bg_path, scene)
        return bg_path
    else:
        clip_path = await self._generate_image_imagen(scene)
        if self.character_overlay:
            return self.character_overlay.composite_on_image(
                clip_path, clip_path.replace(".png", "_final.png")
            )
        return clip_path
```

#### `ProductionService.produce_video()` 수정

```python
# 기존 (캡슐화 위반)
bg_video_path = await generator._generate_background_video(scene)
clip_path = await generator._composite_character_on_video(bg_video_path, scene)

# 변경 후 (public API 사용)
clip_path = await generator.generate_scene_clip(scene)
```

---

## 4. GUI Layer Changes

### 4.1 Planning Tab UI (`gui/components/planning_tab.py`)

#### 레이아웃 변경

```
[현재 레이아웃]
┌──────────────────┬──────────────────────────────┐
│  Left Panel      │  Right Panel                 │
│  - 소스 선택      │  - 각본 미리보기              │
│  - 저장된 각본    │                              │
│  - JSON 편집기    │                              │
│  - 확인 완료 버튼 │                              │
└──────────────────┴──────────────────────────────┘

[변경 후 레이아웃]
┌──────────────────┬──────────────────────────────┐
│  Left Panel      │  Right Panel                 │
│  - 소스 선택      │  [주제 후보 패널] (접힘 가능) │
│  - 피드백 입력창  │  ├ 후보1: 점수/이유           │
│    (스크립트 생성 │  ├ 후보2: 점수/이유           │
│     후 표시)      │  └ 선택됨 표시               │
│  - 재생성 버튼    │                              │
│    (재생성 횟수   │  [각본 미리보기]              │
│     카운터 포함)  │                              │
│  - 저장된 각본    │                              │
│  - JSON 편집기    │                              │
│  - 확인 완료 버튼 │                              │
└──────────────────┴──────────────────────────────┘
```

#### 신규 UI 컴포넌트

**피드백 섹션** (스크립트 생성 완료 후 표시):
```python
# 피드백 입력 영역 - 초기엔 숨김, 스크립트 생성 후 표시
feedback_section = ui.element('div').classes('w-full ...')
feedback_section.visible = False

feedback_input = ui.textarea(
    '피드백',
    placeholder='예: 후크가 약해요. 더 충격적인 사실로 시작해주세요.'
).props('outlined dark rows=3').classes('w-full')

regen_counter_label = ui.label('재생성: 0/3회').classes('text-xs text-gray-500')

async def regenerate_with_feedback():
    # state.script_context (ScriptGenerationContext) 재사용
    # production_service.regenerate_script(context, feedback_input.value) 호출
    ...

ui.button('피드백 반영 재생성', on_click=regenerate_with_feedback)
    .props('color=orange icon=refresh')
```

**주제 후보 패널**:
```python
# ui.expansion으로 접힘 처리
with ui.expansion('주제 후보 목록', icon='format_list_bulleted'):
    candidates_container = ui.column().classes('w-full gap-2')
    # TopicCandidate 목록을 카드 형태로 렌더링
    # 선택된 항목은 하이라이트
```

#### `AppState` 필드 추가

```python
# app_state.py에 추가
script_context: Optional[Any] = None  # ScriptGenerationContext
script_regen_count: int = 0           # 재생성 횟수
topic_candidates: List[Any] = field(default_factory=list)  # TopicCandidate 목록
```

### 4.2 Generation Tab UI (`gui/components/generation_tab.py`)

#### 프롬프트 검토 패널 추가

```
[변경 후 흐름]
각본 로드
    ↓
[프롬프트 검토 패널] ← 신규
  ├ 씬 1: visual_description 편집 가능 텍스트
  ├ 씬 2: visual_description 편집 가능 텍스트
  └ "이 프롬프트로 생성 시작" 버튼
    ↓
[기존 생성 진행 UI]
```

#### 씬 프롬프트 편집 카드

```python
with ui.expansion(f'씬 {scene.scene_number} 프롬프트 검토', icon='edit'):
    visual_input = ui.textarea(
        '비주얼 설명',
        value=scene.visual_description
    ).props('outlined dark rows=3').classes('w-full mb-2')

    if scene.motion_instruction:
        motion_input = ui.textarea(
            '모션 지시',
            value=scene.motion_instruction
        ).props('outlined dark rows=2').classes('w-full')

    # 편집 결과를 scene에 반영하는 콜백
```

---

## 5. State Flow

### Phase A: 스크립트 생성 → 피드백 → 재생성

```
사용자: "각본 생성하기" 클릭
    ↓
generate_script(topic, url)
    → ScriptPlanner._score_topics() → List[TopicCandidate]
    → 최고 점수 후보 선택 → _write_script()
    → (ShortsScript, ScriptGenerationContext) 반환
    ↓
state.script = script
state.script_context = context
state.topic_candidates = candidates
    ↓
UI: 주제 후보 패널 렌더링
UI: 피드백 섹션 표시
    ↓
사용자: 피드백 입력 → "재생성" 클릭
    ↓
regenerate_script(context, feedback)
    → context.source_item 재사용 (RSS 재호출 없음)
    → _write_script(item, feedback=feedback)
    → 새 ShortsScript 반환
    ↓
state.script = new_script
state.script_regen_count += 1
UI: 미리보기 갱신
```

### Phase B: 프롬프트 검토 → 생성

```
사용자: Generation Tab → 각본 로드
    ↓
prepare_generation(script) → 프롬프트 준비된 script 반환
    ↓
UI: 씬별 프롬프트 편집 패널 렌더링
    ↓
사용자: 프롬프트 편집 (선택)
    ↓
"이 프롬프트로 생성 시작" 클릭
    → state.script.scenes 업데이트 (편집 내용 반영)
    ↓
produce_video(script) → generator.generate_scene_clip(scene) 호출
```

---

## 6. File Change Summary

| 파일 | 변경 유형 | 주요 내용 |
|------|----------|----------|
| `planner/models.py` | 추가 | `TopicCandidate`, `ScriptGenerationContext` dataclass |
| `planner/script_planner.py` | 수정 | `_score_topics()` 리팩토링, 파일 경로 settings 사용 |
| `generator/video_generator.py` | 추가 | `generate_scene_clip()` public 메서드 |
| `services/production_service.py` | 추가/수정 | `regenerate_script()`, `prepare_generation()`, `produce_video()` 수정 |
| `gui/state/app_state.py` | 추가 | `script_context`, `script_regen_count`, `topic_candidates` 필드 |
| `gui/components/planning_tab.py` | 수정 | 피드백 섹션, 주제 후보 패널 |
| `gui/components/generation_tab.py` | 수정 | 프롬프트 검토 패널 |

---

## 7. Implementation Order

```
Step 1: models.py — TopicCandidate, ScriptGenerationContext 추가
Step 2: script_planner.py — _score_topics() 리팩토링, 경로 수정
Step 3: video_generator.py — generate_scene_clip() 추가
Step 4: production_service.py — regenerate_script(), prepare_generation(), produce_video() 수정
Step 5: app_state.py — 신규 필드 추가
Step 6: planning_tab.py — Phase A UI
Step 7: generation_tab.py — Phase B UI
Step 8: 구문 검증 및 흐름 확인
```

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-22 | Initial design | Claude |
