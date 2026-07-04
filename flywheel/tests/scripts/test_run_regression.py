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
