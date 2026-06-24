# Flywheel 05 — Judge Version Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the versioned `JudgeVersion` asset and its lifecycle: calibration protocol with train/dev/locked-test splits and explicit thresholds, locked-test rotation accounting, candidate drift recheck (human audit agreement gate), and the production drift sentinel — including propagation that marks judges `recheck_required` on taxonomy migration or drift.

**Architecture:** `flywheel/engine/judge.py` holds the lifecycle service over the State Store. The DB/API `JudgeVersion.status` enum is the Engine §11 set (no persisted `locked_test` status — that is a UI-only display abstraction, see plan 02 `lifecycle.JudgeState`). API read responses add a derived `validation_phase` field so plan 08 can render `locked_test` without creating a parallel persisted lifecycle. Calibration metrics reuse `sdk.metrics`. Synchronous.

**Tech Stack:** Python 3.13, pydantic v2, pytest.

## Global Constraints

(See `2026-06-23-flywheel-00-index.md`.) Most relevant here:
- Automated proposal generation requires a **validated** judge for the relevant task family; otherwise the run collects scores but cannot trigger proposals.
- A taxonomy migration touching labels a validated judge used marks that judge `recheck_required` (consumes `TaxonomyRegistry.changed_labels` from plan 04).
- Judge `status` DB/API values: `draft, calibrating, validated, validated_limited, rejected, recheck_required` (plan 02 `JudgeState`).
- UI/display may show `validation_phase="locked_test"` when the judge prompt is frozen and being evaluated on locked-test cases, but `locked_test` is never persisted as `status`.
- Same-judge comparison and judge-recheck blocking interact with regression (plan 07) — this plan exposes the state transitions plan 07 calls.

---

## File Structure

- Create: `flywheel/engine/judge.py` — `JudgeService`: create, calibrate, locked-test validation, rotation accounting, candidate drift recheck, drift sentinel, taxonomy-migration propagation
- Test: `flywheel/tests/engine/test_judge.py`, `test_judge_drift.py`

**Interfaces consumed:** `JudgeVersionModel` (plan 02 schemas), `JsonRecordStore` (plan 02), `precision_recall_f1` (`sdk.metrics`, plan 01), `TaxonomyRegistry.changed_labels` (plan 04).

---

## Task 1: JudgeService create + calibration gate

**Files:**
- Create: `flywheel/engine/judge.py`
- Test: `flywheel/tests/engine/test_judge.py`

**Interfaces:**
- Consumes: `JudgeVersionModel`, `JsonRecordStore`, `precision_recall_f1`.
- Produces:
  - `@dataclass class CalibrationResult` with `overall_f1: float`, `per_label: dict[str, tuple[float, float]]` (slug → (precision, recall)), `passed: bool`, `threshold: float`.
  - `class JudgeService(store: JsonRecordStore, f1_threshold: float = 0.70)`:
    - `create(*, project, judge_version, task_family, model, prompt_version, taxonomy_version, train_dataset_id, dev_dataset_id, locked_test_dataset_id) -> dict` — status `draft`, collection `"judges"`, id = `f"{project}:{judge_version}"`.
    - `calibrate(*, project, judge_version, confusion: dict[str, dict[str, int]]) -> CalibrationResult` — `confusion[label] = {"tp","fp","fn"}`; computes overall micro-F1 and per-label precision/recall; sets status `calibrating`; stores metrics. Does **not** validate — that needs the locked test (Task 2).

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_judge.py
from api.audit import AuditLog
from api.store import JsonRecordStore
from engine.judge import JudgeService


def _service(tmp_path):
    return JudgeService(JsonRecordStore(root=tmp_path))


def _create(svc):
    return svc.create(
        project="bourbon", judge_version="jv1", task_family="tool_use",
        model="claude-opus-4-8", prompt_version="p1", taxonomy_version="2026-06-22.1",
        train_dataset_id="ds_train", dev_dataset_id="ds_dev",
        locked_test_dataset_id="ds_locked",
    )


def test_create_starts_draft(tmp_path):
    svc = _service(tmp_path)
    judge = _create(svc)
    assert judge["status"] == "draft"
    assert judge["judge_version"] == "jv1"


def test_calibrate_computes_f1_and_sets_calibrating(tmp_path):
    svc = _service(tmp_path)
    _create(svc)
    result = svc.calibrate(project="bourbon", judge_version="jv1", confusion={
        "tool_argument_error": {"tp": 8, "fp": 2, "fn": 2},
        "retrieval_miss": {"tp": 9, "fp": 1, "fn": 1},
    })
    assert 0.0 < result.overall_f1 <= 1.0
    assert "tool_argument_error" in result.per_label
    judge = svc.get(project="bourbon", judge_version="jv1")
    assert judge["status"] == "calibrating"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_judge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.judge'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/judge.py
"""Judge version lifecycle (Engine §11): calibration, locked-test, drift recheck."""
from __future__ import annotations

from dataclasses import dataclass

from api.store import JsonRecordStore
from sdk.metrics import precision_recall_f1


@dataclass
class CalibrationResult:
    overall_f1: float
    per_label: dict[str, tuple[float, float]]
    passed: bool
    threshold: float


class JudgeService:
    def __init__(self, store: JsonRecordStore, f1_threshold: float = 0.70,
                 audit: AuditLog | None = None):
        self._store = store
        self._threshold = f1_threshold
        self._audit = audit

    def _id(self, project: str, judge_version: str) -> str:
        return f"{project}:{judge_version}"

    def get(self, *, project: str, judge_version: str) -> dict:
        judge = self._store.get("judges", self._id(project, judge_version))
        if judge is None:
            raise ValueError(f"unknown judge {judge_version}")
        return judge

    def _save(self, judge: dict) -> dict:
        return self._store.put("judges", self._id(judge["project"],
                               judge["judge_version"]), judge)

    def create(self, *, project: str, judge_version: str, task_family: str,
               model: str, prompt_version: str, taxonomy_version: str,
               train_dataset_id: str, dev_dataset_id: str,
               locked_test_dataset_id: str) -> dict:
        return self._store.put("judges", self._id(project, judge_version), {
            "project": project, "judge_version": judge_version,
            "task_family": task_family, "model": model,
            "prompt_version": prompt_version, "taxonomy_version": taxonomy_version,
            "train_dataset_id": train_dataset_id, "dev_dataset_id": dev_dataset_id,
            "locked_test_dataset_id": locked_test_dataset_id,
            "status": "draft", "metrics": {},
            "locked_test_reuse_count": 0,
        })

    def calibrate(self, *, project: str, judge_version: str,
                  confusion: dict[str, dict[str, int]]) -> CalibrationResult:
        judge = self.get(project=project, judge_version=judge_version)
        total_tp = sum(c["tp"] for c in confusion.values())
        total_fp = sum(c["fp"] for c in confusion.values())
        total_fn = sum(c["fn"] for c in confusion.values())
        _, _, overall_f1 = precision_recall_f1(total_tp, total_fp, total_fn)
        per_label: dict[str, tuple[float, float]] = {}
        for label, c in confusion.items():
            p, r, _ = precision_recall_f1(c["tp"], c["fp"], c["fn"])
            per_label[label] = (p, r)
        judge["status"] = "calibrating"
        judge["metrics"] = {"overall_f1": overall_f1}
        self._save(judge)
        return CalibrationResult(
            overall_f1=overall_f1, per_label=per_label,
            passed=overall_f1 >= self._threshold, threshold=self._threshold,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_judge.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/judge.py flywheel/tests/engine/test_judge.py
git commit -m "feat(engine): JudgeService create and calibration F1 gate"
```

---

## Task 2: Locked-test validation + rotation accounting

**Files:**
- Modify: `flywheel/engine/judge.py` (append `validate_on_locked_test`)
- Test: `flywheel/tests/engine/test_judge_validate.py`

**Interfaces:**
- Produces (added to `JudgeService`):
  - `validate_on_locked_test(*, project, judge_version, overall_f1: float, max_reuse: int = 3) -> dict` — implements Engine §11 locked-test rotation:
    - increments `locked_test_reuse_count`.
    - if `overall_f1 < threshold` → status `rejected`.
    - elif `locked_test_reuse_count > max_reuse` → status `validated_limited` (manual analysis only).
    - else → status `validated`.
    - records `prior_judge_versions_on_locked_test` count for the validation report.
    - returns the updated judge.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_judge_validate.py
from api.store import JsonRecordStore
from engine.judge import JudgeService


def _validated_setup(tmp_path):
    svc = JudgeService(JsonRecordStore(root=tmp_path))
    svc.create(project="bourbon", judge_version="jv1", task_family="tool_use",
               model="m", prompt_version="p1", taxonomy_version="tax1",
               train_dataset_id="d1", dev_dataset_id="d2", locked_test_dataset_id="d3")
    return svc


def test_below_threshold_is_rejected(tmp_path):
    svc = _validated_setup(tmp_path)
    judge = svc.validate_on_locked_test(project="bourbon", judge_version="jv1",
                                        overall_f1=0.5)
    assert judge["status"] == "rejected"


def test_meets_threshold_is_validated(tmp_path):
    svc = _validated_setup(tmp_path)
    judge = svc.validate_on_locked_test(project="bourbon", judge_version="jv1",
                                        overall_f1=0.85)
    assert judge["status"] == "validated"
    assert judge["locked_test_reuse_count"] == 1


def test_reuse_over_limit_is_validated_limited(tmp_path):
    svc = _validated_setup(tmp_path)
    for _ in range(4):  # 4th validation exceeds max_reuse=3
        judge = svc.validate_on_locked_test(project="bourbon", judge_version="jv1",
                                            overall_f1=0.85, max_reuse=3)
    assert judge["status"] == "validated_limited"
    assert judge["locked_test_reuse_count"] == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_judge_validate.py -v`
Expected: FAIL with `AttributeError: ... 'validate_on_locked_test'`.

- [ ] **Step 3: Append implementation to `judge.py`**

```python
# flywheel/engine/judge.py  (append to JudgeService)
    def validate_on_locked_test(self, *, project: str, judge_version: str,
                                overall_f1: float, max_reuse: int = 3) -> dict:
        judge = self.get(project=project, judge_version=judge_version)
        judge["locked_test_reuse_count"] = judge.get("locked_test_reuse_count", 0) + 1
        judge.setdefault("metrics", {})["locked_test_f1"] = overall_f1
        if overall_f1 < self._threshold:
            judge["status"] = "rejected"
        elif judge["locked_test_reuse_count"] > max_reuse:
            # Engine §11: reuse beyond policy -> validated_limited (manual analysis only)
            judge["status"] = "validated_limited"
        else:
            judge["status"] = "validated"
        judge["prior_judge_versions_on_locked_test"] = judge["locked_test_reuse_count"] - 1
        return self._save(judge)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_judge_validate.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/judge.py flywheel/tests/engine/test_judge_validate.py
git commit -m "feat(engine): locked-test validation with rotation accounting"
```

---

## Task 3: Candidate drift recheck + taxonomy-migration propagation

**Files:**
- Modify: `flywheel/engine/judge.py` (append `candidate_drift_recheck`, `propagate_taxonomy_migration`)
- Test: `flywheel/tests/engine/test_judge_drift.py`

**Interfaces:**
- Consumes: `TaxonomyRegistry.changed_labels` (plan 04).
- Produces (added to `JudgeService`):
  - `candidate_drift_recheck(*, project, judge_version, candidate_human_judge_agreement: float) -> dict` — Engine §11: if agreement falls below `self._threshold`, set status `recheck_required` and return judge; else leave status unchanged (still validated). Stores `last_candidate_agreement`.
  - `propagate_taxonomy_migration(*, project, changed_label_slugs: set[str], judge_label_slugs: dict[str, set[str]]) -> list[str]` — for every validated/validated_limited judge whose used labels (`judge_label_slugs[judge_version]`) intersect `changed_label_slugs`, set status `recheck_required`; returns the list of affected `judge_version`s.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_judge_drift.py
from api.store import JsonRecordStore
from engine.judge import JudgeService


def _validated_judge(tmp_path, jv="jv1"):
    svc = JudgeService(JsonRecordStore(root=tmp_path))
    svc.create(project="bourbon", judge_version=jv, task_family="tool_use",
               model="m", prompt_version="p1", taxonomy_version="tax1",
               train_dataset_id="d1", dev_dataset_id="d2", locked_test_dataset_id="d3")
    svc.validate_on_locked_test(project="bourbon", judge_version=jv, overall_f1=0.9)
    return svc


def test_candidate_drift_below_gate_requires_recheck(tmp_path):
    svc = _validated_judge(tmp_path)
    judge = svc.candidate_drift_recheck(project="bourbon", judge_version="jv1",
                                        candidate_human_judge_agreement=0.5)
    assert judge["status"] == "recheck_required"


def test_candidate_agreement_ok_stays_validated(tmp_path):
    svc = _validated_judge(tmp_path)
    judge = svc.candidate_drift_recheck(project="bourbon", judge_version="jv1",
                                        candidate_human_judge_agreement=0.9)
    assert judge["status"] == "validated"


def test_taxonomy_migration_marks_affected_judges(tmp_path):
    svc = _validated_judge(tmp_path)
    affected = svc.propagate_taxonomy_migration(
        project="bourbon",
        changed_label_slugs={"tool_argument_error"},
        judge_label_slugs={"jv1": {"tool_argument_error", "retrieval_miss"}},
    )
    assert affected == ["jv1"]
    assert svc.get(project="bourbon", judge_version="jv1")["status"] == "recheck_required"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_judge_drift.py -v`
Expected: FAIL with `AttributeError: ... 'candidate_drift_recheck'`.

- [ ] **Step 3: Append implementation to `judge.py`**

```python
# flywheel/engine/judge.py  (append to JudgeService)
    def candidate_drift_recheck(self, *, project: str, judge_version: str,
                                candidate_human_judge_agreement: float) -> dict:
        judge = self.get(project=project, judge_version=judge_version)
        judge["last_candidate_agreement"] = candidate_human_judge_agreement
        if candidate_human_judge_agreement < self._threshold:
            judge["status"] = "recheck_required"
        return self._save(judge)

    def propagate_taxonomy_migration(self, *, project: str,
                                     changed_label_slugs: set[str],
                                     judge_label_slugs: dict[str, set[str]]) -> list[str]:
        affected: list[str] = []
        for judge in self._store.list("judges", project=project):
            if judge["status"] not in ("validated", "validated_limited"):
                continue
            used = judge_label_slugs.get(judge["judge_version"], set())
            if used & changed_label_slugs:
                judge["status"] = "recheck_required"
                self._save(judge)
                affected.append(judge["judge_version"])
        return affected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_judge_drift.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/judge.py flywheel/tests/engine/test_judge_drift.py
git commit -m "feat(engine): candidate drift recheck and taxonomy-migration propagation"
```

---

## Task 4: Production drift sentinel (Phase 1.5 — schema + state transition)

**Files:**
- Modify: `flywheel/engine/judge.py` (append `record_drift_check`)
- Test: `flywheel/tests/engine/test_judge_sentinel.py`

**Interfaces:**
- Consumes: `JudgeDriftCheckModel` (plan 02 schemas).
- Produces (added to `JudgeService`):
  - `record_drift_check(*, project, judge_version, human_judge_agreement: float, distribution_drift: float, agreement_floor: float = 0.70, drift_ceiling: float = 0.30) -> dict` — Engine §11 production drift sentinel. Stores a `JudgeDriftCheck` row (collection `"judge_drift_checks"`). If `human_judge_agreement < agreement_floor` **or** `distribution_drift > drift_ceiling`, marks the judge `recheck_required` and moves every non-terminal proposal/regression depending on that judge in `regression_running` or `regression_review` to `blocked_on_judge_recheck`. For `regression_review`, use `assert_transition`; for `regression_running`, plan 02 has no direct transition even though Engine §11 requires the sentinel move, so perform an audited sentinel override when `AuditLog` is available. Returns `{"drift_check": ..., "judge_status": ..., "blocked_regressions": [...]}`.
  - MVP stance per index doc: cadence/sampling is manual; this implements the state transition only.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_judge_sentinel.py
from api.store import JsonRecordStore
from engine.judge import JudgeService


def _validated_judge(tmp_path):
    svc = JudgeService(JsonRecordStore(root=tmp_path))
    svc.create(project="bourbon", judge_version="jv1", task_family="tool_use",
               model="m", prompt_version="p1", taxonomy_version="tax1",
               train_dataset_id="d1", dev_dataset_id="d2", locked_test_dataset_id="d3")
    svc.validate_on_locked_test(project="bourbon", judge_version="jv1", overall_f1=0.9)
    return svc


def test_healthy_drift_check_keeps_validated(tmp_path):
    svc = _validated_judge(tmp_path)
    out = svc.record_drift_check(project="bourbon", judge_version="jv1",
                                 human_judge_agreement=0.85, distribution_drift=0.1)
    assert out["judge_status"] == "validated"


def test_low_agreement_triggers_recheck(tmp_path):
    svc = _validated_judge(tmp_path)
    out = svc.record_drift_check(project="bourbon", judge_version="jv1",
                                 human_judge_agreement=0.5, distribution_drift=0.1)
    assert out["judge_status"] == "recheck_required"


def test_high_distribution_drift_triggers_recheck(tmp_path):
    svc = _validated_judge(tmp_path)
    out = svc.record_drift_check(project="bourbon", judge_version="jv1",
                                 human_judge_agreement=0.9, distribution_drift=0.5)
    assert out["judge_status"] == "recheck_required"


def test_drift_recheck_blocks_dependent_inflight_regressions(tmp_path):
    svc = _validated_judge(tmp_path)
    svc._store.put("proposals", "p_review", {"project": "bourbon", "id": "p_review",
        "state": "regression_review", "judge_version": "jv1"})
    svc._store.put("proposals", "p_running", {"project": "bourbon", "id": "p_running",
        "state": "regression_running", "judge_version": "jv1"})
    svc._store.put("proposals", "p_other", {"project": "bourbon", "id": "p_other",
        "state": "regression_review", "judge_version": "jv2"})
    out = svc.record_drift_check(project="bourbon", judge_version="jv1",
                                 human_judge_agreement=0.5, distribution_drift=0.1)
    assert set(out["blocked_regressions"]) == {"p_review", "p_running"}
    assert svc._store.get("proposals", "p_review")["state"] == "blocked_on_judge_recheck"
    assert svc._store.get("proposals", "p_running")["state"] == "blocked_on_judge_recheck"
    assert svc._store.get("proposals", "p_other")["state"] == "regression_review"


def test_drift_recheck_blocks_plan06_proposals_via_source_run(tmp_path):
    svc = _validated_judge(tmp_path)
    svc._store.put("runs", "run1", {"project": "bourbon", "id": "run1",
        "judge_version": "jv1"})
    svc._store.put("proposals", "p_from_run", {"project": "bourbon", "id": "p_from_run",
        "state": "regression_review", "source_eval_run_id": "run1"})
    out = svc.record_drift_check(project="bourbon", judge_version="jv1",
                                 human_judge_agreement=0.5, distribution_drift=0.1)
    assert out["blocked_regressions"] == ["p_from_run"]
    assert svc._store.get("proposals", "p_from_run")["state"] == "blocked_on_judge_recheck"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_judge_sentinel.py -v`
Expected: FAIL with `AttributeError: ... 'record_drift_check'`.

- [ ] **Step 3: Append implementation to `judge.py`**

```python
# flywheel/engine/judge.py  (append to JudgeService)
    def record_drift_check(self, *, project: str, judge_version: str,
                           human_judge_agreement: float, distribution_drift: float,
                           agreement_floor: float = 0.70,
                           drift_ceiling: float = 0.30) -> dict:
        import uuid
        from datetime import datetime, timezone
        from api.lifecycle import assert_transition
        judge = self.get(project=project, judge_version=judge_version)
        check_id = f"drift_{uuid.uuid4().hex[:12]}"
        self._store.put("judge_drift_checks", check_id, {
            "project": project, "judge_version": judge_version,
            "task_family": judge["task_family"],
            "sampled_at": datetime.now(timezone.utc).isoformat(),
            "human_judge_agreement": human_judge_agreement,
            "distribution_drift": distribution_drift,
        })
        blocked_regressions: list[str] = []
        if human_judge_agreement < agreement_floor or distribution_drift > drift_ceiling:
            judge["status"] = "recheck_required"
            self._save(judge)

            def proposal_uses_judge(prop: dict) -> bool:
                if prop.get("judge_version") == judge_version:
                    return True
                run_id = prop.get("source_eval_run_id")
                if not run_id:
                    return False
                run = self._store.get("runs", run_id)
                return run is not None and run.get("judge_version") == judge_version

            for prop in self._store.list("proposals", project=project):
                if not proposal_uses_judge(prop):
                    continue
                if prop.get("state") not in ("regression_running", "regression_review"):
                    continue
                before = dict(prop)
                if prop["state"] == "regression_review":
                    assert_transition("regression_review", "blocked_on_judge_recheck")
                # Engine §11 requires regression_running to block too; plan 02 has no
                # direct edge, so this is a sentinel override, not a normal proposal action.
                prop["state"] = "blocked_on_judge_recheck"
                self._store.put("proposals", prop["id"], prop)
                blocked_regressions.append(prop["id"])
                audit = getattr(self, "_audit", None)
                if audit is not None:
                    audit.record(project=project, actor="drift_sentinel",
                                 action="block_on_judge_recheck",
                                 target_type="proposal", target_id=prop["id"],
                                 before=before, after=prop)
        return {"drift_check": check_id, "judge_status": judge["status"],
                "blocked_regressions": blocked_regressions}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_judge_sentinel.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Run full suite + lint + types, then commit**

```bash
cd flywheel && pytest -q && ruff check api engine sdk tests && mypy api engine sdk
git add flywheel/engine/judge.py flywheel/tests/engine/test_judge_sentinel.py
git commit -m "feat(engine): production drift sentinel state transitions"
```

---

## Task 5: Wire judge and annotation API routes

**Files:**
- Modify: `flywheel/api/server.py`
- Test: `flywheel/tests/api/test_judge_routes.py`, `flywheel/tests/api/test_annotation_routes.py`

**Interfaces:**
- Consumes: `JudgeService`, `AnnotationModel`, `IdempotencyStore`, `AuditLog`, `require_role`.
- Produces the plan-05 endpoints assigned in `2026-06-23-flywheel-00-index.md`:
  - `GET /api/judges`
  - `GET /api/judges/{version}`
  - `POST /api/judges`
  - `POST /api/judges/{judge_version}/validate`
  - `GET /api/annotations`
  - `POST /api/annotations`
  - `GET /api/annotations/{id}`
  - `POST /api/annotations/{id}`
- Mutations require `Idempotency-Key`, return the updated object plus `audit_event_id`, and duplicate submits return the existing result.
- Judge creation/validation requires `judge_owner`. Annotation create/update requires `dataset_curator` or `judge_owner`, because human labels can be produced by calibration or curation workflows.
- Judge read responses include derived `validation_phase`, never a persisted `locked_test` status. `validation_phase` may be `"locked_test"` when `status == "calibrating"` and `metrics.prompt_locked_for_locked_test == True`; otherwise it mirrors `status`.

- [ ] **Step 1: Write the failing route tests**

```python
# flywheel/tests/api/test_judge_routes.py
from pathlib import Path
from fastapi.testclient import TestClient
from api.auth import Principal
from api.server import create_app


def _client(tmp_path: Path, roles=("judge_owner",)):
    principal = Principal(actor_id="alice", roles=frozenset(roles))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    return TestClient(app), app


def test_create_judge_is_idempotent_and_audited(tmp_path):
    client, _ = _client(tmp_path)
    body = {"project": "bourbon", "judge_version": "jv1",
        "task_family": "tool_use", "model": "m", "prompt_version": "p1",
        "taxonomy_version": "tax1", "train_dataset_id": "train",
        "dev_dataset_id": "dev", "locked_test_dataset_id": "locked"}
    r1 = client.post("/api/judges", json=body, headers={"Idempotency-Key": "judge-1"})
    r2 = client.post("/api/judges", json=body, headers={"Idempotency-Key": "judge-1"})
    assert r1.status_code == 200
    assert r1.json() == r2.json()
    assert r1.json()["judge"]["status"] == "draft"
    assert r1.json()["judge"]["validation_phase"] == "draft"
    assert "audit_event_id" in r1.json()


def test_validate_judge_returns_display_phase_without_locked_test_status(tmp_path):
    client, _ = _client(tmp_path)
    body = {"project": "bourbon", "judge_version": "jv1",
        "task_family": "tool_use", "model": "m", "prompt_version": "p1",
        "taxonomy_version": "tax1", "train_dataset_id": "train",
        "dev_dataset_id": "dev", "locked_test_dataset_id": "locked"}
    client.post("/api/judges", json=body, headers={"Idempotency-Key": "judge-1"})
    r = client.post("/api/judges/jv1/validate",
                    json={"project": "bourbon", "overall_f1": 0.9},
                    headers={"Idempotency-Key": "validate-1"})
    assert r.status_code == 200
    assert r.json()["judge"]["status"] == "validated"
    assert r.json()["judge"]["validation_phase"] == "validated"


def test_judge_route_wiring_keeps_plan02_runs_list_working(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("runs", "run1", {"project": "bourbon", "id": "run1",
        "state": "collecting"})
    r = client.get("/api/runs", params={"project": "bourbon"})
    assert r.status_code == 200
    assert r.json()["runs"][0]["id"] == "run1"
```

```python
# flywheel/tests/api/test_annotation_routes.py
from pathlib import Path
from fastapi.testclient import TestClient
from api.auth import Principal
from api.server import create_app


def _client(tmp_path: Path, roles=("dataset_curator",)):
    principal = Principal(actor_id="alice", roles=frozenset(roles))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    return TestClient(app), app


def test_create_annotation_is_idempotent_and_audited(tmp_path):
    client, _ = _client(tmp_path)
    body = {"project": "bourbon", "id": "ann1", "eval_run_id": "run1",
        "case_id": "c1", "sample_id": "s0", "label": "fail",
        "source": "human", "failure_labels": ["tool_argument_error"],
        "confidence": 0.9, "critique": "bad args",
        "annotated_by": "alice", "annotation_rubric_version": "rubric1"}
    r1 = client.post("/api/annotations", json=body,
                     headers={"Idempotency-Key": "ann-1"})
    r2 = client.post("/api/annotations", json=body,
                     headers={"Idempotency-Key": "ann-1"})
    assert r1.status_code == 200
    assert r1.json() == r2.json()
    assert r1.json()["annotation"]["id"] == "ann1"
    assert "audit_event_id" in r1.json()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd flywheel
pytest tests/api/test_judge_routes.py tests/api/test_annotation_routes.py -v
```

Expected: FAIL because the plan-02 stubs do not yet implement these routes.

- [ ] **Step 3: Wire routes in `server.py`**

Add services/helpers:

```python
    from engine.judge import JudgeService
    judges = JudgeService(store, audit=audit)

    # Unique name: do not shadow plan 02's _idempotent(key, build) helper.
    def _idempotent_judge_mutation(request: Request, compute):
        key = request.headers.get("Idempotency-Key")
        if not key:
            raise HTTPException(status_code=400, detail="Idempotency-Key required")
        prior = idem.lookup(key)
        if prior is not None:
            return prior
        result = compute()
        idem.remember(key, result)
        return result

    def _can_annotate(principal):
        if "dataset_curator" not in principal.roles and "judge_owner" not in principal.roles:
            require_role(principal, "dataset_curator")

    def _judge_response(judge: dict) -> dict:
        out = dict(judge)
        metrics = out.get("metrics", {})
        out["validation_phase"] = (
            "locked_test"
            if out["status"] == "calibrating" and metrics.get("prompt_locked_for_locked_test")
            else out["status"]
        )
        return out
```

Add route-local request models before the route snippets:

```python
    from pydantic import BaseModel
    from api.schemas import AnnotationModel

    class JudgeCreateBody(BaseModel):
        project: str
        judge_version: str
        task_family: str
        model: str
        prompt_version: str
        taxonomy_version: str
        train_dataset_id: str
        dev_dataset_id: str
        locked_test_dataset_id: str

    class JudgeValidateBody(BaseModel):
        project: str
        overall_f1: float
        max_reuse: int = 3
```

Add route snippets:

```python
    @app.get("/api/judges")
    def list_judges(project: str):
        return {"judges": [_judge_response(j) for j in store.list("judges", project=project)]}

    @app.get("/api/judges/{version}")
    def get_judge(version: str, project: str):
        judge = judges.get(project=project, judge_version=version)
        return {"judge": _judge_response(judge)}

    @app.post("/api/judges")
    def create_judge(body: JudgeCreateBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "judge_owner")
        def compute():
            judge = judges.create(**body.model_dump())
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action="create_judge", target_type="judge",
                               target_id=judge["id"], before=None, after=judge)
            return {"judge": _judge_response(judge), "audit_event_id": aid}
        return _idempotent_judge_mutation(request, compute)

    @app.post("/api/judges/{judge_version}/validate")
    def validate_judge(judge_version: str, body: JudgeValidateBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "judge_owner")
        def compute():
            before = judges.get(project=body.project, judge_version=judge_version)
            judge = judges.validate_on_locked_test(project=body.project,
                judge_version=judge_version, overall_f1=body.overall_f1,
                max_reuse=body.max_reuse)
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action="validate_judge", target_type="judge",
                               target_id=judge["id"], before=before, after=judge)
            return {"judge": _judge_response(judge), "audit_event_id": aid}
        return _idempotent_judge_mutation(request, compute)

    @app.get("/api/annotations")
    def list_annotations(project: str, eval_run_id: str | None = None):
        where = {"eval_run_id": eval_run_id} if eval_run_id else None
        return {"annotations": store.list("annotations", project=project, where=where)}

    @app.get("/api/annotations/{annotation_id}")
    def get_annotation(annotation_id: str):
        ann = store.get("annotations", annotation_id)
        if ann is None:
            raise HTTPException(status_code=404, detail="annotation not found")
        return {"annotation": ann}

    @app.post("/api/annotations")
    def create_annotation(body: AnnotationModel, request: Request):
        principal = principal_resolver(request)
        _can_annotate(principal)
        def compute():
            ann = store.put("annotations", body.id, body.model_dump())
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action="create_annotation", target_type="annotation",
                               target_id=body.id, before=None, after=ann)
            return {"annotation": ann, "audit_event_id": aid}
        return _idempotent_judge_mutation(request, compute)

    @app.post("/api/annotations/{annotation_id}")
    def update_annotation(annotation_id: str, body: AnnotationModel, request: Request):
        principal = principal_resolver(request)
        _can_annotate(principal)
        if body.id != annotation_id:
            raise HTTPException(status_code=400, detail="annotation id mismatch")
        def compute():
            before = store.get("annotations", annotation_id)
            ann = store.put("annotations", annotation_id, body.model_dump())
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action="update_annotation", target_type="annotation",
                               target_id=annotation_id, before=before, after=ann)
            return {"annotation": ann, "audit_event_id": aid}
        return _idempotent_judge_mutation(request, compute)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd flywheel
pytest tests/api/test_judge_routes.py tests/api/test_annotation_routes.py -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite + lint + types, then commit**

```bash
cd flywheel && pytest -q && ruff check api engine sdk tests && mypy api engine sdk
git add flywheel/api/server.py flywheel/tests/api/test_judge_routes.py flywheel/tests/api/test_annotation_routes.py
git commit -m "feat(api): judge and annotation routes"
```

---

## Self-Review

- **Spec coverage (Engine §11):** `create`/`calibrate` cover the calibration protocol with F1 threshold + per-label precision/recall; `validate_on_locked_test` covers the locked-test gate and rotation (`validated_limited` on reuse overflow); API responses expose derived `validation_phase` for UI locked-test display without persisting a parallel status; `candidate_drift_recheck` covers the candidate human-audit agreement gate that blocks publish and moves to `recheck_required`; `propagate_taxonomy_migration` implements §5/§11 "migration touching a validated judge's labels → recheck_required"; `record_drift_check` implements the production drift sentinel state transition and blocks dependent in-flight regressions. The API route task covers every plan-05 endpoint assigned by the index.
- **Placeholder scan:** no TODO; every step has complete code. The Phase-1.5 manual-cadence note is a scope statement, not a placeholder — the state transition is fully implemented.
- **Type consistency:** `JudgeState` values used here (`draft, calibrating, validated, validated_limited, rejected, recheck_required`) match plan 02 `lifecycle.JudgeState` exactly (no persisted `locked_test` status). `validation_phase` is an API/display field, not State Store truth. `changed_labels` input to `propagate_taxonomy_migration` is `set[str]`, matching plan 04's `TaxonomyRegistry.changed_labels` return type. `precision_recall_f1` signature matches plan 01. Plan 07 calls `candidate_drift_recheck` and reads `status == "recheck_required"` to drive `blocked_on_judge_recheck`.
