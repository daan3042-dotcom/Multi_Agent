"""
test_horizons.py
Tests voor contract/horizons.py (roadmap 2.0/4.1).

Het punt van deze module is het onderscheid tussen `resolution_rule` (wat
er gescoord wordt, exact) en `resolves_at` (wanneer de resolver kijkt, een
schatting). De tests bewaken vooral dat de eerste niet stilzwijgend van de
tweede afhankelijk wordt gemaakt.
"""

from datetime import datetime, timezone

import pytest

from contract.horizons import (
    ReleaseCadence,
    add_trading_days,
    estimate_release_date,
    resolves_at_for,
)
from contract.prediction import HorizonKind

# Donderdag 1 oktober 2026
DONDERDAG = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def test_handelsdagen_slaan_het_weekend_over():
    """Donderdag + 1 = vrijdag, + 2 = maandag (niet zaterdag)."""
    assert add_trading_days(DONDERDAG, 1).weekday() == 4  # vrijdag
    assert add_trading_days(DONDERDAG, 2).weekday() == 0  # maandag


def test_vijf_handelsdagen_is_een_kalenderweek():
    resultaat = add_trading_days(DONDERDAG, 5)
    assert (resultaat - DONDERDAG).days == 7
    assert resultaat.weekday() == DONDERDAG.weekday()


def test_eenentwintig_handelsdagen_valt_nooit_in_het_weekend():
    """Ongeacht de startdag: de uitkomst is altijd een weekdag."""
    for dag in range(7):
        start = datetime(2026, 10, 5 + dag, 12, 0, tzinfo=timezone.utc)
        assert add_trading_days(start, 21).weekday() < 5


def test_start_in_het_weekend_telt_de_eerstvolgende_weekdag_als_dag_een():
    """Zaterdag + 1 handelsdag is maandag, niet zondag. Het weekend levert
    dus geen 'gratis' dag op.

    Let op wat hier NIET beweerd wordt: zaterdag + 5 komt op vrijdag uit en
    maandag + 5 op de maandag erna. Dat verschilt in kalenderdagen en dat
    hoort ook -- het zijn allebei precies vijf handelsdagen vanaf hun eigen
    startpunt. De forecast-ronde draait sowieso op een vaste weekdag."""
    zaterdag = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    zondag = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    assert add_trading_days(zaterdag, 1).weekday() == 0  # maandag
    assert add_trading_days(zondag, 1).weekday() == 0


def test_niet_positieve_horizon_geweigerd():
    with pytest.raises(ValueError):
        add_trading_days(DONDERDAG, 0)
    with pytest.raises(ValueError):
        estimate_release_date(DONDERDAG, ReleaseCadence.WEEKLY, -1)


# --- Releasehorizonnen ---


def test_wekelijkse_release_telt_de_publicatievertraging_mee():
    """ICSA verschijnt donderdag over de week die de zaterdag ervoor
    eindigde. Zonder die marge zou de resolver structureel te vroeg kijken
    en elke dag tevergeefs proberen."""
    een = estimate_release_date(DONDERDAG, ReleaseCadence.WEEKLY, 1)
    assert (een - DONDERDAG).days > 7


def test_maandelijkse_release_schaalt_met_n():
    een = estimate_release_date(DONDERDAG, ReleaseCadence.MONTHLY, 1)
    drie = estimate_release_date(DONDERDAG, ReleaseCadence.MONTHLY, 3)
    assert (drie - een).days > 55  # ruwweg twee maanden ertussen


def test_fomc_cadans_is_ruimer_dan_een_maand():
    """De Fed vergadert acht keer per jaar, dus gemiddeld ruim zes weken
    ertussen -- niet maandelijks."""
    fomc = estimate_release_date(DONDERDAG, ReleaseCadence.FOMC, 1)
    maand = estimate_release_date(DONDERDAG, ReleaseCadence.MONTHLY, 1)
    assert fomc > maand


# --- De gecombineerde ingang ---


def test_resolves_at_voor_dagreeks():
    resultaat = resolves_at_for(DONDERDAG, HorizonKind.TRADING_DAYS, 21)
    assert resultaat == add_trading_days(DONDERDAG, 21)


def test_resolves_at_voor_releasereeks():
    resultaat = resolves_at_for(DONDERDAG, HorizonKind.RELEASES, 4, ReleaseCadence.WEEKLY)
    assert resultaat == estimate_release_date(DONDERDAG, ReleaseCadence.WEEKLY, 4)


def test_releasehorizon_zonder_cadans_geweigerd():
    """REGRESSIE. Zonder cadans is er geen schatting te maken. Een gok zou
    de resolver dagenlang tevergeefs laten kijken, en dat is precies het
    soort stille verspilling dat onbeheerd draaien onbetrouwbaar maakt."""
    with pytest.raises(ValueError, match="cadence"):
        resolves_at_for(DONDERDAG, HorizonKind.RELEASES, 1)


def test_dagreeks_met_cadans_geweigerd():
    """De tegenhanger: een cadans meegeven bij een dagreeks wijst op
    verwarring over welke horizon bedoeld is."""
    with pytest.raises(ValueError, match="hoort niet"):
        resolves_at_for(DONDERDAG, HorizonKind.TRADING_DAYS, 5, ReleaseCadence.WEEKLY)


def test_resolves_at_ligt_altijd_na_created_at():
    """Het Prediction-contract weigert resolves_at <= created_at, dus elke
    combinatie hier moet daar doorheen komen."""
    for kind, n, cadans in [
        (HorizonKind.TRADING_DAYS, 5, None),
        (HorizonKind.TRADING_DAYS, 63, None),
        (HorizonKind.RELEASES, 1, ReleaseCadence.WEEKLY),
        (HorizonKind.RELEASES, 3, ReleaseCadence.MONTHLY),
        (HorizonKind.RELEASES, 2, ReleaseCadence.FOMC),
    ]:
        assert resolves_at_for(DONDERDAG, kind, n, cadans) > DONDERDAG
