# Web Browser Engineering

Python으로 밑바닥부터 구현하는 웹 브라우저 프로젝트

## 환경 설정

이 프로젝트는 **uv**를 사용하여 관리됩니다.

### uv 설치 (아직 설치하지 않은 경우)

**Windows (PowerShell):**
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 프로젝트 초기화

```bash
cd C:\Users\m\Projects\web-browser
uv sync
```

## 챕터별 구현

### Chapter 1: Downloading Web Pages (웹 페이지 다운로드)

**학습 목표:**
- URL 파싱 방법 이해
- 소켓을 이용한 네트워크 통신
- HTTP 프로토콜의 기본 구조
- HTML에서 텍스트 추출
- ✨ **NEW!** 압축 해제 (gzip, deflate, brotli)

**실행 방법 (uv 사용):**
```bash
# 기본 예제 실행
uv run lab1.py

# 특정 URL 지정
uv run lab1.py http://example.org/

# HTTPS + 압축 테스트
uv run lab1.py https://www.google.com/

# Brotli 압축 테스트
uv run lab1.py https://www.naver.com/
```

**주요 구현 내용:**

1. **URL 클래스**: URL을 scheme, host, path로 파싱
2. **request() 메서드**: 
   - 소켓으로 서버 연결
   - HTTP 요청 전송 (Accept-Encoding 헤더 포함)
   - 응답 수신 및 파싱
   - 압축 해제 (gzip/deflate/brotli)
3. **show() 함수**: HTML 태그 제거하고 텍스트만 출력

**압축 지원:**
- ✅ **gzip**: Python 표준 라이브러리 (gzip 모듈)
- ✅ **deflate**: Python 표준 라이브러리 (zlib 모듈)
- ✅ **brotli**: 외부 패키지 (brotli 모듈)

**압축 방식 설명:**

| 압축 방식 | HTTP 헤더 | 압축률 | 속도 | 브라우저 지원 |
|----------|----------|-------|------|-------------|
| gzip | `Content-Encoding: gzip` | 좋음 (74%) | 빠름 | 100% |
| deflate | `Content-Encoding: deflate` | 좋음 (75%) | 빠름 | 100% |
| brotli | `Content-Encoding: br` | 최고 (80%) | 보통 | 95%+ |

## UV 명령어 참고

```bash
# Python 스크립트 실행
uv run <script.py>

# 의존성 추가
uv add <package-name>

# 의존성 제거
uv remove <package-name>

# 가상환경 동기화
uv sync

# Python 버전 확인
uv run python --version
```

## 필수 요구사항

- Python 3.9+
- 기본 라이브러리 (socket, ssl, gzip, zlib)
- brotli (압축 해제용)
- uv (Python 패키지 관리자)

## 테스트 URL 예시

```bash
# ✅ 압축 없음 (단순 테스트)
uv run lab1.py http://example.org/
uv run lab1.py http://info.cern.ch/

# ✅ gzip 압축
uv run lab1.py https://www.wikipedia.org/

# ✅ brotli 압축
uv run lab1.py https://www.google.com/
uv run lab1.py https://www.naver.com/

# ✅ HTTPS + 압축
uv run lab1.py https://browser.engineering/
```

## 주요 개선사항

### 압축 지원 추가 (v0.1.0)
- gzip, deflate, brotli 압축 자동 해제
- Accept-Encoding 헤더 추가
- 바이너리 모드로 응답 읽기
- 압축 상태 시각적 피드백

## 참고 자료

- [Web Browser Engineering (온라인 책)](https://browser.engineering/)
- [GitHub Repository](https://github.com/browserengineering/book)
- [uv 공식 문서](https://docs.astral.sh/uv/)
- [Brotli 압축 설명](https://github.com/google/brotli)
