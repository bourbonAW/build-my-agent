# Flywheel Engine Design Spec
**Date**: 2026-06-22
**Status**: Revised Draft
**Related**: `docs/superpowers/specs/2026-06-22-flywheel-ui-ux-design.md`

---

## 1. Goal

Build a self-hosted LangSmith Engine equivalent for Bourbon: a reusable **eval flywheel** that turns real traces into datasets, calibrated judges, failure issues, human-reviewed improvement proposals, regression decisions, and better harnesses.

The flywheel is not a generic dashboard. It is a closed-loop improvement system:

```
trace pool
  -> sampling
  -> error analysis
  -> dataset construction
  -> judge calibration
  -> run scoring
  -> failure analysis
  -> proposal review
  -> implementation handoff
  -> regression with human/statistical gates
  -> new harness baseline
```

The revised design treats dataset construction, judge calibration, redaction, and regression validity as core engine mechanics. Langfuse remains the evidence store for traces and scores; Flywheel owns the workflow state, data curation process, improvement proposals, and publish/rollback decisions.

---

## 2. Review-Driven Changes

This revision incorporates the adversarial review rounds.

| Finding | Design change |
|---|---|
| Dataset/error analysis was missing | Added a first-class Data and Error Analysis pipeline before scoring and proposal generation. |
| Failure taxonomy was closed and speculative | Replaced closed `FailureCategory` enum with an open taxonomy registry driven by open coding and axial clustering. |
| Judge calibration was run-scoped | Moved calibration to a versioned `JudgeVersion` asset with train/dev/locked-test splits and explicit thresholds. |
| Regression trusted the same judge after candidate drift | Added candidate distribution recheck through human audit samples before publish. |
| Regression lacked statistical rigor | Added repeat sampling, confidence intervals, no-significant-change state, and configurable minimum effect gates. |
| Trace attrs mixed execution and post-hoc annotations | Split execution-time OTel attributes from score/annotation/proposal metadata. |
| Redaction was only a flag | Added enforced redaction pipeline before UI display or LLM analysis. |
| Holdout integrity was not mechanical | Proposals record `consumed_case_ids`; regression excludes them and reports intersection checks. |
| `harness_version = git SHA` was too narrow | Added `harness_fingerprint` as a composite behavior identity. |
| UI MVP cloned annotation functionality | MVP uses Langfuse annotation where possible; Flywheel UI focuses on workflow decisions and assets Langfuse does not own. |

---

## 3. Architecture

```
L0 Agent Runtime (OTel required)
  emits traces with execution-time flywheel.* identity attrs
        |
        | OTLP traces and metrics, no head sampling for eval traces
        v
L2 Evidence Platform
  OTel Collector + Langfuse
  stores traces, observations, and scores

L1 Eval/Data Pipeline
  samples traces -> runs open coding -> curates datasets
  runs judges and submits scores through Flywheel API

L2.5 Flywheel Control Plane
  API + State Store + slim Web UI
  owns datasets, taxonomy, judge versions, issues, proposals, gates, audit

L3 Analysis Engine
  reads redacted evidence -> clusters failures -> proposes changes
  records consumed evidence -> triggers regression and publish/rollback gates
```

**Evidence vs control**:

| Layer | Owns | Does not own |
|---|---|---|
| OTel Collector | OTLP ingestion, batching, routing, full eval-trace export | Flywheel workflow logic |
| Langfuse | Raw traces, observations, scores, deep trace UI, native annotation when used | Proposal lifecycle, holdout policy, publish decisions |
| Flywheel API | Score Bridge, state transitions, authz, idempotency, redaction enforcement | Raw trace storage |
| Flywheel State Store | Datasets, taxonomy, judge versions, issues, proposals, handoffs, regression results | Long-term raw span payloads |
| Flywheel UI | Human workflow and decisions not covered by Langfuse | Trace explorer clone |
| Flywheel Engine | Error analysis, clustering, proposals, regression comparison | Human approval |

---

## 4. Repository Scope

| Repo | Type | Change |
|---|---|---|
| `bourbon` | Existing | Emit Flywheel OTel execution attrs; expose harness fingerprint inputs. |
| `intelligent_customer` | Existing | In scope only after equivalent OTel traces exist. No JSONL fallback in this design. |
| `flywheel` | New | `sdk/`, `api/`, `engine/`, `ui/`, `infra/`, `datasets/`, and `taxonomy/`. |

All projects must be OTel-capable. `trace_id` is never optional for eval runs.

---

## 5. Data and Error Analysis Pipeline

The flywheel starts with data, not categories. Failure labels and datasets must be derived from real traces before being used as stable evaluation criteria.

### Pipeline

```
trace pool
  -> representative sampling
  -> open coding
  -> axial clustering
  -> taxonomy registry update
  -> dataset candidate construction
  -> train/dev/locked-test split
  -> judge calibration
  -> eval run
```

### Sampling

Sampling must capture both volume and risk:

- recent production traces
- failed or low-confidence traces
- high-risk tool/sandbox/credential paths
- long multi-turn sessions
- repeated user intents
- edge cases from prior regressions

Eval traces must be fully exported to Langfuse. OTel head sampling must not drop traces for records with `flywheel.eval_run_id` or `flywheel.trace_pool_id`.

Trace pools reference raw traces stored in Langfuse. Each trace pool must declare a retention policy for raw evidence and redacted evidence views. Flywheel should not extend raw PII/secret retention beyond the evidence platform's configured TTL.

### Open Coding

Reviewers inspect a sampled trace batch and attach free-form codes such as:

```text
missing offset explanation
wrong tool arg shape
forgot prior user constraint
unsafe file access not escalated
answer omitted generated artifact
```

Open codes are not stable product labels. They are raw observations.

### Axial Clustering

The engine groups open codes into candidate failure labels. Reviewers can merge, rename, split, or retire labels. A label becomes stable only after it has:

- a short slug
- a human-readable definition
- positive and negative examples
- known counterexamples
- owner approval
- versioned inclusion in the taxonomy registry

### Open Taxonomy Registry

Failure taxonomy is open and versioned. The SDK must not hard-code a closed `FailureCategory` enum.

```yaml
taxonomy_version: 2026-06-22.1
labels:
  - slug: tool_argument_error
    parent: tool_misuse
    definition: "The agent chose a plausible tool but supplied invalid, incomplete, or misleading arguments."
    examples:
      - case_id: bourbon-read-offset-001
    counterexamples:
      - case_id: bourbon-tool-not-needed-002
    status: active
```

`other` is only a temporary code. Repeated `other` clusters must be reviewed for promotion, split, or explicit rejection.

### Taxonomy Migration

Taxonomy versions are immutable after publication. Changes create a new version plus an explicit migration map:

```yaml
from_version: 2026-06-22.1
to_version: 2026-07-01.1
migrations:
  - from: tool_argument_error
    to: invalid_tool_arguments
    kind: rename
  - from: context_miss
    to: [retrieval_miss, memory_miss]
    kind: split
  - from: obsolete_label
    to: null
    kind: retire
```

Rules:

- Historical annotations keep the taxonomy version they were created under.
- UI resolves old slugs through aliases and shows the original label plus current mapping.
- Dataset cases can be migrated only by creating a new dataset version.
- Judge versions remain tied to the taxonomy version they validated against.
- A taxonomy migration that touches labels used by a validated judge marks that judge `recheck_required`.

### Dataset Construction

Each dataset case must carry enough information for replay, scoring, and regression integrity.

```python
@dataclass
class DatasetCase:
    dataset_id: str
    dataset_version: str
    case_id: str
    task_family: str
    source_trace_ids: list[str]
    intent_summary: str
    input_messages_ref: str
    expected_outcome: str
    acceptance_criteria: list[str]
    risk_tags: list[str]
    failure_labels: list[str]
    split: Literal["train", "dev", "locked_test", "regression_holdout"]
    created_from: Literal["production_trace", "synthetic", "manual"]
```

Splits must be disjoint:

```
train ∩ dev ∩ locked_test ∩ regression_holdout = ∅
```

`locked_test` validates judge versions. `regression_holdout` validates harness candidates. They must never share cases. A mixed-task dataset is allowed only if every case declares `task_family` and the run either selects a single task family or uses a judge version validated for every included family.

Datasets should grow through curated batches, not by blindly scoring all traffic. Early target sizes:

| Dataset stage | Target |
|---|---|
| Seed set | 20-50 representative cases |
| First stable judge | 100+ cases with minority failure labels represented |
| Regression holdout | 30+ cases or a configured minimum per risk tier |

### Sampling and Cost Budget

Each run must have an explicit budget before it starts:

```python
@dataclass
class EvalBudget:
    max_cases: int
    max_repeats_per_case: int
    max_judge_calls: int
    max_curation_llm_calls: int
    max_drift_sentinel_cases: int
    max_analysis_traces: int
    max_total_cost_usd: float
    max_wall_clock_minutes: int
```

Budget policy should prefer representative samples over full traffic. The engine should report:

- expected judge calls before a run starts
- actual model calls and cost after the run
- cases skipped due to budget
- analysis traces sampled vs available
- curation, clustering, redaction, and drift-sentinel calls counted against the same budget family
- whether statistical confidence is limited by budget

If budget prevents a valid regression decision, the result is `needs_more_data` or `no_significant_change`, not publish.

---

## 6. Identity and Semantic Contract

OTel is the transport and correlation substrate. Flywheel defines a small semantic convention under `flywheel.*`.

### Execution-Time OTel Attributes

These attributes are set during agent execution. They must be available on the root span and propagated where queryability matters.

| Attribute | Type | Purpose |
|---|---|---|
| `flywheel.project` | string | Project namespace, for example `bourbon`. |
| `flywheel.environment` | string | `dev`, `ci`, `staging`, or `prod`. |
| `flywheel.trace_pool_id` | string | Trace pool for sampling and open coding, when not an eval run. |
| `flywheel.eval_run_id` | string | Stable id for one eval run. |
| `flywheel.dataset_id` | string | Versioned dataset id. |
| `flywheel.dataset_version` | string | Dataset version used by this run. |
| `flywheel.case_id` | string | Stable case id inside the dataset. |
| `flywheel.sample_id` | string | Attempt/sample id for repeated runs. |
| `flywheel.harness_fingerprint` | string | Composite behavior fingerprint. |
| `flywheel.session_id` | string | Conversation/session id when applicable. |
| `flywheel.turn_index` | int | Turn index for multi-turn tasks, `0` for single-turn. |

`trace_id` and `span_id` are evidence pointers, not eval identities. The same `case_id` can produce different traces across baseline, candidate, and repeated samples.

### Harness Fingerprint

`harness_fingerprint` must include behavior-affecting inputs, not only a git SHA:

- harness git SHA
- prompt and skill versions
- tool schema version
- memory/index configuration relevant to the run
- model provider and model snapshot when available
- decoding parameters
- dependency lock hash
- environment/runtime config hash

The raw components should be stored in State Store. The fingerprint is a compact comparable id.

### Post-Hoc Score and Annotation Metadata

These fields are not execution-time trace attributes. They are stored on Langfuse scores and mirrored in Flywheel State Store.

| Field | Type | Purpose |
|---|---|---|
| `flywheel.label` | `pass | fail | skip | uncertain` | Human, judge, rule, or system label. |
| `flywheel.failure_labels` | list[string] | Open taxonomy labels. |
| `flywheel.critique` | string | Human-readable reason. |
| `flywheel.confidence` | float | Reviewer or judge confidence from 0 to 1. |
| `flywheel.annotation_source` | `human | judge | rule | system` | Source of the label. |
| `flywheel.annotated_by` | string | Reviewer id, judge id, or system id. |
| `flywheel.annotation_rubric_version` | string | Version of the annotation rubric. |
| `flywheel.judge_version` | string | Prompt/model/config version for judge output. |
| `flywheel.redaction_state` | `raw | redacted | blocked` | Result of the enforced redaction pipeline. |

### Analysis and Proposal Metadata

| Field | Type | Purpose |
|---|---|---|
| `flywheel.issue_id` | string | Stable failure issue id generated by L3. |
| `flywheel.cluster_id` | string | Failure cluster id inside an analysis run. |
| `flywheel.proposal_id` | string | Improvement proposal id. |
| `flywheel.proposal_state` | `ProposalState` | One of the authoritative proposal lifecycle states in section 12. |
| `flywheel.regression_status` | `RegressionStatus` | Execution state for a regression run. |
| `flywheel.regression_outcome` | `RegressionOutcome` | Final regression decision, when available. |
| `flywheel.baseline_fingerprint` | string | Baseline harness fingerprint. |
| `flywheel.candidate_fingerprint` | string | Candidate harness fingerprint. |

---

## 7. L1 Flywheel SDK (`flywheel/sdk/`)

The SDK is a thin integration layer. It validates identity context, builds OTel attrs, submits scores through Flywheel API, and computes local metrics. It does not own UI, taxonomy governance, judge rubrics, or trace storage.

```
flywheel/sdk/
├── schema.py       # Label, AnnotationSource, FlywheelAttr, type aliases
├── context.py      # FlywheelContext validation and OTel attr builders
├── fingerprint.py  # Harness fingerprint helpers
├── score_client.py # Submit judge/rule scores to Flywheel API
└── metrics.py      # F1, precision, recall, confidence intervals
```

`failure_labels` are strings validated against the current taxonomy registry. Unknown labels can be submitted only as open codes during data/error analysis, not as stable regression categories.

---

## 8. L2 Evidence Platform (`flywheel/infra/`)

### Components

- **Langfuse**: self-hosted trace storage, score storage, native trace UI, native annotation where useful.
- **OTel Collector**: receives OTLP traces/metrics and exports them to Langfuse or another configured backend.
- **Metrics backend**: optional sink for long-term cost, latency, and run metrics.

### Routing Rules

```
OTLP traces  -> OTel Collector -> Langfuse OTLP endpoint
OTLP metrics -> OTel Collector -> metrics backend
Scores       -> Flywheel API Score Bridge -> Langfuse Score API
```

Collector routing must not contain Flywheel workflow logic. Score writes go through Flywheel API so they can be validated, deduplicated, retried, audited, and authorized.

---

## 9. Flywheel Control Plane (`flywheel/api/` + State Store)

```
flywheel/api/
├── server.py          # HTTP API for UI, L1, and engine jobs
├── schemas.py         # API request/response models
├── state_store.py     # datasets, taxonomy, judges, runs, issues, proposals
├── score_bridge.py    # idempotent Langfuse Score API writes
├── redaction.py       # redaction transforms and enforcement
├── auth.py            # local auth/session boundary and role checks
└── audit.py           # append-only decision and mutation log
```

### State Store Objects

| Object | Purpose |
|---|---|
| `TracePool` | Source traces available for sampling and open coding. |
| `TracePoolRetentionPolicy` | Raw trace TTL, redacted view TTL, and deletion/audit policy. |
| `OpenCodeBatch` | Human/raw codes applied during error analysis. |
| `TaxonomyLabel` | Versioned, open failure label with examples and status. |
| `TaxonomyMigration` | Alias, rename, split, merge, and retire map between taxonomy versions. |
| `Dataset` / `DatasetCase` | Curated cases and split metadata. |
| `JudgeVersion` | Judge prompt/model/config plus validation metrics. |
| `JudgeDriftCheck` | Periodic production drift sentinel result for a judge/task family. |
| `Baseline` | Project harness baseline generation, fingerprint, lineage, and current pointer state. |
| `EvalRun` | Run state, dataset, harness fingerprint, progress, aggregate metrics. |
| `Annotation` | Human, judge, rule, or system label plus metadata. |
| `FailureIssue` | Clustered, named failure mode with evidence links. |
| `ImprovementProposal` | Proposed changes, consumed evidence, and review state. |
| `Handoff` | Markdown handoff, coding-agent run, PR/diff link. |
| `RegressionResult` | Baseline vs candidate comparison and decision. |
| `RegressionHoldoutLedger` | Distinct holdout hypothesis exposure, raw run count, cold-case refresh metadata, multiple-comparison policy. |
| `BaselineRevertDecision` | Human-approved post-publish revert decision and evidence. |
| `AuditEvent` | Append-only mutation and approval history. |

### Idempotency

All mutating endpoints must support idempotency:

- `POST /api/runs`: server can generate `eval_run_id`; client-provided ids must be unique per project.
- `POST /api/scores`: idempotency key is `eval_run_id + case_id + sample_id + source + judge_version`.
- `POST /api/annotations`, when custom annotation is enabled: idempotency key is `annotation_item_id + annotator_id + rubric_version`.
- proposal approval, rejection, publish, and rollback are compare-and-set state transitions.

---

## 10. Redaction and Evidence Access

Redaction is a mandatory pipeline step, not a display flag.

```
Langfuse raw trace
  -> EvidenceReader
  -> RedactionService
  -> policy decision: redacted evidence | blocked evidence
  -> UI and/or LLM analysis
```

Rules:

- L3 analyzer and proposer must never receive raw trace payloads directly.
- `blocked` evidence is hidden from UI and excluded from LLM analysis.
- `redacted` evidence can be used by UI and LLM analysis, with redaction metadata attached.
- redaction failures fail closed.
- State Store records which redaction policy and version produced the evidence view.

This is required because Bourbon traces may include credentials, filesystem paths, user data, or sandbox policy details.

Redaction can also remove evidence needed for root-cause analysis. Each analysis report must include:

- redacted token/field count
- blocked evidence count
- evidence coverage after redaction
- over-block review count when humans mark evidence as too redacted to diagnose
- redaction policy version

If redaction coverage is too low, analysis can produce `needs_more_data` but must not bypass redaction.

---

## 11. Judge Version Lifecycle

Judge calibration is a versioned asset, not a per-run mandatory loop.

### JudgeVersion

```python
@dataclass
class JudgeVersion:
    judge_version: str
    project: str
    task_family: str
    model: str
    prompt_version: str
    taxonomy_version: str
    train_dataset_id: str
    dev_dataset_id: str
    locked_test_dataset_id: str
    status: Literal[
        "draft",
        "calibrating",
        "validated",
        "validated_limited",
        "rejected",
        "recheck_required",
    ]
    metrics: dict[str, float]
```

### Calibration Protocol

Default gate:

- train/dev/locked-test split is present.
- locked test is not used during judge prompt refinement.
- locked-test cases are disjoint from regression holdout cases.
- overall F1 is at least `0.70`, unless project policy defines a different threshold.
- minority failure labels have explicit precision/recall reporting.
- inter-annotator agreement is measured when multiple reviewers label the same set.
- a single domain owner resolves final rubric disputes for consistency.

Overlap policy for inter-annotator agreement:

- double-label at least 10 percent of calibration cases or 20 cases per task family, whichever is smaller but non-zero
- repeat overlap sampling on each major rubric, taxonomy, or judge change
- track agreement separately from human-vs-judge agreement

Eval runs reference a validated `judge_version`. If the judge is not validated for the dataset's task family, the run can collect scores but cannot trigger automated proposal generation.

### Locked-Test Rotation

The same locked test set must not be reused indefinitely across major judge iterations. Each task family needs a reserve of cold cases that were not used to choose prior judge versions.

Rules:

- Minor judge prompt edits can reuse the same locked test set for a bounded number of attempts.
- Major prompt/model/taxonomy changes require a refreshed locked test set or cold-case supplement.
- Validation reports must show how many previous judge versions used the same locked cases.
- If reuse exceeds project policy, the judge can be marked `validated_limited` for manual analysis but not for automated proposal generation.

### Candidate Drift Recheck

After harness changes, regression must include a small human audit of candidate outputs:

- at least 10 candidate cases or 10 percent of candidate failures, whichever is larger and feasible
- include new failure modes and changed-output cases
- compute candidate human-vs-judge agreement

If candidate agreement falls below the judge gate, publish is blocked and the judge moves to `recheck_required` for that task family.

### Production Drift Sentinel

Validated judges must be monitored after release:

- sample a small production or eval batch on a fixed cadence
- collect fresh human labels or expert review
- compute human-vs-judge agreement and minority-label precision/recall
- compare current input/output distributions with the judge validation set
- mark the judge `recheck_required` when agreement or distribution drift crosses policy thresholds

This sentinel is separate from candidate regression. It detects baseline drift from traffic changes, provider/model changes, and taxonomy drift before a future proposal depends on stale judge scores.

When the sentinel marks a judge `recheck_required`, every in-flight regression that depends on that judge version must move to `blocked_on_judge_recheck` if it is currently `regression_running` or `regression_review`. Automated proposal generation and publish actions that depend on the judge are paused until the judge is validated again or replaced by a migrated judge version.

---

## 12. Authoritative Proposal and Regression Lifecycle

These enums are the single source of truth for DB rows, API payloads, engine jobs, and frontend types. UI diagrams may render friendlier labels, but must not introduce extra lifecycle states.

### Baseline

Baseline is a first-class object because it is the durable output of the flywheel.

```python
@dataclass
class Baseline:
    project: str
    generation: int
    fingerprint: str
    produced_by_proposal_id: str | None
    previous_generation: int | None
    published_at: str
    status: Literal["current", "superseded", "reverted"]
    revert_reason: str | None = None
    reverted_at: str | None = None
```

Rules:

- Each project has exactly one `current` baseline.
- Publishing a proposal creates a new baseline generation and marks the previous current generation `superseded`.
- `baseline_generation` on proposals and regressions refers to this object, not an implicit counter.
- Baseline lineage must be queryable: current generation, previous generation, producing proposal, publish time, and revert history.
- Post-publish production drift, online regressions, or human incident review can request a baseline revert.
- Revert is a human gate: the current baseline is marked `reverted`, the selected previous generation becomes `current`, and in-flight proposals based on the reverted generation become `baseline_stale`.

Post-publish revert is separate from pre-publish `rolled_back`. `rolled_back` means a candidate never became baseline. `reverted` means a published baseline was later removed from current service.

```python
ProposalState = Literal[
    "draft",
    "under_review",
    "rejected",
    "deferred",
    "approved",
    "handoff_ready",
    "implementing",
    "diff_review",
    "revising",
    "regression_running",
    "regression_review",
    "blocked_on_judge_recheck",
    "blocked_on_judge_migration",
    "baseline_stale",
    "validated",
    "rolled_back",
    "no_significant_change",
    "abandoned",
]

RegressionStatus = Literal[
    "not_started",
    "running",
    "waiting_for_judge_recheck",
    "waiting_for_judge_migration",
    "ready_for_review",
    "complete",
]

RegressionOutcome = Literal[
    "published",
    "rolled_back",
    "no_significant_change",
    "revise",
    "abandoned",
    "judge_recheck_required",
    "judge_migration_required",
    "baseline_stale",
]
```

### Lifecycle Rules

```
draft -> under_review
under_review -> rejected | deferred | approved
approved -> handoff_ready -> implementing -> diff_review
diff_review -> revising | abandoned | regression_running
revising -> implementing
regression_running -> regression_review
regression_review + published -> validated
regression_review + rolled_back -> rolled_back -> revising | abandoned
regression_review + no_significant_change -> no_significant_change -> deferred | abandoned
regression_review + revise -> revising
regression_review + abandoned -> abandoned
regression_review + judge_recheck_required -> blocked_on_judge_recheck
regression_review + judge_migration_required -> blocked_on_judge_migration
regression_review + baseline_stale -> baseline_stale
blocked_on_judge_recheck -> regression_running, after the judge version is validated again
blocked_on_judge_migration -> regression_review, after baseline is re-scored with the candidate judge version
baseline_stale -> under_review, after rebase against the current baseline
deferred -> under_review, when new evidence, budget, or product priority revives it
```

Regression outcomes are decision events, not independent proposal states unless explicitly mapped above. `judge_recheck_required`, `judge_migration_required`, and `baseline_stale` block or redirect the proposal through the authoritative lifecycle rather than creating parallel UI-only states.

`rejected` is final for that proposal id. If the idea should be reconsidered later, create a new proposal linked to the original rejection reason. `deferred` is intentionally recoverable.

---

## 13. L3 Analysis Engine (`flywheel/engine/`)

```
flywheel/engine/
├── sampler.py       # representative trace sampling for error analysis
├── coder.py         # open coding support and code normalization
├── taxonomy.py      # axial clustering and taxonomy registry updates
├── dataset.py       # dataset construction and split enforcement
├── reader.py        # redacted evidence reads from Langfuse + State Store
├── analyzer.py      # failure clustering and root-cause attribution
├── proposer.py      # ImprovementProposal generation
├── handoff.py       # coding-agent handoff docs
├── validator.py     # regression, stats, candidate judge recheck
└── writer.py        # state, score, and audit writes
```

### Analysis Flow

```
trigger_analysis(project, eval_run_id)
    |
    |-> assert dataset and judge_version are valid
    |-> reader.fetch_redacted_failed_evidence()
    |-> analyzer.cluster_failures()
    |-> analyzer.attribute_root_causes()
    |-> proposer.generate()
    |-> writer.store_proposal(consumed_case_ids, evidence_trace_ids)
    |
    |-> GATE 1: human proposal review
    |-> handoff.generate_for_coding_agent()
    |-> GATE 2: human diff or PR review
    |-> validator.trigger_regression()
    |-> validator.compare_with_stats()
    |-> validator.run_candidate_judge_recheck()
    |-> GATE 3: publish, rollback, revise, abandon, or block on judge recheck
```

### Clustering Requirements

Do not cluster only by top-level label. Use:

- open codes and taxonomy labels
- tool name, tool error, and decisive span
- case intent and dataset split
- critique similarity
- harness fingerprint
- repeated trace features
- redaction state

Each `FailureIssue` should include evidence, counterexamples, affected labels, and confidence.

### ImprovementProposal

```python
@dataclass
class ProposedChange:
    change_type: Literal["prompt", "tool_definition", "workflow", "config", "code"]
    target_file: str
    description: str
    rationale: str
    evidence_trace_ids: list[str]
    evidence_case_ids: list[str]
    suggested_diff: str
    risk_level: Literal["low", "medium", "high"]

@dataclass
class ImprovementProposal:
    proposal_id: str
    project: str
    baseline_fingerprint: str
    baseline_generation: int
    candidate_hypothesis_id: str
    source_eval_run_id: str
    taxonomy_version: str
    failure_issues: list[str]
    proposed_changes: list[ProposedChange]
    target_files: list[str]
    consumed_case_ids: list[str]
    consumed_trace_ids: list[str]
    proposer_id: str
    expected_metric_delta: dict[str, float]
    rollback_plan: str
    created_at: str
```

`consumed_case_ids` records every case visible to the proposer, not only the examples shown in the final rationale.

`candidate_hypothesis_id` identifies the statistical hypothesis tested on regression holdout. The default identity is `proposal_id + candidate_fingerprint`. Re-running the same candidate because of retries, judge migration, or baseline re-scoring does not create a new hypothesis. A material implementation revision that changes the candidate fingerprint creates a new hypothesis for holdout-ledger accounting.

`expected_metric_delta` is a prediction, not evidence. Regression results must store actual deltas and compare them with the proposal's expected deltas. Flywheel should track long-term proposer calibration so repeatedly over-optimistic proposal sources can be down-weighted or require more review.

### Baseline Concurrency and Rebase

Multiple proposals can be in flight, but only one baseline is current. Publishing a candidate increments `baseline_generation` and changes the project baseline fingerprint.

Rules:

- A proposal can enter regression only if its `baseline_fingerprint` and `baseline_generation` match the current project `Baseline`.
- When a candidate is published, all non-terminal proposals based on the old generation are marked `baseline_stale`.
- A stale proposal must be rebased against the new baseline before returning to `under_review` or `regression_running`.
- Proposals touching overlapping `target_files` cannot be published concurrently. The later proposal waits for rebase or explicit conflict resolution.
- Regression reports must show whether any target files changed since the proposal was drafted.

`target_files` is a conservative approximation, not proof of semantic independence. It can over-block independent edits in different sections of a large prompt file, and it can under-block coupled changes across files such as a tool schema plus prompts that reference that tool. Proposals may add `target_symbols`, `prompt_sections`, or `semantic_dependencies` to improve conflict review, but high-risk conflicts remain a human gate in MVP.

---

## 14. Regression Gate

Regression decides whether a candidate harness can become a new baseline. It must guard against noise, leakage, and judge drift.

### Mechanical Holdout Integrity

The regression runner must compute:

```
consumed = proposal.consumed_case_ids
candidate_holdout = dataset.regression_holdout_cases - consumed
```

Regression uses only `regression_holdout` cases. It must not use `train`, `dev`, or `locked_test` cases that were used to tune or validate a judge.

The report must show:

- `consumed_case_ids ∩ regression_holdout_cases`
- `regression_holdout_cases ∩ train_cases`
- `regression_holdout_cases ∩ dev_cases`
- `regression_holdout_cases ∩ locked_test_cases`

Any non-empty intersection blocks publish.

### Holdout Reuse and Multiple Comparisons

Regression holdout integrity decays as candidates are repeatedly tested against the same cases. Flywheel must track holdout exposure:

```python
@dataclass
class RegressionHoldoutLedger:
    dataset_id: str
    dataset_version: str
    holdout_case_ids: list[str]
    tested_hypothesis_ids: list[str]
    distinct_hypothesis_count: int
    raw_regression_run_count: int
    published_candidate_count: int
    last_cold_case_refresh_at: str
    multiple_comparison_policy: Literal["none", "bonferroni", "fdr"]
```

Rules:

- Each regression run increments `raw_regression_run_count` for observability.
- Multiple-comparison correction uses `distinct_hypothesis_count`, not raw run count.
- A hypothesis is counted once per holdout version, keyed by `candidate_hypothesis_id`.
- Re-running the same hypothesis after retry, judge migration, baseline re-scoring, or infrastructure failure must not increase the multiple-comparison penalty.
- A materially changed candidate fingerprint or a new proposal id creates a new hypothesis and is added to `tested_hypothesis_ids`.
- Publish thresholds become stricter as distinct holdout hypotheses increase, using the configured multiple-comparison policy.
- When reuse exceeds project policy, publish is blocked until the holdout receives cold cases or rotates to a new holdout version.
- Regression reports must show distinct hypothesis count, raw run count, cold-case coverage, and any threshold adjustment.
- New baselines should reserve some never-used cold cases for future regression checks.
- If cold cases are exhausted, the default policy is to block baseline promotion. A project owner may record a manual experimental release, but it must not advance the current baseline until fresh production cases are curated, the holdout is rotated, or the statistical gate is explicitly downgraded with an audit reason.

### Comparison Identity

```
baseline:  dataset_id + case_id + sample_id + baseline_fingerprint + judge_version
candidate: dataset_id + case_id + sample_id + candidate_fingerprint + judge_version
```

Baseline and candidate must be scored with the same `judge_version`. Cached baseline scores from an older judge are not comparable. Before regression comparison:

- re-score baseline holdout cases with the candidate's judge version, or
- mark the result as `judge_migration_required` and block publish.

An explicit judge migration note can explain why historical metrics changed, but it does not allow direct baseline/candidate publish comparison across different judges.

### Statistical Requirements

Default policy:

- repeat nondeterministic cases at least 3 times when budget allows
- report confidence intervals for pass rate and key failure labels
- define a minimum meaningful delta before a candidate can be called a win
- classify small deltas inside the noise band as `no_significant_change`
- publish requires no critical safety regression

### Regression Outcomes

| Outcome | Meaning |
|---|---|
| `published` | Candidate improves meaningful metrics and passes safety/judge gates. |
| `rolled_back` | Candidate is worse or introduces critical regressions. |
| `no_significant_change` | Delta is within noise; no baseline change. |
| `revise` | Candidate fixed some issues but needs another proposal iteration. |
| `abandoned` | Proposal path is not worth continuing. |
| `judge_recheck_required` | Candidate distribution invalidated the current judge. |
| `judge_migration_required` | Baseline and candidate were not scored with the same judge version. |
| `baseline_stale` | Project baseline changed while the proposal was in flight. |

Regression results must store actual metric deltas beside the proposal's expected deltas. The UI should show expected vs actual and record the comparison for proposer calibration.

---

## 15. Implementation Phases

The adversarial review intentionally optimized for correctness. MVP must still separate hard correctness gates from mechanisms that can start as manual or interface-only workflows.

### Day-1 Hard Gates

These are required before Flywheel can safely publish a new baseline:

| Gate | Day-1 requirement |
|---|---|
| OTel identity | `trace_id`, dataset id/version, case id, sample id, and harness fingerprint are present for eval traces. |
| Redaction | Evidence shown to UI or LLM analysis passes redaction; blocked evidence cannot be used for proposals. |
| Dataset splits | `train`, `dev`, `locked_test`, and `regression_holdout` are mechanically disjoint. |
| Judge validity | Automated proposal generation requires a validated judge for the relevant task family. |
| Same-judge comparison | Baseline and candidate regression scores use the same `judge_version`; otherwise publish is blocked. |
| Regression holdout | Regression uses only `regression_holdout` cases, excludes consumed cases, and records holdout ledger exposure. |
| Baseline object | Each project has exactly one current `Baseline` with lineage and generation/fingerprint truth. |
| Human gates | Proposal approval, diff review, publish, rollback, and post-publish revert require explicit human action. |
| Authoritative lifecycle | DB, API, engine, and UI use the section 12 states without parallel vocabularies. |
| Revert path | A published baseline can be reverted to a prior generation through a human-gated audit decision. |

### Phase 1.5 Mechanisms

These mechanisms should have schema/API placeholders in MVP, but can start manual or partially automated:

| Mechanism | MVP stance | Later automation |
|---|---|---|
| Multiple-comparison correction | Store `RegressionHoldoutLedger` and show adjusted threshold inputs. | Automatically tune publish thresholds with Bonferroni/FDR policy. |
| Production drift sentinel | Define cadence, sample size, and state transition. | Scheduled sampling, scoring, and automatic judge recheck propagation. |
| Baseline rebase | Mark `baseline_stale` and require manual rebase review. | Auto-detect low-risk rebases and conflicts. |
| Judge migration | Block publish and require same-judge baseline re-scoring. | Queue baseline re-score jobs and return candidates to `regression_review`. |
| Conflict detection | Use `target_files` plus human review. | Add symbol/section/dependency graph and conflict confidence. |
| Redaction analytics | Record redaction state and blocked evidence count. | Track over-block/under-block metrics and policy recommendations. |
| Cost governance | Enforce run budgets. | Forecast and allocate curation, drift, and clustering spend across projects. |

### Roadmap

| Phase | Includes | Excludes |
|---|---|---|
| MVP | OTel-only contract, Score Bridge, State Store, data/error-analysis workflow, open taxonomy registry, Langfuse annotation sync, validated `JudgeVersion`, failure issues, proposal review, handoff Markdown, regression report with holdout/stat gates | Custom trace annotation UI, automated coding-agent execution, scheduled triggers |
| Phase 2 | Coding-agent executor, PR/diff linking, custom annotation workflow only if Langfuse is insufficient, candidate audit workflow, richer redaction policy UI | Fully automatic merge or publish |
| Phase 3 | Cron/threshold triggers, multi-project trend analytics, long-term taxonomy drift analysis | Autonomous deployment |

MVP is deliberately smaller than a full LangSmith clone. It validates the core flywheel: data curation, judge asset quality, proposal review, and regression decisioning.

---

## 16. Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Project compatibility | OTel required | Flywheel needs trace/span correlation and query semantics. |
| Trace sampling | Eval traces are fully exported | Missing spans make score/evidence review invalid. |
| Failure taxonomy | Open versioned registry | Failure modes must emerge from data, not only from a closed enum. |
| Judge calibration | Versioned judge asset | Judge trust is task/judge specific, not a per-run state. |
| Score ingestion | Flywheel API Score Bridge | Validation, retries, auth, and audit belong server-side. |
| Evidence access | Redaction pipeline before UI/LLM use | Prevent secret/PII leakage from traces. |
| Evidence store | Langfuse | Avoid rebuilding trace storage and trace UI. |
| Workflow store | Flywheel State Store | Langfuse scores do not model dataset, taxonomy, proposals, and publish gates. |
| UI timing | Slim UI in MVP | Human review is core, but trace annotation can initially use Langfuse. |
| Automation level | Human gates before implementation and publish | Prevent agent slop and preserve accountability. |
