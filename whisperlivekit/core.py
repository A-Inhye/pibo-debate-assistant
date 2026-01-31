"""
core.py - WhisperLiveKit 핵심 엔진 모듈

이 모듈은 TranscriptionEngine 싱글톤 클래스를 정의합니다.
모든 AI 모델(ASR, 화자식별, 번역)을 초기화하고 관리하는 중앙 컨트롤러입니다.

주요 클래스:
    - TranscriptionEngine: 스레드 안전 싱글톤 패턴으로 모델 관리

팩토리 함수:
    - online_factory(): 연결별 ASR 온라인 프로세서 생성
    - online_diarization_factory(): 연결별 화자식별 인스턴스 생성
    - online_translation_factory(): 연결별 번역 인스턴스 생성
"""

import logging
import sys
import threading
from argparse import Namespace

# PyTorch 2.6+ weights_only 문제 해결
import torch
import torch.torch_version
torch.serialization.add_safe_globals([torch.torch_version.TorchVersion])

from whisperlivekit.local_agreement.online_asr import OnlineASRProcessor
from whisperlivekit.local_agreement.whisper_online import backend_factory
from whisperlivekit.simul_whisper import SimulStreamingASR


def update_with_kwargs(_dict, kwargs):
    """
    딕셔너리를 kwargs로 업데이트 (존재하는 키만)

    Args:
        _dict: 업데이트할 딕셔너리
        kwargs: 업데이트 소스 딕셔너리

    Returns:
        업데이트된 딕셔너리
    """
    _dict.update({
        k: v for k, v in kwargs.items() if k in _dict
    })
    return _dict


logger = logging.getLogger(__name__)

class TranscriptionEngine:
    """
    전사 엔진 싱글톤 클래스

    모든 AI 모델(ASR, 화자식별, 번역, VAD)을 초기화하고 관리합니다.
    여러 WebSocket 연결이 동일한 모델 인스턴스를 공유하여 메모리를 절약합니다.

    패턴: 스레드 안전 싱글톤 (Double-Checked Locking)

    Attributes:
        _instance: 싱글톤 인스턴스
        _initialized: 초기화 완료 플래그
        _lock: 스레드 안전성을 위한 잠금
        args: 설정 매개변수 (Namespace)
        asr: ASR 백엔드 (SimulStreamingASR 또는 기타)
        tokenizer: 토크나이저 (LocalAgreement만 해당)
        diarization_model: 화자 식별 모델 (선택)
        vac_session: VAC 세션 (선택)
        translation_model: 번역 모델 (선택)
    """
    _instance = None
    _initialized = False
    _lock = threading.Lock()  # 스레드 안전 싱글톤 잠금

    def __new__(cls, *args, **kwargs):
        """
        싱글톤 인스턴스 생성 (Double-Checked Locking)

        여러 스레드가 동시에 인스턴스를 생성하려고 할 때
        경쟁 조건(Race Condition)을 방지합니다.

        Returns:
            TranscriptionEngine: 싱글톤 인스턴스
        """
        # 첫 번째 체크: 잠금 없이 빠른 확인
        if cls._instance is None:
            with cls._lock:
                # 두 번째 체크: 잠금 내부에서 재확인
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, **kwargs):
        """
        엔진 초기화 (스레드 안전)

        여러 연결이 동시에 초기화를 시도해도 한 번만 실행됩니다.

        Args:
            **kwargs: 설정 매개변수
                - model_size (str): 모델 크기 (base, small, medium, large-v3)
                - lan (str): 소스 언어 코드 (auto, en, fr, ...)
                - backend_policy (str): 백엔드 정책 (simulstreaming, localagreement)
                - diarization (bool): 화자 식별 활성화
                - target_language (str): 번역 대상 언어
                - vac (bool): VAC (음성 활동 컨트롤러) 활성화
        """
        # 스레드 안전 초기화 체크
        with TranscriptionEngine._lock:
            if TranscriptionEngine._initialized:
                return  # 이미 초기화됨
            # 즉시 플래그 설정하여 재초기화 방지
            TranscriptionEngine._initialized = True

        # 느린 작업 중 잠금을 유지하지 않도록 잠금 외부에서 초기화 수행
        # 전역 파라미터 (서버 및 일반 설정)
        global_params = {
            "host": "localhost",  # 서버 호스트 주소
            "port": 8000,  # 서버 포트 번호
            "diarization": False,  # 화자 식별 활성화 여부
            "punctuation_split": False,  # 구두점 기반 분할
            "target_language": "",  # 번역 대상 언어 (빈 문자열 = 비활성화)
            "vac": True,  # VAC (음성 활동 컨트롤러) 활성화
            "vac_chunk_size": 0.04,  # VAC 청크 크기 (초)
            "log_level": "DEBUG",  # 로그 레벨
            "ssl_certfile": None,  # SSL 인증서 파일 경로
            "ssl_keyfile": None,  # SSL 키 파일 경로
            "forwarded_allow_ips": None,  # 리버스 프록시 허용 IP
            "transcription": True,  # 전사 활성화 여부
            "vad": True,  # VAD (음성 활동 감지) 활성화
            "pcm_input": False,  # PCM 입력 모드 (FFmpeg 우회)
            "disable_punctuation_split" : False,  # 구두점 분할 비활성화
            "diarization_backend": "sortformer",  # 화자 식별 백엔드
            "backend_policy": "simulstreaming",  # 전사 정책 (simulstreaming 또는 localagreement)
            "backend": "auto",  # ASR 백엔드 (auto, mlx-whisper, faster-whisper, whisper)
            "enable_summary": False,  # ChatGPT 요약 기능 활성화
            "summary_model": "gpt-4o",  # 요약에 사용할 ChatGPT 모델
        }
        global_params = update_with_kwargs(global_params, kwargs)

        # 전사 공통 파라미터 (ASR 모델 설정)
        transcription_common_params = {
            "warmup_file": None,  # 워밍업 파일 경로 (None = JFK 샘플 사용)
            "min_chunk_size": 0.1,  # 최소 청크 크기 (초)
            "model_size": "base",  # 모델 크기 (tiny, base, small, medium, large-v3)
            "model_cache_dir": None,  # 모델 캐시 디렉토리
            "model_dir": None,  # 로컬 모델 디렉토리
            "model_path": None,  # 직접 모델 경로 (HF 저장소 또는 로컬)
            "lora_path": None,  # LoRA 어댑터 경로 (PyTorch 백엔드만)
            "lan": "auto",  # 소스 언어 (auto = 자동 감지)
            "direct_english_translation": False,  # Whisper 직접 영어 번역
        }
        transcription_common_params = update_with_kwargs(transcription_common_params, kwargs)                                            

        # 모델 크기가 .en으로 끝나면 언어를 영어로 강제 설정
        if transcription_common_params['model_size'].endswith(".en"):
            transcription_common_params["lan"] = "en"

        # no_* 플래그를 긍정 플래그로 변환
        if 'no_transcription' in kwargs:
            global_params['transcription'] = not global_params['no_transcription']
        if 'no_vad' in kwargs:
            global_params['vad'] = not kwargs['no_vad']
        if 'no_vac' in kwargs:
            global_params['vac'] = not kwargs['no_vac']

        # 모든 파라미터를 Namespace로 병합
        self.args = Namespace(**{**global_params, **transcription_common_params})

        # 모델 인스턴스 초기화 (None으로 시작)
        self.asr = None  # ASR 백엔드
        self.tokenizer = None  # 토크나이저 (LocalAgreement만)
        self.diarization = None  # 화자 식별 모델
        self.vac_session = None  # VAC 세션 (ONNX)

        # VAC (음성 활동 컨트롤러) 로드
        if self.args.vac:
            from whisperlivekit.silero_vad_iterator import is_onnx_available

            if is_onnx_available():
                # ONNX 세션 사용 (다중 사용자에게 공유 가능, 더 빠름)
                from whisperlivekit.silero_vad_iterator import load_onnx_session
                self.vac_session = load_onnx_session()
            else:
                # ONNX 없으면 JIT 모델 사용 (연결마다 로드됨, 느림)
                logger.warning(
                    "onnxruntime이 설치되지 않았습니다. VAC는 연결마다 로드되는 JIT 모델을 사용합니다. "
                    "다중 사용자 시나리오의 경우 onnxruntime을 설치하세요: pip install onnxruntime"
                )
        backend_policy = self.args.backend_policy
        if self.args.transcription:
            if backend_policy == "simulstreaming":                 
                simulstreaming_params = {
                    "disable_fast_encoder": False,
                    "custom_alignment_heads": None,
                    "frame_threshold": 25,
                    "beams": 1,
                    "decoder_type": None,
                    "audio_max_len": 20.0,
                    "audio_min_len": 0.0,
                    "cif_ckpt_path": None,
                    "never_fire": False,
                    "init_prompt": None,
                    "static_init_prompt": None,
                    "max_context_tokens": None,
                }
                simulstreaming_params = update_with_kwargs(simulstreaming_params, kwargs)
                
                self.tokenizer = None        
                self.asr = SimulStreamingASR(
                    **transcription_common_params,
                    **simulstreaming_params,
                    backend=self.args.backend,
                )
                logger.info(
                    "Using SimulStreaming policy with %s backend",
                    getattr(self.asr, "encoder_backend", "whisper"),
                )
            else:
                
                whisperstreaming_params = {
                    "buffer_trimming": "segment",
                    "confidence_validation": False,
                    "buffer_trimming_sec": 15,
                }
                whisperstreaming_params = update_with_kwargs(whisperstreaming_params, kwargs)
                
                self.asr = backend_factory(
                    backend=self.args.backend,
                    **transcription_common_params,
                    **whisperstreaming_params,
                )
                logger.info(
                    "Using LocalAgreement policy with %s backend",
                    getattr(self.asr, "backend_choice", self.asr.__class__.__name__),
                )

        if self.args.diarization:
            # diart 백엔드만 사용 (Sortformer는 별도 저장소에서 관리)
            from whisperlivekit.diarization.diart_backend import DiartDiarization
            diart_params = {
                "segmentation_model_name": "pyannote/segmentation-3.0",
                "embedding_model_name": "pyannote/embedding",
            }
            diart_params = update_with_kwargs(diart_params, kwargs)
            self.diarization_model = DiartDiarization(
                block_duration=self.args.min_chunk_size,
                **diart_params
            )
            self.args.diarization_backend = "diart"  # 명시적으로 설정
        
        self.translation_model = None
        if self.args.target_language:
            if self.args.lan == 'auto' and backend_policy != "simulstreaming":
                raise Exception('Translation cannot be set with language auto when transcription backend is not simulstreaming')
            else:
                try:
                    from nllw import load_model
                except:
                    raise Exception('To use translation, you must install nllw: `pip install nllw`')
                translation_params = { 
                    "nllb_backend": "transformers",
                    "nllb_size": "600M"
                }
                translation_params = update_with_kwargs(translation_params, kwargs)
                self.translation_model = load_model([self.args.lan], **translation_params) #in the future we want to handle different languages for different speakers


def online_factory(args, asr):
    if args.backend_policy == "simulstreaming":
        from whisperlivekit.simul_whisper import SimulStreamingOnlineProcessor
        return SimulStreamingOnlineProcessor(asr)
    return OnlineASRProcessor(asr)
  
  
def online_diarization_factory(args, diarization_backend):
    # diart 백엔드만 사용
    return diarization_backend


def online_translation_factory(args, translation_model):
    #should be at speaker level in the future:
    #one shared nllb model for all speaker
    #one tokenizer per speaker/language
    from nllw import OnlineTranslation
    return OnlineTranslation(translation_model, [args.lan], [args.target_language])
