# tts_queue_service.py
import os
import platform
import queue
import subprocess
import threading
import time
from typing import Optional, Tuple

import numpy as np
from scipy.io import wavfile

from tts_engine import TTSEngine


class TTSQueueService:
    def __init__(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        self.engine = TTSEngine(
            onnx_dir=os.path.join(self.base_dir, "assets", "onnx"),
            voice_style_path=os.path.join(self.base_dir, "assets", "voice_styles", "M1.json"),
        )

        self.filler_wav = os.path.join(self.base_dir, "assets", "fillers", "um.wav")
        self.temp_dir = os.path.join(os.path.dirname(__file__), "..", "_tmp_audio")
        os.makedirs(self.temp_dir, exist_ok=True)

        # 텍스트 큐 (LLM → TTS)
        self._text_q: "queue.Queue[Optional[str]]" = queue.Queue(maxsize=20)
        # 오디오 큐 (Producer → Consumer)
        self._audio_q: "queue.Queue[Optional[Tuple[int, str, str]]]" = queue.Queue(maxsize=3)

        self._stop_event = threading.Event()
        self._producer: Optional[threading.Thread] = None
        self._consumer: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # -----------------------------
    # Public
    # -----------------------------
    def is_running(self) -> bool:
        return (
            self._producer is not None and self._producer.is_alive()
        ) or (
            self._consumer is not None and self._consumer.is_alive()
        )

    def is_idle(self) -> bool:
        return (
            self._text_q.empty()
            and self._audio_q.empty()
            and not self.is_running()
        )

    def start_if_needed(self) -> None:
        with self._lock:
            if self.is_running():
                return

            self._stop_event.clear()

            self._producer = threading.Thread(
                target=self._producer_loop,
                daemon=True
            )
            self._consumer = threading.Thread(
                target=self._consumer_loop,
                daemon=True
            )

            self._producer.start()
            self._consumer.start()

            # filler는 최초 1회만
            threading.Thread(target=self._play_filler_once, daemon=True).start()

    def enqueue(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.start_if_needed()
        self._text_q.put(text)

    def stop(self) -> None:
        self._stop_event.set()
        try:
            while True:
                self._text_q.get_nowait()
        except queue.Empty:
            pass

        try:
            while True:
                self._audio_q.get_nowait()
        except queue.Empty:
            pass

    # -----------------------------
    # Internal
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

    def _play_filler_once(self) -> None:
        if not self._stop_event.is_set() and os.path.exists(self.filler_wav):
            self._play_wav(self.filler_wav)

    # -----------------------------
    # Producer: 합성 전용
    # -----------------------------
    def _producer_loop(self) -> None:
        idx = 0

        while not self._stop_event.is_set():
            try:
                text = self._text_q.get(timeout=0.2)
            except queue.Empty:
                if self._text_q.empty():
                    break
                continue

            idx += 1
            start = time.time()
            wav_parts = []

            for wav, _ in self.engine.synthesize_streaming(text):
                if self._stop_event.is_set():
                    return
                wav_parts.append(wav)

            if not wav_parts:
                continue

            elapsed = time.time() - start
            preview = text.replace("\n", " ")[:60]

            merged = np.concatenate(wav_parts, axis=0)
            temp_file = os.path.join(self.temp_dir, f"chunk_{idx}.wav")
            wavfile.write(temp_file, self.engine.sample_rate, merged)

            print(f"[TTS GEN {idx:02d}] {preview} ({elapsed:.2f}s)")
            self._audio_q.put((idx, preview, temp_file))

        self._audio_q.put(None)

    # -----------------------------
    # Consumer: 재생 전용
    # -----------------------------
    def _consumer_loop(self) -> None:
        while True:
            item = self._audio_q.get()
            if item is None:
                break

            idx, preview, wav_path = item
            print(f"[TTS PLAY {idx:02d}] {preview}")
            self._play_wav(wav_path)

            if os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception:
                    pass
