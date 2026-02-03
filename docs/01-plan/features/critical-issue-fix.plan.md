# Critical Issue Fix Planning Document

> **Summary**: 코드 품질 분석에서 발견된 Critical 보안 및 품질 이슈 수정
>
> **Project**: ShortsMaker Studio
> **Version**: 0.1.0
> **Author**: Claude
> **Date**: 2026-02-02
> **Status**: Draft

---

## 1. Overview

### 1.1 Purpose

코드 품질 분석(72/100점)에서 발견된 6개의 Critical 이슈를 체계적으로 수정하여 코드 안정성과 보안을 강화합니다.

### 1.2 Background

2026-02-02 코드 분석 결과, 다음과 같은 Critical 이슈가 발견되었습니다:
- 환경변수 직접 오버라이드 (보안 취약점)
- MD5 해시 사용 (암호학적으로 안전하지 않음)
- API 키 None 체크 누락 (런타임 에러 가능)
- 광범위한 bare except 사용 (디버깅 어려움)

### 1.3 Related Documents

- Code Analysis Report: 2026-02-02 코드 품질 분석 결과
- CLAUDE.md: 프로젝트 가이드라인

---

## 2. Scope

### 2.1 In Scope

- [x] `gui.py:387-389` 환경변수 직접 오버라이드 수정
- [x] `script_planner.py:29` MD5 → SHA256 변경
- [x] `script_planner.py:86` API 키 유효성 검증 추가
- [x] `script_validator.py:18` API 키 유효성 검증 추가
- [x] `video_editor.py:40` API 키 유효성 검증 추가
- [x] `gui.py:476-498` bare except → 구체적 예외 타입 지정

### 2.2 Out of Scope

- Warning 레벨 이슈 (gui.py 모듈 분리 등)
- Info 레벨 이슈 (테스트 코드 추가 등)
- 새로운 기능 추가

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 환경변수를 런타임에 직접 수정하지 않고 설정 객체 전달 방식으로 변경 | High | Pending |
| FR-02 | MD5 해시를 SHA256으로 교체 | High | Pending |
| FR-03 | 모든 API 키 사용 전 None/빈 문자열 체크 추가 | High | Pending |
| FR-04 | bare except를 구체적인 예외 타입으로 변경 | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Security | 환경변수 직접 수정 제거 | 코드 리뷰 |
| Security | 암호학적으로 안전한 해시 사용 | SHA256 사용 확인 |
| Reliability | API 키 누락 시 명확한 에러 메시지 | 테스트 |
| Maintainability | 예외 처리 명확화 | 코드 리뷰 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [x] 모든 Critical 이슈 수정 완료
- [x] 기존 기능 정상 동작 확인
- [x] 린트 에러 없음
- [x] 코드 리뷰 완료

### 4.2 Quality Criteria

- [x] 환경변수 직접 수정 코드 0개
- [x] MD5 사용 0개
- [x] API 키 None 체크 100%
- [x] bare except 사용 0개

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 기존 기능 회귀 | High | Medium | 수정 전후 기능 테스트 |
| API 키 검증 추가로 인한 UX 변화 | Low | Low | 명확한 에러 메시지 제공 |
| 예외 타입 변경으로 인한 예기치 않은 에러 | Medium | Low | 점진적 수정 및 테스트 |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure | Static sites | |
| **Dynamic** | Feature-based modules, services layer | Web apps with backend | :white_check_mark: |
| **Enterprise** | Strict layer separation | High-traffic systems | |

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| Framework | NiceGUI (Python) | NiceGUI | 기존 선택 유지 |
| 설정 관리 | os.getenv / Settings 객체 | Settings 객체 | 중앙 집중식 관리 |
| 해시 알고리즘 | MD5 / SHA256 | SHA256 | 보안 강화 |
| 예외 처리 | bare except / 구체적 타입 | 구체적 타입 | 디버깅 용이성 |

### 6.3 Clean Architecture Approach

```
Selected Level: Dynamic

현재 폴더 구조:
src/shorts_maker/
├── gui.py                 # Presentation
├── services/              # Application (production_service.py)
├── planner/               # Domain
├── generator/             # Infrastructure
├── editor/                # Infrastructure
├── uploader/              # Infrastructure
└── utils/                 # Shared utilities (config.py, logger.py)
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

Check which conventions already exist in the project:

- [x] `CLAUDE.md` has coding conventions section
- [ ] `docs/01-plan/conventions.md` exists
- [ ] `CONVENTIONS.md` exists at project root
- [ ] ESLint configuration (N/A - Python project)
- [ ] Prettier configuration (N/A - Python project)
- [ ] pyproject.toml with ruff configuration

### 7.2 Conventions to Define/Verify

| Category | Current State | To Define | Priority |
|----------|---------------|-----------|:--------:|
| **환경변수 관리** | exists (config.py) | settings 객체 일관성 사용 | High |
| **예외 처리** | 불일관 | 구체적 예외 타입 사용 규칙 | High |
| **해시 함수** | MD5 혼재 | SHA256 전용 사용 | High |
| **API 키 검증** | 불일관 | 사용 전 반드시 검증 | High |

### 7.3 Environment Variables Needed

| Variable | Purpose | Scope | Status |
|----------|---------|-------|:------:|
| `OPENAI_API_KEY` | OpenAI API 키 | Server | Exists |
| `GCP_PROJECT_ID` | Google Cloud 프로젝트 ID | Server | Exists |
| `GOOGLE_APPLICATION_CREDENTIALS` | GCP 서비스 계정 | Server | Exists |

---

## 8. Implementation Plan

### 8.1 수정 항목 상세

#### Issue 1: 환경변수 직접 오버라이드 (`gui.py:387-389`)
```python
# Before
os.environ['OPENAI_API_KEY'] = api_key

# After
# settings 객체를 통해 API 키를 전달하거나
# 모듈 초기화 시 설정 객체를 주입
```

#### Issue 2: MD5 사용 (`script_planner.py:29`)
```python
# Before
import hashlib
hash_key = hashlib.md5(url.encode()).hexdigest()

# After
hash_key = hashlib.sha256(url.encode()).hexdigest()
```

#### Issue 3-5: API 키 None 체크
```python
# Before
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# After
api_key = settings.openai_api_key
if not api_key:
    raise ValueError("OPENAI_API_KEY is not configured")
client = OpenAI(api_key=api_key)
```

#### Issue 6: bare except 제거
```python
# Before
except:
    pass

# After
except (ValueError, TypeError, KeyError) as e:
    logger.warning(f"Expected error occurred: {e}")
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise
```

---

## 9. Next Steps

1. [ ] Write design document (`critical-issue-fix.design.md`)
2. [ ] 수정 작업 수행
3. [ ] 기능 테스트
4. [ ] 코드 리뷰
5. [ ] Gap 분석

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-02 | Initial draft | Claude |
