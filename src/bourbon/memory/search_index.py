"""Derived SQLite search index for Bourbon memory."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from bourbon.memory.embeddings import (
    EmbeddingProvider,
    cosine_similarity,
    pack_vector,
    unpack_vector,
)
from bourbon.memory.models import MemoryRecord

INDEX_SCHEMA_VERSION = "memory-search-index-v1"
SEARCH_TEXT_VERSION = "memory-search-text-v1"


@dataclass(frozen=True)
class IndexCandidate:
    """A candidate produced by the local search index."""

    memory_id: str
    channel: Literal["fts", "semantic"]
    score: float
    reason: str


def render_search_text(record: MemoryRecord) -> str:
    """Render searchable text derived from the authoritative memory record."""
    parts = [record.content.strip()]
    if record.cues:
        parts.append("cues:\n" + "\n".join(record.cues))
    return "\n\n".join(part for part in parts if part)


def _content_hash(search_text: str) -> str:
    return hashlib.sha256(search_text.encode("utf-8")).hexdigest()


class MemorySearchIndex:
    """Rebuildable SQLite FTS + dense vector index for memory records."""

    def __init__(
        self,
        index_path: Path,
        provider: EmbeddingProvider,
        *,
        top_k: int,
        min_similarity: float,
    ) -> None:
        self.index_path = index_path
        self.provider = provider
        self.top_k = top_k
        self.min_similarity = min_similarity

    def _connect(self) -> sqlite3.Connection:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.index_path)
        conn.execute("pragma journal_mode=wal")
        conn.execute("pragma busy_timeout=5000")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            create table if not exists memory_index_meta (
              key text primary key,
              value text not null
            );

            create table if not exists memory_index_records (
              memory_id text primary key,
              target text not null,
              content_hash text not null,
              created_at text not null,
              search_text text not null
            );

            create virtual table if not exists memory_fts using fts5(
              memory_id unindexed,
              search_text,
              tokenize='unicode61'
            );

            create table if not exists memory_vectors (
              memory_id text primary key,
              provider text not null,
              model text not null,
              dimensions integer not null,
              vector blob not null
            );
            """
        )
        self._set_meta(conn, "schema_version", INDEX_SCHEMA_VERSION)
        self._set_meta(conn, "search_text_version", SEARCH_TEXT_VERSION)
        self._set_meta(conn, "embedding_provider", self.provider.name)
        self._set_meta(conn, "embedding_model", self.provider.model)

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: object) -> None:
        conn.execute(
            """
            insert into memory_index_meta(key, value) values (?, ?)
            on conflict(key) do update set value = excluded.value
            """,
            (key, str(value)),
        )

    def upsert(self, record: MemoryRecord) -> None:
        search_text = render_search_text(record)
        vector = self.provider.embed_passages([search_text])[0]
        dimensions = len(vector)
        with self._connect() as conn:
            self._ensure_schema(conn)
            self._set_meta(conn, "embedding_dimensions", dimensions)
            conn.execute(
                """
                insert into memory_index_records(
                  memory_id,
                  target,
                  content_hash,
                  created_at,
                  search_text
                )
                values (?, ?, ?, ?, ?)
                on conflict(memory_id) do update set
                  target = excluded.target,
                  content_hash = excluded.content_hash,
                  created_at = excluded.created_at,
                  search_text = excluded.search_text
                """,
                (
                    record.id,
                    record.target,
                    _content_hash(search_text),
                    record.created_at.isoformat(),
                    search_text,
                ),
            )
            conn.execute("delete from memory_fts where memory_id = ?", (record.id,))
            conn.execute(
                "insert into memory_fts(memory_id, search_text) values (?, ?)",
                (record.id, search_text),
            )
            conn.execute(
                """
                insert into memory_vectors(memory_id, provider, model, dimensions, vector)
                values (?, ?, ?, ?, ?)
                on conflict(memory_id) do update set
                  provider = excluded.provider,
                  model = excluded.model,
                  dimensions = excluded.dimensions,
                  vector = excluded.vector
                """,
                (
                    record.id,
                    self.provider.name,
                    self.provider.model,
                    dimensions,
                    pack_vector(vector),
                ),
            )

    def delete(self, memory_id: str) -> None:
        with self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute("delete from memory_index_records where memory_id = ?", (memory_id,))
            conn.execute("delete from memory_fts where memory_id = ?", (memory_id,))
            conn.execute("delete from memory_vectors where memory_id = ?", (memory_id,))

    def rebuild(self, records: Iterable[MemoryRecord]) -> None:
        with self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute("delete from memory_index_records")
            conn.execute("delete from memory_fts")
            conn.execute("delete from memory_vectors")
        for record in records:
            self.upsert(record)

    def search_fts(
        self,
        query: str,
        *,
        target: str | None,
        limit: int,
    ) -> list[IndexCandidate]:
        if not query.strip():
            return []
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                rows = conn.execute(
                    """
                    select memory_fts.memory_id
                    from memory_fts
                    join memory_index_records
                      on memory_index_records.memory_id = memory_fts.memory_id
                    where memory_fts match ?
                      and (? is null or memory_index_records.target = ?)
                    limit ?
                    """,
                    (query, target, target, limit),
                ).fetchall()
        except sqlite3.Error:
            return []
        return [
            IndexCandidate(
                memory_id=str(row[0]),
                channel="fts",
                score=1.0,
                reason=f"matched fts: {query}",
            )
            for row in rows
        ]

    def search_vector(
        self,
        query: str,
        *,
        target: str | None,
        limit: int,
    ) -> list[IndexCandidate]:
        if not query.strip():
            return []
        query_vector = self.provider.embed_query(query)
        dimensions = len(query_vector)
        with self._connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                select memory_vectors.memory_id, memory_vectors.vector
                from memory_vectors
                join memory_index_records
                  on memory_index_records.memory_id = memory_vectors.memory_id
                where memory_vectors.provider = ?
                  and memory_vectors.model = ?
                  and memory_vectors.dimensions = ?
                  and (? is null or memory_index_records.target = ?)
                """,
                (self.provider.name, self.provider.model, dimensions, target, target),
            ).fetchall()
        candidates: list[IndexCandidate] = []
        for memory_id, blob in rows:
            vector = unpack_vector(blob, dimensions)
            similarity = cosine_similarity(query_vector, vector)
            if similarity < self.min_similarity:
                continue
            candidates.append(
                IndexCandidate(
                    memory_id=str(memory_id),
                    channel="semantic",
                    score=similarity,
                    reason=f"matched semantic: {similarity:.2f}",
                )
            )
        candidates.sort(key=lambda candidate: (-candidate.score, candidate.memory_id))
        return candidates[: min(limit, self.top_k)]
