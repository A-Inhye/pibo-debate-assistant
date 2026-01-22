# WhisperLiveKit 기반 실시간 STT + 화자 분할 백엔드
# 기존 index.html (ws://localhost:9090) 호환
# RTX 3090 + Jabra Speak2 75

import asyncio
import json
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Set, List, Dict, Any

import numpy as np
import pyaudio
import websockets

# WhisperLiveKit 경로 추가
WHISPERLIVEKIT_PATH = Path(__file__).parent.parent / "WhisperLiveKit-main" / "WhisperLiveKit-main"
sys.path.insert(0, str(WHISPERLIVEKIT_PATH))

from whisperlivekit import AudioProcessor, TranscriptionEngine

# 로깅 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ===== 설정 =====
CONFIG = {
    "ws_host": "0.0.0.0",
    "ws_port": 9090,
    "model": "large-v3-turbo",  # base, small, medium, large-v3, large-v3-turbo
    "language": "ko",
    "diarization": True,
    "diarization_backend": "sortformer",  # sortformer (권장) 또는 diart
    "sample_rate": 16000,
    "chunk_duration": 0.05,  # ← 0.1 → 0.05 (실시간↑)
    "beam_size": 5,  # ← 이 줄 추가!
}

# ===== 전역 상태 =====
connected_clients: Set = set()  # WebSocket 연결들
sent_segments: List[str] = []  # 중복 방지용


def list_audio_devices():
    """마이크 목록 출력"""
    p = pyaudio.PyAudio()
    print("\n===== 마이크 목록 =====")

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


def speaker_to_korean(speaker_id: int) -> str:
    """화자 ID를 한국어 이름으로 변환 (index.html 형식)"""
    if speaker_id == -2:
        return ""  # 침묵
    if speaker_id < 0:
        return "화자 A"
    return f"화자 {chr(65 + (speaker_id % 4))}"  # A, B, C, D


def format_timestamp() -> str:
    """현재 시간을 HH:MM 형식으로"""
    return datetime.now().strftime("%H:%M")


async def broadcast_message(message: dict):
    """모든 연결된 클라이언트에 메시지 전송"""
    if not connected_clients:
        return

    message_json = json.dumps(message, ensure_ascii=False)
    disconnected = set()

    for client in connected_clients:
        try:
            await client.send(message_json)
        except Exception as e:
            logger.warning(f"클라이언트 전송 실패: {e}")
            disconnected.add(client)

    for client in disconnected:
        connected_clients.discard(client)


async def websocket_handler(websocket):
    """WebSocket 연결 핸들러 (websockets v11+ 호환)"""
    connected_clients.add(websocket)
    logger.info(f"클라이언트 연결됨 (총 {len(connected_clients)}명)")

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("type") == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.discard(websocket)
        logger.info(f"클라이언트 연결 해제 (총 {len(connected_clients)}명)")


class RealtimeSTTProcessor:
    """WhisperLiveKit 기반 실시간 STT 프로세서"""

    def __init__(self, device_index: int):
        self.device_index = device_index
        self.sample_rate = CONFIG["sample_rate"]
        self.chunk_size = int(self.sample_rate * CONFIG["chunk_duration"])

        self.is_running = False
        self.audio_processor = None
        self.p = None
        self.stream = None
        self.audio_buffer = bytearray()

    async def initialize(self):
        """모델 초기화"""
        logger.info("모델 로딩 중...")

        # TranscriptionEngine 초기화 (싱글톤)
        engine = TranscriptionEngine(
            model_size=CONFIG["model"],
            lan=CONFIG["language"],
            diarization=CONFIG["diarization"],
            diarization_backend=CONFIG["diarization_backend"],
            pcm_input=True,
            vac=True,
            beam_size=CONFIG.get("beam_size", 5),  # ← 이 줄 추가!
        )

        # AudioProcessor 생성
        self.audio_processor = AudioProcessor(
            transcription_engine=engine,
        )

        logger.info("모델 로딩 완료!")

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """오디오 콜백 (PyAudio 스레드)"""
        if self.is_running:
            self.audio_buffer.extend(in_data)
        return (None, pyaudio.paContinue)

    async def start(self):
        """STT 처리 시작"""
        self.is_running = True

        # PyAudio 스트림 시작
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk_size,
            stream_callback=self._audio_callback
        )
        self.stream.start_stream()
        logger.info("마이크 캡처 시작")

        # 처리 태스크 시작
        results_generator = await self.audio_processor.create_tasks()

        # 오디오 피딩 태스크
        audio_feed_task = asyncio.create_task(self._feed_audio())

        # 결과 처리 태스크
        results_task = asyncio.create_task(self._process_results(results_generator))

        try:
            await asyncio.gather(audio_feed_task, results_task)
        except asyncio.CancelledError:
            pass

    async def _feed_audio(self):
        """오디오 버퍼에서 AudioProcessor로 데이터 전달"""
        bytes_per_chunk = self.chunk_size * 2  # 16-bit = 2 bytes per sample

        while self.is_running:
            if len(self.audio_buffer) >= bytes_per_chunk:
                # 청크 추출
                chunk = bytes(self.audio_buffer[:bytes_per_chunk])
                self.audio_buffer = self.audio_buffer[bytes_per_chunk:]

                # AudioProcessor에 전달
                await self.audio_processor.process_audio(chunk)
            else:
                await asyncio.sleep(0.01)  # 10ms 대기

    async def _process_results(self, results_generator):
        """결과 처리 및 WebSocket 브로드캐스트"""
        global sent_segments

        try:
            async for front_data in results_generator:
                if not self.is_running:
                    break

                # lines에서 확정된 세그먼트 추출
                if hasattr(front_data, 'lines') and front_data.lines:
                    for segment in front_data.lines:
                        if not segment.text or segment.speaker == -2:
                            continue

                        # 중복 체크용 키
                        seg_key = f"{segment.speaker}:{segment.text.strip()}"
                        if seg_key in sent_segments:
                            continue

                        sent_segments.append(seg_key)
                        if len(sent_segments) > 200:
                            sent_segments = sent_segments[-200:]

                        # index.html 형식으로 전송
                        message = {
                            "type": "new_message",
                            "data": {
                                "timestamp": format_timestamp(),
                                "speaker": speaker_to_korean(segment.speaker),
                                "text": segment.text.strip()
                            }
                        }
                        await broadcast_message(message)
                        logger.info(f"[{message['data']['speaker']}] {message['data']['text']}")

                # 버퍼 상태 로깅 (디버그용)
                if front_data.buffer_transcription:
                    logger.debug(f"[버퍼] {front_data.buffer_transcription}")

        except Exception as e:
            logger.error(f"결과 처리 오류: {e}", exc_info=True)

    async def stop(self):
        """STT 처리 중지"""
        self.is_running = False

        # 종료 신호 전송
        if self.audio_processor:
            await self.audio_processor.process_audio(None)
            await self.audio_processor.cleanup()

        # PyAudio 정리
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.p:
            self.p.terminate()

        logger.info("STT 프로세서 중지")


async def main():
    """메인 함수"""
    print("\n" + "=" * 50)
    print("WhisperLiveKit 실시간 STT + 화자 분할")
    print("=" * 50)
    print(f"모델: {CONFIG['model']}")
    print(f"언어: {CONFIG['language']}")
    print(f"화자 분할: {CONFIG['diarization_backend']}")
    print()

    # 1. 마이크 선택
    devices = list_audio_devices()
    device_index = select_device(devices)
    selected_name = next(d[1] for d in devices if d[0] == device_index)
    print(f"\n선택된 마이크: {selected_name}\n")

    # 2. STT 프로세서 초기화
    processor = RealtimeSTTProcessor(device_index)
    await processor.initialize()

    # 3. WebSocket 서버 시작
    ws_server = await websockets.serve(
        websocket_handler,
        CONFIG["ws_host"],
        CONFIG["ws_port"]
    )
    print(f"\nWebSocket 서버 시작: ws://localhost:{CONFIG['ws_port']}")
    print("브라우저에서 index.html을 열어주세요")
    print("종료: Ctrl+C\n")

    # 4. STT 처리 시작
    try:
        await processor.start()
    except KeyboardInterrupt:
        print("\n종료 중...")
    finally:
        await processor.stop()
        ws_server.close()
        await ws_server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n프로그램 종료")
