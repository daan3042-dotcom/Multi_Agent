"""
runtime/freeze_voorwaarden.py
De VOORWAARDEN vóór de klok (roadmap T₀ᵇ-checklist), als tweede helft van het freeze-overzicht. ALLEEN LEZEN.

Het freeze-overzicht (`freeze_status.py`) toont wat DD bij de freeze moet bevestigen. Dit toont wat er DAARVOOR
gedaan moet zijn: de T₀ᵃ-telling, de begeleide testrun, de pseudo-OOS-run, de dry-run-week. Samen is dat de ene plek
waar je ziet wat er nog tussen nu en de klok staat.

DRIE STATUSSEN, en het verschil is belangrijk:
  AF                  uit de data af te leiden en voldaan (T₀ᵃ gehaald). Alleen hier mag een systeem zelf "klaar" zeggen.
  NOG NIET AF         uit de data af te leiden en NIET voldaan (nog nul rondes, de dag is er nog niet).
  ZELF CONTROLEREN    de data laat zien dát iets gedaan is, maar niet of het GOED is gedaan, óf het is helemaal niet
                      uit de data af te leiden (back-up hersteld, machine uitgezet). Dit is een oordeel van DD.

Wat de database niet kan bewijzen, wordt NOOIT AF genoemd (CLAUDE.md: nooit stilzwijgend een beste gok). Is de
database er niet, dan staat elke datagedreven regel op ZELF CONTROLEREN met "onbekend", niet op NOG NIET AF: dat zou
een kale checkout die niets weet als een stand van zaken presenteren.

Elke waarde wordt bij het aanroepen uit de database en de code gelezen, nooit gekopieerd. De database gaat `mode=ro` open.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

# Het voorstel uit docs/deployment.md (fase 3, "Dry-run-week") en de roadmap (fase 3b). Hier één keer vastgelegd;
# een verschuiving past DD hier en in de docs aan.
DRY_RUN_WEEK_VAN = date(2026, 10, 27)
DRY_RUN_WEEK_TOT = date(2026, 11, 9)

# Roadmap T₀ᵇ-checklist: "14 dagen op rij zonder handmatige actie". De cron draait op werkdagen, dus dit telt
# WERKDAGEN. De roadmap zegt "dagen"; dat is een interpretatie die in de opmerking wordt gevlagd (checkpoint 4).
DAGEN_ZONDER_HANDMATIGE_ACTIE = 14

# Roadmap/handoff: meer dan 5% niet-opgeleverde voorspellingen in de forecast-rondes = het contract heroverwegen.
MAX_AFGEWEZEN_AANDEEL = 0.05

AF = "AF"
NOG_NIET_AF = "NOG NIET AF"
ZELF_CONTROLEREN = "ZELF CONTROLEREN"

GROEP = "VOORWAARDEN VÓÓR DE KLOK"


def _open(db_pad: str | None) -> sqlite3.Connection | None:
    if not db_pad or not Path(db_pad).exists():
        return None
    return sqlite3.connect(f"file:{db_pad}?mode=ro", uri=True)


def _dd_mm(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _t0a_regels(conn, nu: datetime):
    """(T₀ᵃ, 14 dagen op rij zonder handmatige actie). Beide uit dezelfde dagbeoordeling als `t0a_status.py`."""
    from runtime import t0a_status as t0a

    stand = t0a.bereken_stand(conn, nu=nu)
    uit = []
    if stand.gehaald_op is not None:
        uit.append(("T₀ᵃ (ingestieklok)", f"gehaald op {_dd_mm(stand.gehaald_op)}", AF, "eenmaal gehaald blijft gehaald"))
    else:
        vroegst = f", op zijn vroegst {_dd_mm(stand.vroegste_datum)}" if stand.vroegste_datum else ""
        uit.append((
            "T₀ᵃ (ingestieklok)",
            f"reeks {stand.huidige_reeks} van {t0a.DAGEN_VOOR_T0A} schone werkdagen{vroegst}", NOG_NIET_AF,
            "details: `t0a_status.py`",
        ))

    # Achteraan tellen: schoon én niet "mogelijk handmatig". Een dag die nog niet gedraaid is (vandaag) onderbreekt niet.
    reeks = 0
    for dag in reversed(stand.dagen):
        if dag.status == t0a.NOG_NIET:
            continue
        if dag.status == t0a.SCHOON and not dag.mogelijk_handmatig:
            reeks += 1
        else:
            break
    opm = (f"telt werkdagen (de roadmap zegt 'dagen'; kalenderdagen zou langer duren: jouw interpretatie); "
           f"een run buiten 07:00-09:00 UTC telt als mogelijk handmatig")
    if reeks >= DAGEN_ZONDER_HANDMATIGE_ACTIE:
        uit.append((f"{DAGEN_ZONDER_HANDMATIGE_ACTIE} werkdagen op rij zonder handmatige actie", f"{reeks} werkdagen", AF, opm))
    else:
        uit.append((f"{DAGEN_ZONDER_HANDMATIGE_ACTIE} werkdagen op rij zonder handmatige actie",
                    f"{reeks} van {DAGEN_ZONDER_HANDMATIGE_ACTIE}", NOG_NIET_AF, opm))
    return uit


def _deep_dive_regel(conn):
    n, domeinen, laatste = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT domain), MAX(called_at) FROM llm_calls WHERE purpose = 'deep_dive' AND error IS NULL"
    ).fetchone()
    if not n:
        return ("Begeleide deep-dive-testrun", "nog geen deep-dive met het echte model", NOG_NIET_AF,
                "voorwaarden en stappen: docs/deployment.md (fase 1)")
    return ("Begeleide deep-dive-testrun", f"{n} aanroepen, {domeinen} domein(en), laatste {laatste[:10]}", ZELF_CONTROLEREN,
            "dat het draaide is te zien; of de analyse OPRECHT GOED is, beoordeel jij (ruwe antwoorden: llm_calls)")


def _forecast_regel(conn, verwacht_per_domein: dict[str, int]):
    rondes = conn.execute("SELECT domain, trigger_count FROM agent_runs WHERE mode = 'forecast'").fetchall()
    if not rondes:
        return ("Forecast-rondes met het echte model", "nog geen ronde gedraaid", NOG_NIET_AF,
                "de eerste wekelijkse ronde is een maandagochtend")
    verwacht = sum(verwacht_per_domein.get(dom, 0) for dom, _ in rondes)
    kreeg = sum(n or 0 for _, n in rondes)
    gemist = max(verwacht - kreeg, 0)
    aandeel = gemist / verwacht if verwacht else 0.0
    waarde = f"{len(rondes)} agent-rondes, {kreeg} van {verwacht} voorspellingen opgeleverd ({aandeel:.1%} gemist)"
    if aandeel > MAX_AFGEWEZEN_AANDEEL:
        return ("Forecast-rondes met het echte model", waarde, "LET OP",
                f"meer dan {MAX_AFGEWEZEN_AANDEEL:.0%} gemist: het contract (vijf kwantielen) heroverwegen; zie `llm_calls` voor het waarom")
    return ("Forecast-rondes met het echte model", waarde, ZELF_CONTROLEREN,
            f"onder {MAX_AFGEWEZEN_AANDEEL:.0%}; hoeveel rondes genoeg zijn om dat te geloven beoordeel jij. "
            f"Een mislukte LLM-aanroep telt als gemist")


def _resolver_regel(conn):
    totaal, releases = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(p.horizon_kind = 'releases'), 0) FROM evaluations e "
        "JOIN predictions p ON p.id = e.prediction_id WHERE e.status = 'resolved'"
    ).fetchone()
    if not totaal:
        return ("Resolver heeft afgewikkeld (incl. release-horizon)", "nog niets afgewikkeld", NOG_NIET_AF,
                "kan pas als de eerste horizon verstrijkt")
    if not releases:
        return ("Resolver heeft afgewikkeld (incl. release-horizon)", f"{totaal} afgewikkeld, geen release-horizon", NOG_NIET_AF,
                "de checklist vraagt ook een release-gebaseerde horizon")
    return ("Resolver heeft afgewikkeld (incl. release-horizon)", f"{totaal} afgewikkeld, waarvan {releases} release-gebaseerd",
            ZELF_CONTROLEREN, "dat er afgewikkeld is, is te zien; of de uitkomsten KLOPPEN controleer jij op een steekproef")


def _pseudo_oos_regel(conn):
    n = conn.execute("SELECT COUNT(*) FROM predictions WHERE cohort = 'pseudo_oos'").fetchone()[0]
    if not n:
        return ("Pseudo-OOS-run (4.4)", "nog niet gedraaid", NOG_NIET_AF,
                "vraagt FOMC-besluitdagen van vóór oktober 2026 (nu leeg, zie FOMC-kalender hierboven)")
    return ("Pseudo-OOS-run (4.4)", f"{n} voorspellingen onder cohort pseudo_oos", ZELF_CONTROLEREN,
            "'bevindingen verwerkt' is jouw oordeel; geen bewijs, wel contract- en resolverbugs vinden")


def _dry_run_week_regel(nu: datetime):
    vandaag = nu.astimezone(timezone.utc).date()
    periode = f"{_dd_mm(DRY_RUN_WEEK_VAN)} t/m {_dd_mm(DRY_RUN_WEEK_TOT)}"
    if vandaag < DRY_RUN_WEEK_VAN:
        return ("Dry-run-week doorlopen (3b)", f"nog niet begonnen; gepland {periode}", NOG_NIET_AF,
                "volledige cyclus incl. forecast-ronde en resolver; jij controleert dagelijks de logs tegen de vaste lijst")
    return ("Dry-run-week doorlopen (3b)", f"gepland {periode}", ZELF_CONTROLEREN,
            "of de week doorlopen is staat nergens in de data; dat bevestig jij na de logcontrole")


def _reeksen_regel():
    from agents import (
        commodity_agent, currency_agent, economic_agent, equity_agent, financial_agent, monetary_policy_agent, sector_agent,
    )
    from contract.graph import unserved_owned_nodes

    modules = {
        "monetary_policy": monetary_policy_agent, "currency": currency_agent, "financial": financial_agent,
        "sector": sector_agent, "economic": economic_agent, "commodity": commodity_agent, "equity": equity_agent,
    }
    onbediend = {d: [n.value for n in unserved_owned_nodes(d, m.GRAPH_MAPPING)] for d, m in modules.items()}
    onbediend = {d: n for d, n in onbediend.items() if n}
    if not onbediend:
        waarde = "elke graafknoop wordt bediend"
    else:
        waarde = "onbediend: " + "; ".join(f"{d}: {', '.join(n)}" for d, n in sorted(onbediend.items()))
    return ("Reeksenlijst per agent definitief (1.10/2.x)", waarde, ZELF_CONTROLEREN,
            "of dit 'expliciet uitgesteld' is, beslis jij. economic (wage_growth, inflation_persistence) is bewust post-T₀ "
            "vastgelegd; equity valt buiten het cohort, dus equity_valuation heeft geen reeks")


def bepaal_voorwaarden(db_pad: str | None, nu: datetime | None = None):
    """Lijst van (naam, waarde, status, opmerking). Geen database: elke datagedreven regel is ZELF CONTROLEREN."""
    from runtime.daily import default_agents

    nu = nu or datetime.now(timezone.utc)
    verwacht = {s.domain: sum(len(t.horizons) for t in s.forecast_targets) for s in default_agents()}
    regels = []
    conn = _open(db_pad)
    if conn is None:
        regels.append(("Datagedreven voorwaarden", "onbekend (database niet gevonden)",
                       ZELF_CONTROLEREN, "draai dit op de VPS: daar staat de database"))
    else:
        try:
            regels += _t0a_regels(conn, nu)
            regels.append(_deep_dive_regel(conn))
            regels.append(_forecast_regel(conn, verwacht))
            regels.append(_resolver_regel(conn))
            regels.append(_pseudo_oos_regel(conn))
        except sqlite3.Error as e:
            regels.append(("Datagedreven voorwaarden", f"database niet leesbaar: {e}", ZELF_CONTROLEREN, ""))
        finally:
            conn.close()
    regels.append(_dry_run_week_regel(nu))
    regels.append(_reeksen_regel())
    # Niet uit de database af te leiden: er staat niets in dat dit bewijst. Bewust nooit AF.
    regels.append(("Offsite back-up één keer hersteld (1.11)", "niet af te leiden uit de data", ZELF_CONTROLEREN,
                   "de back-up loopt sinds 27-09; een herstel testen en afvinken is jouw handeling"))
    regels.append(("Heartbeat getest met de machine uit (1.11)", "niet af te leiden uit de data", ZELF_CONTROLEREN,
                   "alarmkanaal is getest (30-09); de strikte test met de machine uit volgt na T₀ᵃ"))
    regels.append(("API-quota gemeten incl. deep-dives (1.11)", "niet af te leiden uit de data", ZELF_CONTROLEREN,
                   "meten tegen het callvolume na de testrun; zie docs/data-sources.md"))
    return regels
