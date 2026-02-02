import os
from tts_engine import TTSEngine

# ===== 경로 설정 =====
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

FILLER_DIR = os.path.join(BASE_DIR, "assets", "fillers")
os.makedirs(FILLER_DIR, exist_ok=True)

OUTPUT_WAV = os.path.join(FILLER_DIR, "um.wav")

# ===== TTS 엔진 =====
ENGINE = TTSEngine(
    onnx_dir=os.path.join(BASE_DIR, "assets", "onnx"),
    voice_style_path=os.path.join(BASE_DIR, "assets", "voice_styles", "M1.json")
)

# ===== filler 텍스트 =====
FILLER_TEXT = "음..."

if __name__ == "__main__":
    if os.path.exists(OUTPUT_WAV):
        print(f"♻️ 기존 filler 덮어쓰기: {OUTPUT_WAV}")
    else:
        print(f"🆕 filler 새로 생성: {OUTPUT_WAV}")

    print("🎤 filler 음성 생성 중:", FILLER_TEXT)

    ENGINE.synthesize(
        text=FILLER_TEXT,
        output_path=OUTPUT_WAV,
        speed=1,        # 자연스럽게 약간 빠르게
        total_step=5
    )

    print(f"✅ filler 음성 생성 완료: {OUTPUT_WAV}")
