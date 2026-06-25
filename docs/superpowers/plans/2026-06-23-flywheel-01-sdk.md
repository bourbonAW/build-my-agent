# Flywheel 01 — Core Library (lean) Implementation Plan
**Date**: 2026-06-23 (Lean Revision 2026-06-24)
**Status**: Lean MVP — supersedes the prior "Foundation + L1 SDK" plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the small `flywheel/` package and the pure-logic core: a
minimal identity model, eval metrics (precision/recall/F1 + Wilson CI), and the
regression comparison that returns `better | no_change | worse`. No HTTP SDK, no
score client, no API client — those were deleted with the control plane.

**Architecture:** Pure-Python package `flywheel`, synchronous, no asyncio.
Engine spec §3–§7 are the contract.

**Tech stack:** Python 3.13, pydantic v2 (only where validation helps), pytest.

## What changed vs the old plan
- **Deleted** `sdk/schema.py` (`flywheel.*` attr constants), `sdk/context.py`
  (`FlywheelContext` with 5 eval-identity fields), `sdk/score_client.py`
  (`ScoreClient` → Flywheel API). Reason: no `flywheel.*` convention (use
  `gen_ai.*` + two `eval.*` strings) and no control-plane API to call.
- **Kept** `metrics.py` essentially as-is — it is the one module with standalone
  value.
- **Slimmed** the fingerprint from 8 components to `git_sha + model`.
- **Added** `regression.py` (the three-value comparison) and a flat `labels.md`.

## File structure
- Create: `flywheel/pyproject.toml`
- Create: `flywheel/flywheel/__init__.py`
- Create: `flywheel/flywheel/identity.py` — `Harness`, `case_id`/`run_id` helpers, `Label`
- Create: `flywheel/flywheel/metrics.py` — precision/recall/F1, Wilson CI, pass_rate
- Create: `flywheel/flywheel/regression.py` — `compare()` → `RegressionResult`
- Create: `flywheel/labels.md` — flat editable failure-label list (seed)
- Create: `flywheel/tests/__init__.py`, `flywheel/tests/test_identity.py`, `test_metrics.py`, `test_regression.py`

---

## Task 1: Repo scaffold

**Files:** `flywheel/pyproject.toml`, `flywheel/flywheel/__init__.py`, `flywheel/tests/__init__.py`

- [ ] **Step 1: `pyproject.toml`**

```toml
[project]
name = "flywheel"
version = "0.1.0"
description = "Lean eval flywheel: identity, metrics, judge, regression, reports"
requires-python = ">=3.13"
dependencies = ["pydantic>=2.6"]

[project.optional-dependencies]
judge = ["httpx>=0.27", "anthropic>=0.40"]   # used by plan 02 (judge.py)
api = ["fastapi>=0.110", "uvicorn>=0.29"]      # used by plan 02 (read API)
dev = ["pytest>=8.0", "ruff>=0.4", "mypy>=1.9"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["flywheel", "api"]   # "api" (read-only API, plan 02) is a sibling top-level package

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.13"
strict = true
```

- [ ] **Step 2:** create `flywheel/flywheel/__init__.py` (docstring) and `flywheel/tests/__init__.py` (empty).
- [ ] **Step 3:** `cd flywheel && uv pip install -e ".[dev]" && pytest -q` → install ok, "no tests ran" (exit 5) acceptable.
- [ ] **Step 4:** commit `chore(flywheel): scaffold lean package`.

---

## Task 2: identity.py — Harness, Label, id helpers

**Interfaces:**
- `Label = Literal["pass", "fail", "skip", "uncertain"]`
- `@dataclass(frozen=True) class Harness(git_sha: str, model: str)` with `id() -> str` = `f"{git_sha[:7]}@{model}"`.
- `JudgeVersion = str` (alias, documented as "plain identifier, not a lifecycle").

- [ ] **Step 1: failing test** `tests/test_identity.py`

```python
from flywheel.identity import Harness, Label
from typing import get_args

def test_label_values():
    assert set(get_args(Label)) == {"pass", "fail", "skip", "uncertain"}

def test_harness_id_is_short_and_stable():
    h = Harness(git_sha="abc1234def", model="claude-opus-4-8")
    assert h.id() == "abc1234@claude-opus-4-8"
    assert Harness(git_sha="abc1234def", model="claude-opus-4-8").id() == h.id()

def test_harness_id_changes_with_model():
    a = Harness(git_sha="abc1234def", model="claude-opus-4-8").id()
    b = Harness(git_sha="abc1234def", model="claude-sonnet-4-6").id()
    assert a != b
```

- [ ] **Step 2:** run → fails (`ModuleNotFoundError`).
- [ ] **Step 3: implement** `flywheel/flywheel/identity.py`

```python
"""Minimal eval identity (Engine §4). Four concepts carry the loop:
case_id, run_id, label, trace_id. case_id/run_id live as Langfuse dataset item
ids and run names, mirrored on spans as eval.case_id / eval.run_id. This module
holds the two small typed extras: the label enum and the harness fingerprint."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Label = Literal["pass", "fail", "skip", "uncertain"]
JudgeVersion = str  # a plain identifier, e.g. "judge-v2" — not a lifecycle


@dataclass(frozen=True)
class Harness:
    git_sha: str
    model: str

    def id(self) -> str:
        return f"{self.git_sha[:7]}@{self.model}"
```

- [ ] **Step 4:** run → pass. **Step 5:** commit `feat(flywheel): minimal identity (Harness + Label)`.

---

## Task 3: metrics.py — precision/recall/F1, Wilson CI

(Carried over from the old plan — the one module that survives unchanged.)

**Interfaces:**
- `precision_recall_f1(tp, fp, fn) -> tuple[float, float, float]`
- `@dataclass(frozen=True) ConfidenceInterval(point, low, high)`
- `wilson_interval(successes, n, z=1.96) -> ConfidenceInterval` (n==0 → (0,0,1))
- `pass_rate(labels: list[str]) -> ConfidenceInterval` ("pass" = success; skip/uncertain count as attempts)

- [ ] **Step 1: failing test** `tests/test_metrics.py`

```python
import math
from flywheel.metrics import precision_recall_f1, wilson_interval, pass_rate

def test_prf1_basic():
    p, r, f1 = precision_recall_f1(tp=8, fp=2, fn=2)
    assert math.isclose(p, 0.8) and math.isclose(r, 0.8) and math.isclose(f1, 0.8)

def test_zero_division_safe():
    assert precision_recall_f1(0, 0, 0) == (0.0, 0.0, 0.0)

def test_wilson_brackets_point():
    ci = wilson_interval(successes=9, n=10)
    assert 0.0 <= ci.low < ci.point < ci.high <= 1.0
    assert math.isclose(ci.point, 0.9)

def test_wilson_empty_full_uncertainty():
    ci = wilson_interval(0, 0)
    assert (ci.point, ci.low, ci.high) == (0.0, 0.0, 1.0)

def test_pass_rate_counts_skip_as_attempt():
    assert math.isclose(pass_rate(["pass", "pass", "skip", "uncertain"]).point, 0.5)
```

- [ ] **Step 2:** run → fails. **Step 3: implement** `flywheel/flywheel/metrics.py`

```python
"""Local eval metrics: precision/recall/F1 and Wilson-score pass-rate CIs."""
from __future__ import annotations

import math
from dataclasses import dataclass


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


@dataclass(frozen=True)
class ConfidenceInterval:
    point: float
    low: float
    high: float


def wilson_interval(successes: int, n: int, z: float = 1.96) -> ConfidenceInterval:
    if n == 0:
        return ConfidenceInterval(0.0, 0.0, 1.0)
    phat = successes / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)) / denom
    return ConfidenceInterval(phat, max(0.0, center - margin), min(1.0, center + margin))


def pass_rate(labels: list[str]) -> ConfidenceInterval:
    successes = sum(1 for label in labels if label == "pass")
    return wilson_interval(successes=successes, n=len(labels))
```

- [ ] **Step 4:** run → pass. **Step 5:** commit `feat(flywheel): precision/recall/F1 and Wilson CI`.

---

## Task 4: regression.py — three-value comparison

**Interfaces:**
- `RegressionResult = Literal["better", "no_change", "worse"]`
- `@dataclass(frozen=True) class CaseScore(case_id: str, label: str, failure_label: str | None = None)` — `failure_label` is a free string from `labels.md` / a Langfuse score comment, used for per-label deltas (Engine §7).
- `@dataclass(frozen=True) class RegressionReport(result, baseline_rate, candidate_rate, delta, delta_low, delta_high, fixed, newly_broken, per_label)` — `delta_low/high` are the Wilson-CI bounds of the delta (so report.py can serialize a real CI, not a zero-width one); `fixed`/`newly_broken` are case-id lists; `per_label` is `[{label, baseline, candidate}]` failure counts.
- `compare(baseline, candidate, *, validation_case_ids: set[str], baseline_judge_version: str, candidate_judge_version: str) -> RegressionReport`
  - **same-judge gate (Engine §7):** raises `ValueError` if the two judge versions differ — baseline/candidate must be scored by the same judge or be re-scored first.
  - **disjointness gate (Engine §5/§7):** raises `ValueError` if compared case ids overlap `validation_case_ids`. That set is the dataset's **judge-validation split**; the regression set is the dataset's **regression split** — the caller reads both from the Langfuse dataset metadata.
  - assigns `better`/`worse`/`no_change` by whether the pass-rate-delta Wilson CI clears zero (Engine §7 noise band).
- `aggregate_repeats(scores: list[CaseScore]) -> list[CaseScore]` — collapses repeated scorings of the same `case_id` (Engine §7 "sample ≥3× for nondeterministic cases") into one `CaseScore` by majority vote: a case is `pass` only if a strict majority of its repeats passed (ties → not-a-pass, conservative); the kept `failure_label` is the most common one among the non-pass repeats. Single-run cases pass through unchanged, so callers that don't repeat are unaffected. `run_regression.py` (plan 02 Task 6) calls this before `compare()`.

- [ ] **Step 1: failing test** `tests/test_regression.py`

```python
import pytest
from flywheel.regression import compare, CaseScore

def _scores(passes, fails):
    return [CaseScore(f"c{i}", "pass") for i in range(passes)] + \
           [CaseScore(f"d{i}", "fail") for i in range(fails)]

def _cmp(base, cand, validation_case_ids=frozenset()):
    return compare(base, cand, validation_case_ids=set(validation_case_ids),
                   baseline_judge_version="jv1", candidate_judge_version="jv1")

def test_clear_improvement_is_better():
    rep = _cmp(_scores(2, 18), _scores(18, 2))   # 10% -> 90%
    assert rep.result == "better"
    assert rep.delta > 0
    assert rep.delta_low <= rep.delta <= rep.delta_high

def test_tiny_delta_is_no_change():
    base = [CaseScore(f"c{i}", "pass" if i < 10 else "fail") for i in range(20)]
    cand = [CaseScore(f"c{i}", "pass" if i < 11 else "fail") for i in range(20)]
    assert _cmp(base, cand).result == "no_change"

def test_regression_is_worse():
    assert _cmp(_scores(18, 2), _scores(2, 18)).result == "worse"

def test_mismatched_judge_raises():
    with pytest.raises(ValueError, match="same-judge"):
        compare(_scores(5, 5), _scores(5, 5), validation_case_ids=set(),
                baseline_judge_version="jv1", candidate_judge_version="jv2")

def test_disjointness_violation_raises():
    base = _scores(5, 5)
    with pytest.raises(ValueError, match="disjoint"):
        _cmp(base, base, validation_case_ids={"c0"})

def test_fixed_and_newly_broken_tracked():
    base = [CaseScore("a", "fail"), CaseScore("b", "pass")]
    cand = [CaseScore("a", "pass"), CaseScore("b", "fail")]
    rep = _cmp(base, cand)
    assert "a" in rep.fixed and "b" in rep.newly_broken

def test_per_label_failure_counts():
    base = [CaseScore("a", "fail", "tool_misuse"), CaseScore("b", "fail", "tool_misuse")]
    cand = [CaseScore("a", "pass"), CaseScore("b", "fail", "tool_misuse")]
    rep = _cmp(base, cand)
    row = next(r for r in rep.per_label if r["label"] == "tool_misuse")
    assert row["baseline"] == 2 and row["candidate"] == 1

def test_aggregate_repeats_majority_vote():
    from flywheel.regression import aggregate_repeats
    runs = [
        CaseScore("a", "pass"), CaseScore("a", "pass"), CaseScore("a", "fail", "tool_misuse"),
        CaseScore("b", "fail", "tool_misuse"), CaseScore("b", "fail", "tool_misuse"), CaseScore("b", "pass"),
    ]
    agg = {s.case_id: s for s in aggregate_repeats(runs)}
    assert agg["a"].label == "pass"          # 2/3 pass -> pass
    assert agg["b"].label == "fail"          # 1/3 pass -> fail
    assert agg["b"].failure_label == "tool_misuse"
```

- [ ] **Step 2:** run → fails. **Step 3: implement** `flywheel/flywheel/regression.py`

```python
"""Baseline vs candidate regression (Engine §7): better | no_change | worse.
Decision uses the Wilson CI of the pass-rate delta as the noise band. Enforces
two surviving correctness gates:
  1. same-judge: baseline and candidate must be scored by the same judge_version.
  2. disjointness: compared cases must not overlap the judge-validation set.
`validation_case_ids` is the dataset's judge-validation split; the regression set
is the dataset's regression split. The caller reads both from Langfuse dataset
metadata. Any non-"pass" label (fail/skip/uncertain) counts as not-a-success,
consistent with metrics.pass_rate."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .metrics import pass_rate

RegressionResult = Literal["better", "no_change", "worse"]


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    label: str
    failure_label: str | None = None  # taxonomy string for per-label deltas (Engine §7)


@dataclass(frozen=True)
class RegressionReport:
    result: RegressionResult
    baseline_rate: float
    candidate_rate: float
    delta: float
    delta_low: float        # Wilson-CI lower bound of the delta (noise band)
    delta_high: float       # Wilson-CI upper bound of the delta
    fixed: list[str]        # case ids the candidate fixed
    newly_broken: list[str] # case ids the candidate broke
    per_label: list[dict]   # [{label, baseline, candidate}] failure counts


def _labels_by_case(scores: list[CaseScore]) -> dict[str, str]:
    return {s.case_id: s.label for s in scores}


def _fail_counts(scores: list[CaseScore]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in scores:
        if s.label != "pass" and s.failure_label:
            counts[s.failure_label] = counts.get(s.failure_label, 0) + 1
    return counts


def aggregate_repeats(scores: list[CaseScore]) -> list[CaseScore]:
    """Collapse repeated scorings of one case (Engine §7 "repeats ≥3×") by
    majority vote: pass only if a strict majority of repeats passed (ties are
    conservative non-passes). The kept failure_label is the most common among the
    non-pass repeats. Single-run cases are returned unchanged."""
    from collections import Counter

    by_case: dict[str, list[CaseScore]] = {}
    for s in scores:
        by_case.setdefault(s.case_id, []).append(s)
    out: list[CaseScore] = []
    for case_id, runs in by_case.items():
        passes = sum(1 for r in runs if r.label == "pass")
        if passes * 2 > len(runs):
            out.append(CaseScore(case_id, "pass"))
            continue
        fl = Counter(r.failure_label for r in runs if r.label != "pass" and r.failure_label)
        failure_label = fl.most_common(1)[0][0] if fl else None
        out.append(CaseScore(case_id, "fail", failure_label))
    return sorted(out, key=lambda s: s.case_id)


def compare(
    baseline: list[CaseScore],
    candidate: list[CaseScore],
    *,
    validation_case_ids: set[str],
    baseline_judge_version: str,
    candidate_judge_version: str,
) -> RegressionReport:
    if baseline_judge_version != candidate_judge_version:
        raise ValueError(
            "same-judge gate: baseline and candidate must use one judge_version "
            f"({baseline_judge_version!r} != {candidate_judge_version!r}); re-score first"
        )
    case_ids = {s.case_id for s in baseline} | {s.case_id for s in candidate}
    overlap = case_ids & validation_case_ids
    if overlap:
        raise ValueError(f"regression set must be disjoint from validation set; overlap={overlap}")

    b = _labels_by_case(baseline)
    c = _labels_by_case(candidate)
    fixed = sorted(k for k in b if b[k] != "pass" and c.get(k) == "pass")
    newly_broken = sorted(k for k in b if b[k] == "pass" and c.get(k) not in (None, "pass"))

    base_ci = pass_rate([s.label for s in baseline])
    cand_ci = pass_rate([s.label for s in candidate])
    delta = cand_ci.point - base_ci.point
    # Noise band: delta CI via difference of two Wilson intervals (conservative).
    delta_low = cand_ci.low - base_ci.high
    delta_high = cand_ci.high - base_ci.low
    if delta_low > 0:
        result: RegressionResult = "better"
    elif delta_high < 0:
        result = "worse"
    else:
        result = "no_change"

    base_fails = _fail_counts(baseline)
    cand_fails = _fail_counts(candidate)
    per_label = [
        {"label": label, "baseline": base_fails.get(label, 0), "candidate": cand_fails.get(label, 0)}
        for label in sorted(set(base_fails) | set(cand_fails))
    ]

    return RegressionReport(
        result=result, baseline_rate=base_ci.point, candidate_rate=cand_ci.point,
        delta=delta, delta_low=delta_low, delta_high=delta_high,
        fixed=fixed, newly_broken=newly_broken, per_label=per_label,
    )
```

- [ ] **Step 4:** run → pass.
- [ ] **Step 5:** seed `flywheel/labels.md` with a flat list (one label + one-line definition per row).
- [ ] **Step 6:** full suite + lint + types: `pytest -q && ruff check flywheel tests && mypy flywheel`.
- [ ] **Step 7:** commit `feat(flywheel): three-value regression comparison + seed labels`.

---

## Self-review
- **Engine spec coverage:** identity.py = §4 (four ids + minimal fingerprint);
  metrics.py = the math §6/§7 depend on; regression.py = §7 (three outcomes,
  Wilson noise band, disjointness assert).
- **Deleted-on-purpose:** no `flywheel.*` constants, no context validator, no
  score HTTP client — see "What changed" above; the engine spec §0/§8 record why.
- **Type handoff to plan 02:** `ConfidenceInterval`, `RegressionReport`,
  `CaseScore`, `Label`, `Harness` are imported by `judge.py`/`validate.py`/
  `report.py` and serialized by the read API.
