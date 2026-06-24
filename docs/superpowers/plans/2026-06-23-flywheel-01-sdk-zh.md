# Flywheel 01 — 基础架构 + L1 SDK 实现计划

> **对于智能体工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现本计划。步骤使用复选框（`- [ ]`）语法进行跟踪。

**目标：** 创建 `flywheel/` 仓库脚手架和轻量 L1 SDK，用于验证评估身份上下文、构建 `flywheel.*` OTel 属性、计算测试框架指纹、向 Flywheel API 提交评分，并计算带置信区间的本地指标。

**架构：** 纯 Python 包 `flywheel`，带有 `sdk/` 子包。无 UI，无分类治理，无轨迹存储 —— SDK 仅验证上下文并通过 HTTP 与 Flywheel API 通信。同步（`httpx.Client`），匹配 Bourbon 的无 asyncio 风格。

**技术栈：** Python 3.13, pydantic v2, httpx, pytest。

## 全局约束

（见 `2026-06-23-flywheel-00-index.md` → 全局约束。以下任务均继承。）最相关的约束：
- 评估运行的 `trace_id` 绝不可选；评估身份属性必须存在。
- `failure_labels` 是针对当前分类验证的字符串 —— 未知标签仅允许作为开放代码，不能作为稳定的回归类别。
- 评分幂等键为 `eval_run_id + case_id + sample_id + source + judge_version`。
- `harness_fingerprint` 是行为影响输入的复合，不仅仅是 git SHA。

---

## 文件结构

- 创建：`flywheel/pyproject.toml`
- 创建：`flywheel/sdk/__init__.py`
- 创建：`flywheel/sdk/schema.py` — Label/AnnotationSource 字面量、`FlywheelAttr` 属性名常量、类型别名
- 创建：`flywheel/sdk/context.py` — `FlywheelContext` 验证 + OTel 属性构建器
- 创建：`flywheel/sdk/fingerprint.py` — 测试框架指纹助手
- 创建：`flywheel/sdk/score_client.py` — `ScoreClient` → Flywheel API
- 创建：`flywheel/sdk/metrics.py` — F1、精确率、召回率、Wilson 置信区间
- 创建：`flywheel/tests/sdk/test_schema.py`、`test_context.py`、`test_fingerprint.py`、`test_score_client.py`、`test_metrics.py`

---

## 任务 1：仓库脚手架

**文件：**
- 创建：`flywheel/pyproject.toml`
- 创建：`flywheel/sdk/__init__.py`
- 创建：`flywheel/tests/__init__.py`、`flywheel/tests/sdk/__init__.py`

**接口：**
- 产出：可安装的包 `flywheel`；`pytest` 发现 `flywheel/tests`。

- [ ] **步骤 1：编写 `pyproject.toml`**

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

- [ ] **步骤 2：创建空包标记**

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

- [ ] **步骤 3：验证安装 + 空测试运行**

运行：
```bash
cd flywheel && uv pip install -e ".[dev]" && pytest -q
```
预期：安装成功；pytest 报告"no tests ran"（退出码 5）—— 此步骤可接受。

- [ ] **步骤 4：提交**

```bash
git add flywheel/pyproject.toml flywheel/sdk/__init__.py flywheel/tests/__init__.py flywheel/tests/sdk/__init__.py
git commit -m "chore(flywheel): scaffold package and test layout"
```

---

## 任务 2：schema.py — 标签、属性名、类型别名

**文件：**
- 创建：`flywheel/sdk/schema.py`
- 测试：`flywheel/tests/sdk/test_schema.py`

**接口：**
- 产出：
  - `Label = Literal["pass", "fail", "skip", "uncertain"]`
  - `AnnotationSource = Literal["human", "judge", "rule", "system"]`
  - `RedactionState = Literal["raw", "redacted", "blocked"]`
  - `Environment = Literal["dev", "ci", "staging", "prod"]`
  - 类 `FlywheelAttr` 包含引擎 §6 中每个 `flywheel.*` 属性名的字符串常量。
  - `ALL_EXECUTION_ATTRS: frozenset[str]`、`ALL_SCORE_ATTRS: frozenset[str]` 和 `ALL_ANALYSIS_ATTRS: frozenset[str]`。

- [ ] **步骤 1：编写失败测试**

```python
# flywheel/tests/sdk/test_schema.py
from typing import get_args
from sdk.schema import (
    Label, AnnotationSource, FlywheelAttr,
    ALL_EXECUTION_ATTRS, ALL_SCORE_ATTRS, ALL_ANALYSIS_ATTRS,
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


def test_analysis_attrs_complete():
    assert FlywheelAttr.ISSUE_ID == "flywheel.issue_id"
    assert FlywheelAttr.PROPOSAL_STATE == "flywheel.proposal_state"
    assert all(v.startswith("flywheel.") for v in ALL_ANALYSIS_ATTRS)
    assert len(ALL_ANALYSIS_ATTRS) == 8
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd flywheel && pytest tests/sdk/test_schema.py -v`
预期：失败并显示 `ModuleNotFoundError: No module named 'sdk.schema'`。

- [ ] **步骤 3：编写最小实现**

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

    # --- analysis and proposal metadata (Engine §6) ---
    ISSUE_ID = "flywheel.issue_id"
    CLUSTER_ID = "flywheel.cluster_id"
    PROPOSAL_ID = "flywheel.proposal_id"
    PROPOSAL_STATE = "flywheel.proposal_state"
    REGRESSION_STATUS = "flywheel.regression_status"
    REGRESSION_OUTCOME = "flywheel.regression_outcome"
    BASELINE_FINGERPRINT = "flywheel.baseline_fingerprint"
    CANDIDATE_FINGERPRINT = "flywheel.candidate_fingerprint"


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

ALL_ANALYSIS_ATTRS: frozenset[str] = frozenset({
    FlywheelAttr.ISSUE_ID,
    FlywheelAttr.CLUSTER_ID,
    FlywheelAttr.PROPOSAL_ID,
    FlywheelAttr.PROPOSAL_STATE,
    FlywheelAttr.REGRESSION_STATUS,
    FlywheelAttr.REGRESSION_OUTCOME,
    FlywheelAttr.BASELINE_FINGERPRINT,
    FlywheelAttr.CANDIDATE_FINGERPRINT,
})
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd flywheel && pytest tests/sdk/test_schema.py -v`
预期：通过（5 passed）。

- [ ] **步骤 5：提交**

```bash
git add flywheel/sdk/schema.py flywheel/tests/sdk/test_schema.py
git commit -m "feat(sdk): flywheel.* attribute names and label literals"
```

---

## 任务 3：context.py — FlywheelContext 验证 + OTel 属性构建器

**文件：**
- 创建：`flywheel/sdk/context.py`
- 测试：`flywheel/tests/sdk/test_context.py`

**接口：**
- 消费：`FlywheelAttr`、`Environment`（来自 `sdk.schema`）。
- 产出：
  - `class FlywheelContext(BaseModel)`，字段：`project: str`、`environment: Environment`、`harness_fingerprint: str`，以及可选的 `trace_pool_id`、`eval_run_id`、`dataset_id`、`dataset_version`、`case_id`、`sample_id`、`session_id`、`turn_index: int = 0`。
  - `FlywheelContext.for_eval_run(...)` 类方法，**要求**评估身份字段，如果 `eval_run_id`/`dataset_id`/`dataset_version`/`case_id`/`sample_id` 任何缺失则抛出 `ValueError`。
  - `FlywheelContext.to_otel_attrs() -> dict[str, str | int]` — 仅非 None 字段，以 `FlywheelAttr` 名称为键。
  - `class ContextError(ValueError)`。

- [ ] **步骤 1：编写失败测试**

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

- [ ] **步骤 2：运行测试验证失败**

运行：`cd flywheel && pytest tests/sdk/test_context.py -v`
预期：失败并显示 `ModuleNotFoundError: No module named 'sdk.context'`。

- [ ] **步骤 3：编写最小实现**

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

- [ ] **步骤 4：运行测试验证通过**

运行：`cd flywheel && pytest tests/sdk/test_context.py -v`
预期：通过（3 passed）。

- [ ] **步骤 5：提交**

```bash
git add flywheel/sdk/context.py flywheel/tests/sdk/test_context.py
git commit -m "feat(sdk): FlywheelContext identity validation and OTel attr builder"
```

---

## 任务 4：fingerprint.py — 复合测试框架指纹

**文件：**
- 创建：`flywheel/sdk/fingerprint.py`
- 测试：`flywheel/tests/sdk/test_fingerprint.py`

**接口：**
- 产出：
  - `@dataclass(frozen=True) class HarnessComponents`，字段：`git_sha`、`prompt_version`、`skill_versions: tuple[str, ...]`、`tool_schema_version`、`memory_config_hash`、`model_provider`、`model_snapshot`、`decoding_params: tuple[tuple[str, str], ...]`、`dependency_lock_hash`、`env_config_hash`。
  - `compute_fingerprint(components: HarnessComponents) -> str` — 确定性、无序字段顺序无关，返回 `"fp_" + sha256[:16]`。
  - 相同组件 → 相同指纹；任何变更 → 不同指纹。

- [ ] **步骤 1：编写失败测试**

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

- [ ] **步骤 2：运行测试验证失败**

运行：`cd flywheel && pytest tests/sdk/test_fingerprint.py -v`
预期：失败并显示 `ModuleNotFoundError: No module named 'sdk.fingerprint'`。

- [ ] **步骤 3：编写最小实现**

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

- [ ] **步骤 4：运行测试验证通过**

运行：`cd flywheel && pytest tests/sdk/test_fingerprint.py -v`
预期：通过（3 passed）。

- [ ] **步骤 5：提交**

```bash
git add flywheel/sdk/fingerprint.py flywheel/tests/sdk/test_fingerprint.py
git commit -m "feat(sdk): composite harness fingerprint helpers"
```

---

## 任务 5：metrics.py — F1、精确率、召回率、Wilson CI

**文件：**
- 创建：`flywheel/sdk/metrics.py`
- 测试：`flywheel/tests/sdk/test_metrics.py`

**接口：**
- 产出：
  - `precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]`。
  - `@dataclass(frozen=True) class ConfidenceInterval`，含 `point: float`、`low: float`、`high: float`。
  - `wilson_interval(successes: int, n: int, z: float = 1.96) -> ConfidenceInterval` — 通过率 CI；`n == 0` 返回 `(0.0, 0.0, 1.0)`。
  - `pass_rate(labels: list[str]) -> ConfidenceInterval` — 将 `"pass"` 视为成功。

- [ ] **步骤 1：编写失败测试**

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


def test_pass_rate_skip_uncertain_count_as_attempts():
    # "skip" and "uncertain" are in denominator but not successes (policy locked here)
    ci = pass_rate(["pass", "pass", "skip", "uncertain"])
    assert math.isclose(ci.point, 0.5)  # 2/4
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd flywheel && pytest tests/sdk/test_metrics.py -v`
预期：失败并显示 `ModuleNotFoundError: No module named 'sdk.metrics'`。

- [ ] **步骤 3：编写最小实现**

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
    """Pass rate CI. Denominator = len(labels); "skip" and "uncertain" count as attempts, not successes."""
    successes = sum(1 for label in labels if label == "pass")
    return wilson_interval(successes=successes, n=len(labels))
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd flywheel && pytest tests/sdk/test_metrics.py -v`
预期：通过（5 passed）。

- [ ] **步骤 5：提交**

```bash
git add flywheel/sdk/metrics.py flywheel/tests/sdk/test_metrics.py
git commit -m "feat(sdk): precision/recall/F1 and Wilson confidence intervals"
```

---

## 任务 6：score_client.py — 向 Flywheel API 提交评分

**文件：**
- 创建：`flywheel/sdk/score_client.py`
- 测试：`flywheel/tests/sdk/test_score_client.py`

**接口：**
- 消费：`FlywheelContext`（`sdk.context`）、`Label`/`AnnotationSource`（`sdk.schema`）。
- 产出：
  - `@dataclass(frozen=True) class ScorePayload`，含 `eval_run_id`、`case_id`、`sample_id`、`label: Label`、`source: AnnotationSource`、`judge_version: str | None`、`failure_labels: list[str]`、`confidence: float | None`、`critique: str | None`、`trace_id: str`。
  - `ScorePayload.idempotency_key() -> str` = `f"{eval_run_id}:{case_id}:{sample_id}:{source}:{judge_version or 'none'}"`。
  - `class ScoreClient`，构造参数 `base_url: str`、`api_token: str`、可选 `client: httpx.Client`。方法 `submit(payload: ScorePayload) -> dict` POST 到 `{base_url}/api/runs/{eval_run_id}/scores`，带 header `Idempotency-Key` 和 `Authorization: Bearer {token}`；返回解析的 JSON。非 2xx 时抛出 `ScoreSubmitError`。

- [ ] **步骤 1：编写失败测试**（使用 `respx` 模拟 httpx）

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
        trace_id="abcdef0123456789abcdef0123456789",
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
    import json
    body = json.loads(sent.content)
    assert body["trace_id"] == "abcdef0123456789abcdef0123456789"


@respx.mock
def test_submit_raises_on_error():
    respx.post("http://api/api/runs/run_1/scores").mock(
        return_value=httpx.Response(422, json={"detail": "bad label"})
    )
    client = ScoreClient(base_url="http://api", api_token="tok")
    with pytest.raises(ScoreSubmitError, match="422"):
        client.submit(_payload())
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd flywheel && pytest tests/sdk/test_score_client.py -v`
预期：失败并显示 `ModuleNotFoundError: No module named 'sdk.score_client'`。

- [ ] **步骤 3：编写最小实现**

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
    trace_id: str  # W3C TraceContext trace_id; required by ScoreBridge → Langfuse (Engine §8)
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
            "trace_id": self.trace_id,
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

- [ ] **步骤 4：运行测试验证通过**

运行：`cd flywheel && pytest tests/sdk/test_score_client.py -v`
预期：通过（4 passed）。

- [ ] **步骤 5：运行完整 SDK 套件 + lint + 类型**

运行：
```bash
cd flywheel && pytest tests/sdk -q && ruff check sdk tests && mypy sdk
```
预期：所有测试通过；ruff 干净；mypy 干净。

- [ ] **步骤 6：提交**

```bash
git add flywheel/sdk/score_client.py flywheel/tests/sdk/test_score_client.py
git commit -m "feat(sdk): ScoreClient with idempotent score submission"
```

---

## 自我审查

- **规格覆盖（引擎 §6, §7）：** schema.py 涵盖执行时 + 事后 + 分析/提案属性分割（§6）；context.py 验证评估身份 —— 注意 `eval_run_id` 仅验证应用层身份；**调用者**必须确保在调用 `for_eval_run()` 前 OTel 上下文活跃（trace_id 存在于 span 上），因为 `eval_run_id` 不能替代 trace_id（引擎 §6, §4）；fingerprint.py 实现复合指纹列表（§6）；score_client.py 实现 §9 幂等键；metrics.py 实现 F1/精确率/recall/CI，针对 skip/uncertain 锁定分母策略（§7）。根据 §7，SDK 是轻量层，`failure_labels` 针对实时分类的验证在服务端（计划 02）强制执行（SDK 传递字符串）。
- **占位符扫描：** 无 TBD/TODO；每个代码步骤显示完整代码。
- **类型一致性：** `ScorePayload` 字段名（`eval_run_id`、`case_id`、`sample_id`、`source`、`judge_version`）与计划 02 API 中使用的幂等键匹配。`ConfidenceInterval(point, low, high)` 被计划 07 回归模块重用。