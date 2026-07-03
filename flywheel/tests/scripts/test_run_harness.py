import json
import subprocess
import sys
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
            "--git-sha", "abc123",
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
