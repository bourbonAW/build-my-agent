"""Derived SQLite search index for Bourbon memory."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable
from contextlib import suppress
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


@dataclass(frozen=True)
class _PreparedRecord:
    record: MemoryRecord
    search_text: str
    vector: tuple[float, ...]


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
        self._set_meta_if_absent(conn, "schema_version", INDEX_SCHEMA_VERSION)
        self._set_meta_if_absent(conn, "search_text_version", SEARCH_TEXT_VERSION)
        self._set_meta_if_absent(conn, "embedding_provider", self.provider.name)
        self._set_meta_if_absent(conn, "embedding_model", self.provider.model)

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: object) -> None:
        conn.execute(
            """
            insert into memory_index_meta(key, value) values (?, ?)
            on conflict(key) do update set value = excluded.value
            """,
            (key, str(value)),
        )

    def _set_meta_if_absent(self, conn: sqlite3.Connection, key: str, value: object) -> None:
        conn.execute(
            "insert or ignore into memory_index_meta(key, value) values (?, ?)",
            (key, str(value)),
        )

    def _read_meta(self, conn: sqlite3.Connection) -> dict[str, str]:
        return {
            str(key): str(value)
            for key, value in conn.execute("select key, value from memory_index_meta").fetchall()
        }

    def _expected_meta(self) -> dict[str, str]:
        return {
            "schema_version": INDEX_SCHEMA_VERSION,
            "search_text_version": SEARCH_TEXT_VERSION,
            "embedding_provider": self.provider.name,
            "embedding_model": self.provider.model,
        }

    def _metadata_needs_rebuild(
        self,
        meta: dict[str, str],
        *,
        dimensions: int | None = None,
        probe_text: str | None = None,
    ) -> bool:
        for key, value in self._expected_meta().items():
            if meta.get(key) != value:
                return True

        if dimensions is None:
            dimensions = self.provider.dimensions
        if dimensions is None and probe_text is not None and meta.get("embedding_dimensions"):
            dimensions = len(self.provider.embed_query(probe_text))
        return dimensions is not None and meta.get("embedding_dimensions") != str(dimensions)

    def _records_need_rebuild(
        self,
        conn: sqlite3.Connection,
        records: list[MemoryRecord],
        *,
        meta: dict[str, str],
    ) -> bool:
        actual = {
            (str(memory_id), str(target), str(content_hash))
            for memory_id, target, content_hash in conn.execute(
                "select memory_id, target, content_hash from memory_index_records"
            ).fetchall()
        }
        expected = {
            (record.id, record.target, _content_hash(render_search_text(record)))
            for record in records
        }
        if actual != expected:
            return True
        return bool(records) and not meta.get("embedding_dimensions")

    def needs_rebuild(
        self,
        *,
        records: Iterable[MemoryRecord] | None = None,
        probe_text: str | None = None,
    ) -> bool:
        """Return whether the derived index is missing, stale, or unreadable."""
        if not self.index_path.exists():
            return True
        record_list = list(records) if records is not None else None
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                meta = self._read_meta(conn)
                if self._metadata_needs_rebuild(meta, probe_text=probe_text):
                    return True
                if record_list is None:
                    return False
                return self._records_need_rebuild(conn, record_list, meta=meta)
        except sqlite3.DatabaseError:
            return True

    def _write_current_meta(
        self,
        conn: sqlite3.Connection,
        *,
        dimensions: int | None,
    ) -> None:
        for key, value in self._expected_meta().items():
            self._set_meta(conn, key, value)
        if dimensions is None:
            conn.execute("delete from memory_index_meta where key = ?", ("embedding_dimensions",))
        else:
            self._set_meta(conn, "embedding_dimensions", dimensions)

    def _prepare_records(self, records: Iterable[MemoryRecord]) -> list[_PreparedRecord]:
        record_list = list(records)
        search_texts = [render_search_text(record) for record in record_list]
        vectors = self.provider.embed_passages(search_texts)
        if len(vectors) != len(record_list):
            raise ValueError("Embedding provider returned the wrong number of vectors")
        prepared = [
            _PreparedRecord(
                record=record,
                search_text=search_text,
                vector=tuple(vector),
            )
            for record, search_text, vector in zip(record_list, search_texts, vectors, strict=True)
        ]
        dimensions = {len(item.vector) for item in prepared}
        if len(dimensions) > 1:
            raise ValueError("Embedding provider returned mixed vector dimensions")
        return prepared

    def _upsert_prepared(self, conn: sqlite3.Connection, prepared: _PreparedRecord) -> None:
        dimensions = len(prepared.vector)
        record = prepared.record
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
                _content_hash(prepared.search_text),
                record.created_at.isoformat(),
                prepared.search_text,
            ),
        )
        conn.execute("delete from memory_fts where memory_id = ?", (record.id,))
        conn.execute(
            "insert into memory_fts(memory_id, search_text) values (?, ?)",
            (record.id, prepared.search_text),
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
                pack_vector(prepared.vector),
            ),
        )

    def _remove_index_files(self) -> None:
        for path in (
            self.index_path,
            Path(f"{self.index_path}-wal"),
            Path(f"{self.index_path}-shm"),
        ):
            with suppress(FileNotFoundError):
                path.unlink()

    def _should_reset_after_database_error(self, exc: sqlite3.DatabaseError) -> bool:
        message = str(exc).casefold()
        return (
            "not a database" in message
            or "database disk image is malformed" in message
            or "file is encrypted" in message
        )

    def _replace_records(self, prepared: list[_PreparedRecord]) -> None:
        dimensions = len(prepared[0].vector) if prepared else self.provider.dimensions
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn:
                conn.execute("delete from memory_index_records")
                conn.execute("delete from memory_fts")
                conn.execute("delete from memory_vectors")
                for item in prepared:
                    self._upsert_prepared(conn, item)
                self._write_current_meta(conn, dimensions=dimensions)

    def upsert(self, record: MemoryRecord) -> None:
        search_text = render_search_text(record)
        vector = self.provider.embed_passages([search_text])[0]
        dimensions = len(vector)
        prepared = _PreparedRecord(
            record=record,
            search_text=search_text,
            vector=tuple(vector),
        )
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn:
                self._upsert_prepared(conn, prepared)
                self._write_current_meta(conn, dimensions=dimensions)

    def delete(self, memory_id: str) -> None:
        with self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute("delete from memory_index_records where memory_id = ?", (memory_id,))
            conn.execute("delete from memory_fts where memory_id = ?", (memory_id,))
            conn.execute("delete from memory_vectors where memory_id = ?", (memory_id,))

    def rebuild(self, records: Iterable[MemoryRecord]) -> None:
        prepared = self._prepare_records(records)
        try:
            self._replace_records(prepared)
        except sqlite3.DatabaseError as exc:
            if not self._should_reset_after_database_error(exc):
                raise
            self._remove_index_files()
            self._replace_records(prepared)

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
