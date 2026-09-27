"""
sahm_rule.py
Vijfde model in analysis/ (zie nfci_interpretation.py, taylor_rule.py,
relative_strength.py, moving_average_deviation.py voor de eerdere, en die
map se docstring voor het bredere patroon). Eerste model voor de economic
agent (roadmap 2.7, lean pre-T0).

De Sahm Rule (Claudia Sahm, 2019; operationeel gebruikt door o.a. de
Hutchins Center/FRED SAHMREALTIME-reeks): een realtime recessie-indicator
op basis van de nationale werkloosheidsgraad (U3/UNRATE) zelf, geen apart
model met eigen parameters zoals de Taylor Rule -- puur een vergelijking
BINNEN dezelfde reeks:

    sahm_waarde = (3-maands-voortschrijdend-gemiddelde van UNRATE, nu)
                  - min(3-maands-voortschrijdend-gemiddelde van UNRATE)
                    over de afgelopen 12 maanden (incl. nu)

De regel signaleert het BEGIN van een recessie zodra sahm_waarde >= 0,50
procentpunt. Dit is de OFFICIEEL gepubliceerde drempel, geen zelfbedachte
tussenband -- zelfde soort citeerbare, vaste referentie als
nfci_interpretation.py's nulpunt.

Hier zelf berekend uit de ruwe maandelijkse UNRATE-observaties (CLAUDE.md-
regel 1: Python rekent) i.p.v. FRED's kant-en-klare SAHMREALTIME-reeks
1-op-1 over te nemen -- zelfde keuze als taylor_rule.py.
"""

from __future__ import annotations

SAHM_TRIGGER_THRESHOLD = 0.50  # procentpunt -- officiële drempel (Sahm, 2019)
MOVING_AVERAGE_MONTHS = 3
LOOKBACK_MONTHS = 12
# Minstens dit aantal maandelijkse observaties nodig: LOOKBACK_MONTHS
# opeenvolgende 3-maands-gemiddelden vergen LOOKBACK_MONTHS + (MOVING_
# AVERAGE_MONTHS - 1) ruwe maandpunten.
MINIMUM_OBSERVATIONS = LOOKBACK_MONTHS + MOVING_AVERAGE_MONTHS - 1


def compute_three_month_averages(monthly_rates: list[float]) -> list[float]:
    """Alle opeenvolgende 3-maands-voortschrijdende-gemiddelden van
    `monthly_rates` (OUDSTE EERST), in dezelfde volgorde als de input.
    Minder dan 3 punten -> lege lijst, geen gok op een te korte reeks."""
    if len(monthly_rates) < MOVING_AVERAGE_MONTHS:
        return []
    return [
        sum(monthly_rates[i - MOVING_AVERAGE_MONTHS + 1 : i + 1]) / MOVING_AVERAGE_MONTHS
        for i in range(MOVING_AVERAGE_MONTHS - 1, len(monthly_rates))
    ]


def compute_sahm_rule(monthly_rates: list[float]) -> float:
    """`monthly_rates`: maandelijkse UNRATE-waarden, OUDSTE EERST, minstens
    MINIMUM_OBSERVATIONS (14) observaties. Te weinig data -> ValueError,
    geen gok op een onvolledige reeks (zelfde principe als de rest van
    analysis/: nooit stilzwijgend een cijfer verzinnen op ontbrekende
    input)."""
    if len(monthly_rates) < MINIMUM_OBSERVATIONS:
        raise ValueError(
            f"Sahm Rule heeft minstens {MINIMUM_OBSERVATIONS} maandelijkse observaties nodig, "
            f"kreeg {len(monthly_rates)}"
        )
    averages = compute_three_month_averages(monthly_rates)
    current = averages[-1]
    trailing_window = averages[-LOOKBACK_MONTHS:]
    return current - min(trailing_window)


def is_sahm_rule_triggered(sahm_value: float) -> bool:
    return sahm_value >= SAHM_TRIGGER_THRESHOLD


def classify_sahm_rule(sahm_value: float) -> str:
    """Puur de officiële drempel -- geen zelfbedachte tussenbanden, zelfde
    aanpak als nfci_interpretation.py::classify_nfci()."""
    if is_sahm_rule_triggered(sahm_value):
        return f"recessie-signaal ACTIEF (Sahm Rule >= {SAHM_TRIGGER_THRESHOLD:.2f}pp)"
    return f"recessie-signaal niet actief (Sahm Rule < {SAHM_TRIGGER_THRESHOLD:.2f}pp)"
