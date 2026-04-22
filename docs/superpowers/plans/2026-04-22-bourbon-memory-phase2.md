# Bourbon Memory Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the promoted-memory lifecycle so stable cross-project user preferences can move from per-record memory files into managed global `USER.md`, remain searchable/archivable, and render ahead of handwritten `USER.md` content without duplicating `MEMORY.md` injection.

**Architecture:** Phase 2 extends the existing Phase 1 memory package instead of adding new modules. `MemoryStore` remains the source of truth for record files and `MEMORY.md`, `files.py` owns deterministic `USER.md` managed-block mutation and prompt rendering, `MemoryManager` coordinates policy + ordering + audit, and `tools/memory.py` stays a thin JSON adapter over manager methods.

**Tech Stack:** Python 3.11+, `dataclasses`, `pathlib`, `re`, `tempfile`, `yaml`, existing Bourbon tool registry, `pytest`.

**Spec:** `docs/superpowers/specs/2026-04-22-bourbon-memory-phase2-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `src/bourbon/memory/models.py` | Add `MemoryStatus.PROMOTED` |
| Modify | `src/bourbon/memory/files.py` | Parse/upsert/update managed `USER.md` blocks and render managed-first prompt content |
| Modify | `src/bourbon/memory/store.py` | Add `update_status()` and `_rebuild_index()`; keep promoted/stale/rejected out of `MEMORY.md` |
| Modify | `src/bourbon/memory/manager.py` | Add `promote()` / `archive()` orchestration and audit integration |
| Modify | `src/bourbon/memory/policy.py` | Add manager-level promote/archive permission checks |
| Modify | `src/bourbon/memory/prompt.py` | Switch USER.md render path to managed-first merge function |
| Modify | `src/bourbon/tools/memory.py` | Add `memory_promote` / `memory_archive`; expose `memory_search.status` |
| Modify | `src/bourbon/tools/__init__.py` | Ensure new memory tools are imported and registered |
| Modify | `tests/test_memory_models.py` | Cover `promoted` status enum |
| Modify | `tests/test_memory_files.py` | Cover managed block upsert/status/render behavior |
| Modify | `tests/test_memory_store.py` | Cover status transitions and index rebuild rules |
| Modify | `tests/test_memory_manager.py` | Cover promote/archive manager coordination |
| Modify | `tests/test_memory_policy.py` | Cover new promote/archive permission rules |
| Modify | `tests/test_memory_prompt.py` | Cover managed-first USER.md prompt rendering |
| Modify | `tests/test_memory_tools.py` | Cover new tools and `memory_search.status` schema |
| Create | `tests/test_memory_phase2.py` | End-to-end promoted-memory lifecycle and budget-overflow regressions |

---

### Task 1: Add Phase 2 Status Enum

**Files:**
- Modify: `src/bourbon/memory/models.py`
- Test: `tests/test_memory_models.py`

- [ ] **Step 1: Write the failing enum test**

```python
# tests/test_memory_models.py
def test_memory_status_values():
    assert {e.value for e in MemStatus} == {"active", "stale", "rejected", "promoted"}
```

- [ ] **Step 2: Run the targeted test and verify it fails**

Run: `pytest tests/test_memory_models.py -v`
Expected: FAIL because `promoted` does not exist yet.

- [ ] **Step 3: Add the new enum value**

```python
# src/bourbon/memory/models.py
class MemoryStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    REJECTED = "rejected"
    PROMOTED = "promoted"
```

- [ ] **Step 4: Run the targeted test and verify it passes**

Run: `pytest tests/test_memory_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit the enum groundwork**

```bash
git add src/bourbon/memory/models.py tests/test_memory_models.py
git commit -m "feat(memory): add promoted memory status"
```

---

### Task 2: Add Store Status Transitions and Search Surface

**Files:**
- Modify: `src/bourbon/memory/store.py`
- Modify: `src/bourbon/tools/memory.py`
- Test: `tests/test_memory_store.py`
- Test: `tests/test_memory_tools.py`

Per the current spec, this task also exposes `memory_search(status=...)` so promoted records remain discoverable for later archival and review after they leave `MEMORY.md`.

- [ ] **Step 1: Write failing tests for `update_status()`, `_rebuild_index()`, and `memory_search.status`**

```python
# tests/test_memory_store.py
from dataclasses import replace

def test_update_status_rewrites_frontmatter_and_returns_updated_record(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(id="mem_prom0001", name="Promote me")
    store.write_record(record)

    updated = store.update_status("mem_prom0001", MemStatus.PROMOTED)

    assert updated.status == MemStatus.PROMOTED
    assert updated.updated_at >= record.updated_at


def test_rebuild_index_excludes_promoted_stale_and_rejected(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    active = _make_record(id="mem_act0001", name="Active only")
    promoted = _make_record(id="mem_prm0001", name="Promoted", status=MemStatus.PROMOTED)
    stale = _make_record(id="mem_stl0001", name="Stale", status=MemStatus.STALE)
    rejected = _make_record(id="mem_rej0001", name="Rejected", status=MemStatus.REJECTED)

    for record in (active, promoted, stale, rejected):
        store.write_record(record)

    store._rebuild_index()

    text = (tmp_path / "MEMORY.md").read_text()
    assert "Active only" in text
    assert "Promoted" not in text
    assert "Stale" not in text
    assert "Rejected" not in text
```

```python
# tests/test_memory_tools.py
def test_memory_search_tool_schema() -> None:
    _ensure_imports()
    registry = get_registry()
    tool = registry.get_tool("MemorySearch")
    assert tool is not None
    schema = tool.input_schema
    assert "query" in schema["properties"]
    assert "status" in schema["properties"]
```

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run: `pytest tests/test_memory_store.py tests/test_memory_tools.py -v`
Expected: FAIL because `update_status()` / `_rebuild_index()` are missing and the tool schema has no `status` property.

- [ ] **Step 3: Implement status rewrites, index rebuild, and search schema plumbing**

```python
# src/bourbon/memory/store.py
def update_status(self, memory_id: str, status: MemoryStatus) -> MemoryRecord:
    record = self.read_record(memory_id)
    if record is None:
        raise KeyError(f"Unknown memory id: {memory_id}")

    updated = replace(
        record,
        status=status,
        updated_at=datetime.now(record.updated_at.tzinfo),
    )
    self.write_record(updated)
    self._rebuild_index()
    return updated


def _rebuild_index(self) -> bool:
    index_path = self.memory_dir / "MEMORY.md"
    active_records = sorted(
        self.list_records(status=["active"]),
        key=lambda record: record.updated_at,
        reverse=True,
    )[:200]
    content = "\n".join(
        f"- [{record.name}]({_record_to_filename(record)}) — {record.description}"
        for record in active_records
    )
    self._atomic_write(index_path, content + ("\n" if content else ""))
    return len(active_records) >= 200
```

```python
# src/bourbon/tools/memory.py
@register_tool(
    name="memory_search",
    ...,
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "scope": {...},
            "kind": {...},
            "status": {
                "type": "array",
                "items": {"type": "string", "enum": ["active", "promoted", "stale", "rejected"]},
                "description": "Optional status filter. Defaults to ['active'] when omitted.",
            },
            "limit": {"type": "integer", "default": 8},
        },
        "required": ["query"],
    },
)
def memory_search(query: str, *, ctx: ToolContext, **kwargs: Any) -> str:
    ...
    results = ctx.memory_manager.search(
        query,
        scope=kwargs.get("scope"),
        kind=kwargs.get("kind"),
        status=kwargs.get("status"),
        limit=kwargs.get("limit"),
    )
```

- [ ] **Step 4: Run the targeted tests and verify they pass**

Run: `pytest tests/test_memory_store.py tests/test_memory_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit the store/search plumbing**

```bash
git add src/bourbon/memory/store.py src/bourbon/tools/memory.py tests/test_memory_store.py tests/test_memory_tools.py
git commit -m "feat(memory): add status transitions and promoted search"
```

---

### Task 3: Implement Managed `USER.md` Mutation and Rendering

**Files:**
- Modify: `src/bourbon/memory/files.py`
- Modify: `src/bourbon/memory/prompt.py`
- Test: `tests/test_memory_files.py`
- Test: `tests/test_memory_prompt.py`

- [ ] **Step 1: Write failing tests for managed blocks and managed-first prompt rendering**

```python
# tests/test_memory_files.py
def test_upsert_managed_block_creates_file_and_section(tmp_path: Path) -> None:
    user_md = tmp_path / "USER.md"
    record = _make_record(id="mem_user0001", kind=MemoryKind.USER, scope=MemoryScope.USER)

    upsert_managed_block(user_md, record, note="stable preference")

    text = user_md.read_text()
    assert 'bourbon-managed:start section="preferences"' in text
    assert 'bourbon-memory:start id="mem_user0001"' in text
    assert "- status: promoted" in text


def test_update_managed_block_status_marks_stale_without_deleting_block(tmp_path: Path) -> None:
    user_md = tmp_path / "USER.md"
    record = _make_record(id="mem_user0002", kind=MemoryKind.USER, scope=MemoryScope.USER)
    upsert_managed_block(user_md, record)

    update_managed_block_status(user_md, "mem_user0002", "stale")

    text = user_md.read_text()
    assert "- status: stale" in text
    assert 'bourbon-memory:end id="mem_user0002"' in text


def test_upsert_managed_block_truncates_long_body_and_adds_backlink(tmp_path: Path) -> None:
    user_md = tmp_path / "USER.md"
    record = _make_record(
        id="mem_user0003",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        content="word " * 500,
    )

    upsert_managed_block(user_md, record)

    text = user_md.read_text()
    assert "Source:" in text
    assert len(text.split()) < 250


def test_corrupt_start_without_end_closes_at_eof(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    user_md = tmp_path / "USER.md"
    user_md.write_text('<!-- bourbon-managed:start section="preferences" -->\n### broken\n')
    record = _make_record(id="mem_user0004", kind=MemoryKind.USER, scope=MemoryScope.USER)

    upsert_managed_block(user_md, record)

    assert 'bourbon-memory:start id="mem_user0004"' in user_md.read_text()
    assert "warning" in caplog.text.lower()


def test_corrupt_end_without_start_ignores_orphan(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    user_md = tmp_path / "USER.md"
    user_md.write_text('orphan\n<!-- bourbon-managed:end section="preferences" -->\n')
    record = _make_record(id="mem_user0005", kind=MemoryKind.USER, scope=MemoryScope.USER)

    upsert_managed_block(user_md, record)

    assert 'bourbon-memory:start id="mem_user0005"' in user_md.read_text()
    assert "warning" in caplog.text.lower()
```

```python
# tests/test_memory_prompt.py
def test_memory_anchors_section_renders_promoted_blocks_before_handwritten_user_md(tmp_path: Path) -> None:
    global_user_md = tmp_path / "global" / "USER.md"
    global_user_md.parent.mkdir()
    global_user_md.write_text(
        "<!-- bourbon-managed:start section=\"preferences\" -->\n"
        "## Bourbon Managed Preferences\n\n"
        "<!-- bourbon-memory:start id=\"mem_1\" -->\n"
        "### User Preference: mem_1\n\n"
        "- status: promoted\n"
        "- kind: user\n"
        "- promoted_at: 2026-04-22T10:00:00Z\n\n"
        "Always use uv.\n"
        "<!-- bourbon-memory:end id=\"mem_1\" -->\n"
        "<!-- bourbon-managed:end section=\"preferences\" -->\n\n"
        "## Style\n\nEnglish.\n"
    )
    project_user_md = tmp_path / "USER.md"
    project_user_md.write_text("## Repo Overrides\n\nPrefer terse updates.\n")

    rendered = render_merged_user_md_for_prompt(
        global_path=global_user_md,
        project_path=project_user_md,
        token_limit=600,
    )

    assert rendered.index("Always use uv.") < rendered.index("Prefer terse updates.")
    assert "English." in rendered


def test_render_merged_user_md_for_prompt_prefers_newer_promotions_on_budget_overflow(tmp_path: Path) -> None:
    global_user_md = tmp_path / "global" / "USER.md"
    global_user_md.parent.mkdir()
    global_user_md.write_text(
        "<!-- bourbon-managed:start section=\"preferences\" -->\n"
        "## Bourbon Managed Preferences\n\n"
        "<!-- bourbon-memory:start id=\"mem_old\" -->\n"
        "### User Preference: mem_old\n\n"
        "- status: promoted\n"
        "- kind: user\n"
        "- promoted_at: 2026-04-21T10:00:00Z\n\n"
        "old preference " * 100 + "\n"
        "<!-- bourbon-memory:end id=\"mem_old\" -->\n"
        "<!-- bourbon-memory:start id=\"mem_new\" -->\n"
        "### User Preference: mem_new\n\n"
        "- status: promoted\n"
        "- kind: user\n"
        "- promoted_at: 2026-04-22T10:00:00Z\n\n"
        "new preference " * 100 + "\n"
        "<!-- bourbon-memory:end id=\"mem_new\" -->\n"
        "<!-- bourbon-managed:end section=\"preferences\" -->\n"
    )

    rendered = render_merged_user_md_for_prompt(
        global_path=global_user_md,
        project_path=None,
        token_limit=80,
    )

    assert "mem_new" in rendered
```

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run: `pytest tests/test_memory_files.py tests/test_memory_prompt.py -v`
Expected: FAIL because managed-block helpers and the managed-first renderer do not exist yet.

- [ ] **Step 3: Implement deterministic managed-block helpers and prompt rendering**

```python
# src/bourbon/memory/files.py
_MANAGED_START = '<!-- bourbon-managed:start section="preferences" -->'
_MANAGED_END = '<!-- bourbon-managed:end section="preferences" -->'
_BLOCK_RE = re.compile(
    r'<!-- bourbon-memory:start id="(?P<id>mem_[^"]+)" -->'
    r'(?P<body>.*?)'
    r'<!-- bourbon-memory:end id="(?P=id)" -->',
    re.DOTALL,
)


def upsert_managed_block(user_md_path: Path, record: MemoryRecord, note: str = "") -> None:
    text = _read_text(user_md_path)
    managed_section, outside = _split_managed_section(text)
    block = _render_managed_block(record, note=note)
    updated_section = _replace_or_append_block(managed_section, record.id, block)
    _atomic_write_text(user_md_path, _merge_user_text(outside, updated_section))


def update_managed_block_status(user_md_path: Path, memory_id: str, status: Literal["promoted", "stale", "rejected"]) -> None:
    text = _read_text(user_md_path)
    managed_section, outside = _split_managed_section(text)
    updated_section = _replace_status_line(managed_section, memory_id, status)
    _atomic_write_text(user_md_path, _merge_user_text(outside, updated_section))


def render_merged_user_md_for_prompt(global_path: Path | None, project_path: Path | None, token_limit: int) -> str:
    global_text = _read_text(global_path)
    managed_section, handwritten_global = _split_managed_section(global_text)
    promoted_blocks = sorted(
        _collect_promoted_blocks(managed_section),
        key=lambda block: block.promoted_at,
        reverse=True,
    )
    managed_budget = min(300, token_limit // 2) if promoted_blocks else 0
    managed_text = _truncate_to_tokens(_render_blocks(promoted_blocks), managed_budget)
    handwritten_text = merge_user_md_text(
        global_text=handwritten_global,
        project_text=_read_text(project_path),
    )
    handwritten_budget = token_limit - _estimate_tokens(managed_text)
    handwritten_rendered = _truncate_to_tokens(handwritten_text, handwritten_budget)
    return "\n\n".join(part for part in [managed_text, handwritten_rendered] if part).strip() + "\n"


def _render_managed_block(record: MemoryRecord, note: str = "") -> str:
    body = record.content
    if _estimate_tokens(body) > 150:
        source_path = f"~/.bourbon/projects/{{key}}/memory/{{filename}}"
        body = _truncate_to_tokens(body, 150) + f"\n\nSource: {source_path}"
    ...
```

```python
# src/bourbon/memory/files.py
def _split_managed_section(text: str) -> tuple[str, str]:
    # If start exists without end, treat EOF as the section boundary and log a warning.
    # If end exists without start, ignore the orphan marker, log a warning, and create a fresh section on write.
    ...
```

```python
# src/bourbon/memory/prompt.py
from bourbon.memory.files import read_file_anchor, render_merged_user_md_for_prompt

...
user_content = render_merged_user_md_for_prompt(
    global_path=Path("~/.bourbon/USER.md").expanduser(),
    project_path=ctx.workdir / "USER.md",
    token_limit=config.user_md_token_limit,
)
```

- [ ] **Step 4: Run the targeted tests and verify they pass**

Run: `pytest tests/test_memory_files.py tests/test_memory_prompt.py -v`
Expected: PASS

- [ ] **Step 5: Commit the managed `USER.md` layer**

```bash
git add src/bourbon/memory/files.py src/bourbon/memory/prompt.py tests/test_memory_files.py tests/test_memory_prompt.py
git commit -m "feat(memory): add managed user md promotion layer"
```

---

### Task 4: Implement Promote/Archive Policy and Manager Coordination

**Files:**
- Modify: `src/bourbon/memory/policy.py`
- Modify: `src/bourbon/memory/manager.py`
- Test: `tests/test_memory_policy.py`
- Test: `tests/test_memory_manager.py`

- [ ] **Step 1: Write failing tests for permission checks and manager ordering**

```python
# tests/test_memory_policy.py
from datetime import UTC, datetime

from bourbon.memory.models import MemoryRecord, MemorySource, MemoryStatus


def _policy_record(*, kind: MemoryKind, scope: MemoryScope) -> MemoryRecord:
    return MemoryRecord(
        id="mem_policy0001",
        name="Policy test",
        description="Policy test record",
        kind=kind,
        scope=scope,
        confidence=1.0,
        source=MemorySource.USER,
        status=MemoryStatus.ACTIVE,
        created_at=datetime(2026, 4, 22, tzinfo=UTC),
        updated_at=datetime(2026, 4, 22, tzinfo=UTC),
        created_by="user",
        content="content",
    )


def test_promote_permission_denies_subagent() -> None:
    actor = MemoryActor(kind="subagent", run_id="run_1", agent_type="explore")
    record = _policy_record(kind=MemoryKind.USER, scope=MemoryScope.USER)
    with pytest.raises(PermissionError):
        check_promote_permission(actor, record)


def test_promote_permission_rejects_non_user_scope() -> None:
    actor = MemoryActor(kind="agent")
    record = _policy_record(kind=MemoryKind.FEEDBACK, scope=MemoryScope.PROJECT)
    with pytest.raises(PermissionError):
        check_promote_permission(actor, record)
```

```python
# tests/test_memory_manager.py
def test_promote_happy_path_updates_user_md_and_store(
    manager: MemoryManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    actor = MemoryActor(kind="user")
    draft = MemoryRecordDraft(
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        content="Always use uv for Python work.",
        source=MemorySource.USER,
        name="Use uv",
        description="Cross-project Python tool preference",
    )
    record = manager.write(draft, actor=actor)

    updated = manager.promote(record.id, actor=actor, note="stable preference")

    assert updated.status == MemoryStatus.PROMOTED
    assert "Use uv" not in (manager.get_memory_dir() / "MEMORY.md").read_text()
    assert "- status: promoted" in (tmp_path / ".bourbon" / "USER.md").read_text()
```

```python
def test_archive_promoted_record_marks_block_stale(
    manager: MemoryManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    ...
    manager.archive(record.id, MemoryStatus.STALE, actor=actor, reason="temporary exception")
    user_md = tmp_path / ".bourbon" / "USER.md"
    assert "- status: stale" in user_md.read_text()
```

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run: `pytest tests/test_memory_policy.py tests/test_memory_manager.py -v`
Expected: FAIL because the permission helpers and manager methods do not exist yet.

- [ ] **Step 3: Implement promote/archive permissions and manager lifecycle**

```python
# src/bourbon/memory/policy.py
def check_promote_permission(actor: MemoryActor, record: MemoryRecord) -> None:
    if actor.kind == "subagent":
        raise PermissionError("Subagents cannot promote memory records")
    if record.kind not in {MemoryKind.USER, MemoryKind.FEEDBACK}:
        raise PermissionError(f"Cannot promote memory kind {record.kind}")
    if record.scope != MemoryScope.USER:
        raise PermissionError("Only user-scope records can be promoted")


def check_archive_permission(actor: MemoryActor, record: MemoryRecord) -> None:
    if actor.kind == "subagent":
        raise PermissionError("Subagents cannot archive memory records")
```

```python
# src/bourbon/memory/manager.py
def promote(self, memory_id: str, actor: MemoryActor, note: str = "") -> MemoryRecord:
    record = self._store.read_record(memory_id)
    if record is None:
        raise KeyError(f"Unknown memory id: {memory_id}")
    # Current spec requires scope=user and allows re-promote from stale.
    if record.status not in {MemoryStatus.ACTIVE, MemoryStatus.STALE}:
        raise ValueError(f"Cannot promote record with status {record.status}")
    check_promote_permission(actor, record)

    global_user_md = Path("~/.bourbon/USER.md").expanduser()
    upsert_managed_block(global_user_md, replace(record, status=MemoryStatus.PROMOTED), note=note)
    updated = self._store.update_status(memory_id, MemoryStatus.PROMOTED)
    self._record_audit(
        EventType.MEMORY_PROMOTE,
        tool_input_summary=record.name,
        memory_id=record.id,
        actor=actor_to_created_by(actor),
    )
    return updated


def archive(self, memory_id: str, status: MemoryStatus, actor: MemoryActor, reason: str = "") -> MemoryRecord:
    record = self._store.read_record(memory_id)
    if record is None:
        raise KeyError(f"Unknown memory id: {memory_id}")
    if status not in {MemoryStatus.STALE, MemoryStatus.REJECTED}:
        raise ValueError(f"Cannot archive record as {status}")
    check_archive_permission(actor, record)

    if record.status == MemoryStatus.PROMOTED:
        update_managed_block_status(Path("~/.bourbon/USER.md").expanduser(), memory_id, str(status))

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
```

- [ ] **Step 4: Run the targeted tests and verify they pass**

Run: `pytest tests/test_memory_policy.py tests/test_memory_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit the manager lifecycle**

```bash
git add src/bourbon/memory/policy.py src/bourbon/memory/manager.py tests/test_memory_policy.py tests/test_memory_manager.py
git commit -m "feat(memory): add promote and archive manager flows"
```

---

### Task 5: Add Tool Handlers, Registration, and Phase 2 Integration Tests

**Files:**
- Modify: `src/bourbon/tools/memory.py`
- Modify: `src/bourbon/tools/__init__.py`
- Modify: `tests/test_memory_tools.py`
- Create: `tests/test_memory_phase2.py`

- [ ] **Step 1: Write failing tool and end-to-end tests**

```python
# tests/test_memory_tools.py
def test_memory_tools_registered() -> None:
    _ensure_imports()
    registry = get_registry()
    tool_primary_names = [tool.name for tool in registry.list_tools()]
    assert "memory_promote" in tool_primary_names
    assert "memory_archive" in tool_primary_names


def test_memory_promote_tool_returns_error_when_disabled() -> None:
    from bourbon.tools.memory import memory_promote

    ctx = ToolContext(workdir=Path("/tmp"))
    result = json.loads(memory_promote(memory_id="mem_missing", ctx=ctx))
    assert "error" in result
```

```python
# tests/test_memory_phase2.py
def test_full_promote_archive_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    config = MemoryConfig(storage_dir=str(tmp_path / "store"))
    workdir = tmp_path / "project"
    workdir.mkdir()
    manager = MemoryManager(
        config=config,
        project_key="phase2-test-12345678",
        workdir=workdir,
        audit=None,
    )
    actor = MemoryActor(kind="user")

    record = manager.write(
        MemoryRecordDraft(
            kind=MemoryKind.USER,
            scope=MemoryScope.USER,
            content="Always use uv for Python operations.",
            source=MemorySource.USER,
            name="Use uv",
            description="Cross-project Python preference",
        ),
        actor=actor,
    )
    manager.promote(record.id, actor=actor, note="stable")

    promoted = manager.search("Always use uv", status=["promoted"])
    assert [result.id for result in promoted] == [record.id]

    manager.archive(record.id, MemoryStatus.REJECTED, actor=actor, reason="outdated")
    archived = manager.search("Always use uv", status=["rejected"])
    assert [result.id for result in archived] == [record.id]
    assert "- status: rejected" in (tmp_path / ".bourbon" / "USER.md").read_text()


def test_repromote_stale_record_reuses_managed_block_without_duplicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    ...
    manager.promote(record.id, actor=actor, note="stable")
    manager.archive(record.id, MemoryStatus.STALE, actor=actor, reason="temporary exception")
    manager.promote(record.id, actor=actor, note="restored")

    user_md = (tmp_path / ".bourbon" / "USER.md").read_text()
    assert user_md.count('bourbon-memory:start id="' + record.id + '"') == 1
    assert f"<!-- bourbon-memory:start id=\"{record.id}\" -->" in user_md
    assert "- status: promoted" in user_md
```

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run: `pytest tests/test_memory_tools.py tests/test_memory_phase2.py -v`
Expected: FAIL because the new tools are not registered and no end-to-end promote/archive flow exists yet.

- [ ] **Step 3: Implement the tool handlers and registration path**

```python
# src/bourbon/tools/memory.py
@register_tool(
    name="memory_promote",
    description=(
        "Promote an active or stale user/feedback memory with scope='user' to USER.md "
        "for strong behavioral enforcement. Call this when a user/feedback memory has "
        "proven stable across multiple turns, such as a tool preference, output format, "
        "or workflow rule the user consistently expects. After promotion, the record exits "
        "the MEMORY.md index and its managed block is rendered before freeform USER.md content."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "memory_id": {"type": "string"},
            "note": {"type": "string"},
        },
        "required": ["memory_id"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
def memory_promote(memory_id: str, *, ctx: ToolContext, **kwargs: Any) -> str:
    if ctx.memory_manager is None:
        return _disabled()
    actor = ctx.memory_actor or MemoryActor(kind="agent")
    try:
        record = ctx.memory_manager.promote(memory_id, actor=actor, note=kwargs.get("note", ""))
    except (KeyError, PermissionError, ValueError, OSError) as exc:
        return _json_output({"error": str(exc)})
    return _json_output({"id": record.id, "status": "promoted"})


@register_tool(
    name="memory_archive",
    description=(
        "Archive a memory record by marking it stale or rejected. If the record was previously "
        "promoted to USER.md, also update the managed block status so it is removed from injection. "
        "Use 'rejected' for incorrect or outdated facts; 'stale' for temporarily suspended preferences."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "memory_id": {"type": "string"},
            "status": {"type": "string", "enum": ["stale", "rejected"]},
            "reason": {"type": "string"},
        },
        "required": ["memory_id", "status"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
def memory_archive(memory_id: str, status: str, *, ctx: ToolContext, **kwargs: Any) -> str:
    if ctx.memory_manager is None:
        return _disabled()
    actor = ctx.memory_actor or MemoryActor(kind="agent")
    try:
        record = ctx.memory_manager.archive(
            memory_id,
            MemoryStatus(status),
            actor=actor,
            reason=kwargs.get("reason", ""),
        )
    except (KeyError, PermissionError, ValueError, OSError) as exc:
        return _json_output({"error": str(exc)})
    return _json_output({"id": record.id, "status": status})
```

```python
# src/bourbon/tools/__init__.py
def _ensure_imports() -> None:
    ...
    from bourbon.tools import memory  # noqa: F401
```

- [ ] **Step 4: Run the targeted tests and verify they pass**

Run: `pytest tests/test_memory_tools.py tests/test_memory_phase2.py -v`
Expected: PASS

- [ ] **Step 5: Commit the tool surface and integration coverage**

```bash
git add src/bourbon/tools/memory.py src/bourbon/tools/__init__.py tests/test_memory_tools.py tests/test_memory_phase2.py
git commit -m "feat(memory): add promote and archive tools"
```

---

### Task 6: Run the Full Memory Regression Suite

**Files:**
- Verify only: `tests/test_memory_models.py`
- Verify only: `tests/test_memory_audit.py`
- Verify only: `tests/test_memory_store.py`
- Verify only: `tests/test_memory_files.py`
- Verify only: `tests/test_memory_policy.py`
- Verify only: `tests/test_memory_manager.py`
- Verify only: `tests/test_memory_prompt.py`
- Verify only: `tests/test_memory_tools.py`
- Verify only: `tests/test_memory_phase2.py`

- [ ] **Step 1: Run the full targeted memory suite**

Run:

```bash
pytest \
  tests/test_memory_models.py \
  tests/test_memory_audit.py \
  tests/test_memory_store.py \
  tests/test_memory_files.py \
  tests/test_memory_policy.py \
  tests/test_memory_manager.py \
  tests/test_memory_prompt.py \
  tests/test_memory_tools.py \
  tests/test_memory_phase2.py -v
```

Expected: PASS

- [ ] **Step 2: Run lint on touched files**

Run:

```bash
ruff check src/bourbon/memory src/bourbon/tools tests/test_memory_*.py
```

Expected: PASS with no lint errors in touched files.

- [ ] **Step 3: Summarize remaining risk before merge**

```text
Confirm these before merge:
- Managed USER.md corruption fallback logs a warning and preserves recoverability.
- `memory_search(status=["promoted"])` works even when a promoted block is omitted from the prompt due to budget.
- Project-local USER.md does not suppress promoted global managed blocks.
```

- [ ] **Step 4: Create the final verification commit**

```bash
git add src/bourbon/memory src/bourbon/tools tests/test_memory_*.py
git commit -m "test(memory): verify phase2 promoted memory lifecycle"
```
