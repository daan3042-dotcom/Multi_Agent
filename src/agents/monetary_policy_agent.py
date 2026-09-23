"""
monetary_policy_agent.py
Stap B.1: eerste domain agent, samen met currency_agent.py (B.2) als "duo"
gestart vanwege hun sterke onderlinge koppeling (renteveranderingen werken
vaak direct door in wisselkoersen).

Monitoring mode haalt dezelfde kernreeksen op als analyst_agent.ai's
fred_data.py (FRED: Fed funds rate, 10Y yield, CPI-index, werkloosheid) --
zelfde databron, zelfde conventie (env-var FRED_API_KEY, {"error": "..."}
bij falen, ontbrekende reeksen worden overgeslagen i.p.v. gegokt), maar als
EIGEN, zelfstandige implementatie: dit is een nieuw systeem naast
analyst_agent.ai, geen import ervan (zie CLAUDE.md).

Tolerances in METRIC_SPECS zijn illustratieve plaatshouders -- zie
agents/base.py's docstring en docs/roadmap.md sectie H.

DEEP_DIVE_SYSTEM_PROMPT hieronder bevat ALLEEN vakinhoud -- de algemene
schrijfregels (neutraliteit, alleen aangeleverde cijfers, onzekerheid
expliciet) staan centraal in agents/base.py::SHARED_QUALITY_RULES en worden
door run_deep_dive() automatisch ervoor geplakt.

ONDERBOUWING MET DE TAYLOR RULE (zelfde patroon als financial_agent.py's
NFCI-interpretatie, zie analysis/-map se docstring): deep_dive() voegt,
als er een fed_funds_rate-claim aanwezig is, de Taylor Rule-impliciete
"passende" rente toe (analysis/taylor_rule.py) plus de afwijking t.o.v.
de daadwerkelijke Fed funds rate -- de LLM narrate dat verschil dan,
i.p.v. zelf in te schatten of het beleid krap/ruim is. De benodigde extra
data (CPI 12 maanden terug voor YoY-inflatie, reëel + potentieel bbp voor
de output gap) wordt in _fetch_taylor_rule_inputs() opgehaald, BEWUST NIET
via FRED_SERIES/fetch_snapshot(): bbp-data is kwartaalcijfers, een andere
ververssnelheid dan de rest van deze agent (maandelijks) -- zou de
gedeelde MAX_AGE-staleness-check in run_monitoring() verstoren (bbp zou
dan permanent "STALE" lijken). Blijft daarom een deep-dive-tijd-only
verrijking, niet iets dat de reguliere monitoring/delta-trigger raakt.
"""

from __future__ import annotations

import os
from datetime import timedelta

import requests

from agents.base import MetricSpec, run_deep_dive, run_monitoring
from analysis.taylor_rule import compute_output_gap_pct, compute_taylor_rule_rate
from contract.output_contract import Claim, Confidence, now_utc

DOMAIN = "monetary_policy"
SOURCE_NAME = "FRED"
BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
MAX_AGE = timedelta(days=35)  # de meeste FRED-reeksen hier zijn maandelijks

FRED_SERIES = {
    "fed_funds_rate": "FEDFUNDS",
    "10y_treasury_yield": "DGS10",
    "cpi_inflation_index": "CPIAUCSL",
    "unemployment_rate": "UNRATE",
}

# Extra reeksen, alleen voor de Taylor Rule (_fetch_taylor_rule_inputs) --
# BEWUST GEEN onderdeel van FRED_SERIES: kwartaalcijfers, andere
# ververssnelheid dan de rest van deze agent. Zie moduledocstring.
CPI_SERIES_ID = FRED_SERIES["cpi_inflation_index"]
REAL_GDP_SERIES_ID = "GDPC1"
POTENTIAL_GDP_SERIES_ID = "GDPPOT"
CPI_YOY_LAG_OBSERVATIONS = 12  # maandelijkse reeks: 12 observaties terug = ~1 jaar

METRIC_SPECS = {
    "fed_funds_rate": MetricSpec(label="Fed funds rate", tolerance=0.25, severity="high"),
    "10y_treasury_yield": MetricSpec(label="10-jaars Treasury yield", tolerance=0.25, severity="medium"),
    "cpi_inflation_index": MetricSpec(label="CPI-index", tolerance=2.0, severity="medium"),
    "unemployment_rate": MetricSpec(label="Werkloosheidspercentage", tolerance=0.3, severity="high"),
}

DEEP_DIVE_SYSTEM_PROMPT = """Je bent een macro-analist gespecialiseerd in Amerikaans \
monetair beleid: Fed funds rate, 10-jaars Treasury yield, CPI-index, werkloosheid. Duid \
wat de aangeleverde cijfers betekenen in hun macro-context (bijv. verkrappend/verruimend \
beleidssignaal, een mogelijk verband tussen de aangeleverde reeksen onderling) -- alleen \
als de cijfers dat zelf rechtvaardigen. Krijg je een Taylor Rule-impliciete rente en een \
afwijkingsclaim aangeleverd, gebruik die dan LETTERLIJK als je kwantitatieve anker voor of \
het beleid krap of ruim is t.o.v. wat dit gevestigde model impliceert -- schat dat niet \
zelf in, dat is al voor je berekend. (De algemene schrijfregels -- neutraliteit, alleen \
aangeleverde cijfers, onzekerheid expliciet -- staan al vóór dit stuk; dit is alleen de \
vakinhoudelijke aanvulling.)"""


def _fetch_series(series_id: str, api_key: str, lag_observations: int = 0) -> dict | None:
    """Zelfde aanpak als fred_data.py::_fetch_latest_value: None bij elke
    fout (netwerk, lege respons, '.'-placeholder-waarde van FRED zelf) --
    geen gok, gewoon niets voor deze reeks. lag_observations=0 (default)
    geeft de meest recente observatie; een hogere waarde gaat verder terug
    -- gebruikt door _fetch_taylor_rule_inputs() om CPI van 12 maanden
    terug op te halen (voor de YoY-inflatie die de Taylor Rule nodig
    heeft)."""
    try:
        resp = requests.get(
            BASE_URL,
            params={
                "series_id": series_id, "api_key": api_key, "file_type": "json",
                "sort_order": "desc", "limit": lag_observations + 1,
            },
            timeout=15,
        )
        resp.raise_for_status()
        observations = resp.json().get("observations", [])
    except Exception:
        return None
    if len(observations) <= lag_observations:
        return None
    obs = observations[lag_observations]
    if obs.get("value") in (None, "."):
        return None
    return {"value": obs["value"], "date": obs["date"]}


def fetch_snapshot() -> dict:
    """Haalt de meest recente waarde per FRED-reeks op. {"error": ...} alleen
    als GEEN ENKELE reeks lukte -- een gedeeltelijk mislukte pull is normaal
    (individuele reeksen kunnen tijdelijk leeg zijn) en geen bronstoring."""
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


def monitor(conn, now=None):
    """Eén monitoring-cyclus: zie agents.base.run_monitoring voor het
    volledige gedrag (data-health, claims opslaan, delta-triggers)."""
    return run_monitoring(conn, DOMAIN, SOURCE_NAME, fetch_snapshot, METRIC_SPECS, MAX_AGE, now=now)


def _fetch_taylor_rule_inputs() -> dict | None:
    """Haalt de extra data op die de Taylor Rule nodig heeft maar die niet
    in de reguliere monitoring-snapshot zit (zie moduledocstring voor
    waarom): CPI nu + 12 maanden terug (-> YoY-inflatie), en het laatste
    reële + potentiële bbp (-> output gap). Leest FRED_API_KEY zelf uit de
    environment, zelfde patroon als fetch_snapshot() -- hierdoor in tests
    rechtstreeks monkeypatchbaar zonder een API-key te hoeven simuleren.

    Geeft None terug als één onderdeel ontbreekt of de berekening faalt --
    geen gok, dan wordt de Taylor Rule simpelweg niet toegevoegd."""
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return None

    cpi_now = _fetch_series(CPI_SERIES_ID, api_key)
    cpi_year_ago = _fetch_series(CPI_SERIES_ID, api_key, lag_observations=CPI_YOY_LAG_OBSERVATIONS)
    real_gdp = _fetch_series(REAL_GDP_SERIES_ID, api_key)
    potential_gdp = _fetch_series(POTENTIAL_GDP_SERIES_ID, api_key)
    if not all([cpi_now, cpi_year_ago, real_gdp, potential_gdp]):
        return None

    try:
        cpi_now_value = float(cpi_now["value"])
        cpi_year_ago_value = float(cpi_year_ago["value"])
        inflation_yoy_pct = (cpi_now_value - cpi_year_ago_value) / cpi_year_ago_value * 100
        output_gap_pct = compute_output_gap_pct(float(real_gdp["value"]), float(potential_gdp["value"]))
    except (TypeError, ValueError, ZeroDivisionError):
        return None

    return {
        "inflation_yoy_pct": inflation_yoy_pct,
        "output_gap_pct": output_gap_pct,
        "cpi_date": cpi_now["date"],
        "gdp_date": real_gdp["date"],
    }


def deep_dive(conn, client, claims, trigger_events, now=None):
    """Deep-dive mode na een trigger. Voegt, als er een fed_funds_rate-
    claim tussen zit, de Taylor Rule-impliciete rente en de afwijking
    t.o.v. de daadwerkelijke rente toe als extra claims (zie
    moduledocstring en analysis/taylor_rule.py) -- puur Python, geen
    LLM-inschatting. Ontbreken de benodigde inputs (geen API-key, een
    netwerkfout), dan wordt de verrijking gewoon overgeslagen; de
    deep-dive gaat door zonder."""
    now = now or now_utc()
    enriched_claims = list(claims)
    fed_funds_claim = next((c for c in claims if c.metric_key == "fed_funds_rate"), None)
    if fed_funds_claim is not None and isinstance(fed_funds_claim.value, (int, float)):
        inputs = _fetch_taylor_rule_inputs()
        if inputs is not None:
            implied_rate = compute_taylor_rule_rate(inputs["inflation_yoy_pct"], inputs["output_gap_pct"])
            deviation = fed_funds_claim.value - implied_rate
            assumptions_note = (
                f"r*=2% (aanname, afgestemd met DD), π*=2% (Fed-doel), "
                f"YoY-inflatie={inputs['inflation_yoy_pct']:.2f}% (CPI {inputs['cpi_date']}), "
                f"output gap={inputs['output_gap_pct']:.2f}% (bbp {inputs['gdp_date']})"
            )
            enriched_claims.append(
                Claim(
                    domain=DOMAIN,
                    claim="Taylor Rule-impliciete Fed funds rate",
                    value=round(implied_rate, 2),
                    source="Berekend (Taylor Rule, 1993)",
                    confidence=Confidence.MEDIUM,
                    timestamp=now,
                    note=assumptions_note,
                )
            )
            enriched_claims.append(
                Claim(
                    domain=DOMAIN,
                    claim="Afwijking daadwerkelijke Fed funds rate t.o.v. Taylor Rule",
                    value=round(deviation, 2),
                    source="Berekend (Taylor Rule, 1993)",
                    confidence=Confidence.MEDIUM,
                    timestamp=now,
                )
            )
    return run_deep_dive(conn, client, DOMAIN, DEEP_DIVE_SYSTEM_PROMPT, enriched_claims, trigger_events, now=now)
