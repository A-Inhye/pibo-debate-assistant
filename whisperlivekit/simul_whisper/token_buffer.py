"""
token_buffer.py - 토큰 버퍼 관리

TokenBuffer는 디코딩된 토큰을 텍스트로 변환하고 관리합니다.
불완전한 UTF-8 시퀀스를 처리하고, 단어 단위 트리밍을 지원합니다.
"""

import sys

import torch


class TokenBuffer:
    """
    토큰과 텍스트를 관리하는 버퍼 클래스

    Whisper 디코더가 생성한 토큰 ID를 텍스트로 변환하고,
    불완전한 UTF-8 시퀀스(replacement character �)를 올바르게 처리합니다.

    주요 기능:
        - 토큰 → 텍스트 변환 (UTF-8 디코딩)
        - 불완전한 UTF-8 처리 (pending_token_ids)
        - 단어 단위 트리밍 (컨텍스트 윈도우 관리)
        - 프리픽스 토큰 지원 (언어 토큰 등)

    Attributes:
        text (str): 현재 버퍼의 텍스트 내용
        prefix_token_ids (List[int]): 프리픽스 토큰 (언어, 작업 등)
        tokenizer: 토크나이저 객체 (인코딩/디코딩용)
        device: PyTorch 디바이스 (CPU/CUDA)
        pending_token_ids (List[int]): 불완전한 UTF-8 토큰 대기열

    사용 예:
        buf = TokenBuffer(tokenizer=tokenizer, device="cuda")
        buf.append_token_ids([123, 456])  # 토큰 추가
        text = buf.as_text()  # 텍스트로 변환
        tensor = buf.as_tensor()  # 텐서로 변환
    """

    def __init__(self, text="", tokenizer=None, device=None, prefix_token_ids=[]):
        """
        TokenBuffer 초기화

        Args:
            text (str): 초기 텍스트 내용 (기본값: 빈 문자열)
            tokenizer: 토크나이저 객체 (인코딩/디코딩용)
            device: PyTorch 디바이스 (CPU/CUDA)
            prefix_token_ids (List[int]): 프리픽스 토큰 ID (언어, 작업 토큰 등)
        """
        self.text = text  # 현재 텍스트
        self.prefix_token_ids = prefix_token_ids  # 프리픽스 토큰 (언어 등)
        self.tokenizer = tokenizer  # 토크나이저
        self.device = device  # 디바이스 (CPU/CUDA)
        self.pending_token_ids = []  # 불완전한 UTF-8 토큰 대기열

    def as_token_ids(self, tokenizer=None):
        """
        버퍼 내용을 토큰 ID 리스트로 변환

        Returns:
            List[int]: 프리픽스 + 텍스트 토큰 ID

        Raises:
            ValueError: tokenizer가 설정되지 않음
        """
        if tokenizer is None:
            tokenizer = self.tokenizer
        if tokenizer is None:
            raise ValueError("Tokenizer is not set.")
        return self.prefix_token_ids + tokenizer.encode(self.text)

    def as_tensor(self, device=None):
        """
        버퍼 내용을 PyTorch 텐서로 변환

        Returns:
            Tensor: 토큰 ID 텐서 [1, seq_len]

        Raises:
            ValueError: device가 설정되지 않음
        """
        if device is None:
            device = self.device
        if device is None:
            raise ValueError("Device is not set.")
        tok_ids = self.as_token_ids()
        return torch.tensor(tok_ids,
                     dtype=torch.long, device=device).unsqueeze(0)

    def as_tensor_beam(self, beam, device=None):
        """
        빔 서치를 위한 텐서 생성 (배치 복제)

        Args:
            beam (int): 빔 크기 (복제 횟수)
            device: PyTorch 디바이스

        Returns:
            Tensor: 토큰 ID 텐서 [beam, seq_len]
        """
        t = self.as_tensor(device=device)
        return t.repeat_interleave(beam, dim=0)


    def as_text(self):
        """
        버퍼 내용을 텍스트로 반환

        Returns:
            str: 현재 텍스트
        """
        return self.text

    @staticmethod
    def empty(*a, **kw):
        """
        빈 TokenBuffer 생성 (팩토리 메서드)

        Returns:
            TokenBuffer: 빈 버퍼
        """
        return TokenBuffer(*a,**kw)

    @staticmethod
    def from_text(text, *a, **kw):
        """
        텍스트로부터 TokenBuffer 생성 (팩토리 메서드)

        Args:
            text (str): 초기 텍스트

        Returns:
            TokenBuffer: 텍스트를 포함한 버퍼
        """
        return TokenBuffer(*a, text=text, **kw)

    def is_empty(self):
        """
        버퍼가 비어있는지 확인

        Returns:
            bool: 비어있으면 True
        """
        return self.text is None or self.text == ""

    def trim_words(self, num=1, after=0):
        """
        버퍼 앞부분에서 단어를 제거 (컨텍스트 윈도우 관리)

        오래된 텍스트를 제거하여 컨텍스트 길이를 제한합니다.
        Whisper는 제한된 컨텍스트 윈도우를 가지므로 주기적으로 트리밍이 필요합니다.

        Args:
            num (int): 제거할 단어 개수 (기본값 1)
            after (int): 건너뛸 문자 수 (정적 프롬프트 길이)
                - 정적 프롬프트는 보존하고 그 이후부터 트리밍

        Returns:
            int: 제거된 토큰 수

        동작:
            1. text[after:] 부분을 토큰으로 인코딩
            2. 단어 단위로 분할 (split_to_word_tokens)
            3. 앞에서 num개 단어 제거
            4. 제거된 토큰 수 반환

        예:
            text = "Hello world, how are you?"
            after = 0, num = 2
            → "how are you?" (Hello world 제거)
        """
        tokenizer = self.tokenizer
        assert tokenizer is not None, "Tokenizer is not set."

        # after 이후 부분을 토큰으로 인코딩
        ids = tokenizer.encode(self.text[after:])
        # 단어 단위로 분할
        words, wids = self.tokenizer.split_to_word_tokens(ids)
        if not words:
            return 0
        # 앞에서 num개 단어 제거
        self.text = self.text[:after] + "".join(words[num:])
        # 제거된 토큰 수 반환
        return sum(len(wi) for wi in wids[:num])

    def append_token_ids(self, token_ids):
        """
        토큰 ID를 버퍼에 추가 (불완전한 UTF-8 처리)

        새로운 토큰을 텍스트로 디코딩하여 버퍼에 추가합니다.
        불완전한 UTF-8 시퀀스(replacement character �)가 있으면
        완전한 문자가 될 때까지 pending_token_ids에 보관합니다.

        Args:
            token_ids (List[int]): 추가할 토큰 ID 리스트

        동작:
            1. pending + 새 토큰을 합쳐서 디코딩 시도
            2. � (U+FFFD)가 있는지 확인:
               - 없으면: 완전한 UTF-8, 텍스트에 추가
               - 있으면: 마지막 토큰만 pending에 보관하고 나머지는 추가
                        (또는 모두 pending에 보관)

        예:
            토큰 [123, 456] → "안" (완전)
            토큰 [789] → "�" (불완전) → pending에 보관
            토큰 [790] → pending [789, 790] → "녕" (완전)

        Note:
            이 메커니즘은 멀티바이트 UTF-8 문자가 여러 토큰에 걸쳐
            인코딩될 때 필요합니다 (특히 한국어, 중국어, 일본어).
        """
        tokenizer = self.tokenizer
        assert tokenizer is not None, "Tokenizer is not set."

        # 대기 중인 토큰과 새 토큰 합치기
        all_tokens = self.pending_token_ids + token_ids

        # 전체 디코딩 시도
        decoded = tokenizer.decode(all_tokens)
        replacement_char = "\ufffd"  # UTF-8 디코딩 실패 시 나타나는 문자

        if replacement_char in decoded:
            # 불완전한 UTF-8 시퀀스 존재
            if len(all_tokens) > 1:
                # 마지막 토큰 제외하고 디코딩 시도
                decoded_partial = tokenizer.decode(all_tokens[:-1])

                if replacement_char not in decoded_partial:
                    # 마지막 토큰만 문제 → 텍스트에 추가하고 마지막 토큰만 보관
                    self.text += decoded_partial
                    self.pending_token_ids = [all_tokens[-1]]
                else:
                    # 여전히 불완전 → 모두 보관
                    self.pending_token_ids = all_tokens
            else:
                # 토큰 1개만 있는데 불완전 → 보관
                self.pending_token_ids = all_tokens
        else:
            # 완전한 UTF-8 → 텍스트에 추가
            self.text += decoded
            self.pending_token_ids = []

    def as_split_word_tokens(self):
        """
        버퍼 내용을 단어 단위로 분할

        Returns:
            Tuple[List[str], List[List[int]]]: (단어 리스트, 토큰 ID 리스트)
        """
        tokenizer = self.tokenizer
        assert tokenizer is not None, "Tokenizer is not set."
        ids = tokenizer.encode(self.text)
        return tokenizer.split_to_word_tokens(ids)
