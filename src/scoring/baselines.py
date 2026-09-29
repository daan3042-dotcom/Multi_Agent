"""
baselines.py
De eerste twee baselines (roadmap 4.6): persistence en climatology.

WAAROM BASELINES ER ZIJN. Zonder baseline is niet vast te stellen of we iets
gebouwd hebben of alleen kosten gemaakt. Een LLM-agent met een pinball loss
van 0,8 zegt niets; een agent die 0,8 haalt waar "het blijft zoals het is"
0,7 haalt, zegt alles. De baselines schrijven daarom voorspellingen in
EXACT hetzelfde contract als de agents (zelfde doelen, horizonnen,
`resolves_at`, regel en methode) en worden door dezelfde resolver met
dezelfde scoringsregels gescoord. Er is geen aparte evaluatiepijplijn.

GEEN LLM, GEEN GOKWERK. Alles hier is deterministisch en herleidbaar: de
`note` van elke voorspelling zegt op hoeveel vensters hij rust en welk anker
is gebruikt. Ontbreekt er data, dan komt er GEEN voorspelling maar een
`issue` -- een baseline die met te weinig historie toch iets uitspreekt, is
een strohalm-baseline, en die maakt elke agent er beter uitzien dan hij is.

WAT ER NIET IN ZIT, EN WAAROM.
- De ridge-baseline (derde baseline) staat in `ridge.py`: die moet gefit
  worden op de back-fill, en die staat op de VPS.
- Binaire doelen (de FEDFUNDS-richting): de gebeurtenis is gedefinieerd op
  FOMC-vergaderingen, niet op maandelijkse FEDFUNDS-prints. Een basisrate
  uit maandvensters zou een ANDERE gebeurtenis scoren dan de agent
  voorspelt -- zelfde reden als in `contract/resolution.py`. Ze worden
  bewust overgeslagen, met reden, en dat staat niet als probleem maar als
  `skipped`.

POINT-IN-TIME. Alleen waarnemingen die op `as_of` al bestonden, tellen mee
(zowel `source_time` als `first_seen` op of vóór dat moment). In live
gebruik is dat altijd zo; het zit erin omdat de pseudo-out-of-sample-run
(4.4) hetzelfde pad over het verleden laat lopen, en een baseline die
vooruit kijkt is daar onzichtbaar te goed.

BEKENDE BEPERKING: de back-fill komt uit FRED zoals die NU is (gereviseerd),
niet zoals de eerste print. Voor de spreiding van veranderingen is dat
verwaarloosbaar; voor PAYEMS (grote revisies) telt het mee.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from agents.base import ForecastTarget
from contract.horizons import ReleaseCadence, resolves_at_for
from contract.prediction import HorizonKind, Prediction, PredictionKind
from contract.resolution import Observation, ResolutionMethod, eerste_prints
from scoring.resolver import observations_for

BASELINE_VERSION = "v1"
"""Versie van de baselines. Gaat mee als `prompt_version` (zelfde rol: een
wijziging binnen een cohort is een covariaat, maar moet achteraf te zien
zijn). Verander je hier iets aan de rekenwijze, verhoog dit dan."""

PERSISTENCE = "baseline:persistence"
CLIMATOLOGY = "baseline:climatology"
BASELINE_MODEL_ID = "deterministic"

MIN_SAMPLES = 30
"""Minimaal aantal vensters (persistence) of waarnemingen (climatology)
voordat een baseline iets uitspreekt. Dertig is een ondergrens voor een
10%- en 90%-kwantiel dat nog iets betekent (drie waarnemingen aan elke
staart); het is GEEN garantie dat de schatting goed is, want de vensters
overlappen en de effectieve n ligt veel lager (dat corrigeert 4.5 in de
onzekerheidsband). Te bevestigen bij de freeze."""

MIN_SEASONAL_SAMPLES = 60
"""Minimaal aantal waarnemingen in de kalendermaand van `resolves_at` om
seizoensgebonden te mogen conditioneren. Eronder valt climatology terug op
de onvoorwaardelijke verdeling, en dat staat in de `note`. Maandreeksen
(UNRATE, PAYEMS) halen dit nooit -- twintig jaar geeft twintig waarnemingen
per maand -- en zijn dus altijd onvoorwaardelijk; dat is bedoeld."""

MAX_ANCHOR_AGE_DAYS: dict[str, int] = {
    "trading_days": 10,
    "weekly": 21,
    "monthly": 75,
    "fomc": 75,
}
"""Hoe oud het laatste anker mag zijn. Een persistence-voorspelling vanaf
een verouderd anker zegt "het blijft zoals het was in augustus" en ziet er
verder normaal uit. Dagreeksen: 10 dagen (weekend + feestdagen + een
gemiste cyclus). Maandreeksen 75 dagen: UNRATE voor september wordt begin
oktober gepubliceerd, dus eind september is de nieuwste waarneming legitiem
ruim 55 dagen oud."""


@dataclass(frozen=True)
class BaselineRoundResult:
    """Wat één baseline-ronde voor één domein opleverde.

    `skipped` is bewust GEEN `issues`: het zijn doelen die een baseline per
    ontwerp niet voorspelt. `issues` zijn problemen (te weinig historie,
    verouderd anker) en komen in de melding."""

    domain: str
    predictions: tuple[Prediction, ...]
    skipped: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return not self.issues


# --------------------------------------------------------------------------
# Kleine statistiek, zonder dependencies
# --------------------------------------------------------------------------


def empirical_quantile(sorted_values: list[float], q: float) -> float:
    """Empirisch kwantiel met lineaire interpolatie tussen rangen (de
    gangbare 'type 7'-definitie). Eigen implementatie omdat een
    numpy-dependency niet nodig is voor drie kwantielen (CLAUDE.md regel 2),
    en omdat de definitie hier vastligt in plaats van van een versie
    afhangt."""
    if not sorted_values:
        raise ValueError("geen waarden")
    if not 0 <= q <= 1:
        raise ValueError(f"kwantielniveau moet tussen 0 en 1 liggen, was {q}")
    positie = q * (len(sorted_values) - 1)
    onder = math.floor(positie)
    boven = min(onder + 1, len(sorted_values) - 1)
    return sorted_values[onder] + (positie - onder) * (sorted_values[boven] - sorted_values[onder])


def _kwantielen(waarden: list[float]) -> tuple[float, float, float]:
    ordered = sorted(waarden)
    return (
        empirical_quantile(ordered, 0.10),
        empirical_quantile(ordered, 0.50),
        empirical_quantile(ordered, 0.90),
    )


# --------------------------------------------------------------------------
# De data: wat wisten we op `as_of`
# --------------------------------------------------------------------------


def _history(conn, metric_key: str, as_of: datetime) -> list[Observation]:
    """Eerste prints van deze reeks die op `as_of` al bestonden, oplopend."""
    prints = eerste_prints(observations_for(conn, metric_key))
    return [
        o for o in prints
        if o.source_time.date() <= as_of.date() and o.first_seen <= as_of
    ]


class _Skip(Exception):
    """Dit doel wordt door een baseline per ontwerp niet voorspeld."""


class _Insufficient(Exception):
    """Er is te weinig (of te oude) data. Een probleem, geen ontwerpkeuze."""


@dataclass
class _Sample:
    """Alles wat beide baselines voor één (doel, horizon) nodig hebben."""

    anchor: float                       # laatste bekende niveau; 0 bij relatief rendement
    anchor_date: datetime
    deltas: list[float]                 # veranderingen (niveau) of rendementen (relatief)
    dates: list[datetime]               # startdatum van elk venster, gelijk uitgelijnd met `deltas`
    climate: list[tuple[int, float]]    # (kalendermaand, waarde) voor climatology
    unit: str                           # 'vensters' voor de note


def _level_sample(conn, target: ForecastTarget, horizon_n: int, as_of: datetime) -> _Sample:
    prints = _history(conn, target.metric_key, as_of)
    if not prints:
        raise _Insufficient(f"geen enkele waarneming van {target.metric_key} op {as_of.date()}")
    waarden = [o.value for o in prints]
    deltas = [waarden[i + horizon_n] - waarden[i] for i in range(len(waarden) - horizon_n)]
    return _Sample(
        anchor=waarden[-1],
        anchor_date=prints[-1].source_time,
        deltas=deltas,
        dates=[prints[i].source_time for i in range(len(waarden) - horizon_n)],
        climate=[(o.source_time.month, o.value) for o in prints],
        unit=f"vensters van {horizon_n}",
    )


def _relative_sample(conn, target: ForecastTarget, horizon_n: int, as_of: datetime) -> _Sample:
    if not target.benchmark_metric_key:
        raise _Insufficient(f"{target.metric_key}: relatief rendement zonder benchmark")
    reeks = {o.source_time: o for o in _history(conn, target.metric_key, as_of)}
    bench = {o.source_time: o for o in _history(conn, target.benchmark_metric_key, as_of)}
    # Alleen momenten waarop BEIDE bestaan -- zelfde eis als in
    # contract/resolution.relative_return, en om dezelfde reden.
    gedeeld = sorted(set(reeks) & set(bench))
    if not gedeeld:
        raise _Insufficient(
            f"{target.metric_key} en {target.benchmark_metric_key} hebben geen gemeenschappelijk moment"
        )
    rendementen: list[tuple[int, float]] = []
    startdata: list[datetime] = []
    for i in range(len(gedeeld) - horizon_n):
        start, eind = gedeeld[i], gedeeld[i + horizon_n]
        if reeks[start].value == 0 or bench[start].value == 0:
            continue
        rr = (
            (reeks[eind].value / reeks[start].value - 1) * 100
            - (bench[eind].value / bench[start].value - 1) * 100
        )
        rendementen.append((eind.month, rr))
        startdata.append(start)
    return _Sample(
        anchor=0.0,
        anchor_date=gedeeld[-1],
        deltas=[rr for _, rr in rendementen],
        dates=startdata,
        climate=rendementen,
        unit=f"relatieve-rendementsvensters van {horizon_n}",
    )


def _sample(conn, target: ForecastTarget, horizon_n: int, as_of: datetime) -> _Sample:
    methode = target.resolution_method
    if methode is ResolutionMethod.DIRECTION_AFTER_FOMC:
        raise _Skip(
            "binaire gebeurtenis op FOMC-vergaderingen; een basisrate uit maandelijkse "
            "FEDFUNDS-vensters zou een andere gebeurtenis scoren"
        )
    sample = (
        _relative_sample(conn, target, horizon_n, as_of)
        if methode is ResolutionMethod.RELATIVE_RETURN
        else _level_sample(conn, target, horizon_n, as_of)
    )
    if len(sample.deltas) < MIN_SAMPLES:
        raise _Insufficient(
            f"{target.metric_key} h={horizon_n}: {len(sample.deltas)} {sample.unit}, "
            f"minimaal {MIN_SAMPLES} nodig (back-fill onvolledig?)"
        )
    if target.horizon_kind is HorizonKind.TRADING_DAYS:
        sleutel = "trading_days"
    elif target.cadence is not None:
        sleutel = target.cadence.value
    else:
        # Een releases-doel zonder cadans kan resolves_at_for() al niet
        # berekenen; hier alleen als vangnet, zodat er nooit een KeyError
        # uit een dictionary komt in plaats van een leesbare reden.
        raise _Insufficient(f"{target.metric_key}: releases-doel zonder cadans")
    maximum = MAX_ANCHOR_AGE_DAYS[sleutel]
    leeftijd = (as_of.date() - sample.anchor_date.date()).days
    if leeftijd > maximum:
        raise _Insufficient(
            f"{target.metric_key}: laatste waarneming is {leeftijd} dagen oud "
            f"({sample.anchor_date.date()}), maximaal {maximum} toegestaan"
        )
    return sample


# --------------------------------------------------------------------------
# De twee baselines
# --------------------------------------------------------------------------


def persistence_quantiles(sample: _Sample) -> tuple[float, float, float]:
    """"Het blijft zoals het is": mediaan = anker, spreiding uit de
    historische veranderingen over de horizon.

    De veranderingen worden gecentreerd op hun eigen mediaan. Zonder dat
    zou de historische drift meelopen en is dit geen random walk meer maar
    een random walk mét trend -- en een baseline met een ingebouwde trend
    verslaat een agent die dat niet weet, om de verkeerde reden. Bij
    relatief rendement is het anker 0: 'de sector blijft even sterk als de
    markt'."""
    q10, q50, q90 = _kwantielen(sample.deltas)
    return (sample.anchor + q10 - q50, sample.anchor, sample.anchor + q90 - q50)


def climatology_quantiles(sample: _Sample, resolves_at: datetime) -> tuple[tuple[float, float, float], str]:
    """De onvoorwaardelijke historische verdeling, conditioneel op de
    kalendermaand van `resolves_at` zodra daar genoeg waarnemingen voor zijn.

    Geeft ook de reden terug voor de `note`: welke van de twee gebruikt is.
    Een stille terugval zou twee verschillende methoden onder één label
    zetten, en dat is achteraf niet meer te zien."""
    maand = resolves_at.month
    in_maand = [w for m, w in sample.climate if m == maand]
    if len(in_maand) >= MIN_SEASONAL_SAMPLES:
        return _kwantielen(in_maand), f"seizoen: maand {maand}, n={len(in_maand)}"
    alle = [w for _, w in sample.climate]
    return (
        _kwantielen(alle),
        f"onvoorwaardelijk, n={len(alle)} (maand {maand} heeft {len(in_maand)}, "
        f"minimaal {MIN_SEASONAL_SAMPLES} nodig voor seizoen)",
    )


def _bouw(
    naam: str, domain: str, target: ForecastTarget, horizon_n: int, now: datetime,
    kwantielen: tuple[float, float, float], note: str,
) -> Prediction:
    q10, q50, q90 = kwantielen
    return Prediction(
        agent=naam,
        domain=domain,
        target_metric_key=target.metric_key,
        kind=PredictionKind.QUANTILE,
        horizon_kind=target.horizon_kind,
        horizon_n=horizon_n,
        created_at=now,
        resolves_at=resolves_at_for(now, target.horizon_kind, horizon_n, target.cadence),
        resolution_rule=target.resolution_rule.format(horizon_n=horizon_n),
        resolution_method=target.resolution_method,
        benchmark_metric_key=target.benchmark_metric_key,
        model_id=BASELINE_MODEL_ID,
        prompt_version=f"baseline-{BASELINE_VERSION}",
        q10=q10, q50=q50, q90=q90,
        graph_node=target.graph_node,
        note=note,
    )


def baseline_predictions(
    conn, domain: str, targets: list[ForecastTarget] | tuple[ForecastTarget, ...], now: datetime
) -> BaselineRoundResult:
    """Berekent beide baselines voor alle doelen van één agent. Schrijft
    NIETS weg -- dat doet `run_baseline_round()`. Zuiver genoeg om zonder
    schrijfacties te testen, en om de pseudo-OOS-run (4.4) later met een
    ander `now` over het verleden te laten lopen."""
    predictions: list[Prediction] = []
    skipped: list[str] = []
    issues: list[str] = []

    for target in targets:
        for horizon_n in target.horizons:
            sleutel = f"{domain}/{target.metric_key} h={horizon_n}"
            if target.kind is PredictionKind.BINARY and target.resolution_method is not ResolutionMethod.DIRECTION_AFTER_FOMC:
                issues.append(f"{sleutel}: binair doel met onbekende methode, niet te baselinen")
                continue
            try:
                sample = _sample(conn, target, horizon_n, now)
            except _Skip as e:
                skipped.append(f"{sleutel}: {e}")
                continue
            except _Insufficient as e:
                issues.append(str(e))
                continue

            resolves_at = resolves_at_for(now, target.horizon_kind, horizon_n, target.cadence)
            anker = f"anker {sample.anchor:g} ({sample.anchor_date.date()})"
            n = len(sample.deltas)

            predictions.append(_bouw(
                PERSISTENCE, domain, target, horizon_n, now, persistence_quantiles(sample),
                f"persistence {BASELINE_VERSION}: {n} {sample.unit}, {anker}",
            ))
            kwantielen, reden = climatology_quantiles(sample, resolves_at)
            predictions.append(_bouw(
                CLIMATOLOGY, domain, target, horizon_n, now, kwantielen,
                f"climatology {BASELINE_VERSION}: {reden}",
            ))

    return BaselineRoundResult(domain, tuple(predictions), tuple(skipped), tuple(issues))
