"""
sahm_rule.py
Vijfde model in analysis/ (zie nfci_interpretation.py, taylor_rule.py,
relative_strength.py en moving_average_deviation.py voor de eerste vier, en
die map se docstring voor de bredere uitleg van dit patroon: Python
berekent een citeerbaar, gevestigd model, de LLM narrate het resultaat --
hij schat nooit zelf in of iets "zorgelijk" is).

DE SAHM RULE (Claudia Sahm, 2019). Een recessie-indicator die op precies
een reeks draait die we toch al ophalen: het werkloosheidspercentage.

  Het 3-maands voortschrijdend gemiddelde van de werkloosheid ligt 0,50
  procentpunt of meer boven het LAAGSTE 3-maands gemiddelde van de
  voorgaande twaalf maanden.

Waarom dit model en niet iets ingewikkelders: het is met de hand na te
rekenen tegen de brongetallen, het heeft geen enkele vrije parameter die
wij hebben gekozen (de 0,50 en de vensters komen uit het gepubliceerde
model), en het vertaalt een niveau naar een toestand -- precies wat de
knoop `labor_tightness` uit de causale graaf (1.10) nodig heeft.

BELANGRIJKE NUANCE die de agent moet doorgeven en niet mag weglaten: de
Sahm Rule is beschrijvend, geen voorspelling. Hij identificeert dat een
recessie waarschijnlijk AL BEGONNEN is, niet dat er een aankomt. Sahm
zelf heeft er herhaaldelijk op gewezen dat het een historisch patroon is
en geen natuurwet.
"""

SAHM_THRESHOLD_PP = 0.50
"""De drempel uit het gepubliceerde model. BEWUST GEEN plaatshouder zoals
de tolerances in METRIC_SPECS: dit getal komt niet van ons en mag niet
"gekalibreerd" worden -- dan meet je een eigen model onder de naam van een
gevestigd model."""

MOVING_AVERAGE_MONTHS = 3
LOOKBACK_MONTHS = 12
MIN_OBSERVATIONS = MOVING_AVERAGE_MONTHS + LOOKBACK_MONTHS
"""15 maandelijkse waarnemingen: 3 voor het huidige gemiddelde, plus 12
voorgaande 3-maands gemiddelden om het minimum over te nemen."""


def compute_three_month_averages(unemployment_rates: list[float]) -> list[float]:
    """De reeks 3-maands voortschrijdende gemiddelden. Invoer is
    CHRONOLOGISCH: oudste waarde eerst, meest recente laatst. Bij minder dan
    drie waarden is er niets te middelen en komt er een lege lijst terug."""
    if len(unemployment_rates) < MOVING_AVERAGE_MONTHS:
        return []
    return [
        sum(unemployment_rates[i : i + MOVING_AVERAGE_MONTHS]) / MOVING_AVERAGE_MONTHS
        for i in range(len(unemployment_rates) - MOVING_AVERAGE_MONTHS + 1)
    ]


def compute_sahm_gap(unemployment_rates: list[float]) -> float | None:
    """Het verschil tussen het huidige 3-maands gemiddelde en het laagste
    3-maands gemiddelde van de voorgaande twaalf maanden, in procentpunten.

    Invoer CHRONOLOGISCH (oudste eerst). Geeft None bij minder dan
    MIN_OBSERVATIONS waarnemingen -- geen gok op een korter venster, want
    dan is het de Sahm Rule niet meer maar een eigen variant onder diens
    naam. Zelfde weiger-in-plaats-van-gokken-patroon als
    monetary_policy_agent.py::_fetch_taylor_rule_inputs()."""
    if len(unemployment_rates) < MIN_OBSERVATIONS:
        return None
    averages = compute_three_month_averages(unemployment_rates)
    current = averages[-1]
    preceding = averages[-(LOOKBACK_MONTHS + 1) : -1]
    return current - min(preceding)


def is_sahm_triggered(gap: float) -> bool:
    """Of de gap de gepubliceerde drempel haalt. Losse functie zodat de
    drempelvergelijking herleidbaar in de tests staat en niet verstopt zit
    in een agent."""
    return gap >= SAHM_THRESHOLD_PP


def describe_sahm_gap(gap: float) -> str:
    """Leesbare duiding van de gap, om als kant-en-klare claim aan de LLM
    mee te geven -- die moet dit LETTERLIJK overnemen in plaats van zelf in
    te schatten of de arbeidsmarkt verslechtert.

    De drie banden zijn een presentatiekeuze van ons (het gepubliceerde
    model kent alleen de drempel van 0,50), daarom expliciet benoemd als
    zodanig in de tekst."""
    if is_sahm_triggered(gap):
        return (
            f"Sahm Rule GETRIGGERD: het 3-maands gemiddelde van de werkloosheid ligt "
            f"{gap:.2f} procentpunt boven het laagste 3-maands gemiddelde van de "
            f"voorgaande twaalf maanden, op of boven de gepubliceerde drempel van "
            f"{SAHM_THRESHOLD_PP:.2f}. Historisch samenvallend met een recessie die "
            f"AL BEGONNEN is -- dit is een beschrijvende indicator, geen voorspelling."
        )
    if gap >= SAHM_THRESHOLD_PP / 2:
        return (
            f"Sahm Rule niet getriggerd, maar wel opgelopen: {gap:.2f} procentpunt boven "
            f"het laagste 3-maands gemiddelde van de voorgaande twaalf maanden "
            f"(drempel {SAHM_THRESHOLD_PP:.2f}). De indeling in banden is onze eigen "
            f"presentatiekeuze; het gepubliceerde model kent alleen de drempel."
        )
    return (
        f"Sahm Rule niet getriggerd: {gap:.2f} procentpunt boven het laagste 3-maands "
        f"gemiddelde van de voorgaande twaalf maanden (drempel {SAHM_THRESHOLD_PP:.2f})."
    )
