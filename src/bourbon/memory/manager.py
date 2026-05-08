"""MemoryManager orchestration layer."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from bourbon.audit.events import AuditEvent, EventType
from bourbon.config import MemoryConfig
from bourbon.memory.cues import expand_query_terms, generate_cues
from bourbon.memory.embeddings import FastEmbedProvider
from bourbon.memory.models import (
    MEMORY_TARGETS,
    MemoryActor,
    MemoryRecord,
    MemoryRecordDraft,
    MemorySearchResult,
    MemorySystemInfo,
    RecentWriteSummary,
    validate_memory_target,
)
from bourbon.memory.policy import check_delete_permission, check_write_permission
from bourbon.memory.retriever import MemoryRetriever
from bourbon.memory.search_index import MemorySearchIndex
from bourbon.memory.store import MEMORY_INDEX_LINE_LIMIT, MemoryStore

if TYPE_CHECKING:
    from bourbon.audit import AuditLogger

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return f"mem_{secrets.token_hex(4)}"


def _preview(content: str, *, limit: int = 100) -> str:
    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    return (first_line or content.strip())[:limit].rstrip()


class MemoryManager:
    """High-level facade for memory writes, search, delete, and status."""

    def __init__(
        self,
        *,
        config: MemoryConfig,
        project_key: str,
        workdir: Path,
        audit: AuditLogger | None,
    ) -> None:
        self.config = config
        self.project_key = project_key
        self.workdir = workdir
        self._audit = audit
        self._memory_dir = Path(config.storage_dir).expanduser() / project_key / "memory"
        self._store = MemoryStore(memory_dir=self._memory_dir)
        self._search_index = self._make_search_index()
        self._retriever = (
            MemoryRetriever(store=self._store, index=self._search_index)
            if self._search_index is not None
            else None
        )
        self._recent_writes: list[RecentWriteSummary] = []
        self._last_expanded_terms: tuple[str, ...] = ()

    def _make_search_index(self) -> MemorySearchIndex | None:
        semantic = self.config.semantic
        if not semantic.enabled:
            return None
        if semantic.provider != "fastembed":
            logger.warning("Unsupported memory semantic provider: %s", semantic.provider)
            return None
        provider = FastEmbedProvider(model=semantic.model)
        return MemorySearchIndex(
            self._memory_dir / "search_index.sqlite",
            provider,
            top_k=semantic.top_k,
            min_similarity=semantic.min_similarity,
        )

    def _ensure_search_index_current(self, *, probe_text: str | None = None) -> bool:
        if self._search_index is None:
            return False
        try:
            records = self._store.list_records()
            if not self._search_index.needs_rebuild(records=records, probe_text=probe_text):
                return False
            self._search_index.rebuild(records)
            return True
        except Exception:
            logger.warning("Memory semantic index rebuild failed", exc_info=True)
            return False

    def get_memory_dir(self) -> Path:
        return self._memory_dir

    def get_last_expanded_terms(self) -> tuple[str, ...]:
        return self._last_expanded_terms

    def write(self, draft: MemoryRecordDraft, *, actor: MemoryActor) -> MemoryRecord:
        target = validate_memory_target(draft.target)
        content = draft.content.strip()
        if not content:
            raise ValueError("Memory content must be non-empty")
        if not check_write_permission(actor, target=target):
            raise PermissionError(
                f"Actor {actor.kind}:{actor.agent_type} cannot write target={target}"
            )
        if self._audit is None:
            raise RuntimeError("memory writes require audit")

        record = MemoryRecord(
            id=_generate_id(),
            target=target,
            content=content,
            created_at=datetime.now(UTC),
            cues=generate_cues(content),
        )
        self._store.write_record(record)
        if self._search_index is not None:
            try:
                rebuilt = self._ensure_search_index_current()
                if not rebuilt:
                    self._search_index.upsert(record)
            except Exception:
                logger.warning("Memory semantic index upsert failed", exc_info=True)
        self._recent_writes.append(
            RecentWriteSummary(
                id=record.id,
                target=record.target,
                preview=_preview(record.content),
                created_at=record.created_at,
            )
        )
        self._recent_writes = self._recent_writes[-10:]
        self._record_audit(
            EventType.MEMORY_WRITE,
            tool_input_summary=_preview(record.content),
            memory_id=record.id,
            target=record.target,
            actor_kind=actor.kind,
            session_id=actor.session_id,
            run_id=actor.run_id,
            agent_type=actor.agent_type,
            content_preview=_preview(record.content),
        )
        return record

    def search(
        self,
        query: str,
        *,
        target: str | None = None,
        limit: int | None = None,
    ) -> list[MemorySearchResult]:
        if target is not None:
            target = validate_memory_target(target)
        effective_limit = limit if limit is not None else self.config.recall_limit
        terms = expand_query_terms(query)
        self._last_expanded_terms = terms
        if self._retriever is not None:
            try:
                self._ensure_search_index_current(probe_text=query)
                semantic_results = self._retriever.search(
                    query,
                    terms=terms,
                    target=target,
                    limit=effective_limit,
                )
                self._record_search_audit(
                    query=query,
                    target=target,
                    result_count=len(semantic_results),
                )
                return semantic_results
            except Exception:
                logger.warning("Memory semantic retriever failed; falling back", exc_info=True)
        results: list[MemorySearchResult] = []
        seen: set[str] = set()
        for term in terms:
            for result in self._store.search(
                term,
                target=target,
                limit=effective_limit,
            ):
                if result.id in seen:
                    continue
                results.append(result)
                seen.add(result.id)
                if len(results) >= effective_limit:
                    self._record_search_audit(query=query, target=target, result_count=len(results))
                    return results
        self._record_search_audit(query=query, target=target, result_count=len(results))
        return results

    def delete(self, memory_id: str, *, actor: MemoryActor) -> None:
        check_delete_permission(actor)
        self._store.delete_record(memory_id)
        if self._search_index is not None:
            try:
                self._search_index.delete(memory_id)
            except Exception:
                logger.warning("Memory semantic index delete failed", exc_info=True)
        self._record_audit(
            EventType.MEMORY_DELETE,
            tool_input_summary=memory_id,
            memory_id=memory_id,
            actor_kind=actor.kind,
            session_id=actor.session_id,
            run_id=actor.run_id,
            agent_type=actor.agent_type,
        )

    def get_status(self, *, actor: MemoryActor) -> MemorySystemInfo:
        writable_targets = ["project"] if actor.kind == "subagent" else list(MEMORY_TARGETS)
        memory_file_count = 0
        if self._memory_dir.exists():
            memory_file_count = len(
                [path for path in self._memory_dir.glob("*.md") if path.name != "MEMORY.md"]
            )
        index_path = self._memory_dir / "MEMORY.md"
        index_at_capacity = False
        if index_path.exists():
            index_at_capacity = len(
                [line for line in index_path.read_text(encoding="utf-8").splitlines() if line]
            ) >= MEMORY_INDEX_LINE_LIMIT
        return MemorySystemInfo(
            readable_targets=MEMORY_TARGETS,
            writable_targets=tuple(writable_targets),
            recent_writes=tuple(self._recent_writes),
            index_at_capacity=index_at_capacity,
            memory_file_count=memory_file_count,
        )

    def _record_search_audit(self, *, query: str, target: str | None, result_count: int) -> None:
        self._record_audit(
            EventType.MEMORY_SEARCH,
            tool_input_summary=query[:100],
            query=query,
            target=target,
            result_count=result_count,
        )

    def _record_audit(
        self,
        event_type: EventType,
        *,
        tool_input_summary: str,
        **extra: object,
    ) -> None:
        if self._audit is None:
            return
        self._audit.record(
            AuditEvent(
                timestamp=datetime.now(UTC),
                event_type=event_type,
                tool_name="memory",
                tool_input_summary=tool_input_summary,
                extra=extra,
            )
        )
