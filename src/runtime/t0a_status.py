"""
runtime/t0a_status.py
De teller voor T₀ᵃ, de ingestieklok (roadmap 1.11). ALLEEN LEZEN.

DE DEFINITIE (beslist 01-10-2026, docs/roadmap.md "Herzieningen"). Een werkdag is
SCHOON als:
  1. elk van de zes agents die dag een succesvolle monitoring-run had, EN
  2. er die dag geen volledigheidstrigger was (een reeks die de bron niet
     leverde, "completeness: ... ontbreekt: ...").
Een niet-schone dag zet de teller op nul ("zeven op rij"). Zeven schone
werkdagen op rij = T₀ᵃ gehaald. Weekenden tellen niet mee en breken niets.

WAAROM DIT EEN SCRIPT IS. Zonder dit moet iemand elke ochtend in de log en de
database zoeken, en één verkeerd geteld getal geeft een verkeerde T₀ᵃ-datum.
Alle regels staan hier, getest, in plaats van in iemands hoofd.

WAT HET NIET KAN: bewijzen dat er geen handmatige actie was. Een run die buiten
het venster van de cron valt (`CRON_UUR_UTC`) krijgt de markering "mogelijk
handmatig". Dat is een vermoeden, geen bewijs, en het telt NIET als niet-schoon:
de definitie hierboven kent die voorwaarde niet. DD beoordeelt zelf.

ONBEKEND IS GEEN SCHOON. Een dag zonder enige run staat als "geen run", niet als
"schoon", en breekt de reeks. Een dag in de toekomst of vandaag-nog-niet-gedraaid
staat als "nog niet", en breekt niets.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

DAGEN_VOOR_T0A = 7
STARTDATUM = date(2026, 10, 2)
"""De eerste dag van de lopende telling: de run van 01-10 was niet schoon (sector
10 van 12 reeksen), dus de reeks herstartte op 02-10."""
CRON_UUR_UTC = (7, 8)
"""De cron draait 07:15 UTC; een run met `run_at` buiten uur 7 of 8 (UTC) is
vermoedelijk met de hand gedaan."""

SCHOON = "schoon"
NIET_SCHOON = "NIET SCHOON"
GEEN_RUN = "GEEN RUN"
NOG_NIET = "nog niet"


def verwachte_domeinen() -> list[str]:
    """De zes agents zoals de dagelijkse run ze kent, rechtstreeks uit
    `runtime.daily.default_agents()`: geen tweede lijst die uit de pas kan
    lopen als er een agent bijkomt."""
    from runtime.daily import default_agents

    return [a.domain for a in default_agents()]


@dataclass
class DagStatus:
    dag: date
    status: str
    redenen: list[str] = field(default_factory=list)
    trigger_versies: list[str] = field(default_factory=list)
    mogelijk_handmatig: bool = False


@dataclass
class T0aStand:
    start: date
    dagen: list[DagStatus]
    huidige_reeks: int
    gehaald_op: date | None
    vroegste_datum: date | None  # als elke komende werkdag schoon is
    versie_wisselt: bool


def werkdagen(van: date, tot: date) -> list[date]:
    uit, d = [], van
    while d <= tot:
        if d.weekday() < 5:
            uit.append(d)
        d += timedelta(days=1)
    return uit


def _dag(tekst: str) -> date:
    return datetime.fromisoformat(tekst).astimezone(timezone.utc).date()


def _uur(tekst: str) -> int:
    return datetime.fromisoformat(tekst).astimezone(timezone.utc).hour


def beoordeel_dag(conn: sqlite3.Connection, dag: date, domeinen: list[str]) -> DagStatus:
    runs = [
        r for r in conn.execute(
            "SELECT domain, run_at, success, error FROM agent_runs WHERE mode = 'monitoring'"
        ).fetchall()
        if _dag(r[1]) == dag
    ]
    triggers = [
        r for r in conn.execute("SELECT reason, triggered_at, trigger_version FROM trigger_events").fetchall()
        if _dag(r[1]) == dag
    ]
    versies = sorted({t[2] for t in triggers if t[2]})
    if not runs:
        return DagStatus(dag, GEEN_RUN, ["geen enkele monitoring-run gevonden"])

    redenen: list[str] = []
    for dom in domeinen:
        eigen = [r for r in runs if r[0] == dom]
        if not any(r[2] for r in eigen):
            fout = next((r[3] for r in eigen if r[3]), None)
            redenen.append(f"{dom}: " + (f"mislukt ({fout[:80]})" if fout else "geen succesvolle run"))
    for reden, _, _ in triggers:
        if reden.startswith("completeness"):
            redenen.append(reden[:140])
    handmatig = any(r[2] and _uur(r[1]) not in CRON_UUR_UTC for r in runs)
    return DagStatus(dag, NIET_SCHOON if redenen else SCHOON, redenen, versies, handmatig)


def bereken_stand(
    conn: sqlite3.Connection,
    nu: datetime | None = None,
    start: date = STARTDATUM,
    domeinen: list[str] | None = None,
) -> T0aStand:
    nu = nu or datetime.now(timezone.utc)
    domeinen = domeinen if domeinen is not None else verwachte_domeinen()
    vandaag = nu.astimezone(timezone.utc).date()

    dagen: list[DagStatus] = []
    for d in werkdagen(start, vandaag):
        s = beoordeel_dag(conn, d, domeinen)
        if s.status == GEEN_RUN and d == vandaag:
            # Vandaag kan de cron nog moeten draaien (07:15): geen oordeel, geen breuk.
            s = DagStatus(d, NOG_NIET, ["vandaag nog niet gedraaid"])
        dagen.append(s)

    reeks, gehaald_op = 0, None
    for s in dagen:
        if s.status == SCHOON:
            reeks += 1
            if reeks == DAGEN_VOOR_T0A and gehaald_op is None:
                gehaald_op = s.dag  # eenmaal gehaald blijft gehaald: de klok loopt dan
        elif s.status != NOG_NIET:
            reeks = 0

    vroegste = None
    if gehaald_op is None:
        # Projectie: elke volgende werkdag schoon. Vandaag telt mee zolang hij nog niet gedraaid is.
        d = max(vandaag, start)
        if dagen and dagen[-1].status != NOG_NIET:
            d = max(vandaag + timedelta(days=1), start)
        tel = reeks
        while vroegste is None:
            if d.weekday() < 5:
                tel += 1
                if tel == DAGEN_VOOR_T0A:
                    vroegste = d
            d += timedelta(days=1)

    versie_set = {v for s in dagen if s.status == SCHOON for v in s.trigger_versies}
    wisselt = len(versie_set) > 1
    return T0aStand(start, dagen, reeks, gehaald_op, vroegste, wisselt)


def format_stand(stand: T0aStand) -> str:
    uit = [
        f"T₀ᵃ-TELLER (alleen lezen). Telling begint op {stand.start}. "
        f"Schoon = alle agents ok én geen volledigheidstrigger; een niet-schone dag zet de teller op nul.",
        "",
    ]
    for s in stand.dagen:
        extra = "  [mogelijk handmatig: run buiten het cron-venster]" if s.mogelijk_handmatig else ""
        uit.append(f"  {s.dag} ({s.dag.strftime('%a')})  {s.status}{extra}")
        for r in s.redenen:
            uit.append(f"      - {r}")
    uit.append("")
    if stand.gehaald_op is not None:
        uit.append(f"RESULTAAT: T₀ᵃ GEHAALD op {stand.gehaald_op} ({DAGEN_VOOR_T0A} schone werkdagen op rij).")
    else:
        uit.append(f"RESULTAAT: lopende reeks {stand.huidige_reeks} van {DAGEN_VOOR_T0A} schone werkdagen.")
        if stand.vroegste_datum:
            uit.append(f"           Op zijn vroegst gehaald op {stand.vroegste_datum} als elke komende werkdag schoon is.")
    if any(s.mogelijk_handmatig for s in stand.dagen):
        uit.append("LET OP:    minstens één run viel buiten het cron-venster; beoordeel zelf of dat handmatige actie was.")
    if stand.versie_wisselt:
        uit.append("LET OP:    de trigger-versie wisselt binnen de schone dagen; controleer dat dat bedoeld was.")
    return "\n".join(uit) + "\n"
