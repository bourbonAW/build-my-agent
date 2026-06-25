> **⚠️ SUPERSEDED (lean revision 2026-06-24).** Do not implement. The holdout
> ledger, Bonferroni/FDR correction, and publish/rollback/revert state machine are
> replaced by `regression.py` (3-value `better|no_change|worse` + Wilson noise
> band) in plan `01-sdk` Task 4 — see `specs/2026-06-22-flywheel-engine-design.md`
> §7. Live plans: `00-index`, `01-sdk`, `02-control-plane`.

# Flywheel 07 — Regression Gate + Publish/Rollback/Revert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the regression gate that decides whether a candidate harness becomes a new baseline: mechanical holdout integrity (consumed-case exclusion + split intersection checks), the `RegressionHoldoutLedger` with multiple-comparison accounting, same-judge comparison enforcement, statistical comparison with confidence intervals and a noise band, candidate judge recheck, and the proposal lifecycle transitions that wire into `BaselineService` publish/rollback/revert.

**Architecture:** `flywheel/engine/validator.py` orchestrates the gate, calling `sdk.metrics` for stats, plan 02 `lifecycle.assert_transition`, plan 02 `BaselineService`, and plan 05 `JudgeService`. All publish/rollback/revert decisions are compare-and-set transitions emitting audit events. Synchronous.

**Tech Stack:** Python 3.13, pydantic v2, pytest.

## Global Constraints

(See `2026-06-23-flywheel-00-index.md`.) Most relevant here:
- Regression uses only `regression_holdout` cases, excludes `consumed_case_ids`; any non-empty intersection between `regression_holdout` and `consumed_case_ids`, `train`, `dev`, or `locked_test` blocks publish until fresh/rotated holdout cases are available.
- Same-judge comparison: baseline + candidate scored with the same `judge_version`, else `judge_migration_required` and publish blocked.
- Multiple-comparison correction uses `distinct_hypothesis_count` (keyed by `candidate_hypothesis_id`), not raw run count.
- Noise band: deltas inside the minimum meaningful delta → `no_significant_change`, not publish.
- Publish/rollback/post-publish revert require harness-owner authorization (enforced at API layer, plan 02) and are human gates.
- Lifecycle transitions use plan 02 `assert_transition`.

---

## File Structure

- Create: `flywheel/engine/holdout.py` — holdout integrity + `HoldoutLedger`
- Create: `flywheel/engine/stats.py` — delta, CI, noise band, multiple-comparison threshold
- Create: `flywheel/engine/validator.py` — orchestrates the gate + lifecycle transitions
- Modify: `flywheel/api/server.py` — regression + proposal mutation routes
- Test: mirrors under `flywheel/tests/`

**Interfaces consumed:** `wilson_interval`/`ConfidenceInterval` (`sdk.metrics`, plan 01); `assert_transition`/`RegressionOutcome`/`ProposalState` (`api.lifecycle`, plan 02); `BaselineService` (plan 02); `RegressionHoldoutLedgerModel`/`RegressionResultModel` (plan 02 schemas); `JudgeService` (plan 05); `candidate_hypothesis_id` (plan 06).

---

## Task 1: Holdout integrity checks

**Files:**
- Create: `flywheel/engine/holdout.py`
- Test: `flywheel/tests/engine/test_holdout.py`

**Interfaces:**
- Produces:
  - `@dataclass class HoldoutIntegrity` with `candidate_holdout: list[str]`, `consumed_intersection: list[str]`, `train_intersection: list[str]`, `dev_intersection: list[str]`, `locked_test_intersection: list[str]`, `publish_blocked: bool`.
  - `compute_holdout_integrity(*, regression_holdout: set[str], consumed: set[str], train: set[str], dev: set[str], locked_test: set[str]) -> HoldoutIntegrity` — Engine §14: `candidate_holdout = regression_holdout - consumed`; reports all four intersections; `publish_blocked` True if any of consumed/train/dev/locked_test intersect the holdout. A consumed intersection means the proposer saw holdout evidence, so publish is blocked until fresh or rotated holdout cases are curated.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_holdout.py
from engine.holdout import compute_holdout_integrity


def test_consumed_cases_excluded_and_block_publish():
    integrity = compute_holdout_integrity(
        regression_holdout={"c1", "c2", "c3"}, consumed={"c2"},
        train=set(), dev=set(), locked_test=set())
    assert set(integrity.candidate_holdout) == {"c1", "c3"}
    assert integrity.consumed_intersection == ["c2"]
    assert integrity.publish_blocked is True


def test_locked_test_overlap_blocks_publish():
    integrity = compute_holdout_integrity(
        regression_holdout={"c1", "c2"}, consumed=set(),
        train=set(), dev=set(), locked_test={"c2"})
    assert integrity.locked_test_intersection == ["c2"]
    assert integrity.publish_blocked is True


def test_train_overlap_blocks_publish():
    integrity = compute_holdout_integrity(
        regression_holdout={"c1"}, consumed=set(),
        train={"c1"}, dev=set(), locked_test=set())
    assert integrity.publish_blocked is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_holdout.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.holdout'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/holdout.py
"""Mechanical holdout integrity checks (Engine §14)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HoldoutIntegrity:
    candidate_holdout: list[str]
    consumed_intersection: list[str]
    train_intersection: list[str]
    dev_intersection: list[str]
    locked_test_intersection: list[str]
    publish_blocked: bool


def compute_holdout_integrity(*, regression_holdout: set[str], consumed: set[str],
                              train: set[str], dev: set[str],
                              locked_test: set[str]) -> HoldoutIntegrity:
    candidate_holdout = regression_holdout - consumed
    train_x = sorted(regression_holdout & train)
    dev_x = sorted(regression_holdout & dev)
    locked_x = sorted(regression_holdout & locked_test)
    consumed_x = sorted(regression_holdout & consumed)
    publish_blocked = bool(consumed_x or train_x or dev_x or locked_x)
    return HoldoutIntegrity(
        candidate_holdout=sorted(candidate_holdout),
        consumed_intersection=consumed_x,
        train_intersection=train_x, dev_intersection=dev_x,
        locked_test_intersection=locked_x, publish_blocked=publish_blocked,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_holdout.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/holdout.py flywheel/tests/engine/test_holdout.py
git commit -m "feat(engine): mechanical holdout integrity checks"
```

---

## Task 2: HoldoutLedger — multiple-comparison accounting

**Files:**
- Modify: `flywheel/engine/holdout.py` (append `HoldoutLedger`)
- Test: `flywheel/tests/engine/test_holdout_ledger.py`

**Interfaces:**
- Consumes: `JsonRecordStore` (plan 02), `RegressionHoldoutLedgerModel` (plan 02 schemas).
- Produces:
  - `class HoldoutLedger(store: JsonRecordStore)`:
    - `register_run(*, project, dataset_id, dataset_version, holdout_case_ids: list[str], candidate_hypothesis_id: str, policy: str = "bonferroni") -> dict` — increments `raw_regression_run_count`; adds the hypothesis id to `tested_hypothesis_ids` only if new (re-runs of the same hypothesis do not increase `distinct_hypothesis_count`); updates `distinct_hypothesis_count`. Ledger id = `f"{dataset_id}:{dataset_version}"`.
    - `adjusted_alpha(*, dataset_id, dataset_version, base_alpha: float = 0.05) -> float` — Bonferroni: `base_alpha / max(1, distinct_hypothesis_count)`; `none` policy returns `base_alpha`.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_holdout_ledger.py
from api.store import JsonRecordStore
from engine.holdout import HoldoutLedger


def test_rerun_same_hypothesis_does_not_increase_distinct(tmp_path):
    led = HoldoutLedger(JsonRecordStore(root=tmp_path))
    led.register_run(project="bourbon", dataset_id="ds1", dataset_version="v1",
                     holdout_case_ids=["c1"], candidate_hypothesis_id="p1::fpA")
    row = led.register_run(project="bourbon", dataset_id="ds1", dataset_version="v1",
                           holdout_case_ids=["c1"], candidate_hypothesis_id="p1::fpA")
    assert row["raw_regression_run_count"] == 2
    assert row["distinct_hypothesis_count"] == 1  # same hypothesis re-run


def test_new_hypothesis_increases_distinct(tmp_path):
    led = HoldoutLedger(JsonRecordStore(root=tmp_path))
    led.register_run(project="bourbon", dataset_id="ds1", dataset_version="v1",
                     holdout_case_ids=["c1"], candidate_hypothesis_id="p1::fpA")
    row = led.register_run(project="bourbon", dataset_id="ds1", dataset_version="v1",
                           holdout_case_ids=["c1"], candidate_hypothesis_id="p2::fpB")
    assert row["distinct_hypothesis_count"] == 2


def test_bonferroni_tightens_alpha(tmp_path):
    led = HoldoutLedger(JsonRecordStore(root=tmp_path))
    for hyp in ("p1::a", "p2::b", "p3::c", "p4::d"):
        led.register_run(project="bourbon", dataset_id="ds1", dataset_version="v1",
                         holdout_case_ids=["c1"], candidate_hypothesis_id=hyp)
    alpha = led.adjusted_alpha(dataset_id="ds1", dataset_version="v1", base_alpha=0.05)
    assert abs(alpha - 0.0125) < 1e-9  # 0.05 / 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_holdout_ledger.py -v`
Expected: FAIL with `ImportError: cannot import name 'HoldoutLedger'`.

- [ ] **Step 3: Append implementation to `holdout.py`**

```python
# flywheel/engine/holdout.py  (append)
from api.store import JsonRecordStore


class HoldoutLedger:
    def __init__(self, store: JsonRecordStore):
        self._store = store

    def _id(self, dataset_id: str, dataset_version: str) -> str:
        return f"{dataset_id}:{dataset_version}"

    def register_run(self, *, project: str, dataset_id: str, dataset_version: str,
                     holdout_case_ids: list[str], candidate_hypothesis_id: str,
                     policy: str = "bonferroni") -> dict:
        ledger_id = self._id(dataset_id, dataset_version)
        row = self._store.get("holdout_ledgers", ledger_id) or {
            "project": project, "dataset_id": dataset_id,
            "dataset_version": dataset_version, "holdout_case_ids": holdout_case_ids,
            "tested_hypothesis_ids": [], "distinct_hypothesis_count": 0,
            "raw_regression_run_count": 0, "published_candidate_count": 0,
            "last_cold_case_refresh_at": "", "multiple_comparison_policy": policy,
        }
        row["raw_regression_run_count"] += 1
        if candidate_hypothesis_id not in row["tested_hypothesis_ids"]:
            row["tested_hypothesis_ids"].append(candidate_hypothesis_id)
        row["distinct_hypothesis_count"] = len(row["tested_hypothesis_ids"])
        row["multiple_comparison_policy"] = policy
        return self._store.put("holdout_ledgers", ledger_id, row)

    def adjusted_alpha(self, *, dataset_id: str, dataset_version: str,
                       base_alpha: float = 0.05) -> float:
        row = self._store.get("holdout_ledgers", self._id(dataset_id, dataset_version))
        if row is None:
            return base_alpha
        if row["multiple_comparison_policy"] == "none":
            return base_alpha
        # bonferroni / fdr-as-bonferroni-floor in MVP
        return base_alpha / max(1, row["distinct_hypothesis_count"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_holdout_ledger.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/holdout.py flywheel/tests/engine/test_holdout_ledger.py
git commit -m "feat(engine): holdout ledger with multiple-comparison accounting"
```

---

## Task 3: Statistical comparison + noise band

**Files:**
- Create: `flywheel/engine/stats.py`
- Test: `flywheel/tests/engine/test_stats.py`

**Interfaces:**
- Consumes: `wilson_interval`, `ConfidenceInterval` (`sdk.metrics`, plan 01).
- Produces:
  - `@dataclass class RegressionComparison` with `baseline_rate: float`, `candidate_rate: float`, `delta: float`, `baseline_ci: ConfidenceInterval`, `candidate_ci: ConfidenceInterval`, `within_noise_band: bool`, `ci_overlaps: bool`.
  - `compare_pass_rates(*, baseline_pass: int, baseline_n: int, candidate_pass: int, candidate_n: int, min_meaningful_delta: float) -> RegressionComparison` — Engine §14: computes Wilson CIs for both, `delta = candidate_rate - baseline_rate`, `within_noise_band = abs(delta) < min_meaningful_delta`, `ci_overlaps` when the two intervals overlap.
  - `classify_outcome(comparison: RegressionComparison, *, has_critical_safety_regression: bool) -> str` — returns one of `"published" | "rolled_back" | "no_significant_change"` (a subset of `RegressionOutcome`): safety regression → `rolled_back`; within noise band or overlapping CIs → `no_significant_change`; positive delta beyond band with no safety regression → `published`; negative delta beyond band → `rolled_back`.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_stats.py
from engine.stats import compare_pass_rates, classify_outcome


def test_meaningful_improvement_publishes():
    cmp = compare_pass_rates(baseline_pass=60, baseline_n=100,
                             candidate_pass=85, candidate_n=100,
                             min_meaningful_delta=0.05)
    assert cmp.delta > 0
    assert cmp.within_noise_band is False
    assert classify_outcome(cmp, has_critical_safety_regression=False) == "published"


def test_small_delta_is_no_significant_change():
    cmp = compare_pass_rates(baseline_pass=70, baseline_n=100,
                             candidate_pass=72, candidate_n=100,
                             min_meaningful_delta=0.05)
    assert cmp.within_noise_band is True
    assert classify_outcome(cmp, has_critical_safety_regression=False) == "no_significant_change"


def test_safety_regression_rolls_back_even_if_improved():
    cmp = compare_pass_rates(baseline_pass=60, baseline_n=100,
                             candidate_pass=90, candidate_n=100,
                             min_meaningful_delta=0.05)
    assert classify_outcome(cmp, has_critical_safety_regression=True) == "rolled_back"


def test_meaningful_regression_rolls_back():
    cmp = compare_pass_rates(baseline_pass=85, baseline_n=100,
                             candidate_pass=60, candidate_n=100,
                             min_meaningful_delta=0.05)
    assert cmp.delta < 0
    assert classify_outcome(cmp, has_critical_safety_regression=False) == "rolled_back"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_stats.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.stats'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/stats.py
"""Statistical regression comparison with noise band (Engine §14)."""
from __future__ import annotations

from dataclasses import dataclass

from sdk.metrics import ConfidenceInterval, wilson_interval


@dataclass
class RegressionComparison:
    baseline_rate: float
    candidate_rate: float
    delta: float
    baseline_ci: ConfidenceInterval
    candidate_ci: ConfidenceInterval
    within_noise_band: bool
    ci_overlaps: bool


def compare_pass_rates(*, baseline_pass: int, baseline_n: int, candidate_pass: int,
                       candidate_n: int, min_meaningful_delta: float) -> RegressionComparison:
    baseline_ci = wilson_interval(successes=baseline_pass, n=baseline_n)
    candidate_ci = wilson_interval(successes=candidate_pass, n=candidate_n)
    delta = candidate_ci.point - baseline_ci.point
    overlaps = not (candidate_ci.low > baseline_ci.high
                    or baseline_ci.low > candidate_ci.high)
    return RegressionComparison(
        baseline_rate=baseline_ci.point, candidate_rate=candidate_ci.point,
        delta=delta, baseline_ci=baseline_ci, candidate_ci=candidate_ci,
        within_noise_band=abs(delta) < min_meaningful_delta, ci_overlaps=overlaps,
    )


def classify_outcome(comparison: RegressionComparison, *,
                     has_critical_safety_regression: bool) -> str:
    if has_critical_safety_regression:
        return "rolled_back"
    if comparison.within_noise_band or comparison.ci_overlaps:
        return "no_significant_change"
    return "published" if comparison.delta > 0 else "rolled_back"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_stats.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/stats.py flywheel/tests/engine/test_stats.py
git commit -m "feat(engine): statistical comparison with noise band and outcome classifier"
```

---

## Task 4: Validator — orchestrate the gate + lifecycle transitions

**Files:**
- Create: `flywheel/engine/validator.py`
- Test: `flywheel/tests/engine/test_validator.py`

**Interfaces:**
- Consumes: `HoldoutIntegrity`/`compute_holdout_integrity` (`engine.holdout`), `compare_pass_rates`/`classify_outcome` (`engine.stats`), `assert_transition` (`api.lifecycle`), `JsonRecordStore`/`AuditLog`/`BaselineService` (plan 02), `JudgeService` (plan 05).
- Produces:
  - `@dataclass class RegressionDecision` with `outcome: str`, `proposal_state: str`, `publish_blocked: bool`, `reason: str`. `outcome` may be an internal decision code such as `"holdout_leakage"` for invalid comparisons; internal blocked codes are not persisted `RegressionOutcome` values and are not lifecycle states.
  - `class RegressionValidator(store, audit, baselines: BaselineService, judges: JudgeService)`:
    - `decide(*, project, proposal: dict, integrity: HoldoutIntegrity, baseline_judge_version: str, candidate_judge_version: str, comparison, has_critical_safety_regression: bool, candidate_human_judge_agreement: float | None) -> RegressionDecision` — applies the gate order:
      1. If `integrity.publish_blocked` → outcome `"holdout_leakage"`, proposal stays in its current state (`proposal_state=frm`), `publish_blocked=True`. This is an invalid/blocked comparison, not a candidate rollback/quality outcome, not a persisted `RegressionOutcome`, and not a lifecycle state.
      2. If `baseline_judge_version != candidate_judge_version` → outcome `judge_migration_required`, transition `regression_review → blocked_on_judge_migration`.
      3. If `candidate_human_judge_agreement` is not None and below judge threshold → trigger `judges.candidate_drift_recheck`; if it returns `recheck_required` → outcome `judge_recheck_required`, transition `→ blocked_on_judge_recheck`.
      4. Else outcome = `classify_outcome(...)`; map to transition: `published → validated`, `rolled_back → rolled_back`, `no_significant_change → no_significant_change`.
    - `publish(*, project, proposal_id, candidate_fingerprint, actor) -> dict` — loads the proposal and current `Baseline`, verifies the proposal's `baseline_generation` and `baseline_fingerprint` match the current baseline, and blocks by moving the proposal to `baseline_stale` when they do not. On success, calls `baselines.publish(...)`, transitions and persists the publishing proposal to `validated`, marks only non-terminal proposals from the superseded generation `baseline_stale` (Engine §13 rebase), and returns the new baseline + publishing proposal + stale proposal ids + `audit_event_id`.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_validator.py
from api.store import JsonRecordStore
from api.audit import AuditLog
from api.baselines import BaselineService
from engine.judge import JudgeService
from engine.holdout import compute_holdout_integrity
from engine.stats import compare_pass_rates
from engine.validator import RegressionValidator


def _validator(tmp_path):
    store = JsonRecordStore(root=tmp_path)
    audit = AuditLog(store)
    judges = JudgeService(store)
    judges.create(project="bourbon", judge_version="jv1", task_family="tool_use",
                  model="m", prompt_version="p1", taxonomy_version="tax1",
                  train_dataset_id="train", dev_dataset_id="dev",
                  locked_test_dataset_id="locked")
    judges.validate_on_locked_test(project="bourbon", judge_version="jv1",
                                   overall_f1=0.9)
    return RegressionValidator(store, audit, BaselineService(store, audit),
                               judges), store


def _clean_integrity():
    return compute_holdout_integrity(regression_holdout={"c1", "c2"}, consumed=set(),
                                     train=set(), dev=set(), locked_test=set())


def _good_comparison():
    return compare_pass_rates(baseline_pass=60, baseline_n=100,
                              candidate_pass=85, candidate_n=100,
                              min_meaningful_delta=0.05)


def test_clean_meaningful_win_validates(tmp_path):
    v, _ = _validator(tmp_path)
    decision = v.decide(project="bourbon", proposal={"id": "p1", "state": "regression_review"},
        integrity=_clean_integrity(), baseline_judge_version="jv1",
        candidate_judge_version="jv1", comparison=_good_comparison(),
        has_critical_safety_regression=False, candidate_human_judge_agreement=0.9)
    assert decision.outcome == "published"
    assert decision.proposal_state == "validated"
    assert decision.publish_blocked is False


def test_holdout_leakage_blocks(tmp_path):
    v, _ = _validator(tmp_path)
    leaky = compute_holdout_integrity(regression_holdout={"c1"}, consumed=set(),
        train=set(), dev=set(), locked_test={"c1"})
    decision = v.decide(project="bourbon", proposal={"id": "p1", "state": "regression_review"},
        integrity=leaky, baseline_judge_version="jv1", candidate_judge_version="jv1",
        comparison=_good_comparison(), has_critical_safety_regression=False,
        candidate_human_judge_agreement=0.9)
    assert decision.publish_blocked is True
    assert decision.outcome == "holdout_leakage"
    assert decision.proposal_state == "regression_review"
    assert "leakage" in decision.reason


def test_consumed_holdout_overlap_blocks(tmp_path):
    v, _ = _validator(tmp_path)
    leaky = compute_holdout_integrity(regression_holdout={"c1", "c2"}, consumed={"c2"},
        train=set(), dev=set(), locked_test=set())
    decision = v.decide(project="bourbon", proposal={"id": "p1", "state": "regression_review"},
        integrity=leaky, baseline_judge_version="jv1", candidate_judge_version="jv1",
        comparison=_good_comparison(), has_critical_safety_regression=False,
        candidate_human_judge_agreement=0.9)
    assert decision.publish_blocked is True
    assert decision.outcome == "holdout_leakage"
    assert decision.proposal_state == "regression_review"
    assert "consumed" in decision.reason


def test_judge_mismatch_requires_migration(tmp_path):
    v, _ = _validator(tmp_path)
    decision = v.decide(project="bourbon", proposal={"id": "p1", "state": "regression_review"},
        integrity=_clean_integrity(), baseline_judge_version="jv1",
        candidate_judge_version="jv2", comparison=_good_comparison(),
        has_critical_safety_regression=False, candidate_human_judge_agreement=0.9)
    assert decision.outcome == "judge_migration_required"
    assert decision.proposal_state == "blocked_on_judge_migration"


def test_publish_marks_other_proposals_stale(tmp_path):
    v, store = _validator(tmp_path)
    store.put("baselines", "bourbon:gen1", {"project": "bourbon", "generation": 1,
        "fingerprint": "fp0", "produced_by_proposal_id": None,
        "previous_generation": None, "published_at": "now", "status": "current"})
    store.put("proposals", "p1", {"project": "bourbon", "id": "p1",
        "state": "regression_review", "baseline_generation": 1,
        "baseline_fingerprint": "fp0"})
    store.put("proposals", "p_old", {"project": "bourbon", "id": "p_old",
        "state": "under_review", "baseline_generation": 1})
    store.put("proposals", "p_newer", {"project": "bourbon", "id": "p_newer",
        "state": "under_review", "baseline_generation": 2})
    v.publish(project="bourbon", proposal_id="p1", candidate_fingerprint="fpA",
              actor="alice")
    assert store.get("proposals", "p1")["state"] == "validated"
    refreshed = store.get("proposals", "p_old")
    assert refreshed["state"] == "baseline_stale"
    assert store.get("proposals", "p_newer")["state"] == "under_review"


def test_publish_blocks_stale_proposal(tmp_path):
    v, store = _validator(tmp_path)
    store.put("baselines", "bourbon:gen2", {"project": "bourbon", "generation": 2,
        "fingerprint": "fp2", "produced_by_proposal_id": "p0",
        "previous_generation": 1, "published_at": "now", "status": "current"})
    store.put("proposals", "p1", {"project": "bourbon", "id": "p1",
        "state": "regression_review", "baseline_generation": 1,
        "baseline_fingerprint": "fp1"})
    out = v.publish(project="bourbon", proposal_id="p1", candidate_fingerprint="fpA",
                    actor="alice")
    assert out["publish_blocked"] is True
    assert store.get("proposals", "p1")["state"] == "baseline_stale"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_validator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.validator'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/validator.py
"""Regression gate orchestration and lifecycle transitions (Engine §12, §14)."""
from __future__ import annotations

from dataclasses import dataclass

from api.audit import AuditLog
from api.baselines import BaselineService
from api.lifecycle import assert_transition
from api.store import JsonRecordStore
from engine.holdout import HoldoutIntegrity
from engine.judge import JudgeService
from engine.stats import RegressionComparison, classify_outcome


@dataclass
class RegressionDecision:
    outcome: str
    proposal_state: str
    publish_blocked: bool
    reason: str


_OUTCOME_TO_STATE = {
    "published": "validated",
    "rolled_back": "rolled_back",
    "no_significant_change": "no_significant_change",
}


class RegressionValidator:
    def __init__(self, store: JsonRecordStore, audit: AuditLog,
                 baselines: BaselineService, judges: JudgeService):
        self._store = store
        self._audit = audit
        self._baselines = baselines
        self._judges = judges

    def decide(self, *, project: str, proposal: dict, integrity: HoldoutIntegrity,
               baseline_judge_version: str, candidate_judge_version: str,
               comparison: RegressionComparison, has_critical_safety_regression: bool,
               candidate_human_judge_agreement: float | None) -> RegressionDecision:
        frm = proposal["state"]
        # 1) holdout leakage is an invalid comparison, not a persisted
        # RegressionOutcome and not a lifecycle state.
        if integrity.publish_blocked:
            intersections = []
            if integrity.consumed_intersection:
                intersections.append("consumed")
            if integrity.train_intersection:
                intersections.append("train")
            if integrity.dev_intersection:
                intersections.append("dev")
            if integrity.locked_test_intersection:
                intersections.append("locked_test")
            return RegressionDecision(outcome="holdout_leakage", proposal_state=frm,
                publish_blocked=True,
                reason="holdout leakage: "
                       f"{'/'.join(intersections)} intersect regression_holdout; "
                       "fresh or rotated holdout required before publish")
        # 2) same-judge comparison (Engine §14)
        if baseline_judge_version != candidate_judge_version:
            assert_transition(frm, "blocked_on_judge_migration")
            return RegressionDecision(outcome="judge_migration_required",
                proposal_state="blocked_on_judge_migration", publish_blocked=True,
                reason="baseline and candidate scored with different judge versions")
        # 3) candidate drift recheck (Engine §11)
        if candidate_human_judge_agreement is not None:
            judge = self._judges.candidate_drift_recheck(
                project=project, judge_version=candidate_judge_version,
                candidate_human_judge_agreement=candidate_human_judge_agreement)
            if judge["status"] == "recheck_required":
                assert_transition(frm, "blocked_on_judge_recheck")
                return RegressionDecision(outcome="judge_recheck_required",
                    proposal_state="blocked_on_judge_recheck", publish_blocked=True,
                    reason="candidate distribution invalidated the judge")
        # 4) statistical outcome
        outcome = classify_outcome(comparison,
            has_critical_safety_regression=has_critical_safety_regression)
        target_state = _OUTCOME_TO_STATE[outcome]
        assert_transition(frm, target_state)
        return RegressionDecision(outcome=outcome, proposal_state=target_state,
            publish_blocked=False, reason="statistical gate evaluated")

    def publish(self, *, project: str, proposal_id: str, candidate_fingerprint: str,
                actor: str) -> dict:
        proposal = self._store.get("proposals", proposal_id)
        if proposal is None:
            raise ValueError(f"unknown proposal {proposal_id}")
        current = self._baselines.current(project)
        if current is None:
            raise ValueError(f"project {project} has no current baseline")
        if (proposal.get("baseline_generation") != current.generation
                or proposal.get("baseline_fingerprint") != current.fingerprint):
            before = dict(proposal)
            assert_transition(proposal["state"], "baseline_stale")
            proposal["state"] = "baseline_stale"
            self._store.put("proposals", proposal_id, proposal)
            audit_event_id = self._audit.record(project=project, actor=actor,
                action="block_stale_proposal", target_type="proposal",
                target_id=proposal_id, before=before, after=proposal)
            return {"publish_blocked": True, "reason": "baseline stale",
                    "audit_event_id": audit_event_id, "stale_proposals": [proposal_id]}
        superseded_generation = current.generation
        proposal_before = dict(proposal)
        assert_transition(proposal["state"], "validated")
        baseline = self._baselines.publish(project=project,
            fingerprint=candidate_fingerprint, proposal_id=proposal_id, actor=actor)
        proposal["state"] = "validated"
        proposal = self._store.put("proposals", proposal_id, proposal)
        stale: list[str] = []
        terminal = {"validated", "rolled_back", "abandoned", "rejected",
                    "no_significant_change"}
        for prop in self._store.list("proposals", project=project):
            if prop["id"] == proposal_id:
                continue
            if prop.get("state") in terminal:
                continue
            if prop.get("baseline_generation") != superseded_generation:
                continue
            before = dict(prop)
            # Engine §13 baseline publication stales all non-terminal proposals on
            # the superseded generation. Plan 02 does not model baseline_stale as a
            # legal transition from every in-flight state, so this publication
            # cascade is an audited baseline-concurrency override.
            prop["state"] = "baseline_stale"
            self._store.put("proposals", prop["id"], prop)
            self._audit.record(project=project, actor=actor, action="mark_baseline_stale",
                               target_type="proposal", target_id=prop["id"],
                               before=before, after=prop)
            stale.append(prop["id"])
        audit_event_id = self._audit.record(project=project, actor=actor,
            action="publish_regression", target_type="proposal", target_id=proposal_id,
            before=proposal_before,
            after={"baseline_generation": baseline.generation, "proposal": proposal})
        return {"publish_blocked": False, "baseline_generation": baseline.generation,
                "proposal": proposal, "stale_proposals": stale,
                "audit_event_id": audit_event_id}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_validator.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/validator.py flywheel/tests/engine/test_validator.py
git commit -m "feat(engine): regression validator gate and lifecycle transitions"
```

---

## Task 5: Wire regression + proposal mutation routes into the server

**Files:**
- Modify: `flywheel/api/server.py`
- Test: `flywheel/tests/api/test_regression_routes.py`, `flywheel/tests/api/test_regression_block_routes.py`

**Interfaces:**
- Consumes: `RegressionValidator`, `BaselineService` (built in `create_app`), `IdempotencyStore`, `AuditLog`, role checks.
- Produces every plan-07 endpoint assigned in `2026-06-23-flywheel-00-index.md`, all `POST` mutations requiring `harness_owner`, `Idempotency-Key`, and returning the updated object plus `audit_event_id`:
  - `POST /api/proposals/{proposal_id}/approve` — transition `under_review → approved`.
  - `POST /api/proposals/{proposal_id}/reject` — transition `under_review → rejected`.
  - `POST /api/proposals/{proposal_id}/defer` — transition `under_review → deferred`.
  - `POST /api/regressions` — trigger regression for a proposal; transition `diff_review → regression_running`; create a `RegressionResult` row.
  - `GET /api/regressions/{regression_id}` — return regression result detail.
  - `POST /api/regressions/{regression_id}/publish` — calls `validator.publish(...)`, returns new baseline generation + stale proposals + `audit_event_id`.
  - `POST /api/regressions/{regression_id}/rollback` — records outcome `rolled_back`, transition to `rolled_back`.
  - `POST /api/regressions/{regression_id}/no-significant-change` — transition to `no_significant_change`.
  - `POST /api/regressions/{regression_id}/require-judge-recheck` — transition `regression_review → blocked_on_judge_recheck`.
  - `POST /api/regressions/{regression_id}/resume-after-judge-recheck` — transition `blocked_on_judge_recheck → regression_running`.
  - `POST /api/regressions/{regression_id}/require-judge-migration` — transition `regression_review → blocked_on_judge_migration`.
  - `POST /api/regressions/{regression_id}/resume-after-judge-migration` — transition `blocked_on_judge_migration → regression_review`.
  - On `IllegalTransition` → HTTP 409 (handler already wired in plan 02).

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/api/test_regression_routes.py
from pathlib import Path
from fastapi.testclient import TestClient
from api.schemas import RegressionResultModel
from api.server import create_app
from api.auth import Principal


def _client(tmp_path: Path, roles=("harness_owner",)):
    principal = Principal(actor_id="alice", roles=frozenset(roles))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    return TestClient(app), app


def test_approve_requires_harness_owner(tmp_path):
    client, app = _client(tmp_path, roles=("dataset_curator",))
    app.state.store.put("proposals", "p1", {"project": "bourbon", "id": "p1",
        "state": "under_review"})
    r = client.post("/api/proposals/p1/approve", json={"project": "bourbon"},
                    headers={"Idempotency-Key": "approve-1"})
    assert r.status_code == 403


def test_approve_transitions_state_idempotently(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("proposals", "p1", {"project": "bourbon", "id": "p1",
        "state": "under_review"})
    r1 = client.post("/api/proposals/p1/approve", json={"project": "bourbon"},
                     headers={"Idempotency-Key": "approve-1"})
    r2 = client.post("/api/proposals/p1/approve", json={"project": "bourbon"},
                     headers={"Idempotency-Key": "approve-1"})
    assert r1.status_code == 200
    assert r1.json() == r2.json()
    assert r1.json()["proposal"]["state"] == "approved"
    assert "audit_event_id" in r1.json()


def test_regression_route_wiring_keeps_plan02_runs_list_working(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("runs", "run1", {"project": "bourbon", "id": "run1",
        "state": "collecting"})
    r = client.get("/api/runs", params={"project": "bourbon"})
    assert r.status_code == 200
    assert r.json()["runs"][0]["id"] == "run1"


def test_reject_and_defer_routes(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("proposals", "p_reject", {"project": "bourbon", "id": "p_reject",
        "state": "under_review"})
    app.state.store.put("proposals", "p_defer", {"project": "bourbon", "id": "p_defer",
        "state": "under_review"})
    reject = client.post("/api/proposals/p_reject/reject", json={"project": "bourbon"},
                         headers={"Idempotency-Key": "reject-1"})
    defer = client.post("/api/proposals/p_defer/defer", json={"project": "bourbon"},
                        headers={"Idempotency-Key": "defer-1"})
    assert reject.json()["proposal"]["state"] == "rejected"
    assert defer.json()["proposal"]["state"] == "deferred"


def test_trigger_regression_creates_result_and_state(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("runs", "run1", {"project": "bourbon", "id": "run1",
        "judge_version": "jv1"})
    app.state.store.put("proposals", "p1", {"project": "bourbon", "id": "p1",
        "state": "diff_review", "baseline_fingerprint": "fp0",
        "candidate_fingerprint": "fpA", "source_eval_run_id": "run1"})
    r = client.post("/api/regressions", json={"project": "bourbon",
        "proposal_id": "p1", "candidate_fingerprint": "fpA"},
        headers={"Idempotency-Key": "reg-1"})
    assert r.status_code == 200
    assert r.json()["proposal"]["state"] == "regression_running"
    assert r.json()["regression"]["status"] == "running"
    assert r.json()["regression"]["proposal_id"] == "p1"
    stored = app.state.store.get("regressions", "p1")
    RegressionResultModel(**stored)
    assert "status" not in stored
    assert client.get("/api/regressions/p1").json()["regression"]["id"] == "p1"


def test_publish_returns_new_generation(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("baselines", "bourbon:gen1", {"project": "bourbon",
        "generation": 1, "fingerprint": "fp0", "produced_by_proposal_id": None,
        "previous_generation": None, "published_at": "now", "status": "current"})
    app.state.store.put("proposals", "p1", {"project": "bourbon", "id": "p1",
        "state": "regression_review", "candidate_fingerprint": "fpA",
        "baseline_generation": 1, "baseline_fingerprint": "fp0"})
    r = client.post("/api/regressions/p1/publish", json={"project": "bourbon",
        "candidate_fingerprint": "fpA"}, headers={"Idempotency-Key": "publish-1"})
    assert r.status_code == 200
    assert r.json()["baseline_generation"] == 2
    assert r.json()["proposal"]["state"] == "validated"
    assert "audit_event_id" in r.json()
```

```python
# flywheel/tests/api/test_regression_block_routes.py
from pathlib import Path
from fastapi.testclient import TestClient
from api.server import create_app
from api.auth import Principal


def _client(tmp_path: Path):
    principal = Principal(actor_id="alice", roles=frozenset({"harness_owner"}))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    return TestClient(app), app


def test_rollback_and_no_significant_change_routes(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("proposals", "p_roll", {"project": "bourbon", "id": "p_roll",
        "state": "regression_review"})
    app.state.store.put("proposals", "p_noise", {"project": "bourbon", "id": "p_noise",
        "state": "regression_review"})
    assert client.post("/api/regressions/p_roll/rollback", json={"project": "bourbon"},
        headers={"Idempotency-Key": "rollback-1"}).json()["proposal"]["state"] == "rolled_back"
    assert client.post("/api/regressions/p_noise/no-significant-change",
        json={"project": "bourbon"}, headers={"Idempotency-Key": "noise-1"}
    ).json()["proposal"]["state"] == "no_significant_change"


def test_judge_recheck_require_and_resume(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("proposals", "p1", {"project": "bourbon", "id": "p1",
        "state": "regression_review"})
    block = client.post("/api/regressions/p1/require-judge-recheck",
        json={"project": "bourbon"}, headers={"Idempotency-Key": "recheck-1"})
    assert block.json()["proposal"]["state"] == "blocked_on_judge_recheck"
    resume = client.post("/api/regressions/p1/resume-after-judge-recheck",
        json={"project": "bourbon"}, headers={"Idempotency-Key": "recheck-resume-1"})
    assert resume.json()["proposal"]["state"] == "regression_running"


def test_judge_migration_require_and_resume(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("proposals", "p1", {"project": "bourbon", "id": "p1",
        "state": "regression_review"})
    block = client.post("/api/regressions/p1/require-judge-migration",
        json={"project": "bourbon"}, headers={"Idempotency-Key": "migration-1"})
    assert block.json()["proposal"]["state"] == "blocked_on_judge_migration"
    resume = client.post("/api/regressions/p1/resume-after-judge-migration",
        json={"project": "bourbon"}, headers={"Idempotency-Key": "migration-resume-1"})
    assert resume.json()["proposal"]["state"] == "regression_review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_regression_routes.py tests/api/test_regression_block_routes.py -v`
Expected: FAIL — routes not present / `app.state.store` not exposed.

- [ ] **Step 3: Modify `server.py`**

Expose the store + validator on app state (inside `create_app`, after services built):

```python
# flywheel/api/server.py  (inside create_app)
    app.state.store = store
    from engine.judge import JudgeService
    from engine.validator import RegressionValidator
    validator = RegressionValidator(store, audit, baselines, JudgeService(store))
```

Add the routes:

```python
    from pydantic import BaseModel
    from .lifecycle import derive_regression_status

    class ProjectBody(BaseModel):
        project: str

    class RegressionCreateBody(BaseModel):
        project: str
        proposal_id: str
        candidate_fingerprint: str

    class PublishBody(BaseModel):
        project: str
        candidate_fingerprint: str

    # Unique name: do not shadow plan 02's _idempotent(key, build) helper.
    def _idempotent_regression_mutation(request: Request, compute):
        key = request.headers.get("Idempotency-Key")
        if not key:
            raise HTTPException(status_code=400, detail="Idempotency-Key required")
        prior = idem.lookup(key)
        if prior is not None:
            return prior
        result = compute()
        idem.remember(key, result)
        return result

    def _transition_proposal(proposal_id: str, project: str, to_state: str,
                             action: str, principal) -> dict:
        from .lifecycle import assert_transition
        prop = store.get("proposals", proposal_id)
        if prop is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        assert_transition(prop["state"], to_state)
        before = dict(prop)
        prop["state"] = to_state
        store.put("proposals", proposal_id, prop)
        aid = audit.record(project=project, actor=principal.actor_id, action=action,
                           target_type="proposal", target_id=proposal_id,
                           before=before, after=prop)
        return {"proposal": prop, "audit_event_id": aid}

    def _regression_response(regression: dict) -> dict:
        out = dict(regression)
        prop = store.get("proposals", out["proposal_id"])
        out["status"] = derive_regression_status(prop["state"]) if prop else None
        return out

    @app.post("/api/proposals/{proposal_id}/approve")
    def approve_proposal(proposal_id: str, body: ProjectBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        return _idempotent_regression_mutation(request, lambda: _transition_proposal(
            proposal_id, body.project, "approved", "approve_proposal", principal))

    @app.post("/api/proposals/{proposal_id}/reject")
    def reject_proposal(proposal_id: str, body: ProjectBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        return _idempotent_regression_mutation(request, lambda: _transition_proposal(
            proposal_id, body.project, "rejected", "reject_proposal", principal))

    @app.post("/api/proposals/{proposal_id}/defer")
    def defer_proposal(proposal_id: str, body: ProjectBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        return _idempotent_regression_mutation(request, lambda: _transition_proposal(
            proposal_id, body.project, "deferred", "defer_proposal", principal))

    @app.post("/api/regressions")
    def trigger_regression(body: RegressionCreateBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        def compute():
            proposal = store.get("proposals", body.proposal_id)
            if proposal is None:
                raise HTTPException(status_code=404, detail="proposal not found")
            source_run = store.get("runs", proposal.get("source_eval_run_id", ""))
            judge_version = proposal.get("judge_version") or (
                source_run or {}).get("judge_version")
            if not judge_version:
                raise HTTPException(status_code=409,
                                    detail="regression requires a comparable judge_version")
            result = _transition_proposal(body.proposal_id, body.project,
                "regression_running", "trigger_regression", principal)
            regression = store.put("regressions", body.proposal_id, {
                "project": body.project, "id": body.proposal_id,
                "proposal_id": body.proposal_id,
                "baseline_fingerprint": proposal["baseline_fingerprint"],
                "candidate_fingerprint": body.candidate_fingerprint,
                "judge_version": judge_version,
                "pass_rate_delta": 0.0,
                "pass_rate_ci": [0.0, 0.0],
                "expected_metric_delta": proposal.get("expected_metric_delta", {}),
                "actual_metric_delta": {},
                "fixed_failures": [],
                "new_failures": [],
                "outcome": None,
            })
            return {**result, "regression": _regression_response(regression)}
        return _idempotent_regression_mutation(request, compute)

    @app.get("/api/regressions/{regression_id}")
    def get_regression(regression_id: str):
        regression = store.get("regressions", regression_id)
        if regression is None:
            raise HTTPException(status_code=404, detail="regression not found")
        return {"regression": _regression_response(regression)}

    @app.post("/api/regressions/{regression_id}/publish")
    def publish_regression(regression_id: str, body: PublishBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        return _idempotent_regression_mutation(request, lambda: validator.publish(
            project=body.project, proposal_id=regression_id,
            candidate_fingerprint=body.candidate_fingerprint,
            actor=principal.actor_id))

    @app.post("/api/regressions/{regression_id}/rollback")
    def rollback_regression(regression_id: str, body: ProjectBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        return _idempotent_regression_mutation(request, lambda: _transition_proposal(
            regression_id, body.project, "rolled_back", "rollback_regression", principal))

    @app.post("/api/regressions/{regression_id}/no-significant-change")
    def no_sig_change(regression_id: str, body: ProjectBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        return _idempotent_regression_mutation(request, lambda: _transition_proposal(
            regression_id, body.project, "no_significant_change",
            "no_significant_change", principal))

    @app.post("/api/regressions/{regression_id}/require-judge-recheck")
    def require_judge_recheck(regression_id: str, body: ProjectBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        return _idempotent_regression_mutation(request, lambda: _transition_proposal(
            regression_id, body.project, "blocked_on_judge_recheck",
            "require_judge_recheck", principal))

    @app.post("/api/regressions/{regression_id}/resume-after-judge-recheck")
    def resume_after_judge_recheck(regression_id: str, body: ProjectBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        return _idempotent_regression_mutation(request, lambda: _transition_proposal(
            regression_id, body.project, "regression_running",
            "resume_after_judge_recheck", principal))

    @app.post("/api/regressions/{regression_id}/require-judge-migration")
    def require_judge_migration(regression_id: str, body: ProjectBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        return _idempotent_regression_mutation(request, lambda: _transition_proposal(
            regression_id, body.project, "blocked_on_judge_migration",
            "require_judge_migration", principal))

    @app.post("/api/regressions/{regression_id}/resume-after-judge-migration")
    def resume_after_judge_migration(regression_id: str, body: ProjectBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        return _idempotent_regression_mutation(request, lambda: _transition_proposal(
            regression_id, body.project, "regression_review",
            "resume_after_judge_migration", principal))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_regression_routes.py tests/api/test_regression_block_routes.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite + lint + types, then commit**

```bash
cd flywheel && pytest -q && ruff check api engine sdk tests && mypy api engine sdk
git add flywheel/api/server.py flywheel/tests/api/test_regression_routes.py
git add flywheel/tests/api/test_regression_block_routes.py
git commit -m "feat(api): regression and proposal decision routes"
```

---

## Self-Review

- **Spec coverage (Engine §12, §14):** `compute_holdout_integrity` implements the §14 mechanical holdout integrity and the four intersection checks (any non-empty consumed/train/dev/locked_test intersection blocks publish; consumed overlap requires fresh/rotated holdout before publish); `HoldoutLedger` implements §14 multiple-comparison accounting keyed by `candidate_hypothesis_id` (re-runs don't inflate distinct count) and Bonferroni alpha tightening; `compare_pass_rates`/`classify_outcome` implement §14 CIs, noise band, no-significant-change, safety-regression rollback; `RegressionValidator.decide` implements the §12 gate order (holdout leakage returns internal non-persisted `holdout_leakage` with unchanged proposal state → judge migration → judge recheck → statistical outcome) using `assert_transition` where the authoritative lifecycle supports it; `publish` verifies proposal baseline generation/fingerprint against the current `Baseline`, blocks stale proposals, increments the baseline generation via `BaselineService`, persists the publishing proposal as `validated`, and marks only proposals from the superseded generation `baseline_stale` (§13 rebase). Server routes cover every plan-07 endpoint assigned by the index, derive `RegressionStatus` from `ProposalState` instead of persisting it on regression rows, and are harness-owner-gated, idempotent human gates returning audit ids. Post-publish revert is already on the server from plan 02.
- **Placeholder scan:** no TODO; FDR is documented as Bonferroni-floor in MVP (Phase 1.5 stance from index doc), not a placeholder.
- **Type consistency:** `candidate_hypothesis_id` string format matches plan 06 (`proposal_id::candidate_fingerprint`). `assert_transition`/`ProposalState` from plan 02 used unchanged; outcome→state map only targets legal transitions present in plan 02 `PROPOSAL_TRANSITIONS`. `BaselineService.publish` signature matches plan 02. `JudgeService.candidate_drift_recheck` return shape (`status` field) matches plan 05. `wilson_interval`/`ConfidenceInterval` match plan 01.
