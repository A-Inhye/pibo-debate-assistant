# WhisperLiveKit 파일별 한국어 주석 가이드

이 문서는 WhisperLiveKit 프로젝트의 각 파일에 대한 한국어 설명과 주요 함수/클래스의 역할을 정리한 것입니다.

---

## 📁 코어 모듈 (whisperlivekit/)

### `__init__.py`
**역할**: 패키지 진입점, 주요 클래스/함수 export

**주요 export**:
```python
from .audio_processor import AudioProcessor  # 오디오 처리 파이프라인
from .core import TranscriptionEngine  # 전사 엔진 (싱글톤)
from .parse_args import parse_args  # CLI 인자 파서
from .web.web_interface import get_inline_ui_html, get_web_interface_html  # 웹 UI
```

---

### `core.py` ⭐ (핵심 엔진)
**역할**: 모든 AI 모델을 초기화하고 관리하는 싱글톤 클래스

#### 주요 클래스: `TranscriptionEngine`
**패턴**: 스레드 안전 싱글톤 (Double-Checked Locking)

**초기화 파라미터**:
- `model_size`: 모델 크기 (base, small, medium, large-v3)
- `lan`: 소스 언어 (auto, en, fr, ko, ...)
- `backend_policy`: 전사 정책 (simulstreaming, localagreement)
- `backend`: ASR 백엔드 (auto, mlx-whisper, faster-whisper, whisper)
- `diarization`: 화자 식별 활성화 (True/False)
- `target_language`: 번역 대상 언어 (빈 문자열 = 비활성화)

**멤버 변수**:
- `self.asr`: ASR 백엔드 인스턴스
- `self.diarization_model`: 화자 식별 모델
- `self.translation_model`: 번역 모델 (NLLW)
- `self.vac_session`: VAC 세션 (Silero VAD ONNX)

**사용 예**:
```python
engine = TranscriptionEngine(
    model_size="medium",
    lan="ko",
    diarization=True
)
```

#### 팩토리 함수

##### `online_factory(args, asr)`
**역할**: 각 WebSocket 연결마다 새로운 ASR 온라인 프로세서 생성

**반환**:
- `SimulStreamingOnlineProcessor`: SimulStreaming 정책용
- `OnlineASRProcessor`: LocalAgreement 정책용

##### `online_diarization_factory(args, diarization_backend)`
**역할**: 각 연결마다 새로운 화자 식별 인스턴스 생성

**반환**:
- `SortformerDiarizationOnline`: Sortformer 백엔드용
- `DiartDiarization`: Diart 백엔드용 (공유 인스턴스)

##### `online_translation_factory(args, translation_model)`
**역할**: 각 연결마다 새로운 번역 인스턴스 생성

**반환**:
- `OnlineTranslation`: NLLW 기반 번역 프로세서

---

### `audio_processor.py` ⭐ (오디오 파이프라인)
**역할**: 실시간 오디오 스트림 처리 및 결과 조합

#### 주요 클래스: `AudioProcessor`

**초기화 파라미터**:
- `transcription_engine`: TranscriptionEngine 인스턴스 (필수)

**주요 멤버 변수**:
- `self.sample_rate`: 샘플레이트 (16000 Hz)
- `self.channels`: 채널 수 (1 = 모노)
- `self.ffmpeg_manager`: FFmpeg 관리자 (WebM/Opus → PCM 변환)
- `self.vac`: Silero VAD 인스턴스 (음성 활동 감지)
- `self.transcription_queue`: 전사용 asyncio.Queue
- `self.diarization_queue`: 화자 식별용 asyncio.Queue
- `self.translation_queue`: 번역용 asyncio.Queue
- `self.state`: 현재 상태 (State 객체)

**주요 메서드**:

##### `async def create_tasks()`
**역할**: 모든 비동기 처리 작업 시작

**반환**: `results_formatter()` 제너레이터

**생성되는 작업**:
1. `ffmpeg_stdout_reader()`: FFmpeg 출력 읽기
2. `transcription_processor()`: ASR 처리
3. `diarization_processor()`: 화자 식별 처리
4. `translation_processor()`: 번역 처리
5. `watchdog()`: 작업 건강 모니터링

##### `async def process_audio(message: bytes)`
**역할**: WebSocket에서 받은 오디오 메시지 처리

**처리 흐름**:
1. PCM 모드: `self.pcm_buffer.extend(message)` → `handle_pcm_data()`
2. 압축 모드: `ffmpeg_manager.write_data(message)` → FFmpeg 변환

##### `async def handle_pcm_data()`
**역할**: PCM 데이터 VAD 처리 및 큐 삽입

**처리 단계**:
1. PCM 버퍼 → NumPy 배열 변환
2. Silero VAD 실행 → 음성/침묵 감지
3. 음성 활동 중이면 `transcription_queue`에 삽입
4. 침묵 감지 시 `Silence` 객체 삽입

##### `async def transcription_processor()`
**역할**: ASR 백엔드 호출 및 토큰 생성

**처리 흐름**:
1. 큐에서 오디오 청크 또는 Silence 객체 가져오기
2. ASR 실행: `self.transcription.process_iter()`
3. 새 토큰 생성: `ASRToken(start, end, text)`
4. 상태 업데이트: `self.state.tokens.extend(new_tokens)`
5. 번역 큐에 토큰 전달

##### `async def results_formatter()`
**역할**: 처리 결과를 프론트엔드 형식으로 변환

**반환**: `FrontData` 객체 스트림

**출력 구조**:
```python
{
    "status": "active_transcription",
    "lines": [Segment, ...],  # 정렬된 세그먼트
    "buffer_transcription": "현재 버퍼 텍스트",
    "buffer_diarization": "화자별 버퍼",
    "buffer_translation": "번역 버퍼",
    "remaining_time_transcription": 0.5,  # 남은 처리 시간
    "remaining_time_diarization": 0.2
}
```

---

### `basic_server.py` (FastAPI 서버)
**역할**: HTTP/WebSocket 서버 제공

#### 주요 엔드포인트

##### `GET /`
**역할**: 웹 UI HTML 반환

**응답**: `get_inline_ui_html()` - 인라인 CSS/JS가 포함된 HTML

##### `WebSocket /asr`
**역할**: 실시간 오디오 스트리밍 및 전사 결과 전송

**처리 흐름**:
1. WebSocket 연결 수락
2. `AudioProcessor` 인스턴스 생성 (연결별)
3. `create_tasks()` 호출 → 비동기 작업 시작
4. `handle_websocket_results()` 작업 생성 → 결과 전송
5. 루프: `receive_bytes()` → `process_audio(message)`
6. 연결 종료 시: `cleanup()`

**메시지 형식**:
- **입력**: Binary (WebM/Opus 또는 PCM s16le)
- **출력**: JSON (FrontData.to_dict())

##### `async def lifespan(app)`
**역할**: 서버 시작/종료 시 실행

**시작 시**: `TranscriptionEngine` 초기화 (싱글톤)
**종료 시**: 정리 작업 (선택)

---

### `parse_args.py` (CLI 인자 파서)
**역할**: 100개 이상의 명령줄 옵션 정의

**주요 인자 그룹**:

#### 서버 설정
```bash
--host localhost          # 서버 호스트
--port 8000               # 서버 포트
--ssl-certfile cert.pem   # SSL 인증서
--ssl-keyfile key.pem     # SSL 키
```

#### 모델 설정
```bash
--model base              # 모델 크기
--model-path /path        # 커스텀 모델 경로
--lora-path /path         # LoRA 어댑터
--language en             # 소스 언어
--target-language ko      # 번역 대상
```

#### 백엔드 설정
```bash
--backend-policy simulstreaming    # 전사 정책
--backend auto                     # ASR 백엔드
--diarization                      # 화자 식별 활성화
--diarization-backend sortformer   # 화자 식별 백엔드
```

#### SimulStreaming 옵션
```bash
--frame-threshold 25      # AlignAtt 임계값
--beams 1                 # 빔 탐색 크기
--audio-max-len 30.0      # 최대 오디오 길이
--cif-ckpt-path /path     # CIF 모델 경로
```

**반환**: `argparse.Namespace` 객체

---

### `ffmpeg_manager.py` (FFmpeg 관리자)
**역할**: 비동기 FFmpeg 서브프로세스 관리

#### 주요 클래스: `FFmpegManager`

**초기화 파라미터**:
- `sample_rate`: 출력 샘플레이트 (16000)
- `channels`: 출력 채널 수 (1)

**주요 메서드**:

##### `async def start()`
**역할**: FFmpeg 서브프로세스 시작

**FFmpeg 명령어**:
```bash
ffmpeg -hide_banner -loglevel error -i pipe:0 \
  -f s16le -acodec pcm_s16le -ac 1 -ar 16000 pipe:1
```

**설명**:
- `pipe:0`: stdin에서 입력 (WebM/Opus 등)
- `-f s16le`: PCM signed 16-bit little-endian 출력
- `-ac 1`: 모노 변환
- `-ar 16000`: 16kHz 리샘플링
- `pipe:1`: stdout으로 출력

##### `async def write_data(data: bytes)`
**역할**: FFmpeg stdin에 압축 오디오 쓰기

##### `async def read_data(size: int)`
**역할**: FFmpeg stdout에서 PCM 데이터 읽기

**반환**: `bytes` (PCM s16le)

##### `async def stop()`
**역할**: FFmpeg 종료 및 리소스 정리

---

### `silero_vad_iterator.py` (음성 활동 감지)
**역할**: Silero VAD 모델을 사용한 음성/침묵 감지

#### 주요 클래스

##### `OnnxSession`
**역할**: 공유 ONNX 세션 (상태 없음)

**장점**: 여러 연결이 동일한 세션 공유 → 메모리 절약

##### `OnnxWrapper`
**역할**: ONNX 런타임 래퍼 (연결별 상태 관리)

**멤버 변수**:
- `_shared_session`: 공유 OnnxSession
- `_state`: 내부 상태 텐서 [2, batch, 128]
- `_context`: 컨텍스트 윈도우 (64 프레임)

##### `FixedVADIterator(VADIterator)`
**역할**: 가변 길이 오디오 청크 처리

**메서드**: `__call__(self, x)`
**입력**: NumPy 배열 (가변 길이)
**출력**:
- `{"start": sample_index}`: 음성 시작
- `{"end": sample_index}`: 음성 종료
- `None`: 변화 없음

**내부 동작**:
1. 버퍼에 오디오 누적
2. 512 샘플마다 VAD 모델 실행
3. 음성 확률 > 0.5 → 음성
4. 음성 확률 < 0.35 → 침묵

---

### `timed_objects.py` (데이터 구조)
**역할**: 시간 정보가 있는 데이터 클래스 정의

#### 주요 클래스

##### `ASRToken`
**역할**: 개별 단어/토큰 (타임스탬프 포함)

**속성**:
```python
start: float        # 시작 시간 (초)
end: float          # 종료 시간 (초)
text: str           # 텍스트
speaker: int        # 화자 ID (-1 = 미지정)
detected_language: str  # 감지된 언어
```

##### `Segment`
**역할**: 여러 토큰의 집합 (문장/구절)

**속성**:
```python
start: float
end: float
text: str           # 연결된 텍스트
speaker: int        # 화자 ID
translation: str    # 번역 (선택)
```

##### `Silence`
**역할**: 침묵 구간 표시

**속성**:
```python
start: float
end: float
duration: float
is_starting: bool   # 침묵 시작 중
has_ended: bool     # 침묵 종료됨
```

##### `FrontData`
**역할**: 프론트엔드로 전송될 응답 데이터

**속성**:
```python
status: str         # "active_transcription", "no_audio_detected", "error"
lines: List[Segment]  # 확정된 세그먼트
buffer_transcription: str  # 전사 버퍼
buffer_diarization: str    # 화자 식별 버퍼
buffer_translation: str    # 번역 버퍼
remaining_time_transcription: float
remaining_time_diarization: float
```

##### `State`
**역할**: 오디오 처리 상태 관리

**영구 상태**:
```python
tokens: List[ASRToken]          # 모든 토큰
buffer_transcription: Transcript  # 전사 버퍼
end_buffer: float                 # 버퍼 종료 시간
end_attributed_speaker: float     # 화자 식별 종료 시간
```

**임시 업데이트 버퍼**:
```python
new_tokens: List[ASRToken]       # 새 토큰 (TokensAlignment가 소비)
new_diarization: List[SpeakerSegment]
new_translation: List[Translation]
new_tokens_buffer: Transcript
new_translation_buffer: Translation
```

---

### `tokens_alignment.py` (토큰 정렬)
**역할**: 전사, 화자 식별, 번역을 시간축으로 정렬

#### 주요 클래스: `TokensAlignment`

**초기화 파라미터**:
- `state`: State 객체
- `args`: 설정 파라미터
- `sep`: 단어 구분자 (기본값: " ")

**주요 메서드**:

##### `update()`
**역할**: state의 새 데이터를 내부 버퍼로 이동

**처리**:
```python
self.new_tokens = state.new_tokens
state.new_tokens = []  # 비우기

self.all_tokens.extend(self.new_tokens)
self.all_diarization_segments.extend(self.new_diarization)
```

##### `get_lines(diarization, translation, current_silence)`
**역할**: 정렬된 세그먼트 생성

**반환**:
- `segments: List[Segment]`: 화자/번역이 매핑된 세그먼트
- `diarization_buffer: str`: 화자 버퍼 텍스트
- `translation_buffer: str`: 번역 버퍼 텍스트

**처리 흐름**:
1. 구두점으로 토큰 그룹화: `compute_punctuations_segments()`
2. 화자 정보 매핑: `intersection_duration()` 사용
3. 번역 정보 병합: `add_translation()`
4. Segment 객체 생성

---

## 📁 SimulStreaming 백엔드 (whisperlivekit/simul_whisper/)

### `simul_whisper.py` ⭐ (AlignAtt 디코더)
**역할**: Attention Alignment를 사용한 동시 스트리밍 디코딩

#### 주요 클래스: `AlignAtt`

**초기화 파라미터**:
- `model`: Whisper 모델 인스턴스
- `alignment_heads`: 정렬 헤드 리스트 [(layer, head), ...]
- `frame_threshold`: 발화 임계값 (기본값: 25)
- `tokenizer`: 토크나이저 인스턴스

**주요 메서드**:

##### `compute_alignment(encoder_output, tokens)`
**역할**: Cross-Attention 가중치 계산

**반환**: `[num_tokens, num_frames]` 텐서

**처리**:
1. 각 alignment head의 attention 가중치 추출
2. 평균 계산
3. 현재 토큰이 어느 오디오 프레임에 집중하는지 반환

##### `should_fire(alignment_scores)`
**역할**: 발화 지점 감지

**알고리즘**:
```python
last_token_attention = alignment_scores[-1]  # 마지막 토큰
recent_frames_attention = last_token_attention[-threshold:]
if recent_frames_attention.sum() > 0.25:  # 25% 임계값
    return True  # 단어 완성, 발화!
```

##### `decode_streaming(encoder_output, audio_chunk)`
**역할**: 스트리밍 디코딩 실행

**반환**: `ASRToken` 또는 `None`

**처리 흐름**:
1. 디코더 forward: `logits = model.decoder(...)`
2. Attention alignment 계산
3. `should_fire()` 체크
4. 발화 시:
   - 다음 토큰 샘플링
   - ASRToken 생성
   - KV-cache 업데이트
5. 미발화 시: `None` 반환

---

### `backend.py` (SimulStreamingASR)
**역할**: AlignAtt를 사용한 ASR 백엔드 설정

#### 주요 클래스: `SimulStreamingASR`

**초기화 파라미터**:
- `model_size`: 모델 크기
- `lan`: 언어
- `backend`: "auto", "mlx-whisper", "faster-whisper", "whisper"
- `frame_threshold`: AlignAtt 임계값
- `beams`: 빔 탐색 크기

**주요 메서드**:

##### `__init__(...)`
**역할**: 모델 및 인코더 로드

**처리 흐름**:
1. 백엔드 자동 선택 (`backend="auto"`)
   - macOS + ARM → MLX-Whisper
   - 기타 → Faster-Whisper → PyTorch
2. Alignment Heads 로드
3. 인코더 설정 (빠른 인코더 사용)

##### `transcribe(audio)`
**역할**: 오디오 전사 (배치)

**내부 호출**: `AlignAtt.decode_streaming()`

---

### `decoder_state.py` (디코더 상태)
**역할**: 디코더의 상태 관리 (토큰, KV-캐시)

#### 주요 클래스: `DecoderState`

**속성**:
```python
tokens: List[int]           # 생성된 토큰 ID
kv_cache: Dict[str, Tensor] # KV-캐시 (레이어별)
audio_offset: float         # 오디오 오프셋
```

**주요 메서드**:

##### `clean_cache()`
**역할**: KV-캐시 메모리 해제

**처리**:
```python
for key in list(self.kv_cache.keys()):
    tensor = self.kv_cache.pop(key)
    del tensor

if torch.cuda.is_available():
    torch.cuda.empty_cache()
```

---

### `token_buffer.py` (토큰 버퍼)
**역할**: 생성된 토큰의 버퍼 관리

#### 주요 클래스: `TokenBuffer`

**메서드**:

##### `add_token(token_id, text, timing)`
**역할**: 토큰 추가

##### `get_confirmed_tokens()`
**역할**: 확정된 토큰 반환

##### `reset()`
**역할**: 버퍼 초기화

---

### `beam.py` (빔 탐색)
**역할**: 빔 탐색 디코딩 구현

#### 주요 클래스: `BeamSearch`

**초기화 파라미터**:
- `beam_size`: 빔 크기 (기본값: 5)
- `max_length`: 최대 시퀀스 길이

**주요 메서드**:

##### `search(model, encoder_output)`
**역할**: 빔 탐색 실행

**반환**: 최고 점수 토큰 시퀀스

**알고리즘**:
1. 초기 빔: [<SOT>]
2. 각 단계:
   - 각 빔에서 상위 K개 토큰 생성
   - 총 K×K개 후보 중 상위 K개 선택
3. 종료 조건: 모든 빔이 <EOT>에 도달
4. 최고 점수 빔 반환

---

### `eow_detection.py` (단어 끝 감지)
**역할**: CIF (Continuous Integrate-and-Fire) 구현

#### 주요 클래스: `CIFModel`

**역할**: Encoder 출력에서 단어 경계 예측

**메서드**:

##### `forward(encoder_output)`
**역할**: 각 프레임의 발화 확률 계산

**반환**: `[num_frames]` 텐서 (0-1 확률)

**알고리즘**:
```python
h_t = encoder_output[t]
α_t = sigmoid(W_cif @ h_t + b_cif)  # 발화 확률
C_t = cumsum(α)  # 누적 합
if floor(C_t) > floor(C_{t-1}):
    fire = True  # 단어 경계
```

---

## 📁 LocalAgreement 백엔드 (whisperlivekit/local_agreement/)

### `whisper_online.py` (백엔드 팩토리)
**역할**: ASR 백엔드 선택 및 생성

#### 주요 함수: `backend_factory(backend, **kwargs)`

**지원 백엔드**:
- `"whisper"`: PyTorch Whisper
- `"faster-whisper"`: CTranslate2 Faster-Whisper
- `"mlx-whisper"`: MLX-Whisper (Apple Silicon)
- `"openai-api"`: OpenAI API

**반환**: ASR 백엔드 인스턴스

---

### `online_asr.py` (온라인 프로세서)
**역할**: LocalAgreement 정책 구현

#### 주요 클래스: `OnlineASRProcessor`

**초기화 파라미터**:
- `asr`: ASR 백엔드
- `buffer_trimming`: "sentence" 또는 "segment"

**주요 메서드**:

##### `insert_audio_chunk(audio, offset)`
**역할**: 오디오 청크 삽입

##### `process_iter()`
**역할**: ASR 실행 및 토큰 확정

**반환**: `(confirmed_tokens, processed_upto)`

**처리 흐름**:
1. ASR 실행: `result = self.asr.transcribe(audio)`
2. 타임스탬프 단어 추출: `words = self.asr.ts_words(result)`
3. Hypothesis Buffer에 삽입
4. LCP (Longest Common Prefix) 계산
5. 확정된 토큰 반환

##### `get_buffer()`
**역할**: 현재 버퍼 텍스트 반환

**반환**: `Transcript` 객체

---

### `backends.py` (ASR 백엔드 구현)

#### `WhisperASR`
**역할**: PyTorch Whisper 백엔드

**메서드**:
- `transcribe(audio)`: 전사 실행
- `ts_words(segments)`: 타임스탬프 단어 추출

#### `FasterWhisperASR`
**역할**: CTranslate2 최적화 백엔드

**장점**: 4-10배 빠른 추론, INT8 양자화

#### `MLXWhisper`
**역할**: Apple Silicon 최적화 백엔드

**장점**: 초저지연 (10-50ms), 통합 메모리 사용

#### `OpenaiApiASR`
**역할**: OpenAI API 클라우드 백엔드

**장점**: 무제한 동시성, 최고 정확도
**단점**: 높은 지연시간 (1-3초), 유료

---

## 📁 화자 식별 (whisperlivekit/diarization/)

### `sortformer_backend.py` ⭐ (Sortformer)
**역할**: 스트리밍 화자 식별 (SOTA 2025)

#### 주요 클래스: `SortformerDiarization`

**역할**: 공유 Sortformer 모델 (싱글톤)

**초기화**:
```python
from nemo.collections.asr.models import SortformerEncLabelModel
self.model = SortformerEncLabelModel.from_pretrained("nvidia/sortformer-diar-1b")
```

#### 주요 클래스: `SortformerDiarizationOnline`

**역할**: 연결별 스트리밍 상태 관리

**메서드**:

##### `insert_audio_chunk(audio)`
**역할**: 오디오 청크 삽입

##### `diarize()`
**역할**: 화자 식별 실행

**반환**: `List[SpeakerSegment]`

**처리 흐름**:
1. Mel-spectrogram 추출 (10 프레임 청크)
2. Sortformer 모델 forward
3. Speaker embeddings 생성
4. 온라인 클러스터링
5. SpeakerSegment 출력

---

### `diart_backend.py` (Diart)
**역할**: Pyannote 기반 화자 식별 (SOTA 2021)

#### 주요 클래스: `DiartDiarization`

**역할**: RxPy Observable 기반 화자 식별

**초기화 파라미터**:
- `segmentation_model`: "pyannote/segmentation-3.0"
- `embedding_model`: "speechbrain/spkrec-ecapa-voxceleb"

**메서드**:

##### `start()`
**역할**: Observable 스트림 시작

##### `insert_audio_chunk(audio)`
**역할**: 오디오 삽입

**내부 동작**:
1. Segmentation: 음성 활동 감지
2. Embedding: 화자 임베딩 생성
3. Clustering: 화자별 그룹화
4. Observable emit: SpeakerSegment

---

## 📁 Whisper 모델 (whisperlivekit/whisper/)

### `model.py` (Whisper 아키텍처)
**역할**: Whisper 트랜스포머 구현

#### 주요 클래스: `Whisper`

**구조**:
```python
Whisper
├── encoder: AudioEncoder
│   ├── Conv1d (80 → 1280)
│   ├── Conv1d (stride=2)
│   ├── PositionalEmbedding
│   └── ResidualAttentionBlock × 32
└── decoder: TextDecoder
    ├── TokenEmbedding (51865 vocab)
    ├── PositionalEmbedding
    └── ResidualAttentionBlock × 32 (Cross-Attention)
```

**입력/출력**:
- 입력: Mel-spectrogram [80, 3000]
- 출력: Logits [seq_len, 51865]

---

### `audio.py` (오디오 전처리)
**역할**: Mel-spectrogram 추출

#### 주요 함수

##### `log_mel_spectrogram(audio)`
**역할**: 오디오 → Mel-spectrogram 변환

**파라미터**:
- `N_FFT=400`: FFT 윈도우 크기
- `HOP_LENGTH=160`: 스트라이드
- `N_MELS=80`: Mel 빈 개수

**반환**: `[80, frames]` 텐서

---

### `decoding.py` (디코딩)
**역할**: 토큰 생성 (Greedy, Beam Search)

#### 주요 클래스

##### `GreedyDecoder`
**역할**: Argmax 기반 디코딩

**장점**: 빠름 (1x)
**단점**: 차선 경로 탐색 안 함

##### `BeamSearchDecoder`
**역할**: 빔 탐색 디코딩

**장점**: 높은 정확도
**단점**: 느림 (5-10x)

**파라미터**:
- `beam_size`: 빔 크기
- `patience`: 조기 종료 인내심
- `length_penalty`: 길이 페널티

---

### `tokenizer.py` (토크나이저)
**역할**: 텍스트 ↔ 토큰 ID 변환

#### 주요 클래스: `Tokenizer`

**지원 언어**: 99개

**특수 토큰**:
- `<SOT>`: Start-of-Transcript
- `<EOT>`: End-of-Transcript
- `<|en|>`: 언어 토큰
- `<|notimestamps|>`: 타임스탬프 비활성화
- `<|0.00|>`: 타임스탬프

**메서드**:

##### `encode(text)`
**역할**: 텍스트 → 토큰 ID

##### `decode(token_ids)`
**역할**: 토큰 ID → 텍스트

---

### `transcribe.py` (전사 파이프라인)
**역할**: 고수준 전사 인터페이스

#### 주요 함수: `transcribe(model, audio, **kwargs)`

**처리 흐름**:
1. 오디오 → Mel-spectrogram
2. 30초 청크로 분할
3. 언어 감지 (lan="auto"인 경우)
4. 각 청크 전사
5. 세그먼트 병합
6. 타임스탬프 추출
7. 결과 반환

**반환**:
```python
{
    "text": "전체 텍스트",
    "segments": [
        {
            "start": 0.0,
            "end": 3.5,
            "text": "Hello world",
            "words": [
                {"word": "Hello", "start": 0.0, "end": 0.6},
                {"word": "world", "start": 0.8, "end": 1.2}
            ]
        },
        ...
    ],
    "language": "en"
}
```

---

## 📁 웹 인터페이스 (whisperlivekit/web/)

### `web_interface.py` (UI 로더)
**역할**: HTML/CSS/JS 파일 로드 및 인라인화

#### 주요 함수

##### `get_inline_ui_html()`
**역할**: 단일 HTML 파일 생성 (CSS/JS 인라인)

**반환**: 완전한 HTML 문자열

**처리**:
1. HTML 파일 읽기
2. CSS 파일 읽기 → `<style>` 태그로 삽입
3. JS 파일 읽기 → `<script>` 태그로 삽입
4. SVG 아이콘 → data URI 변환
5. AudioWorklet/Worker → 인라인 삽입

---

### `live_transcription.html/css/js` (프론트엔드)

#### HTML 구조
```html
<div id="app">
    <div id="settings">
        <!-- 설정 패널 -->
    </div>
    <div id="transcript">
        <!-- 전사 출력 -->
    </div>
    <div id="controls">
        <button id="start">Start</button>
        <button id="stop">Stop</button>
    </div>
</div>
```

#### JavaScript 주요 함수

##### `startRecording()`
**역할**: 오디오 캡처 시작

**처리**:
1. `navigator.mediaDevices.getUserMedia()` 호출
2. MediaRecorder 또는 AudioWorklet 초기화
3. WebSocket 연결: `ws://localhost:8000/asr`
4. 오디오 청크 전송

##### `onWebSocketMessage(event)`
**역할**: 서버 응답 처리

**처리**:
```javascript
const data = JSON.parse(event.data);

if (data.type === "config") {
    // 설정 수신
    useAudioWorklet = data.useAudioWorklet;
}

if (data.status === "active_transcription") {
    // 전사 결과 표시
    updateTranscript(data.lines);
    updateBuffer(data.buffer_transcription);
}
```

##### `updateTranscript(lines)`
**역할**: UI 업데이트

**처리**:
```javascript
lines.forEach(segment => {
    const div = document.createElement('div');
    div.className = 'segment';
    div.dataset.speaker = segment.speaker;
    div.textContent = segment.text;
    transcriptDiv.appendChild(div);
});
```

---

### `pcm_worklet.js` (AudioWorklet)
**역할**: PCM 모드 오디오 캡처

#### 클래스: `PCMProcessor`

**역할**: 16kHz PCM s16le 데이터 생성

**메서드**:

##### `process(inputs, outputs, parameters)`
**역할**: 오디오 프레임 처리

**처리**:
1. Float32 입력 → Int16 변환
2. `postMessage()` → 메인 스레드로 전송
3. WebSocket으로 전송

---

## 📁 스크립트 (scripts/)

### `convert_hf_whisper.py`
**역할**: HuggingFace 모델 → WhisperLiveKit 형식 변환

**사용법**:
```bash
python scripts/convert_hf_whisper.py \
  --repo openai/whisper-large-v3 \
  --output ./models/large-v3
```

---

### `determine_alignment_heads.py`
**역할**: Alignment Heads 추출

**사용법**:
```bash
python scripts/determine_alignment_heads.py \
  --model-path ./models/large-v3 \
  --output alignment_heads.json
```

**알고리즘**:
1. 여러 오디오 샘플 전사
2. 각 헤드의 attention 가중치 분석
3. Cross-Attention이 강한 헤드 선택
4. JSON으로 저장

---

### `sync_extension.py`
**역할**: Chrome 확장 프로그램 동기화

**사용법**:
```bash
python scripts/sync_extension.py --url http://localhost:8000
```

---

## 🔧 유틸리티 모듈

### `backend_support.py`
**역할**: 백엔드 가용성 확인

#### 함수

##### `mlx_backend_available(warn_on_missing=False)`
**역할**: MLX-Whisper 설치 여부 확인

**조건**: macOS + ARM64 + mlx-whisper 설치

##### `faster_backend_available(warn_on_missing=False)`
**역할**: Faster-Whisper 설치 여부 확인

---

### `model_paths.py`
**역할**: 모델 경로 해석 및 다운로드

#### 주요 함수

##### `resolve_model_path(model_path)`
**역할**: 모델 경로 → 로컬 경로 변환

**처리**:
1. 로컬 파일 확인
2. HuggingFace 저장소 확인
3. 자동 다운로드
4. 형식 감지 (PyTorch, MLX, CTranslate2)

---

### `thread_safety.py`
**역할**: 스레드 안전 모델 접근

#### 함수

##### `@with_model_lock`
**역할**: 데코레이터 - 모델 호출 직렬화

**사용법**:
```python
@with_model_lock
def transcribe(audio):
    return model(audio)
```

---

### `warmup.py`
**역할**: 모델 워밍업

#### 함수

##### `warmup_asr(asr, warmup_file=None)`
**역할**: 첫 호출 지연 감소

**처리**:
1. JFK 샘플 다운로드
2. ASR 실행 (결과 무시)
3. GPU 메모리 할당
4. JIT 컴파일 (PyTorch)

---

## 📊 데이터 흐름 요약

```
[브라우저]
   ↓ WebSocket Binary
[basic_server.py - FastAPI]
   ↓ WebSocket.receive_bytes()
[AudioProcessor.process_audio()]
   ↓ FFmpeg 변환 (선택)
[handle_pcm_data()]
   ↓ Silero VAD
[transcription_queue.put()]
   ↓
[transcription_processor()]
   ├→ SimulStreamingASR (AlignAtt)
   └→ LocalAgreement (Hypothesis Buffer)
   ↓ ASRToken 스트림
[state.tokens.extend()]
   ↓
[diarization_processor()] (선택)
   └→ Sortformer / Diart
   ↓ SpeakerSegment 스트림
[state.new_diarization.extend()]
   ↓
[translation_processor()] (선택)
   └→ NLLW
   ↓ Translation 스트림
[state.new_translation.extend()]
   ↓
[TokensAlignment.update()]
   ↓
[TokensAlignment.get_lines()]
   ↓ Segment 리스트
[results_formatter()]
   ↓ FrontData.to_dict()
[WebSocket.send_json()]
   ↓
[브라우저 UI 업데이트]
```

---

## 🎯 주요 설계 패턴

### 1. 싱글톤 패턴
**위치**: `TranscriptionEngine`
**목적**: 모델 인스턴스 공유로 메모리 절약

### 2. 팩토리 패턴
**위치**: `online_factory()`, `backend_factory()`
**목적**: 백엔드 선택 추상화

### 3. Producer-Consumer 패턴
**위치**: asyncio.Queue (전사, 화자식별, 번역)
**목적**: 비동기 처리 파이프라인

### 4. Observer 패턴
**위치**: Diart (RxPy Observable)
**목적**: 이벤트 기반 화자 식별

### 5. State 패턴
**위치**: `FFmpegState`, `DecoderState`
**목적**: 상태 관리 및 전환

---

## 🚀 성능 최적화 기법

### 1. KV-Cache
**위치**: `decoder_state.py`
**효과**: 10-100배 메모리/계산 절약

### 2. Attention Alignment
**위치**: `simul_whisper.py`
**효과**: 300-800ms 단어 단위 지연

### 3. ONNX Runtime
**위치**: `silero_vad_iterator.py`
**효과**: VAD 3-5배 빠름

### 4. 비동기 I/O
**위치**: `audio_processor.py`, `ffmpeg_manager.py`
**효과**: 다중 연결 동시 처리

### 5. 빠른 인코더
**위치**: Faster-Whisper, MLX-Whisper
**효과**: 4-10배 빠른 인코딩

---

**문서 작성일**: 2026-01-26
**작성자**: WhisperLiveKit Korean Documentation Team
**버전**: 0.2.17.post1
