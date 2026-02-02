# pibo_tts_server.py
# 파이보(라즈베리파이)에서 실행하는 TTS 재생 서버
# AI 응답 텍스트를 받으면 노트북의 TTS API를 호출하고 음성을 재생합니다.

import os
import subprocess
import threading
import queue
from fastapi import FastAPI
from pydantic import BaseModel
import requests
import uvicorn

# ===== 설정 =====
LAPTOP_IP = "172.20.10.2"  # 노트북 IP (TTS API 서버) - 핫스팟 연결
LAPTOP_PORT = 8000         # TTS API 포트
PIBO_PORT = 8080           # 파이보 서버 포트

app = FastAPI(title="Pibo TTS Server")

TEMP_DIR = os.path.join(os.path.dirname(__file__), "_tmp_audio")
os.makedirs(TEMP_DIR, exist_ok=True)


class SpeakRequest(BaseModel):
    text: str


def fetch_streaming(text: str, audio_queue: queue.Queue):
    """노트북 TTS API에서 스트리밍으로 음성 받기"""
    api_url = f"http://{LAPTOP_IP}:{LAPTOP_PORT}/tts-stream"
    print(f"[TTS] 노트북 API 호출: {api_url}")
    print(f"[TTS] 텍스트: {text[:50]}...")

    try:
        response = requests.post(
            api_url,
            params={"text": text},
            stream=True,
            timeout=60
        )

        if response.status_code != 200:
            print(f"[TTS] API 오류: {response.status_code}")
            audio_queue.put(None)
            return

        chunk_idx = 0
        buffer = b''

        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue

            buffer += chunk

            while len(buffer) >= 4:
                chunk_size = int.from_bytes(buffer[:4], byteorder='big')

                if len(buffer) < 4 + chunk_size:
                    break

                chunk_data = buffer[4:4+chunk_size]
                buffer = buffer[4+chunk_size:]

                chunk_idx += 1

                temp_file = os.path.join(TEMP_DIR, f"chunk_{chunk_idx}.wav")
                with open(temp_file, "wb") as f:
                    f.write(chunk_data)

                print(f"[TTS] 청크 {chunk_idx} 수신 ({len(chunk_data)} bytes)")
                audio_queue.put((chunk_idx, temp_file))

        audio_queue.put(None)
        print("[TTS] 모든 청크 수신 완료")

    except requests.exceptions.RequestException as e:
        print(f"[TTS] 연결 오류: {e}")
        audio_queue.put(None)


def play_audio(audio_queue: queue.Queue):
    """큐에서 오디오 파일을 받아 순서대로 재생"""
    print("[TTS] 재생 시작")

    while True:
        item = audio_queue.get()

        if item is None:
            print("[TTS] 재생 완료")
            break

        idx, audio_file = item
        print(f"[TTS] 재생 중: 청크 {idx}")

        # aplay로 재생 (라즈베리파이)
        subprocess.run(
            ["aplay", audio_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # 재생 후 삭제
        if os.path.exists(audio_file):
            os.remove(audio_file)


def speak_text(text: str):
    """텍스트를 TTS로 변환하여 재생 (비동기)"""
    audio_queue = queue.Queue(maxsize=3)

    fetch_thread = threading.Thread(
        target=fetch_streaming,
        args=(text, audio_queue),
        daemon=True
    )

    play_thread = threading.Thread(
        target=play_audio,
        args=(audio_queue,),
        daemon=True
    )

    fetch_thread.start()
    play_thread.start()

    # 백그라운드에서 실행 (API 응답은 즉시 반환)
    # 필요시 join()으로 대기 가능


@app.post("/speak")
async def speak(request: SpeakRequest):
    """
    AI 응답 텍스트를 받아 TTS로 재생
    """
    text = request.text.strip()
    if not text:
        return {"status": "error", "message": "텍스트가 비어있습니다"}

    # 백그라운드에서 TTS 실행
    thread = threading.Thread(
        target=speak_text,
        args=(text,),
        daemon=True
    )
    thread.start()

    return {"status": "ok", "message": "TTS 재생 시작"}


@app.get("/health")
async def health():
    """서버 상태 확인"""
    return {"status": "ok"}


if __name__ == "__main__":
    print(f"[Pibo TTS Server] 시작: http://0.0.0.0:{PIBO_PORT}")
    print(f"[Pibo TTS Server] 노트북 TTS API: http://{LAPTOP_IP}:{LAPTOP_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PIBO_PORT)
