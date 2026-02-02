# tts_engine.py
import os
import uuid
import numpy as np
from scipy.io import wavfile
import re

from helper import (
    load_text_to_speech,
    load_voice_style,
)

# --------------------------------------------------
# 텍스트 정제 유틸
# --------------------------------------------------
def sanitize_text(text: str) -> str:
    """
    허용:
    - 한글, 영문, 숫자
    - 공백
    - . , ? ! ~
    그 외 특수문자 제거
    """
    text = re.sub(r'[^가-힣a-zA-Z0-9\s\.\,\?\!\~]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


class TTSEngine:
    def __init__(
        self,
        onnx_dir: str,
        voice_style_path: str,
        lang: str = "ko"
    ):
        self.lang = lang
        self.tts = load_text_to_speech(onnx_dir, use_gpu=True)
        self.voice_style = load_voice_style([voice_style_path])
        self.sample_rate = self.tts.sample_rate

    # --------------------------------------------------
    # 일반 단일 합성
    # --------------------------------------------------
    def synthesize(
        self,
        text: str,
        output_path: str,
        speed: float = 1.05,
        total_step: int = 5
    ):
        text = sanitize_text(text)

        wav, _ = self.tts(
            text=text,
            lang=self.lang,
            style=self.voice_style,
            total_step=total_step,
            speed=speed
        )

        final_wav = wav.squeeze()
        wavfile.write(output_path, self.sample_rate, final_wav)
        return output_path

    # --------------------------------------------------
    # 스트리밍 합성
    # --------------------------------------------------
    def synthesize_streaming(
        self,
        text: str,
        speed: float = 1.2,
        total_step: int = 5,
        min_chunk_length: int = 50
    ):
        sentences = self._split_sentences_only(text)
        if not sentences:
            return

        # 1️⃣ 첫 문장 즉시 생성
        first_sentence = sanitize_text(sentences[0])
        if first_sentence:
            wav, _ = self.tts(
                text=first_sentence,
                lang=self.lang,
                style=self.voice_style,
                total_step=total_step,
                speed=speed
            )
            yield wav.squeeze(), 1

        # 2️⃣ 나머지 병합
        merged_sentences = self._merge_sentences(
            sentences[1:], min_chunk_length
        )

        for i, sentence in enumerate(merged_sentences, start=2):
            sentence = sanitize_text(sentence)
            if not sentence:
                continue

            wav, _ = self.tts(
                text=sentence,
                lang=self.lang,
                style=self.voice_style,
                total_step=total_step,
                speed=speed
            )
            yield wav.squeeze(), i

    # --------------------------------------------------
    def _split_sentences_only(self, text: str):
        parts = re.split(r'([.!?]\s*)', text)

        sentences = []
        for i in range(0, len(parts) - 1, 2):
            s = parts[i] + parts[i + 1]
            if s.strip():
                sentences.append(s.strip())

        if len(parts) % 2 == 1 and parts[-1].strip():
            sentences.append(parts[-1].strip())

        return sentences

    # --------------------------------------------------
    def _merge_sentences(self, sentences, min_length: int):
        merged = []
        buffer = ""

        for sentence in sentences:
            sentence = sentence.strip()

            if sentence.endswith("!"):
                if buffer:
                    merged.append(buffer)
                    buffer = ""
                merged.append(sentence)
                continue

            buffer = f"{buffer} {sentence}".strip() if buffer else sentence

            if len(buffer) >= min_length:
                merged.append(buffer)
                buffer = ""

        if buffer:
            merged.append(buffer)

        return merged

    # --------------------------------------------------
    def synthesize_temp(self, text: str) -> str:
        import tempfile
        text = sanitize_text(text)

        filename = os.path.join(
            tempfile.gettempdir(),
            f"{uuid.uuid4()}.wav"
        )
        return self.synthesize(text, filename)
