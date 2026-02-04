# 파이보 토론 지원 시스템 - 기술 문서

## 1. 시스템 개요

### 1.1 프로젝트 목적
본 시스템은 **실시간 상호작용형 자율 진화형 토론 중재 에이전트**로, 다음 기능을 제공합니다:
- 실시간 음성-텍스트 변환 (STT)
- 다중 화자 인식 (Speaker Diarization)
- AI 기반 실시간 요약
- 파이보 로봇을 통한 음성 출력 (TTS)
- 웨이크워드 기반 AI 어시스턴트 ("파동아")

### 1.2 시스템 구성도

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              웹 브라우저 (클라이언트)                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │   마이크 입력    │  │  WebSocket 통신  │  │    UI (HTML/CSS/JS)        │  │
│  │  (MediaRecorder │  │                 │  │  - 실시간 대화 표시          │  │
│  │   /AudioWorklet)│  │                 │  │  - 타임스탬프 요약           │  │
│  └────────┬────────┘  └────────┬────────┘  │  - AI 응답 표시             │  │
│           │                    │           └─────────────────────────────┘  │
└───────────┼────────────────────┼────────────────────────────────────────────┘
            │ 오디오 스트림        │ JSON 결과
            ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           메인 서버 (FastAPI + WebSocket)                    │
│                         basic_server_pibo_design.py                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      AudioProcessor (연결별 인스턴스)                  │   │
│  │  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────────┐  │   │
│  │  │ FFmpeg   │──▶│Silero VAD│──▶│전사 큐   │──▶│ Whisper ASR      │  │   │
│  │  │ (디코딩) │   │(음성감지)│   │          │   │ (음성→텍스트)    │  │   │
│  │  └──────────┘   └──────────┘   └──────────┘   └──────────────────┘  │   │
│  │                                     │                                │   │
│  │  ┌──────────────────────────────────┼────────────────────────────┐  │   │
│  │  │                                  ▼                            │  │   │
│  │  │  ┌──────────────────┐   ┌──────────────────┐                  │  │   │
│  │  │  │ Diart 화자 인식  │   │ 번역 (NLLB)      │                  │  │   │
│  │  │  │ (pyannote 기반)  │   │ (선택적)         │                  │  │   │
│  │  │  └──────────────────┘   └──────────────────┘                  │  │   │
│  │  └───────────────────────────────────────────────────────────────┘  │   │
│  │                                     │                                │   │
│  │  ┌──────────────────────────────────┼────────────────────────────┐  │   │
│  │  │           결과 정렬 및 포맷팅 (TokensAlignment)                │  │   │
│  │  └──────────────────────────────────┬────────────────────────────┘  │   │
│  │                                     │                                │   │
│  │  ┌──────────────────────────────────┼────────────────────────────┐  │   │
│  │  │  ┌──────────────────┐   ┌──────────────────┐   ┌────────────┐ │  │   │
│  │  │  │ChatGPT 요약기    │   │타임스탬프 요약기 │   │AI 어시스턴트│ │  │   │
│  │  │  │(전체 요약)       │   │(실시간 세그먼트) │   │(웨이크워드) │ │  │   │
│  │  │  └──────────────────┘   └──────────────────┘   └────────────┘ │  │   │
│  │  └───────────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                     │                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                   TranscriptionEngine (싱글톤, 모델 공유)            │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐ │   │
│  │  │Whisper   │  │Diart     │  │VAC       │  │번역 모델 (NLLB)      │ │   │
│  │  │모델      │  │모델      │  │(ONNX)    │  │                      │ │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
            │
            │ HTTP POST /speak
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        파이보 로봇 (라즈베리파이)                             │
│                          pibo_tts_server.py                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  /speak 엔드포인트                                                   │   │
│  │     │                                                               │   │
│  │     ▼                                                               │   │
│  │  노트북 TTS API 호출 ──▶ 스트리밍 오디오 수신 ──▶ aplay 재생         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 핵심 모듈 상세 설명

### 2.1 STT (Speech-to-Text) - 음성 인식

#### 2.1.1 Whisper ASR
- **위치**: `whisperlivekit/simul_whisper/`, `whisperlivekit/local_agreement/`
- **모델**: OpenAI Whisper (base, small, medium, large-v3)
- **백엔드 옵션**:
  - `SimulStreaming`: 실시간 스트리밍 전사 (낮은 지연)
  - `LocalAgreement`: 안정적인 전사 (높은 정확도)

#### 2.1.2 처리 흐름
```
WebSocket 수신 → FFmpeg 디코딩 → VAD 필터링 → Whisper 전사 → 토큰 출력
     │              │                │              │            │
   WebM/Opus     PCM 16kHz      음성 구간만      텍스트 생성   시간 정렬
```

#### 2.1.3 주요 파라미터
| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `model_size` | base | Whisper 모델 크기 |
| `lan` | auto | 소스 언어 (auto=자동감지) |
| `min_chunk_size` | 0.1 | 최소 청크 크기 (초) |
| `backend_policy` | localagreement | 전사 정책 |

---

### 2.2 화자 인식 (Speaker Diarization)

#### 2.2.1 Diart 백엔드
- **위치**: `whisperlivekit/diarization/diart_backend.py`
- **모델**: pyannote/segmentation-3.0 + pyannote/embedding
- **방식**: 실시간 온라인 클러스터링

#### 2.2.2 핵심 알고리즘
```python
SpeakerDiarizationConfig(
    tau_active=0.6,     # 음성 활동 감지 임계값
    rho_update=0.3,     # 클러스터 업데이트 비율
    delta_new=0.8,      # 새 화자 생성 임계값 (낮을수록 분리 증가)
    max_speakers=5,     # 최대 화자 수
)
```

#### 2.2.3 화자 인식 파이프라인
```
오디오 청크 → WebSocketAudioSource → StreamingInference → DiarizationObserver
                    │                        │                    │
              고정 크기 블록              화자 세그먼트화        결과 저장
              (0.5초 단위)              (실시간 클러스터링)   (SpeakerSegment)
```

#### 2.2.4 화자 통합 문제
실시간 클러스터링의 특성상 초기에 화자가 잘못 분류되었다가 나중에 통합될 수 있습니다:
1. **온라인 클러스터링 한계**: 초기 데이터 부족으로 오판 가능
2. **임베딩 업데이트**: 시간이 지나면서 화자 임베딩이 정교해짐
3. **클러스터 병합**: 유사한 화자가 하나로 통합됨

---

### 2.3 AI 요약 (ChatGPT 기반)

#### 2.3.1 요약 모듈 구조
- **위치**: `whisperlivekit/summary/`
- **API**: OpenAI GPT-4o

#### 2.3.2 두 가지 요약 방식

**1. 전체 요약 (ConversationSummarizer)**
- **시점**: 녹음 종료 시
- **입력**: 전체 전사 세그먼트
- **출력**: 전체 요약 + 화자별 논지

```python
# summarizer.py
async def summarize(segments) -> SummaryResult:
    """
    Returns:
        summary: "전체 대화 요약 (2-3문장)"
        speaker_summaries: {"1": "화자1 논지", "2": "화자2 논지"}
    """
```

**2. 타임스탬프 요약 (TimestampSummarizer)**
- **시점**: 실시간 (세그먼트 완료 시)
- **입력**: 개별 세그먼트 (5초 이상)
- **출력**: 간결한 한 문장 요약

```python
# timestamp_summarizer.py
async def summarize_segment(segment) -> TimestampSegmentSummary:
    """
    Returns:
        timestamp: "00:02 - 00:13"
        speaker: 1
        summary: "국민 발언제 도입 필요성 제기"
    """
```

#### 2.3.3 Hierarchical Summarization
논문 기반 계층적 요약 접근법:
1. **Stage 1**: 세그먼트별 실시간 요약 생성
2. **Stage 2**: 세그먼트 요약들을 재사용하여 전체 요약 생성
3. **효과**: 토큰 사용량 ~70% 절감

---

### 2.4 AI 어시스턴트 ("파동아")

#### 2.4.1 웨이크워드 감지
- **위치**: `whisperlivekit/audio_processor.py` (line 267-274)
- **웨이크워드**: "파동아", "파동 아", "피보야", "피보 야" 등

```python
wake_words = [
    "파동아", "파동 아", "파돈아", "바동아", "파동이", "파동",
    "피보야", "피보 야", "피보아", "삐보야", "피보", "피보이",
]
```

#### 2.4.2 명령 처리 흐름
```
전사 텍스트 → 웨이크워드 감지 → 명령어 추출 → GPT 응답 생성 → 파이보 TTS 전송
```

#### 2.4.3 직접 명령어
웨이크워드 없이도 작동하는 키워드:
- "요약해줘", "요약해 줘"
- "정리해줘", "정리해 줘"
- "지금까지 요약"

---

### 2.5 TTS (Text-to-Speech) - 파이보 연동

#### 2.5.1 시스템 구성
```
메인 서버 (MacBook/노트북)          파이보 (라즈베리파이)
┌───────────────────────┐         ┌───────────────────────┐
│ AI 응답 생성          │         │ pibo_tts_server.py    │
│         │             │ HTTP    │         │             │
│         ▼             │ POST    │         ▼             │
│ _send_to_pibo_tts()  ─┼────────▶│ /speak 엔드포인트     │
│                       │         │         │             │
│                       │         │         ▼             │
│                       │         │ 노트북 TTS API 호출   │
│                       │         │         │             │
│                       │         │         ▼             │
│                       │         │ aplay로 스피커 출력   │
└───────────────────────┘         └───────────────────────┘
```

#### 2.5.2 pibo_tts_server.py 주요 기능
- **POST /speak**: AI 응답 텍스트 수신 및 TTS 재생
- **POST /stop**: 현재 재생 중단
- **GET /health**: 서버 상태 확인

#### 2.5.3 스트리밍 재생
```python
def speak_text(text, stop_event):
    # 1. 노트북 TTS API에서 스트리밍으로 오디오 청크 수신
    # 2. 청크를 큐에 저장
    # 3. 별도 스레드에서 순차적으로 재생 (aplay)
    # 4. 새 요청 시 이전 재생 중단
```

---

## 3. 데이터 흐름 및 구조

### 3.1 핵심 데이터 클래스

```python
# timed_objects.py

@dataclass
class ASRToken(TimedText):
    """전사된 단어/토큰"""
    start: float      # 시작 시간
    end: float        # 종료 시간
    text: str         # 텍스트
    speaker: int      # 화자 ID (-1: 미지정)

@dataclass
class SpeakerSegment(Timed):
    """화자 세그먼트"""
    speaker: int      # 화자 ID
    start: float
    end: float

@dataclass
class Segment(TimedText):
    """최종 출력 세그먼트"""
    text: str
    speaker: int      # -2: 침묵, -1: 미지정, 1+: 화자
    translation: Optional[str]

@dataclass
class FrontData:
    """프론트엔드 전송 데이터"""
    status: str
    lines: List[Segment]
    buffer_transcription: str
    buffer_diarization: str
    timestamp_summaries: List[dict]  # 실시간 요약
    ai_response: Optional[dict]      # AI 어시스턴트 응답
    summary: Optional[dict]          # 전체 요약
```

### 3.2 WebSocket 메시지 형식

**서버 → 클라이언트**:
```json
{
  "status": "active_transcription",
  "lines": [
    {
      "speaker": 1,
      "text": "국민 발언제 도입이 필요합니다",
      "start": "0:00:02",
      "end": "0:00:13",
      "detected_language": "ko"
    }
  ],
  "buffer_transcription": "현재 처리 중인 텍스트...",
  "buffer_diarization": "화자 인식 대기 중...",
  "remaining_time_transcription": 0.5,
  "remaining_time_diarization": 0.2,
  "timestamp_summaries": [
    {
      "timestamp": "00:02 - 00:13",
      "speaker": 1,
      "summary": "국민 발언제 도입 필요성 제기"
    }
  ],
  "ai_response": {
    "command": "요약해줘",
    "response": "현재까지 토론은...",
    "timestamp": 1234567890
  }
}
```

---

## 4. 서버 실행 및 설정

### 4.1 실행 명령어

```bash
# 기본 실행
python -m whisperlivekit.basic_server_pibo_design \
    --model medium \
    --language ko \
    --diarization \
    --enable-summary

# 전체 옵션
python -m whisperlivekit.basic_server_pibo_design \
    --model medium \
    --lan ko \
    --diarization \
    --enable-summary \
    --summary-model gpt-4o \
    --host 0.0.0.0 \
    --port 8000 \
    --vac \
    --backend-policy localagreement
```

### 4.2 주요 CLI 옵션

| 옵션 | 설명 | 기본값 |
|-----|------|--------|
| `--model` | Whisper 모델 크기 | base |
| `--lan` | 소스 언어 | auto |
| `--diarization` | 화자 인식 활성화 | False |
| `--enable-summary` | ChatGPT 요약 활성화 | False |
| `--summary-model` | 요약 모델 | gpt-4o |
| `--host` | 서버 호스트 | localhost |
| `--port` | 서버 포트 | 8000 |
| `--vac` | VAD 컨트롤러 활성화 | True |
| `--backend-policy` | 전사 정책 | simulstreaming |
| `--pcm-input` | PCM 입력 모드 | False |

### 4.3 환경 변수

```bash
# OpenAI API 키 (요약 기능 필수)
export OPENAI_API_KEY="sk-..."

# Hugging Face 토큰 (화자 인식 모델 다운로드)
export HF_TOKEN="hf_..."
```

---

## 5. 프론트엔드 구조

### 5.1 파일 구조
```
whisperlivekit/web_pibo_design/
├── live_transcription.html    # 메인 HTML
├── live_transcription.css     # 스타일시트
├── live_transcription.js      # 클라이언트 로직
├── pcm_worklet.js             # AudioWorklet (PCM 모드)
├── recorder_worker.js         # Web Worker (리샘플링)
└── web_interface.py           # FastAPI 라우팅
```

### 5.2 UI 구성

```
┌─────────────────────────────────────────────────────────────────┐
│ 헤더: 제목 + 녹음 버튼 + 설정                                    │
├─────────────────────────────────┬───────────────────────────────┤
│ Live Transcript                 │ Timestamp Summary             │
│ ┌─────────────────────────────┐ │ ┌───────────────────────────┐ │
│ │ [화자 1] 0:00:02 - 0:00:13  │ │ │ 00:02-00:13 요약 내용     │ │
│ │ 국민 발언제 도입이...       │ │ │                           │ │
│ │                             │ │ │ 00:15-00:25 요약 내용     │ │
│ │ [화자 2] 0:00:15 - 0:00:25  │ │ │                           │ │
│ │ 그러나 현실적으로...        │ │ └───────────────────────────┘ │
│ │                             │ ├───────────────────────────────┤
│ │ 버퍼: 현재 처리 중...       │ │ Full Summary (AI 요약)        │
│ └─────────────────────────────┘ │ ┌───────────────────────────┐ │
│                                 │ │ 화자별 논지 요약 표시      │ │
│                                 │ └───────────────────────────┘ │
└─────────────────────────────────┴───────────────────────────────┘
```

### 5.3 오디오 캡처 모드

**1. MediaRecorder 모드 (기본)**
```
마이크 → MediaRecorder → WebM/Opus → WebSocket → 서버(FFmpeg 디코딩)
```
- 낮은 대역폭
- 브라우저 호환성 높음

**2. AudioWorklet 모드 (--pcm-input)**
```
마이크 → AudioWorklet → PCM Float32 → Worker → PCM Int16 → WebSocket
```
- 낮은 지연시간
- 서버 FFmpeg 불필요

---

## 6. 성능 최적화

### 6.1 싱글톤 패턴 (TranscriptionEngine)
- 모든 WebSocket 연결이 동일한 AI 모델 공유
- 메모리 사용량 최소화
- 스레드 안전 Double-Checked Locking

### 6.2 비동기 처리 파이프라인
- 전사, 화자 인식, 번역이 병렬 비동기 큐로 동작
- CPU 활용 극대화

### 6.3 VAD (Voice Activity Detection)
- Silero VAD로 음성 구간만 처리
- 침묵 구간 스킵으로 계산량 절감

### 6.4 Hierarchical Summarization
- 세그먼트 요약 재사용으로 API 토큰 ~70% 절감

---

## 7. 의존성

### 7.1 Python 패키지
```
# 핵심
fastapi>=0.100.0
uvicorn>=0.23.0
websockets>=11.0
numpy>=1.24.0
torch>=2.0.0

# STT
openai-whisper>=20230918
faster-whisper>=0.10.0  # 선택

# 화자 인식
diart>=0.8.0
pyannote.audio>=3.0.0

# 요약
openai>=1.0.0

# TTS (파이보)
requests>=2.31.0
pydantic>=2.0.0

# 오디오 처리
soundfile>=0.12.0
onnxruntime>=1.16.0  # VAD
```

### 7.2 시스템 의존성
```bash
# FFmpeg (오디오 디코딩)
brew install ffmpeg  # macOS
apt install ffmpeg   # Ubuntu

# 파이보 (라즈베리파이)
apt install alsa-utils  # aplay
```

---

## 8. 참고 논문

1. **Zhang et al. (2021)**: QMSum - Query-based multi-domain meeting summarization
2. **Retkowski & Waibel (2024)**: Smart chaptering for real-time speech transcription
3. **Radford et al. (2023)**: Robust Speech Recognition via Large-Scale Weak Supervision (Whisper)
4. **Plaquet & Bredin (2023)**: Powerset multi-class cross entropy loss for neural speaker diarization

---

## 9. 문제 해결

### 9.1 화자 인식이 불안정함
- `delta_new` 값 조정 (낮추면 화자 분리 증가)
- 현재 설정: `delta_new=0.8`

### 9.2 요약이 생성되지 않음
- `OPENAI_API_KEY` 환경변수 확인
- `--enable-summary` 옵션 확인

### 9.3 파이보 TTS가 작동하지 않음
- 파이보 IP 주소 확인 (`pibo_ip` 설정)
- 파이보에서 `pibo_tts_server.py` 실행 중인지 확인

---

## 10. 향후 개선 방향

1. **다국어 실시간 번역**: NLLB 모델 통합 완성
2. **감정 분석**: 화자별 감정 상태 추적
3. **논쟁 포인트 하이라이트**: 주요 대립 지점 자동 감지
4. **토론 진행 가이드**: AI 중재자 역할 강화
