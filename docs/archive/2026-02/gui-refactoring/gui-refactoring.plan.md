# GUI Refactoring Planning Document

> **Summary**: gui.py 모놀리식 코드를 모듈화하여 유지보수성과 테스트 용이성 향상
>
> **Project**: ShortsMaker Studio
> **Version**: 0.1.0
> **Author**: Claude
> **Date**: 2026-02-03
> **Status**: Draft

---

## 1. Overview

### 1.1 Purpose

2,134줄의 모놀리식 gui.py를 Clean Architecture 원칙에 따라 모듈화하여:
- 코드 가독성 향상
- 단위 테스트 가능성 확보
- 유지보수 용이성 개선
- 코드 재사용성 증가

### 1.2 Background

**현재 문제점 (코드 분석 결과: 45/100점)**:
- 파일 크기: 2,134줄 (권장 300줄의 7배)
- 8개의 책임이 단일 파일에 혼재 (SRP 위반)
- 50+ 중복 코드 패턴
- 300줄 이상의 거대 함수 5개
- 10+ 매직 넘버/스트링

### 1.3 Related Documents

- Code Analysis Report: 2026-02-03 분석 결과
- CLAUDE.md: 프로젝트 가이드라인
- critical-issue-fix PDCA: 이전 보안 이슈 수정

---

## 2. Scope

### 2.1 In Scope

- [ ] **Phase 1**: 공통 유틸리티 추출
  - [ ] `components/common/safe_ui.py` 생성 (50+ 중복 제거)
  - [ ] `config/constants.py` 생성 (매직 넘버 제거)
  - [ ] `config/ui_theme.py` 생성 (CSS 클래스 중앙화)

- [ ] **Phase 2**: 상태 관리 분리
  - [ ] `state/app_state.py` 분리
  - [ ] `state/session_manager.py` 분리

- [ ] **Phase 3**: 공통 컴포넌트 추출
  - [ ] `components/common/card_header.py` 생성
  - [ ] `components/common/step_indicator.py` 생성
  - [ ] `components/common/error_panel.py` 생성

- [ ] **Phase 4**: 탭 컴포넌트 분리
  - [ ] `components/pipeline_tab.py` 분리 (~480줄 → ~150줄)
  - [ ] `components/sources_tab.py` 분리
  - [ ] `components/planning_tab.py` 분리
  - [ ] `components/generation_tab.py` 분리
  - [ ] `components/publishing_tab.py` 분리
  - [ ] `components/scheduling_tab.py` 분리

- [ ] **Phase 5**: 메인 진입점 정리
  - [ ] `gui.py` 최소화 (~50줄)
  - [ ] `pages/main_page.py` 생성

### 2.2 Out of Scope

- 기능 변경 또는 추가
- UI 디자인 변경
- 백엔드 로직 수정
- 테스트 코드 작성 (별도 PDCA로 진행)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 리팩토링 후 기존 기능 100% 동작 | Critical | Pending |
| FR-02 | 각 탭 컴포넌트 독립 동작 | High | Pending |
| FR-03 | 상태 공유 정상 유지 | High | Pending |
| FR-04 | 에러 처리 동일하게 동작 | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Maintainability | 모든 모듈 300줄 이하 | 라인 수 측정 |
| Readability | 함수당 50줄 이하 | 코드 리뷰 |
| Reusability | 중복 코드 90% 제거 | 중복 패턴 검색 |
| Testability | 단위 테스트 가능한 구조 | 모듈 독립성 확인 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 모든 모듈 300줄 이하
- [ ] gui.py 50줄 이하
- [ ] 중복 코드 패턴 90% 이상 제거
- [ ] 기존 기능 정상 동작 확인
- [ ] 린트 에러 없음
- [ ] 구문 에러 없음

### 4.2 Quality Criteria

| Metric | Before | Target |
|--------|:------:|:------:|
| gui.py 라인 수 | 2,134 | ≤50 |
| 최대 모듈 크기 | 2,134줄 | ≤300줄 |
| 중복 코드 패턴 | 50+ | ≤5 |
| 코드 품질 점수 | 45/100 | ≥80/100 |

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 기능 회귀 | Critical | Medium | 단계별 테스트, Git 브랜치 관리 |
| 순환 임포트 | High | Medium | 의존성 방향 설계 |
| 상태 공유 문제 | High | Low | AppState 싱글톤 패턴 유지 |
| NiceGUI 호환성 | Medium | Low | 컴포넌트별 테스트 |

---

## 6. Architecture Considerations

### 6.1 Project Level

| Level | Characteristics | Selected |
|-------|-----------------|:--------:|
| **Starter** | Simple structure | |
| **Dynamic** | Feature-based modules | ✅ |
| **Enterprise** | Strict layer separation | |

### 6.2 Target Architecture

```
src/shorts_maker/
├── gui.py                     # Entry point (~50 lines)
│
├── state/                     # State Management Layer
│   ├── __init__.py
│   ├── app_state.py           # AppState dataclass
│   └── session_manager.py     # SessionManager class
│
├── components/                # UI Components Layer
│   ├── __init__.py
│   ├── common/                # Shared components
│   │   ├── __init__.py
│   │   ├── safe_ui.py         # safe_notify, safe_refresh
│   │   ├── card_header.py     # Reusable card component
│   │   ├── step_indicator.py  # Pipeline step display
│   │   └── error_panel.py     # Error display component
│   │
│   ├── pipeline_tab.py        # Pipeline execution tab
│   ├── sources_tab.py         # RSS/URL sources tab
│   ├── planning_tab.py        # Script planning tab
│   ├── generation_tab.py      # Video generation tab
│   ├── publishing_tab.py      # YouTube upload tab
│   └── scheduling_tab.py      # Schedule management tab
│
├── pages/                     # Page Layout Layer
│   ├── __init__.py
│   └── main_page.py           # Main page composition
│
└── config/                    # Configuration Layer
    ├── __init__.py
    ├── constants.py           # Magic numbers, limits
    └── ui_theme.py            # Colors, gradients, CSS classes
```

### 6.3 Dependency Direction

```
gui.py (entry)
    │
    ▼
pages/main_page.py
    │
    ▼
components/*_tab.py
    │
    ├──▶ components/common/*
    │
    ├──▶ state/app_state.py
    │
    └──▶ config/constants.py
```

### 6.4 Key Design Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 상태 관리 | Context / Singleton | Singleton | NiceGUI 특성상 간단한 싱글톤 유지 |
| 컴포넌트 구조 | Class / Function | Function | NiceGUI 스타일과 일관성 |
| 설정 관리 | Env / Constants | Constants | UI 관련 상수는 코드 내 관리 |

---

## 7. Implementation Plan

### 7.1 Phase 순서

```
Phase 1: 공통 유틸리티 (safe_ui, constants)
    │
    ▼
Phase 2: 상태 관리 분리 (app_state, session_manager)
    │
    ▼
Phase 3: 공통 컴포넌트 (card_header, step_indicator)
    │
    ▼
Phase 4: 탭 컴포넌트 분리 (6개 탭)
    │
    ▼
Phase 5: 메인 진입점 정리 (gui.py 최소화)
```

### 7.2 Phase별 예상 변경

| Phase | 새 파일 | 수정 파일 | 삭제 라인 |
|-------|---------|----------|----------|
| Phase 1 | 3 | gui.py | ~100 |
| Phase 2 | 3 | gui.py | ~100 |
| Phase 3 | 4 | gui.py | ~50 |
| Phase 4 | 6 | gui.py | ~1,800 |
| Phase 5 | 2 | gui.py | ~80 |

### 7.3 Rollback Plan

- Git 브랜치: `feature/gui-refactoring`
- 각 Phase 완료 시 커밋
- 문제 발생 시 해당 Phase만 롤백 가능

---

## 8. Estimates

| Phase | 예상 작업량 | 복잡도 |
|-------|:---------:|:------:|
| Phase 1 | 중 | 낮음 |
| Phase 2 | 중 | 중간 |
| Phase 3 | 중 | 낮음 |
| Phase 4 | 대 | 중간 |
| Phase 5 | 소 | 낮음 |

---

## 9. Next Steps

1. [ ] Design 문서 작성 (`gui-refactoring.design.md`)
2. [ ] Phase 1 구현 시작
3. [ ] 단계별 테스트 및 검증
4. [ ] Gap 분석

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-03 | Initial draft | Claude |
