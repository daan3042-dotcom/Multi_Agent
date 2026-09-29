"""
trigger_calibration.py
Hoe vaak zou elke triggerdrempel gevuurd hebben (roadmap 1.5, "Drempels
kalibreren tegen de volledige historie"; T₀ᵇ-checklist).

DIT IS EEN RAPPORT, GEEN WIJZIGING. Niets hier verandert een drempel, een
agent of `src/triggers/`. Het beantwoordt de vraag "wat betekent de huidige
tolerance eigenlijk", zodat DD een goed onderbouwde keuze kan maken. Na T₀ᵇ mag
een drempel niet meer verschuiven zonder een nieuw cohort te starten (CLAUDE.md),
dus deze keuze hoort vóór de freeze te vallen, met open ogen.

HOE HET SYSTEEM TELT, EN HOE DIT RAPPORT HET NABOOTST. `run_monitoring` vergelijkt
elke cyclus de nieuwste waarde met de vorige OPGESLAGEN waarde en vuurt als
`|nu - vorige| > tolerance` (strikt groter dan; gelijk telt niet, zie
`triggers.trigger_engine.evaluate_surprise`). Bij een dagreeks is dat de
verandering tussen twee opeenvolgende waarnemingen; bij een week- of maandreeks
is de waarde op de meeste dagen ongewijzigd en vuurt de regel hooguit één keer
per nieuwe publicatie. Het rapport telt daarom per PAAR OPEENVOLGENDE
WAARNEMINGEN. Een test controleert dat dit exact dezelfde uitkomst geeft als de
echte `evaluate_surprise`, zodat de twee niet uit elkaar kunnen lopen.

WAAROM OOK EEN NIVEAU-GECORRIGEERDE TELLING. De tolerances zijn ABSOLUUT. Voor
een rente of een spread is dat goed (een kwart procentpunt betekent altijd
hetzelfde), maar voor een koers is het dat niet: een ETF stond in 1999 op ~$25 en
nu op ~$250, dus een vaste $6 vuurt in het verleden veel minder vaak dan nu. Voor
elke reeks staat daarom ook wat dezelfde drempel, uitgedrukt als PERCENTAGE van het
huidige niveau, over de afgelopen jaren zou hebben gedaan. Verschillen die twee
sterk, dan schuift de absolute drempel niet mee met het niveau.

BEPERKINGEN. De historie is de back-fill zoals die NU is (gereviseerd, niet de eerste
print): voor de spreiding van veranderingen verwaarloosbaar, voor PAYEMS niet
helemaal. En de historie is per reeks verschillend lang: `high_yield_credit_spread`
heeft maar ~3 jaar, dus daar zegt "alles" niets meer dan "3 jaar".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from contract.resolution import eerste_prints
from scoring.baselines import empirical_quantile
from scoring.resolver import observations_for

WINDOWS: tuple[tuple[str, float | None], ...] = (("alles", None), ("10j", 10.0), ("3j", 3.0), ("1j", 1.0))
"""Terugkijkvensters in jaren, gerekend vanaf de LAATSTE waarneming van de reeks
(niet vanaf 'nu', zodat een reeks die even stilligt geen leeg venster krijgt)."""

TARGET_FRACTIONS = (0.01, 0.02, 0.05)
"""Doelfrequenties voor de tabel 'welke drempel hoort bij X% van de waarnemingen'.
Een keuze, geen berekening: 1% is zeldzaam (grofweg twee tot drie keer per jaar bij
een dagreeks), 5% is regelmatig (ongeveer één keer per maand)."""

MIN_PAIRS = 30
SHORT_HISTORY_YEARS = 5.0
UNSTABLE_FACTOR = 3.0
OFTEN_FRACTION = 0.10
SELDOM_FRACTION = 0.005
"""Drempels voor de 'oordeel'-kolom. Adviserend en bewust ruim; het zijn leeshulpen,
geen regels. Wijzigen ze, dan wijzigt alleen de tekst in het rapport."""

DAYS_PER_YEAR = 365.25


@dataclass(frozen=True)
class WindowStat:
    pairs: int
    fires: int
    per_year: float | None      # None als het venster korter dan een kwartaal beslaat
    fraction: float | None      # aandeel waarnemingen dat vuurt

    @property
    def is_empty(self) -> bool:
        return self.pairs == 0


@dataclass(frozen=True)
class MetricCalibration:
    domain: str
    metric_key: str
    tolerance: float
    last_value: float | None
    n_pairs: int
    years: float
    stats: dict[str, WindowStat]
    level_adjusted_3y: WindowStat | None
    quantile_thresholds: dict[float, float]     # doelfractie -> absolute drempel (laatste 3j)
    flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def tolerance_pct_of_level(self) -> float | None:
        if not self.last_value:
            return None
        return abs(self.tolerance / self.last_value) * 100


def abs_changes(values: list[tuple[datetime, float]]) -> list[tuple[datetime, float, float]]:
    """Voor elk paar opeenvolgende waarnemingen: (datum van de nieuwe, |verandering|,
    |vorige waarde|). Oplopend in de tijd."""
    return [
        (values[i][0], abs(values[i][1] - values[i - 1][1]), abs(values[i - 1][1]))
        for i in range(1, len(values))
    ]


def fires(deviation: float, tolerance: float) -> bool:
    """Exact de regel van `evaluate_surprise`: strikt groter dan. Gelijk aan de
    tolerance vuurt NIET."""
    return deviation > tolerance


def _window_stat(
    changes: list[tuple[datetime, float, float]], tolerance: float, since: datetime | None,
    ref: datetime, first: datetime, relative_to: float | None = None,
) -> WindowStat:
    """`relative_to`: het huidige niveau. Als gezet wordt de drempel als percentage van
    dat niveau toegepast op de RELATIEVE verandering van elk paar."""
    subset = [c for c in changes if since is None or c[0] >= since]
    if relative_to is None:
        n_fire = sum(1 for _, dev, _ in subset if fires(dev, tolerance))
    else:
        drempel_rel = tolerance / abs(relative_to)
        n_fire = sum(1 for _, dev, prev in subset if prev != 0 and fires(dev / prev, drempel_rel))
    start = first if since is None else max(since, first)
    years = (ref - start).total_seconds() / 86400 / DAYS_PER_YEAR
    return WindowStat(
        pairs=len(subset),
        fires=n_fire,
        per_year=(n_fire / years) if years >= 0.25 else None,
        fraction=(n_fire / len(subset)) if subset else None,
    )


def calibrate_series(
    domain: str, metric_key: str, tolerance: float, values: list[tuple[datetime, float]],
) -> MetricCalibration:
    """De kern, zonder database: neemt de waarnemingen (oplopend) en rekent."""
    if len(values) < 2:
        return MetricCalibration(domain, metric_key, tolerance, values[-1][1] if values else None,
                                 0, 0.0, {}, None, {}, ("geen historie",))
    changes = abs_changes(values)
    ref, first = values[-1][0], values[0][0]
    last_value = values[-1][1]
    years = (ref - first).total_seconds() / 86400 / DAYS_PER_YEAR

    stats = {}
    for naam, jaren in WINDOWS:
        since = None if jaren is None else ref - timedelta(days=jaren * DAYS_PER_YEAR)
        stats[naam] = _window_stat(changes, tolerance, since, ref, first)

    drie_jaar = ref - timedelta(days=3 * DAYS_PER_YEAR)
    adjusted = _window_stat(changes, tolerance, drie_jaar, ref, first, relative_to=last_value) if last_value else None

    # Drempels bij doelfrequenties, op de laatste drie jaar (of alles als dat te weinig is).
    recent = [dev for d, dev, _ in changes if d >= drie_jaar]
    bron = recent if len(recent) >= MIN_PAIRS else [dev for _, dev, _ in changes]
    quantiles: dict[float, float] = {}
    if len(bron) >= MIN_PAIRS:
        gesorteerd = sorted(bron)
        quantiles = {f: empirical_quantile(gesorteerd, 1 - f) for f in TARGET_FRACTIONS}

    return MetricCalibration(
        domain, metric_key, tolerance, last_value, len(changes), years, stats, adjusted, quantiles,
        tuple(_flags(stats, adjusted, years, len(changes))),
    )


def _flags(stats: dict[str, WindowStat], adjusted: WindowStat | None, years: float, n_pairs: int) -> list[str]:
    flags: list[str] = []
    if n_pairs < MIN_PAIRS:
        return ["te weinig historie"]
    if years < SHORT_HISTORY_YEARS:
        flags.append(f"korte historie ({years:.1f} jaar)")
    alles, drie = stats["alles"], stats["3j"]
    if alles.fires == 0 and drie.fires == 0:
        flags.append("vuurt nooit")
    elif drie.fraction is not None and drie.fraction > OFTEN_FRACTION:
        flags.append(f"vuurt vaak ({drie.fraction:.0%} van de waarnemingen)")
    elif drie.fraction is not None and drie.fraction < SELDOM_FRACTION and drie.fires > 0:
        flags.append("vuurt zelden")

    snelheden = [s.per_year for s in stats.values() if s.per_year is not None and s.pairs >= MIN_PAIRS]
    if len(snelheden) >= 2 and max(snelheden) >= 1.0:
        laagste = min(snelheden)
        if laagste == 0 or max(snelheden) / laagste >= UNSTABLE_FACTOR:
            flags.append("wisselt sterk per periode")
    if adjusted and adjusted.per_year is not None and drie.per_year is not None:
        hoog, laag = max(adjusted.per_year, drie.per_year), min(adjusted.per_year, drie.per_year)
        if hoog >= 1.0 and (laag == 0 or hoog / laag >= UNSTABLE_FACTOR):
            flags.append("niveau-afhankelijk")
    return flags


def metric_registry() -> list[tuple[str, str, object]]:
    """(domein, metric_key, MetricSpec) voor élke gemonitorde reeks, rechtstreeks uit de
    agent-modules. Geen kopie: een drempel die in de code verandert, verandert hier mee."""
    from agents import (
        commodity_agent, currency_agent, economic_agent, financial_agent,
        monetary_policy_agent, sector_agent,
    )

    modules = (monetary_policy_agent, currency_agent, financial_agent, sector_agent, commodity_agent, economic_agent)
    return [(m.DOMAIN, key, spec) for m in modules for key, spec in m.METRIC_SPECS.items()]


def calibrate_all(conn, now: datetime, domain: str | None = None) -> list[MetricCalibration]:
    """Kalibreert elke geregistreerde reeks tegen wat er in de database staat, tot en met
    `now`. Point-in-time: een waarneming van na `now` telt niet mee."""
    resultaten = []
    for dom, key, spec in metric_registry():
        if domain is not None and dom != domain:
            continue
        prints = [
            o for o in eerste_prints(observations_for(conn, key))
            if o.source_time <= now and o.first_seen <= now
        ]
        resultaten.append(
            calibrate_series(dom, key, spec.tolerance, [(o.source_time, o.value) for o in prints])
        )
    return resultaten


# --------------------------------------------------------------------------
# Weergave
# --------------------------------------------------------------------------


def _g(x: float | None, breedte: int = 9) -> str:
    if x is None:
        return "-".rjust(breedte)
    return f"{x:.4g}".rjust(breedte)


def _rate(s: WindowStat | None) -> str:
    return "-".rjust(7) if s is None or s.per_year is None else f"{s.per_year:.1f}".rjust(7)


def render_report(resultaten: list[MetricCalibration]) -> str:
    regels: list[str] = []
    regels.append("TABEL 1 -- Hoe vaak vuurt de HUIDIGE drempel? (aantal keer per jaar)")
    regels.append(
        f"{'domein':<16}{'reeks':<28}{'tolerance':>10}{'niveau':>10}{'tol%':>7}{'jaren':>7}"
        f"{'alles':>7}{'10j':>7}{'3j':>7}{'1j':>7}{'3j,rel':>8}  oordeel"
    )
    for r in resultaten:
        s = r.stats
        pct = "-" if r.tolerance_pct_of_level is None else f"{r.tolerance_pct_of_level:.2g}"
        regels.append(
            f"{r.domain:<16}{r.metric_key:<28}{_g(r.tolerance, 10)}{_g(r.last_value, 10)}{pct:>7}{r.years:>7.1f}"
            f"{_rate(s.get('alles'))}{_rate(s.get('10j'))}{_rate(s.get('3j'))}{_rate(s.get('1j'))}"
            f"{_rate(r.level_adjusted_3y).rjust(8)}  {'; '.join(r.flags) or 'ok'}"
        )

    regels.append("")
    regels.append("TABEL 2 -- Welke drempel hoort bij een doelfrequentie? (laatste 3 jaar, absoluut)")
    regels.append(
        f"{'domein':<16}{'reeks':<28}{'huidig':>10}   {'1% van de dagen':>16}{'2%':>10}{'5%':>10}     "
        f"{'idem als % van niveau (1% / 2% / 5%)'}"
    )
    for r in resultaten:
        if not r.quantile_thresholds:
            regels.append(f"{r.domain:<16}{r.metric_key:<28}{'(te weinig historie)':>30}")
            continue
        q = r.quantile_thresholds
        if r.last_value:
            pcts = " / ".join(f"{abs(q[f] / r.last_value) * 100:.2g}" for f in TARGET_FRACTIONS)
        else:
            pcts = "-"
        regels.append(
            f"{r.domain:<16}{r.metric_key:<28}{_g(r.tolerance, 10)}   {_g(q[0.01], 16)}{_g(q[0.02], 10)}{_g(q[0.05], 10)}     {pcts}"
        )

    regels.append("")
    regels.append("TABEL 3 -- Verwacht aantal triggers per jaar bij de huidige drempels (laatste 3 jaar)")
    per_domein: dict[str, float] = {}
    for r in resultaten:
        s = r.stats.get("3j")
        if s is not None and s.per_year is not None:
            per_domein[r.domain] = per_domein.get(r.domain, 0.0) + s.per_year
    for domein, totaal in per_domein.items():
        regels.append(f"  {domein:<18}{totaal:>7.1f} per jaar  (~{totaal / 52:.1f} per week)")
    regels.append(f"  {'TOTAAL':<18}{sum(per_domein.values()):>7.1f} per jaar")

    regels.append("")
    regels.append(LEESWIJZER)
    return "\n".join(regels)


LEESWIJZER = """HOE TE LEZEN
- tolerance: de huidige drempel, in de eenheid van de reeks. niveau: de laatste waarde. tol%: tolerance als % daarvan.
- alles / 10j / 3j / 1j: hoe vaak de huidige drempel per jaar gevuurd ZOU hebben in dat terugkijkvenster.
- 3j,rel: dezelfde drempel, maar uitgedrukt als % van het HUIDIGE niveau en toegepast op de relatieve verandering
  per waarneming. Verschilt dit sterk van '3j', dan schuift een vaste, absolute drempel niet mee met het niveau.
- Strikt groter dan telt: een verandering precies gelijk aan de tolerance vuurt niet (zoals in het echte systeem).
- Een weekreeks of maandreeks vuurt hooguit een keer per nieuwe publicatie, want op de tussenliggende dagen is de waarde ongewijzigd.
- Dit rapport wijzigt niets. Drempels wijzigen na T0b start een nieuw cohort: kies dus nu, met deze tabellen erbij."""
