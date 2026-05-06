# Bourbon Memory Minimal Model Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Bourbon's over-modeled memory stack with the minimal `target + content + created_at + cues` model defined in `docs/superpowers/specs/2026-05-06-bourbon-memory-minimal-model-design.md`.

**Architecture:** Memory records become immutable, active-only Markdown files with minimal YAML frontmatter. The `src/bourbon/memory/cues/` package is removed and replaced by one small `src/bourbon/memory/cues.py` helper module for cue normalization, write-time cue extraction, and query term expansion. Manager, tools, prompt text, config, evals, and tests are updated to remove `kind`, `scope`, `status`, promotion/archive lifecycle, source metadata, cue telemetry, query cue models, backfill, and compact-time memory flushing.

**Tech Stack:** Python 3.12, dataclasses, YAML frontmatter, pytest, uv, promptfoo Python provider.

---

## File Structure

- Modify `src/bourbon/memory/models.py`: minimal model dataclasses and target validation.
- Modify `src/bourbon/memory/__init__.py`: export only minimal memory symbols.
- Modify `src/bourbon/memory/policy.py`: target-based write/delete permissions.
- Modify `src/bourbon/config.py`: remove compact flush and cue schema config fields.
- Create `src/bourbon/memory/cues.py`: single cue helper module.
- Delete `src/bourbon/memory/cues/`: old package with models/query/runtime/backfill/eval.
- Modify `src/bourbon/memory/store.py`: minimal frontmatter, id filename, full index rebuild, delete, content/cue search.
- Modify `src/bourbon/memory/manager.py`: write/search/delete/status orchestration and required write audit.
- Modify `src/bourbon/tools/memory.py`: `memory_write`, `memory_search`, `memory_delete`, `memory_status`; remove promote/archive tools.
- Modify `src/bourbon/tools/__init__.py`: remove cue runtime context from `ToolContext`.
- Modify `src/bourbon/agent.py`: remove cue runtime context builder and compact memory flush hook.
- Modify `src/bourbon/prompt/sections.py`: remove promote/archive/status filter prompt guidance.
- Modify `src/bourbon/memory/files.py`: remove managed preference block helpers tied to promote/archive; keep anchor reading and USER.md merge.
- Delete `src/bourbon/memory/compact.py`: no compact-time memory extraction.
- Delete `scripts/backfill_memory_cues.py`: no cue backfill workflow.
- Modify `src/bourbon/audit/events.py`: remove memory promote/reject/flush events and add memory delete event.
- Create `evals/memory_retrieval_provider.py` and delete `evals/memory_cue_retrieval_provider.py`: evaluate `content_only`, `content_plus_cues`, and `expanded_query_plus_cues`.
- Create `evals/cases/memory-retrieval.yaml`, create `evals/fixtures/memory_retrieval/retrieval-smoke.json`, and delete the old memory-cue eval files.
- Replace memory tests under `tests/test_memory_*.py` with minimal-model tests; delete obsolete cue/backfill/phase2/compact tests.

---

### Task 1: Minimal Models, Policy, And Config

**Files:**
- Modify: `src/bourbon/memory/models.py`
- Modify: `src/bourbon/memory/__init__.py`
- Modify: `src/bourbon/memory/policy.py`
- Modify: `src/bourbon/config.py`
- Test: `tests/test_memory_models.py`
- Test: `tests/test_memory_policy.py`
- Test: `tests/test_memory_config.py`

- [ ] **Step 1: Replace model tests with minimal model expectations**

Replace `tests/test_memory_models.py` with:

```python
"""Tests for minimal Bourbon memory models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

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


def test_memory_targets_are_user_and_project_only() -> None:
    assert MEMORY_TARGETS == ("user", "project")
    assert validate_memory_target("user") == "user"
    assert validate_memory_target("project") == "project"
    with pytest.raises(ValueError, match="Invalid memory target"):
        validate_memory_target("session")


def test_memory_actor_identifies_runtime_writer() -> None:
    actor = MemoryActor(
        kind="subagent",
        session_id="ses_1",
        run_id="run_1",
        agent_type="explorer",
    )

    assert actor.kind == "subagent"
    assert actor.session_id == "ses_1"
    assert actor.run_id == "run_1"
    assert actor.agent_type == "explorer"


def test_memory_record_draft_only_requires_target_and_content() -> None:
    draft = MemoryRecordDraft(target="project", content="Prefer append-only memory records.")

    assert draft.target == "project"
    assert draft.content == "Prefer append-only memory records."


def test_memory_record_has_minimal_fields() -> None:
    created_at = datetime(2026, 5, 6, 8, 30, tzinfo=UTC)
    record = MemoryRecord(
        id="mem_abc12345",
        target="user",
        content="User prefers dark mode for UI components.",
        created_at=created_at,
        cues=("dark mode", "ui preference"),
    )

    assert record.__dict__ == {
        "id": "mem_abc12345",
        "target": "user",
        "content": "User prefers dark mode for UI components.",
        "created_at": created_at,
        "cues": ("dark mode", "ui preference"),
    }


def test_memory_search_result_is_target_based() -> None:
    result = MemorySearchResult(
        id="mem_abc12345",
        target="project",
        snippet="Prefer append-only memory records.",
        why_matched="matched content: append-only",
    )

    assert result.target == "project"
    assert result.why_matched == "matched content: append-only"


def test_memory_system_info_uses_targets_not_status() -> None:
    info = MemorySystemInfo(
        readable_targets=("user", "project"),
        writable_targets=("project",),
        recent_writes=(
            RecentWriteSummary(
                id="mem_abc12345",
                target="project",
                preview="Prefer append-only memory records.",
                created_at=datetime(2026, 5, 6, tzinfo=UTC),
            ),
        ),
        index_at_capacity=False,
        memory_file_count=1,
    )

    assert info.readable_targets == ("user", "project")
    assert info.writable_targets == ("project",)
    assert info.recent_writes[0].preview == "Prefer append-only memory records."
```

- [ ] **Step 2: Replace policy tests with target permission tests**

Replace `tests/test_memory_policy.py` with:

```python
"""Tests for minimal memory target permissions."""

from __future__ import annotations

import pytest

from bourbon.memory.models import MemoryActor
from bourbon.memory.policy import check_delete_permission, check_write_permission


def test_user_agent_and_system_can_write_user_and_project_targets() -> None:
    for actor in (
        MemoryActor(kind="user"),
        MemoryActor(kind="agent", session_id="ses_1"),
        MemoryActor(kind="system"),
    ):
        assert check_write_permission(actor, target="user") is True
        assert check_write_permission(actor, target="project") is True


def test_subagents_can_write_project_but_not_user_target() -> None:
    actor = MemoryActor(kind="subagent", session_id="ses_1", run_id="run_1")

    assert check_write_permission(actor, target="project") is True
    assert check_write_permission(actor, target="user") is False


def test_delete_permission_rejects_subagents() -> None:
    check_delete_permission(MemoryActor(kind="agent", session_id="ses_1"))
    check_delete_permission(MemoryActor(kind="user"))
    check_delete_permission(MemoryActor(kind="system"))

    with pytest.raises(PermissionError, match="Subagents cannot delete memory"):
        check_delete_permission(MemoryActor(kind="subagent", run_id="run_1"))
```

- [ ] **Step 3: Replace memory config tests**

Update `tests/test_memory_config.py` so the memory config assertions are:

```python
def test_memory_config_defaults():
    cfg = MemoryConfig()
    assert cfg.enabled is True
    assert cfg.storage_dir == "~/.bourbon/projects"
    assert cfg.recall_limit == 8
    assert cfg.memory_md_token_limit == 1200
    assert cfg.user_md_token_limit == 600


def test_config_from_dict_memory_minimal_fields() -> None:
    cfg = Config.from_dict(
        {
            "memory": {
                "enabled": False,
                "storage_dir": "/tmp/memory",
                "recall_limit": 3,
                "memory_md_token_limit": 500,
                "user_md_token_limit": 250,
            }
        }
    )

    assert cfg.memory.enabled is False
    assert cfg.memory.storage_dir == "/tmp/memory"
    assert cfg.memory.recall_limit == 3
    assert cfg.memory.memory_md_token_limit == 500
    assert cfg.memory.user_md_token_limit == 250


def test_config_to_dict_memory_minimal_fields() -> None:
    cfg = Config()
    data = cfg.to_dict()

    assert data["memory"] == {
        "enabled": True,
        "storage_dir": "~/.bourbon/projects",
        "recall_limit": 8,
        "memory_md_token_limit": 1200,
        "user_md_token_limit": 600,
    }
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_memory_models.py tests/test_memory_policy.py tests/test_memory_config.py -q
```

Expected: FAIL with import errors for removed/renamed symbols or assertions showing old config fields still exist.

- [ ] **Step 5: Replace `src/bourbon/memory/models.py`**

Use this content:

```python
"""Minimal memory data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MemoryTarget = Literal["user", "project"]
MEMORY_TARGETS: tuple[MemoryTarget, ...] = ("user", "project")


def validate_memory_target(value: str) -> MemoryTarget:
    """Validate and return a memory target."""
    if value not in MEMORY_TARGETS:
        allowed = ", ".join(MEMORY_TARGETS)
        raise ValueError(f"Invalid memory target {value!r}; expected one of: {allowed}")
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class MemoryActor:
    """Identifies who is performing a memory operation."""

    kind: Literal["user", "agent", "subagent", "system"]
    session_id: str | None = None
    run_id: str | None = None
    agent_type: str | None = None


@dataclass(frozen=True)
class MemoryRecordDraft:
    """Input for creating a memory record."""

    target: MemoryTarget
    content: str


@dataclass(frozen=True)
class MemoryRecord:
    """A persisted memory record."""

    id: str
    target: MemoryTarget
    content: str
    created_at: datetime
    cues: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemorySearchResult:
    """A single search result returned by memory search."""

    id: str
    target: MemoryTarget
    snippet: str
    why_matched: str = ""


@dataclass(frozen=True)
class RecentWriteSummary:
    """Summary of a recent memory write for memory status display."""

    id: str
    target: MemoryTarget
    preview: str
    created_at: datetime


@dataclass(frozen=True)
class MemorySystemInfo:
    """Runtime memory system information."""

    readable_targets: tuple[str, ...]
    writable_targets: tuple[str, ...]
    recent_writes: tuple[RecentWriteSummary, ...]
    index_at_capacity: bool
    memory_file_count: int
```

- [ ] **Step 6: Replace memory exports**

Use this content for `src/bourbon/memory/__init__.py`:

```python
"""Bourbon memory system."""

from bourbon.memory.models import (
    MEMORY_TARGETS,
    MemoryActor,
    MemoryRecord,
    MemoryRecordDraft,
    MemorySearchResult,
    MemorySystemInfo,
    MemoryTarget,
    RecentWriteSummary,
    validate_memory_target,
)

__all__ = [
    "MEMORY_TARGETS",
    "MemoryActor",
    "MemoryRecord",
    "MemoryRecordDraft",
    "MemorySearchResult",
    "MemorySystemInfo",
    "MemoryTarget",
    "RecentWriteSummary",
    "validate_memory_target",
]
```

- [ ] **Step 7: Replace memory policy**

Use this content for `src/bourbon/memory/policy.py`:

```python
"""Memory access policy helpers."""

from __future__ import annotations

from bourbon.memory.models import MemoryActor, MemoryTarget


def check_write_permission(actor: MemoryActor, *, target: MemoryTarget) -> bool:
    """Return whether the actor can write a memory for the target."""
    if actor.kind == "subagent":
        return target == "project"
    return actor.kind in {"user", "agent", "system"}


def check_delete_permission(actor: MemoryActor) -> None:
    """Raise when the actor cannot delete a memory record."""
    if actor.kind == "subagent":
        raise PermissionError("Subagents cannot delete memory records")
```

- [ ] **Step 8: Simplify memory config**

In `src/bourbon/config.py`, replace `MemoryConfig` with:

```python
@dataclass
class MemoryConfig:
    """Memory system configuration."""

    enabled: bool = True
    storage_dir: str = "~/.bourbon/projects"
    recall_limit: int = 8
    memory_md_token_limit: int = 1200
    user_md_token_limit: int = 600
```

In `Config.to_dict()`, replace the `"memory"` payload with:

```python
"memory": {
    "enabled": self.memory.enabled,
    "storage_dir": self.memory.storage_dir,
    "recall_limit": self.memory.recall_limit,
    "memory_md_token_limit": self.memory.memory_md_token_limit,
    "user_md_token_limit": self.memory.user_md_token_limit,
},
```

- [ ] **Step 9: Run focused tests**

Run:

```bash
uv run pytest tests/test_memory_models.py tests/test_memory_policy.py tests/test_memory_config.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

Run:

```bash
git add src/bourbon/memory/models.py src/bourbon/memory/__init__.py src/bourbon/memory/policy.py src/bourbon/config.py tests/test_memory_models.py tests/test_memory_policy.py tests/test_memory_config.py
git commit -m "refactor(memory): reduce core memory models"
```

---

### Task 2: Single Cue Helper And Minimal Store

**Files:**
- Create: `src/bourbon/memory/cues.py`
- Delete: `src/bourbon/memory/cues/__init__.py`
- Delete: `src/bourbon/memory/cues/backfill.py`
- Delete: `src/bourbon/memory/cues/engine.py`
- Delete: `src/bourbon/memory/cues/eval.py`
- Delete: `src/bourbon/memory/cues/models.py`
- Delete: `src/bourbon/memory/cues/query.py`
- Delete: `src/bourbon/memory/cues/runtime.py`
- Modify: `src/bourbon/memory/store.py`
- Test: `tests/test_memory_cues.py`
- Test: `tests/test_memory_store.py`

- [ ] **Step 1: Add cue helper tests**

Create `tests/test_memory_cues.py`:

```python
"""Tests for minimal memory cue helpers."""

from __future__ import annotations

from bourbon.memory.cues import MAX_CUES, expand_query_terms, generate_cues, normalize_cues


def test_normalize_cues_trims_deduplicates_and_limits() -> None:
    values = [" dark mode ", "", "dark mode", "ui", *[f"term-{index}" for index in range(20)]]

    cues = normalize_cues(values)

    assert cues[0:2] == ("dark mode", "ui")
    assert len(cues) == MAX_CUES
    assert "" not in cues


def test_generate_cues_extracts_backticks_quotes_and_paths() -> None:
    content = 'Use `dark mode` for "settings panels" in src/ui/theme.py.'

    cues = generate_cues(content)

    assert cues == ("dark mode", "settings panels", "src/ui/theme.py")


def test_generate_cues_returns_empty_tuple_for_plain_content() -> None:
    assert generate_cues("User prefers concise replies.") == ()


def test_expand_query_terms_returns_normalized_query_and_extracted_terms() -> None:
    terms = expand_query_terms('Find `dark mode` memory in src/ui/theme.py')

    assert terms == (
        "Find `dark mode` memory in src/ui/theme.py",
        "dark mode",
        "src/ui/theme.py",
    )
```

- [ ] **Step 2: Replace store tests with minimal frontmatter tests**

Replace `tests/test_memory_store.py` with:

```python
"""Tests for minimal memory store."""

from __future__ import annotations

from datetime import UTC, datetime

from bourbon.memory.models import MemoryRecord
from bourbon.memory.store import MemoryStore, _record_preview, _record_to_filename


def _record(
    memory_id: str = "mem_abc12345",
    *,
    target: str = "project",
    content: str = "Prefer append-only memory records.",
    cues: tuple[str, ...] = ("append-only",),
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        target=target,  # type: ignore[arg-type]
        content=content,
        created_at=datetime(2026, 5, 6, 8, 0, tzinfo=UTC),
        cues=cues,
    )


def test_record_filename_is_id_only() -> None:
    assert _record_to_filename(_record()) == "mem_abc12345.md"


def test_record_preview_uses_first_line() -> None:
    assert _record_preview(_record(content="First line.\nSecond line.")) == "First line."


def test_store_round_trips_minimal_frontmatter(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    record = _record(target="user", content="User prefers dark mode.", cues=("dark mode",))

    path = store.write_record(record)
    loaded = store.read_record(record.id)

    assert path.name == "mem_abc12345.md"
    assert loaded == record
    raw = path.read_text(encoding="utf-8")
    assert "target: user" in raw
    assert "created_at:" in raw
    assert "cues:" in raw
    assert "kind:" not in raw
    assert "scope:" not in raw
    assert "status:" not in raw
    assert "created_by:" not in raw
    assert "cue_metadata:" not in raw


def test_store_rebuilds_index_after_write_and_delete(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    first = _record("mem_first111", target="user", content="User prefers dark mode.")
    second = _record("mem_second22", target="project", content="Prefer append-only memory records.")

    store.write_record(first)
    store.write_record(second)

    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "- [user] User prefers dark mode." in index
    assert "- [project] Prefer append-only memory records." in index

    store.delete_record(first.id)

    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "User prefers dark mode." not in index
    assert "Prefer append-only memory records." in index


def test_search_matches_content_and_cues_with_target_filter(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    store.write_record(_record("mem_user1111", target="user", content="User likes compact output."))
    store.write_record(
        _record(
            "mem_project1",
            target="project",
            content="Theme settings live in the UI package.",
            cues=("dark mode",),
        )
    )

    cue_results = store.search("dark mode")
    target_results = store.search("compact", target="project")

    assert [result.id for result in cue_results] == ["mem_project1"]
    assert cue_results[0].why_matched == "matched cue: dark mode"
    assert target_results == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_memory_cues.py tests/test_memory_store.py -q
```

Expected: FAIL because `src/bourbon/memory/cues.py` does not exist and store still expects the old model.

- [ ] **Step 4: Remove old cue package and add single cue module**

Run:

```bash
git rm -r src/bourbon/memory/cues
```

Create `src/bourbon/memory/cues.py`:

```python
"""Small cue helpers for minimal memory search."""

from __future__ import annotations

import re
from collections.abc import Iterable

MAX_CUES = 12
_MAX_CUE_LENGTH = 80
_BACKTICK_RE = re.compile(r"`([^`]{1,120})`")
_QUOTE_RE = re.compile(r'"([^"]{1,120})"')
_PATH_RE = re.compile(r"(?<!\w)[\w./@+-]+\.[A-Za-z0-9]{1,8}(?!\w)")


def _clean_term(value: object) -> str:
    text = " ".join(str(value).strip().split())
    return text[:_MAX_CUE_LENGTH].rstrip()


def normalize_cues(values: Iterable[object], *, limit: int = MAX_CUES) -> tuple[str, ...]:
    """Normalize cue strings while preserving first-seen order."""
    cues: list[str] = []
    seen: set[str] = set()
    for value in values:
        cue = _clean_term(value)
        key = cue.casefold()
        if not cue or key in seen:
            continue
        cues.append(cue)
        seen.add(key)
        if len(cues) >= limit:
            break
    return tuple(cues)


def _extract_terms(text: str) -> list[str]:
    terms: list[str] = []
    terms.extend(match.group(1) for match in _BACKTICK_RE.finditer(text))
    terms.extend(match.group(1) for match in _QUOTE_RE.finditer(text))
    terms.extend(match.group(0) for match in _PATH_RE.finditer(text))
    return terms


def generate_cues(content: str) -> tuple[str, ...]:
    """Generate write-time cues from explicit textual hints only."""
    return normalize_cues(_extract_terms(content))


def expand_query_terms(query: str) -> tuple[str, ...]:
    """Return the normalized query plus explicit terms extracted from it."""
    base = _clean_term(query)
    if not base:
        return ()
    return normalize_cues((base, *_extract_terms(query)))
```

- [ ] **Step 5: Replace `src/bourbon/memory/store.py`**

Use the minimal store implementation below:

```python
"""Minimal memory file store."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from bourbon.memory.cues import normalize_cues
from bourbon.memory.models import MemoryRecord, MemorySearchResult, validate_memory_target

_index_lock = threading.Lock()


def sanitize_project_key(canonical_path: Path) -> str:
    """Derive a filesystem-safe project key from canonical path."""
    path_str = str(canonical_path)
    slug = path_str.replace("/", "-").replace("\\", "-").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")[:64]
    hash_suffix = hashlib.sha256(path_str.encode()).hexdigest()[:8]
    return f"{slug}-{hash_suffix}"


def _record_to_filename(record: MemoryRecord) -> str:
    """Return the record filename."""
    return f"{record.id}.md"


def _record_preview(record: MemoryRecord, *, limit: int = 100) -> str:
    """Return display text derived from content."""
    first_line = next((line.strip() for line in record.content.splitlines() if line.strip()), "")
    preview = first_line or record.content.strip()
    return preview[:limit].rstrip()


def _record_to_frontmatter(record: MemoryRecord) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": record.id,
        "target": record.target,
        "created_at": record.created_at.isoformat(),
    }
    if record.cues:
        raw["cues"] = list(record.cues)
    return raw


def _record_to_file_content(record: MemoryRecord) -> str:
    frontmatter = yaml.dump(_record_to_frontmatter(record), default_flow_style=False)
    return f"---\n{frontmatter}---\n\n{record.content.rstrip()}\n"


def _frontmatter_to_record(fm: dict[str, Any], body: str) -> MemoryRecord:
    created_at = fm["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    cues = fm.get("cues", [])
    if not isinstance(cues, list):
        cues = []
    return MemoryRecord(
        id=str(fm["id"]),
        target=validate_memory_target(str(fm["target"])),
        content=body.strip(),
        created_at=created_at,
        cues=normalize_cues(cues),
    )


class MemoryStore:
    """File-based memory storage with atomic writes and simple search."""

    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir
        self._id_to_filename: dict[str, str] = {}
        self._scan_existing()

    def _scan_existing(self) -> None:
        if not self.memory_dir.exists():
            return
        for path in self.memory_dir.glob("*.md"):
            if path.name == "MEMORY.md":
                continue
            try:
                fm, _ = self._parse_file(path)
                if "id" in fm:
                    self._id_to_filename[str(fm["id"])] = path.name
            except Exception:
                continue

    def _parse_file(self, path: Path) -> tuple[dict[str, Any], str]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return {}, text
        end_marker = text.find("\n---\n", 4)
        if end_marker == -1:
            return {}, text
        raw_frontmatter = text[4:end_marker]
        body = text[end_marker + len("\n---\n") :]
        loaded = yaml.safe_load(raw_frontmatter) or {}
        return loaded if isinstance(loaded, dict) else {}, body

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            fd = -1
            os.replace(tmp_path, path)
        except Exception:
            if fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(fd)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def write_record(self, record: MemoryRecord) -> Path:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        filename = _record_to_filename(record)
        target = self.memory_dir / filename
        self._atomic_write(target, _record_to_file_content(record))
        self._id_to_filename[record.id] = filename
        self.rebuild_index()
        return target

    def delete_record(self, memory_id: str) -> None:
        filename = self._id_to_filename.get(memory_id)
        if filename is None:
            self._scan_existing()
            filename = self._id_to_filename.get(memory_id)
        if filename is None:
            raise KeyError(f"Unknown memory id: {memory_id}")
        path = self.memory_dir / filename
        if path.exists():
            path.unlink()
        self._id_to_filename.pop(memory_id, None)
        self.rebuild_index()

    def read_record(self, memory_id: str) -> MemoryRecord | None:
        filename = self._id_to_filename.get(memory_id)
        if filename is None:
            self._scan_existing()
            filename = self._id_to_filename.get(memory_id)
        if filename is None:
            return None
        path = self.memory_dir / filename
        if not path.exists():
            return None
        fm, body = self._parse_file(path)
        if "id" not in fm:
            return None
        return _frontmatter_to_record(fm, body)

    def list_records(self) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        if not self.memory_dir.exists():
            return records
        for path in sorted(self.memory_dir.glob("*.md")):
            if path.name == "MEMORY.md":
                continue
            try:
                fm, body = self._parse_file(path)
                if "id" not in fm:
                    continue
                records.append(_frontmatter_to_record(fm, body))
            except Exception:
                continue
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def rebuild_index(self) -> bool:
        records = self.list_records()[:200]
        lines = [
            f"- [{record.target}] {_record_preview(record)} ([{_record_to_filename(record)}]({_record_to_filename(record)}))"
            for record in records
        ]
        content = "\n".join(lines)
        if content:
            content += "\n"
        with _index_lock:
            self._atomic_write(self.memory_dir / "MEMORY.md", content)
        return len(records) >= 200

    def search(
        self,
        query: str,
        *,
        target: str | None = None,
        limit: int = 8,
    ) -> list[MemorySearchResult]:
        normalized_query = query.casefold()
        results: list[MemorySearchResult] = []
        for record in self.list_records():
            if target is not None and record.target != target:
                continue
            content_match = normalized_query in record.content.casefold()
            matched_cue = next(
                (cue for cue in record.cues if normalized_query in cue.casefold()),
                None,
            )
            if not content_match and matched_cue is None:
                continue
            reason = (
                f"matched cue: {matched_cue}"
                if matched_cue is not None
                else f"matched content: {query}"
            )
            results.append(
                MemorySearchResult(
                    id=record.id,
                    target=record.target,
                    snippet=_record_preview(record),
                    why_matched=reason,
                )
            )
            if len(results) >= limit:
                break
        return results
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/test_memory_cues.py tests/test_memory_store.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/bourbon/memory/cues.py src/bourbon/memory/store.py tests/test_memory_cues.py tests/test_memory_store.py
git add -u src/bourbon/memory/cues
git commit -m "refactor(memory): collapse cues and store format"
```

---

### Task 3: Manager, Audit, And Delete Semantics

**Files:**
- Modify: `src/bourbon/memory/manager.py`
- Modify: `src/bourbon/audit/events.py`
- Test: `tests/test_memory_manager.py`
- Test: `tests/test_memory_audit.py`

- [ ] **Step 1: Replace manager tests with minimal orchestration tests**

Replace `tests/test_memory_manager.py` with focused tests:

```python
"""Tests for minimal MemoryManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from bourbon.audit.events import EventType
from bourbon.config import MemoryConfig
from bourbon.memory.manager import MemoryManager
from bourbon.memory.models import MemoryActor, MemoryRecordDraft


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[object] = []

    def record(self, event: object) -> None:
        self.events.append(event)


@pytest.fixture
def audit() -> FakeAudit:
    return FakeAudit()


@pytest.fixture
def manager(tmp_path: Path, audit: FakeAudit) -> MemoryManager:
    return MemoryManager(
        config=MemoryConfig(storage_dir=str(tmp_path)),
        project_key="proj",
        workdir=tmp_path,
        audit=audit,  # type: ignore[arg-type]
    )


def test_write_persists_record_and_emits_required_audit(
    manager: MemoryManager,
    audit: FakeAudit,
) -> None:
    record = manager.write(
        MemoryRecordDraft(target="project", content='Use `dark mode` for UI settings.'),
        actor=MemoryActor(kind="agent", session_id="ses_1"),
    )

    assert record.target == "project"
    assert record.cues == ("dark mode",)
    assert len(audit.events) == 1
    event = audit.events[0]
    assert event.event_type == EventType.MEMORY_WRITE
    assert event.extra["actor_kind"] == "agent"
    assert event.extra["session_id"] == "ses_1"
    assert event.extra["target"] == "project"
    assert event.extra["memory_id"] == record.id


def test_write_fails_without_audit(tmp_path: Path) -> None:
    manager = MemoryManager(
        config=MemoryConfig(storage_dir=str(tmp_path)),
        project_key="proj",
        workdir=tmp_path,
        audit=None,
    )

    with pytest.raises(RuntimeError, match="memory writes require audit"):
        manager.write(
            MemoryRecordDraft(target="project", content="Missing audit must fail."),
            actor=MemoryActor(kind="agent"),
        )


def test_search_uses_expanded_terms_and_target_filter(manager: MemoryManager) -> None:
    manager.write(
        MemoryRecordDraft(target="project", content='Use `dark mode` for UI settings.'),
        actor=MemoryActor(kind="agent", session_id="ses_1"),
    )

    results = manager.search("dark mode", target="project")

    assert [result.target for result in results] == ["project"]
    assert manager.get_last_expanded_terms() == ("dark mode",)


def test_delete_removes_record_and_rejects_subagents(manager: MemoryManager) -> None:
    record = manager.write(
        MemoryRecordDraft(target="project", content="Remove this memory."),
        actor=MemoryActor(kind="agent", session_id="ses_1"),
    )

    with pytest.raises(PermissionError, match="Subagents cannot delete memory"):
        manager.delete(record.id, actor=MemoryActor(kind="subagent", run_id="run_1"))

    manager.delete(record.id, actor=MemoryActor(kind="agent", session_id="ses_1"))

    assert manager.search("Remove this memory") == []


def test_get_status_returns_system_info(manager: MemoryManager) -> None:
    manager.write(
        MemoryRecordDraft(target="project", content="Status preview content."),
        actor=MemoryActor(kind="agent", session_id="ses_1"),
    )

    info = manager.get_status(actor=MemoryActor(kind="subagent", run_id="run_1"))

    assert info.readable_targets == ["user", "project"]
    assert info.writable_targets == ["project"]
    assert info.memory_file_count == 1
    assert info.recent_writes[0].preview == "Status preview content."
```

- [ ] **Step 2: Update audit event tests**

Replace `tests/test_memory_audit.py` with:

```python
from bourbon.audit.events import EventType


def test_memory_event_types_exist() -> None:
    assert EventType.MEMORY_WRITE == "memory_write"
    assert EventType.MEMORY_SEARCH == "memory_search"
    assert EventType.MEMORY_DELETE == "memory_delete"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_memory_manager.py tests/test_memory_audit.py -q
```

Expected: FAIL because manager still exposes lifecycle/cue metadata behavior and `MEMORY_DELETE` is not defined.

- [ ] **Step 4: Update audit event types**

In `src/bourbon/audit/events.py`, replace memory event values with:

```python
    MEMORY_WRITE = "memory_write"
    MEMORY_SEARCH = "memory_search"
    MEMORY_DELETE = "memory_delete"
```

- [ ] **Step 5: Replace manager with minimal orchestration**

Replace `src/bourbon/memory/manager.py` with:

```python
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
            index_at_capacity = len([line for line in index_path.read_text(encoding="utf-8").splitlines() if line]) >= 200
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
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/test_memory_manager.py tests/test_memory_audit.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/bourbon/memory/manager.py src/bourbon/audit/events.py tests/test_memory_manager.py tests/test_memory_audit.py
git commit -m "refactor(memory): simplify manager and audit"
```

---

### Task 4: Tool Surface And Prompt Guidance

**Files:**
- Modify: `src/bourbon/tools/memory.py`
- Modify: `src/bourbon/prompt/sections.py`
- Test: `tests/test_memory_tools.py`
- Test: `tests/test_agent_error_policy.py`

- [ ] **Step 1: Replace memory tool tests**

Replace `tests/test_memory_tools.py` with:

```python
import json
from pathlib import Path

from bourbon.tools import ToolContext, _ensure_imports, get_registry


def test_memory_tools_registered() -> None:
    _ensure_imports()
    registry = get_registry()
    names = [tool.name for tool in registry.list_tools()]
    assert "memory_search" in names
    assert "memory_write" in names
    assert "memory_delete" in names
    assert "memory_status" in names
    assert "memory_promote" not in names
    assert "memory_archive" not in names


def test_memory_write_tool_schema() -> None:
    _ensure_imports()
    tool = get_registry().get_tool("MemoryWrite")
    assert tool is not None
    schema = tool.input_schema
    assert schema["required"] == ["target", "content"]
    assert schema["properties"]["target"]["enum"] == ["user", "project"]
    assert "kind" not in schema["properties"]
    assert "scope" not in schema["properties"]
    assert "source" not in schema["properties"]


def test_memory_search_tool_schema() -> None:
    _ensure_imports()
    tool = get_registry().get_tool("MemorySearch")
    assert tool is not None
    schema = tool.input_schema
    assert schema["required"] == ["query"]
    assert schema["properties"]["target"]["enum"] == ["user", "project"]
    assert schema["properties"]["debug_terms"]["type"] == "boolean"
    assert "status" not in schema["properties"]
    assert "kind" not in schema["properties"]
    assert "scope" not in schema["properties"]


def test_memory_search_passes_target_filter_and_debug_terms() -> None:
    from bourbon.tools.memory import memory_search

    class _FakeMemoryManager:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def search(self, query: str, **kwargs: object) -> list[object]:
            self.calls.append({"query": query, **kwargs})
            return []

        def get_last_expanded_terms(self) -> tuple[str, ...]:
            return ("dark mode",)

    manager = _FakeMemoryManager()
    ctx = ToolContext(workdir=Path("/tmp"), memory_manager=manager)

    result = json.loads(memory_search(query="dark mode", target="project", debug_terms=True, ctx=ctx))

    assert result == {"results": [], "expanded_terms": ["dark mode"]}
    assert manager.calls == [{"query": "dark mode", "target": "project", "limit": None}]


def test_memory_write_uses_target_and_content() -> None:
    from bourbon.memory.models import MemoryRecord
    from bourbon.tools.memory import memory_write
    from datetime import UTC, datetime

    class _FakeMemoryManager:
        def write(self, draft: object, *, actor: object) -> MemoryRecord:
            self.draft = draft
            self.actor = actor
            return MemoryRecord(
                id="mem_abc12345",
                target="project",
                content="Prefer append-only memory records.",
                created_at=datetime(2026, 5, 6, tzinfo=UTC),
            )

    manager = _FakeMemoryManager()
    ctx = ToolContext(workdir=Path("/tmp"), memory_manager=manager)

    result = json.loads(
        memory_write(
            target="project",
            content="Prefer append-only memory records.",
            ctx=ctx,
        )
    )

    assert result == {
        "id": "mem_abc12345",
        "target": "project",
        "status": "written",
        "file": "mem_abc12345.md",
    }
    assert manager.draft.target == "project"
    assert manager.draft.content == "Prefer append-only memory records."


def test_memory_delete_calls_manager() -> None:
    from bourbon.tools.memory import memory_delete

    class _FakeMemoryManager:
        def delete(self, memory_id: str, *, actor: object) -> None:
            self.memory_id = memory_id
            self.actor = actor

    manager = _FakeMemoryManager()
    ctx = ToolContext(workdir=Path("/tmp"), memory_manager=manager)

    result = json.loads(memory_delete(memory_id="mem_abc12345", ctx=ctx))

    assert result == {"id": "mem_abc12345", "status": "deleted"}
    assert manager.memory_id == "mem_abc12345"


def test_memory_status_uses_targets_and_recent_previews() -> None:
    from datetime import UTC, datetime
    from bourbon.memory.models import MemorySystemInfo, RecentWriteSummary
    from bourbon.tools.memory import memory_status

    class _FakeMemoryManager:
        def get_status(self, *, actor: object) -> MemorySystemInfo:
            return MemorySystemInfo(
                readable_targets=("user", "project"),
                writable_targets=("project",),
                recent_writes=(
                    RecentWriteSummary(
                        id="mem_abc12345",
                        target="project",
                        preview="Prefer append-only memory records.",
                        created_at=datetime(2026, 5, 6, tzinfo=UTC),
                    ),
                ),
                index_at_capacity=False,
                memory_file_count=1,
            )

    ctx = ToolContext(workdir=Path("/tmp"), memory_manager=_FakeMemoryManager())

    result = json.loads(memory_status(ctx=ctx))

    assert result["readable_targets"] == ["user", "project"]
    assert result["writable_targets"] == ["project"]
    assert result["recent_writes"][0]["preview"] == "Prefer append-only memory records."


def test_memory_tools_return_error_when_disabled() -> None:
    from bourbon.tools.memory import memory_delete, memory_search, memory_status, memory_write

    ctx = ToolContext(workdir=Path("/tmp"))

    assert "error" in json.loads(memory_search(query="test", ctx=ctx))
    assert "error" in json.loads(memory_write(target="project", content="test", ctx=ctx))
    assert "error" in json.loads(memory_delete(memory_id="mem_abc12345", ctx=ctx))
    assert "error" in json.loads(memory_status(ctx=ctx))
```

- [ ] **Step 2: Update prompt policy tests**

In `tests/test_agent_error_policy.py`, replace `test_memory_write_operations_rule_exists` with:

```python
    def test_memory_write_operations_rule_exists(self, mock_agent):
        """System prompt must tell the agent not to bash-verify memory writes."""
        prompt = mock_agent.system_prompt
        assert "memory_write" in prompt
        assert "memory_delete" in prompt
        assert "memory_promote" not in prompt
        assert "memory_archive" not in prompt
        assert "NOT observable in the current session" in prompt
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_memory_tools.py tests/test_agent_error_policy.py::TestAgentErrorPolicy::test_memory_write_operations_rule_exists -q
```

Expected: FAIL because old tools and old prompt guidance still exist.

- [ ] **Step 4: Replace `src/bourbon/tools/memory.py`**

Use a minimal tool module:

```python
"""Memory tools."""

from __future__ import annotations

import json
from typing import Any

from bourbon.tools import RiskLevel, ToolContext, register_tool


def _json_output(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def _disabled() -> str:
    return _json_output({"error": "Memory system is not enabled"})


@register_tool(
    name="memory_search",
    aliases=["MemorySearch"],
    description="Search stored memory records by keyword.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query keywords"},
            "target": {
                "type": "string",
                "enum": ["user", "project"],
                "description": "Optional target filter",
            },
            "limit": {"type": "integer", "default": 8, "description": "Maximum results"},
            "debug_terms": {
                "type": "boolean",
                "default": False,
                "description": "Include expanded query terms used for search",
            },
        },
        "required": ["query"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    required_capabilities=["file_read"],
)
def memory_search(query: str, *, ctx: ToolContext, **kwargs: Any) -> str:
    if ctx.memory_manager is None:
        return _disabled()
    results = ctx.memory_manager.search(
        query,
        target=kwargs.get("target"),
        limit=kwargs.get("limit"),
    )
    payload: dict[str, Any] = {
        "results": [
            {
                "id": result.id,
                "target": result.target,
                "snippet": result.snippet,
                "why_matched": result.why_matched,
            }
            for result in results
        ]
    }
    if kwargs.get("debug_terms"):
        get_terms = getattr(ctx.memory_manager, "get_last_expanded_terms", None)
        if callable(get_terms):
            payload["expanded_terms"] = list(get_terms())
    return _json_output(payload)


@register_tool(
    name="memory_write",
    aliases=["MemoryWrite"],
    description=(
        "Write a memory record for future recall. Use target='user' for durable user "
        "preferences and target='project' for repository decisions, files, workflows, "
        "and references. Do not write ephemeral task state to memory."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "enum": ["user", "project"],
                "description": "Memory target",
            },
            "content": {"type": "string", "description": "Memory content"},
        },
        "required": ["target", "content"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
def memory_write(target: str, content: str, *, ctx: ToolContext, **kwargs: Any) -> str:
    del kwargs
    if ctx.memory_manager is None:
        return _disabled()
    from bourbon.memory.models import MemoryActor, MemoryRecordDraft, validate_memory_target

    try:
        draft = MemoryRecordDraft(target=validate_memory_target(target), content=content)
        actor = ctx.memory_actor or MemoryActor(kind="agent")
        record = ctx.memory_manager.write(draft, actor=actor)
    except (PermissionError, RuntimeError, ValueError) as exc:
        return _json_output({"error": str(exc)})
    return _json_output(
        {
            "id": record.id,
            "target": record.target,
            "status": "written",
            "file": f"{record.id}.md",
        }
    )


@register_tool(
    name="memory_delete",
    aliases=["MemoryDelete"],
    description="Delete a stored memory record by id.",
    input_schema={
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "description": "ID of the memory record to delete"},
        },
        "required": ["memory_id"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
def memory_delete(memory_id: str, *, ctx: ToolContext, **kwargs: Any) -> str:
    del kwargs
    if ctx.memory_manager is None:
        return _disabled()
    from bourbon.memory.models import MemoryActor

    try:
        actor = ctx.memory_actor or MemoryActor(kind="agent")
        ctx.memory_manager.delete(memory_id, actor=actor)
    except (KeyError, PermissionError) as exc:
        return _json_output({"error": str(exc)})
    return _json_output({"id": memory_id, "status": "deleted"})


@register_tool(
    name="memory_status",
    aliases=["MemoryStatus"],
    description="Return current memory system status and recent writes.",
    input_schema={"type": "object", "properties": {}},
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    required_capabilities=["file_read"],
)
def memory_status(*, ctx: ToolContext, **kwargs: Any) -> str:
    del kwargs
    if ctx.memory_manager is None:
        return _disabled()
    from bourbon.memory.models import MemoryActor

    actor = ctx.memory_actor or MemoryActor(kind="agent")
    status = ctx.memory_manager.get_status(actor=actor)
    return _json_output(
        {
            "readable_targets": status.readable_targets,
            "writable_targets": status.writable_targets,
            "index_at_capacity": status.index_at_capacity,
            "memory_file_count": status.memory_file_count,
            "recent_writes": [
                {
                    "id": write.id,
                    "target": write.target,
                    "preview": write.preview,
                }
                for write in status.recent_writes
            ],
        }
    )
```

- [ ] **Step 5: Update prompt guidance**

In `src/bourbon/prompt/sections.py`, replace the memory paragraph inside `TOOL_RESULT_TRUST` with:

```python
        "- Memory write/delete operations (memory_write, memory_delete) "
        "modify on-disk state that is NOT observable in the current session. "
        "Treat a success status as conclusive. Do NOT use Bash/Read/find to "
        "inspect USER.md, MEMORY.md, or memory files. If you need to re-query "
        "memory state, call memory_search with the relevant target filter.\n"
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/test_memory_tools.py tests/test_agent_error_policy.py::TestAgentErrorPolicy::test_memory_write_operations_rule_exists -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/bourbon/tools/memory.py src/bourbon/prompt/sections.py tests/test_memory_tools.py tests/test_agent_error_policy.py
git commit -m "refactor(memory): simplify tool surface"
```

---

### Task 5: Remove Compact Flush, Cue Runtime Context, And USER.md Managed Blocks

**Files:**
- Modify: `src/bourbon/agent.py`
- Modify: `src/bourbon/tools/__init__.py`
- Modify: `src/bourbon/memory/files.py`
- Delete: `src/bourbon/memory/compact.py`
- Delete: `scripts/backfill_memory_cues.py`
- Test: `tests/test_memory_agent_integration.py`
- Test: `tests/test_memory_files.py`
- Delete: `tests/test_memory_compact.py`
- Delete: `tests/test_memory_cue_runtime.py`
- Delete: `tests/test_memory_cue_backfill.py`
- Delete: `tests/test_memory_cue_backfill_script.py`
- Delete: `tests/test_memory_phase2.py`

- [ ] **Step 1: Update agent integration tests**

In `tests/test_memory_agent_integration.py`, remove tests that assert `cue_runtime_context_factory` exists and tests that assert `flush_before_compact` is called. Add this test:

```python
def test_agent_tool_context_has_memory_actor_without_cue_runtime_context(tmp_path: Path) -> None:
    config = Config()
    config.memory.enabled = True
    config.memory.storage_dir = str(tmp_path / "memory")
    agent = Agent(config=config, workdir=tmp_path)

    ctx = agent._make_tool_context()

    assert ctx.memory_manager is agent._memory_manager
    assert ctx.memory_actor is not None
    assert ctx.memory_actor.kind == "agent"
    assert not hasattr(ctx, "cue_runtime_context_factory")
```

- [ ] **Step 2: Replace memory files tests with anchor/merge-only coverage**

Replace `tests/test_memory_files.py` with tests for `read_file_anchor`, `merge_user_md`, and `render_merged_user_md_for_prompt` only:

```python
"""Tests for memory prompt anchor file helpers."""

from __future__ import annotations

from pathlib import Path

from bourbon.memory.files import merge_user_md, read_file_anchor, render_merged_user_md_for_prompt


def test_read_file_anchor_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert read_file_anchor(tmp_path / "missing.md", token_limit=100) == ""


def test_read_file_anchor_truncates_to_token_budget(tmp_path: Path) -> None:
    path = tmp_path / "MEMORY.md"
    path.write_text("x" * 1000, encoding="utf-8")

    text = read_file_anchor(path, token_limit=10)

    assert "[... truncated to token limit ...]" in text


def test_merge_user_md_prefers_project_preamble(tmp_path: Path) -> None:
    global_path = tmp_path / "global_USER.md"
    project_path = tmp_path / "USER.md"
    global_path.write_text("Global preference\n", encoding="utf-8")
    project_path.write_text("Project preference\n", encoding="utf-8")

    assert merge_user_md(global_path, project_path) == "Project preference\n"


def test_render_merged_user_md_for_prompt_uses_merge_and_budget(tmp_path: Path) -> None:
    global_path = tmp_path / "global_USER.md"
    project_path = tmp_path / "USER.md"
    global_path.write_text("# Style\n\nUse concise answers.\n", encoding="utf-8")
    project_path.write_text("# Style\n\nUse Chinese for this repo.\n", encoding="utf-8")

    rendered = render_merged_user_md_for_prompt(global_path, project_path, token_limit=100)

    assert "Use Chinese for this repo." in rendered
    assert "Use concise answers." not in rendered
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_memory_agent_integration.py tests/test_memory_files.py -q
```

Expected: FAIL because agent/tool context and files helpers still expose old cue runtime and managed-block behavior.

- [ ] **Step 4: Remove cue runtime context from `ToolContext`**

`ToolContext.memory_actor` already exists and must stay. In `src/bourbon/tools/__init__.py`, remove only this field from `ToolContext`:

```python
cue_runtime_context_factory: Callable[[], Any] | None = None
```

Also remove the now-unused `Callable` import if it is only used by that field.

- [ ] **Step 5: Remove compact flush and cue runtime methods from `Agent`**

In `src/bourbon/agent.py`, delete the method blocks named `_make_cue_runtime_context`, `_serialize_message_for_memory_flush`, `_compactable_messages_for_flush`, and `_maybe_flush_memory_before_compact`.

In `_make_tool_context`, remove the `cue_runtime_context_factory` keyword argument.

Search for `_maybe_flush_memory_before_compact()` callers in `agent.py` and remove those calls. The compact flow must continue without memory flushing.

- [ ] **Step 6: Reduce `memory/files.py` to anchor and USER.md merge helpers**

Remove managed preference block helpers and imports tied to `MemoryRecord` and `_record_to_filename`. Keep:

```python
read_file_anchor(path: Path, token_limit: int) -> str
merge_user_md(global_path: Path | None, project_path: Path | None) -> str
render_merged_user_md_for_prompt(global_path: Path | None, project_path: Path | None, token_limit: int) -> str
```

`render_merged_user_md_for_prompt` should simply return:

```python
return _truncate_to_tokens(merge_user_md(global_path, project_path), token_limit)
```

- [ ] **Step 7: Delete obsolete compact/backfill files and tests**

Run:

```bash
git rm src/bourbon/memory/compact.py scripts/backfill_memory_cues.py
git rm tests/test_memory_compact.py tests/test_memory_cue_runtime.py tests/test_memory_cue_backfill.py tests/test_memory_cue_backfill_script.py tests/test_memory_phase2.py
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
uv run pytest tests/test_memory_agent_integration.py tests/test_memory_files.py tests/test_tools_registry.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```bash
git add src/bourbon/agent.py src/bourbon/tools/__init__.py src/bourbon/memory/files.py tests/test_memory_agent_integration.py tests/test_memory_files.py
git add -u src/bourbon/memory/compact.py scripts/backfill_memory_cues.py tests/test_memory_compact.py tests/test_memory_cue_runtime.py tests/test_memory_cue_backfill.py tests/test_memory_cue_backfill_script.py tests/test_memory_phase2.py
git commit -m "refactor(memory): remove compact and managed lifecycle paths"
```

---

### Task 6: Minimal Retrieval Eval And Obsolete Test Removal

**Files:**
- Delete: `tests/test_memory_cue_models.py`
- Delete: `tests/test_memory_cue_engine.py`
- Delete: `tests/test_memory_cue_query.py`
- Delete: `tests/test_memory_cue_eval.py`
- Modify: `tests/test_memory_e2e.py`
- Modify: `tests/test_memory_prompt.py`
- Create: `evals/memory_retrieval_provider.py`
- Delete: `evals/memory_cue_retrieval_provider.py`
- Create: `evals/fixtures/memory_retrieval/retrieval-smoke.json`
- Delete: `evals/fixtures/memory_cues/retrieval-smoke.json`
- Create: `evals/cases/memory-retrieval.yaml`
- Delete: `evals/cases/memory-cue-retrieval.yaml`
- Modify: `promptfooconfig.yaml`

- [ ] **Step 1: Delete obsolete cue model/query/eval tests**

Run:

```bash
git rm tests/test_memory_cue_models.py tests/test_memory_cue_engine.py tests/test_memory_cue_query.py tests/test_memory_cue_eval.py
```

- [ ] **Step 2: Replace memory e2e test**

Replace `tests/test_memory_e2e.py` with:

```python
"""End-to-end tests for minimal memory."""

from __future__ import annotations

from bourbon.config import MemoryConfig
from bourbon.memory.manager import MemoryManager
from bourbon.memory.models import MemoryActor, MemoryRecordDraft


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[object] = []

    def record(self, event: object) -> None:
        self.events.append(event)


def test_memory_write_search_delete_e2e(tmp_path) -> None:
    manager = MemoryManager(
        config=MemoryConfig(storage_dir=str(tmp_path)),
        project_key="proj",
        workdir=tmp_path,
        audit=FakeAudit(),  # type: ignore[arg-type]
    )
    actor = MemoryActor(kind="agent", session_id="ses_1")

    record = manager.write(
        MemoryRecordDraft(target="project", content='Use `dark mode` for UI components.'),
        actor=actor,
    )

    assert manager.search("dark mode", target="project")[0].id == record.id

    manager.delete(record.id, actor=actor)

    assert manager.search("dark mode", target="project") == []
```

- [ ] **Step 3: Replace prompt memory test expectations**

In `tests/test_memory_prompt.py`, keep anchor rendering tests and update expected memory index text to the new format:

```python
assert "- [project] Prefer append-only memory records." in prompt
```

Remove assertions that rely on promoted USER.md blocks, `kind`, `status`, or `updated_at`.

- [ ] **Step 4: Replace eval provider with minimal retrieval metrics**

Create `evals/memory_retrieval_provider.py`:

```python
"""Promptfoo provider for deterministic minimal memory retrieval eval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bourbon.memory.cues import expand_query_terms, normalize_cues


def _score_record(record: dict[str, Any], terms: tuple[str, ...], *, use_cues: bool) -> int:
    haystack = str(record["content"]).casefold()
    if use_cues:
        cues = normalize_cues(record.get("cues", []))
        haystack += "\n" + "\n".join(cues).casefold()
    return sum(1 for term in terms if term.casefold() in haystack)


def _rank(records: list[dict[str, Any]], query: str, *, use_cues: bool, expand_query: bool) -> list[str]:
    terms = expand_query_terms(query) if expand_query else (query,)
    scored = [
        (_score_record(record, terms, use_cues=use_cues), str(record["id"]))
        for record in records
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [record_id for score, record_id in scored if score > 0]


def _recall_at(ranked_ids: list[str], expected_id: str, k: int) -> float:
    return 1.0 if expected_id in ranked_ids[:k] else 0.0


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del prompt, options
    vars_data = context.get("vars", {})
    fixture_path = Path("evals/fixtures") / str(vars_data["fixture"])
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    records = list(data["records"])
    cases = list(data["cases"])

    metrics: dict[str, dict[str, float]] = {}
    variants = {
        "content_only": {"use_cues": False, "expand_query": False},
        "content_plus_cues": {"use_cues": True, "expand_query": False},
        "expanded_query_plus_cues": {"use_cues": True, "expand_query": True},
    }
    for name, settings in variants.items():
        recalls = []
        for case in cases:
            ranked = _rank(
                records,
                str(case["query"]),
                use_cues=bool(settings["use_cues"]),
                expand_query=bool(settings["expand_query"]),
            )
            recalls.append(_recall_at(ranked, str(case["expected_id"]), 3))
        metrics[name] = {"recall_at_3": sum(recalls) / len(recalls)}

    output = {
        "metrics": metrics,
        "thresholds": {
            "expanded_query_plus_cues_recall_at_3_min": 0.8,
        },
    }
    return {"output": json.dumps(output)}
```

- [ ] **Step 5: Replace memory eval fixture**

Create `evals/fixtures/memory_retrieval/retrieval-smoke.json`:

```json
{
  "records": [
    {
      "id": "mem_dark_mode",
      "target": "user",
      "content": "User prefers dark UI components.",
      "cues": ["dark mode", "ui preference"]
    },
    {
      "id": "mem_append_only",
      "target": "project",
      "content": "Prefer append-only memory records.",
      "cues": ["minimal memory model", "record immutability"]
    },
    {
      "id": "mem_no_session",
      "target": "project",
      "content": "Temporary session facts stay in active session state.",
      "cues": ["no session memory", "target user project"]
    },
    {
      "id": "mem_audit",
      "target": "project",
      "content": "memory_write must emit an audit event.",
      "cues": ["memory audit", "required audit"]
    },
    {
      "id": "mem_index",
      "target": "project",
      "content": "MEMORY.md is rebuilt after every write and delete.",
      "cues": ["index rebuild", "memory delete"]
    }
  ],
  "cases": [
    {
      "query": "where is `dark mode` preference",
      "expected_id": "mem_dark_mode"
    },
    {
      "query": "append-only memory",
      "expected_id": "mem_append_only"
    },
    {
      "query": "`no session memory` decision",
      "expected_id": "mem_no_session"
    },
    {
      "query": "`memory audit` requirement",
      "expected_id": "mem_audit"
    },
    {
      "query": "`index rebuild` on delete",
      "expected_id": "mem_index"
    }
  ]
}
```

- [ ] **Step 6: Update promptfoo memory eval assertions**

Create `evals/cases/memory-retrieval.yaml`:

```yaml
- description: "Memory Retrieval: minimal content and cue smoke"
  provider: python:evals/memory_retrieval_provider.py
  vars:
    case_id: "memory-retrieval-smoke"
    fixture: "memory_retrieval/retrieval-smoke.json"
    prompt: "Run deterministic minimal memory retrieval smoke."
  assert:
    - type: javascript
      metric: "memory_retrieval_recall_at_3"
      value: |
        const data = JSON.parse(output);
        const actual = data.metrics.expanded_query_plus_cues.recall_at_3;
        const min = data.thresholds.expanded_query_plus_cues_recall_at_3_min;
        const pass = actual >= min;
        return { pass, reason: `Recall@3 ${actual} >= ${min}` };
  metadata:
    category: "memory-retrieval"
    legacy_case_id: "memory-retrieval-smoke"
```

In `promptfooconfig.yaml`, replace the memory provider entry with:

```yaml
  - id: python:evals/memory_retrieval_provider.py
    label: memory-retrieval
    config:
      pythonExecutable: .venv/bin/python
```

Also replace the test file entry:

```yaml
  - file://evals/cases/memory-retrieval.yaml
```

Delete the old cue-named eval files:

```bash
git rm evals/memory_cue_retrieval_provider.py evals/fixtures/memory_cues/retrieval-smoke.json evals/cases/memory-cue-retrieval.yaml
```

- [ ] **Step 7: Run focused tests and provider smoke**

Run:

```bash
uv run pytest tests/test_memory_e2e.py tests/test_memory_prompt.py -q
uv run python -c "from evals.memory_retrieval_provider import call_api; print(call_api('', {}, {'vars': {'fixture': 'memory_retrieval/retrieval-smoke.json'}})['output'])"
```

Expected: tests PASS and the provider command prints JSON with `expanded_query_plus_cues`.

- [ ] **Step 8: Commit**

Run:

```bash
git add tests/test_memory_e2e.py tests/test_memory_prompt.py evals/memory_retrieval_provider.py evals/fixtures/memory_retrieval/retrieval-smoke.json evals/cases/memory-retrieval.yaml promptfooconfig.yaml
git add -u evals/memory_cue_retrieval_provider.py evals/fixtures/memory_cues/retrieval-smoke.json evals/cases/memory-cue-retrieval.yaml
git add -u tests/test_memory_cue_models.py tests/test_memory_cue_engine.py tests/test_memory_cue_query.py tests/test_memory_cue_eval.py
git commit -m "refactor(memory): simplify retrieval evals"
```

---

### Task 7: Global Cleanup And Verification

**Files:**
- Modify any remaining imports or tests surfaced by the commands in this task.
- Test: full memory test set and static checks.

- [ ] **Step 1: Search for removed symbols**

Run:

```bash
rg -n "MemoryKind|MemoryScope|MemorySource|MemoryStatus|MemoryStatusInfo|SourceRef|actor_to_created_by|cue_metadata|QueryCue|MemoryConcept|CueKind|CueSource|CueGenerationStatus|CueQualityFlag|DomainConcept|memory_promote|memory_archive|flush_before_compact|auto_flush_on_compact|cue_runtime_context_factory|backfill_memory_cues|memory_cue_retrieval|memory-cue-retrieval|memory_cues" src tests evals scripts
```

Expected: no matches, except references inside historical design/spec/plan docs if the command is intentionally expanded to `docs`.

- [ ] **Step 2: Run memory-focused tests**

Run:

```bash
uv run pytest tests/test_memory_models.py tests/test_memory_policy.py tests/test_memory_config.py tests/test_memory_cues.py tests/test_memory_store.py tests/test_memory_manager.py tests/test_memory_tools.py tests/test_memory_files.py tests/test_memory_e2e.py tests/test_memory_prompt.py tests/test_memory_agent_integration.py tests/test_memory_audit.py -q
```

Expected: PASS.

- [ ] **Step 3: Run prompt and registry tests touched by tool names**

Run:

```bash
uv run pytest tests/test_agent_error_policy.py tests/test_tools_registry.py tests/test_agent_tool_discovery.py tests/test_agent_system_prompt.py -q
```

Expected: PASS.

- [ ] **Step 4: Run static checks**

Run:

```bash
uv run ruff check src tests evals
uv run mypy src
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit final cleanup**

If any remaining import cleanup or test adjustment was needed, commit it:

```bash
git add src tests evals promptfooconfig.yaml
git commit -m "chore(memory): remove minimal model leftovers"
```

If Step 1 through Step 5 passed without additional file changes, do not create an empty commit.
