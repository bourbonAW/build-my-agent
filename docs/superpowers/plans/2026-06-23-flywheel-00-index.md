# Flywheel Implementation Plan — Index (Lean Revision 2026-06-24)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development
> for the Python core; the frontend uses Vitest + Testing Library. Steps use
> checkbox (`- [ ]`) syntax.

> **⚠️ This index was rewritten for the lean MVP.** The prior version mandated a
> control plane (State Store, 5 lifecycle enums, Score Bridge, ~45 endpoints,
> taxonomy registry, redaction pipeline, holdout ledger) and pointed at sub-plans
> 03–08. **All of that is superseded.** See `specs/2026-06-22-flywheel-engine-design.md`
> §0 for why ~85% was cut. Sub-plans **03–08 were deleted** — their surviving
> content is folded into plans 01/02 and the rest is deferred per engine spec §8.
> The table below records what each was (git history preserves the originals); do
> not recreate or implement them. The Chinese `-zh` variants of these docs were
> intentionally left untouched and still describe the old design — do not
> implement from them either.

**Goal:** Make Bourbon measurably better from its own traces with the smallest
machinery that closes the loop: real traces → look at failures → a few replayable
cases → score them (judge) → change one thing → re-run, compare, don't regress.

**Architecture:** A small `flywheel/` Python package (pure-logic core + thin
read-only API) plus a real React+Vite frontend. **Langfuse** is the evidence
store and owns traces, datasets, scores, and annotation (not rebuilt here).
**OpenTelemetry `gen_ai.*`** (already emitted by Bourbon) is the trace convention;
the only new attrs are `eval.case_id` and `eval.run_id`.

**Tech Stack:** Python 3.13, pydantic v2, FastAPI (read-only), pytest; React +
TypeScript + Vite, React Router, TanStack Query/Table, Recharts, Vitest +
Testing Library, one Playwright happy-path.

**Parent specs:**
- `docs/superpowers/specs/2026-06-22-flywheel-engine-design.md` (lean)
- `docs/superpowers/specs/2026-06-22-flywheel-ui-ux-design.md` (lean)

---

## Global Constraints

Apply to every task below.

- **Reuse standards, don't reinvent.** Execution-time trace attrs = OTel
  `gen_ai.*` + `eval.case_id`/`eval.run_id`. Datasets, scores, annotation, trace
  browsing = Langfuse native. No private `flywheel.*` convention, no State Store
  re-modeling of Langfuse objects.
- **Four identity concepts only:** `case_id`, `run_id`, `label` (pass/fail), and
  `trace_id`. Plus a minimal harness id `git_sha@model` and a plain
  `judge_version` string. No 8-part fingerprint, no lifecycle enums.
- **Two surviving correctness gates** (asserts, not state machines):
  - *same-judge:* baseline and candidate must be scored by one `judge_version`;
    `compare()` raises otherwise.
  - *disjointness:* the regression split must not overlap the judge-validation
    split; `compare()` raises otherwise.
- **Judge is the one validated asset.** F1 ≥ 0.70 (recomputed by re-running
  `validate.py`), not a 6-state lifecycle.
- **Regression result is three-valued:** `better | no_change | worse`, decided by
  the Wilson CI of the pass-rate delta (noise band). A proposal is a git PR; a
  baseline is `main`; "publish" is merge.
- **No control plane.** No auth/roles, no audit log, no idempotency layer, no
  Score Bridge. The read API is read-only; the browser never receives Langfuse
  write credentials.

---

## Repo Conventions

```
flywheel/
├── pyproject.toml          # package "flywheel" + sibling package "api"
├── flywheel/               # core library (plan 01) + judge/validate/report (plan 02)
│   ├── identity.py metrics.py regression.py
│   └── judge.py validate.py report.py
├── api/                    # thin read-only FastAPI (plan 02)
├── scripts/                # Bourbon/Langfuse glue: run_judge.py, run_regression.py (plan 02 Task 6)
├── ui/                     # React + Vite frontend (plan 02 Task 5)
├── labels.md               # flat editable failure-label list (plan 01)
└── tests/                  # pytest tree
```

**Conventions (match Bourbon):** synchronous code, no asyncio; `@dataclass` for
domain objects, pydantic only where validation helps; TDD for the pure-logic
core; report JSON is camelCase end-to-end (UI §7) so the read API serves it
verbatim.

**Test commands:**
```bash
cd flywheel
uv pip install -e ".[dev]"
pytest
ruff check flywheel api tests
mypy flywheel api
cd ui && npm install && npm run test -- --run && npx playwright test
```

---

## Sub-Plan DAG (8 plans → 2)

```
00-index (this doc)
   │
   ▼
01-sdk (core library: identity, metrics, regression)
   │
   ▼
02-control-plane (judge, validate, report, read API, frontend, Bourbon glue)
```

| Plan | File | Produces | Spec coverage |
|---|---|---|---|
| 01 | `2026-06-23-flywheel-01-sdk.md` | repo scaffold, `identity.py` (Harness, Label), `metrics.py` (P/R/F1, Wilson CI), `regression.py` (3-value compare + gates), `labels.md` | Engine §4, §5, §7 |
| 02 | `2026-06-23-flywheel-02-control-plane.md` | `judge.py`, `validate.py`, `report.py`, thin read-only API, React frontend, Bourbon integration glue | Engine §6, §9; UI spec |

> The file names still say "01-sdk" / "02-control-plane" for git continuity, but
> their **content is the lean rewrite** — not an SDK and not a control plane.

### Deleted sub-plans (do not recreate)

These files were **deleted** in the lean revision (recoverable from git history).
Each row records what the plan was and where its surviving scope went.

| File (deleted) | Was | Disposition |
|---|---|---|
| `2026-06-23-flywheel-03-redaction.md` | Redaction pipeline | Deferred (Engine §8); single trusted maintainer needs no redaction. |
| `2026-06-23-flywheel-04-data-analysis.md` | Sampler/coder/taxonomy registry/dataset splits | Data + labeling live in Langfuse; labels are a flat `labels.md`. |
| `2026-06-23-flywheel-05-judge.md` | JudgeVersion lifecycle + drift sentinel | Replaced by `validate.py` (F1 ≥ 0.70). |
| `2026-06-23-flywheel-06-engine.md` | Analyzer/proposer/handoff | Proposals are git PRs (Engine §8 add-back trigger). |
| `2026-06-23-flywheel-07-regression.md` | Holdout ledger, Bonferroni/FDR, publish/rollback states | `regression.py` 3-value result + Wilson noise band. |
| `2026-06-23-flywheel-08-ui.md` | Full 13-route control UI | UI is plan 02 Task 5 (3 routes). |

---

## API Surface (45 → 3, read-only)

| Endpoint | Method | Owner |
|---|---|---|
| `/api/runs` | GET | 02 |
| `/api/runs/{run_id}` | GET | 02 |
| `/api/judges/{judge_version}` | GET | 02 |

Everything else the old index listed (scores, annotations, datasets, taxonomy,
trace-pools, issues, proposals, regressions, baselines, redaction) is either a
Langfuse-native operation or a deleted concept.

---

## Execution Order

Plan 01 (pure logic, TDD) → Plan 02 (judge/validate/report TDD, then read API,
then frontend, then Bourbon glue in Task 6). Within each plan, tasks are strictly
ordered. The trace→case link that justifies the repo is built in **plan 02
Task 6** (Bourbon span attrs + `run_judge.py` + `run_regression.py` +
`runs_provider`), not in the pure-logic tasks.
