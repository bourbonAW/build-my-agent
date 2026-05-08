"""Local embedding provider boundary for memory semantic search."""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from typing import Protocol


class EmbeddingUnavailableError(RuntimeError):
    """Raised when semantic embeddings cannot be generated."""


class EmbeddingProvider(Protocol):
    """Minimal embedding provider interface used by memory search."""

    name: str
    model: str
    dimensions: int | None

    def embed_passages(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Embed stored memory passages."""
        ...

    def embed_query(self, text: str) -> tuple[float, ...]:
        """Embed a search query."""
        ...


def pack_vector(vector: Sequence[float]) -> bytes:
    """Pack a vector as little-endian float32 bytes."""
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(blob: bytes, dimensions: int) -> tuple[float, ...]:
    """Unpack a little-endian float32 vector and validate dimensions."""
    if len(blob) % 4 != 0:
        raise ValueError("Vector blob length is not divisible by 4")
    actual_dimensions = len(blob) // 4
    if actual_dimensions != dimensions:
        raise ValueError(
            f"Vector blob has {actual_dimensions} dimensions; expected {dimensions}"
        )
    if dimensions == 0:
        return ()
    return struct.unpack(f"<{dimensions}f", blob)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Return cosine similarity for two equal-length vectors."""
    if len(left) != len(right):
        raise ValueError(f"Vector dimensions differ: {len(left)} != {len(right)}")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))
    return dot / (left_norm * right_norm)


class FastEmbedProvider:
    """FastEmbed-backed local embedding provider with lazy model loading."""

    name = "fastembed"

    def __init__(self, *, model: str) -> None:
        self.model = model
        self.dimensions: int | None = None
        self._embedding_model: object | None = None

    def _load_model(self) -> object:
        try:
            from fastembed import TextEmbedding
        except Exception as exc:  # pragma: no cover - depends on optional package state
            raise EmbeddingUnavailableError("fastembed is not available") from exc
        try:
            return TextEmbedding(model_name=self.model)
        except Exception as exc:  # pragma: no cover - depends on local model cache/network
            raise EmbeddingUnavailableError(
                f"fastembed model is not available: {self.model}"
            ) from exc

    def _model(self) -> object:
        if self._embedding_model is None:
            try:
                self._embedding_model = self._load_model()
            except EmbeddingUnavailableError:
                raise
            except Exception as exc:
                raise EmbeddingUnavailableError(str(exc)) from exc
        return self._embedding_model

    def _embed(self, texts: list[str], *, passage: bool) -> list[tuple[float, ...]]:
        if not texts:
            return []
        model = self._model()
        try:
            if passage and hasattr(model, "passage_embed"):
                raw_vectors = model.passage_embed(texts)
            elif not passage and hasattr(model, "query_embed"):
                raw_vectors = model.query_embed(texts)
            else:
                raw_vectors = model.embed(texts)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - provider-specific failures
            raise EmbeddingUnavailableError("fastembed embedding failed") from exc
        vectors = [tuple(float(value) for value in vector) for vector in raw_vectors]
        if vectors:
            self.dimensions = len(vectors[0])
        return vectors

    def embed_passages(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Embed stored memory passages."""
        return self._embed(texts, passage=True)

    def embed_query(self, text: str) -> tuple[float, ...]:
        """Embed a search query."""
        vectors = self._embed([text], passage=False)
        return vectors[0] if vectors else ()
