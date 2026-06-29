"""Serialize reports to JSON consumed by the read API / frontend (UI §7)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .regression import RegressionReport
from .validate import JudgeReport

_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9._@-]+")


def _safe_segment(value: str) -> str:
    if not _SAFE_SEGMENT.fullmatch(value) or value in (".", ".."):
        raise ValueError(f"unsafe id segment: {value!r}")
    return value


def _reports_dir(root: Path, project: str, kind: str) -> Path:
    directory = Path(root) / _safe_segment(project) / "reports" / kind
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_regression_report(
    root: Path,
    project: str,
    run_id: str,
    report: RegressionReport,
    *,
    baseline_harness: str,
    candidate_harness: str,
    trace_urls: dict[str, str] | None = None,
    candidate_pr_url: str | None = None,
) -> Path:
    safe_run_id = _safe_segment(run_id)
    urls = trace_urls or {}

    def enrich(case_ids: list[str]) -> list[dict[str, str]]:
        return [{"caseId": case_id, "traceUrl": urls.get(case_id, "")} for case_id in case_ids]

    payload: dict[str, object] = {
        "runId": run_id,
        "baselineHarness": baseline_harness,
        "candidateHarness": candidate_harness,
        "judgeVersion": report.judge_version,
        "passRate": {
            "point": report.candidate_rate,
            "low": report.candidate_rate_low,
            "high": report.candidate_rate_high,
        },
        "nonPassCount": report.candidate_non_pass_count,
        "passRateDelta": {
            "point": report.delta,
            "low": report.delta_low,
            "high": report.delta_high,
        },
        "result": report.result,
        "perLabel": report.per_label,
        "fixed": enrich(report.fixed),
        "newlyBroken": enrich(report.newly_broken),
    }
    if candidate_pr_url is not None:
        payload["candidatePrUrl"] = candidate_pr_url
    path = _reports_dir(root, project, "regression") / f"{safe_run_id}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def write_regression_markdown(
    root: Path,
    project: str,
    run_id: str,
    report: RegressionReport,
    *,
    baseline_harness: str,
    candidate_harness: str,
    trace_urls: dict[str, str] | None = None,
    candidate_pr_url: str | None = None,
) -> Path:
    safe_run_id = _safe_segment(run_id)
    urls = trace_urls or {}

    def links(case_ids: list[str]) -> str:
        if not case_ids:
            return "-"
        return ", ".join(
            f"[{case_id}]({urls[case_id]})" if urls.get(case_id) else case_id
            for case_id in case_ids
        )

    lines = [
        f"# Regression report - {run_id}",
        "",
        f"- **Result:** {report.result}",
        f"- **Comparing:** {baseline_harness} -> {candidate_harness}",
        f"- **Judge:** {report.judge_version}",
        f"- **Pass rate:** {report.baseline_rate:.3f} -> {report.candidate_rate:.3f} "
        f"(delta {report.delta:+.3f}, descriptive band "
        f"[{report.delta_low:+.3f}, {report.delta_high:+.3f}]; gate = exact sign test)",
    ]
    if candidate_pr_url:
        lines.append(f"- **Candidate PR:** {candidate_pr_url}")
    lines += ["", "## Per-label failures", "", "| label | baseline | candidate |", "|---|---|---|"]
    lines += [
        f"| {row['label']} | {row['baseline']} | {row['candidate']} |" for row in report.per_label
    ]
    lines += [
        "",
        f"**Fixed ({len(report.fixed)}):** {links(report.fixed)}",
        f"**Newly broken ({len(report.newly_broken)}):** {links(report.newly_broken)}",
    ]
    path = _reports_dir(root, project, "regression") / f"{safe_run_id}.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def write_judge_report(root: Path, project: str, report: JudgeReport) -> Path:
    confusion = report.confusion
    payload = {
        "judgeVersion": report.judge_version,
        "model": report.model,
        "promptVersion": report.prompt_version,
        "f1": report.f1,
        "threshold": report.threshold,
        "passes": report.passes(),
        "goldFailCount": confusion["tp"] + confusion["fn"],
        "goldPassCount": confusion["fp"] + confusion["tn"],
        "minClassSupport": report.min_class_support,
        "perLabel": report.per_label,
        "confusion": report.confusion,
        "goldFailAbstained": report.gold_fail_abstained,
        "goldPassAbstained": report.gold_pass_abstained,
        "validationSetSize": report.validation_set_size,
    }
    path = _reports_dir(root, project, "judge") / f"{_safe_segment(report.judge_version)}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def read_json(path: Path) -> dict[str, object]:
    result: dict[str, object] = json.loads(Path(path).read_text())
    return result
