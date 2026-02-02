# run_tts_full.py
import os
import time
import platform
import subprocess

from tts_engine import TTSEngine

# MIRAE/laptop에서 2단계 위
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

ENGINE = TTSEngine(
    onnx_dir=os.path.join(BASE_DIR, "assets", "onnx"),
    voice_style_path=os.path.join(BASE_DIR, "assets", "voice_styles", "M1.json")
)

# 출력 파일
OUTPUT_WAV = os.path.join(os.path.dirname(__file__), "full_output.wav")


def play_audio_cross_platform(wav_path: str):
    """
    Windows / macOS / Linux 공통 오디오 재생
    """
    system = platform.system()

    if system == "Windows":
        import winsound
        winsound.PlaySound(wav_path, winsound.SND_FILENAME)

    elif system == "Darwin":  # macOS
        subprocess.run(["afplay", wav_path], check=False)

    elif system == "Linux":
        # aplay 우선, 없으면 paplay 시도
        if subprocess.call(["which", "aplay"], stdout=subprocess.DEVNULL) == 0:
            subprocess.run(["aplay", wav_path], check=False)
        elif subprocess.call(["which", "paplay"], stdout=subprocess.DEVNULL) == 0:
            subprocess.run(["paplay", wav_path], check=False)
        else:
            print("⚠️ 오디오 재생 도구(aplay/paplay)를 찾을 수 없습니다.")

    else:
        print(f"⚠️ 지원하지 않는 OS: {system}")


if __name__ == "__main__":
    input_path = os.path.join(
        os.path.dirname(__file__), "..", "raspberrypi", "input.txt"
    )

    with open(input_path, "r", encoding="utf-8") as f:
        text = f.read()

    print(f"📝 텍스트 길이: {len(text)} 글자")
    print("🔄 전체 음성 합성 시작...")

    start = time.time()

    # 전체 음성 생성
    ENGINE.synthesize(text, OUTPUT_WAV)

    elapsed = time.time() - start

    print("✅ 음성 생성 완료!")
    print(f"📁 출력 파일: {OUTPUT_WAV}")
    print(f"⏱️  합성 소요 시간: {elapsed:.2f}초")

    # 크로스플랫폼 재생
    print("🔊 재생 중...")
    play_audio_cross_platform(OUTPUT_WAV)

    print("🎉 종료")
