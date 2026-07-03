import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.common import Case, active_cases, append_case, cases_path, labeled_cases, load_cases


def _case(case_id: str, label: str | None = None, **overrides: object) -> Case:
    base: dict[str, object] = dict(
        case_id=case_id,
        input="input text",
        frozen_output="agent said X",
        trace_url=f"https://cloud.langfuse.com/trace/{case_id}",
        expected_output="",
        label=label,
        critique="",
        failure_category=None,
        annotated_at="",
    )
    base.update(overrides)
    return Case(**base)  # type: ignore[arg-type]


def test_cases_path_lives_under_state_root(tmp_path: Path) -> None:
    path = cases_path(tmp_path, "bourbon")
    assert path == tmp_path / "bourbon" / "state" / "cases.jsonl"


def test_append_then_load_round_trips(tmp_path: Path) -> None:
    append_case(tmp_path, "bourbon", _case("t1"))
    append_case(tmp_path, "bourbon", _case("t2", label="pass"))
    cases = load_cases(cases_path(tmp_path, "bourbon"))
    assert [c.case_id for c in cases] == ["t1", "t2"]
    assert cases[1].label == "pass"


def test_load_cases_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_cases(cases_path(tmp_path, "bourbon")) == []


def test_later_record_wins_for_same_case_id(tmp_path: Path) -> None:
    append_case(tmp_path, "bourbon", _case("t1", label=None))
    append_case(tmp_path, "bourbon", _case("t1", label="fail", critique="wrong tool"))
    cases = load_cases(cases_path(tmp_path, "bourbon"))
    assert len(cases) == 1
    assert cases[0].label == "fail"
    assert cases[0].critique == "wrong tool"


def test_malformed_line_is_skipped_not_fatal(tmp_path: Path, capsys: object) -> None:
    path = cases_path(tmp_path, "bourbon")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('not json\n{"case_id": "t1", "input": "i", "frozen_output": "o", '
                     '"trace_url": "", "expected_output": "", "label": null, '
                     '"critique": "", "failure_category": null, "annotated_at": ""}\n')
    cases = load_cases(path)
    assert [c.case_id for c in cases] == ["t1"]


def test_active_cases_excludes_skip(tmp_path: Path) -> None:
    cases = [_case("a", label="pass"), _case("b", label="skip"), _case("c", label=None)]
    assert [c.case_id for c in active_cases(cases)] == ["a", "c"]


def test_labeled_cases_only_pass_or_fail(tmp_path: Path) -> None:
    cases = [_case("a", label="pass"), _case("b", label="fail"), _case("c", label="skip"),
             _case("d", label=None)]
    assert [c.case_id for c in labeled_cases(cases)] == ["a", "b"]
