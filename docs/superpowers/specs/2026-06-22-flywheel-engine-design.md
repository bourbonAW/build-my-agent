# Flywheel Engine Design Spec
**Date**: 2026-06-22 (Lean Revision 2026-06-24)
**Status**: Lean MVP Draft — supersedes the prior "Revised Draft"
**Related**: `docs/superpowers/specs/2026-06-22-flywheel-ui-ux-design.md`

---

## 0. Why this was rewritten

The prior draft was a self-hosted LangSmith clone: ~20 identity ids, four
overlapping state machines (18-state `ProposalState`, 6-state
`RegressionStatus`, 9-value `RegressionOutcome`, 6-state `JudgeVersion`,
3-state `Baseline`), a versioned taxonomy registry with immutable migration
maps, a mandatory redaction pipeline, holdout ledgers with Bonferroni/FDR
multiple-comparison correction, candidate drift recheck, production drift
sentinels, baseline rebase/conflict detection, and a private `flywheel.*` OTel
semantic convention.

For a single-maintainer agent (Bourbon) that does not yet have a stable judge
or 100 curated cases, that is a platform-sized concept tax paid up front. The
`flywheel.*` namespace is **bespoke and will never be an industry standard**;
the two things that *are* close to standard — OpenTelemetry `gen_ai.*` and
Langfuse's native dataset/score/annotation model — were being re-implemented
inside a private State Store, producing a double bookkeeping system.

This revision cuts ~85% of those mechanics. The discipline that survives is the
irreducible core of an eval flywheel (per the `llm-eval` skill): **error
analysis** (look at real failures) and **judge validation** (prove the scorer is
trustworthy). Everything deferred is listed in §8 so the cut is honest and
reversible.

---

## 1. Goal

Make Bourbon measurably better over time from its own traces, with the smallest
machinery that still closes the loop:

```
real traces  ->  look at failures  ->  a few replayable cases
             ->  score them (judge)  ->  change one thing
             ->  re-run, compare pass rate, don't regress
```

That is the whole flywheel. No proposal lifecycle, no baseline generations, no
taxonomy migrations. A "proposal" is a git branch / PR. A "baseline" is the main
branch. "Publish" is merge.

---

## 2. Reuse standards, don't reinvent them

| Concern | Use this (close to standard) | Do **not** build |
|---|---|---|
| Execution-time trace attrs | OpenTelemetry `gen_ai.*` (already emitted by Bourbon observability) | a private `flywheel.*` convention |
| Traces / spans storage + UI | Langfuse (self-hosted) | a trace explorer |
| Datasets + dataset items | Langfuse Datasets | a `DatasetCase` State Store table |
| Scores / labels / annotation | Langfuse Scores + native annotation UI | an `Annotation` table + Score Bridge mirror |
| Dataset run comparison | Langfuse Dataset Runs | a regression State Store |

The flywheel adds **exactly one** thing OTel/Langfuse don't give for free:
linking a trace to a replayable eval case and a harness identity, plus a small
amount of judge/regression math. That is the entire reason this repo exists.

---

## 3. Architecture (lean)

```
Bourbon agent runtime (OTel, gen_ai.* already wired)
      |  OTLP traces
      v
Langfuse (self-hosted): traces, datasets, dataset items, scores, annotation UI
      ^                                   |
      | scores/dataset writes             | trace + score reads
      |                                   v
flywheel/  (a small Python package + scripts)
  - identity.py   : case_id, run_id, label, minimal harness fingerprint, judge_version
  - metrics.py    : precision / recall / F1 / Wilson CI
  - judge.py      : run an LLM judge over a dataset, write scores to Langfuse
  - validate.py   : 60/20/20 judge validation report (macro-F1 ≥ 0.70 + per-class support)
  - regression.py : baseline vs candidate -> better | no_change | worse
  - report.py     : emit markdown / JSON report (consumed by the UI read API)
      |
      v
flywheel read API (thin FastAPI, read-only) -> Flywheel UI (see ui spec)
```

No State Store, no auth/role matrix, no audit log, no Score Bridge, no engine
job orchestrator. Scripts run locally / in CI; results are files + Langfuse
scores; the UI reads them.

---

## 4. Minimal identity contract

Four concepts carry the whole loop. Two small extras get added back when the
second judge or second harness appears.

| Field | Where it lives | Meaning |
|---|---|---|
| `case_id` | Langfuse dataset item id; mirrored as `eval.case_id` span attr | Which replayable case. |
| `run_id` | Langfuse dataset run name; span attr `eval.run_id` | Which eval run / which harness version. |
| `label` | Langfuse score + free-text critique | The verdict on one case attempt. A **human** annotation is `pass`/`fail` (gold, binary). A **judge** verdict is persisted as a categorical score and may also be `uncertain` (the judge abstained); `skip` marks a case not run. `uncertain`/`skip` are non-successes, never a pass. |
| `trace_id` | W3C trace id (OTel) | Pointer to the evidence. |

The only new OTel attributes are `eval.case_id` and `eval.run_id`. Everything
else uses `gen_ai.*`. That is the complete semantic surface — two strings.

**Minimal harness fingerprint** (added back from the deleted 8-part composite):

```python
@dataclass(frozen=True)
class Harness:
    git_sha: str        # which code
    model: str          # which model snapshot, e.g. "claude-opus-4-8"

    def id(self) -> str:  # "abc1234@claude-opus-4-8"
        return f"{self.git_sha[:7]}@{self.model}"
```

**Judge version**: a plain string, e.g. `"judge-v2"`. Not a 6-state lifecycle —
just an identifier so two runs scored by different judge prompts are not
compared. (Same-judge comparison is enforced in §7 as a one-line assert.)

---

## 5. Data & error analysis (the part you must not skip)

This is the irreplaceable half of the flywheel. It stays manual and lives in
Langfuse.

1. **Sample** ~20–50 real traces, biased toward failures, risky tool/sandbox
   paths, and long multi-turn sessions. A short script queries Langfuse.
2. **Open-code** them in Langfuse annotation: attach a `pass`/`fail` score and a
   one-line critique ("wrong tool arg shape", "forgot prior user constraint").
3. **Cluster** the critiques by hand into a short flat list of failure labels —
   a markdown file in `flywheel/labels.md`, edited freely. No versioned
   registry, no migration maps. A label is just a string used in a Langfuse
   score comment.
4. **Promote** representative failures into a **Langfuse Dataset** as items.
   A dataset item needs only: `input`, `expected` / acceptance note,
   `failure_label`.

Split policy is intentionally minimal: keep a **judge-validation set** and a
**regression set** disjoint (don't validate the judge on the same cases you use
to gate a change). That single disjointness rule replaces the four-way
`train/dev/locked_test/regression_holdout` partition. Enforced as a set
intersection check in `regression.py`.

---

## 6. The judge: build it, then prove it

The judge is the one asset worth real rigor (per `llm-eval` stages 4–5).

- `judge.py` runs an LLM judge over a dataset run and writes `pass`/`fail`/`uncertain`
  scores back to Langfuse (the judge may abstain — `uncertain` is persisted as
  itself, never coerced to a pass/fail). Few-shot labeled examples carry the
  signal; the system prompt stays neutral.
- The human-labeled cases are partitioned **60/20/20** as a data-prep step:
  `train` supplies the judge's few-shot examples, `dev` is used while iterating
  the prompt, and the disjoint `test` split is the held-out validation set.
- `validate.py` scores the judge **on that held-out validation split only** (never
  the few-shot/train cases — that would leak) and emits a report. The gate is
  **macro-F1 ≥ 0.70** — the mean of the `pass`-class and `fail`-class F1, *not* the
  `fail`-class F1 alone. `fail` is the class we care about (the judge's job is to
  catch failures), but with the failure-biased sampling in §5 a degenerate
  always-`fail` judge would score a high *fail-only* F1 (perfect recall, base-rate
  precision) while being unable to recognize success; averaging both classes' F1
  forces the judge to get passes right too, so an always-`fail` (or always-`pass`)
  judge fails the gate. An `uncertain` verdict is an abstention — never a true
  positive for either class — so a hedging judge cannot pass either. The gate also
  requires a **per-class support floor (~5 gold cases of *each* of `pass` and
  `fail`)** in the held-out split: F1 over a handful of cases swings by >0.2 per
  single case, and a one-class split lets a degenerate judge through. Sample enough
  of **both** outcomes (§5) that the 20% `test` split clears the floor on each
  class. The report also carries per-label precision/recall and a confusion matrix.
  Below threshold (or below either support floor) → refine prompt/examples or label
  more cases, and re-run.

That's the lifecycle. No `draft → calibrating → locked_test → validated →
validated_limited → recheck_required` machine. A judge is "good enough to gate"
(F1 met) or not. The decision is recomputed by re-running `validate.py`, not
tracked as persistent state.

---

## 7. Regression: three outcomes, no state machine

`regression.py` compares a candidate harness against the baseline on the
regression set:

```python
RegressionResult = Literal["better", "no_change", "worse"]
```

Mechanics that survived because they are correctness, not ceremony:

- **Same-judge comparison**: assert baseline and candidate scored with the same
  `judge_version`; otherwise refuse and ask for a re-score. (One assert,
  replacing `judge_migration_required` / `blocked_on_judge_migration`.)
- **Disjointness**: assert the regression set shares no cases with the
  judge-validation set. (One assert, replacing the holdout ledger.)
- **Noise band**: baseline and candidate are scored on the **same** regression
  cases (a paired design), so report the pass-rate delta with a **paired
  (McNemar) Wilson confidence interval** computed from the discordant pairs
  (fixed vs newly-broken) — an unpaired difference of two independent Wilson
  intervals would ignore the pairing and hide real one-directional changes. If
  the interval crosses zero, the result is `no_change`, not a win. (Replaces
  `no_significant_change` as a first-class lifecycle state.)
- **Repeats**: for nondeterministic cases, sample ≥3× when budget allows.

Output is a report (markdown + JSON): pass-rate delta + CI, per-label delta,
which cases got fixed, which newly broke, and deep links to the Langfuse traces.
The human reads it and decides merge / iterate / drop. That decision is a git
action, not a database transition.

---

## 8. Deliberately deferred (the honest add-back list)

These are not rejected forever — they are removed until there is evidence they
are needed. Each maps to a deleted piece of the old design.

| Deferred | Trigger to add it back |
|---|---|
| Bonferroni/FDR multiple-comparison correction | After repeatedly gating many candidates on the same regression set. |
| Production drift sentinel for the judge | After the judge has been live long enough for traffic to drift. |
| Versioned taxonomy + migration maps | When failure labels stabilize and are shared across people/quarters. |
| Composite 8-part fingerprint | When `git_sha + model` can't distinguish two behaviors that actually differ. |
| Redaction pipeline | If traces are exposed beyond the single trusted maintainer. |
| Baseline generations / rebase / conflict detection | When multiple candidates are genuinely in flight concurrently. |
| Engine auto-clustering & auto-proposals | After enough labeled data to make clustering pay off. |

If, over time, **less than ~10% of this list gets pulled back in, the cut was
not aggressive enough** and more should be deleted.

---

## 9. Repository scope

| Repo | Change |
|---|---|
| `bourbon` | Already emits OTel `gen_ai.*`. Add two attrs (`eval.case_id`, `eval.run_id`) on eval runs. Expose `git_sha` + `model` for the fingerprint. **This wiring is not yet built** — it is plan-02 Task 6 (Bourbon integration glue), tracked explicitly so it is not mistaken for done. |
| `flywheel` | New, small: `identity.py`, `metrics.py`, `judge.py`, `validate.py`, `regression.py`, `report.py`, a thin read API, and the UI frontend project. No `sdk/` HTTP client, no `api/` control plane, no State Store. |

The trace→case link that justifies this repo is built by plan-02 Task 6 (span
attrs + `run_harness.py` + `run_judge.py` + `run_regression.py` + `runs_provider`),
not by the pure-logic tasks. Per-label deltas (§7) come from `CaseScore.failure_label`, a
free string drawn from `labels.md` / the Langfuse score comment.

---

## 10. Design decisions

| Decision | Choice | Reason |
|---|---|---|
| Identity surface | `case_id`, `run_id`, `label`, `trace_id` (+ `git_sha@model`, `judge_version`) | Four concepts close the loop; the rest was noise. |
| Trace attrs | `gen_ai.*` + two `eval.*` strings | Reuse the real standard, don't invent `flywheel.*`. |
| Data / scores / datasets | Langfuse native | It already models these; mirroring them is double bookkeeping. |
| Failure taxonomy | A flat editable markdown list | Versioned registries are for stable cross-team contracts. |
| Judge lifecycle | Re-run `validate.py`; macro-F1 ≥ 0.70 (+ per-class support) | "Trustworthy" is recomputed, not a persisted 6-state machine. |
| Regression result | `better` / `no_change` / `worse` + Wilson CI | A proposal is a PR; its outcome is a merge decision. |
| Control plane | None (scripts + thin read API) | No users, no roles, no concurrency to govern yet. |
| UI | A real frontend (per owner), lean surface | See ui spec — kept as a project, slimmed to ~3 routes. |
