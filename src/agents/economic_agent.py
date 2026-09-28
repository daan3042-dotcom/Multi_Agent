"""
economic_agent.py
Sectie 2.7: de economic agent, LEAN -- de ENE uitzondering op "geen nieuwe
agents pre-T0" (zie CLAUDE.md, "Wat NIET te doen zonder te vragen"; besloten
27-09-2026, zie docs/roadmap.md "Wat er op 27-09-2026 veranderd is", punt 6
van de tabel/fase 0). Zonder groei-knopen heeft de causale graaf (1.10) en
de forward test (cohort 0) niets dat groei/arbeidsmarkt bedient -- dit is
BEWUST smal gehouden tot precies dat: geen output gap, geen ISM, geen
Phillips curve (die komen pas post-T0, zie roadmap fase 4, "Causale graaf
v1 verplicht... economic agent uitbreiden").

Drie kernreeksen, alle van FRED, zelfde opzet als financial_agent.py/
monetary_policy_agent.py (eigen, zelfstandige FRED-implementatie, geen
import van analyst_agent.ai, zie CLAUDE.md):
- ICSA (Initial Claims, wekelijks, NIET seizoensgecorrigeerd) -- de
  snelst-resolvende macroreeks die er is (wekelijks vs. maandelijks voor de
  andere twee), en daarmee de rijkste testbron van de drie voor de forward
  test op korte horizon.
- UNRATE (Civilian Unemployment Rate, maandelijks) -- LET OP: dezelfde
  reeks als monetary_policy_agent.py::FRED_SERIES["unemployment_rate"],
  bewust ook hier (roadmap 0b-2 se DoD noemt UNRATE expliciet) omdat de
  Sahm Rule 'm nodig heeft en de twee agents 'm voor verschillende doelen
  gebruiken (beleidscontext daar, arbeidsmarkt/groei-context hier). Eigen,
  domein-gescopete SOURCE_KEY (zie hieronder) voorkomt dat dit de
  Source-Registry-bug van vóór 1.4 herintroduceert.
- PAYEMS (All Employees, Total Nonfarm, maandelijks) -- de tweede
  klassieke arbeidsmarkt-groeimaatstaf naast UNRATE.

MAX_AGE is afgestemd op de TRAAGSTE reeks (UNRATE/PAYEMS, maandelijks,
zelfde buffer als monetary_policy_agent.py's 35 dagen) -- ICSA is
wekelijks en zal dus altijd ruim binnen die marge vers zijn.

ONDERBOUWING MET DE SAHM RULE (zelfde patroon als financial_agent.py's
NFCI-interpretatie en monetary_policy_agent.py's Taylor Rule, zie
analysis/-map se docstring): deep_dive() voegt, als er een
unemployment_rate-claim aanwezig is, de Sahm Rule-waarde en de officiële
classificatie (recessie-signaal actief/niet actief) toe als extra claims
(analysis/sahm_rule.py) -- de LLM narrate dat resultaat dan LETTERLIJK,
i.p.v. zelf in te schatten of de arbeidsmarkt aan het verzwakken is. De
Sahm Rule heeft 14 maanden UNRATE-historie nodig (zie
analysis/sahm_rule.py::MINIMUM_OBSERVATIONS) -- BEWUST NIET via de
reguliere fetch_snapshot() (die haalt per reeks maar de MEEST RECENTE
waarde), maar een losse _fetch_unrate_history() met precies ÉÉN extra
FRED-call (limit=14 in plaats van 14 losse calls), zelfde
kostenbewustzijn als commodity_agent.py's aanpak (historie komt uit
dezelfde soort respons, geen call-per-observatie).

Checkpoint 1 uit CLAUDE.md ("Na elke nieuwe domain/functionele agent, vóór
hij aan de trigger-engine of manager wordt gekoppeld") is DOORLOPEN op
28-09-2026: DD heeft deze sectie + docs/agents.md se "Economic agent"-
sectie gereviewd en akkoord gegeven (drie punten expliciet afgetikt: het
dubbel volgen van UNRATE is bewust, de illustratieve drempels wachten op
2.7's finetuning, en het past bij het patroon van de andere zes agents).
Sindsdien staat dit bestand in runtime/daily.py::default_agents() en
draait 'ie mee in de dagelijkse cyclus. Zie docs/agents.md voor wat deze
agent monitort, welke triggers hij kan geven, en hoe zijn output op het
A.1-contract aansluit.
"""

from __future__ import annotations

import os
from datetime import timedelta

import requests

from agents.base import MetricSpec, run_deep_dive, run_monitoring
from analysis.sahm_rule import MINIMUM_OBSERVATIONS, classify_sahm_rule, compute_sahm_rule
from contract.output_contract import Claim, Confidence, now_utc
from storage.schema import register_source

DOMAIN = "economic"
PROVIDER = "FRED"
# Roadmap 1.4 (Source Registry): EIGEN, per-agent-gescopete source_key --
# zelfde reden als monetary_policy_agent.py/financial_agent.py se
# SOURCE_KEY-toelichting. Zonder deze scoping zou deze agent's UNRATE-poll
# de data_health-rij van monetary_policy_agent.py's UNRATE-poll delen (of
# omgekeerd overschrijven), en zouden de twee agents elkaars staleness
# kunnen verbergen -- exact de bug die 1.4 al eens opgelost heeft.
SOURCE_KEY = f"{PROVIDER}:{DOMAIN}"
BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
MAX_AGE = timedelta(days=35)  # UNRATE/PAYEMS zijn maandelijks; ICSA (wekelijks) is dan altijd ruim vers

FRED_SERIES = {
    "initial_claims": "ICSA",
    "unemployment_rate": "UNRATE",
    "nonfarm_payrolls": "PAYEMS",
}

METRIC_SPECS = {
    # Tolerances zijn illustratieve plaatshouders, zie agents/base.py se
    # docstring en docs/roadmap.md sectie H -- "unemployment_rate" gebruikt
    # BEWUST dezelfde 0.3 als monetary_policy_agent.py's METRIC_SPECS (zelfde
    # onderliggende reeks, geen reden voor een andere drempel per domein).
    "initial_claims": MetricSpec(label="Initial Claims (ICSA)", tolerance=20_000.0, severity="medium"),
    "unemployment_rate": MetricSpec(label="Werkloosheidspercentage (UNRATE)", tolerance=0.3, severity="high"),
    "nonfarm_payrolls": MetricSpec(label="Nonfarm Payrolls (PAYEMS)", tolerance=150.0, severity="high"),
}

DEEP_DIVE_SYSTEM_PROMPT = """Je bent een macro-analist gespecialiseerd in Amerikaanse groei- \
en arbeidsmarktdata: wekelijkse WW-aanvragen (Initial Claims), het werkloosheidspercentage, en \
de nonfarm payrolls-groei. Duid wat de aangeleverde cijfers betekenen voor de arbeidsmarkt/ \
groei -- alleen als de cijfers dat zelf rechtvaardigen. Krijg je een claim met een Sahm \
Rule-waarde en -classificatie aangeleverd, gebruik die dan LETTERLIJK als je kwantitatieve \
anker voor of er een recessie-signaal actief is -- schat dat niet zelf in, dat is al voor je \
berekend volgens de officiële, gepubliceerde drempel (Sahm, 2019). (De algemene schrijfregels \
-- neutraliteit, alleen aangeleverde cijfers, onzekerheid expliciet -- staan al vóór dit stuk; \
dit is alleen de vakinhoudelijke aanvulling.)"""


def _fetch_series(series_id: str, api_key: str) -> dict | None:
    """Zelfde aanpak als financial_agent.py/monetary_policy_agent.py::
    _fetch_series: None bij elke fout -- geen gok, gewoon niets voor deze
    reeks."""
    try:
        resp = requests.get(
            BASE_URL,
            params={"series_id": series_id, "api_key": api_key, "file_type": "json", "sort_order": "desc", "limit": 1},
            timeout=15,
        )
        resp.raise_for_status()
        observations = resp.json().get("observations", [])
    except Exception:
        return None
    if not observations or observations[0].get("value") in (None, "."):
        return None
    return {"value": observations[0]["value"], "date": observations[0]["date"]}


def fetch_snapshot() -> dict:
    """Haalt de meest recente waarde per FRED-reeks op. {"error": ...} alleen
    als GEEN ENKELE reeks lukte."""
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return {"error": "FRED_API_KEY niet gevonden in environment"}
    snapshot = {}
    for metric_key, series_id in FRED_SERIES.items():
        result = _fetch_series(series_id, api_key)
        if result:
            snapshot[metric_key] = result
    if not snapshot:
        return {"error": "geen enkele FRED-reeks kon worden opgehaald"}
    return snapshot


def monitor(conn, now=None, event_id=None):
    """Eén monitoring-cyclus: zie agents.base.run_monitoring voor het
    volledige gedrag (data-health, claims opslaan, delta-triggers).
    register_source() is een idempotente upsert (roadmap 1.4) -- veilig
    om op elke cyclus te herhalen, declareert alleen de actuele config."""
    register_source(
        conn, SOURCE_KEY, provider=PROVIDER, domain=DOMAIN, max_age=MAX_AGE,
        frequency="maandelijks (UNRATE/PAYEMS, de traagste twee van de drie)",
        latency="~1s per call (REST)", cost="gratis (FRED API)",
    )
    return run_monitoring(conn, DOMAIN, SOURCE_KEY, fetch_snapshot, METRIC_SPECS, MAX_AGE, now=now, event_id=event_id)


def _fetch_unrate_history(api_key: str, count: int = MINIMUM_OBSERVATIONS) -> list[float] | None:
    """Haalt de `count` meest recente maandelijkse UNRATE-observaties op in
    ÉÉN call (sort_order=asc, dus al oudste-eerst -- precies de volgorde die
    analysis.sahm_rule.compute_sahm_rule() verwacht), i.p.v. `count` losse
    calls. None als de call mislukt of er te weinig observaties zijn voor
    de Sahm Rule -- geen gok, dan wordt de verrijking gewoon overgeslagen."""
    try:
        resp = requests.get(
            BASE_URL,
            params={
                "series_id": FRED_SERIES["unemployment_rate"], "api_key": api_key,
                "file_type": "json", "sort_order": "asc", "limit": count,
            },
            timeout=15,
        )
        resp.raise_for_status()
        observations = resp.json().get("observations", [])
    except Exception:
        return None
    try:
        values = [float(o["value"]) for o in observations if o.get("value") not in (None, ".")]
    except (TypeError, ValueError):
        return None
    if len(values) < MINIMUM_OBSERVATIONS:
        return None
    return values


def deep_dive(conn, client, claims, trigger_events, now=None, event_id=None):
    """Deep-dive mode na een trigger. Voegt, als er een unemployment_rate-
    claim tussen zit, de Sahm Rule-waarde en -classificatie toe als extra
    claims (zie moduledocstring en analysis/sahm_rule.py) -- puur Python,
    geen LLM-inschatting. Ontbreken de benodigde inputs (geen API-key, een
    netwerkfout, te weinig historie), dan wordt de verrijking gewoon
    overgeslagen; de deep-dive gaat door zonder."""
    now = now or now_utc()
    enriched_claims = list(claims)
    unemployment_claim = next((c for c in claims if c.metric_key == "unemployment_rate"), None)
    api_key = os.environ.get("FRED_API_KEY")

    if unemployment_claim is not None and api_key:
        history = _fetch_unrate_history(api_key)
        if history is not None:
            try:
                sahm_value = compute_sahm_rule(history)
            except ValueError:
                sahm_value = None
            if sahm_value is not None:
                enriched_claims.append(
                    Claim(
                        domain=DOMAIN,
                        claim="Sahm Rule-waarde",
                        value=round(sahm_value, 2),
                        source="Berekend (Sahm Rule, Sahm 2019)",
                        confidence=Confidence.HIGH,
                        analysis_time=now,
                        source_time=now,
                        note="3-maands-gemiddelde UNRATE nu minus het laagste 3-maands-gemiddelde over de afgelopen 12 maanden",
                    )
                )
                enriched_claims.append(
                    Claim(
                        domain=DOMAIN,
                        claim="Sahm Rule-classificatie",
                        value=classify_sahm_rule(sahm_value),
                        source="Sahm Rule-methodologie (Sahm, 2019)",
                        confidence=Confidence.VERY_HIGH,
                        analysis_time=now,
                        source_time=now,
                        note="drempel 0,50 procentpunt, officieel gepubliceerd, geen zelfbedachte tussenband",
                    )
                )

    return run_deep_dive(conn, client, DOMAIN, DEEP_DIVE_SYSTEM_PROMPT, enriched_claims, trigger_events, now=now, event_id=event_id)
