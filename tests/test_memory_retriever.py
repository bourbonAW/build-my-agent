"""Tests for hybrid memory retrieval."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bourbon.memory.models import MemoryRecord
from bourbon.memory.retriever import MemoryRetriever
from bourbon.memory.search_index import MemorySearchIndex
from bourbon.memory.store import MemoryStore


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
        if "dark" in lowered or "theme" in lowered or "界面主题" in text:
            return (1.0, 0.0, 0.0)
        if "append" in lowered or "原地修改" in text:
            return (0.0, 1.0, 0.0)
        return (0.0, 0.0, 1.0)


class BrokenIndex:
    def search_fts(self, *args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("fts broken")

    def search_vector(self, *args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("vector broken")


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


def _store_and_retriever(tmp_path: Path) -> tuple[MemoryStore, MemoryRetriever]:
    store = MemoryStore(tmp_path / "memory")
    index = MemorySearchIndex(
        tmp_path / "memory" / "search_index.sqlite",
        FakeEmbeddingProvider(),
        top_k=8,
        min_similarity=0.25,
    )
    return store, MemoryRetriever(store=store, index=index)


def test_exact_content_match_outranks_semantic_only_match(tmp_path: Path) -> None:
    store, retriever = _store_and_retriever(tmp_path)
    exact = _record("mem_exact", content="Use dark mode for UI settings.")
    semantic = _record("mem_semantic", content="Theme appearance preference.")
    store.write_record(semantic)
    store.write_record(exact)
    retriever.rebuild_index()

    results = retriever.search("dark mode", terms=("dark mode",), target=None, limit=8)

    assert [result.id for result in results][:2] == ["mem_exact", "mem_semantic"]
    assert results[0].why_matched == "matched content: dark mode"
    assert results[1].why_matched.startswith("matched semantic:")


def test_semantic_search_finds_mixed_chinese_english_query(tmp_path: Path) -> None:
    store, retriever = _store_and_retriever(tmp_path)
    record = _record(
        "mem_dark",
        target="user",
        content="User prefers dark mode for UI components.",
    )
    store.write_record(record)
    retriever.rebuild_index()

    results = retriever.search(
        "用户喜欢什么界面主题？",
        terms=("用户喜欢什么界面主题？",),
        target="user",
        limit=8,
    )

    assert [result.id for result in results] == ["mem_dark"]
    assert results[0].why_matched.startswith("matched semantic:")


def test_target_filter_applies_to_semantic_candidates(tmp_path: Path) -> None:
    store, retriever = _store_and_retriever(tmp_path)
    user_record = _record("mem_user", target="user", content="User prefers dark mode.")
    project_record = _record("mem_project", target="project", content="Project uses dark UI.")
    store.write_record(user_record)
    store.write_record(project_record)
    retriever.rebuild_index()

    results = retriever.search(
        "用户喜欢什么界面主题？",
        terms=("用户喜欢什么界面主题？",),
        target="user",
        limit=8,
    )

    assert [result.id for result in results] == ["mem_user"]


def test_index_failure_falls_back_to_exact_store_search(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.write_record(_record("mem_dark", content="Use dark mode for UI settings."))
    retriever = MemoryRetriever(store=store, index=BrokenIndex())  # type: ignore[arg-type]

    results = retriever.search("dark mode", terms=("dark mode",), target=None, limit=8)

    assert [result.id for result in results] == ["mem_dark"]
    assert results[0].why_matched == "matched content: dark mode"
