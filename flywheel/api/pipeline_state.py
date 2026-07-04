"""Pipeline state — persisted to ~/.flywheel/<project>/pipeline.json."""
from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

_lock = threading.Lock()


@dataclass
class DatasetInfo:
    name: str = ""
    total_cases: int = 0
    baseline_scored: bool = False
    last_updated: str = ""


@dataclass
class TaskInfo:
    type: str = "idle"
    # idle | sample | promote | baseline_harness | baseline_judge
    # | candidate_harness | judge_compare
    status: str = "idle"  # idle | running | done | error
    run_id: str = ""
    done: int = 0
    total: int = 0
    phase: str = ""   # human-readable step within a multi-phase task
    error: str = ""
    result: str = ""  # better | worse | no_change  (set after judge_compare)


@dataclass
class PipelineState:
    dataset: DatasetInfo = field(default_factory=DatasetInfo)
    task: TaskInfo = field(default_factory=TaskInfo)
    last_run_id: str = ""
    last_result: str = ""


def _state_path(root: Path, project: str) -> Path:
    from flywheel.report import _safe_segment
    return root / _safe_segment(project) / "pipeline.json"


def load(root: Path, project: str) -> PipelineState:
    path = _state_path(root, project)
    if not path.exists():
        return PipelineState()
    try:
        data = json.loads(path.read_text())
        ds = data.get("dataset", {})
        tk = data.get("task", {})
        ds_keys = set(DatasetInfo.__dataclass_fields__)
        tk_keys = set(TaskInfo.__dataclass_fields__)
        return PipelineState(
            dataset=DatasetInfo(**{k: v for k, v in ds.items() if k in ds_keys}),
            task=TaskInfo(**{k: v for k, v in tk.items() if k in tk_keys}),
            last_run_id=data.get("last_run_id", ""),
            last_result=data.get("last_result", ""),
        )
    except Exception:
        return PipelineState()


def save(root: Path, project: str, state: PipelineState) -> None:
    path = _state_path(root, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2) + "\n")


def mutate(root: Path, project: str, fn: Callable[[PipelineState], None]) -> PipelineState:
    """Atomically load, mutate in place via fn, and save. Serializes concurrent callers."""
    with _lock:
        state = load(root, project)
        fn(state)
        save(root, project, state)
        return state


def update_task(root: Path, project: str, **kwargs: object) -> None:
    def _apply(state: PipelineState) -> None:
        for k, v in kwargs.items():
            setattr(state.task, k, v)

    mutate(root, project, _apply)


def reset_stale_running(root: Path, project: str) -> None:
    """Clear a task left status='running' by a crash or restart from a prior process.

    Call once at server startup, before any request can observe or start a task.
    """

    def _apply(state: PipelineState) -> None:
        if state.task.status == "running":
            state.task.status = "error"
            state.task.error = "Interrupted by server restart"

    mutate(root, project, _apply)
