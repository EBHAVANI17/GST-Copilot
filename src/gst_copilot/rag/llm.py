"""LLM access through the OpenAI-compatible chat API.

Most providers and local servers speak this same API (OpenAI, Groq,
OpenRouter, Together, vLLM, and Ollama at http://localhost:11434/v1), so one
small client covers them all. Swap providers by changing three env variables.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
class StreamingLLMClient(LLMClient, Protocol):
    def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str | Completion]:
        """Yield text pieces as the model writes them, then one final Completion
        (full text, finish_reason, token counts)."""
        ...


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

    def _payload(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,  # facts, not creativity
        }
        if self._max_tokens:
            payload["max_tokens"] = self._max_tokens
        if self._frequency_penalty:
            payload["frequency_penalty"] = self._frequency_penalty
        return payload

    async def complete(self, messages: list[dict[str, str]]) -> Completion:
        try:
            r = await self._client.post("/chat/completions", json=self._payload(messages))
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

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str | Completion]:
        """Server-sent events from /chat/completions with "stream": true.

        Each event is a line "data: {json}" with the next piece of text in
        choices[0].delta.content; "data: [DONE]" ends the stream. include_usage asks
        for a last event with token counts (Ollama and OpenAI support it).
        If the caller stops iterating (the user disconnected), leaving the
        "async with" closes the connection and the server stops generating.
        """
        payload = {
            **self._payload(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        parts: list[str] = []
        model, finish = self._model, None
        usage: dict[str, Any] = {}
        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue  # blank separators and ": keep-alive" comments
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    event = json.loads(data)
                    model = event.get("model") or model
                    usage = event.get("usage") or usage
                    for choice in event.get("choices") or []:
                        finish = choice.get("finish_reason") or finish
                        piece = (choice.get("delta") or {}).get("content")
                        if piece:
                            parts.append(piece)
                            yield piece
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM stream failed: {type(exc).__name__}") from exc
        except json.JSONDecodeError as exc:
            raise LLMError("LLM stream sent invalid JSON") from exc
        yield Completion(
            text="".join(parts),
            model=model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            finish_reason=finish,
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
