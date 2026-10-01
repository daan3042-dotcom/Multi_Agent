"""
diagnostics.py
Kalibratie, discriminatie en effectieve n (roadmap 4.5, "Kalibratiecurve per
agent", "Discrimination (AUC)", "[27-09] Effectieve n"). Zuivere wiskunde,
net als `scores.py`: lijsten in, getallen uit, geen database, geen LLM, geen
dependency buiten de standaardbibliotheek (CLAUDE.md regel 2; de bootstrap
gebruikt `random.Random` met een vaste seed, dus dezelfde invoer geeft altijd
dezelfde uitkomst).

WAAROM DIT NAAST DE SCORES. Pinball, CRPS en Brier zeggen hoe goed een agent
scoorde, niet WAAROM. Drie dingen die een gemiddelde score verbergt:

1. KALIBRATIE. Zegt een agent tien keer "70%", gebeurt het dan zeven keer?
   Bij kwantielen: valt de uitkomst in 10% van de gevallen onder q10, en de helft van de
   tijd tussen q25 en q75?
2. DISCRIMINATIE (AUC). Een agent die altijd het basispercentage roept is
   perfect gekalibreerd en volstrekt waardeloos. Alleen AUC ziet dat.
3. EFFECTIEVE N. Wekelijkse voorspellingen met een horizon van 63 dagen
   overlappen negen weken: opeenvolgende uitkomsten zijn bijna dezelfde
   waarneming. "n = 130" kan dan "n ≈ 4" betekenen, en wie in februari
   conclusies trekt uit 130 trekt ze uit 4.

ALLES HIER IS BESCHRIJVEND, GEEN OORDEEL. Bij enkelcijferige n zeggen deze
getallen vooral dat er nog niets te zeggen valt; elke functie levert daarom
zijn eigen n mee, en `effective_n` markeert zichzelf als onbetrouwbaar zodra
er te weinig onafhankelijke blokken zijn.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from datetime import datetime

from contract.prediction import QUANTILE_LEVELS


# --------------------------------------------------------------------------
# Kalibratie
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ReliabilityBin:
    low: float
    high: float
    n: int
    mean_forecast: float | None  # gemiddelde voorspelde kans in deze klasse
    observed_frequency: float | None  # hoe vaak het echt gebeurde


def reliability_bins(
    probabilities: list[float], outcomes: list[bool], n_bins: int = 5
) -> list[ReliabilityBin]:
    """Kalibratiecurve voor binaire voorspellingen: kansen in `n_bins` gelijke
    klassen, per klasse het gemiddelde voorspelde en het waargenomen
    percentage. Perfect gekalibreerd = die twee gelijk.

    Een lege klasse krijgt `None` en niet 0: "nooit gezien" is iets anders dan
    "gebeurde nooit". De bovenste klasse bevat ook kans 1,0."""
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities en outcomes moeten even lang zijn")
    if n_bins < 1:
        raise ValueError("n_bins moet minstens 1 zijn")
    klassen: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for p, o in zip(probabilities, outcomes):
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"kans buiten [0, 1]: {p}")
        klassen[min(int(p * n_bins), n_bins - 1)].append((p, o))
    resultaat = []
    for i, klasse in enumerate(klassen):
        if klasse:
            gem = sum(p for p, _ in klasse) / len(klasse)
            freq = sum(1 for _, o in klasse if o) / len(klasse)
        else:
            gem = freq = None
        resultaat.append(ReliabilityBin(i / n_bins, (i + 1) / n_bins, len(klasse), gem, freq))
    return resultaat


@dataclass(frozen=True)
class QuantileCoverage:
    """Waar de uitkomst viel ten opzichte van de vijf kwantielen: zes gebieden,
    van 'onder q10' tot 'boven q90'. `shares[i]` hoort bij `expected()[i]`."""

    n: int
    shares: tuple[float, ...]

    @staticmethod
    def expected() -> tuple[float, ...]:
        """Wat een perfect gekalibreerde agent haalt: de verschillen tussen
        opeenvolgende niveaus, 10/15/25/25/15/10%."""
        niveaus = (0.0, *QUANTILE_LEVELS, 1.0)
        return tuple(b - a for a, b in zip(niveaus, niveaus[1:]))

    @property
    def below_q10(self) -> float:
        return self.shares[0]

    @property
    def above_q90(self) -> float:
        return self.shares[-1]

    def central_share(self) -> float:
        """Aandeel binnen q25-q75 (verwacht 50%): de informatiefste kalibratiecheck
        bij weinig data."""
        return self.shares[2] + self.shares[3]

    def within_80(self) -> float:
        """Aandeel binnen q10-q90 (verwacht 80%)."""
        return 1.0 - self.shares[0] - self.shares[-1]


def quantile_coverage(rows: list[tuple[float, ...]]) -> QuantileCoverage | None:
    """`rows`: (q10, q25, q50, q75, q90, werkelijk). Een uitkomst precies OP een
    kwantiel telt naar de binnenkant van het gebied eronder, zodat een agent die
    het exact raakt niet voor een mis wordt aangerekend. `None` bij lege invoer:
    geen gok."""
    if not rows:
        return None
    k = len(QUANTILE_LEVELS)
    tellers = [0] * (k + 1)
    for rij in rows:
        if len(rij) != k + 1:
            raise ValueError(f"{k} kwantielen plus de uitkomst verwacht, kreeg {len(rij)} waarden")
        *q, werkelijk = rij
        gebied = next((i for i, waarde in enumerate(q) if werkelijk <= waarde), k)
        # Gelijk aan het eerste kwantiel hoort bij het gebied ONDER q10 alleen als het strikt lager is.
        if gebied == 0 and werkelijk == q[0]:
            gebied = 1
        tellers[gebied] += 1
    n = len(rows)
    return QuantileCoverage(n, tuple(t / n for t in tellers))


# --------------------------------------------------------------------------
# Discriminatie
# --------------------------------------------------------------------------


def auc(probabilities: list[float], outcomes: list[bool]) -> float | None:
    """Kans dat een willekeurige 'gebeurde'-voorspelling een hogere kans kreeg
    dan een willekeurige 'gebeurde niet'-voorspelling (Mann-Whitney; gelijke
    kansen tellen voor de helft). 0,5 = geen onderscheidend vermogen, 1,0 =
    perfect.

    `None` als er maar één soort uitkomst is: AUC is dan niet gedefinieerd, en
    een getal verzinnen (0,5?) zou "geen vermogen" suggereren waar het
    eigenlijk "nog niet te meten" is. Dat is bij de FOMC-doelen de normale
    stand: de Fed verhoogt zelden, dus lang is er geen enkele 'gebeurde'."""
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities en outcomes moeten even lang zijn")
    pos = [p for p, o in zip(probabilities, outcomes) if o]
    neg = [p for p, o in zip(probabilities, outcomes) if not o]
    if not pos or not neg:
        return None
    punten = 0.0
    for a in pos:
        for b in neg:
            punten += 1.0 if a > b else 0.5 if a == b else 0.0
    return punten / (len(pos) * len(neg))


# --------------------------------------------------------------------------
# Effectieve n
# --------------------------------------------------------------------------

MIN_PERIODS = 8
"""Minder dan acht voorspelrondes en een bootstrap met blokken zegt niets."""


@dataclass(frozen=True)
class EffectiveN:
    n_nominal: int  # aantal voorspellingen
    periods: int  # aantal voorspelrondes (verschillende dagen)
    block_length: int  # in rondes: zoveel opeenvolgende rondes overlappen
    mean: float  # gemiddelde score
    ci_low: float | None  # 5e percentiel van het bootstrap-gemiddelde
    ci_high: float | None  # 95e percentiel
    n_effective: float | None
    reliable: bool
    note: str


def effective_n(
    scores_by_time: list[tuple[datetime, float]],
    horizon_days: float,
    n_boot: int = 1000,
    seed: int = 20261110,
) -> EffectiveN:
    """Hoeveel ONAFHANKELIJKE waarnemingen zit er achter deze scores?

    Methode: moving-block bootstrap over voorspelrondes. Alle scores van één
    dag worden eerst tot één rondegemiddelde gemiddeld (de doelen binnen een
    ronde zijn gecorreleerd, dus een cluster, geen losse trekkingen). Rondes
    die elkaar overlappen (horizon langer dan de afstand tussen rondes)
    blijven bij elkaar door in blokken van `horizon / afstand` rondes te
    trekken. Het ontwerpeffect is de variantie van het gemiddelde MET blokken
    gedeeld door die ZONDER (alsof elke ronde onafhankelijk was); n_effectief
    = nominaal / ontwerpeffect, nooit boven nominaal.

    DIT IS EEN SCHATTING, geen exacte grootheid, en `reliable` zegt wanneer hij
    iets waard is: minstens `MIN_PERIODS` rondes en minstens twee blokken. Bij
    minder levert de functie wel de nominale gegevens maar `n_effective=None`:
    liever geen getal dan een getal dat vertrouwen wekt.

    Reproduceerbaar: vaste seed, dus hetzelfde cohort geeft dezelfde band."""
    if horizon_days <= 0:
        raise ValueError("horizon_days moet positief zijn")
    per_dag: dict = {}
    for tijd, score in scores_by_time:
        per_dag.setdefault(tijd.date(), []).append(score)
    dagen = sorted(per_dag)
    reeks = [sum(per_dag[d]) / len(per_dag[d]) for d in dagen]
    t = len(reeks)
    n_nominal = len(scores_by_time)
    if n_nominal == 0:
        return EffectiveN(0, 0, 1, 0.0, None, None, None, False, "geen scores")
    gemiddelde = sum(s for _, s in scores_by_time) / n_nominal

    if t >= 2:
        afstanden = [(b - a).days for a, b in zip(dagen, dagen[1:])]
        afstand = max(1.0, statistics.median(afstanden))
    else:
        afstand = 7.0
    blok = max(1, math.ceil(horizon_days / afstand))

    if t < MIN_PERIODS or t < 2 * blok:
        return EffectiveN(
            n_nominal, t, blok, gemiddelde, None, None, None, False,
            f"{t} voorspelrondes met blokken van {blok}: te weinig voor een schatting "
            f"(minstens {MIN_PERIODS} en twee blokken nodig)",
        )

    rng = random.Random(seed)
    starts = range(t - blok + 1)
    k = math.ceil(t / blok)
    gemiddelden = []
    for _ in range(n_boot):
        monster: list[float] = []
        for _ in range(k):
            s = rng.choice(starts)
            monster.extend(reeks[s : s + blok])
        monster = monster[:t]
        gemiddelden.append(sum(monster) / t)
    var_blok = statistics.pvariance(gemiddelden)
    var_iid = statistics.variance(reeks) / t
    if var_blok <= 0 or var_iid <= 0:
        ontwerpeffect = 1.0  # constante scores: geen informatie over afhankelijkheid
    else:
        ontwerpeffect = max(1.0, var_blok / var_iid)
    gemiddelden.sort()
    laag = gemiddelden[int(0.05 * (n_boot - 1))]
    hoog = gemiddelden[int(0.95 * (n_boot - 1))]
    return EffectiveN(
        n_nominal, t, blok, gemiddelde, laag, hoog,
        n_nominal / ontwerpeffect, True,
        f"{t} rondes, blokken van {blok}, ontwerpeffect {ontwerpeffect:.2f}",
    )
