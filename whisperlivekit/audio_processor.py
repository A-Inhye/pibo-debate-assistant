"""
audio_processor.py - WhisperLiveKit 오디오 처리 파이프라인

이 모듈은 실시간 오디오 스트림을 처리하고 전사, 화자 식별, 번역 결과를 조합하는
핵심 파이프라인을 구현합니다.

주요 클래스:
    - AudioProcessor: 오디오 스트림 처리 및 결과 조합

주요 기능:
    - FFmpeg을 통한 오디오 포맷 변환 (WebM/Opus → PCM)
    - Silero VAD를 통한 음성 활동 감지
    - 비동기 큐를 통한 병렬 처리 (전사, 화자식별, 번역)
    - 토큰 정렬 및 결과 포맷팅
    - WebSocket을 통한 실시간 결과 전송

데이터 흐름:
    WebSocket → FFmpeg → VAD → 전사 → 화자식별 → 번역 → 정렬 → 출력
"""

import asyncio
import logging
import traceback
from time import time
from typing import Any, AsyncGenerator, List, Optional, Union

import numpy as np

from whisperlivekit.core import (TranscriptionEngine,
                                 online_diarization_factory, online_factory,
                                 online_translation_factory)
from whisperlivekit.ffmpeg_manager import FFmpegManager, FFmpegState
from whisperlivekit.silero_vad_iterator import FixedVADIterator, OnnxWrapper, load_jit_vad
from whisperlivekit.timed_objects import (ASRToken, ChangeSpeaker, FrontData,
                                          Segment, Silence, State, Transcript)
from whisperlivekit.tokens_alignment import TokensAlignment
from whisperlivekit.summary import (ConversationSummarizer, SummaryResult,
                                          TimestampSummarizer, TimestampSegmentSummary)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

SENTINEL = object()  # 스트림 종료를 나타내는 고유한 센티넬 객체
MIN_DURATION_REAL_SILENCE = 5  # 실제 침묵으로 인정할 최소 지속 시간 (초)

async def get_all_from_queue(queue: asyncio.Queue) -> Union[object, Silence, np.ndarray, List[Any]]:
    """
    큐에서 사용 가능한 모든 항목을 가져옵니다.

    배치 처리를 위해 큐에 있는 여러 항목을 한 번에 가져옵니다.
    SENTINEL이나 Silence 객체를 만나면 즉시 반환합니다.

    Args:
        queue: 항목을 가져올 asyncio.Queue

    Returns:
        - SENTINEL: 스트림 종료 신호
        - Silence: 침묵 이벤트 객체
        - np.ndarray: 연결된 오디오 청크들
        - List[Any]: 번역 토큰 리스트
    """
    items: List[Any] = []

    # 첫 번째 항목 가져오기
    first_item = await queue.get()
    queue.task_done()

    # 센티넬이면 즉시 반환 (스트림 종료)
    if first_item is SENTINEL:
        return first_item

    # Silence 객체면 즉시 반환 (침묵 이벤트)
    if isinstance(first_item, Silence):
        return first_item

    items.append(first_item)

    # 큐에 남아있는 모든 항목 가져오기 (배치 처리)
    while True:
        if not queue._queue:
            break
        next_item = queue._queue[0]

        # 센티넬이나 Silence를 만나면 중단
        if next_item is SENTINEL:
            break
        if isinstance(next_item, Silence):
            break

        items.append(await queue.get())
        queue.task_done()

    # NumPy 배열이면 연결, 아니면 리스트 반환 (번역용)
    if isinstance(items[0], np.ndarray):
        return np.concatenate(items)
    else:
        return items

class AudioProcessor:
    """
    오디오 스트림 처리기

    실시간 오디오 스트림을 처리하고 전사, 화자 식별, 번역을 수행합니다.
    각 WebSocket 연결마다 하나의 AudioProcessor 인스턴스가 생성됩니다.

    주요 기능:
        - FFmpeg을 통한 오디오 포맷 변환 (WebM/Opus → PCM s16le)
        - Silero VAD를 통한 음성 활동 감지
        - 비동기 큐를 통한 병렬 처리 파이프라인
        - 전사, 화자 식별, 번역 결과의 시간축 정렬
        - 실시간 결과 스트리밍

    처리 파이프라인:
        1. WebSocket → FFmpeg 변환 → PCM 버퍼
        2. PCM 버퍼 → VAD → 음성/침묵 감지
        3. 음성 활동 → 전사 큐 → ASR 처리
        4. ASR 결과 → 화자식별 큐 → 화자 매핑
        5. ASR 결과 → 번역 큐 → 번역 처리
        6. 모든 결과 정렬 → JSON 포맷팅 → WebSocket 전송

    Attributes:
        args: 설정 파라미터 (Namespace)
        sample_rate: 샘플레이트 (16000 Hz)
        channels: 채널 수 (1 = 모노)
        ffmpeg_manager: FFmpeg 관리자 (오디오 변환)
        vac: Silero VAD 인스턴스 (음성 활동 감지)
        transcription_queue: 전사용 비동기 큐
        diarization_queue: 화자 식별용 비동기 큐
        translation_queue: 번역용 비동기 큐
        state: 현재 처리 상태 (State 객체)
    """

    def __init__(self, **kwargs: Any) -> None:
        """
        오디오 프로세서 초기화

        Args:
            **kwargs: 설정 매개변수
                - transcription_engine (TranscriptionEngine): 전사 엔진 인스턴스 (권장)
                - 또는 TranscriptionEngine 초기화 파라미터
        """

        # TranscriptionEngine 인스턴스 가져오기 또는 생성
        if 'transcription_engine' in kwargs and isinstance(kwargs['transcription_engine'], TranscriptionEngine):
            models = kwargs['transcription_engine']
        else:
            models = TranscriptionEngine(**kwargs)

        # 오디오 처리 설정
        self.args = models.args
        self.sample_rate = 16000  # 샘플레이트 (Hz)
        self.channels = 1  # 채널 수 (모노)
        self.samples_per_sec = int(self.sample_rate * self.args.min_chunk_size)  # 청크당 샘플 수
        self.bytes_per_sample = 2  # 샘플당 바이트 수 (s16le = 16bit = 2bytes)
        self.bytes_per_sec = self.samples_per_sec * self.bytes_per_sample  # 초당 바이트 수
        self.max_bytes_per_sec = 32000 * 5  # 최대 버퍼 크기 (5초 오디오)
        self.is_pcm_input = self.args.pcm_input  # PCM 입력 모드 여부

        # 상태 관리
        self.is_stopping: bool = False  # 종료 플래그
        self.current_silence: Optional[Silence] = None  # 현재 침묵 객체
        self.state: State = State()  # 전체 처리 상태
        self.lock: asyncio.Lock = asyncio.Lock()  # 비동기 잠금 (상태 보호)
        self.sep: str = " "  # 단어 구분자 (기본값: 공백)
        self.last_response_content: FrontData = FrontData()  # 마지막 응답 내용

        self.tokens_alignment: TokensAlignment = TokensAlignment(self.state, self.args, self.sep)
        self.beg_loop: Optional[float] = None  # 처리 시작 시간

        # 모델 및 처리
        self.asr: Any = models.asr  # ASR 백엔드 (공유)
        self.vac: Optional[FixedVADIterator] = None  # VAC (음성 활동 컨트롤러)

        # VAC (음성 활동 컨트롤러) 초기화
        if self.args.vac:
            if models.vac_session is not None:
                # ONNX 세션 사용 (공유, 빠름)
                vac_model = OnnxWrapper(session=models.vac_session)
                self.vac = FixedVADIterator(vac_model)
            else:
                # JIT 모델 사용 (연결별, 느림)
                self.vac = FixedVADIterator(load_jit_vad())

        # FFmpeg 관리자 (압축 오디오 → PCM 변환)
        self.ffmpeg_manager: Optional[FFmpegManager] = None
        self.ffmpeg_reader_task: Optional[asyncio.Task] = None
        self._ffmpeg_error: Optional[str] = None

        if not self.is_pcm_input:
            # PCM 모드가 아니면 FFmpeg 사용
            self.ffmpeg_manager = FFmpegManager(
                sample_rate=self.sample_rate,
                channels=self.channels
            )
            # FFmpeg 오류 콜백 설정
            async def handle_ffmpeg_error(error_type: str):
                logger.error(f"FFmpeg 오류: {error_type}")
                self._ffmpeg_error = error_type
            self.ffmpeg_manager.on_error_callback = handle_ffmpeg_error

        # 비동기 큐 초기화
        self.transcription_queue: Optional[asyncio.Queue] = asyncio.Queue() if self.args.transcription else None
        self.diarization_queue: Optional[asyncio.Queue] = asyncio.Queue() if self.args.diarization else None
        self.translation_queue: Optional[asyncio.Queue] = asyncio.Queue() if self.args.target_language else None

        # PCM 버퍼
        self.pcm_buffer: bytearray = bytearray()  # 원시 PCM 데이터 버퍼
        self.total_pcm_samples: int = 0  # 총 처리된 샘플 수

        # 비동기 작업 (태스크)
        self.transcription_task: Optional[asyncio.Task] = None
        self.diarization_task: Optional[asyncio.Task] = None
        self.translation_task: Optional[asyncio.Task] = None
        self.watchdog_task: Optional[asyncio.Task] = None
        self.all_tasks_for_cleanup: List[asyncio.Task] = []  # 정리할 모든 작업

        # 온라인 프로세서 (연결별 인스턴스)
        self.transcription: Optional[Any] = None  # 전사 온라인 프로세서
        self.translation: Optional[Any] = None  # 번역 온라인 프로세서
        self.diarization: Optional[Any] = None  # 화자 식별 온라인 프로세서

        if self.args.transcription:
            # 전사 프로세서 생성 (SimulStreamingOnlineProcessor 또는 OnlineASRProcessor)
            self.transcription = online_factory(self.args, models.asr)
            self.sep = self.transcription.asr.sep  # 단어 구분자 설정
        if self.args.diarization:
            # 화자 식별 프로세서 생성
            self.diarization = online_diarization_factory(self.args, models.diarization_model)
        if models.translation_model:
            # 번역 프로세서 생성
            self.translation = online_translation_factory(self.args, models.translation_model)

        # 요약 프로세서 (ChatGPT API)
        self.summarizer: Optional[ConversationSummarizer] = None
        self.timestamp_summarizer: Optional[TimestampSummarizer] = None
        self.summarized_segment_indices: set = set()  # 이미 요약된 세그먼트 인덱스 추적

        logger.info(f"enable_summary 설정: {getattr(self.args, 'enable_summary', 'NOT SET')}")
        if getattr(self.args, 'enable_summary', False):
            import os
            logger.info(f"OPENAI_API_KEY 설정 여부: {'SET' if os.getenv('OPENAI_API_KEY') else 'NOT SET'}")
            try:
                # 전체 요약기 (기존)
                self.summarizer = ConversationSummarizer(
                    model=getattr(self.args, 'summary_model', 'gpt-4o'),
                    language=self.args.lan if self.args.lan != 'auto' else 'ko'
                )
                logger.info("ChatGPT 요약기 초기화 완료")

                # 타임스탬프 요약기 (실시간 세그먼트 요약)
                self.timestamp_summarizer = TimestampSummarizer(
                    model=getattr(self.args, 'summary_model', 'gpt-4o'),
                    language=self.args.lan if self.args.lan != 'auto' else 'ko'
                )
                logger.info("타임스탬프 요약기 초기화 완료")

            except Exception as e:
                import traceback
                logger.warning(f"요약기 초기화 실패: {e}")
                logger.warning(traceback.format_exc())

    async def _push_silence_event(self) -> None:
        if self.transcription_queue:
            await self.transcription_queue.put(self.current_silence)
        if self.args.diarization and self.diarization_queue:
            await self.diarization_queue.put(self.current_silence)
        if self.translation_queue:
            await self.translation_queue.put(self.current_silence)

    async def _begin_silence(self) -> None:
        if self.current_silence:
            return
        now = time() - self.beg_loop
        self.current_silence = Silence(
            is_starting=True, start=now
        )
        await self._push_silence_event()

    async def _end_silence(self) -> None:
        if not self.current_silence:
            return
        now = time() - self.beg_loop
        self.current_silence.end = now
        self.current_silence.is_starting=False
        self.current_silence.has_ended=True
        self.current_silence.compute_duration()
        if self.current_silence.duration > MIN_DURATION_REAL_SILENCE:
            self.state.new_tokens.append(self.current_silence)
        await self._push_silence_event()
        self.current_silence = None

    async def _enqueue_active_audio(self, pcm_chunk: np.ndarray) -> None:
        if pcm_chunk is None or pcm_chunk.size == 0:
            return
        if self.transcription_queue:
            await self.transcription_queue.put(pcm_chunk.copy())
        if self.args.diarization and self.diarization_queue:
            await self.diarization_queue.put(pcm_chunk.copy())

    def _slice_before_silence(self, pcm_array: np.ndarray, chunk_sample_start: int, silence_sample: Optional[int]) -> Optional[np.ndarray]:
        if silence_sample is None:
            return None
        relative_index = int(silence_sample - chunk_sample_start)
        if relative_index <= 0:
            return None
        split_index = min(relative_index, len(pcm_array))
        if split_index <= 0:
            return None
        return pcm_array[:split_index]

    def convert_pcm_to_float(self, pcm_buffer: Union[bytes, bytearray]) -> np.ndarray:
        """Convert PCM buffer in s16le format to normalized NumPy array."""
        return np.frombuffer(pcm_buffer, dtype=np.int16).astype(np.float32) / 32768.0

    async def get_current_state(self) -> State:
        """Get current state."""
        async with self.lock:
            current_time = time()

            remaining_transcription = 0
            if self.state.end_buffer > 0:
                remaining_transcription = max(0, round(current_time - self.beg_loop - self.state.end_buffer, 1))

            remaining_diarization = 0
            if self.state.tokens:
                latest_end = max(self.state.end_buffer, self.state.tokens[-1].end if self.state.tokens else 0)
                remaining_diarization = max(0, round(latest_end - self.state.end_attributed_speaker, 1))

            self.state.remaining_time_transcription = remaining_transcription
            self.state.remaining_time_diarization = remaining_diarization

            return self.state

    async def ffmpeg_stdout_reader(self) -> None:
        """Read audio data from FFmpeg stdout and process it into the PCM pipeline."""
        beg = time()
        while True:
            try:
                if self.is_stopping:
                    logger.info("Stopping ffmpeg_stdout_reader due to stopping flag.")
                    break

                state = await self.ffmpeg_manager.get_state() if self.ffmpeg_manager else FFmpegState.STOPPED
                if state == FFmpegState.FAILED:
                    logger.error("FFmpeg is in FAILED state, cannot read data")
                    break
                elif state == FFmpegState.STOPPED:
                    logger.info("FFmpeg is stopped")
                    break
                elif state != FFmpegState.RUNNING:
                    await asyncio.sleep(0.1)
                    continue

                current_time = time()
                elapsed_time = max(0.0, current_time - beg)
                buffer_size = max(int(32000 * elapsed_time), 4096)  # dynamic read
                beg = current_time

                chunk = await self.ffmpeg_manager.read_data(buffer_size)
                if not chunk:
                    # No data currently available
                    await asyncio.sleep(0.05)
                    continue

                self.pcm_buffer.extend(chunk)
                await self.handle_pcm_data()

            except asyncio.CancelledError:
                logger.info("ffmpeg_stdout_reader cancelled.")
                break
            except Exception as e:
                logger.warning(f"Exception in ffmpeg_stdout_reader: {e}")
                logger.debug(f"Traceback: {traceback.format_exc()}")
                await asyncio.sleep(0.2)

        logger.info("FFmpeg stdout processing finished. Signaling downstream processors if needed.")
        if self.transcription_queue:
            await self.transcription_queue.put(SENTINEL)
        if self.diarization:
            await self.diarization_queue.put(SENTINEL)
        if self.translation:
            await self.translation_queue.put(SENTINEL)

    async def transcription_processor(self) -> None:
        """Process audio chunks for transcription."""
        cumulative_pcm_duration_stream_time = 0.0

        while True:
            try:
                # item = await self.transcription_queue.get()
                item = await get_all_from_queue(self.transcription_queue)
                if item is SENTINEL:
                    logger.debug("Transcription processor received sentinel. Finishing.")
                    break

                asr_internal_buffer_duration_s = len(getattr(self.transcription, 'audio_buffer', [])) / self.transcription.SAMPLING_RATE
                transcription_lag_s = max(0.0, time() - self.beg_loop - self.state.end_buffer)
                asr_processing_logs = f"internal_buffer={asr_internal_buffer_duration_s:.2f}s | lag={transcription_lag_s:.2f}s |"
                stream_time_end_of_current_pcm = cumulative_pcm_duration_stream_time
                new_tokens = []
                current_audio_processed_upto = self.state.end_buffer

                if isinstance(item, Silence):
                    if item.is_starting:
                        new_tokens, current_audio_processed_upto = await asyncio.to_thread(
                            self.transcription.start_silence
                        )
                        asr_processing_logs += f" + Silence starting"
                    if item.has_ended:
                        asr_processing_logs += f" + Silence of = {item.duration:.2f}s"
                        cumulative_pcm_duration_stream_time += item.duration
                        current_audio_processed_upto = cumulative_pcm_duration_stream_time
                        self.transcription.end_silence(item.duration, self.state.tokens[-1].end if self.state.tokens else 0)
                    if self.state.tokens:
                        asr_processing_logs += f" | last_end = {self.state.tokens[-1].end} |"
                    logger.info(asr_processing_logs)
                    new_tokens = new_tokens or []
                    current_audio_processed_upto = max(current_audio_processed_upto, stream_time_end_of_current_pcm)
                elif isinstance(item, ChangeSpeaker):
                    self.transcription.new_speaker(item)
                    continue
                elif isinstance(item, np.ndarray):
                    pcm_array = item
                    logger.info(asr_processing_logs)
                    cumulative_pcm_duration_stream_time += len(pcm_array) / self.sample_rate
                    stream_time_end_of_current_pcm = cumulative_pcm_duration_stream_time
                    self.transcription.insert_audio_chunk(pcm_array, stream_time_end_of_current_pcm)
                    new_tokens, current_audio_processed_upto = await asyncio.to_thread(self.transcription.process_iter)
                    new_tokens = new_tokens or []

                _buffer_transcript = self.transcription.get_buffer()
                buffer_text = _buffer_transcript.text

                if new_tokens:
                    validated_text = self.sep.join([t.text for t in new_tokens])
                    if buffer_text.startswith(validated_text):
                        _buffer_transcript.text = buffer_text[len(validated_text):].lstrip()

                candidate_end_times = [self.state.end_buffer]

                if new_tokens:
                    candidate_end_times.append(new_tokens[-1].end)

                if _buffer_transcript.end is not None:
                    candidate_end_times.append(_buffer_transcript.end)

                candidate_end_times.append(current_audio_processed_upto)

                async with self.lock:
                    self.state.tokens.extend(new_tokens)
                    self.state.buffer_transcription = _buffer_transcript
                    self.state.end_buffer = max(candidate_end_times)
                    self.state.new_tokens.extend(new_tokens)
                    self.state.new_tokens_buffer = _buffer_transcript

                if self.translation_queue:
                    for token in new_tokens:
                        await self.translation_queue.put(token)
            except Exception as e:
                logger.warning(f"Exception in transcription_processor: {e}")
                logger.warning(f"Traceback: {traceback.format_exc()}")
                if 'pcm_array' in locals() and pcm_array is not SENTINEL : # Check if pcm_array was assigned from queue
                    self.transcription_queue.task_done()

        if self.is_stopping:
            logger.info("Transcription processor finishing due to stopping flag.")
            if self.diarization_queue:
                await self.diarization_queue.put(SENTINEL)
            if self.translation_queue:
                await self.translation_queue.put(SENTINEL)

        logger.info("Transcription processor task finished.")


    async def diarization_processor(self) -> None:
        while True:
            try:
                item = await get_all_from_queue(self.diarization_queue)
                if item is SENTINEL:
                    break
                elif type(item) is Silence:
                    if item.has_ended:
                        self.diarization.insert_silence(item.duration)
                    continue
                self.diarization.insert_audio_chunk(item)
                diarization_segments = await self.diarization.diarize()
                diar_end = 0.0
                if diarization_segments:
                    diar_end = max(getattr(s, "end", 0.0) for s in diarization_segments)
                async with self.lock:
                    self.state.new_diarization = diarization_segments
                    self.state.end_attributed_speaker = max(self.state.end_attributed_speaker, diar_end)
            except Exception as e:
                logger.warning(f"Exception in diarization_processor: {e}")
                logger.warning(f"Traceback: {traceback.format_exc()}")
        logger.info("Diarization processor task finished.")

    async def translation_processor(self) -> None:
        # the idea is to ignore diarization for the moment. We use only transcription tokens.
        # And the speaker is attributed given the segments used for the translation
        # in the future we want to have different languages for each speaker etc, so it will be more complex.
        while True:
            try:
                item = await get_all_from_queue(self.translation_queue)
                if item is SENTINEL:
                    logger.debug("Translation processor received sentinel. Finishing.")
                    break
                elif type(item) is Silence:
                    if item.is_starting:
                        new_translation, new_translation_buffer = self.translation.validate_buffer_and_reset()
                    if item.has_ended:
                        self.translation.insert_silence(item.duration)
                        continue
                elif isinstance(item, ChangeSpeaker):
                    new_translation, new_translation_buffer = self.translation.validate_buffer_and_reset()
                    pass
                else:
                    self.translation.insert_tokens(item)
                    new_translation, new_translation_buffer = await asyncio.to_thread(self.translation.process)
                async with self.lock:
                    self.state.new_translation.append(new_translation)
                    self.state.new_translation_buffer = new_translation_buffer
            except Exception as e:
                logger.warning(f"Exception in translation_processor: {e}")
                logger.warning(f"Traceback: {traceback.format_exc()}")
        logger.info("Translation processor task finished.")

    async def results_formatter(self) -> AsyncGenerator[FrontData, None]:
        """Format processing results for output."""
        while True:
            try:
                if self._ffmpeg_error:
                    yield FrontData(status="error", error=f"FFmpeg error: {self._ffmpeg_error}")
                    self._ffmpeg_error = None
                    await asyncio.sleep(1)
                    continue

                self.tokens_alignment.update()
                lines, buffer_diarization_text, buffer_translation_text = self.tokens_alignment.get_lines(
                    diarization=self.args.diarization,
                    translation=bool(self.translation),
                    current_silence=self.current_silence
                )
                state = await self.get_current_state()

                buffer_transcription_text = state.buffer_transcription.text if state.buffer_transcription else ''

                # 타임스탬프 요약 처리 (실시간으로 새 세그먼트 요약)
                timestamp_summaries = []
                if self.timestamp_summarizer and lines:
                    timestamp_summaries = await self.process_new_segments_for_timestamp_summary(lines)

                response_status = "active_transcription"
                if not lines and not buffer_transcription_text and not buffer_diarization_text:
                    response_status = "no_audio_detected"

                response = FrontData(
                    status=response_status,
                    lines=lines,
                    buffer_transcription=buffer_transcription_text,
                    buffer_diarization=buffer_diarization_text,
                    buffer_translation=buffer_translation_text,
                    remaining_time_transcription=state.remaining_time_transcription,
                    remaining_time_diarization=state.remaining_time_diarization if self.args.diarization else 0,
                    timestamp_summaries=timestamp_summaries  # 실시간 타임스탬프 요약
                )

                should_push = (response != self.last_response_content)
                if should_push:
                    yield response
                    self.last_response_content = response

                if self.is_stopping and self._processing_tasks_done():
                    logger.info("Results formatter: All upstream processors are done and in stopping state.")

                    # 종료 전 요약 생성
                    final_summary = None
                    hierarchical_summary = None

                    if self.summarizer:
                        logger.info("요약 생성 시작...")
                        summary_result = await self.generate_summary()
                        if summary_result:
                            final_summary = summary_result.to_dict()
                            logger.info("전체 요약 완료")

                    # 계층적 요약 생성 (타임스탬프 요약 재사용)
                    if self.timestamp_summarizer:
                        logger.info("계층적 요약 생성 시작...")
                        hierarchical_summary = await self.generate_hierarchical_summary()
                        if hierarchical_summary:
                            logger.info("계층적 요약 완료")

                    # 요약이 하나라도 있으면 전송
                    if final_summary or hierarchical_summary:
                        # 최종 요약 응답 전송
                        summary_data = {}
                        if final_summary:
                            summary_data['full'] = final_summary
                        if hierarchical_summary:
                            summary_data['hierarchical'] = hierarchical_summary

                        final_response = FrontData(
                            status="summary",
                            lines=lines,
                            buffer_transcription="",
                            buffer_diarization="",
                            buffer_translation="",
                            remaining_time_transcription=0,
                            remaining_time_diarization=0,
                            summary=summary_data
                        )
                        yield final_response
                        logger.info("요약 전송 완료")

                    logger.info("Results formatter: Terminating.")
                    return

                await asyncio.sleep(0.05)

            except Exception as e:
                logger.warning(f"Exception in results_formatter. Traceback: {traceback.format_exc()}")
                await asyncio.sleep(0.5)

    async def create_tasks(self) -> AsyncGenerator[FrontData, None]:
        """Create and start processing tasks."""
        self.all_tasks_for_cleanup = []
        processing_tasks_for_watchdog: List[asyncio.Task] = []

        # If using FFmpeg (non-PCM input), start it and spawn stdout reader
        if not self.is_pcm_input:
            success = await self.ffmpeg_manager.start()
            if not success:
                logger.error("Failed to start FFmpeg manager")
                async def error_generator() -> AsyncGenerator[FrontData, None]:
                    yield FrontData(
                        status="error",
                        error="FFmpeg failed to start. Please check that FFmpeg is installed."
                    )
                return error_generator()
            self.ffmpeg_reader_task = asyncio.create_task(self.ffmpeg_stdout_reader())
            self.all_tasks_for_cleanup.append(self.ffmpeg_reader_task)
            processing_tasks_for_watchdog.append(self.ffmpeg_reader_task)

        if self.transcription:
            self.transcription_task = asyncio.create_task(self.transcription_processor())
            self.all_tasks_for_cleanup.append(self.transcription_task)
            processing_tasks_for_watchdog.append(self.transcription_task)

        if self.diarization:
            self.diarization_task = asyncio.create_task(self.diarization_processor())
            self.all_tasks_for_cleanup.append(self.diarization_task)
            processing_tasks_for_watchdog.append(self.diarization_task)

        if self.translation:
            self.translation_task = asyncio.create_task(self.translation_processor())
            self.all_tasks_for_cleanup.append(self.translation_task)
            processing_tasks_for_watchdog.append(self.translation_task)

        # Monitor overall system health
        self.watchdog_task = asyncio.create_task(self.watchdog(processing_tasks_for_watchdog))
        self.all_tasks_for_cleanup.append(self.watchdog_task)

        return self.results_formatter()

    async def watchdog(self, tasks_to_monitor: List[asyncio.Task]) -> None:
        """Monitors the health of critical processing tasks."""
        tasks_remaining: List[asyncio.Task] = [task for task in tasks_to_monitor if task]
        while True:
            try:
                if not tasks_remaining:
                    logger.info("Watchdog task finishing: all monitored tasks completed.")
                    return

                await asyncio.sleep(10)

                for i, task in enumerate(list(tasks_remaining)):
                    if task.done():
                        exc = task.exception()
                        task_name = task.get_name() if hasattr(task, 'get_name') else f"Monitored Task {i}"
                        if exc:
                            logger.error(f"{task_name} unexpectedly completed with exception: {exc}")
                        else:
                            logger.info(f"{task_name} completed normally.")
                        tasks_remaining.remove(task)

            except asyncio.CancelledError:
                logger.info("Watchdog task cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in watchdog task: {e}", exc_info=True)

    async def cleanup(self) -> None:
        """Clean up resources when processing is complete."""
        logger.info("Starting cleanup of AudioProcessor resources.")
        self.is_stopping = True
        for task in self.all_tasks_for_cleanup:
            if task and not task.done():
                task.cancel()

        created_tasks = [t for t in self.all_tasks_for_cleanup if t]
        if created_tasks:
            await asyncio.gather(*created_tasks, return_exceptions=True)
        logger.info("All processing tasks cancelled or finished.")

        if not self.is_pcm_input and self.ffmpeg_manager:
            try:
                await self.ffmpeg_manager.stop()
                logger.info("FFmpeg manager stopped.")
            except Exception as e:
                logger.warning(f"Error stopping FFmpeg manager: {e}")
        if self.diarization:
            self.diarization.close()
        logger.info("AudioProcessor cleanup complete.")

    async def generate_summary(self) -> Optional[SummaryResult]:
        """
        전체 대화를 요약 (녹음 종료 시 호출)

        Returns:
            SummaryResult: 요약 결과 (summary, speaker_summaries)
            None: 요약기가 비활성화되었거나 대화가 없는 경우
        """
        if not self.summarizer:
            logger.debug("요약기가 비활성화되어 있습니다.")
            return None

        # 현재까지의 모든 세그먼트 수집
        self.tokens_alignment.update()
        lines, _, _ = self.tokens_alignment.get_lines(
            diarization=self.args.diarization,
            translation=False,
            current_silence=None
        )

        if not lines:
            logger.info("요약할 대화가 없습니다.")
            return None

        # 세그먼트를 딕셔너리 리스트로 변환
        segments = []
        for line in lines:
            if hasattr(line, 'text') and line.text:
                segments.append({
                    "speaker": line.speaker,
                    "text": line.text,
                    "start": line.start,
                    "end": line.end
                })

        if not segments:
            return None

        logger.info(f"요약 시작: {len(segments)}개 세그먼트")

        # ChatGPT API 호출
        result = await self.summarizer.summarize(segments)
        if result:
            logger.info(f"요약 완료: {result.summary[:50]}...")
        return result

    async def process_new_segments_for_timestamp_summary(self, lines: List[Segment]) -> List[dict]:
        """
        새로운 완성된 세그먼트에 대해 타임스탬프 요약 생성 (실시간)

        Args:
            lines: 현재까지의 모든 세그먼트 (Segment 객체 리스트)

        Returns:
            List[dict]: 새로 생성된 타임스탬프 요약들
        """
        if not self.timestamp_summarizer:
            return []

        new_summaries = []

        # 새로운 세그먼트만 처리 (이미 요약된 것은 스킵)
        for idx, line in enumerate(lines):
            if idx in self.summarized_segment_indices:
                continue  # 이미 요약됨

            # 유효한 세그먼트인지 확인
            if not hasattr(line, 'text') or not line.text:
                continue
            if getattr(line, 'speaker', -1) == -2:  # 침묵 세그먼트 제외
                continue

            # 세그먼트 요약 생성
            segment_data = {
                "start": getattr(line, 'start', 0.0),
                "end": getattr(line, 'end', 0.0),
                "speaker": getattr(line, 'speaker', -1),
                "text": line.text
            }

            try:
                summary = await self.timestamp_summarizer.summarize_segment(segment_data)
                if summary:
                    new_summaries.append(summary.to_dict())
                    self.summarized_segment_indices.add(idx)
                    logger.info(f"타임스탬프 요약 생성: {summary}")
            except Exception as e:
                logger.warning(f"세그먼트 요약 실패 (idx={idx}): {e}")

        return new_summaries

    async def generate_hierarchical_summary(self) -> Optional[dict]:
        """
        계층적 요약 생성 (타임스탬프 요약 재사용)

        TimestampSummarizer가 활성화된 경우, 이미 생성된 타임스탬프 요약들을
        재사용하여 전체 요약을 생성합니다 (토큰 절감).

        Returns:
            dict: 계층적 요약 결과 또는 None
        """
        if not self.timestamp_summarizer:
            return None

        try:
            result = await self.timestamp_summarizer.summarize_full()
            if "error" not in result:
                logger.info(f"계층적 요약 완료: {result.get('summary', '')[:50]}...")
                logger.info(f"토큰 사용: {result.get('token_usage')}개, 세그먼트: {result.get('segment_count')}개")
                return result
            else:
                logger.warning(f"계층적 요약 실패: {result['error']}")
                return None
        except Exception as e:
            logger.warning(f"계층적 요약 생성 중 오류: {e}")
            return None

    def _processing_tasks_done(self) -> bool:
        """Return True when all active processing tasks have completed."""
        tasks_to_check = [
            self.transcription_task,
            self.diarization_task,
            self.translation_task,
            self.ffmpeg_reader_task,
        ]
        return all(task.done() for task in tasks_to_check if task)


    async def process_audio(self, message: Optional[bytes]) -> None:
        """
        WebSocket에서 받은 오디오 데이터 처리

        이 메서드는 WebSocket 연결에서 수신한 오디오 메시지를 처리합니다.
        PCM 모드와 압축 모드를 모두 지원합니다.

        Args:
            message: 오디오 바이너리 데이터
                - None: 스트림 종료 신호
                - bytes: PCM 또는 WebM/Opus 압축 오디오

        처리 흐름:
            1. 첫 호출 시: 타이머 시작, 초기 침묵 설정
            2. message == None: 종료 시퀀스 시작
            3. PCM 모드: 버퍼에 직접 추가 → handle_pcm_data()
            4. 압축 모드: FFmpeg에 전달 → 변환 → ffmpeg_stdout_reader()에서 처리
        """

        # 첫 호출 시 초기화
        if not self.beg_loop:
            self.beg_loop = time()  # 처리 시작 시간 기록
            self.current_silence = Silence(start=0.0, is_starting=True)  # 초기 침묵
            self.tokens_alignment.beg_loop = self.beg_loop

        # 빈 메시지 = 스트림 종료 신호
        if not message:
            logger.info("빈 오디오 메시지 수신, 종료 시퀀스 시작")
            self.is_stopping = True

            # 전사 큐에 SENTINEL 전송 (종료 신호)
            if self.transcription_queue:
                await self.transcription_queue.put(SENTINEL)

            # FFmpeg 중지
            if not self.is_pcm_input and self.ffmpeg_manager:
                await self.ffmpeg_manager.stop()

            return

        # 이미 종료 중이면 무시
        if self.is_stopping:
            logger.warning("AudioProcessor 종료 중, 들어오는 오디오 무시")
            return

        # PCM 입력 모드
        if self.is_pcm_input:
            self.pcm_buffer.extend(message)  # 버퍼에 직접 추가
            await self.handle_pcm_data()  # VAD 및 큐 삽입
        # 압축 오디오 모드 (WebM/Opus)
        else:
            if not self.ffmpeg_manager:
                logger.error("FFmpeg 관리자가 초기화되지 않음 (PCM 입력이 아닌 경우)")
                return

            # FFmpeg stdin에 오디오 쓰기
            success = await self.ffmpeg_manager.write_data(message)
            if not success:
                ffmpeg_state = await self.ffmpeg_manager.get_state()
                if ffmpeg_state == FFmpegState.FAILED:
                    logger.error("FFmpeg가 FAILED 상태, 오디오 처리 불가")
                else:
                    logger.warning("FFmpeg에 오디오 데이터 쓰기 실패")

    async def handle_pcm_data(self) -> None:
        """
        PCM 버퍼 처리 및 VAD 적용

        PCM 버퍼에 충분한 데이터가 쌓이면 처리합니다.
        Silero VAD를 사용하여 음성/침묵을 감지하고, 음성 활동 중인 오디오만
        전사 큐에 삽입합니다.

        처리 흐름:
            1. 버퍼 크기 확인 (최소 bytes_per_sec)
            2. PCM → Float32 변환 (정규화)
            3. Silero VAD 실행 → 음성/침묵 감지
            4. 음성 시작 감지: _end_silence()
            5. 음성 종료 감지: 침묵 전 청크 큐 삽입 → _begin_silence()
            6. 음성 활동 중: 전체 청크 큐 삽입
        """
        # 충분한 데이터가 쌓일 때까지 대기
        if len(self.pcm_buffer) < self.bytes_per_sec:
            return

        # 버퍼가 너무 크면 경고 (모델이 처리를 따라가지 못함)
        if len(self.pcm_buffer) > self.max_bytes_per_sec:
            logger.warning(
                f"오디오 버퍼가 너무 큼: {len(self.pcm_buffer) / self.bytes_per_sec:.2f}초. "
                f"더 작은 모델 사용을 고려하세요."
            )

        # 처리할 청크 크기 결정 (최대 5초)
        chunk_size = min(len(self.pcm_buffer), self.max_bytes_per_sec)
        # 샘플 경계에 맞춰 정렬 (2바이트 단위)
        aligned_chunk_size = (chunk_size // self.bytes_per_sample) * self.bytes_per_sample

        if aligned_chunk_size == 0:
            return

        # PCM (s16le) → Float32 변환 및 정규화 (-1.0 ~ 1.0)
        pcm_array = self.convert_pcm_to_float(self.pcm_buffer[:aligned_chunk_size])
        self.pcm_buffer = self.pcm_buffer[aligned_chunk_size:]  # 버퍼에서 제거

        # 샘플 카운팅 (타임스탬프 계산용)
        num_samples = len(pcm_array)
        chunk_sample_start = self.total_pcm_samples
        chunk_sample_end = chunk_sample_start + num_samples

        # Silero VAD 실행 (음성 활동 감지)
        res = None
        if self.args.vac:
            res = self.vac(pcm_array)

        if res is not None:
            # 음성 시작 감지 (침묵 → 음성)
            if "start" in res and self.current_silence:
                await self._end_silence()  # 침묵 종료

            # 음성 종료 감지 (음성 → 침묵)
            if "end" in res and not self.current_silence:
                # 침묵 시작 전까지의 오디오 추출
                pre_silence_chunk = self._slice_before_silence(
                    pcm_array, chunk_sample_start, res.get("end")
                )
                if pre_silence_chunk is not None and pre_silence_chunk.size > 0:
                    await self._enqueue_active_audio(pre_silence_chunk)
                await self._begin_silence()  # 침묵 시작

        # 음성 활동 중이면 전체 청크를 전사 큐에 삽입
        if not self.current_silence:
            await self._enqueue_active_audio(pcm_array)

        self.total_pcm_samples = chunk_sample_end

        # 전사나 화자식별이 비활성화된 경우 CPU 절약
        if not self.args.transcription and not self.args.diarization:
            await asyncio.sleep(0.1)
