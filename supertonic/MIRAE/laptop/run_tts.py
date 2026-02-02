# run_tts.py
import os
import sys

# 같은 폴더의 tts_core import
from tts_core import TTSService


def _read_text_from_default_file() -> str:
    # 기존 run_tts.py가 읽던 input.txt 경로 유지
    input_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "raspberrypi",
        "input.txt"
    )
    with open(input_path, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    # 1) 인자로 텍스트가 들어오면 그걸 우선 사용
    # 2) 없으면 기존처럼 input.txt를 읽음
    if len(sys.argv) >= 2:
        text = " ".join(sys.argv[1:]).strip()
    else:
        text = _read_text_from_default_file().strip()

    if not text:
        print("⚠️ 입력 텍스트가 비어 있습니다.")
        sys.exit(0)

    svc = TTSService()
    # 단독 실행에서는 동기 실행이 필요하므로 speak_async 후 join으로 대기
    svc.speak_async(text)

    # 작업이 끝날 때까지 대기
    while svc.is_running():
        pass
