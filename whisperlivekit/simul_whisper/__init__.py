"""
simul_whisper 패키지 - Simultaneous Streaming ASR

SimulStreaming 정책을 사용한 실시간 음성 전사 모듈입니다.
AlignAtt (Alignment Attention) 정책을 기반으로 낮은 지연시간의 실시간 전사를 제공합니다.

주요 클래스:
    - SimulStreamingASR: ASR 백엔드 (모델 로드 및 인코딩)
    - SimulStreamingOnlineProcessor: 연결별 온라인 프로세서 (실시간 디코딩)

특징:
    - AlignAtt 정책: Cross-attention을 분석하여 단어 경계 감지
    - CIF (Continuous Integrate-and-Fire): 끝말 감지 모델
    - Beam Search: 다중 가설 탐색으로 정확도 향상
    - Token Buffer: 불완전한 UTF-8 토큰 처리
"""

from .backend import SimulStreamingASR, SimulStreamingOnlineProcessor

__all__ = [
    "SimulStreamingASR",
    "SimulStreamingOnlineProcessor",
]
