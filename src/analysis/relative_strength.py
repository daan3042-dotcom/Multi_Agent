"""
relative_strength.py
Derde model in analysis/ (zie nfci_interpretation.py en taylor_rule.py
voor de eerste twee, en die map se docstring voor de bredere uitleg van
dit patroon). Relatieve sterkte: het verschil tussen het rendement van een
sector-ETF en het rendement van de bredere markt (S&P 500, via SPY) over
dezelfde periode -- een gevestigd concept in sector-rotatie-analyse.
Positief = de sector outperformt de markt (mogelijk kapitaal dat ERNAARTOE
roteert), negatief = de sector underperformt (mogelijk kapitaal dat
ERVANDAAN roteert).

Bewust een simpele, transparante formule (sector-rendement minus
benchmark-rendement) -- geen gewichten of samengestelde score, zodat de
uitkomst zelf tegen de twee brongetallen te verifiëren is.
"""


def compute_relative_strength_pct(sector_change_pct: float, benchmark_change_pct: float) -> float:
    """Positief = sector outperformt de benchmark, negatief = underperformt."""
    return sector_change_pct - benchmark_change_pct


def classify_relative_strength(relative_strength_pct: float) -> str:
    """Puur het teken -- geen zelfbedachte tussenbanden, zelfde aanpak als
    nfci_interpretation.py::classify_nfci()."""
    if relative_strength_pct > 0:
        return "outperformt de brede markt (S&P 500) vandaag"
    if relative_strength_pct < 0:
        return "underperformt de brede markt (S&P 500) vandaag"
    return "presteert exact gelijk aan de brede markt (S&P 500) vandaag"
