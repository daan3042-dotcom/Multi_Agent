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

EERSTE GEBRUIK VAN analysis/ (zie die map se docstring): deep_dive()
voegt, als er een NFCI-claim aanwezig is, de EIGEN gepubliceerde
interpretatie van de Chicago Fed toe (analysis/nfci_interpretation.py) als
extra, deterministisch berekende claim -- de LLM narrate die classificatie
dan alleen, in plaats van zelf te moeten inschatten of een NFCI-waarde
"krap" of "ruim" betekent (zie CLAUDE.md-regel 1: Python berekent, de LLM
vertelt).
"""

from __future__ import annotations

import os
from datetime import timedelta

import requests

from agents.base import ForecastTarget, MetricSpec, run_deep_dive, run_monitoring
from contract.horizons import ReleaseCadence
from contract.prediction import HorizonKind, PredictionKind
from analysis.nfci_interpretation import classify_nfci
from contract.graph import Node
from contract.output_contract import Claim, Confidence, now_utc
from storage.schema import register_source

DOMAIN = "financial"
PROVIDER = "FRED"
# Roadmap 1.4 (Source Registry): EIGEN, per-agent-gescopete source_key i.p.v.
# de kale providernaam "FRED" -- monetary_policy_agent.py gebruikt dezelfde
# provider met een andere MAX_AGE (35 vs. 10 dagen). Zie SOURCE_KEY se
# toelichting daar en docs/architecture.md ("Ontwerpkeuzes") voor de
# volledige afweging.
SOURCE_KEY = f"{PROVIDER}:{DOMAIN}"
BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
MAX_AGE = timedelta(days=10)  # NFCI is wekelijks; de andere drie zijn dagelijks

FRED_SERIES = {
    "financial_conditions_index": "NFCI",
    "high_yield_credit_spread": "BAMLH0A0HYM2",
    "vix": "VIXCLS",
    "yield_curve_10y_2y": "T10Y2Y",
}


GRAPH_MAPPING: dict[str, Node | None] = {
    "financial_conditions_index": Node.FINANCIAL_CONDITIONS,
    "high_yield_credit_spread": Node.CREDIT_RISK_PREMIUM,
    "vix": Node.RISK_APPETITE,
    # Waarneming voor een knoop die de MONETARY agent bezit. Mag: deze agent
    # leest de curve als onderdeel van de financieringscondities, maar de
    # termijnpremie zelf wordt door monetary geschat.
    "yield_curve_10y_2y": Node.TERM_PREMIUM,
}
"""De enige agent die al zijn eigen knopen dekt -- alle drie
(financial_conditions, credit_risk_premium, risk_appetite) hebben een
waarneming.

LET OP BIJ HET UITBREIDEN: deze drie knopen overlappen elkaar in de METING.
De NFCI bevat kredietspreads, VIX en aandelenkoersen als componenten, dus de
drie reeksen hierboven zijn niet onafhankelijk. Dat is waarom zes pijlen in
de graaf op Verifiability.NONE staan -- zie docs/causal-graph.md, "Wat niet
toetsbaar is". Een reeks toevoegen die opnieuw in de NFCI zit, vergroot die
overlap zonder informatie toe te voegen."""

METRIC_SPECS = {
    "financial_conditions_index": MetricSpec(label="Financial Conditions Index (NFCI)", tolerance=0.1, severity="high"),
    "high_yield_credit_spread": MetricSpec(label="High-yield credit spread", tolerance=0.5, severity="high"),
    "vix": MetricSpec(label="VIX", tolerance=5.0, severity="medium"),
    "yield_curve_10y_2y": MetricSpec(label="10Y-2Y yield curve", tolerance=0.15, severity="medium"),
}

FORECAST_TARGETS = tuple(
    ForecastTarget(
        metric_key=key,
        kind=PredictionKind.QUANTILE,
        horizon_kind=HorizonKind.TRADING_DAYS,
        horizons=(5, 21, 63),
        graph_node=node,
        resolution_rule=(
            reeks + " zoals EERST gepubliceerd, gemeten op de eerste beschikbare "
            "observatie op of na resolves_at ({horizon_n} handelsdagen na created_at). "
            "Latere revisies wijzigen de uitkomst nooit."
        ),
    )
    for key, reeks, node in (
        ("high_yield_credit_spread", "BAMLH0A0HYM2", Node.CREDIT_RISK_PREMIUM),
        ("vix", "VIXCLS", Node.RISK_APPETITE),
        ("yield_curve_10y_2y", "T10Y2Y", Node.TERM_PREMIUM),
    )
) + (
    ForecastTarget(
        metric_key="financial_conditions_index",
        kind=PredictionKind.QUANTILE,
        horizon_kind=HorizonKind.RELEASES,
        horizons=(1, 4, 12),
        cadence=ReleaseCadence.WEEKLY,
        graph_node=Node.FINANCIAL_CONDITIONS,
        resolution_rule=(
            "De {horizon_n}-de NFCI-publicatie na created_at, EERSTE print. "
            "Latere revisies wijzigen de uitkomst nooit."
        ),
    ),
)
# Roadmap deel A. De NFCI gaat op releases en niet op handelsdagen: het is
# een wekelijkse reeks, dus een 5-daagse voorspelling erop bestaat niet.


FORECAST_PROMPT_VERSION = "v1"
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


DEEP_DIVE_SYSTEM_PROMPT = """Je bent een analist gespecialiseerd in financiële-
marktcondities: de Chicago Fed National Financial Conditions Index (NFCI), \
high-yield credit spreads, VIX, en de 10-jaars-min-2-jaars yield curve. Duid wat de \
aangeleverde cijfers betekenen voor marktstress/liquiditeit (bijv. verkrappende/ \
verruimende financiële condities, toegenomen kredietrisico-opslag, een veranderende \
curve-vorm) -- alleen als de cijfers dat zelf rechtvaardigen. Krijg je een claim met een \
NFCI-interpretatie aangeleverd, gebruik dan LETTERLIJK die classificatie (krapper/ruimer \
dan het historisch gemiddelde) -- baseer je duiding niet op een eigen inschatting van wat \
een NFCI-waarde betekent, dat is al voor je berekend. (De algemene schrijfregels -- \
neutraliteit, alleen aangeleverde cijfers, onzekerheid expliciet -- staan al vóór dit \
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


def monitor(conn, now=None, event_id=None):
    """Eén monitoring-cyclus: zie agents.base.run_monitoring voor het
    volledige gedrag (data-health, claims opslaan, delta-triggers).
    register_source() is een idempotente upsert (roadmap 1.4) -- veilig
    om op elke cyclus te herhalen, declareert alleen de actuele config."""
    register_source(
        conn, SOURCE_KEY, provider=PROVIDER, domain=DOMAIN, max_age=MAX_AGE,
        frequency="wekelijks (NFCI, de traagste van de vier reeksen)", latency="~1s per call (REST)", cost="gratis (FRED API)",
    )
    return run_monitoring(conn, DOMAIN, SOURCE_KEY, fetch_snapshot, METRIC_SPECS, MAX_AGE, now=now, event_id=event_id)


def deep_dive(conn, client, claims, trigger_events, now=None, event_id=None):
    """Deep-dive mode na een trigger. Voegt, als er een NFCI-claim tussen
    zit, de NFCI's eigen gepubliceerde interpretatie toe als extra claim
    (zie moduledocstring en analysis/nfci_interpretation.py) -- puur
    Python, geen LLM-inschatting."""
    now = now or now_utc()
    enriched_claims = list(claims)
    nfci_claim = next((c for c in claims if c.metric_key == "financial_conditions_index"), None)
    if nfci_claim is not None and isinstance(nfci_claim.value, (int, float)):
        enriched_claims.append(
            Claim(
                domain=DOMAIN,
                claim="NFCI-interpretatie (Chicago Fed, gepubliceerde methodologie)",
                value=classify_nfci(nfci_claim.value),
                source="Chicago Fed NFCI-methodologie",
                confidence=Confidence.VERY_HIGH,
                analysis_time=now,
                source_time=now,
                note="0 = historisch gemiddelde sinds 1973; positief = krapper, negatief = ruimer",
            )
        )
    return run_deep_dive(conn, client, DOMAIN, DEEP_DIVE_SYSTEM_PROMPT, enriched_claims, trigger_events, now=now, event_id=event_id)
