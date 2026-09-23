"""
financial_agent.py
Stap C.2: financiële-marktcondities -- marktstress/liquiditeit, te
onderscheiden van de equity agent (C.1, per-ticker bedrijfsfundamentals) en
van monetary_policy_agent.py (B.1, Fed-beleid zelf). Zelfde opzet als B.1/
B.2: één instantie (geen per-ticker namespacing nodig, in tegenstelling tot
equity_agent.py), eigen FRED-implementatie (zelfde conventie als
analyst_agent.ai's fred_data.py, hier zelfstandig -- geen import, zie
CLAUDE.md), hangt aan agents/base.py's gedeelde scaffolding.

Vier kernreeksen, alle van FRED:
- NFCI (Chicago Fed National Financial Conditions Index) -- de directe,
  samengestelde maatstaf voor "hoe krap/ruim zijn financiële condities".
- BAMLH0A0HYM2 (ICE BofA US High Yield Index Option-Adjusted Spread) --
  kredietrisico-opslag; een snelle stijging is een klassiek stress-signaal.
- VIXCLS (CBOE Volatility Index) -- impliciete volatiliteit, de
  "angstindex".
- T10Y2Y (10-jaars minus 2-jaars Treasury-rente) -- yield-curve-vorm,
  relevant voor recessierisico-inschatting.

MAX_AGE is afgestemd op de TRAAGSTE reeks (NFCI, wekelijks) -- de overige
drie zijn dagelijks en zullen dus vaker vers zijn dan het minimum vereist;
zelfde redenering als monetary_policy_agent.py's MAX_AGE op zijn traagste
(maandelijkse) reeks.

METRIC_SPECS-tolerances zijn illustratieve plaatshouders -- zie
agents/base.py's docstring en docs/roadmap.md sectie H.

DEEP_DIVE_SYSTEM_PROMPT bevat ALLEEN vakinhoud -- de algemene schrijfregels
staan centraal in agents/base.py::SHARED_QUALITY_RULES en worden door
run_deep_dive() automatisch ervoor geplakt.
"""

from __future__ import annotations

import os
from datetime import timedelta

import requests

from agents.base import MetricSpec, run_deep_dive, run_monitoring

DOMAIN = "financial"
SOURCE_NAME = "FRED"
BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
MAX_AGE = timedelta(days=10)  # NFCI is wekelijks; de andere drie zijn dagelijks

FRED_SERIES = {
    "financial_conditions_index": "NFCI",
    "high_yield_credit_spread": "BAMLH0A0HYM2",
    "vix": "VIXCLS",
    "yield_curve_10y_2y": "T10Y2Y",
}

METRIC_SPECS = {
    "financial_conditions_index": MetricSpec(label="Financial Conditions Index (NFCI)", tolerance=0.1, severity="high"),
    "high_yield_credit_spread": MetricSpec(label="High-yield credit spread", tolerance=0.5, severity="high"),
    "vix": MetricSpec(label="VIX", tolerance=5.0, severity="medium"),
    "yield_curve_10y_2y": MetricSpec(label="10Y-2Y yield curve", tolerance=0.15, severity="medium"),
}

DEEP_DIVE_SYSTEM_PROMPT = """Je bent een analist gespecialiseerd in financiële-
marktcondities: de Chicago Fed National Financial Conditions Index (NFCI), \
high-yield credit spreads, VIX, en de 10-jaars-min-2-jaars yield curve. Duid wat de \
aangeleverde cijfers betekenen voor marktstress/liquiditeit (bijv. verkrappende/ \
verruimende financiële condities, toegenomen kredietrisico-opslag, een veranderende \
curve-vorm) -- alleen als de cijfers dat zelf rechtvaardigen. (De algemene schrijfregels \
-- neutraliteit, alleen aangeleverde cijfers, onzekerheid expliciet -- staan al vóór dit \
stuk; dit is alleen de vakinhoudelijke aanvulling.)"""


def _fetch_series(series_id: str, api_key: str) -> dict | None:
    """Zelfde aanpak als monetary_policy_agent.py::_fetch_series /
    fred_data.py::_fetch_latest_value: None bij elke fout -- geen gok,
    gewoon niets voor deze reeks."""
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


def monitor(conn, now=None):
    """Eén monitoring-cyclus: zie agents.base.run_monitoring voor het
    volledige gedrag (data-health, claims opslaan, delta-triggers)."""
    return run_monitoring(conn, DOMAIN, SOURCE_NAME, fetch_snapshot, METRIC_SPECS, MAX_AGE, now=now)


def deep_dive(conn, client, claims, trigger_events, now=None):
    """Deep-dive mode na een trigger. Zie agents.base.run_deep_dive."""
    return run_deep_dive(conn, client, DOMAIN, DEEP_DIVE_SYSTEM_PROMPT, claims, trigger_events, now=now)
