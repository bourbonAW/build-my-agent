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
judge = ["httpx>=0.27", "anthropic>=0.40"]   # used by plan 02 (judge.py glue)
api = ["fastapi>=0.110", "uvicorn>=0.29"]      # used by plan 02 (read API)
# dev is a superset so a single `.[dev]` install runs the whole suite, incl.
# plan 02's api tests (fastapi + httpx TestClient) and mypy over api/.
dev = ["pytest>=8.0", "ruff>=0.4", "mypy>=1.9",
       "fastapi>=0.110", "uvicorn>=0.29", "httpx>=0.27", "anthropic>=0.40"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["flywheel"]   # plan 02 Task 4 adds the sibling "api" package here when api/ is created

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
- `Label = Literal["pass", "fail", "skip", "uncertain"]` — any verdict: human, judge, or operational. `pass`/`fail` are the gating classes; `skip` (case not run) and `uncertain` (judge abstained) are non-successes, never a pass.
- `HumanLabel = Literal["pass", "fail"]` — a **human** annotation is gold and binary (no `skip`/`uncertain`). A judge verdict may be `uncertain`; a human verdict may not.
- `@dataclass(frozen=True) class Harness(git_sha: str, model: str)` with `id() -> str` = `f"{git_sha[:7]}@{model}"`.
- `JudgeVersion = str` (alias; a **URL-safe slug** `^[A-Za-z0-9._@-]+$` since it is a report filename / `/api/judges/{judge_version}` segment — not a lifecycle).
- `validate_judge_version(value: str) -> str` — raises `ValueError` unless `value` matches the JudgeVersion slug; enforced at the typed boundary (`compare()`, `validate()`, `JudgeConfig.__post_init__`), not just at report-write time.

- [ ] **Step 1: failing test** `tests/test_identity.py`

```python
import pytest
from flywheel.identity import Harness, Label, HumanLabel, validate_judge_version
from typing import get_args

def test_label_values():
    assert set(get_args(Label)) == {"pass", "fail", "skip", "uncertain"}

def test_judge_version_slug_accepts_and_rejects():
    assert validate_judge_version("judge-v2.1@m") == "judge-v2.1@m"
    for bad in ("judge:v1", "judge/v1", "judge v1", "judge-v1\n", ".", "..", ""):
        with pytest.raises(ValueError, match="invalid judge_version"):
            validate_judge_version(bad)   # fullmatch + dot guard: no trailing-\n / dot-segment holes

def test_human_label_is_binary():
    assert set(get_args(HumanLabel)) == {"pass", "fail"}

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

import re
from dataclasses import dataclass
from typing import Literal

Label = Literal["pass", "fail", "skip", "uncertain"]  # any verdict (human/judge/operational)
HumanLabel = Literal["pass", "fail"]  # a human annotation is gold and binary
JudgeVersion = str  # a URL-safe slug ^[A-Za-z0-9._@-]+$ (it is a report filename /
# /api/judges/{judge_version} segment), e.g. "judge-v2" — not a lifecycle

_JUDGE_VERSION_RE = re.compile(r"[A-Za-z0-9._@-]+")  # fullmatch — no ^…$ trailing-\n hole


def validate_judge_version(value: str) -> str:
    """Enforce the JudgeVersion slug contract at the typed boundary (not just at the
    report-filename write). A bad value like "judge:v1" / "judge/v1" / a trailing
    newline / "."/".." must fail where it enters the core — JudgeConfig, validate(),
    compare() — not late at write time. `fullmatch` (not `match` + `$`, which accepts
    a trailing newline) and the explicit dot check make it a real path segment."""
    if not _JUDGE_VERSION_RE.fullmatch(value) or value in (".", ".."):
        raise ValueError(f"invalid judge_version {value!r}; must be a slug [A-Za-z0-9._@-]+ and not '.'/'..'")
    return value


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
- `@dataclass(frozen=True) class CaseScore(case_id: str, label: Label, failure_label: str | None = None)` — `label` is the typed `Label` (`pass`/`fail`/`skip`/`uncertain`); `__post_init__` rejects any other value so a malformed Langfuse score (`"PASS"`, `"error"`, `""`) raises at ingestion instead of being silently miscounted as a failure. `failure_label` is a free string from `labels.md` / a Langfuse score comment, used for per-label deltas (Engine §7).
- `@dataclass(frozen=True) class RegressionReport(result, judge_version, baseline_rate, candidate_rate, candidate_rate_low, candidate_rate_high, candidate_non_pass_count, delta, delta_low, delta_high, fixed, newly_broken, per_label)` — `judge_version` is the single version `compare()` asserted both sides share (so report.py serializes the *gated* version, not an arbitrary caller string); `delta_low/high` are a **descriptive discordance band** for the delta (a magnitude cue, **not** a confidence interval and **not** the gate — the decision is the exact sign test; the band can disagree, see `compare()`), serialized so report.py shows a non-zero-width band; `candidate_rate` + `candidate_rate_low/high` are the candidate run's **case-level** Wilson CI and `candidate_non_pass_count` its case-level non-pass count, computed from the **same aggregated scores `compare()` gates on** — so `RunSummary.passRate`/`nonPassCount` (served from the report) can never disagree with the regression report on a run with repeats; `fixed`/`newly_broken` are case-id lists; `per_label` is `[{label, baseline, candidate}]` failure counts (a non-pass case with no `failure_label` is bucketed as `"unlabeled"`, never silently dropped).
- `compare(baseline, candidate, *, regression_case_ids: set[str], validation_case_ids: set[str], baseline_judge_version: str, candidate_judge_version: str) -> RegressionReport`
  - **same-judge gate (Engine §7):** raises `ValueError` if the two judge versions differ — baseline/candidate must be scored by the same judge or be re-scored first.
  - **completeness gate:** raises `ValueError` unless the compared cases are **exactly** `regression_case_ids` (the full declared regression split read from the dataset). A silently dropped case (harness error, missing score) must not let a candidate pass the gate on an easier subset; "same scored ids on both sides" alone can't catch a case both runs skipped.
  - **disjointness gate (Engine §5/§7):** raises `ValueError` if compared case ids overlap `validation_case_ids`. That set is the **entire judge-validation set** — the union of all human-labeled judge cases (`judge_train ∪ judge_dev ∪ judge_test`), not just the held-out `judge_test` split, because a regression case that was a few-shot (`train`) or prompt-tuning (`dev`) case is leaked too. The regression set is the dataset's **regression split**; the caller reads both from the Langfuse dataset metadata.
  - assigns `better`/`worse`/`no_change` by an **exact two-sided paired sign test** (McNemar exact) on the discordant pairs (Engine §7); the Wilson delta CI is kept only as the descriptive interval (it is anti-conservative on tiny discordant counts).
- `aggregate_repeats(scores: list[CaseScore]) -> list[CaseScore]` — collapses repeated scorings of the same `case_id` (Engine §7 "sample ≥3× for nondeterministic cases") into one `CaseScore` by majority vote: a case is `pass` only if a strict majority of its repeats passed (ties → not-a-pass, conservative); the kept `failure_label` is the most common one among the non-pass repeats. Single-run cases pass through unchanged, so callers that don't repeat are unaffected. `run_regression.py` (plan 02 Task 6) calls this before `compare()`.
- `check_repeat_budgets(baseline, candidate, *, min_repeats=3) -> None` — pure, unit-tested guard run **before** `aggregate_repeats` (which discards counts): raises `ValueError` if any case has an **unequal** score count across baseline/candidate (unfair majority vote) or is sampled `>1` but `< min_repeats` (under-powered half-sample). `compare()` can't see this post-aggregation, so the check lives here rather than in I/O glue; `run_regression.py` calls it first.
- `check_splits_disjoint(splits: dict[str, set[str]]) -> None` — pure, unit-tested guard: raises `ValueError` if any two of the dataset's case-id splits (`judge_train`/`judge_dev`/`judge_test`/`regression`) overlap. The 60/20/20 partition + regression set must be disjoint or a few-shot/dev case leaks into the held-out gate and inflates it; `validate()` only sees the held-out list and can't detect it. The split loaders (`run_judge.py`, `validate_judge.py`, `run_regression.py`) call it right after reading the splits.

- [ ] **Step 1: failing test** `tests/test_regression.py`

```python
import pytest
from flywheel.regression import compare, CaseScore

def _scores(passes, fails):
    return [CaseScore(f"c{i}", "pass") for i in range(passes)] + \
           [CaseScore(f"d{i}", "fail") for i in range(fails)]

def _run(labels):
    """One score per case c0..c{n-1}; `labels` are the verdicts in order. Baseline
    and candidate built this way share the same case-id set (required by compare)."""
    return [CaseScore(f"c{i}", lab) for i, lab in enumerate(labels)]

def _cmp(base, cand, validation_case_ids=frozenset(), regression_case_ids=None):
    # default the declared split to the baseline ids so existing cases compare the
    # full set; tests that exercise the completeness gate pass it explicitly.
    ids = {s.case_id for s in base} if regression_case_ids is None else set(regression_case_ids)
    return compare(base, cand, regression_case_ids=ids,
                   validation_case_ids=set(validation_case_ids),
                   baseline_judge_version="jv1", candidate_judge_version="jv1")

def test_clear_improvement_is_better():
    rep = _cmp(_run(["fail"] * 18 + ["pass"] * 2), _run(["pass"] * 18 + ["fail"] * 2))  # 10% -> 90%
    assert rep.result == "better"
    assert rep.delta > 0
    assert rep.delta_low <= rep.delta <= rep.delta_high

def test_tiny_delta_is_no_change():
    base = [CaseScore(f"c{i}", "pass" if i < 10 else "fail") for i in range(20)]
    cand = [CaseScore(f"c{i}", "pass" if i < 11 else "fail") for i in range(20)]
    assert _cmp(base, cand).result == "no_change"

def test_regression_is_worse():
    assert _cmp(_run(["pass"] * 18 + ["fail"] * 2), _run(["fail"] * 18 + ["pass"] * 2)).result == "worse"

def test_no_discordance_reports_finite_band_not_certainty():
    base = _run(["pass", "fail", "pass"])
    rep = _cmp(base, base)                       # identical runs → 0 discordant pairs
    assert rep.result == "no_change"
    assert rep.delta == 0.0
    assert rep.delta_low < 0 < rep.delta_high    # honest finite-sample band, never [0, 0]

def test_small_one_sided_discordance_is_no_change():
    # 4 fixed / 0 newly-broken: exact two-sided sign-test p = 0.125, not significant.
    # The Wilson band alone would clear zero and call this "better" (anti-conservative).
    base = _run(["fail", "fail", "fail", "fail", "pass", "pass"])
    cand = _run(["pass", "pass", "pass", "pass", "pass", "pass"])
    assert _cmp(base, cand).result == "no_change"   # need ≥6 consistent fixes for p<0.05

def test_mismatched_judge_raises():
    s = _scores(5, 5)
    with pytest.raises(ValueError, match="same-judge"):
        compare(s, s, regression_case_ids={x.case_id for x in s}, validation_case_ids=set(),
                baseline_judge_version="jv1", candidate_judge_version="jv2")

def test_invalid_judge_version_raises():
    with pytest.raises(ValueError, match="invalid judge_version"):
        compare([CaseScore("a", "pass")], [CaseScore("a", "pass")],
                regression_case_ids={"a"}, validation_case_ids=set(),
                baseline_judge_version="judge:v1", candidate_judge_version="judge:v1")

def test_disjointness_violation_raises():
    base = _scores(5, 5)
    with pytest.raises(ValueError, match="disjoint"):
        _cmp(base, base, validation_case_ids={"c0"})

def test_mismatched_case_set_raises():
    with pytest.raises(ValueError, match="same regression case set"):
        _cmp([CaseScore("a", "pass")], [CaseScore("b", "pass")])

def test_incomplete_regression_set_raises():
    # both runs silently dropped c2 — must not pass the gate on the easier subset
    base = _run(["pass", "fail"])  # c0, c1
    with pytest.raises(ValueError, match="regression set is incomplete"):
        _cmp(base, base, regression_case_ids={"c0", "c1", "c2"})

def test_duplicate_case_id_raises():
    dup = [CaseScore("a", "pass"), CaseScore("a", "fail")]
    with pytest.raises(ValueError, match="duplicate case_id"):
        _cmp(dup, dup)

def test_invalid_label_raises():
    # a malformed Langfuse value must fail loudly at construction, not be miscounted
    with pytest.raises(ValueError, match="invalid label"):
        CaseScore("a", "PASS")  # not a canonical Label ("pass"/"fail"/"skip"/"uncertain")

def test_empty_regression_set_raises():
    with pytest.raises(ValueError, match="must not be empty"):
        _cmp([], [])

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

def test_unlabeled_non_pass_is_bucketed_not_dropped():
    base = [CaseScore("a", "fail"), CaseScore("b", "fail", "tool_misuse")]  # a has no failure_label
    cand = [CaseScore("a", "fail"), CaseScore("b", "pass")]
    rows = {r["label"]: r for r in _cmp(base, cand).per_label}
    assert rows["unlabeled"]["baseline"] == 1 and rows["unlabeled"]["candidate"] == 1  # not dropped
    assert rows["tool_misuse"]["baseline"] == 1 and rows["tool_misuse"]["candidate"] == 0

def test_aggregate_repeats_majority_vote():
    from flywheel.regression import aggregate_repeats
    runs = [
        CaseScore("a", "pass"), CaseScore("a", "pass"), CaseScore("a", "fail", "tool_misuse"),
        CaseScore("b", "fail", "tool_misuse"), CaseScore("b", "fail", "tool_misuse"), CaseScore("b", "pass"),
        CaseScore("c", "uncertain"),  # single run
        CaseScore("u", "uncertain"), CaseScore("u", "uncertain"), CaseScore("u", "pass"),
        CaseScore("k", "skip"), CaseScore("k", "skip"), CaseScore("k", "fail", "x"),
        CaseScore("t", "fail", "y"), CaseScore("t", "uncertain"),  # tie -> fail
    ]
    agg = {s.case_id: s for s in aggregate_repeats(runs)}
    assert agg["a"].label == "pass"          # 2/3 pass -> pass
    assert agg["b"].label == "fail"          # 1/3 pass -> fail
    assert agg["b"].failure_label == "tool_misuse"
    assert agg["c"].label == "uncertain"     # single run preserved, not coerced to fail
    assert agg["u"].label == "uncertain"     # majority non-pass label kept, not rewritten to fail
    assert agg["k"].label == "skip"          # all-skip majority kept
    assert agg["t"].label == "fail"          # 1 fail / 1 uncertain tie -> fail (priority)

def test_repeat_budget_equal_ok():
    from flywheel.regression import check_repeat_budgets
    base = [CaseScore("a", "pass")] * 3 + [CaseScore("b", "pass")]
    cand = [CaseScore("a", "fail")] * 3 + [CaseScore("b", "pass")]
    check_repeat_budgets(base, cand)         # 3x both sides for a, 1x for b → ok (no raise)

def test_repeat_budget_unequal_raises():
    from flywheel.regression import check_repeat_budgets
    with pytest.raises(ValueError, match="unequal repeat budget"):
        check_repeat_budgets([CaseScore("a", "pass")] * 3, [CaseScore("a", "pass")])

def test_repeat_budget_under_min_raises():
    from flywheel.regression import check_repeat_budgets
    with pytest.raises(ValueError, match="repeat once or >="):
        check_repeat_budgets([CaseScore("a", "pass")] * 2, [CaseScore("a", "pass")] * 2)

def test_splits_disjoint_ok():
    from flywheel.regression import check_splits_disjoint
    check_splits_disjoint({"judge_train": {"a", "b"}, "judge_test": {"c"}, "regression": {"d"}})

def test_splits_overlap_raises():
    from flywheel.regression import check_splits_disjoint
    with pytest.raises(ValueError, match="split overlap"):
        check_splits_disjoint({"judge_train": {"a", "b"}, "judge_test": {"b"}})  # b leaks train→test
```

- [ ] **Step 2:** run → fails. **Step 3: implement** `flywheel/flywheel/regression.py`

```python
"""Baseline vs candidate regression (Engine §7): better | no_change | worse.
The better/worse decision uses an EXACT two-sided paired sign test (McNemar exact)
on the discordant pairs; the Wilson delta CI is kept only as the descriptive
interval the UI shows (it is anti-conservative on tiny discordant counts). Enforces
two surviving correctness gates:
  1. same-judge: baseline and candidate must be scored by the same judge_version.
  2. disjointness: compared cases must not overlap the judge-validation set.
`validation_case_ids` is the *entire* judge-validation set (the union of
`judge_train ∪ judge_dev ∪ judge_test` — train/dev cases leak too, not only the
held-out test split); the regression set is the dataset's regression split. The
caller reads both from Langfuse dataset metadata. Any non-"pass" label
(fail/skip/uncertain) counts as not-a-success,
consistent with metrics.pass_rate."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, get_args

from .identity import Label, validate_judge_version
from .metrics import pass_rate

RegressionResult = Literal["better", "no_change", "worse"]


def _sign_test_significant(fixed_n: int, broken_n: int, alpha: float = 0.05) -> bool:
    """Exact two-sided binomial sign test (McNemar exact) on discordant pairs.
    Under H0 (no real change) a discordant pair is equally likely a fix or a break,
    so the smaller count ~ Binomial(disc, 0.5). Returns True only when we can reject
    H0 at `alpha` — i.e. the direction is real, not small-sample noise. This is
    stricter than "the Wilson delta band clears zero", which would call 4-fixed /
    0-broken `better` though the exact two-sided p is 0.125."""
    disc = fixed_n + broken_n
    if disc == 0:
        return False
    k = min(fixed_n, broken_n)
    tail = sum(math.comb(disc, i) for i in range(k + 1)) / (2 ** disc)
    return min(1.0, 2.0 * tail) < alpha


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    label: Label
    failure_label: str | None = None  # taxonomy string for per-label deltas (Engine §7)

    def __post_init__(self) -> None:
        # Reject malformed Langfuse score values ("PASS", "error", "") at ingestion
        # instead of silently counting them as a non-"pass" failure.
        if self.label not in get_args(Label):
            raise ValueError(f"invalid label {self.label!r}; expected one of {get_args(Label)}")


@dataclass(frozen=True)
class RegressionReport:
    result: RegressionResult
    judge_version: str             # the single judge_version compare() asserted both sides share
    baseline_rate: float
    candidate_rate: float          # candidate case-level pass-rate point
    candidate_rate_low: float      # candidate case-level Wilson CI bounds — same
    candidate_rate_high: float     # aggregated scores compare() gates on, so the
    candidate_non_pass_count: int  # runs list (served from this) can't disagree
    delta: float
    delta_low: float        # descriptive discordance band (NOT a CI; gate = exact sign test)
    delta_high: float       # descriptive upper bound — magnitude cue only
    fixed: list[str]        # case ids the candidate fixed
    newly_broken: list[str] # case ids the candidate broke
    per_label: list[dict[str, object]]  # [{label, baseline, candidate}] failure counts


def _labels_by_case(scores: list[CaseScore]) -> dict[str, str]:
    return {s.case_id: s.label for s in scores}


def _fail_counts(scores: list[CaseScore]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in scores:
        if s.label != "pass":
            # Bucket a missing/empty failure_label as "unlabeled" rather than silently
            # dropping it: Engine §5 wants every regression item labeled, but a forgotten
            # label must surface in the per-label deltas, not undercount fixes/breaks.
            counts[s.failure_label or "unlabeled"] = counts.get(s.failure_label or "unlabeled", 0) + 1
    return counts


def aggregate_repeats(scores: list[CaseScore]) -> list[CaseScore]:
    """Collapse repeated scorings of one case (Engine §7 "repeats ≥3×") by
    majority vote: "pass" only if a strict majority of repeats passed; otherwise
    keep the most common non-pass label (all-"uncertain" -> "uncertain",
    all-"skip" -> "skip"), ties broken toward the most safety-relevant label
    (fail > uncertain > skip). The kept failure_label is the most common among the
    non-pass repeats. Single-run cases are returned unchanged.

    Collapsing drops the repeat count, so this assumes the caller already ensured a
    **fair, equal repeat budget per case across the two runs** being compared (an
    unequal budget would make the majority vote unfair). `run_regression.py` (plan 02
    Task 6 Step 7) validates that cardinality on baseline and candidate before
    calling this."""
    from collections import Counter

    by_case: dict[str, list[CaseScore]] = {}
    for s in scores:
        by_case.setdefault(s.case_id, []).append(s)
    out: list[CaseScore] = []
    for case_id, runs in by_case.items():
        if len(runs) == 1:
            out.append(runs[0])  # single run: preserve the original label (incl. skip/uncertain)
            continue
        passes = sum(1 for r in runs if r.label == "pass")
        if passes * 2 > len(runs):
            out.append(CaseScore(case_id, "pass"))
            continue
        # Not a pass-majority: keep the most common non-pass label, so all-"uncertain"
        # stays "uncertain" and all-"skip" stays "skip" (the label model distinguishes
        # them). Ties resolve toward the most safety-relevant label: fail > uncertain > skip.
        _priority = {"fail": 0, "uncertain": 1, "skip": 2}
        non_pass = Counter(r.label for r in runs if r.label != "pass")
        label = max(non_pass, key=lambda lbl: (non_pass[lbl], -_priority.get(lbl, 3)))
        fl = Counter(r.failure_label for r in runs if r.label != "pass" and r.failure_label)
        failure_label = fl.most_common(1)[0][0] if fl else None
        out.append(CaseScore(case_id, label, failure_label))
    return sorted(out, key=lambda s: s.case_id)


def check_repeat_budgets(
    baseline: list[CaseScore], candidate: list[CaseScore], *, min_repeats: int = 3
) -> None:
    """Pure, tested guard run **before** `aggregate_repeats` (which discards counts).
    For every case id, baseline and candidate must have the **same number of scores**
    (an unequal budget — e.g. 5x vs 1x — makes the per-case majority vote unfair), and
    any case sampled more than once must reach `min_repeats` on both sides (a 2x
    half-sample is under-powered; Engine §7 says repeat once or ≥3x). Single-run cases
    (count == 1) are fine. Raises `ValueError` on violation. `run_regression.py`
    (plan 02 Task 6 Step 7) calls this before aggregating; `compare()` can't see it
    post-aggregation, so it lives here as a unit-tested function, not in I/O glue."""
    from collections import Counter

    bc = Counter(s.case_id for s in baseline)
    cc = Counter(s.case_id for s in candidate)
    if set(bc) != set(cc):
        raise ValueError("baseline and candidate cover different case ids before aggregation")
    for cid in bc:
        if bc[cid] != cc[cid]:
            raise ValueError(
                f"unequal repeat budget for {cid!r}: baseline {bc[cid]}x vs candidate {cc[cid]}x"
            )
        if bc[cid] != 1 and bc[cid] < min_repeats:
            raise ValueError(
                f"case {cid!r} sampled {bc[cid]}x: repeat once or >= {min_repeats}x (Engine §7)"
            )


def check_splits_disjoint(splits: dict[str, set[str]]) -> None:
    """Pure, tested guard: raise if any two of the dataset's case-id splits share a
    case. The pipeline depends on `judge_train` / `judge_dev` / `judge_test` /
    `regression` being a **true partition** (Engine §5/§6) — a case used as a few-shot
    (`train`) example that also appears in `judge_test` leaks and inflates the gate,
    and `validate()` only sees the held-out list so it cannot detect it. The split
    loaders (`run_judge.py`, `validate_judge.py`, `run_regression.py`) call this on the
    four named splits right after reading them from the dataset."""
    names = list(splits)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            overlap = splits[names[i]] & splits[names[j]]
            if overlap:
                raise ValueError(
                    f"split overlap: {names[i]} ∩ {names[j]} = {sorted(overlap)}; "
                    "judge_train/judge_dev/judge_test/regression must be a true partition"
                )


def compare(
    baseline: list[CaseScore],
    candidate: list[CaseScore],
    *,
    regression_case_ids: set[str],
    validation_case_ids: set[str],
    baseline_judge_version: str,
    candidate_judge_version: str,
) -> RegressionReport:
    validate_judge_version(baseline_judge_version)   # slug contract (Engine §4), enforced
    validate_judge_version(candidate_judge_version)   # at the typed boundary, not just at write
    if baseline_judge_version != candidate_judge_version:
        raise ValueError(
            "same-judge gate: baseline and candidate must use one judge_version "
            f"({baseline_judge_version!r} != {candidate_judge_version!r}); re-score first"
        )
    base_ids = [s.case_id for s in baseline]
    cand_ids = [s.case_id for s in candidate]
    if not base_ids or not cand_ids:
        raise ValueError("regression set must not be empty")
    if len(set(base_ids)) != len(base_ids) or len(set(cand_ids)) != len(cand_ids):
        raise ValueError("duplicate case_id within baseline or candidate scores; "
                         "aggregate repeats first (see aggregate_repeats)")
    if set(base_ids) != set(cand_ids):
        raise ValueError(
            "same-population gate: baseline and candidate must cover the same "
            "regression case set (compare on identical case_ids, not different "
            "populations); re-run the missing cases first"
        )
    # Completeness gate: the compared set must be exactly the declared split. A case
    # both runs silently dropped (harness error, missing score) would slip past the
    # same-population check above and let a candidate pass on an easier subset.
    if set(base_ids) != regression_case_ids:
        missing = regression_case_ids - set(base_ids)
        extra = set(base_ids) - regression_case_ids
        raise ValueError(
            "regression set is incomplete: baseline/candidate must cover exactly the "
            f"declared regression split (missing={missing}, extra={extra}); re-run the "
            "missing cases — a silently dropped case must not pass the gate"
        )
    case_ids = set(base_ids) | set(cand_ids)
    overlap = case_ids & validation_case_ids
    if overlap:
        raise ValueError(f"regression set must be disjoint from validation set; overlap={overlap}")

    b = _labels_by_case(baseline)
    c = _labels_by_case(candidate)
    fixed = sorted(k for k in b if b[k] != "pass" and c.get(k) == "pass")
    newly_broken = sorted(k for k in b if b[k] == "pass" and c.get(k) not in (None, "pass"))

    cand_labels = [s.label for s in candidate]
    base_rate = pass_rate([s.label for s in baseline]).point
    cand_ci = pass_rate(cand_labels)  # candidate case-level Wilson CI (post-aggregation)
    cand_rate = cand_ci.point
    cand_non_pass = sum(1 for label in cand_labels if label != "pass")
    delta = cand_rate - base_rate
    # Descriptive discordance band (NOT a confidence interval, and NOT the gate — the
    # gate is the exact sign test below). The case sets are identical, so the delta is
    # driven entirely by discordant pairs (fixed vs newly-broken); concordant pairs
    # cancel. Put a Wilson band on the fraction of discordant pairs that improved and
    # map it back to a pass-rate delta (delta = (2p - 1) * disc / n) purely as a
    # magnitude cue for the UI; it can disagree with the sign test and that's expected.
    n = len(base_ids)
    disc = len(fixed) + len(newly_broken)
    if disc == 0:
        # No discordant pairs observed. The point delta is 0, but a finite paired
        # sample can't *prove* the true difference is 0 — a zero-width band would
        # falsely claim certainty (badly so on small sets). Rule of three: with 0
        # discordant pairs in n, up to ~3 could plausibly occur, in either
        # direction, so report a symmetric ±3/n band (clamped to the [-1, 1] range
        # of a rate difference). It still straddles 0 → "no_change".
        bound = min(3.0 / n, 1.0)
        delta_low, delta_high = -bound, bound
    else:
        p_ci = pass_rate(["pass"] * len(fixed) + ["fail"] * len(newly_broken))
        delta_low = (2 * p_ci.low - 1) * disc / n
        delta_high = (2 * p_ci.high - 1) * disc / n
    # Decision uses the EXACT paired sign test, not "does the band clear zero" (which
    # is anti-conservative on tiny discordant counts). delta_low/high remain a
    # descriptive band only. When significant, fixed != broken so delta != 0.
    if _sign_test_significant(len(fixed), len(newly_broken)):
        result: RegressionResult = "better" if delta > 0 else "worse"
    else:
        result = "no_change"

    base_fails = _fail_counts(baseline)
    cand_fails = _fail_counts(candidate)
    per_label = [
        {"label": label, "baseline": base_fails.get(label, 0), "candidate": cand_fails.get(label, 0)}
        for label in sorted(set(base_fails) | set(cand_fails))
    ]

    return RegressionReport(
        result=result, judge_version=baseline_judge_version,  # == candidate's, asserted above
        baseline_rate=base_rate, candidate_rate=cand_rate,
        candidate_rate_low=cand_ci.low, candidate_rate_high=cand_ci.high,
        candidate_non_pass_count=cand_non_pass,
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
  exact sign-test decision + descriptive delta band, same-judge + completeness + disjointness asserts;
  `CaseScore.label` is the typed `Label`, validated at ingestion).
- **Deleted-on-purpose:** no `flywheel.*` constants, no context validator, no
  score HTTP client — see "What changed" above; the engine spec §0/§8 record why.
- **Type handoff to plan 02:** `ConfidenceInterval`, `RegressionReport`,
  `CaseScore`, `Label`, `Harness` are imported by `judge.py`/`validate.py`/
  `report.py` and serialized by the read API.
