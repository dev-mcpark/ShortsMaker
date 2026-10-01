# Script Feedback Loop Planning Document

> **Summary**: 스크립트 생성 품질 향상과 Human-in-the-Loop 피드백 루프 구현
>
> **Project**: ShortsMaker Studio
> **Version**: 0.3.0
> **Author**: Claude
> **Date**: 2026-03-22
> **Status**: Draft

---

## 1. Overview

### 1.1 Purpose

현재 파이프라인은 스크립트 생성 후 사용자 검토/피드백 없이 영상 생성으로 바로 진행됩니다.
이번 개선을 통해:

1. **스크립트 피드백 루프**: 생성된 스크립트에 피드백을 주고 재생성하는 UI 흐름
2. **주제 후보 투명성**: 왜 이 주제가 선택됐는지 점수와 이유를 UI에 노출
3. **Veo 프롬프트 검토**: 영상 생성 전 씬별 프롬프트를 검토/편집하는 단계

### 1.2 Background

**아키텍처 분석에서 발견된 핵심 갭**:

- `ScriptPlanner._write_script(feedback=None)` — feedback 파라미터가 이미 존재하지만 GUI에서 호출 경로 없음
- `_select_best_topic()` — GPT-4o가 인덱스 번호만 반환, 선택 이유 불투명
- `ProductionService` — "멈추고 사용자 확인" 체크포인트 개념 없음
- `VideoGenerator` — private 메서드를 ProductionService가 직접 호출 (캡슐화 위반)

**사용자 요구사항**:
- 각 프로세스마다 사용자의 조언/통제
- 스크립트와 프롬프트에 피드백을 주고 반영

### 1.3 Related Documents

- 아키텍처 분석: 2026-03-22 세션 분석
- `docs/archive/2026-02/gui-refactoring/`: 이전 GUI 모듈화 PDCA
- `src/shorts_maker/planner/script_planner.py:509` — `_write_script(feedback)` 기존 구현

---

## 2. Scope

### 2.1 In Scope

**Phase A: 스크립트 피드백 루프**
- [ ] `ProductionService.regenerate_script(script, feedback)` 메서드 추가
- [ ] `_select_best_topic()` → 후보 목록 + 각 후보의 선택 이유 반환
- [ ] Planning Tab UI: 피드백 입력창 + "재생성" 버튼
- [ ] Planning Tab UI: 주제 후보 목록과 선택 이유 표시 패널

**Phase B: Veo 프롬프트 검토 단계**
- [ ] `VideoGenerator.get_scene_prompts(script)` public 메서드 추가
- [ ] `VideoGenerator.generate_from_prompts(scenes, prompts)` public 메서드 추가
- [ ] `ProductionService.prepare_generation(script)` — 프롬프트만 준비하는 단계
- [ ] Generation Tab UI: 씬별 프롬프트 편집 패널

**공통**
- [ ] `ScriptPlanner` 파일 경로 `settings` 상수로 교체 (history_file, script_output_dir)

### 2.2 Out of Scope

- 스케줄링 기능
- 편집 옵션 (자막/BGM) 피드백
- YouTube 업로드 메타데이터 편집 UI (별도 개선)
- 테스트 코드 (별도 PDCA)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| FR-01 | 스크립트 생성 후 피드백 입력 → 동일 주제로 재생성 | Critical | A |
| FR-02 | 주제 후보 목록과 선택 이유를 UI에 표시 | High | A |
| FR-03 | 재생성 횟수 제한 (최대 3회) 및 카운터 표시 | Medium | A |
| FR-04 | 생성 전 씬별 Veo 프롬프트 확인 및 편집 가능 | Critical | B |
| FR-05 | 프롬프트 편집 후 해당 씬만 재생성 가능 | High | B |
| FR-06 | `ScriptPlanner` 파일 경로 settings 상수 사용 | Low | 공통 |

### 3.2 Non-Functional Requirements

| Category | Criteria |
|----------|----------|
| Responsiveness | 피드백 제출 → 재생성 시작까지 1초 이내 UI 반응 |
| Usability | 피드백 입력창은 스크립트 옆에 배치 (별도 탭 이동 없음) |
| Compatibility | 기존 Pipeline Tab 자동 실행 흐름 100% 유지 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] Planning Tab에서 스크립트 → 피드백 → 재생성 흐름 동작
- [ ] 주제 후보 패널에서 선택 이유 확인 가능
- [ ] Generation Tab에서 프롬프트 편집 후 생성 가능
- [ ] 기존 Pipeline Tab 자동 실행 흐름 깨지지 않음
- [ ] 구문 오류 없음

### 4.2 Quality Criteria

| Metric | Target |
|--------|--------|
| 기존 기능 호환성 | 100% |
| 신규 코드 모듈 크기 | ≤ 150줄/파일 |
| 서비스 레이어 캡슐화 | VideoGenerator private 메서드 직접 호출 0건 |

---

## 5. Architecture Decisions

### 5.1 체크포인트 패턴 (Human-in-the-Loop)

Full pipeline은 그대로 유지. 개별 단계 메서드를 강화하는 방식 선택.

```
[현재]
full_pipeline() → generate_script() → produce_video() → upload()

[변경 후]
generate_script()          ← Planning Tab에서 호출
    ↓ (UI 검토)
regenerate_script(feedback) ← "재생성" 버튼
    ↓ (UI 승인)
prepare_generation(script)  ← 프롬프트만 준비 (NEW)
    ↓ (UI 프롬프트 편집)
produce_video(script, prompts) ← Generation Tab에서 호출
```

`full_pipeline()`은 자동 실행 모드(Pipeline Tab)에서 그대로 사용.

### 5.2 주제 후보 점수 반환

```python
# 현재
async def _select_best_topic(candidates) -> Dict

# 변경 후
@dataclass
class TopicCandidate:
    item: Dict
    score: int          # 1-10
    reason: str         # 선택/미선택 이유
    selected: bool

async def _score_topics(candidates) -> List[TopicCandidate]
```

### 5.3 VideoGenerator Public API 정비

```python
# 현재 (캡슐화 위반)
generator._generate_background_video(scene)
generator._composite_character_on_video(bg, scene)

# 변경 후
generator.generate_scene_clip(scene) -> str   # public
generator.get_scene_prompt(scene) -> str      # public (프롬프트 반환만)
```

---

## 6. Risks and Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Planning Tab 리팩토링 중 기존 기능 회귀 | High | Pipeline Tab은 수정하지 않음 |
| GPT-4o 호출 증가로 비용 상승 | Medium | 재생성 최대 3회 제한 |
| Veo 프롬프트 편집 UI 복잡도 | Medium | 씬 카드에 편집 가능한 텍스트 영역으로 단순하게 구현 |

---

## 7. Implementation Plan

### Phase A (스크립트 피드백 루프)

```
1. ProductionService.regenerate_script() 추가
2. ScriptPlanner._score_topics() 리팩토링
3. Planning Tab UI 개선
   - 주제 후보 패널
   - 스크립트 피드백 입력창 + 재생성 버튼
```

### Phase B (Veo 프롬프트 검토)

```
1. VideoGenerator public API 정비
2. ProductionService.prepare_generation() 추가
3. Generation Tab UI 개선
   - 씬별 프롬프트 편집 패널
```

### 파일별 변경 예상

| 파일 | 변경 유형 | 예상 변경량 |
|------|----------|------------|
| `services/production_service.py` | 메서드 추가 | +50줄 |
| `planner/script_planner.py` | 메서드 변경 | +30줄 |
| `planner/models.py` | 모델 추가 | +20줄 |
| `generator/video_generator.py` | public API 추가 | +20줄 |
| `gui/components/planning_tab.py` | UI 개선 | +80줄 |
| `gui/components/generation_tab.py` | UI 개선 | +60줄 |

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`script-feedback-loop.design.md`)
2. [ ] Phase A 구현
3. [ ] Phase B 구현
4. [ ] Gap 분석

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-22 | Initial draft | Claude |
