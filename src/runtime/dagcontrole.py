"""
runtime/dagcontrole.py
De dagelijkse controle voor de begeleide weken en de dry-run-week (roadmap fase 3b, checkpoint 3): ÉÉN scherm in plaats van
vijf losse commando's. ALLEEN LEZEN: de database gaat open met `mode=ro`, logbestanden en mappen worden alleen gelezen, er
wordt niets aangeroepen op het netwerk en niets gewijzigd.

WAT HET CONTROLEERT, voor één dag (default: vandaag, UTC):
  run              per agent een succesvolle monitoring-run, geen volledigheidstrigger (dezelfde definitie als de T₀ᵃ-teller:
                   `runtime/t0a_status.py`, geen tweede regelset)
  triggers         aantal per domein; draagt elke trigger de huidige `TRIGGER_VERSION`?
  claims           heeft elk domein die dag claims opgeslagen?
  bronnen          mislukte bronchecks in `data_health`
  voorspellingen   aantal per cohort; op een maandag moet de forecast-ronde er zijn
  llm-verbruik     de maandrem (aandeel van de grens)
  log              WARNING/ERROR/CRITICAL-regels van die dag uit daily.log (Alpha Vantage-redenen, splitsing-waarschuwingen,
                   forecast-/baseline-problemen, resolver-fouten), en wat de run zei over cohort en trigger-versie
  back-up          is het back-uplog van vandaag bijgewerkt, en staat er een fout in?
  archief          staat er een SPY-bestand van vandaag in het manifest?
  schijf           hoe vol is de schijf?

ONBEKEND IS GEEN OK (zelfde regel als de T₀ᵃ-teller en CLAUDE.md: een check mag nooit stilzwijgend overgeslagen worden bij
ontbrekende data). Is het logbestand er niet, dan staat er ONBEKEND, niet ok. Voor een tijdstip dat nog niet verstreken is
(de cron van 07:15, de back-up van 08:00, het archief van 08:30) staat er "nog niet", dat geen LET OP is.

WAT HET NIET KAN: beoordelen of een analyse goed is, of er handmatig ingegrepen is, of de back-up herstelbaar is (daarvoor
is de hersteltest). Het zegt wat er in de bestanden staat.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from contract.trigger_version import TRIGGER_VERSION
from runtime import llm_budget
from runtime.t0a_status import GEEN_RUN, NIET_SCHOON, SCHOON, beoordeel_dag, verwachte_domeinen

OK = "ok"
LET_OP = "LET OP"
ONBEKEND = "ONBEKEND"
INFO = "info"
NOG_NIET = "nog niet"

# Cron-tijden in UTC (docs/deployment.md): de dagelijkse run 07:15, de back-up 08:00, het SPY-archief 08:30.
RUN_KLAAR = time(7, 45)
BACKUP_KLAAR = time(8, 15)
ARCHIEF_KLAAR = time(8, 45)
SCHIJF_WAARSCHUWING = 0.85
"""Vanaf welk aandeel van de schijf er LET OP staat. Op 02-10 was 11% van 23 GB in gebruik; een keuze, geen berekening."""
MAX_LOGREGELS = 12
LOGNIVEAUS = ("WARNING", "ERROR", "CRITICAL")
SLEUTELREGELS = ("Cohort voor nieuwe voorspellingen", "Trigger-versie:", "Forecast-ronde:", "Baseline-ronde:")
BACKUP_FOUTEN = ("error", "denied", "failed", "no such file", "unable", "fatal")


@dataclass(frozen=True)
class Regel:
    onderwerp: str
    status: str
    tekst: str


def _dag_van(tekst: str) -> date | None:
    try:
        return datetime.fromisoformat(tekst).astimezone(timezone.utc).date()
    except (ValueError, TypeError):
        return None


def _verstreken(dag: date, moment: time, nu: datetime) -> bool:
    """Is `moment` (UTC) op `dag` al voorbij? Een eerdere dag altijd; een latere dag nooit."""
    grens = datetime.combine(dag, moment, tzinfo=timezone.utc)
    return nu.astimezone(timezone.utc) >= grens


def _nog_niet(onderwerp: str, tekst: str) -> Regel:
    return Regel(onderwerp, NOG_NIET, tekst)


def controleer_run(conn: sqlite3.Connection, dag: date, nu: datetime, domeinen: list[str]) -> list[Regel]:
    if dag.weekday() >= 5:
        return [Regel("run", INFO, f"{dag} is een weekend: de cron draait alleen ma t/m vr")]
    s = beoordeel_dag(conn, dag, domeinen)
    if s.status == GEEN_RUN and not _verstreken(dag, RUN_KLAAR, nu):
        return [_nog_niet("run", "de run van 07:15 UTC is er nog niet (of net bezig)")]
    if s.status == SCHOON:
        uit = [Regel("run", OK, f"alle {len(domeinen)} agents ok, geen volledigheidstrigger (schone dag)")]
    else:
        uit = [Regel("run", LET_OP, f"{s.status}: " + "; ".join(s.redenen))] if s.status in (NIET_SCHOON, GEEN_RUN) else [
            Regel("run", ONBEKEND, f"onverwachte status {s.status}")
        ]
    if s.mogelijk_handmatig:
        uit.append(Regel("run", LET_OP, "een run viel buiten het cron-venster (07-09 UTC): handmatig? Beoordeel zelf"))
    return uit


def controleer_triggers(conn: sqlite3.Connection, dag: date) -> list[Regel]:
    rijen = [r for r in conn.execute("SELECT domain, triggered_at, trigger_version FROM trigger_events").fetchall()
             if _dag_van(r[1]) == dag]
    if not rijen:
        return [Regel("triggers", INFO, "geen triggers vandaag")]
    per_domein: dict[str, int] = {}
    for dom, _, _ in rijen:
        per_domein[dom] = per_domein.get(dom, 0) + 1
    tekst = f"{len(rijen)} trigger(s): " + ", ".join(f"{d} {n}" for d, n in sorted(per_domein.items()))
    versies = {r[2] for r in rijen}
    uit = [Regel("triggers", INFO, tekst)]
    if versies != {TRIGGER_VERSION}:
        uit.append(Regel("triggers", LET_OP,
                         f"trigger-versie in de database {sorted(v or '(leeg)' for v in versies)} wijkt af van de code ({TRIGGER_VERSION})"))
    return uit


def controleer_claims(conn: sqlite3.Connection, dag: date, domeinen: list[str]) -> list[Regel]:
    per_domein = {d: 0 for d in domeinen}
    # De claims-tabel is groot (~175.000 rijen na de back-fill): eerst op tekst voorfilteren met een dag marge aan beide kanten
    # (tijdzone-offsets), dan pas exact op UTC-dag.
    van, tot = (dag - timedelta(days=1)).isoformat(), (dag + timedelta(days=2)).isoformat()
    for dom, ingestie in conn.execute(
        "SELECT domain, ingestion_time FROM claims WHERE ingestion_time >= ? AND ingestion_time < ?", (van, tot)
    ).fetchall():
        if dom in per_domein and _dag_van(ingestie) == dag:
            per_domein[dom] += 1
    leeg = [d for d, n in per_domein.items() if n == 0]
    if leeg:
        return [Regel("claims", LET_OP, f"geen claims opgeslagen voor: {', '.join(leeg)}")]
    return [Regel("claims", OK, f"{sum(per_domein.values())} claims, elk domein minstens één")]


def controleer_bronnen(conn: sqlite3.Connection, dag: date) -> list[Regel]:
    mislukt = [(b, d) for b, c, ok, d in conn.execute(
        "SELECT source, checked_at, success, detail FROM data_health").fetchall() if not ok and _dag_van(c) == dag]
    if not mislukt:
        return [Regel("bronnen", OK, "geen mislukte bronchecks")]
    return [Regel("bronnen", LET_OP, f"{b}: {(d or '')[:100]}") for b, d in mislukt[:MAX_LOGREGELS]]


def controleer_voorspellingen(conn: sqlite3.Connection, dag: date, nu: datetime) -> list[Regel]:
    rijen = [r for r in conn.execute("SELECT cohort, created_at FROM predictions").fetchall() if _dag_van(r[1]) == dag]
    per_cohort: dict[str, int] = {}
    for cohort, _ in rijen:
        per_cohort[cohort] = per_cohort.get(cohort, 0) + 1
    tekst = ", ".join(f"{c} {n}" for c, n in sorted(per_cohort.items()))
    if dag.weekday() == 0:   # maandag: forecast-ronde
        if rijen:
            return [Regel("voorspellingen", OK, f"forecast-ronde aanwezig: {tekst}")]
        if not _verstreken(dag, RUN_KLAAR, nu):
            return [_nog_niet("voorspellingen", "de forecast-ronde komt met de run van 07:15 UTC")]
        return [Regel("voorspellingen", LET_OP, "maandag zonder forecast-ronde (een ronde haalt zich alleen binnen dezelfde ISO-week in)")]
    return [Regel("voorspellingen", INFO, tekst if rijen else "geen voorspellingen (geen maandag)")]


def controleer_llm(conn: sqlite3.Connection, nu: datetime, max_bedrag: float | None = None) -> list[Regel]:
    grens = llm_budget.STANDAARD_MAX_MAANDBEDRAG_USD if max_bedrag is None else max_bedrag
    v = llm_budget.maandverbruik(conn, nu)
    tekst = f"deze maand ${v.kosten_usd:.2f} van ${grens:.0f} ({v.aanroepen} aanroepen)"
    if v.kosten_usd >= grens * llm_budget.WAARSCHUWING_VANAF:
        return [Regel("llm-verbruik", LET_OP, tekst + f", boven {llm_budget.WAARSCHUWING_VANAF:.0%} van de grens")]
    return [Regel("llm-verbruik", OK, tekst)]


def controleer_log(pad: Path | None, dag: date) -> list[Regel]:
    if pad is None or not pad.exists():
        return [Regel("log", ONBEKEND, f"logbestand niet gevonden ({pad}): de WARNING/ERROR-regels van vandaag zijn niet gecontroleerd")]
    voorvoegsel = dag.isoformat()
    van_vandaag = [r for r in pad.read_text(encoding="utf-8", errors="replace").splitlines() if r.startswith(voorvoegsel)]
    if not van_vandaag:
        return [Regel("log", LET_OP, f"geen enkele logregel van {dag} in {pad} (de run heeft niets geschreven, of de logklok staat niet op UTC)")]
    uit: list[Regel] = []
    problemen = [r for r in van_vandaag if any(f" {n} " in r for n in LOGNIVEAUS)]
    for r in problemen[:MAX_LOGREGELS]:
        uit.append(Regel("log", LET_OP, r[:220]))
    if len(problemen) > MAX_LOGREGELS:
        uit.append(Regel("log", LET_OP, f"... en nog {len(problemen) - MAX_LOGREGELS} regels; zie het log"))
    if not problemen:
        uit.append(Regel("log", OK, f"{len(van_vandaag)} regels, geen WARNING/ERROR/CRITICAL"))
    for r in van_vandaag:
        if any(s in r for s in SLEUTELREGELS):
            uit.append(Regel("log", INFO, re.sub(r"^\S+ \S+ INFO \S+: ", "", r)[:200]))
    return uit


def controleer_backup(pad: Path | None, dag: date, nu: datetime) -> list[Regel]:
    # De back-up draait elke dag (cron 0 8 * * *), ook in het weekend: geen weekendregel hier.
    if pad is None or not pad.exists():
        return [Regel("back-up", ONBEKEND, f"back-uplog niet gevonden ({pad}): niet gecontroleerd")]
    gewijzigd = datetime.fromtimestamp(pad.stat().st_mtime, tz=timezone.utc)
    laatste = [r for r in pad.read_text(encoding="utf-8", errors="replace").splitlines() if r.strip()][-5:]
    fouten = [r for r in laatste if any(f in r.lower() for f in BACKUP_FOUTEN)]
    if fouten:
        return [Regel("back-up", LET_OP, "fout in de laatste regels van het back-uplog: " + fouten[-1][:160])]
    if gewijzigd.date() == dag:
        return [Regel("back-up", OK, f"back-uplog bijgewerkt om {gewijzigd:%H:%M} UTC, geen foutregels")]
    if not _verstreken(dag, BACKUP_KLAAR, nu):
        return [_nog_niet("back-up", "de back-up van 08:00 UTC is er nog niet")]
    return [Regel("back-up", LET_OP, f"back-uplog voor het laatst bijgewerkt op {gewijzigd:%Y-%m-%d %H:%M} UTC, niet op {dag}")]


def controleer_archief(basis: Path | None, dag: date, nu: datetime) -> list[Regel]:
    from archive import spy_holdings

    if basis is None or not basis.exists():
        return [Regel("archief", ONBEKEND, f"archiefmap niet gevonden ({basis}): niet gecontroleerd")]
    try:
        records = spy_holdings.lees_manifest(basis)
    except (OSError, ValueError) as e:
        return [Regel("archief", LET_OP, f"manifest niet te lezen: {type(e).__name__}: {e}")]
    dagstempel = f"_{dag.isoformat()}."
    van_vandaag = [r for r in records if dagstempel in r.get("path", "")]
    if van_vandaag:
        r = van_vandaag[-1]
        return [Regel("archief", OK, f"bestand van {dag} gearchiveerd (as_of {r.get('as_of')})")]
    if not _verstreken(dag, ARCHIEF_KLAAR, nu):
        return [_nog_niet("archief", "het archief van 08:30 UTC is er nog niet")]
    return [Regel("archief", LET_OP, f"geen archiefbestand van {dag} in het manifest ({len(records)} records)")]


def controleer_schijf(pad: str = "/", gebruikt: float | None = None) -> list[Regel]:
    if gebruikt is None:
        try:
            u = shutil.disk_usage(pad)
        except OSError as e:
            return [Regel("schijf", ONBEKEND, f"niet te lezen: {e}")]
        gebruikt = u.used / u.total
    tekst = f"{gebruikt:.0%} in gebruik"
    return [Regel("schijf", LET_OP if gebruikt >= SCHIJF_WAARSCHUWING else OK, tekst)]


def controleer_alles(
    conn: sqlite3.Connection, dag: date, nu: datetime | None = None, *, log: Path | None = None,
    backup_log: Path | None = None, archief: Path | None = None, domeinen: list[str] | None = None,
    schijf_pad: str = "/",
) -> list[Regel]:
    nu = nu or datetime.now(timezone.utc)
    domeinen = domeinen if domeinen is not None else verwachte_domeinen()
    regels: list[Regel] = []
    regels += controleer_run(conn, dag, nu, domeinen)
    regels += controleer_triggers(conn, dag)
    regels += controleer_claims(conn, dag, domeinen) if _verstreken(dag, RUN_KLAAR, nu) and dag.weekday() < 5 else [
        Regel("claims", INFO, "niet beoordeeld: weekend of de run is er nog niet")]
    regels += controleer_bronnen(conn, dag)
    regels += controleer_voorspellingen(conn, dag, nu)
    regels += controleer_llm(conn, nu)
    regels += controleer_log(log, dag)
    regels += controleer_backup(backup_log, dag, nu)
    regels += controleer_archief(archief, dag, nu)
    regels += controleer_schijf(schijf_pad)
    return regels


def heeft_aandacht(regels: list[Regel]) -> bool:
    return any(r.status in (LET_OP, ONBEKEND) for r in regels)


def format_controle(dag: date, regels: list[Regel]) -> str:
    uit = [f"DAGCONTROLE {dag} ({dag.strftime('%a')}) -- alleen lezen, wijzigt niets", ""]
    vorige = None
    for r in regels:
        onderwerp = r.onderwerp if r.onderwerp != vorige else ""
        uit.append(f"  {onderwerp:<16}{r.status:<10}{r.tekst}")
        vorige = r.onderwerp
    uit.append("")
    aandacht = [r for r in regels if r.status in (LET_OP, ONBEKEND)]
    if aandacht:
        uit.append(f"RESULTAAT: {len(aandacht)} punt(en) vragen aandacht ({', '.join(sorted({r.onderwerp for r in aandacht}))}).")
        uit.append("           'ONBEKEND' betekent: niet gecontroleerd, dus niet goedgekeurd.")
    else:
        uit.append("RESULTAAT: alles ok (of 'nog niet' / 'info').")
    return "\n".join(uit) + "\n"
