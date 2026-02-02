# ollama_stream.py
import json
from typing import Iterator, Optional

import requests


def stream_ollama_tokens(
    prompt: str,
    model: str = "qwen2.5:1.5b",
    host: str = "http://localhost:11434",
    timeout: Optional[float] = None,
) -> Iterator[str]:
    """
    Ollama /api/generate 스트리밍 응답을 토큰(문자열 조각) 단위로 yield.
    """
    url = f"{host.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
    }

    with requests.post(url, json=payload, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            data = json.loads(line)
            if "response" in data:
                yield data["response"]
            if data.get("done"):
                break
