"""Tests for local semantic memory embedding helpers."""

from __future__ import annotations

import math
import struct

import pytest

from bourbon.memory.embeddings import (
    EmbeddingUnavailableError,
    FastEmbedProvider,
    cosine_similarity,
    pack_vector,
    unpack_vector,
)


def test_pack_vector_round_trips_float32_values() -> None:
    raw = (0.25, -0.5, 1.0)
    blob = pack_vector(raw)

    assert isinstance(blob, bytes)
    assert len(blob) == 12
    assert unpack_vector(blob, 3) == pytest.approx(raw)


def test_unpack_vector_rejects_dimension_mismatch() -> None:
    blob = struct.pack("<2f", 1.0, 2.0)

    with pytest.raises(ValueError, match="Vector blob has 2 dimensions; expected 3"):
        unpack_vector(blob, 3)


def test_cosine_similarity() -> None:
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)
    assert math.isclose(cosine_similarity((0.0, 0.0), (1.0, 0.0)), 0.0)


def test_fastembed_provider_import_is_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_import() -> object:
        raise ImportError("fastembed")

    provider = FastEmbedProvider(model="local/model")
    monkeypatch.setattr(provider, "_load_model", fail_import)

    with pytest.raises(EmbeddingUnavailableError):
        provider.embed_query("hello")
