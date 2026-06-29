from pathlib import Path

from api.runs_provider import list_runs
from flywheel.regression import CaseScore, compare
from flywheel.report import write_judge_report, write_regression_report
from flywheel.validate import LabeledCase, validate


class StubLangfuse:
    def __init__(self) -> None:
        self.metadata = {
            "run_pass": {
                "createdAt": "2026-06-24T10:00:00Z",
                "langfuseRunUrl": "http://lf/r/run_pass",
            },
            "run_fail": {
                "createdAt": "2026-06-24T11:00:00Z",
                "langfuseRunUrl": "http://lf/r/run_fail",
            },
            "run_missing_judge": {
                "createdAt": "2026-06-24T12:00:00Z",
                "langfuseRunUrl": "http://lf/r/run_missing_judge",
            },
            "run_without_report": {
                "createdAt": "2026-06-24T13:00:00Z",
                "langfuseRunUrl": "http://lf/r/run_without_report",
            },
        }

    def get_run_metadata(self, run_id: str) -> dict[str, object]:
        return self.metadata[run_id]


def _write_regression(
    tmp_path: Path, run_id: str, judge_version: str, candidate_label: str
) -> None:
    base = [CaseScore("a", "pass"), CaseScore("b", "fail", "tool_misuse")]
    cand = [CaseScore("a", candidate_label), CaseScore("b", "pass")]
    rep = compare(
        base,
        cand,
        regression_case_ids={"a", "b"},
        validation_case_ids=set(),
        baseline_judge_version=judge_version,
        candidate_judge_version=judge_version,
    )
    write_regression_report(
        tmp_path,
        "bourbon",
        run_id,
        rep,
        baseline_harness="base@m",
        candidate_harness=f"{run_id}@m",
    )


def test_list_runs_uses_report_backed_summaries_and_judge_reports(tmp_path: Path) -> None:
    _write_regression(tmp_path, "run_pass", "jv_pass", "fail")
    _write_regression(tmp_path, "run_fail", "jv_fail", "fail")
    _write_regression(tmp_path, "run_missing_judge", "jv_missing", "pass")

    passing = validate(
        [LabeledCase(f"f{i}", "fail", "fail") for i in range(5)]
        + [LabeledCase(f"p{i}", "pass", "pass") for i in range(5)],
        judge_version="jv_pass",
        model="m",
        prompt_version="p",
    )
    failing = validate(
        [LabeledCase(f"f{i}", "fail", "uncertain") for i in range(5)]
        + [LabeledCase(f"p{i}", "pass", "pass") for i in range(5)],
        judge_version="jv_fail",
        model="m",
        prompt_version="p",
    )
    write_judge_report(tmp_path, "bourbon", passing)
    write_judge_report(tmp_path, "bourbon", failing)

    rows = list_runs(tmp_path, "bourbon", langfuse=StubLangfuse())
    by_id = {row["runId"]: row for row in rows}

    assert set(by_id) == {"run_pass", "run_fail", "run_missing_judge"}
    assert by_id["run_pass"]["judgeF1"] == passing.f1
    assert by_id["run_pass"]["judgeValidated"] is True
    assert by_id["run_fail"]["judgeF1"] == failing.f1
    assert by_id["run_fail"]["judgeValidated"] is False
    assert by_id["run_missing_judge"]["judgeF1"] is None
    assert by_id["run_missing_judge"]["judgeValidated"] is None
    assert by_id["run_missing_judge"]["passRate"]["point"] == 1.0  # type: ignore[index]
    assert by_id["run_fail"]["nonPassCount"] == 1
    assert by_id["run_pass"]["createdAt"] == "2026-06-24T10:00:00Z"
    assert by_id["run_pass"]["langfuseRunUrl"] == "http://lf/r/run_pass"
