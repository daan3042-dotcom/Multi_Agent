"""
moving_average_deviation.py
Vierde model in analysis/ (zie nfci_interpretation.py, taylor_rule.py en
relative_strength.py voor de eerste drie, en die map se docstring voor de
bredere uitleg van dit patroon). Procentuele afwijking van de huidige
prijs t.o.v. een voortschrijdend gemiddelde over de laatste N periodes --
een gevestigd, eenvoudig technisch-analyse-concept (mean reversion/
trend-sterkte-signaal). Positief = prijs ligt boven het gemiddelde
(mogelijk overgewaardeerd t.o.v. het recente verleden, of een sterke
opwaartse trend), negatief = eronder.

Bewust simpel gehouden (rekenkundig gemiddelde, geen exponentieel gewogen
variant) -- transparant en met de hand na te rekenen tegen de brongetallen.
"""


def compute_moving_average(values: list[float]) -> float:
    """Rekenkundig gemiddelde over de aangeleverde waarden. De aanroeper
    bepaalt de periode (aantal waarden) -- deze functie is periode-
    agnostisch."""
    return sum(values) / len(values)


def compute_deviation_from_average_pct(current_value: float, average: float) -> float:
    """Procentuele afwijking van current_value t.o.v. average. Positief =
    boven het gemiddelde, negatief = eronder."""
    return (current_value - average) / average * 100
