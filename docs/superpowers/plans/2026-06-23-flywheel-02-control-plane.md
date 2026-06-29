# Flywheel 02 — Judge, Reports, Read API & Frontend (lean) Implementation Plan
**Date**: 2026-06-23 (Lean Revision 2026-06-24)
**Status**: Lean MVP — supersedes the prior "Control Plane (API + State Store)" plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development
> for the Python side; the frontend uses Vitest + Testing Library. Steps use
> checkbox (`- [ ]`) syntax.

**Goal:** Build the rest of the lean flywheel on top of plan 01: an LLM judge
runner, a 60/20/20 judge-validation report, a regression report writer, a thin
**read-only** FastAPI that serves those reports, and the **real React frontend
project** (owner's requirement) with ~3 routes.

**Architecture:** Scripts write report JSON to `~/.flywheel/<project>/reports/`.
The read API exposes three GET endpoints over those files plus Langfuse run/score
summaries. The browser talks only to the read API and gets Langfuse **deep-link
URLs**, never Langfuse write credentials.

## What changed vs the old plan
The old plan-02 built a control plane: authoritative lifecycle enums
(`ProposalState` ×18, `RegressionStatus`, `RegressionOutcome`, `RunState`,
`JudgeState`), `JsonRecordStore` + SQLite index, append-only `AuditLog`,
`IdempotencyStore`, a 4-role `auth` layer, `BaselineService` with
publish/supersede/revert, a `ScoreBridge`, ~45 endpoints (most stubbed for plans
03–07), and 17 State Store record schemas. **All deleted.** Reasons (Engine
spec §0):
- No proposal/regression/run/judge state machines — a proposal is a git PR; a
  regression result is `better|no_change|worse`; a baseline is `main`.
- No State Store — datasets/scores/annotations/issues live in Langfuse or as
  flat files; the 17 record schemas modeled deleted concepts.
- No auth/audit/idempotency control plane — single maintainer, read-only API.
- No Score Bridge — judge scores are written to Langfuse directly by `judge.py`.

What survives is the genuinely useful part: judge running, judge validation,
regression reporting, and a frontend to read them.

## File structure
- Create: `flywheel/flywheel/judge.py` — run an LLM judge over a dataset run
- Create: `flywheel/flywheel/validate.py` — 60/20/20 validation report (macro-F1 ≥ 0.70 + per-class support)
- Create: `flywheel/flywheel/report.py` — write `RegressionReport`/`JudgeReport` JSON
- Create: `flywheel/api/__init__.py`, `flywheel/api/read_api.py` — thin read-only FastAPI
- Create: `flywheel/api/runs_provider.py` — production `/api/runs` data source (Task 6 Step 8)
- Create: `flywheel/tests/test_judge.py`, `test_validate.py`, `test_report.py`, `tests/api/test_read_api.py`, `tests/api/test_runs_provider.py`
- Create: `flywheel/ui/` — React + Vite + TS frontend project (scaffold + 3 routes)

---

## Task 1: judge.py — run an LLM judge over a dataset run

**Files:** `flywheel/flywheel/judge.py`, `flywheel/tests/test_judge.py`

**Interfaces:**
- `@dataclass(frozen=True) class JudgeExample(input: str, expected: str, output: str, label: HumanLabel, critique: str)` — few-shot signal (llm-eval: examples > prompt); `expected` is the case's acceptance note (Engine §5 dataset item). `label` is `HumanLabel` (binary `pass`/`fail`) — examples come from human gold, never a `skip`/`uncertain` verdict; `__post_init__` rejects a non-binary few-shot label.
- `@dataclass(frozen=True) class JudgeConfig(judge_version: str, model: str, prompt_version: str, examples: tuple[JudgeExample, ...])`.
- `class Judge` constructed with a `JudgeConfig` and an injectable `complete: Callable[[str], str]` (the LLM call; injected so tests don't hit the network).
  - `score_case(case_input: str, case_output: str, acceptance: str) -> tuple[Label, str]` — returns `(label, critique)` with a **non-empty** critique; `acceptance` is the dataset item's `expected` / acceptance note (Engine §5) so the judge grades against real criteria, not an empty "acceptance criteria" reference. A genuine `uncertain` is a judge abstention; a **missing/malformed verdict — or a missing `REASON:` critique — raises `ValueError`** (a verdict must explain itself, UI §2 "never anonymous"; a protocol failure is not an abstention, so the caller retries or records an operational skip, never writes it as judge uncertainty).
- Few-shot examples render into the prompt; the system instruction stays neutral.

- [ ] **Step 1: failing test** `tests/test_judge.py`

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

- [ ] **Step 2:** run → fails. **Step 3: implement** `flywheel/flywheel/judge.py`

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

- [ ] **Step 4:** run → pass. **Step 5:** commit `feat(flywheel): few-shot LLM judge runner`.

> Wiring `complete` to Anthropic and writing scores back to Langfuse is a thin
> glue script under `flywheel/scripts/run_judge.py` (not TDD'd here — it is I/O).
> It reuses the `gen_ai.*` traces Bourbon already emits and the dataset run name
> as `eval.run_id`.

---

## Task 2: validate.py — 60/20/20 judge validation report

**Files:** `flywheel/flywheel/validate.py`, `flywheel/tests/test_validate.py`

**Interfaces:**
- `@dataclass(frozen=True) class LabeledCase(case_id: str, human: HumanLabel, judge: Label)` — `human` is gold and binary (`pass`/`fail`); `judge` may be `uncertain` (abstention).
- `@dataclass(frozen=True) class JudgeReport(judge_version, model, prompt_version, f1, threshold, per_label, confusion, gold_fail_abstained, gold_pass_abstained, validation_set_size, min_class_support)` — `f1` is **macro-F1** (mean of pass-class and fail-class F1). `confusion` is the 2x2 fail-positive matrix; `gold_fail_abstained`/`gold_pass_abstained` break the judge's abstentions out of `fn`/`tn` so the UI matrix doesn't read an `uncertain` on a gold case as a correct cell. `report.py` serializes the UI §7 `JudgeReport` shape including the gate decision (`passes`) and gold support counts so consumers never re-derive private gate logic; `min_class_support` is the gate's per-class floor.
- `validate(cases, *, judge_version, model, prompt_version, threshold=0.70, min_class_support=5) -> JudgeReport` — `cases` is the **held-out validation split** (the `test` 20% of the 60/20/20 partition; Engine §6). The caller is responsible for the split — the judge's few-shot examples come from `train` and must not appear here (leakage), and `dev` is used while iterating the prompt. Confusion is fail-positive (`fail` is the class we detect); an `uncertain`/`skip` verdict is non-`fail` (and non-`pass`), so a hedging judge earns no true positive in either class. The headline metric is **macro-F1** — the mean of pass-class and fail-class F1 — so a degenerate always-`fail` judge (high fail-recall, base-rate precision) can't pass on a failure-biased split. Computes tp/fp/fn/tn, per-class precision/recall, macro-F1.
- `JudgeReport.passes() -> bool` = `f1 (macro) >= threshold` **and** `fail-class F1 >= threshold` **and** the split holds at least `min_class_support` gold cases of **each** class — gold `fail` (`tp + fn`) **and** gold `pass` (`fp + tn`). The fail-class floor is independent of macro-F1: a judge can clear the mean with a perfect pass class while hedging on real failures (e.g. catching 2/5 fails, abstaining on 3 → macro ≈ 0.79 but fail-F1 ≈ 0.57), and catching failures is the judge's core job, so it must still fail. Macro-F1 over a handful of cases swings by >0.2 per single case, and a one-class split lets a degenerate judge through, so an undersized/imbalanced split is *not yet validated* and cannot gate (Engine §6) instead of passing on noise.

- [ ] **Step 1: failing test** `tests/test_validate.py`

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
    # but macro-F1 (averaging in the pass class it gets wrong) fails the gate.
    # Balanced support (8/8) so the failure is the metric, not the support floor.
    cases = [LabeledCase(f"c{i}", "fail", "fail") for i in range(8)] + \
            [LabeledCase(f"d{i}", "pass", "fail") for i in range(8)]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 < 0.70          # macro-F1 ≈ 0.33, not the inflated fail-only ≈ 0.89
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

- [ ] **Step 2:** run → fails. **Step 3: implement** `flywheel/flywheel/validate.py`

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

- [ ] **Step 4:** run → pass. **Step 5:** commit `feat(flywheel): 60/20/20 judge validation report`.

---

## Task 3: report.py — serialize reports to JSON for the read API

**Files:** `flywheel/flywheel/report.py`, `flywheel/tests/test_report.py`

**Interfaces:**
- `write_regression_report(root, project, run_id, report: RegressionReport, *, baseline_harness, candidate_harness, trace_urls: dict[str, str] | None = None, candidate_pr_url=None) -> Path` — writes `root/<project>/reports/regression/<run_id>.json` matching UI §7 `RegressionReport`. `judgeVersion` is serialized from `report.judge_version` (the version `compare()` gated), **not** a caller arg, so it can't drift from what was asserted. `run_id` becomes the filename and the `/api/runs/{run_id}` segment, so it must be a URL-safe slug (generated so in Task 6 Step 4); `_safe_segment` rejects path separators / traversal defensively. `fixed`/`newlyBroken`/`perLabel`/`passRateDelta` plus the candidate case-level `passRate`/`nonPassCount` are all derived from `report` (single owner) — the latter two from the same aggregated scores `compare()` gated on, so `runs_provider` serves them verbatim and the list never disagrees with this report; `trace_urls` maps `case_id → Langfuse deep link` so the glue script supplies URLs without `compare()` knowing about Langfuse — for a repeated case it must be a **representative** trace matching the aggregated verdict (Task 6 Step 7), not an arbitrary repeat.
- `write_judge_report(root, project, report: JudgeReport) -> Path` — writes `root/<project>/reports/judge/<judge_version>.json` matching UI §7 `JudgeReport`, including the serialized gate decision (`passes`) and gold support counts so `run_regression.py` and the UI honor the gate without re-deriving private logic.
- `write_regression_markdown(root, project, run_id, report: RegressionReport, *, baseline_harness, candidate_harness, trace_urls: dict[str, str] | None = None, candidate_pr_url=None) -> Path` — renders `report.judge_version` (not a caller arg). Writes a human-readable `root/<project>/reports/regression/<run_id>.md` (Engine §3/§7 mandate "markdown + JSON"). The JSON feeds the UI; the markdown is the artifact a human reads or pastes into the candidate PR, so it renders `baseline_harness → candidate_harness` (same data as the JSON — without it the artifact can't say *what* was compared). `trace_urls` (same map passed to `write_regression_report`) renders fixed/newly-broken case ids as Langfuse deep links (Engine §7 / UI §6). Same data as the JSON, no new computation.
- `read_json(path) -> dict`.
- **Locked decision:** report JSON uses the camelCase keys the frontend expects (UI §7), written directly here, so the read API can serve them verbatim. The CI bounds come from `report.delta_low/delta_high` (a real interval, never zero-width).

- [ ] **Step 1: failing test** `tests/test_report.py`

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
    # real CI: low <= point <= high (not a zero-width fake)
    d = data["passRateDelta"]
    assert d["low"] <= d["point"] <= d["high"]
    # candidate case-level summary served from the report (not raw Langfuse attempts)
    assert data["passRate"]["low"] <= data["passRate"]["point"] <= data["passRate"]["high"]
    assert data["nonPassCount"] == 0          # both candidate cases pass
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
    with pytest.raises(ValueError, match="unsafe id segment"):
        write_regression_report(tmp_path, "bourbon", "../../escape", rep,
                                baseline_harness="a@m", candidate_harness="b@m")
```

- [ ] **Step 2:** run → fails. **Step 3: implement** `flywheel/flywheel/report.py`

```python
"""Serialize reports to JSON consumed by the read API / frontend (UI §7).
Keys are camelCase to match the frontend types exactly — no boundary mapping."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .regression import RegressionReport
from .validate import JudgeReport

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._@-]+$")


def _reports_dir(root: Path, project: str, kind: str) -> Path:
    d = Path(root) / project / "reports" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_segment(value: str) -> str:
    """Allow only URL-safe slug ids `[A-Za-z0-9._@-]` (and never bare '.'/'..'), so a
    run_id/judge_version with a space, '?', '#', '/', '\\', NUL, or unicode can't
    escape the reports dir or break the `/api/...` path — reject rather than sanitize,
    so a non-slug id fails loudly at write time instead of silently relocating."""
    if not _SAFE_SEGMENT.match(value) or value in (".", ".."):
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
        # real CI from the regression report — never a zero-width fake
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
        f"(Δ {report.delta:+.3f}, 95% CI [{report.delta_low:+.3f}, {report.delta_high:+.3f}])",
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

- [ ] **Step 4:** run → pass. **Step 5:** commit `feat(flywheel): regression/judge report serialization`.

---

## Task 4: read_api.py — thin read-only FastAPI (3 endpoints)

**Files:** `flywheel/api/__init__.py`, `flywheel/api/read_api.py`, `flywheel/tests/api/test_read_api.py`

**Interfaces:**
- `create_app(root, *, project: str, runs_provider: Callable[[str], list[dict[str, object]]]) -> FastAPI`. The app is bound to a single configured `project` (this is a personal one-project tool), so the endpoints carry no `?project=` query — matching UI §8 exactly. `runs_provider(project)` returns `RunSummary[]` (injected; the production implementation is `flywheel/api/runs_provider.py:list_runs` — Task 6 Step 8 — which returns the **report-backed regression runs only** so every listed run resolves to a `/runs/{run_id}` report and never 404s; stubbed here in the endpoint tests, tested on its own in `tests/api/test_runs_provider.py`).
- **Endpoints return the UI §8 shapes directly — no envelope wrapper, no query params:**
- `GET /api/runs` → `RunSummary[]` (a bare JSON array).
- `GET /api/runs/{run_id}` → `RegressionReport` from the report file; 404 if absent.
- `GET /api/judges/{judge_version}` → `JudgeReport` from the report file; 404 if absent.
- Read-only: no POST, no auth, no idempotency. Browser never receives Langfuse write creds (UI §4).
- **Packaging:** this task creates the sibling `api/` package, so add `api` to `[tool.hatch.build.targets.wheel] packages` in `flywheel/pyproject.toml` (plan 01 shipped `packages = ["flywheel"]` only) before re-installing.

- [ ] **Step 1: failing test** `tests/api/test_read_api.py`

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

- [ ] **Step 2:** run → fails. **Step 3: implement** `flywheel/api/read_api.py`

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

- [ ] **Step 4: Package `api`** — edit `flywheel/pyproject.toml` so the sibling
  package ships in the wheel: `[tool.hatch.build.targets.wheel] packages = ["flywheel", "api"]`
  (plan 01 shipped `["flywheel"]` only), then re-run `uv pip install -e ".[dev]"`.
  Verify `python -c "import api.read_api"` works from **outside** the source root
  (so the build, not just `pythonpath = ["."]`, exposes `api`).
- [ ] **Step 5:** run → pass. **Step 6:** `pytest tests/api -q && ruff check api flywheel tests && mypy flywheel api`. **Step 7:** commit `feat(api): thin read-only API for runs and judge reports`.

---

## Task 5: ui/ — React + Vite + TS frontend project

**Files:** `flywheel/ui/` (scaffold). The owner wants a real frontend project, so
this is a full Vite app — slim in **surface** (3 routes), not in stack.

**Stack (UI §3):** React + TS + Vite, React Router, TanStack Query, TanStack
Table, shadcn/ui (or local components), Recharts, Vitest + Testing Library, one
Playwright happy-path.

- [ ] **Step 1: Scaffold**

```bash
cd flywheel && npm create vite@latest ui -- --template react-ts
cd ui && npm install @tanstack/react-query @tanstack/react-table react-router-dom recharts
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom @playwright/test
```

- [ ] **Step 2: API client + types** — `ui/src/api.ts` with the UI §7 types
  (`RunSummary`, `RegressionReport`, `LabelDelta`, `JudgeReport`,
  `RegressionResult`) and three fetchers hitting the read API. The report JSON is
  already camelCase (Task 3), so the types map 1:1 — no boundary translation.

- [ ] **Step 3: Routes (UI §5)**
  - `/` — index: links to runs + a Langfuse deep link for traces/datasets/annotation.
  - `/runs` — `RunSummary[]` table: run id, harness, judge version, judge status — **render `judgeF1` (macro-F1) whenever it is non-null, including when `judgeValidated === false`** (don't hide the number); `judgeValidated` drives only the badge (`validated` vs `judge: not validated`, the latter linking to `/judges/:judgeVersion`); show `not available` **only** when `judgeF1`/`judgeValidated` are null (no report) — UI §6/§9. Then pass rate + CI bar, #not-passed, Langfuse link.
  - `/runs/:runId` — `RegressionReport`: baseline vs candidate harness, judge version (with the "same judge" note), pass-rate delta + CI, result badge (`better` green / `no_change` amber / `worse` red), per-label delta table, fixed / newly-broken lists with Langfuse trace deep links, and the **disjointness note** "regression set ∩ judge case pool = ∅" rendered as a static invariant (UI §6 — the report's existence proves it, no data field).
  - `/judges/:judgeVersion` — `JudgeReport`: macro-F1 vs threshold + validated/`passes` badge, gold pass/fail counts vs the support floor, per-label precision/recall/**F1** (fail-class F1 flagged against its own 0.70 gate, so a `passes=false` at healthy macro-F1 is explained), confusion matrix.
  - **Empty / error states (UI §9):** `/runs` with no runs shows the "how to run the eval script" empty state + Langfuse sample-traces link; `/runs/:runId` with a missing report (404) shows "run regression.py to produce this report". For a fixed/newly-broken case, distinguish two trace states (UI §9): when `traceUrl === ""` (no URL in the report) render the row with **no link**; when a `traceUrl` is present but the trace is gone in Langfuse, **keep the link** and mark it `unavailable` (don't drop a real deep link the user may still want).

- [ ] **Step 4: Component tests (Vitest + Testing Library)**
  - runs table renders rows + CI, and the three judge states: validated (F1 shown), `not validated` (`judgeValidated === false`, badge + `/judges/:v` link, **F1 still shown** — the number isn't hidden), and `not available` (`judgeF1`/`judgeValidated` null).
  - regression report renders all three result badges (parametrized) and the static disjointness note.
  - judge report renders macro-F1 vs threshold, the `passes` badge, per-label F1 (incl. the fail-class F1 gate), and confusion matrix.
  - **UI §9 states:** empty `/runs` (no runs) renders the empty state, not a blank table; a 404 `/runs/:runId` renders the "report not generated" state, not a crash; a case with `traceUrl === ""` renders the row with no link; a case with a present-but-unavailable trace keeps the link with an `unavailable` marker (UI §9).

- [ ] **Step 5: One Playwright happy path**
  - mock the read API → open `/runs` → click a run → assert the result badge and a working Langfuse deep-link `href`.

- [ ] **Step 6: Verify**

```bash
cd flywheel/ui && npm run test -- --run && npx playwright test
```

- [ ] **Step 7: Commit** `feat(ui): React+Vite frontend with runs, regression, and judge views`.

---

## Task 6: Bourbon integration glue (I/O, not TDD — but it is the point)

The engine spec says the one reason this repo exists is linking a trace to a
replayable case. That link is **not** built by Tasks 1–5 (they are pure logic +
a read API over files). This task makes it real. It is glue/I/O, so it is
verified by a manual smoke run, not unit tests — but it must not be skipped or
described as done.

- [ ] **Step 1: Emit eval identity attrs from Bourbon** — on eval runs, set OTel
  span attributes `eval.case_id` (the Langfuse dataset item id) and `eval.run_id`
  (the dataset run name) on the root span, alongside the `gen_ai.*` attrs Bourbon
  already emits. This is a small change in `bourbon`'s observability wiring.
- [ ] **Step 2: `flywheel/scripts/sample_traces.py`** — query Langfuse for ~20–50
  recent traces, biased toward **all three** of Engine §5 step 1's strata — failures
  (low score / flagged / errored), **risky tool/sandbox paths** (traces touching
  high-risk tools or sandbox execution), and **long multi-turn sessions** (high
  span/turn count) — not failures alone, so the pool isn't blind to the risky-but-
  un-flagged cases. Write them into a Langfuse dataset as the error-analysis pool.
  This seeds the cases the rest of the loop scores; it does no scoring itself.
- [ ] **Step 3: Annotate & promote (manual, in Langfuse — Engine §5 error analysis).**
  Open-code the sampled traces (attach a `pass`/`fail` score + one-line critique),
  cluster the critiques into `flywheel/labels.md`, then **promote** representative
  items into the Langfuse Dataset, setting on each dataset item: `input`, the
  `expected`/acceptance note, a curated `failure_label` drawn from `labels.md`, and
  a **split tag**. The judge-validation cases are partitioned 60/20/20 into
  `judge_train` / `judge_dev` / `judge_test` (Engine §6); the gating cases are
  tagged `regression`, disjoint from all three judge splits (Engine §5). **`failure_label`
  and `expected` are dataset-item metadata curated here — not derived from judge
  output.** On each **judge** item (`judge_train`/`judge_dev`/`judge_test`) also
  **freeze the annotated output and its human `pass`/`fail` label** — the exact
  trace output you graded — because the judge is later validated against *that*
  output, never a fresh rerun (a rerun would change the output and make the gold
  label stale). `regression` items store **no** frozen output; their outputs come
  from the baseline/candidate harness runs (Step 4). This is the human half of the
  flywheel; it is manual by design and has no script.
- [ ] **Step 4: `flywheel/scripts/run_harness.py`** — execute Bourbon over the
  **`regression`-tagged items only** to create the Langfuse **dataset runs** the
  regression compare reads; **without this step there is no candidate `output` to
  score.** For a given `Harness(git_sha, model)` (baseline = `main`, candidate = the
  PR branch), run the agent on each `regression` item's `input`, record the agent
  output as that dataset-run item's output, and set the `eval.case_id` (dataset item
  id) and `eval.run_id` (dataset run name) span attrs from Step 1 so each trace
  links back. **Generate `eval.run_id` as a URL-safe slug** (`^[A-Za-z0-9._@-]+$`)
  because it becomes both the report filename and the `/api/runs/{run_id}` path
  segment. **Slugify — don't trust `harness.id()` verbatim:** `Harness.model` is
  unconstrained (a model snapshot string can carry spaces/odd chars), so map any
  char outside the allowlist to `-` before appending the timestamp (e.g.
  `re.sub(r"[^A-Za-z0-9._@-]", "-", harness.id()) + f"-{ts}"`). `report._safe_segment`
  enforces `^[A-Za-z0-9._@-]+$` as the defensive guard, rejecting a non-slug id
  loudly rather than letting it escape the reports dir. Run
  it **twice** — once for baseline, once for candidate — before any scoring.
  Nondeterministic cases are run ≥3× (Engine §7), one dataset-run output per repeat.
  **Judge-validation items (`judge_test`) are *not* rerun here** — they keep the
  frozen annotated output from Step 3 so their gold labels stay valid.
- [ ] **Step 5: `flywheel/scripts/run_judge.py --split <judge_dev|judge_test|regression> [--run <name>]`** —
  score the judge over **one target split**, reading each case's `input`/`output` and
  the dataset item's `expected`/acceptance note. The `output` source differs by split:
  for **`judge_dev`** and **`judge_test`** there is **no harness dataset run** (Step 4
  deliberately skips them), so read the **frozen annotated output straight from each
  item's metadata** (Step 3) — the judge grades the exact output the human labeled —
  and write the verdict as a Langfuse **categorical score keyed to that item** (which
  `validate_judge.py` reads back); for a **`regression`** run, read the **Step-4
  harness output** of the named baseline/candidate dataset run and write the verdict
  as a score on that run's item. **`judge_dev` is the split you iterate the prompt
  against** (score `judge_dev` → `validate` → tweak prompt/examples → repeat, as
  often as you like); **`judge_test` is reserved for the final gate, scored once** —
  iterating against `judge_test` would tune on the held-out set and inflate the gate.
  Build
  the judge's few-shot examples **only from `judge_train` items** (never `judge_dev`
  / `judge_test` / `regression` — that would leak the validation set), call
  `Judge.score_case(case_input, case_output, acceptance)` with `complete` wired to
  Anthropic, and write the verdict as a Langfuse **categorical** score with value
  `pass` / `fail` / `uncertain` (the judge may abstain; `uncertain` is persisted as
  itself, not coerced) plus the critique as the score comment. **Persist the judge
  identity on every score** — `judge_version`, judge `model`, and `prompt_version`
  in the score metadata (or a versioned score name like `judge:<judge_version>`) —
  because `validate_judge.py` and `run_regression.py` read `judge_version` back from
  the score to enforce the same-judge gate; a reader **fails loudly** on a score with
  a missing judge identity or on a run carrying **mixed** `judge_version`s rather than
  guessing. A genuine `uncertain`
  is persisted; a `score_case` **`ValueError` (unparseable verdict) is an operational
  failure** — retry, or record an operational `skip`, but **never** persist it as an
  `uncertain` score (that would inflate the abstention rate and punish the judge for
  a protocol glitch). Uses `Harness(git_sha, model)` for the run's harness id.
  **Invoke this once per target** — it scores exactly one split/run per call, so the
  smoke path runs it **three times**: the `judge_test` split (frozen outputs from item
  metadata — no harness run), the **baseline** `regression` run, and the **candidate**
  `regression` run. The ≥3× repeat sampling (Engine §7) is a property of the **`regression`** runs
  only — score those nondeterministic cases ≥3× when budget allows, one score per
  repeat. The **`judge_test`** run is scored **once per case**, so each validation
  case has a single judge verdict to compare against its human label.
- [ ] **Step 6: `flywheel/scripts/validate_judge.py [--split <judge_dev|judge_test>]`** —
  during prompt iteration, run it on **`judge_dev`** (cheap, repeatable — that's the
  feedback signal for tuning); the **gating** run loads the **held-out `judge_test`
  split** (default), scored once. Load the chosen split as `LabeledCase`s — `human`
  from the gold annotation (`pass`/`fail`), `judge` read back from the Step 5
  categorical score on the
  **same frozen output the human annotated** (Step 3 — no harness rerun for
  `judge_test`, so the gold label is never stale). `judge_test` is scored **once per
  case** (Step 5), so each `LabeledCase` has exactly one judge verdict — do **not**
  run `aggregate_repeats(...)` here (it operates on `CaseScore` and has no human
  label to preserve); `validate(...)` rejects any duplicate `case_id` loudly, so a
  stray repeat surfaces as an error instead of being silently collapsed. Call
  `validate(...)`. **Only the `judge_test` (gate) run calls `write_judge_report(...)`**
  — the canonical report that `runs_provider`/the UI read; a `judge_dev` iteration run
  just prints its `JudgeReport` to stdout and does **not** write (so dev runs can't
  clobber the gating report at the same `judge_version` filename). **Exit non-zero when `not
  report.passes()` (macro-F1 < 0.70, fail-class F1 < 0.70, or too few gold
  `pass`/`fail` cases to trust it)** so CI cannot gate a change with an unvalidated
  judge (Engine §6). This wires the full judge gate into the real workflow, not just
  the unit test.
- [ ] **Step 7: `flywheel/scripts/run_regression.py`** — first **require a passing
  `JudgeReport`** for the run's `judge_version` (read the report written in Step 6;
  refuse to compare if it is missing or its serialized **`passes` is false** — the
  gate decision lives in the JSON, so this honors non-default support floors without
  re-deriving gate logic). Then load baseline +
  candidate `CaseScore`s over the `regression`-tagged items, **reading each side's
  `judge_version` from its own score metadata (Step 5; fail loudly if a score lacks
  the judge identity or a run carries mixed `judge_version`s) and passing both into
  `compare(...)` (which enforces the same-judge gate — never pass one run-level
  string for both sides)**; take each case's `failure_label` from the **dataset-item metadata**
  (Step 3), not the judge critique; when a case was scored ≥3× (nondeterministic,
  Engine §7), **first call `check_repeat_budgets(baseline, candidate)` (plan 01
  Task 4)** — it raises on an unequal per-case score count (e.g. baseline 5× vs
  candidate 1×, which would bias the majority vote) or an under-powered 2× half-
  sample — then call `aggregate_repeats(...)` to collapse repeats by majority vote
  before comparing; read **both** the full `regression` split ids **and
  the full judge-validation set (`judge_train ∪ judge_dev ∪ judge_test`)** from the
  dataset, and pass the former as `compare(...)`'s `regression_case_ids` (so a case
  the harness silently dropped fails the completeness gate, not slips through) and
  the latter **union** as `validation_case_ids` — not just `judge_test`, since a
  regression case that was a `train` (few-shot) or `dev` (prompt-tuning) case is
  leaked too. Then build the `case_id → Langfuse trace URL` map — for a **repeated**
  case, pick a **representative** trace whose own verdict matches the case's
  aggregated majority label (deterministically, e.g. the first such repeat), so the
  deep link shows evidence consistent with the `fixed`/`newly-broken` classification
  rather than an arbitrary minority repeat — and call both
  `write_regression_report(...)` and `write_regression_markdown(...)`,
  passing `baseline_harness` / `candidate_harness` (the two `Harness.id()`s compared)
  and `trace_urls=...` to each.
- [ ] **Step 8: `flywheel/api/runs_provider.py`** — the **production** data source
  for `/api/runs` (Task 4 only injects a stub, so this is implemented and tested on
  its own, not left as an untested lambda). Expose
  `list_runs(root, project, *, langfuse) -> list[dict]` and wire the real app as
  `create_app(root, project=project, runs_provider=lambda p: list_runs(root, p, langfuse=client))`.
  `list_runs` enumerates **only the project's report-backed regression runs** (glob
  `root/<project>/reports/regression/*.json`) so every `/runs` row opens to a real
  `/runs/{run_id}` report — never a Langfuse run that 404s. For each, join its judge
  validation report to populate `RunSummary.judgeF1` (macro-F1) and
  `RunSummary.judgeValidated`: **both `null`** when the judge has **no** validation
  report (UI "not available", never a misleading `0`); when a report exists,
  `judgeF1` is its macro-F1 and `judgeValidated` is its serialized **`passes`** (UI
  badges "judge: not validated" when the gate failed even though an F1 number exists
  — UI §6/§9). **Take `RunSummary.passRate` / `nonPassCount` from the run's own
  regression report** (the candidate case-level fields persisted there), **not** from
  the Langfuse raw run summary — with ≥3× repeats the raw summary is attempt-level
  and would disagree with the case-level regression report on the same run. The
  injected `langfuse` client supplies only the metadata Langfuse owns —
  `createdAt` / `langfuseRunUrl` (and `harness`/`judgeVersion` if not already in the
  report) — per run. Return `RunSummary[]` (UI §7).
  **Contract test `tests/api/test_runs_provider.py`:** write a regression report
  (with a non-zero `nonPassCount` from repeats) plus one **passing** and one
  **failing** judge report into `tmp_path`, pass a stub `langfuse` returning canned
  metadata, and assert `list_runs` returns one `RunSummary` per report-backed run
  with the correct `judgeF1`/`judgeValidated` (including `null`/`null` when the run's
  judge has no report), `passRate`/`nonPassCount` **equal to the report's** (not the
  stub's attempt-level numbers), and **never** a run that lacks a regression report.
- [ ] **Step 9: Smoke** — run one real dataset through `sample_traces.py` →
  (manual annotate/promote) → `run_harness.py` (baseline **and** candidate
  `regression` runs) → `run_judge.py` **×3** (`--split judge_test` reading frozen
  outputs, then the baseline and candidate `regression` runs — one invocation each,
  Step 5) → `validate_judge.py` → `run_regression.py`, open the UI `/runs`, and
  confirm a trace deep link resolves in Langfuse. Confirm `run_regression.py` refuses
  to run when the judge report is below macro-F1 0.70 / below fail-class F1 0.70 / below
  either the gold `pass`/`fail` support floor. Document the commands in
  `flywheel/README.md`.

No commit gating here beyond "the smoke run works"; this is the seam between the
tested core and the real Bourbon/Langfuse environment.

---

## Self-review
- **Engine/UI coverage:** judge.py = Engine §6 judge running; validate.py =
  Engine §6 macro-F1≥0.70 + per-class support gate + UI §7 `JudgeReport`; report.py + read_api.py = UI §7
  shapes + §8 three read endpoints; ui/ = UI §5 routes and §6 page designs.
- **Deleted-on-purpose:** no lifecycle enums, State Store, audit, idempotency,
  roles, ScoreBridge, 45-endpoint surface, or 17 record schemas — Engine §0/§8
  record why and the add-back triggers.
- **Type handoff:** consumes plan 01's `Label`, `Harness`, `ConfidenceInterval`,
  `RegressionReport`, `CaseScore`. Report JSON is camelCase end-to-end (Task 3),
  so the read API serves it verbatim and the frontend types map 1:1.
- **Frontend kept as a real project** per owner decision: full Vite stack, slim
  route surface (3), read-only data, Langfuse deep links for everything Langfuse
  already does.
