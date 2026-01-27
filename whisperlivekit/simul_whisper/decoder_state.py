"""
decoder_state.py - 디코더 상태 관리

DecoderState는 실시간 디코딩 중 모든 상태 정보를 저장합니다.
KV 캐시, 토큰 버퍼, 타임스탬프, 화자 정보 등을 포함합니다.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import torch


@dataclass
class DecoderState:
    """
    디코더 상태를 저장하는 데이터 클래스

    실시간 스트리밍 디코딩 중 필요한 모든 상태 정보를 관리합니다.
    각 온라인 프로세서 인스턴스마다 하나의 DecoderState를 가집니다.

    주요 카테고리:
        1. 캐시: KV 캐시 (self-attention, cross-attention)
        2. 토큰: 생성된 토큰, 초기 토큰, 불완전 토큰
        3. 타임스탬프: 누적 시간, 마지막 attend 프레임
        4. 세그먼트: 오디오 세그먼트 리스트
        5. 디코더 설정: 디코더 타입, 빔 크기 등
        6. AlignAtt 설정: CIF, always_fire, never_fire
        7. 화자 식별: 화자 ID

    Attributes:
        kv_cache (Dict[str, Tensor]): KV 캐시 (디코더 블록별)
        tokenizer: 토크나이저 객체
        detected_language (str): 감지된 언어 코드
        reset_tokenizer_to_auto_next_call (bool): 다음 호출 시 자동 언어 감지
        tokens (List[Tensor]): 생성된 토큰 리스트
        initial_tokens (Tensor): 초기 토큰 (언어, 작업 등)
        initial_token_length (int): 초기 토큰 길이
        sot_index (int): SOT (Start of Transcript) 인덱스
        align_source (Dict): Alignment 소스 정보
        num_align_heads (int): Alignment 헤드 수
        segments (List[Tensor]): 오디오 세그먼트 리스트
        context: 컨텍스트 버퍼 (TokenBuffer)
        pending_incomplete_tokens (List[int]): 불완전한 토큰 대기열
        global_time_offset (float): 전역 시간 오프셋
        cumulative_time_offset (float): 누적 시간 오프셋
        first_timestamp (float): 첫 타임스탬프
        last_attend_frame (int): 마지막 attend 프레임 인덱스
        speaker (int): 화자 ID (-1 = 미할당)
        log_segments (int): 로그 세그먼트 카운터
        CIFLinear (torch.nn.Module): CIF 끝말 감지 모델
        always_fire (bool): 항상 단어 경계로 간주 (CIF 없음)
        never_fire (bool): 단어 경계 감지 안 함 (CIF 없음)
        suppress_tokens_fn: 토큰 억제 함수
        token_decoder: 토큰 디코더 (beam search 등)
        decoder_type (str): 디코더 타입 ("greedy" 또는 "beam")
        inference: Inference 객체 (PyTorchInference 등)
    """

    kv_cache: Dict[str, torch.Tensor] = field(default_factory=dict)
    
    tokenizer: Any = None
    detected_language: Optional[str] = None
    reset_tokenizer_to_auto_next_call: bool = False
    
    tokens: List[torch.Tensor] = field(default_factory=list)
    initial_tokens: Optional[torch.Tensor] = None
    initial_token_length: int = 0
    sot_index: int = 0
    
    align_source: Dict[int, List[Tuple[int, int]]] = field(default_factory=dict)
    num_align_heads: int = 0
    
    segments: List[torch.Tensor] = field(default_factory=list)
    
    context: Any = None
    
    pending_incomplete_tokens: List[int] = field(default_factory=list)
    
    global_time_offset: float = 0.0
    cumulative_time_offset: float = 0.0
    first_timestamp: Optional[float] = None
    last_attend_frame: int = 0
    
    speaker: int = -1
    log_segments: int = 0
    
    CIFLinear: Optional[torch.nn.Module] = None
    always_fire: bool = False
    never_fire: bool = False
    
    suppress_tokens_fn: Any = None
    
    token_decoder: Any = None
    decoder_type: str = "greedy"
    
    inference: Any = None
    
    def clean_cache(self):
        """
        KV 캐시 정리 (각 inference 단계 후)

        GPU 메모리를 확보하기 위해 KV 캐시를 명시적으로 삭제합니다.
        Beam search 사용 시 inference 객체의 캐시도 초기화합니다.

        동작:
            1. kv_cache의 모든 텐서를 명시적으로 삭제 (del)
            2. 딕셔너리 비우기 (clear)
            3. CUDA 캐시 비우기 (GPU만 해당)
            4. Beam search 사용 시: inference.kv_cache 새로 생성
            5. Token decoder 리셋 (beam search)

        Note:
            명시적인 del과 torch.cuda.empty_cache()는
            PyTorch의 캐싱 할당자를 우회하여 메모리를 즉시 해제합니다.
            실시간 스트리밍에서 메모리 누수를 방지하는 데 중요합니다.
        """
        # KV 캐시 텐서 명시적 삭제
        if self.kv_cache:
            for key in list(self.kv_cache.keys()):
                tensor = self.kv_cache.pop(key, None)
                if tensor is not None:
                    del tensor

        # 딕셔너리 비우기
        self.kv_cache.clear()

        # GPU 캐시 강제 정리 (CUDA만)
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # Beam search 전용: inference 캐시도 같은 dict 참조하도록 유지
        if self.decoder_type == "beam" and self.inference is not None:
            # 기존: self.inference.kv_cache = {}  ← 참조 끊김!
            # 수정: 참조가 끊어진 경우 재연결
            if self.inference.kv_cache is not self.kv_cache:
                self.inference.kv_cache = self.kv_cache
            # clear()는 이미 위에서 했으므로 추가 작업 불필요

            if self.token_decoder is not None:
                self.token_decoder.reset()

    def reset(self, rewind_threshold: int = 200):
        """
        새로운 세그먼트를 위한 일시적 상태 리셋

        세그먼트 경계에서 호출되어 일부 상태만 초기화합니다.
        오디오 세그먼트와 토큰은 유지합니다.

        Args:
            rewind_threshold (int): last_attend_frame 초기화 값 (기본값 200)
                - 음수 값으로 설정하여 다음 세그먼트 시작 시
                  프레임 임계값 조건을 충족하도록 함

        리셋 항목:
            - last_attend_frame: -rewind_threshold로 설정
            - cumulative_time_offset: 0.0
            - pending_incomplete_tokens: []
            - log_segments: 증가

        유지 항목:
            - segments: 오디오 세그먼트 리스트
            - tokens: 생성된 토큰
            - kv_cache: KV 캐시
            - first_timestamp: 첫 타임스탬프
        """
        self.last_attend_frame = -rewind_threshold
        self.cumulative_time_offset = 0.0
        self.pending_incomplete_tokens = []
        self.log_segments += 1

    def full_reset(self, rewind_threshold: int = 200):
        """
        전체 리셋 (오디오 세그먼트 및 토큰 포함)

        모든 상태를 초기화합니다. 새로운 오디오 스트림 시작 시 사용합니다.

        Args:
            rewind_threshold (int): last_attend_frame 초기화 값

        리셋 항목:
            - reset()이 리셋하는 모든 항목
            - segments: 오디오 세그먼트 리스트
            - tokens: 생성된 토큰
            - kv_cache: KV 캐시
            - first_timestamp: 첫 타임스탬프

        Note:
            이 메서드는 연결 재시작 또는 긴 침묵 후 사용됩니다.
        """
        self.reset(rewind_threshold)
        self.segments = []
        self.tokens = []
        self.kv_cache = {}
        self.first_timestamp = None

