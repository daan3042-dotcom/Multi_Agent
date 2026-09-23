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
"""

from __future__ import annotations

import os
from datetime import timedelta

import requests

from agents.base import MetricSpec, run_deep_dive, run_monitoring

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

METRIC_SPECS = {
    "fed_funds_rate": MetricSpec(label="Fed funds rate", tolerance=0.25, severity="high"),
    "10y_treasury_yield": MetricSpec(label="10-jaars Treasury yield", tolerance=0.25, severity="medium"),
    "cpi_inflation_index": MetricSpec(label="CPI-index", tolerance=2.0, severity="medium"),
    "unemployment_rate": MetricSpec(label="Werkloosheidspercentage", tolerance=0.3, severity="high"),
}

DEEP_DIVE_SYSTEM_PROMPT = """Je bent een macro-analist die kort en neutraal duidt wat een \
verandering in Amerikaans monetair beleid (Fed funds rate, 10-jaars yield, CPI-index, \
werkloosheid) betekent. Puur feitelijk: geen koop/verkoop-advies, geen koersvoorspelling, \
geen stellige richting zonder expliciete onderbouwing uit de aangeleverde cijfers. \
Gebruik UITSLUITEND de aangeleverde cijfers -- bereken of verzin er zelf niets bij."""


def _fetch_series(series_id: str, api_key: str) -> dict | None:
    """Zelfde aanpak als fred_data.py::_fetch_latest_value: None bij elke
    fout (netwerk, lege respons, '.'-placeholder-waarde van FRED zelf) --
    geen gok, gewoon niets voor deze reeks."""
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


def deep_dive(conn, client, claims, trigger_events, now=None):
    """Deep-dive mode na een trigger. Zie agents.base.run_deep_dive."""
    return run_deep_dive(conn, client, DOMAIN, DEEP_DIVE_SYSTEM_PROMPT, claims, trigger_events, now=now)
