# WhisperLiveKit 한국어 상세 문서

## 📋 목차
1. [프로젝트 개요](#1-프로젝트-개요)
2. [전체 아키텍처](#2-전체-아키텍처)
3. [파일 구조](#3-파일-구조)
4. [핵심 모듈 설명](#4-핵심-모듈-설명)
5. [데이터 흐름](#5-데이터-흐름)
6. [주요 알고리즘](#6-주요-알고리즘)
7. [설치 및 사용법](#7-설치-및-사용법)
8. [성능 최적화](#8-성능-최적화)
9. [배포 가이드](#9-배포-가이드)

---

## 1. 프로젝트 개요

### 1.1 WhisperLiveKit이란?

**WhisperLiveKit**은 초저지연 실시간 음성-텍스트 변환(STT) 시스템입니다. 화자 식별(Speaker Diarization) 기능과 200개 언어 번역을 지원하는 자체 호스팅 가능한 솔루션입니다.

### 1.2 주요 특징

- ⚡ **초저지연**: 300-800ms 단어 단위 지연시간
- 🎯 **실시간 스트리밍**: 발화와 동시에 텍스트 출력
- 👥 **화자 식별**: 여러 화자를 실시간으로 구분
- 🌍 **다국어 지원**: 99개 언어 인식, 200개 언어 번역
- 🔒 **프라이버시**: 자체 서버 호스팅, 데이터 외부 전송 없음
- 🚀 **다중 백엔드**: PyTorch, Faster-Whisper, MLX, OpenAI API

### 1.3 기술 스택

| 계층 | 기술 |
|------|------|
| **AI 모델** | OpenAI Whisper (음성인식), NLLB (번역), Sortformer/Diart (화자식별) |
| **백엔드** | Python 3.9+, FastAPI, asyncio, WebSocket |
| **추론 엔진** | PyTorch, Faster-Whisper (CTranslate2), MLX-Whisper |
| **오디오 처리** | FFmpeg, librosa, soundfile, Silero VAD |
| **프론트엔드** | HTML5, WebSocket API, AudioWorklet |

### 1.4 프로젝트 통계

```
총 코드 라인: 11,457 LOC (Python)
버전: 0.2.17.post1
라이센스: MIT / Apache 2.0
지원 Python: 3.9 - 3.15
```

---

## 2. 전체 아키텍처

### 2.1 시스템 구성도

```
┌─────────────────────────────────────────────────────────────┐
│                        브라우저 클라이언트                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ MediaRecorder│  │ AudioWorklet │  │  WebSocket   │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
└─────────┼──────────────────┼──────────────────┼─────────────┘
          │ WebM/Opus        │ PCM s16le        │
          └──────────────────┴──────────────────┘
                              │
                    WebSocket 바이너리 스트림
                              │
┌─────────────────────────────▼─────────────────────────────┐
│                    FastAPI WebSocket 서버                   │
│                    (basic_server.py)                        │
└─────────────────────────────┬─────────────────────────────┘
                              │
┌─────────────────────────────▼─────────────────────────────┐
│                   AudioProcessor (핵심 파이프라인)           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ FFmpegManager│→ │  Silero VAD  │→ │  오디오 큐   │    │
│  └──────────────┘  └──────────────┘  └──────┬───────┘    │
└────────────────────────────────────────────────┬──────────┘
                                                 │
                    ┌────────────────────────────┴────────────────┐
                    │                                             │
        ┌───────────▼──────────┐                 ┌───────────────▼────────┐
        │  SimulStreaming ASR  │                 │  LocalAgreement ASR     │
        │  (AlignAtt 정책)     │                 │  (버퍼 기반 정책)        │
        └───────────┬──────────┘                 └───────────────┬────────┘
                    │                                             │
                    └─────────────┬───────────────────────────────┘
                                  │ ASRToken 스트림
                    ┌─────────────▼─────────────┐
                    │    화자 식별 (선택)          │
                    │  • Sortformer (SOTA 2025) │
                    │  • Diart (SOTA 2021)      │
                    └─────────────┬─────────────┘
                                  │ SpeakerSegment 스트림
                    ┌─────────────▼─────────────┐
                    │    번역 (선택)              │
                    │  • NLLW (200개 언어)       │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │   TokensAlignment         │
                    │  (토큰 + 화자 + 번역 병합)  │
                    └─────────────┬─────────────┘
                                  │ Segment 객체
                    ┌─────────────▼─────────────┐
                    │  JSON 응답 (FrontData)     │
                    └─────────────┬─────────────┘
                                  │
                          WebSocket.send_json()
                                  │
                    ┌─────────────▼─────────────┐
                    │   브라우저 UI 업데이트      │
                    └───────────────────────────┘
```

### 2.2 주요 컴포넌트

#### 2.2.1 TranscriptionEngine (코어 엔진)
- **역할**: 모든 AI 모델을 초기화하고 관리하는 싱글톤 클래스
- **패턴**: 스레드 안전 싱글톤 (Double-Checked Locking)
- **관리 대상**: ASR 백엔드, 화자 식별, 번역, VAD

#### 2.2.2 AudioProcessor (오디오 파이프라인)
- **역할**: 실시간 오디오 스트림 처리 및 결과 조합
- **특징**: asyncio 기반 비동기 처리, 여러 큐를 통한 병렬 처리
- **처리 흐름**: FFmpeg 디코딩 → VAD → ASR → 화자식별 → 정렬

#### 2.2.3 SimulStreamingASR (최신 백엔드)
- **역할**: AlignAtt 정책을 사용한 동시 스트리밍 ASR
- **핵심 기술**: Attention Alignment Heads로 단어 경계 예측
- **지연시간**: 300-800ms 단어 단위

#### 2.2.4 LocalAgreement (안정적 백엔드)
- **역할**: 버퍼 기반 가설 매칭으로 안정적 출력
- **핵심 기술**: Hypothesis Buffer와 Longest Common Prefix
- **지연시간**: 1-3초 문장 단위

---

## 3. 파일 구조

### 3.1 전체 디렉토리 구조

```
WhisperLiveKit-main/
├── whisperlivekit/                      # 메인 패키지 (11,457 LOC)
│   ├── __init__.py                      # 패키지 진입점
│   ├── core.py                          # TranscriptionEngine (213 LOC)
│   ├── audio_processor.py               # AudioProcessor (635 LOC)
│   ├── basic_server.py                  # FastAPI 서버 (131 LOC)
│   ├── parse_args.py                    # CLI 인자 파서 (333 LOC)
│   ├── backend_support.py               # 백엔드 감지 (42 LOC)
│   ├── model_paths.py                   # 모델 경로 관리 (203 LOC)
│   ├── thread_safety.py                 # 스레드 안전성 (31 LOC)
│   ├── timed_objects.py                 # 데이터 구조 (229 LOC)
│   ├── tokens_alignment.py              # 토큰 정렬 (220 LOC)
│   ├── warmup.py                        # 모델 워밍업 (51 LOC)
│   ├── ffmpeg_manager.py                # FFmpeg 관리 (198 LOC)
│   ├── silero_vad_iterator.py           # 음성 활동 감지 (326 LOC)
│   │
│   ├── simul_whisper/                   # SimulStreaming 백엔드 (2,152 LOC)
│   │   ├── simul_whisper.py             # AlignAtt 디코더 (720 LOC)
│   │   ├── backend.py                   # ASR 설정 (259 LOC)
│   │   ├── config.py                    # 설정 클래스 (80 LOC)
│   │   ├── decoder_state.py             # 디코더 상태 (197 LOC)
│   │   ├── token_buffer.py              # 토큰 버퍼 (141 LOC)
│   │   ├── beam.py                      # 빔 탐색 (280 LOC)
│   │   ├── eow_detection.py             # 단어 끝 감지 (157 LOC)
│   │   ├── mlx_encoder.py               # MLX 인코더 (156 LOC)
│   │   └── mlx/                         # MLX 변형 (162 LOC)
│   │
│   ├── local_agreement/                 # LocalAgreement 백엔드 (1,025 LOC)
│   │   ├── whisper_online.py            # ASR 팩토리 (92 LOC)
│   │   ├── online_asr.py                # 온라인 프로세서 (377 LOC)
│   │   └── backends.py                  # 백엔드 구현 (556 LOC)
│   │
│   ├── diarization/                     # 화자 식별 (505 LOC)
│   │   ├── diart_backend.py             # Diart 백엔드 (233 LOC)
│   │   └── sortformer_backend.py        # Sortformer 백엔드 (272 LOC)
│   │
│   ├── whisper/                         # Whisper 구현 (7,031 LOC)
│   │   ├── model.py                     # Whisper 모델 (407 LOC)
│   │   ├── audio.py                     # 오디오 전처리 (157 LOC)
│   │   ├── tokenizer.py                 # 토크나이저 (395 LOC)
│   │   ├── decoding.py                  # 디코더 (821 LOC)
│   │   ├── transcribe.py                # 전사 파이프라인 (608 LOC)
│   │   ├── timing.py                    # 타이밍 추출 (145 LOC)
│   │   ├── utils.py                     # 유틸리티 (213 LOC)
│   │   ├── triton_ops.py                # Triton 최적화 (121 LOC)
│   │   └── normalizers/                 # 텍스트 정규화 (534 LOC)
│   │
│   ├── web/                             # 웹 인터페이스 (325 LOC + 프론트엔드)
│   │   ├── web_interface.py             # HTML/CSS/JS 로더
│   │   ├── live_transcription.html      # 웹 UI
│   │   ├── live_transcription.css       # 스타일
│   │   ├── live_transcription.js        # 프론트엔드 로직
│   │   ├── pcm_worklet.js               # AudioWorklet 프로세서
│   │   └── recorder_worker.js           # Web Worker
│   │
│   └── silero_vad_models/               # 사전 훈련된 VAD 모델
│       ├── silero_vad.onnx              # ONNX 모델 (opset 16)
│       └── silero_vad.jit               # JIT 모델
│
├── scripts/                             # 유틸리티 스크립트
│   ├── convert_hf_whisper.py            # HuggingFace 모델 변환
│   ├── determine_alignment_heads.py     # Alignment Head 추출
│   └── sync_extension.py                # Chrome 확장 동기화
│
├── chrome-extension/                    # 브라우저 확장 프로그램
│   ├── background.js
│   ├── sidepanel.js
│   ├── requestPermissions.js
│   └── manifest.json
│
├── docs/                                # 문서
│   ├── API.md
│   ├── technical_integration.md
│   ├── troubleshooting.md
│   └── supported_languages.md
│
├── pyproject.toml                       # 프로젝트 메타데이터
├── README.md                            # 메인 문서
├── Dockerfile                           # GPU 지원 도커
└── Dockerfile.cpu                       # CPU 전용 도커
```

### 3.2 핵심 파일 설명

| 파일 | LOC | 주요 기능 |
|------|-----|-----------|
| `core.py` | 213 | 싱글톤 엔진, 모델 초기화, 팩토리 함수 |
| `audio_processor.py` | 635 | 오디오 파이프라인, 비동기 처리, 결과 조합 |
| `basic_server.py` | 131 | FastAPI 서버, WebSocket 엔드포인트 |
| `simul_whisper/simul_whisper.py` | 720 | AlignAtt 디코더, KV-캐시 관리 |
| `whisper/model.py` | 407 | Whisper 트랜스포머 아키텍처 |
| `whisper/decoding.py` | 821 | 빔 탐색, 그리디 디코딩 |
| `whisper/transcribe.py` | 608 | 전사 파이프라인 |
| `ffmpeg_manager.py` | 198 | FFmpeg 비동기 관리 |
| `tokens_alignment.py` | 220 | 크로스모달 정렬 |

---

## 4. 핵심 모듈 설명

### 4.1 core.py - TranscriptionEngine

#### 4.1.1 싱글톤 패턴 구현

```python
class TranscriptionEngine:
    _instance = None
    _initialized = False
    _lock = threading.Lock()  # 스레드 안전 잠금

    def __new__(cls, *args, **kwargs):
        # Double-Checked Locking 패턴
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
```

**목적**: 여러 WebSocket 연결에서 동일한 모델 인스턴스를 공유하여 메모리 절약

#### 4.1.2 초기화 프로세스

```python
def __init__(self, **kwargs):
    with TranscriptionEngine._lock:
        if TranscriptionEngine._initialized:
            return  # 이미 초기화됨
        TranscriptionEngine._initialized = True

    # 1. 기본 파라미터 설정
    global_params = {
        "host": "localhost",
        "port": 8000,
        "diarization": False,
        "target_language": "",
        "backend_policy": "simulstreaming",
        "backend": "auto",
    }

    # 2. ASR 백엔드 선택
    if backend_policy == "simulstreaming":
        self.asr = SimulStreamingASR(...)
    else:
        self.asr = backend_factory(backend="faster-whisper", ...)

    # 3. 화자 식별 로드 (선택)
    if diarization:
        self.diarization_model = SortformerDiarization() or DiartDiarization()

    # 4. 번역 모델 로드 (선택)
    if target_language:
        self.translation_model = load_model([lan], backend="ctranslate2")
```

#### 4.1.3 팩토리 함수

```python
def online_factory(args, asr):
    """각 연결마다 새로운 온라인 프로세서 생성"""
    if args.backend_policy == "simulstreaming":
        return SimulStreamingOnlineProcessor(asr)
    return OnlineASRProcessor(asr)

def online_diarization_factory(args, diarization_backend):
    """각 연결마다 새로운 화자 식별 인스턴스 생성"""
    if args.diarization_backend == "sortformer":
        return SortformerDiarizationOnline(shared_model=diarization_backend)
    return diarization_backend  # Diart는 공유
```

---

### 4.2 audio_processor.py - AudioProcessor

#### 4.2.1 주요 컴포넌트

```python
class AudioProcessor:
    def __init__(self, **kwargs):
        # 오디오 설정
        self.sample_rate = 16000  # 16kHz
        self.channels = 1  # 모노

        # 비동기 큐
        self.transcription_queue = asyncio.Queue()  # ASR용
        self.diarization_queue = asyncio.Queue()    # 화자 식별용
        self.translation_queue = asyncio.Queue()    # 번역용

        # FFmpeg 관리자 (WebM/Opus → PCM 변환)
        self.ffmpeg_manager = FFmpegManager(
            sample_rate=16000,
            channels=1
        )

        # Silero VAD (음성 활동 감지)
        self.vac = FixedVADIterator(load_jit_vad())

        # 온라인 프로세서 (연결별 인스턴스)
        self.transcription = online_factory(args, models.asr)
        self.diarization = online_diarization_factory(args, models.diarization_model)
        self.translation = online_translation_factory(args, models.translation_model)
```

#### 4.2.2 비동기 작업 생성

```python
async def create_tasks(self):
    """모든 처리 작업을 병렬로 시작"""
    # 1. FFmpeg stdout 읽기
    self.ffmpeg_reader_task = asyncio.create_task(
        self.ffmpeg_stdout_reader()
    )

    # 2. 전사 프로세서
    self.transcription_task = asyncio.create_task(
        self.transcription_processor()
    )

    # 3. 화자 식별 프로세서
    self.diarization_task = asyncio.create_task(
        self.diarization_processor()
    )

    # 4. 번역 프로세서
    self.translation_task = asyncio.create_task(
        self.translation_processor()
    )

    # 5. 결과 포맷터 (제너레이터)
    return self.results_formatter()
```

#### 4.2.3 오디오 처리 흐름

```python
async def process_audio(self, message: bytes):
    """WebSocket에서 받은 오디오 메시지 처리"""
    if not message:
        # 빈 메시지 = 스트림 종료 신호
        await self.transcription_queue.put(SENTINEL)
        return

    if self.is_pcm_input:
        # PCM 모드: 직접 버퍼에 추가
        self.pcm_buffer.extend(message)
        await self.handle_pcm_data()
    else:
        # 압축 모드: FFmpeg로 전송
        await self.ffmpeg_manager.write_data(message)
```

#### 4.2.4 VAD 처리

```python
async def handle_pcm_data(self):
    """PCM 데이터 처리 및 VAD 적용"""
    pcm_array = np.frombuffer(self.pcm_buffer, dtype=np.int16).astype(np.float32) / 32768.0

    # Silero VAD 실행
    res = self.vac(pcm_array)

    if res is not None:
        if "start" in res:
            # 음성 시작 감지
            await self._end_silence()

        if "end" in res:
            # 음성 종료 감지
            pre_silence_chunk = self._slice_before_silence(pcm_array, res["end"])
            await self._enqueue_active_audio(pre_silence_chunk)
            await self._begin_silence()

    # 음성 활동 중이면 큐에 추가
    if not self.current_silence:
        await self._enqueue_active_audio(pcm_array)
```

#### 4.2.5 전사 프로세서

```python
async def transcription_processor(self):
    """ASR 백엔드 호출 및 토큰 생성"""
    while True:
        item = await get_all_from_queue(self.transcription_queue)

        if item is SENTINEL:
            break  # 스트림 종료

        if isinstance(item, Silence):
            # 침묵 처리
            new_tokens, processed_upto = await asyncio.to_thread(
                self.transcription.start_silence
            )
            self.transcription.end_silence(item.duration)

        elif isinstance(item, np.ndarray):
            # 오디오 청크 처리
            stream_time = len(item) / self.sample_rate
            self.transcription.insert_audio_chunk(item, stream_time)

            # ASR 실행 (별도 스레드에서)
            new_tokens, processed_upto = await asyncio.to_thread(
                self.transcription.process_iter
            )

        # 상태 업데이트 (스레드 안전)
        async with self.lock:
            self.state.tokens.extend(new_tokens)
            self.state.buffer_transcription = self.transcription.get_buffer()
            self.state.end_buffer = max(processed_upto, self.state.end_buffer)
            self.state.new_tokens.extend(new_tokens)

        # 번역 큐에 토큰 전달
        if self.translation_queue:
            for token in new_tokens:
                await self.translation_queue.put(token)
```

#### 4.2.6 결과 포맷터

```python
async def results_formatter(self):
    """처리 결과를 프론트엔드 형식으로 변환"""
    while True:
        # TokensAlignment 업데이트
        self.tokens_alignment.update()

        # 정렬된 세그먼트 생성
        lines, buffer_diarization, buffer_translation = self.tokens_alignment.get_lines(
            diarization=self.args.diarization,
            translation=bool(self.translation)
        )

        # 현재 상태 가져오기
        state = await self.get_current_state()

        # JSON 응답 생성
        response = FrontData(
            status="active_transcription",
            lines=lines,  # Segment 리스트
            buffer_transcription=state.buffer_transcription.text,
            buffer_diarization=buffer_diarization,
            buffer_translation=buffer_translation,
            remaining_time_transcription=state.remaining_time_transcription,
            remaining_time_diarization=state.remaining_time_diarization
        )

        # 변경사항이 있을 때만 전송
        if response != self.last_response_content:
            yield response
            self.last_response_content = response

        await asyncio.sleep(0.05)  # 20 FPS
```

---

### 4.3 simul_whisper/simul_whisper.py - AlignAtt

#### 4.3.1 AlignAtt 디코더 개요

**AlignAtt**는 Attention Alignment Heads를 사용하여 단어 경계를 예측하는 동시 스트리밍 디코더입니다.

#### 4.3.2 핵심 메커니즘

```python
class AlignAtt:
    def __init__(self, model, alignment_heads, frame_threshold=25):
        self.model = model  # Whisper 모델
        self.alignment_heads = alignment_heads  # [(layer, head), ...]
        self.frame_threshold = frame_threshold  # 발화 임계값
        self.decoder_state = DecoderState()

    def decode_streaming(self, encoder_output, audio_chunk):
        """스트리밍 디코딩"""
        # 1. 디코더 실행
        logits = self.model.decoder(
            self.decoder_state.tokens,
            encoder_output,
            kv_cache=self.decoder_state.kv_cache
        )

        # 2. Attention Alignment 계산
        alignment_scores = self.compute_alignment(
            encoder_output,
            self.decoder_state.tokens,
            self.alignment_heads
        )

        # 3. 발화 지점 감지
        if self.should_fire(alignment_scores, self.frame_threshold):
            # 다음 토큰 샘플링
            next_token = self.sample_token(logits[-1])

            # 디코더 상태 업데이트
            self.decoder_state.tokens.append(next_token)
            self.decoder_state.kv_cache = self.update_kv_cache()

            # ASRToken 생성
            return self.create_asr_token(next_token, alignment_scores)

        return None  # 아직 발화하지 않음
```

#### 4.3.3 Attention Alignment Heads

```python
def compute_alignment(self, encoder_output, tokens, alignment_heads):
    """
    Cross-Attention 가중치를 사용하여 정렬 계산

    Returns:
        alignment_scores: [num_tokens, num_frames] 형태의 텐서
    """
    all_attentions = []

    for layer_idx, head_idx in alignment_heads:
        # 특정 레이어와 헤드의 attention 가중치 추출
        attention_weights = self.model.decoder.blocks[layer_idx].cross_attn.attn_weights[head_idx]
        # shape: [num_tokens, num_frames]
        all_attentions.append(attention_weights)

    # 평균 attention
    alignment_scores = torch.stack(all_attentions).mean(dim=0)
    return alignment_scores

def should_fire(self, alignment_scores, threshold):
    """
    발화 지점 감지

    Args:
        alignment_scores: [num_tokens, num_frames]
        threshold: 25 (default) - 25% 확률로 발화

    Returns:
        bool: True if should fire
    """
    # 마지막 토큰의 attention 분포
    last_token_attention = alignment_scores[-1]  # [num_frames]

    # 오디오의 마지막 25개 프레임에 대한 attention 합
    num_frames_to_check = threshold  # 25 frames = 0.5초
    attention_on_recent = last_token_attention[-num_frames_to_check:].sum()

    # 임계값 초과 시 발화
    return attention_on_recent > 0.25  # 25% 이상
```

#### 4.3.4 KV-Cache 관리

```python
def update_kv_cache(self):
    """
    KV-Cache를 업데이트하여 메모리 절약

    KV-Cache는 이전 토큰들의 Key/Value 텐서를 저장하여
    다음 토큰 생성 시 재계산을 방지
    """
    new_cache = {}

    for layer_name, (key, value) in self.decoder_state.kv_cache.items():
        # 최대 컨텍스트 길이 유지 (예: 448 토큰)
        if len(self.decoder_state.tokens) > self.max_context_tokens:
            # 오래된 토큰의 KV 제거
            key = key[:, -self.max_context_tokens:]
            value = value[:, -self.max_context_tokens:]

        new_cache[layer_name] = (key, value)

    return new_cache

def clean_cache(self):
    """GPU 메모리 해제"""
    for key in list(self.decoder_state.kv_cache.keys()):
        tensor = self.decoder_state.kv_cache.pop(key, None)
        if tensor is not None:
            del tensor

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
```

---

### 4.4 whisper/model.py - Whisper 아키텍처

#### 4.4.1 Whisper 모델 구조

```python
class Whisper(nn.Module):
    def __init__(self, dims: ModelDimensions):
        super().__init__()

        # 오디오 인코더 (80-dim mel → 1280-dim features)
        self.encoder = AudioEncoder(
            n_mels=dims.n_mels,  # 80
            n_ctx=dims.n_audio_ctx,  # 1500 (30초)
            n_state=dims.n_audio_state,  # 1280
            n_head=dims.n_audio_head,  # 20
            n_layer=dims.n_audio_layer  # 32 (large 모델)
        )

        # 텍스트 디코더 (토큰 → 다음 토큰 예측)
        self.decoder = TextDecoder(
            n_vocab=dims.n_vocab,  # 51865 (다국어)
            n_ctx=dims.n_text_ctx,  # 448
            n_state=dims.n_text_state,  # 1280
            n_head=dims.n_text_head,  # 20
            n_layer=dims.n_text_layer  # 32
        )

    def forward(self, mel, tokens):
        # 인코더: mel-spectrogram → features
        encoder_output = self.encoder(mel)

        # 디코더: tokens + encoder_output → logits
        logits = self.decoder(tokens, encoder_output)

        return logits
```

#### 4.4.2 AudioEncoder

```python
class AudioEncoder(nn.Module):
    def __init__(self, n_mels, n_ctx, n_state, n_head, n_layer):
        super().__init__()

        # Conv1d 레이어 (80-dim → 1280-dim)
        self.conv1 = Conv1d(n_mels, n_state, kernel_size=3, padding=1)
        self.conv2 = Conv1d(n_state, n_state, kernel_size=3, stride=2, padding=1)

        # Positional Embedding
        self.positional_embedding = nn.Parameter(torch.empty(n_ctx, n_state))

        # Transformer 블록 (32개)
        self.blocks = nn.ModuleList([
            ResidualAttentionBlock(n_state, n_head)
            for _ in range(n_layer)
        ])

        self.ln_post = LayerNorm(n_state)

    def forward(self, x):
        # x: [batch, n_mels=80, n_frames=3000]

        # Conv 레이어 통과
        x = F.gelu(self.conv1(x))
        x = F.gelu(self.conv2(x))
        # x: [batch, n_state=1280, n_frames=1500]

        x = x.permute(0, 2, 1)  # [batch, n_frames=1500, n_state=1280]

        # Positional Embedding 추가
        x = (x + self.positional_embedding).to(x.dtype)

        # Transformer 블록 통과
        for block in self.blocks:
            x = block(x)

        x = self.ln_post(x)
        # x: [batch, n_frames=1500, n_state=1280]

        return x
```

#### 4.4.3 TextDecoder

```python
class TextDecoder(nn.Module):
    def __init__(self, n_vocab, n_ctx, n_state, n_head, n_layer):
        super().__init__()

        # Token Embedding
        self.token_embedding = nn.Embedding(n_vocab, n_state)

        # Positional Embedding
        self.positional_embedding = nn.Parameter(torch.empty(n_ctx, n_state))

        # Transformer 블록 (Self-Attention + Cross-Attention)
        self.blocks = nn.ModuleList([
            ResidualAttentionBlock(
                n_state,
                n_head,
                cross_attention=True  # Cross-Attention 활성화
            )
            for _ in range(n_layer)
        ])

        self.ln = LayerNorm(n_state)

    def forward(self, tokens, encoder_output, kv_cache=None):
        # tokens: [batch, seq_len]
        # encoder_output: [batch, n_frames=1500, n_state=1280]

        # Token Embedding
        x = self.token_embedding(tokens)
        # x: [batch, seq_len, n_state=1280]

        # Positional Embedding
        x = x + self.positional_embedding[:tokens.shape[-1]]

        # Transformer 블록 통과
        for i, block in enumerate(self.blocks):
            x = block(
                x,
                xa=encoder_output,  # Cross-Attention의 Key/Value
                kv_cache=kv_cache.get(i) if kv_cache else None
            )

        x = self.ln(x)
        # x: [batch, seq_len, n_state=1280]

        # Output Projection (n_state → n_vocab)
        logits = (x @ torch.transpose(self.token_embedding.weight.to(x.dtype), 0, 1)).float()
        # logits: [batch, seq_len, n_vocab=51865]

        return logits
```

---

### 4.5 ffmpeg_manager.py - FFmpegManager

#### 4.5.1 FFmpeg 상태 관리

```python
class FFmpegState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    RESTARTING = "restarting"
    FAILED = "failed"

class FFmpegManager:
    def __init__(self, sample_rate=16000, channels=1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.state = FFmpegState.STOPPED
        self._state_lock = asyncio.Lock()
```

#### 4.5.2 FFmpeg 프로세스 시작

```python
async def start(self):
    """FFmpeg 서브프로세스 시작"""
    async with self._state_lock:
        if self.state != FFmpegState.STOPPED:
            return False
        self.state = FFmpegState.STARTING

    try:
        # FFmpeg 명령어 구성
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-i", "pipe:0",  # stdin에서 입력
            "-f", "s16le",  # PCM signed 16-bit little-endian
            "-acodec", "pcm_s16le",
            "-ac", str(self.channels),  # 1 (모노)
            "-ar", str(self.sample_rate),  # 16000 Hz
            "pipe:1"  # stdout으로 출력
        ]

        # 비동기 서브프로세스 생성
        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # stderr 로깅 작업 시작
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        async with self._state_lock:
            self.state = FFmpegState.RUNNING

        return True

    except FileNotFoundError:
        # FFmpeg가 설치되지 않음
        async with self._state_lock:
            self.state = FFmpegState.FAILED

        if self.on_error_callback:
            await self.on_error_callback("ffmpeg_not_found")

        return False
```

#### 4.5.3 데이터 읽기/쓰기

```python
async def write_data(self, data: bytes):
    """FFmpeg stdin으로 오디오 데이터 쓰기"""
    async with self._state_lock:
        if self.state != FFmpegState.RUNNING:
            return False

    try:
        self.process.stdin.write(data)
        await self.process.stdin.drain()
        return True
    except Exception as e:
        logger.error(f"FFmpeg 쓰기 오류: {e}")
        return False

async def read_data(self, size: int):
    """FFmpeg stdout에서 PCM 데이터 읽기"""
    async with self._state_lock:
        if self.state != FFmpegState.RUNNING:
            return None

    try:
        data = await asyncio.wait_for(
            self.process.stdout.read(size),
            timeout=20.0
        )
        return data
    except asyncio.TimeoutError:
        logger.warning("FFmpeg 읽기 타임아웃")
        return None
```

---

## 5. 데이터 흐름

### 5.1 전체 데이터 흐름도

```
[브라우저 오디오 캡처]
        │
        ├─ MediaRecorder → WebM/Opus (압축)
        └─ AudioWorklet → PCM s16le (비압축)
        │
        ↓ WebSocket Binary
        │
[AudioProcessor.process_audio()]
        │
        ├─ is_pcm_input == True
        │  └→ self.pcm_buffer.extend(message)
        │
        └─ is_pcm_input == False
           └→ FFmpegManager.write_data(message)
              └→ FFmpeg: WebM/Opus → PCM s16le
                 └→ FFmpegManager.read_data()
        │
        ↓ PCM 배열 (np.float32)
        │
[handle_pcm_data()]
        │
        ├─ Silero VAD 실행
        │  ├─ confidence > 0.5 → 음성
        │  └─ confidence < 0.35 → 침묵
        │
        └─ 음성 활동 시
           └→ transcription_queue.put(pcm_chunk)
        │
        ↓
[transcription_processor()]
        │
        ├─ SimulStreaming 백엔드
        │  │
        │  ├─ 1. Encoder (Faster-Whisper/MLX)
        │  │    PCM → Mel-Spectrogram → Features
        │  │    [80, 3000] → [1280, 1500]
        │  │
        │  ├─ 2. AlignAtt Decoder
        │  │    ├─ Decoder State (tokens, kv_cache)
        │  │    ├─ Forward pass
        │  │    ├─ Attention Alignment 계산
        │  │    ├─ should_fire() 체크
        │  │    └─ Token 생성 (Beam/Greedy)
        │  │
        │  └─ 3. ASRToken 출력
        │       ASRToken(start=1.2, end=1.5, text="hello")
        │
        └─ LocalAgreement 백엔드
           │
           ├─ 1. Whisper ASR 실행
           │    PCM → Mel → Encoder → Decoder → Tokens
           │
           ├─ 2. Hypothesis Buffer
           │    ├─ 새로운 가설 삽입
           │    ├─ 이전 가설과 비교
           │    └─ Longest Common Prefix 확인
           │
           └─ 3. ASRToken 출력 (확정된 것만)
        │
        ↓ ASRToken 스트림
        │
[state.tokens 업데이트]
        │
        └→ translation_queue.put(token)  (번역 활성화 시)
        │
        ↓
[diarization_processor()] (선택)
        │
        ├─ SortformerDiarization
        │  ├─ Mel 추출 (10 프레임 청크)
        │  ├─ Model Forward (speaker embeddings)
        │  ├─ Speaker Clustering (온라인)
        │  └─ SpeakerSegment 출력
        │
        └─ DiartDiarization
           ├─ RxPy Observable
           ├─ Segmentation + Embedding
           └─ SpeakerSegment 출력
        │
        ↓ SpeakerSegment 스트림
        │
[state.new_diarization 업데이트]
        │
        ↓
[translation_processor()] (선택)
        │
        ├─ NLLW 모델 로드
        ├─ Source Language: 감지된 언어
        ├─ Target Language: 설정된 언어
        └─ Translation 출력
        │
        ↓ Translation 스트림
        │
[TokensAlignment.update()]
        │
        ├─ state.new_tokens → all_tokens
        ├─ state.new_diarization → all_diarization_segments
        └─ state.new_translation → all_translation_segments
        │
        ↓
[TokensAlignment.get_lines()]
        │
        ├─ 1. Punctuation 기반 세그먼트 생성
        │    "Hello world." → Segment
        │
        ├─ 2. Speaker 매핑
        │    for token in segment:
        │        find_overlapping_speaker_segment()
        │        token.speaker = segment.speaker
        │
        ├─ 3. Translation 병합
        │    for translation in translations:
        │        if translation.is_within(segment):
        │            segment.translation += translation.text
        │
        └─ 4. Segment 리스트 반환
           Segment(start, end, text, speaker, translation)
        │
        ↓
[results_formatter()]
        │
        ├─ FrontData 생성
        │    {
        │      status: "active_transcription",
        │      lines: [Segment, ...],
        │      buffer_transcription: "ongoing...",
        │      buffer_diarization: "Speaker 1...",
        │      buffer_translation: "번역 중...",
        │    }
        │
        └─ JSON 변환
           FrontData.to_dict()
        │
        ↓ JSON 응답
        │
[WebSocket.send_json()]
        │
        ↓
[브라우저 UI 업데이트]
        │
        └─ live_transcription.js
           ├─ onMessage(json)
           ├─ updateTranscript(lines)
           └─ renderSegments(lines)
```

### 5.2 타이밍 정보 흐름

```
[Audio Timeline]
0.0s ──────── 1.0s ──────── 2.0s ──────── 3.0s ──────── 4.0s
  │            │            │            │            │
  │ PCM Chunk  │ PCM Chunk  │ PCM Chunk  │ PCM Chunk  │
  │ [0-1s]     │ [1-2s]     │ [2-3s]     │ [3-4s]     │
  │            │            │            │            │
  ▼            ▼            ▼            ▼            ▼
[ASR Processing]
  │            │            │            │            │
  │ Token 1    │ Token 2    │ Token 3    │ Token 4    │
  │ "Hello"    │ "world"    │ "how"      │ "are"      │
  │ [0.2-0.7s] │ [0.8-1.3s] │ [2.1-2.5s] │ [2.6-3.1s] │
  │            │            │            │            │

[Diarization Processing]
  │                                                    │
  │ Speaker Segment 1          Speaker Segment 2      │
  │ Speaker 0 [0.0-2.0s]       Speaker 1 [2.0-4.0s]   │
  │                                                    │

[Alignment]
  │                                                    │
  │ Segment 1                  Segment 2              │
  │ "Hello world"              "how are"              │
  │ Speaker 0 [0.2-1.3s]       Speaker 1 [2.1-3.1s]   │
  │                                                    │

[Output Timeline]
  │
  ├─ t=0.7s: {"text": "Hello", "speaker": 0, "is_final": false}
  ├─ t=1.3s: {"text": "Hello world", "speaker": 0, "is_final": true}
  ├─ t=2.5s: {"text": "how", "speaker": 1, "is_final": false}
  └─ t=3.1s: {"text": "how are", "speaker": 1, "is_final": true}
```

---

## 6. 주요 알고리즘

### 6.1 AlignAtt (Attention Alignment)

#### 6.1.1 알고리즘 개요

**목표**: Cross-Attention 가중치를 분석하여 단어 경계를 실시간으로 예측

**원리**:
- Encoder-Decoder 아키텍처에서 Decoder는 Encoder 출력에 대해 Cross-Attention 수행
- Attention 가중치가 현재 단어에서 다음 단어로 "이동"하는 시점 감지
- 이동 시점 = 단어 경계 = 발화(Fire) 지점

#### 6.1.2 수식

```
1. Cross-Attention 계산:
   Attention(Q, K, V) = softmax(QK^T / √d_k) V

   여기서:
   - Q: Decoder의 Query (현재 토큰)
   - K, V: Encoder의 Key, Value (오디오 프레임)
   - Attention 가중치: α = softmax(QK^T / √d_k)
     shape: [num_tokens, num_frames]

2. Alignment Score 계산:
   alignment_heads = [(layer_i, head_j), ...]  # 사전 추출된 헤드

   α_avg = mean([α[layer_i, head_j] for (layer_i, head_j) in alignment_heads])

3. Fire 조건:
   last_token_attention = α_avg[-1]  # 마지막 토큰의 attention

   recent_attention = sum(last_token_attention[-threshold:])

   if recent_attention > fire_threshold:
       fire = True  # 단어 완성, 다음 토큰 생성
```

#### 6.1.3 예제

```
오디오: "Hello world"
Frames: [f0, f1, f2, ..., f99]  (100 프레임 = 2초)

Token 1: "<SOT>"
  Attention: [0.01, 0.01, ..., 0.01]  # 균등 분포

Token 2: "Hello"
  Decoding Step 1:
    Attention: [0.8, 0.2, ..., 0.0]  # f0-f10에 집중
    recent_attention (last 25 frames) = 0.05
    → fire = False (계속 대기)

  Decoding Step 2 (0.1초 후):
    Attention: [0.6, 0.4, ..., 0.0]  # f10-f20에 집중
    recent_attention = 0.1
    → fire = False

  Decoding Step 3 (0.2초 후):
    Attention: [0.2, 0.3, 0.5, ..., 0.0]  # f20-f30으로 이동
    recent_attention = 0.3
    → fire = True ✓

    → Output: ASRToken("Hello", start=0.0, end=0.6)

Token 3: "world"
  (반복...)
```

---

### 6.2 LocalAgreement (Hypothesis Buffer)

#### 6.2.1 알고리즘 개요

**목표**: 여러 가설을 비교하여 안정적인(확정된) 토큰만 출력

**원리**:
- 각 오디오 청크마다 독립적으로 ASR 실행 → 가설 생성
- 이전 가설과 현재 가설의 Longest Common Prefix (LCP) 찾기
- LCP = 확정된 텍스트 → 출력
- 나머지 = 불확실 → 다음 청크에서 재검증

#### 6.2.2 의사 코드

```python
class HypothesisBuffer:
    def __init__(self):
        self.committed_tokens = []  # 확정된 토큰
        self.buffer_tokens = []     # 대기 중인 토큰

    def insert(self, new_hypothesis, offset):
        """
        새로운 가설 삽입

        Args:
            new_hypothesis: ["Hello", "world", "how"]
            offset: 오디오 시작 시간
        """
        # 1. 이전 버퍼와 새 가설 비교
        lcp_len = self.find_longest_common_prefix(
            self.buffer_tokens,
            new_hypothesis
        )

        # 2. LCP 부분을 확정
        for i in range(lcp_len):
            if i < len(self.buffer_tokens):
                self.committed_tokens.append(self.buffer_tokens[i])

        # 3. 나머지를 새 버퍼로 설정
        self.buffer_tokens = new_hypothesis[lcp_len:]

    def find_longest_common_prefix(self, tokens1, tokens2):
        """
        두 토큰 리스트의 LCP 길이 반환

        Example:
            tokens1 = ["Hello", "world", "how"]
            tokens2 = ["Hello", "world", "are"]
            → LCP = 2 (["Hello", "world"])
        """
        lcp_len = 0
        for t1, t2 in zip(tokens1, tokens2):
            if t1 == t2:
                lcp_len += 1
            else:
                break
        return lcp_len

    def flush(self):
        """확정된 토큰 반환"""
        result = self.committed_tokens.copy()
        self.committed_tokens.clear()
        return result
```

#### 6.2.3 예제

```
Chunk 1 (0-1초):
  ASR → ["Hello"]
  Buffer: ["Hello"]
  Committed: []
  Output: []

Chunk 2 (0-2초):
  ASR → ["Hello", "world"]
  LCP(["Hello"], ["Hello", "world"]) = 1
  Committed: ["Hello"]
  Buffer: ["world"]
  Output: ["Hello"]

Chunk 3 (0-3초):
  ASR → ["Hello", "world", "how"]
  LCP(["world"], ["world", "how"]) = 1
  Committed: ["world"]
  Buffer: ["how"]
  Output: ["world"]

Chunk 4 (0-4초):
  ASR → ["Hello", "world", "how", "are"]
  LCP(["how"], ["how", "are"]) = 1
  Committed: ["how"]
  Buffer: ["are"]
  Output: ["how"]

Chunk 5 (0-5초):
  ASR → ["Hello", "world", "how", "are", "you"]
  LCP(["are"], ["are", "you"]) = 1
  Committed: ["are"]
  Buffer: ["you"]
  Output: ["are"]
```

---

### 6.3 CIF (Continuous Integrate-and-Fire)

#### 6.3.1 알고리즘 개요

**목표**: Encoder 출력에서 직접 단어 경계를 예측 (Alignment Heads 불필요)

**원리**:
- Encoder 각 프레임에 "발화 확률" 부여
- 확률의 누적 합이 정수를 넘을 때 = 단어 경계

#### 6.3.2 수식

```
1. CIF 레이어:
   h_t = Encoder(audio)[t]  # t번째 프레임의 hidden state

   α_t = sigmoid(W_cif @ h_t + b_cif)  # 발화 확률 [0, 1]

2. 누적 합:
   C_t = Σ α_i  (i=0 to t)

3. Fire 조건:
   if floor(C_t) > floor(C_{t-1}):
       fire = True
       emit_word()
```

#### 6.3.3 예제

```
프레임:  f0    f1    f2    f3    f4    f5    f6
α:      0.1   0.2   0.7   0.3   0.4   0.6   0.2
C:      0.1   0.3   1.0   1.3   1.7   2.3   2.5
                     ↑              ↑
                   Fire 1        Fire 2

Output:
  - t=2: 단어 1 완성 ("Hello")
  - t=5: 단어 2 완성 ("world")
```

---

### 6.4 Beam Search

#### 6.4.1 알고리즘 개요

**목표**: 여러 가능한 토큰 시퀀스를 동시에 탐색하여 최적 경로 찾기

**원리**:
- 각 단계에서 상위 K개의 가설(Beam) 유지
- 각 가설에서 다음 토큰 생성
- K × V개의 후보 중 상위 K개 선택 (V = vocab size)

#### 6.4.2 의사 코드

```python
def beam_search(model, encoder_output, beam_size=5, max_length=448):
    # 초기 가설: [<SOT>]
    beams = [Beam(tokens=[SOT_TOKEN], score=0.0)]

    for step in range(max_length):
        all_candidates = []

        for beam in beams:
            # 디코더 실행
            logits = model.decoder(beam.tokens, encoder_output)
            log_probs = F.log_softmax(logits[-1], dim=-1)

            # 상위 K개 토큰 선택
            top_k_probs, top_k_tokens = torch.topk(log_probs, beam_size)

            for prob, token in zip(top_k_probs, top_k_tokens):
                new_beam = Beam(
                    tokens=beam.tokens + [token],
                    score=beam.score + prob
                )
                all_candidates.append(new_beam)

        # 상위 K개 beam 선택
        all_candidates.sort(key=lambda b: b.score / len(b.tokens), reverse=True)
        beams = all_candidates[:beam_size]

        # 종료 조건
        if all(beam.tokens[-1] == EOT_TOKEN for beam in beams):
            break

    # 최고 점수 beam 반환
    return beams[0]
```

#### 6.4.3 예제

```
Beam Size = 3

Step 0:
  Beam 1: [<SOT>], score=0

Step 1:
  Beam 1 → ["Hello"] (score=-0.5)
  Beam 1 → ["Hi"] (score=-0.8)
  Beam 1 → ["Hey"] (score=-1.2)

  Selected: [["Hello"], ["Hi"], ["Hey"]]

Step 2:
  ["Hello"] → ["Hello", "world"] (score=-1.0)
  ["Hello"] → ["Hello", "there"] (score=-1.3)
  ["Hi"] → ["Hi", "there"] (score=-1.5)
  ["Hi"] → ["Hi", "everyone"] (score=-1.8)
  ["Hey"] → ["Hey", "there"] (score=-2.0)

  Selected: [
    ["Hello", "world"],
    ["Hello", "there"],
    ["Hi", "there"]
  ]

... (반복)

Final:
  Best Beam: ["Hello", "world", "how", "are", "you"]
```

---

## 7. 설치 및 사용법

### 7.1 시스템 요구사항

#### 7.1.1 하드웨어

| 컴포넌트 | 최소 사양 | 권장 사양 |
|---------|----------|----------|
| **CPU** | 2 코어 | 4+ 코어 |
| **RAM** | 4GB | 8GB+ |
| **GPU** | 없음 (CPU 모드) | NVIDIA GPU (4GB+ VRAM) |
| **디스크** | 2GB | 10GB+ (여러 모델) |

#### 7.1.2 소프트웨어

- **Python**: 3.9 - 3.15
- **OS**: Windows, macOS, Linux
- **FFmpeg**: 최신 버전 (선택, `--pcm-input` 사용 시 불필요)

### 7.2 설치

#### 7.2.1 기본 설치

```bash
# PyPI에서 설치
pip install whisperlivekit

# 또는 최신 버전 (GitHub)
git clone https://github.com/QuentinFuxa/WhisperLiveKit.git
cd WhisperLiveKit
pip install -e .
```

#### 7.2.2 선택적 의존성

```bash
# Faster-Whisper (Windows/Linux 최적화)
pip install faster-whisper

# MLX-Whisper (Apple Silicon 최적화)
pip install mlx-whisper

# 번역 (200개 언어)
pip install nllw

# 화자 식별 (Sortformer)
pip install git+https://github.com/NVIDIA/NeMo.git@main#egg=nemo_toolkit[asr]

# 화자 식별 (Diart, 비권장)
pip install diart
```

### 7.3 기본 사용법

#### 7.3.1 빠른 시작

```bash
# 1. 서버 시작 (base 모델, 영어)
wlk --model base --language en

# 2. 브라우저에서 http://localhost:8000 접속

# 3. 마이크 권한 허용 → 말하기 시작
```

#### 7.3.2 고급 사용법

```bash
# Large 모델 + 프랑스어 → 덴마크어 번역
wlk --model large-v3 --language fr --target-language da

# 화자 식별 활성화
wlk --model medium --diarization --language en

# 외부 접속 허용 (80 포트)
wlk --host 0.0.0.0 --port 80 --model small

# HTTPS 활성화
wlk --ssl-certfile cert.pem --ssl-keyfile key.pem

# PCM 모드 (FFmpeg 불필요)
wlk --pcm-input --model base

# Apple Silicon 최적화
wlk --backend mlx-whisper --model medium --language en
```

### 7.4 Python API 사용

```python
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from whisperlivekit import AudioProcessor, TranscriptionEngine

# 전역 엔진 (싱글톤)
transcription_engine = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine
    # 엔진 초기화 (서버 시작 시 1회)
    transcription_engine = TranscriptionEngine(
        model_size="medium",
        diarization=True,
        lan="en"
    )
    yield

app = FastAPI(lifespan=lifespan)

async def handle_websocket_results(websocket, results_generator):
    """결과 스트림 처리"""
    async for response in results_generator:
        await websocket.send_json(response.to_dict())
    await websocket.send_json({"type": "ready_to_stop"})

@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    global transcription_engine

    # 연결별 AudioProcessor 생성
    audio_processor = AudioProcessor(
        transcription_engine=transcription_engine
    )

    # 작업 시작
    results_generator = await audio_processor.create_tasks()
    results_task = asyncio.create_task(
        handle_websocket_results(websocket, results_generator)
    )

    await websocket.accept()

    try:
        while True:
            message = await websocket.receive_bytes()
            await audio_processor.process_audio(message)
    except Exception as e:
        print(f"오류: {e}")
    finally:
        await audio_processor.cleanup()
```

---

## 8. 성능 최적화

### 8.1 지연시간 최적화

#### 8.1.1 백엔드 선택

| 백엔드 | 지연시간 | 정확도 | 권장 환경 |
|--------|---------|-------|----------|
| **MLX-Whisper** | 50-150ms | 높음 | Apple Silicon (M1/M2/M3) |
| **Faster-Whisper** | 100-300ms | 높음 | NVIDIA GPU, CPU |
| **PyTorch** | 300-800ms | 최고 | NVIDIA GPU |
| **OpenAI API** | 1000-3000ms | 최고 | 클라우드 |

#### 8.1.2 정책 선택

```bash
# 최저 지연시간 (300-800ms)
wlk --backend-policy simulstreaming --frame-threshold 15

# 균형 (1-2초)
wlk --backend-policy simulstreaming --frame-threshold 25

# 최고 정확도 (2-3초)
wlk --backend-policy localagreement --buffer-trimming sentence
```

#### 8.1.3 모델 크기 선택

| 모델 | 파라미터 | 메모리 | 추론 속도 | 정확도 |
|------|---------|-------|-----------|--------|
| **tiny** | 39M | 400MB | 32x | 낮음 |
| **base** | 74M | 600MB | 16x | 중간 |
| **small** | 244M | 1.5GB | 6x | 높음 |
| **medium** | 769M | 3GB | 2x | 매우 높음 |
| **large-v3** | 1550M | 6GB | 1x | 최고 |

**권장**:
- 실시간: `base` 또는 `small`
- 오프라인 전사: `large-v3`

### 8.2 메모리 최적화

#### 8.2.1 KV-Cache 정리

```python
# core.py 또는 audio_processor.py 수정
class AudioProcessor:
    async def cleanup(self):
        # 명시적 캐시 정리
        if hasattr(self.transcription, 'decoder_state'):
            self.transcription.decoder_state.clean_cache()

        # GPU 메모리 해제
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
```

#### 8.2.2 모델 양자화

```bash
# Faster-Whisper는 자동으로 INT8 양자화 사용
wlk --backend faster-whisper --model large-v3
# → 6GB VRAM → 2GB VRAM
```

### 8.3 다중 사용자 최적화

#### 8.3.1 모델 잠금 비활성화 (단일 사용자)

```bash
# 환경 변수 설정
export WHISPERLIVEKIT_MODEL_LOCK=0

# 서버 시작
wlk --model base
```

#### 8.3.2 모델 잠금 활성화 (다중 사용자)

```bash
export WHISPERLIVEKIT_MODEL_LOCK=1
export WHISPERLIVEKIT_LOCK_TIMEOUT=30  # 30초

# Gunicorn으로 다중 워커
gunicorn -k uvicorn.workers.UvicornWorker -w 4 \
  whisperlivekit.basic_server:app
```

---

## 9. 배포 가이드

### 9.1 Docker 배포

#### 9.1.1 GPU 지원

```bash
# 1. 이미지 빌드
docker build -t wlk .

# 2. 컨테이너 실행
docker run --gpus all -p 8000:8000 --name wlk wlk

# 3. 커스텀 설정
docker run --gpus all -p 8000:8000 wlk \
  --model large-v3 \
  --language fr \
  --diarization
```

#### 9.1.2 CPU 전용

```bash
# 1. CPU Dockerfile 사용
docker build -f Dockerfile.cpu -t wlk-cpu .

# 2. 실행
docker run -p 8000:8000 wlk-cpu --model base
```

### 9.2 Nginx 리버스 프록시

```nginx
# /etc/nginx/sites-available/whisperlivekit
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 9.3 HTTPS 설정

#### 9.3.1 Let's Encrypt

```bash
# 1. Certbot 설치
sudo apt install certbot python3-certbot-nginx

# 2. 인증서 발급
sudo certbot --nginx -d your-domain.com

# 3. WhisperLiveKit에 SSL 전달
wlk --ssl-certfile /etc/letsencrypt/live/your-domain.com/fullchain.pem \
    --ssl-keyfile /etc/letsencrypt/live/your-domain.com/privkey.pem
```

#### 9.3.2 자체 서명 인증서

```bash
# 1. 인증서 생성
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

# 2. 서버 시작
wlk --ssl-certfile cert.pem --ssl-keyfile key.pem
```

### 9.4 프로덕션 배포 체크리스트

- [ ] FFmpeg 설치 확인 (`ffmpeg -version`)
- [ ] GPU 드라이버 설치 (CUDA, cuDNN)
- [ ] 방화벽 포트 개방 (8000 또는 커스텀)
- [ ] 환경 변수 설정 (WHISPERLIVEKIT_MODEL_LOCK)
- [ ] 로그 디렉토리 생성 (`/var/log/whisperlivekit/`)
- [ ] Systemd 서비스 등록
- [ ] 모니터링 설정 (Prometheus, Grafana)
- [ ] 백업 전략 수립

---

## 10. 문제 해결

### 10.1 일반적인 오류

#### 10.1.1 FFmpeg 관련

**오류**: `FFmpeg is not installed`

**해결**:
```bash
# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Windows
# https://ffmpeg.org/download.html에서 다운로드
# PATH에 bin 폴더 추가

# 또는 PCM 모드 사용
wlk --pcm-input
```

#### 10.1.2 GPU 메모리 부족

**오류**: `CUDA out of memory`

**해결**:
```bash
# 1. 더 작은 모델 사용
wlk --model small  # large-v3 대신

# 2. Fast Encoder 비활성화
wlk --disable-fast-encoder

# 3. Batch Size 감소 (코드 수정 필요)

# 4. Faster-Whisper 사용 (양자화)
wlk --backend faster-whisper --model large-v3
```

#### 10.1.3 모델 다운로드 실패

**오류**: `Failed to download model`

**해결**:
```bash
# 1. HuggingFace 토큰 설정 (게이트된 모델)
huggingface-cli login

# 2. 수동 다운로드
python scripts/convert_hf_whisper.py \
  --repo openai/whisper-large-v3 \
  --output ./models/large-v3

# 3. 로컬 모델 사용
wlk --model-path ./models/large-v3
```

### 10.2 성능 문제

#### 10.2.1 높은 지연시간

**증상**: 3초 이상 지연

**해결**:
```bash
# 1. 백엔드 변경
wlk --backend mlx-whisper  # Apple Silicon
wlk --backend faster-whisper  # Others

# 2. 정책 변경
wlk --backend-policy simulstreaming

# 3. Frame Threshold 낮추기
wlk --frame-threshold 15

# 4. 작은 모델 사용
wlk --model small
```

#### 10.2.2 낮은 정확도

**증상**: 잘못된 전사

**해결**:
```bash
# 1. 큰 모델 사용
wlk --model large-v3

# 2. 언어 명시
wlk --language en  # auto 대신

# 3. Frame Threshold 높이기
wlk --frame-threshold 35

# 4. 초기 프롬프트 사용
wlk --init-prompt "Technical discussion about AI"
```

---

## 11. 개발자 가이드

### 11.1 프로젝트 구조 이해

#### 11.1.1 레이어 아키텍처

```
┌─────────────────────────────────────────┐
│         Presentation Layer              │
│  (basic_server.py, web_interface.py)    │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│         Application Layer               │
│  (audio_processor.py, tokens_alignment) │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│           Domain Layer                  │
│  (core.py, simul_whisper, whisper)      │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│       Infrastructure Layer              │
│  (ffmpeg_manager, silero_vad_iterator)  │
└─────────────────────────────────────────┘
```

### 11.2 커스텀 백엔드 추가

#### 11.2.1 새 ASR 백엔드 구현

```python
# whisperlivekit/local_agreement/backends.py

class CustomASR:
    def __init__(self, model_size="base", lan="en"):
        # 모델 로드
        self.model = load_custom_model(model_size)
        self.language = lan

    def transcribe(self, audio, prompt=None):
        """
        오디오 전사

        Args:
            audio: numpy array [samples]
            prompt: 선택적 초기 프롬프트

        Returns:
            result: {'text': str, 'segments': [...]}
        """
        # 전사 로직 구현
        result = self.model(audio, language=self.language)
        return result

    def ts_words(self, segments, start_time):
        """
        타임스탬프가 있는 단어 추출

        Args:
            segments: transcribe() 반환값
            start_time: 오디오 시작 시간

        Returns:
            words: [ASRToken, ...]
        """
        words = []
        for segment in segments:
            for word in segment['words']:
                token = ASRToken(
                    start=start_time + word['start'],
                    end=start_time + word['end'],
                    text=word['word']
                )
                words.append(token)
        return words

# whisperlivekit/local_agreement/whisper_online.py

def backend_factory(backend="auto", **kwargs):
    if backend == "custom":
        return CustomASR(**kwargs)
    # 기존 백엔드...
```

### 11.3 테스트

```bash
# 단위 테스트 (예정)
pytest tests/

# 통합 테스트
python -m whisperlivekit.basic_server &
curl -X POST http://localhost:8000/asr \
  -H "Content-Type: audio/wav" \
  --data-binary @test.wav
```

---

## 12. FAQ

### Q1. WhisperLiveKit과 OpenAI Whisper API의 차이점은?

**A**:
- **WhisperLiveKit**: 자체 호스팅, 실시간 스트리밍, 무료, 프라이버시 보호
- **OpenAI API**: 클라우드, 배치 처리, 유료, 외부 전송

### Q2. 지원되는 언어는?

**A**: 99개 언어 인식, 200개 언어 번역 지원. [전체 목록](docs/supported_languages.md)

### Q3. 모델을 어떻게 교체하나요?

**A**:
```bash
# HuggingFace에서 자동 다운로드
wlk --model large-v3

# 로컬 경로
wlk --model-path /path/to/model

# HuggingFace 저장소
wlk --model-path openai/whisper-large-v3-turbo
```

### Q4. 화자 식별 정확도를 높이려면?

**A**:
```bash
# Sortformer 사용 (SOTA 2025)
wlk --diarization --diarization-backend sortformer

# 더 나은 세그먼트 모델 (Diart)
wlk --diarization --diarization-backend diart \
  --segmentation-model pyannote/segmentation-3.0
```

### Q5. 상용 프로젝트에 사용할 수 있나요?

**A**: 네, MIT/Apache 2.0 라이센스로 상업적 사용 가능합니다.

---

## 13. 기여 및 라이센스

### 13.1 기여 방법

1. Fork 저장소
2. 새 브랜치 생성 (`git checkout -b feature/amazing-feature`)
3. 변경사항 커밋 (`git commit -m 'Add amazing feature'`)
4. 브랜치 푸시 (`git push origin feature/amazing-feature`)
5. Pull Request 생성

### 13.2 라이센스

- **코드**: MIT / Apache 2.0
- **모델**: OpenAI Whisper - MIT
- **문서**: CC BY 4.0

---

## 14. 참고 자료

### 14.1 공식 문서

- [GitHub 저장소](https://github.com/QuentinFuxa/WhisperLiveKit)
- [API 문서](docs/API.md)
- [기술 통합 가이드](docs/technical_integration.md)

### 14.2 관련 논문

- [SimulWhisper](https://arxiv.org/pdf/2406.10052)
- [SimulStreaming](https://arxiv.org/abs/2506.17077)
- [AlignAtt](https://arxiv.org/pdf/2305.11408)
- [NLLB](https://arxiv.org/abs/2207.04672)
- [Streaming Sortformer](https://arxiv.org/abs/2507.18446)

### 14.3 커뮤니티

- [GitHub Issues](https://github.com/QuentinFuxa/WhisperLiveKit/issues)
- [Discussions](https://github.com/QuentinFuxa/WhisperLiveKit/discussions)

---

**문서 버전**: 1.0.0
**최종 업데이트**: 2026-01-26
**작성자**: WhisperLiveKit 커뮤니티
