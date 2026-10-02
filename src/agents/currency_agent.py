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

from agents.base import ForecastTarget, MetricSpec, run_deep_dive, run_monitoring
from contract.horizons import ReleaseCadence
from contract.prediction import HorizonKind, PredictionKind
from contract.resolution import ResolutionMethod
from contract.graph import Node
from sources import alpha_vantage as av
from storage.schema import register_source

DOMAIN = "currency"
PROVIDER = "ALPHA_VANTAGE_FX"
SOURCE_KEY = f"{PROVIDER}:{DOMAIN}"  # roadmap 1.4 (Source Registry); zie monetary_policy_agent.py::SOURCE_KEY voor de volledige toelichting
MAX_AGE = timedelta(hours=6)  # wisselkoersen bewegen continu, hebben vaker verse pulls nodig dan macro-reeksen

FX_PAIRS = {
    "eur_usd": ("EUR", "USD"),
    "usd_jpy": ("USD", "JPY"),
    "gbp_usd": ("GBP", "USD"),
}


GRAPH_MAPPING: dict[str, Node | None] = {
    "eur_usd": Node.DOLLAR,
    "usd_jpy": Node.DOLLAR,
    "gbp_usd": Node.DOLLAR,
}
"""Alle drie de paren schatten dezelfde toestand: de brede dollarsterkte.
Ze zijn drie waarnemingen van een knoop, geen drie knopen -- precies het
onderscheid observatie/toestand uit docs/causal-graph.md.

BEKENDE ZWAKTE: een brede dollarindex (DTWEXBGS) ontbreekt, dus deze knoop
wordt geschat uit drie losse paren waarin de euro zwaar doorweegt. Het
dichten daarvan is uitgesteld tot na T0-a (besloten 28-09-2026), omdat het
een tweede databron in deze agent zou vragen -- zie docs/project-state.md.
"""

METRIC_SPECS = {
    "eur_usd": MetricSpec(label="EUR/USD", tolerance=0.016, severity="medium"),
    "usd_jpy": MetricSpec(label="USD/JPY", tolerance=3.0, severity="medium"),
    "gbp_usd": MetricSpec(label="GBP/USD", tolerance=0.016, severity="medium"),
}

FORECAST_TARGETS = tuple(
    ForecastTarget(
        metric_key=key,
        kind=PredictionKind.QUANTILE,
        horizon_kind=HorizonKind.TRADING_DAYS,
        horizons=(5, 21, 63),
        graph_node=Node.DOLLAR,
        resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER,
        resolution_rule=(
            label + " zoals opgehaald bij de reguliere monitoring, eerste observatie "
            "op of na resolves_at ({horizon_n} handelsdagen na created_at). "
            "Wisselkoersen worden niet gereviseerd, dus vintage speelt hier niet."
        ),
    )
    for key, label in (("eur_usd", "EUR/USD"), ("usd_jpy", "USD/JPY"), ("gbp_usd", "GBP/USD"))
)
# Roadmap deel A: de currency agent is de CONTROLEGROEP. De verwachting is
# dat hij een random walk niet verslaat. Blijkt dat zo, dan is dat geen
# mislukking maar de bevestiging dat de meetopstelling werkt -- en verslaat
# hij hem wel, dan is dat pas interessant omdat de lat vooraf laag lag.


FORECAST_PROMPT_VERSION = "v3"
"""Versie van de prompt waarmee deze agent voorspelt -- gaat mee in elke
prediction (`prompt_version`). De prompt is FORECAST_SYSTEM_RULES uit
`agents/base.py` PLUS de DEEP_DIVE_SYSTEM_PROMPT hieronder.

VERHOOG DIT ZODRA EEN VAN DIE TWEE VERANDERT. Binnen een cohort is een
promptwijziging een covariaat en geen nieuw cohort (CLAUDE.md), maar dan
moet je achteraf wel kunnen zien wélke voorspellingen onder welke prompt
zijn gedaan. Vergeet je het, dan zijn twee verschillende prompts achteraf
niet meer te scheiden en is dat deel van het cohort onbruikbaar.
`tests/test_forecast_prompt_version.py` faalt als de prompt verandert
zonder dat dit getal meebeweegt."""


DEEP_DIVE_SYSTEM_PROMPT = """Je bent een valuta-analist gespecialiseerd in majeure \
wisselkoersen: EUR/USD, USD/JPY, GBP/USD. Duid wat de aangeleverde beweging betekent, en \
benoem een mogelijk verband met monetair beleid ALLEEN als de aangeleverde cijfers daar \
zelf aanleiding toe geven -- verzin geen causaliteit die er niet expliciet uit blijkt. \
(De algemene schrijfregels -- neutraliteit, alleen aangeleverde cijfers, onzekerheid \
expliciet -- staan al vóór dit stuk; dit is alleen de vakinhoudelijke aanvulling.)"""


def _fetch_pair_met_reden(from_currency: str, to_currency: str, api_key: str) -> tuple[dict | None, str | None]:
    """Zelfde aanpak als commodity_data.py::fetch_fx_rate, maar geeft geen resultaat
    terug bij falen i.p.v. een {"error": ...}-dict -- deze functie levert
    aan fetch_snapshot(), die zelf bepaalt of GEEN ENKEL paar lukte. Sinds 02-10-2026
    komt er bij een mislukking een REDEN mee (sources/alpha_vantage.py)."""
    payload, reden = av.haal_json({
        "function": "CURRENCY_EXCHANGE_RATE",
        "from_currency": from_currency,
        "to_currency": to_currency,
        "apikey": api_key,
    })
    if payload is None:
        return None, reden
    rate_data = payload.get("Realtime Currency Exchange Rate")
    if not rate_data or "5. Exchange Rate" not in rate_data:
        return None, "lege respons (geen wisselkoers in het antwoord)"
    return {"value": rate_data["5. Exchange Rate"], "date": rate_data.get("6. Last Refreshed", "")}, None


def _fetch_pair(from_currency: str, to_currency: str, api_key: str) -> dict | None:
    """Alleen het resultaat (zonder herhaling of log); `fetch_snapshot` gebruikt `_fetch_pair_met_reden`."""
    return _fetch_pair_met_reden(from_currency, to_currency, api_key)[0]


def fetch_snapshot() -> dict:
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        return {"error": "ALPHAVANTAGE_API_KEY niet gevonden in environment"}
    snapshot = av.verzamel(
        DOMAIN, FX_PAIRS, lambda metric_key: _fetch_pair_met_reden(*FX_PAIRS[metric_key], api_key),
    )
    if not snapshot:
        return {"error": "geen enkel valutapaar kon worden opgehaald"}
    return snapshot


def monitor(conn, now=None, event_id=None):
    """register_source() is een idempotente upsert (roadmap 1.4) -- veilig
    om op elke cyclus te herhalen."""
    register_source(
        conn, SOURCE_KEY, provider=PROVIDER, domain=DOMAIN, max_age=MAX_AGE,
        frequency="continu (wisselkoersen)", latency="~1s per call (REST)", cost="gratis (Alpha Vantage, rate-limited)",
    )
    return run_monitoring(conn, DOMAIN, SOURCE_KEY, fetch_snapshot, METRIC_SPECS, MAX_AGE, now=now, event_id=event_id)


def deep_dive(conn, client, claims, trigger_events, now=None, event_id=None):
    return run_deep_dive(conn, client, DOMAIN, DEEP_DIVE_SYSTEM_PROMPT, claims, trigger_events, now=now, event_id=event_id)
