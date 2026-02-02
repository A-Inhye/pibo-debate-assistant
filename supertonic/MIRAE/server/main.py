#uvicorn main:app --reload 
import os
import sys
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse

# server 폴더에서 laptop/tts_core.py를 import할 수 있도록 경로 추가
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))   # MIRAE
LAPTOP_DIR = os.path.join(BASE_DIR, "laptop")
if LAPTOP_DIR not in sys.path:
    sys.path.insert(0, LAPTOP_DIR)

from tts_core import TTSService  # noqa: E402

app = FastAPI()

# 서버 시작 시 딱 1번 로딩(중요!)
tts_service = TTSService()


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <html>
    <head>
        <meta charset="utf-8" />
        <style>
            body {
                margin: 0;
                height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                background-color: #111;
                color: white;
                font-family: Arial, sans-serif;
            }
            .container { text-align: center; width: 520px; }
            textarea {
                width: 520px;
                height: 160px;
                font-size: 16px;
                padding: 12px;
                border-radius: 10px;
                border: 1px solid #333;
                background: #1b1b1b;
                color: white;
                resize: vertical;
            }
            button {
                margin: 10px 6px;
                padding: 10px 20px;
                font-size: 16px;
                border-radius: 10px;
                border: 1px solid #333;
                background: #2a2a2a;
                color: white;
                cursor: pointer;
            }
            button:hover { background: #3a3a3a; }
            .status { margin-top: 10px; opacity: 0.85; }
        </style>

        <script>
            async function speak() {
                const text = document.getElementById("text").value;
                const res = await fetch("/speak", {
                    method: "POST",
                    headers: {"Content-Type": "application/x-www-form-urlencoded"},
                    body: "text=" + encodeURIComponent(text)
                });
                const data = await res.json();
                document.getElementById("status").innerText = data.status;
            }

            async function stop() {
                const res = await fetch("/stop", { method: "POST" });
                const data = await res.json();
                document.getElementById("status").innerText = data.status;
            }
        </script>
    </head>
    <body>
        <div class="container">
            <h2>TTS Demo</h2>
            <textarea id="text" placeholder="여기에 문장을 입력하세요"></textarea><br>
            <button onclick="speak()">말하기</button>
            <button onclick="stop()">중단</button>
            <div class="status" id="status">ready</div>
        </div>
    </body>
    </html>
    """


@app.post("/speak")
def speak(text: str = Form(...)):
    # subprocess로 run_tts.py를 다시 실행하지 않고,
    # 서버에 이미 로드된 엔진(tts_service)을 재사용합니다.
    tts_service.speak_async(text)
    return {"status": "speaking"}


@app.post("/stop")
def stop():
    tts_service.stop()
    return {"status": "stopped"}
