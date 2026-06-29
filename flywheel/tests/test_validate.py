import pytest

from flywheel.validate import LabeledCase, validate


def test_perfect_agreement_is_f1_1() -> None:
    cases = [LabeledCase(f"c{i}", "fail", "fail") for i in range(5)] + [
        LabeledCase(f"d{i}", "pass", "pass") for i in range(5)
    ]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 == 1.0
    assert rep.passes()


def test_insufficient_positive_support_does_not_gate() -> None:
    cases = [LabeledCase("a", "fail", "fail")] + [
        LabeledCase(f"d{i}", "pass", "pass") for i in range(9)
    ]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 == 1.0
    assert not rep.passes()


def test_below_threshold_does_not_pass() -> None:
    cases = [LabeledCase(f"c{i}", "fail", "pass") for i in range(8)] + [
        LabeledCase(f"d{i}", "pass", "pass") for i in range(2)
    ]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 < 0.70
    assert not rep.passes()


def test_confusion_counts() -> None:
    cases = [
        LabeledCase("a", "fail", "fail"),
        LabeledCase("b", "pass", "fail"),
        LabeledCase("c", "fail", "pass"),
        LabeledCase("d", "pass", "pass"),
    ]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert (rep.confusion["tp"], rep.confusion["fp"], rep.confusion["fn"], rep.confusion["tn"]) == (
        1,
        1,
        1,
        1,
    )
    assert rep.validation_set_size == 4


def test_uncertain_judge_is_a_miss_not_a_true_positive() -> None:
    cases = [LabeledCase("a", "fail", "uncertain"), LabeledCase("b", "pass", "pass")]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.confusion["tp"] == 0
    assert rep.confusion["fn"] == 1
    assert rep.gold_fail_abstained == 1
    assert rep.gold_pass_abstained == 0
    assert rep.validation_set_size == 2


def test_all_uncertain_judge_fails_gate() -> None:
    cases = [LabeledCase(f"c{i}", "fail", "uncertain") for i in range(8)] + [
        LabeledCase(f"d{i}", "pass", "uncertain") for i in range(2)
    ]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 == 0.0
    assert not rep.passes()


def test_always_fail_judge_fails_gate() -> None:
    cases = [LabeledCase(f"c{i}", "fail", "fail") for i in range(20)] + [
        LabeledCase(f"d{i}", "pass", "fail") for i in range(5)
    ]
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 < 0.70
    assert not rep.passes()


def test_partial_hedge_on_failures_fails_gate() -> None:
    cases = (
        [LabeledCase(f"f{i}", "fail", "fail") for i in range(2)]
        + [LabeledCase(f"g{i}", "fail", "uncertain") for i in range(3)]
        + [LabeledCase(f"p{i}", "pass", "pass") for i in range(5)]
    )
    rep = validate(cases, judge_version="jv1", model="m", prompt_version="p")
    assert rep.f1 >= 0.70
    assert not rep.passes()


def test_duplicate_case_id_rejected() -> None:
    cases = [LabeledCase("a", "fail", "fail")] * 5 + [LabeledCase("b", "pass", "pass")] * 5
    with pytest.raises(ValueError, match="duplicate case_id"):
        validate(cases, judge_version="jv1", model="m", prompt_version="p")


def test_invalid_labels_rejected() -> None:
    with pytest.raises(ValueError, match="invalid judge label"):
        LabeledCase("a", "fail", "PASS")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid human label"):
        LabeledCase("a", "skip", "pass")  # type: ignore[arg-type]


def test_validate_rejects_bad_judge_version() -> None:
    with pytest.raises(ValueError, match="invalid judge_version"):
        validate(
            [LabeledCase("a", "fail", "fail")],
            judge_version="judge/v1",
            model="m",
            prompt_version="p",
        )
