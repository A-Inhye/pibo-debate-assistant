"""
summarizer.py - ChatGPT API를 사용한 대화 요약 모듈

이 모듈은 WhisperLiveKit의 STT 전사 결과를 ChatGPT API로 요약합니다.

요약 과정:
    1. 전사된 세그먼트(화자별 발언)를 수집
    2. 프롬프트 생성 (대화 내용 + 요약 지시)
    3. ChatGPT API 호출
    4. JSON 응답 파싱
    5. SummaryResult 객체로 반환

사용 예시:
    from whisperlivekit.summary import ConversationSummarizer

    summarizer = ConversationSummarizer(model="gpt-3.5-turbo")
    segments = [
        {"speaker": 1, "text": "안녕하세요"},
        {"speaker": 2, "text": "반갑습니다"},
    ]
    result = await summarizer.summarize(segments)
    print(result.summary)  # "두 명이 인사를 나눔"
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SummaryResult:
    """
    요약 결과 데이터 클래스

    Attributes:
        summary: 전체 대화 요약 (2-3문장)
        speaker_summaries: 화자별 논지 {"1": "화자1의 주장", "2": "화자2의 주장"}
        token_usage: API 호출에 사용된 토큰 수
        error: 에러 메시지 (실패 시)
    """
    summary: str = ""
    speaker_summaries: Dict[str, str] = field(default_factory=dict)
    token_usage: int = 0
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """프론트엔드로 전송할 딕셔너리로 변환"""
        return {
            "summary": self.summary,
            "speaker_summaries": self.speaker_summaries,
            "token_usage": self.token_usage,
            "error": self.error
        }

    def __bool__(self) -> bool:
        """요약이 있는지 확인"""
        return bool(self.summary or self.speaker_summaries)


class ConversationSummarizer:
    """
    대화 요약기 클래스

    ChatGPT API를 사용하여 전사된 대화를 요약합니다.

    Args:
        model: 사용할 ChatGPT 모델 ("gpt-3.5-turbo" 또는 "gpt-4")
        api_key: OpenAI API 키 (None이면 환경변수에서 로드)
        language: 출력 언어 ("ko" 또는 "en")
        max_tokens: 응답 최대 토큰 수

    사용 예시:
        summarizer = ConversationSummarizer()
        result = await summarizer.summarize(segments)
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        language: str = "ko",
        max_tokens: int = 1000
    ):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.language = language
        self.max_tokens = max_tokens

        # API 키 검증
        if not self.api_key:
            logger.warning("OPENAI_API_KEY가 설정되지 않았습니다. 요약 기능이 비활성화됩니다.")
            self.client = None
        else:
            try:
                from openai import AsyncOpenAI
                self.client = AsyncOpenAI(api_key=self.api_key)
                logger.info(f"ChatGPT 요약기 초기화 완료 (모델: {self.model})")
            except ImportError:
                logger.error("openai 패키지가 설치되지 않았습니다. pip install openai")
                self.client = None

        # 통계
        self.total_tokens_used = 0
        self.call_count = 0

    def _build_prompt(self, segments: List[Dict[str, Any]]) -> str:
        """
        전사 세그먼트를 ChatGPT 프롬프트로 변환

        Args:
            segments: 전사 세그먼트 리스트
                [{"speaker": 1, "text": "안녕하세요"}, ...]

        Returns:
            ChatGPT에 보낼 프롬프트 문자열

        프롬프트 구조:
            1. 역할 설명: "당신은 토론 분석 전문가입니다"
            2. 대화 내용: "화자 1: ...\n화자 2: ..."
            3. 요청 사항: 전체 요약, 화자별 논지, 핵심 포인트
            4. 출력 형식: JSON
        """
        # 대화 텍스트 구성
        conversation_lines = []
        for seg in segments:
            speaker = seg.get("speaker", "?")
            text = seg.get("text", "").strip()

            # 침묵(-2) 또는 빈 텍스트 제외
            if text and speaker != -2:
                conversation_lines.append(f"화자 {speaker}: {text}")

        conversation_text = "\n".join(conversation_lines)

        # 언어별 프롬프트
        if self.language == "ko":
            prompt = f"""다음은 실시간 토론 대화입니다. 이 대화를 분석하여 다음을 제공하세요:

1. **전체 요약**: 대화의 핵심 내용을 2-3문장으로 요약
2. **화자별 논지**: 각 화자의 주요 주장이나 의견을 간단히 정리

대화 내용:
{conversation_text}

응답은 반드시 다음 JSON 형식으로 작성해주세요:
{{
    "summary": "전체 요약 내용",
    "speaker_summaries": {{
        "1": "화자 1의 논지",
        "2": "화자 2의 논지"
    }}
}}"""
        else:
            prompt = f"""Analyze the following conversation and provide:

1. **Summary**: Summarize the key points in 2-3 sentences
2. **Speaker Arguments**: Main arguments or opinions of each speaker

Conversation:
{conversation_text}

Respond in this JSON format:
{{
    "summary": "Overall summary",
    "speaker_summaries": {{
        "1": "Speaker 1's argument",
        "2": "Speaker 2's argument"
    }}
}}"""

        return prompt

    async def summarize(
        self,
        segments: List[Dict[str, Any]]
    ) -> SummaryResult:
        """
        대화 세그먼트를 요약

        Args:
            segments: 전사 세그먼트 리스트
                [{"speaker": 1, "text": "...", "start": 0.0, "end": 1.5}, ...]

        Returns:
            SummaryResult 객체

        과정:
            1. 세그먼트가 비어있으면 빈 결과 반환
            2. 프롬프트 생성
            3. ChatGPT API 호출
            4. JSON 응답 파싱
            5. SummaryResult 생성 및 반환
        """
        # 클라이언트 확인
        if not self.client:
            return SummaryResult(error="ChatGPT API가 초기화되지 않았습니다.")

        # 빈 세그먼트 확인
        if not segments:
            return SummaryResult(error="요약할 대화가 없습니다.")

        # 실제 텍스트가 있는 세그먼트만 필터링
        valid_segments = [
            seg for seg in segments
            if seg.get("text", "").strip() and seg.get("speaker", -2) != -2
        ]

        if not valid_segments:
            return SummaryResult(error="요약할 대화가 없습니다.")

        # 프롬프트 생성
        prompt = self._build_prompt(valid_segments)
        logger.debug(f"요약 프롬프트 생성 완료 (세그먼트 수: {len(valid_segments)})")

        try:
            # ChatGPT API 호출
            logger.info(f"ChatGPT API 호출 중... (모델: {self.model})")

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 토론 분석 전문가입니다. 항상 JSON 형식으로 응답합니다."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=self.max_tokens,
                temperature=0.3,  # 일관된 응답을 위해 낮은 온도
                response_format={"type": "json_object"}  # JSON 응답 강제
            )

            # 응답 추출
            content = response.choices[0].message.content
            usage = response.usage.total_tokens if response.usage else 0

            # 통계 업데이트
            self.total_tokens_used += usage
            self.call_count += 1
            logger.info(f"ChatGPT 응답 수신 (토큰: {usage}, 총 호출: {self.call_count})")

            # JSON 파싱
            try:
                result_data = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"JSON 파싱 실패: {e}")
                logger.debug(f"원본 응답: {content}")
                return SummaryResult(
                    summary=content,  # 파싱 실패 시 원본 텍스트 사용
                    token_usage=usage,
                    error="JSON 파싱 실패"
                )

            # SummaryResult 생성
            result = SummaryResult(
                summary=result_data.get("summary", ""),
                speaker_summaries=result_data.get("speaker_summaries", {}),
                token_usage=usage
            )

            logger.info(f"요약 완료: {result.summary[:50]}...")
            return result

        except Exception as e:
            error_msg = str(e)
            logger.error(f"ChatGPT API 호출 오류: {error_msg}")

            # 에러 유형별 메시지
            if "rate_limit" in error_msg.lower():
                return SummaryResult(error="API 호출 한도 초과. 잠시 후 다시 시도하세요.")
            elif "authentication" in error_msg.lower():
                return SummaryResult(error="API 키가 유효하지 않습니다.")
            elif "connection" in error_msg.lower():
                return SummaryResult(error="네트워크 연결 오류입니다.")
            else:
                return SummaryResult(error=f"요약 실패: {error_msg}")

    def get_stats(self) -> Dict[str, Any]:
        """통계 정보 반환"""
        return {
            "total_tokens_used": self.total_tokens_used,
            "call_count": self.call_count,
            "model": self.model
        }
