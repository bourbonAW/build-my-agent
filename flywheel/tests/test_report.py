from pathlib import Path

import pytest

from flywheel.regression import CaseScore, compare
from flywheel.report import read_json, write_regression_report


def test_regression_report_written_with_expected_keys(tmp_path: Path) -> None:
    base = [CaseScore("a", "fail", "tool_misuse"), CaseScore("b", "pass")]
    cand = [CaseScore("a", "pass"), CaseScore("b", "pass")]
    rep = compare(
        base,
        cand,
        regression_case_ids={"a", "b"},
        validation_case_ids=set(),
        baseline_judge_version="jv1",
        candidate_judge_version="jv1",
    )
    path = write_regression_report(
        tmp_path,
        "bourbon",
        "run_1",
        rep,
        baseline_harness="abc@m",
        candidate_harness="def@m",
        trace_urls={"a": "http://lf/t/a"},
    )
    assert path.exists()
    data = read_json(path)
    assert data["runId"] == "run_1"
    assert data["result"] in ("better", "no_change", "worse")
    assert data["judgeVersion"] == "jv1"
    assert data["fixed"][0]["caseId"] == "a"  # type: ignore[index]
    assert data["fixed"][0]["traceUrl"] == "http://lf/t/a"  # type: ignore[index]
    delta = data["passRateDelta"]
    assert delta["low"] <= delta["point"] <= delta["high"]  # type: ignore[index]
    pass_rate = data["passRate"]
    assert pass_rate["low"] <= pass_rate["point"] <= pass_rate["high"]  # type: ignore[index]
    assert data["nonPassCount"] == 0
    assert data["perLabel"][0]["label"] == "tool_misuse"  # type: ignore[index]


def test_regression_markdown_written(tmp_path: Path) -> None:
    from flywheel.report import write_regression_markdown

    base = [CaseScore("a", "fail", "tool_misuse"), CaseScore("b", "pass")]
    cand = [CaseScore("a", "pass"), CaseScore("b", "pass")]
    rep = compare(
        base,
        cand,
        regression_case_ids={"a", "b"},
        validation_case_ids=set(),
        baseline_judge_version="jv1",
        candidate_judge_version="jv1",
    )
    path = write_regression_markdown(
        tmp_path,
        "bourbon",
        "run_1",
        rep,
        baseline_harness="abc@m",
        candidate_harness="def@m",
    )
    text = path.read_text()
    assert path.suffix == ".md"
    assert "run_1" in text and rep.result in text and "tool_misuse" in text
    assert "abc@m" in text and "def@m" in text


def test_judge_report_written_with_expected_keys(tmp_path: Path) -> None:
    from flywheel.report import write_judge_report
    from flywheel.validate import LabeledCase, validate

    rep = validate(
        [LabeledCase("a", "fail", "fail"), LabeledCase("b", "pass", "pass")],
        judge_version="jv1",
        model="claude-opus-4-8",
        prompt_version="p1",
    )
    path = write_judge_report(tmp_path, "bourbon", rep)
    data = read_json(path)
    assert set(data) == {
        "judgeVersion",
        "model",
        "promptVersion",
        "f1",
        "threshold",
        "passes",
        "goldFailCount",
        "goldPassCount",
        "minClassSupport",
        "goldFailAbstained",
        "goldPassAbstained",
        "perLabel",
        "confusion",
        "validationSetSize",
    }
    assert data["judgeVersion"] == "jv1"
    assert data["confusion"]["tp"] == 1  # type: ignore[index]
    assert data["passes"] is False


def test_unsafe_run_id_rejected(tmp_path: Path) -> None:
    base = [CaseScore("a", "pass")]
    rep = compare(
        base,
        base,
        regression_case_ids={"a"},
        validation_case_ids=set(),
        baseline_judge_version="jv1",
        candidate_judge_version="jv1",
    )
    for bad in ("../../escape", "run\n", ".", ".."):
        with pytest.raises(ValueError, match="unsafe id segment"):
            write_regression_report(
                tmp_path, "bourbon", bad, rep, baseline_harness="a@m", candidate_harness="b@m"
            )
    with pytest.raises(ValueError, match="unsafe id segment"):
        write_regression_report(
            tmp_path, "../../escape", "run_1", rep, baseline_harness="a@m", candidate_harness="b@m"
        )
