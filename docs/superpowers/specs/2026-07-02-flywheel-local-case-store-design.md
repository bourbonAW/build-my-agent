# Flywheel Local Case Store: Owning Labels Instead of Langfuse Datasets

**Date**: 2026-07-02
**Status**: Draft
**Supersedes**: `2026-06-22-flywheel-engine-design.md` — specifically:
  - §2 reuse table rows "Datasets + dataset items" and "Scores / labels / annotation"
  - §5 step 4 ("Promote representative failures into a Langfuse Dataset")
  - §6 (60/20/20 `judge_train`/`judge_dev`/`judge_test` split, per-class support floor, macro-F1 gate as a pass/fail gate)
  - §7 disjointness assert ("regression set shares no cases with the entire judge case pool")
  - §10 design-decision row "Data / scores / datasets → Langfuse native"
**Unchanged**: OTel `gen_ai.*` trace attrs, Langfuse as the Tracing/Observability system of record, `flywheel/` local-file reports + thin read API + React UI, `identity.py`/`metrics.py`/`report.py`, McNemar exact-test mechanics in `regression.py` (the disjointness *precondition* for that test is what's removed, not the test itself).
**Related**: `2026-06-22-flywheel-engine-design.md`, `2026-06-22-flywheel-ui-ux-design.md`

---

## 0. Why this reverses a deliberate earlier decision

The original engine design chose "reuse Langfuse Datasets + Scores + native
annotation UI, don't build a private Annotation table" as a matter of
principle — avoid double bookkeeping against a system that already models
this. That principle is still generally right. What changed is direct,
hands-on use of the resulting workflow on this project:

- Promoting a trace creates a Langfuse **Dataset Item**, but labeling it
  requires hand-editing a raw JSON `metadata` blob in the Langfuse item detail
  page — there is no structured form for `splits` / `failure_label` /
  `human_label`, because those are flywheel-invented conventions layered onto
  a generic `metadata` field, not something Langfuse's UI understands.
- Langfuse's own **Human Annotation** feature (queues, score configs) is a
  real, polished labeling UI — but it writes **Scores** attached to a
  **trace**, not to the Dataset Item's `metadata`. Task 6's actual
  implementation reads `metadata.human_label`, never Scores. The two
  surfaces don't talk to each other: a human can complete an annotation
  queue and see 100% progress in Langfuse, while `validate_judge.py` still
  sees the item as unlabeled.
- The result in practice is two disconnected "labeling" surfaces
  (metadata-editing and Human Annotation) neither of which was actually
  designed for `flywheel`'s specific fields, plus a third, unrelated concept
  (Langfuse "Experiments" / dataset runs) that this codebase never uses at
  all. None of this is Langfuse being a bad product — it's a general-purpose
  eval platform's UI being fitted, awkwardly, onto one maintainer's
  narrow, already-decided label schema.

For a single-maintainer project with a small, fixed set of fields to capture
per case, owning that storage and UI directly is now less code and less
friction than continuing to bend Langfuse's dataset/annotation model to fit.
Langfuse's genuinely-standard piece — trace capture via OTel `gen_ai.*` — is
untouched and remains the system of record for raw execution history.

---

## 1. Goal

Replace "Langfuse Dataset Item + hand-edited metadata + disconnected Human
Annotation queue" with a single flywheel-owned local store and a purpose-built
labeling UI, while keeping everything upstream (trace capture) and downstream
(harness run, judge scoring, regression comparison, reports) working the same
way they do today — just reading from a different place.

```
real traces -> look at failures -> a few replayable cases
            -> score them (judge) -> change one thing
            -> re-run, compare pass rate, don't regress
```

This goal is identical to §1 of the original engine design. Only the "few
replayable cases" storage and labeling step changes.

---

## 2. What changes vs. the original design

| Concern | Original (2026-06-22) | New (this doc) |
|---|---|---|
| Dataset items | Langfuse Dataset | Local `cases.jsonl`, `case_id` = Langfuse `trace_id` |
| Label / critique | Langfuse Score + free-text comment | `Case.label` / `Case.critique` fields, edited in a new flywheel `/label` UI |
| Failure taxonomy | Free string in `flywheel/labels.md`, attached as a score comment | `Case.failure_category`, optional free string, same spirit — just stored on the case instead of a Langfuse score |
| Split policy | `judge_train`/`judge_dev`/`judge_test`/`regression`, mutually disjoint, enforced at load time | **Removed.** Every labeled case (`label` is `pass` or `fail`) can serve both as regression-comparison input and as judge-validation evidence. |
| Judge validation | 60/20/20 stratified split, per-class support floor (≥5 gold each class in a held-out 20%), macro-F1 ≥ 0.70 **gate** that blocks/unblocks the flow | **Continuous metric, not a gate**: judge-vs-human agreement (F1) computed over *all* currently-labeled `pass`/`fail` cases, recomputed and shown every time judging runs. No pass/fail threshold blocking the pipeline. |
| Regression disjointness | Assert regression set ∩ full judge pool = ∅ | **Removed** — there is only one pool now, so the assert is vacuous. |
| Regression significance test | Paired exact McNemar sign test on baseline vs candidate | **Unchanged.** This is about comparing two harness runs on the same cases, orthogonal to where labels live. |
| Human annotation UI | Langfuse annotation queues | New flywheel `/label` route (see §6) |

The tradeoff being made explicit: this drops the original design's
statistical rigor around judge validation (stratified sampling, held-out
test split, per-class support floor, hard F1 gate). That rigor exists to
prevent a judge from being implicitly overfit to the exact cases used to
grade it. At current scale (single-digit to low-double-digit case counts,
one maintainer doing all the labeling), a dedicated held-out split is more
process than the case volume can support, and a continuous full-pool
agreement metric is more actionable. If the case pool grows past roughly
~50 labeled cases per class, revisit reintroducing a held-out split — see
§10.

---

## 3. Architecture / data flow

```
Langfuse Tracing (unchanged — trace/observability system of record)
      | sample_traces.py (unchanged — heuristic tagging + stratified sample)
      v
sample_traces.json (unchanged — local candidate pool)
      | Promote (changed: no Langfuse Dataset/Item calls)
      v
cases.jsonl  <-- new flywheel-owned store, case_id = trace_id
      | /label UI (new)
      v
cases.jsonl updated in place (append-only, last record per case_id wins)
      | run_harness.py / run_judge.py / validate_judge.py / run_regression.py
      v
(changed: read cases.jsonl directly, no Langfuse get_dataset(), no split filtering)
```

Langfuse's role shrinks to exactly one thing: supplying raw traces that
`sample_traces.py` reads. Everything from "promote" onward is a local file
loop that never talks to Langfuse again. Langfuse Datasets and Human
Annotation are no longer used by this pipeline.

---

## 4. Data model: `Case`

Stored as append-only JSONL at
`~/.flywheel/<project>/state/cases.jsonl` (same directory convention as
`sample_traces.json` and `runs/*.jsonl`). Reading resolves duplicates by
`case_id`, last record wins — mirrors the crash-safety pattern already used
by `write_run_outputs` and the append-only annotation log pattern from the
`intelligent_customer` reference project.

```python
class Case(TypedDict):
    case_id: str                    # = trace_id from the source trace; globally unique
    input: str                      # copied from the trace at promote time
    frozen_output: str              # the agent's actual output on that trace, copied at
                                     # promote time — what the labeler judges, and the
                                     # fixed reference run_judge.py uses for few-shot examples
    trace_url: str                  # deep link back to Langfuse Tracing for full context
    expected_output: str            # filled during labeling; "" until labeled
    label: Literal["pass", "fail", "skip"] | None   # None until labeled
    critique: str                   # optional free text, encouraged (not required) when label == "fail"
    failure_category: str | None    # optional free string; no enforced taxonomy yet
    annotated_at: str               # ISO 8601; "" until first labeled
```

Fields deliberately cut during review and why:
- `annotated_by` — no multi-user concept needed yet (single maintainer).
- `source_trace_score` (the `sample_traces.py` heuristic tags) — never
  consumed downstream; `trace_url` gives direct access to full context if
  needed, better than a stale heuristic snapshot.
- `promoted_at` — JSONL append order already captures promotion order at
  this scale; not worth a dedicated field.
- `splits` — removed per §2.

---

## 5. Backend changes

### 5.1 Promote rewrite (`api/pipeline.py`)

`promote_cases()` drops the `create_dataset()` / `create_dataset_item()` /
`_write_langfuse_dataset()` calls entirely. It instead:
1. Loads the selected entries from `sample_traces.json`.
2. For each, if `case_id` (the trace id) already exists in `cases.jsonl`,
   skip it (never overwrite an existing label).
3. Appends a new `Case` record: `input`/`frozen_output` copied from the
   trace's own `input`/`output` fields (already captured by
   `sample_traces.py`'s `_as_dict()`), `expected_output=""`, `label=None`.
4. Returns a summary: `{promoted: N, skipped: M}`.

`dataset.name`/`total_cases` bookkeeping in `pipeline_state.json` is repointed
at `cases.jsonl`'s count instead of a Langfuse dataset name.

### 5.2 New case endpoints

- `GET /api/pipeline/cases` — full list of cases (labeled and unlabeled),
  used by both the `/label` UI and `DatasetPanel`'s progress display.
- `POST /api/pipeline/cases/{case_id}/label` — body: `expected_output`,
  `label`, `critique`, `failure_category`. Appends a new record for that
  `case_id` (never mutates in place — same append-only, last-wins pattern),
  guarded by the same `threading.Lock`-protected write helper introduced for
  `pipeline_state.py`'s `mutate()` in this session's earlier fix pass, to
  keep concurrent label submissions from corrupting the file.

### 5.3 Script layer (`scripts/common.py` + the four run scripts)

- `DatasetItem` dataclass: drop `splits`, `failure_label`, `human_label`;
  add fields matching `Case` (`label`, `critique`, `failure_category`).
- `load_dataset_items()`: drop the Langfuse `get_dataset()` branch; only
  reads local JSON. Rename the `--dataset-json` CLI flag to `--cases-path`
  across all four scripts (`run_harness.py`, `run_judge.py`,
  `validate_judge.py`, `run_regression.py`) to stop implying a Langfuse
  "dataset" is involved.
- `ensure_disjoint_splits()` (`scripts/common.py`) and
  `check_splits_disjoint()` (`flywheel/regression.py`): **delete**, along
  with their call sites in `run_harness.py` and `run_regression.py`.
- `require_failure_labels()`: **delete** (failure_category is now optional
  everywhere, not just non-regression items).
- `run_harness.py`: runs every case where `label != "skip"` (previously:
  every case in the `regression` split).
- `validate_judge.py`: rewritten from a pass/fail **gate** into a
  **continuous report** — computes judge-vs-human F1 (and per-label
  precision/recall/confusion matrix, same math as today) over every case
  with `label in ("pass", "fail")`, no held-out split, no support-floor
  check, no `passes: bool` gate field blocking downstream steps.
- `run_judge.py`: judge few-shot examples draw from any labeled case,
  using `Case.frozen_output` (§4) as the fixed output being graded and
  `Case.label` as the gold verdict — no schema gap; `frozen_output` is
  populated automatically at promote time (§5.1).

---

## 6. Frontend: `/label` route

New route in the existing flywheel React app (`flywheel/ui/src/App.tsx`),
modeled on `intelligent_customer/eval/templates/annotate.html`'s interaction
pattern, reimplemented as React components rather than ported directly.

```
+---------+------------------------------------------+
| strip   |  detail panel                             |
| case1 o |  Input: ...                               |
| case2 v |  Actual output (frozen_output): ...        |
| case3 v |  [ View original trace -> ]                |
| case4 o |  Expected output: [textarea]               |
|  ...    |  ( Pass )  ( Fail )  ( Skip )               |
|         |  Critique (optional): [textarea]           |
|         |  Failure category (optional): [text input] |
|         |  [ Save (Enter) ]  [<- prev]  [next ->]     |
+---------+------------------------------------------+
```

The labeler judges `frozen_output` (what the agent actually said) against
their own `expected_output` to decide Pass/Fail/Skip — `frozen_output` is
read-only, always shown, never edited here.

- Left strip: `o` unlabeled / `v` labeled, click to jump; default lands on
  the first unlabeled case.
- Keyboard: `←`/`→` navigate, `Enter` saves and auto-advances to the next
  unlabeled case (mirrors `annotate.html`'s flow, optimized for rapid
  sequential labeling of many cases).
- Save calls `POST /api/pipeline/cases/{case_id}/label` via a
  `useMutation`, optimistically updates the strip's checkmark state.
- `DatasetPanel`'s existing `LabelStatusRow` ("Human labels x/y") switches
  from querying Langfuse dataset-item scores to `GET /api/pipeline/cases`,
  computing `labeled = count(label != null)` client-side. The "Label in
  Langfuse ↗" external link becomes an in-app `<Link to="/label">`.
- Top nav (`Shell` component) gains a third entry: `Control | Label |
  History`.

---

## 7. Error handling

- Promoting an already-existing `case_id`: skip, report count skipped —
  never silently overwrite an existing label.
- `cases.jsonl` read: skip malformed individual lines with a warning
  (matches `intelligent_customer/eval/annotate.py`'s `load_jsonl`), rather
  than failing the whole load on one corrupt line from a killed writer.
- Concurrent writes: lock-protected append (see §5.2).
- Zero labeled cases, or all cases `skip`/unlabeled, when `run_harness.py`
  or `validate_judge.py` run: raise a clear `SystemExit` message (same style
  as the existing `"dataset has no regression items"` check), not a bare
  exception from deeper in the script.

---

## 8. Testing

- Backend: unit tests for `Case` parsing/serialization, promote dedup logic,
  and `cases.jsonl` append/last-wins read behavior, following the existing
  `flywheel/tests` conventions.
- Script layer: remove the now-dead split-disjointness tests; add coverage
  for the new `label`/`critique`/`failure_category` fields and the
  `--cases-path` rename.
- Frontend: no automated test infra exists in this repo currently for the
  React app; verify the `/label` flow (promote → label → save →
  run baseline) manually via the `/run` skill, as done for the rest of this
  session's UI work.

---

## 9. Existing data / migration

The 5 items already promoted into the Langfuse `bourbon-evals` dataset
(including one with a manually-edited `expected_output`) are **not**
migrated. They are abandoned; a fresh sample → promote cycle populates
`cases.jsonl` from scratch once this ships. The Langfuse dataset itself is
left as-is (not deleted) — it simply stops being written to or read from.

---

## 10. Deferred (not rejected — revisit with evidence)

| Item | Revisit when |
|---|---|
| Held-out judge-validation split + per-class support floor + hard F1 gate | Labeled pool grows past roughly ~50 cases per class and a single maintainer is no longer hand-verifying every judge disagreement directly |
| `failure_category` enforced taxonomy (required field, fixed enum) | A stable set of categories has organically emerged from free-text use |
| Multi-user `annotated_by` | More than one person labels cases |
| Re-syncing labels back into Langfuse (e.g. as Scores, for cross-tool visibility) | Someone outside this single-maintainer loop needs to see labels inside Langfuse itself |
