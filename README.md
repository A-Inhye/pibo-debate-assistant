# Pibo Debate Assistant - 실시간 토론 지원 시스템

실시간 음성 전사(STT) + 화자 인식 + ChatGPT 요약 기능을 갖춘 토론 지원 시스템입니다.

---

## 지원 플랫폼

| 플랫폼 | STT | 화자분리 | 요약 | 비고 |
|--------|-----|----------|------|------|
| **Linux (CUDA)** | Whisper | Sortformer | ChatGPT | 권장 환경 |
| **macOS (Apple Silicon)** | MLX-Whisper | diart | ChatGPT | M1/M2/M3/M4 지원 |
| **macOS (Intel)** | Whisper | diart | ChatGPT | 성능 제한 |

---

## 🚀 빠른 시작 (팀원용)

### 1. 레포지토리 클론
```bash
git clone https://github.com/A-Inhye/pibo-debate-assistant.git
cd pibo-debate-assistant
```

### 2. 가상환경 생성 및 활성화
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows
```

### 3. 의존성 설치
```bash
pip install -e .
pip install openai
```

### 4. OpenAI API 키 설정
```bash
# .env 파일 생성 (각자 API 키 발급 필요)
echo 'export OPENAI_API_KEY="sk-your-api-key-here"' > .env
```
⚠️ **API 키 발급:** https://platform.openai.com/api-keys

### 5. 서버 실행
```bash
source .env && python -m whisperlivekit.basic_server_pibo_design --model medium --language ko --diarization --enable-summary
```

### 6. 브라우저 접속
```
http://localhost:8000
```

---

## 🍎 macOS 설치 가이드 (Apple Silicon)

macOS에서는 MLX-Whisper (Apple Silicon 최적화)와 diart (화자분리)를 사용합니다.

### 자동 설치 (권장)
```bash
# 설치 스크립트 실행
./scripts/install_macos.sh
```

### 수동 설치

#### 1. Homebrew로 Python 3.11+ 설치 (권장)
```bash
brew install python@3.11 ffmpeg
```

#### 2. 가상환경 생성
```bash
python3.11 -m venv venv
source venv/bin/activate
```

#### 3. 의존성 설치
```bash
# 기본 패키지 설치
pip install -e .

# macOS 전용 패키지 설치
pip install mlx-whisper diart pyannote.audio openai
```

#### 4. Hugging Face 토큰 설정 (화자분리용)
pyannote 모델을 사용하려면 Hugging Face 토큰이 필요합니다:
1. https://huggingface.co/settings/tokens 에서 토큰 발급
2. https://huggingface.co/pyannote/segmentation-3.0 에서 모델 사용 동의
3. https://huggingface.co/pyannote/embedding 에서 모델 사용 동의

```bash
# 토큰 설정
huggingface-cli login
```

#### 5. OpenAI API 키 설정
```bash
echo 'export OPENAI_API_KEY="sk-your-api-key-here"' > .env
```

### macOS 실행 방법

```bash
# 전체 기능 (STT + 화자분리 + 요약)
source .env && python -m whisperlivekit.basic_server_pibo_design \
  --model small \
  --language ko \
  --diarization \
  --backend mlx-whisper \
  --enable-summary

# 화자분리 없이 (더 빠름)
source .env && python -m whisperlivekit.basic_server_pibo_design \
  --model small \
  --language ko \
  --backend mlx-whisper \
  --enable-summary
```

### macOS 성능 팁
- **모델 크기**: `small` 또는 `medium` 권장 (large는 느림)
- **MLX-Whisper**: Apple Silicon에서 ~70ms 추론 시간 (vs 1초+)
- **화자분리**: diart는 Sortformer보다 가볍지만 정확도는 다소 낮음

---

## ✨ 주요 기능

| 기능 | 설명 | 옵션 |
|------|------|------|
| **실시간 STT** | Whisper 모델로 음성→텍스트 | `--model medium` |
| **화자 인식** | Sortformer로 화자 구분 (최대 4명) | `--diarization` |
| **ChatGPT 요약** | 녹음 종료 시 대화 요약 생성 | `--enable-summary` |
| **한국어 지원** | 한국어 음성 인식 | `--language ko` |

---

## 수정/생성한 파일 목록

> 이 프로젝트를 위해 **새로 생성하거나 수정한 파일**들입니다.

### 새로 생성한 파일 (Created)

| 파일 경로 | 설명 |
|-----------|------|
| `whisperlivekit/basic_server_pibo_design.py` | 커스텀 서버 (LocalAgreement 강제 적용) |
| `whisperlivekit/summary/__init__.py` | 요약 모듈 초기화 |
| `whisperlivekit/summary/summarizer.py` | ChatGPT API 연동 요약 기능 |
| `whisperlivekit/web_pibo_design/live_transcription.html` | 커스텀 UI - HTML |
| `whisperlivekit/web_pibo_design/live_transcription.css` | 커스텀 UI - CSS (동적 클래스 포함) |
| `whisperlivekit/web_pibo_design/live_transcription.js` | JavaScript (요약 패널 포함) |
| `whisperlivekit/web_pibo_design/web_interface.py` | 인라인 HTML 생성 유틸리티 |
| `whisperlivekit/web_pibo_design/__init__.py` | 패키지 초기화 |
| `whisperlivekit/web_pibo_design/pcm_worklet.js` | AudioWorklet (원본에서 복사) |
| `whisperlivekit/web_pibo_design/recorder_worker.js` | Web Worker (원본에서 복사) |
| `whisperlivekit/web_pibo_design/src/*.svg` | 아이콘 파일들 (원본에서 복사) |

### 수정한 파일 (Modified)

| 파일 경로 | 수정 내용 |
|-----------|-----------|
| `pyproject.toml` | `whisperlivekit.web_pibo_design`, `whisperlivekit.summary` 패키지 등록 |
| `whisperlivekit/core.py` | `enable_summary`, `summary_model` 파라미터 추가 |
| `whisperlivekit/parse_args.py` | `--enable-summary`, `--summary-model` 옵션 추가 |
| `whisperlivekit/audio_processor.py` | 녹음 종료 시 요약 생성 로직 추가 |
| `whisperlivekit/timed_objects.py` | `FrontData`에 `summary` 필드 추가 |

### 핵심 변경 사항

**1. `basic_server_pibo_design.py`에서 LocalAgreement 강제 적용:**
```python
from whisperlivekit.web_pibo_design.web_interface import get_inline_ui_html
args.backend_policy = "localagreement"  # LocalAgreement 강제 사용
```

**2. `live_transcription.css`에 동적 클래스 추가:**
- `.spinner`, `.speaker-badge`, `.textcontent` - JavaScript가 동적으로 생성하는 요소
- `.label_*`, `.buffer_*` - 전사 결과 표시용
- `--wave-stroke: #4ade80` - 파형 시각화용 CSS 변수

---

## 프로젝트 개요

WhisperLiveKit은 OpenAI Whisper 모델을 사용한 실시간 음성 전사(STT) 시스템입니다. 이 프로젝트에서는 원본 WhisperLiveKit에 다음을 추가했습니다:

1. **커스텀 웹 UI** - 토론 지원에 적합한 2분할 레이아웃 디자인
2. **LocalAgreement 백엔드 고정** - 안정적인 전사를 위해 SimulStreaming 대신 LocalAgreement 사용
3. **화자 분리(Diarization)** - Sortformer 모델을 사용한 실시간 화자 식별

---

## 실행 방법

### 전체 기능 실행 (STT + 화자인식 + 요약)
```bash
source .env && python -m whisperlivekit.basic_server_pibo_design --model medium --language ko --diarization --enable-summary
```

### 요약 없이 실행 (STT + 화자인식만)
```bash
python -m whisperlivekit.basic_server_pibo_design --model medium --language ko --diarization
```

실행 후 브라우저에서 `http://localhost:8000` 접속하면 커스텀 UI가 표시됩니다.

### 실행 옵션 설명

| 옵션 | 설명 |
|------|------|
| `--model medium` | Whisper 모델 크기 (tiny, base, small, medium, large-v3) |
| `--language ko` | 인식할 언어 (ko=한국어, en=영어, auto=자동감지) |
| `--diarization` | 화자 분리 활성화 (누가 말했는지 구분) |
| `--enable-summary` | ChatGPT 요약 기능 활성화 (API 키 필요) |
| `--summary-model gpt-4o` | 요약에 사용할 모델 (기본값: gpt-4o) |

---

## 추가한 파일 설명

### 1. `basic_server_pibo_design.py` (서버 파일)

FastAPI 기반 WebSocket 서버입니다. 원본 `basic_server.py`를 복사하여 다음을 변경했습니다:

- **웹 UI 경로 변경**: `web/` → `web_pibo_design/`
- **LocalAgreement 백엔드 강제 적용**: SimulStreaming의 텐서 오류 문제를 피하기 위해

```python
# 핵심 변경 부분
from whisperlivekit.web_pibo_design.web_interface import get_inline_ui_html

args.backend_policy = "localagreement"  # LocalAgreement 강제 사용
```

### 2. `web_pibo_design/` (커스텀 UI 폴더)

사용자 제안 디자인을 적용한 웹 인터페이스입니다.

| 파일 | 설명 |
|------|------|
| `live_transcription.html` | 메인 HTML - 다크 헤더, 2분할 레이아웃 |
| `live_transcription.css` | 스타일시트 - 커스텀 디자인 + 동적 요소 스타일 |
| `live_transcription.js` | JavaScript - 녹음, WebSocket 통신, 화면 업데이트 (원본과 동일) |
| `web_interface.py` | HTML/CSS/JS를 하나의 인라인 HTML로 합치는 유틸리티 |
| `pcm_worklet.js` | AudioWorklet - PCM 오디오 처리 |
| `recorder_worker.js` | Web Worker - MediaRecorder 오디오 처리 |
| `src/*.svg` | 아이콘 파일들 |

### 3. `pyproject.toml` 수정

새로운 패키지를 Python이 인식하도록 등록했습니다:

```toml
# packages 목록에 추가
"whisperlivekit.web_pibo_design"

# package-data에 추가 (정적 파일 포함)
"web_pibo_design/*.html", "web_pibo_design/*.css", ...
```

---

## 삭제된 파일 (정리 완료)

개발 과정에서 생성되었던 **중복 파일들**은 이미 삭제되었습니다.

### 삭제된 파일/폴더

| 파일/폴더 | 삭제 이유 |
|-----------|-----------|
| `web_pibo/` | 이전 버전 UI, `web_pibo_design/`으로 대체됨 |
| `web_pibo_localagreement/` | 중복 UI, `web_pibo_design/`으로 대체됨 |
| `basic_server_pibo.py` | 이전 버전 서버, `basic_server_pibo_design.py`로 대체됨 |
| `basic_server_pibo_localagreement.py` | 중복 서버, `basic_server_pibo_design.py`로 대체됨 |

### 유지 중인 원본 파일 (나중에 사용 가능)

| 파일/폴더 | 설명 |
|-----------|------|
| `web/` | WhisperLiveKit 원본 웹 UI |
| `simul_whisper/` | SimulStreaming 백엔드 (현재 미사용) |
| `basic_server.py` | WhisperLiveKit 원본 서버 |

### 삭제하면 안 되는 파일 (필수)

| 파일/폴더 | 이유 |
|-----------|------|
| `local_agreement/` | LocalAgreement 백엔드 핵심 코드 |
| `whisper/` | Whisper 모델 관련 코드 |
| `diarization/` | 화자 분리 코드 |
| `audio_processor.py` | 오디오 처리 파이프라인 |
| `core.py` | TranscriptionEngine 핵심 코드 |

---

## 백엔드 정책 비교

WhisperLiveKit은 두 가지 스트리밍 백엔드를 제공합니다:

### LocalAgreement (이 프로젝트에서 사용)

- **동작 방식**: 여러 번의 전사 결과를 비교하여 일치하는 부분만 확정
- **장점**: 안정적, 오류 적음
- **단점**: 약간의 지연 발생 (확정까지 시간 필요)

### SimulStreaming (사용 안 함)

- **동작 방식**: Cross-attention을 분석하여 실시간으로 단어 경계 감지
- **장점**: 낮은 지연
- **단점**: KV Cache 관련 텐서 오류 발생 가능

**결론**: 안정성을 위해 LocalAgreement를 사용합니다.

---

## 커스텀 UI 구조

```
┌─────────────────────────────────────────────────────────────┐
│  실시간 상호작용형 자율 진화형 토론 중재 에이전트        [●]   │  ← 다크 헤더
├────────────────────────────┬────────────────────────────────┤
│                            │                                │
│   Live Transcript          │   Argument Summary             │
│                            │                                │
│   Speaker 1: 안녕하세요... │   Summary                      │
│   Speaker 2: 반갑습니다... │   전체 대화 요약...             │
│                            │                                │
│                            │   Speaker Arguments            │
│                            │   Speaker 1: 주장 요약...       │
│                            │   Speaker 2: 주장 요약...       │
│                            │                                │
└────────────────────────────┴────────────────────────────────┘
      ↑ 실시간 전사 영역              ↑ ChatGPT 요약 영역
```

---

## 문제 해결

### 1. lag(지연)가 계속 증가하는 경우

처리 속도가 입력 속도를 따라가지 못하는 상황입니다.

**해결 방법:**
```bash
# 방법 1: 더 작은 모델 사용
python -m whisperlivekit.basic_server_pibo_design --model small --language ko --diarization

# 방법 2: 화자 분리 비활성화 (GPU 부담 감소)
python -m whisperlivekit.basic_server_pibo_design --model medium --language ko
```

### 2. 서버가 느려지는 경우

GPU 메모리에 이전 상태가 남아있을 수 있습니다.

**해결 방법:**
```bash
# 서버 종료
Ctrl+C

# GPU 메모리 정리 (선택)
python -c "import torch; torch.cuda.empty_cache()"

# 서버 재시작
python -m whisperlivekit.basic_server_pibo_design --model medium --language ko --diarization
```

### 3. 화자가 2명만 인식되는 경우

Sortformer 모델은 기본적으로 최대 4명까지 인식합니다. 실제로 2명만 나오는 것은 정상입니다.

---

## 관련 Git 커밋

| 커밋 | 설명 |
|------|------|
| `aaa0fe6` | 커스텀 디자인 UI 추가 |
| `a238147` | SimulStreaming 코드 롤백 |
| `4967c79` | LocalAgreement 백엔드 버전 추가 |

---

## 원본 프로젝트

- WhisperLiveKit: https://github.com/QuentinFuxa/WhisperLiveKit
