"""Embedding utilities for best_buddy_agent."""

from __future__ import annotations

import hashlib
import math


class LocalHashEmbedding:
    def __init__(self, dim: int = 256):
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in text.lower().split():
            h = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]


_MODEL: LocalHashEmbedding | None = None


def get_embedding_model() -> LocalHashEmbedding:
    global _MODEL
    if _MODEL is None:
        _MODEL = LocalHashEmbedding()
    return _MODEL
