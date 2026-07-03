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
