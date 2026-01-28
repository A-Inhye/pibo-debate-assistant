"""
summary 모듈 - ChatGPT API를 사용한 대화 요약

이 모듈은 STT 전사 결과를 ChatGPT API로 요약합니다.
"""

from .summarizer import ConversationSummarizer, SummaryResult

__all__ = ['ConversationSummarizer', 'SummaryResult']
