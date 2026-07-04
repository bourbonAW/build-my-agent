from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import pipeline


def _app(tmp_path: Path) -> FastAPI:
    pipeline.configure(tmp_path, "bourbon", langfuse=None, python="python3")
    app = FastAPI()
    app.include_router(pipeline.router)
    return app


def _write_sample_traces(tmp_path: Path, traces: list[dict[str, Any]]) -> None:
    from scripts.common import state_root, write_json

    path = state_root(tmp_path, "bourbon") / "sample_traces.json"
    write_json(path, {"traces": traces})


def test_promote_writes_local_cases_not_langfuse(tmp_path: Path) -> None:
    _write_sample_traces(tmp_path, [
        {"id": "trace-1", "input": "hi", "output": "hello there"},
        {"id": "trace-2", "input": "bye", "output": "goodbye"},
    ])
    client = TestClient(_app(tmp_path))

    response = client.post(
        "/api/pipeline/promote",
        json={"dataset_name": "unused", "trace_ids": ["trace-1", "trace-2"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["promoted"] == 2
    assert body["skipped"] == 0

    from scripts.common import cases_path, load_cases

    cases = load_cases(cases_path(tmp_path, "bourbon"))
    assert {c.case_id for c in cases} == {"trace-1", "trace-2"}
    trace1 = next(c for c in cases if c.case_id == "trace-1")
    assert trace1.input == "hi"
    assert trace1.frozen_output == "hello there"
    assert trace1.label is None


def test_promote_skips_already_promoted_case(tmp_path: Path) -> None:
    _write_sample_traces(tmp_path, [{"id": "trace-1", "input": "hi", "output": "hello"}])
    client = TestClient(_app(tmp_path))

    first = client.post(
        "/api/pipeline/promote",
        json={"dataset_name": "unused", "trace_ids": ["trace-1"]},
    )
    assert first.json()["promoted"] == 1

    second = client.post(
        "/api/pipeline/promote",
        json={"dataset_name": "unused", "trace_ids": ["trace-1"]},
    )
    assert second.json()["promoted"] == 0
    assert second.json()["skipped"] == 1

    from scripts.common import cases_path, load_cases

    cases = load_cases(cases_path(tmp_path, "bourbon"))
    assert len(cases) == 1  # not duplicated


def test_promote_without_sample_file_returns_400(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/pipeline/promote",
        json={"dataset_name": "unused", "trace_ids": ["trace-1"]},
    )
    assert response.status_code == 400


def test_get_cases_returns_camel_case_shape(tmp_path: Path) -> None:
    from scripts.common import Case, append_case

    append_case(tmp_path, "bourbon", Case(
        case_id="t1", input="hi", frozen_output="hello", trace_url="https://x/t1",
        expected_output="", label=None, critique="", failure_category=None, annotated_at="",
    ))
    client = TestClient(_app(tmp_path))
    response = client.get("/api/pipeline/cases")
    assert response.status_code == 200
    body = response.json()
    assert body["cases"] == [{
        "caseId": "t1", "input": "hi", "frozenOutput": "hello", "traceUrl": "https://x/t1",
        "expectedOutput": "", "label": None, "critique": "", "failureCategory": None,
        "annotatedAt": "",
    }]


def test_get_cases_empty_when_no_cases_file(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    response = client.get("/api/pipeline/cases")
    assert response.json() == {"cases": []}


def test_label_case_appends_and_returns_updated_case(tmp_path: Path) -> None:
    from scripts.common import Case, append_case

    append_case(tmp_path, "bourbon", Case(
        case_id="t1", input="hi", frozen_output="hello", trace_url="",
        expected_output="", label=None, critique="", failure_category=None, annotated_at="",
    ))
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/pipeline/cases/t1/label",
        json={
            "expectedOutput": "should say hi back",
            "label": "fail",
            "critique": "ignored greeting",
            "failureCategory": "off_topic",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["label"] == "fail"
    assert body["critique"] == "ignored greeting"
    assert body["annotatedAt"] != ""

    from scripts.common import cases_path, load_cases

    cases = load_cases(cases_path(tmp_path, "bourbon"))
    assert len(cases) == 1  # append-only, last-wins -- not duplicated on read
    assert cases[0].label == "fail"


def test_label_unknown_case_returns_404(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/pipeline/cases/nope/label",
        json={"expectedOutput": "x", "label": "pass", "critique": "", "failureCategory": None},
    )
    assert response.status_code == 404


def test_label_rejects_invalid_label_value(tmp_path: Path) -> None:
    from scripts.common import Case, append_case

    append_case(tmp_path, "bourbon", Case(
        case_id="t1", input="hi", frozen_output="hello", trace_url="",
        expected_output="", label=None, critique="", failure_category=None, annotated_at="",
    ))
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/pipeline/cases/t1/label",
        json={"expectedOutput": "x", "label": "maybe", "critique": "", "failureCategory": None},
    )
    assert response.status_code == 422  # pydantic literal validation
