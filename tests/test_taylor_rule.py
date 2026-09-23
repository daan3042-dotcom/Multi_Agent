from analysis.taylor_rule import compute_output_gap_pct, compute_taylor_rule_rate


def test_compute_output_gap_pct_positive_when_above_potential():
    assert compute_output_gap_pct(actual_real_gdp=102.0, potential_real_gdp=100.0) == 2.0


def test_compute_output_gap_pct_negative_when_below_potential():
    assert compute_output_gap_pct(actual_real_gdp=98.0, potential_real_gdp=100.0) == -2.0


def test_compute_taylor_rule_rate_known_example():
    # r*=2, inflatie=3%, doel=2%, output gap=0% -> 2 + 3 + 0.5(3-2) + 0.5(0) = 5.5
    rate = compute_taylor_rule_rate(inflation_yoy_pct=3.0, output_gap_pct=0.0)
    assert rate == 5.5


def test_compute_taylor_rule_rate_with_negative_output_gap():
    # r*=2, inflatie=1.5%, doel=2%, output gap=-2% -> 2 + 1.5 + 0.5(1.5-2) + 0.5(-2) = 2.25
    rate = compute_taylor_rule_rate(inflation_yoy_pct=1.5, output_gap_pct=-2.0)
    assert rate == 2.25


def test_compute_taylor_rule_rate_respects_overridden_assumptions():
    rate_default = compute_taylor_rule_rate(inflation_yoy_pct=2.0, output_gap_pct=0.0)
    rate_override = compute_taylor_rule_rate(inflation_yoy_pct=2.0, output_gap_pct=0.0, r_star_pct=3.0)
    assert rate_override == rate_default + 1.0
