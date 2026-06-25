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
- Create: `flywheel/flywheel/validate.py` — 60/20/20 validation report (F1 ≥ 0.70)
- Create: `flywheel/flywheel/report.py` — write `RegressionReport`/`JudgeReport` JSON
- Create: `flywheel/api/__init__.py`, `flywheel/api/read_api.py` — thin read-only FastAPI
- Create: `flywheel/tests/test_judge.py`, `test_validate.py`, `test_report.py`, `tests/api/test_read_api.py`
- Create: `flywheel/ui/` — React + Vite + TS frontend project (scaffold + 3 routes)

---

## Task 1: judge.py — run an LLM judge over a dataset run

**Files:** `flywheel/flywheel/judge.py`, `flywheel/tests/test_judge.py`

**Interfaces:**
- `@dataclass(frozen=True) class JudgeExample(input: str, output: str, label: Label, critique: str)` — few-shot signal (llm-eval: examples > prompt).
- `@dataclass(frozen=True) class JudgeConfig(judge_version: str, model: str, prompt_version: str, examples: tuple[JudgeExample, ...])`.
- `class Judge` constructed with a `JudgeConfig` and an injectable `complete: Callable[[str], str]` (the LLM call; injected so tests don't hit the network).
  - `score_case(case_input: str, case_output: str) -> tuple[Label, str]` — returns `(label, critique)`; parses the model's verdict line.
- Few-shot examples render into the prompt; the system instruction stays neutral.

- [ ] **Step 1: failing test** `tests/test_judge.py`

```python
from flywheel.judge import Judge, JudgeConfig, JudgeExample

def _judge(canned: str):
    cfg = JudgeConfig(
        judge_version="judge-v1", model="claude-opus-4-8", prompt_version="p1",
        examples=(JudgeExample("in", "good out", "pass", "meets criteria"),),
    )
    return Judge(cfg, complete=lambda prompt: canned)

def test_judge_parses_pass():
    label, critique = _judge("VERDICT: pass\nREASON: tool args correct").score_case("q", "a")
    assert label == "pass"
    assert "tool args correct" in critique

def test_judge_parses_fail():
    label, _ = _judge("VERDICT: fail\nREASON: wrong arg shape").score_case("q", "a")
    assert label == "fail"

def test_judge_prompt_includes_fewshot():
    seen = {}
    cfg = JudgeConfig("judge-v1", "claude-opus-4-8", "p1",
                      (JudgeExample("ex-in", "ex-out", "fail", "missing offset"),))
    j = Judge(cfg, complete=lambda p: seen.setdefault("p", p) or "VERDICT: pass\nREASON: ok")
    j.score_case("q", "a")
    assert "missing offset" in seen["p"]  # few-shot critique carried into the prompt
```

- [ ] **Step 2:** run → fails. **Step 3: implement** `flywheel/flywheel/judge.py`

```python
"""LLM judge runner (Engine §6; llm-eval stage 4). Few-shot examples carry the
signal; the system instruction stays neutral. The LLM call is injected so the
logic is testable without a network."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .identity import Label

_NEUTRAL_SYSTEM = (
    "You are grading whether an agent's output satisfies the case's acceptance "
    "criteria. Reply with two lines:\nVERDICT: pass|fail\nREASON: <one line>"
)


@dataclass(frozen=True)
class JudgeExample:
    input: str
    output: str
    label: Label
    critique: str


@dataclass(frozen=True)
class JudgeConfig:
    judge_version: str
    model: str
    prompt_version: str
    examples: tuple[JudgeExample, ...]


class Judge:
    def __init__(self, config: JudgeConfig, complete: Callable[[str], str]):
        self._config = config
        self._complete = complete

    def _prompt(self, case_input: str, case_output: str) -> str:
        shots = "\n\n".join(
            f"INPUT: {e.input}\nOUTPUT: {e.output}\nVERDICT: {e.label}\nREASON: {e.critique}"
            for e in self._config.examples
        )
        return (
            f"{_NEUTRAL_SYSTEM}\n\n# Examples\n{shots}\n\n"
            f"# Case\nINPUT: {case_input}\nOUTPUT: {case_output}\n"
        )

    def score_case(self, case_input: str, case_output: str) -> tuple[Label, str]:
        raw = self._complete(self._prompt(case_input, case_output))
        label: Label = "uncertain"
        critique = ""
        for line in raw.splitlines():
            low = line.strip().lower()
            if low.startswith("verdict:"):
                value = low.split(":", 1)[1].strip()
                label = "pass" if value == "pass" else "fail" if value == "fail" else "uncertain"
            elif low.startswith("reason:"):
                critique = line.split(":", 1)[1].strip()
        return label, critique
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
- `@dataclass(frozen=True) class LabeledCase(case_id: str, human: Label, judge: Label)`.
- `@dataclass(frozen=True) class JudgeReport(judge_version, model, prompt_version, f1, threshold, per_label, confusion, validation_set_size)` — matches UI §7 `JudgeReport`.
- `validate(cases, *, judge_version, model, prompt_version, threshold=0.70) -> JudgeReport` — `fail` is the positive class (we detect failures); computes tp/fp/fn/tn, overall F1, per-label precision/recall.
- `JudgeReport.passes() -> bool` = `f1 >= threshold`.

- [ ] **Step 1: failing test** `tests/test_validate.py`

```python
from flywheel.validate import validate, LabeledCase

def test_perfect_agreement_is_f1_1():
    cases = [LabeledCase(f"c{i}", "fail", "fail") for i in range(5)] + \
            [LabeledCase(f"d{i}", "pass", "pass") for i in range(5)]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 == 1.0
    assert rep.passes()

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

def test_uncertain_judge_counts_as_fail_not_dropped():
    # judge "uncertain" on a real failure must count (as a fail prediction), not vanish
    cases = [LabeledCase("a", "fail", "uncertain"), LabeledCase("b", "pass", "pass")]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.confusion["tp"] == 1  # uncertain -> fail -> matches human fail
    assert rep.validation_set_size == 2
```

- [ ] **Step 2:** run → fails. **Step 3: implement** `flywheel/flywheel/validate.py`

```python
"""Judge validation (Engine §6; llm-eval stage 5). 'fail' is the positive class
because the judge's job is to catch failures. F1 >= threshold => usable to gate.

The gate is binary, but Label has four values. Any non-"pass" label
(fail/skip/uncertain) is normalized to "fail" before counting, so a judge that
hedges with "uncertain" is counted conservatively against the gate rather than
silently dropped from tp/fp/fn/tn (which would inflate apparent agreement)."""
from __future__ import annotations

from dataclasses import dataclass

from .identity import Label
from .metrics import precision_recall_f1


def _bin(label: Label) -> str:
    """Binarize to the gating classes: pass vs fail (everything else -> fail)."""
    return "pass" if label == "pass" else "fail"


@dataclass(frozen=True)
class LabeledCase:
    case_id: str
    human: Label
    judge: Label


@dataclass(frozen=True)
class JudgeReport:
    judge_version: str
    model: str
    prompt_version: str
    f1: float
    threshold: float
    per_label: list[dict]
    confusion: dict[str, int]
    validation_set_size: int

    def passes(self) -> bool:
        return self.f1 >= self.threshold


def validate(cases: list[LabeledCase], *, judge_version: str, model: str,
             prompt_version: str, threshold: float = 0.70) -> JudgeReport:
    pairs = [(_bin(c.human), _bin(c.judge)) for c in cases]
    tp = sum(1 for h, j in pairs if h == "fail" and j == "fail")
    fp = sum(1 for h, j in pairs if h == "pass" and j == "fail")
    fn = sum(1 for h, j in pairs if h == "fail" and j == "pass")
    tn = sum(1 for h, j in pairs if h == "pass" and j == "pass")
    _, _, f1 = precision_recall_f1(tp, fp, fn)

    per_label = []
    for label in ("pass", "fail"):
        ltp = sum(1 for h, j in pairs if h == label and j == label)
        lfp = sum(1 for h, j in pairs if h != label and j == label)
        lfn = sum(1 for h, j in pairs if h == label and j != label)
        p, r, _ = precision_recall_f1(ltp, lfp, lfn)
        per_label.append({"label": label, "precision": p, "recall": r})

    return JudgeReport(
        judge_version=judge_version, model=model, prompt_version=prompt_version,
        f1=f1, threshold=threshold, per_label=per_label,
        confusion={"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        validation_set_size=len(cases),
    )
```

- [ ] **Step 4:** run → pass. **Step 5:** commit `feat(flywheel): 60/20/20 judge validation report`.

---

## Task 3: report.py — serialize reports to JSON for the read API

**Files:** `flywheel/flywheel/report.py`, `flywheel/tests/test_report.py`

**Interfaces:**
- `write_regression_report(root, project, run_id, report: RegressionReport, *, baseline_harness, candidate_harness, judge_version, trace_urls: dict[str, str] | None = None, candidate_pr_url=None) -> Path` — writes `root/<project>/reports/regression/<run_id>.json` matching UI §7 `RegressionReport`. `fixed`/`newlyBroken`/`perLabel`/`passRateDelta` are all derived from `report` (single owner); `trace_urls` maps `case_id → Langfuse deep link` so the glue script supplies URLs without `compare()` knowing about Langfuse.
- `write_judge_report(root, project, report: JudgeReport) -> Path` — writes `root/<project>/reports/judge/<judge_version>.json` matching UI §7 `JudgeReport`.
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
    rep = compare(base, cand, validation_case_ids=set(),
                  baseline_judge_version="jv1", candidate_judge_version="jv1")
    path = write_regression_report(
        tmp_path, "bourbon", "run_1", rep,
        baseline_harness="abc@m", candidate_harness="def@m", judge_version="jv1",
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
    assert data["perLabel"][0]["label"] == "tool_misuse"
```

- [ ] **Step 2:** run → fails. **Step 3: implement** `flywheel/flywheel/report.py`

```python
"""Serialize reports to JSON consumed by the read API / frontend (UI §7).
Keys are camelCase to match the frontend types exactly — no boundary mapping."""
from __future__ import annotations

import json
from pathlib import Path

from .regression import RegressionReport
from .validate import JudgeReport


def _reports_dir(root: Path, project: str, kind: str) -> Path:
    d = Path(root) / project / "reports" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_regression_report(
    root: Path, project: str, run_id: str, report: RegressionReport, *,
    baseline_harness: str, candidate_harness: str, judge_version: str,
    trace_urls: dict[str, str] | None = None,
    candidate_pr_url: str | None = None,
) -> Path:
    urls = trace_urls or {}

    def _enrich(case_ids: list[str]) -> list[dict]:
        return [{"caseId": cid, "traceUrl": urls.get(cid, "")} for cid in case_ids]

    payload = {
        "runId": run_id,
        "baselineHarness": baseline_harness,
        "candidateHarness": candidate_harness,
        "judgeVersion": judge_version,
        # real CI from the regression report — never a zero-width fake
        "passRateDelta": {"point": report.delta,
                          "low": report.delta_low,
                          "high": report.delta_high},
        "result": report.result,
        "perLabel": report.per_label,           # single owner: derived in compare()
        "fixed": _enrich(report.fixed),
        "newlyBroken": _enrich(report.newly_broken),
        "candidatePrUrl": candidate_pr_url,
    }
    path = _reports_dir(root, project, "regression") / f"{run_id}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def write_judge_report(root: Path, project: str, report: JudgeReport) -> Path:
    payload = {
        "judgeVersion": report.judge_version,
        "model": report.model,
        "promptVersion": report.prompt_version,
        "f1": report.f1,
        "threshold": report.threshold,
        "perLabel": report.per_label,
        "confusion": report.confusion,
        "validationSetSize": report.validation_set_size,
    }
    path = _reports_dir(root, project, "judge") / f"{report.judge_version}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text())
```

- [ ] **Step 4:** run → pass. **Step 5:** commit `feat(flywheel): regression/judge report serialization`.

---

## Task 4: read_api.py — thin read-only FastAPI (3 endpoints)

**Files:** `flywheel/api/__init__.py`, `flywheel/api/read_api.py`, `flywheel/tests/api/test_read_api.py`

**Interfaces:**
- `create_app(root, *, runs_provider: Callable[[str], list[dict]]) -> FastAPI`. `runs_provider(project)` returns `RunSummary[]` (injected; in production it queries Langfuse run/score summaries — stubbed in tests).
- `GET /api/runs?project=` → `{"runs": RunSummary[]}`.
- `GET /api/runs/{run_id}?project=` → `{"run": RegressionReport}` from the report file; 404 if absent.
- `GET /api/judges/{judge_version}?project=` → `{"judge": JudgeReport}` from the report file; 404 if absent.
- Read-only: no POST, no auth, no idempotency. Browser never receives Langfuse write creds (UI §4).

- [ ] **Step 1: failing test** `tests/api/test_read_api.py`

```python
from pathlib import Path
from fastapi.testclient import TestClient
from flywheel.regression import compare, CaseScore
from flywheel.report import write_regression_report
from api.read_api import create_app

def _client(tmp_path: Path):
    runs = [{"runId": "run_1", "harness": "abc@m", "judgeVersion": "jv1",
             "passRate": {"point": 0.5, "low": 0.3, "high": 0.7}, "failCount": 1,
             "createdAt": "2026-06-24", "langfuseRunUrl": "http://lf/r/run_1"}]
    app = create_app(tmp_path, runs_provider=lambda project: runs)
    return TestClient(app)

def test_list_runs(tmp_path):
    r = _client(tmp_path).get("/api/runs", params={"project": "bourbon"})
    assert r.status_code == 200
    assert r.json()["runs"][0]["runId"] == "run_1"

def test_get_regression_report(tmp_path):
    rep = compare([CaseScore("a", "fail")], [CaseScore("a", "pass")], validation_case_ids=set(),
                  baseline_judge_version="jv1", candidate_judge_version="jv1")
    write_regression_report(tmp_path, "bourbon", "run_1", rep,
                            baseline_harness="abc@m", candidate_harness="def@m",
                            judge_version="jv1")
    r = _client(tmp_path).get("/api/runs/run_1", params={"project": "bourbon"})
    assert r.status_code == 200
    assert r.json()["run"]["result"] in ("better", "no_change", "worse")

def test_missing_report_404(tmp_path):
    r = _client(tmp_path).get("/api/runs/nope", params={"project": "bourbon"})
    assert r.status_code == 404
```

- [ ] **Step 2:** run → fails. **Step 3: implement** `flywheel/api/read_api.py`

```python
"""Thin read-only API serving report JSON + Langfuse run summaries (UI §4, §8)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException

from flywheel.report import read_json


def create_app(root: Path, *, runs_provider: Callable[[str], list[dict]]) -> FastAPI:
    app = FastAPI(title="Flywheel Read API")
    root = Path(root)

    @app.get("/api/runs")
    def list_runs(project: str):
        return {"runs": runs_provider(project)}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, project: str):
        path = root / project / "reports" / "regression" / f"{run_id}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="regression report not found")
        return {"run": read_json(path)}

    @app.get("/api/judges/{judge_version}")
    def get_judge(judge_version: str, project: str):
        path = root / project / "reports" / "judge" / f"{judge_version}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="judge report not found")
        return {"judge": read_json(path)}

    return app
```

- [ ] **Step 4:** run → pass. **Step 5:** `pytest tests/api -q && ruff check api flywheel tests && mypy flywheel api`. **Step 6:** commit `feat(api): thin read-only API for runs and judge reports`.

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
  - `/runs` — `RunSummary[]` table: run id, harness, judge version, pass rate + CI bar, #fail, Langfuse link.
  - `/runs/:runId` — `RegressionReport`: baseline vs candidate harness, judge version (with the "same judge" note), pass-rate delta + CI, result badge (`better` green / `no_change` amber / `worse` red), per-label delta table, fixed / newly-broken lists with Langfuse trace deep links.
  - `/judges/:judgeVersion` — `JudgeReport`: F1 vs threshold, per-label precision/recall, confusion matrix.

- [ ] **Step 4: Component tests (Vitest + Testing Library)**
  - runs table renders rows + CI.
  - regression report renders all three result badges (parametrized).
  - judge report renders F1 vs threshold and confusion matrix.

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
- [ ] **Step 2: `flywheel/scripts/run_judge.py`** — for a dataset run: read each
  case's input/output, call `Judge.score_case` with `complete` wired to Anthropic,
  and write `pass/fail` + critique as a Langfuse score on the case's trace. Uses
  `Harness(git_sha, model)` for the run's harness id.
- [ ] **Step 3: `flywheel/scripts/run_regression.py`** — load baseline + candidate
  `CaseScore`s (with `failure_label` from the Langfuse score comment), the
  validation/regression split ids from the dataset, call `compare(...)`, build the
  `case_id → Langfuse trace URL` map, and call `write_regression_report(...)`.
- [ ] **Step 4: `runs_provider`** — implement the callable injected into the read
  API: query Langfuse for a project's dataset runs and their score summaries, and
  return `RunSummary[]` (UI §7). This is the only place that reads Langfuse for
  the list view.
- [ ] **Step 5: Smoke** — run one real dataset through `run_judge.py` →
  `run_regression.py`, open the UI `/runs`, and confirm a trace deep link resolves
  in Langfuse. Document the command in `flywheel/README.md`.

No commit gating here beyond "the smoke run works"; this is the seam between the
tested core and the real Bourbon/Langfuse environment.

---

## Self-review
- **Engine/UI coverage:** judge.py = Engine §6 judge running; validate.py =
  Engine §6 F1≥0.70 gate + UI §7 `JudgeReport`; report.py + read_api.py = UI §7
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
