"""LLM access through the OpenAI-compatible chat API.

Most providers and local servers speak this same API (OpenAI, Groq,
OpenRouter, Together, vLLM, and Ollama at http://localhost:11434/v1), so one
small client covers them all. Swap providers by changing three env variables.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import httpx

from gst_copilot.config import get_settings


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None


class LLMClient(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> Completion: ...


class LLMError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,  # tests inject a fake server
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )
        self._model = model

    async def complete(self, messages: list[dict[str, str]]) -> Completion:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,  # facts, not creativity
        }
        try:
            r = await self._client.post("/chat/completions", json=payload)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {type(exc).__name__}") from exc
        data = r.json()
        usage = data.get("usage") or {}
        return Completion(
            text=data["choices"][0]["message"]["content"] or "",
            model=data.get("model", self._model),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )


@lru_cache
def get_llm() -> LLMClient | None:
    """None means no LLM is configured: the API runs in retrieval-only mode."""
    s = get_settings()
    if not s.llm_base_url or not s.llm_model:
        return None
    return OpenAICompatibleClient(s.llm_base_url, s.llm_model, s.llm_api_key, s.llm_timeout_seconds)
