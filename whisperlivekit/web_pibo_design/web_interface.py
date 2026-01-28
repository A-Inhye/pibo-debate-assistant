"""
web_interface.py - 파이보 프로젝트 커스텀 디자인 웹 인터페이스 HTML 생성

사용자 제안 디자인을 기반으로 한 웹 UI를 제공합니다.
모든 에셋을 인라인으로 임베드하여 외부 파일 의존성을 제거합니다.

사용법:
    from whisperlivekit.web_pibo_design.web_interface import get_inline_ui_html
    html = get_inline_ui_html()
"""

import base64
import importlib.resources as resources
import logging

logger = logging.getLogger(__name__)

def get_web_interface_html():
    """
    웹 인터페이스 HTML 로드 (기본)
    """
    try:
        with resources.files('whisperlivekit.web_pibo_design').joinpath('live_transcription.html').open('r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error loading web interface HTML: {e}")
        return "<html><body><h1>Error loading interface</h1></body></html>"

def get_inline_ui_html():
    """
    완전한 웹 인터페이스 HTML 생성 (모든 에셋 임베드)
    """
    try:
        # 1. HTML, CSS, JavaScript 메인 파일 로드
        with resources.files('whisperlivekit.web_pibo_design').joinpath('live_transcription.html').open('r', encoding='utf-8') as f:
            html_content = f.read()
        with resources.files('whisperlivekit.web_pibo_design').joinpath('live_transcription.css').open('r', encoding='utf-8') as f:
            css_content = f.read()
        with resources.files('whisperlivekit.web_pibo_design').joinpath('live_transcription.js').open('r', encoding='utf-8') as f:
            js_content = f.read()

        # 2. AudioWorklet과 Web Worker 코드 로드
        with resources.files('whisperlivekit.web_pibo_design').joinpath('pcm_worklet.js').open('r', encoding='utf-8') as f:
            worklet_code = f.read()
        with resources.files('whisperlivekit.web_pibo_design').joinpath('recorder_worker.js').open('r', encoding='utf-8') as f:
            worker_code = f.read()

        # 3. JavaScript 코드 변환: 외부 파일 참조 → Blob URL
        # pcm_worklet.js를 Blob URL로 인라인화 (AudioWorklet 모듈)
        js_content = js_content.replace(
            'await audioContext.audioWorklet.addModule("/web/pcm_worklet.js");',
            'const workletBlob = new Blob([`' + worklet_code + '`], { type: "application/javascript" });\n' +
            'const workletUrl = URL.createObjectURL(workletBlob);\n' +
            'await audioContext.audioWorklet.addModule(workletUrl);'
        )
        # recorder_worker.js를 Blob URL로 인라인화 (Web Worker)
        js_content = js_content.replace(
            'recorderWorker = new Worker("/web/recorder_worker.js");',
            'const workerBlob = new Blob([`' + worker_code + '`], { type: "application/javascript" });\n' +
            'const workerUrl = URL.createObjectURL(workerBlob);\n' +
            'recorderWorker = new Worker(workerUrl);'
        )

        # 4. HTML 조립: 외부 참조를 인라인 코드로 대체
        # CSS 외부 링크 → 인라인 <style>
        html_content = html_content.replace(
            '<link rel="stylesheet" href="live_transcription.css" />',
            f'<style>\n{css_content}\n</style>'
        )

        # JavaScript 외부 링크 → 인라인 <script>
        html_content = html_content.replace(
            '<script src="live_transcription.js"></script>',
            f'<script>\n{js_content}\n</script>'
        )

        # 5. 완전한 HTML 반환
        return html_content

    except Exception as e:
        logger.error(f"Error creating embedded web interface: {e}")
        return "<html><body><h1>Error loading embedded interface</h1></body></html>"


if __name__ == '__main__':
    import pathlib

    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from starlette.staticfiles import StaticFiles

    import whisperlivekit.web_pibo_design as webpkg

    app = FastAPI()
    web_dir = pathlib.Path(webpkg.__file__).parent
    app.mount("/web", StaticFiles(directory=str(web_dir)), name="web")

    @app.get("/")
    async def get():
        return HTMLResponse(get_inline_ui_html())

    uvicorn.run(app=app)
