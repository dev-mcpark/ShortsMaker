# Critical Issue Fix Design Document

> **Summary**: 6개 Critical 보안/품질 이슈에 대한 상세 설계 및 구현 명세
>
> **Project**: ShortsMaker Studio
> **Version**: 0.1.0
> **Author**: Claude
> **Date**: 2026-02-02
> **Status**: Draft
> **Planning Doc**: [critical-issue-fix.plan.md](../01-plan/features/critical-issue-fix.plan.md)

### Pipeline References

| Phase | Document | Status |
|-------|----------|--------|
| Phase 1 | Schema Definition | N/A |
| Phase 2 | Coding Conventions | N/A |

---

## 1. Overview

### 1.1 Design Goals

- 환경변수 직접 수정 제거로 보안 강화
- 암호학적으로 안전한 해시 함수 사용
- API 키 검증을 통한 런타임 안정성 확보
- 명확한 예외 처리로 디버깅 용이성 향상

### 1.2 Design Principles

- **Single Source of Truth**: 모든 설정은 `settings` 객체를 통해 접근
- **Fail-Fast**: API 키 누락 시 즉시 명확한 에러 발생
- **Explicit over Implicit**: 예외 처리 시 구체적인 타입 명시

---

## 2. Architecture

### 2.1 현재 구조 (Before)

```
┌─────────────┐     ┌─────────────────┐
│   gui.py    │────▶│  os.environ     │  (직접 수정 - 위험)
└─────────────┘     └────────┬────────┘
                             │
┌─────────────┐              │
│script_planner│─────────────┤  os.getenv() (직접 호출)
├─────────────┤              │
│script_validator│───────────┤
├─────────────┤              │
│video_editor │──────────────┘
└─────────────┘
```

### 2.2 개선 구조 (After)

```
┌─────────────┐     ┌─────────────────┐
│   gui.py    │────▶│ settings 갱신   │  (안전한 방식)
└─────────────┘     └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  config.py      │
                    │  (Settings)     │
                    └────────┬────────┘
                             │
┌─────────────┐              │
│script_planner│─────────────┤
├─────────────┤              │  settings.openai_api_key
│script_validator│───────────┤  (중앙 집중식)
├─────────────┤              │
│video_editor │──────────────┘
└─────────────┘
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| `script_planner.py` | `config.py` | API 키 및 설정 접근 |
| `script_validator.py` | `config.py` | API 키 접근 |
| `video_editor.py` | `config.py` | API 키 접근 |
| `gui.py` | `config.py` | 설정 업데이트 |

---

## 3. Detailed Design

### 3.1 Issue #1: 환경변수 직접 오버라이드 (`gui.py:386-389`)

#### 현재 코드

```python
# gui.py:386-389
if state.openai_key:
    os.environ["OPENAI_API_KEY"] = state.openai_key
if state.gcp_project:
    os.environ["GCP_PROJECT_ID"] = state.gcp_project
```

#### 문제점

- 환경변수 직접 수정은 전역 상태를 변경하여 예측 불가능한 부작용 발생
- 다른 스레드/프로세스에 영향을 줄 수 있음
- 테스트 시 상태 격리 어려움

#### 해결 방안

`Settings` 클래스에 동적 업데이트 메서드 추가 후 사용

```python
# config.py - Settings 클래스에 추가
def update_api_keys(self, openai_key: Optional[str] = None,
                    gcp_project: Optional[str] = None):
    """GUI에서 입력된 API 키로 설정 업데이트 (환경변수 직접 수정 대신)"""
    if openai_key:
        self.openai_api_key = openai_key
    if gcp_project:
        self.gcp_project_id = gcp_project
```

```python
# gui.py - 변경 후
from shorts_maker.utils.config import settings

# 기존 os.environ 직접 수정 대신:
if state.openai_key:
    settings.update_api_keys(openai_key=state.openai_key)
if state.gcp_project:
    settings.update_api_keys(gcp_project=state.gcp_project)
```

---

### 3.2 Issue #2: MD5 해시 사용 (`script_planner.py:29-30`)

#### 현재 코드

```python
# script_planner.py:29-30
def _get_key(self, url: str) -> str:
    """URL을 해시 키로 변환"""
    return hashlib.md5(url.encode()).hexdigest()
```

#### 문제점

- MD5는 암호학적으로 안전하지 않음 (충돌 공격 가능)
- 보안 감사 시 경고 대상

#### 해결 방안

SHA256 해시 함수로 교체

```python
# script_planner.py - 변경 후
def _get_key(self, url: str) -> str:
    """URL을 해시 키로 변환"""
    return hashlib.sha256(url.encode()).hexdigest()
```

**영향 분석**: 캐시 키 용도로만 사용되므로 해시 길이 변경(32→64자)은 기능에 영향 없음.

---

### 3.3 Issue #3: API 키 None 체크 (`script_planner.py:86`)

#### 현재 코드

```python
# script_planner.py:86
self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
```

#### 문제점

- `OPENAI_API_KEY` 미설정 시 `None` 전달되어 런타임 에러 발생
- 에러 메시지가 불명확함

#### 해결 방안

```python
# script_planner.py - 변경 후
from shorts_maker.utils.config import settings

class ScriptPlanner:
    def __init__(self, generation_mode: str = "image"):
        self.logger = get_logger(__name__)

        # API 키 검증
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured. "
                "Please set it in .env file or config/.env"
            )

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        # ... 나머지 코드
```

---

### 3.4 Issue #4: API 키 None 체크 (`script_validator.py:18`)

#### 현재 코드

```python
# script_validator.py:17-18
def __init__(self):
    self.logger = get_logger(__name__)
    self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
```

#### 해결 방안

```python
# script_validator.py - 변경 후
from shorts_maker.utils.config import settings

class ScriptValidator:
    def __init__(self):
        self.logger = get_logger(__name__)

        # API 키 검증
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured. "
                "Please set it in .env file or config/.env"
            )

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
```

---

### 3.5 Issue #5: API 키 None 체크 (`video_editor.py:40`)

#### 현재 코드

```python
# video_editor.py:40
self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
```

#### 해결 방안

```python
# video_editor.py - 변경 후
from shorts_maker.utils.config import settings

class VideoEditor:
    def __init__(self, ...):
        self.logger = get_logger(__name__)
        self.bgm_manager = BGMManager()

        # API 키 검증
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured. "
                "Please set it in .env file or config/.env"
            )

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        # ... 나머지 코드
```

---

### 3.6 Issue #6: bare except 제거 (`gui.py:476-498`)

#### 현재 코드

```python
# gui.py:474-497
try:
    ui.notify('🎉 Pipeline completed successfully!', type='positive')
except:
    pass

# ... 여러 곳에서 동일 패턴 반복
try:
    video_preview.set_source(result.video_path)
    video_preview.visible = True
    preview_placeholder.visible = False
except:
    pass
```

#### 문제점

- 모든 예외를 무시하여 디버깅 어려움
- 예상치 못한 에러도 숨겨짐
- PEP 8 및 보안 가이드라인 위반

#### 해결 방안

```python
# gui.py - 변경 후
from shorts_maker.utils.logger import get_logger

logger = get_logger(__name__)

# UI 알림 예외 처리
try:
    ui.notify('🎉 Pipeline completed successfully!', type='positive')
except RuntimeError as e:
    # NiceGUI 컨텍스트 외부에서 호출 시 발생
    logger.debug(f"UI notify skipped (no context): {e}")

# 비디오 프리뷰 예외 처리
try:
    video_preview.set_source(result.video_path)
    video_preview.visible = True
    preview_placeholder.visible = False
except (FileNotFoundError, ValueError) as e:
    logger.warning(f"Failed to set video preview: {e}")
except RuntimeError as e:
    logger.debug(f"UI update skipped (no context): {e}")
```

---

## 4. Data Model

### 4.1 Settings 클래스 확장

```python
@dataclass
class Settings:
    # 기존 필드...

    # 새로운 메서드 추가
    def update_api_keys(
        self,
        openai_key: Optional[str] = None,
        gcp_project: Optional[str] = None
    ) -> None:
        """GUI에서 입력된 API 키로 동적 업데이트"""
        if openai_key:
            self.openai_api_key = openai_key
        if gcp_project:
            self.gcp_project_id = gcp_project
```

---

## 5. Error Handling

### 5.1 API 키 검증 에러

| Situation | Exception | Message |
|-----------|-----------|---------|
| OpenAI API 키 미설정 | `ValueError` | "OPENAI_API_KEY is not configured..." |
| GCP 프로젝트 ID 미설정 | `ValueError` | "GCP_PROJECT_ID is not configured..." |

### 5.2 UI 예외 처리 매핑

| Exception | Cause | Action |
|-----------|-------|--------|
| `RuntimeError` | NiceGUI 컨텍스트 외부 호출 | Debug 로그 후 무시 |
| `FileNotFoundError` | 비디오 파일 없음 | Warning 로그 |
| `ValueError` | 잘못된 파일 경로 | Warning 로그 |

---

## 6. Security Considerations

- [x] 환경변수 직접 수정 제거
- [x] MD5 → SHA256 교체
- [x] API 키 검증 추가
- [x] 예외 처리 명확화
- [x] 민감 정보 로깅 방지

---

## 7. Test Plan

### 7.1 Test Scope

| Type | Target | Method |
|------|--------|--------|
| Unit Test | API 키 검증 로직 | 수동 테스트 |
| Integration Test | 전체 파이프라인 | GUI 실행 테스트 |
| Regression Test | 기존 기능 | 비디오 생성 테스트 |

### 7.2 Test Cases

- [x] API 키 미설정 시 명확한 에러 메시지 출력
- [x] 정상적인 API 키 설정 시 기능 동작
- [x] 캐시 키 생성 정상 동작 (SHA256)
- [x] UI 예외 발생 시 로그 기록

---

## 8. Implementation Guide

### 8.1 파일 수정 목록

| File | Line | Change Type |
|------|------|-------------|
| `utils/config.py` | 109+ | 메서드 추가 |
| `gui.py` | 386-389 | 수정 |
| `gui.py` | 476-498 | 수정 |
| `planner/script_planner.py` | 29-30 | 수정 |
| `planner/script_planner.py` | 86 | 수정 |
| `planner/script_validator.py` | 1, 18 | 수정 |
| `editor/video_editor.py` | 1, 40 | 수정 |

### 8.2 Implementation Order

1. [x] `config.py` - `update_api_keys()` 메서드 추가
2. [x] `script_planner.py` - MD5 → SHA256 변경
3. [x] `script_planner.py` - settings 임포트 및 API 키 검증
4. [x] `script_validator.py` - settings 임포트 및 API 키 검증
5. [x] `video_editor.py` - settings 임포트 및 API 키 검증
6. [x] `gui.py` - 환경변수 직접 수정 제거
7. [x] `gui.py` - bare except 제거

### 8.3 Rollback Plan

문제 발생 시 각 파일의 변경 사항을 개별적으로 되돌릴 수 있음.
Git을 통한 버전 관리 활용.

---

## 9. Clean Architecture

### 9.1 Layer Structure

| Layer | Location | Affected Files |
|-------|----------|----------------|
| **Presentation** | `gui.py` | Issue #1, #6 |
| **Application** | `services/` | - |
| **Domain** | `planner/` | Issue #2, #3, #4 |
| **Infrastructure** | `editor/`, `utils/` | Issue #5 |

### 9.2 This Feature's Layer Assignment

| Component | Layer | Location |
|-----------|-------|----------|
| Settings.update_api_keys | Infrastructure | `utils/config.py` |
| API 키 검증 로직 | Domain | 각 클래스 `__init__` |
| 예외 처리 | Presentation | `gui.py` |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-02 | Initial draft | Claude |
