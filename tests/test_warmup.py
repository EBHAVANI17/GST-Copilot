"""Warm-up at startup and the readiness check that waits for it."""

from collections.abc import Sequence
from typing import Any

import pytest

from gst_copilot.api import warmup
from gst_copilot.embeddings import FakeEmbedder
from gst_copilot.rag.llm import Completion, LLMError
from gst_copilot.rag.rerank import FakeReranker


class Counting:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages: list[dict[str, str]]) -> Completion:
        self.calls += 1
        return Completion("OK", "m", None, None)


@pytest.fixture
def fresh(monkeypatch: pytest.MonkeyPatch) -> warmup.WarmupState:
    state = warmup.WarmupState()
    monkeypatch.setattr(warmup, "STATE", state)
    monkeypatch.setattr(warmup, "get_embedder", lambda: FakeEmbedder(384))
    monkeypatch.setattr(warmup, "get_reranker", FakeReranker)
    return state


async def test_ready_only_after_warm_up(fresh: warmup.WarmupState, monkeypatch: Any) -> None:
    llm = Counting()
    monkeypatch.setattr(warmup, "get_llm", lambda: llm)
    with pytest.raises(RuntimeError, match="not started"):
        await warmup.models_ready()
    await warmup.warm_up(fresh)
    await warmup.models_ready()  # no exception: ready
    assert set(fresh.timings_ms) == {"embedder", "reranker", "llm"} and not fresh.errors
    assert llm.calls == 1


async def test_llm_down_is_reported_but_does_not_block_readiness(
    fresh: warmup.WarmupState, monkeypatch: Any
) -> None:
    class Down:
        async def complete(self, messages: Sequence[Any]) -> Completion:
            raise LLMError("connection refused")

    monkeypatch.setattr(warmup, "get_llm", lambda: Down())
    await warmup.warm_up(fresh)
    assert "llm" in fresh.errors
    await warmup.models_ready()  # retrieval still works, so the instance is ready


async def test_failed_model_load_keeps_instance_not_ready(
    fresh: warmup.WarmupState, monkeypatch: Any
) -> None:
    def broken() -> Any:
        raise OSError("model file missing")

    monkeypatch.setattr(warmup, "get_embedder", broken)
    monkeypatch.setattr(warmup, "get_llm", lambda: None)
    await warmup.warm_up(fresh)
    assert fresh.done and "embedder" in fresh.errors
    with pytest.raises(RuntimeError, match="model load failed: embedder"):
        await warmup.models_ready()
