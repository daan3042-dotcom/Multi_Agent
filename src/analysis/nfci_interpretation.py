"""
nfci_interpretation.py
Eerste bestand in analysis/ -- zelfde patroon als analyst_agent.ai/src/
analysis/ (altman_z.py, piotroski_score.py, reverse_dcf.py, ...): één
kwantitatief model per bestand, zodat DD hier later eigen modellen kan
toevoegen (bijv. taylor_rule.py voor de monetary policy agent, later
phillips_curve.py voor de economic agent) zonder iets te herstructureren.

Dit bestand voegt GEEN nieuw model toe -- het maakt de NFCI's EIGEN,
al-gepubliceerde interpretatie bruikbaar (Chicago Fed National Financial
Conditions Index-methodologie), in plaats van dat de LLM zelf moet
inschatten of een NFCI-waarde "krap" of "ruim" betekent. De NFCI is per
definitie een maatstaf t.o.v. het historisch gemiddelde (sample sinds
1973): 0 = exact dat gemiddelde, positief = krapper dan gemiddeld,
negatief = ruimer dan gemiddeld. Geen zelfbedachte tussenbanden ("laag"/
"hoog") bovenop dat gepubliceerde nulpunt -- alleen het teken zelf is de
citeerbare, officiële interpretatie.

Bron: Chicago Fed, NFCI-methodologie
(https://www.chicagofed.org/research/data/nfci/current-data).
"""


def classify_nfci(value: float) -> str:
    """Puur het teken van de NFCI-waarde -- geen zelfbedachte tussenbanden.
    Zie moduledocstring voor de bron van deze interpretatie."""
    if value > 0:
        return "krapper dan het historisch gemiddelde (sinds 1973)"
    if value < 0:
        return "ruimer dan het historisch gemiddelde (sinds 1973)"
    return "exact op het historisch gemiddelde (sinds 1973)"
