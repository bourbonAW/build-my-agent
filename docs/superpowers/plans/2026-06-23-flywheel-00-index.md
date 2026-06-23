# Flywheel Implementation Plan — Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement each sub-plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the self-hosted Flywheel control plane + engine + UI described in the two parent specs: a closed-loop eval improvement system that turns real traces into datasets, calibrated judges, failure issues, human-reviewed proposals, regression decisions, and published harness baselines.

**Architecture:** New `flywheel/` repo with a Python control plane/engine (FastAPI + file/SQLite State Store, synchronous, matching Bourbon's style) and a React+TypeScript+Vite UI. Langfuse + OTel Collector are the evidence store (not built here, only integrated). The browser talks only to Flywheel API and never receives Langfuse write credentials.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, httpx, SQLite (stdlib `sqlite3`), pytest; React 18 + TypeScript + Vite, React Router, TanStack Query, TanStack Table, shadcn/ui, lucide-react, Recharts, Vitest + Testing Library + Playwright.

**Parent specs:**
- `docs/superpowers/specs/2026-06-22-flywheel-engine-design.md`
- `docs/superpowers/specs/2026-06-22-flywheel-ui-ux-design.md`

---

## Global Constraints

These apply to **every** sub-plan and task. Values copied verbatim from the specs.

- **OTel required.** `trace_id` is never optional for eval runs. Every project must be OTel-capable. No JSONL fallback.
- **No head sampling for eval traces.** Traces with `flywheel.eval_run_id` or `flywheel.trace_pool_id` must be fully exported to Langfuse.
- **Splits are mechanically disjoint:** `train ∩ dev ∩ locked_test ∩ regression_holdout = ∅`. `locked_test` validates judges; `regression_holdout` validates harness candidates; they must never share cases.
- **Redaction fails closed.** L3 analyzer/proposer must never receive raw trace payloads. `blocked` evidence is hidden from UI and excluded from LLM analysis. State Store records the redaction policy + version that produced each evidence view.
- **Same-judge comparison.** Baseline and candidate regression scores must use the same `judge_version`; otherwise publish is blocked (`judge_migration_required`).
- **Authoritative lifecycle states.** DB, API, engine, and UI use the section-12 `ProposalState`, `RegressionStatus`, `RegressionOutcome`, `RunState`, `JudgeState` enums verbatim. No parallel vocabularies. `RegressionStatus` is **derived** from `ProposalState`, never independently persisted.
- **Human gates.** Proposal approval, diff review, publish, rollback, and post-publish revert require explicit human action. No fully-automatic approval or publish.
- **Idempotency on all mutations.** Duplicate submits return the existing object. Keys:
  - `POST /api/scores`: `eval_run_id + case_id + sample_id + source + judge_version`
  - `POST /api/annotations`: `annotation_item_id + annotator_id + rubric_version`
  - proposal approval/rejection/publish/rollback are compare-and-set transitions.
- **Browser never receives Langfuse write credentials.** Score writes go only through Flywheel API Score Bridge.
- **One current Baseline per project**, with queryable lineage (current/previous generation, producing proposal, publish time, revert history).
- **Open taxonomy registry.** No hard-coded closed `FailureCategory` enum anywhere. Taxonomy versions are immutable after publication; changes create a new version + migration map.
- **Authz roles:** Dataset curator, Judge owner, Harness owner, Platform maintainer. Publish, rollback, post-publish revert, redaction-policy changes, and proposal approval require explicit role checks.
- **All mutations return** the updated object **and** an append-only audit event id.

---

## Repo Conventions

```
flywheel/
├── pyproject.toml          # Python package "flywheel", deps, ruff/mypy/pytest config
├── sdk/                    # L1 SDK (plan 01)
├── api/                    # Control plane: server, state store, score bridge, auth, audit, redaction (plans 02, 03)
├── engine/                 # L3: sampler, coder, taxonomy, dataset, reader, analyzer, proposer, handoff, validator, writer (plans 04–07)
├── infra/                  # docker-compose for Langfuse + OTel Collector (referenced, not a coding plan)
├── datasets/               # curated dataset YAML/JSON artifacts
├── taxonomy/               # taxonomy registry YAML artifacts
├── ui/                     # React app (plan 08)
└── tests/                  # pytest tree mirrors package layout
```

**Python conventions (match Bourbon):**
- Synchronous code. No asyncio in engine/state-store logic. FastAPI route handlers may be `def` (sync) — FastAPI runs them in a threadpool.
- `@dataclass` for engine domain objects; pydantic `BaseModel` for API request/response schemas.
- File-first State Store: JSON/JSONL on disk under `~/.flywheel/<project>/`, with a SQLite index for queryable lists. Crash-safety = append to disk before returning.
- Tests: `pytest`. Lint: `ruff check sdk api engine tests`. Types: `mypy sdk api engine`.

**Test commands:**
```bash
cd flywheel
uv pip install -e ".[dev]"
pytest                       # all
pytest tests/sdk -v          # one subsystem
ruff check sdk api engine tests
mypy sdk api engine
# UI:
cd flywheel/ui && npm install && npm run test && npm run test:e2e
```

---

## Sub-Plan DAG

Execute in dependency order. Each sub-plan ends with working, independently testable software.

```
00-index (this doc)
   │
   ▼
01-sdk ──────────────► 02-control-plane ──┬──► 03-redaction ──┐
                                          │                   │
                                          ├──► 04-data-analysis│
                                          │         │         │
                                          │         ▼         ▼
                                          │      05-judge ◄────┘
                                          │         │
                                          │         ▼
                                          │      06-engine ◄── 03
                                          │         │
                                          │         ▼
                                          │      07-regression
                                          │         │
                                          └─────────┴──► 08-ui (consumes all APIs)
```

| Plan | File | Produces | Spec coverage |
|---|---|---|---|
| 01 | `2026-06-23-flywheel-01-sdk.md` | repo scaffold, `flywheel.schema`, `FlywheelContext`, fingerprint, `ScoreClient`, metrics | Engine §6, §7 |
| 02 | `2026-06-23-flywheel-02-control-plane.md` | FastAPI server, State Store objects, Score Bridge, auth/roles, audit, idempotency, Baseline object | Engine §9, §12 (Baseline), UI §10, §11 |
| 03 | `2026-06-23-flywheel-03-redaction.md` | `RedactionService`, `EvidenceReader`, fail-closed pipeline, redaction analytics | Engine §10, UI §13 |
| 04 | `2026-06-23-flywheel-04-data-analysis.md` | sampler, coder, taxonomy registry+migration, dataset construction + split enforcement, budgets | Engine §5, §13 (sampler/coder/taxonomy/dataset) |
| 05 | `2026-06-23-flywheel-05-judge.md` | `JudgeVersion` lifecycle, calibration protocol, locked-test rotation, candidate drift recheck, drift sentinel | Engine §11 |
| 06 | `2026-06-23-flywheel-06-engine.md` | reader integration, analyzer (clustering+root cause), proposer, handoff Markdown, FailureIssue/ImprovementProposal | Engine §13 (analyzer/proposer/handoff) |
| 07 | `2026-06-23-flywheel-07-regression.md` | validator: holdout integrity, holdout ledger, stats/CI/noise band, candidate judge recheck, publish/rollback/no-sig-change/revert | Engine §12, §14 |
| 08 | `2026-06-23-flywheel-08-ui.md` | React app: all MVP routes + Phase 2 routes, decision forms, API client, Playwright loop test | UI spec (whole) |

---

## Phase Mapping (coverage = full: MVP + Phase 2/3)

Per engine spec §15, each sub-plan tags its tasks with the phase they satisfy:

- **Day-1 Hard Gates** — OTel identity (01,02), Redaction (03), Dataset splits (04), Judge validity (05), Same-judge comparison (07), Regression holdout (07), Baseline object (02,07), Human gates (02,08), Authoritative lifecycle (02), Revert path (02,07).
- **Phase 1.5 mechanisms** — multiple-comparison correction (07), drift sentinel (05), baseline rebase (07), judge migration (07), conflict detection (06,07), redaction analytics (03), cost governance (04). MVP stance = schema/API placeholder + manual; later automation noted per task.
- **Phase 2** — coding-agent executor + PR/diff linking (06,08), custom annotation workflow (08), candidate audit workflow (05,08), richer redaction policy UI (03,08).
- **Phase 3** — cron/threshold triggers, multi-project trend analytics, long-term taxonomy drift analysis (added as final tasks in 04, 05, 07, 08 marked Phase 3).

---

## API Endpoint Ownership (UI §10)

Every UI §10 endpoint is assigned to exactly one sub-plan. Plan 02 implements the runs and baselines endpoints and stubs all others with 501.

| Endpoint | Method | Owner plan |
|---|---|---|
| `/api/runs` | GET, POST | 02 |
| `/api/runs/{run_id}` | GET | 02 |
| `/api/runs/{run_id}/scores` | POST | 02 (stub) → 04 wires taxonomy validation |
| `/api/runs/{run_id}/sync-labels` | POST | 06 |
| `/api/runs/{run_id}/analysis` | POST | 06 |
| `/api/baselines` | GET, POST | 02 |
| `/api/baselines/{generation}` | GET | 02 |
| `/api/baselines/{generation}/revert` | POST | 02 |
| `/api/projects` | GET | 04 |
| `/api/datasets`, `/api/datasets/{id}` | GET | 04 |
| `/api/datasets/{dataset_id}/cases` | POST | 04 |
| `/api/taxonomy` | GET | 04 (aggregate of labels+migrations; UI §10) |
| `/api/taxonomy/labels`, `/api/taxonomy/migrations` | GET, POST | 04 |
| `/api/taxonomy/propose-update` | POST | 04 |
| `/api/trace-pools` | GET | 04 |
| `/api/trace-pools/{pool_id}/sample` | POST | 04 |
| `/api/open-code-batches/{batch_id}` | GET | 04 |
| `/api/open-code-batches/{batch_id}/codes` | POST | 04 |
| `/api/judges`, `/api/judges/{version}` | GET | 05 |
| `/api/judges` | POST | 05 |
| `/api/judges/{judge_version}/validate` | POST | 05 |
| `/api/annotations`, `/api/annotations/{id}` | GET, POST | 05 |
| `/api/issues`, `/api/issues/{issue_id}` | GET | 06 |
| `/api/proposals/{proposal_id}` | GET | 06 |
| `/api/proposals/{proposal_id}/handoff` | POST | 06 |
| `/api/proposals/{proposal_id}/implementation-link` | POST | 06 |
| `/api/proposals/{proposal_id}/rebase` | POST | 06 |
| `/api/proposals/{proposal_id}/approve` | POST | 07 |
| `/api/proposals/{proposal_id}/reject` | POST | 07 |
| `/api/proposals/{proposal_id}/defer` | POST | 07 |
| `/api/regressions` | POST | 07 |
| `/api/regressions/{regression_id}` | GET | 07 |
| `/api/regressions/{regression_id}/publish` | POST | 07 |
| `/api/regressions/{regression_id}/rollback` | POST | 07 |
| `/api/regressions/{regression_id}/no-significant-change` | POST | 07 |
| `/api/regressions/{regression_id}/require-judge-recheck` | POST | 07 |
| `/api/regressions/{regression_id}/resume-after-judge-recheck` | POST | 07 |
| `/api/regressions/{regression_id}/require-judge-migration` | POST | 07 |
| `/api/regressions/{regression_id}/resume-after-judge-migration` | POST | 07 |
| `/api/redaction/reports` | GET | 03 |
| `/api/evidence/{path}`, `/api/traces/{path}` | GET | 03 (guarded by REDACTION_ENABLED) |

## Dependency Notes

- **Plan 05 inherits type definitions from Plan 02.** `JudgeState`, `JudgeVersionModel`, and `JudgeDriftCheckModel` are defined in plan 02 `api/lifecycle.py` and `api/schemas.py`. Plan 05 imports and extends behavior but does not redefine these types.
- **Redaction hard gate (Engine §10, §15):** Plan 02 evidence-serving endpoints (`/api/evidence/*`, `/api/traces/*`) return 503 until `REDACTION_ENABLED` env var is set. This var must only be set after plan 03 `RedactionService` is wired into the app. Do not set `REDACTION_ENABLED=1` as part of plan 02 integration testing.

## Execution Order Note

Plans 03 and 04 both depend only on 02 and can run in parallel. 05 needs both. 06 needs 03+05. 07 needs 05+06. 08 needs every API contract, but its foundation tasks (scaffold, router, API client, runs/data pages) can start once 02 is stable. Within each plan, tasks are strictly ordered.
