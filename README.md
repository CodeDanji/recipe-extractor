# 🍳 유튜브 레시피 추출 시스템

YouTube 요리 영상에서 자동으로 레시피와 재료를 추출하고, 가진 재료로 만들 수 있는 요리를 추천해주는 웹 애플리케이션입니다.

## ✨ 주요 기능

- 📹 **YouTube 플레이리스트 자동 처리**: 여러 요리 영상을 한 번에 분석
- 🎤 **음성-텍스트 변환**: OpenAI Whisper API로 영상 대사 추출
- 🤖 **AI 재료 추출**: GPT-3.5로 요리 이름과 재료 자동 분석
- 🔍 **스마트 검색**: 가진 재료로 만들 수 있는 레시피 추천
- 📊 **매칭률 표시**: 재료 일치도를 %로 표시
- 💾 **데이터베이스 저장**: SQLite로 효율적인 데이터 관리

## 🚀 빠른 시작

### 1. 필수 요구사항

```bash
Python 3.10 이상
FFmpeg (오디오 변환용)
```

### 2. 설치

```bash
# 저장소 클론
git clone https://github.com/your-username/recipe-extractor.git
cd recipe-extractor

# 가상환경 생성 (권장)
python -m venv venv

# 가상환경 활성화
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```

### 3. FFmpeg 설치

#### Windows
```bash
# Chocolatey 사용
choco install ffmpeg

# 또는 https://ffmpeg.org/download.html 에서 직접 다운로드
```

#### Mac
```bash
brew install ffmpeg
```

#### Linux
```bash
sudo apt install ffmpeg
```

### 4. API 키 설정

1. `.env.example` 파일을 `.env`로 복사
```bash
cp .env.example .env
```

2. `.env` 파일 편집하여 API 키 입력
```env
OPENAI_API_KEY=sk-your-openai-key-here
YOUTUBE_API_KEY=your-youtube-api-key-here
SECRET_KEY=random-secret-key-here
```

#### API 키 발급 방법

**OpenAI API Key:**
1. https://platform.openai.com/api-keys 접속
2. "Create new secret key" 클릭
3. 키 복사 (한 번만 표시됨!)

**YouTube API Key:**
1. https://console.cloud.google.com 접속
2. 새 프로젝트 생성
3. "YouTube Data API v3" 활성화
4. "사용자 인증 정보" → "API 키" 생성

### 5. 실행

```bash
python app.py
```

브라우저에서 http://localhost:5000 접속

## 📖 사용 방법

### 1단계: 영상 처리
1. YouTube에서 요리 플레이리스트 URL 복사
2. 메인 페이지에서 URL 입력
3. "영상 처리 시작" 클릭
4. 처리 완료 대기 (영상당 약 1-2분)

### 2단계: 레시피 추천
1. "레시피 추천받기" 클릭
2. 가진 재료 입력 (쉼표로 구분)
   - 예: `돼지고기, 김치, 두부, 대파`
3. 매칭률 순으로 정렬된 레시피 확인
4. 영상 링크로 요리 방법 확인

## 🏗️ 프로젝트 구조

```
recipe-extractor/
├── app.py                 # 메인 Flask 애플리케이션
├── requirements.txt       # Python 의존성
├── .env                   # 환경 변수 (Git 제외)
├── .env.example          # 환경 변수 템플릿
├── Procfile              # 배포용 설정
├── .gitignore            # Git 제외 파일
├── templates/
│   └── recommend.html    # 추천 페이지 템플릿
├── recipes.db            # SQLite 데이터베이스
└── app.log              # 애플리케이션 로그
```

## ⚙️ 설정 옵션

`.env` 파일에서 다음을 설정할 수 있습니다:

```env
# 필수
OPENAI_API_KEY=your_key
YOUTUBE_API_KEY=your_key

# 선택 (기본값 있음)
SECRET_KEY=random_string       # Flask 세션 키
DEBUG=False                    # 디버그 모드
PORT=5000                      # 서버 포트
MAX_WORKERS=1                  # 병렬 처리 수 (1-3 권장)
DATABASE_PATH=recipes.db       # DB 파일 경로
```

## 💡 최적화 팁

### 속도 향상
- `MAX_WORKERS`를 2-3으로 증가 (API 제한 주의)
- 이미 처리된 영상은 자동 스킵됨
- 짧은 영상부터 처리하면 빠름

### 비용 절감
- 영상당 비용: 약 $0.007 (Whisper + GPT-3.5)
- 100개 영상 처리 시: ~$0.70
- 중복 처리 방지로 비용 절감

### 정확도 향상
- 대본이 명확한 영상 선택
- 재료 언급이 많은 영상 권장
- 영상 설명에 재료 목록이 있으면 더 정확

## 🐛 문제 해결

### FFmpeg 없음 오류
```bash
# 설치 확인
ffmpeg -version

# PATH 설정 확인
```

### API 키 오류
```bash
# .env 파일 확인
cat .env

# 환경 변수 로드 확인
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('OPENAI_API_KEY'))"
```

### 데이터베이스 락
```bash
# 다른 프로세스가 DB를 사용 중인지 확인
# app.py 재시작
```

### 다운로드 타임아웃
- 네트워크 연결 확인
- 영상이 너무 길면 실패 가능 (30분 이상)
- VPN 사용 시 비활성화

## 📊 데이터베이스 구조

```sql
CREATE TABLE recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    ingredients TEXT,
    dish_name TEXT,
    url TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 🔒 보안 주의사항

- ⚠️ `.env` 파일을 절대 Git에 커밋하지 마세요
- ⚠️ API 키를 공개하지 마세요
- ⚠️ 프로덕션에서는 `DEBUG=False` 설정
- ⚠️ `SECRET_KEY`는 랜덤하게 생성

## 📈 향후 계획

- [ ] 사용자 계정 및 로그인
- [ ] 즐겨찾기 기능
- [ ] 레시피 평점 시스템
- [ ] 모바일 앱 개발
- [ ] 이미지 인식 추가
- [ ] 다국어 지원
- [ ] PostgreSQL 마이그레이션

## 🤝 기여하기

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 라이선스

MIT License - 자유롭게 사용하세요!

## 📧 연락처

문제나 제안사항이 있으시면 Issues를 열어주세요.

## 🙏 감사의 말

- OpenAI (Whisper & GPT-3.5)
- Google (YouTube API)
- Flask Framework
- yt-dlp 프로젝트

---

**즐거운 코딩 되세요! 🚀**