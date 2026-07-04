import pytest

from flywheel.regression import CaseScore, compare


def _scores(passes: int, fails: int) -> list[CaseScore]:
    return [CaseScore(f"c{i}", "pass") for i in range(passes)] + [
        CaseScore(f"d{i}", "fail") for i in range(fails)
    ]


def _run(labels: list[str]) -> list[CaseScore]:
    """One score per case c0..c{n-1}; labels are verdicts in order."""
    return [CaseScore(f"c{i}", lab) for i, lab in enumerate(labels)]  # type: ignore[arg-type]


def _cmp(
    base: list[CaseScore],
    cand: list[CaseScore],
    regression_case_ids: set[str] | None = None,
):
    ids = {s.case_id for s in base} if regression_case_ids is None else set(regression_case_ids)
    return compare(
        base,
        cand,
        regression_case_ids=ids,
        baseline_judge_version="jv1",
        candidate_judge_version="jv1",
    )


def test_clear_improvement_is_better() -> None:
    rep = _cmp(_run(["fail"] * 18 + ["pass"] * 2), _run(["pass"] * 18 + ["fail"] * 2))
    assert rep.result == "better"
    assert rep.delta > 0
    assert rep.delta_low <= rep.delta <= rep.delta_high


def test_tiny_delta_is_no_change() -> None:
    base = [CaseScore(f"c{i}", "pass" if i < 10 else "fail") for i in range(20)]
    cand = [CaseScore(f"c{i}", "pass" if i < 11 else "fail") for i in range(20)]
    assert _cmp(base, cand).result == "no_change"


def test_regression_is_worse() -> None:
    assert (
        _cmp(_run(["pass"] * 18 + ["fail"] * 2), _run(["fail"] * 18 + ["pass"] * 2)).result
        == "worse"
    )


def test_no_discordance_reports_finite_band_not_certainty() -> None:
    base = _run(["pass", "fail", "pass"])
    rep = _cmp(base, base)
    assert rep.result == "no_change"
    assert rep.delta == 0.0
    assert rep.delta_low < 0 < rep.delta_high


def test_small_one_sided_discordance_is_no_change() -> None:
    base = _run(["fail", "fail", "fail", "fail", "pass", "pass"])
    cand = _run(["pass", "pass", "pass", "pass", "pass", "pass"])
    assert _cmp(base, cand).result == "no_change"


def test_mismatched_judge_raises() -> None:
    s = _scores(5, 5)
    with pytest.raises(ValueError, match="same-judge"):
        compare(
            s,
            s,
            regression_case_ids={x.case_id for x in s},
            baseline_judge_version="jv1",
            candidate_judge_version="jv2",
        )


def test_invalid_judge_version_raises() -> None:
    with pytest.raises(ValueError, match="invalid judge_version"):
        compare(
            [CaseScore("a", "pass")],
            [CaseScore("a", "pass")],
            regression_case_ids={"a"},
            baseline_judge_version="judge:v1",
            candidate_judge_version="judge:v1",
        )


def test_mismatched_case_set_raises() -> None:
    with pytest.raises(ValueError, match="same regression case set"):
        _cmp([CaseScore("a", "pass")], [CaseScore("b", "pass")])


def test_incomplete_regression_set_raises() -> None:
    base = _run(["pass", "fail"])
    with pytest.raises(ValueError, match="regression set is incomplete"):
        _cmp(base, base, regression_case_ids={"c0", "c1", "c2"})


def test_duplicate_case_id_raises() -> None:
    dup = [CaseScore("a", "pass"), CaseScore("a", "fail")]
    with pytest.raises(ValueError, match="duplicate case_id"):
        _cmp(dup, dup)


def test_invalid_label_raises() -> None:
    with pytest.raises(ValueError, match="invalid label"):
        CaseScore("a", "PASS")  # type: ignore[arg-type]


def test_empty_regression_set_raises() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        _cmp([], [])


def test_fixed_and_newly_broken_tracked() -> None:
    base = [CaseScore("a", "fail"), CaseScore("b", "pass")]
    cand = [CaseScore("a", "pass"), CaseScore("b", "fail")]
    rep = _cmp(base, cand)
    assert "a" in rep.fixed and "b" in rep.newly_broken


def test_per_label_failure_counts() -> None:
    base = [CaseScore("a", "fail", "tool_misuse"), CaseScore("b", "fail", "tool_misuse")]
    cand = [CaseScore("a", "pass"), CaseScore("b", "fail", "tool_misuse")]
    rep = _cmp(base, cand)
    row = next(r for r in rep.per_label if r["label"] == "tool_misuse")
    assert row["baseline"] == 2 and row["candidate"] == 1


def test_unlabeled_non_pass_is_bucketed_not_dropped() -> None:
    base = [CaseScore("a", "fail"), CaseScore("b", "fail", "tool_misuse")]
    cand = [CaseScore("a", "fail"), CaseScore("b", "pass")]
    rows = {r["label"]: r for r in _cmp(base, cand).per_label}
    assert rows["unlabeled"]["baseline"] == 1 and rows["unlabeled"]["candidate"] == 1
    assert rows["tool_misuse"]["baseline"] == 1 and rows["tool_misuse"]["candidate"] == 0


def test_aggregate_repeats_majority_vote() -> None:
    from flywheel.regression import aggregate_repeats

    runs = [
        CaseScore("a", "pass"),
        CaseScore("a", "pass"),
        CaseScore("a", "fail", "tool_misuse"),
        CaseScore("b", "fail", "tool_misuse"),
        CaseScore("b", "fail", "tool_misuse"),
        CaseScore("b", "pass"),
        CaseScore("c", "uncertain"),
        CaseScore("u", "uncertain"),
        CaseScore("u", "uncertain"),
        CaseScore("u", "pass"),
        CaseScore("k", "skip"),
        CaseScore("k", "skip"),
        CaseScore("k", "fail", "x"),
        CaseScore("t", "fail", "y"),
        CaseScore("t", "uncertain"),
    ]
    agg = {s.case_id: s for s in aggregate_repeats(runs)}
    assert agg["a"].label == "pass"
    assert agg["b"].label == "fail"
    assert agg["b"].failure_label == "tool_misuse"
    assert agg["c"].label == "uncertain"
    assert agg["u"].label == "uncertain"
    assert agg["k"].label == "skip"
    assert agg["t"].label == "fail"


def test_repeat_budget_equal_ok() -> None:
    from flywheel.regression import check_repeat_budgets

    base = [CaseScore("a", "pass")] * 3 + [CaseScore("b", "pass")]
    cand = [CaseScore("a", "fail")] * 3 + [CaseScore("b", "pass")]
    check_repeat_budgets(base, cand)


def test_repeat_budget_unequal_raises() -> None:
    from flywheel.regression import check_repeat_budgets

    with pytest.raises(ValueError, match="unequal repeat budget"):
        check_repeat_budgets([CaseScore("a", "pass")] * 3, [CaseScore("a", "pass")])


def test_repeat_budget_under_min_raises() -> None:
    from flywheel.regression import check_repeat_budgets

    with pytest.raises(ValueError, match="repeat once or >="):
        check_repeat_budgets([CaseScore("a", "pass")] * 2, [CaseScore("a", "pass")] * 2)
