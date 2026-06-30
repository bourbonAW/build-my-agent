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
from typing import Any, Iterable, Literal, cast, get_args

from flywheel.identity import HumanLabel, Label, validate_judge_version
from flywheel.regression import check_splits_disjoint
from flywheel.report import _safe_segment

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

Split = Literal["judge_train", "judge_dev", "judge_test", "regression"]
SPLITS: tuple[Split, ...] = ("judge_train", "judge_dev", "judge_test", "regression")
DEFAULT_ROOT = Path(os.environ.get("FLYWHEEL_ROOT", "~/.flywheel")).expanduser()
_SLUG_BAD = re.compile(r"[^A-Za-z0-9._@-]")


@dataclass(frozen=True)
class DatasetItem:
    case_id: str
    splits: tuple[Split, ...]
    input: str
    expected: str
    metadata: dict[str, Any]
    failure_label: str | None = None
    frozen_output: str | None = None
    human_label: HumanLabel | None = None
    trace_url: str = ""

    def in_split(self, split: Split) -> bool:
        return split in self.splits


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


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _metadata_from(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("metadata", {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"metadata must be an object for dataset item {record!r}")
    return dict(raw)


def _parse_splits(record: dict[str, Any], metadata: dict[str, Any]) -> tuple[Split, ...]:
    raw = record.get("splits", record.get("split", metadata.get("splits", metadata.get("split"))))
    if isinstance(raw, str):
        values: Iterable[Any] = [raw]
    elif isinstance(raw, list | tuple):
        values = raw
    else:
        raise ValueError(f"dataset item missing split label: {record!r}")

    out: list[Split] = []
    for value in values:
        if value not in SPLITS:
            raise ValueError(f"invalid split {value!r}; expected one of {SPLITS}")
        out.append(value)
    if not out:
        raise ValueError(f"dataset item has no split label: {record!r}")
    return tuple(out)


def _human_label(record: dict[str, Any], metadata: dict[str, Any]) -> HumanLabel | None:
    value = record.get(
        "human_label", record.get("human", metadata.get("human_label", metadata.get("human")))
    )
    if value is None:
        return None
    if value not in get_args(HumanLabel):
        raise ValueError(f"invalid human label {value!r}; expected {get_args(HumanLabel)}")
    return cast(HumanLabel, value)


def _record_from_langfuse_item(item: object) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name in ("id", "case_id", "input", "expected", "expected_output", "metadata", "output"):
        if hasattr(item, name):
            data[name] = getattr(item, name)
    return data


def _item_from_record(record: dict[str, Any]) -> DatasetItem:
    metadata = _metadata_from(record)
    case_id = str(record.get("case_id", record.get("id", metadata.get("case_id", ""))))
    if not case_id:
        raise ValueError(f"dataset item missing case id: {record!r}")
    expected = record.get(
        "expected",
        record.get("acceptance", record.get("expected_output", metadata.get("expected", ""))),
    )
    if expected == "":
        raise ValueError(f"dataset item {case_id!r} missing expected/acceptance text")
    frozen_output = record.get(
        "frozen_output",
        record.get("output", metadata.get("frozen_output", metadata.get("output"))),
    )
    return DatasetItem(
        case_id=case_id,
        splits=_parse_splits(record, metadata),
        input=_stringify(record.get("input", metadata.get("input", ""))),
        expected=_stringify(expected),
        metadata=metadata,
        failure_label=(
            None
            if record.get("failure_label", metadata.get("failure_label")) is None
            else str(record.get("failure_label", metadata.get("failure_label")))
        ),
        frozen_output=None if frozen_output is None else _stringify(frozen_output),
        human_label=_human_label(record, metadata),
        trace_url=str(record.get("trace_url", metadata.get("trace_url", ""))),
    )


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


def load_dataset_items(dataset_json: Path | None, dataset_name: str | None) -> list[DatasetItem]:
    if dataset_json is not None:
        payload = read_json(dataset_json)
        raw_items = (
            payload["items"] if isinstance(payload, dict) and "items" in payload else payload
        )
        if not isinstance(raw_items, list):
            raise ValueError("dataset JSON must be a list or an object with an 'items' list")
        return [_item_from_record(dict(item)) for item in raw_items]

    if not dataset_name:
        raise ValueError("pass --dataset-json or --dataset")

    client = create_langfuse_client()
    get_dataset = getattr(client, "get_dataset", None)
    if not callable(get_dataset):
        raise RuntimeError("Langfuse client does not expose get_dataset(); use --dataset-json")
    try:
        dataset = get_dataset(name=dataset_name)
    except TypeError:
        dataset = get_dataset(dataset_name)
    raw_items = getattr(dataset, "items", dataset)
    if callable(raw_items):
        raw_items = raw_items()
    if not isinstance(raw_items, list):
        raise RuntimeError("Langfuse dataset items were not returned as a list")
    return [_item_from_record(_record_from_langfuse_item(item)) for item in raw_items]


def split_sets(items: list[DatasetItem]) -> dict[str, set[str]]:
    return {split: {item.case_id for item in items if item.in_split(split)} for split in SPLITS}


def ensure_disjoint_splits(items: list[DatasetItem]) -> None:
    check_splits_disjoint(split_sets(items))


def items_for_split(items: list[DatasetItem], split: Split) -> list[DatasetItem]:
    return sorted((item for item in items if item.in_split(split)), key=lambda item: item.case_id)


def require_failure_labels(items: list[DatasetItem]) -> None:
    missing = [item.case_id for item in items if not item.failure_label]
    if missing:
        raise ValueError(f"regression items missing failure_label metadata: {missing}")


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
