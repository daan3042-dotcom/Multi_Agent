"""
ridge.py
De derde baseline (roadmap 4.6): een ridge-regressie op de eigen inputs van
de agent, gefit op de back-fill en daarna bevroren.

WAAROM DEZE BASELINE ER IS. Persistence en climatology zeggen of een agent
iets weet dat "het blijft zoals het is" niet weet. Deze zegt iets anders:
voegt het LLM iets toe BOVEN zijn eigen inputs? Een lineair model op precies
de cijfers die de agent ziet, is de eenvoudigste manier waarop je die inputs
zonder taalmodel kunt gebruiken. Verslaat het LLM dit niet, dan zit de
meerwaarde niet in het redeneren maar (hooguit) in tekst -- en dat is een
uitkomst, geen mislukking.

WAT HET MODEL DOET. Per (domein, doel, horizon) één model dat de VERANDERING
over de horizon voorspelt (bij relatief rendement: het rendement zelf) uit de
z-scores van alle reeksen van dat domein. De voorspelde kwantielen zijn
anker + ŷ + de kwantielen van de residuen UIT DE CROSS-VALIDATIE. Niet uit de
fit zelf: residuen van de trainingsdata zijn te klein, en dan is de baseline
overmoedig -- en een overmoedige baseline is te verslaan met alleen breder
te voorspellen.

POINT-IN-TIME, DE KERN. Twee valkuilen die hier apart worden afgedekt:
1. PUBLICATIEVERTRAGING. Een maandcijfer heeft als `source_time` de eerste
   van de referentiemaand maar is pas ~5 weken later bekend. Wie dat als
   'beschikbaar op de eerste' behandelt, laat het model in de trainingsdata
   de toekomst zien -- en dat is onzichtbaar, want de scores zien er alleen
   beter uit. Elke reeks krijgt daarom een conservatieve vertraging per
   cadans (CADENCE_RULES). De cadans wordt AFGELEID uit de reeks zelf.
2. Dezelfde functie voor fit en voorspelling. Features worden op beide
   momenten met dezelfde code berekend, ten opzichte van dezelfde datum (de
   laatste waarneming van het doel), zodat er geen verschil tussen training
   en gebruik kan sluipen.

BEKENDE BEPERKING (te bevestigen bij de freeze): voor week- en maanddoelen
ziet dit model de inputs zoals ze waren op de laatste waarneming van het
DOEL, en dat kan tot ~5 weken ouder zijn dan wat het LLM ziet. Dat maakt
de ridge daar iets zwakker dan het zou kunnen zijn. Alternatief is features
op `now`, maar dan valt de gelijkheid tussen training en gebruik weg.

GEEN NUMPY. Het stelsel is p×p met p ≲ 12; een eigen eliminatie is genoeg en
houdt CLAUDE.md regel 2 (geen native dependencies) intact.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from agents.base import ForecastTarget
from contract.prediction import Prediction, PredictionKind
from contract.resolution import Observation, ResolutionMethod
from scoring.baselines import (
    BASELINE_VERSION,
    BaselineRoundResult,
    _Insufficient,
    _Sample,
    _Skip,
    _bouw,
    _history,
    _kwantielen,
    _sample,
)
from storage.schema import (
    count_baseline_models,
    list_domain_metric_keys,
    load_baseline_model,
    save_baseline_model,
)

RIDGE = "baseline:ridge"
RIDGE_NAME = "ridge"
RIDGE_SPEC_VERSION = "v1"
"""Versie van de SPECIFICATIE van dit model: features, z-scorevenster,
regularisatiegrid, CV-opzet. Zit in de sleutel van de bevroren modellen.
Verander je iets aan een van die keuzes, verhoog dit dan -- oude modellen
blijven staan en het verschil is achteraf te zien."""

Z_WINDOW = 252
"""Aantal waarnemingen waarover de z-score wordt berekend. 252 is een
handelsjaar bij dagdata; bij weekdata is het vijf jaar en bij maanddata
21 jaar. Dat verschil in tijdspanne is een gevolg van tellen op
waarnemingen in plaats van op kalendertijd, en bewust: het venster hoort
groot genoeg te zijn voor een stabiele standaardafwijking, niet gelijk in
jaren."""
MIN_Z_OBS = 30
Z_CLIP = 5.0
"""Z-scores worden op ±5 afgekapt, bij fit én voorspelling. Een eenheidswijziging
in een bron (zoals WALCL, dat op 28-09 in miljoenen bleek te staan) of een
glitch levert anders een z van 40 op, en een lineair model extrapoleert die
gedwee naar een absurde voorspelling."""

MIN_TRAIN_ROWS = 100
MIN_FEATURE_COVERAGE = 0.8
"""Een feature die voor minder dan 80% van de trainingsrijen bestaat (een
reeks met korte historie) wordt uit het model gelaten en genoteerd in
`dropped`, in plaats van 20% van de rijen weg te gooien voor één feature."""

LAMBDA_GRID = (0.01, 0.1, 1.0, 10.0, 100.0, 1_000.0, 10_000.0)
"""Het raster loopt door tot 10.000 zodat het 'niets doen'-model bereikbaar is.
Bij λ = 10.000 zijn alle coëfficiënten praktisch nul. Het eerste raster stopte
bij 100, en in de eerste droge run op echte data koos de cross-validatie bij
bijna elk doel precies die bovengrens: het teken dat nog sterkere regularisatie
beter was."""
CV_BLOCKS = 6

CADENCE_RULES: dict[str, tuple[int, int]] = {
    "daily": (1, 10),
    "weekly": (7, 21),
    "monthly": (50, 90),
}
"""Per cadans: (vertraging in dagen tot een waarneming 'bekend' is, maximale
ouderdom waarna hij als ontbrekend telt).

DE VERTRAGINGEN ZIJN CONSERVATIEF EN NIET PER REEKS GEVERIFIEERD (checkpoint
4). Maandreeksen 50 dagen: UNRATE/PAYEMS zijn ~5 weken na de referentiemaand
bekend, CPI ~6 weken. Te lang is onschuldig (het model ziet iets oudere
data); te kort is precies het lek dat dit moet voorkomen."""


def infer_cadence(times: list[datetime]) -> str | None:
    """Cadans uit de mediane afstand tussen waarnemingen. None als de reeks
    niet in daily/weekly/monthly past (kwartaal, onregelmatig): zo'n reeks
    valt dan als feature af in plaats van met een geraden vertraging mee te
    doen."""
    if len(times) < 3:
        return None
    gaps = sorted((b - a).days for a, b in zip(times, times[1:]))
    mediaan = gaps[len(gaps) // 2]
    if mediaan <= 4:
        return "daily"
    if mediaan <= 10:
        return "weekly"
    if 25 <= mediaan <= 35:
        return "monthly"
    return None


class FeatureSeries:
    """Eén input-reeks met z-scores 'zoals bekend op moment t'."""

    def __init__(self, key: str, prints: list[Observation]):
        self.key = key
        self.times = [o.source_time for o in prints]
        self.cadence = infer_cadence(self.times)
        self.values = [o.value for o in prints]
        if self.cadence is None:
            self.avail: list[datetime] = []
            self.max_age = 0
            return
        lag, self.max_age = CADENCE_RULES[self.cadence]
        self.avail = [t + timedelta(days=lag) for t in self.times]
        # Prefixsommen op de gecentreerde waarden: dan is de z-score op elk
        # moment O(1) en blijft de variantie numeriek stabiel bij grote
        # niveaus (PAYEMS ~1,6e5, WALCL ~6,7e6).
        self._offset = sum(self.values) / len(self.values)
        self._p1 = [0.0]
        self._p2 = [0.0]
        for v in self.values:
            c = v - self._offset
            self._p1.append(self._p1[-1] + c)
            self._p2.append(self._p2[-1] + c * c)

    def z_at(self, t: datetime) -> float | None:
        """De z-score van de nieuwste waarneming die op `t` al bekend was, of
        None (te weinig historie, of te oud). Nooit een gok."""
        if self.cadence is None:
            return None
        idx = bisect.bisect_right(self.avail, t) - 1
        if idx < MIN_Z_OBS - 1:
            return None
        if (t - self.times[idx]).days > self.max_age:
            return None
        lo = max(0, idx + 1 - Z_WINDOW)
        n = idx + 1 - lo
        mean = (self._p1[idx + 1] - self._p1[lo]) / n
        var = max((self._p2[idx + 1] - self._p2[lo]) / n - mean * mean, 0.0)
        std = math.sqrt(var)
        if std < 1e-12:
            return 0.0
        z = (self.values[idx] - self._offset - mean) / std
        return max(-Z_CLIP, min(Z_CLIP, z))


# --------------------------------------------------------------------------
# De regressie
# --------------------------------------------------------------------------


def solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    """Gauss-eliminatie met gedeeltelijke pivotering. Gooit ValueError bij
    een singuliere matrix -- met λ > 0 gebeurt dat niet, maar stil een
    onzin-oplossing teruggeven is erger dan falen."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            raise ValueError("singuliere matrix in ridge-oplossing")
        m[col], m[piv] = m[piv], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            if f:
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (m[i][n] - sum(m[i][j] * x[j] for j in range(i + 1, n))) / m[i][i]
    return x


def fit_ridge(
    x: list[list[float]], y: list[float], lam: float, drift: bool = True
) -> tuple[float, list[float]]:
    """Ridge. λ is geschaald op het GEMIDDELDE (X'X/n), niet op de som: zo
    betekent dezelfde λ hetzelfde bij 200 en bij 5000 rijen.

    `drift=True`: met een onbestrafte intercept, dus het model schat de
    gemiddelde verandering uit de trainingsdata en telt die op bij elke
    voorspelling. `drift=False`: zonder intercept; alleen de inputs voorspellen
    een verandering, en zonder inputs is de voorspelling 'geen verandering'.

    WAAROM BEIDE. Bij een reeks met een echte, stabiele trend (banen, prijzen)
    is de drift precies wat een goed model moet vangen. Bij een reeks zonder
    (valutakoersen) is de geschatte trend ruis die uit-de-steekproef niet klopt,
    en dat maakte het model in de eerste droge run tot 17% slechter dan 'geen
    verandering'. De cross-validatie kiest per doel."""
    n, p = len(x), len(x[0])
    if drift:
        xm = [sum(r[j] for r in x) / n for j in range(p)]
        ym = sum(y) / n
    else:
        xm, ym = [0.0] * p, 0.0
    a = [[0.0] * p for _ in range(p)]
    b = [0.0] * p
    for row, yi in zip(x, y):
        d = [row[j] - xm[j] for j in range(p)]
        yc = yi - ym
        for j in range(p):
            b[j] += d[j] * yc
            for k in range(j, p):
                a[j][k] += d[j] * d[k]
    for j in range(p):
        for k in range(j, p):
            a[j][k] /= n
            a[k][j] = a[j][k]
        b[j] /= n
        a[j][j] += lam
    beta = solve_linear(a, b)
    return ym - sum(xm[j] * beta[j] for j in range(p)), beta


def _voorspel(intercept: float, beta: list[float], row: list[float]) -> float:
    return intercept + sum(b * v for b, v in zip(beta, row))


@dataclass(frozen=True)
class RidgeFit:
    """Wat een fit opleverde, inclusief de diagnostiek waarop DD bij de
    freeze beslist. `mse_oos` tegen `mse_random_walk` is de eerlijke
    vergelijking: is dit model uit-de-steekproef beter dan 'geen verandering'?"""

    model: dict
    mse_oos: float
    mse_random_walk: float


def _cv_residuen(
    x: list[list[float]], y: list[float], horizon_n: int, lam: float, drift: bool = True
) -> list[float] | None:
    """Uit-de-steekproef-residuen via expanding-window CV. Tussen trainings-
    en validatieblok zit een gat van `horizon_n` rijen: de vensters
    overlappen, dus een trainingsrij vlak voor het blok kent al een deel van
    de toekomst van het validatieblok. Zonder dat gat is de CV te
    optimistisch en de residuenspreiding te smal."""
    n = len(x)
    grenzen = [n * k // CV_BLOCKS for k in range(CV_BLOCKS + 1)]
    resid: list[float] = []
    for k in range(1, CV_BLOCKS):
        train_eind = grenzen[k] - horizon_n
        if train_eind < MIN_TRAIN_ROWS // 2:
            continue
        intercept, beta = fit_ridge(x[:train_eind], y[:train_eind], lam, drift)
        for i in range(grenzen[k], grenzen[k + 1]):
            resid.append(y[i] - _voorspel(intercept, beta, x[i]))
    return resid or None


def fit_ridge_model(
    conn, domain: str, target: ForecastTarget, horizon_n: int, as_of: datetime
) -> RidgeFit:
    """Fit één model op alles wat er op `as_of` bekend was. Schrijft niets
    weg -- zie `freeze_ridge_model()`. Gooit `_Insufficient` als er te weinig
    te fitten valt."""
    sample = _sample(conn, target, horizon_n, as_of)
    rijen = list(zip(sample.dates, sample.deltas))

    kandidaten: list[FeatureSeries] = []
    for key in list_domain_metric_keys(conn, domain):
        reeks = FeatureSeries(key, _history(conn, key, as_of))
        if reeks.cadence is not None:
            kandidaten.append(reeks)
    if not kandidaten:
        raise _Insufficient(f"{domain}: geen enkele reeks met bruikbare cadans als input")

    # Coverage per feature, dan de rijen die ALLE behouden features hebben.
    z_per_rij = [[f.z_at(t) for f in kandidaten] for t, _ in rijen]
    behouden, weggelaten = [], []
    for j, f in enumerate(kandidaten):
        dekking = sum(1 for z in z_per_rij if z[j] is not None) / max(len(rijen), 1)
        (behouden if dekking >= MIN_FEATURE_COVERAGE else weggelaten).append((j, f, dekking))
    if not behouden:
        raise _Insufficient(f"{domain}/{target.metric_key} h={horizon_n}: geen feature met genoeg dekking")

    idx = [j for j, _, _ in behouden]
    x, y, datums = [], [], []
    for (t, delta), zs in zip(rijen, z_per_rij):
        rij = [zs[j] for j in idx]
        if all(v is not None for v in rij):
            x.append(rij)
            y.append(delta)
            datums.append(t)
    if len(x) < MIN_TRAIN_ROWS:
        raise _Insufficient(
            f"{domain}/{target.metric_key} h={horizon_n}: {len(x)} trainingsrijen, "
            f"minimaal {MIN_TRAIN_ROWS} nodig (back-fill onvolledig?)"
        )

    # Alle combinaties van (drift, lambda), van complex naar eenvoudig. Bij gelijke
    # MSE wint de LAATSTE, dus de eenvoudigste: zonder drift, sterkste regularisatie.
    beste = None
    for drift in (True, False):
        for lam in LAMBDA_GRID:
            resid = _cv_residuen(x, y, horizon_n, lam, drift)
            if resid is None:
                continue
            mse = sum(r * r for r in resid) / len(resid)
            if beste is None or mse <= beste[0]:
                beste = (mse, lam, resid, drift)
    if beste is None:
        raise _Insufficient(f"{domain}/{target.metric_key} h={horizon_n}: te weinig rijen voor cross-validatie")
    mse, lam, resid, drift = beste

    # Diagnostiek: dezelfde validatiepunten, voorspeld met 'geen verandering'.
    n = len(x)
    grenzen = [n * k // CV_BLOCKS for k in range(CV_BLOCKS + 1)]
    rw = [
        y[i] ** 2
        for k in range(1, CV_BLOCKS)
        if grenzen[k] - horizon_n >= MIN_TRAIN_ROWS // 2
        for i in range(grenzen[k], grenzen[k + 1])
    ]
    intercept, beta = fit_ridge(x, y, lam, drift)
    q10, q50, q90 = _kwantielen(resid)
    model = {
        "spec_version": RIDGE_SPEC_VERSION,
        "lambda": lam,
        "drift": drift,
        "intercept": intercept,
        "features": [f.key for _, f, _ in behouden],
        "coefficients": beta,
        "dropped": [f"{f.key} (dekking {d:.0%})" for _, f, d in weggelaten],
        "resid_q": [q10, q50, q90],
        "n_rows": n,
        "n_oos": len(resid),
        "mse_oos": mse,
        "mse_random_walk": sum(rw) / len(rw),
        "first_row": datums[0].isoformat(),
        "last_row": datums[-1].isoformat(),
        "as_of": as_of.isoformat(),
    }
    return RidgeFit(model, mse, sum(rw) / len(rw))


def freeze_ridge_model(
    conn, domain: str, target: ForecastTarget, horizon_n: int, fit: RidgeFit,
    fitted_at: datetime, as_of: datetime,
) -> int:
    """Bevriest het model. Een tweede keer geeft een IntegrityError: opnieuw
    fitten is een nieuwe RIDGE_SPEC_VERSION."""
    return save_baseline_model(
        conn, RIDGE_NAME, RIDGE_SPEC_VERSION, domain, target.metric_key, horizon_n,
        fitted_at, as_of, fit.model["n_rows"], fit.model,
    )


# --------------------------------------------------------------------------
# Voorspellen met een bevroren model
# --------------------------------------------------------------------------


def _ridge_prediction(
    conn, domain: str, target: ForecastTarget, horizon_n: int, now: datetime, sample: _Sample
) -> Prediction:
    model = load_baseline_model(conn, RIDGE_NAME, RIDGE_SPEC_VERSION, domain, target.metric_key, horizon_n)
    if model is None:
        raise _Insufficient(
            f"{target.metric_key} h={horizon_n}: geen bevroren ridge-model "
            f"(draai fit_baselines.py --freeze)"
        )
    # Dezelfde referentiedatum als bij het fitten: de laatste waarneming van
    # het doel. Zie de moduledocstring.
    t = sample.anchor_date
    rij = []
    for key in model["features"]:
        z = FeatureSeries(key, _history(conn, key, now)).z_at(t)
        if z is None:
            raise _Insufficient(
                f"{target.metric_key} h={horizon_n}: ridge-input {key} niet beschikbaar "
                f"op {t.date()} (verouderd of te weinig historie)"
            )
        rij.append(z)
    y_hat = _voorspel(model["intercept"], model["coefficients"], rij)
    q10, q50, q90 = (sample.anchor + y_hat + q for q in model["resid_q"])
    if not all(math.isfinite(v) for v in (q10, q50, q90)):
        raise _Insufficient(f"{target.metric_key} h={horizon_n}: niet-eindige ridge-voorspelling")
    note = (
        f"ridge {RIDGE_SPEC_VERSION}: lambda={model['lambda']:g}, "
        f"{'met' if model.get('drift', True) else 'zonder'} drift, {len(model['features'])} inputs, "
        f"{model['n_rows']} rijen, {model['n_oos']} uit-de-steekproef-residuen, "
        f"gefit t/m {model['as_of'][:10]}, anker {sample.anchor:g} ({sample.anchor_date.date()})"
    )
    return _bouw(RIDGE, domain, target, horizon_n, now, (q10, q50, q90), note)


def ridge_predictions(
    conn, domain: str, targets: list[ForecastTarget] | tuple[ForecastTarget, ...], now: datetime
) -> BaselineRoundResult:
    """De ridge-tegenhanger van `baseline_predictions()`. Schrijft niets weg.

    Bestaat er voor dit domein NOG GEEN bevroren model, dan is dat één
    melding en niet 55: het is één oorzaak (er is nog niet gefit), en 55
    regels in een telefoonmelding worden niet gelezen."""
    quantile_doelen = [
        t for t in targets
        if t.kind is PredictionKind.QUANTILE
        and t.resolution_method is not ResolutionMethod.DIRECTION_AFTER_FOMC
    ]
    if not quantile_doelen:
        return BaselineRoundResult(domain, ())
    if count_baseline_models(conn, RIDGE_NAME, RIDGE_SPEC_VERSION, domain) == 0:
        return BaselineRoundResult(
            domain, (),
            issues=("ridge: nog geen enkel bevroren model (draai fit_baselines.py --freeze)",),
        )

    predictions: list[Prediction] = []
    issues: list[str] = []
    for target in quantile_doelen:
        for horizon_n in target.horizons:
            try:
                sample = _sample(conn, target, horizon_n, now)
                predictions.append(_ridge_prediction(conn, domain, target, horizon_n, now, sample))
            except (_Insufficient, _Skip) as e:
                issues.append(str(e))
    return BaselineRoundResult(domain, tuple(predictions), (), tuple(issues))
