# tts_core.py
import os
import time
import queue
import threading
import platform
import subprocess
import re
from typing import Optional

from scipy.io import wavfile
from tts_engine import TTSEngine
import numpy as np


def split_text(text: str, first_free: bool = True, min_len: int = 40):
    """
    - 첫 청크: 길이 제한 없이, 처음 만나는 문장부호에서 즉시 분할
    - 이후 청크: 최소 min_len(기본 40자) 이후, 문장부호에서만 분할
    """

    seps = set(".,?!，。！？\n")
    chunks = []
    buf = ""

    it = iter(text)

    # 1️⃣ 첫 청크 (딜레이 최소화)
    if first_free:
        for ch in it:
            buf += ch
            if ch in seps:
                chunks.append(buf)
                buf = ""
                break

    # 2️⃣ 이후 청크 (기존 규칙: 40자 이후 문장부호)
    for ch in it:
        buf += ch

        if len(buf) < min_len:
            continue

        if ch in seps:
            chunks.append(buf)
            buf = ""

    if buf.strip():
        chunks.append(buf)

    return chunks



class TTSService:
    """
    - 서버 프로세스 시작 시 ONNX 엔진을 1회 로딩하고 재사용
    - speak_async()로 백그라운드 합성/재생 실행
    - stop() 호출 시, 다음 청크부터 재생/생성을 중단(협조적 취소)
    """

    def __init__(self):
        # laptop 폴더 기준으로 BASE_DIR = MIRAE (.., ..)
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        self.engine = TTSEngine(
            onnx_dir=os.path.join(self.base_dir, "assets", "onnx"),
            voice_style_path=os.path.join(self.base_dir, "assets", "voice_styles", "M1.json"),
        )

        self.filler_wav = os.path.join(self.base_dir, "assets", "fillers", "um.wav")

        # 임시 wav 청크 저장 폴더
        self.temp_dir = os.path.join(os.path.dirname(__file__), "..", "_tmp_audio")
        os.makedirs(self.temp_dir, exist_ok=True)

        # 실행 제어
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # -----------------------------
    # Public API
    # -----------------------------
    def is_running(self) -> bool:
        t = self._worker_thread
        return t is not None and t.is_alive()

    def stop(self) -> None:
        """현재 진행 중인 재생/생성을 중단 요청."""
        self._stop_event.set()

    def speak_async(self, text: str) -> None:
        """
        - 이미 실행 중이면 stop() 요청 후 새 작업 시작
        - 백그라운드 스레드로 수행 (FastAPI 요청을 막지 않음)
        """
        text = (text or "").strip()
        if not text:
            return

        with self._lock:
            # 기존 실행 중이면 중단 요청
            if self.is_running():
                self._stop_event.set()

            # 새 작업 준비
            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._run_pipeline,
                args=(text,),
                daemon=True
            )
            self._worker_thread.start()

    # -----------------------------
    # Internal helpers
    # -----------------------------
    def _play_wav(self, path: str) -> None:
        system = platform.system()
        try:
            if system == "Windows":
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME)
            elif system == "Darwin":
                subprocess.run(["afplay", path], check=False)
            else:
                subprocess.run(["aplay", path], check=False)
        except Exception as e:
            print(f"⚠️ 재생 실패: {e}")

    def _play_filler(self, program_start: float) -> None:
        if self._stop_event.is_set():
            return
        if not os.path.exists(self.filler_wav):
            print("⚠️ filler 음성 파일이 없습니다.")
            return

        latency = time.time() - program_start
        print("🎧 filler 재생 시작: 음...")
        print(f"⏱️ filler 재생 시작까지: {latency:.3f}초")
        self._play_wav(self.filler_wav)

    def _producer(self, text: str, audio_q: queue.Queue) -> None:
        print("\n=== TTS GENERATION START ===")

        chunks = split_text(text, first_free=True, min_len=40)

        for i, chunk in enumerate(chunks, start=1):
            if self._stop_event.is_set():
                break

            preview = chunk.replace("\n", " ")[:50]
            print(f"[GEN {i:02d}] {preview}")

            wav_parts = []
            start = time.time()

            for wav, _ in self.engine.synthesize_streaming(chunk):
                if self._stop_event.is_set():
                    break
                wav_parts.append(wav)

            if not wav_parts:
                continue

            elapsed = time.time() - start

            # 🔥 각 GEN마다 한 번씩만 출력
            print(f"   ✅ 완료 ({elapsed:.2f}초, {len(chunk)}자)")

            merged = np.concatenate(wav_parts, axis=0)
            temp_file = os.path.join(self.temp_dir, f"chunk_{i}.wav")
            wavfile.write(temp_file, self.engine.sample_rate, merged)
            audio_q.put((i, temp_file))

        audio_q.put(None)
        print("=== GENERATION END ===\n")

    def _consumer(self, audio_q: queue.Queue) -> None:
        print("=== PLAYBACK START ===")

        while True:
            item = audio_q.get()
            if item is None:
                print("=== PLAYBACK END ===")
                break

            if self._stop_event.is_set():
                idx, audio_file = item
                if os.path.exists(audio_file):
                    try:
                        os.remove(audio_file)
                    except:
                        pass

                # 큐 비우기
                while True:
                    rest = audio_q.get()
                    if rest is None:
                        break
                    _, f = rest
                    if os.path.exists(f):
                        try:
                            os.remove(f)
                        except:
                            pass
                break  # ← 이 break는 try 블록 바깥

            idx, audio_file = item
            print(f"[PLAY {idx:02d}]")
            self._play_wav(audio_file)

            if os.path.exists(audio_file):
                try:
                    os.remove(audio_file)
                except:
                    pass

    def _run_pipeline(self, text: str) -> None:
        program_start = time.time()
        print(f"📝 텍스트 로드 완료 ({len(text)}자)")
        print("=" * 60)

        audio_q: queue.Queue = queue.Queue(maxsize=3)

        # filler는 즉시 재생(별도 스레드)
        threading.Thread(
            target=self._play_filler,
            args=(program_start,),
            daemon=True
        ).start()

        # producer / consumer
        producer_t = threading.Thread(
            target=self._producer,
            args=(text, audio_q),
            daemon=True
        )
        consumer_t = threading.Thread(
            target=self._consumer,
            args=(audio_q,),
            daemon=True
        )

        producer_t.start()
        consumer_t.start()

        producer_t.join()
        consumer_t.join()

        print("=" * 60)
        if self._stop_event.is_set():
            print("🛑 중단 요청으로 종료")
        else:
            print("🎉 프로그램 종료")
