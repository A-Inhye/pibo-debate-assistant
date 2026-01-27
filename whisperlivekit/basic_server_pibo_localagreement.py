"""
basic_server_pibo_localagreement.py - 파이보 프로젝트용 WhisperLiveKit FastAPI WebSocket 서버 (LocalAgreement 백엔드)

이 모듈은 파이보 실시간 토론 지원 시스템의 메인 서버를 구현합니다.
FastAPI와 WebSocket을 사용하여 실시간 음성 전사 서비스를 제공합니다.

주요 엔드포인트:
    - GET /: 파이보 웹 UI HTML 반환 (2분할 레이아웃)
    - WebSocket /asr: 실시간 오디오 스트리밍 및 전사 결과 전송

서버 생명주기:
    1. 시작 시: TranscriptionEngine 싱글톤 초기화 (모델 로드)
    2. 요청 처리: 각 WebSocket 연결마다 AudioProcessor 생성
    3. 종료 시: 리소스 정리

사용법:
    # Python 모듈로 실행 (권장)
    $ python -m whisperlivekit.basic_server_pibo_localagreement --model medium --language ko --diarization

    # 또는 uvicorn으로 실행
    $ uvicorn whisperlivekit.basic_server_pibo_localagreement:app --host 0.0.0.0 --port 8000

특징:
    - 좌우 2분할 웹 UI (실시간 대화 기록 + 화자별 논지 요약)
    - LocalAgreement 백엔드 사용 (SimulStreaming보다 안정적)
    - WhisperLiveKit의 모든 기능 유지 (STT, 화자 분리, 번역)
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from whisperlivekit import (AudioProcessor, TranscriptionEngine, parse_args)
from whisperlivekit.web_pibo_localagreement.web_interface import get_inline_ui_html

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger().setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# CLI 인자 파싱
args = parse_args()

# LocalAgreement 백엔드 강제 설정 (텐서 크기 오류 해결)
args.backend_policy = "localagreement"
logger.info(f"백엔드 정책: {args.backend_policy} (LocalAgreement - 안정적 버전)")

# 전역 전사 엔진 (싱글톤, 모든 연결이 공유)
transcription_engine = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 생명주기 관리

    서버 시작 시 TranscriptionEngine을 초기화하고,
    서버 종료 시 리소스를 정리합니다.

    생명주기:
        1. 시작 (yield 전): TranscriptionEngine 싱글톤 생성
           - AI 모델 로드 (ASR, 화자식별, 번역)
           - VAD 모델 로드
           - 설정 검증
        2. 실행 중: FastAPI 앱 실행
        3. 종료 (yield 후): 리소스 정리 (선택)

    Note:
        TranscriptionEngine은 싱글톤이므로 한 번만 초기화됩니다.
        모든 WebSocket 연결이 동일한 모델 인스턴스를 공유합니다.
    """
    global transcription_engine

    # 서버 시작: TranscriptionEngine 초기화
    logger.info("TranscriptionEngine 초기화 중...")
    transcription_engine = TranscriptionEngine(
        **vars(args),  # CLI 인자를 딕셔너리로 변환
    )
    logger.info("TranscriptionEngine 초기화 완료")

    yield  # 서버 실행

    # 서버 종료 시 정리 작업 (필요 시)
    logger.info("서버 종료 중...")

# FastAPI 앱 생성
app = FastAPI(lifespan=lifespan)

# CORS 미들웨어 추가 (모든 origin 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 도메인 허용 (프로덕션에서는 제한 권장)
    allow_credentials=True,  # 쿠키 허용
    allow_methods=["*"],  # 모든 HTTP 메서드 허용
    allow_headers=["*"],  # 모든 헤더 허용
)

@app.get("/")
async def get():
    """
    루트 엔드포인트: 웹 UI HTML 반환

    Returns:
        HTMLResponse: 인라인 CSS/JS가 포함된 완전한 HTML 페이지

    사용법:
        브라우저에서 http://localhost:8000 접속
    """
    return HTMLResponse(get_inline_ui_html())


async def handle_websocket_results(websocket, results_generator):
    """
    오디오 프로세서 결과를 WebSocket으로 전송

    AudioProcessor의 results_formatter()에서 생성된 결과를
    비동기적으로 소비하고 클라이언트에게 JSON으로 전송합니다.

    Args:
        websocket: WebSocket 연결 객체
        results_generator: AudioProcessor.results_formatter() 제너레이터

    처리 흐름:
        1. results_generator에서 FrontData 객체 수신
        2. FrontData.to_dict()로 JSON 변환
        3. WebSocket으로 전송
        4. 제너레이터 종료 시: "ready_to_stop" 메시지 전송

    전송 형식:
        {
            "status": "active_transcription",
            "lines": [{"text": "...", "speaker": 0, ...}, ...],
            "buffer_transcription": "현재 버퍼...",
            "buffer_diarization": "화자별 버퍼...",
            "buffer_translation": "번역 버퍼...",
            "remaining_time_transcription": 0.5,
            "remaining_time_diarization": 0.2
        }
    """
    try:
        # 결과 스트림 처리 (비동기 for 루프)
        async for response in results_generator:
            # FrontData 객체를 딕셔너리로 변환하여 전송
            await websocket.send_json(response.to_dict())

        # 제너레이터 종료 = 모든 오디오 처리 완료
        logger.info("결과 제너레이터 종료. 클라이언트에 'ready_to_stop' 전송")
        await websocket.send_json({"type": "ready_to_stop"})

    except WebSocketDisconnect:
        logger.info("결과 처리 중 WebSocket 연결 끊김 (클라이언트가 연결 종료)")
    except Exception as e:
        logger.exception(f"WebSocket 결과 핸들러 오류: {e}")


@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 엔드포인트: 실시간 오디오 전사

    클라이언트로부터 오디오 스트림을 받아 실시간으로 전사하고,
    결과를 WebSocket으로 전송합니다.

    연결 흐름:
        1. WebSocket 연결 수락
        2. AudioProcessor 인스턴스 생성 (연결별)
        3. 설정 메시지 전송 (PCM 모드 여부)
        4. 비동기 작업 시작 (전사, 화자식별, 번역)
        5. 오디오 수신 루프:
           - 클라이언트로부터 바이너리 데이터 수신
           - AudioProcessor.process_audio() 호출
        6. 연결 종료 시: 리소스 정리

    메시지 형식:
        입력 (클라이언트 → 서버):
            - Binary: PCM s16le 또는 WebM/Opus 오디오

        출력 (서버 → 클라이언트):
            - JSON: 전사 결과, 화자 정보, 번역 등

    Args:
        websocket: FastAPI WebSocket 연결 객체

    Note:
        각 WebSocket 연결마다 새로운 AudioProcessor가 생성되지만,
        TranscriptionEngine(AI 모델)은 모든 연결이 공유합니다.
    """
    global transcription_engine

    # 연결별 AudioProcessor 생성
    audio_processor = AudioProcessor(
        transcription_engine=transcription_engine,
    )

    # WebSocket 연결 수락
    await websocket.accept()
    logger.info("WebSocket 연결 열림")

    # 설정 메시지 전송 (프론트엔드에 PCM 모드 알림)
    try:
        await websocket.send_json({
            "type": "config",
            "useAudioWorklet": bool(args.pcm_input)  # True: AudioWorklet, False: MediaRecorder
        })
    except Exception as e:
        logger.warning(f"클라이언트에 설정 전송 실패: {e}")

    # 비동기 처리 작업 시작
    results_generator = await audio_processor.create_tasks()

    # 결과 전송 작업 생성 (백그라운드에서 실행)
    websocket_task = asyncio.create_task(
        handle_websocket_results(websocket, results_generator)
    )

    try:
        # 오디오 수신 루프
        while True:
            # 클라이언트로부터 바이너리 오디오 수신
            message = await websocket.receive_bytes()

            # 오디오 처리 (FFmpeg 변환, VAD, 전사 큐 삽입)
            await audio_processor.process_audio(message)

    except KeyError as e:
        # 'bytes' KeyError = 클라이언트가 연결 종료
        if 'bytes' in str(e):
            logger.warning(f"클라이언트가 연결 종료")
        else:
            logger.error(f"websocket_endpoint에서 예상치 못한 KeyError: {e}", exc_info=True)

    except WebSocketDisconnect:
        logger.info("메시지 수신 루프 중 클라이언트가 WebSocket 연결 끊음")

    except Exception as e:
        logger.error(f"websocket_endpoint 메인 루프에서 예상치 못한 오류: {e}", exc_info=True)

    finally:
        # 연결 종료 시 정리 작업
        logger.info("WebSocket 엔드포인트 정리 중...")

        # 결과 전송 작업 취소
        if not websocket_task.done():
            websocket_task.cancel()

        try:
            await websocket_task
        except asyncio.CancelledError:
            logger.info("WebSocket 결과 핸들러 작업이 취소됨")
        except Exception as e:
            logger.warning(f"websocket_task 완료 대기 중 예외 발생: {e}")

        # AudioProcessor 정리 (모든 작업 취소, FFmpeg 종료)
        await audio_processor.cleanup()
        logger.info("WebSocket 엔드포인트 정리 완료")

def main():
    """
    CLI 진입점

    이 함수는 `wlk` 또는 `whisperlivekit-server` 명령으로 실행됩니다.
    uvicorn을 사용하여 FastAPI 서버를 시작합니다.

    사용법:
        $ wlk --model base --language en
        $ whisperlivekit-server --model large-v3 --diarization

    설정:
        - host, port: CLI 인자에서 가져옴
        - SSL: --ssl-certfile, --ssl-keyfile 지정 시 HTTPS 활성화
        - 리버스 프록시: --forwarded-allow-ips 지정 시 허용

    Note:
        pyproject.toml의 [project.scripts]에 정의됨:
        - wlk = "whisperlivekit.basic_server:main"
        - whisperlivekit-server = "whisperlivekit.basic_server:main"
    """
    import uvicorn

    # Uvicorn 기본 설정
    uvicorn_kwargs = {
        "app": "whisperlivekit.basic_server_pibo_localagreement:app",  # 앱 경로 (문자열)
        "host": args.host,  # 호스트 주소 (기본값: localhost)
        "port": args.port,  # 포트 번호 (기본값: 8000)
        "reload": False,  # 자동 리로드 비활성화 (프로덕션)
        "log_level": "info",  # 로그 레벨
        "lifespan": "on",  # lifespan 이벤트 활성화
    }

    # SSL 설정 (HTTPS)
    ssl_kwargs = {}
    if args.ssl_certfile or args.ssl_keyfile:
        # 인증서와 키 파일 둘 다 필요
        if not (args.ssl_certfile and args.ssl_keyfile):
            raise ValueError(
                "--ssl-certfile과 --ssl-keyfile을 함께 지정해야 합니다."
            )
        ssl_kwargs = {
            "ssl_certfile": args.ssl_certfile,  # SSL 인증서 파일
            "ssl_keyfile": args.ssl_keyfile  # SSL 개인 키 파일
        }

    # SSL 설정 병합
    if ssl_kwargs:
        uvicorn_kwargs = {**uvicorn_kwargs, **ssl_kwargs}

    # 리버스 프록시 설정 (Nginx, Apache 등)
    if args.forwarded_allow_ips:
        uvicorn_kwargs = {
            **uvicorn_kwargs,
            "forwarded_allow_ips": args.forwarded_allow_ips  # 허용할 프록시 IP
        }

    # Uvicorn 서버 시작
    logger.info(f"서버 시작: {args.host}:{args.port}")
    uvicorn.run(**uvicorn_kwargs)

if __name__ == "__main__":
    main()
