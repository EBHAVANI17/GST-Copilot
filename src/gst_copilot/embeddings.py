"""Text embeddings behind one small interface.

The rest of the code only knows the `Embedder` protocol, so the model can be
swapped (local model, an API, or a fake for tests) without touching ingestion
or retrieval. This is the "depend on an interface" rule.
"""

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

from gst_copilot.config import get_settings


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """Local CPU embeddings with fastembed (ONNX runtime, no PyTorch).

    The model (about 130 MB for bge-small) downloads from Hugging Face on first
    use and is cached in cache_dir.
    """

    def __init__(self, model_name: str, dim: int, cache_dir: str | None = None) -> None:
        from fastembed import TextEmbedding  # imported here so tests don't need the model

        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.dim = dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = [[float(x) for x in v] for v in self._model.embed(texts, batch_size=32)]
        self._check(vectors)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        # bge models expect queries and passages to be embedded slightly differently;
        # fastembed's query_embed applies the right query prefix.
        vector = [float(x) for x in next(iter(self._model.query_embed(text)))]
        self._check([vector])
        return vector

    def _check(self, vectors: list[list[float]]) -> None:
        if vectors and len(vectors[0]) != self.dim:
            raise ValueError(
                f"Model returned {len(vectors[0])} dimensions but EMBEDDING_DIM is {self.dim}"
            )


_WORD = re.compile(r"[a-z0-9]+")


class FakeEmbedder:
    """Deterministic 'bag of words' embeddings using the hashing trick.

    Each word is hashed into one of `dim` slots; texts that share words get
    similar vectors. Good enough to test the whole pipeline, with no download.
    Not for real use: it has no idea that "refund" and "reimbursement" are related.
    """

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in _WORD.findall(text.lower()):
            h = int.from_bytes(hashlib.md5(word.encode(), usedforsecurity=False).digest()[:4])
            v[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    if s.embedding_provider == "fake":
        return FakeEmbedder(s.embedding_dim)
    return FastEmbedEmbedder(s.embedding_model, s.embedding_dim, s.embedding_cache_dir)
