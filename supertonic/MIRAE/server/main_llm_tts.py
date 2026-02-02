import os
import sys
import threading
import time
from typing import Optional

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse

# -----------------------------
# 경로 설정 (server → laptop)
# -----------------------------
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))  # MIRAE
LAPTOP_DIR = os.path.join(BASE_DIR, "laptop")
if LAPTOP_DIR not in sys.path:
    sys.path.insert(0, LAPTOP_DIR)

from ollama_stream import stream_ollama_tokens
from sentence_stream import stream_text_chunks
from tts_queue_service import TTSQueueService

# -----------------------------
# FastAPI
# -----------------------------
app = FastAPI()

tts = TTSQueueService()

# -----------------------------
# LLM 상태 관리
# -----------------------------
_llm_thread: Optional[threading.Thread] = None
_llm_stop_event = threading.Event()
_llm_done_event = threading.Event()

_latest_text_lock = threading.Lock()
_latest_text = ""

# -----------------------------
# LLM latency 계측
# -----------------------------
_llm_start_time = 0.0
_first_token_logged = False
_first_chunk_logged = False


# -----------------------------
# util
# -----------------------------
def _set_latest_text(s: str) -> None:
    global _latest_text
    with _latest_text_lock:
        _latest_text = s


def _append_latest_text(s: str) -> None:
    global _latest_text
    with _latest_text_lock:
        _latest_text += s


def _get_latest_text() -> str:
    with _latest_text_lock:
        return _latest_text


# -----------------------------
# LLM token timing wrapper
# -----------------------------
def timed_token_stream(token_stream):
    """
    첫 토큰 도착 시간만 계측하고
    이후 토큰은 그대로 passthrough
    """
    global _first_token_logged

    for token in token_stream:
        if not _first_token_logged:
            dt = time.time() - _llm_start_time
            print(f"[LLM FIRST TOKEN] {dt:.2f}s")
            _first_token_logged = True
        yield token


# -----------------------------
# LLM worker
# -----------------------------
def _llm_worker(user_text: str) -> None:
    global _first_chunk_logged

    _llm_stop_event.clear()
    _llm_done_event.clear()
    _set_latest_text("")

    prompt = (
        "답변은 말하듯 자연스럽게, 문장 단위로 작성하세요.\n"
        f"사용자: {user_text}\n"
        "assistant: "
    )

    try:
        raw_token_stream = stream_ollama_tokens(
            prompt=prompt,
            model="qwen2.5:1.5b"
        )

        token_stream = timed_token_stream(raw_token_stream)

        for chunk in stream_text_chunks(token_stream):
            if _llm_stop_event.is_set():
                break

            if not _first_chunk_logged:
                dt = time.time() - _llm_start_time
                print(f"[LLM FIRST CHUNK → TTS] {dt:.2f}s")
                _first_chunk_logged = True

            _append_latest_text(chunk)
            tts.enqueue(chunk)

    except Exception as e:
        print("LLM ERROR:", e)

    finally:
        _llm_done_event.set()


# -----------------------------
# Web UI
# -----------------------------
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
                align-items: flex-start;
                background-color: #111;
                color: white;
                font-family: Arial, sans-serif;
                padding-top: 40px;
            }
            .container { width: 760px; }
            textarea {
                width: 100%;
                height: 120px;
                font-size: 16px;
                padding: 12px;
                border-radius: 10px;
                border: 1px solid #333;
                background: #1b1b1b;
                color: white;
                resize: vertical;
            }
            button {
                margin: 10px 6px 10px 0;
                padding: 10px 18px;
                font-size: 16px;
                border-radius: 10px;
                border: 1px solid #333;
                background: #2a2a2a;
                color: white;
                cursor: pointer;
            }
            button:hover { background: #3a3a3a; }
            .status { margin-top: 8px; opacity: 0.85; }
            pre {
                margin-top: 16px;
                padding: 12px;
                background: #1b1b1b;
                border: 1px solid #333;
                border-radius: 10px;
                white-space: pre-wrap;
                min-height: 160px;
            }
        </style>

        <script>
            let polling = null;

            async function chat() {
                const text = document.getElementById("text").value;

                await fetch("/chat", {
                    method: "POST",
                    headers: {"Content-Type": "application/x-www-form-urlencoded"},
                    body: "text=" + encodeURIComponent(text)
                });

                if (polling) clearInterval(polling);
                polling = setInterval(updateStatus, 200);
            }

            async function updateStatus() {
                const res = await fetch("/status");
                const data = await res.json();

                document.getElementById("out").innerText = data.text;
                document.getElementById("status").innerText = data.state;

                if (data.state === "idle") {
                    clearInterval(polling);
                    polling = null;
                }
            }

            async function stopAll() {
                await fetch("/stop", { method: "POST" });
                if (polling) {
                    clearInterval(polling);
                    polling = null;
                }
            }
        </script>
    </head>
    <body>
        <div class="container">
            <h2>LLM → TTS Streaming Demo</h2>
            <textarea id="text" placeholder="여기에 자연어를 입력하세요"></textarea><br>
            <button onclick="chat()">보내기</button>
            <button onclick="stopAll()">중단</button>
            <div class="status" id="status">ready</div>
            <pre id="out"></pre>
        </div>
    </body>
    </html>
    """


# -----------------------------
# API
# -----------------------------
@app.post("/chat")
def chat(text: str = Form(...)):
    global _llm_thread, _llm_start_time, _first_token_logged, _first_chunk_logged

    _llm_stop_event.set()
    tts.stop()

    _llm_start_time = time.time()
    _first_token_logged = False
    _first_chunk_logged = False
    _llm_done_event.clear()
    _set_latest_text("")

    print("[LLM START] user input received")

    _llm_thread = threading.Thread(
        target=_llm_worker,
        args=(text,),
        daemon=True
    )
    _llm_thread.start()

    return JSONResponse({"status": "running"})


@app.post("/stop")
def stop():
    _llm_stop_event.set()
    tts.stop()
    return JSONResponse({"status": "stopped"})


@app.get("/status")
def status():
    if _llm_done_event.is_set() and tts.is_idle():
        state = "idle"
    else:
        state = "running"

    return JSONResponse({
        "state": state,
        "text": _get_latest_text()
    })
