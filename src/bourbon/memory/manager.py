"""MemoryManager orchestration layer."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from bourbon.audit.events import AuditEvent, EventType
from bourbon.config import MemoryConfig
from bourbon.memory.cues import expand_query_terms, generate_cues
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
from bourbon.memory.store import MemoryStore

if TYPE_CHECKING:
    from bourbon.audit import AuditLogger


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
        self._recent_writes: list[RecentWriteSummary] = []
        self._last_expanded_terms: tuple[str, ...] = ()

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
            raise PermissionError(f"Actor {actor.kind}:{actor.agent_type} cannot write target={target}")
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
        terms = expand_query_terms(query)
        self._last_expanded_terms = terms
        results: list[MemorySearchResult] = []
        seen: set[str] = set()
        for term in terms:
            for result in self._store.search(
                term,
                target=target,
                limit=limit or self.config.recall_limit,
            ):
                if result.id in seen:
                    continue
                results.append(result)
                seen.add(result.id)
                if len(results) >= (limit or self.config.recall_limit):
                    self._record_search_audit(query=query, target=target, result_count=len(results))
                    return results
        self._record_search_audit(query=query, target=target, result_count=len(results))
        return results

    def delete(self, memory_id: str, *, actor: MemoryActor) -> None:
        check_delete_permission(actor)
        self._store.delete_record(memory_id)
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
            ) >= 200
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
