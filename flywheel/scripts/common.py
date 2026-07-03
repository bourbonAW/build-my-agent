"""Shared helpers for Flywheel's local Bourbon/Langfuse glue scripts.

The scripts mirror the minimal data needed for deterministic reports under
`~/.flywheel/<project>/state/`. Langfuse remains the evidence system for traces,
datasets, scores, and annotations; the file mirror lets CI and local smoke runs
rebuild reports without write credentials in the browser.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, get_args

from flywheel.identity import Label, validate_judge_version
from flywheel.report import _safe_segment

CaseLabel = Literal["pass", "fail", "skip"]

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_ROOT = Path(os.environ.get("FLYWHEEL_ROOT", "~/.flywheel")).expanduser()
_SLUG_BAD = re.compile(r"[^A-Za-z0-9._@-]")


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


@dataclass(frozen=True)
class RunOutput:
    case_id: str
    run_id: str
    harness_id: str
    output: str
    trace_url: str
    repeat_index: int
    sample_id: str


@dataclass(frozen=True)
class ScoreRecord:
    case_id: str
    run_id: str
    judge_version: str
    model: str
    prompt_version: str
    label: Label
    critique: str
    trace_url: str
    sample_id: str

    def __post_init__(self) -> None:
        validate_judge_version(self.judge_version)
        if self.label not in get_args(Label):
            raise ValueError(f"invalid score label {self.label!r}; expected {get_args(Label)}")
        if not self.model:
            raise ValueError("score record missing judge model")
        if not self.prompt_version:
            raise ValueError("score record missing prompt_version")


def utc_timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def slugify(value: str) -> str:
    slug = _SLUG_BAD.sub("-", value).strip("-")
    return slug or "run"


def current_git_sha(workdir: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def state_root(root: Path, project: str) -> Path:
    path = Path(root) / _safe_segment(project) / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def create_langfuse_client() -> object:
    try:
        from langfuse import get_client

        return get_client()
    except ImportError:
        try:
            from langfuse import Langfuse

            return Langfuse()
        except ImportError as exc:
            raise RuntimeError(
                "Langfuse SDK is not installed. Install it in the environment or pass "
                "--dataset-json for local/CI smoke runs."
            ) from exc


def load_dataset_items(
    explicit_path: Path | None, root: Path, project: str
) -> list[Case]:
    """Load cases from an explicit JSONL path, or the project's default
    cases.jsonl if no explicit path is given."""
    path = explicit_path if explicit_path is not None else cases_path(root, project)
    return load_cases(path)


def run_outputs_path(root: Path, project: str, run_id: str) -> Path:
    return state_root(root, project) / "runs" / f"{_safe_segment(run_id)}.jsonl"


def run_metadata_path(root: Path, project: str, run_id: str) -> Path:
    return state_root(root, project) / "runs" / f"{_safe_segment(run_id)}.metadata.json"


def write_run_outputs(
    root: Path,
    project: str,
    run_id: str,
    outputs: list[RunOutput],
    metadata: dict[str, Any],
) -> None:
    path = run_outputs_path(root, project, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(asdict(output), sort_keys=True) for output in outputs) + "\n"
    )
    write_json(run_metadata_path(root, project, run_id), metadata)


def load_run_outputs(root: Path, project: str, run_id: str) -> list[RunOutput]:
    path = run_outputs_path(root, project, run_id)
    if not path.exists():
        raise FileNotFoundError(f"missing harness output mirror for run {run_id!r}: {path}")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [RunOutput(**row) for row in rows]


def load_run_metadata(root: Path, project: str, run_id: str) -> dict[str, Any]:
    path = run_metadata_path(root, project, run_id)
    return dict(read_json(path)) if path.exists() else {}


def _score_dir(root: Path, project: str, target: str) -> Path:
    path = state_root(root, project) / "scores" / _safe_segment(target)
    path.mkdir(parents=True, exist_ok=True)
    return path


def score_path(root: Path, project: str, target: str, judge_version: str) -> Path:
    return _score_dir(root, project, target) / f"{validate_judge_version(judge_version)}.jsonl"


def write_score_records(
    root: Path,
    project: str,
    target: str,
    judge_version: str,
    records: list[ScoreRecord],
) -> None:
    path = score_path(root, project, target, judge_version)
    path.write_text(
        "\n".join(json.dumps(asdict(record), sort_keys=True) for record in records) + "\n"
    )


def _read_score_file(path: Path) -> list[ScoreRecord]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [ScoreRecord(**row) for row in rows]


def load_score_records(
    root: Path,
    project: str,
    target: str,
    judge_version: str | None = None,
) -> tuple[list[ScoreRecord], str]:
    directory = _score_dir(root, project, target)
    if judge_version is not None:
        path = score_path(root, project, target, judge_version)
        if not path.exists():
            raise FileNotFoundError(
                f"missing scores for target {target!r}, judge {judge_version!r}"
            )
        records = _read_score_file(path)
        inferred = validate_judge_version(judge_version)
    else:
        paths = sorted(directory.glob("*.jsonl"))
        if not paths:
            raise FileNotFoundError(f"missing scores for target {target!r}")
        if len(paths) != 1:
            raise ValueError(
                f"target {target!r} carries mixed judge_version score files: "
                f"{[path.stem for path in paths]}"
            )
        inferred = validate_judge_version(paths[0].stem)
        records = _read_score_file(paths[0])

    versions = {record.judge_version for record in records}
    if versions != {inferred}:
        raise ValueError(
            f"score metadata has mixed or missing judge_version values: {sorted(versions)}"
        )
    models = {record.model for record in records}
    prompts = {record.prompt_version for record in records}
    if len(models) != 1 or len(prompts) != 1:
        raise ValueError("score metadata has mixed judge model or prompt_version values")
    return records, inferred


def one_score_per_case(
    records: list[ScoreRecord], expected_ids: set[str]
) -> dict[str, ScoreRecord]:
    by_case: dict[str, ScoreRecord] = {}
    for record in records:
        if record.case_id in by_case:
            raise ValueError(f"duplicate judge score for validation case {record.case_id!r}")
        by_case[record.case_id] = record
    missing = expected_ids - set(by_case)
    extra = set(by_case) - expected_ids
    if missing or extra:
        raise ValueError(
            f"score coverage mismatch: missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return by_case
