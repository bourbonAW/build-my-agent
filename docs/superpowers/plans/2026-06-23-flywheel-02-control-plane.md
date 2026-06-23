# Flywheel 02 — Control Plane (API + State Store) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Flywheel control plane: a FastAPI server backed by a file-first State Store with a SQLite index, an append-only audit log, idempotency enforcement, role-based authorization, the authoritative lifecycle enums, the `Baseline` object with publish/revert lineage, and the Score Bridge that writes scores to Langfuse idempotently.

**Architecture:** `flywheel/api/` holds the HTTP layer + persistence. Domain records are JSON files under `~/.flywheel/<project>/<collection>/<id>.json`; a SQLite index makes list/filter queries fast. Every mutation goes through an idempotency check and emits an `AuditEvent`. Synchronous FastAPI route handlers (`def`).

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, stdlib `sqlite3`, httpx (Score Bridge → Langfuse), pytest + FastAPI `TestClient`.

## Global Constraints

(See `2026-06-23-flywheel-00-index.md`.) Most relevant here:
- Authoritative lifecycle enums verbatim; `RegressionStatus` is **derived** from `ProposalState`.
- All mutations idempotent; duplicate returns the existing object. Keys per the index doc.
- All mutations return the updated object **and** an append-only audit event id.
- One `current` Baseline per project; publish supersedes; revert is a human-gated transition.
- Publish, rollback, post-publish revert, redaction-policy changes, and proposal approval require explicit role checks.
- Browser never receives Langfuse write credentials — score writes go only through the Score Bridge.

---

## File Structure

- Create: `flywheel/api/__init__.py`
- Create: `flywheel/api/lifecycle.py` — authoritative enums + derivation + legal-transition table
- Create: `flywheel/api/store.py` — `JsonRecordStore` (file + SQLite index)
- Create: `flywheel/api/audit.py` — `AuditLog` append-only
- Create: `flywheel/api/idempotency.py` — `IdempotencyStore`
- Create: `flywheel/api/auth.py` — `Role`, `Principal`, `require_role`
- Create: `flywheel/api/baselines.py` — `Baseline` record + `BaselineService` (publish/supersede/revert)
- Create: `flywheel/api/schemas.py` — pydantic request/response models
- Create: `flywheel/api/server.py` — FastAPI app, dependency wiring, routers
- Create: `flywheel/api/score_bridge.py` — idempotent Langfuse score writer
- Test: `flywheel/tests/api/` mirror

---

## Task 1: Authoritative lifecycle enums + derivation

**Files:**
- Create: `flywheel/api/lifecycle.py`
- Test: `flywheel/tests/api/test_lifecycle.py`

**Interfaces:**
- Produces:
  - `ProposalState`, `RegressionStatus`, `RegressionOutcome`, `RunState`, `JudgeState` as `Literal` aliases — exact values from Engine §12 / UI §12.
  - `derive_regression_status(state: ProposalState) -> RegressionStatus | None` — implements UI §12 derivation table; returns `None` where `regressionStatus` is omitted.
  - `PROPOSAL_TRANSITIONS: dict[ProposalState, frozenset[ProposalState]]` — legal transitions from Engine §12 lifecycle rules.
  - `assert_transition(frm: ProposalState, to: ProposalState) -> None` — raises `IllegalTransition` if not allowed.
  - `class IllegalTransition(ValueError)`.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/api/test_lifecycle.py
from typing import get_args
import pytest
from api.lifecycle import (
    ProposalState, derive_regression_status, assert_transition, IllegalTransition,
)


def test_proposal_state_has_all_authoritative_values():
    assert set(get_args(ProposalState)) == {
        "draft", "under_review", "rejected", "deferred", "approved",
        "handoff_ready", "implementing", "diff_review", "revising",
        "regression_running", "regression_review", "blocked_on_judge_recheck",
        "blocked_on_judge_migration", "baseline_stale", "validated",
        "rolled_back", "no_significant_change", "abandoned",
    }


def test_regression_status_derivation_table():
    assert derive_regression_status("draft") == "not_started"
    assert derive_regression_status("diff_review") == "not_started"
    assert derive_regression_status("regression_running") == "running"
    assert derive_regression_status("blocked_on_judge_recheck") == "waiting_for_judge_recheck"
    assert derive_regression_status("blocked_on_judge_migration") == "waiting_for_judge_migration"
    assert derive_regression_status("regression_review") == "ready_for_review"
    assert derive_regression_status("validated") == "complete"
    assert derive_regression_status("rolled_back") == "complete"
    assert derive_regression_status("baseline_stale") is None
    assert derive_regression_status("deferred") is None
    assert derive_regression_status("rejected") is None
    assert derive_regression_status("revising") is None


def test_legal_transition():
    assert_transition("under_review", "approved")  # no raise


def test_illegal_transition_raises():
    with pytest.raises(IllegalTransition):
        assert_transition("rejected", "approved")  # rejected is final
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_lifecycle.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.lifecycle'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/api/lifecycle.py
"""Authoritative lifecycle enums and transition rules (Engine §12, UI §12).

Single source of truth for DB rows, API payloads, engine jobs, and frontend types.
RegressionStatus is derived from ProposalState and never independently persisted.
"""
from __future__ import annotations

from typing import Literal

ProposalState = Literal[
    "draft", "under_review", "rejected", "deferred", "approved",
    "handoff_ready", "implementing", "diff_review", "revising",
    "regression_running", "regression_review", "blocked_on_judge_recheck",
    "blocked_on_judge_migration", "baseline_stale", "validated",
    "rolled_back", "no_significant_change", "abandoned",
]

RegressionStatus = Literal[
    "not_started", "running", "waiting_for_judge_recheck",
    "waiting_for_judge_migration", "ready_for_review", "complete",
]

RegressionOutcome = Literal[
    "published", "rolled_back", "no_significant_change", "revise",
    "abandoned", "judge_recheck_required", "judge_migration_required",
    "baseline_stale",
]

RunState = Literal[
    "idle", "collecting", "scored", "waiting_for_labels", "labels_synced",
    "manual_analysis_ready", "auto_analysis_ready", "analyzing",
    "clean_run", "needs_more_data", "under_review",
]

JudgeState = Literal[
    "draft", "calibrating", "validated",
    "validated_limited", "rejected", "recheck_required",
]
# NOTE: "locked_test" is a UI-only display abstraction (UI §12 TypeScript type).
# It is NOT a DB/API status — Engine §12 preamble: these enums are the single source of truth.


class IllegalTransition(ValueError):
    """Raised when a proposal state transition is not in the authoritative table."""


_NOT_STARTED: frozenset[str] = frozenset({
    "draft", "under_review", "approved",
    "handoff_ready", "implementing", "diff_review",
})
# "rejected", "deferred", "revising", "baseline_stale" -> return None per UI §12 derivation table
_COMPLETE: frozenset[str] = frozenset({
    "validated", "rolled_back", "no_significant_change", "abandoned",
})


def derive_regression_status(state: ProposalState) -> RegressionStatus | None:
    if state in _NOT_STARTED:
        return "not_started"
    if state == "regression_running":
        return "running"
    if state == "blocked_on_judge_recheck":
        return "waiting_for_judge_recheck"
    if state == "blocked_on_judge_migration":
        return "waiting_for_judge_migration"
    if state == "regression_review":
        return "ready_for_review"
    if state in _COMPLETE:
        return "complete"
    # baseline_stale -> omit (UI §12)
    return None


# Engine §12 "Lifecycle Rules"
PROPOSAL_TRANSITIONS: dict[ProposalState, frozenset[ProposalState]] = {
    "draft": frozenset({"under_review"}),
    "under_review": frozenset({"rejected", "deferred", "approved"}),
    "deferred": frozenset({"under_review"}),
    "rejected": frozenset(),  # final
    "approved": frozenset({"handoff_ready"}),
    "handoff_ready": frozenset({"implementing"}),
    "implementing": frozenset({"diff_review"}),
    "diff_review": frozenset({"revising", "abandoned", "regression_running"}),
    "revising": frozenset({"implementing"}),
    "regression_running": frozenset({"regression_review"}),
    "regression_review": frozenset({
        "validated", "rolled_back", "no_significant_change", "revising",
        "abandoned", "blocked_on_judge_recheck", "blocked_on_judge_migration",
        "baseline_stale",
    }),
    "blocked_on_judge_recheck": frozenset({"regression_running"}),
    "blocked_on_judge_migration": frozenset({"regression_review"}),
    "baseline_stale": frozenset({"under_review"}),  # requires rebase_proposal() first (plan 07); transition table allows it but validator enforces precondition
    "validated": frozenset(),  # terminal
    "rolled_back": frozenset({"revising", "abandoned"}),
    "no_significant_change": frozenset({"deferred", "abandoned"}),
    "abandoned": frozenset(),  # terminal
}


def assert_transition(frm: ProposalState, to: ProposalState) -> None:
    if to not in PROPOSAL_TRANSITIONS.get(frm, frozenset()):
        raise IllegalTransition(f"illegal proposal transition {frm} -> {to}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_lifecycle.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/api/lifecycle.py flywheel/tests/api/__init__.py flywheel/tests/api/test_lifecycle.py
git commit -m "feat(api): authoritative lifecycle enums and transition rules"
```

---

## Task 2: JsonRecordStore — file + SQLite index

**Files:**
- Create: `flywheel/api/store.py`
- Test: `flywheel/tests/api/test_store.py`

**Interfaces:**
- Produces:
  - `class JsonRecordStore` constructed with `root: Path`. Methods:
    - `put(collection: str, record_id: str, data: dict) -> dict` — writes `root/<collection>/<id>.json` (atomic temp+rename), upserts a row into the SQLite index `(collection, id, project, created_at, json)`.
    - `get(collection: str, record_id: str) -> dict | None`.
    - `list(collection: str, *, project: str | None = None, where: dict | None = None) -> list[dict]` — filters via the index on `project` plus optional equality `where` on top-level JSON keys, newest first.
  - Crash-safety: file written before index row.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/api/test_store.py
from api.store import JsonRecordStore


def test_put_get_roundtrip(tmp_path):
    store = JsonRecordStore(root=tmp_path)
    rec = store.put("runs", "run_1", {"project": "bourbon", "state": "scored"})
    assert rec["id"] == "run_1"
    assert (tmp_path / "runs" / "run_1.json").exists()
    assert store.get("runs", "run_1")["state"] == "scored"


def test_get_missing_returns_none(tmp_path):
    assert JsonRecordStore(root=tmp_path).get("runs", "nope") is None


def test_list_filters_by_project_and_where(tmp_path):
    store = JsonRecordStore(root=tmp_path)
    store.put("runs", "r1", {"project": "bourbon", "state": "scored"})
    store.put("runs", "r2", {"project": "bourbon", "state": "idle"})
    store.put("runs", "r3", {"project": "other", "state": "scored"})
    scored = store.list("runs", project="bourbon", where={"state": "scored"})
    assert [r["id"] for r in scored] == ["r1"]
    all_bourbon = store.list("runs", project="bourbon")
    assert {r["id"] for r in all_bourbon} == {"r1", "r2"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.store'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/api/store.py
"""File-first record store with a SQLite index for list/filter queries."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path


class JsonRecordStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.root / "_index.db", check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS records ("
            "collection TEXT, id TEXT, project TEXT, created_at REAL, json TEXT, "
            "PRIMARY KEY (collection, id))"
        )
        self._db.commit()

    def put(self, collection: str, record_id: str, data: dict) -> dict:
        record = dict(data)
        record["id"] = record_id
        record.setdefault("created_at", time.time())
        # 1) write file first (crash-safety: durable evidence before index)
        col_dir = self.root / collection
        col_dir.mkdir(parents=True, exist_ok=True)
        path = col_dir / f"{record_id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2))
        os.replace(tmp, path)
        # 2) upsert index row
        self._db.execute(
            "INSERT INTO records (collection, id, project, created_at, json) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(collection, id) DO UPDATE SET "
            "project=excluded.project, created_at=excluded.created_at, json=excluded.json",
            (collection, record_id, record.get("project"), record["created_at"],
             json.dumps(record)),
        )
        self._db.commit()
        return record

    def get(self, collection: str, record_id: str) -> dict | None:
        path = self.root / collection / f"{record_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def list(self, collection: str, *, project: str | None = None,
             where: dict | None = None) -> list[dict]:
        query = "SELECT json FROM records WHERE collection = ?"
        params: list[object] = [collection]
        if project is not None:
            query += " AND project = ?"
            params.append(project)
        query += " ORDER BY created_at DESC"
        rows = self._db.execute(query, params).fetchall()
        records = [json.loads(row[0]) for row in rows]
        if where:
            records = [r for r in records if all(r.get(k) == v for k, v in where.items())]
        return records
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_store.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/api/store.py flywheel/tests/api/test_store.py
git commit -m "feat(api): file-first record store with SQLite index"
```

---

## Task 3: AuditLog — append-only mutation history

**Files:**
- Create: `flywheel/api/audit.py`
- Test: `flywheel/tests/api/test_audit.py`

**Interfaces:**
- Consumes: `JsonRecordStore`.
- Produces:
  - `@dataclass class AuditEvent` with `id`, `project`, `actor`, `action`, `target_type`, `target_id`, `before: dict | None`, `after: dict | None`, `created_at: float`.
  - `class AuditLog(store: JsonRecordStore)` with `record(*, project, actor, action, target_type, target_id, before, after) -> str` returning the new audit event id; events stored in collection `"audit"`; `list(project) -> list[AuditEvent]`.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/api/test_audit.py
from api.store import JsonRecordStore
from api.audit import AuditLog


def test_record_returns_event_id_and_persists(tmp_path):
    log = AuditLog(JsonRecordStore(root=tmp_path))
    eid = log.record(
        project="bourbon", actor="alice", action="publish",
        target_type="baseline", target_id="gen_2",
        before={"status": "current"}, after={"status": "current"},
    )
    assert eid.startswith("ae_")
    events = log.list("bourbon")
    assert len(events) == 1
    assert events[0].action == "publish"
    assert events[0].actor == "alice"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.audit'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/api/audit.py
"""Append-only audit log for every mutation and approval."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from .store import JsonRecordStore


@dataclass
class AuditEvent:
    id: str
    project: str
    actor: str
    action: str
    target_type: str
    target_id: str
    before: dict | None
    after: dict | None
    created_at: float


class AuditLog:
    def __init__(self, store: JsonRecordStore):
        self._store = store

    def record(self, *, project: str, actor: str, action: str,
               target_type: str, target_id: str,
               before: dict | None, after: dict | None) -> str:
        event_id = f"ae_{uuid.uuid4().hex[:12]}"
        self._store.put("audit", event_id, {
            "project": project, "actor": actor, "action": action,
            "target_type": target_type, "target_id": target_id,
            "before": before, "after": after, "created_at": time.time(),
        })
        return event_id

    def list(self, project: str) -> list[AuditEvent]:
        return [
            AuditEvent(
                id=r["id"], project=r["project"], actor=r["actor"],
                action=r["action"], target_type=r["target_type"],
                target_id=r["target_id"], before=r.get("before"),
                after=r.get("after"), created_at=r["created_at"],
            )
            for r in self._store.list("audit", project=project)
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_audit.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/api/audit.py flywheel/tests/api/test_audit.py
git commit -m "feat(api): append-only audit log"
```

---

## Task 4: IdempotencyStore

**Files:**
- Create: `flywheel/api/idempotency.py`
- Test: `flywheel/tests/api/test_idempotency.py`

**Interfaces:**
- Consumes: `JsonRecordStore`.
- Produces:
  - `class IdempotencyStore(store: JsonRecordStore)` with `remember(key: str, result: dict) -> None` and `lookup(key: str) -> dict | None`. Keys stored in collection `"idempotency"`, value is the prior result. `lookup` returns `None` when unseen.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/api/test_idempotency.py
from api.store import JsonRecordStore
from api.idempotency import IdempotencyStore


def test_unseen_key_returns_none(tmp_path):
    idem = IdempotencyStore(JsonRecordStore(root=tmp_path))
    assert idem.lookup("k1") is None


def test_remember_then_lookup_returns_prior_result(tmp_path):
    idem = IdempotencyStore(JsonRecordStore(root=tmp_path))
    idem.remember("k1", {"id": "run_1", "state": "collecting"})
    assert idem.lookup("k1") == {"id": "run_1", "state": "collecting"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_idempotency.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.idempotency'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/api/idempotency.py
"""Idempotency key store. Duplicate submits return the prior result."""
from __future__ import annotations

import hashlib

from .store import JsonRecordStore


class IdempotencyStore:
    def __init__(self, store: JsonRecordStore):
        self._store = store

    def _slug(self, key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]

    def remember(self, key: str, result: dict) -> None:
        self._store.put("idempotency", self._slug(key), {"key": key, "result": result})

    def lookup(self, key: str) -> dict | None:
        rec = self._store.get("idempotency", self._slug(key))
        if rec is None:
            return None
        if rec.get("key") != key:  # guard against SHA-prefix collision
            return None
        return rec["result"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_idempotency.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/api/idempotency.py flywheel/tests/api/test_idempotency.py
git commit -m "feat(api): idempotency key store"
```

---

## Task 5: Auth — roles and require_role

**Files:**
- Create: `flywheel/api/auth.py`
- Test: `flywheel/tests/api/test_auth.py`

**Interfaces:**
- Produces:
  - `Role = Literal["dataset_curator", "judge_owner", "harness_owner", "platform_maintainer"]`.
  - `@dataclass class Principal` with `actor_id: str`, `roles: frozenset[Role]`.
  - `class Unauthorized(Exception)` carrying `required: Role`.
  - `require_role(principal: Principal, role: Role) -> None` — raises `Unauthorized` if missing. Message must not leak policy internals (UI §13).

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/api/test_auth.py
import pytest
from api.auth import Principal, require_role, Unauthorized


def test_role_present_passes():
    p = Principal(actor_id="alice", roles=frozenset({"harness_owner"}))
    require_role(p, "harness_owner")  # no raise


def test_role_missing_raises_without_leaking():
    p = Principal(actor_id="bob", roles=frozenset({"dataset_curator"}))
    with pytest.raises(Unauthorized) as exc:
        require_role(p, "harness_owner")
    assert "harness_owner" in str(exc.value)
    # message must not expose other principals' roles or policy internals
    assert "dataset_curator" not in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.auth'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/api/auth.py
"""Roles and authorization checks (UI §11 roles, §13 safety states)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Role = Literal["dataset_curator", "judge_owner", "harness_owner", "platform_maintainer"]


@dataclass(frozen=True)
class Principal:
    actor_id: str
    roles: frozenset[Role]


class Unauthorized(Exception):
    def __init__(self, required: Role):
        self.required = required
        super().__init__(f"requires role: {required}")


def require_role(principal: Principal, role: Role) -> None:
    if role not in principal.roles:
        raise Unauthorized(required=role)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_auth.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/api/auth.py flywheel/tests/api/test_auth.py
git commit -m "feat(api): roles and require_role authorization"
```

---

## Task 6: BaselineService — publish, supersede, human-gated revert

**Files:**
- Create: `flywheel/api/baselines.py`
- Test: `flywheel/tests/api/test_baselines.py`

**Interfaces:**
- Consumes: `JsonRecordStore`, `AuditLog`.
- Produces:
  - `@dataclass class Baseline` matching Engine §12: `project`, `generation: int`, `fingerprint: str`, `produced_by_proposal_id: str | None`, `previous_generation: int | None`, `published_at: str`, `status: Literal["current","superseded","reverted"]`, `revert_reason: str | None`, `reverted_at: str | None`.
  - `class BaselineService(store, audit)`:
    - `current(project) -> Baseline | None`.
    - `publish(*, project, fingerprint, proposal_id, actor) -> Baseline` — creates next generation `current`, marks prior `current` → `superseded`, audits. Returns new baseline.
    - `revert(*, project, to_generation: int, reason: str, actor) -> tuple[Baseline, str]` — marks current `reverted`, makes `to_generation` `current` again, audits. Returns `(restored_baseline, audit_event_id)`. Raises `ValueError` if `to_generation` is not a prior generation.
  - Collection: `"baselines"`, id = `f"{project}:gen{generation}"`.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/api/test_baselines.py
import pytest
from api.store import JsonRecordStore
from api.audit import AuditLog
from api.baselines import BaselineService


def _service(tmp_path):
    store = JsonRecordStore(root=tmp_path)
    return BaselineService(store, AuditLog(store))


def test_first_publish_is_generation_1_current(tmp_path):
    svc = _service(tmp_path)
    b = svc.publish(project="bourbon", fingerprint="fp1", proposal_id="p1", actor="alice")
    assert b.generation == 1
    assert b.status == "current"
    assert svc.current("bourbon").fingerprint == "fp1"


def test_second_publish_supersedes_first(tmp_path):
    svc = _service(tmp_path)
    svc.publish(project="bourbon", fingerprint="fp1", proposal_id="p1", actor="alice")
    b2 = svc.publish(project="bourbon", fingerprint="fp2", proposal_id="p2", actor="alice")
    assert b2.generation == 2
    assert b2.previous_generation == 1
    assert svc.current("bourbon").generation == 2


def test_revert_restores_previous_generation(tmp_path):
    svc = _service(tmp_path)
    svc.publish(project="bourbon", fingerprint="fp1", proposal_id="p1", actor="alice")
    svc.publish(project="bourbon", fingerprint="fp2", proposal_id="p2", actor="alice")
    restored, audit_id = svc.revert(project="bourbon", to_generation=1, reason="prod regression", actor="alice")
    assert restored.generation == 1
    assert restored.status == "current"
    assert audit_id is not None
    assert svc.current("bourbon").generation == 1


def test_revert_to_unknown_generation_raises(tmp_path):
    svc = _service(tmp_path)
    svc.publish(project="bourbon", fingerprint="fp1", proposal_id="p1", actor="alice")
    with pytest.raises(ValueError):
        svc.revert(project="bourbon", to_generation=99, reason="x", actor="alice")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_baselines.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.baselines'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/api/baselines.py
"""Baseline object and lifecycle: publish, supersede, human-gated revert (Engine §12)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

from .audit import AuditLog
from .store import JsonRecordStore

BaselineStatus = Literal["current", "superseded", "reverted"]


@dataclass
class Baseline:
    project: str
    generation: int
    fingerprint: str
    produced_by_proposal_id: str | None
    previous_generation: int | None
    published_at: str
    status: BaselineStatus
    revert_reason: str | None = None
    reverted_at: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaselineService:
    def __init__(self, store: JsonRecordStore, audit: AuditLog):
        self._store = store
        self._audit = audit

    def _id(self, project: str, generation: int) -> str:
        return f"{project}:gen{generation}"

    def _all(self, project: str) -> list[Baseline]:
        return [Baseline(**r) for r in self._store.list("baselines", project=project)]

    def current(self, project: str) -> Baseline | None:
        for b in self._all(project):
            if b.status == "current":
                return b
        return None

    def _save(self, b: Baseline) -> None:
        self._store.put("baselines", self._id(b.project, b.generation), asdict(b))

    def publish(self, *, project: str, fingerprint: str,
                proposal_id: str | None, actor: str) -> Baseline:
        existing = self._all(project)
        prev = max((b for b in existing), key=lambda b: b.generation, default=None)
        prev_current = self.current(project)
        if prev_current is not None:
            before = asdict(prev_current)
            prev_current.status = "superseded"
            self._save(prev_current)
            self._audit.record(project=project, actor=actor, action="supersede",
                               target_type="baseline",
                               target_id=self._id(project, prev_current.generation),
                               before=before, after=asdict(prev_current))
        generation = (prev.generation + 1) if prev else 1
        baseline = Baseline(
            project=project, generation=generation, fingerprint=fingerprint,
            produced_by_proposal_id=proposal_id,
            previous_generation=(prev.generation if prev else None),
            published_at=_now(), status="current",
        )
        self._save(baseline)
        self._audit.record(project=project, actor=actor, action="publish",
                           target_type="baseline", target_id=self._id(project, generation),
                           before=None, after=asdict(baseline))
        return baseline

    def revert(self, *, project: str, to_generation: int, reason: str,
               actor: str) -> tuple["Baseline", str]:
        """Returns (restored_baseline, audit_event_id) — UI §10: all mutations return audit event id."""
        target = self._store.get("baselines", self._id(project, to_generation))
        if target is None:
            raise ValueError(f"unknown baseline generation {to_generation} for {project}")
        current = self.current(project)
        if current is not None:
            before = asdict(current)
            current.status = "reverted"
            current.revert_reason = reason
            current.reverted_at = _now()
            self._save(current)
            self._audit.record(project=project, actor=actor, action="revert",
                               target_type="baseline",
                               target_id=self._id(project, current.generation),
                               before=before, after=asdict(current))
        restored = Baseline(**target)
        restored.status = "current"
        self._save(restored)
        audit_event_id = self._audit.record(
            project=project, actor=actor, action="restore",
            target_type="baseline", target_id=self._id(project, to_generation),
            before=target, after=asdict(restored),
        )
        return restored, audit_event_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_baselines.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/api/baselines.py flywheel/tests/api/test_baselines.py
git commit -m "feat(api): Baseline service with publish/supersede/revert lineage"
```

---

## Task 7: ScoreBridge — idempotent Langfuse score writes

**Files:**
- Create: `flywheel/api/score_bridge.py`
- Test: `flywheel/tests/api/test_score_bridge.py`

**Interfaces:**
- Consumes: `IdempotencyStore`, `AuditLog`.
- Produces:
  - `class ScoreBridge(langfuse_url, langfuse_secret, idem: IdempotencyStore, audit: AuditLog, project: str, client: httpx.Client | None)`.
  - `write_score(*, eval_run_id, case_id, sample_id, source, judge_version, label, failure_labels, confidence, critique, trace_id) -> dict`. Computes idempotency key `eval_run_id:case_id:sample_id:source:judge_version_or_none` (literal `:none` when judge_version absent); on duplicate returns prior result without calling Langfuse; otherwise POSTs to Langfuse Score API, records audit event, remembers result, returns `{"score_id":..., "deduped": False, "audit_event_id": ...}`.
  - Raises `ScoreBridgeError` on Langfuse non-2xx.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/api/test_score_bridge.py
import httpx
import respx
import pytest
from api.audit import AuditLog
from api.store import JsonRecordStore
from api.idempotency import IdempotencyStore
from api.score_bridge import ScoreBridge, ScoreBridgeError


def _bridge(tmp_path):
    store = JsonRecordStore(root=tmp_path)
    idem = IdempotencyStore(store)
    audit = AuditLog(store)
    return ScoreBridge(langfuse_url="http://lf", langfuse_secret="sec",
                       idem=idem, audit=audit, project="test")


@respx.mock
def test_write_score_posts_to_langfuse(tmp_path):
    route = respx.post("http://lf/api/public/scores").mock(
        return_value=httpx.Response(200, json={"id": "score_1"})
    )
    out = _bridge(tmp_path).write_score(
        eval_run_id="run_1", case_id="c1", sample_id="s0", source="judge",
        judge_version="jv1", label="fail", failure_labels=["tool_argument_error"],
        confidence=0.9, critique="x", trace_id="trace_1",
    )
    assert out["deduped"] is False
    assert out["score_id"] == "score_1"
    assert out["audit_event_id"] is not None
    assert route.called


@respx.mock
def test_duplicate_score_is_deduped_without_langfuse_call(tmp_path):
    bridge = _bridge(tmp_path)
    route = respx.post("http://lf/api/public/scores").mock(
        return_value=httpx.Response(200, json={"id": "score_1"})
    )
    args = dict(eval_run_id="run_1", case_id="c1", sample_id="s0", source="judge",
                judge_version="jv1", label="fail", failure_labels=[], confidence=0.9,
                critique="x", trace_id="trace_1")
    bridge.write_score(**args)
    out2 = bridge.write_score(**args)
    assert out2["deduped"] is True
    assert route.call_count == 1


@respx.mock
def test_langfuse_error_raises(tmp_path):
    respx.post("http://lf/api/public/scores").mock(
        return_value=httpx.Response(500, text="boom")
    )
    with pytest.raises(ScoreBridgeError, match="500"):
        _bridge(tmp_path).write_score(
            eval_run_id="run_1", case_id="c1", sample_id="s0", source="judge",
            judge_version="jv1", label="fail", failure_labels=[], confidence=0.9,
            critique="x", trace_id="trace_1",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_score_bridge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.score_bridge'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/api/score_bridge.py
"""Score Bridge: validated, idempotent, auditable writes to the Langfuse Score API."""
from __future__ import annotations

import httpx

from .idempotency import IdempotencyStore


class ScoreBridgeError(RuntimeError):
    """Raised when Langfuse rejects a score write."""


class ScoreBridge:
    def __init__(self, langfuse_url: str, langfuse_secret: str,
                 idem: IdempotencyStore, audit: "AuditLog", project: str,
                 client: httpx.Client | None = None):
        self._url = langfuse_url.rstrip("/")
        self._secret = langfuse_secret
        self._idem = idem
        self._client = client or httpx.Client(timeout=30.0)
        self._audit = audit
        self._project = project

    def write_score(self, *, eval_run_id: str, case_id: str, sample_id: str,
                    source: str, judge_version: str | None, label: str,
                    failure_labels: list[str], confidence: float | None,
                    critique: str | None, trace_id: str) -> dict:
        key = f"{eval_run_id}:{case_id}:{sample_id}:{source}:{judge_version or 'none'}"
        prior = self._idem.lookup(key)
        if prior is not None:
            return {"score_id": prior["score_id"], "deduped": True, "audit_event_id": prior.get("audit_event_id")}
        body = {
            "traceId": trace_id,
            "name": "flywheel.label",
            "value": label,
            "comment": critique,
            "metadata": {
                "flywheel.failure_labels": failure_labels,
                "flywheel.confidence": confidence,
                "flywheel.annotation_source": source,
                "flywheel.judge_version": judge_version,
                "flywheel.case_id": case_id,
                "flywheel.sample_id": sample_id,
                "flywheel.eval_run_id": eval_run_id,
            },
        }
        resp = self._client.post(
            f"{self._url}/api/public/scores", json=body,
            headers={"Authorization": f"Bearer {self._secret}"},
        )
        if resp.status_code >= 300:
            raise ScoreBridgeError(f"langfuse score write failed {resp.status_code}: {resp.text}")
        score_id = resp.json()["id"]
        audit_event_id = self._audit.record(
                project=self._project, actor=source, action="write_score",
                target_type="score", target_id=score_id, before=None,
                after={"eval_run_id": eval_run_id, "case_id": case_id, "label": label},
            )
        result = {"score_id": score_id, "audit_event_id": audit_event_id}
        self._idem.remember(key, result)
        return {"score_id": score_id, "deduped": False, "audit_event_id": audit_event_id}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_score_bridge.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/api/score_bridge.py flywheel/tests/api/test_score_bridge.py
git commit -m "feat(api): Score Bridge with idempotent Langfuse score writes"
```

---

## Task 8: FastAPI server — wiring, runs endpoints, baseline revert endpoint

**Files:**
- Create: `flywheel/api/schemas.py`
- Create: `flywheel/api/server.py`
- Test: `flywheel/tests/api/test_server.py`

**Interfaces:**
- Consumes: every service above.
- Produces:
  - `create_app(*, root: Path, principal_resolver) -> FastAPI`. `principal_resolver(request) -> Principal` is injected so tests can stub auth.
  - `GET /api/runs` (list, filter by `project`, `state`); `POST /api/runs` (create, idempotent via `Idempotency-Key` header, requires `harness_owner`); response includes `audit_event_id`.
  - `GET /api/baselines?project=` (list with lineage); `POST /api/baselines/{generation}/revert` (requires `harness_owner`, body `{project, reason}`), returns restored baseline + audit id.
  - 401 maps `Unauthorized` → HTTP 403 with `{"detail": "requires role: <role>"}`; `IllegalTransition` → HTTP 409.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/api/test_server.py
from pathlib import Path
from fastapi.testclient import TestClient
from api.server import create_app
from api.auth import Principal


def _client(tmp_path: Path, roles=("harness_owner",)):
    principal = Principal(actor_id="alice", roles=frozenset(roles))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    return TestClient(app)


def test_create_run_is_idempotent(tmp_path):
    client = _client(tmp_path)
    body = {"project": "bourbon", "dataset_id": "ds1", "dataset_version": "v1",
            "harness_fingerprint": "fp1", "judge_version": "jv1"}
    r1 = client.post("/api/runs", json=body, headers={"Idempotency-Key": "k1"})
    r2 = client.post("/api/runs", json=body, headers={"Idempotency-Key": "k1"})
    assert r1.status_code == 200
    assert r1.json()["run"]["id"] == r2.json()["run"]["id"]
    assert "audit_event_id" in r1.json()
    runs = client.get("/api/runs", params={"project": "bourbon"}).json()["runs"]
    assert len(runs) == 1  # deduped, not two rows


def test_get_run_by_id(tmp_path):
    client = _client(tmp_path)
    body = {"project": "bourbon", "dataset_id": "ds1", "dataset_version": "v1",
            "harness_fingerprint": "fp1", "judge_version": "jv1"}
    r1 = client.post("/api/runs", json=body, headers={"Idempotency-Key": "k-get"})
    run_id = r1.json()["run"]["id"]
    r2 = client.get(f"/api/runs/{run_id}")
    assert r2.status_code == 200
    assert r2.json()["run"]["id"] == run_id


def test_get_run_unknown_id_returns_404(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/runs/does_not_exist").status_code == 404


def test_create_run_requires_harness_owner(tmp_path):
    client = _client(tmp_path, roles=("dataset_curator",))
    r = client.post("/api/runs", json={"project": "bourbon", "dataset_id": "ds1",
                    "dataset_version": "v1", "harness_fingerprint": "fp1",
                    "judge_version": "jv1"}, headers={"Idempotency-Key": "k2"})
    assert r.status_code == 403
    assert "harness_owner" in r.json()["detail"]


def test_baseline_revert_flow(tmp_path):
    client = _client(tmp_path)
    # seed two baselines via the publish helper endpoint used in tests
    client.post("/api/baselines", json={"project": "bourbon", "fingerprint": "fp1",
                "proposal_id": "p1"}, headers={"Idempotency-Key": "b1"})
    client.post("/api/baselines", json={"project": "bourbon", "fingerprint": "fp2",
                "proposal_id": "p2"}, headers={"Idempotency-Key": "b2"})
    r = client.post("/api/baselines/1/revert", json={"project": "bourbon",
                    "reason": "prod regression"})
    assert r.status_code == 200
    assert r.json()["baseline"]["generation"] == 1
    assert r.json()["baseline"]["status"] == "current"
    assert "audit_event_id" in r.json()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.server'`.

- [ ] **Step 3: Write schemas**

```python
# flywheel/api/schemas.py
"""Pydantic request/response models for the Flywheel API."""
from __future__ import annotations

from pydantic import BaseModel

from .lifecycle import RunState


class CreateRunRequest(BaseModel):
    project: str
    dataset_id: str
    dataset_version: str
    harness_fingerprint: str
    judge_version: str


class RunOut(BaseModel):
    id: str  # eval_run_id in Engine §6; field name kept as "id" for MVP, rename tracked in plan 07
    project: str
    dataset_id: str
    dataset_version: str
    harness_fingerprint: str
    judge_version: str
    state: RunState
    created_at: float
    progress: dict = {}
    aggregate_metrics: dict = {}


class MutationEnvelope(BaseModel):
    audit_event_id: str


class PublishBaselineRequest(BaseModel):
    project: str
    fingerprint: str
    proposal_id: str | None = None


class RevertBaselineRequest(BaseModel):
    project: str
    reason: str
```

- [ ] **Step 4: Write minimal server implementation**

```python
# flywheel/api/server.py
"""FastAPI app: dependency wiring, idempotency, role checks, audit, error mapping."""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Header, HTTPException, Request

from .audit import AuditLog
from .auth import Principal, Unauthorized, require_role
from .baselines import BaselineService
from .idempotency import IdempotencyStore
from .lifecycle import IllegalTransition
from .schemas import CreateRunRequest, PublishBaselineRequest, RevertBaselineRequest
from .store import JsonRecordStore


def create_app(*, root: Path,
               principal_resolver: Callable[[Request], Principal]) -> FastAPI:
    app = FastAPI(title="Flywheel API")
    store = JsonRecordStore(root=root)
    audit = AuditLog(store)
    idem = IdempotencyStore(store)
    baselines = BaselineService(store, audit)

    @app.exception_handler(Unauthorized)
    def _unauth(_: Request, exc: Unauthorized):
        return _json(403, {"detail": f"requires role: {exc.required}"})

    @app.exception_handler(IllegalTransition)
    def _illegal(_: Request, exc: IllegalTransition):
        return _json(409, {"detail": str(exc)})

    def _idempotent(key: str | None, build: Callable[[], dict]) -> dict:
        if key:
            prior = idem.lookup(key)
            if prior is not None:
                return prior
        result = build()
        if key:
            idem.remember(key, result)
        return result

    # ---- runs ----
    @app.get("/api/runs")
    def list_runs(project: str, state: str | None = None):
        where = {"state": state} if state else None
        return {"runs": store.list("runs", project=project, where=where)}

    @app.post("/api/runs")
    def create_run(req: CreateRunRequest, request: Request,
                   idempotency_key: str | None = Header(default=None)):
        # NOTE: harness_owner is required for humans; L1 machine actors need a service account
        # with harness_owner role (or a dedicated "eval_runner" role — document in infra plan).
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")

        def build() -> dict:
            run_id = f"run_{uuid.uuid4().hex[:12]}"
            run = store.put("runs", run_id, {
                "project": req.project, "dataset_id": req.dataset_id,
                "dataset_version": req.dataset_version,
                "harness_fingerprint": req.harness_fingerprint,
                "judge_version": req.judge_version, "state": "collecting",
                "created_at": time.time(), "progress": {}, "aggregate_metrics": {},
            })
            aid = audit.record(project=req.project, actor=principal.actor_id,
                               action="create_run", target_type="run",
                               target_id=run_id, before=None, after=run)
            return {"run": run, "audit_event_id": aid}

        return _idempotent(idempotency_key, build)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        r = store.get("runs", run_id)
        if r is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"run": r}

    @app.post("/api/runs/{run_id}/scores")
    def submit_score(run_id: str, request: Request):
        # TODO(plan-04): implement taxonomy registry validation — reject unknown stable labels with 422.
        # Until then, this endpoint stubs as 501; L1 SDK calls ScoreBridge.write_score() directly.
        return _json(501, {"detail": "not yet implemented — taxonomy validation wired in plan 04"})

    # ---- baselines ----
    @app.get("/api/baselines")
    def list_baselines(project: str):
        return {"baselines": store.list("baselines", project=project)}

    @app.get("/api/baselines/{generation}")
    def get_baseline(generation: int, project: str):
        b = store.get("baselines", f"{project}:gen{generation}")
        if b is None:
            raise HTTPException(status_code=404, detail="baseline not found")
        return {"baseline": b}

    @app.post("/api/baselines")
    def publish_baseline(req: PublishBaselineRequest, request: Request,
                         idempotency_key: str | None = Header(default=None)):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")

        def build() -> dict:
            from dataclasses import asdict
            b = baselines.publish(project=req.project, fingerprint=req.fingerprint,
                                  proposal_id=req.proposal_id, actor=principal.actor_id)
            return {"baseline": asdict(b)}

        return _idempotent(idempotency_key, build)

    @app.post("/api/baselines/{generation}/revert")
    def revert_baseline(generation: int, req: RevertBaselineRequest, request: Request):
        from dataclasses import asdict
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        b, audit_event_id = baselines.revert(project=req.project, to_generation=generation,
                                              reason=req.reason, actor=principal.actor_id)
        return {"baseline": asdict(b), "audit_event_id": audit_event_id}

    # ---- stubs for State Store objects defined in Task 9 (owners assigned in 00-index) ----
    # plan 04: /api/projects, /api/datasets, /api/taxonomy, /api/trace-pools, /api/open-code-batches
    # plan 05: /api/judges, /api/annotations
    # plan 06: /api/issues, /api/proposals (GET + handoff/implementation-link/rebase)
    # plan 07: /api/regressions, proposal approve/reject/defer/publish/rollback
    # Each tuple: (method, path, owner_plan)
    _STUB_ROUTES: list[tuple[str, str, str]] = [
        # plan 03
        ("GET", "/api/redaction/reports", "03"),
        # plan 04
        ("GET", "/api/projects", "04"),
        ("GET", "/api/datasets/{dataset_id}", "04"),
        ("POST", "/api/datasets/{dataset_id}/cases", "04"),
        ("GET", "/api/taxonomy", "04"),
        ("GET", "/api/taxonomy/labels", "04"),
        ("POST", "/api/taxonomy/labels", "04"),
        ("GET", "/api/taxonomy/migrations", "04"),
        ("POST", "/api/taxonomy/migrations", "04"),
        ("POST", "/api/taxonomy/propose-update", "04"),
        ("GET", "/api/trace-pools", "04"),
        ("POST", "/api/trace-pools/{pool_id}/sample", "04"),
        ("GET", "/api/open-code-batches/{batch_id}", "04"),
        ("POST", "/api/open-code-batches/{batch_id}/codes", "04"),
        # plan 05
        ("GET", "/api/judges", "05"),
        ("POST", "/api/judges", "05"),
        ("GET", "/api/judges/{judge_version}", "05"),
        ("POST", "/api/judges/{judge_version}/validate", "05"),
        ("GET", "/api/annotations", "05"),
        ("POST", "/api/annotations", "05"),
        ("GET", "/api/annotations/{annotation_id}", "05"),
        ("POST", "/api/annotations/{annotation_id}", "05"),
        # plan 06
        ("GET", "/api/issues", "06"),
        ("GET", "/api/issues/{issue_id}", "06"),
        ("GET", "/api/proposals/{proposal_id}", "06"),
        ("POST", "/api/proposals/{proposal_id}/handoff", "06"),
        ("POST", "/api/proposals/{proposal_id}/implementation-link", "06"),
        ("POST", "/api/proposals/{proposal_id}/rebase", "06"),
        ("POST", "/api/runs/{run_id}/sync-labels", "06"),
        ("POST", "/api/runs/{run_id}/analysis", "06"),
        # plan 07
        ("GET", "/api/regressions/{regression_id}", "07"),
        ("POST", "/api/regressions", "07"),
        ("POST", "/api/regressions/{regression_id}/publish", "07"),
        ("POST", "/api/regressions/{regression_id}/rollback", "07"),
        ("POST", "/api/regressions/{regression_id}/no-significant-change", "07"),
        ("POST", "/api/regressions/{regression_id}/require-judge-recheck", "07"),
        ("POST", "/api/regressions/{regression_id}/resume-after-judge-recheck", "07"),
        ("POST", "/api/regressions/{regression_id}/require-judge-migration", "07"),
        ("POST", "/api/regressions/{regression_id}/resume-after-judge-migration", "07"),
        ("POST", "/api/proposals/{proposal_id}/approve", "07"),
        ("POST", "/api/proposals/{proposal_id}/reject", "07"),
        ("POST", "/api/proposals/{proposal_id}/defer", "07"),
    ]

    def _make_stub(owner_plan: str):
        def _stub(**_):
            return _json(501, {"detail": f"not implemented in plan 02 — implemented in plan {owner_plan}"})
        return _stub

    for _method, _path, _plan in _STUB_ROUTES:
        app.add_api_route(_path, _make_stub(_plan), methods=[_method])

    # ---- redaction guard (Engine §10, §15 Day-1 Hard Gate) ----
    # Evidence-serving endpoints must not be callable until plan 03 RedactionService is wired.
    # Any route under /api/evidence or /api/traces returns 503 until REDACTION_ENABLED is set.
    import os
    _REDACTION_ENABLED = os.getenv("REDACTION_ENABLED", "") != ""

    def _evidence_guard(**_):
        if not _REDACTION_ENABLED:
            return _json(503, {"detail": "evidence endpoints require redaction pipeline (plan 03); set REDACTION_ENABLED after wiring RedactionService"})
        return _json(501, {"detail": "evidence routing implemented in plan 03"})

    app.add_api_route("/api/evidence/{path:path}", _evidence_guard, methods=["GET"])
    app.add_api_route("/api/traces/{path:path}", _evidence_guard, methods=["GET"])

    return app


def _json(status: int, body: dict):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=body)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_server.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Run full API suite + lint + types**

Run:
```bash
cd flywheel && pytest tests/api -q && ruff check api tests && mypy api
```
Expected: all pass; ruff clean; mypy clean.

- [ ] **Step 7: Commit**

```bash
git add flywheel/api/schemas.py flywheel/api/server.py flywheel/tests/api/test_server.py
git commit -m "feat(api): FastAPI server with idempotent runs and baseline revert"
```

---

## Task 9: State Store record schemas for downstream objects (placeholders for plans 03–07)

**Files:**
- Modify: `flywheel/api/schemas.py` (append models)
- Test: `flywheel/tests/api/test_state_objects.py`

**Interfaces:**
- Produces pydantic models (validation only; persistence reuses `JsonRecordStore`) for the remaining State Store objects in Engine §9 so later plans share one schema definition:
  `TracePool`, `TracePoolRetentionPolicy`, `OpenCodeBatch`, `TaxonomyLabel`, `TaxonomyMigration`, `Dataset`, `DatasetCase`, `JudgeVersion`, `JudgeDriftCheck`, `EvalRun` (already as `RunOut`), `Annotation`, `FailureIssue`, `ImprovementProposal`, `Handoff`, `RegressionResult`, `RegressionHoldoutLedger`, `BaselineRevertDecision`.
- Each model carries `project` and `id`. This task defines the **field shapes only** — behavior lives in later plans.

- [ ] **Step 1: Write the failing test** (one representative model per object family)

```python
# flywheel/tests/api/test_state_objects.py
from api.schemas import (
    DatasetCaseModel, TaxonomyLabelModel, ImprovementProposalModel,
    RegressionHoldoutLedgerModel,
)


def test_dataset_case_requires_split_enum():
    import pytest
    with pytest.raises(Exception):
        DatasetCaseModel(
            project="bourbon", id="c1", dataset_id="ds1", dataset_version="v1",
            case_id="c1", task_family="tool_use", source_trace_ids=["t1"],
            intent_summary="x", input_messages_ref="ref", expected_outcome="ok",
            acceptance_criteria=["a"], risk_tags=[], failure_labels=[],
            split="not_a_split", created_from="production_trace",
        )


def test_taxonomy_label_status_enum():
    label = TaxonomyLabelModel(project="bourbon", id="l1", slug="tool_argument_error",
        definition="bad args", examples=[], counterexamples=[], status="active")
    assert label.status == "active"


def test_proposal_carries_consumed_cases():
    p = ImprovementProposalModel(project="bourbon", id="p1", baseline_fingerprint="fp1",
        baseline_generation=1, candidate_hypothesis_id="h1", source_eval_run_id="run1",
        taxonomy_version="v1", failure_issues=["i1"], proposed_changes=[],
        target_files=["src/x.py"], consumed_case_ids=["c1", "c2"], consumed_trace_ids=[],
        proposer_id="engine", expected_metric_delta={"pass_rate": 0.05}, rollback_plan="revert")
    assert p.consumed_case_ids == ["c1", "c2"]


def test_holdout_ledger_multiple_comparison_policy():
    led = RegressionHoldoutLedgerModel(project="bourbon", id="led1", dataset_id="ds1",
        dataset_version="v1", holdout_case_ids=["c1"], tested_hypothesis_ids=[],
        distinct_hypothesis_count=0, raw_regression_run_count=0,
        published_candidate_count=0, last_cold_case_refresh_at="2026-06-23T00:00:00Z",
        multiple_comparison_policy="bonferroni")
    assert led.multiple_comparison_policy == "bonferroni"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_state_objects.py -v`
Expected: FAIL with `ImportError: cannot import name 'DatasetCaseModel'`.

- [ ] **Step 3: Append models to `schemas.py`**

```python
# flywheel/api/schemas.py  (append)
from typing import Literal

from .lifecycle import ProposalState

Split = Literal["train", "dev", "locked_test", "regression_holdout"]
CreatedFrom = Literal["production_trace", "synthetic", "manual"]
LabelStatus = Literal["candidate", "active", "retired"]
MultipleComparisonPolicy = Literal["none", "bonferroni", "fdr"]


class TracePoolRetentionPolicyModel(BaseModel):
    """Separate object per Engine §9 State Store — owns raw+redacted TTL and deletion/audit policy."""
    raw_ttl_days: int
    redacted_ttl_days: int
    deletion_policy: Literal["auto", "manual", "audit_required"] = "manual"
    audit_required: bool = False


class TracePoolModel(BaseModel):
    project: str
    id: str
    name: str
    source_trace_ids: list[str] = []
    retention_policy: TracePoolRetentionPolicyModel | None = None


class OpenCodeBatchModel(BaseModel):
    project: str
    id: str
    trace_pool_id: str
    codes: list[dict] = []  # {trace_id, code, author}


class TaxonomyLabelModel(BaseModel):
    project: str
    id: str
    slug: str
    parent: str | None = None
    definition: str
    examples: list[str] = []
    counterexamples: list[str] = []
    status: LabelStatus
    taxonomy_version: str | None = None
    owner_approved: bool = False
    approved_by: str | None = None


class TaxonomyMigrationStepModel(BaseModel):
    from_slug: str
    to_slug: str | list[str] | None
    kind: Literal["rename", "split", "merge", "retire"]


class TaxonomyMigrationModel(BaseModel):
    project: str
    id: str
    from_version: str
    to_version: str
    migrations: list[TaxonomyMigrationStepModel]


class DatasetCaseModel(BaseModel):
    project: str
    id: str
    dataset_id: str
    dataset_version: str
    case_id: str
    task_family: str
    source_trace_ids: list[str]
    intent_summary: str
    input_messages_ref: str
    expected_outcome: str
    acceptance_criteria: list[str]
    risk_tags: list[str]
    failure_labels: list[str]
    split: Split
    created_from: CreatedFrom


class DatasetModel(BaseModel):
    project: str
    id: str
    dataset_id: str
    dataset_version: str
    task_families: list[str] = []


class JudgeVersionModel(BaseModel):
    project: str
    id: str
    judge_version: str
    task_family: str
    model: str
    prompt_version: str
    taxonomy_version: str
    train_dataset_id: str
    dev_dataset_id: str
    locked_test_dataset_id: str
    status: Literal["draft", "calibrating", "validated",
                    "validated_limited", "rejected", "recheck_required"]
    # "locked_test" is UI-only (UI §12 TypeScript display type); not a DB/API status (Engine §12)
    metrics: dict[str, float] = {}


class JudgeDriftCheckModel(BaseModel):
    project: str
    id: str
    judge_version: str
    task_family: str
    sampled_at: str
    human_judge_agreement: float
    distribution_drift: float


class AnnotationModel(BaseModel):
    project: str
    id: str
    eval_run_id: str
    case_id: str
    sample_id: str
    label: Literal["pass", "fail", "skip", "uncertain"]
    source: Literal["human", "judge", "rule", "system"]
    judge_version: str | None = None
    failure_labels: list[str] = []
    confidence: float | None = None
    critique: str | None = None
    annotated_by: str | None = None
    annotation_rubric_version: str | None = None
    redaction_state: Literal["raw", "redacted", "blocked"] | None = None


class FailureIssueModel(BaseModel):
    project: str
    id: str
    title: str
    taxonomy_labels: list[str] = []
    open_codes: list[str] = []
    affected_case_ids: list[str] = []
    evidence_trace_ids: list[str] = []
    counterexamples: list[str] = []
    affected_labels: list[str] = []
    root_cause_hypothesis: str = ""
    confidence: float = 0.0


class ProposedChangeModel(BaseModel):
    change_type: Literal["prompt", "tool_definition", "workflow", "config", "code"]
    target_file: str
    description: str
    rationale: str
    evidence_trace_ids: list[str] = []
    evidence_case_ids: list[str] = []
    suggested_diff: str = ""
    risk_level: Literal["low", "medium", "high"]


class ImprovementProposalModel(BaseModel):
    project: str
    id: str
    baseline_fingerprint: str
    baseline_generation: int
    candidate_hypothesis_id: str
    source_eval_run_id: str
    taxonomy_version: str
    failure_issues: list[str]
    proposed_changes: list[ProposedChangeModel]
    target_files: list[str]
    consumed_case_ids: list[str]
    consumed_trace_ids: list[str]
    proposer_id: str
    expected_metric_delta: dict[str, float]
    rollback_plan: str
    state: ProposalState = "draft"
    created_at: str = ""


class HandoffModel(BaseModel):
    project: str
    id: str
    proposal_id: str
    markdown: str
    pr_url: str | None = None
    diff_url: str | None = None


class RegressionResultModel(BaseModel):
    project: str
    id: str
    proposal_id: str
    baseline_fingerprint: str
    candidate_fingerprint: str
    judge_version: str
    pass_rate_delta: float
    pass_rate_ci: list[float]  # [low, high]
    expected_metric_delta: dict[str, float] = {}
    actual_metric_delta: dict[str, float] = {}
    fixed_failures: list[str] = []
    new_failures: list[str] = []
    outcome: str | None = None
    # Holdout integrity proof fields (Engine §14 — any non-empty intersection blocks publish)
    consumed_holdout_intersection: list[str] = []
    holdout_train_intersection: list[str] = []
    holdout_dev_intersection: list[str] = []
    holdout_locked_test_intersection: list[str] = []
    # Candidate quality fields (Engine §11, UI §9)
    candidate_human_judge_agreement: float | None = None
    per_label_deltas: dict[str, float] = {}


class RegressionHoldoutLedgerModel(BaseModel):
    project: str
    id: str
    dataset_id: str
    dataset_version: str
    holdout_case_ids: list[str]
    tested_hypothesis_ids: list[str]
    distinct_hypothesis_count: int
    raw_regression_run_count: int
    published_candidate_count: int
    last_cold_case_refresh_at: str
    multiple_comparison_policy: MultipleComparisonPolicy


class BaselineRevertDecisionModel(BaseModel):
    project: str
    id: str
    from_generation: int
    to_generation: int
    reason: str
    actor: str
    decided_at: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_state_objects.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Run full suite + lint + types, then commit**

```bash
cd flywheel && pytest -q && ruff check api sdk tests && mypy api sdk
git add flywheel/api/schemas.py flywheel/tests/api/test_state_objects.py
git commit -m "feat(api): State Store record schemas for downstream objects"
```

---

## Self-Review

- **Spec coverage (Engine §9, §12 Baseline; UI §10/§11):** lifecycle enums + derivation (§12); JsonRecordStore covers all §9 State Store objects via collections; AuditLog satisfies "all mutations return an audit event id"; IdempotencyStore implements §9 idempotency; auth implements §11 roles; BaselineService implements the §12 Baseline rules (one current, publish supersedes, human-gated revert with lineage); ScoreBridge implements §8 routing + §9 score idempotency key; server wires idempotency + role checks + audit and maps errors. Task 9 defines schemas for every remaining §9 object so plans 03–07 share one definition.
- **Placeholder scan:** the only prose-with-note is the Task 8 exception-handler simplification, which gives the exact final code. No TBD/TODO. All other code blocks are complete.
- **Type consistency:** `ScoreBridge` idempotency key string matches `ScorePayload.idempotency_key()` from plan 01 (`eval_run_id:case_id:sample_id:source:judge_version_or_none` — literal `":none"` when judge_version is absent). `Baseline` dataclass fields match `Engine §12` and the `BaselineRevertDecisionModel`. `ProposalState`/`RegressionStatus`/`RegressionOutcome` literals match plan 01 metrics consumers and plan 07 regression logic. `RunState` used in `RunOut` matches `lifecycle.RunState`.
