"""MemoryManager orchestration layer."""

from __future__ import annotations

import secrets
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bourbon.audit.events import AuditEvent, EventType
from bourbon.config import MemoryConfig
from bourbon.memory.compact import extract_flush_candidates
from bourbon.memory.files import upsert_managed_block, update_managed_block_status
from bourbon.memory.models import (
    MemoryActor,
    MemoryRecord,
    MemoryRecordDraft,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
    MemoryStatus,
    MemoryStatusInfo,
    RecentWriteSummary,
    actor_to_created_by,
)
from bourbon.memory.policy import (
    check_archive_permission,
    check_promote_permission,
    check_write_permission,
)
from bourbon.memory.store import MemoryStore

if TYPE_CHECKING:
    from bourbon.audit import AuditLogger


def _generate_id() -> str:
    return f"mem_{secrets.token_hex(4)}"


def _derive_name(draft: MemoryRecordDraft) -> str:
    if draft.name:
        return draft.name
    first_line = draft.content.splitlines()[0].strip() if draft.content else ""
    return first_line[:60] or "Untitled memory"


def _derive_description(draft: MemoryRecordDraft, *, name: str) -> str:
    if draft.description:
        return draft.description
    first_line = draft.content.splitlines()[0].strip() if draft.content else ""
    return first_line[:120] or name


def _managed_block_marker(memory_id: str) -> str:
    return f'<!-- bourbon-memory:start id="{memory_id}" -->'


class MemoryManager:
    """High-level facade for memory writes, search, and status."""

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

    def get_memory_dir(self) -> Path:
        """Return the backing memory directory."""
        return self._memory_dir

    def _global_user_md_path(self) -> Path:
        return Path("~/.bourbon/USER.md").expanduser()

    def _require_promoted_projection(self, user_md_path: Path, memory_id: str) -> None:
        if not user_md_path.exists():
            raise RuntimeError("Managed USER.md projection missing")

        text = user_md_path.read_text(encoding="utf-8")
        if _managed_block_marker(memory_id) not in text:
            raise RuntimeError(f"Managed USER.md block missing for {memory_id}")

    def promote(self, memory_id: str, actor: MemoryActor, note: str = "") -> MemoryRecord:
        """Promote an eligible record into the managed global USER.md section."""
        record = self._store.read_record(memory_id)
        if record is None:
            raise KeyError(f"Unknown memory id: {memory_id}")
        if record.status not in {MemoryStatus.ACTIVE, MemoryStatus.STALE}:
            raise ValueError(f"Cannot promote record with status {record.status}")
        check_promote_permission(actor, record)

        promotion_time = datetime.now(record.updated_at.tzinfo or UTC)
        promoted_record = replace(
            record,
            status=MemoryStatus.PROMOTED,
            updated_at=promotion_time,
        )
        global_user_md = self._global_user_md_path()
        source_filename = self._store._id_to_filename.get(record.id)
        source_path = self._memory_dir / source_filename if source_filename else None
        upsert_managed_block(
            global_user_md,
            promoted_record,
            note=note,
            source_path=source_path,
        )
        updated = self._store.update_status(memory_id, MemoryStatus.PROMOTED)
        self._record_audit(
            EventType.MEMORY_PROMOTE,
            tool_input_summary=record.name,
            memory_id=record.id,
            actor=actor_to_created_by(actor),
        )
        return updated

    def archive(
        self,
        memory_id: str,
        status: MemoryStatus,
        actor: MemoryActor,
        reason: str = "",
    ) -> MemoryRecord:
        """Archive a record as stale or rejected, updating USER.md when needed."""
        record = self._store.read_record(memory_id)
        if record is None:
            raise KeyError(f"Unknown memory id: {memory_id}")
        if status not in {MemoryStatus.STALE, MemoryStatus.REJECTED}:
            raise ValueError(f"Cannot archive record as {status}")
        check_archive_permission(actor, record)

        if record.status == MemoryStatus.PROMOTED:
            user_md_path = self._global_user_md_path()
            self._require_promoted_projection(user_md_path, memory_id)
            update_managed_block_status(
                user_md_path,
                memory_id,
                str(status),
            )
            self._require_promoted_projection(user_md_path, memory_id)

        updated = self._store.update_status(memory_id, status)
        self._record_audit(
            EventType.MEMORY_REJECT,
            tool_input_summary=record.name,
            memory_id=record.id,
            archive_status=str(status),
            actor=actor_to_created_by(actor),
            reason=reason,
        )
        return updated

    def write(self, draft: MemoryRecordDraft, *, actor: MemoryActor) -> MemoryRecord:
        """Persist a new memory record and update the MEMORY.md index."""
        if not check_write_permission(actor, kind=draft.kind, scope=draft.scope):
            raise PermissionError(
                f"Actor {actor.kind}:{actor.agent_type} cannot write "
                f"kind={draft.kind} scope={draft.scope}"
            )

        now = datetime.now(UTC)
        name = _derive_name(draft)
        description = _derive_description(draft, name=name)
        record = MemoryRecord(
            id=_generate_id(),
            name=name,
            description=description,
            kind=draft.kind,
            scope=draft.scope,
            confidence=draft.confidence,
            source=draft.source,
            status=MemoryStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            created_by=actor_to_created_by(actor),
            content=draft.content,
            source_ref=draft.source_ref,
        )

        self._store.write_record(record)
        self._store.update_index(record)
        self._recent_writes.append(
            RecentWriteSummary(
                id=record.id,
                name=record.name,
                kind=record.kind,
                created_at=record.created_at,
            )
        )
        self._recent_writes = self._recent_writes[-10:]
        self._record_audit(
            EventType.MEMORY_WRITE,
            tool_input_summary=record.name,
            memory_id=record.id,
            memory_kind=str(record.kind),
            memory_scope=str(record.scope),
            actor=actor_to_created_by(actor),
        )
        return record

    def search(
        self,
        query: str,
        *,
        scope: str | None = None,
        kind: list[str] | None = None,
        limit: int | None = None,
        status: list[str] | None = None,
    ) -> list[MemorySearchResult]:
        """Search stored memories."""
        results = self._store.search(
            query,
            kind=kind,
            status=status,
            limit=limit or self.config.recall_limit,
        )
        if scope is not None:
            results = [result for result in results if result.scope == scope]
        self._record_audit(
            EventType.MEMORY_SEARCH,
            tool_input_summary=query[:200],
            query=query,
            scope=scope,
            kind=kind,
            result_count=len(results),
        )
        return results

    def get_status(self, *, actor: MemoryActor) -> MemoryStatusInfo:
        """Return current memory system status for the actor."""
        if actor.kind in {"user", "agent", "system"}:
            readable_scopes = ["project", "session", "user"]
            writable_scopes = ["project", "session", "user"]
        else:
            readable_scopes = ["project", "session"]
            writable_scopes = ["project", "session"]

        memory_file_count = 0
        if self._memory_dir.exists():
            memory_file_count = len(
                [path for path in self._memory_dir.glob("*.md") if path.name != "MEMORY.md"]
            )

        index_at_capacity = False
        index_path = self._memory_dir / "MEMORY.md"
        if index_path.exists():
            lines = [line for line in index_path.read_text(encoding="utf-8").splitlines() if line]
            index_at_capacity = len(lines) >= 200

        return MemoryStatusInfo(
            readable_scopes=readable_scopes,
            writable_scopes=writable_scopes,
            prompt_anchor_tokens=0,
            recent_writes=list(self._recent_writes),
            index_at_capacity=index_at_capacity,
            memory_file_count=memory_file_count,
        )

    def flush_before_compact(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str,
    ) -> list[MemoryRecord]:
        """Persist deterministic candidates before a session compact."""
        written: list[MemoryRecord] = []
        for candidate in extract_flush_candidates(messages, session_id=session_id):
            draft = MemoryRecordDraft(
                kind=candidate.kind,
                scope=MemoryScope.SESSION,
                content=candidate.content,
                source=MemorySource.COMPACTION,
                confidence=candidate.confidence,
                source_ref=candidate.source_ref,
            )
            record = self.write(draft, actor=MemoryActor(kind="system"))
            written.append(record)

        if written:
            self._record_audit(
                EventType.MEMORY_FLUSH,
                tool_input_summary=f"flush:{session_id}",
                session_id=session_id,
                records_flushed=len(written),
                record_ids=[record.id for record in written],
            )

        return written

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
