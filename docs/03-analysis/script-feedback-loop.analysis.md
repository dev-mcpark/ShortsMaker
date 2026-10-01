# Gap Analysis Report: script-feedback-loop

> **Feature**: script-feedback-loop
> **Date**: 2026-03-22
> **Match Rate**: **97%** (35/36 항목)
> **Status**: ✅ PASS

---

## 1. 분석 요약

| 카테고리 | 점수 | 상태 |
|----------|:----:|:----:|
| Data Models (models.py) | 100% | ✅ |
| Service Layer — ScriptPlanner | 100% | ✅ |
| Service Layer — ProductionService | 100% | ✅ |
| Service Layer — VideoGenerator | 100% | ✅ |
| GUI — Planning Tab | 100% | ✅ |
| GUI — Generation Tab | 83% | ✅ (소폭 차이) |
| AppState 신규 필드 | 100% | ✅ |
| State Flow | 100% | ✅ |
| **전체** | **97%** | ✅ **PASS** |

---

## 2. 일치 항목 (35/36)

### Data Models
- `TopicCandidate` — `item`, `score`, `reason`, `selected` 필드 모두 설계 일치
- `ScriptGenerationContext` — `source_item`, `candidates`, `attempt_count`, `max_attempts` 필드 모두 설계 일치

### ScriptPlanner
- `_score_topics()` — `_select_best_topic()` 대체, GPT-4o JSON 배열 응답으로 전체 후보 점수/이유 반환 ✅
- `plan_content()` 반환 타입 → `Tuple[Optional[ShortsScript], Optional[ScriptGenerationContext]]` ✅
- 파일 경로 `settings.topic_history_file`, `settings.url_history_file`, `settings.scripts_dir` 사용 ✅
- `_write_script(feedback=None)` — 기존 파라미터 그대로 활용 ✅

### ProductionService
- `generate_script()` 반환 타입 확장 → `Tuple[Optional[ShortsScript], Optional[ScriptGenerationContext]]` ✅
- `regenerate_script(context, feedback)` 신규 추가 ✅
- `prepare_generation(script)` 신규 추가 ✅
- `produce_video()` → `generator.generate_scene_clip(scene)` public API 사용 ✅
- `full_pipeline()` 호환성 수정 (`script, _context = await self.generate_script(...)`) ✅

### VideoGenerator
- `generate_scene_clip(scene)` public 메서드 — mode 분기, character overlay 처리 모두 설계 일치 ✅

### AppState
- `script_context: Any = None` ✅
- `script_regen_count: int = 0` ✅
- `topic_candidates: List[Any] = field(default_factory=list)` ✅

### Planning Tab
- 피드백 섹션 (초기 hidden, 각본 생성 후 표시) ✅
- 피드백 textarea + placeholder ✅
- 재생성 횟수 카운터 레이블 ✅
- "피드백 반영 재생성" 버튼 + 최대 횟수 초과 방지 ✅
- 주제 후보 expansion 패널 (점수/이유/선택 표시 카드) ✅
- `generate_script()` → `context.candidates` 저장 ✅

### Generation Tab
- 씬별 `visual_description` 편집 textarea ✅
- `motion_instruction` 편집 textarea (조건부) ✅
- 편집 내용 반영 로직 (`apply_prompt_edits()`) ✅

---

## 3. 차이 항목 (1/36)

| 항목 | 설계 명세 | 실제 구현 | 영향도 |
|------|----------|---------|--------|
| Generation Tab 버튼 텍스트 | "이 프롬프트로 생성 시작" | "편집 내용 반영 후 생성 시작" | 낮음 |

**평가**: 기능 동일, 텍스트가 더 명확하게 개선됨. 설계 문서 업데이트 권장.

---

## 4. 설계 외 추가 구현 사항

- `apply_prompt_edits()` 를 명명된 함수로 분리 — 설계에서 인라인 처리로 암시된 것을 클린하게 분리
- Planning Tab의 주제 후보 패널에서 점수 기준 내림차순 정렬 추가 (설계에 없는 UX 개선)

---

## 5. 누락 항목

없음 (0건)

---

## 6. 결론 및 권장 사항

Match Rate **97% ≥ 90%** — 추가 수정 불필요.

**선택적 후속 작업**:
- 설계 문서 Section 4.2 버튼 텍스트 업데이트 (낮은 우선순위)
- `/pdca report script-feedback-loop` 실행하여 완료 보고서 생성 권장

---

## Version History

| Version | Date | Author |
|---------|------|--------|
| 1.0 | 2026-03-22 | gap-detector |
