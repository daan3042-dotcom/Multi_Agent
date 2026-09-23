import pytest

from analysis.moving_average_deviation import compute_deviation_from_average_pct, compute_moving_average


def test_compute_moving_average():
    assert compute_moving_average([4.0, 4.2, 4.1, 4.3, 4.0, 4.4]) == pytest.approx(4.1666, rel=1e-3)


def test_compute_deviation_from_average_pct_above_average():
    assert compute_deviation_from_average_pct(current_value=4.4, average=4.0) == pytest.approx(10.0)


def test_compute_deviation_from_average_pct_below_average():
    assert compute_deviation_from_average_pct(current_value=3.6, average=4.0) == pytest.approx(-10.0)


def test_compute_deviation_from_average_pct_at_average():
    assert compute_deviation_from_average_pct(current_value=4.0, average=4.0) == 0.0
