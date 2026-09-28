"""
horizons.py
Roadmap 2.0/4.1 -- het omrekenen van een horizon naar een `resolves_at`.

HET ONDERSCHEID DAT ALLES DRAAGT. `resolution_rule` is de autoriteit: die
zegt WAT er gescoord wordt ("de eerste print van ICSA na de vierde
publicatie volgend op created_at"). `resolves_at` zegt alleen WANNEER de
resolver moet gaan kijken. De eerste moet exact zijn, de tweede hoeft dat
niet te zijn -- en dat is maar goed ook, want bij releasehorizonnen is de
publicatiedatum op het moment van voorspellen simpelweg niet bekend.

Zonder dat onderscheid zou je de publicatiekalender van FRED moeten
voorspellen om een voorspelling te mogen doen, en dat is absurd. Met dit
onderscheid is een ruime schatting genoeg: komt de resolver te vroeg, dan
is de print er nog niet en probeert hij de volgende dag opnieuw.

TWEE SOORTEN HORIZON (roadmap, correctie van 27-09):

- `TRADING_DAYS` voor dagreeksen (5/21/63). Hier wordt gerekend in
  WEEKDAGEN, zonder feestdagenkalender. Dat is een bewuste
  vereenvoudiging: een echte handelskalender vraagt een dependency of een
  handmatig bijgehouden lijst die elk jaar veroudert, terwijl de fout die
  hij oplost (een handvol dagen per jaar) volledig wordt opgevangen door
  de resolver, die de eerste beschikbare observatie op of ná `resolves_at`
  pakt. De `resolution_rule` blijft exact.
- `RELEASES` voor week- en maandreeksen (de volgende 1/2/3 prints). Hier
  wordt geschat op basis van de bekende cadans, met een marge erbovenop.

WAAROM DE MARGE ERUIT ZIET ZOALS HIJ ERUITZIET: een maandreeks wordt
gepubliceerd met vertraging (PAYEMS over september komt begin oktober).
De schatting telt daarom de publicatievertraging mee, zodat de resolver
niet structureel te vroeg kijkt en elke dag opnieuw tevergeefs probeert.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from contract.prediction import HorizonKind

WEEKDAGEN_PER_WEEK = 5


class ReleaseCadence(str, Enum):
    """De publicatiecadans van een reeks. Alleen nodig bij
    `HorizonKind.RELEASES` -- een dagreeks heeft er niets aan."""

    WEEKLY = "weekly"
    MONTHLY = "monthly"
    FOMC = "fomc"


_CADANS_DAGEN = {
    ReleaseCadence.WEEKLY: 7,
    ReleaseCadence.MONTHLY: 31,
    # De Fed vergadert acht keer per jaar, onregelmatig verdeeld: soms vijf
    # weken ertussen, soms acht. 46 dagen is het jaargemiddelde. Ruim genoeg
    # om niet structureel te vroeg te kijken, en de resolution_rule noemt de
    # vergadering zelf, dus de precisie zit daar.
    ReleaseCadence.FOMC: 46,
}

_PUBLICATIEVERTRAGING_DAGEN = {
    # ICSA verschijnt op donderdag over de week die de zaterdag ervoor
    # eindigde: een paar dagen.
    ReleaseCadence.WEEKLY: 5,
    # PAYEMS/UNRATE over september komen begin oktober; CPI rond het midden
    # van de maand erna. Twee weken vangt beide.
    ReleaseCadence.MONTHLY: 14,
    # Het besluit is er op de dag zelf.
    ReleaseCadence.FOMC: 1,
}


def add_trading_days(start: datetime, n: int) -> datetime:
    """`n` weekdagen verder vanaf `start`. Zaterdag en zondag tellen niet
    mee; feestdagen wel (zie moduledocstring voor waarom).

    Begint `start` in het weekend, dan telt de eerstvolgende weekdag als
    dag 1 -- anders zou een voorspelling die zaterdag gemaakt wordt een
    dag korter lopen dan dezelfde voorspelling op maandag."""
    if n <= 0:
        raise ValueError(f"n moet positief zijn, kreeg {n!r}")
    huidig = start
    resterend = n
    while resterend > 0:
        huidig += timedelta(days=1)
        if huidig.weekday() < WEEKDAGEN_PER_WEEK:
            resterend -= 1
    return huidig


def estimate_release_date(start: datetime, cadence: ReleaseCadence, n: int) -> datetime:
    """Geschatte datum van de `n`-de publicatie ná `start`, inclusief de
    gebruikelijke publicatievertraging.

    Nadrukkelijk een SCHATTING: de echte kalender is niet vooraf bekend en
    hoeft dat ook niet te zijn, want de `resolution_rule` noemt de print
    zelf. Deze datum bepaalt alleen wanneer de resolver begint te kijken."""
    if n <= 0:
        raise ValueError(f"n moet positief zijn, kreeg {n!r}")
    return start + timedelta(days=_CADANS_DAGEN[cadence] * n + _PUBLICATIEVERTRAGING_DAGEN[cadence])


def resolves_at_for(
    created_at: datetime,
    horizon_kind: HorizonKind,
    horizon_n: int,
    cadence: ReleaseCadence | None = None,
) -> datetime:
    """De `resolves_at` voor een voorspelling. Fail loud bij een
    releasehorizon zonder cadans: zonder die informatie is er geen
    schatting te maken, en een gok zou de resolver dagenlang tevergeefs
    laten kijken."""
    if horizon_kind is HorizonKind.TRADING_DAYS:
        if cadence is not None:
            raise ValueError("cadence hoort niet bij een trading_days-horizon")
        return add_trading_days(created_at, horizon_n)

    if cadence is None:
        raise ValueError(
            "een releases-horizon vereist een cadence (weekly/monthly/fomc) -- "
            "zonder de publicatiecadans is resolves_at niet te schatten"
        )
    return estimate_release_date(created_at, cadence, horizon_n)
