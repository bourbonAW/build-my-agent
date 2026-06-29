# Flywheel 01 — 核心库（精简版）实现计划
**日期**: 2026-06-23（精简修订版 2026-06-24）
**状态**: 精简 MVP — 取代之前的"基础 + L1 SDK"计划

> **致 agentic workers:** 必需子技能: superpowers:test-driven-development。
> 步骤使用复选框（`- [ ]`）语法进行跟踪。

**目标:** 创建小型 `flywheel/` 包和纯逻辑核心：最小化身份模型、评估指标（precision/recall/F1 + Wilson CI）、以及返回 `better | no_change | worse` 的回归比较。不含 HTTP SDK、不含 score client、不含 API client — 这些已随控制平面一起删除。

**架构:** 纯 Python 包 `flywheel`，同步，无 asyncio。
Engine spec §3–§7 是契约。

**技术栈:** Python 3.13, pydantic v2（仅在验证有帮助时使用）, pytest。

## 与旧计划相比的变更
- **删除了** `sdk/schema.py`（`flywheel.*` 属性常量）、`sdk/context.py`
  （`FlywheelContext` 含 5 个 eval-identity 字段）、`sdk/score_client.py`
  （`ScoreClient` → Flywheel API）。原因：不再使用 `flywheel.*` 约定（改用
  `gen_ai.*` + 两个 `eval.*` 字符串），且无控制平面 API 可调用。
- **保留了** `metrics.py` 基本不变 — 这是唯一具有独立价值的模块。
- **精简了** 指纹，从 8 个组件缩减为 `git_sha + model`。
- **新增了** `regression.py`（三值比较）和扁平的 `labels.md`。

## 文件结构
- 创建: `flywheel/pyproject.toml`
- 创建: `flywheel/flywheel/__init__.py`
- 创建: `flywheel/flywheel/identity.py` — `Harness`、`case_id`/`run_id` 辅助函数、`Label`
- 创建: `flywheel/flywheel/metrics.py` — precision/recall/F1、Wilson CI、pass_rate
- 创建: `flywheel/flywheel/regression.py` — `compare()` → `RegressionResult`
- 创建: `flywheel/labels.md` — 扁平可编辑的失败标签列表（种子）
- 创建: `flywheel/tests/__init__.py`、`flywheel/tests/test_identity.py`、`test_metrics.py`、`test_regression.py`

---

## 任务 1: 仓库脚手架

**文件:** `flywheel/pyproject.toml`、`flywheel/flywheel/__init__.py`、`flywheel/tests/__init__.py`

- [x] **步骤 1: `pyproject.toml`**

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

- [x] **步骤 2:** 创建 `flywheel/flywheel/__init__.py`（文档字符串）和 `flywheel/tests/__init__.py`（空文件）。
- [x] **步骤 3:** `cd flywheel && uv pip install -e ".[dev]" && pytest -q` → 安装成功，"no tests ran"（退出码 5）可接受。
- [ ] **步骤 4:** 提交 `chore(flywheel): scaffold lean package`。

---

## 任务 2: identity.py — Harness、Label、id 辅助函数

**接口:**
- `Label = Literal["pass", "fail", "skip", "uncertain"]` — 任意裁定：人工、judge 或运营。`pass`/`fail` 是门控分类；`skip`（用例未运行）和 `uncertain`（judge 弃权）是非成功，永远不算通过。
- `HumanLabel = Literal["pass", "fail"]` — **人工**标注是金标准且为二元的（无 `skip`/`uncertain`）。judge 裁定可以是 `uncertain`；人工裁定不可以。
- `@dataclass(frozen=True) class Harness(git_sha: str, model: str)` 含 `id() -> str` = `f"{git_sha[:7]}@{model}"`。
- `JudgeVersion = str`（别名；一个 **URL 安全的 slug** `^[A-Za-z0-9._@-]+$`，因为它是报告文件名 / `/api/judges/{judge_version}` 路径段 — 不是生命周期）。
- `validate_judge_version(value: str) -> str` — 除非 `value` 匹配 JudgeVersion slug 否则抛出 `ValueError`；在类型边界（`compare()`、`validate()`、`JudgeConfig.__post_init__`）强制执行，而非仅在报告写入时。

- [x] **步骤 1: 失败测试** `tests/test_identity.py`

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

- [x] **步骤 2:** 运行 → 失败（`ModuleNotFoundError`）。
- [x] **步骤 3: 实现** `flywheel/flywheel/identity.py`

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

- [x] **步骤 4:** 运行 → 通过。**步骤 5:** 提交 `feat(flywheel): minimal identity (Harness + Label)`。

---

## 任务 3: metrics.py — precision/recall/F1、Wilson CI

（从旧计划延续 — 唯一保持不变的模块。）

**接口:**
- `precision_recall_f1(tp, fp, fn) -> tuple[float, float, float]`
- `@dataclass(frozen=True) ConfidenceInterval(point, low, high)`
- `wilson_interval(successes, n, z=1.96) -> ConfidenceInterval`（n==0 → (0,0,1)）
- `pass_rate(labels: list[str]) -> ConfidenceInterval`（"pass" = 成功；skip/uncertain 计为尝试）

- [x] **步骤 1: 失败测试** `tests/test_metrics.py`

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

- [x] **步骤 2:** 运行 → 失败。**步骤 3: 实现** `flywheel/flywheel/metrics.py`

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

- [x] **步骤 4:** 运行 → 通过。**步骤 5:** 提交 `feat(flywheel): precision/recall/F1 and Wilson CI`。

---

## 任务 4: regression.py — 三值比较

**接口:**
- `RegressionResult = Literal["better", "no_change", "worse"]`
- `@dataclass(frozen=True) class CaseScore(case_id: str, label: Label, failure_label: str | None = None)` — `label` 是类型化的 `Label`（`pass`/`fail`/`skip`/`uncertain`）；`__post_init__` 拒绝任何其他值，使得格式错误的 Langfuse 评分（`"PASS"`、`"error"`、`""`）在摄入时报错，而非被静默误计为失败。`failure_label` 是来自 `labels.md` / Langfuse 评分注释的自由字符串，用于按标签增量分析（Engine §7）。
- `@dataclass(frozen=True) class RegressionReport(result, judge_version, baseline_rate, candidate_rate, candidate_rate_low, candidate_rate_high, candidate_non_pass_count, delta, delta_low, delta_high, fixed, newly_broken, per_label)` — `judge_version` 是 `compare()` 断言双方共享的单一版本（因此 report.py 序列化的是*门控*版本，而非任意调用者字符串）；`delta_low/high` 是 delta 的**描述性差异带**（量级线索，**不是**置信区间，也**不是**门控 — 决策是精确符号检验；该带可以不一致，参见 `compare()`），被序列化以便 report.py 显示非零宽度带；`candidate_rate` + `candidate_rate_low/high` 是候选运行的**用例级** Wilson CI，`candidate_non_pass_count` 是其用例级非通过计数，从 `compare()` 门控所用的**相同聚合分数**计算 — 因此 `RunSummary.passRate`/`nonPassCount`（从报告中提供）永远不会与带有重复的运行的回归报告产生分歧；`fixed`/`newly_broken` 是用例 id 列表；`per_label` 是 `[{label, baseline, candidate}]` 失败计数（无 `failure_label` 的非通过用例归入 `"unlabeled"` 桶，永不静默丢弃）。
- `compare(baseline, candidate, *, regression_case_ids: set[str], validation_case_ids: set[str], baseline_judge_version: str, candidate_judge_version: str) -> RegressionReport`
  - **同一 judge 门控（Engine §7）：** 如果两个 judge 版本不同则抛出 `ValueError` — 基线/候选必须由同一 judge 评分，或先重新评分。
  - **完整性门控：** 除非被比较的用例**恰好**是 `regression_case_ids`（从数据集读取的完整声明回归拆分），否则抛出 `ValueError`。静默丢弃的用例（harness 错误、缺失评分）不得让候选在更简单的子集上通过门控；"双方相同的评分 id"单独无法捕获双方都跳过的用例。
  - **不相交门控（Engine §5/§7）：** 如果被比较的用例 id 与 `validation_case_ids` 重叠则抛出 `ValueError`。该集合是**完整的 judge 验证集** — 所有人工标注 judge 用例的并集（`judge_train ∪ judge_dev ∪ judge_test`），不仅是保留的 `judge_test` 拆分，因为作为 few-shot（`train`）或 prompt-tuning（`dev`）用例的回归用例同样是泄漏。回归集是数据集的**回归拆分**；调用者从 Langfuse 数据集元数据中读取两者。
  - 通过对不一致对的**精确双边配对符号检验**（McNemar exact）分配 `better`/`worse`/`no_change`（Engine §7）；Wilson delta CI 仅作为描述性区间保留（在少量不一致计数上它是反保守的）。
- `aggregate_repeats(scores: list[CaseScore]) -> list[CaseScore]` — 将同一 `case_id` 的重复评分（Engine §7 "对非确定性用例采样 ≥3 次"）通过多数投票合并为一个 `CaseScore`：一个用例仅在其重复的严格多数通过时为 `pass`（平局 → 非通过，保守）；保留的 `failure_label` 是非通过重复中最常见的。单次运行的用例直接传递不变，因此不重复的调用者不受影响。`run_regression.py`（计划 02 任务 6）在 `compare()` 之前调用此函数。
- `check_repeat_budgets(baseline, candidate, *, min_repeats=3) -> None` — 纯函数、可单元测试的守卫，在 `aggregate_repeats`（会丢弃计数）**之前**运行：如果任何用例在基线/候选之间的评分计数**不等**（不公平的多数投票）或被采样 `>1` 次但 `< min_repeats`（欠动力半样本），则抛出 `ValueError`。`compare()` 在聚合后无法看到这一点，因此检查位于此处而非 I/O 胶水中；`run_regression.py` 首先调用它。
- `check_splits_disjoint(splits: dict[str, set[str]]) -> None` — 纯函数、可单元测试的守卫：如果数据集的用例 id 拆分（`judge_train`/`judge_dev`/`judge_test`/`regression`）中任意两个重叠则抛出 `ValueError`。60/20/20 分区 + 回归集必须不相交，否则 few-shot/dev 用例泄漏到保留门控中并使其膨胀；`validate()` 仅看到保留列表，无法检测到它。拆分加载器（`run_judge.py`、`validate_judge.py`、`run_regression.py`）在读取拆分后立即调用它。

- [x] **步骤 1: 失败测试** `tests/test_regression.py`

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

- [x] **步骤 2:** 运行 → 失败。**步骤 3: 实现** `flywheel/flywheel/regression.py`

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
    post-aggregation, so it lives here as a unit-tested function, not in I/O glue
    that happens to run before the function that needs the invariant."""
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

- [x] **步骤 4:** 运行 → 通过。
- [x] **步骤 5:** 种子文件 `flywheel/labels.md`，含扁平列表（每行一个标签 + 一行定义）。
- [x] **步骤 6:** 完整套件 + lint + 类型检查: `pytest -q && ruff check flywheel tests && mypy flywheel`。
- [x] **步骤 7:** 提交 `feat(flywheel): three-value regression comparison + seed labels`。

---

## 自审
- **Engine spec 覆盖:** identity.py = §4（四个 id + 最小指纹）；
  metrics.py = §6/§7 依赖的数学；regression.py = §7（三种结果，
  精确符号检验决策 + 描述性 delta 带，同一 judge + 完整性 + 不相交断言；
  `CaseScore.label` 是类型化的 `Label`，在摄入时验证）。
- **有意删除:** 无 `flywheel.*` 常量，无 context 验证器，无
  score HTTP client — 见上方"与旧计划相比的变更"；engine spec §0/§8 记录了原因。
- **交给计划 02 的类型:** `ConfidenceInterval`、`RegressionReport`、
  `CaseScore`、`Label`、`Harness` 被 `judge.py`/`validate.py`/
  `report.py` 导入，并由 read API 序列化。
