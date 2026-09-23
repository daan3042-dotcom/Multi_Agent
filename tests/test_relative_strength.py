from analysis.relative_strength import classify_relative_strength, compute_relative_strength_pct


def test_compute_relative_strength_positive_when_sector_outperforms():
    assert compute_relative_strength_pct(sector_change_pct=2.0, benchmark_change_pct=0.5) == 1.5


def test_compute_relative_strength_negative_when_sector_underperforms():
    assert compute_relative_strength_pct(sector_change_pct=-3.0, benchmark_change_pct=-0.5) == -2.5


def test_classify_relative_strength_outperform():
    assert classify_relative_strength(1.5) == "outperformt de brede markt (S&P 500) vandaag"


def test_classify_relative_strength_underperform():
    assert classify_relative_strength(-2.5) == "underperformt de brede markt (S&P 500) vandaag"


def test_classify_relative_strength_exactly_equal():
    assert classify_relative_strength(0.0) == "presteert exact gelijk aan de brede markt (S&P 500) vandaag"
