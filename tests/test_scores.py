"""
test_scores.py
Tests voor de scoringsregels (roadmap 4.5), `src/scoring/scores.py`.

DE BELANGRIJKSTE TEST HIER IS `test_eerlijkheid_loont`. Een scoringsregel
die niet 'proper' is, meet niet of een agent goed voorspelt maar of hij de
regel goed bespeelt -- en dat merk je nergens aan, want de getallen zien er
precies zo uit. Die eigenschap is de reden dat pinball en Brier gekozen
zijn, dus hij hoort getest te worden en niet aangenomen.
"""

from __future__ import annotations

import math
import random
from statistics import NormalDist

import pytest

from contract.prediction import QUANTILE_FIELDS, QUANTILE_LEVELS
from scoring.scores import (
    brier_score,
    crps_from_quantiles,
    log_loss,
    pinball_loss,
    pinball_losses,
    within_interval,
)


def _normaal(schaal: float) -> tuple[float, ...]:
    """De kwantielen op alle vijf niveaus van een normale verdeling met deze schaal."""
    nd = NormalDist()
    return tuple(schaal * nd.inv_cdf(t) for t in QUANTILE_LEVELS)


def test_perfecte_voorspelling_kost_niets():
    assert pinball_loss(0.5, 4.0, 4.0) == 0.0
    assert pinball_losses((4.0,) * 5, 4.0)["mean"] == 0.0
    assert crps_from_quantiles((4.0,) * 5, 4.0) == 0.0


def test_pinball_is_asymmetrisch_en_die_asymmetrie_is_het_punt():
    """Bij het 10%-kwantiel is te HOOG voorspellen negen keer zo duur als
    te laag. Daardoor is het optimaal om je echte 10%-punt op te schrijven
    en niet een veilige marge."""
    te_hoog = pinball_loss(0.10, 5.0, 4.0)   # werkelijk ligt 1 onder
    te_laag = pinball_loss(0.10, 3.0, 4.0)   # werkelijk ligt 1 boven
    assert te_hoog == pytest.approx(0.9)
    assert te_laag == pytest.approx(0.1)
    assert te_hoog == pytest.approx(9 * te_laag)

    # Bij het 90%-kwantiel precies andersom.
    assert pinball_loss(0.90, 3.0, 4.0) == pytest.approx(0.9)
    assert pinball_loss(0.90, 5.0, 4.0) == pytest.approx(0.1)


def test_mediaan_straft_beide_kanten_gelijk():
    assert pinball_loss(0.5, 3.0, 4.0) == pytest.approx(pinball_loss(0.5, 5.0, 4.0))


def test_eerlijkheid_loont():
    """De eigenschap waar alles op rust: wie zijn ECHTE verdeling opschrijft
    scoort gemiddeld beter dan wie iets anders opschrijft.

    Aanpak: trek een steekproef uit een bekende verdeling, en vergelijk de
    gemiddelde pinball loss van de echte kwantielen met die van een te
    smalle en een te brede opgave. Beide varianten horen te verliezen --
    overmoed én lafheid worden gestraft, en dat is precies wat een
    'proper' scoringsregel doet."""
    random.seed(20260928)
    steekproef = [random.gauss(0.0, 1.0) for _ in range(20000)]

    # Echte kwantielen (.1 .25 .5 .75 .9) van een standaardnormale verdeling.
    echt = _normaal(1.0)
    te_smal = _normaal(0.3)
    te_breed = _normaal(3.0)

    def gemiddeld(q):
        return sum(pinball_losses(q, y)["mean"] for y in steekproef) / len(steekproef)

    assert gemiddeld(echt) < gemiddeld(te_smal)
    assert gemiddeld(echt) < gemiddeld(te_breed)


def test_crps_is_tweemaal_de_gemiddelde_pinball():
    """Pint de gekozen benadering vast. Verandert deze relatie, dan zijn
    oude en nieuwe scores niet meer vergelijkbaar en hoort SCORER_VERSION
    omhoog."""
    q = (3.9, 4.0, 4.1, 4.25, 4.4)
    y = 4.25
    assert crps_from_quantiles(q, y) == pytest.approx(2 * pinball_losses(q, y)["mean"])


def test_de_crps_benadering_zit_dicht_bij_de_echte_crps():
    """Pint de meting van 01-10-2026 vast (de reden dat de vijf niveaus gelijk
    gewogen worden): voor een voorspeller die de echte verdeling kent zit de
    benadering binnen 5% van de echte CRPS (integraal over 40 niveaus). Met drie
    niveaus was het ~11%. Wordt dit slechter, dan is de weging aan herziening toe."""
    random.seed(20261001)
    steekproef = [random.gauss(0.0, 1.0) for _ in range(6000)]

    def gem(niveaus, waarden):
        return sum(
            sum(pinball_loss(t, w, y) for t, w in zip(niveaus, waarden)) / len(niveaus) for y in steekproef
        ) / len(steekproef)

    nd = NormalDist()
    fijn = [(i + 0.5) / 40 for i in range(40)]
    echt = 2 * gem(fijn, [nd.inv_cdf(t) for t in fijn])
    benadering = 2 * gem(QUANTILE_LEVELS, _normaal(1.0))
    assert abs(benadering / echt - 1) < 0.05


def test_de_interkwartielrange_telt_mee_in_de_score():
    """Waarom q25 en q75 erbij zijn gekomen: een voorspeller met de juiste q10/q50/q90 maar
    een te smalle kern scoort slechter dan een met de juiste kern. Met drie niveaus was dat
    verschil onzichtbaar."""
    random.seed(7)
    steekproef = [random.gauss(0.0, 1.0) for _ in range(20000)]
    goed = _normaal(1.0)
    smalle_kern = (goed[0], goed[1] * 0.3, goed[2], goed[3] * 0.3, goed[4])

    def gem(q):
        return sum(pinball_losses(q, y)["mean"] for y in steekproef) / len(steekproef)

    assert gem(goed) < gem(smalle_kern)


def test_een_verkeerd_aantal_kwantielen_wordt_geweigerd_en_niet_afgekapt():
    with pytest.raises(ValueError, match="5 kwantielen"):
        pinball_losses((3.9, 4.1, 4.4), 4.0)
    with pytest.raises(ValueError):
        crps_from_quantiles((1, 2, 3, 4, 5, 6), 3.0)


def test_de_vijf_niveaus_staan_op_een_plek_en_de_veldnamen_volgen():
    assert QUANTILE_LEVELS == (0.10, 0.25, 0.50, 0.75, 0.90)
    assert QUANTILE_FIELDS == ("q10", "q25", "q50", "q75", "q90")
    assert list(pinball_losses((1, 2, 3, 4, 5), 3.0)) == [*QUANTILE_FIELDS, "mean"]


def test_brier_en_log_loss_belonen_de_goede_kant():
    assert brier_score(0.9, True) < brier_score(0.5, True) < brier_score(0.1, True)
    assert log_loss(0.9, True) < log_loss(0.5, True) < log_loss(0.1, True)
    assert brier_score(0.5, True) == pytest.approx(0.25)
    assert log_loss(0.5, True) == pytest.approx(math.log(2))


def test_log_loss_straft_overmoed_veel_harder_dan_brier():
    """De reden dat we ze allebei bewaren. Een agent die 99% zegt en
    ernaast zit, kost onder Brier bijna evenveel als een die 90% zei --
    onder log loss een veelvoud."""
    brier_verhouding = brier_score(0.99, False) / brier_score(0.90, False)
    log_verhouding = log_loss(0.99, False) / log_loss(0.90, False)
    assert brier_verhouding < 1.3
    assert log_verhouding > 1.9


def test_absolute_zekerheid_geeft_een_eindig_maar_zwaar_verlies():
    """Regressiegeval: zonder afkapping geeft p=0 met een gebeurtenis die
    wél plaatsvindt oneindig verlies, en dan is het gemiddelde van een heel
    cohort onbruikbaar door één voorspelling."""
    verlies = log_loss(0.0, True)
    assert math.isfinite(verlies)
    assert verlies > 30
    assert log_loss(1.0, True) == pytest.approx(0.0, abs=1e-9)


def test_ongeldige_invoer_wordt_geweigerd():
    with pytest.raises(ValueError):
        brier_score(1.5, True)
    with pytest.raises(ValueError):
        log_loss(-0.1, False)
    with pytest.raises(ValueError):
        pinball_loss(0.0, 1.0, 1.0)


def test_within_interval_is_inclusief_aan_de_randen():
    assert within_interval(3.9, 4.4, 3.9)
    assert within_interval(3.9, 4.4, 4.4)
    assert not within_interval(3.9, 4.4, 4.41)
