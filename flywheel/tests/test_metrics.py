import math

from flywheel.metrics import pass_rate, precision_recall_f1, wilson_interval


def test_prf1_basic() -> None:
    p, r, f1 = precision_recall_f1(tp=8, fp=2, fn=2)
    assert math.isclose(p, 0.8) and math.isclose(r, 0.8) and math.isclose(f1, 0.8)


def test_zero_division_safe() -> None:
    assert precision_recall_f1(0, 0, 0) == (0.0, 0.0, 0.0)


def test_wilson_brackets_point() -> None:
    ci = wilson_interval(successes=9, n=10)
    assert 0.0 <= ci.low < ci.point < ci.high <= 1.0
    assert math.isclose(ci.point, 0.9)


def test_wilson_empty_full_uncertainty() -> None:
    ci = wilson_interval(0, 0)
    assert (ci.point, ci.low, ci.high) == (0.0, 0.0, 1.0)


def test_pass_rate_counts_skip_as_attempt() -> None:
    assert math.isclose(pass_rate(["pass", "pass", "skip", "uncertain"]).point, 0.5)
