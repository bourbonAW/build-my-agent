"""Production RunSummary provider for the read API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flywheel.report import _safe_segment, read_json


def _reports_root(root: Path, project: str) -> Path:
    return Path(root) / _safe_segment(project) / "reports"


def _metadata_for(langfuse: object, run_id: str) -> dict[str, object]:
    for method_name in ("get_run_metadata", "run_metadata"):
        method = getattr(langfuse, method_name, None)
        if callable(method):
            result = method(run_id)
            if isinstance(result, dict):
                return {str(key): value for key, value in result.items()}
    return {}


def _read_optional_json(path: Path) -> dict[str, object] | None:
    return read_json(path) if path.exists() else None


def _string(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def list_runs(root: Path, project: str, *, langfuse: object) -> list[dict[str, Any]]:
    """Return report-backed RunSummary rows for one project.

    Only regression reports are enumerated, so every returned row opens at
    `/api/runs/{run_id}`. Langfuse is used only for metadata that Langfuse owns
    (`createdAt`, deep links, and optional harness fallbacks).
    """
    reports_root = _reports_root(root, project)
    regression_dir = reports_root / "regression"
    if not regression_dir.exists():
        return []

    rows: list[dict[str, Any]] = []
    for report_path in sorted(regression_dir.glob("*.json")):
        report = read_json(report_path)
        run_id = _string(report.get("runId"), report_path.stem)
        metadata = _metadata_for(langfuse, run_id)
        judge_version = _string(report.get("judgeVersion"))
        judge_report = _read_optional_json(
            reports_root / "judge" / f"{_safe_segment(judge_version)}.json"
        )

        rows.append(
            {
                "runId": run_id,
                "harness": _string(
                    metadata.get("harness"), _string(report.get("candidateHarness"))
                ),
                "judgeVersion": judge_version,
                "judgeF1": None if judge_report is None else judge_report.get("f1"),
                "judgeValidated": None if judge_report is None else judge_report.get("passes"),
                "passRate": report.get("passRate"),
                "nonPassCount": report.get("nonPassCount"),
                "createdAt": _string(metadata.get("createdAt")),
                "langfuseRunUrl": _string(metadata.get("langfuseRunUrl")),
            }
        )

    return sorted(rows, key=lambda row: str(row.get("createdAt", "")), reverse=True)
