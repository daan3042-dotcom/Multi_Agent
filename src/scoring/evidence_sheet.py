"""
scoring/evidence_sheet.py
De CONTEXT die elke agent bij zijn forecast-ronde meekrijgt (roadmap 2.0, 4.1, "gestructureerde
evidence-sheet"; besluit DD 01-10-2026, optie B). Zuiver Python: geen LLM, geen netwerk, alleen lezen uit de
eigen database. Python rekent, Claude vertelt.

WAAROM DIT BESTAAT. Tot 01-10-2026 kreeg een agent per reeks één getal ("10-jaars yield: 4,12") en moest hij
daaruit kwantielen over 5, 21 en 63 dagen opschrijven. Een kwantiel is een uitspraak over SPREIDING, en die zat
nergens in de aangeleverde cijfers: het model moest hem uit zijn geheugen halen. De baselines (persistence en
climatology) krijgen wél alle historie. Dan meet de vergelijking agent-tegen-baseline vooral wie de maat kende,
niet wie beter redeneert. Deze sheet geeft de agent dezelfde soort informatie, als samenvatting.

WAT ER IN STAAT, per reeks (alleen wat uit onze eigen opgeslagen waarnemingen volgt, zoals bekend op `as_of`):
- de laatste waarde, de datum ervan en hoe oud hij is (CPI is van augustus, een yield van gisteren);
- de verandering ten opzichte van ongeveer 1 en 3 maanden eerder;
- het bereik van de laatste 52 weken en waar de waarde daarin staat;
- voor elk kwantieldoel en elke horizon: de STANDAARDDEVIATIE van de verandering over die horizon, over de laatste
  vijf jaar en over het laatste jaar;
- voor de FOMC-doelen: de laatste verandering van de doelrange, de veranderingen van de afgelopen twee jaar en de
  eerstvolgende vergaderdata.

BEWUSTE KEUZE: SPREIDING, GEEN KANT-EN-KLARE KWANTIELEN. De standaarddeviatie van de verandering is wat de
persistence-baseline ook gebruikt, maar de baseline-KWANTIELEN staan er bewust NIET in. Gaven we die mee, dan kan de
agent ze overschrijven en meet de test alleen nog of het model kan kopiëren. Nu moet hij zelf van spreiding naar
kwantielen, en dat (plus het oordeel over wat anders is dan het verleden) is wat getest wordt. Wil DD dit anders,
dan is het een promptwijziging (`prompt_version`), geen contractwijziging.

WAT ER NIET IN STAAT en ook niet verzonnen wordt: releasedata van CPI of banen (daar is geen kalender van), en de
uitkomst van eerdere FOMC-vergaderingen van vóór oktober 2026 (de kalender begint bij 28-10-2026).

POINT-IN-TIME. Alles gaat via `baselines._history`: alleen eerste prints die op `as_of` al bestonden. Zo kan de
pseudo-OOS-run (4.4) deze functie met een datum in het verleden gebruiken zonder dat de agent de toekomst ziet.

VENSTERS OVERLAPPEN. Opeenvolgende horizon-vensters delen bijna al hun data; het aantal (n=...) is dus GEEN aantal
onafhankelijke waarnemingen. Dat staat in de kop, omdat het model anders de zekerheid van de schatting overschat.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta

from agents.base import ForecastTarget
from contract.prediction import HorizonKind, PredictionKind
from contract.resolution import FOMC_MEETING_DATES, ResolutionMethod
from scoring.baselines import _history, _Insufficient, _sample, _Skip  # noqa: PLC2701 -- zelfde pakket

DAGEN_1_MAAND = 30
DAGEN_3_MAANDEN = 91
DAGEN_JAAR = 365
DAGEN_VIJF_JAAR = 5 * 365
MIN_VENSTERS_SPREIDING = 8
"""Minder dan dit aantal vensters en de standaarddeviatie wordt niet getoond. Dit is bewust LAGER dan `MIN_SAMPLES`
van de baselines (30): voor een maandreeks over één publicatie heeft het laatste jaar maar 12 vensters, en dan
liever een getal mét zijn n dan geen getal."""
MIN_WAARNEMINGEN_BEREIK = 6
VERANDERINGEN_LAATSTE_JAREN = 2


def _g(x: float) -> str:
    """Leesbaar getal: geheel boven 1000 (balanstotaal, claims), anders vier significante cijfers."""
    return f"{x:.0f}" if abs(x) >= 1000 else f"{x:.4g}"


def _s(x: float) -> str:
    """Zelfde, met teken."""
    return f"{x:+.0f}" if abs(x) >= 1000 else f"{x:+.4g}"


def _dag(d: datetime) -> str:
    return d.date().isoformat()


def _dagen(n: int) -> str:
    return "1 dag" if n == 1 else f"{n} dagen"


def _verschil(x: float) -> str:
    return "ongewijzigd" if x == 0 else _s(x)


def _op_of_voor(prints, moment: datetime):
    """De laatste print met `source_time` op of vóór `moment`, of None."""
    kandidaat = None
    for o in prints:
        if o.source_time <= moment:
            kandidaat = o
        else:
            break
    return kandidaat


def _reeksregel(label: str, key: str, prints, as_of: datetime) -> str:
    if not prints:
        return f"- {key} ({label}): geen opgeslagen waarnemingen op {as_of.date()}; geen context beschikbaar"
    laatste = prints[-1]
    leeftijd = (as_of.date() - laatste.source_time.date()).days
    delen = [f"laatste waarde {_g(laatste.value)} van {_dag(laatste.source_time)} ({_dagen(leeftijd)} oud)"]

    for naam, dagen in (("1 maand", DAGEN_1_MAAND), ("3 maanden", DAGEN_3_MAANDEN)):
        eerder = _op_of_voor(prints, laatste.source_time - timedelta(days=dagen))
        if eerder is not None:
            delen.append(f"{naam} eerder {_g(eerder.value)} ({_verschil(laatste.value - eerder.value)})")
        else:
            delen.append(f"{naam} eerder: te weinig historie")

    jaar = [o for o in prints if o.source_time > laatste.source_time - timedelta(days=DAGEN_JAAR)]
    if len(jaar) >= MIN_WAARNEMINGEN_BEREIK:
        waarden = [o.value for o in jaar]
        if min(waarden) == max(waarden):
            # Een stapreeks die een jaar niet bewoog: "hoger dan 100%" zou suggereren dat hij op een extreem staat.
            delen.append(f"laatste 52 weken: ongewijzigd op {_g(waarden[0])} ({len(waarden)} waarnemingen)")
        else:
            # Gelijke waarden tellen voor de helft mee, zodat een reeks op zijn laagste stand niet "hoger dan 100%" is.
            positie = (sum(1 for w in waarden if w < laatste.value) + 0.5 * sum(1 for w in waarden if w == laatste.value)) / len(waarden)
            delen.append(
                f"laatste 52 weken: laag {_g(min(waarden))}, hoog {_g(max(waarden))}, "
                f"nu hoger dan {positie:.0%} van die waarnemingen"
            )
    else:
        delen.append(f"laatste 52 weken: slechts {len(jaar)} waarnemingen, geen bereik")
    return f"- {key} ({label}): " + "; ".join(delen)


def _eenheid(target: ForecastTarget) -> str:
    return "handelsdagen" if target.horizon_kind is HorizonKind.TRADING_DAYS else "publicaties"


def _spreidingsregel(conn, target: ForecastTarget, as_of: datetime) -> str | None:
    """De standaarddeviatie van de verandering per horizon voor één kwantieldoel."""
    stukken = []
    for n in target.horizons:
        try:
            sample = _sample(conn, target, n, as_of)
        except _Skip:
            return None
        except _Insufficient as e:
            stukken.append(f"over {n} {_eenheid(target)}: niet te berekenen ({e})")
            continue
        vijf = [d for d, start in zip(sample.deltas, sample.dates) if start >= as_of - timedelta(days=DAGEN_VIJF_JAAR)]
        een = [d for d, start in zip(sample.deltas, sample.dates) if start >= as_of - timedelta(days=DAGEN_JAAR)]
        delen = []
        for naam, reeks in (("laatste 5 jaar", vijf), ("laatste jaar", een)):
            if len(reeks) >= MIN_VENSTERS_SPREIDING:
                delen.append(f"{naam} {_g(statistics.stdev(reeks))} (n={len(reeks)})")
            else:
                delen.append(f"{naam}: te weinig vensters ({len(reeks)})")
        stukken.append(f"over {n} {_eenheid(target)}: " + ", ".join(delen))
    unit = "procentpunt relatief rendement" if target.resolution_method is ResolutionMethod.RELATIVE_RETURN else "dezelfde eenheid als de reeks"
    return f"  Spreiding van de verandering ({target.metric_key}, standaarddeviatie, {unit}): " + "; ".join(stukken)


def _fomc_regels(conn, target: ForecastTarget, as_of: datetime) -> list[str]:
    prints = _history(conn, target.metric_key, as_of)
    if not prints:
        return [f"- {target.metric_key}: geen opgeslagen waarnemingen; geen FOMC-context beschikbaar"]
    veranderingen = [
        (b.source_time, b.value - a.value) for a, b in zip(prints, prints[1:]) if b.value != a.value
    ]
    regels = [f"- {target.metric_key} (FOMC-doel): huidige stand {_g(prints[-1].value)} van {_dag(prints[-1].source_time)}"]
    if veranderingen:
        wanneer, grootte = veranderingen[-1]
        regels.append(
            f"  Laatste verandering van de doelrange: {_s(grootte)} op {_dag(wanneer)} "
            f"({_dagen((as_of.date() - wanneer.date()).days)} geleden)"
        )
    else:
        regels.append("  In de opgeslagen historie is de doelrange nooit veranderd")
    recent = [(w, g) for w, g in veranderingen if w >= as_of - timedelta(days=VERANDERINGEN_LAATSTE_JAREN * 365)]
    regels.append(
        f"  Veranderingen in de laatste {VERANDERINGEN_LAATSTE_JAREN} jaar: "
        + (", ".join(f"{_s(g)} op {_dag(w)}" for w, g in recent) if recent else "geen")
    )
    komend = [m for m in sorted(FOMC_MEETING_DATES) if m > as_of.date()][: max(target.horizons)]
    regels.append(
        "  Eerstvolgende FOMC-besluitdagen: "
        + (", ".join(f"{m.isoformat()} (over {_dagen((m - as_of.date()).days)})" for m in komend) if komend else "onbekend (kalender is op)")
    )
    return regels


def build_evidence_sheet(
    conn, targets: list[ForecastTarget] | tuple[ForecastTarget, ...], claims, as_of: datetime
) -> str:
    """De context-tekst voor één agent. `claims` zijn de claims van de laatste cyclus (bepalen welke reeksen
    aan bod komen); `as_of` bepaalt wat er bekend is. Geeft nooit een uitzondering voor ontbrekende data: een reeks
    zonder historie krijgt een regel die dat zegt (stil weglaten zou het model laten raden)."""
    volgorde: list[str] = []
    labels: dict[str, str] = {}
    for c in claims:
        if c.metric_key and c.metric_key not in labels:
            volgorde.append(c.metric_key)
            labels[c.metric_key] = c.claim

    regels = [
        f"Context per reeks, door Python berekend uit onze eigen opgeslagen waarnemingen zoals bekend op {as_of.date()} "
        f"(geen voorspelling; vensters overlappen, dus n telt niet als onafhankelijke waarnemingen):"
    ]
    for key in volgorde:
        regels.append(_reeksregel(labels[key], key, _history(conn, key, as_of), as_of))
        for t in targets:
            if t.metric_key == key and t.kind is PredictionKind.QUANTILE:
                regel = _spreidingsregel(conn, t, as_of)
                if regel:
                    regels.append(regel)

    fomc = [t for t in targets if t.resolution_method is ResolutionMethod.DIRECTION_AFTER_FOMC]
    if fomc:
        regels.append("")
        regels.append("Context voor de FOMC-vragen:")
        for t in fomc:
            regels.extend(_fomc_regels(conn, t, as_of))
    return "\n".join(regels)
