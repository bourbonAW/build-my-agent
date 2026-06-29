# Flywheel 02 — Judge、报告、只读 API 与前端（精简版）实施计划
**日期**: 2026-06-23（精简修订 2026-06-24）
**状态**: 精简 MVP — 取代先前的"控制平面（API + 状态存储）"计划

> **致 Agent 工作者：** 必需子技能：superpowers:test-driven-development
> 用于 Python 端；前端使用 Vitest + Testing Library。步骤使用
> 复选框（`- [ ]`）语法。

**目标：** 在计划 01 之上构建精简飞轮的其余部分：一个 LLM judge
运行器、一个 60/20/20 judge 验证报告、一个回归报告生成器、一个精简的
**只读** FastAPI 服务这些报告，以及**真实的 React 前端
项目**（所有者要求），包含约 3 个路由。

**架构：** 脚本将报告 JSON 写入 `~/.flywheel/<project>/reports/`。
只读 API 在这些文件上暴露三个 GET 端点，外加 Langfuse 运行/评分
摘要。浏览器仅与只读 API 通信，获取 Langfuse **深链接
URL**，永远不会获取 Langfuse 写入凭证。

## 相较旧计划的变化
旧的 plan-02 构建了一个控制平面：权威生命周期枚举
（`ProposalState` ×18、`RegressionStatus`、`RegressionOutcome`、`RunState`、
`JudgeState`），`JsonRecordStore` + SQLite 索引，仅追加 `AuditLog`，
`IdempotencyStore`，一个 4 角色 `auth` 层，带有
publish/supersede/revert 的 `BaselineService`，一个 `ScoreBridge`，约 45 个端点（大部分
为 plans 03–07 预留桩），以及 17 个状态存储记录 schema。**全部删除。** 原因（Engine
spec §0）：
- 无 proposal/regression/run/judge 状态机 — proposal 就是一个 git PR；
  回归结果就是 `better|no_change|worse`；baseline 就是 `main`。
- 无状态存储 — datasets/scores/annotations/issues 存放在 Langfuse 或
  平面文件中；那 17 个记录 schema 建模的是已删除的概念。
- 无 auth/audit/idempotency 控制平面 — 单一维护者，只读 API。
- 无 Score Bridge — judge 评分由 `judge.py` 直接写入 Langfuse。

保留下来的是真正有用的部分：judge 运行、judge 验证、
回归报告以及用于阅读它们的前端。

## 文件结构
- 创建：`flywheel/flywheel/judge.py` — 在数据集运行上执行 LLM judge
- 创建：`flywheel/flywheel/validate.py` — 60/20/20 验证报告（macro-F1 ≥ 0.70 + 每类支撑度）
- 创建：`flywheel/flywheel/report.py` — 写入 `RegressionReport`/`JudgeReport` JSON
- 创建：`flywheel/api/__init__.py`、`flywheel/api/read_api.py` — 精简只读 FastAPI
- 创建：`flywheel/api/runs_provider.py` — 生产环境 `/api/runs` 数据源（Task 6 Step 8）
- 创建：`flywheel/tests/test_judge.py`、`test_validate.py`、`test_report.py`、`tests/api/test_read_api.py`、`tests/api/test_runs_provider.py`
- 创建：`flywheel/ui/` — React + Vite + TS 前端项目（脚手架 + 3 个路由）

---

## Task 1: judge.py — 在数据集运行上执行 LLM judge

**文件：** `flywheel/flywheel/judge.py`、`flywheel/tests/test_judge.py`

**接口：**
- `@dataclass(frozen=True) class JudgeExample(input: str, expected: str, output: str, label: HumanLabel, critique: str)` — few-shot 信号（llm-eval：示例 > 提示词）；`expected` 是用例的验收说明（Engine §5 数据集项）。`label` 是 `HumanLabel`（二元 `pass`/`fail`）— 示例来自人类黄金标注，永远不会是 `skip`/`uncertain` 判定；`__post_init__` 拒绝非二元的 few-shot 标签。
- `@dataclass(frozen=True) class JudgeConfig(judge_version: str, model: str, prompt_version: str, examples: tuple[JudgeExample, ...])`.
- `class Judge` 使用 `JudgeConfig` 和一个可注入的 `complete: Callable[[str], str]`（LLM 调用；注入使得测试无需访问网络）构造。
  - `score_case(case_input: str, case_output: str, acceptance: str) -> tuple[Label, str]` — 返回 `(label, critique)`，critique **不可为空**；`acceptance` 是数据集项的 `expected`/验收说明（Engine §5），这样 judge 就能根据真实标准评分，而非空的"验收标准"引用。真正的 `uncertain` 是 judge 弃权；**缺失/格式错误的判定 — 或缺失 `REASON:` 评语 — 引发 `ValueError`**（判定必须自我解释，UI §2"永远不匿名"；协议失败不是弃权，因此调用者重试或记录操作性跳过，永远不将其写为 judge 不确定性）。
- Few-shot 示例渲染到提示词中；系统指令保持中立。

- [x] **Step 1: 失败测试** `tests/test_judge.py`

```python
from flywheel.judge import Judge, JudgeConfig, JudgeExample

def _judge(canned: str):
    cfg = JudgeConfig(
        judge_version="judge-v1", model="claude-opus-4-8", prompt_version="p1",
        examples=(JudgeExample("in", "must meet criteria", "good out", "pass", "meets criteria"),),
    )
    return Judge(cfg, complete=lambda prompt: canned)

def test_judge_parses_pass():
    label, critique = _judge("VERDICT: pass\nREASON: tool args correct").score_case("q", "a", "args must be correct")
    assert label == "pass"
    assert "tool args correct" in critique

def test_judge_parses_fail():
    label, _ = _judge("VERDICT: fail\nREASON: wrong arg shape").score_case("q", "a", "args must be correct")
    assert label == "fail"

def test_judge_parses_uncertain():
    label, _ = _judge("VERDICT: uncertain\nREASON: criteria don't decide").score_case("q", "a", "ambiguous")
    assert label == "uncertain"

def test_judge_config_rejects_bad_judge_version():
    import pytest
    with pytest.raises(ValueError, match="invalid judge_version"):
        JudgeConfig("judge:v1", "claude-opus-4-8", "p1", ())   # ":" violates the slug

def test_unparseable_verdict_raises():
    # a protocol failure (no parseable VERDICT) is NOT a judge abstention — it must
    # raise so the glue can retry / record an operational skip, not be scored as uncertain
    import pytest
    with pytest.raises(ValueError, match="no parseable VERDICT"):
        _judge("the model rambled with no verdict line").score_case("q", "a", "criteria")

def test_missing_reason_critique_raises():
    # a verdict must explain itself (the critique is the Langfuse score comment, UI §2)
    import pytest
    with pytest.raises(ValueError, match="no REASON critique"):
        _judge("VERDICT: pass").score_case("q", "a", "criteria")

def test_fewshot_label_must_be_binary():
    import pytest
    with pytest.raises(ValueError, match="invalid few-shot label"):
        JudgeExample("i", "e", "o", "uncertain", "c")  # few-shot is human gold (pass/fail only)

def test_judge_prompt_includes_fewshot_and_acceptance():
    seen = {}
    cfg = JudgeConfig("judge-v1", "claude-opus-4-8", "p1",
                      (JudgeExample("ex-in", "ex-expected", "ex-out", "fail", "missing offset"),))
    # __setitem__ returns None, so `complete` returns the canned verdict (not the prompt)
    j = Judge(cfg, complete=lambda p: seen.__setitem__("p", p) or "VERDICT: pass\nREASON: ok")
    label, critique = j.score_case("q", "a", "must page through all results")
    assert label == "pass" and critique == "ok"          # the canned verdict was parsed, not the prompt
    assert "missing offset" in seen["p"]                 # few-shot critique carried into the prompt
    assert "must page through all results" in seen["p"]  # the case's acceptance criteria are provided
```

- [x] **Step 2:** 运行 → 失败。**Step 3: 实现** `flywheel/flywheel/judge.py`

```python
"""LLM judge runner (Engine §6; llm-eval stage 4). Few-shot examples carry the
signal; the system instruction stays neutral. The LLM call is injected so the
logic is testable without a network."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, get_args

from .identity import HumanLabel, Label, validate_judge_version

_NEUTRAL_SYSTEM = (
    "You are grading whether an agent's output satisfies the case's acceptance "
    "criteria. Reply with two lines:\nVERDICT: pass|fail|uncertain\nREASON: <one line>"
    "\nUse 'uncertain' only when the acceptance criteria genuinely do not let you "
    "decide; prefer pass or fail."
)


@dataclass(frozen=True)
class JudgeExample:
    input: str
    expected: str   # the case's acceptance note (Engine §5 dataset item)
    output: str
    label: HumanLabel   # few-shot signal comes from binary human gold; never skip/uncertain
    critique: str

    def __post_init__(self) -> None:
        if self.label not in get_args(HumanLabel):
            raise ValueError(f"invalid few-shot label {self.label!r}; examples carry "
                             f"binary human gold, expected {get_args(HumanLabel)}")


@dataclass(frozen=True)
class JudgeConfig:
    judge_version: str
    model: str
    prompt_version: str
    examples: tuple[JudgeExample, ...]

    def __post_init__(self) -> None:
        validate_judge_version(self.judge_version)  # slug contract (Engine §4)


class Judge:
    def __init__(self, config: JudgeConfig, complete: Callable[[str], str]):
        self._config = config
        self._complete = complete

    def _prompt(self, case_input: str, case_output: str, acceptance: str) -> str:
        shots = "\n\n".join(
            f"INPUT: {e.input}\nACCEPTANCE: {e.expected}\nOUTPUT: {e.output}\n"
            f"VERDICT: {e.label}\nREASON: {e.critique}"
            for e in self._config.examples
        )
        return (
            f"{_NEUTRAL_SYSTEM}\n\n# Examples\n{shots}\n\n"
            f"# Case\nINPUT: {case_input}\nACCEPTANCE: {acceptance}\nOUTPUT: {case_output}\n"
        )

    def score_case(self, case_input: str, case_output: str, acceptance: str) -> tuple[Label, str]:
        raw = self._complete(self._prompt(case_input, case_output, acceptance))
        verdict: str | None = None
        critique = ""
        for line in raw.splitlines():
            low = line.strip().lower()
            if low.startswith("verdict:"):
                verdict = low.split(":", 1)[1].strip()
            elif low.startswith("reason:"):
                critique = line.split(":", 1)[1].strip()
        # A genuine "uncertain" is a judge abstention (scored as a miss). A *missing
        # or malformed* verdict is a protocol failure, not an abstention — raise so
        # the glue retries or records an operational skip, never write it as judge
        # uncertainty (which would silently inflate the abstention rate).
        if verdict not in ("pass", "fail", "uncertain"):
            raise ValueError(
                f"judge response has no parseable VERDICT (pass/fail/uncertain): {raw!r}"
            )
        if not critique:
            # A verdict must explain itself — the critique is the score comment in
            # Langfuse (UI §2 "a machine verdict is never anonymous"). A missing
            # REASON is a protocol failure, handled like a missing verdict.
            raise ValueError(f"judge verdict has no REASON critique: {raw!r}")
        if verdict == "pass":
            return "pass", critique
        if verdict == "fail":
            return "fail", critique
        return "uncertain", critique
```

- [x] **Step 4:** 运行 → 通过。**Step 5:** 提交 `feat(flywheel): few-shot LLM judge runner`。

> 将 `complete` 连接到 Anthropic 并将评分写回 Langfuse 是
> `flywheel/scripts/run_judge.py` 下的一个薄胶水脚本（此处不做 TDD — 它是 I/O）。
> 它复用 Bourbon 已经发出的 `gen_ai.*` 追踪以及数据集运行名称
> 作为 `eval.run_id`。

---

## Task 2: validate.py — 60/20/20 judge 验证报告

**文件：** `flywheel/flywheel/validate.py`、`flywheel/tests/test_validate.py`

**接口：**
- `@dataclass(frozen=True) class LabeledCase(case_id: str, human: HumanLabel, judge: Label)` — `human` 是黄金标注且为二元（`pass`/`fail`）；`judge` 可以是 `uncertain`（弃权）。
- `@dataclass(frozen=True) class JudgeReport(judge_version, model, prompt_version, f1, threshold, per_label, confusion, gold_fail_abstained, gold_pass_abstained, validation_set_size, min_class_support)` — `f1` 是 **macro-F1**（pass 类和 fail 类 F1 的平均值）。`confusion` 是 2x2 fail-positive 矩阵；`gold_fail_abstained`/`gold_pass_abstained` 将 judge 的弃权从 `fn`/`tn` 中分离出来，这样 UI 矩阵就不会把 gold 用例上的 `uncertain` 读作正确的单元格。`report.py` 序列化 UI §7 `JudgeReport` 形状，包括门控决策（`passes`）和 gold 支撑计数，使消费者永远不需要重新推导私有门控逻辑；`min_class_support` 是门控的每类下限。
- `validate(cases, *, judge_version, model, prompt_version, threshold=0.70, min_class_support=5) -> JudgeReport` — `cases` 是**留出的验证分割**（60/20/20 分区的 `test` 20%；Engine §6）。调用者负责分割 — judge 的 few-shot 示例来自 `train`，不得出现在此处（泄漏），`dev` 用于迭代提示词。混淆矩阵是 fail-positive（`fail` 是我们检测的类）；`uncertain`/`skip` 判定是非 `fail`（且非 `pass`），所以规避型 judge 在任一类中都不能获得 true positive。核心指标是 **macro-F1** — pass 类和 fail 类 F1 的平均值 — 这样退化的 always-`fail` judge（高 fail 召回率、基准率精度）就不能在 failure 偏置的分割上通过。计算 tp/fp/fn/tn、每类 precision/recall、macro-F1。
- `JudgeReport.passes() -> bool` = `f1 (macro) >= threshold` **且** `fail 类 F1 >= threshold` **且** 分割持有至少 `min_class_support` 个**每类**黄金用例 — gold `fail`（`tp + fn`）**且** gold `pass`（`fp + tn`）。fail 类下限独立于 macro-F1：一个 judge 可以凭借完美的 pass 类通过均值，同时对真实失败采取规避策略（例如捕获 2/5 个 fail，弃权 3 个 → macro ≈ 0.79 但 fail-F1 ≈ 0.57），而捕获失败是 judge 的核心职责，所以它仍然必须失败。少量用例上的 macro-F1 每单个用例波动 >0.2，单类分割会让退化 judge 通过，所以规模不足/不平衡的分割是*尚未验证的*，不能门控（Engine §6），而不是在噪声上通过。

- [ ] **Step 1: 失败测试** `tests/test_validate.py`

```python
from flywheel.validate import validate, LabeledCase

def test_perfect_agreement_is_f1_1():
    cases = [LabeledCase(f"c{i}", "fail", "fail") for i in range(5)] + \
            [LabeledCase(f"d{i}", "pass", "pass") for i in range(5)]  # 5 gold fails = support floor
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 == 1.0
    assert rep.passes()

def test_insufficient_positive_support_does_not_gate():
    # perfect agreement but only 1 gold failure: F1 over a single positive is noise,
    # so the gate must refuse it (not yet validated), not pass (Engine §6 support floor).
    cases = [LabeledCase("a", "fail", "fail")] + \
            [LabeledCase(f"d{i}", "pass", "pass") for i in range(9)]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 == 1.0
    assert not rep.passes()

def test_below_threshold_does_not_pass():
    cases = [LabeledCase(f"c{i}", "fail", "pass") for i in range(8)] + \
            [LabeledCase(f"d{i}", "pass", "pass") for i in range(2)]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 < 0.70
    assert not rep.passes()

def test_confusion_counts():
    cases = [LabeledCase("a", "fail", "fail"),   # tp
             LabeledCase("b", "pass", "fail"),   # fp
             LabeledCase("c", "fail", "pass"),   # fn
             LabeledCase("d", "pass", "pass")]   # tn
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert (rep.confusion["tp"], rep.confusion["fp"], rep.confusion["fn"], rep.confusion["tn"]) == (1, 1, 1, 1)
    assert rep.validation_set_size == 4

def test_uncertain_judge_is_a_miss_not_a_true_positive():
    # judge "uncertain" on a real failure is an abstention: it must NOT be credited
    # as catching the failure (no tp); it counts as a miss (fn).
    cases = [LabeledCase("a", "fail", "uncertain"), LabeledCase("b", "pass", "pass")]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.confusion["tp"] == 0
    assert rep.confusion["fn"] == 1
    assert rep.gold_fail_abstained == 1   # the abstention is broken out of fn, not hidden
    assert rep.gold_pass_abstained == 0
    assert rep.validation_set_size == 2

def test_all_uncertain_judge_fails_gate():
    # a judge that always abstains must not pass F1, even on a failure-heavy set
    cases = [LabeledCase(f"c{i}", "fail", "uncertain") for i in range(8)] + \
            [LabeledCase(f"d{i}", "pass", "uncertain") for i in range(2)]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 == 0.0
    assert not rep.passes()

def test_always_fail_judge_fails_gate():
    # flagging everything "fail" gives a high fail-only F1 on a failure-biased split,
    # but macro-F1 (averaging in the pass class it gets wrong) fails the gate. Use a
    # 20-fail / 5-pass split so fail-only F1 really is high AND both support floors
    # (≥5 each) are met — the failure is the metric, not the support floor.
    cases = [LabeledCase(f"c{i}", "fail", "fail") for i in range(20)] + \
            [LabeledCase(f"d{i}", "pass", "fail") for i in range(5)]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 < 0.70          # macro-F1 ≈ 0.44, despite the inflated fail-only ≈ 0.89
    assert not rep.passes()

def test_partial_hedge_on_failures_fails_gate():
    # catches 2/5 failures, abstains on 3, perfect on passes: macro-F1 ≈ 0.79 clears
    # the mean, but fail-class F1 ≈ 0.57 < 0.70 — it misses 60% of real failures.
    cases = ([LabeledCase(f"f{i}", "fail", "fail") for i in range(2)]
             + [LabeledCase(f"g{i}", "fail", "uncertain") for i in range(3)]
             + [LabeledCase(f"p{i}", "pass", "pass") for i in range(5)])
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 >= 0.70        # macro-F1 ≈ 0.79 clears the mean
    assert not rep.passes()      # but fail-class F1 ≈ 0.57 < 0.70 → not validated

def test_duplicate_case_id_rejected():
    import pytest
    # 2 distinct cases copied 5× must not satisfy the "5 gold per class" floor
    cases = [LabeledCase("a", "fail", "fail")] * 5 + [LabeledCase("b", "pass", "pass")] * 5
    with pytest.raises(ValueError, match="duplicate case_id"):
        validate(cases, judge_version="jv1", model="m", prompt_version="p")

def test_invalid_labels_rejected():
    import pytest
    with pytest.raises(ValueError, match="invalid judge label"):
        LabeledCase("a", "fail", "PASS")   # judge not a canonical Label
    with pytest.raises(ValueError, match="invalid human label"):
        LabeledCase("a", "skip", "pass")   # human must be binary pass/fail (no skip/uncertain)

def test_validate_rejects_bad_judge_version():
    import pytest
    with pytest.raises(ValueError, match="invalid judge_version"):
        validate([LabeledCase("a", "fail", "fail")], judge_version="judge/v1", model="m", prompt_version="p")
```

- [ ] **Step 2:** 运行 → 失败。**Step 3: 实现** `flywheel/flywheel/validate.py`

```python
"""Judge validation (Engine §6; llm-eval stage 5). The gate is macro-F1 >= threshold
(the mean of pass-class and fail-class F1), not fail-only F1: on the failure-biased
validation set, an always-"fail" judge would earn a high fail-only F1 (perfect
recall, base-rate precision) while never recognizing success — averaging both
classes forces it to get passes right too, so a degenerate always-"fail" or
always-"pass" judge fails the gate.

Confusion is fail-positive ("fail" is the class we detect). An abstention
("uncertain"/"skip") is non-"fail" and non-"pass", so a hedging judge earns no true
positive in either class: an all-"uncertain" judge scores macro-F1=0 and fails.
The gate also requires fail-class F1 >= threshold on its own (a judge can clear the
macro mean with a perfect pass class while hedging on real failures — catching 2/5,
abstaining on 3 → macro ~0.79 but fail-F1 ~0.57 — and catching failures is the
core job) and >= min_class_support gold cases of *each* class, so a tiny or
one-sided split can't pass on noise. `cases` must be the held-out validation split
(few-shot/train cases excluded by the caller — including them would leak)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import get_args

from .identity import HumanLabel, Label, validate_judge_version
from .metrics import precision_recall_f1


@dataclass(frozen=True)
class LabeledCase:
    case_id: str
    human: HumanLabel   # gold, binary pass/fail
    judge: Label        # may be "uncertain" (abstention)

    def __post_init__(self) -> None:
        # Validate at ingestion: a malformed Langfuse value must fail loudly, not be
        # silently folded into the confusion matrix / F1 (a "human" gold label is
        # binary; only the judge may abstain).
        if self.human not in get_args(HumanLabel):
            raise ValueError(f"invalid human label {self.human!r}; expected {get_args(HumanLabel)}")
        if self.judge not in get_args(Label):
            raise ValueError(f"invalid judge label {self.judge!r}; expected {get_args(Label)}")


@dataclass(frozen=True)
class JudgeReport:
    judge_version: str
    model: str
    prompt_version: str
    f1: float
    threshold: float
    per_label: list[dict[str, object]]
    confusion: dict[str, int]            # 2x2 fail-positive: tp/fp/fn/tn
    gold_fail_abstained: int             # gold-fail cases the judge abstained on (subset of fn)
    gold_pass_abstained: int             # gold-pass cases the judge abstained on (subset of tn)
    validation_set_size: int
    min_class_support: int  # per-class gold floor (server-side gate input)

    def passes(self) -> bool:
        # Gate (Engine §6): macro-F1 ≥ threshold (catches a judge blind to one
        # class) AND fail-class F1 ≥ threshold (the judge's core job is catching
        # failures, so a judge that hedges on real failures — high macro via a
        # perfect pass class but low fail recall — must still fail) AND enough gold
        # cases of BOTH classes (F1 over a handful is noise; a one-class split lets
        # a degenerate judge through).
        c = self.confusion
        _, _, fail_f1 = precision_recall_f1(c["tp"], c["fp"], c["fn"])
        gold_fail = c["tp"] + c["fn"]
        gold_pass = c["fp"] + c["tn"]
        return (self.f1 >= self.threshold
                and fail_f1 >= self.threshold
                and gold_fail >= self.min_class_support
                and gold_pass >= self.min_class_support)


def validate(cases: list[LabeledCase], *, judge_version: str, model: str,
             prompt_version: str, threshold: float = 0.70,
             min_class_support: int = 5) -> JudgeReport:
    validate_judge_version(judge_version)  # slug contract (Engine §4)
    # Reject duplicate case_ids: the per-class support floor counts distinct gold
    # cases, so repeated copies of one pass + one fail must not satisfy it. judge_test
    # is scored once per case (Task 6 Step 5), so a repeat here is an error, not data.
    ids = [c.case_id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case_id in validation split; judge_test is scored "
                         "once per case — collapse or drop repeats before validate()")
    # Confusion is fail-positive ("fail" is the class we detect). Only a literal
    # judge "fail" is a fail-prediction; "pass"/"skip"/"uncertain" are non-"fail",
    # so an abstaining judge never earns a fail true-positive.
    tp = sum(1 for c in cases if c.human == "fail" and c.judge == "fail")
    fp = sum(1 for c in cases if c.human != "fail" and c.judge == "fail")
    fn = sum(1 for c in cases if c.human == "fail" and c.judge != "fail")
    tn = sum(1 for c in cases if c.human != "fail" and c.judge != "fail")
    # Abstentions are folded into fn/tn by the binary view, which hides them in the
    # UI matrix (a gold-pass the judge abstained on counts as tn — "correct-looking"
    # — though pass-class F1 treats it as a miss). Surface them explicitly.
    _abstain = ("uncertain", "skip")
    gold_fail_abstained = sum(1 for c in cases if c.human == "fail" and c.judge in _abstain)
    gold_pass_abstained = sum(1 for c in cases if c.human != "fail" and c.judge in _abstain)

    # Macro-F1 = mean of pass-class and fail-class F1. Averaging both classes stops
    # an always-"fail" judge from passing on a failure-biased split (fail-only F1
    # is inflated by the base rate); it must get passes right too.
    per_label: list[dict[str, object]] = []
    class_f1: list[float] = []
    for label in ("pass", "fail"):
        ltp = sum(1 for c in cases if c.human == label and c.judge == label)
        lfp = sum(1 for c in cases if c.human != label and c.judge == label)
        lfn = sum(1 for c in cases if c.human == label and c.judge != label)
        p, r, lf1 = precision_recall_f1(ltp, lfp, lfn)
        # per-class f1 is surfaced so the UI can show *why* a judge fails the gate
        # (e.g. fail-class f1 < threshold while macro clears it).
        per_label.append({"label": label, "precision": p, "recall": r, "f1": lf1})
        class_f1.append(lf1)
    f1 = sum(class_f1) / len(class_f1)  # macro-F1

    return JudgeReport(
        judge_version=judge_version, model=model, prompt_version=prompt_version,
        f1=f1, threshold=threshold, per_label=per_label,
        confusion={"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        gold_fail_abstained=gold_fail_abstained, gold_pass_abstained=gold_pass_abstained,
        validation_set_size=len(cases), min_class_support=min_class_support,
    )
```

- [ ] **Step 4:** 运行 → 通过。**Step 5:** 提交 `feat(flywheel): 60/20/20 judge validation report`。

---

## Task 3: report.py — 将报告序列化为 JSON 供只读 API 使用

**文件：** `flywheel/flywheel/report.py`、`flywheel/tests/test_report.py`

**接口：**
- `write_regression_report(root, project, run_id, report: RegressionReport, *, baseline_harness, candidate_harness, trace_urls: dict[str, str] | None = None, candidate_pr_url=None) -> Path` — 写入 `root/<project>/reports/regression/<run_id>.json`，匹配 UI §7 `RegressionReport`。`judgeVersion` 从 `report.judge_version`（`compare()` 门控的版本）序列化，**不是**调用者参数，所以它不会与实际断言的版本偏移。`run_id` 成为文件名和 `/api/runs/{run_id}` 路径段，所以它必须是 URL 安全的 slug（在 Task 6 Step 4 中生成）；`_safe_segment` 防御性地拒绝路径分隔符/遍历。`fixed`/`newlyBroken`/`perLabel`/`passRateDelta` 加上候选用例级别的 `passRate`/`nonPassCount` 都是从 `report` 派生的（单一所有者）— 后两者来自 `compare()` 门控的相同聚合分数，所以 `runs_provider` 直接服务它们，列表永远不会与该报告在重复项上产生分歧；`trace_urls` 映射 `case_id → Langfuse 深链接`，这样胶水脚本提供 URL 而无需 `compare()` 知道 Langfuse — 对于重复用例，它必须是一个**代表性的**追踪，匹配聚合判定（Task 6 Step 7），而非任意重复。
- `write_judge_report(root, project, report: JudgeReport) -> Path` — 写入 `root/<project>/reports/judge/<judge_version>.json`，匹配 UI §7 `JudgeReport`，包括序列化的门控决策（`passes`）和 gold 支撑计数，使 `run_regression.py` 和 UI 无需重新推导私有门控逻辑即可尊重该决策。
- `write_regression_markdown(root, project, run_id, report: RegressionReport, *, baseline_harness, candidate_harness, trace_urls: dict[str, str] | None = None, candidate_pr_url=None) -> Path` — 渲染 `report.judge_version`（非调用者参数）。写入一个人类可读的 `root/<project>/reports/regression/<run_id>.md`（Engine §3/§7 要求"markdown + JSON"）。JSON 供 UI 使用；markdown 是人类阅读或粘贴到候选 PR 中的产物，所以它渲染 `baseline_harness → candidate_harness`（与 JSON 相同的数据 — 没有它，产物就无法说明*比较了什么*）。`trace_urls`（传递给 `write_regression_report` 的同一映射）将 fixed/newly-broken 用例 id 渲染为 Langfuse 深链接（Engine §7 / UI §6）。与 JSON 相同的数据，无新计算。
- `read_json(path) -> dict`。
- **锁定决策：** 报告 JSON 使用前端期望的 camelCase 键（UI §7），直接在此处写入，这样只读 API 可以原样服务它们。CI 边界来自 `report.delta_low/delta_high`（真实区间，永远非零宽度）。

- [ ] **Step 1: 失败测试** `tests/test_report.py`

```python
from pathlib import Path
from flywheel.regression import compare, CaseScore
from flywheel.report import write_regression_report, read_json

def test_regression_report_written_with_expected_keys(tmp_path: Path):
    base = [CaseScore("a", "fail", "tool_misuse"), CaseScore("b", "pass")]
    cand = [CaseScore("a", "pass"), CaseScore("b", "pass")]
    rep = compare(base, cand, regression_case_ids={"a", "b"}, validation_case_ids=set(),
                  baseline_judge_version="jv1", candidate_judge_version="jv1")
    path = write_regression_report(
        tmp_path, "bourbon", "run_1", rep,
        baseline_harness="abc@m", candidate_harness="def@m",
        trace_urls={"a": "http://lf/t/a"},
    )
    assert path.exists()
    data = read_json(path)
    assert data["runId"] == "run_1"
    assert data["result"] in ("better", "no_change", "worse")
    assert data["judgeVersion"] == "jv1"
    assert data["fixed"][0]["caseId"] == "a"
    assert data["fixed"][0]["traceUrl"] == "http://lf/t/a"
    # descriptive delta band: low <= point <= high (not a zero-width fake)
    d = data["passRateDelta"]
    assert d["low"] <= d["point"] <= d["high"]
    # candidate case-level summary served from the report (not raw Langfuse attempts)
    assert data["passRate"]["low"] <= data["passRate"]["point"] <= data["passRate"]["high"]
    assert data["nonPassCount"] == 0          # both candidates pass
    assert data["perLabel"][0]["label"] == "tool_misuse"

def test_regression_markdown_written(tmp_path: Path):
    from flywheel.report import write_regression_markdown
    base = [CaseScore("a", "fail", "tool_misuse"), CaseScore("b", "pass")]
    cand = [CaseScore("a", "pass"), CaseScore("b", "pass")]
    rep = compare(base, cand, regression_case_ids={"a", "b"}, validation_case_ids=set(),
                  baseline_judge_version="jv1", candidate_judge_version="jv1")
    path = write_regression_markdown(tmp_path, "bourbon", "run_1", rep,
                                     baseline_harness="abc@m", candidate_harness="def@m")
    text = path.read_text()
    assert path.suffix == ".md"
    assert "run_1" in text and rep.result in text and "tool_misuse" in text
    assert "abc@m" in text and "def@m" in text  # the artifact says what was compared

def test_judge_report_written_with_expected_keys(tmp_path: Path):
    from flywheel.report import write_judge_report
    from flywheel.validate import validate, LabeledCase
    rep = validate([LabeledCase("a", "fail", "fail"), LabeledCase("b", "pass", "pass")],
                   judge_version="jv1", model="claude-opus-4-8", prompt_version="p1")
    path = write_judge_report(tmp_path, "bourbon", rep)
    data = read_json(path)
    # exact UI §7 JudgeReport camelCase contract (incl. serialized gate decision)
    assert set(data) == {"judgeVersion", "model", "promptVersion", "f1", "threshold",
                         "passes", "goldFailCount", "goldPassCount", "minClassSupport",
                         "goldFailAbstained", "goldPassAbstained",
                         "perLabel", "confusion", "validationSetSize"}
    assert data["judgeVersion"] == "jv1"
    assert data["confusion"]["tp"] == 1
    assert data["passes"] is False  # only 1 gold fail / 1 gold pass < support floor

def test_unsafe_run_id_rejected(tmp_path: Path):
    import pytest
    base = [CaseScore("a", "pass")]
    rep = compare(base, base, regression_case_ids={"a"}, validation_case_ids=set(),
                  baseline_judge_version="jv1", candidate_judge_version="jv1")
    for bad in ("../../escape", "run\n", ".", ".."):     # fullmatch: trailing-\n / dot are unsafe
        with pytest.raises(ValueError, match="unsafe id segment"):
            write_regression_report(tmp_path, "bourbon", bad, rep,
                                    baseline_harness="a@m", candidate_harness="b@m")
    with pytest.raises(ValueError, match="unsafe id segment"):     # project is a path segment too
        write_regression_report(tmp_path, "../../escape", "run_1", rep,
                                baseline_harness="a@m", candidate_harness="b@m")
```

- [ ] **Step 2:** 运行 → 失败。**Step 3: 实现** `flywheel/flywheel/report.py`

```python
"""Serialize reports to JSON consumed by the read API / frontend (UI §7).
Keys are camelCase to match the frontend types exactly — no boundary mapping."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .regression import RegressionReport
from .validate import JudgeReport

_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9._@-]+")  # used with fullmatch — no ^…$ trailing-\n hole


def _reports_dir(root: Path, project: str, kind: str) -> Path:
    # `project` is also a path segment under root, so it gets the same slug guard as
    # run_id/judge_version — a configured project like "../../x" must not escape root.
    d = Path(root) / _safe_segment(project) / "reports" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_segment(value: str) -> str:
    """Allow only URL-safe slug ids `[A-Za-z0-9._@-]` (and never bare '.'/'..'), so a
    run_id/judge_version with a space, '?', '#', '/', '\\', NUL, or unicode can't
    escape the reports dir or break the `/api/...` path — reject rather than sanitize,
    so a non-slug id fails loudly at write time instead of silently relocating."""
    if not _SAFE_SEGMENT.fullmatch(value) or value in (".", ".."):
        raise ValueError(f"unsafe id segment: {value!r}")
    return value


def write_regression_report(
    root: Path, project: str, run_id: str, report: RegressionReport, *,
    baseline_harness: str, candidate_harness: str,
    trace_urls: dict[str, str] | None = None,
    candidate_pr_url: str | None = None,
) -> Path:
    urls = trace_urls or {}

    def _enrich(case_ids: list[str]) -> list[dict[str, str]]:
        return [{"caseId": cid, "traceUrl": urls.get(cid, "")} for cid in case_ids]

    payload = {
        "runId": run_id,
        "baselineHarness": baseline_harness,
        "candidateHarness": candidate_harness,
        "judgeVersion": report.judge_version,   # the version compare() actually gated, not a caller string
        # candidate case-level pass rate + non-pass count, from the SAME aggregated
        # scores compare() gates on, so runs_provider can serve RunSummary.passRate /
        # nonPassCount from here and never disagree with this report on repeats.
        "passRate": {"point": report.candidate_rate,
                     "low": report.candidate_rate_low,
                     "high": report.candidate_rate_high},
        "nonPassCount": report.candidate_non_pass_count,
        # descriptive delta band from the regression report — never a zero-width fake,
        # and not a CI (the better/worse gate is the exact sign test, see compare())
        "passRateDelta": {"point": report.delta,
                          "low": report.delta_low,
                          "high": report.delta_high},
        "result": report.result,
        "perLabel": report.per_label,           # single owner: derived in compare()
        "fixed": _enrich(report.fixed),
        "newlyBroken": _enrich(report.newly_broken),
    }
    if candidate_pr_url is not None:
        payload["candidatePrUrl"] = candidate_pr_url  # optional key (UI §7 `candidatePrUrl?: string`), omitted when absent
    path = _reports_dir(root, project, "regression") / f"{_safe_segment(run_id)}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def write_regression_markdown(
    root: Path, project: str, run_id: str, report: RegressionReport, *,
    baseline_harness: str, candidate_harness: str,
    trace_urls: dict[str, str] | None = None,
    candidate_pr_url: str | None = None,
) -> Path:
    urls = trace_urls or {}

    def _links(case_ids: list[str]) -> str:
        if not case_ids:
            return "—"
        return ", ".join(f"[{cid}]({urls[cid]})" if urls.get(cid) else cid for cid in case_ids)

    lines = [
        f"# Regression report — {run_id}",
        "",
        f"- **Result:** {report.result}",
        f"- **Comparing:** {baseline_harness} → {candidate_harness}",
        f"- **Judge:** {report.judge_version}",
        f"- **Pass rate:** {report.baseline_rate:.3f} → {report.candidate_rate:.3f} "
        f"(Δ {report.delta:+.3f}, descriptive band [{report.delta_low:+.3f}, {report.delta_high:+.3f}]; gate = exact sign test)",
    ]
    if candidate_pr_url:
        lines.append(f"- **Candidate PR:** {candidate_pr_url}")
    lines += ["", "## Per-label failures", "", "| label | baseline | candidate |", "|---|---|---|"]
    lines += [f"| {r['label']} | {r['baseline']} | {r['candidate']} |" for r in report.per_label]
    lines += ["",
              f"**Fixed ({len(report.fixed)}):** {_links(report.fixed)}",
              f"**Newly broken ({len(report.newly_broken)}):** {_links(report.newly_broken)}"]
    path = _reports_dir(root, project, "regression") / f"{_safe_segment(run_id)}.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def write_judge_report(root: Path, project: str, report: JudgeReport) -> Path:
    confusion = report.confusion
    payload = {
        "judgeVersion": report.judge_version,
        "model": report.model,
        "promptVersion": report.prompt_version,
        "f1": report.f1,                       # macro-F1
        "threshold": report.threshold,
        # the gate decision + support, serialized so run_regression.py and the UI
        # honor it without re-deriving private gate logic (UI §6/§9)
        "passes": report.passes(),
        "goldFailCount": confusion["tp"] + confusion["fn"],
        "goldPassCount": confusion["fp"] + confusion["tn"],
        "minClassSupport": report.min_class_support,
        "perLabel": report.per_label,
        "confusion": report.confusion,
        # abstentions broken out of the binary fn/tn so the UI matrix doesn't show
        # a judge's "uncertain" on a gold case as a correct prediction
        "goldFailAbstained": report.gold_fail_abstained,
        "goldPassAbstained": report.gold_pass_abstained,
        "validationSetSize": report.validation_set_size,
    }
    path = _reports_dir(root, project, "judge") / f"{_safe_segment(report.judge_version)}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def read_json(path: Path) -> dict[str, object]:
    result: dict[str, object] = json.loads(Path(path).read_text())
    return result
```

- [ ] **Step 4:** 运行 → 通过。**Step 5:** 提交 `feat(flywheel): regression/judge report serialization`。

---

## Task 4: read_api.py — 精简只读 FastAPI（3 个端点）

**文件：** `flywheel/api/__init__.py`、`flywheel/api/read_api.py`、`flywheel/tests/api/test_read_api.py`

**接口：**
- `create_app(root, *, project: str, runs_provider: Callable[[str], list[dict[str, object]]]) -> FastAPI`。应用绑定到单个已配置的 `project`（这是个人单项目工具），所以端点不带 `?project=` 查询 — 完全匹配 UI §8。`runs_provider(project)` 返回 `RunSummary[]`（注入；生产实现是 `flywheel/api/runs_provider.py:list_runs` — Task 6 Step 8 — 它只返回**有报告支持的回归运行**，这样每个列出的运行都能解析到一个 `/runs/{run_id}` 报告且永远不会 404；在此端点测试中使用桩，在 `tests/api/test_runs_provider.py` 中单独测试）。
- **端点直接返回 UI §8 形状 — 无封装包装器，无查询参数：**
- `GET /api/runs` → `RunSummary[]`（裸 JSON 数组）。
- `GET /api/runs/{run_id}` → 从报告文件获取的 `RegressionReport`；不存在则 404。
- `GET /api/judges/{judge_version}` → 从报告文件获取的 `JudgeReport`；不存在则 404。
- 只读：无 POST，无 auth，无幂等性。浏览器永远不会接收 Langfuse 写入凭证（UI §4）。
- **打包：** 此任务创建了兄弟 `api/` 包，所以在重新安装之前，将 `api` 添加到 `flywheel/pyproject.toml` 中的 `[tool.hatch.build.targets.wheel] packages`（plan 01 只有 `packages = ["flywheel"]`）。

- [ ] **Step 1: 失败测试** `tests/api/test_read_api.py`

```python
from pathlib import Path
from fastapi.testclient import TestClient
from flywheel.regression import compare, CaseScore
from flywheel.report import write_regression_report, write_judge_report
from flywheel.validate import validate, LabeledCase
from api.read_api import create_app

def _client(tmp_path: Path):
    runs = [{"runId": "run_1", "harness": "abc@m", "judgeVersion": "jv1",
             "judgeF1": None, "judgeValidated": None,
             "passRate": {"point": 0.5, "low": 0.3, "high": 0.7}, "nonPassCount": 1,
             "createdAt": "2026-06-24", "langfuseRunUrl": "http://lf/r/run_1"}]
    app = create_app(tmp_path, project="bourbon", runs_provider=lambda project: runs)
    return TestClient(app)

def test_list_runs_returns_bare_array(tmp_path):
    r = _client(tmp_path).get("/api/runs")            # no ?project= (UI §8)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)                     # UI §8: bare RunSummary[], no envelope
    assert body[0]["runId"] == "run_1"
    assert set(body[0]) >= {"runId", "harness", "judgeVersion", "judgeF1", "judgeValidated",
                            "passRate", "nonPassCount", "createdAt", "langfuseRunUrl"}

def test_get_regression_report(tmp_path):
    # baseline failure carries a failure_label so compare() emits a perLabel row
    # (per-label counts only non-pass scores that have a failure_label)
    rep = compare([CaseScore("a", "fail", "tool_misuse")], [CaseScore("a", "pass")],
                  regression_case_ids={"a"}, validation_case_ids=set(),
                  baseline_judge_version="jv1", candidate_judge_version="jv1")
    write_regression_report(tmp_path, "bourbon", "run_1", rep,
                            baseline_harness="abc@m", candidate_harness="def@m")
    body = _client(tmp_path).get("/api/runs/run_1").json()  # bare RegressionReport (UI §7)
    assert set(body) >= {"runId", "baselineHarness", "candidateHarness", "judgeVersion",
                         "passRate", "nonPassCount", "passRateDelta", "result",
                         "perLabel", "fixed", "newlyBroken"}
    assert set(body["passRateDelta"]) == {"point", "low", "high"}
    assert set(body["passRate"]) == {"point", "low", "high"}
    assert body["result"] in ("better", "no_change", "worse")
    assert set(body["fixed"][0]) == {"caseId", "traceUrl"}
    assert set(body["perLabel"][0]) == {"label", "baseline", "candidate"}

def test_get_judge_report(tmp_path):
    rep = validate([LabeledCase("a", "fail", "fail"), LabeledCase("b", "pass", "pass")],
                   judge_version="jv1", model="m", prompt_version="p")
    write_judge_report(tmp_path, "bourbon", rep)
    body = _client(tmp_path).get("/api/judges/jv1").json()   # bare JudgeReport (UI §7)
    assert set(body) == {"judgeVersion", "model", "promptVersion", "f1", "threshold",
                         "passes", "goldFailCount", "goldPassCount", "minClassSupport",
                         "goldFailAbstained", "goldPassAbstained",
                         "perLabel", "confusion", "validationSetSize"}
    assert body["judgeVersion"] == "jv1"
    assert isinstance(body["passes"], bool)
    assert set(body["confusion"]) == {"tp", "fp", "fn", "tn"}
    assert set(body["perLabel"][0]) == {"label", "precision", "recall", "f1"}  # per-class f1 surfaced (fail-class gate)

def test_missing_report_404(tmp_path):
    assert _client(tmp_path).get("/api/runs/nope").status_code == 404
    assert _client(tmp_path).get("/api/judges/nope").status_code == 404

def test_path_traversal_is_rejected(tmp_path):
    # a resolved id that escapes the reports dir must 404, never read outside it
    assert _client(tmp_path).get("/api/runs/..%2f..%2fsecret").status_code == 404

def test_unsafe_project_rejected(tmp_path):
    # a configured project must be a slug too — "../../x" can't escape root
    import pytest
    with pytest.raises(ValueError, match="unsafe id segment"):
        create_app(tmp_path, project="../../escape", runs_provider=lambda p: [])

def test_contained_path_guards_traversal_directly(tmp_path):
    # exercise the resolver guard directly — the route test above may be short-
    # circuited by FastAPI's own path handling before _report_path runs
    from api.read_api import _contained_path
    base = tmp_path / "reports" / "regression"
    base.mkdir(parents=True)
    assert _contained_path(base, "../../escape") is None        # parent escapes base
    assert _contained_path(base, "a/b") is None                 # nested, not directly under base
    assert _contained_path(base, "run_1") == (base / "run_1.json").resolve()  # ok
```

- [ ] **Step 2:** 运行 → 失败。**Step 3: 实现** `flywheel/api/read_api.py`

```python
"""Thin read-only API serving report JSON + Langfuse run summaries (UI §4, §8)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException

from flywheel.report import _safe_segment, read_json


def _contained_path(base: Path, name: str) -> Path | None:
    """Resolve base/<name>.json and return it only if `name` is a valid URL-safe slug
    (same `_safe_segment` allowlist as the write side, so a non-slug id is rejected,
    not served) **and** the file stays **directly under** base. Module-level + pure so
    the guard is unit-testable independent of the HTTP route (FastAPI may reject some
    encodings before the handler runs, so a route-level test can pass without
    exercising this)."""
    try:
        _safe_segment(name)               # enforce the slug contract on reads too
    except ValueError:
        return None
    base = base.resolve()
    p = (base / f"{name}.json").resolve()
    return p if p.parent == base else None


def create_app(root: Path, *, project: str,
               runs_provider: Callable[[str], list[dict[str, object]]]) -> FastAPI:
    app = FastAPI(title="Flywheel Read API")
    root = Path(root)
    project = _safe_segment(project)  # `project` is a path segment under root too —
    # a configured "../../x" must not escape root on reads (mirrors report._reports_dir)

    # Bound to one configured project; endpoints carry no ?project= (UI §8) and
    # return the UI §8 shapes directly (no envelope wrapper).
    @app.get("/api/runs")
    def list_runs() -> list[dict[str, object]]:
        return runs_provider(project)

    def _report_path(kind: str, name: str) -> Path | None:
        # Containment (a run_id/judge_version with separators or `..` can't read
        # outside the reports dir) is delegated to the unit-tested _contained_path.
        p = _contained_path(root / project / "reports" / kind, name)
        return p if p is not None and p.exists() else None

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, object]:
        path = _report_path("regression", run_id)
        if path is None:
            raise HTTPException(status_code=404, detail="regression report not found")
        return read_json(path)

    @app.get("/api/judges/{judge_version}")
    def get_judge(judge_version: str) -> dict[str, object]:
        path = _report_path("judge", judge_version)
        if path is None:
            raise HTTPException(status_code=404, detail="judge report not found")
        return read_json(path)

    return app
```

- [ ] **Step 4: 打包 `api`** — 编辑 `flywheel/pyproject.toml` 使兄弟
  包在 wheel 中分发：`[tool.hatch.build.targets.wheel] packages = ["flywheel", "api"]`
  （plan 01 只有 `["flywheel"]`），然后重新运行 `uv pip install -e ".[dev]"`。
  验证 `python -c "import api.read_api"` 能从源代码根目录**外部**工作
  （这样是构建暴露了 `api`，而不仅仅是 `pythonpath = ["."]`）。
- [ ] **Step 5:** 运行 → 通过。**Step 6:** `pytest tests/api -q && ruff check api flywheel tests && mypy flywheel api`。**Step 7:** 提交 `feat(api): thin read-only API for runs and judge reports`。

---

## Task 5: ui/ — React + Vite + TS 前端项目

**文件：** `flywheel/ui/`（脚手架）。所有者要求一个真正的前端项目，所以
这是一个完整的 Vite 应用 — **表面**精简（3 个路由），技术栈不精简。

**技术栈（UI §3）：** React + TS + Vite、React Router、TanStack Query、TanStack
Table、shadcn/ui（或本地组件）、Recharts、Vitest + Testing Library，加一个
Playwright 快乐路径测试。

- [ ] **Step 1: 脚手架**

```bash
cd flywheel && npm create vite@latest ui -- --template react-ts
cd ui && npm install @tanstack/react-query @tanstack/react-table react-router-dom recharts
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom @playwright/test
```

- [ ] **Step 2: API 客户端 + 类型** — `ui/src/api.ts`，包含 UI §7 类型
  （`RunSummary`、`RegressionReport`、`LabelDelta`、`JudgeReport`、
  `RegressionResult`）和三个命中只读 API 的 fetcher。报告 JSON 已经是
  camelCase（Task 3），所以类型 1:1 映射 — 无边界转换。

- [ ] **Step 3: 路由（UI §5）**
  - `/` — 首页：链接到 runs + 一个用于 traces/datasets/annotation 的 Langfuse 深链接。
  - `/runs` — `RunSummary[]` 表格：run id、harness、judge version、judge 状态 — **当 `judgeF1` 非 null 时渲染它（macro-F1），包括 `judgeValidated === false` 时**（不要隐藏数字）；`judgeValidated` 只驱动徽章（`validated` vs `judge: not validated`，后者链接到 `/judges/:judgeVersion`）；**仅当** `judgeF1`/`judgeValidated` 为 null（无报告）时显示 `not available` — UI §6/§9。然后是通过率 + CI 条形图、#not-passed、Langfuse 链接。
  - `/runs/:runId` — `RegressionReport`：baseline vs candidate harness、judge version（带"同一 judge"注释）、pass-rate delta + 描述性带（非 CI；徽章来自精确符号检验）、结果徽章（`better` 绿色 / `no_change` 琥珀色 / `worse` 红色）、per-label delta 表格、fixed/newly-broken 列表（带 Langfuse 追踪深链接），以及**不相交性说明** "regression set ∩ judge case pool = ∅" 作为静态不变量渲染（UI §6 — 报告的存在证明了它，无需数据字段）。
  - `/judges/:judgeVersion` — `JudgeReport`：macro-F1 vs 阈值 + validated/`passes` 徽章、gold pass/fail 计数 vs 支撑下限、per-label precision/recall/**F1**（fail 类 F1 针对其自身 0.70 门控标注，这样当 macro-F1 健康时 `passes=false` 就能被解释）、带**弃权分解**的混淆矩阵（`goldFailAbstained`/`goldPassAbstained` 在 `fn`/`tn` 旁边显示/从中减去，这样 gold-pass 的 `uncertain` 不会被渲染为普通 TN）。
  - **空状态/错误状态（UI §9）：** `/runs` 无运行时显示"如何运行 eval 脚本"空状态 + Langfuse sample-traces 链接；`/runs/:runId` 缺少报告（404）时显示"运行 regression.py 以生成此报告"。对于 fixed/newly-broken 用例（UI §9）：当 `traceUrl === ""` 时渲染该行**无链接**；当 `traceUrl` 存在时，始终将其渲染为链接（只读 API 服务报告 JSON 且不探测 Langfuse 的追踪存在性，所以不存在"存在但已消失"的状态需要标记 — 已删除的追踪在点击时简单地在 Langfuse 中 404）。

- [ ] **Step 4: 组件测试（Vitest + Testing Library）**
  - runs 表格渲染行 + CI，以及三种 judge 状态：validated（显示 F1）、`not validated`（`judgeValidated === false`，徽章 + `/judges/:v` 链接，**F1 仍然显示** — 数字不被隐藏）、和 `not available`（`judgeF1`/`judgeValidated` null）。
  - 回归报告渲染所有三个结果徽章（参数化）和静态不相交性说明。
  - judge 报告渲染 macro-F1 vs 阈值、`passes` 徽章、per-label F1（包括 fail 类 F1 门控）、以及带**弃权分解**的混淆矩阵（`goldFailAbstained`/`goldPassAbstained` 明确显示，不被静默折叠到 `fn`/`tn` 中）。
  - **UI §9 状态：** 空 `/runs`（无运行）渲染空状态，而非空表格；404 `/runs/:runId` 渲染"报告未生成"状态，而非崩溃；`traceUrl === ""` 的用例渲染该行无链接；具有 `traceUrl` 的用例渲染链接（UI §9 — 只读 API 中无追踪可用性探测）。

- [ ] **Step 5: 一个 Playwright 快乐路径**
  - mock 只读 API → 打开 `/runs` → 点击一个 run → 断言结果徽章和一个有效的 Langfuse 深链接 `href`。

- [ ] **Step 6: 验证**

```bash
cd flywheel/ui && npm run test -- --run && npx playwright test
```

- [ ] **Step 7: 提交** `feat(ui): React+Vite frontend with runs, regression, and judge views`。

---

## Task 6: Bourbon 集成胶水（I/O，非 TDD — 但它是关键）

Engine spec 说这个仓库存在的唯一原因是将追踪链接到可重放的用例。
这个链接**不是**由 Tasks 1–5 构建的（它们是纯逻辑 + 
文件上的只读 API）。这个任务使其成为现实。它是胶水/I/O，所以通过
手动冒烟运行验证，而非单元测试 — 但它不能被跳过或
描述为已完成。

- [ ] **Step 1: 从 Bourbon 发出 eval 身份属性** — 在 eval 运行时，在根 span 上设置 OTel
  span 属性 `eval.case_id`（Langfuse 数据集项 id）和 `eval.run_id`
  （数据集运行名称），与 Bourbon 已发出的 `gen_ai.*` 属性并列。这是 `bourbon` 可观测性连线的一个小改动。
- [ ] **Step 2: `flywheel/scripts/sample_traces.py`** — 查询 Langfuse 获取约 20–50
  条近期追踪，偏向 Engine §5 step 1 的**所有三个**分层 — 失败
  （低分/被标记/错误）、**高风险工具/沙箱路径**（涉及高风险工具或沙箱执行的追踪）、和**长多轮会话**（高
  span/轮次数）— 而非仅失败，这样池就不会对高风险但
  未被标记的用例视而不见。将它们写入 Langfuse 数据集作为错误分析池。
  这为循环其余部分评分的用例提供种子；它本身不做评分。
- [ ] **Step 3: 标注与提升（手动，在 Langfuse 中 — Engine §5 错误分析）。**
  开放编码采样的追踪（附加 `pass`/`fail` 评分 + 一行评语），
  将评语聚类到 `flywheel/labels.md`，然后**提升**代表性
  项目到 Langfuse Dataset，在每个数据集项上设置：`input`、
  `expected`/验收说明、一个从 `labels.md` 提取的策划 `failure_label`，和
  一个**分割标签**。judge 验证用例按 60/20/20 分区为
  `judge_train` / `judge_dev` / `judge_test`（Engine §6）；门控用例
  标记为 `regression`，与所有三个 judge 分割不相交（Engine §5）。**`failure_label`
  和 `expected` 是在此处策划的数据集项元数据 — 不是从 judge
  输出派生的。** 在每个 **judge** 项（`judge_train`/`judge_dev`/`judge_test`）上还要
  **冻结标注的输出及其人类 `pass`/`fail` 标签** — 你评分的确切
  追踪输出 — 因为 judge 后来是针对*那个*输出进行验证的，永远不是重新运行的（重新运行会改变输出并使黄金
  标签过时）。`regression` 项**不**存储冻结输出；它们的输出来自
  baseline/candidate harness 运行（Step 4）。这是飞轮的人类
  部分；它设计上就是手动的，没有脚本。
- [ ] **Step 4: `flywheel/scripts/run_harness.py`** — 在
  **仅 `regression` 标签的项** 上执行 Bourbon 以创建 Langfuse **数据集运行**，
  供回归比较读取；**没有这一步就没有候选 `output` 可供
  评分。** 对于给定的 `Harness(git_sha, model)`（baseline = `main`，candidate = 
  PR 分支），在每个 `regression` 项的 `input` 上运行 agent，将 agent
  输出记录为该数据集运行项的输出，并设置 Step 1 的 `eval.case_id`（数据集项
  id）和 `eval.run_id`（数据集运行名称）span 属性，使每个追踪
  可链接回来。**将 `eval.run_id` 生成为 URL 安全的 slug**（`^[A-Za-z0-9._@-]+$`），
  因为它同时成为报告文件名和 `/api/runs/{run_id}` 路径
  段。**Slugify — 不要直接信任 `harness.id()`：** `Harness.model` 不受约束（模型快照字符串可能包含空格/奇怪字符），所以在追加时间戳之前将允许列表之外的任何
  字符映射为 `-`（例如
  `re.sub(r"[^A-Za-z0-9._@-]", "-", harness.id()) + f"-{ts}"`）。`report._safe_segment`
  强制执行 `^[A-Za-z0-9._@-]+$` 作为防御性守卫，大声拒绝非 slug id
  而非让其逃逸报告目录。运行
  **两次** — 一次用于 baseline，一次用于 candidate — 在任何评分之前。
  非确定性用例运行 ≥3×（Engine §7），每次重复一个数据集运行输出。
  **Judge 验证项（`judge_test`）*不*在此处重新运行** — 它们保留
  Step 3 的冻结标注输出，这样其黄金标签保持有效。
- [ ] **Step 5: `flywheel/scripts/run_judge.py --split <judge_dev|judge_test|regression> [--run <name>]`** —
  在**一个目标分割**上评分 judge，读取每个用例的 `input`/`output` 和
  数据集项的 `expected`/验收说明。`output` 来源因分割而异：
  对于 **`judge_dev`** 和 **`judge_test`**，没有 harness 数据集运行（Step 4
  故意跳过它们），所以**直接从每个项的元数据中读取冻结的标注输出**（Step 3）— judge 对人类标注的确切输出评分 — 
  并将判定写为 Langfuse **分类评分，以该项为键**（`validate_judge.py` 读回）；对于 **`regression`** 运行，读取命名的 baseline/candidate 数据集运行的 **Step-4
  harness 输出**，并将判定写为该运行项上的评分。**`judge_dev` 是你迭代提示词时使用的分割**（评分 `judge_dev` → `validate` → 调整提示词/示例 → 重复，次数不限）；**`judge_test` 保留给最终门控，只评分一次** — 
  对 `judge_test` 迭代会在留出集上调优，膨胀门控。
  读取数据集的分割标签后，**调用 `check_splits_disjoint({judge_train,
  judge_dev, judge_test, regression})`（plan 01 Task 4）** — 一个同时标记为
  `judge_train`（few-shot）和 `judge_test` 的用例会泄漏并膨胀门控，而
  `validate()` 看不到它，所以分区在此处被大声强制执行，在任何评分之前。构建
  judge 的 few-shot 示例**仅从 `judge_train` 项**（永远不是 `judge_dev`
  / `judge_test` / `regression` — 那样会泄漏验证集），调用
  `Judge.score_case(case_input, case_output, acceptance)` 并将 `complete` 连接到
  Anthropic，然后将判定写为 Langfuse **分类** 评分，值为
  `pass` / `fail` / `uncertain`（judge 可能弃权；`uncertain` 原样持久化，
  不被强制转换）加上评语作为评分注释。**在每个评分上持久化 judge
  身份** — `judge_version`、judge `model` 和 `prompt_version`
  在评分元数据中（或版本化评分名称如 `judge:<judge_version>`）—
  因为 `validate_judge.py` 和 `run_regression.py` 从评分中读回 `judge_version`
  以强制同一 judge 门控；读取者在评分缺少 judge 身份或运行携带**混合** `judge_version` 时**大声失败**，而非猜测。真正的 `uncertain`
  被持久化；`score_case` **`ValueError`（不可解析判定）是操作性
  失败** — 重试，或记录操作性 `skip`，但**永远不**将其持久化为
  `uncertain` 评分（那样会膨胀弃权率并因协议故障惩罚 judge）。使用 `Harness(git_sha, model)` 作为运行的 harness id。
  **每个目标调用一次** — 它每次调用恰好评分一个分割/运行，所以
  冒烟路径运行它**三次**：`judge_test` 分割（从项元数据读冻结输出 — 无 harness 运行）、**baseline** `regression` 运行和 **candidate** `regression` 运行 — 每次各一个调用（Step 5）。≥3× 重复采样（Engine §7）是 **`regression`** 运行独有的属性 — 当预算允许时对那些非确定性用例评分 ≥3×，每次重复一个评分。**`judge_test`** 运行**每用例评分一次**，所以每个验证用例有单一 judge 判定来与其人类标签比较。
- [ ] **Step 6: `flywheel/scripts/validate_judge.py [--split <judge_dev|judge_test>]`** —
  在提示词迭代期间，在 **`judge_dev`** 上运行（便宜、可重复 — 那是
  调优的反馈信号）；**门控**运行加载**留出的 `judge_test`
  分割**（默认），只评分一次。**首先对四个分割调用 `check_splits_disjoint(...)`**（纵深防御 — 即使
  `run_judge` 被跳过也能捕获泄漏的 `train`/`dev` 用例，因为此处的泄漏直接膨胀门控 F1）。加载
  选定的分割为 `LabeledCase` — `human`
  来自黄金标注（`pass`/`fail`），`judge` 从 Step 5 在
  **人类标注的同一冻结输出**上的分类评分读回（Step 3 — `judge_test` 无 harness 重新运行，
  所以黄金标签永远不过时）。`judge_test` **每用例评分一次**（Step 5），所以每个 `LabeledCase` 恰好有一个 judge 判定 — **不要**
  在此运行 `aggregate_repeats(...)`（它操作 `CaseScore` 且没有人类标签可保留）；`validate(...)` 大声拒绝任何重复的 `case_id`，所以
  杂散重复作为错误浮出，而非被静默折叠。调用
  `validate(...)`。**只有 `judge_test`（门控）运行调用 `write_judge_report(...)`**
  — `runs_provider`/UI 读取的规范报告；`judge_dev` 迭代运行
  只将其 `JudgeReport` 打印到 stdout，**不**写入（这样 dev 运行就不能
  在相同 `judge_version` 文件名处覆盖门控报告）。**当 `not
  report.passes()` 时以非零退出（macro-F1 < 0.70、fail 类 F1 < 0.70、或 gold
  `pass`/`fail` 用例太少而不能信任）** 这样 CI 就不能用未验证的
  judge 门控变更（Engine §6）。这将完整的 judge 门控连入真实工作流，而不仅仅是
  单元测试。
- [ ] **Step 7: `flywheel/scripts/run_regression.py`** — 首先**要求一个通过的
  `JudgeReport`**（读取 Step 6 写入的报告；
  如果缺失或其序列化的 **`passes` 为 false** 则拒绝比较 — 门控决策
  存在于 JSON 中，所以这无需重新推导门控逻辑就能尊重非默认支撑下限）。然后加载 baseline +
  candidate `CaseScore`，遍历 `regression` 标签的项，**从每一侧自己的评分元数据中读取其 `judge_version`（Step 5；如果评分缺少 judge 身份或运行携带混合 `judge_version` 则大声失败），并将两者都传入
  `compare(...)`（它强制同一 judge 门控 — 永远不要为双方传递一个运行级别的字符串）**；取每个用例的 `failure_label` 来自**数据集项元数据**
  （Step 3），而非 judge 评语；当一个用例被评分 ≥3×（非确定性，
  Engine §7）时，**首先调用 `check_repeat_budgets(baseline, candidate)`（plan 01
  Task 4）** — 它在不等的每用例评分计数时引发异常（例如 baseline 5× vs
  candidate 1×，这会偏置多数投票）或不足的 2× 半样本 — 然后调用 `aggregate_repeats(...)` 在比较前通过多数投票折叠重复；读取**完整的** `regression` 分割 id **和
  完整的 judge 验证集（`judge_train ∪ judge_dev ∪ judge_test`）** 从
  数据集，将前者作为 `compare(...)` 的 `regression_case_ids` 传入（这样 harness 静默丢弃的用例使完整性门控失败，而非溜过），将后者的**并集**作为 `validation_case_ids` — 不仅是 `judge_test`，因为一个同时是 `train`（few-shot）或 `dev`（提示词调优）用例的回归用例也是泄漏的。（加载时对四个分割运行 `check_splits_disjoint(...)`，
  这样错误标记的分区在此处也会大声失败。）然后构建
  `case_id → Langfuse 追踪 URL` 映射 — 对于**重复**
  用例，选取一个**代表性的**追踪，其自身判定匹配用例的
  聚合多数标签（确定性地，例如第一个这样的重复），这样
  深链接显示与 `fixed`/`newly-broken` 分类一致的证据
  而非任意的少数重复 — 然后调用
  `write_regression_report(...)` 和 `write_regression_markdown(...)`，
  向每个传入 `baseline_harness` / `candidate_harness`（比较的两个 `Harness.id()`）
  和 `trace_urls=...`。
- [ ] **Step 8: `flywheel/api/runs_provider.py`** — `/api/runs` 的**生产**数据源
  （Task 4 只注入了一个桩，所以这是单独实现和测试的，
  不是作为未测试的 lambda 遗留的）。暴露
  `list_runs(root, project, *, langfuse) -> list[dict]` 并将真实应用连接为
  `create_app(root, project=project, runs_provider=lambda p: list_runs(root, p, langfuse=client))`。
  `list_runs` 只枚举**项目的有报告支持的回归运行**（glob
  `root/<project>/reports/regression/*.json`），这样每个 `/runs` 行都能打开到真实的
  `/runs/{run_id}` 报告 — 永远不会是 404 的 Langfuse 运行。对于每个运行，关联其 judge
  验证报告以填充 `RunSummary.judgeF1`（macro-F1）和
  `RunSummary.judgeValidated`：当 judge **没有**验证报告时**两者都为 `null`**（UI"不可用"，永远不是误导性的 `0`）；当报告存在时，
  `judgeF1` 是其 macro-F1，`judgeValidated` 是其序列化的 **`passes`**（UI
  在门控失败时显示徽章"judge: not validated"，即使存在 F1 数字 — UI §6/§9）。**从运行自身的回归报告中取 `RunSummary.passRate` / `nonPassCount`**（其中持久化的候选用例级别字段），**不是**来自 Langfuse 原始运行摘要 — 带 ≥3× 重复时，原始摘要是尝试级别的，会与同一运行上的用例级别回归报告产生分歧。注入的 `langfuse` 客户端只提供 Langfuse 拥有的元数据 —
  `createdAt` / `langfuseRunUrl`（如果报告中没有则还有 `harness`/`judgeVersion`）— 每个运行。返回 `RunSummary[]`（UI §7）。
  **契约测试 `tests/api/test_runs_provider.py`：** 将一个回归报告
  （带有来自重复的非零 `nonPassCount`）加上一个**通过的**和一个
  **失败的** judge 报告写入 `tmp_path`，传入返回预设元数据的桩 `langfuse`，并断言 `list_runs` 每个有报告支持的运行返回一个 `RunSummary`，
  带有正确的 `judgeF1`/`judgeValidated`（包括当运行的 judge 没有报告时的 `null`/`null`）、`passRate`/`nonPassCount` **等于报告的**（不是桩的尝试级别数字），且**永远不**返回缺少回归报告的运行。
- [ ] **Step 9: 冒烟** — 通过 `sample_traces.py` →
  （手动标注/提升）→ `run_harness.py`（baseline **和** candidate
  `regression` 运行）→ `run_judge.py` **×3**（`--split judge_test` 读取冻结
  输出、然后是 baseline 和 candidate `regression` 运行 — 每个一次调用，
  Step 5）→ `validate_judge.py` → `run_regression.py` 运行一个真实数据集，打开 UI `/runs`，并
  确认追踪深链接在 Langfuse 中可解析。确认 `run_regression.py` 在
  judge 报告低于 macro-F1 0.70 / 低于 fail 类 F1 0.70 / 低于
  任一 gold `pass`/`fail` 支撑下限时拒绝运行。将命令记录在
  `flywheel/README.md`。

此处无超出"冒烟运行有效"的提交门控；这是
被测核心与真实 Bourbon/Langfuse 环境之间的接缝。

---

## 自审
- **Engine/UI 覆盖：** judge.py = Engine §6 judge 运行；validate.py =
  Engine §6 macro-F1≥0.70 + 每类支撑门控 + UI §7 `JudgeReport`；report.py + read_api.py = UI §7
  形状 + §8 三个只读端点；ui/ = UI §5 路由和 §6 页面设计。
- **有意删除的：** 无生命周期枚举、状态存储、审计、幂等性、
  角色、ScoreBridge、45 端点表面或 17 个记录 schema — Engine §0/§8
  记录了原因和重新添加的触发条件。
- **类型交接：** 消费 plan 01 的 `Label`、`Harness`、`ConfidenceInterval`、
  `RegressionReport`、`CaseScore`。报告 JSON 端到端都是 camelCase（Task 3），
  所以只读 API 原样服务，前端类型 1:1 映射。
- **前端保持为真实项目** — 根据所有者决策：完整 Vite 技术栈、精简
  路由表面（3 个）、只读数据、Langfuse 深链接用于 Langfuse
  已有的一切功能。
