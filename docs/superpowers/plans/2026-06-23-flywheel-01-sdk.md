# Flywheel 01 — Foundation + L1 SDK Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `flywheel/` repo scaffold and the thin L1 SDK that validates eval identity context, builds `flywheel.*` OTel attributes, computes the harness fingerprint, submits scores to the Flywheel API, and computes local metrics with confidence intervals.

**Architecture:** Pure-Python package `flywheel` with a `sdk/` subpackage. No UI, no taxonomy governance, no trace storage — the SDK only validates context and talks to the Flywheel API over HTTP. Synchronous (`httpx.Client`), matching Bourbon's no-asyncio style.

**Tech Stack:** Python 3.13, pydantic v2, httpx, pytest.

## Global Constraints

(See `2026-06-23-flywheel-00-index.md` → Global Constraints. Every task below inherits them.) Most relevant here:
- `trace_id` is never optional for eval runs; eval identity attrs must be present.
- `failure_labels` are strings validated against the current taxonomy — unknown labels allowed only as open codes, not stable regression categories.
- Score idempotency key is `eval_run_id + case_id + sample_id + source + judge_version`.
- `harness_fingerprint` is a composite of behavior-affecting inputs, not just a git SHA.

---

## File Structure

- Create: `flywheel/pyproject.toml`
- Create: `flywheel/sdk/__init__.py`
- Create: `flywheel/sdk/schema.py` — Label/AnnotationSource literals, `FlywheelAttr` attribute-name constants, type aliases
- Create: `flywheel/sdk/context.py` — `FlywheelContext` validation + OTel attr builder
- Create: `flywheel/sdk/fingerprint.py` — harness fingerprint helpers
- Create: `flywheel/sdk/score_client.py` — `ScoreClient` → Flywheel API
- Create: `flywheel/sdk/metrics.py` — F1, precision, recall, Wilson confidence intervals
- Create: `flywheel/tests/sdk/test_schema.py`, `test_context.py`, `test_fingerprint.py`, `test_score_client.py`, `test_metrics.py`

---

## Task 1: Repo scaffold

**Files:**
- Create: `flywheel/pyproject.toml`
- Create: `flywheel/sdk/__init__.py`
- Create: `flywheel/tests/__init__.py`, `flywheel/tests/sdk/__init__.py`

**Interfaces:**
- Produces: an installable package `flywheel`; `pytest` discovers `flywheel/tests`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
# flywheel/pyproject.toml
[project]
name = "flywheel"
version = "0.1.0"
description = "Self-hosted eval flywheel control plane, engine, and SDK"
requires-python = ">=3.13"
dependencies = [
    "pydantic>=2.6",
    "httpx>=0.27",
]

[project.optional-dependencies]
api = ["fastapi>=0.110", "uvicorn>=0.29"]
dev = ["pytest>=8.0", "ruff>=0.4", "mypy>=1.9", "respx>=0.21"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["sdk", "api", "engine"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.13"
strict = true
```

- [ ] **Step 2: Create empty package markers**

```python
# flywheel/sdk/__init__.py
"""Flywheel L1 SDK: identity context, fingerprint, score submission, metrics."""
```

```python
# flywheel/tests/__init__.py
```

```python
# flywheel/tests/sdk/__init__.py
```

- [ ] **Step 3: Verify install + empty test run**

Run:
```bash
cd flywheel && uv pip install -e ".[dev]" && pytest -q
```
Expected: install succeeds; pytest reports "no tests ran" (exit 5) — acceptable at this step.

- [ ] **Step 4: Commit**

```bash
git add flywheel/pyproject.toml flywheel/sdk/__init__.py flywheel/tests/__init__.py flywheel/tests/sdk/__init__.py
git commit -m "chore(flywheel): scaffold package and test layout"
```

---

## Task 2: schema.py — labels, attribute names, type aliases

**Files:**
- Create: `flywheel/sdk/schema.py`
- Test: `flywheel/tests/sdk/test_schema.py`

**Interfaces:**
- Produces:
  - `Label = Literal["pass", "fail", "skip", "uncertain"]`
  - `AnnotationSource = Literal["human", "judge", "rule", "system"]`
  - `RedactionState = Literal["raw", "redacted", "blocked"]`
  - `Environment = Literal["dev", "ci", "staging", "prod"]`
  - class `FlywheelAttr` with string constants for every `flywheel.*` attribute name in Engine §6.
  - `ALL_EXECUTION_ATTRS: frozenset[str]` and `ALL_SCORE_ATTRS: frozenset[str]`.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/sdk/test_schema.py
from typing import get_args
from sdk.schema import (
    Label, AnnotationSource, FlywheelAttr,
    ALL_EXECUTION_ATTRS, ALL_SCORE_ATTRS,
)


def test_label_values():
    assert set(get_args(Label)) == {"pass", "fail", "skip", "uncertain"}


def test_annotation_source_values():
    assert set(get_args(AnnotationSource)) == {"human", "judge", "rule", "system"}


def test_attr_names_are_namespaced():
    assert FlywheelAttr.EVAL_RUN_ID == "flywheel.eval_run_id"
    assert FlywheelAttr.HARNESS_FINGERPRINT == "flywheel.harness_fingerprint"
    assert all(v.startswith("flywheel.") for v in ALL_EXECUTION_ATTRS)


def test_execution_and_score_attrs_disjoint():
    # Engine §6 splits execution-time attrs from post-hoc score metadata.
    assert ALL_EXECUTION_ATTRS.isdisjoint(ALL_SCORE_ATTRS)
    assert FlywheelAttr.CASE_ID in ALL_EXECUTION_ATTRS
    assert FlywheelAttr.LABEL in ALL_SCORE_ATTRS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/sdk/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdk.schema'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/sdk/schema.py
"""Type aliases, label literals, and flywheel.* attribute-name constants.

Mirrors the Engine design spec §6 semantic contract. Execution-time attrs are
set during agent execution; score/annotation attrs are post-hoc metadata.
"""
from __future__ import annotations

from typing import Literal

Label = Literal["pass", "fail", "skip", "uncertain"]
AnnotationSource = Literal["human", "judge", "rule", "system"]
RedactionState = Literal["raw", "redacted", "blocked"]
Environment = Literal["dev", "ci", "staging", "prod"]


class FlywheelAttr:
    """Canonical flywheel.* OTel attribute names. Use these constants, never literals."""

    # --- execution-time identity (Engine §6) ---
    PROJECT = "flywheel.project"
    ENVIRONMENT = "flywheel.environment"
    TRACE_POOL_ID = "flywheel.trace_pool_id"
    EVAL_RUN_ID = "flywheel.eval_run_id"
    DATASET_ID = "flywheel.dataset_id"
    DATASET_VERSION = "flywheel.dataset_version"
    CASE_ID = "flywheel.case_id"
    SAMPLE_ID = "flywheel.sample_id"
    HARNESS_FINGERPRINT = "flywheel.harness_fingerprint"
    SESSION_ID = "flywheel.session_id"
    TURN_INDEX = "flywheel.turn_index"

    # --- post-hoc score / annotation metadata (Engine §6) ---
    LABEL = "flywheel.label"
    FAILURE_LABELS = "flywheel.failure_labels"
    CRITIQUE = "flywheel.critique"
    CONFIDENCE = "flywheel.confidence"
    ANNOTATION_SOURCE = "flywheel.annotation_source"
    ANNOTATED_BY = "flywheel.annotated_by"
    ANNOTATION_RUBRIC_VERSION = "flywheel.annotation_rubric_version"
    JUDGE_VERSION = "flywheel.judge_version"
    REDACTION_STATE = "flywheel.redaction_state"


ALL_EXECUTION_ATTRS: frozenset[str] = frozenset({
    FlywheelAttr.PROJECT,
    FlywheelAttr.ENVIRONMENT,
    FlywheelAttr.TRACE_POOL_ID,
    FlywheelAttr.EVAL_RUN_ID,
    FlywheelAttr.DATASET_ID,
    FlywheelAttr.DATASET_VERSION,
    FlywheelAttr.CASE_ID,
    FlywheelAttr.SAMPLE_ID,
    FlywheelAttr.HARNESS_FINGERPRINT,
    FlywheelAttr.SESSION_ID,
    FlywheelAttr.TURN_INDEX,
})

ALL_SCORE_ATTRS: frozenset[str] = frozenset({
    FlywheelAttr.LABEL,
    FlywheelAttr.FAILURE_LABELS,
    FlywheelAttr.CRITIQUE,
    FlywheelAttr.CONFIDENCE,
    FlywheelAttr.ANNOTATION_SOURCE,
    FlywheelAttr.ANNOTATED_BY,
    FlywheelAttr.ANNOTATION_RUBRIC_VERSION,
    FlywheelAttr.JUDGE_VERSION,
    FlywheelAttr.REDACTION_STATE,
})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/sdk/test_schema.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/sdk/schema.py flywheel/tests/sdk/test_schema.py
git commit -m "feat(sdk): flywheel.* attribute names and label literals"
```

---

## Task 3: context.py — FlywheelContext validation + OTel attr builder

**Files:**
- Create: `flywheel/sdk/context.py`
- Test: `flywheel/tests/sdk/test_context.py`

**Interfaces:**
- Consumes: `FlywheelAttr`, `Environment` from `sdk.schema`.
- Produces:
  - `class FlywheelContext(BaseModel)` with fields: `project: str`, `environment: Environment`, `harness_fingerprint: str`, and optionals `trace_pool_id`, `eval_run_id`, `dataset_id`, `dataset_version`, `case_id`, `sample_id`, `session_id`, `turn_index: int = 0`.
  - `FlywheelContext.for_eval_run(...)` classmethod that **requires** eval identity fields and raises `ValueError` if any of `eval_run_id`/`dataset_id`/`dataset_version`/`case_id`/`sample_id` is missing.
  - `FlywheelContext.to_otel_attrs() -> dict[str, str | int]` — only non-None fields, keyed by `FlywheelAttr` names.
  - `class ContextError(ValueError)`.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/sdk/test_context.py
import pytest
from sdk.context import FlywheelContext, ContextError
from sdk.schema import FlywheelAttr


def test_eval_run_context_builds_attrs():
    ctx = FlywheelContext.for_eval_run(
        project="bourbon", environment="ci",
        harness_fingerprint="fp_abc",
        eval_run_id="run_1", dataset_id="ds_1", dataset_version="2026-06-22.1",
        case_id="case_1", sample_id="s0",
    )
    attrs = ctx.to_otel_attrs()
    assert attrs[FlywheelAttr.EVAL_RUN_ID] == "run_1"
    assert attrs[FlywheelAttr.CASE_ID] == "case_1"
    assert attrs[FlywheelAttr.HARNESS_FINGERPRINT] == "fp_abc"
    assert attrs[FlywheelAttr.TURN_INDEX] == 0


def test_eval_run_requires_identity():
    with pytest.raises(ContextError, match="case_id"):
        FlywheelContext.for_eval_run(
            project="bourbon", environment="ci", harness_fingerprint="fp",
            eval_run_id="run_1", dataset_id="ds_1", dataset_version="v1",
            case_id="", sample_id="s0",
        )


def test_attrs_omit_none_fields():
    ctx = FlywheelContext(
        project="bourbon", environment="dev", harness_fingerprint="fp",
        trace_pool_id="pool_1",
    )
    attrs = ctx.to_otel_attrs()
    assert attrs[FlywheelAttr.TRACE_POOL_ID] == "pool_1"
    assert FlywheelAttr.EVAL_RUN_ID not in attrs
    assert FlywheelAttr.CASE_ID not in attrs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/sdk/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdk.context'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/sdk/context.py
"""FlywheelContext: validates eval identity and builds flywheel.* OTel attrs."""
from __future__ import annotations

from pydantic import BaseModel

from .schema import Environment, FlywheelAttr


class ContextError(ValueError):
    """Raised when required identity context is missing or invalid."""


class FlywheelContext(BaseModel):
    project: str
    environment: Environment
    harness_fingerprint: str
    trace_pool_id: str | None = None
    eval_run_id: str | None = None
    dataset_id: str | None = None
    dataset_version: str | None = None
    case_id: str | None = None
    sample_id: str | None = None
    session_id: str | None = None
    turn_index: int = 0

    @classmethod
    def for_eval_run(
        cls,
        *,
        project: str,
        environment: Environment,
        harness_fingerprint: str,
        eval_run_id: str,
        dataset_id: str,
        dataset_version: str,
        case_id: str,
        sample_id: str,
        session_id: str | None = None,
        turn_index: int = 0,
    ) -> "FlywheelContext":
        required = {
            "eval_run_id": eval_run_id,
            "dataset_id": dataset_id,
            "dataset_version": dataset_version,
            "case_id": case_id,
            "sample_id": sample_id,
            "harness_fingerprint": harness_fingerprint,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ContextError(f"eval run context missing required fields: {missing}")
        return cls(
            project=project,
            environment=environment,
            harness_fingerprint=harness_fingerprint,
            eval_run_id=eval_run_id,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            case_id=case_id,
            sample_id=sample_id,
            session_id=session_id,
            turn_index=turn_index,
        )

    def to_otel_attrs(self) -> dict[str, str | int]:
        candidates: dict[str, str | int | None] = {
            FlywheelAttr.PROJECT: self.project,
            FlywheelAttr.ENVIRONMENT: self.environment,
            FlywheelAttr.HARNESS_FINGERPRINT: self.harness_fingerprint,
            FlywheelAttr.TRACE_POOL_ID: self.trace_pool_id,
            FlywheelAttr.EVAL_RUN_ID: self.eval_run_id,
            FlywheelAttr.DATASET_ID: self.dataset_id,
            FlywheelAttr.DATASET_VERSION: self.dataset_version,
            FlywheelAttr.CASE_ID: self.case_id,
            FlywheelAttr.SAMPLE_ID: self.sample_id,
            FlywheelAttr.SESSION_ID: self.session_id,
            FlywheelAttr.TURN_INDEX: self.turn_index,
        }
        return {k: v for k, v in candidates.items() if v is not None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/sdk/test_context.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/sdk/context.py flywheel/tests/sdk/test_context.py
git commit -m "feat(sdk): FlywheelContext identity validation and OTel attr builder"
```

---

## Task 4: fingerprint.py — composite harness fingerprint

**Files:**
- Create: `flywheel/sdk/fingerprint.py`
- Test: `flywheel/tests/sdk/test_fingerprint.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class HarnessComponents` with fields: `git_sha`, `prompt_version`, `skill_versions: tuple[str, ...]`, `tool_schema_version`, `memory_config_hash`, `model_provider`, `model_snapshot`, `decoding_params: tuple[tuple[str, str], ...]`, `dependency_lock_hash`, `env_config_hash`.
  - `compute_fingerprint(components: HarnessComponents) -> str` — deterministic, order-independent for unordered fields, returns `"fp_" + sha256[:16]`.
  - Same components → same fingerprint; any change → different fingerprint.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/sdk/test_fingerprint.py
from sdk.fingerprint import HarnessComponents, compute_fingerprint


def _components(**overrides):
    base = dict(
        git_sha="abc123",
        prompt_version="p1",
        skill_versions=("skill-a@1", "skill-b@2"),
        tool_schema_version="t1",
        memory_config_hash="m1",
        model_provider="anthropic",
        model_snapshot="claude-opus-4-8",
        decoding_params=(("temperature", "0.0"),),
        dependency_lock_hash="lock1",
        env_config_hash="env1",
    )
    base.update(overrides)
    return HarnessComponents(**base)


def test_fingerprint_is_deterministic():
    a = compute_fingerprint(_components())
    b = compute_fingerprint(_components())
    assert a == b
    assert a.startswith("fp_")


def test_skill_order_does_not_matter():
    a = compute_fingerprint(_components(skill_versions=("skill-a@1", "skill-b@2")))
    b = compute_fingerprint(_components(skill_versions=("skill-b@2", "skill-a@1")))
    assert a == b


def test_any_behavior_change_changes_fingerprint():
    base = compute_fingerprint(_components())
    assert compute_fingerprint(_components(model_snapshot="claude-sonnet-4-6")) != base
    assert compute_fingerprint(_components(prompt_version="p2")) != base
    assert compute_fingerprint(_components(decoding_params=(("temperature", "0.7"),))) != base
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/sdk/test_fingerprint.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdk.fingerprint'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/sdk/fingerprint.py
"""Composite harness fingerprint (Engine §6). Behavior identity, not just git SHA."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class HarnessComponents:
    git_sha: str
    prompt_version: str
    skill_versions: tuple[str, ...]
    tool_schema_version: str
    memory_config_hash: str
    model_provider: str
    model_snapshot: str
    decoding_params: tuple[tuple[str, str], ...]
    dependency_lock_hash: str
    env_config_hash: str


def compute_fingerprint(components: HarnessComponents) -> str:
    """Stable, order-independent fingerprint. Sets/maps are sorted before hashing."""
    raw = asdict(components)
    normalized = {
        "git_sha": raw["git_sha"],
        "prompt_version": raw["prompt_version"],
        "skill_versions": sorted(raw["skill_versions"]),
        "tool_schema_version": raw["tool_schema_version"],
        "memory_config_hash": raw["memory_config_hash"],
        "model_provider": raw["model_provider"],
        "model_snapshot": raw["model_snapshot"],
        "decoding_params": sorted(raw["decoding_params"]),
        "dependency_lock_hash": raw["dependency_lock_hash"],
        "env_config_hash": raw["env_config_hash"],
    }
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"fp_{digest[:16]}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/sdk/test_fingerprint.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/sdk/fingerprint.py flywheel/tests/sdk/test_fingerprint.py
git commit -m "feat(sdk): composite harness fingerprint helpers"
```

---

## Task 5: metrics.py — F1, precision, recall, Wilson CI

**Files:**
- Create: `flywheel/sdk/metrics.py`
- Test: `flywheel/tests/sdk/test_metrics.py`

**Interfaces:**
- Produces:
  - `precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]`.
  - `@dataclass(frozen=True) class ConfidenceInterval` with `point: float`, `low: float`, `high: float`.
  - `wilson_interval(successes: int, n: int, z: float = 1.96) -> ConfidenceInterval` — pass-rate CI; `n == 0` returns `(0.0, 0.0, 1.0)`.
  - `pass_rate(labels: list[str]) -> ConfidenceInterval` — treats `"pass"` as success.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/sdk/test_metrics.py
import math
from sdk.metrics import precision_recall_f1, wilson_interval, pass_rate


def test_precision_recall_f1_basic():
    p, r, f1 = precision_recall_f1(tp=8, fp=2, fn=2)
    assert math.isclose(p, 0.8)
    assert math.isclose(r, 0.8)
    assert math.isclose(f1, 0.8)


def test_zero_division_is_safe():
    assert precision_recall_f1(tp=0, fp=0, fn=0) == (0.0, 0.0, 0.0)


def test_wilson_interval_brackets_point():
    ci = wilson_interval(successes=9, n=10)
    assert 0.0 <= ci.low < ci.point < ci.high <= 1.0
    assert math.isclose(ci.point, 0.9)


def test_wilson_empty_is_full_uncertainty():
    ci = wilson_interval(successes=0, n=0)
    assert (ci.point, ci.low, ci.high) == (0.0, 0.0, 1.0)


def test_pass_rate_from_labels():
    ci = pass_rate(["pass", "pass", "fail", "skip"])
    assert math.isclose(ci.point, 0.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/sdk/test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdk.metrics'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/sdk/metrics.py
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
    """Wilson score interval. n==0 -> maximal uncertainty (0, 0, 1)."""
    if n == 0:
        return ConfidenceInterval(point=0.0, low=0.0, high=1.0)
    phat = successes / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)) / denom
    return ConfidenceInterval(
        point=phat,
        low=max(0.0, center - margin),
        high=min(1.0, center + margin),
    )


def pass_rate(labels: list[str]) -> ConfidenceInterval:
    successes = sum(1 for label in labels if label == "pass")
    return wilson_interval(successes=successes, n=len(labels))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/sdk/test_metrics.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/sdk/metrics.py flywheel/tests/sdk/test_metrics.py
git commit -m "feat(sdk): precision/recall/F1 and Wilson confidence intervals"
```

---

## Task 6: score_client.py — submit scores to Flywheel API

**Files:**
- Create: `flywheel/sdk/score_client.py`
- Test: `flywheel/tests/sdk/test_score_client.py`

**Interfaces:**
- Consumes: `FlywheelContext` (`sdk.context`), `Label`/`AnnotationSource` (`sdk.schema`).
- Produces:
  - `@dataclass(frozen=True) class ScorePayload` with `eval_run_id`, `case_id`, `sample_id`, `label: Label`, `source: AnnotationSource`, `judge_version: str | None`, `failure_labels: list[str]`, `confidence: float | None`, `critique: str | None`.
  - `ScorePayload.idempotency_key() -> str` = `f"{eval_run_id}:{case_id}:{sample_id}:{source}:{judge_version or 'none'}"`.
  - `class ScoreClient` constructed with `base_url: str`, `api_token: str`, optional `client: httpx.Client`. Method `submit(payload: ScorePayload) -> dict` POSTs to `{base_url}/api/runs/{eval_run_id}/scores` with header `Idempotency-Key` and `Authorization: Bearer {token}`; returns parsed JSON. Raises `ScoreSubmitError` on non-2xx.

- [ ] **Step 1: Write the failing test** (uses `respx` to mock httpx)

```python
# flywheel/tests/sdk/test_score_client.py
import httpx
import respx
import pytest
from sdk.score_client import ScoreClient, ScorePayload, ScoreSubmitError


def _payload(**overrides):
    base = dict(
        eval_run_id="run_1", case_id="case_1", sample_id="s0",
        label="fail", source="judge", judge_version="jv_1",
        failure_labels=["tool_argument_error"], confidence=0.9, critique="bad arg",
    )
    base.update(overrides)
    return ScorePayload(**base)


def test_idempotency_key_shape():
    key = _payload().idempotency_key()
    assert key == "run_1:case_1:s0:judge:jv_1"


def test_idempotency_key_handles_missing_judge():
    assert _payload(judge_version=None, source="human").idempotency_key() == \
        "run_1:case_1:s0:human:none"


@respx.mock
def test_submit_posts_with_idempotency_header():
    route = respx.post("http://api/api/runs/run_1/scores").mock(
        return_value=httpx.Response(200, json={"ok": True, "audit_event_id": "ae_1"})
    )
    client = ScoreClient(base_url="http://api", api_token="tok")
    result = client.submit(_payload())
    assert result["audit_event_id"] == "ae_1"
    sent = route.calls.last.request
    assert sent.headers["Idempotency-Key"] == "run_1:case_1:s0:judge:jv_1"
    assert sent.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_submit_raises_on_error():
    respx.post("http://api/api/runs/run_1/scores").mock(
        return_value=httpx.Response(422, json={"detail": "bad label"})
    )
    client = ScoreClient(base_url="http://api", api_token="tok")
    with pytest.raises(ScoreSubmitError, match="422"):
        client.submit(_payload())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/sdk/test_score_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdk.score_client'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/sdk/score_client.py
"""ScoreClient: submit judge/rule/human scores to the Flywheel API Score Bridge."""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from .schema import AnnotationSource, Label


class ScoreSubmitError(RuntimeError):
    """Raised when the Flywheel API rejects a score submission."""


@dataclass(frozen=True)
class ScorePayload:
    eval_run_id: str
    case_id: str
    sample_id: str
    label: Label
    source: AnnotationSource
    judge_version: str | None = None
    failure_labels: list[str] = field(default_factory=list)
    confidence: float | None = None
    critique: str | None = None

    def idempotency_key(self) -> str:
        # Engine §9: eval_run_id + case_id + sample_id + source + judge_version
        return f"{self.eval_run_id}:{self.case_id}:{self.sample_id}:{self.source}:{self.judge_version or 'none'}"

    def to_body(self) -> dict:
        return {
            "case_id": self.case_id,
            "sample_id": self.sample_id,
            "label": self.label,
            "source": self.source,
            "judge_version": self.judge_version,
            "failure_labels": self.failure_labels,
            "confidence": self.confidence,
            "critique": self.critique,
        }


class ScoreClient:
    def __init__(self, base_url: str, api_token: str, client: httpx.Client | None = None):
        self._base_url = base_url.rstrip("/")
        self._token = api_token
        self._client = client or httpx.Client(timeout=30.0)

    def submit(self, payload: ScorePayload) -> dict:
        url = f"{self._base_url}/api/runs/{payload.eval_run_id}/scores"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Idempotency-Key": payload.idempotency_key(),
        }
        response = self._client.post(url, json=payload.to_body(), headers=headers)
        if response.status_code >= 300:
            raise ScoreSubmitError(
                f"score submit failed {response.status_code}: {response.text}"
            )
        return response.json()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/sdk/test_score_client.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Run full SDK suite + lint + types**

Run:
```bash
cd flywheel && pytest tests/sdk -q && ruff check sdk tests && mypy sdk
```
Expected: all tests pass; ruff clean; mypy clean.

- [ ] **Step 6: Commit**

```bash
git add flywheel/sdk/score_client.py flywheel/tests/sdk/test_score_client.py
git commit -m "feat(sdk): ScoreClient with idempotent score submission"
```

---

## Self-Review

- **Spec coverage (Engine §6, §7):** schema.py covers execution + post-hoc attr split (§6); context.py validates eval identity and `trace_id` requirement is enforced upstream by requiring `eval_run_id` (§6); fingerprint.py implements the composite fingerprint list (§6); score_client.py implements the §9 idempotency key; metrics.py implements F1/precision/recall/CI (§7). `failure_labels` validation against the live taxonomy is enforced server-side in plan 02 (the SDK passes strings through, as §7 states the SDK is a thin layer).
- **Placeholder scan:** no TBD/TODO; every code step shows complete code.
- **Type consistency:** `ScorePayload` field names (`eval_run_id`, `case_id`, `sample_id`, `source`, `judge_version`) match the idempotency key used by the API in plan 02. `ConfidenceInterval(point, low, high)` is reused by plan 07 regression stats.
