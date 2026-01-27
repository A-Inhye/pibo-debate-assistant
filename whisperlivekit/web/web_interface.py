"""
web_interface.py - 웹 인터페이스 HTML 생성

웹 UI 리소스(HTML, CSS, JS)를 로드하고 단일 HTML로 결합합니다.
모든 에셋을 인라인으로 임베드하여 외부 파일 의존성을 제거합니다.

주요 함수:
    - get_web_interface_html(): HTML 파일만 로드
    - get_inline_ui_html(): 모든 리소스를 임베드한 완전한 HTML 반환

사용법:
    from whisperlivekit.web.web_interface import get_inline_ui_html
    html = get_inline_ui_html()
    # FastAPI에서 HTMLResponse로 반환
"""

import base64
import importlib.resources as resources
import logging

logger = logging.getLogger(__name__)

def get_web_interface_html():
    """
    웹 인터페이스 HTML 로드 (기본)

    importlib.resources를 사용하여 패키지 내부의 HTML 파일을 로드합니다.
    CSS와 JavaScript는 외부 참조로 남아있습니다.

    Returns:
        str: HTML 내용

    Note:
        단순히 HTML만 반환하므로 CSS/JS 파일이 별도로 제공되어야 합니다.
        프로덕션에서는 get_inline_ui_html()을 사용하는 것이 권장됩니다.
    """
    try:
        with resources.files('whisperlivekit.web').joinpath('live_transcription.html').open('r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error loading web interface HTML: {e}")
        return "<html><body><h1>Error loading interface</h1></body></html>"

def get_inline_ui_html():
    """
    완전한 웹 인터페이스 HTML 생성 (모든 에셋 임베드)

    HTML, CSS, JavaScript, SVG 아이콘 등 모든 리소스를 단일 HTML 파일로 결합합니다.
    외부 파일 참조를 인라인 코드로 대체하여 독립적인 HTML을 생성합니다.

    처리 과정:
        1. 리소스 로드:
           - live_transcription.html: 메인 HTML
           - live_transcription.css: 스타일시트
           - live_transcription.js: 메인 JavaScript
           - pcm_worklet.js: AudioWorklet 코드 (PCM 모드)
           - recorder_worker.js: Web Worker 코드 (MediaRecorder 모드)
           - src/*.svg: 아이콘 SVG 파일들

        2. JavaScript 코드 변환:
           - pcm_worklet.js: 외부 파일 → Blob URL로 인라인화
           - recorder_worker.js: 외부 파일 → Blob URL로 인라인화

        3. SVG 아이콘 변환:
           - SVG 파일 → Base64 data URI로 변환
           - 다크/라이트 모드 아이콘, 설정 아이콘 등

        4. HTML 조립:
           - <link> 태그 → <style> 인라인 CSS
           - <script src> 태그 → <script> 인라인 JS
           - <img src="/web/..."> → <img src="data:image/svg+xml;base64,...">

    Returns:
        str: 완전한 HTML 문서 (모든 리소스 임베드됨)
            - 외부 파일 의존성 없음
            - 단일 파일로 배포 가능
            - 브라우저에서 바로 실행 가능

    오류 처리:
        - 파일 로드 실패 시: 오류 페이지 반환
        - 로거를 통해 오류 기록

    Note:
        Blob URL을 사용하여 AudioWorklet과 Web Worker를 인라인화하므로
        Content Security Policy (CSP)에 영향을 받을 수 있습니다.
        blob: 스키마를 허용해야 합니다.

    사용 예:
        # FastAPI 서버
        @app.get("/")
        async def get():
            return HTMLResponse(get_inline_ui_html())
    """
    try:
        # 1. HTML, CSS, JavaScript 메인 파일 로드
        with resources.files('whisperlivekit.web').joinpath('live_transcription.html').open('r', encoding='utf-8') as f:
            html_content = f.read()
        with resources.files('whisperlivekit.web').joinpath('live_transcription.css').open('r', encoding='utf-8') as f:
            css_content = f.read()
        with resources.files('whisperlivekit.web').joinpath('live_transcription.js').open('r', encoding='utf-8') as f:
            js_content = f.read()

        # 2. AudioWorklet과 Web Worker 코드 로드
        with resources.files('whisperlivekit.web').joinpath('pcm_worklet.js').open('r', encoding='utf-8') as f:
            worklet_code = f.read()
        with resources.files('whisperlivekit.web').joinpath('recorder_worker.js').open('r', encoding='utf-8') as f:
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

        # 4. SVG 아이콘 파일을 Base64 data URI로 변환
        with resources.files('whisperlivekit.web').joinpath('src', 'system_mode.svg').open('r', encoding='utf-8') as f:
            system_svg = f.read()
            system_data_uri = f"data:image/svg+xml;base64,{base64.b64encode(system_svg.encode('utf-8')).decode('utf-8')}"
        with resources.files('whisperlivekit.web').joinpath('src', 'light_mode.svg').open('r', encoding='utf-8') as f:
            light_svg = f.read()
            light_data_uri = f"data:image/svg+xml;base64,{base64.b64encode(light_svg.encode('utf-8')).decode('utf-8')}"
        with resources.files('whisperlivekit.web').joinpath('src', 'dark_mode.svg').open('r', encoding='utf-8') as f:
            dark_svg = f.read()
            dark_data_uri = f"data:image/svg+xml;base64,{base64.b64encode(dark_svg.encode('utf-8')).decode('utf-8')}"
        with resources.files('whisperlivekit.web').joinpath('src', 'settings.svg').open('r', encoding='utf-8') as f:
            settings = f.read()
            settings_uri = f"data:image/svg+xml;base64,{base64.b64encode(settings.encode('utf-8')).decode('utf-8')}"

        # 5. HTML 조립: 외부 참조를 인라인 코드로 대체
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

        # SVG 이미지 외부 링크 → Base64 data URI
        # 시스템 모드 아이콘
        html_content = html_content.replace(
            '<img src="/web/src/system_mode.svg" alt="" />',
            f'<img src="{system_data_uri}" alt="" />'
        )

        # 라이트 모드 아이콘
        html_content = html_content.replace(
            '<img src="/web/src/light_mode.svg" alt="" />',
            f'<img src="{light_data_uri}" alt="" />'
        )

        # 다크 모드 아이콘
        html_content = html_content.replace(
            '<img src="/web/src/dark_mode.svg" alt="" />',
            f'<img src="{dark_data_uri}" alt="" />'
        )

        # 설정 아이콘
        html_content = html_content.replace(
            '<img src="web/src/settings.svg" alt="Settings" />',
            f'<img src="{settings_uri}" alt="" />'
        )

        # 6. 완전한 HTML 반환
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

    import whisperlivekit.web as webpkg
    
    app = FastAPI()    
    web_dir = pathlib.Path(webpkg.__file__).parent
    app.mount("/web", StaticFiles(directory=str(web_dir)), name="web")
    
    @app.get("/")
    async def get():
        return HTMLResponse(get_inline_ui_html())

    uvicorn.run(app=app)
