"""
atr_proef.py
Proefrapport voor DD's idee van 02-10-2026 (roadmap 4.2): een volatiliteitsgebonden drempel -- trigger als een beweging
N keer zo groot is als de gemiddelde dagbeweging van de afgelopen 30 dagen.

DIT IS EEN RAPPORT, GEEN WIJZIGING. Niets hier verandert een drempel, een agent of `src/triggers/`; het lees alleen
de database. Het beantwoordt de vraag die in de roadmap vóór het bouwen stond: hoeveel triggers per jaar zou "N keer
de gemiddelde beweging" geven, per reeks, voor N van 2 tot 6 -- naast wat de huidige vaste drempel doet.

WAAROM DIT GEEN ECHTE "ATR" IS. We bewaren per dag één waarde (de slotkoers). Een echte ATR vraagt
hoogste, laagste en slotkoers. De eerlijke tegenhanger is de gemiddelde ABSOLUTE verandering tussen opeenvolgende
waarnemingen, en dat is wat hier gemeten wordt.

POINT-IN-TIME. Voor elke waarneming telt het gemiddelde alleen de veranderingen die er VOOR lagen (het venster
eindigt vóór de waarneming zelf), anders zou een grote sprong zijn eigen drempel optrekken.

WAT NIET MEEDOET, EN HOE JE DAT ZIET. Het venster beslaat 30 kalenderdagen en heeft minstens MIN_VENSTER veranderingen
nodig. Een weekreeks (ICSA, NFCI, WALCL: ~4 per 30 dagen) en een maandreeks (CPI, banen: ~1) halen dat niet; een
stapreeks (de doelrange van de Fed) heeft vaak een gemiddelde van nul. Die paren zijn "niet te beoordelen" en tellen
niet mee in de triggers; de kolom `dekking` toont hoeveel van de paren wel beoordeeld konden worden. Een lage
dekking betekent dat de regel voor die reeks een ander venster of een ondergrens zou nodig hebben (roadmap 4.2, punt 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from calibration.trigger_calibration import DAYS_PER_YEAR, calibrate_series, metric_registry
from contract.resolution import eerste_prints
from scoring.resolver import observations_for

VENSTER_DAGEN = 30
MIN_VENSTER = 10
"""Minimaal aantal veranderingen in het venster om een gemiddelde te vertrouwen. Een keuze, geen berekening: bij een
dagreeks zijn dat ~21 per 30 dagen (alleen werkdagen), dus ruim gehaald; bij een weekreeks nooit."""
NS = (2, 3, 4, 5, 6)
DOEL_PER_JAAR = 5.0
"""De frequentie waar de huidige drempels op gekalibreerd zijn (calibrate_triggers, 29-09)."""
JAREN = 3.0
MIN_DEKKING = 0.8
"""Onder dit aandeel beoordeelbare paren is de telling niet vergelijkbaar met die van de huidige drempel."""
MIN_VENSTER_PCT = int(MIN_DEKKING * 100)


@dataclass(frozen=True)
class AtrResultaat:
    domain: str
    metric_key: str
    pairs: int                       # paren in het venster van de laatste drie jaar
    beoordeeld: int                  # daarvan paren met een bruikbaar 30-daags gemiddelde
    years: float
    per_jaar: dict[int, float | None]    # N -> triggers per jaar (None bij te korte historie)
    huidig_per_jaar: float | None

    @property
    def dekking(self) -> float | None:
        return self.beoordeeld / self.pairs if self.pairs else None

    @property
    def vergelijkbaar(self) -> bool:
        return self.dekking is not None and self.dekking >= MIN_DEKKING

    @property
    def n_dichtst_bij_doel(self) -> int | None:
        """De N waarvan het tempo het dichtst bij DOEL_PER_JAAR ligt (alleen als de reeks vergelijkbaar is)."""
        if not self.vergelijkbaar:
            return None
        kandidaten = [(abs(v - DOEL_PER_JAAR), n) for n, v in self.per_jaar.items() if v is not None]
        return min(kandidaten)[1] if kandidaten else None


def atr_tellingen(
    values: list[tuple[datetime, float]], ns: tuple[int, ...] = NS,
    venster_dagen: int = VENSTER_DAGEN, min_venster: int = MIN_VENSTER, vanaf: datetime | None = None,
) -> tuple[int, int, dict[int, int]]:
    """De kern, zonder database. Neemt de waarnemingen (oplopend) en geeft (paren, beoordeeld, triggers per N) over de
    paren waarvan de nieuwe waarneming op of na `vanaf` ligt (None = alles).

    Voor paar i (waarneming i tegenover i-1) is het gemiddelde dat van de |veranderingen| van de paren j < i waarvan de
    nieuwe waarneming binnen `venster_dagen` voor waarneming i lag. Vuren: |verandering i| > N * gemiddelde, STRIKT groter
    (zoals evaluate_surprise). Een gemiddelde van nul (stapreeks zonder beweging) maakt het paar niet beoordeelbaar,
    anders zou elke verandering vuren."""
    veranderingen = [(values[i][0], abs(values[i][1] - values[i - 1][1])) for i in range(1, len(values))]
    paren = beoordeeld = 0
    triggers = {n: 0 for n in ns}
    start = 0
    for i, (datum, afwijking) in enumerate(veranderingen):
        if vanaf is not None and datum < vanaf:
            continue
        paren += 1
        grens = datum - timedelta(days=venster_dagen)
        while start < i and veranderingen[start][0] < grens:
            start += 1
        venster = veranderingen[start:i]
        if len(venster) < min_venster:
            continue
        gemiddelde = sum(d for _, d in venster) / len(venster)
        if gemiddelde <= 0:
            continue
        beoordeeld += 1
        for n in ns:
            if afwijking > n * gemiddelde:
                triggers[n] += 1
    return paren, beoordeeld, triggers


def atr_proef_reeks(domain: str, metric_key: str, tolerance: float, values: list[tuple[datetime, float]]) -> AtrResultaat:
    if len(values) < 2:
        return AtrResultaat(domain, metric_key, 0, 0, 0.0, {n: None for n in NS}, None)
    ref, first = values[-1][0], values[0][0]
    vanaf = ref - timedelta(days=JAREN * DAYS_PER_YEAR)
    paren, beoordeeld, triggers = atr_tellingen(values, vanaf=vanaf)
    jaren = (ref - max(vanaf, first)).total_seconds() / 86400 / DAYS_PER_YEAR
    per_jaar = {n: (triggers[n] / jaren if jaren >= 0.25 else None) for n in NS}
    huidig = calibrate_series(domain, metric_key, tolerance, values).stats.get("3j")
    return AtrResultaat(
        domain, metric_key, paren, beoordeeld, max(jaren, 0.0), per_jaar,
        huidig.per_year if huidig is not None else None,
    )


def atr_proef_alles(conn, now: datetime, domain: str | None = None) -> list[AtrResultaat]:
    """Alle geregistreerde reeksen, tot en met `now` (point-in-time), op de splitsingsgecorrigeerde reeksen."""
    resultaten = []
    for dom, key, spec in metric_registry():
        if domain is not None and dom != domain:
            continue
        prints = [o for o in eerste_prints(observations_for(conn, key)) if o.source_time <= now and o.first_seen <= now]
        resultaten.append(atr_proef_reeks(dom, key, spec.tolerance, [(o.source_time, o.value) for o in prints]))
    return resultaten


def _f(x: float | None, breedte: int = 7) -> str:
    return "-".rjust(breedte) if x is None else f"{x:.1f}".rjust(breedte)


def render_atr_rapport(resultaten: list[AtrResultaat]) -> str:
    regels = [
        f"ATR-PROEF -- triggers per jaar bij 'N keer de gemiddelde absolute beweging van de afgelopen {VENSTER_DAGEN} dagen' (laatste {JAREN:.0f} jaar)",
        f"{'domein':<16}{'reeks':<28}{'nu':>7}" + "".join(f"{'N=' + str(n):>7}" for n in NS) + f"{'dekking':>9}{'N~5':>6}  opmerking",
    ]
    for r in resultaten:
        dekking = "-" if r.dekking is None else f"{r.dekking * 100:.0f}%"
        n5 = "-" if r.n_dichtst_bij_doel is None else str(r.n_dichtst_bij_doel)
        opm = "" if r.vergelijkbaar else "niet te beoordelen: te weinig waarnemingen per venster"
        regels.append(
            f"{r.domain:<16}{r.metric_key:<28}{_f(r.huidig_per_jaar)}" + "".join(_f(r.per_jaar.get(n)) for n in NS)
            + f"{dekking:>9}{n5:>6}  {opm}"
        )
    vergelijkbaar = [r for r in resultaten if r.vergelijkbaar]
    if vergelijkbaar:
        regels.append("")
        regels.append(f"TOTAAL over de {len(vergelijkbaar)} vergelijkbare reeksen (triggers per jaar):")
        regels.append(f"  {'nu (vaste drempels)':<24}{sum(r.huidig_per_jaar or 0.0 for r in vergelijkbaar):>8.1f}")
        for n in NS:
            regels.append(f"  {'N=' + str(n):<24}{sum(r.per_jaar.get(n) or 0.0 for r in vergelijkbaar):>8.1f}")
    regels.append("")
    regels.append(LEESWIJZER)
    return "\n".join(regels)


LEESWIJZER = f"""HOE TE LEZEN
- nu: hoe vaak de HUIDIGE vaste drempel (trigger-versie v4) per jaar gevuurd zou hebben, laatste drie jaar.
- N=2..6: hoe vaak de regel 'beweging > N x gemiddelde absolute beweging van de {VENSTER_DAGEN} dagen ervoor' zou vuren.
- dekking: aandeel van de paren waarvoor het venster minstens {MIN_VENSTER} veranderingen had. Onder {MIN_VENSTER_PCT}% staat de reeks als
  'niet te beoordelen': week- en maandreeksen (ICSA, NFCI, WALCL, CPI, banen) en stapreeksen passen niet in een venster van {VENSTER_DAGEN} dagen.
- N~5: de N die het dichtst bij {DOEL_PER_JAAR:.0f} triggers per jaar komt, het tempo waarop de huidige drempels gekalibreerd zijn.
- Dit is geen echte ATR (we bewaren alleen de slotkoers, geen hoogste/laagste): het is de gemiddelde absolute verandering tussen waarnemingen.
- Het gemiddelde telt alleen veranderingen van VOOR de waarneming, zodat een sprong zijn eigen drempel niet optrekt.
- Een rustige tijd laat een gewone beweging snel triggeren; in een crisis stijgt de drempel mee. Dit rapport laat dat niet zien: het telt alleen.
- Dit rapport wijzigt niets. Een volatiliteitsdrempel invoeren raakt de trigger-engine (checkpoint 2), vraagt een nieuwe trigger-versie en is een besluit van DD."""
