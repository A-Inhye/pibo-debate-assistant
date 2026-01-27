"""
ffmpeg_manager.py - FFmpeg 프로세스 관리자

이 모듈은 FFmpeg 서브프로세스를 관리하여 실시간 오디오 포맷 변환을 수행합니다.
WebSocket으로 수신한 WebM/Opus 오디오를 Whisper가 처리할 수 있는 PCM s16le 포맷으로 변환합니다.

주요 클래스:
    - FFmpegState: FFmpeg 프로세스 상태 관리 (Enum)
    - FFmpegManager: FFmpeg 프로세스 생명주기 관리

변환 과정:
    WebSocket (WebM/Opus) → FFmpeg stdin → FFmpeg stdout (PCM s16le) → Whisper

특징:
    - 비동기 파이프 I/O (asyncio.subprocess)
    - 상태 기반 프로세스 관리 (STOPPED, STARTING, RUNNING, RESTARTING, FAILED)
    - 자동 stderr 로깅 (FFmpeg 오류 감지)
    - 재시작 메커니즘 (오류 복구)

사용법:
    manager = FFmpegManager(sample_rate=16000, channels=1)
    await manager.start()
    await manager.write_data(webm_audio_chunk)
    pcm_data = await manager.read_data(3200)  # 0.1초분 (16kHz mono)
    await manager.stop()
"""

import asyncio
import contextlib
import logging
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

ERROR_INSTALL_INSTRUCTIONS = f"""
{'='*50}
FFmpeg is not installed or not found in your system's PATH.
Alternative Solution: You can still use WhisperLiveKit without FFmpeg by adding the --pcm-input parameter. Note that when using this option, audio will not be compressed between the frontend and backend, which may result in higher bandwidth usage.

If you want to install FFmpeg:

# Ubuntu/Debian:
sudo apt update && sudo apt install ffmpeg

# macOS (using Homebrew):
brew install ffmpeg

# Windows:
# 1. Download the latest static build from https://ffmpeg.org/download.html
# 2. Extract the archive (e.g., to C:\\FFmpeg).
# 3. Add the 'bin' directory (e.g., C:\\FFmpeg\\bin) to your system's PATH environment variable.

After installation, please restart the application.
{'='*50}
"""

class FFmpegState(Enum):
    """
    FFmpeg 프로세스 상태 열거형

    FFmpegManager의 현재 상태를 추적하여 동시성 제어 및 오류 처리를 수행합니다.

    States:
        STOPPED: 프로세스가 종료되었거나 아직 시작되지 않음
        STARTING: 프로세스 시작 중 (subprocess 생성 단계)
        RUNNING: 정상 실행 중 (데이터 읽기/쓰기 가능)
        RESTARTING: 재시작 진행 중 (stop → start)
        FAILED: 오류로 인한 실패 상태 (FFmpeg 설치 안됨 또는 프로세스 오류)

    상태 전이:
        STOPPED → STARTING → RUNNING
        RUNNING → RESTARTING → RUNNING
        * → FAILED (오류 시 언제든지)
        * → STOPPED (stop() 호출 시)
    """
    STOPPED = "stopped"      # 프로세스 종료 상태
    STARTING = "starting"    # 프로세스 시작 중
    RUNNING = "running"      # 정상 실행 중
    RESTARTING = "restarting"  # 재시작 중
    FAILED = "failed"        # 실패 상태

class FFmpegManager:
    """
    FFmpeg 서브프로세스 관리자

    FFmpeg를 비동기 서브프로세스로 실행하여 실시간 오디오 포맷 변환을 수행합니다.
    WebSocket으로 수신한 압축 오디오(WebM/Opus)를 PCM s16le로 변환하여
    Whisper 모델이 처리할 수 있도록 합니다.

    아키텍처:
        - stdin (pipe:0): 클라이언트로부터 받은 압축 오디오 입력
        - stdout (pipe:1): 변환된 PCM 오디오 출력
        - stderr (pipe): FFmpeg 오류 메시지 (백그라운드에서 로깅)

    동시성:
        - asyncio.Lock을 사용하여 상태 변경을 스레드 안전하게 보호
        - 각 AudioProcessor 인스턴스마다 하나의 FFmpegManager 생성

    오류 처리:
        - FFmpeg 설치 확인: start() 시 FileNotFoundError 처리
        - 콜백 메커니즘: on_error_callback으로 오류를 AudioProcessor에 전달
        - 자동 재시작: restart() 메서드로 복구 시도

    Attributes:
        sample_rate (int): 출력 샘플레이트 (Hz, 기본값 16000)
        channels (int): 출력 채널 수 (1=모노, 2=스테레오, 기본값 1)
        process: FFmpeg 서브프로세스 객체
        _stderr_task: stderr 로깅 백그라운드 작업
        on_error_callback: 오류 발생 시 호출할 콜백 함수
        state: 현재 FFmpeg 프로세스 상태 (FFmpegState)
        _state_lock: 상태 변경 동기화 잠금
    """
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        """
        FFmpegManager 초기화

        Args:
            sample_rate (int): 출력 오디오 샘플레이트 (Hz)
                - 16000: Whisper 권장 샘플레이트 (기본값)
                - 다른 값 사용 시 Whisper가 내부적으로 리샘플링 수행
            channels (int): 출력 채널 수
                - 1: 모노 (기본값, Whisper 권장)
                - 2: 스테레오

        Note:
            초기 상태는 STOPPED이며, start()를 호출해야 FFmpeg가 시작됩니다.
        """
        # FFmpeg 출력 포맷 설정
        self.sample_rate = sample_rate  # 샘플레이트 (Hz)
        self.channels = channels  # 채널 수 (1=모노, 2=스테레오)

        # 프로세스 관리
        self.process: Optional[asyncio.subprocess.Process] = None  # FFmpeg 서브프로세스
        self._stderr_task: Optional[asyncio.Task] = None  # stderr 로깅 작업

        # 오류 콜백 (AudioProcessor가 설정)
        self.on_error_callback: Optional[Callable[[str], None]] = None

        # 상태 관리
        self.state = FFmpegState.STOPPED  # 초기 상태
        self._state_lock = asyncio.Lock()  # 상태 변경 잠금 (동시성 제어)

    async def start(self) -> bool:
        """
        FFmpeg 프로세스 시작

        FFmpeg를 서브프로세스로 실행하고 파이프를 설정합니다.
        이미 실행 중이면 무시하고 False를 반환합니다.

        FFmpeg 명령어:
            ffmpeg -hide_banner -loglevel error -i pipe:0 \
                   -f s16le -acodec pcm_s16le -ac 1 -ar 16000 \
                   pipe:1

        설명:
            - -hide_banner: FFmpeg 버전 정보 숨김
            - -loglevel error: 오류만 로깅
            - -i pipe:0: stdin으로 입력 (WebM/Opus 등)
            - -f s16le: 출력 포맷 (signed 16-bit little-endian PCM)
            - -acodec pcm_s16le: 출력 코덱 (PCM s16le)
            - -ac 1: 출력 채널 수 (1=모노)
            - -ar 16000: 출력 샘플레이트 (16kHz)
            - pipe:1: stdout으로 출력

        Returns:
            bool: 시작 성공 시 True, 실패 시 False

        오류 처리:
            - FileNotFoundError: FFmpeg가 설치되지 않음
              → ERROR_INSTALL_INSTRUCTIONS 출력
              → on_error_callback("ffmpeg_not_found") 호출
            - 기타 Exception: 프로세스 시작 실패
              → on_error_callback("start_failed") 호출
        """
        # 중복 시작 방지 (스레드 안전)
        async with self._state_lock:
            if self.state != FFmpegState.STOPPED:
                logger.warning(f"FFmpeg already running in state: {self.state}")
                return False
            self.state = FFmpegState.STARTING  # 시작 중 상태로 변경

        try:
            # FFmpeg 명령어 구성
            cmd = [
                "ffmpeg",
                "-hide_banner",  # 버전 정보 숨김
                "-loglevel", "error",  # 오류만 로깅
                "-i", "pipe:0",  # stdin으로 입력 받기
                "-f", "s16le",  # 출력 포맷: signed 16-bit little-endian PCM
                "-acodec", "pcm_s16le",  # 출력 코덱: PCM s16le
                "-ac", str(self.channels),  # 출력 채널 수
                "-ar", str(self.sample_rate),  # 출력 샘플레이트
                "pipe:1"  # stdout으로 출력
            ]

            # 서브프로세스 생성 (비동기)
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,  # stdin 파이프 생성
                stdout=asyncio.subprocess.PIPE,  # stdout 파이프 생성
                stderr=asyncio.subprocess.PIPE  # stderr 파이프 생성
            )

            # stderr 로깅 백그라운드 작업 시작
            self._stderr_task = asyncio.create_task(self._drain_stderr())

            # 상태를 RUNNING으로 변경
            async with self._state_lock:
                self.state = FFmpegState.RUNNING

            logger.info("FFmpeg started.")
            return True

        except FileNotFoundError:
            # FFmpeg가 설치되지 않음
            logger.error(ERROR_INSTALL_INSTRUCTIONS)
            async with self._state_lock:
                self.state = FFmpegState.FAILED
            if self.on_error_callback:
                await self.on_error_callback("ffmpeg_not_found")
            return False

        except Exception as e:
            # 기타 시작 오류
            logger.error(f"Error starting FFmpeg: {e}")
            async with self._state_lock:
                self.state = FFmpegState.FAILED
            if self.on_error_callback:
                await self.on_error_callback("start_failed")
            return False

    async def stop(self):
        """
        FFmpeg 프로세스 종료

        실행 중인 FFmpeg 프로세스를 안전하게 종료합니다.
        stdin을 닫고 프로세스가 종료될 때까지 기다린 후,
        stderr 로깅 작업도 취소합니다.

        종료 순서:
            1. 상태를 STOPPED로 변경 (새로운 write/read 차단)
            2. stdin 닫기 (FFmpeg에 EOF 전송)
            3. 프로세스 종료 대기
            4. stderr 작업 취소

        Note:
            이미 STOPPED 상태면 무시하고 즉시 반환합니다.
            이 메서드는 멱등성이 보장됩니다 (여러 번 호출해도 안전).
        """
        # 중복 종료 방지
        async with self._state_lock:
            if self.state == FFmpegState.STOPPED:
                return  # 이미 종료됨
            self.state = FFmpegState.STOPPED  # 종료 상태로 변경

        # FFmpeg 프로세스 종료
        if self.process:
            # stdin 닫기 (FFmpeg에 EOF 신호 전송)
            if self.process.stdin and not self.process.stdin.is_closing():
                self.process.stdin.close()
                await self.process.stdin.wait_closed()
            # 프로세스 종료 대기
            await self.process.wait()
            self.process = None

        # stderr 로깅 작업 취소
        if self._stderr_task:
            self._stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stderr_task

        logger.info("FFmpeg stopped.")

    async def write_data(self, data: bytes) -> bool:
        """
        FFmpeg stdin에 데이터 쓰기

        클라이언트로부터 받은 압축 오디오 데이터를 FFmpeg의 stdin으로 전송합니다.
        FFmpeg는 이 데이터를 실시간으로 변환하여 stdout에 PCM 데이터를 출력합니다.

        Args:
            data (bytes): 압축 오디오 데이터 (WebM/Opus 등)
                - MediaRecorder API (브라우저): WebM 컨테이너, Opus 코덱
                - 일반적인 청크 크기: 수백 바이트 ~ 수 KB

        Returns:
            bool: 쓰기 성공 시 True, 실패 시 False

        오류 처리:
            - FFmpegState.RUNNING이 아니면 쓰기 거부
            - Exception 발생 시: on_error_callback("write_error") 호출

        Note:
            drain()을 호출하여 백프레셔(backpressure)를 처리합니다.
            stdout 읽기가 느리면 stdin 쓰기가 블록될 수 있습니다.
        """
        # 실행 중인지 확인
        async with self._state_lock:
            if self.state != FFmpegState.RUNNING:
                logger.warning(f"Cannot write, FFmpeg state: {self.state}")
                return False

        try:
            # FFmpeg stdin에 데이터 쓰기
            self.process.stdin.write(data)
            # 백프레셔 처리 (버퍼가 가득 차면 대기)
            await self.process.stdin.drain()
            return True
        except Exception as e:
            logger.error(f"Error writing to FFmpeg: {e}")
            if self.on_error_callback:
                await self.on_error_callback("write_error")
            return False

    async def read_data(self, size: int) -> Optional[bytes]:
        """
        FFmpeg stdout에서 데이터 읽기

        FFmpeg가 변환한 PCM 데이터를 stdout에서 읽어옵니다.
        이 데이터는 Whisper 모델이 직접 처리할 수 있는 형식입니다.

        Args:
            size (int): 읽을 바이트 수
                - 일반적인 값: 3200 바이트 (16kHz mono, 0.1초)
                - 계산: sample_rate * channels * bytes_per_sample * duration
                - 예: 16000 * 1 * 2 * 0.1 = 3200 바이트

        Returns:
            Optional[bytes]: PCM s16le 데이터 (성공), None (실패 또는 타임아웃)
                - PCM s16le: 16비트 리틀엔디안 부호 있는 정수
                - 각 샘플: 2바이트 (-32768 ~ 32767)

        타임아웃:
            - 20초: FFmpeg가 응답하지 않으면 타임아웃
            - 정상 작동 시 몇 밀리초 내에 응답

        오류 처리:
            - FFmpegState.RUNNING이 아니면 읽기 거부
            - TimeoutError: FFmpeg 응답 없음
            - Exception: on_error_callback("read_error") 호출

        Note:
            read()는 정확히 size 바이트를 읽지 못할 수 있습니다.
            EOF에 도달하면 더 적은 바이트를 반환할 수 있습니다.
        """
        # 실행 중인지 확인
        async with self._state_lock:
            if self.state != FFmpegState.RUNNING:
                logger.warning(f"Cannot read, FFmpeg state: {self.state}")
                return None

        try:
            # FFmpeg stdout에서 데이터 읽기 (타임아웃 20초)
            data = await asyncio.wait_for(
                self.process.stdout.read(size),
                timeout=20.0
            )
            return data
        except asyncio.TimeoutError:
            logger.warning("FFmpeg read timeout.")
            return None
        except Exception as e:
            logger.error(f"Error reading from FFmpeg: {e}")
            if self.on_error_callback:
                await self.on_error_callback("read_error")
            return None

    async def get_state(self) -> FFmpegState:
        """
        현재 FFmpeg 프로세스 상태 조회

        스레드 안전하게 현재 상태를 반환합니다.

        Returns:
            FFmpegState: 현재 프로세스 상태
                - STOPPED: 종료됨
                - STARTING: 시작 중
                - RUNNING: 실행 중
                - RESTARTING: 재시작 중
                - FAILED: 실패

        Note:
            상태 잠금을 획득하여 경쟁 조건을 방지합니다.
        """
        async with self._state_lock:
            return self.state

    async def restart(self) -> bool:
        """
        FFmpeg 프로세스 재시작

        현재 프로세스를 종료하고 새로운 프로세스를 시작합니다.
        오류 복구나 설정 변경 시 사용됩니다.

        재시작 순서:
            1. 상태를 RESTARTING으로 변경
            2. stop() 호출 (기존 프로세스 종료)
            3. 1초 대기 (리소스 정리)
            4. start() 호출 (새 프로세스 시작)

        Returns:
            bool: 재시작 성공 시 True, 실패 시 False

        오류 처리:
            - 이미 RESTARTING 중이면 False 반환 (중복 방지)
            - Exception 발생 시: 상태를 FAILED로 변경
            - on_error_callback("restart_failed") 호출

        Note:
            재시작 중에는 read/write 요청이 거부됩니다.
            stop()과 start() 사이에 1초 지연이 있어 즉시 재개되지 않습니다.
        """
        # 중복 재시작 방지
        async with self._state_lock:
            if self.state == FFmpegState.RESTARTING:
                logger.warning("Restart already in progress.")
                return False
            self.state = FFmpegState.RESTARTING  # 재시작 중 상태로 변경

        logger.info("Restarting FFmpeg...")

        try:
            # 기존 프로세스 종료
            await self.stop()
            # 잠깐 대기 (리소스 정리)
            await asyncio.sleep(1)
            # 새 프로세스 시작
            return await self.start()
        except Exception as e:
            logger.error(f"Error during FFmpeg restart: {e}")
            async with self._state_lock:
                self.state = FFmpegState.FAILED
            if self.on_error_callback:
                await self.on_error_callback("restart_failed")
            return False

    async def _drain_stderr(self):
        """
        FFmpeg stderr 로깅 (백그라운드 작업)

        FFmpeg의 stderr 스트림을 지속적으로 읽어서 로그로 출력합니다.
        FFmpeg는 모든 진단 메시지(경고, 오류)를 stderr로 출력합니다.

        동작:
            1. 무한 루프로 stderr.readline() 호출
            2. 각 라인을 DEBUG 레벨로 로깅
            3. EOF 또는 프로세스 종료 시 종료
            4. stop()에서 취소될 때까지 실행

        로깅 레벨:
            - DEBUG: 정상 메시지 (FFmpeg의 -loglevel error로 최소화)
            - 사용자가 볼 필요 없는 내부 진단 정보

        종료 조건:
            - process가 None (stop() 호출)
            - stderr가 None (파이프 닫힘)
            - readline()이 빈 바이트 반환 (EOF)
            - asyncio.CancelledError (stop()에서 취소)

        Note:
            이 작업은 start()에서 백그라운드로 시작되며,
            stop()에서 취소됩니다. 오류를 무시하고 조용히 종료합니다.
        """
        try:
            while True:
                # 프로세스 또는 stderr가 없으면 종료
                if not self.process or not self.process.stderr:
                    break
                # stderr에서 한 줄 읽기
                line = await self.process.stderr.readline()
                # EOF 도달 시 종료
                if not line:
                    break
                # 로그 출력 (디코딩 오류 무시)
                logger.debug(f"FFmpeg stderr: {line.decode(errors='ignore').strip()}")
        except asyncio.CancelledError:
            # stop()에서 취소됨 (정상)
            logger.info("FFmpeg stderr drain task cancelled.")
        except Exception as e:
            # 기타 오류 (예상치 못한 상황)
            logger.error(f"Error draining FFmpeg stderr: {e}")
