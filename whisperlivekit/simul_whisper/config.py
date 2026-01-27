"""
config.py - AlignAtt 정책 설정

AlignAttConfig 데이터 클래스는 SimulStreaming 정책의 모든 설정 매개변수를 정의합니다.
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class AlignAttConfig():
    """
    AlignAtt (Alignment Attention) 정책 설정

    SimulStreaming ASR의 동작을 제어하는 설정 매개변수들입니다.
    알고리즘 동작, 디코더 설정, 언어 옵션 등을 포함합니다.

    주요 매개변수:
        - frame_threshold: Cross-attention이 프레임에 집중하는 임계값 (끝말 감지)
        - audio_max_len: 최대 오디오 길이 (초)
        - decoder_type: 디코더 타입 (greedy 또는 beam)
        - cif_ckpt_path: CIF 모델 체크포인트 경로 (끝말 감지)

    Attributes:
        eval_data_path (str): 평가 데이터 경로 (사용 안 함)
        segment_length (float): 세그먼트 길이 (초, 기본값 1.0)
        frame_threshold (int): Cross-attention 프레임 임계값 (기본값 4)
            - 디코더가 오디오의 마지막 N 프레임에 집중하면 단어 경계로 간주
            - 낮을수록 더 빨리 출력 (낮은 지연), 높을수록 더 안정적
        rewind_threshold (int): 되감기 임계값 (기본값 200)
            - 세그먼트 리셋 시 last_attend_frame 초기값
        audio_max_len (float): 최대 오디오 길이 (초, 기본값 20.0)
            - 이 길이를 초과하면 버퍼 트리밍 발생
        cif_ckpt_path (str): CIF 모델 체크포인트 경로
            - Continuous Integrate-and-Fire 모델 (끝말 감지)
            - 빈 문자열이면 always_fire 또는 never_fire 모드 사용
        never_fire (bool): CIF를 사용하지 않음 (기본값 False)
            - True면 CIF 없이 frame_threshold만 사용
        language (str): 소스 언어 코드 (기본값 "zh")
        nonspeech_prob (float): 비음성 토큰 확률 임계값 (기본값 0.5)
        audio_min_len (float): 최소 오디오 길이 (초, 기본값 1.0)
        decoder_type (Literal["greedy","beam"]): 디코더 타입
            - "greedy": 탐욕 디코딩 (빠름, 단일 가설)
            - "beam": 빔 서치 (느림, 다중 가설)
        beam_size (int): 빔 크기 (beam 디코더만 해당, 기본값 5)
        task (Literal["transcribe","translate"]): 작업 타입
            - "transcribe": 전사 (같은 언어로 출력)
            - "translate": 번역 (영어로 번역)
        tokenizer_is_multilingual (bool): 다국어 토크나이저 여부
        init_prompt (str): 초기 프롬프트 (None = 사용 안 함)
            - 동적 프롬프트: 각 세그먼트마다 이전 출력 포함
        static_init_prompt (str): 정적 초기 프롬프트 (None = 사용 안 함)
            - 모든 세그먼트에 동일하게 적용
        max_context_tokens (int): 최대 컨텍스트 토큰 수 (None = 제한 없음)
            - 프롬프트의 최대 길이 제한
    """
    eval_data_path: str = "tmp"
    segment_length: float = field(default=1.0, metadata = {"help": "in second"})
    frame_threshold: int = 4
    rewind_threshold: int = 200
    audio_max_len: float = 20.0
    cif_ckpt_path: str = ""
    never_fire: bool = False
    language: str = field(default="zh")
    nonspeech_prob: float = 0.5
    audio_min_len: float = 1.0
    decoder_type: Literal["greedy","beam"] = "greedy"
    beam_size: int = 5
    task: Literal["transcribe","translate"] = "transcribe"
    tokenizer_is_multilingual: bool = False
    init_prompt: str = field(default=None)
    static_init_prompt: str = field(default=None)
    max_context_tokens: int = field(default=None)
    