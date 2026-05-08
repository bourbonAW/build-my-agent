"""Hybrid memory retrieval over exact, FTS, and semantic channels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bourbon.memory.models import MemorySearchResult
from bourbon.memory.search_index import IndexCandidate, MemorySearchIndex
from bourbon.memory.store import MemoryStore, _record_preview


class SearchIndex(Protocol):
    """Search index operations used by the retriever."""

    def search_fts(
        self,
        query: str,
        *,
        target: str | None,
        limit: int,
    ) -> list[IndexCandidate]:
        ...

    def search_vector(
        self,
        query: str,
        *,
        target: str | None,
        limit: int,
    ) -> list[IndexCandidate]:
        ...


@dataclass
class _Ranked:
    score: float = 0.0
    reason: str = ""


class MemoryRetriever:
    """Combine exact store search with derived SQLite index candidates."""

    def __init__(self, *, store: MemoryStore, index: SearchIndex) -> None:
        self._store = store
        self._index = index

    def rebuild_index(self) -> None:
        """Rebuild the derived index from authoritative memory records."""
        if isinstance(self._index, MemorySearchIndex):
            self._index.rebuild(self._store.list_records())

    def search(
        self,
        query: str,
        *,
        terms: tuple[str, ...],
        target: str | None,
        limit: int,
    ) -> list[MemorySearchResult]:
        ranked: dict[str, _Ranked] = {}

        for term in terms:
            for result in self._store.search(term, target=target, limit=limit):
                entry = ranked.setdefault(result.id, _Ranked())
                entry.score += 3.2 if result.why_matched.startswith("matched cue:") else 3.0
                if not entry.reason:
                    entry.reason = result.why_matched

        for candidate in self._safe_fts(query=query, target=target, limit=limit):
            entry = ranked.setdefault(candidate.memory_id, _Ranked())
            entry.score += 1.5 * candidate.score
            if not entry.reason:
                entry.reason = candidate.reason

        for candidate in self._safe_vector(query=query, target=target, limit=limit):
            entry = ranked.setdefault(candidate.memory_id, _Ranked())
            entry.score += 1.2 * candidate.score
            if not entry.reason:
                entry.reason = candidate.reason

        ordered_ids = sorted(ranked, key=lambda memory_id: (-ranked[memory_id].score, memory_id))
        results: list[MemorySearchResult] = []
        for memory_id in ordered_ids:
            record = self._store.read_record(memory_id)
            if record is None:
                continue
            if target is not None and record.target != target:
                continue
            results.append(
                MemorySearchResult(
                    id=record.id,
                    target=record.target,
                    snippet=_record_preview(record),
                    why_matched=ranked[memory_id].reason,
                )
            )
            if len(results) >= limit:
                break
        return results

    def _safe_fts(self, *, query: str, target: str | None, limit: int) -> list[IndexCandidate]:
        try:
            return self._index.search_fts(query, target=target, limit=limit)
        except Exception:
            return []

    def _safe_vector(self, *, query: str, target: str | None, limit: int) -> list[IndexCandidate]:
        try:
            return self._index.search_vector(query, target=target, limit=limit)
        except Exception:
            return []
