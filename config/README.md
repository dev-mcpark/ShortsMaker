# ShortsMaker 설정 가이드

이 문서는 ShortsMaker를 실행하기 위한 설정 방법을 안내합니다.

## 📁 설정 파일 구조

```
config/
├── .env.example          # 환경변수 템플릿 (이 파일을 복사하여 사용)
├── .env                  # 실제 환경변수 (Git 제외)
├── credentials/          # 인증 파일 폴더
│   ├── service_account.json   # GCP 서비스 계정 (Veo/Imagen용)
│   ├── client_secrets.json    # YouTube OAuth (선택)
│   └── token.json             # YouTube 토큰 (자동 생성)
└── README.md             # 이 파일
```

## 🚀 빠른 시작

### 1단계: 환경변수 파일 생성

```bash
cp config/.env.example config/.env
```

또는 프로젝트 루트에 `.env` 파일을 생성해도 됩니다.

### 2단계: 필수 API 키 설정

`.env` 파일을 열고 다음 값들을 설정하세요.

---

## 1. OpenAI API (필수)

**용도:** GPT-4o (스크립트 생성), TTS (나레이션 음성)

### 발급 방법
1. https://platform.openai.com 접속
2. 로그인 후 API Keys 메뉴 이동
3. "Create new secret key" 클릭
4. 생성된 키를 `.env`의 `OPENAI_API_KEY`에 입력

```env
OPENAI_API_KEY="sk-proj-xxxxxxxxxxxxxxxx"
```

### 예상 비용
- GPT-4o: 스크립트 1개당 약 $0.01~0.03
- TTS: 1분 음성당 약 $0.015

---

## 2. Google Cloud Platform (필수)

**용도:** Veo (AI 영상 생성), Imagen (AI 이미지 생성)

### 2-1. GCP 프로젝트 생성

1. https://console.cloud.google.com 접속
2. 상단 프로젝트 선택기 클릭 → "새 프로젝트" 생성
3. 프로젝트 ID 확인 (예: `my-shorts-maker-12345`)
4. `.env`에 프로젝트 ID 입력:
   ```env
   GCP_PROJECT_ID="my-shorts-maker-12345"
   ```

### 2-2. Vertex AI API 활성화

1. GCP Console에서 "APIs & Services" → "Library" 이동
2. "Vertex AI API" 검색 후 활성화
3. 결제 계정 연결 필요 (무료 크레딧 $300 제공)

### 2-3. 서비스 계정 생성

1. GCP Console → "IAM & Admin" → "Service Accounts"
2. "Create Service Account" 클릭
3. 설정:
   - 이름: `shorts-maker-service`
   - 역할: `Vertex AI User`
4. 생성 후 해당 계정 클릭 → "Keys" 탭
5. "Add Key" → "Create new key" → JSON 선택
6. 다운로드된 파일을 `config/credentials/service_account.json`으로 저장

```bash
mv ~/Downloads/my-project-xxxxx.json config/credentials/service_account.json
```

### 예상 비용
- Veo: 영상 1개당 약 $0.05~0.15
- Imagen: 이미지 1개당 약 $0.01~0.02

---

## 3. YouTube API (선택)

**용도:** 생성된 영상을 YouTube에 자동 업로드

> ⚠️ 자동 업로드 기능을 사용하지 않으면 이 설정은 건너뛰어도 됩니다.

### 3-1. YouTube Data API 활성화

1. GCP Console → "APIs & Services" → "Library"
2. "YouTube Data API v3" 검색 후 활성화

### 3-2. OAuth 동의 화면 구성

1. "APIs & Services" → "OAuth consent screen"
2. User Type: "External" 선택
3. 앱 정보 입력:
   - 앱 이름: `ShortsMaker`
   - 사용자 지원 이메일: 본인 이메일
4. 범위(Scopes) 추가:
   - `youtube.upload`
   - `youtube.readonly`
5. 테스트 사용자에 본인 이메일 추가

### 3-3. OAuth 클라이언트 ID 생성

1. "APIs & Services" → "Credentials"
2. "Create Credentials" → "OAuth client ID"
3. 애플리케이션 유형: "Desktop app"
4. 이름: `ShortsMaker Desktop`
5. JSON 다운로드 → `config/credentials/client_secrets.json`으로 저장

### 3-4. 첫 인증

처음 YouTube 업로드 시 브라우저가 열리며 Google 로그인을 요청합니다.
로그인 후 `token.json`이 자동 생성되며, 이후에는 자동 인증됩니다.

---

## 4. Pixabay API (선택)

**용도:** BGM 및 스톡 이미지 검색

1. https://pixabay.com/api/docs/ 접속
2. 회원가입 후 API Key 확인
3. `.env`에 입력:
   ```env
   PIXABAY_API_KEY="your-pixabay-key"
   ```

> 미설정 시 `bgm/` 폴더의 기본 BGM이 사용됩니다.

---

## ✅ 설정 검증

모든 설정이 올바른지 확인하려면:

```bash
python -m shorts_maker.utils.config --validate
```

정상적인 출력 예시:
```
==================================================
🎬 ShortsMaker Configuration Status
==================================================

📌 API Keys:
   OpenAI:   ✅ sk-proj-...xxxx
   Pixabay:  ✅ 54133958...5463

☁️ Google Cloud:
   Project:  my-shorts-maker-12345
   Location: us-central1
   Veo:      veo-3.1-fast-generate-001

🔐 Credentials:
   Service Account: ✅ config/credentials/service_account.json
   YouTube OAuth:   ✅ config/credentials/client_secrets.json

✅ All configurations valid!
==================================================
```

---

## 🔒 보안 주의사항

1. **절대로 인증 파일을 Git에 커밋하지 마세요**
   - `.env`, `service_account.json`, `client_secrets.json`은 `.gitignore`에 포함됨

2. **API 키 노출 시 즉시 재발급**
   - OpenAI: https://platform.openai.com/api-keys 에서 키 삭제 후 재발급
   - GCP: 서비스 계정 키 삭제 후 새 키 생성

3. **프로덕션 환경에서는 환경변수 사용 권장**
   ```bash
   export OPENAI_API_KEY="sk-proj-xxx"
   export GCP_PROJECT_ID="my-project"
   ```

---

## 🆘 문제 해결

### "OPENAI_API_KEY 미설정" 오류
- `.env` 파일에 `OPENAI_API_KEY` 값이 있는지 확인
- 키가 `sk-`로 시작하는지 확인

### "서비스 계정 파일 없음" 오류
- `config/credentials/service_account.json` 파일 존재 확인
- 또는 프로젝트 루트의 `service_account.json` 확인

### "Vertex AI API not enabled" 오류
- GCP Console에서 Vertex AI API 활성화 여부 확인
- 결제 계정 연결 여부 확인

### YouTube 업로드 실패
- `client_secrets.json` 파일 확인
- OAuth 동의 화면에서 테스트 사용자 등록 확인
- `token.json` 삭제 후 재인증 시도
