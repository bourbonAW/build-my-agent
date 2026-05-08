"""Tests for the local SQLite memory search index."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bourbon.memory.models import MemoryRecord
from bourbon.memory.search_index import MemorySearchIndex


class FakeEmbeddingProvider:
    name = "fake"
    model = "fake-model"
    dimensions = 3

    def embed_passages(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self._vector(text)

    def _vector(self, text: str) -> tuple[float, ...]:
        lowered = text.casefold()
        if "dark" in lowered or "界面主题" in text:
            return (1.0, 0.0, 0.0)
        if "append" in lowered or "原地修改" in text:
            return (0.0, 1.0, 0.0)
        return (0.0, 0.0, 1.0)


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    def embed_passages(self, texts: list[str]) -> list[tuple[float, ...]]:
        if any("broken" in text.casefold() for text in texts):
            raise RuntimeError("embedding failed")
        return super().embed_passages(texts)


def _record(
    memory_id: str,
    *,
    target: str = "project",
    content: str = "Prefer append-only memory records.",
    cues: tuple[str, ...] = (),
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        target=target,  # type: ignore[arg-type]
        content=content,
        created_at=datetime(2026, 5, 7, 8, 0, tzinfo=UTC),
        cues=cues,
    )


def _index(tmp_path: Path) -> MemorySearchIndex:
    return MemorySearchIndex(
        tmp_path / "search_index.sqlite",
        FakeEmbeddingProvider(),
        top_k=8,
        min_similarity=0.25,
    )


def test_upsert_stores_search_text_and_vector(tmp_path: Path) -> None:
    index = _index(tmp_path)
    record = _record(
        "mem_dark",
        target="user",
        content="User prefers dark mode for UI components.",
        cues=("dark mode", "ui preference"),
    )

    index.upsert(record)

    assert (tmp_path / "search_index.sqlite").exists()
    with sqlite3.connect(tmp_path / "search_index.sqlite") as conn:
        row = conn.execute(
            "select target, search_text from memory_index_records where memory_id = ?",
            (record.id,),
        ).fetchone()
        vector_row = conn.execute(
            "select provider, model, dimensions, vector from memory_vectors where memory_id = ?",
            (record.id,),
        ).fetchone()

    assert row == (
        "user",
        "User prefers dark mode for UI components.\n\ncues:\ndark mode\nui preference",
    )
    assert vector_row[:3] == ("fake", "fake-model", 3)
    assert len(vector_row[3]) == 12


def test_search_fts_returns_candidates_with_target_filter(tmp_path: Path) -> None:
    index = _index(tmp_path)
    user_record = _record("mem_user", target="user", content="User prefers dark mode.")
    project_record = _record("mem_project", target="project", content="Dark mode lives in UI.")
    index.rebuild([user_record, project_record])

    results = index.search_fts("dark mode", target="user", limit=8)

    assert [candidate.memory_id for candidate in results] == ["mem_user"]
    assert results[0].channel == "fts"


def test_search_vector_returns_cosine_ranked_candidates(tmp_path: Path) -> None:
    index = _index(tmp_path)
    dark_record = _record(
        "mem_dark",
        target="user",
        content="User prefers dark mode for UI components.",
    )
    append_record = _record(
        "mem_append",
        target="project",
        content="Prefer append-only memory records.",
    )
    index.rebuild([append_record, dark_record])

    results = index.search_vector("用户喜欢什么界面主题？", target=None, limit=8)

    assert [candidate.memory_id for candidate in results] == ["mem_dark"]
    assert results[0].channel == "semantic"
    assert results[0].score == pytest.approx(1.0)


def test_delete_removes_record_from_all_index_tables(tmp_path: Path) -> None:
    index = _index(tmp_path)
    record = _record("mem_delete", content="Delete this memory.")
    index.upsert(record)

    index.delete(record.id)

    with sqlite3.connect(tmp_path / "search_index.sqlite") as conn:
        record_count = conn.execute("select count(*) from memory_index_records").fetchone()[0]
        fts_count = conn.execute("select count(*) from memory_fts").fetchone()[0]
        vector_count = conn.execute("select count(*) from memory_vectors").fetchone()[0]

    assert record_count == 0
    assert fts_count == 0
    assert vector_count == 0


def test_rebuild_clears_stale_rows(tmp_path: Path) -> None:
    index = _index(tmp_path)
    stale = _record("mem_stale", content="Stale semantic memory.")
    current = _record("mem_current", content="Current semantic memory.")
    index.rebuild([stale])

    index.rebuild([current])

    with sqlite3.connect(tmp_path / "search_index.sqlite") as conn:
        ids = [
            row[0]
            for row in conn.execute(
                "select memory_id from memory_index_records order by memory_id"
            ).fetchall()
        ]

    assert ids == ["mem_current"]


def test_rebuild_failure_leaves_existing_index_unchanged(tmp_path: Path) -> None:
    index_path = tmp_path / "search_index.sqlite"
    old_index = MemorySearchIndex(
        index_path,
        FakeEmbeddingProvider(),
        top_k=8,
        min_similarity=0.25,
    )
    old_index.rebuild([_record("mem_old", content="Old append-only memory.")])
    failing_index = MemorySearchIndex(
        index_path,
        FailingEmbeddingProvider(),
        top_k=8,
        min_similarity=0.25,
    )

    with pytest.raises(RuntimeError, match="embedding failed"):
        failing_index.rebuild(
            [
                _record("mem_new", content="New append-only memory."),
                _record("mem_broken", content="This broken memory cannot embed."),
            ]
        )

    with sqlite3.connect(index_path) as conn:
        ids = [
            row[0]
            for row in conn.execute(
                "select memory_id from memory_index_records order by memory_id"
            ).fetchall()
        ]

    assert ids == ["mem_old"]
