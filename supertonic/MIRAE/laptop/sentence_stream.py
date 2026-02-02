import re
from typing import Iterable, Iterator

SENT_END_RE = re.compile(r"[.!?]\s*$")


def should_emit(
    buffer: str,
    *,
    is_first_chunk: bool,
    min_len: int = 20
) -> bool:
    """
    - 첫 chunk: 문장부호만 나오면 바로 emit
    - 이후 chunk: 문장부호 + min_len 조건
    """
    buf = buffer.strip()
    if not buf:
        return False

    # 🔥 첫 chunk는 길이 무시
    if is_first_chunk:
        return bool(SENT_END_RE.search(buf))

    # 이후 chunk는 기존 규칙
    if len(buf) < min_len:
        return False

    return bool(SENT_END_RE.search(buf))


def stream_text_chunks(
    token_stream: Iterable[str],
    *,
    soft_max_len: int = 80,
    min_len: int = 20
) -> Iterator[str]:
    """
    - 토큰을 누적하며 buffer 관리
    - 첫 chunk는 빠른 응답을 위해 짧게 emit
    - 이후 chunk는 품질 기준 유지
    """
    buf = ""
    is_first_chunk = True

    for tok in token_stream:
        buf += tok

        if should_emit(
            buf,
            is_first_chunk=is_first_chunk,
            min_len=min_len
        ):
            yield buf
            buf = ""
            is_first_chunk = False
            continue

        # 문장부호가 늦어질 경우 안전장치
        if not is_first_chunk and len(buf) >= soft_max_len:
            yield buf
            buf = ""
            is_first_chunk = False

    if buf.strip():
        yield buf
