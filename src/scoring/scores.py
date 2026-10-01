"""
scores.py
De scoringsregels (roadmap 4.5). Zuivere wiskunde: functies in, getal uit,
geen database, geen LLM.

WAAROM PROPER SCORING RULES. Een scoringsregel is 'proper' als de
voorspeller zijn verwachte score optimaliseert door zijn ECHTE overtuiging
op te schrijven. Dat klinkt vanzelfsprekend maar is het niet: scoor je
alleen op "zat de waarheid binnen het interval", dan is de winnende
strategie een interval van min oneindig tot plus oneindig. Scoor je alleen
op de mediaan, dan is de winnende strategie een heel smal interval. Pinball
loss en CRPS straffen allebei -- een te breed interval kost breedte, een te
smal interval kost missers. Brier en log loss doen hetzelfde voor kansen.

Dit is precies wat dit project moet meten: niet of de agents gelijk hadden,
maar of ze wisten hoe zeker ze waren.

LAGER IS BETER, bij alle vier. Dat staat hier omdat het de meest gemaakte
leesfout is bij een kalibratietabel.
"""

from __future__ import annotations

import math

from contract.prediction import QUANTILE_FIELDS, QUANTILE_LEVELS

SCORER_VERSION = "v2"
"""Versie van de scoringsregels. Gaat mee in elke evaluation-rij.

v2 (01-10-2026): vijf kwantielen i.p.v. drie. Nog vóór de eerste echte
afwikkeling; v1-scores bestaan niet.

Zelfde reden als `prompt_version` bij de predictions: verandert de manier
van scoren, dan zijn oude en nieuwe scores niet meer op één hoop te gooien.
Een wijziging hier ná T₀ᵇ is geen bugfix maar een breuk in de meetlat, en
dat moet achteraf te zien zijn."""

_EPSILON = 1e-15
"""Afkapgrens voor log loss. Een kans van precies 0 of 1 die fout uitpakt
geeft oneindig verlies, en één zo'n voorspelling zou het gemiddelde van een
heel cohort onbruikbaar maken. Afkappen begrenst de straf op ~34,5 -- nog
altijd verreweg de zwaarste straf in de tabel, wat klopt, want absolute
zekerheid uitspreken en er naast zitten hoort het duurst te zijn."""


def pinball_loss(quantile_level: float, voorspeld: float, werkelijk: float) -> float:
    """De verliesfunctie voor één kwantiel.

    Asymmetrisch, en dat is het hele punt: bij het 10%-kwantiel is te hoog
    voorspellen negen keer zo duur als te laag voorspellen. Daardoor is de
    optimale strategie precies het echte 10%-punt van je verdeling
    opschrijven -- niet je beste gok, en niet een veilige marge."""
    if not 0 < quantile_level < 1:
        raise ValueError(f"kwantielniveau moet tussen 0 en 1 liggen, was {quantile_level}")
    fout = werkelijk - voorspeld
    if fout >= 0:
        return quantile_level * fout
    return (quantile_level - 1) * fout


def pinball_losses(kwantielen: tuple[float, ...] | list[float], werkelijk: float) -> dict[str, float]:
    """De pinball losses per niveau (sleutels `q10`, `q25`, `q50`, `q75`, `q90`)
    plus hun gemiddelde (`mean`). `kwantielen` staan in de volgorde van
    `contract.prediction.QUANTILE_LEVELS`; een andere lengte is een bug en wordt
    geweigerd in plaats van afgekapt."""
    if len(kwantielen) != len(QUANTILE_LEVELS):
        raise ValueError(
            f"{len(QUANTILE_LEVELS)} kwantielen verwacht ({', '.join(QUANTILE_FIELDS)}), "
            f"kreeg er {len(kwantielen)}"
        )
    verliezen = {
        veld: pinball_loss(niveau, waarde, werkelijk)
        for veld, niveau, waarde in zip(QUANTILE_FIELDS, QUANTILE_LEVELS, kwantielen)
    }
    verliezen["mean"] = sum(verliezen[veld] for veld in QUANTILE_FIELDS) / len(QUANTILE_FIELDS)
    return verliezen


def crps_from_quantiles(kwantielen: tuple[float, ...] | list[float], werkelijk: float) -> float:
    """CRPS, benaderd uit vijf kwantielen.

    WAT HIER EEN BENADERING IS, EN WAAROM DAT MAG. De echte CRPS is een
    integraal over ALLE kwantielniveaus: CRPS = 2 · ∫ pinball(τ) dτ. Wij
    hebben er vijf, dus de integraal wordt een gemiddelde over die vijf --
    een grove kwadratuur. De uitkomst is systematisch iets anders dan de
    echte CRPS.

    GEMETEN OP 01-10-2026 (synthetische data, een voorspeller die de echte
    verdeling kent): met de vijf niveaus .1 .25 .5 .75 .9 zit het gelijk
    gewogen gemiddelde 1 tot 2% BENEDEN de echte CRPS (normaal -1,9%, dikke
    staarten t3 -0,7%). Weging naar kansbreedte zat er 2 tot 2,5% BOVEN, en
    een trapezium 4 tot 4,5% eronder; gelijk gewogen is dus zowel de dichtste
    als de eenvoudigste. (Met drie niveaus was het ~11% te laag.)

    Dat is aanvaardbaar omdat deze score alleen wordt gebruikt om agents
    ONDERLING en tegen de baselines te vergelijken, en die krijgen
    allemaal exact dezelfde behandeling op dezelfde vijf niveaus. De
    vertekening zit dan in elke score even hard en valt weg in het
    verschil. Wat je met dit getal NIET mag doen, is het vergelijken met
    een CRPS uit de literatuur of uit een ander systeem.

    Vijf en niet meer, bewust: het is wat een taalmodel nog betrouwbaar kan
    uitspreken zonder dat kwantielen gaan kruisen, en de uiteinden (q05/q95)
    zijn met onze effectieve n niet te toetsen."""
    return 2 * pinball_losses(kwantielen, werkelijk)["mean"]


def brier_score(kans: float, gebeurde: bool) -> float:
    """Kwadratisch verlies op een kansvoorspelling. Begrensd op [0, 1],
    waardoor hij makkelijker te lezen is dan log loss -- maar hij straft
    overmoed ook veel milder, vandaar dat we beide bewaren."""
    if not 0 <= kans <= 1:
        raise ValueError(f"kans moet tussen 0 en 1 liggen, was {kans}")
    return (kans - (1.0 if gebeurde else 0.0)) ** 2


def log_loss(kans: float, gebeurde: bool) -> float:
    """Logaritmisch verlies. Onbegrensd van boven (na afkapping ~34,5) en
    daarmee de strengste straf op overmoed die er is.

    Naast Brier en niet in plaats daarvan: log loss is gevoelig voor
    precies die ene voorspelling waar een agent 99% zei en ernaast zat, en
    dat is bij een onbeheerd systeem het gedrag dat je het eerst wilt
    zien."""
    if not 0 <= kans <= 1:
        raise ValueError(f"kans moet tussen 0 en 1 liggen, was {kans}")
    p = min(max(kans, _EPSILON), 1 - _EPSILON)
    return -math.log(p) if gebeurde else -math.log(1 - p)


def within_interval(q10: float, q90: float, werkelijk: float) -> bool:
    """Viel de uitkomst binnen het 80%-interval?

    Geen scoringsregel (je kunt hem bespelen met een oneindig breed
    interval) maar wel de meest directe kalibratiecheck die er is: over
    veel voorspellingen hoort dit ongeveer 80% te zijn. Zit een agent op
    50%, dan is hij overmoedig; zit hij op 98%, dan is hij zo voorzichtig
    dat zijn voorspellingen niets zeggen. Beide zijn onzichtbaar in een
    gemiddelde pinball loss."""
    return q10 <= werkelijk <= q90
