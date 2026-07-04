"""Pipeline orchestration endpoints — controls the flywheel loop."""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api import pipeline_state as ps
from api import task_runner as tr

# `scripts` is only importable once serve.py's build_app() adds the flywheel
# dir to sys.path, so this stays a deferred import (like the ones inside the
# route handlers below) rather than a top-level one.

router = APIRouter(prefix="/api/pipeline")

# Injected by serve.py at startup
_root: Path = Path("~/.flywheel").expanduser()
_project: str = "bourbon"
_langfuse: Any = None
_python: str = "python"
_scripts_dir: Path = Path(__file__).resolve().parent.parent / "scripts"


def configure(
    root: Path,
    project: str,
    langfuse: Any = None,
    python: str = "python",
) -> None:
    global _root, _project, _langfuse, _python
    _root, _project, _langfuse, _python = root, project, langfuse, python


def _judge_version() -> str:
    return os.environ.get("FLYWHEEL_JUDGE_VERSION", "judge-v1")


def _judge_model() -> str:
    return os.environ.get("FLYWHEEL_JUDGE_MODEL", "claude-sonnet-4-6")


def _judge_prompt_version() -> str:
    return os.environ.get("FLYWHEEL_JUDGE_PROMPT_VERSION", "p1")


def _harness_model() -> str:
    return os.environ.get("FLYWHEEL_HARNESS_MODEL", _judge_model())


def _trace_url(trace_id: str) -> str:
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
    return f"{host.rstrip('/')}/trace/{trace_id}"


# ── State ──────────────────────────────────────────────────────────────────

@router.get("/state")
def get_state() -> dict[str, Any]:
    state = ps.load(_root, _project)
    return {
        "dataset": {
            "name": state.dataset.name,
            "totalCases": state.dataset.total_cases,
            "baselineScored": state.dataset.baseline_scored,
            "lastUpdated": state.dataset.last_updated,
        },
        "task": {
            "type": state.task.type,
            "status": state.task.status,
            "runId": state.task.run_id,
            "done": state.task.done,
            "total": state.task.total,
            "phase": state.task.phase,
            "error": state.task.error,
            "result": state.task.result,
        },
        "lastRunId": state.last_run_id,
        "lastResult": state.last_result,
    }


# ── Sample traces ──────────────────────────────────────────────────────────

class SampleRequest(BaseModel):
    limit: int = 30
    # Kept in sync with scripts.sample_traces.LANGFUSE_MAX_FETCH_LIMIT; enforced
    # for real (not just as a default) in sample_traces() below.
    fetch_limit: int = 100


@router.post("/sample")
def sample_traces(body: SampleRequest) -> dict[str, Any]:
    if _langfuse is None:
        raise HTTPException(503, "Langfuse client not configured. Set LANGFUSE_* env vars.")
    if tr.is_busy(_root, _project):
        raise HTTPException(409, "A task is already running.")

    from scripts.sample_traces import (
        LANGFUSE_MAX_FETCH_LIMIT,
        _fetch_recent_traces,
        _select_stratified,
    )
    from scripts.common import state_root, write_json

    if body.fetch_limit > LANGFUSE_MAX_FETCH_LIMIT:
        raise HTTPException(400, f"fetch_limit must be <= {LANGFUSE_MAX_FETCH_LIMIT}")

    def do_sample() -> None:
        recent = _fetch_recent_traces(_langfuse, body.fetch_limit)
        selected = _select_stratified(recent, body.limit)
        path = state_root(_root, _project) / "sample_traces.json"
        write_json(path, {"traces": selected})
        ps.update_task(_root, _project, status="done", done=len(selected), total=len(selected))

    tr.start(do_sample, _root, _project, "sample", total=body.limit)
    return {"started": True}


@router.get("/samples")
def get_samples() -> dict[str, Any]:
    from scripts.common import state_root, read_json
    path = state_root(_root, _project) / "sample_traces.json"
    if not path.exists():
        return {"traces": []}
    data = read_json(path)
    traces = data.get("traces", data) if isinstance(data, dict) else data
    return {"traces": traces}


class LabelRequest(BaseModel):
    expected_output: str = Field(alias="expectedOutput")
    label: Literal["pass", "fail", "skip"]
    critique: str = ""
    failure_category: str | None = Field(default=None, alias="failureCategory")

    model_config = {"populate_by_name": True}


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


# ── Promote ────────────────────────────────────────────────────────────────

class PromoteRequest(BaseModel):
    dataset_name: str
    trace_ids: list[str]


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


# ── Label status ───────────────────────────────────────────────────────────

@router.get("/label-status")
def label_status() -> dict[str, Any]:
    state = ps.load(_root, _project)
    if not state.dataset.name:
        return {"total": 0, "labeled": 0, "complete": False}

    if _langfuse is None:
        return {"total": state.dataset.total_cases, "labeled": 0, "complete": False}

    # Fetch dataset items from Langfuse and count those with a human_label score
    try:
        get_dataset = getattr(_langfuse, "get_dataset", None)
        if not callable(get_dataset):
            raise RuntimeError("no get_dataset")
        dataset = get_dataset(state.dataset.name)
        items = getattr(dataset, "items", [])
        total = len(items)

        # Count items that have a human_label score attached
        labeled = 0
        for item in items:
            scores = getattr(item, "scores", None) or []
            if any(getattr(s, "name", "") == "human_label" for s in scores):
                labeled += 1

        # Also update dataset case counts in state
        def _apply(s: ps.PipelineState) -> None:
            s.dataset.total_cases = total

        ps.mutate(_root, _project, _apply)

        return {
            "total": total,
            "labeled": labeled,
            "complete": labeled >= total > 0,
        }
    except Exception as exc:
        return {"total": state.dataset.total_cases, "labeled": 0, "complete": False, "error": str(exc)}


# ── Baseline harness ───────────────────────────────────────────────────────

@router.post("/baseline/run")
def run_baseline() -> dict[str, Any]:
    state = ps.load(_root, _project)
    if not state.dataset.name:
        raise HTTPException(400, "No dataset. Run sample + promote first.")
    if tr.is_busy(_root, _project):
        raise HTTPException(409, "A task is already running.")

    total = state.dataset.total_cases
    output_jsonl = _root / _project / "state" / "runs" / "baseline.jsonl"
    stop_event = threading.Event()

    def do_run() -> None:
        # Remove stale output so progress counter starts from 0
        if output_jsonl.exists():
            output_jsonl.unlink()

        poll_thread = threading.Thread(
            target=tr.poll_progress,
            args=(_root, _project, output_jsonl, total, stop_event),
            daemon=True,
        )
        poll_thread.start()
        try:
            tr.run_script(
                _python, _scripts_dir, "run_harness.py",
                "--project", _project,
                "--root", str(_root),
                "--model", _harness_model(),
                "--run-id", "baseline",
            )
        finally:
            stop_event.set()
            # Wait for the poller's in-flight update to land before writing the
            # final status, so a stale poll write can't race the "done" write
            # and revert it back to "running".
            poll_thread.join()

        done = tr.count_jsonl_lines(output_jsonl)
        ps.update_task(_root, _project, status="done", done=done, total=total)

    tr.start(do_run, _root, _project, "baseline_harness", run_id="baseline", total=total)
    return {"started": True}


# ── Baseline judge ─────────────────────────────────────────────────────────

@router.post("/baseline/judge")
def judge_baseline() -> dict[str, Any]:
    state = ps.load(_root, _project)
    if not state.dataset.name:
        raise HTTPException(400, "No dataset.")
    if tr.is_busy(_root, _project):
        raise HTTPException(409, "A task is already running.")

    def do_judge() -> None:
        jv = _judge_version()
        # Score every labeled case's frozen_output (continuous judge-quality signal)
        ps.update_task(_root, _project, phase="Judging labeled cases", done=0, total=3)
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
        ps.update_task(_root, _project, phase="Judging baseline run", done=1, total=3)
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
        ps.update_task(_root, _project, phase="Validating judge", done=2, total=3)
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
            s.task.done = 3
            s.task.total = 3
            s.task.phase = ""

        ps.mutate(_root, _project, _apply)

    tr.start(do_judge, _root, _project, "baseline_judge", total=3)
    return {"started": True}


# ── Candidate harness ──────────────────────────────────────────────────────

class EvalRunRequest(BaseModel):
    run_id: str


@router.post("/eval/run")
def run_candidate(body: EvalRunRequest) -> dict[str, Any]:
    state = ps.load(_root, _project)
    if not state.dataset.baseline_scored:
        raise HTTPException(400, "Baseline not scored. Complete baseline first.")
    if tr.is_busy(_root, _project):
        raise HTTPException(409, "A task is already running.")
    if not body.run_id:
        raise HTTPException(400, "run_id is required.")

    total = state.dataset.total_cases
    output_jsonl = _root / _project / "state" / "runs" / f"{body.run_id}.jsonl"
    stop_event = threading.Event()

    def do_run() -> None:
        if output_jsonl.exists():
            output_jsonl.unlink()

        poll_thread = threading.Thread(
            target=tr.poll_progress,
            args=(_root, _project, output_jsonl, total, stop_event),
            daemon=True,
        )
        poll_thread.start()
        try:
            tr.run_script(
                _python, _scripts_dir, "run_harness.py",
                "--project", _project,
                "--root", str(_root),
                "--model", _harness_model(),
                "--run-id", body.run_id,
            )
        finally:
            stop_event.set()
            poll_thread.join()

        done = tr.count_jsonl_lines(output_jsonl)

        def _finish(s: ps.PipelineState) -> None:
            s.last_run_id = body.run_id
            s.task.status = "done"
            s.task.done = done
            s.task.total = total

        ps.mutate(_root, _project, _finish)

    tr.start(do_run, _root, _project, "candidate_harness", run_id=body.run_id, total=total)
    return {"started": True}


# ── Judge + compare ────────────────────────────────────────────────────────

@router.post("/eval/judge-compare")
def judge_and_compare() -> dict[str, Any]:
    state = ps.load(_root, _project)
    if not state.last_run_id:
        raise HTTPException(400, "No candidate run yet.")
    if not state.dataset.baseline_scored:
        raise HTTPException(400, "Baseline not scored.")
    if tr.is_busy(_root, _project):
        raise HTTPException(409, "A task is already running.")

    run_id = state.last_run_id

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
        # Read result from regression report. Any failure here (missing/malformed
        # report) propagates out of do_compare and is recorded as a real task
        # error by tr.start()'s wrapper, instead of silently finishing as "done"
        # with an empty result.
        result = _read_regression_result(run_id)

        def _apply(s: ps.PipelineState) -> None:
            s.last_result = result
            s.task.status = "done"
            s.task.done = 2
            s.task.total = 2
            s.task.phase = ""
            s.task.result = result

        ps.mutate(_root, _project, _apply)

    tr.start(do_compare, _root, _project, "judge_compare", run_id=run_id, total=2)
    return {"started": True}


def _read_regression_result(run_id: str) -> str:
    from flywheel.report import read_json, _safe_segment
    path = _root / _safe_segment(_project) / "reports" / "regression" / f"{_safe_segment(run_id)}.json"
    if not path.exists():
        raise RuntimeError(f"regression report not found: {path}")
    data = read_json(path)
    return str(data.get("result", ""))
