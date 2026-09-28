"""
test_sahm_rule.py
Tests voor analysis/sahm_rule.py (roadmap 2.7, lean economic agent).

Patroon zoals de andere analysis-tests: een met de hand narekenbaar
"correct"-geval, plus de regressiegevallen die ertoe doen -- hier vooral
dat het model WEIGERT te rekenen op te weinig data in plaats van een
kortere variant te verzinnen onder de naam van een gepubliceerd model.
"""

import pytest

from src.analysis.sahm_rule import (
    LOOKBACK_MONTHS,
    MIN_OBSERVATIONS,
    SAHM_THRESHOLD_PP,
    compute_sahm_gap,
    compute_three_month_averages,
    describe_sahm_gap,
    is_sahm_triggered,
)


def test_drie_maands_gemiddelden_met_de_hand_naberekend():
    averages = compute_three_month_averages([4.0, 4.0, 4.0, 4.3, 4.6])
    # vensters: (4,4,4)=4.0  (4,4,4.3)=4.1  (4,4.3,4.6)=4.3
    assert averages == pytest.approx([4.0, 4.1, 4.3])


def test_te_weinig_waarden_geeft_geen_gemiddelden():
    assert compute_three_month_averages([4.0, 4.1]) == []


def test_stabiele_arbeidsmarkt_geeft_gap_nul():
    """Het correcte geval: werkloosheid staat 15 maanden stil, dus het
    huidige 3-maands gemiddelde is gelijk aan het laagste voorgaande."""
    gap = compute_sahm_gap([4.0] * MIN_OBSERVATIONS)
    assert gap == 0.0
    assert is_sahm_triggered(gap) is False


def test_oplopende_werkloosheid_triggert():
    """Twaalf maanden vlak op 3,5, daarna drie maanden oplopend naar 4,4.
    Huidig 3-maands gemiddelde = (3.8+4.1+4.4)/3 = 4.1; laagste voorgaande
    3-maands gemiddelde = 3.5. Gap = 0,60 >= 0,50."""
    rates = [3.5] * 12 + [3.8, 4.1, 4.4]
    gap = compute_sahm_gap(rates)
    assert gap is not None
    assert round(gap, 2) == 0.60
    assert is_sahm_triggered(gap) is True


def test_gap_net_onder_de_drempel_triggert_niet():
    """REGRESSIE op de drempelvergelijking zelf: 0,49 mag niet vuren, 0,50
    (de gepubliceerde drempel) wel -- de vergelijking is >=, niet >."""
    assert is_sahm_triggered(SAHM_THRESHOLD_PP - 0.01) is False
    assert is_sahm_triggered(SAHM_THRESHOLD_PP) is True


def test_te_weinig_waarnemingen_geeft_none_in_plaats_van_een_gok():
    """REGRESSIE. Met minder dan 15 maanden is het de Sahm Rule niet meer.
    Een kortere terugblik zou een EIGEN variant zijn onder de naam van een
    gepubliceerd model -- precies het soort stille aanname dat dit project
    nergens accepteert."""
    assert compute_sahm_gap([4.0] * (MIN_OBSERVATIONS - 1)) is None
    assert compute_sahm_gap([]) is None


def test_exact_het_minimum_aantal_waarnemingen_rekent_wel():
    """De grens moet aan de goede kant liggen: 15 is genoeg, 14 niet."""
    assert compute_sahm_gap([4.0] * MIN_OBSERVATIONS) is not None
    assert MIN_OBSERVATIONS == LOOKBACK_MONTHS + 3


def test_alleen_de_voorgaande_twaalf_maanden_tellen_mee():
    """REGRESSIE. Een heel laag punt van VOOR het terugblikvenster mag de
    gap niet opblazen. Hier staat 2,0 helemaal vooraan; het venster van
    twaalf voorgaande 3-maands gemiddelden mag daar niet bij."""
    rates = [2.0, 2.0, 2.0] + [4.0] * 12 + [4.5, 4.5, 4.5]
    gap = compute_sahm_gap(rates)
    assert gap is not None
    assert gap < 1.0  # zou ~2,5 zijn als het oude dal wel meetelde


def test_omschrijving_benoemt_dat_het_beschrijvend_is():
    """De LLM krijgt deze tekst letterlijk mee. Bij een trigger MOET er in
    staan dat het om een al begonnen recessie gaat en niet om een
    voorspelling -- anders schrijft de deep-dive alsnog een prognose."""
    tekst = describe_sahm_gap(0.7)
    assert "GETRIGGERD" in tekst
    assert "AL BEGONNEN" in tekst
    assert "geen voorspelling" in tekst


def test_omschrijving_zonder_trigger_noemt_de_drempel():
    tekst = describe_sahm_gap(0.1)
    assert "niet getriggerd" in tekst
    assert "0.50" in tekst
