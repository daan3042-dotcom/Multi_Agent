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
    # 15 waarnemingen sinds MINIMUM_OBSERVATIONS op 15 staat (besluit 28-09):
    # twaalf voorafgaande 3-maands-gemiddelden, het huidige telt niet mee.
    rates = [4.0] * 12 + [4.1, 4.1, 4.1]
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


def test_terugblikvenster_sluit_het_huidige_gemiddelde_uit():
    """REGRESSIE op het besluit van 28-09-2026 (DD): MINIMUM_OBSERVATIONS is
    15, want het venster bevat de twaalf VOORAFGAANDE 3-maands-gemiddelden
    en niet het huidige.

    Dit scenario laat zien waarom dat verschil telt. De werkloosheid daalt
    twaalf maanden lang en staat nu op haar laagste punt. Zou het huidige
    gemiddelde in het venster zitten, dan is het zelf het minimum en komt er
    per definitie 0,0 uit -- de indicator kan dan niet reageren op een
    stijging vanaf de bodem. Met het huidige gemiddelde buiten het venster
    wordt er altijd tegen het verleden vergeleken.

    Het getal bevriest bij T₀: erna verschuiven start een nieuw cohort in de
    scoring (roadmap 4.5), dus dit is geen detail om later 'even' bij te
    stellen."""
    dalend = [6.0, 5.8, 5.6, 5.4, 5.2, 5.0, 4.8, 4.6, 4.4, 4.2, 4.0, 3.8, 3.6, 3.4, 3.2]
    assert len(dalend) == MINIMUM_OBSERVATIONS

    waarde = compute_sahm_rule(dalend)
    assert waarde < 0  # huidig gemiddelde ligt ONDER elk voorafgaand gemiddelde
    assert is_sahm_rule_triggered(waarde) is False


def test_stijging_vanaf_de_bodem_wordt_gezien():
    """De keerzijde van het bovenstaande: twaalf maanden op een bodem,
    daarna een scherpe stijging. Het venster kijkt naar de bodem, dus de
    stijging is meteen zichtbaar."""
    rates = [3.5] * 12 + [3.9, 4.3, 4.7]
    waarde = compute_sahm_rule(rates)
    assert waarde == pytest.approx(0.80, abs=0.001)
    assert is_sahm_rule_triggered(waarde) is True
