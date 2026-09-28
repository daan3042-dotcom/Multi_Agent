"""
test_resolution_mapping.py
Bewaakt de koppeling tussen de resolution_rule (tekst, voor mensen) en de
resolution_method (enum, voor Python) -- roadmap 4.5.

WAAROM DIT NIET AUTOMATISCH TE CONTROLEREN IS. De regeltekst is vrije
taal; de methode is code. Dat die twee hetzelfde zeggen, is een menselijk
oordeel. Wat deze test wél kan: de afgesproken combinatie per doel
vastleggen, zodat een wijziging aan één van beide opvalt in plaats van
stilletjes een andere meting op te leveren.

DE FOUT DIE DIT MOET VANGEN. Iemand past een regeltekst aan ("laten we
toch de laatste revisie nemen") zonder de methode te wijzigen. De
voorspellingen blijven binnenkomen, de scores blijven plausibel, en pas bij
de evaluatie in mei blijkt dat de tekst iets anders belooft dan er gemeten
is. Op dat moment is er geen weg terug: evaluations kent geen update-pad.
"""

from __future__ import annotations

import pytest

from agents import (
    currency_agent,
    economic_agent,
    financial_agent,
    monetary_policy_agent,
    sector_agent,
)
from contract.prediction import HorizonKind
from contract.resolution import ResolutionMethod

AGENTS = {
    "monetary_policy": monetary_policy_agent,
    "currency": currency_agent,
    "financial": financial_agent,
    "sector": sector_agent,
    "economic": economic_agent,
}

# Vastgelegd op 28-09-2026. Per doel: welke methode is afgesproken.
VERWACHT: dict[str, dict[str, ResolutionMethod]] = {
    "monetary_policy": {
        "10y_treasury_yield": ResolutionMethod.LEVEL_AT_OR_AFTER,
        "2y_treasury_yield": ResolutionMethod.LEVEL_AT_OR_AFTER,
        "fed_funds_rate": ResolutionMethod.DIRECTION_AFTER_FOMC,
    },
    "currency": {
        "eur_usd": ResolutionMethod.LEVEL_AT_OR_AFTER,
        "usd_jpy": ResolutionMethod.LEVEL_AT_OR_AFTER,
        "gbp_usd": ResolutionMethod.LEVEL_AT_OR_AFTER,
    },
    "financial": {
        "high_yield_credit_spread": ResolutionMethod.LEVEL_AT_OR_AFTER,
        "vix": ResolutionMethod.LEVEL_AT_OR_AFTER,
        "yield_curve_10y_2y": ResolutionMethod.LEVEL_AT_OR_AFTER,
        "financial_conditions_index": ResolutionMethod.NTH_RELEASE,
    },
    "economic": {
        "initial_claims": ResolutionMethod.NTH_RELEASE,
        "unemployment_rate": ResolutionMethod.NTH_RELEASE,
        "nonfarm_payrolls": ResolutionMethod.NTH_RELEASE,
    },
}


@pytest.mark.parametrize("domain", sorted(VERWACHT))
def test_afgesproken_methode_per_doel(domain):
    werkelijk = {t.metric_key: t.resolution_method for t in AGENTS[domain].FORECAST_TARGETS}
    assert werkelijk == VERWACHT[domain]


def test_alle_sector_doelen_resolven_op_relatief_rendement():
    """Apart, omdat het er elf zijn en ze allemaal hetzelfde patroon
    volgen: de benchmark moet overal dezelfde sleutel zijn als waaronder
    SPY wordt opgeslagen, anders is geen enkel sector-doel te resolven."""
    doelen = sector_agent.FORECAST_TARGETS
    assert len(doelen) == 11
    for doel in doelen:
        assert doel.resolution_method is ResolutionMethod.RELATIVE_RETURN
        assert doel.benchmark_metric_key == sector_agent.BENCHMARK_KEY
    assert sector_agent.BENCHMARK_KEY in sector_agent.SECTOR_ETFS


def test_de_horizonsoort_past_bij_de_methode():
    """Een structurele controle die wél automatisch kan: een reeks die op
    publicaties telt, mag niet met een dagen-methode afgewikkeld worden en
    andersom. Die combinatie zou een horizon van '4 publicaties' als '4
    handelsdagen' meten."""
    dagen_methoden = {ResolutionMethod.LEVEL_AT_OR_AFTER, ResolutionMethod.RELATIVE_RETURN}
    release_methoden = {ResolutionMethod.NTH_RELEASE, ResolutionMethod.DIRECTION_AFTER_FOMC}

    for domain, module in AGENTS.items():
        for doel in module.FORECAST_TARGETS:
            if doel.horizon_kind is HorizonKind.TRADING_DAYS:
                assert doel.resolution_method in dagen_methoden, (domain, doel.metric_key)
            else:
                assert doel.resolution_method in release_methoden, (domain, doel.metric_key)


def test_de_regeltekst_noemt_waar_de_methode_op_let():
    """Zwakke maar goedkope controle op de koppeling: de tekst hoort het
    sleutelwoord van zijn methode te bevatten. Geen bewijs dat ze hetzelfde
    zeggen -- wel een vangnet tegen het plakken van een regeltekst onder de
    verkeerde methode."""
    sleutelwoorden = {
        ResolutionMethod.LEVEL_AT_OR_AFTER: ("op of na resolves_at",),
        ResolutionMethod.NTH_RELEASE: ("publicatie", "print"),
        ResolutionMethod.RELATIVE_RETURN: ("RELATIEVE", "MINUS"),
        ResolutionMethod.DIRECTION_AFTER_FOMC: ("FOMC",),
    }
    for domain, module in AGENTS.items():
        for doel in module.FORECAST_TARGETS:
            verwacht = sleutelwoorden[doel.resolution_method]
            assert any(w in doel.resolution_rule for w in verwacht), (
                f"{domain}/{doel.metric_key}: de regeltekst noemt geen van "
                f"{verwacht}, terwijl de methode {doel.resolution_method.value} is"
            )


def test_elk_doel_van_elke_voorspellende_agent_staat_hier():
    """Voorkomt dat een nieuw doel ongemerkt buiten deze controle valt --
    zelfde rol als de graafmapping-test voor de monitoring-reeksen."""
    gedekt = {d: set(v) for d, v in VERWACHT.items()}
    gedekt["sector"] = {t.metric_key for t in sector_agent.FORECAST_TARGETS}
    for domain, module in AGENTS.items():
        werkelijk = {t.metric_key for t in module.FORECAST_TARGETS}
        assert werkelijk == gedekt[domain], (
            f"{domain}: doelen zonder afgesproken resolutiemethode: "
            f"{werkelijk - gedekt[domain]}"
        )
