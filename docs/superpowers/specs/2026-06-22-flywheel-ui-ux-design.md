# Flywheel UI/UX Design Spec
**Date**: 2026-06-22 (Lean Revision 2026-06-24)
**Status**: Lean MVP Draft — supersedes the prior "Revised Draft"
**Parent Spec**: `docs/superpowers/specs/2026-06-22-flywheel-engine-design.md`

---

## 0. Why this was rewritten

The prior draft mirrored the over-built engine: 13 MVP routes, three state
machines (11-state `RunState`, 7-state `JudgeState`, 18-state `ProposalState`
plus `RegressionStatus`/`RegressionOutcome`), 30+ API endpoints, a 4-role
authorization matrix, and a 9-participant interaction sequence. Most of those
pages existed only to render lifecycle states that the lean engine deleted.

**This is still a real, standalone frontend project** (owner's call) — not a set
of markdown reports. But its surface is slimmed to match the lean engine: it
renders the four-id model and the three-value regression result, deep-links into
Langfuse for anything Langfuse already does well (trace browsing, annotation,
dataset editing), and talks to a **thin read-only API** instead of a State Store
control plane.

---

## 1. Goal

A quiet internal web app that answers three questions fast:

1. *Which eval runs exist and how did they score?*
2. *Can this candidate harness become the new baseline?* (the regression report)
3. *Is the judge trustworthy for this task?* (the validation report)

Everything else — browsing a raw trace, editing a dataset item, attaching a
human annotation — is a **deep link into Langfuse**, not a cloned page.

---

## 2. Product principles

1. **Evidence before decision**: the regression view shows pass-rate delta with
   confidence interval, fixed vs newly-broken cases, and trace links.
2. **Don't clone Langfuse**: reuse it for traces, annotation, and dataset
   editing.
3. **Noise is a result**: `no_change` is rendered distinctly from `better` /
   `worse` — never dressed up as a win.
4. **No hidden automation**: judge-generated labels show the `judge_version` and
   confidence.

---

## 3. Frontend stack (kept — it's standard)

| Layer | Choice | Reason |
|---|---|---|
| Runtime | React + TypeScript + Vite | Standard, fast local iteration. |
| Routing | React Router | ~3 routes. |
| Server state | TanStack Query | Cache reads, handle loading/error. |
| Tables | TanStack Table | Dense runs / per-label delta tables. |
| UI primitives | shadcn/ui (or local equivalents) | Restrained internal-tool components. |
| Charts | Recharts or small SVG | Confidence-interval and delta bars. |
| Testing | Vitest + Testing Library; one Playwright happy-path | Component tests + a single end-to-end smoke. |

This is the one place we keep a full stack, because the owner wants a real
frontend project. The cut is in **surface area**, not technology.

---

## 4. Backend boundary

```
Browser UI  ->  Flywheel read API (thin FastAPI, read-only)
                     |-> reads regression / judge report JSON written by the scripts
                     |-> reads run + score summaries from Langfuse
                     |-> returns Langfuse deep-link URLs (browser never gets write creds)
```

The browser never receives Langfuse write credentials. Writes (scores,
annotations, dataset edits) happen in Langfuse's own UI or via the scripts — not
through this app. The app is a **reader and decision surface**, so there is no
mutation/auth/audit layer in MVP.

---

## 5. Routes (13 → 3 + 1)

| Route | Purpose |
|---|---|
| `/runs` | Eval runs: run id, harness (`git_sha@model`), judge version, pass rate + CI, link to Langfuse run. |
| `/runs/:runId` | One regression report: baseline vs candidate, pass-rate delta + CI, per-label delta, fixed / newly-broken cases, Langfuse trace deep links, the three-value result. |
| `/judges/:judgeVersion` | Judge validation report: overall F1, per-label precision/recall, confusion matrix. |
| `/` | A minimal index linking the above + a deep link to Langfuse for traces/datasets/annotation. |

Deleted routes and where their job went: `/data/*`, `/datasets`, `/taxonomy`,
`/annotations` → **Langfuse**. `/issues`, `/proposals`, `/handoffs`,
`/baselines`, `/settings`, `/costs` → **deleted** (they rendered the removed
state machines; a "proposal" is a git PR, a "baseline" is `main`).

---

## 6. Page designs

### `/runs` — runs list

Columns: run id · harness (`git_sha@model`) · judge version · pass rate **with
confidence interval** · #fail · created at · link to Langfuse run.

`judge F1` shows only when the run's judge has a validation report; otherwise
`not available` (never a misleading `0`).

### `/runs/:runId` — regression report (the core page)

Primary question: *"Can this candidate become the new baseline?"*

Show:
- baseline vs candidate harness ids; the single `judge_version` used for both
  (with a visible assert that they match)
- pass-rate delta with Wilson confidence interval
- result badge: `better` (green) / `no_change` (amber) / `worse` (red)
- per-label delta table
- fixed failures and newly-broken failures, each linking to its Langfuse trace
- a disjointness note: regression set ∩ judge-validation set = ∅

No publish/rollback/defer/rebase buttons. The decision is "merge the PR or not,"
taken in git. The page may show the candidate's branch/PR URL if provided.

### `/judges/:judgeVersion` — judge validation report

Primary question: *"Can this judge be trusted to gate changes?"*

Show: model + prompt version · overall F1 vs the 0.70 threshold · per-label
precision/recall · confusion matrix · validation set size.

---

## 7. Core data shapes (lean)

```ts
type RegressionResult = "better" | "no_change" | "worse";

type RunSummary = {
  runId: string;
  harness: string;          // "abc1234@claude-opus-4-8"
  judgeVersion: string | null;
  judgeF1: number | null;   // from the judge's validation report; null → "not available" (§6)
  passRate: { point: number; low: number; high: number };  // Wilson CI
  failCount: number;
  createdAt: string;
  langfuseRunUrl: string;
};

type LabelDelta = { label: string; baseline: number; candidate: number };

type RegressionReport = {
  runId: string;
  baselineHarness: string;
  candidateHarness: string;
  judgeVersion: string;     // same for both, asserted server-side
  passRateDelta: { point: number; low: number; high: number };
  result: RegressionResult;
  perLabel: LabelDelta[];
  fixed: { caseId: string; traceUrl: string }[];
  newlyBroken: { caseId: string; traceUrl: string }[];
  candidatePrUrl?: string;
};

type JudgeReport = {
  judgeVersion: string;
  model: string;
  promptVersion: string;
  f1: number;
  threshold: number;        // 0.70
  perLabel: { label: string; precision: number; recall: number }[];
  confusion: { tp: number; fp: number; fn: number; tn: number };
  validationSetSize: number;
};
```

No `RunState`, `JudgeState`, `ProposalState`, `RegressionStatus`,
`RegressionOutcome`, `Baseline`, or `TaxonomyLabel` types — those state machines
are gone.

---

## 8. Read API surface (30+ → 3)

| Endpoint | Purpose |
|---|---|
| `GET /api/runs` | `RunSummary[]` for the runs list. |
| `GET /api/runs/{run_id}` | `RegressionReport` for one run. |
| `GET /api/judges/{judge_version}` | `JudgeReport`. |

All read-only. The thin API reads report JSON produced by the engine scripts and
run/score summaries from Langfuse. No mutations, no idempotency keys, no roles,
no audit log in MVP.

---

## 9. Empty / error states

| State | UI behavior |
|---|---|
| No runs yet | Show how to run the eval script; link to Langfuse to sample traces. |
| Judge not validated | Run badge shows `judge: not validated`; link to `/judges/:v`. |
| Trace missing in Langfuse | Keep the case row, mark trace `unavailable`, keep the link. |
| Delta inside noise band | Render `no_change` (amber); do not imply a win. |
| Report not generated yet | Show "run regression.py to produce this report." |

---

## 10. Visual direction

Quiet internal tool: neutral background, high-contrast text, compact tables,
split panes for "evidence summary | decision context." Semantic colors: green =
better/validated, amber = no_change/review, red = worse/failed. Optimize for
scan → compare → decide → next. No hero, no gradients, no oversized panels.

---

## 11. Frontend verification

- Component tests: runs table, regression report (all three result badges),
  judge report.
- One Playwright happy path: open `/runs` → open a run → see the regression
  result and a working Langfuse deep link.
- A read-API contract test for the three GET schemas.

---

## 12. Non-goals

- Replacing Langfuse trace browsing, annotation, or dataset editing.
- Any mutation / publish / rollback UI (those are git actions).
- Roles, auth matrix, audit log, multi-tenant admin.
- BI dashboards, cost analytics, mobile-first annotation.
