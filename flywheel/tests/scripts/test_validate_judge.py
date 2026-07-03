import json
import subprocess
import sys
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
    assert payload["validation_set_size"] == 2
