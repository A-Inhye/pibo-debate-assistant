# 한국어 실시간 STT + Diart 화자 분할 + WebSocket 서버
# RTX 3090 + Jabra Speak2 75
#
# 구조:
#     [마이크/Jabra]
#           │
#           ▼
#     ┌─────────────┐
#     │ RealtimeSTT │──→ on_recorded_chunk ──→ [Diart 화자 분할]
#     └─────────────┘                              │
#           │                                      │
#           ▼                                      ▼
#        텍스트                               화자 라벨
#           │                                      │
#           └──────────────┬───────────────────────┘
#                          ▼
#                   [WebSocket 서버]
#                          │
#                          ▼
#                    [웹 브라우저]
#
# 실행 방법:
#     1. python realtime_stt_korean_diart_web.py
#     2. 브라우저에서 http://localhost:8000/index.html 열기
#        (별도 터미널에서: python -m http.server 8000)

# ============================================================
# 중요: torch를 가장 먼저 import하고 패치해야 함
# ============================================================
import sys
import os
from datetime import datetime

# Windows에서 cuDNN/cuBLAS DLL 경로 설정 (CUDA 오류 방지)
if os.name == 'nt':  # Windows
    try:
        import nvidia.cublas.bin
        import nvidia.cudnn.bin
        os.add_dll_directory(os.path.dirname(nvidia.cublas.bin.__file__))
        os.add_dll_directory(os.path.dirname(nvidia.cudnn.bin.__file__))
    except (ImportError, OSError):
        pass

import torch

# PyTorch 2.6+ weights_only 기본값 변경 대응
# pyannote 모델 로드 시 오류 방지

# 방법 1: safe_globals에 TorchVersion 추가
try:
    torch.serialization.add_safe_globals([torch.torch_version.TorchVersion])
except (AttributeError, TypeError):
    pass

# 방법 2: torch.load 패치 (다른 import 전에 패치해야 함)
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    kwargs.setdefault('weights_only', False)
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

# 방법 3: 환경 변수 설정
os.environ['TORCH_FORCE_WEIGHTS_ONLY_LOAD'] = '0'

# 이제 나머지 모듈 import
from RealtimeSTT import AudioToTextRecorder
import pyaudio
import numpy as np
import threading
import asyncio
import websockets
import json

# 현재 스크립트 디렉토리 경로
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Hugging Face 토큰 설정 (pyannote 모델 사용에 필요)
# 환경 변수 HF_TOKEN을 설정해야 함
# 예: export HF_TOKEN="your_token_here" (Linux/Mac)
#     set HF_TOKEN=your_token_here (Windows)
if "HF_TOKEN" not in os.environ:
    print("경고: HF_TOKEN 환경 변수가 설정되지 않았습니다.")
    print("pyannote 모델 사용을 위해 Hugging Face 토큰이 필요합니다.")

# Diart 모듈 경로 추가 및 임포트
try:
    from pyannote.core import SlidingWindowFeature, SlidingWindow

    # diart 모듈 경로 추가 (현재 스크립트 기준 상대 경로)
    diart_path = os.path.join(SCRIPT_DIR, "diart-main", "diart-main", "src")
    if diart_path not in sys.path:
        sys.path.insert(0, diart_path)

    from diart.models import SegmentationModel, EmbeddingModel
    from diart.blocks.segmentation import SpeakerSegmentation
    from diart.blocks.embedding import OverlapAwareSpeakerEmbedding
    from diart.blocks.clustering import OnlineSpeakerClustering

    DIARIZATION_AVAILABLE = True
    print("Diart 화자 분할 모듈 로드 성공")
except ImportError as e:
    DIARIZATION_AVAILABLE = False
    print(f"Diart 모듈 로드 실패: {e}")
    print("화자 구분 없이 STT만 사용합니다.")


# ============================================================
# WebSocket 서버
# ============================================================

connected_clients = set()
conversation_log = []


async def broadcast_message(message):
    """모든 연결된 클라이언트에게 메시지 전송"""
    if connected_clients:
        message_json = json.dumps(message, ensure_ascii=False)
        await asyncio.gather(
            *[client.send(message_json) for client in connected_clients],
            return_exceptions=True
        )


def broadcast_sync(message):
    """동기 함수에서 브로드캐스트 (STT 콜백용)"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(broadcast_message(message))
        loop.close()
    except Exception as e:
        print(f"브로드캐스트 오류: {e}")


async def handle_client(websocket):
    """WebSocket 클라이언트 처리"""
    print(f"[WebSocket] 새 클라이언트 연결: {websocket.remote_address}")
    connected_clients.add(websocket)

    try:
        # 초기 데이터 전송 (기존 대화 로그)
        await websocket.send(json.dumps({
            "type": "init",
            "conversation": conversation_log,
            "summaries": {}
        }, ensure_ascii=False))

        # 클라이언트 메시지 수신 대기
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("type") == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass

    except websockets.exceptions.ConnectionClosed:
        print(f"[WebSocket] 클라이언트 연결 종료: {websocket.remote_address}")
    finally:
        connected_clients.discard(websocket)


async def start_websocket_server():
    """WebSocket 서버 시작"""
    print("[WebSocket] 서버 시작 중... (포트: 9090)")
    async with websockets.serve(handle_client, "0.0.0.0", 9090):
        print("[WebSocket] 서버 실행 중 (ws://localhost:9090)")
        await asyncio.Future()


def run_websocket_server():
    """별도 쓰레드에서 WebSocket 서버 실행"""
    asyncio.run(start_websocket_server())


# ============================================================
# Diart 화자 분할 클래스
# ============================================================

class DiartSpeakerDiarization:
    """Diart 기반 실시간 화자 분할"""

    def __init__(
        self,
        sample_rate=16000,
        chunk_duration=5.0,
        device="cuda",
        tau_active=0.6,
        rho_update=0.3,
        delta_new=1.0,
    ):
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration
        self.chunk_samples = int(chunk_duration * sample_rate)
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")

        print(f"\n화자 분할 초기화 중...")
        print(f"  장치: {self.device}")
        print(f"  청크 길이: {chunk_duration}초")

        # pyannote Segmentation 모델 로드
        print("  Segmentation 모델 로드 중... (pyannote/segmentation-3.0)")
        seg_model = SegmentationModel.from_pretrained("pyannote/segmentation-3.0")
        self.segmentation = SpeakerSegmentation(seg_model, self.device)

        # pyannote Embedding 모델 로드
        print("  Embedding 모델 로드 중... (pyannote/embedding)")
        emb_model = EmbeddingModel.from_pretrained("pyannote/embedding")
        self.embedding = OverlapAwareSpeakerEmbedding(
            emb_model,
            gamma=3.0,
            beta=10.0,
            device=self.device
        )

        # 온라인 클러스터링
        self.clustering = OnlineSpeakerClustering(
            tau_active=tau_active,
            rho_update=rho_update,
            delta_new=delta_new,
            metric="cosine",
            max_speakers=10
        )

        # 오디오 버퍼
        self.audio_buffer = np.array([], dtype=np.float32)
        self.current_speaker = None
        self.lock = threading.Lock()

        # 화자 등장 순서 매핑 (첫 화자 → A, 두 번째 → B, ...)
        self.speaker_order_map = {}
        self.next_speaker_index = 0

        print("화자 분할 초기화 완료\n")

    def feed_audio(self, audio_chunk):
        """오디오 청크를 버퍼에 추가"""
        with self.lock:
            # bytes 또는 bytearray → numpy 변환
            if isinstance(audio_chunk, (bytes, bytearray)):
                audio_chunk = np.frombuffer(audio_chunk, dtype=np.int16)

            # int16 → float32 정규화
            if hasattr(audio_chunk, 'dtype') and audio_chunk.dtype == np.int16:
                audio_chunk = audio_chunk.astype(np.float32) / 32768.0

            # 다채널 → 모노
            if audio_chunk.ndim > 1:
                audio_chunk = np.mean(audio_chunk, axis=1)

            self.audio_buffer = np.concatenate([self.audio_buffer, audio_chunk])
            self._process_if_ready()

    def _process_if_ready(self):
        """버퍼가 충분히 쌓이면 화자 분할 수행"""
        if len(self.audio_buffer) < self.chunk_samples:
            return

        chunk = self.audio_buffer[:self.chunk_samples]
        # 50% 오버랩으로 버퍼 유지
        overlap_samples = self.chunk_samples // 2
        self.audio_buffer = self.audio_buffer[overlap_samples:]

        # 별도 스레드에서 처리 (블로킹 방지)
        threading.Thread(target=self._process_chunk, args=(chunk,), daemon=True).start()

    def _process_chunk(self, chunk):
        """화자 분할 처리"""
        try:
            # waveform 형태: (batch, samples, channels)
            waveform = torch.from_numpy(chunk).float().unsqueeze(0).unsqueeze(-1)

            # Segmentation
            segmentation = self.segmentation(waveform)

            # Embedding
            embeddings = self.embedding(waveform, segmentation)

            # SlidingWindowFeature로 변환
            num_frames = segmentation.shape[1]
            frame_duration = self.chunk_duration / num_frames
            sw = SlidingWindow(start=0.0, duration=frame_duration, step=frame_duration)
            seg_feature = SlidingWindowFeature(segmentation.squeeze(0).cpu().numpy(), sw)

            # 클러스터링
            clustered = self.clustering(seg_feature, embeddings.squeeze(0))

            # 현재 화자 결정 (가장 활성화된 화자)
            speaker_activity = np.mean(clustered.data, axis=0)
            max_activity = np.max(speaker_activity)

            if max_activity > 0.3:
                self.current_speaker = int(np.argmax(speaker_activity))
            else:
                self.current_speaker = None

        except Exception as e:
            pass  # 오류 시 무시 (STT는 계속 동작)

    def get_current_speaker(self):
        """현재 화자 ID 반환"""
        return self.current_speaker

    def get_speaker_label(self, speaker_id=None):
        """화자 라벨 반환 (등장 순서대로: 첫 화자 → A, 두 번째 → B, ...)"""
        if speaker_id is None:
            speaker_id = self.current_speaker

        if speaker_id is None:
            return "미지정"

        # 새로운 화자면 등장 순서에 따라 매핑
        if speaker_id not in self.speaker_order_map:
            self.speaker_order_map[speaker_id] = self.next_speaker_index
            self.next_speaker_index += 1

        # 등장 순서로 라벨 결정
        order_index = self.speaker_order_map[speaker_id]
        labels = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
        if order_index < len(labels):
            return f"화자 {labels[order_index]}"
        return f"화자 {order_index}"


# ============================================================
# 전역 변수
# ============================================================

diarization = None


# ============================================================
# 유틸리티 함수
# ============================================================

def list_audio_devices():
    """마이크 목록 출력"""
    p = pyaudio.PyAudio()
    print("마이크 목록")

    input_devices = []
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        if info['maxInputChannels'] > 0:
            input_devices.append((i, info['name']))
            print(f"  [{i}] {info['name']}")

    p.terminate()
    print()
    return input_devices


def select_device(devices):
    """사용자에게 장치 선택 받기"""
    while True:
        try:
            choice = input("마이크 번호 입력: ")
            device_index = int(choice)
            if any(d[0] == device_index for d in devices):
                return device_index
            print("잘못된 번호입니다.")
        except ValueError:
            print("숫자를 입력하세요.")


# ============================================================
# RealtimeSTT 콜백
# ============================================================

def on_recording_start():
    print("말씀하세요")


def on_recording_stop():
    print("변환 중...")


def on_recorded_chunk(audio_chunk):
    """RealtimeSTT 오디오 청크 → Diart로 전달"""
    global diarization
    if diarization is not None:
        diarization.feed_audio(audio_chunk)


def process_text(text):
    """최종 변환 결과 출력 및 WebSocket 전송"""
    global diarization, conversation_log

    if not text.strip():
        return

    timestamp = datetime.now().strftime("%H:%M")

    # 화자 라벨 가져오기
    if diarization is not None:
        speaker_label = diarization.get_speaker_label()
    else:
        speaker_label = "미지정"

    # 대화 기록
    message_data = {
        "timestamp": timestamp,
        "speaker": speaker_label,
        "text": text.strip()
    }
    conversation_log.append(message_data)

    # 콘솔 출력
    print(f"\n[{timestamp}] [{speaker_label}] {text}\n")

    # WebSocket으로 전송
    broadcast_sync({
        "type": "new_message",
        "data": message_data
    })


def realtime_update(text):
    """실시간 결과 출력 (화자 정보 포함)"""
    global diarization

    if diarization is not None:
        speaker_label = diarization.get_speaker_label()
        print(f"\r[{speaker_label}] {text}", end="", flush=True)
    else:
        print(f"\r{text}", end="", flush=True)


# ============================================================
# 메인
# ============================================================

def main():
    global diarization

    print("=" * 50)
    print("한국어 실시간 STT + Diart 화자 분할 + 웹 UI")
    print("=" * 50 + "\n")

    # 1. WebSocket 서버 시작 (별도 쓰레드)
    ws_thread = threading.Thread(target=run_websocket_server, daemon=True)
    ws_thread.start()
    print("WebSocket 서버가 백그라운드에서 실행 중입니다.\n")

    # 2. 오디오 장치 목록 출력 및 선택
    devices = list_audio_devices()
    device_index = select_device(devices)
    selected_name = next(d[1] for d in devices if d[0] == device_index)
    print(f"\n{selected_name} 사용\n")

    # 3. Diart 화자 분할 초기화
    if DIARIZATION_AVAILABLE:
        try:
            diarization = DiartSpeakerDiarization(
                sample_rate=16000,
                chunk_duration=2.0,
                device="cuda",
                tau_active=0.5,
                rho_update=0.3,
                delta_new=1.0,
            )
        except Exception as e:
            print(f"화자 분할 초기화 실패: {e}")
            diarization = None

    # 4. RealtimeSTT 설정
    print("RealtimeSTT 초기화 중...")

    recorder = AudioToTextRecorder(
        # 모델 설정
        model="small",
        language="ko",

        # GPU 설정 (RTX 3090)
        device="cuda",
        gpu_device_index=0,
        compute_type="float16",

        # 마이크 설정
        input_device_index=device_index,

        # 실시간 전사 활성화
        enable_realtime_transcription=True,
        realtime_model_type="large-v3-turbo",
        realtime_processing_pause=0.1,

        # 콜백 함수
        on_recorded_chunk=on_recorded_chunk,  # Diart로 오디오 전달
        on_recording_start=on_recording_start,
        on_recording_stop=on_recording_stop,
        on_realtime_transcription_update=realtime_update,

        # 음성 감지 설정
        silero_sensitivity=0.5,
        webrtc_sensitivity=3,
        post_speech_silence_duration=0.5,
        min_length_of_recording=0.5,
        pre_recording_buffer_duration=0.3,

        # 성능 설정
        beam_size=5,
        batch_size=16,
    )

    print("\n" + "=" * 50)
    print("준비 완료!")
    print("=" * 50)
    print("\n웹 브라우저에서 다음 주소를 여세요:")
    print("   http://localhost:8000/index.html")
    print("\n   (먼저 웹 서버를 실행해야 합니다)")
    print("   python -m http.server 8000")
    print("\n말씀하시면 실시간으로 텍스트가 웹에 표시됩니다.")
    if diarization is not None:
        print("화자 분할 기능 활성화됨 (최대 10명)")
    print("종료: Ctrl+C\n")
    print("=" * 50 + "\n")

    try:
        while True:
            recorder.text(process_text)
    except KeyboardInterrupt:
        print("\n\n프로그램을 종료합니다.")

        if conversation_log:
            print("\n" + "=" * 50)
            print("대화 기록 요약")
            print("=" * 50)
            for entry in conversation_log:
                print(f"[{entry['timestamp']}] [{entry['speaker']}] {entry['text']}")
            print("=" * 50 + "\n")

        recorder.shutdown()


if __name__ == '__main__':
    main()
