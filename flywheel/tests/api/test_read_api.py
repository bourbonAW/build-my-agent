from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.read_api import create_app
from flywheel.regression import CaseScore, compare
from flywheel.report import write_judge_report, write_regression_report
from flywheel.validate import LabeledCase, validate


def _client(tmp_path: Path) -> TestClient:
    runs = [
        {
            "runId": "run_1",
            "harness": "abc@m",
            "judgeVersion": "jv1",
            "judgeF1": None,
            "judgeValidated": None,
            "passRate": {"point": 0.5, "low": 0.3, "high": 0.7},
            "nonPassCount": 1,
            "createdAt": "2026-06-24",
            "langfuseRunUrl": "http://lf/r/run_1",
        }
    ]
    app = create_app(tmp_path, project="bourbon", runs_provider=lambda project: runs)
    return TestClient(app)


def test_list_runs_returns_bare_array(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/api/runs")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert body[0]["runId"] == "run_1"
    assert set(body[0]) >= {
        "runId",
        "harness",
        "judgeVersion",
        "judgeF1",
        "judgeValidated",
        "passRate",
        "nonPassCount",
        "createdAt",
        "langfuseRunUrl",
    }


def test_get_regression_report(tmp_path: Path) -> None:
    rep = compare(
        [CaseScore("a", "fail", "tool_misuse")],
        [CaseScore("a", "pass")],
        regression_case_ids={"a"},
        baseline_judge_version="jv1",
        candidate_judge_version="jv1",
    )
    write_regression_report(
        tmp_path, "bourbon", "run_1", rep, baseline_harness="abc@m", candidate_harness="def@m"
    )
    body = _client(tmp_path).get("/api/runs/run_1").json()
    assert set(body) >= {
        "runId",
        "baselineHarness",
        "candidateHarness",
        "judgeVersion",
        "passRate",
        "nonPassCount",
        "passRateDelta",
        "result",
        "perLabel",
        "fixed",
        "newlyBroken",
    }
    assert set(body["passRateDelta"]) == {"point", "low", "high"}
    assert set(body["passRate"]) == {"point", "low", "high"}
    assert body["result"] in ("better", "no_change", "worse")
    assert set(body["fixed"][0]) == {"caseId", "traceUrl"}
    assert set(body["perLabel"][0]) == {"label", "baseline", "candidate"}


def test_get_judge_report(tmp_path: Path) -> None:
    rep = validate(
        [LabeledCase("a", "fail", "fail"), LabeledCase("b", "pass", "pass")],
        judge_version="jv1",
        model="m",
        prompt_version="p",
    )
    write_judge_report(tmp_path, "bourbon", rep)
    body = _client(tmp_path).get("/api/judges/jv1").json()
    assert set(body) == {
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
    assert body["judgeVersion"] == "jv1"
    assert isinstance(body["passes"], bool)
    assert set(body["confusion"]) == {"tp", "fp", "fn", "tn"}
    assert set(body["perLabel"][0]) == {"label", "precision", "recall", "f1"}


def test_missing_report_404(tmp_path: Path) -> None:
    assert _client(tmp_path).get("/api/runs/nope").status_code == 404
    assert _client(tmp_path).get("/api/judges/nope").status_code == 404


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    assert _client(tmp_path).get("/api/runs/..%2f..%2fsecret").status_code == 404


def test_unsafe_project_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe id segment"):
        create_app(tmp_path, project="../../escape", runs_provider=lambda project: [])


def test_contained_path_guards_traversal_directly(tmp_path: Path) -> None:
    from api.read_api import _contained_path

    base = tmp_path / "reports" / "regression"
    base.mkdir(parents=True)
    assert _contained_path(base, "../../escape") is None
    assert _contained_path(base, "a/b") is None
    assert _contained_path(base, "run_1") == (base / "run_1.json").resolve()
