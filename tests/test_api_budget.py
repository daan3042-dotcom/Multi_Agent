"""
test_api_budget.py
Bewaakt het dagelijkse API-callvolume (roadmap 1.11, "API-quota meten",
fase 0 vóór T₀ᵃ). De getallen hier horen één-op-één bij
`docs/data-sources.md`.

WAAROM DIT EEN TEST IS EN GEEN NOTITIE. Het systeem draait onbeheerd. Loopt
het volume tegen een quotum aan, dan mislukken de laatste agents van de
cyclus stil -- en het volume piekt precies op de dagen dat er veel
triggert, dus op de volatiele dagen. Een gat in de reeks dat samenhangt met
marktvolatiliteit is erger dan willekeurig ontbrekende data: dan ontbreken
systematisch de moeilijke weken en ziet het track record er beter uit dan
het is.

Een reeks toevoegen is één regel; het effect op het quotum is onzichtbaar
tot het een keer op de VPS omvalt. Deze test maakt dat effect zichtbaar op
het moment dat de regel geschreven wordt.
"""

from __future__ import annotations

from agents import (
    commodity_agent,
    currency_agent,
    economic_agent,
    financial_agent,
    monetary_policy_agent,
    sector_agent,
)

# Extra calls op deep-dive-tijd, uit de agent-implementaties:
#   Taylor Rule: CPI nu + CPI 12 maanden terug + GDPC1 + GDPPOT
#   Sahm Rule:   15 UNRATE-waarnemingen in ÉÉN call
TAYLOR_RULE_CALLS = 4
SAHM_RULE_CALLS = 1
SPY_REFERENTIE_CALLS = 1  # sector haalt SPY één keer op per deep-dive


def test_fred_monitoring_volume():
    """15 calls per dag. FRED is gratis en ruim; dit getal staat hier zodat
    het zichtbaar meegroeit, niet omdat het krap is."""
    fred = (
        len(monetary_policy_agent.FRED_SERIES)
        + len(financial_agent.FRED_SERIES)
        + len(economic_agent.FRED_SERIES)
    )
    assert fred == 15, (
        f"FRED-monitoringvolume is {fred}, docs/data-sources.md zegt 15. "
        f"Werk dat document in dezelfde ronde bij."
    )


def test_alpha_vantage_monitoring_volume():
    """24 calls per dag -- HET KNELPUNT. De gratis Alpha Vantage-tier ligt
    in de orde van 25 requests per dag (niet vanuit de ontwikkelomgeving te
    verifiëren, zie docs/data-sources.md), dus de monitoring alléén zit al
    tegen het plafond en elke deep-dive-dag gaat eroverheen.

    Stijgt dit getal, dan wordt het probleem groter; daalt het door een
    overstap naar een andere bron, dan hoort dit getal in dezelfde ronde
    omlaag."""
    alpha_vantage = (
        len(currency_agent.FX_PAIRS)
        + len(sector_agent.SECTOR_ETFS)
        + len(commodity_agent.COMMODITIES)
    )
    assert alpha_vantage == 24, (
        f"Alpha Vantage-monitoringvolume is {alpha_vantage}, "
        f"docs/data-sources.md zegt 24. Werk dat document in dezelfde ronde bij."
    )


def test_worst_case_volume_op_een_volatiele_dag():
    """Alles triggert, alle deep-dives draaien. Dit is het getal dat telt
    voor een quotum, niet het rustige-dag-getal -- en het valt samen met de
    dagen waarop we de data het hardst nodig hebben."""
    fred = (
        len(monetary_policy_agent.FRED_SERIES)
        + len(financial_agent.FRED_SERIES)
        + len(economic_agent.FRED_SERIES)
        + TAYLOR_RULE_CALLS
        + SAHM_RULE_CALLS
    )
    alpha_vantage = (
        len(currency_agent.FX_PAIRS)
        + len(sector_agent.SECTOR_ETFS)
        + len(commodity_agent.COMMODITIES)
        + len(sector_agent.SECTOR_ETFS)  # relatieve sterkte per getriggerde sector
        + SPY_REFERENTIE_CALLS
        + len(commodity_agent.COMMODITIES)  # voortschrijdend gemiddelde per grondstof
    )

    assert fred == 20
    assert alpha_vantage == 46


def test_sector_agent_is_de_grootverbruiker():
    """Vastgelegd omdat het de goedkoopste knop is als het quotum krap
    blijkt: 11 van de 24 monitoring-calls komen van één agent, en die haalt
    alleen dagelijkse slotkoersen op -- iets waar meerdere gratis bronnen
    met ruimere limieten voor bestaan (optie 2 in docs/data-sources.md)."""
    assert len(sector_agent.SECTOR_ETFS) == 11


def test_commodity_agent_haalt_maandelijkse_data_dagelijks_op():
    """Tien calls per dag voor een bron die maandelijks ververst. Dat is de
    duidelijkste verspilling in het budget, en tegelijk de reden dat deze
    agent in cohort 0 niet mag voorspellen (maandcadans is niet te resolven
    op 5/21/63 handelsdagen). Overstappen op een dagelijkse bron lost
    allebei tegelijk op -- zie docs/data-sources.md, optie 1."""
    assert len(commodity_agent.COMMODITIES) == 10
