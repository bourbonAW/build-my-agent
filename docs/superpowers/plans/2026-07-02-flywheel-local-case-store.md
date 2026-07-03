# Flywheel Local Case Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Langfuse Dataset Items + hand-edited metadata + disconnected Human Annotation queues with a flywheel-owned local `cases.jsonl` store and a purpose-built `/label` UI, while keeping Langfuse as the trace/observability system of record and keeping the rest of the harness/judge/regression pipeline working (just reading from a different place).

**Architecture:** Add a `Case` dataclass + append-only JSONL store (`~/.flywheel/<project>/state/cases.jsonl`, last-record-per-`case_id` wins) to `scripts/common.py`. Rewire `promote_cases()` to write there instead of calling the Langfuse Datasets API. Add two new FastAPI endpoints for listing/labeling cases. Remove the `judge_train`/`judge_dev`/`judge_test`/`regression` split system everywhere (scripts, `flywheel/regression.py`) in favor of one pool + a continuous (non-gating) judge-vs-human agreement metric. Add a new `/label` React route modeled on `intelligent_customer/eval/templates/annotate.html`'s single-case-review interaction.

**Tech Stack:** Python 3.13, FastAPI, pytest, React + TypeScript + Vite, `@tanstack/react-query`.

**Spec:** `docs/superpowers/specs/2026-07-02-flywheel-local-case-store-design.md`

## Global Constraints

- All new/changed Python files must pass `uv run mypy <file>` under this package's `[tool.mypy] strict = true` config (see `flywheel/pyproject.toml`).
- All new/changed Python files must pass `uv run ruff check <file>`.
- Every backend task must leave `uv run pytest` green for the whole `flywheel/` test suite before moving to the next task — do not leave the repo in a state where unrelated tests fail because of an in-progress rename.
- Case JSON field names use `snake_case` on disk (Python dataclass `asdict()` output) and `camelCase` over the HTTP API (matching the existing convention in `api/pipeline.py`'s other endpoints, e.g. `PipelineState`'s `totalCases`/`baselineScored`).
- No Langfuse Dataset/Score/Annotation API calls anywhere in the new code path (`promote_cases`, the two new case endpoints, or any of the four run scripts). `create_langfuse_client()` in `scripts/common.py` stays — it is still used by `scripts/sample_traces.py` to read raw traces, which is unchanged.
- Working directory for all commands below is `/home/hf/github_project/build-my-agent/flywheel` unless stated otherwise.

---

### Task 1: `Case` store in `scripts/common.py`

**Files:**
- Modify: `scripts/common.py`
- Create: `tests/scripts/__init__.py`
- Create: `tests/scripts/test_common_cases.py`

**Interfaces:**
- Produces: `CaseLabel = Literal["pass", "fail", "skip"]`, `Case` (frozen dataclass: `case_id: str`, `input: str`, `frozen_output: str`, `trace_url: str`, `expected_output: str`, `label: CaseLabel | None`, `critique: str`, `failure_category: str | None`, `annotated_at: str`), `cases_path(root: Path, project: str) -> Path`, `append_case(root: Path, project: str, case: Case) -> None`, `load_cases(path: Path) -> list[Case]`, `active_cases(cases: list[Case]) -> list[Case]`, `labeled_cases(cases: list[Case]) -> list[Case]`.
- Consumes: nothing new (uses existing `state_root`, `json`, `dataclasses.asdict`, `sys`, already imported in this file).

This task is purely additive — it does not yet touch `DatasetItem` or the split system, so nothing else in the repo breaks.

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/__init__.py` (empty file, makes the directory a package like `tests/api/`):

```python
```

Create `tests/scripts/test_common_cases.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.common import Case, active_cases, append_case, cases_path, labeled_cases, load_cases


def _case(case_id: str, label: str | None = None, **overrides: object) -> Case:
    base = dict(
        case_id=case_id,
        input="input text",
        frozen_output="agent said X",
        trace_url=f"https://cloud.langfuse.com/trace/{case_id}",
        expected_output="",
        label=label,
        critique="",
        failure_category=None,
        annotated_at="",
    )
    base.update(overrides)
    return Case(**base)  # type: ignore[arg-type]


def test_cases_path_lives_under_state_root(tmp_path: Path) -> None:
    path = cases_path(tmp_path, "bourbon")
    assert path == tmp_path / "bourbon" / "state" / "cases.jsonl"


def test_append_then_load_round_trips(tmp_path: Path) -> None:
    append_case(tmp_path, "bourbon", _case("t1"))
    append_case(tmp_path, "bourbon", _case("t2", label="pass"))
    cases = load_cases(cases_path(tmp_path, "bourbon"))
    assert [c.case_id for c in cases] == ["t1", "t2"]
    assert cases[1].label == "pass"


def test_load_cases_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_cases(cases_path(tmp_path, "bourbon")) == []


def test_later_record_wins_for_same_case_id(tmp_path: Path) -> None:
    append_case(tmp_path, "bourbon", _case("t1", label=None))
    append_case(tmp_path, "bourbon", _case("t1", label="fail", critique="wrong tool"))
    cases = load_cases(cases_path(tmp_path, "bourbon"))
    assert len(cases) == 1
    assert cases[0].label == "fail"
    assert cases[0].critique == "wrong tool"


def test_malformed_line_is_skipped_not_fatal(tmp_path: Path, capsys: object) -> None:
    path = cases_path(tmp_path, "bourbon")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('not json\n{"case_id": "t1", "input": "i", "frozen_output": "o", '
                     '"trace_url": "", "expected_output": "", "label": null, '
                     '"critique": "", "failure_category": null, "annotated_at": ""}\n')
    cases = load_cases(path)
    assert [c.case_id for c in cases] == ["t1"]


def test_active_cases_excludes_skip(tmp_path: Path) -> None:
    cases = [_case("a", label="pass"), _case("b", label="skip"), _case("c", label=None)]
    assert [c.case_id for c in active_cases(cases)] == ["a", "c"]


def test_labeled_cases_only_pass_or_fail(tmp_path: Path) -> None:
    cases = [_case("a", label="pass"), _case("b", label="fail"), _case("c", label="skip"),
             _case("d", label=None)]
    assert [c.case_id for c in labeled_cases(cases)] == ["a", "b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hf/github_project/build-my-agent/flywheel && uv run pytest tests/scripts/test_common_cases.py -v`
Expected: FAIL / ERROR — `ImportError: cannot import name 'Case' from 'scripts.common'` (none of the new names exist yet).

- [ ] **Step 3: Implement `Case` and its helpers**

In `scripts/common.py`, add near the top (after the existing `from flywheel.report import _safe_segment` import, before `REPO_ROOT`):

```python
CaseLabel = Literal["pass", "fail", "skip"]
```

Add after the existing `DatasetItem` class (do not remove `DatasetItem` yet — Task 2 does that):

```python
@dataclass(frozen=True)
class Case:
    case_id: str
    input: str
    frozen_output: str
    trace_url: str
    expected_output: str
    label: CaseLabel | None
    critique: str
    failure_category: str | None
    annotated_at: str


def cases_path(root: Path, project: str) -> Path:
    return state_root(root, project) / "cases.jsonl"


def append_case(root: Path, project: str, case: Case) -> None:
    path = cases_path(root, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(case), sort_keys=True, ensure_ascii=False) + "\n")


def load_cases(path: Path) -> list[Case]:
    """Read cases.jsonl; the last record per case_id wins; malformed lines are
    skipped with a warning rather than failing the whole load (a writer can be
    killed mid-write, leaving a truncated final line)."""
    if not path.exists():
        return []
    latest: dict[str, Case] = {}
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            latest[row["case_id"]] = Case(**row)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            print(f"[warn] skipping malformed cases.jsonl line {lineno}: {exc}", file=sys.stderr)
    return sorted(latest.values(), key=lambda c: c.case_id)


def active_cases(cases: list[Case]) -> list[Case]:
    """Cases eligible to run through the harness: everything not marked skip."""
    return [c for c in cases if c.label != "skip"]


def labeled_cases(cases: list[Case]) -> list[Case]:
    """Cases with a binary human verdict: judge few-shot source + validation pool."""
    return [c for c in cases if c.label in ("pass", "fail")]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hf/github_project/build-my-agent/flywheel && uv run pytest tests/scripts/test_common_cases.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check scripts/common.py tests/scripts/test_common_cases.py && uv run mypy scripts/common.py`
Expected: both clean. If mypy complains about `Case(**row)` in `load_cases` (dict unpacking into a dataclass isn't statically checked), add `# type: ignore[arg-type]` on that line — this mirrors the existing pattern at `_read_score_file`'s `ScoreRecord(**row)` a few lines below in the same file (check that this pattern is in fact unannotated there; if mypy is already clean on that pre-existing line, do the same here and don't add an ignore that isn't needed).

- [ ] **Step 6: Commit**

```bash
git add tests/scripts/__init__.py tests/scripts/test_common_cases.py scripts/common.py
git commit -m "feat(flywheel): add local Case store (cases.jsonl) to scripts/common.py"
```

---

### Task 2: Remove `DatasetItem`/splits, add `Case`-based `load_dataset_items`

**Files:**
- Modify: `scripts/common.py`
- Delete-in-place (within `scripts/common.py`): `DatasetItem`, `Split`, `SPLITS`, `_metadata_from`, `_parse_splits`, `_human_label`, `_record_from_langfuse_item`, `_item_from_record`, `load_dataset_items` (old signature), `split_sets`, `ensure_disjoint_splits`, `items_for_split`, `require_failure_labels`
- Test: `tests/scripts/test_common_cases.py` (extend)

**Interfaces:**
- Consumes: `Case`, `cases_path`, `load_cases` from Task 1.
- Produces: `load_dataset_items(cases_path: Path | None, root: Path, project: str) -> list[Case]` — new signature, replaces the old Langfuse-or-local-JSON loader with "explicit path, or default to `cases_path(root, project)`". Callers in Tasks 3–6 use this.

This task deliberately breaks `scripts/run_harness.py`, `scripts/run_judge.py`, `scripts/validate_judge.py`, and `scripts/run_regression.py`'s imports (they still import the now-deleted names). That's expected — Tasks 3–6 fix each script in turn. Do not attempt to fix all four scripts inside this task; keep this task scoped to `scripts/common.py` and its own tests only, and confirm the breakage is exactly the four expected import errors (not a fifth, unexpected one) before moving on.

- [ ] **Step 1: Write the failing test for the new `load_dataset_items`**

Append to `tests/scripts/test_common_cases.py`:

```python
from scripts.common import load_dataset_items


def test_load_dataset_items_defaults_to_project_cases_path(tmp_path: Path) -> None:
    append_case(tmp_path, "bourbon", _case("t1", label="pass"))
    items = load_dataset_items(None, tmp_path, "bourbon")
    assert [c.case_id for c in items] == ["t1"]


def test_load_dataset_items_explicit_path_overrides_default(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere.jsonl"
    other.write_text(
        json.dumps(asdict(_case("only-here", label="fail"))) + "\n"
    )
    items = load_dataset_items(other, tmp_path, "bourbon")
    assert [c.case_id for c in items] == ["only-here"]
```

Add the two missing imports at the top of the test file:

```python
import json
from dataclasses import asdict
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_common_cases.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_dataset_items'` doesn't apply (old one still exists with old signature) — instead expect a `TypeError: load_dataset_items() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Delete the old split/Langfuse-item system, add the new loader**

In `scripts/common.py`, remove these top-of-file imports that only the deleted code used:

```python
from flywheel.identity import HumanLabel, Label, validate_judge_version
from flywheel.regression import check_splits_disjoint
```

Replace with (still need `validate_judge_version` for `ScoreRecord`/`score_path`, keep it):

```python
from flywheel.identity import validate_judge_version
```

Delete these blocks entirely (in order of appearance): `Split`/`SPLITS` type aliases; the `DatasetItem` dataclass and its `in_split` method; `_metadata_from`; `_parse_splits`; `_human_label`; `_record_from_langfuse_item`; `_item_from_record`; the old `load_dataset_items`; `split_sets`; `ensure_disjoint_splits`; `items_for_split`; `require_failure_labels`.

Add the replacement loader where the old `load_dataset_items` was:

```python
def load_dataset_items(
    explicit_path: Path | None, root: Path, project: str
) -> list[Case]:
    """Load cases from an explicit JSONL path, or the project's default
    cases.jsonl if no explicit path is given."""
    path = explicit_path if explicit_path is not None else cases_path(root, project)
    return load_cases(path)
```

- [ ] **Step 4: Run this task's tests to verify they pass**

Run: `uv run pytest tests/scripts/test_common_cases.py -v`
Expected: PASS (all tests, including the two new ones)

- [ ] **Step 5: Confirm the expected (and only the expected) breakage elsewhere**

Run: `cd /home/hf/github_project/build-my-agent/flywheel && uv run pytest -q 2>&1 | tail -30`
Expected: failures/errors only from `run_harness.py`, `run_judge.py`, `validate_judge.py`, `run_regression.py` import chains (no test files import those scripts directly today, so you should instead see this as `mypy`/`ruff` import errors, not pytest failures — pytest itself should still be fully green since nothing in `tests/` imports the four scripts). Run `uv run ruff check scripts/` and confirm it reports unresolved-import-style errors (`F821`/`E999`, or unused-import if ruff parses successfully) only in `run_harness.py`, `run_judge.py`, `validate_judge.py`, `run_regression.py` — not in any other file.

- [ ] **Step 6: Lint and type-check `scripts/common.py` itself**

Run: `uv run ruff check scripts/common.py && uv run mypy scripts/common.py`
Expected: both clean (the four broken scripts are out of scope for this task's lint/type gate — they get fixed in Tasks 3–6).

- [ ] **Step 7: Commit**

```bash
git add scripts/common.py tests/scripts/test_common_cases.py
git commit -m "feat(flywheel): replace split-based DatasetItem with Case in scripts/common.py"
```

---

### Task 3: Rewrite `run_harness.py` for the new `Case` pool

**Files:**
- Modify: `scripts/run_harness.py`
- Create: `tests/scripts/test_run_harness.py`

**Interfaces:**
- Consumes: `Case`, `load_dataset_items`, `active_cases` from `scripts.common` (Tasks 1–2).
- Produces: nothing new consumed by later tasks (this script is a leaf CLI entry point invoked by `api/pipeline.py`, wired in Task 8).

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/test_run_harness.py`:

```python
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_cases(root: Path, project: str, cases: list[dict]) -> None:
    from scripts.common import cases_path

    path = cases_path(root, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(c) for c in cases) + "\n")


def _case(case_id: str, label: str | None) -> dict:
    return {
        "case_id": case_id,
        "input": f"hello from {case_id}",
        "frozen_output": "",
        "trace_url": "",
        "expected_output": "",
        "label": label,
        "critique": "",
        "failure_category": None,
        "annotated_at": "",
    }


def test_run_harness_runs_all_non_skip_cases(tmp_path: Path) -> None:
    _write_cases(tmp_path, "bourbon", [_case("a", "pass"), _case("b", None), _case("c", "skip")])
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.run_harness",
            "--project", "bourbon",
            "--root", str(tmp_path),
            "--model", "smoke-model",
            "--run-id", "run1",
            "--output-template", "echoed: {input}",
            "--workdir", str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cases"] == 2

    from scripts.common import load_run_outputs

    outputs = load_run_outputs(tmp_path, "bourbon", "run1")
    assert {o.case_id for o in outputs} == {"a", "b"}


def test_run_harness_errors_when_all_cases_skipped(tmp_path: Path) -> None:
    _write_cases(tmp_path, "bourbon", [_case("a", "skip")])
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.run_harness",
            "--project", "bourbon",
            "--root", str(tmp_path),
            "--model", "smoke-model",
            "--output-template", "echoed: {input}",
            "--workdir", str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "no active cases" in result.stderr.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_run_harness.py -v`
Expected: FAIL — `run_harness.py` still imports the deleted `ensure_disjoint_splits`/`items_for_split`/`require_failure_labels` names, so the subprocess exits non-zero with an `ImportError` traceback on stderr.

- [ ] **Step 3: Rewrite `run_harness.py`**

Replace the `scripts.common` import block:

```python
from scripts.common import (
    DEFAULT_ROOT,
    RunOutput,
    active_cases,
    current_git_sha,
    load_dataset_items,
    slugify,
    utc_timestamp_slug,
    write_run_outputs,
)
```

Replace `--dataset-json`/`--dataset` args with a single `--cases-path`:

```python
    parser.add_argument("--cases-path", type=Path, default=None)
```

(remove the two old `parser.add_argument("--dataset-json", ...)` / `parser.add_argument("--dataset", ...)` lines)

Replace the loading block:

```python
    items = load_dataset_items(args.cases_path, args.root, args.project)
    regression_items = active_cases(items)
    if not regression_items:
        raise SystemExit("no active cases (every case is skipped or the pool is empty)")
```

Everything below this (the `for item in regression_items:` loop, `write_run_outputs` calls, the final `print(json.dumps(...))`) is unchanged — `item.input` still resolves the same way since `Case.input` has the same name/type as the old `DatasetItem.input`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_run_harness.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check scripts/run_harness.py tests/scripts/test_run_harness.py && uv run mypy scripts/run_harness.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add scripts/run_harness.py tests/scripts/test_run_harness.py
git commit -m "feat(flywheel): run_harness.py runs the unified Case pool, drops splits"
```

---

### Task 4: Rewrite `run_judge.py` — few-shot from labeled cases, `--target` replaces `--split`

**Files:**
- Modify: `scripts/run_judge.py`
- Create: `tests/scripts/test_run_judge.py`

**Interfaces:**
- Consumes: `Case`, `load_dataset_items`, `active_cases`, `labeled_cases` from `scripts.common`.
- Produces: score files written under target name `"frozen"` (all labeled cases' `frozen_output`, used by Task 5's `validate_judge.py`) or a harness `run_id` (baseline/candidate live outputs, used by Task 6's `run_regression.py`). This target-name convention is relied on by Tasks 5, 6, and 8.

Old CLI: `--split {judge_dev,judge_test,regression} [--run RUN_ID]`, few-shot always drawn from the separate `judge_train` split. New CLI: `--target {frozen,<run_id>}` — `frozen` scores every labeled case's own `frozen_output`; anything else is treated as a harness `run_id` and scores that run's live outputs. Few-shot examples are drawn from `labeled_cases()` in both cases (there is no more train/test separation — see spec §2).

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/test_run_judge.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _case(case_id: str, label: str | None, frozen_output: str = "", expected: str = "") -> dict:
    return {
        "case_id": case_id,
        "input": f"input for {case_id}",
        "frozen_output": frozen_output,
        "trace_url": "",
        "expected_output": expected,
        "label": label,
        "critique": "",
        "failure_category": None,
        "annotated_at": "2026-07-02T00:00:00Z" if label else "",
    }


def _write_cases(root: Path, project: str, cases: list[dict]) -> None:
    from scripts.common import cases_path

    path = cases_path(root, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(c) for c in cases) + "\n")


def test_run_judge_scores_frozen_target(tmp_path: Path) -> None:
    _write_cases(
        tmp_path, "bourbon",
        [
            _case("train1", "pass", frozen_output="good answer", expected="be correct"),
            _case("eval1", "fail", frozen_output="bad answer", expected="be correct"),
        ],
    )
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.run_judge",
            "--project", "bourbon",
            "--root", str(tmp_path),
            "--target", "frozen",
            "--judge-version", "judge-v1",
            "--model", "claude-x",
            "--prompt-version", "p1",
            "--canned-response", "VERDICT: fail\nREASON: canned",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["target"] == "frozen"
    assert payload["scores"] == 2  # both labeled cases get scored, including the few-shot source


def test_run_judge_errors_with_no_labeled_cases(tmp_path: Path) -> None:
    _write_cases(tmp_path, "bourbon", [_case("a", None)])
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.run_judge",
            "--project", "bourbon",
            "--root", str(tmp_path),
            "--target", "frozen",
            "--judge-version", "judge-v1",
            "--model", "claude-x",
            "--prompt-version", "p1",
            "--canned-response", "VERDICT: pass\nREASON: canned",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "no labeled cases" in result.stderr.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_run_judge.py -v`
Expected: FAIL — `run_judge.py` still imports deleted names (`ensure_disjoint_splits`, `items_for_split`), subprocess exits with an `ImportError` traceback.

- [ ] **Step 3: Rewrite `run_judge.py`**

Replace the `scripts.common` import block:

```python
from scripts.common import (
    DEFAULT_ROOT,
    Case,
    RunOutput,
    ScoreRecord,
    active_cases,
    labeled_cases,
    load_dataset_items,
    load_run_outputs,
    write_score_records,
)
```

Replace `_example`:

```python
def _example(item: Case) -> JudgeExample:
    critique = item.critique or "human gold label"
    return JudgeExample(item.input, item.expected_output, item.frozen_output, item.label, critique)
```

(`item.label` here is statically `CaseLabel | None`; callers only pass items already filtered by `labeled_cases()`, so it is always `"pass"` or `"fail"` at runtime — `JudgeExample.__post_init__` still validates this against `HumanLabel`'s `get_args`, so a real bug would still raise loudly, it just isn't provable to mypy from this call site. Add `# type: ignore[arg-type]` on the `JudgeExample(...)` line if mypy flags it.)

Replace `_target_outputs_for_frozen` and `_target_outputs_for_run`:

```python
def _target_outputs_for_frozen(items: list[Case]) -> list[tuple[Case, str, str, str]]:
    return [(item, item.frozen_output, item.trace_url, item.case_id) for item in items]


def _target_outputs_for_run(
    items: list[Case],
    outputs: list[RunOutput],
) -> list[tuple[Case, str, str, str]]:
    by_case = {item.case_id: item for item in items}
    out: list[tuple[Case, str, str, str]] = []
    for output in outputs:
        item = by_case.get(output.case_id)
        if item is not None:
            out.append((item, output.output, output.trace_url, output.sample_id))
    return out
```

Replace the `main()` argument parsing (drop `--dataset-json`/`--dataset`/`--split`/`--run`, add `--cases-path`/`--target`):

```python
    parser.add_argument("--cases-path", type=Path, default=None)
    parser.add_argument(
        "--target", required=True,
        help="'frozen' to score every labeled case's frozen_output, or a harness run_id "
             "to score that run's live outputs",
    )
```

Replace the body from `split = cast(Split, args.split)` down through the `if split == "regression":` branch with:

```python
    items = load_dataset_items(args.cases_path, args.root, args.project)
    train_items = labeled_cases(items)
    if not train_items:
        raise SystemExit("no labeled cases to build judge few-shot examples from")
    examples = tuple(_example(item) for item in train_items)
    canned_by_key = (
        json.loads(args.canned_labels_json.read_text()) if args.canned_labels_json else None
    )
    complete = (
        None
        if canned_by_key
        else (
            (lambda _prompt: args.canned_response)
            if args.canned_response
            else _anthropic_complete(args.model)
        )
    )
    config = JudgeConfig(args.judge_version, args.model, args.prompt_version, examples)

    target = args.target
    if target == "frozen":
        target_items = train_items
        outputs = _target_outputs_for_frozen(target_items)
    else:
        target_items = active_cases(items)
        outputs = _target_outputs_for_run(
            target_items, load_run_outputs(args.root, args.project, target)
        )
```

The rest of `main()` (the `if not outputs:` check through the final `print`) is unchanged, except every `item.expected` becomes `item.expected_output` in the `judge.score_case(item.input, output, item.expected)` call — update that one line too:

```python
            label, critique = judge.score_case(item.input, output, item.expected_output)
```

Remove the now-unused `cast` import and `Split` import if still present at the top of the file (`from typing import Callable, cast` → `from typing import Callable`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_run_judge.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check scripts/run_judge.py tests/scripts/test_run_judge.py && uv run mypy scripts/run_judge.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add scripts/run_judge.py tests/scripts/test_run_judge.py
git commit -m "feat(flywheel): run_judge.py scores the unified Case pool via --target"
```

---

### Task 5: Rewrite `validate_judge.py` — continuous metric, not a gate

**Files:**
- Modify: `scripts/validate_judge.py`
- Create: `tests/scripts/test_validate_judge.py`

**Interfaces:**
- Consumes: `Case`, `load_dataset_items`, `labeled_cases` from `scripts.common`; `LabeledCase`, `validate` from `flywheel.validate` (unchanged — see spec §5.3, this library needs no changes).
- Produces: a `JudgeReport` written via `write_judge_report` (unchanged call), always exit code 0 regardless of `report.passes()` (previously exited 1 below threshold — that gate is removed per spec §2).

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/test_validate_judge.py`:

```python
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _case(case_id: str, label: str) -> dict:
    return {
        "case_id": case_id, "input": "i", "frozen_output": "o", "trace_url": "",
        "expected_output": "e", "label": label, "critique": "", "failure_category": None,
        "annotated_at": "2026-07-02T00:00:00Z",
    }


def _write_cases(root: Path, project: str, cases: list[dict]) -> None:
    from scripts.common import cases_path

    path = cases_path(root, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(c) for c in cases) + "\n")


def _write_scores(root: Path, project: str, target: str, judge_version: str, rows: list[dict]) -> None:
    from scripts.common import ScoreRecord, write_score_records

    write_score_records(
        root, project, target, judge_version,
        [ScoreRecord(**row) for row in rows],
    )


def test_validate_judge_reports_without_gating_exit_code(tmp_path: Path) -> None:
    _write_cases(tmp_path, "bourbon", [_case("a", "fail"), _case("b", "pass")])
    _write_scores(
        tmp_path, "bourbon", "frozen", "judge-v1",
        [
            {"case_id": "a", "run_id": "frozen", "judge_version": "judge-v1", "model": "m",
             "prompt_version": "p1", "label": "pass", "critique": "wrong", "trace_url": "",
             "sample_id": "a"},
            {"case_id": "b", "run_id": "frozen", "judge_version": "judge-v1", "model": "m",
             "prompt_version": "p1", "label": "pass", "critique": "ok", "trace_url": "",
             "sample_id": "b"},
        ],
    )
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.validate_judge",
            "--project", "bourbon", "--root", str(tmp_path), "--judge-version", "judge-v1",
        ],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    # judge disagreed on case "a" (human fail, judge pass) -> low F1 -> passes() is False,
    # but the script must still exit 0 (informational report, not a gate).
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["passes"] is False
    assert payload["validationSetSize"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_validate_judge.py -v`
Expected: FAIL — `validate_judge.py` still imports `ensure_disjoint_splits`/`items_for_split`/`Split`, subprocess exits with an `ImportError`.

- [ ] **Step 3: Rewrite `validate_judge.py`**

Full new contents:

```python
"""Validate a judge against every currently human-labeled case (continuous metric,
not a pass/fail gate — see docs/superpowers/specs/2026-07-02-flywheel-local-case-store-design.md §2)."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from flywheel.report import write_judge_report
from flywheel.validate import LabeledCase, validate

from scripts.common import (
    DEFAULT_ROOT,
    labeled_cases,
    load_dataset_items,
    load_score_records,
    one_score_per_case,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="bourbon")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--cases-path", type=Path, default=None)
    parser.add_argument("--judge-version", default=None)
    parser.add_argument("--threshold", type=float, default=0.70)
    parser.add_argument("--min-class-support", type=int, default=5)
    args = parser.parse_args()

    items = load_dataset_items(args.cases_path, args.root, args.project)
    target_items = labeled_cases(items)
    if not target_items:
        raise SystemExit("no labeled cases to validate the judge against")

    scores, judge_version = load_score_records(
        args.root, args.project, "frozen", judge_version=args.judge_version,
    )
    by_case = one_score_per_case(scores, {item.case_id for item in target_items})

    labeled: list[LabeledCase] = [
        LabeledCase(item.case_id, item.label, by_case[item.case_id].label)  # type: ignore[arg-type]
        for item in target_items
    ]

    first = scores[0]
    report = validate(
        labeled,
        judge_version=judge_version,
        model=first.model,
        prompt_version=first.prompt_version,
        threshold=args.threshold,
        min_class_support=args.min_class_support,
    )
    path = write_judge_report(args.root, args.project, report)
    payload = asdict(report) | {"passes": report.passes(), "path": str(path)}
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
```

Note the `# type: ignore[arg-type]`: `item.label` is `CaseLabel | None` statically, but `target_items` is already filtered by `labeled_cases()` to only `"pass"`/`"fail"`, matching `LabeledCase.human`'s `HumanLabel` type at runtime — same reasoning as Task 4's `_example`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_validate_judge.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check scripts/validate_judge.py tests/scripts/test_validate_judge.py && uv run mypy scripts/validate_judge.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add scripts/validate_judge.py tests/scripts/test_validate_judge.py
git commit -m "feat(flywheel): validate_judge.py is a continuous metric, not a gate"
```

---

### Task 6: `flywheel/regression.py` drops disjointness; rewrite `run_regression.py`

**Files:**
- Modify: `flywheel/regression.py`
- Modify: `tests/test_regression.py`
- Modify: `scripts/run_regression.py`
- Create: `tests/scripts/test_run_regression.py`

**Interfaces:**
- Consumes (in `run_regression.py`): `Case`, `load_dataset_items`, `active_cases` from `scripts.common`.
- Produces: `compare(baseline, candidate, *, regression_case_ids, baseline_judge_version, candidate_judge_version) -> RegressionReport` — `validation_case_ids` parameter removed.

- [ ] **Step 1: Update `tests/test_regression.py` for the new `compare()` signature (this IS the failing-test step — the test file itself is being changed to match the target API)**

Replace the `_cmp` helper (drop `validation_case_ids`):

```python
def _cmp(
    base: list[CaseScore],
    cand: list[CaseScore],
    regression_case_ids: set[str] | None = None,
):
    ids = {s.case_id for s in base} if regression_case_ids is None else set(regression_case_ids)
    return compare(
        base,
        cand,
        regression_case_ids=ids,
        baseline_judge_version="jv1",
        candidate_judge_version="jv1",
    )
```

Remove the two `validation_case_ids=set()` kwargs from `test_mismatched_judge_raises` and `test_invalid_judge_version_raises`'s `compare(...)` calls (they now use the updated `_cmp` signature, or call `compare()` directly without the removed kwarg — check each call site and delete the `validation_case_ids=set(),` line).

Delete `test_disjointness_violation_raises` entirely (the behavior it tests no longer exists).

Delete `test_splits_disjoint_ok` and `test_splits_overlap_raises` entirely (they test `check_splits_disjoint`, which Step 3 below deletes).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hf/github_project/build-my-agent/flywheel && uv run pytest tests/test_regression.py -v`
Expected: FAIL — `compare()` still requires `validation_case_ids` (`TypeError: compare() missing 1 required keyword-only argument: 'validation_case_ids'`) for the calls that no longer pass it, and errors for the two deleted-behavior tests you removed shouldn't appear at all (confirm they're gone from the collected test list, not failing).

- [ ] **Step 3: Update `flywheel/regression.py`**

Delete the `check_splits_disjoint` function entirely.

In `compare()`, remove the `validation_case_ids: set[str],` parameter from the signature and remove this block from the body:

```python
    overlap = set(base_ids) & validation_case_ids
    if overlap:
        raise ValueError(f"regression set must be disjoint from validation set; overlap={overlap}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_regression.py -v`
Expected: PASS (all remaining tests)

- [ ] **Step 5: Write the failing test for `run_regression.py`**

Create `tests/scripts/test_run_regression.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _case(case_id: str) -> dict:
    return {
        "case_id": case_id, "input": "i", "frozen_output": "o", "trace_url": "",
        "expected_output": "e", "label": None, "critique": "", "failure_category": None,
        "annotated_at": "",
    }


def _write_cases(root: Path, project: str, ids: list[str]) -> None:
    from scripts.common import cases_path

    path = cases_path(root, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(_case(i)) for i in ids) + "\n")


def _write_scores(root: Path, project: str, run_id: str, labels: dict[str, str]) -> None:
    from scripts.common import ScoreRecord, write_score_records

    write_score_records(
        root, project, run_id, "judge-v1",
        [
            ScoreRecord(
                case_id=case_id, run_id=run_id, judge_version="judge-v1", model="m",
                prompt_version="p1", label=label, critique="c", trace_url="", sample_id=case_id,
            )
            for case_id, label in labels.items()
        ],
    )


def test_run_regression_compares_without_judge_gate(tmp_path: Path) -> None:
    _write_cases(tmp_path, "bourbon", ["a", "b"])
    _write_scores(tmp_path, "bourbon", "baseline", {"a": "fail", "b": "pass"})
    _write_scores(tmp_path, "bourbon", "candidate", {"a": "pass", "b": "pass"})
    # No judge report written at all -- the old code required a passing JudgeReport
    # on disk before allowing a compare; the new code must not require this.
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.run_regression",
            "--project", "bourbon", "--root", str(tmp_path),
            "--baseline-run", "baseline", "--candidate-run", "candidate",
        ],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["result"] in ("better", "no_change", "worse")
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/scripts/test_run_regression.py -v`
Expected: FAIL — `run_regression.py` still imports deleted `ensure_disjoint_splits`/`items_for_split`/`require_failure_labels`/`split_sets`, subprocess exits with an `ImportError`.

- [ ] **Step 7: Rewrite `run_regression.py`**

Replace the `scripts.common` import block:

```python
from scripts.common import (
    DEFAULT_ROOT,
    Case,
    ScoreRecord,
    active_cases,
    load_dataset_items,
    load_run_metadata,
    load_score_records,
)
```

Delete `_judge_report_path` and `_require_passing_judge` entirely (the hard judge-validation gate before comparing is removed — see spec §2/§5.3; `validate_judge.py`'s report remains available for a human to look at, it just no longer blocks this script).

Replace `_case_scores`'s type hint and `failure_label` lookup (rename to `failure_category`):

```python
def _case_scores(items: dict[str, Case], records: list[ScoreRecord]) -> list[CaseScore]:
    scores: list[CaseScore] = []
    for record in records:
        item = items.get(record.case_id)
        if item is None:
            scores.append(CaseScore(record.case_id, record.label))
            continue
        failure_label = item.failure_category if record.label != "pass" else None
        scores.append(CaseScore(record.case_id, record.label, failure_label))
    return scores
```

Replace the `main()` body from `items = load_dataset_items(...)` through `_require_passing_judge(...)`:

```python
    items = load_dataset_items(args.cases_path, args.root, args.project)
    regression_items = active_cases(items)
    item_by_id = {item.case_id: item for item in regression_items}

    baseline_records, baseline_judge_version = load_score_records(
        args.root, args.project, args.baseline_run
    )
    candidate_records, candidate_judge_version = load_score_records(
        args.root, args.project, args.candidate_run
    )
    if args.judge_version is not None and args.judge_version not in {
        baseline_judge_version,
        candidate_judge_version,
    }:
        raise ValueError(
            f"--judge-version {args.judge_version!r} does not match score metadata "
            f"{baseline_judge_version!r}/{candidate_judge_version!r}"
        )
```

Replace the `compare(...)` call (remove `validation_case_ids`/`splits`/`split_sets` usage):

```python
    report = compare(
        baseline_aggregated,
        candidate_aggregated,
        regression_case_ids={item.case_id for item in regression_items},
        baseline_judge_version=baseline_judge_version,
        candidate_judge_version=candidate_judge_version,
    )
```

Also add `--cases-path` and remove `--dataset-json`/`--dataset` from the argument parser (same pattern as Tasks 3–5):

```python
    parser.add_argument("--cases-path", type=Path, default=None)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_run_regression.py -v`
Expected: PASS (1 passed)

- [ ] **Step 9: Run the full flywheel test suite**

Run: `uv run pytest -q`
Expected: all green — this is the first point where all four scripts + the library are consistent again.

- [ ] **Step 10: Lint and type-check everything touched in this task**

Run: `uv run ruff check flywheel/regression.py scripts/run_regression.py tests/test_regression.py tests/scripts/test_run_regression.py && uv run mypy flywheel/regression.py scripts/run_regression.py`
Expected: both clean.

- [ ] **Step 11: Commit**

```bash
git add flywheel/regression.py tests/test_regression.py scripts/run_regression.py tests/scripts/test_run_regression.py
git commit -m "feat(flywheel): drop split disjointness from regression.py and run_regression.py"
```

---

### Task 7: `pipeline.py` — promote writes `cases.jsonl`, no Langfuse Dataset calls

**Files:**
- Modify: `api/pipeline.py`
- Create: `tests/api/test_pipeline.py`

**Interfaces:**
- Consumes: `Case`, `cases_path`, `append_case`, `load_cases` from `scripts.common` (imported lazily inside the route handler, matching this file's existing lazy-import convention for `scripts.*`).
- Produces: `promote_cases()` behavior change only in this task; the two brand-new endpoints (`GET /api/pipeline/cases`, `POST /api/pipeline/cases/{case_id}/label`) are Task 8, kept separate because they're independently reviewable (promote vs. label are different user actions).

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_pipeline.py`:

```python
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import pipeline
from api import pipeline_state as ps


def _app(tmp_path: Path) -> FastAPI:
    pipeline.configure(tmp_path, "bourbon", langfuse=None, python="python3")
    app = FastAPI()
    app.include_router(pipeline.router)
    return app


def _write_sample_traces(tmp_path: Path, traces: list[dict]) -> None:
    from scripts.common import state_root, write_json

    path = state_root(tmp_path, "bourbon") / "sample_traces.json"
    write_json(path, {"traces": traces})


def test_promote_writes_local_cases_not_langfuse(tmp_path: Path) -> None:
    _write_sample_traces(tmp_path, [
        {"id": "trace-1", "input": "hi", "output": "hello there"},
        {"id": "trace-2", "input": "bye", "output": "goodbye"},
    ])
    client = TestClient(_app(tmp_path))

    response = client.post(
        "/api/pipeline/promote",
        json={"dataset_name": "unused", "trace_ids": ["trace-1", "trace-2"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["promoted"] == 2
    assert body["skipped"] == 0

    from scripts.common import cases_path, load_cases

    cases = load_cases(cases_path(tmp_path, "bourbon"))
    assert {c.case_id for c in cases} == {"trace-1", "trace-2"}
    trace1 = next(c for c in cases if c.case_id == "trace-1")
    assert trace1.input == "hi"
    assert trace1.frozen_output == "hello there"
    assert trace1.label is None


def test_promote_skips_already_promoted_case(tmp_path: Path) -> None:
    _write_sample_traces(tmp_path, [{"id": "trace-1", "input": "hi", "output": "hello"}])
    client = TestClient(_app(tmp_path))

    first = client.post(
        "/api/pipeline/promote",
        json={"dataset_name": "unused", "trace_ids": ["trace-1"]},
    )
    assert first.json()["promoted"] == 1

    second = client.post(
        "/api/pipeline/promote",
        json={"dataset_name": "unused", "trace_ids": ["trace-1"]},
    )
    assert second.json()["promoted"] == 0
    assert second.json()["skipped"] == 1

    from scripts.common import cases_path, load_cases

    cases = load_cases(cases_path(tmp_path, "bourbon"))
    assert len(cases) == 1  # not duplicated


def test_promote_without_sample_file_returns_400(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/pipeline/promote",
        json={"dataset_name": "unused", "trace_ids": ["trace-1"]},
    )
    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hf/github_project/build-my-agent/flywheel && uv run pytest tests/api/test_pipeline.py -v`
Expected: FAIL — `promote_cases()` still calls `_langfuse.create_dataset`/`_write_langfuse_dataset`, and since `langfuse=None` in this test's `configure()` call, the route currently raises `HTTPException(503, "Langfuse client not configured.")` before ever reaching the promote logic — assert this is the failure you see (503, not the expected 200), confirming the old Langfuse-required gate is what's under test here.

- [ ] **Step 3: Rewrite `promote_cases()`**

Replace the whole `promote_cases` function body (keep the `@router.post("/promote")` decorator and `PromoteRequest` model as-is):

```python
@router.post("/promote")
def promote_cases(body: PromoteRequest) -> dict[str, Any]:
    if not body.trace_ids:
        raise HTTPException(400, "trace_ids must not be empty.")

    from scripts.common import Case, append_case, cases_path, load_cases, state_root, read_json

    path = state_root(_root, _project) / "sample_traces.json"
    if not path.exists():
        raise HTTPException(400, "No sampled traces. Run /sample first.")
    raw = read_json(path)
    traces = raw.get("traces", raw) if isinstance(raw, dict) else raw
    selected_ids = set(body.trace_ids)
    selected = [t for t in traces if str(t.get("id", "")) in selected_ids]
    if not selected:
        raise HTTPException(400, "None of the given trace_ids were found in sample_traces.json.")

    existing_ids = {c.case_id for c in load_cases(cases_path(_root, _project))}
    promoted = 0
    skipped = 0
    for trace in selected:
        case_id = str(trace.get("id", ""))
        if case_id in existing_ids:
            skipped += 1
            continue
        append_case(
            _root, _project,
            Case(
                case_id=case_id,
                input=str(trace.get("input", "")),
                frozen_output=str(trace.get("output", "")),
                trace_url=_trace_url(case_id),
                expected_output="",
                label=None,
                critique="",
                failure_category=None,
                annotated_at="",
            ),
        )
        promoted += 1

    def _apply(state: ps.PipelineState) -> None:
        state.dataset.total_cases = len(existing_ids) + promoted
        state.dataset.last_updated = datetime.now(timezone.utc).isoformat()
        state.dataset.baseline_scored = False

    ps.mutate(_root, _project, _apply)

    return {"promoted": promoted, "skipped": skipped}
```

Add the `_trace_url` helper near the other module-level helpers (`_judge_version`, `_judge_model`, etc.):

```python
def _trace_url(trace_id: str) -> str:
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
    return f"{host.rstrip('/')}/trace/{trace_id}"
```

Remove the now-unused `PromoteRequest.dataset_name` field's only remaining consumer check — `dataset_name` stays on the request model for backward API compatibility with the existing frontend call shape (Task 9 will stop sending anything meaningful in it, but leaving the field accepted-and-ignored avoids an extra coordinated frontend+backend change in this task). Do not delete `dataset_name` from `PromoteRequest`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_pipeline.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full flywheel test suite**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check api/pipeline.py tests/api/test_pipeline.py && uv run mypy api/pipeline.py`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add api/pipeline.py tests/api/test_pipeline.py
git commit -m "feat(flywheel): promote writes local cases.jsonl instead of a Langfuse Dataset"
```

---

### Task 8: New `GET /api/pipeline/cases` and `POST /api/pipeline/cases/{case_id}/label`

**Files:**
- Modify: `api/pipeline.py`
- Modify: `tests/api/test_pipeline.py` (extend)

**Interfaces:**
- Produces: `GET /api/pipeline/cases` → `{"cases": [{caseId, input, frozenOutput, traceUrl, expectedOutput, label, critique, failureCategory, annotatedAt}, ...]}` (camelCase over HTTP, sorted by `case_id`). `POST /api/pipeline/cases/{case_id}/label` → body `{expectedOutput, label, critique, failureCategory}`, returns the updated case in the same shape. Consumed by Task 10's frontend `api.ts`.

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_pipeline.py`:

```python
def test_get_cases_returns_camel_case_shape(tmp_path: Path) -> None:
    from scripts.common import Case, append_case

    append_case(tmp_path, "bourbon", Case(
        case_id="t1", input="hi", frozen_output="hello", trace_url="https://x/t1",
        expected_output="", label=None, critique="", failure_category=None, annotated_at="",
    ))
    client = TestClient(_app(tmp_path))
    response = client.get("/api/pipeline/cases")
    assert response.status_code == 200
    body = response.json()
    assert body["cases"] == [{
        "caseId": "t1", "input": "hi", "frozenOutput": "hello", "traceUrl": "https://x/t1",
        "expectedOutput": "", "label": None, "critique": "", "failureCategory": None,
        "annotatedAt": "",
    }]


def test_get_cases_empty_when_no_cases_file(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    response = client.get("/api/pipeline/cases")
    assert response.json() == {"cases": []}


def test_label_case_appends_and_returns_updated_case(tmp_path: Path) -> None:
    from scripts.common import Case, append_case

    append_case(tmp_path, "bourbon", Case(
        case_id="t1", input="hi", frozen_output="hello", trace_url="",
        expected_output="", label=None, critique="", failure_category=None, annotated_at="",
    ))
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/pipeline/cases/t1/label",
        json={
            "expectedOutput": "should say hi back",
            "label": "fail",
            "critique": "ignored greeting",
            "failureCategory": "off_topic",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["label"] == "fail"
    assert body["critique"] == "ignored greeting"
    assert body["annotatedAt"] != ""

    from scripts.common import cases_path, load_cases

    cases = load_cases(cases_path(tmp_path, "bourbon"))
    assert len(cases) == 1  # append-only, last-wins -- not duplicated on read
    assert cases[0].label == "fail"


def test_label_unknown_case_returns_404(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/pipeline/cases/nope/label",
        json={"expectedOutput": "x", "label": "pass", "critique": "", "failureCategory": None},
    )
    assert response.status_code == 404


def test_label_rejects_invalid_label_value(tmp_path: Path) -> None:
    from scripts.common import Case, append_case

    append_case(tmp_path, "bourbon", Case(
        case_id="t1", input="hi", frozen_output="hello", trace_url="",
        expected_output="", label=None, critique="", failure_category=None, annotated_at="",
    ))
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/pipeline/cases/t1/label",
        json={"expectedOutput": "x", "label": "maybe", "critique": "", "failureCategory": None},
    )
    assert response.status_code == 422  # pydantic literal validation
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_pipeline.py -v -k "test_get_cases or test_label_case or test_label_unknown or test_label_rejects"`
Expected: FAIL — `404 Not Found` for both routes (they don't exist yet).

- [ ] **Step 3: Implement the two endpoints**

Add near the top of `api/pipeline.py`, alongside the other `BaseModel` request classes:

```python
class LabelRequest(BaseModel):
    expected_output: str = Field(alias="expectedOutput")
    label: Literal["pass", "fail", "skip"]
    critique: str = ""
    failure_category: str | None = Field(default=None, alias="failureCategory")

    model_config = {"populate_by_name": True}
```

Add `Literal` to the existing `pydantic`/`typing` imports at the top of the file (`from typing import Any, Literal`).

Add a serialization helper and the two routes, placed after `get_samples()` and before the `# ── Promote ──` section:

```python
def _case_to_json(case: "Any") -> dict[str, Any]:
    return {
        "caseId": case.case_id,
        "input": case.input,
        "frozenOutput": case.frozen_output,
        "traceUrl": case.trace_url,
        "expectedOutput": case.expected_output,
        "label": case.label,
        "critique": case.critique,
        "failureCategory": case.failure_category,
        "annotatedAt": case.annotated_at,
    }


@router.get("/cases")
def get_cases() -> dict[str, Any]:
    from scripts.common import cases_path, load_cases

    cases = load_cases(cases_path(_root, _project))
    return {"cases": [_case_to_json(c) for c in cases]}


@router.post("/cases/{case_id}/label")
def label_case(case_id: str, body: LabelRequest) -> dict[str, Any]:
    from scripts.common import Case, append_case, cases_path, load_cases

    existing = {c.case_id: c for c in load_cases(cases_path(_root, _project))}
    current = existing.get(case_id)
    if current is None:
        raise HTTPException(404, f"unknown case_id {case_id!r}; promote it first")

    updated = Case(
        case_id=case_id,
        input=current.input,
        frozen_output=current.frozen_output,
        trace_url=current.trace_url,
        expected_output=body.expected_output,
        label=body.label,
        critique=body.critique,
        failure_category=body.failure_category,
        annotated_at=datetime.now(timezone.utc).isoformat(),
    )
    append_case(_root, _project, updated)
    return _case_to_json(updated)
```

`_case_to_json`'s parameter is annotated `"Any"` rather than `scripts.common.Case` because `scripts.common` is only importable after `serve.py`'s `sys.path` setup (same deferred-import constraint as every other `scripts.*` usage in this file — see the existing comment above `SampleRequest`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_pipeline.py -v`
Expected: PASS (all tests in the file, including Task 7's)

- [ ] **Step 5: Run the full flywheel test suite**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check api/pipeline.py tests/api/test_pipeline.py && uv run mypy api/pipeline.py`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add api/pipeline.py tests/api/test_pipeline.py
git commit -m "feat(flywheel): add GET /api/pipeline/cases and POST .../label endpoints"
```

---

### Task 9: Wire `pipeline.py`'s baseline/candidate/judge flows to the new scripts

**Files:**
- Modify: `api/pipeline.py`
- Modify: `api/pipeline_state.py`
- Modify: `tests/api/test_pipeline.py` (extend)

**Interfaces:**
- Consumes: the new `--cases-path`/`--target` CLI surfaces from Tasks 3–6.
- Produces: `run_baseline`, `judge_baseline`, `run_candidate`, `judge_and_compare` route handlers call the four scripts with the new flags; `DatasetInfo` drops `judge_test_cases`/`regression_cases` (meaningless without splits).

- [ ] **Step 1: Update `DatasetInfo`**

In `api/pipeline_state.py`, change:

```python
@dataclass
class DatasetInfo:
    name: str = ""
    total_cases: int = 0
    judge_test_cases: int = 0
    regression_cases: int = 0
    baseline_scored: bool = False
    last_updated: str = ""
```

to:

```python
@dataclass
class DatasetInfo:
    name: str = ""
    total_cases: int = 0
    baseline_scored: bool = False
    last_updated: str = ""
```

- [ ] **Step 2: Write the failing test for the script invocations**

Add to `tests/api/test_pipeline.py` (this test checks the exact CLI args passed to `tr.run_script`, using `monkeypatch` to intercept it rather than actually running scripts — follow the existing pattern for testing `tr.run_script` call sites in this codebase; if no such pattern exists yet, use `monkeypatch.setattr` on the `tr` module directly):

```python
def test_baseline_judge_invokes_frozen_target_not_split(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_script(python: str, scripts_dir: Path, script: str, *args: str) -> None:
        calls.append([script, *args])

    monkeypatch.setattr(pipeline.tr, "run_script", fake_run_script)

    state = ps.load(tmp_path, "bourbon")
    state.dataset.name = "bourbon-evals"
    ps.save(tmp_path, "bourbon", state)

    client = TestClient(_app(tmp_path))
    response = client.post("/api/pipeline/baseline/judge")
    assert response.status_code == 200

    import time
    for _ in range(50):
        if ps.load(tmp_path, "bourbon").task.status in ("done", "error"):
            break
        time.sleep(0.05)

    final_state = ps.load(tmp_path, "bourbon")
    assert final_state.task.status == "done", final_state.task.error

    run_judge_calls = [c for c in calls if c[0] == "run_judge.py"]
    assert any("--target" in c and "frozen" in c for c in run_judge_calls)
    assert not any("--split" in c for c in calls)
    assert not any("--dataset" in c for c in calls)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/api/test_pipeline.py::test_baseline_judge_invokes_frozen_target_not_split -v`
Expected: FAIL — current `judge_baseline()` still passes `--dataset`, `--split judge_test`, `--split regression`, etc.

- [ ] **Step 4: Rewrite `judge_baseline()`, `run_baseline()`, `run_candidate()`, `judge_and_compare()`**

Replace `judge_baseline()`'s `do_judge` inner function body:

```python
    def do_judge() -> None:
        jv = _judge_version()
        # Score every labeled case's frozen_output (continuous judge-quality signal)
        ps.update_task(_root, _project, phase="Judging labeled cases", done=0, total=2)
        tr.run_script(
            _python, _scripts_dir, "run_judge.py",
            "--project", _project,
            "--root", str(_root),
            "--target", "frozen",
            "--judge-version", jv,
            "--model", _judge_model(),
            "--prompt-version", _judge_prompt_version(),
        )
        # Score baseline harness run's live outputs
        ps.update_task(_root, _project, phase="Judging baseline run", done=1, total=2)
        tr.run_script(
            _python, _scripts_dir, "run_judge.py",
            "--project", _project,
            "--root", str(_root),
            "--target", "baseline",
            "--judge-version", jv,
            "--model", _judge_model(),
            "--prompt-version", _judge_prompt_version(),
        )
        # Validate judge (informational report, not a gate — see run task below)
        ps.update_task(_root, _project, phase="Validating judge", done=2, total=2)
        tr.run_script(
            _python, _scripts_dir, "validate_judge.py",
            "--project", _project,
            "--root", str(_root),
            "--judge-version", jv,
        )
        # Mark baseline as scored
        def _apply(s: ps.PipelineState) -> None:
            s.dataset.baseline_scored = True
            s.task.status = "done"
            s.task.done = 2
            s.task.total = 2
            s.task.phase = ""

        ps.mutate(_root, _project, _apply)
```

In `run_baseline()`'s `do_run` inner function, replace the `tr.run_script(...)` call's args (drop `"--dataset", state.dataset.name`):

```python
        try:
            tr.run_script(
                _python, _scripts_dir, "run_harness.py",
                "--project", _project,
                "--root", str(_root),
                "--model", _harness_model(),
                "--run-id", "baseline",
            )
        finally:
```

Also update `run_baseline()`'s own guard clause — it currently does `total = state.dataset.regression_cases or state.dataset.total_cases`; since `regression_cases` no longer exists, change to:

```python
    total = state.dataset.total_cases
```

Apply the same two changes (drop `--dataset`, use `state.dataset.total_cases` directly) to `run_candidate()`.

In `judge_and_compare()`'s `do_compare` inner function, update the three `tr.run_script` calls:

```python
    def do_compare() -> None:
        jv = _judge_version()
        # Judge candidate run's live outputs
        ps.update_task(_root, _project, phase="Judging candidate", done=0, total=2)
        tr.run_script(
            _python, _scripts_dir, "run_judge.py",
            "--project", _project,
            "--root", str(_root),
            "--target", run_id,
            "--judge-version", jv,
            "--model", _judge_model(),
            "--prompt-version", _judge_prompt_version(),
        )
        # Run regression comparison (no judge-passing gate -- see spec §2)
        ps.update_task(_root, _project, phase="Comparing baseline vs candidate", done=1, total=2)
        tr.run_script(
            _python, _scripts_dir, "run_regression.py",
            "--project", _project,
            "--root", str(_root),
            "--baseline-run", "baseline",
            "--candidate-run", run_id,
            "--judge-version", jv,
        )
        # Read result from regression report...
```

(keep everything from `# Read result from regression report` onward unchanged — that block was already updated in an earlier session's work and doesn't reference splits).

Remove the now-deleted "Validate judge (re-validate to ensure it still passes)" `run_script` call for `validate_judge.py` inside `do_compare` if present — re-validating against `judge_test` doesn't apply anymore; skip straight from judging the candidate to comparing. Renumber the `total=` values in the `ps.update_task` calls above from 3 to 2 to match (two phases now, not three), and update the final `ps.update_task(_root, _project, status="done", done=3, total=3, ...)`-style call inside `_apply` at the end of `do_compare` to use `2` instead of `3`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_pipeline.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 6: Run the full flywheel test suite**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 7: Lint and type-check**

Run: `uv run ruff check api/pipeline.py api/pipeline_state.py tests/api/test_pipeline.py && uv run mypy api/pipeline.py api/pipeline_state.py`
Expected: both clean.

- [ ] **Step 8: Commit**

```bash
git add api/pipeline.py api/pipeline_state.py tests/api/test_pipeline.py
git commit -m "feat(flywheel): wire baseline/candidate/judge flows to Case-based scripts"
```

---

### Task 10: Frontend — `Case` type, `fetchCases`/`submitLabel` in `api.ts`

**Files:**
- Modify: `ui/src/api.ts`

**Interfaces:**
- Produces: `type Case = { caseId, input, frozenOutput, traceUrl, expectedOutput, label, critique, failureCategory, annotatedAt }`, `fetchCases(): Promise<{cases: Case[]}>`, `submitLabel(caseId: string, body: {expectedOutput, label, critique, failureCategory}): Promise<Case>`. Consumed by Task 11.

No automated frontend test infra exists in this repo (confirmed in the spec, §8) — this task is verified by a manual smoke check against the running dev server, done at the end of Task 11 once there's a UI to click through. This task alone only needs to type-check.

- [ ] **Step 1: Add the `Case` type and API functions**

In `ui/src/api.ts`, add near the other type definitions (after `LabelStatus`):

```typescript
export type CaseLabel = 'pass' | 'fail' | 'skip'

export type Case = {
  caseId: string
  input: string
  frozenOutput: string
  traceUrl: string
  expectedOutput: string
  label: CaseLabel | null
  critique: string
  failureCategory: string | null
  annotatedAt: string
}

export type CasesResult = {
  cases: Case[]
}

export type LabelSubmission = {
  expectedOutput: string
  label: CaseLabel
  critique: string
  failureCategory: string | null
}
```

Add near the other Pipeline API functions (after `startPromote`):

```typescript
export const fetchCases = () => fetchJson<CasesResult>('/api/pipeline/cases')

export const submitLabel = (caseId: string, body: LabelSubmission) =>
  postJson<Case>(`/api/pipeline/cases/${caseId}/label`, body)
```

- [ ] **Step 2: Type-check**

Run: `cd /home/hf/github_project/build-my-agent/flywheel/ui && npx tsc --noEmit`
Expected: no errors (the new exports aren't consumed by anything yet in this task, so there's nothing to break — this just confirms the new code itself is valid TypeScript).

- [ ] **Step 3: Commit**

```bash
git add ui/src/api.ts
git commit -m "feat(flywheel-ui): add Case type and cases/label API functions"
```

---

### Task 11: Frontend — `/label` route and `DatasetPanel` rewiring

**Files:**
- Modify: `ui/src/App.tsx`

**Interfaces:**
- Consumes: `fetchCases`, `submitLabel`, `Case`, `CaseLabel` from `ui/src/api.ts` (Task 10).

This is the largest single frontend change in the plan; it is kept as one task because the new `/label` route and the `DatasetPanel` rewiring are two small, tightly-related edits to the same file that are easiest to review together, and neither is independently useful without the other (a `/label` route nobody can navigate to from `DatasetPanel` is dead code; a `DatasetPanel` link to a route that doesn't exist is broken).

- [ ] **Step 1: Add the `LabelView` component and its route**

Add the import of the new API functions/types to the existing `import { ... } from './api'` block in `App.tsx`:

```typescript
  fetchCases,
  submitLabel,
  type Case,
  type CaseLabel,
```

Add the route in `Shell`'s `<Routes>` block:

```tsx
          <Route path="/label" element={<LabelView />} />
```

Add the nav link in `Shell`'s `<nav className="nav-links">`, between the `Control` and `History` links:

```tsx
          <NavLink to="/label">Label</NavLink>
```

Add the `LabelView` component (place it near `RunsView`, in a new `// ── Label view ──` section):

```tsx
// ── Label view ──────────────────────────────────────────────────────────────

function LabelView() {
  const qc = useQueryClient()
  const casesQuery = useQuery({ queryKey: ['cases'], queryFn: fetchCases })
  const cases = casesQuery.data?.cases ?? []

  const firstUnlabeledIndex = cases.findIndex((c) => c.label === null)
  const [index, setIndex] = useState(0)
  const [expectedOutput, setExpectedOutput] = useState('')
  const [critique, setCritique] = useState('')
  const [failureCategory, setFailureCategory] = useState('')

  const current = cases[index]

  const labelMutation = useMutation({
    mutationFn: (label: CaseLabel) => {
      if (!current) throw new Error('no case selected')
      return submitLabel(current.caseId, {
        expectedOutput,
        label,
        critique,
        failureCategory: failureCategory || null,
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases'] })
      qc.invalidateQueries({ queryKey: ['label-status'] })
      const next = cases.findIndex((c, i) => i > index && c.label === null)
      if (next >= 0) selectCase(next)
    },
  })

  function selectCase(i: number) {
    setIndex(i)
    const c = cases[i]
    setExpectedOutput(c?.expectedOutput ?? '')
    setCritique(c?.critique ?? '')
    setFailureCategory(c?.failureCategory ?? '')
  }

  function navigate(delta: number) {
    const next = index + delta
    if (next < 0 || next >= cases.length) return
    selectCase(next)
  }

  if (casesQuery.isLoading) return <PageState title="Loading cases" />
  if (!cases.length)
    return (
      <PageState
        title="No cases yet"
        detail="Sample and promote traces from Control before labeling."
        action={<Link to="/">Go to Control →</Link>}
      />
    )

  const startIndex = firstUnlabeledIndex >= 0 ? firstUnlabeledIndex : 0
  if (index === 0 && startIndex !== 0 && expectedOutput === '' && critique === '') {
    // Land on the first unlabeled case on initial load only.
    selectCase(startIndex)
  }

  return (
    <section className="page-section label-layout">
      <div className="label-strip">
        {cases.map((c, i) => (
          <button
            key={c.caseId}
            className={`label-strip-item ${i === index ? 'active' : ''}`}
            onClick={() => selectCase(i)}
          >
            {c.label ? '✓' : '○'} {c.caseId.slice(0, 8)}…
          </button>
        ))}
      </div>
      {current && (
        <div className="label-detail">
          <h3>Input</h3>
          <pre className="label-text">{current.input}</pre>
          <h3>Actual output (frozen)</h3>
          <pre className="label-text">{current.frozenOutput}</pre>
          <a href={current.traceUrl} target="_blank" rel="noreferrer">
            View original trace ↗
          </a>
          <h3>Expected output</h3>
          <textarea
            value={expectedOutput}
            onChange={(e) => setExpectedOutput(e.target.value)}
            rows={4}
          />
          <div className="label-buttons">
            <button
              className="button primary"
              disabled={labelMutation.isPending}
              onClick={() => labelMutation.mutate('pass')}
            >
              Pass
            </button>
            <button
              className="button secondary"
              disabled={labelMutation.isPending}
              onClick={() => labelMutation.mutate('fail')}
            >
              Fail
            </button>
            <button
              className="button secondary"
              disabled={labelMutation.isPending}
              onClick={() => labelMutation.mutate('skip')}
            >
              Skip
            </button>
          </div>
          <label>
            Critique (optional)
            <textarea value={critique} onChange={(e) => setCritique(e.target.value)} rows={2} />
          </label>
          <label>
            Failure category (optional)
            <input value={failureCategory} onChange={(e) => setFailureCategory(e.target.value)} />
          </label>
          <div className="label-nav">
            <button onClick={() => navigate(-1)} disabled={index === 0}>
              ← prev
            </button>
            <button onClick={() => navigate(1)} disabled={index === cases.length - 1}>
              next →
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
```

- [ ] **Step 2: Rewire `DatasetPanel`'s `LabelStatusRow`**

Replace `LabelStatusRow`'s body entirely:

```tsx
function LabelStatusRow() {
  const q = useQuery({
    queryKey: ['label-status'],
    queryFn: fetchCases,
    refetchInterval: 10_000,
  })
  const cases = q.data?.cases ?? []
  const total = cases.length
  const labeled = cases.filter((c) => c.label !== null).length
  const complete = labeled >= total && total > 0
  return (
    <div className="status-row">
      <span>{complete ? '✅' : '○'} Human labels</span>
      <span className="quiet">
        {labeled}/{total}
      </span>
      {!complete && (
        <Link to="/label" className="quiet-link">
          Label cases →
        </Link>
      )}
    </div>
  )
}
```

Update `DatasetPanel`'s stats row — remove the `judge_test`/`regression` `Stat`s (those fields no longer exist on `DatasetInfo`), replacing with a labeled-count stat sourced the same way:

```tsx
          <div className="dataset-stats">
            <Stat label="Dataset" value={dataset.name} mono />
            <Stat label="Total cases" value={String(dataset.totalCases)} />
          </div>
```

(This drops the two `<Stat label="judge_test" .../>` and `<Stat label="regression" .../>` lines — the per-case label progress is already shown by `LabelStatusRow` immediately below, so no replacement stat is needed here.)

- [ ] **Step 3: Type-check**

Run: `cd /home/hf/github_project/build-my-agent/flywheel/ui && npx tsc --noEmit`
Expected: no errors. If `PipelineState['dataset']` still types `judgeTestCases`/`regressionCases` as required fields anywhere (check `api.ts`'s `DatasetInfo` type, which mirrors the backend `DatasetInfo` dataclass from Task 9's `pipeline_state.py` change), remove those two fields from the TypeScript `DatasetInfo` type in `api.ts` too — they must be deleted on both sides together or `tsc` will report an unused-but-present mismatch against the backend's actual JSON shape (not a compile error, but a silent lie in the type; fix it here for correctness even though `tsc` alone won't catch it).

- [ ] **Step 4: Build**

Run: `npm run build`
Expected: succeeds, no TypeScript errors, no unused-import warnings (watch for `useState`/`useEffect` if any became unused by this edit — they should not, `useState` is used by `LabelView`).

- [ ] **Step 5: Manual smoke test**

Use the `/run` skill (or start the servers manually per `flywheel/api/serve.py`'s docstring) to launch the flywheel API and UI dev server against a scratch `FLYWHEEL_ROOT`. Walk through: Sample traces → Promote a few → navigate to `/label` → confirm the strip shows unlabeled cases, confirm `frozenOutput` and `input` render, submit a Pass/Fail/Skip label, confirm the strip checkmark updates and `DatasetPanel`'s "Human labels" count increments. Confirm `Run baseline harness` is still gated the same way as before (unaffected by this task).

- [ ] **Step 6: Commit**

```bash
git add ui/src/App.tsx ui/src/api.ts
git commit -m "feat(flywheel-ui): add /label route, rewire DatasetPanel to local case store"
```

---

## Self-Review Notes

**Spec coverage:** §3 architecture/data flow → Tasks 1–2 (storage) + Task 7 (promote) + Tasks 3–6 (scripts read from the new store). §4 `Case` schema → Task 1 (matches the spec's final six-field shape plus `frozen_output`, added during the spec's own self-review). §5.1 promote rewrite → Task 7. §5.2 new endpoints → Task 8. §5.3 script layer → Tasks 3–6. §6 `/label` UI → Tasks 10–11. §7 error handling (malformed line skip, dedup on promote, empty-pool `SystemExit`, lock-protected append) → covered in Tasks 1 (malformed line test), 7 (dedup test), 3–4 (`SystemExit` tests); lock-protected append reuses the `ps.mutate`-style lock pattern already in `pipeline_state.py` from this session's earlier fix — Task 8's `append_case` itself is not lock-wrapped in this plan. **Gap found and left as a known follow-up, not silently dropped:** `scripts/common.py`'s `append_case` (Task 1) has no lock around the file write, unlike `pipeline_state.py`'s `mutate()`. For a single React tab submitting one label at a time this is low-risk, but concurrent label submissions (two browser tabs) could interleave writes. Flagged here rather than fixed inline because it needs its own test (concurrent-write simulation) and touches Task 1 after Tasks 2–9 already depend on its exact signature — safer as an explicit fast-follow than a late signature change threaded back through six already-planned tasks. §9 migration (no migration, discard 5 old items) → no code task needed, it's a "don't do anything" decision, correctly not represented as a task. §10 deferred items → correctly excluded from this plan.

**Placeholder scan:** no TBD/TODO strings; every step has complete code. The one open item (`append_case` locking) is called out explicitly above as a scoped, named follow-up rather than a vague "add error handling" placeholder.

**Type consistency:** `Case`/`CaseLabel` field names are identical across Tasks 1–11 (`case_id`, `input`, `frozen_output`, `trace_url`, `expected_output`, `label`, `critique`, `failure_category`, `annotated_at` in Python; `caseId`, `input`, `frozenOutput`, `traceUrl`, `expectedOutput`, `label`, `critique`, `failureCategory`, `annotatedAt` in TypeScript) — checked against every task that constructs or reads a `Case`/`Case`-shaped JSON object. `load_dataset_items(explicit_path, root, project)`'s three-positional-argument signature from Task 2 is used identically in Tasks 3, 4, 5, 6 (no task calls it with the old two-argument form). `--cases-path`/`--target` flag names are consistent across Tasks 3–6 and Task 9's `tr.run_script` call sites.

**Scope check:** this is one linear feature (local case store replacing Langfuse Dataset dependency) with a strict dependency order — storage (1–2) → scripts (3–6) → API (7–9) → frontend (10–11). It was not split into separate specs during brainstorming because none of these layers is independently shippable or valuable without the others (a `/label` UI with no backend to call is useless; a rewritten `run_regression.py` with no way to promote cases into the new store has nothing to read). Kept as one plan, executed in strict task order.
