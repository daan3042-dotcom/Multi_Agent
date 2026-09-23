"""
currency_agent.py
Stap B.2, gestart als duo met monetary_policy_agent.py (B.1) vanwege hun
sterke onderlinge koppeling. Zelfde tweeledige opzet en dezelfde databron-
conventie als analyst_agent.ai's commodity_data.py::fetch_fx_rate (Alpha
Vantage CURRENCY_EXCHANGE_RATE) -- hier als eigen, zelfstandige
implementatie, geen import van analyst_agent.ai (zie CLAUDE.md).

Drie majeure paren als startset (bewust klein, zelfde stijl als
fred_data.py's SERIES-selectie) -- generaliseren naar meer instrumenten
(incl. DXY, dat niet als los CURRENCY_EXCHANGE_RATE-paar beschikbaar is) is
sectie E/I, niet hier.

Tolerances in METRIC_SPECS zijn illustratieve plaatshouders -- zie
agents/base.py's docstring en docs/roadmap.md sectie H.

DEEP_DIVE_SYSTEM_PROMPT hieronder bevat ALLEEN vakinhoud -- de algemene
schrijfregels (neutraliteit, alleen aangeleverde cijfers, onzekerheid
expliciet) staan centraal in agents/base.py::SHARED_QUALITY_RULES en worden
door run_deep_dive() automatisch ervoor geplakt.
"""

from __future__ import annotations

import os
from datetime import timedelta

import requests

from agents.base import MetricSpec, run_deep_dive, run_monitoring

DOMAIN = "currency"
SOURCE_NAME = "ALPHA_VANTAGE_FX"
BASE_URL = "https://www.alphavantage.co/query"
MAX_AGE = timedelta(hours=6)  # wisselkoersen bewegen continu, hebben vaker verse pulls nodig dan macro-reeksen

FX_PAIRS = {
    "eur_usd": ("EUR", "USD"),
    "usd_jpy": ("USD", "JPY"),
    "gbp_usd": ("GBP", "USD"),
}

METRIC_SPECS = {
    "eur_usd": MetricSpec(label="EUR/USD", tolerance=0.01, severity="medium"),
    "usd_jpy": MetricSpec(label="USD/JPY", tolerance=1.0, severity="medium"),
    "gbp_usd": MetricSpec(label="GBP/USD", tolerance=0.01, severity="medium"),
}

DEEP_DIVE_SYSTEM_PROMPT = """Je bent een valuta-analist gespecialiseerd in majeure \
wisselkoersen: EUR/USD, USD/JPY, GBP/USD. Duid wat de aangeleverde beweging betekent, en \
benoem een mogelijk verband met monetair beleid ALLEEN als de aangeleverde cijfers daar \
zelf aanleiding toe geven -- verzin geen causaliteit die er niet expliciet uit blijkt. \
(De algemene schrijfregels -- neutraliteit, alleen aangeleverde cijfers, onzekerheid \
expliciet -- staan al vóór dit stuk; dit is alleen de vakinhoudelijke aanvulling.)"""


def _fetch_pair(from_currency: str, to_currency: str, api_key: str) -> dict | None:
    """Zelfde aanpak als commodity_data.py::fetch_fx_rate, maar geeft None
    terug bij falen i.p.v. een {"error": ...}-dict -- deze functie levert
    aan fetch_snapshot(), die zelf bepaalt of GEEN ENKEL paar lukte."""
    try:
        resp = requests.get(
            BASE_URL,
            params={
                "function": "CURRENCY_EXCHANGE_RATE",
                "from_currency": from_currency,
                "to_currency": to_currency,
                "apikey": api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        rate_data = resp.json().get("Realtime Currency Exchange Rate")
    except Exception:
        return None
    if not rate_data or "5. Exchange Rate" not in rate_data:
        return None
    return {"value": rate_data["5. Exchange Rate"], "date": rate_data.get("6. Last Refreshed", "")}


def fetch_snapshot() -> dict:
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        return {"error": "ALPHAVANTAGE_API_KEY niet gevonden in environment"}
    snapshot = {}
    for metric_key, (from_currency, to_currency) in FX_PAIRS.items():
        result = _fetch_pair(from_currency, to_currency, api_key)
        if result:
            snapshot[metric_key] = result
    if not snapshot:
        return {"error": "geen enkel valutapaar kon worden opgehaald"}
    return snapshot


def monitor(conn, now=None):
    return run_monitoring(conn, DOMAIN, SOURCE_NAME, fetch_snapshot, METRIC_SPECS, MAX_AGE, now=now)


def deep_dive(conn, client, claims, trigger_events, now=None):
    return run_deep_dive(conn, client, DOMAIN, DEEP_DIVE_SYSTEM_PROMPT, claims, trigger_events, now=now)
