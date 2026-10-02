"""
runtime/freeze_status.py
Het freeze-overzicht (CLAUDE.md, checkpoint 5): alles wat DD bij de freeze vóór T₀ᵇ met versienummers moet
bevestigen, op één scherm. ALLEEN LEZEN.

DIT BEVRIEST NIETS. De freeze zelf is een handeling van DD: `FROZEN_TRIGGER_VERSION` zetten, de ridge bevriezen
(`fit_baselines.py --freeze`, onomkeerbaar) en daarna `MI_COHORT=cohort_0`. Dit overzicht toont alleen wat er nu
staat en wat nog open is. Het schrijft niets (de database gaat `mode=ro` open) en raakt de cron niet aan.

ELKE WAARDE WORDT BIJ HET AANROEPEN UIT DE CODE GELEZEN, nooit gekopieerd. Dat is het hele punt: een overzicht dat een
eigen kopie van "v3" bijhoudt kan uit de pas lopen met de werkelijkheid, en dan bevestig je bij de freeze iets dat
niet is wat er draait. De tests bewijzen dat een gewijzigde waarde hier zichtbaar wordt.

STATUSSEN
  BEVROREN          echt vastgezet (de trigger-pin staat op de huidige versie, de ridge-modellen staan in de database)
  TE BEVESTIGEN     staat in de code en wacht op DD's bevestiging bij de freeze
  OPEN BESLISSING   er is nog niets om te bevestigen: DD moet eerst iets beslissen of aanleveren
  WIJZIGING ZONDER VERSIE   de code wijkt af van de vingerafdruk van zijn versienummer (de tests vangen dit al;
                            hier staat het voor het geval iemand ze niet draaide)
  LET OP            iets staat in een stand die niet bij de rest past
  INFO              geen freeze-punt, wel goed om te zien

TWEEDE HELFT, "VOORWAARDEN VÓÓR DE KLOK": wat er VÓÓR de freeze gedaan moet zijn (T₀ᵃ, begeleide testrun, pseudo-OOS,
dry-run-week, ...). Zie `runtime/freeze_voorwaarden.py`.
  AF                uit de data af te leiden en voldaan. Alleen dit mag "klaar" heten.
  NOG NIET AF       uit de data af te leiden en niet voldaan.
  ZELF CONTROLEREN  de data toont dat iets gedaan is maar niet of het GOED is, of het is niet uit de data af te leiden.
                    Dat oordeel is van DD; het overzicht zegt hier nooit "klaar".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

BEVROREN = "BEVROREN"
TE_BEVESTIGEN = "TE BEVESTIGEN"
OPEN_BESLISSING = "OPEN BESLISSING"
ZONDER_VERSIE = "WIJZIGING ZONDER VERSIE"
LET_OP = "LET OP"
INFO = "INFO"
# Voorwaarden vóór de klok (runtime/freeze_voorwaarden.py): zie daar voor het verschil tussen de drie.
AF = "AF"
NOG_NIET_AF = "NOG NIET AF"
ZELF_CONTROLEREN = "ZELF CONTROLEREN"
TELLEN_MEE = (BEVROREN, TE_BEVESTIGEN, OPEN_BESLISSING, ZONDER_VERSIE, LET_OP, NOG_NIET_AF, ZELF_CONTROLEREN, AF)


@dataclass(frozen=True)
class Punt:
    groep: str
    naam: str
    waarde: str
    bron: str
    status: str
    opmerking: str = ""


def _versie_status(versie: str, register: dict[str, str], werkelijk: str) -> str:
    """TE BEVESTIGEN als de vingerafdruk bij het versienummer past, anders ZONDER_VERSIE."""
    return TE_BEVESTIGEN if register.get(versie) == werkelijk else ZONDER_VERSIE


def _db_tellingen(db_pad: str | None):
    """(ridge-modellen per spec-versie, voorspellingen per cohort) uit de database, of None als die er niet is.
    Alleen-lezen: `mode=ro`."""
    if not db_pad or not Path(db_pad).exists():
        return None
    conn = sqlite3.connect(f"file:{db_pad}?mode=ro", uri=True)
    try:
        ridge = dict(conn.execute(
            "SELECT spec_version, COUNT(*) FROM baseline_models WHERE model_name = 'ridge' GROUP BY spec_version"
        ).fetchall())
        cohorten = dict(conn.execute("SELECT cohort, COUNT(*) FROM predictions GROUP BY cohort").fetchall())
        return ridge, cohorten
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _splitsingen_beoordeling(db_pad: str | None, sw) -> str:
    """Leeg als de splitsingswaakhond niets te melden heeft (of de database er niet is), anders de samenvatting."""
    if not db_pad or not Path(db_pad).exists():
        return ""
    conn = sqlite3.connect(f"file:{db_pad}?mode=ro", uri=True)
    try:
        regels = sw.waarschuwingen(conn)
    except Exception as e:  # noqa: BLE001
        return f"splitsingscontrole mislukt: {type(e).__name__}"
    finally:
        conn.close()
    return f"{len(regels)} melding(en) van de splitsingswaakhond: " + " | ".join(regels)[:300] if regels else ""


def bepaal_punten(db_pad: str | None = None, environ=None, nu=None) -> list[Punt]:
    # Imports bij het aanroepen, zodat een test een module-waarde kan vervangen en het hier terugziet.
    from agents import (
        currency_agent, economic_agent, financial_agent, monetary_policy_agent, sector_agent,
    )
    from agents.base import DEFAULT_DEEP_DIVE_MODEL
    from contract import freeze_versions as fv
    from contract import graph as graph_mod
    from contract import prediction as pred
    from contract import resolution as res
    from contract import trigger_version as tv
    from runtime import freeze_guard as fg
    from runtime import llm_budget as lb
    from runtime import trigger_guard as tg
    from scoring import baselines as bl
    from scoring import resolver as rs
    from scoring import ridge as rg
    from scoring import scores as sc

    punten: list[Punt] = []
    voeg = lambda *a, **k: punten.append(Punt(*a, **k))  # noqa: E731

    # --- Contract en regels -------------------------------------------------
    G = "CONTRACT EN REGELS"
    voeg(G, "Predictiecontract", pred.CONTRACT_VERSION, "src/contract/prediction.py", TE_BEVESTIGEN,
         "vijf kwantielen sinds 01-10 (v0 had er drie)")
    voeg(G, "Kwantielniveaus", " ".join(f"{p:.2f}"[1:] for p in pred.QUANTILE_LEVELS), "src/contract/prediction.py",
         TE_BEVESTIGEN, "staartrisico (q05/q95) bewust niet vastgelegd; later toevoegen vraagt een nieuw cohort")
    voeg(G, "Causale graaf", f"{graph_mod.GRAPH_VERSION} ({len(graph_mod.NODE_OWNER)} knopen, {len(graph_mod.EDGES)} pijlen)",
         "src/contract/graph.py", OPEN_BESLISSING,
         "voorlopige v0 (niet door DD); DD en partner maken een eigen graaf, die vóór de freeze moet binnenkomen")
    doelen_fp = fg.doelen_fingerprint()
    voeg(G, "Doelenlijst en resolutieregels", f"{fv.TARGETS_VERSION}, {len(fg.doelen_beschrijving())} doelen, afdruk {doelen_fp}",
         "src/agents/*_agent.py", _versie_status(fv.TARGETS_VERSION, fv.TARGETS_FINGERPRINTS, doelen_fp),
         "wijziging na T₀ᵇ = nieuw cohort")
    from contract import corporate_actions as ca
    from runtime import split_waakhond as sw

    splits = ", ".join(sorted({f"{s.datum}" for s in ca.SPLITSINGEN}))
    waak = _splitsingen_beoordeling(db_pad, sw)
    voeg(G, "Aandelensplitsingen (correctie bij het lezen)", f"{len(ca.SPLITSINGEN)} geregistreerd ({splits})",
         "src/contract/corporate_actions.py", LET_OP if waak else TE_BEVESTIGEN,
         waak or "reeksen van vóór een splitsing worden omgerekend naar de huidige aandelen; de ruwe claims blijven ongewijzigd")
    voeg(G, "Resolver-wachttijd", f"{rs.MAX_WACHTTIJD.days} dagen", "src/scoring/resolver.py", TE_BEVESTIGEN,
         "bepaalt mede welke voorspellingen in het cohort belanden; 'te bevestigen bij de freeze' (roadmap 4.5)")
    voeg(G, "Scorer", sc.SCORER_VERSION, "src/scoring/scores.py", TE_BEVESTIGEN, "pinball + CRPS (gelijk gewogen), Brier, log loss")
    kal = sorted(res.FOMC_MEETING_DATES)
    voeg(G, "FOMC-kalender", f"{len(kal)} besluitdagen, {kal[0]} t/m {kal[-1]}" if kal else "leeg", "src/contract/resolution.py",
         TE_BEVESTIGEN, "juli en september 2026 toegevoegd voor de pseudo-OOS-run (bron: Fed-persberichten, DD 02-10); vergaderingen van januari tot en met juni 2026 ontbreken (niet nodig voor het venster)")

    # --- Drempels -----------------------------------------------------------
    G = "DREMPELS"
    trig_fp = tg.trigger_fingerprint()
    voeg(G, "Trigger-regels", f"{tv.TRIGGER_VERSION}, afdruk {trig_fp}", "src/contract/trigger_version.py",
         _versie_status(tv.TRIGGER_VERSION, tv.TRIGGER_FINGERPRINTS, trig_fp), "")
    if tv.FROZEN_TRIGGER_VERSION is None:
        voeg(G, "Trigger-pin (FROZEN_TRIGGER_VERSION)", "niet gezet", "src/contract/trigger_version.py", TE_BEVESTIGEN,
             "dit is de eigenlijke freeze van de drempels; zonder pin weigert run_daily.py cohort_0")
    elif tv.FROZEN_TRIGGER_VERSION == tv.TRIGGER_VERSION:
        voeg(G, "Trigger-pin (FROZEN_TRIGGER_VERSION)", tv.FROZEN_TRIGGER_VERSION, "src/contract/trigger_version.py", BEVROREN, "")
    else:
        voeg(G, "Trigger-pin (FROZEN_TRIGGER_VERSION)", f"{tv.FROZEN_TRIGGER_VERSION}, maar de code is {tv.TRIGGER_VERSION}",
             "src/contract/trigger_version.py", LET_OP, "de pin wijkt af van de huidige regelset: cohort_0 weigert te starten")

    # --- LLM ----------------------------------------------------------------
    G = "LLM"
    ev_fp = fg.evidence_fingerprint()
    voeg(G, "Model (model_id)", DEFAULT_DEEP_DIVE_MODEL, "src/agents/base.py", TE_BEVESTIGEN,
         "kennisgrens juni 2026 en uittreding niet eerder dan 28-09-2027 (Anthropic-modeloverzicht, 01-10-2026)")
    voeg(G, "Denkinstelling", f"{lb.DENKEN_UIT['type']} voor {', '.join(sorted(lb.MODELLEN_ZONDER_STANDAARD_DENKEN))}",
         "src/runtime/llm_budget.py", TE_BEVESTIGEN, "denken AAN voor de forecast-ronde is een experiment na de testrun; staat NIET in model_id")
    for naam, mod in (
        ("monetary_policy", monetary_policy_agent), ("currency", currency_agent), ("financial", financial_agent),
        ("sector", sector_agent), ("economic", economic_agent),
    ):
        voeg(G, f"Prompt {naam}", f"{mod.FORECAST_PROMPT_VERSION}, afdruk {fg.forecast_prompt_hash(mod, ev_fp)}",
             f"src/agents/{naam}_agent.py", TE_BEVESTIGEN, "afdruk = regels + vakparagraaf + evidence-sheet")
    voeg(G, "Evidence-sheet", f"{fv.EVIDENCE_SHEET_VERSION}, afdruk {ev_fp}", "src/scoring/evidence_sheet.py",
         _versie_status(fv.EVIDENCE_SHEET_VERSION, fv.EVIDENCE_SHEET_FINGERPRINTS, ev_fp),
         "de context bij de forecast-ronde; een wijziging verandert ook de prompt-afdrukken hierboven")
    voeg(G, "Richtlijnen van DD voor de agents", "nog niet geschreven", "(nog niet in het project)", OPEN_BESLISSING,
         "eerst een echte prompt zien in de begeleide testrun")
    voeg(G, "Vangrails (geen onderdeel van het cohort)", f"maandrem ${lb.max_maandbedrag(environ):.0f}, verzoekgrens {lb.MAX_VERZOEK_TEKENS:,} tekens".replace(",", "."),
         "src/runtime/llm_budget.py", INFO, "")

    # --- Baselines ----------------------------------------------------------
    G = "BASELINES"
    voeg(G, "Persistence en climatology", f"{bl.BASELINE_VERSION}, minimaal {bl.MIN_SAMPLES} vensters (seizoen {bl.MIN_SEASONAL_SAMPLES})",
         "src/scoring/baselines.py", TE_BEVESTIGEN, "'te bevestigen bij de freeze' (roadmap 4.6)")
    totaal = fg.aantal_kwantielreeksen_voor_ridge()
    db = _db_tellingen(db_pad)
    if db is None:
        voeg(G, "Ridge-baseline", f"{rg.RIDGE_SPEC_VERSION}, bevroren: onbekend (database niet gevonden)", "database", TE_BEVESTIGEN, "")
    else:
        bevroren = db[0].get(rg.RIDGE_SPEC_VERSION, 0)
        status = BEVROREN if bevroren >= totaal else TE_BEVESTIGEN
        voeg(G, "Ridge-baseline", f"{rg.RIDGE_SPEC_VERSION}, {bevroren} van {totaal} bevroren", "database (baseline_models)", status,
             "bevriezen is onomkeerbaar (`fit_baselines.py --freeze`)" if bevroren < totaal else "")

    # --- Stand van zaken ----------------------------------------------------
    G = "STAND VAN ZAKEN"
    cohort = pred.current_cohort(environ)
    if cohort == pred.COHORT_0:
        niet_bevroren = tv.FROZEN_TRIGGER_VERSION != tv.TRIGGER_VERSION
        voeg(G, "Cohort voor nieuwe voorspellingen", cohort, ".env (MI_COHORT)", LET_OP if niet_bevroren else BEVROREN,
             "echt cohort actief terwijl de trigger-pin ontbreekt" if niet_bevroren else "")
    else:
        voeg(G, "Cohort voor nieuwe voorspellingen", f"{cohort} (telt niet mee)", ".env (MI_COHORT)", TE_BEVESTIGEN,
             "wordt cohort_0 NA de freeze, en dan controleren dat de eerste run 'ECHT COHORT' zegt")
    voeg(G, "Prior voor de skill-posterior", "niet vastgelegd", "(nog niet in het project)", OPEN_BESLISSING,
         "bepaalt of een agent na zes maanden wordt verwijderd; moet vooraf worden vastgelegd (roadmap 4.5)")
    if db is not None:
        voeg(G, "Voorspellingen per cohort", ", ".join(f"{c}: {n}" for c, n in sorted(db[1].items())) or "geen", "database", INFO, "")

    # --- Voorwaarden vóór de klok -------------------------------------------
    from runtime.freeze_voorwaarden import GROEP, bepaal_voorwaarden

    for naam, waarde, status, opmerking in bepaal_voorwaarden(db_pad, nu):
        voeg(GROEP, naam, waarde, "database/docs", status, opmerking)
    return punten


def samenvatting(punten: list[Punt]) -> dict[str, int]:
    tel = {s: 0 for s in TELLEN_MEE}
    for p in punten:
        if p.status in tel:
            tel[p.status] += 1
    return tel


def format_overzicht(punten: list[Punt]) -> str:
    uit = [
        "FREEZE-OVERZICHT (alleen lezen; dit bevriest niets)",
        "Waarden komen rechtstreeks uit de code en de database. De freeze zelf is een handeling van DD.",
        "",
    ]
    huidige = None
    for p in punten:
        if p.groep != huidige:
            if huidige is not None:
                uit.append("")
            huidige = p.groep
            uit.append(huidige)
        uit.append(f"  {p.naam:<42} {p.waarde}")
        uit.append(f"  {'':<42} [{p.status}]" + (f"  {p.opmerking}" if p.opmerking else ""))
    if any(p.groep == "VOORWAARDEN VÓÓR DE KLOK" for p in punten):
        uit.append("")
        uit.append("  AF = uit de data af te leiden en voldaan (alleen dit mag 'klaar' heten).")
        uit.append("  NOG NIET AF = uit de data af te leiden en niet voldaan.")
        uit.append("  ZELF CONTROLEREN = de data toont dat het gedaan is, niet of het GOED is (of het is niet af te leiden): jouw oordeel.")
    tel = samenvatting(punten)
    uit.append("")
    uit.append(
        "SAMENVATTING: " + ", ".join(f"{n} {s.lower()}" for s, n in tel.items() if n)
        + (f"  ({len(punten)} punten)" if punten else "")
    )
    if tel[ZONDER_VERSIE]:
        uit.append("LET OP: een vingerafdruk wijkt af van zijn versienummer. Draai de tests en verhoog het versienummer.")
    return "\n".join(uit) + "\n"
