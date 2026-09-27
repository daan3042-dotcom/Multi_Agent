import pytest
from analysis.sahm_rule import (
    MINIMUM_OBSERVATIONS,
    compute_sahm_rule,
    compute_three_month_averages,
    classify_sahm_rule,
    is_sahm_rule_triggered,
)


def test_compute_three_month_averages_known_example():
    assert compute_three_month_averages([3.0, 4.0, 5.0, 6.0]) == [4.0, 5.0]


def test_compute_three_month_averages_too_short_returns_empty():
    assert compute_three_month_averages([3.0, 4.0]) == []


def test_compute_sahm_rule_zero_when_unemployment_flat():
    rates = [4.0] * MINIMUM_OBSERVATIONS
    assert compute_sahm_rule(rates) == 0.0


def test_compute_sahm_rule_positive_and_triggered_on_sharp_recent_rise():
    # Twaalf maanden stabiel op 3.5%, dan een scherpe stijging in de laatste
    # drie maanden -- het klassieke Sahm Rule-scenario (begin recessie).
    rates = [3.5] * 12 + [4.3, 4.6, 5.0]
    sahm_value = compute_sahm_rule(rates)
    assert sahm_value == pytest.approx(1.133, abs=0.001)
    assert is_sahm_rule_triggered(sahm_value) is True


def test_compute_sahm_rule_small_drift_not_triggered():
    rates = [4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.1, 4.1]
    sahm_value = compute_sahm_rule(rates)
    assert is_sahm_rule_triggered(sahm_value) is False


def test_compute_sahm_rule_raises_on_too_few_observations():
    with pytest.raises(ValueError):
        compute_sahm_rule([4.0] * (MINIMUM_OBSERVATIONS - 1))


def test_classify_sahm_rule_mentions_active_when_triggered():
    assert "ACTIEF" in classify_sahm_rule(0.6)


def test_classify_sahm_rule_mentions_not_active_when_below_threshold():
    label = classify_sahm_rule(0.1)
    assert "niet actief" in label
