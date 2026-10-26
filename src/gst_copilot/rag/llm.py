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
    finish_reason: str | None = None  # "stop" = finished; "length" = hit max_tokens

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"


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
        max_tokens: int | None = None,
        frequency_penalty: float = 0.0,
        transport: httpx.AsyncBaseTransport | None = None,  # tests inject a fake server
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )
        self._model = model
        self._max_tokens = max_tokens
        self._frequency_penalty = frequency_penalty

    async def complete(self, messages: list[dict[str, str]]) -> Completion:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,  # facts, not creativity
        }
        if self._max_tokens:
            payload["max_tokens"] = self._max_tokens
        if self._frequency_penalty:
            payload["frequency_penalty"] = self._frequency_penalty
        try:
            r = await self._client.post("/chat/completions", json=payload)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {type(exc).__name__}") from exc
        data = r.json()
        usage = data.get("usage") or {}
        choice = data["choices"][0]
        return Completion(
            text=choice["message"]["content"] or "",
            finish_reason=choice.get("finish_reason"),
            model=data.get("model", self._model),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )


def get_judge_llm() -> LLMClient | None:
    """The judge model for --judge evaluations; None if no LLM server is configured."""
    s = get_settings()
    base = s.judge_base_url or s.llm_base_url
    if not base or not s.judge_model:
        return None
    return OpenAICompatibleClient(
        base,
        s.judge_model,
        s.judge_api_key or s.llm_api_key,
        s.judge_timeout_seconds,
        max_tokens=300,
    )


@lru_cache
def get_llm() -> LLMClient | None:
    """None means no LLM is configured: the API runs in retrieval-only mode."""
    s = get_settings()
    if not s.llm_base_url or not s.llm_model:
        return None
    return OpenAICompatibleClient(
        s.llm_base_url,
        s.llm_model,
        s.llm_api_key,
        s.llm_timeout_seconds,
        max_tokens=s.llm_max_tokens,
        frequency_penalty=s.llm_frequency_penalty,
    )
