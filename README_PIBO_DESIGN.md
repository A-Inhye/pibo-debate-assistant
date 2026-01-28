# Pibo Debate Assistant - 커스텀 디자인 버전

실시간 토론 지원 시스템을 위한 WhisperLiveKit 커스텀 UI 버전입니다.

## 실행 방법

```bash
python -m whisperlivekit.basic_server_pibo_design --model medium --language ko --diarization
```

브라우저에서 `http://localhost:8000` 접속

---

## 필요한 파일 구조

```
whisperlivekit/
├── basic_server_pibo_design.py      # 서버 메인 파일 (신규)
├── web_pibo_design/                  # 커스텀 UI 폴더 (신규)
│   ├── __init__.py
│   ├── live_transcription.html       # 커스텀 디자인 HTML
│   ├── live_transcription.css        # 커스텀 스타일
│   ├── live_transcription.js         # 프론트엔드 로직
│   ├── pcm_worklet.js                # AudioWorklet
│   ├── recorder_worker.js            # Web Worker
│   ├── web_interface.py              # HTML 인라인 생성
│   └── src/                          # SVG 아이콘
│       ├── dark_mode.svg
│       ├── light_mode.svg
│       ├── settings.svg
│       ├── speaker.svg
│       └── ...
├── local_agreement/                  # LocalAgreement 백엔드 (기존)
├── simul_whisper/                    # SimulStreaming 백엔드 (기존)
└── ...
```

---

## 수정된 파일 목록

### 1. 신규 생성 파일

| 파일 | 설명 |
|------|------|
| `basic_server_pibo_design.py` | FastAPI 서버, LocalAgreement 백엔드 기본 적용 |
| `web_pibo_design/` | 사용자 제안 디자인 기반 커스텀 UI |

### 2. 수정된 기존 파일

| 파일 | 수정 내용 |
|------|----------|
| `pyproject.toml` | `web_pibo_design` 패키지 등록 |
| `whisperlivekit/whisper/model.py` | positional_embedding offset 범위 초과 방지 |
| `whisperlivekit/simul_whisper/backend.py` | 오류 발생 시 상태 리셋 추가 |

---

## 주요 수정 내용 상세

### pyproject.toml
```toml
[tool.setuptools]
packages = [
    ...
    "whisperlivekit.web_pibo_design",  # 추가
    ...
]

[tool.setuptools.package-data]
whisperlivekit = [
    ...
    "web_pibo_design/*.html", "web_pibo_design/*.css", "web_pibo_design/*.js", "web_pibo_design/src/*.svg"  # 추가
]
```

### basic_server_pibo_design.py (핵심 부분)
```python
from whisperlivekit.web_pibo_design.web_interface import get_inline_ui_html

# LocalAgreement 백엔드 강제 설정
args.backend_policy = "localagreement"
```

### model.py (offset 보정)
```python
# 수정 전
offset = kv_cache[first_self_attn_key].shape[1]

# 수정 후
offset = kv_cache[first_self_attn_key].shape[1]
token_len = x.shape[-1]
max_pos = self.positional_embedding.shape[0]
if offset + token_len > max_pos:
    offset = max(0, max_pos - token_len)
```

### backend.py (오류 복구)
```python
except Exception as e:
    logger.exception(f"SimulStreaming processing error: {e}")
    # 오류 시 상태 리셋 추가
    try:
        self.model.refresh_segment(complete=True)
    except Exception as reset_error:
        logger.warning(f"Failed to reset: {reset_error}")
    return [], self.end
```

---

## 커스텀 UI 특징

### 디자인
- 다크 헤더 (타이틀 + 녹음 버튼 + 상태 표시)
- AI Mediator 배너 (추후 개발 예정)
- 2분할 레이아웃 (Live Transcript | Argument Summary)

### 기능
- 실시간 음성 전사 (STT)
- 화자 분리 (Diarization)
- 파형 시각화 (녹음 중)
- 설정 토글 (WebSocket URL, 마이크 선택)

---

## 백엔드 정책

| 정책 | 설명 | 안정성 |
|------|------|--------|
| `localagreement` | LocalAgreement 알고리즘 (기본) | 안정적 |
| `simulstreaming` | SimulStreaming (AlignAtt) | 텐서 오류 가능 |

이 버전은 **LocalAgreement**를 기본으로 사용합니다.

---

## 의존성

```bash
pip install -e .
```

추가 의존성:
- `faster-whisper` 또는 `whisper`
- `torch`, `torchaudio`
- `fastapi`, `uvicorn`
- Diarization: `nemo_toolkit` (Sortformer)

---

## 관련 커밋

```
aaa0fe6 feat: 커스텀 디자인 UI 추가 (web_pibo_design)
a238147 revert: SimulStreaming 코드 4c31bd4 상태로 롤백
4c31bd4 fix: SimulStreaming 텐서 크기 불일치 오류 방지 및 복구
4967c79 feat: Add LocalAgreement backend version for Pibo project
```

---

## 문제 해결

### lag가 계속 증가하는 경우
```bash
# 모델 크기 줄이기
python -m whisperlivekit.basic_server_pibo_design --model small --language ko --diarization

# 또는 화자 분리 비활성화
python -m whisperlivekit.basic_server_pibo_design --model medium --language ko
```

### 서버 재시작 전 초기화
```bash
pkill -f "whisperlivekit"
python -c "import torch; torch.cuda.empty_cache()"
```
