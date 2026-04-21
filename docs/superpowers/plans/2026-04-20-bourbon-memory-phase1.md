# Bourbon Memory Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Bourbon's file-first memory system: structured memory records with YAML frontmatter, grep-based recall, prompt anchor injection, pre-compact flush, and three memory tools (MemorySearch, MemoryWrite, MemoryStatus).

**Architecture:** New `src/bourbon/memory/` package with a `MemoryManager` facade. Memory records are individual `.md` files under `~/.bourbon/projects/{sanitized-project}/memory/`. `MEMORY.md` serves as an always-injected index. Prompt anchors (`AGENTS.md`, `USER.md`, `MEMORY.md`) are rendered via a new order=15 prompt section. Tools are registered via `@register_tool` and route through thin handlers to `MemoryManager`. Pre-compact flush is a deterministic heuristic (no LLM) triggered in `Agent._step_impl()` and `Agent._step_stream_impl()`.

**Tech Stack:** Python 3.11+, dataclasses, YAML (via `yaml` stdlib or frontmatter parsing), `subprocess` for ripgrep, `threading.Lock` for process-local write safety, existing `AuditLogger`.

**Spec:** `docs/superpowers/specs/2026-04-19-bourbon-memory-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/bourbon/memory/__init__.py` | Export `MemoryManager`, models |
| Create | `src/bourbon/memory/models.py` | `MemoryRecord`, `MemoryRecordDraft`, `SourceRef`, `MemoryActor`, `MemorySearchResult`, `MemoryStatus`, enums |
| Create | `src/bourbon/memory/store.py` | File CRUD (atomic rename), MEMORY.md index, grep search |
| Create | `src/bourbon/memory/files.py` | `AGENTS.md` / `USER.md` / `MEMORY.md` reading, `USER.md` merge |
| Create | `src/bourbon/memory/manager.py` | `MemoryManager` orchestration (search, write, status, flush) |
| Create | `src/bourbon/memory/policy.py` | Scope/kind checks for agent types |
| Create | `src/bourbon/memory/prompt.py` | Render bounded memory prompt section (order=15) |
| Create | `src/bourbon/memory/compact.py` | Pre-compact flush heuristics |
| Create | `src/bourbon/tools/memory.py` | `MemorySearch`, `MemoryWrite`, `MemoryStatus` tool handlers |
| Modify | `src/bourbon/config.py` | Add `MemoryConfig` dataclass |
| Modify | `src/bourbon/tools/__init__.py` | Add `memory_manager`/`memory_actor` to `ToolContext`, lazy import |
| Modify | `src/bourbon/prompt/types.py` | Add `memory_manager` to `PromptContext` |
| Modify | `src/bourbon/prompt/__init__.py` | Include anchor section in `ALL_SECTIONS` |
| Modify | `src/bourbon/agent.py` | Init `MemoryManager`, wire flush hook, pass to contexts |
| Modify | `src/bourbon/audit/events.py` | Add memory event types |
| Create | `tests/test_memory_models.py` | Model validation tests |
| Create | `tests/test_memory_store.py` | Store CRUD and grep tests |
| Create | `tests/test_memory_files.py` | File reading and USER.md merge tests |
| Create | `tests/test_memory_manager.py` | Manager integration tests |
| Create | `tests/test_memory_prompt.py` | Prompt section rendering tests |
| Create | `tests/test_memory_tools.py` | Tool handler tests |

---

## Task 1: Memory Models (`models.py`)

**Files:**
- Create: `src/bourbon/memory/__init__.py`
- Create: `src/bourbon/memory/models.py`
- Test: `tests/test_memory_models.py`

- [x] **Step 1: Write failing tests for enums and MemoryActor**

```python
# tests/test_memory_models.py
import pytest
from bourbon.memory.models import (
    MemoryKind, MemoryScope, MemorySource, MemoryStatus as MemStatus,
    MemoryActor, actor_to_created_by,
)


def test_memory_kind_values():
    assert {e.value for e in MemoryKind} == {"user", "feedback", "project", "reference"}


def test_memory_scope_values():
    assert {e.value for e in MemoryScope} == {"user", "project", "session"}


def test_memory_source_values():
    assert {e.value for e in MemorySource} == {"user", "agent", "subagent", "compaction", "manual"}


def test_memory_status_values():
    assert {e.value for e in MemStatus} == {"active", "stale", "rejected"}


def test_actor_user():
    actor = MemoryActor(kind="user")
    assert actor_to_created_by(actor) == "user"


def test_actor_agent():
    actor = MemoryActor(kind="agent", session_id="ses_abc123")
    assert actor_to_created_by(actor) == "agent:ses_abc123"


def test_actor_subagent():
    actor = MemoryActor(kind="subagent", run_id="run_xyz", agent_type="explore")
    assert actor_to_created_by(actor) == "subagent:run_xyz"


def test_actor_system():
    actor = MemoryActor(kind="system")
    assert actor_to_created_by(actor) == "system:system"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bourbon.memory'`

- [x] **Step 3: Implement enums and MemoryActor**

```python
# src/bourbon/memory/__init__.py
"""Bourbon memory system."""

from bourbon.memory.models import (
    MemoryActor,
    MemoryKind,
    MemoryRecord,
    MemoryRecordDraft,
    MemoryScope,
    MemorySource,
    MemoryStatus,
    SourceRef,
    actor_to_created_by,
)

__all__ = [
    "MemoryActor",
    "MemoryKind",
    "MemoryRecord",
    "MemoryRecordDraft",
    "MemoryScope",
    "MemorySource",
    "MemoryStatus",
    "SourceRef",
    "actor_to_created_by",
]
```

```python
# src/bourbon/memory/models.py
"""Memory data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal


class MemoryKind(StrEnum):
    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"


class MemoryScope(StrEnum):
    USER = "user"
    PROJECT = "project"
    SESSION = "session"


class MemorySource(StrEnum):
    USER = "user"
    AGENT = "agent"
    SUBAGENT = "subagent"
    COMPACTION = "compaction"
    MANUAL = "manual"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    REJECTED = "rejected"


@dataclass(frozen=True)
class MemoryActor:
    """Identifies who is performing a memory operation."""

    kind: Literal["user", "agent", "subagent", "system"]
    session_id: str | None = None
    run_id: str | None = None
    agent_type: str | None = None


def actor_to_created_by(actor: MemoryActor) -> str:
    """Derive created_by string from actor."""
    if actor.kind == "user":
        return "user"
    if actor.kind == "agent":
        return f"agent:{actor.session_id}"
    if actor.kind == "subagent":
        return f"subagent:{actor.run_id}"
    return f"system:{actor.kind}"
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_memory_models.py -v`
Expected: PASS

- [x] **Step 5: Write failing tests for SourceRef with __post_init__ validation**

```python
# append to tests/test_memory_models.py
from bourbon.memory.models import SourceRef


def test_source_ref_transcript_valid():
    ref = SourceRef(kind="transcript", project_name="proj", session_id="ses_1", message_uuid="msg_1")
    assert ref.kind == "transcript"


def test_source_ref_transcript_missing_session():
    with pytest.raises(ValueError, match="session_id"):
        SourceRef(kind="transcript", project_name="proj", message_uuid="msg_1")


def test_source_ref_file_valid():
    ref = SourceRef(kind="file", file_path="/path/to/file.md")
    assert ref.file_path == "/path/to/file.md"


def test_source_ref_file_missing_path():
    with pytest.raises(ValueError, match="file_path"):
        SourceRef(kind="file")


def test_source_ref_range_requires_both_start_end():
    with pytest.raises(ValueError, match="start_message_uuid.*end_message_uuid"):
        SourceRef(kind="transcript_range", project_name="proj", session_id="ses_1", start_message_uuid="msg_1")


def test_source_ref_range_valid():
    ref = SourceRef(
        kind="transcript_range", project_name="proj", session_id="ses_1",
        start_message_uuid="msg_1", end_message_uuid="msg_5",
    )
    assert ref.start_message_uuid == "msg_1"


def test_source_ref_message_uuid_and_range_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        SourceRef(
            kind="transcript", project_name="proj", session_id="ses_1",
            message_uuid="msg_1", start_message_uuid="msg_2", end_message_uuid="msg_3",
        )
```

- [x] **Step 6: Implement SourceRef**

```python
# Add to src/bourbon/memory/models.py

@dataclass(frozen=True)
class SourceRef:
    """Reference to the origin of a memory record."""

    kind: Literal["transcript", "transcript_range", "file", "tool_call", "manual"]
    project_name: str | None = None
    session_id: str | None = None
    message_uuid: str | None = None
    start_message_uuid: str | None = None
    end_message_uuid: str | None = None
    file_path: str | None = None
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        # Mutual exclusion: message_uuid vs range
        if self.message_uuid and (self.start_message_uuid or self.end_message_uuid):
            raise ValueError("message_uuid and start_message_uuid/end_message_uuid are mutually exclusive")

        # Range requires both start and end
        if bool(self.start_message_uuid) != bool(self.end_message_uuid):
            raise ValueError("start_message_uuid and end_message_uuid must both be provided or both omitted")

        # Kind-specific required fields
        if self.kind == "transcript":
            if not self.session_id:
                raise ValueError("session_id is required for transcript SourceRef")
            if not self.message_uuid:
                raise ValueError("message_uuid is required for transcript SourceRef")
        elif self.kind == "transcript_range":
            if not self.session_id:
                raise ValueError("session_id is required for transcript_range SourceRef")
            if not self.start_message_uuid or not self.end_message_uuid:
                raise ValueError("start_message_uuid and end_message_uuid are required for transcript_range SourceRef")
        elif self.kind == "file":
            if not self.file_path:
                raise ValueError("file_path is required for file SourceRef")
        elif self.kind == "tool_call":
            if not self.tool_call_id:
                raise ValueError("tool_call_id is required for tool_call SourceRef")
```

- [x] **Step 7: Run tests to verify pass**

Run: `pytest tests/test_memory_models.py -v`
Expected: PASS

- [x] **Step 8: Write failing tests for MemoryRecord and MemoryRecordDraft**

```python
# append to tests/test_memory_models.py
from bourbon.memory.models import MemoryRecord, MemoryRecordDraft
from datetime import datetime, UTC


def test_memory_record_draft_minimal():
    draft = MemoryRecordDraft(
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        content="Always use WAL mode.",
        source=MemorySource.USER,
        confidence=1.0,
    )
    assert draft.kind == "project"
    assert draft.name is None  # auto-derived later


def test_memory_record_has_all_fields():
    ref = SourceRef(kind="manual")
    record = MemoryRecord(
        id="mem_abc12345",
        name="WAL mode rule",
        description="Always use WAL mode for SQLite",
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        confidence=1.0,
        source=MemorySource.USER,
        status=MemStatus.ACTIVE,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
        updated_at=datetime(2026, 4, 20, tzinfo=UTC),
        created_by="user",
        content="Always use WAL mode for SQLite stores.",
        source_ref=ref,
    )
    assert record.id.startswith("mem_")
    assert record.status == "active"
```

- [x] **Step 9: Implement MemoryRecord and MemoryRecordDraft**

```python
# Add to src/bourbon/memory/models.py

@dataclass
class MemoryRecordDraft:
    """Input for creating a new memory record (no id, timestamps, or created_by)."""

    kind: MemoryKind
    scope: MemoryScope
    content: str
    source: MemorySource
    confidence: float = 1.0
    name: str | None = None
    description: str | None = None
    source_ref: SourceRef | None = None


@dataclass
class MemoryRecord:
    """A persisted memory record with full metadata."""

    id: str
    name: str
    description: str
    kind: MemoryKind
    scope: MemoryScope
    confidence: float
    source: MemorySource
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    created_by: str
    content: str
    source_ref: SourceRef | None = None
```

- [x] **Step 10: Run all model tests**

Run: `pytest tests/test_memory_models.py -v`
Expected: PASS

- [x] **Step 11: Write test for MemorySearchResult and status dataclass**

```python
# append to tests/test_memory_models.py
from bourbon.memory.models import MemorySearchResult, MemoryStatusInfo


def test_memory_search_result():
    result = MemorySearchResult(
        id="mem_abc12345",
        name="test",
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        snippet="Always use WAL",
        confidence=1.0,
        status=MemStatus.ACTIVE,
        source_ref=SourceRef(kind="manual"),
        why_matched="keyword: WAL",
    )
    assert result.snippet == "Always use WAL"


def test_memory_status_info():
    info = MemoryStatusInfo(
        readable_scopes=["project", "session"],
        writable_scopes=["project"],
        prompt_anchor_tokens=800,
        recent_writes=[],
        index_at_capacity=False,
        memory_file_count=5,
    )
    assert info.memory_file_count == 5
```

- [x] **Step 12: Implement MemorySearchResult and MemoryStatusInfo**

```python
# Add to src/bourbon/memory/models.py

@dataclass
class MemorySearchResult:
    """A single search result returned by MemorySearch."""

    id: str
    name: str
    kind: MemoryKind
    scope: MemoryScope
    snippet: str
    confidence: float
    status: MemoryStatus
    source_ref: SourceRef | None = None
    why_matched: str = ""


@dataclass
class RecentWriteSummary:
    """Summary of a recent memory write for MemoryStatus display."""

    id: str
    name: str
    kind: MemoryKind
    created_at: datetime


@dataclass
class MemoryStatusInfo:
    """Runtime memory status information."""

    readable_scopes: list[str]
    writable_scopes: list[str]
    prompt_anchor_tokens: int
    recent_writes: list[RecentWriteSummary]
    index_at_capacity: bool
    memory_file_count: int
    transcript_search_slow: bool = False
```

- [x] **Step 13: Run all tests, verify pass**

Run: `pytest tests/test_memory_models.py -v`
Expected: PASS

- [x] **Step 14: Commit**

```bash
git add src/bourbon/memory/__init__.py src/bourbon/memory/models.py tests/test_memory_models.py
git commit -m "feat(memory): add Phase 1 data models — enums, MemoryActor, SourceRef, MemoryRecord"
```

---

## Task 2: Memory Config (`config.py`)

**Files:**
- Modify: `src/bourbon/config.py`
- Test: `tests/test_memory_models.py` (append config tests)

- [x] **Step 1: Write failing test for MemoryConfig**

```python
# tests/test_memory_config.py
from bourbon.config import Config, MemoryConfig


def test_memory_config_defaults():
    cfg = MemoryConfig()
    assert cfg.enabled is True
    assert cfg.storage_dir == "~/.bourbon/projects"
    assert cfg.auto_flush_on_compact is True
    assert cfg.auto_extract is False
    assert cfg.recall_limit == 8
    assert cfg.recall_transcript_session_limit == 10
    assert cfg.memory_md_token_limit == 1200
    assert cfg.user_md_token_limit == 600
    assert cfg.core_block_token_limit == 1200


def test_config_from_dict_memory():
    cfg = Config.from_dict({"memory": {"enabled": False, "recall_limit": 5}})
    assert cfg.memory.enabled is False
    assert cfg.memory.recall_limit == 5


def test_config_from_dict_no_memory():
    cfg = Config.from_dict({})
    assert cfg.memory.enabled is True
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_config.py -v`
Expected: FAIL with `ImportError` or `AttributeError`

- [x] **Step 3: Implement MemoryConfig**

Add to `src/bourbon/config.py`:

```python
@dataclass
class MemoryConfig:
    """Memory system configuration."""

    enabled: bool = True
    storage_dir: str = "~/.bourbon/projects"
    auto_flush_on_compact: bool = True
    auto_extract: bool = False
    recall_limit: int = 8
    recall_transcript_session_limit: int = 10
    memory_md_token_limit: int = 1200
    user_md_token_limit: int = 600
    core_block_token_limit: int = 1200
```

Add `memory: MemoryConfig = field(default_factory=MemoryConfig)` to the `Config` class and wire into `from_dict()` / `to_dict()`.

- [x] **Step 4: Run test to verify pass**

Run: `pytest tests/test_memory_config.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/bourbon/config.py tests/test_memory_config.py
git commit -m "feat(memory): add MemoryConfig to bourbon config"
```

---

## Task 3: Sanitized Project Key

**Files:**
- Create: `src/bourbon/memory/store.py`
- Test: `tests/test_memory_store.py`

- [x] **Step 1: Write failing tests for sanitized project key**

```python
# tests/test_memory_store.py
from pathlib import Path
from bourbon.memory.store import sanitize_project_key


def test_sanitize_simple_path():
    key = sanitize_project_key(Path("/home/user/projects/bourbon"))
    # Should be slug + 8-char hash suffix
    assert key.startswith("home-user-projects-bourbon-")
    assert len(key.split("-")[-1]) == 8  # sha256 hex prefix


def test_sanitize_truncates_long_slug():
    long_path = Path("/" + "a" * 200)
    key = sanitize_project_key(long_path)
    # slug (before hash) should be ≤64 chars, total = slug + "-" + 8
    slug_part = key.rsplit("-", 1)[0]
    assert len(slug_part) <= 64


def test_sanitize_removes_non_ascii():
    key = sanitize_project_key(Path("/home/用户/project"))
    assert "用" not in key
    assert "户" not in key


def test_sanitize_same_path_same_key():
    p = Path("/home/user/myrepo")
    assert sanitize_project_key(p) == sanitize_project_key(p)


def test_sanitize_different_paths_different_keys():
    k1 = sanitize_project_key(Path("/home/user/repo1"))
    k2 = sanitize_project_key(Path("/home/user/repo2"))
    assert k1 != k2
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_store.py::test_sanitize_simple_path -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement sanitize_project_key**

```python
# src/bourbon/memory/store.py
"""Memory file store — file CRUD, MEMORY.md index, grep search."""

from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path


def sanitize_project_key(canonical_path: Path) -> str:
    """Derive a filesystem-safe project key from canonical path.

    Algorithm:
    1. Convert path to string
    2. Slugify: replace /, \\, space with -, remove non-ASCII, lowercase
    3. Truncate slug to 64 chars
    4. Append SHA256[:8] of original path
    """
    path_str = str(canonical_path)
    # Slugify
    slug = path_str.replace("/", "-").replace("\\", "-").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    slug = slug[:64]
    # Hash suffix
    hash_suffix = hashlib.sha256(path_str.encode()).hexdigest()[:8]
    return f"{slug}-{hash_suffix}"
```

- [x] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_memory_store.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/bourbon/memory/store.py tests/test_memory_store.py
git commit -m "feat(memory): implement sanitize_project_key for memory directory derivation"
```

---

## Task 4: Memory File CRUD (store.py)

**Files:**
- Modify: `src/bourbon/memory/store.py`
- Test: `tests/test_memory_store.py`

- [x] **Step 1: Write failing tests for file write and read**

```python
# append to tests/test_memory_store.py
import tempfile
from datetime import datetime, UTC
from bourbon.memory.models import (
    MemoryRecord, MemoryKind, MemoryScope, MemorySource,
    MemoryStatus as MemStatus, SourceRef,
)
from bourbon.memory.store import MemoryStore


def test_write_and_read_memory_file(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    record = MemoryRecord(
        id="mem_test1234",
        name="Test rule",
        description="A test memory record",
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        confidence=1.0,
        source=MemorySource.USER,
        status=MemStatus.ACTIVE,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
        updated_at=datetime(2026, 4, 20, tzinfo=UTC),
        created_by="user",
        content="Always use WAL mode.",
        source_ref=SourceRef(kind="manual"),
    )
    store.write_record(record)

    # File should exist with expected name
    expected_file = tmp_path / "project_test-rule.md"
    assert expected_file.exists()

    # Read it back
    loaded = store.read_record("mem_test1234")
    assert loaded is not None
    assert loaded.id == "mem_test1234"
    assert loaded.content == "Always use WAL mode."
    assert loaded.kind == MemoryKind.PROJECT


def test_write_atomic_does_not_corrupt_on_existing(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    record = MemoryRecord(
        id="mem_dup00001",
        name="Dup test",
        description="Duplicate",
        kind=MemoryKind.FEEDBACK,
        scope=MemoryScope.PROJECT,
        confidence=0.8,
        source=MemorySource.AGENT,
        status=MemStatus.ACTIVE,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
        updated_at=datetime(2026, 4, 20, tzinfo=UTC),
        created_by="agent:ses_1",
        content="Original content.",
    )
    store.write_record(record)

    # Update content
    record2 = MemoryRecord(
        id="mem_dup00001",
        name="Dup test",
        description="Duplicate updated",
        kind=MemoryKind.FEEDBACK,
        scope=MemoryScope.PROJECT,
        confidence=0.9,
        source=MemorySource.AGENT,
        status=MemStatus.ACTIVE,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
        updated_at=datetime(2026, 4, 20, 1, tzinfo=UTC),
        created_by="agent:ses_1",
        content="Updated content.",
    )
    store.write_record(record2)
    loaded = store.read_record("mem_dup00001")
    assert loaded.content == "Updated content."


def test_read_nonexistent_returns_none(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    assert store.read_record("mem_notexist") is None
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_store.py::test_write_and_read_memory_file -v`
Expected: FAIL with `ImportError`

- [x] **Step 3: Implement MemoryStore write/read**

```python
# Add to src/bourbon/memory/store.py
import os
import tempfile
from datetime import datetime, UTC

import yaml

from bourbon.memory.models import (
    MemoryRecord, MemoryKind, MemoryScope, MemorySource,
    MemoryStatus, SourceRef,
)

_index_lock = threading.Lock()


def _slugify_name(name: str) -> str:
    """Convert name to filename-safe slug."""
    slug = name.lower().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:50]


def _record_to_filename(record: MemoryRecord) -> str:
    """Derive filename from kind and name."""
    slug = _slugify_name(record.name)
    return f"{record.kind}_{slug}.md"


def _record_to_frontmatter(record: MemoryRecord) -> dict:
    """Convert record metadata to YAML frontmatter dict."""
    fm = {
        "id": record.id,
        "name": record.name,
        "description": record.description,
        "kind": str(record.kind),
        "scope": str(record.scope),
        "confidence": record.confidence,
        "source": str(record.source),
        "status": str(record.status),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "created_by": record.created_by,
    }
    if record.source_ref:
        ref_dict = {"kind": record.source_ref.kind}
        for f in ("project_name", "session_id", "message_uuid",
                  "start_message_uuid", "end_message_uuid",
                  "file_path", "tool_call_id"):
            val = getattr(record.source_ref, f)
            if val is not None:
                ref_dict[f] = val
        fm["source_ref"] = ref_dict
    return fm


def _frontmatter_to_record(fm: dict, body: str) -> MemoryRecord:
    """Parse frontmatter dict + body into MemoryRecord."""
    source_ref = None
    if "source_ref" in fm:
        ref_data = fm["source_ref"]
        source_ref = SourceRef(
            kind=ref_data["kind"],
            project_name=ref_data.get("project_name"),
            session_id=ref_data.get("session_id"),
            message_uuid=ref_data.get("message_uuid"),
            start_message_uuid=ref_data.get("start_message_uuid"),
            end_message_uuid=ref_data.get("end_message_uuid"),
            file_path=ref_data.get("file_path"),
            tool_call_id=ref_data.get("tool_call_id"),
        )

    created_at = fm["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    updated_at = fm["updated_at"]
    if isinstance(updated_at, str):
        updated_at = datetime.fromisoformat(updated_at)

    return MemoryRecord(
        id=fm["id"],
        name=fm["name"],
        description=fm["description"],
        kind=MemoryKind(fm["kind"]),
        scope=MemoryScope(fm["scope"]),
        confidence=float(fm["confidence"]),
        source=MemorySource(fm["source"]),
        status=MemoryStatus(fm["status"]),
        created_at=created_at,
        updated_at=updated_at,
        created_by=fm["created_by"],
        content=body.strip(),
        source_ref=source_ref,
    )


class MemoryStore:
    """File-based memory storage with atomic writes and grep search."""

    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir
        self._id_to_filename: dict[str, str] = {}
        self._scan_existing()

    def _scan_existing(self) -> None:
        """Build id→filename index from existing files.

        Note: This scans all .md files in memory_dir at init time.
        Phase 1 assumes ≤ a few hundred files; if this becomes a bottleneck,
        defer scanning to first read/search call.
        """
        if not self.memory_dir.exists():
            return
        for f in self.memory_dir.glob("*.md"):
            if f.name == "MEMORY.md":
                continue
            try:
                fm, _ = self._parse_file(f)
                if "id" in fm:
                    self._id_to_filename[fm["id"]] = f.name
            except Exception:
                continue

    def _parse_file(self, path: Path) -> tuple[dict, str]:
        """Parse a memory file into (frontmatter_dict, body_str)."""
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}, text
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}, text
        fm = yaml.safe_load(parts[1]) or {}
        body = parts[2]
        return fm, body

    def write_record(self, record: MemoryRecord) -> Path:
        """Write a memory record to disk using atomic rename."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        filename = _record_to_filename(record)
        target = self.memory_dir / filename

        fm = _record_to_frontmatter(record)
        content = f"---\n{yaml.dump(fm, default_flow_style=False, allow_unicode=True)}---\n\n{record.content}\n"

        # Atomic write: write to temp, then rename
        fd, tmp_path = tempfile.mkstemp(dir=self.memory_dir, suffix=".tmp")
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            fd = -1  # mark as closed
            os.replace(tmp_path, target)
        except Exception:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        self._id_to_filename[record.id] = filename
        return target

    def read_record(self, memory_id: str) -> MemoryRecord | None:
        """Read a memory record by id."""
        filename = self._id_to_filename.get(memory_id)
        if not filename:
            # Fallback: scan files
            self._scan_existing()
            filename = self._id_to_filename.get(memory_id)
        if not filename:
            return None

        path = self.memory_dir / filename
        if not path.exists():
            return None

        fm, body = self._parse_file(path)
        return _frontmatter_to_record(fm, body)

    def list_records(self, *, status: list[str] | None = None) -> list[MemoryRecord]:
        """List all memory records, optionally filtered by status."""
        records = []
        if not self.memory_dir.exists():
            return records
        for f in sorted(self.memory_dir.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            try:
                fm, body = self._parse_file(f)
                if "id" not in fm:
                    continue
                record = _frontmatter_to_record(fm, body)
                if status and record.status not in status:
                    continue
                records.append(record)
            except Exception:
                continue
        return records
```

- [x] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_memory_store.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/bourbon/memory/store.py tests/test_memory_store.py
git commit -m "feat(memory): implement MemoryStore file CRUD with atomic writes"
```

---

## Task 5: MEMORY.md Index Maintenance

**Files:**
- Modify: `src/bourbon/memory/store.py`
- Test: `tests/test_memory_store.py`

- [x] **Step 1: Write failing tests for index operations**

```python
# append to tests/test_memory_store.py

def test_update_index_adds_entry(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    record = MemoryRecord(
        id="mem_idx00001",
        name="Index test",
        description="Testing index update",
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        confidence=1.0,
        source=MemorySource.USER,
        status=MemStatus.ACTIVE,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
        updated_at=datetime(2026, 4, 20, tzinfo=UTC),
        created_by="user",
        content="Test content.",
    )
    store.write_record(record)
    store.update_index(record)

    index_path = tmp_path / "MEMORY.md"
    assert index_path.exists()
    text = index_path.read_text()
    assert "Index test" in text
    assert "project_index-test.md" in text


def test_update_index_deduplicates(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    record = MemoryRecord(
        id="mem_dedup001",
        name="Dedup entry",
        description="Should not duplicate",
        kind=MemoryKind.FEEDBACK,
        scope=MemoryScope.PROJECT,
        confidence=1.0,
        source=MemorySource.USER,
        status=MemStatus.ACTIVE,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
        updated_at=datetime(2026, 4, 20, tzinfo=UTC),
        created_by="user",
        content="Content.",
    )
    store.write_record(record)
    store.update_index(record)
    store.update_index(record)  # second call

    text = (tmp_path / "MEMORY.md").read_text()
    assert text.count("mem_dedup001") == 1  # filename contains id reference


def test_update_index_capacity_200_lines(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    # Write 200 records to fill index
    for i in range(200):
        record = MemoryRecord(
            id=f"mem_cap{i:05d}",
            name=f"Cap entry {i}",
            description=f"Entry number {i}",
            kind=MemoryKind.PROJECT,
            scope=MemoryScope.PROJECT,
            confidence=1.0,
            source=MemorySource.USER,
            status=MemStatus.ACTIVE,
            created_at=datetime(2026, 4, 20, tzinfo=UTC),
            updated_at=datetime(2026, 4, 20, tzinfo=UTC),
            created_by="user",
            content=f"Content {i}.",
        )
        store.write_record(record)
        store.update_index(record)

    # 201st should return at_capacity=True
    extra = MemoryRecord(
        id="mem_cap00200",
        name="Over capacity",
        description="Should not be indexed",
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        confidence=1.0,
        source=MemorySource.USER,
        status=MemStatus.ACTIVE,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
        updated_at=datetime(2026, 4, 20, tzinfo=UTC),
        created_by="user",
        content="Over cap.",
    )
    store.write_record(extra)
    at_capacity = store.update_index(extra)
    assert at_capacity is True

    lines = (tmp_path / "MEMORY.md").read_text().strip().split("\n")
    assert len(lines) <= 200
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_store.py::test_update_index_adds_entry -v`
Expected: FAIL with `AttributeError: 'MemoryStore' object has no attribute 'update_index'`

- [x] **Step 3: Implement update_index**

```python
# Add to MemoryStore class in src/bourbon/memory/store.py

    def update_index(self, record: MemoryRecord) -> bool:
        """Update MEMORY.md index with record entry.

        Returns True if index is at capacity (>=200 lines) and entry was NOT added.
        """
        index_path = self.memory_dir / "MEMORY.md"
        filename = _record_to_filename(record)
        entry_line = f"- [{record.name}]({filename}) — {record.description}"

        with _index_lock:
            existing_lines: list[str] = []
            if index_path.exists():
                existing_lines = index_path.read_text(encoding="utf-8").strip().split("\n")
                existing_lines = [l for l in existing_lines if l.strip()]

            # Check for existing entry with same filename (deduplicate)
            new_lines = [l for l in existing_lines if f"]({filename})" not in l]

            # Capacity check
            if len(new_lines) >= 200:
                # Write back without adding new entry
                content = "\n".join(new_lines) + "\n"
                self._atomic_write(index_path, content)
                return True

            new_lines.append(entry_line)
            content = "\n".join(new_lines) + "\n"
            self._atomic_write(index_path, content)
            return False

    def _atomic_write(self, path: Path, content: str) -> None:
        """Write content to path using atomic rename."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
```

- [x] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_memory_store.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/bourbon/memory/store.py tests/test_memory_store.py
git commit -m "feat(memory): implement MEMORY.md index maintenance with 200-line capacity"
```

---

## Task 6: Grep-Based Search

**Files:**
- Modify: `src/bourbon/memory/store.py`
- Test: `tests/test_memory_store.py`

- [x] **Step 1: Write failing tests for grep search**

```python
# append to tests/test_memory_store.py

def test_grep_search_finds_matching_content(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    record = MemoryRecord(
        id="mem_srch0001",
        name="WAL mode rule",
        description="Use WAL for SQLite",
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        confidence=1.0,
        source=MemorySource.USER,
        status=MemStatus.ACTIVE,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
        updated_at=datetime(2026, 4, 20, tzinfo=UTC),
        created_by="user",
        content="Always use WAL mode for SQLite stores to allow concurrent reads.",
    )
    store.write_record(record)

    results = store.search("WAL mode")
    assert len(results) >= 1
    assert results[0].id == "mem_srch0001"
    assert "WAL" in results[0].snippet


def test_grep_search_filters_by_kind(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    for i, kind in enumerate([MemoryKind.PROJECT, MemoryKind.USER]):
        store.write_record(MemoryRecord(
            id=f"mem_kind000{i}",
            name=f"Kind test {i}",
            description=f"Test {kind}",
            kind=kind,
            scope=MemoryScope.PROJECT,
            confidence=1.0,
            source=MemorySource.USER,
            status=MemStatus.ACTIVE,
            created_at=datetime(2026, 4, 20, tzinfo=UTC),
            updated_at=datetime(2026, 4, 20, tzinfo=UTC),
            created_by="user",
            content="Searchable content here.",
        ))

    results = store.search("Searchable", kind=["project"])
    assert len(results) == 1
    assert results[0].kind == MemoryKind.PROJECT


def test_grep_search_empty_dir_returns_empty(tmp_path):
    store = MemoryStore(memory_dir=tmp_path / "nonexistent")
    results = store.search("anything")
    assert results == []


def test_grep_search_respects_status_filter(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    store.write_record(MemoryRecord(
        id="mem_stat0001",
        name="Rejected item",
        description="Was rejected",
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        confidence=1.0,
        source=MemorySource.USER,
        status=MemStatus.REJECTED,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
        updated_at=datetime(2026, 4, 20, tzinfo=UTC),
        created_by="user",
        content="Rejected searchable content.",
    ))

    # Default: only active
    results = store.search("Rejected searchable", status=["active"])
    assert len(results) == 0

    # Explicit rejected
    results = store.search("Rejected searchable", status=["rejected"])
    assert len(results) == 1
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_store.py::test_grep_search_finds_matching_content -v`
Expected: FAIL with `AttributeError: 'MemoryStore' object has no attribute 'search'`

- [x] **Step 3: Implement grep-based search**

```python
# Add to MemoryStore class in src/bourbon/memory/store.py
import subprocess

from bourbon.memory.models import MemorySearchResult

    def search(
        self,
        query: str,
        *,
        kind: list[str] | None = None,
        status: list[str] | None = None,
        limit: int = 8,
    ) -> list[MemorySearchResult]:
        """Search memory files using grep.

        Args:
            query: Search string
            kind: Filter by memory kind
            status: Filter by status (default: ["active"])
            limit: Max results to return
        """
        if status is None:
            status = ["active"]

        if not self.memory_dir.exists():
            return []

        # Use grep to find matching files
        matching_files = self._grep_files(query)

        results: list[MemorySearchResult] = []
        for filepath, matched_lines in matching_files:
            try:
                fm, body = self._parse_file(filepath)
                if "id" not in fm:
                    continue

                record = _frontmatter_to_record(fm, body)

                # Apply filters
                if record.status not in status:
                    continue
                if kind and record.kind not in kind:
                    continue

                snippet = "\n".join(matched_lines[:3])
                results.append(MemorySearchResult(
                    id=record.id,
                    name=record.name,
                    kind=record.kind,
                    scope=record.scope,
                    snippet=snippet,
                    confidence=record.confidence,
                    status=record.status,
                    source_ref=record.source_ref,
                    why_matched=f"grep: {query}",
                ))

                if len(results) >= limit:
                    break
            except Exception:
                continue

        return results

    def _grep_files(self, query: str) -> list[tuple[Path, list[str]]]:
        """Run grep/ripgrep on memory directory, return (file, matched_lines) pairs.

        Uses a single rg invocation with context lines to avoid N+1 subprocess calls.
        """
        if not self.memory_dir.exists():
            return []

        try:
            # Single invocation: --with-filename + context lines, grouped by file
            result = subprocess.run(
                [
                    "rg", "--no-heading", "--with-filename", "-C", "1",
                    "--type", "md", query, str(self.memory_dir),
                ],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode not in (0, 1):  # 1 means no matches
                return []
            if not result.stdout.strip():
                return []

            # Parse grouped output: lines prefixed with "filepath:..." or "filepath-..."
            files_with_matches: dict[Path, list[str]] = {}
            for line in result.stdout.strip().split("\n"):
                if not line or line == "--":
                    continue
                # rg format: /path/file.md:linenum:content or /path/file.md-linenum-content
                for sep in (":", "-"):
                    parts = line.split(sep, 2)
                    if len(parts) >= 3:
                        fp = Path(parts[0])
                        if fp.suffix == ".md" and fp.name != "MEMORY.md":
                            files_with_matches.setdefault(fp, []).append(parts[2])
                        break

            return list(files_with_matches.items())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # Fallback to Python grep if rg not available
            return self._python_grep(query)

    def _python_grep(self, query: str) -> list[tuple[Path, list[str]]]:
        """Fallback grep using Python when ripgrep is not available."""
        results: list[tuple[Path, list[str]]] = []
        if not self.memory_dir.exists():
            return results
        query_lower = query.lower()
        for f in sorted(self.memory_dir.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            try:
                text = f.read_text(encoding="utf-8")
                if query_lower in text.lower():
                    lines = [l for l in text.split("\n") if query_lower in l.lower()]
                    results.append((f, lines[:5]))
            except Exception:
                continue
        return results
```

- [x] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_memory_store.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/bourbon/memory/store.py tests/test_memory_store.py
git commit -m "feat(memory): implement grep-based memory search with ripgrep fallback"
```

---

## Task 7: File Anchors Reader (`files.py`)

**Files:**
- Create: `src/bourbon/memory/files.py`
- Test: `tests/test_memory_files.py`

- [x] **Step 1: Write failing tests for USER.md merge**

```python
# tests/test_memory_files.py
from pathlib import Path
from bourbon.memory.files import merge_user_md, read_file_anchor


def test_merge_user_md_project_local_wins(tmp_path):
    global_file = tmp_path / "global" / "USER.md"
    global_file.parent.mkdir()
    global_file.write_text("## Code Style\n\nUse tabs.\n\n## Language\n\nEnglish.\n")

    project_file = tmp_path / "project" / "USER.md"
    project_file.parent.mkdir()
    project_file.write_text("## Code Style\n\nUse spaces.\n")

    merged = merge_user_md(global_path=global_file, project_path=project_file)
    assert "Use spaces" in merged  # project wins
    assert "English" in merged  # global-only section preserved
    assert "Use tabs" not in merged  # overridden


def test_merge_user_md_preamble_only_files(tmp_path):
    """Pure preamble files: project-local replaces global entirely."""
    global_file = tmp_path / "global.md"
    global_file.write_text("Global prefs here.\n")

    project_file = tmp_path / "project.md"
    project_file.write_text("Project-specific prefs.\n")

    merged = merge_user_md(global_path=global_file, project_path=project_file)
    assert "Project-specific prefs" in merged
    assert "Global prefs" not in merged


def test_merge_user_md_global_only(tmp_path):
    global_file = tmp_path / "global.md"
    global_file.write_text("## Prefs\n\nMy prefs.\n")

    merged = merge_user_md(global_path=global_file, project_path=None)
    assert "My prefs" in merged


def test_merge_user_md_neither_exists(tmp_path):
    merged = merge_user_md(
        global_path=tmp_path / "nonexistent.md",
        project_path=tmp_path / "also_nonexistent.md",
    )
    assert merged == ""


def test_read_file_anchor_exists(tmp_path):
    f = tmp_path / "AGENTS.md"
    f.write_text("# Project Rules\n\nDo TDD.\n")
    content = read_file_anchor(f, token_limit=5000)
    assert "Do TDD" in content


def test_read_file_anchor_missing(tmp_path):
    content = read_file_anchor(tmp_path / "missing.md", token_limit=5000)
    assert content == ""


def test_read_file_anchor_truncates(tmp_path):
    f = tmp_path / "LARGE.md"
    f.write_text("x " * 10000)  # Very large
    content = read_file_anchor(f, token_limit=100)
    # Should be truncated (rough token estimate: 1 token ~= 4 chars)
    assert len(content) < 1000
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_files.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement files.py**

```python
# src/bourbon/memory/files.py
"""File anchor reading: AGENTS.md, MEMORY.md, USER.md, daily logs."""

from __future__ import annotations

from pathlib import Path


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def _truncate_to_tokens(text: str, token_limit: int) -> str:
    """Truncate text to approximate token limit."""
    char_limit = token_limit * 4
    if len(text) <= char_limit:
        return text
    # Truncate at line boundary
    truncated = text[:char_limit]
    last_newline = truncated.rfind("\n")
    if last_newline > char_limit // 2:
        truncated = truncated[:last_newline]
    return truncated + "\n\n[... truncated to token limit ...]"


def read_file_anchor(path: Path, token_limit: int) -> str:
    """Read a file anchor, truncating to token limit. Returns '' if missing."""
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    return _truncate_to_tokens(text, token_limit)


def _parse_sections(text: str) -> list[tuple[str, str]]:
    """Parse markdown into (normalized_key, section_content) pairs.

    Content before first heading is keyed as '__preamble__'.
    Heading key: strip # and whitespace, lowercase.
    """
    lines = text.split("\n")
    sections: list[tuple[str, str]] = []
    current_key = "__preamble__"
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("#"):
            # Save previous section
            if current_lines or current_key != "__preamble__":
                sections.append((current_key, "\n".join(current_lines)))
            # New section
            heading_text = line.lstrip("#").strip()
            current_key = heading_text.lower()
            current_lines = [line]
        else:
            current_lines.append(line)

    # Save final section
    if current_lines or sections:
        sections.append((current_key, "\n".join(current_lines)))

    return sections


def merge_user_md(
    global_path: Path | None,
    project_path: Path | None,
) -> str:
    """Merge user-global and project-local USER.md files.

    Project-local sections replace matching global sections (by normalized heading key).
    Non-matching project-local sections are appended after global-only sections.
    If both files are pure preamble (no headings), project-local replaces global entirely.
    """
    global_text = ""
    project_text = ""

    if global_path and global_path.exists():
        try:
            global_text = global_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass

    if project_path and project_path.exists():
        try:
            project_text = project_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass

    if not global_text and not project_text:
        return ""
    if not global_text:
        return project_text
    if not project_text:
        return global_text

    global_sections = _parse_sections(global_text)
    project_sections = _parse_sections(project_text)

    project_keys = {key for key, _ in project_sections}

    # Build merged output: global sections (replaced where project has match) + new project sections
    merged_parts: list[str] = []
    used_project_keys: set[str] = set()

    for key, content in global_sections:
        if key in project_keys:
            # Project-local wins
            for pk, pc in project_sections:
                if pk == key:
                    merged_parts.append(pc)
                    used_project_keys.add(pk)
                    break
        else:
            merged_parts.append(content)

    # Append project-local sections not matching any global section
    for key, content in project_sections:
        if key not in used_project_keys:
            merged_parts.append(content)

    return "\n".join(merged_parts).strip() + "\n"
```

- [x] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_memory_files.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/bourbon/memory/files.py tests/test_memory_files.py
git commit -m "feat(memory): implement file anchor reading and USER.md merge"
```

---

## Task 8: Memory Prompt Section (`prompt.py`)

**Files:**
- Create: `src/bourbon/memory/prompt.py`
- Modify: `src/bourbon/prompt/types.py`
- Modify: `src/bourbon/prompt/__init__.py`
- Test: `tests/test_memory_prompt.py`

- [x] **Step 1: Write failing tests for prompt section**

```python
# tests/test_memory_prompt.py
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from bourbon.memory.prompt import memory_anchors_section, MEMORY_ANCHOR_ORDER
from bourbon.prompt.types import PromptContext


def test_memory_anchor_order():
    assert MEMORY_ANCHOR_ORDER == 15


def test_memory_anchors_section_no_manager():
    """When no memory_manager in context, returns empty string."""
    ctx = PromptContext(workdir=Path("/tmp/test"))
    result = asyncio.run(memory_anchors_section(ctx))
    assert result == ""


def test_memory_anchors_section_with_agents_md(tmp_path):
    """Renders AGENTS.md content when file exists."""
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("# Rules\n\nAlways use TDD.\n")

    mock_manager = MagicMock()
    mock_manager.get_memory_dir.return_value = tmp_path / "memory"
    mock_manager.config.memory_md_token_limit = 1200
    mock_manager.config.user_md_token_limit = 600

    ctx = PromptContext(workdir=tmp_path, memory_manager=mock_manager)
    result = asyncio.run(memory_anchors_section(ctx))
    assert "Always use TDD" in result


def test_memory_anchors_section_includes_memory_md(tmp_path):
    """Renders MEMORY.md index when it exists."""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    memory_md = mem_dir / "MEMORY.md"
    memory_md.write_text("- [Rule 1](project_rule-1.md) — Important rule\n")

    mock_manager = MagicMock()
    mock_manager.get_memory_dir.return_value = mem_dir
    mock_manager.config.memory_md_token_limit = 1200
    mock_manager.config.user_md_token_limit = 600

    ctx = PromptContext(workdir=tmp_path, memory_manager=mock_manager)
    result = asyncio.run(memory_anchors_section(ctx))
    assert "Important rule" in result
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_prompt.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Add memory_manager to PromptContext**

Modify `src/bourbon/prompt/types.py`:

```python
if TYPE_CHECKING:
    from bourbon.mcp_client import MCPManager
    from bourbon.skills import SkillManager


@dataclass
class PromptContext:
    """Runtime context passed to dynamic section factories and ContextInjector."""

    workdir: Path
    skill_manager: "SkillManager | None" = None
    mcp_manager: "MCPManager | None" = None
    memory_manager: Any | None = None
```

Add `from typing import Any` to imports.

- [x] **Step 4: Implement memory prompt section**

```python
# src/bourbon/memory/prompt.py
"""Memory prompt section — order=15 anchor injection."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from bourbon.memory.files import merge_user_md, read_file_anchor, _truncate_to_tokens

if TYPE_CHECKING:
    from bourbon.prompt.types import PromptContext

MEMORY_ANCHOR_ORDER = 15


async def memory_anchors_section(ctx: "PromptContext") -> str:
    """Render the memory anchors prompt section.

    Includes: AGENTS.md, USER.md (merged), MEMORY.md index.
    Returns empty string if memory is not configured.
    """
    if not hasattr(ctx, "memory_manager") or ctx.memory_manager is None:
        return ""

    manager = ctx.memory_manager
    memory_dir = manager.get_memory_dir()
    config = manager.config

    parts: list[str] = []

    # 1. AGENTS.md (project-level, no hard limit per spec but use a generous default)
    AGENTS_MD_TOKEN_LIMIT = 8000  # generous default; spec says "no new limit, but show token cost"
    agents_md = ctx.workdir / "AGENTS.md"
    agents_content = read_file_anchor(agents_md, token_limit=AGENTS_MD_TOKEN_LIMIT)
    if agents_content:
        parts.append(f"# Project Instructions (AGENTS.md)\n\n{agents_content}")

    # 2. USER.md (merged global + project-local, then truncated via same path as other anchors)
    global_user_md = Path("~/.bourbon/USER.md").expanduser()
    project_user_md = ctx.workdir / "USER.md"
    user_content = merge_user_md(
        global_path=global_user_md,
        project_path=project_user_md if project_user_md.exists() else None,
    )
    if user_content:
        user_content = _truncate_to_tokens(user_content, config.user_md_token_limit)
        parts.append(f"# User Preferences (USER.md)\n\n{user_content}")

    # 3. MEMORY.md index (use same truncation path as USER.md for consistency)
    memory_md = memory_dir / "MEMORY.md" if memory_dir else None
    if memory_md and memory_md.exists():
        index_content = read_file_anchor(memory_md, token_limit=config.memory_md_token_limit)
        if index_content:
            parts.append(f"# Memory Index (MEMORY.md)\n\n{index_content}")

    return "\n\n---\n\n".join(parts)
```

- [x] **Step 5: Wire into prompt system**

Modify `src/bourbon/prompt/__init__.py`:

```python
from bourbon.memory.prompt import MEMORY_ANCHOR_ORDER, memory_anchors_section
from bourbon.prompt.builder import PromptBuilder
from bourbon.prompt.context import ContextInjector
from bourbon.prompt.dynamic import DYNAMIC_SECTIONS
from bourbon.prompt.sections import DEFAULT_SECTIONS
from bourbon.prompt.types import PromptContext, PromptSection

ANCHOR_SECTIONS = [
    PromptSection(name="memory_anchors", order=MEMORY_ANCHOR_ORDER, content=memory_anchors_section),
]

ALL_SECTIONS = DEFAULT_SECTIONS + ANCHOR_SECTIONS + DYNAMIC_SECTIONS

__all__ = [
    "PromptBuilder",
    "PromptSection",
    "PromptContext",
    "ContextInjector",
    "ALL_SECTIONS",
    "DEFAULT_SECTIONS",
    "DYNAMIC_SECTIONS",
    "ANCHOR_SECTIONS",
]
```

- [x] **Step 6: Run tests to verify pass**

Run: `pytest tests/test_memory_prompt.py -v`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add src/bourbon/memory/prompt.py src/bourbon/prompt/types.py src/bourbon/prompt/__init__.py tests/test_memory_prompt.py
git commit -m "feat(memory): add order=15 memory anchors prompt section with AGENTS.md/USER.md/MEMORY.md"
```

---

## Task 9: Memory Policy (`policy.py`)

**Files:**
- Create: `src/bourbon/memory/policy.py`
- Test: `tests/test_memory_models.py` (append policy tests)

- [x] **Step 1: Write failing tests for policy checks**

```python
# tests/test_memory_policy.py
import pytest
from bourbon.memory.policy import check_write_permission
from bourbon.memory.models import MemoryActor, MemoryKind, MemoryScope


def test_main_agent_can_write_all():
    actor = MemoryActor(kind="agent", session_id="ses_1")
    # Main agent (no agent_type) can write any kind/scope
    assert check_write_permission(actor, kind=MemoryKind.USER, scope=MemoryScope.USER) is True
    assert check_write_permission(actor, kind=MemoryKind.FEEDBACK, scope=MemoryScope.PROJECT) is True


def test_explore_subagent_limited():
    actor = MemoryActor(kind="subagent", run_id="run_1", agent_type="explore")
    # Can write project (session scope, low conf implied by policy)
    assert check_write_permission(actor, kind=MemoryKind.PROJECT, scope=MemoryScope.SESSION) is True
    assert check_write_permission(actor, kind=MemoryKind.REFERENCE, scope=MemoryScope.SESSION) is True
    # Cannot write user or feedback
    assert check_write_permission(actor, kind=MemoryKind.USER, scope=MemoryScope.USER) is False
    assert check_write_permission(actor, kind=MemoryKind.FEEDBACK, scope=MemoryScope.PROJECT) is False


def test_user_can_write_all():
    actor = MemoryActor(kind="user")
    assert check_write_permission(actor, kind=MemoryKind.FEEDBACK, scope=MemoryScope.PROJECT) is True


def test_coder_subagent_limited():
    actor = MemoryActor(kind="subagent", run_id="run_2", agent_type="coder")
    assert check_write_permission(actor, kind=MemoryKind.PROJECT, scope=MemoryScope.SESSION) is True
    assert check_write_permission(actor, kind=MemoryKind.REFERENCE, scope=MemoryScope.SESSION) is True
    assert check_write_permission(actor, kind=MemoryKind.USER, scope=MemoryScope.USER) is False
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_policy.py -v`
Expected: FAIL

- [x] **Step 3: Implement policy.py**

```python
# src/bourbon/memory/policy.py
"""Memory access policy — scope and kind checks for agent types."""

from __future__ import annotations

from bourbon.memory.models import MemoryActor, MemoryKind, MemoryScope

# Subagent types and their allowed write kinds
_SUBAGENT_ALLOWED_KINDS: dict[str, set[str]] = {
    "explore": {MemoryKind.PROJECT, MemoryKind.REFERENCE},
    "coder": {MemoryKind.PROJECT, MemoryKind.REFERENCE},
    "plan": {MemoryKind.PROJECT},
}


def check_write_permission(
    actor: MemoryActor,
    *,
    kind: MemoryKind,
    scope: MemoryScope,
) -> bool:
    """Check if actor is allowed to write a record with given kind/scope.

    Rules:
    - user: always allowed
    - agent (main, no agent_type): always allowed
    - subagent: restricted by agent_type to specific kinds
    - system: always allowed (flush operations)
    """
    if actor.kind == "user":
        return True
    if actor.kind == "system":
        return True
    if actor.kind == "agent" and not actor.agent_type:
        # Main agent
        return True

    # Subagent or typed agent
    agent_type = actor.agent_type or "default"
    if agent_type == "default":
        return True

    allowed_kinds = _SUBAGENT_ALLOWED_KINDS.get(agent_type, {MemoryKind.PROJECT, MemoryKind.REFERENCE})
    return kind in allowed_kinds
```

- [x] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_memory_policy.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/bourbon/memory/policy.py tests/test_memory_policy.py
git commit -m "feat(memory): implement memory write policy for subagent kind restrictions"
```

---

## Task 10: MemoryManager (`manager.py`)

**Files:**
- Create: `src/bourbon/memory/manager.py`
- Test: `tests/test_memory_manager.py`

- [x] **Step 1: Write failing tests for MemoryManager.write and search**

```python
# tests/test_memory_manager.py
import pytest
from pathlib import Path
from datetime import datetime, UTC

from bourbon.memory.manager import MemoryManager
from bourbon.memory.models import (
    MemoryActor, MemoryKind, MemoryScope, MemorySource,
    MemoryRecordDraft, SourceRef,
)
from bourbon.config import MemoryConfig


@pytest.fixture
def manager(tmp_path):
    config = MemoryConfig(storage_dir=str(tmp_path))
    return MemoryManager(
        config=config,
        project_key="test-project-abc12345",
        workdir=tmp_path / "workdir",
        audit=None,  # no audit in unit tests
    )


def test_write_creates_file(manager, tmp_path):
    actor = MemoryActor(kind="user")
    draft = MemoryRecordDraft(
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        content="Always use WAL mode.",
        source=MemorySource.USER,
        confidence=1.0,
        name="WAL rule",
        description="Use WAL for SQLite",
    )
    record = manager.write(draft, actor=actor)

    assert record.id.startswith("mem_")
    assert record.created_by == "user"
    assert record.status == "active"

    # File should exist
    mem_dir = tmp_path / "test-project-abc12345" / "memory"
    assert (mem_dir / "project_wal-rule.md").exists()


def test_write_updates_index(manager, tmp_path):
    actor = MemoryActor(kind="user")
    draft = MemoryRecordDraft(
        kind=MemoryKind.FEEDBACK,
        scope=MemoryScope.PROJECT,
        content="Never mock the database.",
        source=MemorySource.USER,
        confidence=1.0,
        name="No DB mocks",
        description="Integration tests must use real DB",
    )
    manager.write(draft, actor=actor)

    index_path = tmp_path / "test-project-abc12345" / "memory" / "MEMORY.md"
    assert index_path.exists()
    assert "No DB mocks" in index_path.read_text()


def test_search_finds_written_record(manager):
    actor = MemoryActor(kind="user")
    draft = MemoryRecordDraft(
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        content="Use pytest for all tests.",
        source=MemorySource.USER,
        confidence=1.0,
        name="Pytest preference",
        description="Use pytest not unittest",
    )
    manager.write(draft, actor=actor)

    results = manager.search("pytest", scope="project")
    assert len(results) >= 1
    assert "pytest" in results[0].snippet.lower() or "pytest" in results[0].name.lower()


def test_write_denied_for_subagent_user_kind(manager):
    actor = MemoryActor(kind="subagent", run_id="run_1", agent_type="explore")
    draft = MemoryRecordDraft(
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        content="Should be denied.",
        source=MemorySource.SUBAGENT,
        confidence=0.5,
    )
    with pytest.raises(PermissionError):
        manager.write(draft, actor=actor)


def test_get_status(manager):
    status = manager.get_status(actor=MemoryActor(kind="user"))
    assert "project" in status.readable_scopes
    assert status.index_at_capacity is False
    assert status.memory_file_count == 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_manager.py -v`
Expected: FAIL

- [x] **Step 3: Implement MemoryManager**

```python
# src/bourbon/memory/manager.py
"""MemoryManager — orchestration layer for memory operations."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path

from bourbon.config import MemoryConfig
from bourbon.memory.models import (
    MemoryActor,
    MemoryKind,
    MemoryRecord,
    MemoryRecordDraft,
    MemoryScope,
    MemorySearchResult,
    MemoryStatus,
    MemoryStatusInfo,
    RecentWriteSummary,
    actor_to_created_by,
)
from bourbon.memory.policy import check_write_permission
from bourbon.memory.store import MemoryStore


def _generate_id() -> str:
    """Generate a unique memory record id."""
    return f"mem_{secrets.token_hex(4)}"


def _derive_name(draft: MemoryRecordDraft) -> str:
    """Derive a name from draft content if not provided."""
    if draft.name:
        return draft.name
    # Use first line of content, truncated
    first_line = draft.content.split("\n")[0].strip()
    return first_line[:60] if first_line else "Untitled memory"


def _derive_description(draft: MemoryRecordDraft, name: str) -> str:
    """Derive a description from draft if not provided."""
    if draft.description:
        return draft.description
    # Use first sentence of content
    first_line = draft.content.split("\n")[0].strip()
    return first_line[:120] if first_line else name


class MemoryManager:
    """Orchestrates memory operations: write, search, status, flush."""

    def __init__(
        self,
        config: MemoryConfig,
        project_key: str,
        workdir: Path,
        audit: "AuditLogger | None" = None,
    ) -> None:
        self.config = config
        self.project_key = project_key
        self.workdir = workdir
        self._memory_dir = Path(config.storage_dir).expanduser() / project_key / "memory"
        self._store = MemoryStore(memory_dir=self._memory_dir)
        self._recent_writes: list[RecentWriteSummary] = []
        self._audit = audit

    def get_memory_dir(self) -> Path:
        """Return the memory directory path."""
        return self._memory_dir

    def write(self, draft: MemoryRecordDraft, *, actor: MemoryActor) -> MemoryRecord:
        """Write a new memory record.

        Raises PermissionError if actor is not allowed to write this kind/scope.
        """
        if not check_write_permission(actor, kind=draft.kind, scope=draft.scope):
            raise PermissionError(
                f"Actor {actor.kind}:{actor.agent_type} cannot write "
                f"kind={draft.kind} scope={draft.scope}"
            )

        now = datetime.now(UTC)
        name = _derive_name(draft)
        description = _derive_description(draft, name)

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

        # Audit: record the write event
        self._record_audit("memory_write", record, actor)

        self._recent_writes.append(RecentWriteSummary(
            id=record.id,
            name=record.name,
            kind=record.kind,
            created_at=now,
        ))
        # Keep only last 10 recent writes
        self._recent_writes = self._recent_writes[-10:]

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
        """Search memory records."""
        return self._store.search(
            query,
            kind=kind,
            status=status,
            limit=limit or self.config.recall_limit,
        )

    def get_status(self, *, actor: MemoryActor) -> MemoryStatusInfo:
        """Return current memory status."""
        # Determine readable/writable scopes based on actor
        if actor.kind in ("user", "agent", "system"):
            readable = ["project", "session", "user"]
            writable = ["project", "session", "user"]
        else:
            readable = ["project", "session"]
            writable = ["project", "session"]

        # Count memory files
        file_count = 0
        if self._memory_dir.exists():
            file_count = len([f for f in self._memory_dir.glob("*.md") if f.name != "MEMORY.md"])

        # Check index capacity
        index_path = self._memory_dir / "MEMORY.md"
        at_capacity = False
        if index_path.exists():
            lines = index_path.read_text(encoding="utf-8").strip().split("\n")
            at_capacity = len([l for l in lines if l.strip()]) >= 200

        return MemoryStatusInfo(
            readable_scopes=readable,
            writable_scopes=writable,
            prompt_anchor_tokens=0,  # computed at render time
            recent_writes=self._recent_writes,
            index_at_capacity=at_capacity,
            memory_file_count=file_count,
        )

    def _record_audit(self, event_type: str, record: MemoryRecord, actor: MemoryActor) -> None:
        """Record a memory audit event via AuditLogger."""
        if not self._audit:
            return
        from bourbon.audit.events import AuditEvent, EventType
        self._audit.record(AuditEvent(
            event_type=EventType(event_type),
            details={
                "memory_id": record.id,
                "memory_file": f"{record.kind}_{record.name}",
                "kind": str(record.kind),
                "scope": str(record.scope),
                "actor": actor_to_created_by(actor),
            },
        ))
```

- [x] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_memory_manager.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/bourbon/memory/manager.py tests/test_memory_manager.py
git commit -m "feat(memory): implement MemoryManager with write, search, and status"
```

---

## Task 11: Memory Tools (`tools/memory.py`)

**Files:**
- Create: `src/bourbon/tools/memory.py`
- Modify: `src/bourbon/tools/__init__.py`
- Test: `tests/test_memory_tools.py`

- [x] **Step 1: Write failing tests for memory tools**

```python
# tests/test_memory_tools.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bourbon.tools import ToolContext, get_registry, _ensure_imports


def test_memory_tools_registered():
    """Memory tools should be registered after _ensure_imports."""
    _ensure_imports()
    registry = get_registry()
    tool_names = [t.name for t in registry._tools.values()]
    assert "memory_search" in tool_names
    assert "memory_write" in tool_names
    assert "memory_status" in tool_names


def test_memory_write_tool_schema():
    _ensure_imports()
    registry = get_registry()
    tool = registry.get_tool("memory_write")
    assert tool is not None
    schema = tool.input_schema
    assert "content" in schema["properties"]
    assert "kind" in schema["properties"]


def test_memory_search_tool_schema():
    _ensure_imports()
    registry = get_registry()
    tool = registry.get_tool("memory_search")
    assert tool is not None
    schema = tool.input_schema
    assert "query" in schema["properties"]
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_tools.py -v`
Expected: FAIL

- [x] **Step 3: Implement memory tools**

```python
# src/bourbon/tools/memory.py
"""Memory tools — MemorySearch, MemoryWrite, MemoryStatus."""

from __future__ import annotations

import json
from typing import Any

from bourbon.tools import RiskLevel, ToolContext, register_tool


@register_tool(
    name="memory_search",
    description="Search memory records, daily logs, and transcript history by keyword.",
    risk_level=RiskLevel.LOW,
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query keywords"},
            "scope": {"type": "string", "enum": ["user", "project", "session"], "description": "Scope filter"},
            "kind": {
                "type": "array",
                "items": {"type": "string", "enum": ["user", "feedback", "project", "reference"]},
                "description": "Filter by memory kind",
            },
            "limit": {"type": "integer", "default": 8, "description": "Max results"},
            "from_date": {"type": "string", "description": "ISO date YYYY-MM-DD start filter"},
            "to_date": {"type": "string", "description": "ISO date YYYY-MM-DD end filter"},
        },
        "required": ["query"],
    },
)
def memory_search(query: str, ctx: ToolContext, **kwargs: Any) -> str:
    """Handle MemorySearch tool call."""
    if not hasattr(ctx, "memory_manager") or ctx.memory_manager is None:
        return json.dumps({"error": "Memory system is not enabled"})

    manager = ctx.memory_manager
    results = manager.search(
        query,
        scope=kwargs.get("scope"),
        kind=kwargs.get("kind"),
        limit=kwargs.get("limit", 8),
    )

    if not results:
        return json.dumps({"results": [], "message": "No matching memories found."})

    output = []
    for r in results:
        output.append({
            "id": r.id,
            "name": r.name,
            "kind": str(r.kind),
            "scope": str(r.scope),
            "confidence": r.confidence,
            "snippet": r.snippet,
            "why_matched": r.why_matched,
        })
    return json.dumps({"results": output})


@register_tool(
    name="memory_write",
    description="Write a new memory record. Used when user asks to remember something or agent captures important context.",
    risk_level=RiskLevel.MEDIUM,  # writes affect future behavior — governed writes per spec
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Memory content (main body text)"},
            "kind": {"type": "string", "enum": ["user", "feedback", "project", "reference"], "description": "Memory kind"},
            "scope": {"type": "string", "enum": ["user", "project", "session"], "description": "Memory scope"},
            "source": {"type": "string", "enum": ["user", "agent", "subagent", "compaction", "manual"], "description": "Who originated this memory"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 1.0},
            "name": {"type": "string", "description": "Short title for the memory"},
            "description": {"type": "string", "description": "One-line description for MEMORY.md index"},
            "source_ref": {
                "type": "object",
                "description": "Reference to origin (transcript, file, etc.)",
                "properties": {
                    "kind": {"type": "string"},
                    "project_name": {"type": "string"},
                    "session_id": {"type": "string"},
                    "message_uuid": {"type": "string"},
                    "file_path": {"type": "string"},
                },
            },
        },
        "required": ["content", "kind", "scope", "source"],
    },
)
def memory_write(content: str, kind: str, scope: str, source: str, ctx: ToolContext, **kwargs: Any) -> str:
    """Handle MemoryWrite tool call."""
    if not hasattr(ctx, "memory_manager") or ctx.memory_manager is None:
        return json.dumps({"error": "Memory system is not enabled"})

    from bourbon.memory.models import MemoryRecordDraft, MemorySource, MemoryKind, MemoryScope, SourceRef

    # Build source_ref if provided
    source_ref = None
    if "source_ref" in kwargs and kwargs["source_ref"]:
        ref_data = kwargs["source_ref"]
        source_ref = SourceRef(
            kind=ref_data.get("kind", "manual"),
            project_name=ref_data.get("project_name"),
            session_id=ref_data.get("session_id"),
            message_uuid=ref_data.get("message_uuid"),
            file_path=ref_data.get("file_path"),
        )

    draft = MemoryRecordDraft(
        kind=MemoryKind(kind),
        scope=MemoryScope(scope),
        content=content,
        source=MemorySource(source),
        confidence=kwargs.get("confidence", 1.0),
        name=kwargs.get("name"),
        description=kwargs.get("description"),
        source_ref=source_ref,
    )

    actor = ctx.memory_actor
    if actor is None:
        from bourbon.memory.models import MemoryActor
        actor = MemoryActor(kind="agent")

    try:
        record = ctx.memory_manager.write(draft, actor=actor)
    except PermissionError as e:
        return json.dumps({"error": str(e)})

    return json.dumps({
        "id": record.id,
        "name": record.name,
        "status": "written",
        "file": str(record.kind) + "_" + record.name.lower().replace(" ", "-")[:50] + ".md",
    })


@register_tool(
    name="memory_status",
    description="Show current memory system status: scopes, capacity, recent writes.",
    risk_level=RiskLevel.LOW,
    input_schema={
        "type": "object",
        "properties": {},
    },
)
def memory_status(ctx: ToolContext, **kwargs: Any) -> str:
    """Handle MemoryStatus tool call."""
    if not hasattr(ctx, "memory_manager") or ctx.memory_manager is None:
        return json.dumps({"error": "Memory system is not enabled"})

    from bourbon.memory.models import MemoryActor
    actor = ctx.memory_actor if hasattr(ctx, "memory_actor") and ctx.memory_actor else MemoryActor(kind="agent")

    status = ctx.memory_manager.get_status(actor=actor)
    return json.dumps({
        "readable_scopes": status.readable_scopes,
        "writable_scopes": status.writable_scopes,
        "prompt_anchor_tokens": status.prompt_anchor_tokens,
        "index_at_capacity": status.index_at_capacity,
        "memory_file_count": status.memory_file_count,
        "recent_writes": [
            {"id": w.id, "name": w.name, "kind": str(w.kind)}
            for w in status.recent_writes
        ],
    })
```

- [x] **Step 4: Add lazy import to tools/__init__.py**

Add to the `_ensure_imports()` function in `src/bourbon/tools/__init__.py`:

```python
def _ensure_imports() -> None:
    """Lazily import tool modules to trigger registration."""
    from bourbon.tools import (  # noqa: F401
        agent_tool,
        base,
        memory,      # <-- ADD THIS
        search,
        skill_tool,
        task_tools,
        tool_search,
    )
    ...
```

Add `memory_manager` and `memory_actor` fields to `ToolContext`:

```python
@dataclass
class ToolContext:
    """Execution context shared across tool handlers."""

    workdir: Path
    agent: Any | None = None
    execution_markers: set[str] = field(default_factory=set)
    skill_manager: Any | None = None
    on_tools_discovered: Callable[[set[str]], None] | None = None
    memory_manager: Any | None = None
    memory_actor: Any | None = None
```

- [x] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_memory_tools.py -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add src/bourbon/tools/memory.py src/bourbon/tools/__init__.py tests/test_memory_tools.py
git commit -m "feat(memory): implement MemorySearch/MemoryWrite/MemoryStatus tools"
```

---

## Task 12: Pre-Compact Flush (`compact.py`)

**Files:**
- Create: `src/bourbon/memory/compact.py`
- Test: `tests/test_memory_manager.py` (append flush tests)

- [x] **Step 1: Write failing tests for flush logic**

```python
# tests/test_memory_compact.py
import pytest
from datetime import datetime, UTC

from bourbon.memory.compact import extract_flush_candidates


def test_extract_remember_keywords():
    """Messages with 'remember' are captured as candidates."""
    messages = [
        {"role": "user", "content": "Please remember to always use WAL mode.", "uuid": "msg_1"},
        {"role": "assistant", "content": "Sure, I'll remember that.", "uuid": "msg_2"},
        {"role": "user", "content": "What's the weather?", "uuid": "msg_3"},
    ]
    candidates = extract_flush_candidates(messages, session_id="ses_1")
    # Should capture the user message with "remember"
    assert len(candidates) >= 1
    assert any("WAL mode" in c.content for c in candidates)


def test_extract_error_tool_results():
    """Tool results with is_error=True are captured."""
    messages = [
        {
            "role": "assistant",
            "content": "Running command...",
            "uuid": "msg_1",
            "tool_results": [
                {"tool_name": "bash", "output": "Permission denied: /etc/passwd", "is_error": True}
            ],
        },
    ]
    candidates = extract_flush_candidates(messages, session_id="ses_1")
    assert len(candidates) >= 1
    assert any("Permission denied" in c.content for c in candidates)


def test_extract_no_candidates_from_normal_chat():
    """Normal conversation without keywords produces no candidates."""
    messages = [
        {"role": "user", "content": "Hello, how are you?", "uuid": "msg_1"},
        {"role": "assistant", "content": "I'm doing well!", "uuid": "msg_2"},
    ]
    candidates = extract_flush_candidates(messages, session_id="ses_1")
    assert len(candidates) == 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_compact.py -v`
Expected: FAIL

- [x] **Step 3: Implement compact.py**

```python
# src/bourbon/memory/compact.py
"""Pre-compact flush — deterministic heuristic extraction (no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bourbon.memory.models import (
    MemoryKind,
    MemoryRecordDraft,
    MemoryScope,
    MemorySource,
    SourceRef,
)

# Keywords that suggest user wants something remembered
_REMEMBER_KEYWORDS = re.compile(
    r"\b(remember|always|never|以后|记住|从现在起|每次)\b",
    re.IGNORECASE,
)


@dataclass
class FlushCandidate:
    """A candidate extracted from messages for potential memory write."""

    content: str
    source_ref: SourceRef
    kind: MemoryKind
    confidence: float


def extract_flush_candidates(
    messages: list[dict],
    *,
    session_id: str,
) -> list[FlushCandidate]:
    """Extract memory candidates from messages about to be compacted.

    Deterministic heuristics (no LLM):
    - User messages with remember/always/never keywords → low-confidence candidate
    - Tool results with is_error=True → reference candidate
    """
    candidates: list[FlushCandidate] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        uuid = msg.get("uuid", "")

        if isinstance(content, list):
            # Handle block-based content
            content = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )

        # Check user messages for remember keywords
        if role == "user" and _REMEMBER_KEYWORDS.search(content):
            candidates.append(FlushCandidate(
                content=content[:500],
                source_ref=SourceRef(
                    kind="transcript",
                    session_id=session_id,
                    message_uuid=uuid,
                ),
                kind=MemoryKind.PROJECT,
                confidence=0.6,
            ))

        # Check for error tool results
        tool_results = msg.get("tool_results", [])
        for tr in tool_results:
            if tr.get("is_error"):
                error_content = f"Error in {tr.get('tool_name', 'unknown')}: {tr.get('output', '')[:300]}"
                candidates.append(FlushCandidate(
                    content=error_content,
                    source_ref=SourceRef(
                        kind="transcript",
                        session_id=session_id,
                        message_uuid=uuid,
                    ),
                    kind=MemoryKind.REFERENCE,
                    confidence=0.4,
                ))

    return candidates
```

- [x] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_memory_compact.py -v`
Expected: PASS

- [x] **Step 5: Add flush_before_compact to MemoryManager**

```python
# Add to src/bourbon/memory/manager.py

from bourbon.memory.compact import extract_flush_candidates, FlushCandidate

    def flush_before_compact(
        self,
        messages: list[dict],
        *,
        session_id: str,
    ) -> list[MemoryRecord]:
        """Flush memory candidates before compaction.

        Deterministic extraction — no LLM calls.
        Returns list of records written.
        """
        candidates = extract_flush_candidates(messages, session_id=session_id)
        written: list[MemoryRecord] = []

        system_actor = MemoryActor(kind="system")

        for candidate in candidates:
            draft = MemoryRecordDraft(
                kind=candidate.kind,
                scope=MemoryScope.SESSION,
                content=candidate.content,
                source=MemorySource.COMPACTION,
                confidence=candidate.confidence,
                source_ref=candidate.source_ref,
            )
            record = self.write(draft, actor=system_actor)
            written.append(record)

        # Audit: record the flush event (one event for the batch)
        if written and self._audit:
            from bourbon.audit.events import AuditEvent, EventType
            self._audit.record(AuditEvent(
                event_type=EventType.MEMORY_FLUSH,
                details={
                    "session_id": session_id,
                    "records_flushed": len(written),
                    "record_ids": [r.id for r in written],
                },
            ))

        return written
```

- [x] **Step 6: Write test for flush_before_compact integration**

```python
# append to tests/test_memory_manager.py

def test_flush_before_compact(manager):
    messages = [
        {"role": "user", "content": "Remember to always run linting before commits.", "uuid": "msg_abc"},
    ]
    records = manager.flush_before_compact(messages, session_id="ses_test")
    assert len(records) >= 1
    assert records[0].source == "compaction"
    assert records[0].confidence < 1.0
```

- [x] **Step 7: Run all tests**

Run: `pytest tests/test_memory_compact.py tests/test_memory_manager.py -v`
Expected: PASS

- [x] **Step 8: Commit**

```bash
git add src/bourbon/memory/compact.py src/bourbon/memory/manager.py tests/test_memory_compact.py tests/test_memory_manager.py
git commit -m "feat(memory): implement deterministic pre-compact flush heuristics"
```

---

## Task 13: Audit Event Types

**Files:**
- Modify: `src/bourbon/audit/events.py`
- Test: `tests/test_memory_manager.py`

- [x] **Step 1: Write failing test for memory audit events**

```python
# tests/test_memory_audit.py
from bourbon.audit.events import EventType


def test_memory_event_types_exist():
    assert EventType.MEMORY_WRITE == "memory_write"
    assert EventType.MEMORY_SEARCH == "memory_search"
    assert EventType.MEMORY_FLUSH == "memory_flush"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_audit.py -v`
Expected: FAIL with `AttributeError`

- [x] **Step 3: Add memory event types to EventType**

```python
# In src/bourbon/audit/events.py, add to EventType enum:

class EventType(StrEnum):
    """Types of audit events."""

    POLICY_DECISION = "policy_decision"
    SANDBOX_EXEC = "sandbox_exec"
    SANDBOX_VIOLATION = "sandbox_violation"
    TOOL_CALL = "tool_call"
    MEMORY_WRITE = "memory_write"
    MEMORY_SEARCH = "memory_search"
    MEMORY_FLUSH = "memory_flush"
    MEMORY_PROMOTE = "memory_promote"
    MEMORY_REJECT = "memory_reject"
```

- [x] **Step 4: Run test to verify pass**

Run: `pytest tests/test_memory_audit.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/bourbon/audit/events.py tests/test_memory_audit.py
git commit -m "feat(memory): add memory event types to AuditLogger"
```

---

## Task 14: Agent Integration

**Files:**
- Modify: `src/bourbon/agent.py`
- Test: `tests/test_memory_manager.py` (append integration test)

- [x] **Step 1: Write failing integration test**

```python
# tests/test_memory_agent_integration.py
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from bourbon.agent import Agent
from bourbon.config import Config, MemoryConfig


def test_agent_initializes_memory_manager(tmp_path):
    """Agent should create MemoryManager when memory is enabled."""
    config = Config.from_dict({
        "memory": {"enabled": True, "storage_dir": str(tmp_path / "memory_store")},
        "llm": {"default_provider": "anthropic", "anthropic": {"api_key": "test-key"}},
    })
    with patch("bourbon.agent.create_client") as mock_llm:
        mock_llm.return_value = MagicMock()
        agent = Agent(config=config, workdir=tmp_path)

    assert agent._memory_manager is not None


def test_agent_no_memory_when_disabled(tmp_path):
    """Agent should not create MemoryManager when memory is disabled."""
    config = Config.from_dict({
        "memory": {"enabled": False},
        "llm": {"default_provider": "anthropic", "anthropic": {"api_key": "test-key"}},
    })
    with patch("bourbon.agent.create_client") as mock_llm:
        mock_llm.return_value = MagicMock()
        agent = Agent(config=config, workdir=tmp_path)

    assert agent._memory_manager is None


def test_agent_prompt_context_has_memory_manager(tmp_path):
    """PromptContext should carry memory_manager."""
    config = Config.from_dict({
        "memory": {"enabled": True, "storage_dir": str(tmp_path / "memory_store")},
        "llm": {"default_provider": "anthropic", "anthropic": {"api_key": "test-key"}},
    })
    with patch("bourbon.agent.create_client") as mock_llm:
        mock_llm.return_value = MagicMock()
        agent = Agent(config=config, workdir=tmp_path)

    assert agent._prompt_ctx.memory_manager is not None
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_agent_integration.py -v`
Expected: FAIL

- [x] **Step 3: Wire MemoryManager into Agent.__init__**

Add to `Agent.__init__` in `src/bourbon/agent.py`, after MCP manager initialization:

```python
        # Initialize Memory Manager
        self._memory_manager = None
        if config.memory.enabled:
            from bourbon.memory.manager import MemoryManager
            from bourbon.memory.store import sanitize_project_key

            canonical_path = self._resolve_canonical_path()
            project_key = sanitize_project_key(canonical_path)
            self._memory_manager = MemoryManager(
                config=config.memory,
                project_key=project_key,
                workdir=self.workdir,
                audit=self.audit,
            )
```

Add a helper method:

```python
    def _resolve_canonical_path(self) -> Path:
        """Resolve canonical git root for memory project key."""
        import subprocess
        # Fast check: skip subprocess if not in a git repo
        if not (self.workdir / ".git").exists() and not (self.workdir / ".git").is_file():
            # Walk up to check for parent git repos (worktrees have .git as file)
            for parent in self.workdir.parents:
                if (parent / ".git").exists():
                    break
            else:
                return self.workdir
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, cwd=self.workdir, timeout=2,
            )
            if result.returncode == 0:
                return Path(result.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return self.workdir
```

Pass memory_manager to PromptContext:

```python
        self._prompt_ctx = PromptContext(
            workdir=self.workdir,
            skill_manager=self.skills,
            mcp_manager=self.mcp,
            memory_manager=self._memory_manager,
        )
```

- [x] **Step 4: Wire flush hook into _step_impl and _step_stream_impl**

In both `_step_impl` and `_step_stream_impl`, before `self.session.maybe_compact()`:

```python
        # Pre-compact memory flush
        if self.session.context_manager.should_compact() and self._memory_manager:
            if self.config.memory.auto_flush_on_compact:
                compactable = self.session.chain.get_compactable_messages()
                # Convert TranscriptMessages to dicts for flush, preserving
                # multi-block content and tool result metadata
                flush_msgs = []
                for msg in compactable:
                    # Extract text from all content blocks
                    text_parts = []
                    for block in (msg.content or []):
                        if hasattr(block, "text"):
                            text_parts.append(block.text)
                        elif hasattr(block, "content"):
                            text_parts.append(str(block.content))

                    # Extract tool results with error flags
                    tool_results = []
                    for block in (msg.content or []):
                        if hasattr(block, "tool_use_id"):
                            tool_results.append({
                                "tool_name": getattr(block, "tool_name", "unknown"),
                                "output": getattr(block, "content", "")
                                    if isinstance(getattr(block, "content", ""), str)
                                    else str(getattr(block, "content", "")),
                                "is_error": getattr(block, "is_error", False),
                            })

                    flush_msgs.append({
                        "role": msg.role.value,
                        "content": "\n".join(text_parts),
                        "uuid": str(getattr(msg, "uuid", "")),
                        "tool_results": tool_results,
                    })
                self._memory_manager.flush_before_compact(
                    flush_msgs, session_id=self.session.session_id,
                )

        # Check if we need full compression
        self.session.maybe_compact()
```

- [x] **Step 5: Wire memory into ToolContext creation**

In `Agent._make_tool_context()` (or wherever ToolContext is constructed), add:

```python
        memory_actor = None
        if self._memory_manager:
            from bourbon.memory.models import MemoryActor
            if self._subagent_agent_def:
                memory_actor = MemoryActor(
                    kind="subagent",
                    session_id=self.session.session_id,
                    run_id=getattr(self._subagent_agent_def, "run_id", None),
                    agent_type=getattr(self._subagent_agent_def, "type", None),
                )
            else:
                memory_actor = MemoryActor(kind="agent", session_id=self.session.session_id)

        ctx = ToolContext(
            workdir=self.workdir,
            agent=self,
            skill_manager=self.skills,
            memory_manager=self._memory_manager,
            memory_actor=memory_actor,
        )
```

- [x] **Step 6: Run tests to verify pass**

Run: `pytest tests/test_memory_agent_integration.py -v`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add src/bourbon/agent.py tests/test_memory_agent_integration.py
git commit -m "feat(memory): wire MemoryManager into Agent init, flush hook, and ToolContext"
```

---

## Task 15: Daily Log Writer

**Files:**
- Modify: `src/bourbon/memory/compact.py`
- Test: `tests/test_memory_compact.py`

- [x] **Step 1: Write failing test for daily log writing**

```python
# append to tests/test_memory_compact.py
from pathlib import Path
from datetime import datetime, UTC
from bourbon.memory.compact import write_daily_log


def test_write_daily_log_creates_file(tmp_path):
    log_dir = tmp_path / "logs"
    write_daily_log(
        log_dir=log_dir,
        session_start=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
        session_id="ses_test123",
        entries=["Discussed WAL mode decision", "Fixed bug in sandbox"],
    )
    expected_file = log_dir / "2026" / "04" / "2026-04-20.md"
    assert expected_file.exists()
    content = expected_file.read_text()
    assert "WAL mode" in content
    assert "ses_test123" in content


def test_write_daily_log_appends_to_existing(tmp_path):
    log_dir = tmp_path / "logs"
    dt = datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    write_daily_log(log_dir=log_dir, session_start=dt, session_id="ses_1", entries=["First entry"])
    write_daily_log(log_dir=log_dir, session_start=dt, session_id="ses_2", entries=["Second entry"])

    content = (log_dir / "2026" / "04" / "2026-04-20.md").read_text()
    assert "First entry" in content
    assert "Second entry" in content


def test_write_daily_log_uses_session_start_date(tmp_path):
    """Cross-midnight: use session start date, not current date."""
    log_dir = tmp_path / "logs"
    # Session started on April 20, flush happens April 21
    session_start = datetime(2026, 4, 20, 23, 50, tzinfo=UTC)
    write_daily_log(
        log_dir=log_dir,
        session_start=session_start,
        session_id="ses_cross",
        entries=["Late night work"],
    )
    assert (log_dir / "2026" / "04" / "2026-04-20.md").exists()
    assert not (log_dir / "2026" / "04" / "2026-04-21.md").exists()
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_compact.py::test_write_daily_log_creates_file -v`
Expected: FAIL

- [x] **Step 3: Implement write_daily_log**

```python
# Add to src/bourbon/memory/compact.py
from pathlib import Path
from datetime import datetime


def write_daily_log(
    log_dir: Path,
    *,
    session_start: datetime,
    session_id: str,
    entries: list[str],
) -> Path:
    """Write entries to the daily log for the session's start date.

    Uses session start date (not current time) for cross-midnight consistency.
    Appends to existing log file if present.

    Note: daily log uses simple write (not atomic rename) because:
    - Append-only pattern has low corruption risk
    - Concurrent appends from different sessions are unlikely in Phase 1
      (single-process agent). If subagents become multi-process, upgrade to
      atomic write + file lock.
    """
    date_str = session_start.strftime("%Y-%m-%d")
    year = session_start.strftime("%Y")
    month = session_start.strftime("%m")

    log_path = log_dir / year / month / f"{date_str}.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Build log section
    time_str = session_start.strftime("%H:%M")
    section = f"\n## Session {session_id} ({time_str})\n\n"
    for entry in entries:
        section += f"- {entry}\n"

    # Append to existing file
    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        log_path.write_text(existing + section, encoding="utf-8")
    else:
        header = f"# Daily Log: {date_str}\n"
        log_path.write_text(header + section, encoding="utf-8")

    return log_path
```

- [x] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_memory_compact.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/bourbon/memory/compact.py tests/test_memory_compact.py
git commit -m "feat(memory): implement daily log writer with cross-midnight date handling"
```

---

## Task 16: Graceful Degradation (memory.enabled=false)

**Files:**
- Test: `tests/test_memory_tools.py` (append)

- [x] **Step 1: Write test for disabled memory**

```python
# append to tests/test_memory_tools.py
import json
from bourbon.tools import ToolContext
from bourbon.tools.memory import memory_search, memory_write, memory_status
from pathlib import Path


def test_memory_tools_return_error_when_disabled():
    ctx = ToolContext(workdir=Path("/tmp"))
    # memory_manager is None by default
    result = json.loads(memory_search(query="test", ctx=ctx))
    assert "error" in result

    result = json.loads(memory_write(
        content="test", kind="project", scope="project", source="user", ctx=ctx
    ))
    assert "error" in result

    result = json.loads(memory_status(ctx=ctx))
    assert "error" in result
```

- [x] **Step 2: Run test to verify it passes (already implemented in Step 3 of Task 11)**

Run: `pytest tests/test_memory_tools.py::test_memory_tools_return_error_when_disabled -v`
Expected: PASS (tool handlers already check for None manager)

- [x] **Step 3: Commit (if needed)**

If the test already passes, no code change needed. Verify with:

```bash
pytest tests/test_memory_tools.py -v
```

---

## Task 17: End-to-End Integration Test

**Files:**
- Test: `tests/test_memory_e2e.py`

- [x] **Step 1: Write end-to-end test**

```python
# tests/test_memory_e2e.py
"""End-to-end memory flow: write → search → status → prompt rendering."""
import pytest
from pathlib import Path
from datetime import datetime, UTC
import asyncio

from bourbon.config import MemoryConfig
from bourbon.memory.manager import MemoryManager
from bourbon.memory.models import (
    MemoryActor, MemoryKind, MemoryRecordDraft, MemoryScope, MemorySource,
)
from bourbon.memory.prompt import memory_anchors_section
from bourbon.prompt.types import PromptContext


@pytest.fixture
def e2e_setup(tmp_path):
    """Full memory system setup for e2e testing."""
    workdir = tmp_path / "project"
    workdir.mkdir()

    config = MemoryConfig(storage_dir=str(tmp_path / "store"))
    manager = MemoryManager(
        config=config,
        project_key="e2e-test-12345678",
        workdir=workdir,
        audit=None,
    )
    return manager, workdir, tmp_path


def test_write_search_roundtrip(e2e_setup):
    manager, workdir, tmp_path = e2e_setup
    actor = MemoryActor(kind="user")

    # Write
    draft = MemoryRecordDraft(
        kind=MemoryKind.FEEDBACK,
        scope=MemoryScope.PROJECT,
        content="Never mock the database in integration tests.",
        source=MemorySource.USER,
        confidence=1.0,
        name="No DB mocks",
        description="Integration tests must hit real DB",
    )
    record = manager.write(draft, actor=actor)
    assert record.id.startswith("mem_")

    # Search
    results = manager.search("mock database")
    assert len(results) >= 1
    assert any("mock" in r.snippet.lower() or "database" in r.snippet.lower() for r in results)

    # Status
    status = manager.get_status(actor=actor)
    assert status.memory_file_count == 1
    assert not status.index_at_capacity


def test_prompt_section_renders_index(e2e_setup):
    manager, workdir, tmp_path = e2e_setup
    actor = MemoryActor(kind="user")

    # Write a memory
    draft = MemoryRecordDraft(
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        content="Use SQLite WAL mode.",
        source=MemorySource.USER,
        confidence=1.0,
        name="WAL mode",
        description="Always use WAL mode for SQLite",
    )
    manager.write(draft, actor=actor)

    # Render prompt section
    ctx = PromptContext(workdir=workdir, memory_manager=manager)
    result = asyncio.run(memory_anchors_section(ctx))
    assert "WAL mode" in result


def test_rejected_memory_not_in_default_search(e2e_setup):
    manager, workdir, tmp_path = e2e_setup
    actor = MemoryActor(kind="user")

    # Write then manually mark as rejected
    draft = MemoryRecordDraft(
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        content="Old wrong advice.",
        source=MemorySource.USER,
        confidence=1.0,
        name="Wrong advice",
        description="This was wrong",
    )
    record = manager.write(draft, actor=actor)

    # Manually update status in file (simulating MemoryReject which is Phase 2)
    from dataclasses import replace
    from bourbon.memory.models import MemoryStatus
    rejected_record = replace(record, status=MemoryStatus.REJECTED)
    manager._store.write_record(rejected_record)

    # Default search should not find it
    results = manager.search("Old wrong advice")
    assert len(results) == 0
```

- [x] **Step 2: Run e2e tests**

Run: `pytest tests/test_memory_e2e.py -v`
Expected: PASS

- [x] **Step 3: Run full test suite**

Run: `pytest tests/test_memory_*.py -v`
Expected: ALL PASS

- [x] **Step 4: Commit**

```bash
git add tests/test_memory_e2e.py
git commit -m "test(memory): add end-to-end integration tests for memory Phase 1"
```

---

## Task 18: Lint, Type Check, Final Verification

- [x] **Step 1: Run linter**

```bash
ruff check src/bourbon/memory/ src/bourbon/tools/memory.py
ruff format src/bourbon/memory/ src/bourbon/tools/memory.py
```

- [x] **Step 2: Run type checker**

```bash
mypy src/bourbon/memory/
```

Fix any type errors.

- [x] **Step 3: Run full project test suite**

```bash
pytest
```

Verify no regressions.

- [x] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore(memory): fix lint and type errors for Phase 1 memory system"
```
