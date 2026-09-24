"""
commodity_agent.py
Stap C.4: "eerste écht andere databron (prijzen/supply chain)". Dit
bestand levert de PRIJZEN-helft -- supply-chain-signalen (bijv. een
verstoring bij een mijn of raffinaderij) zijn kwalitatief/nieuws-vormig en
horen eerder bij de news monitor agent (sectie D) dan bij een prijs-API.

Grondstoffenlijst en Alpha Vantage-functienamen 1-op-1 overgenomen van
analyst_agent.ai's data/commodity_data.py::SUPPORTED_COMMODITIES -- dit IS
de bestaande, curated lijst (geen eigen selectie bedacht), en bevat
letterlijk COPPER (relevant voor DD's ERO Copper-positie) en de twee
majeure ruwe-oliebenchmarks. Alle 10, net als sector_agent.py's "bewust
compleet"-keuze: het is al een kleine, curated set, geen reden om er
zelf nog een subset uit te pikken.

Eén plat domain="commodity" (zoals currency/sector: elke grondstof heeft
een unieke metric_key, geen namespacing-risico zoals bij equity).

Data via Alpha Vantage (hergebruikt ALPHAVANTAGE_API_KEY). Anders dan
GLOBAL_QUOTE (sector_agent.py) geeft dit endpoint een LIJST historische
punten terug (interval=monthly, zelfde keuze als analyst_agent.ai) --
fetch_snapshot() gebruikt alleen het meest recente punt; deep_dive()
gebruikt de overige punten (al in dezelfde API-respons aanwezig) voor het
voortschrijdend-gemiddelde-model hieronder, dus GEEN extra API-call nodig
t.o.v. wat er al opgehaald wordt.

ONDERBOUWING: analysis/moving_average_deviation.py -- de procentuele
afwijking van de huidige prijs t.o.v. het 6-maands-gemiddelde (dezelfde 6
punten die Alpha Vantage's commodity-endpoint al teruggeeft). Positief =
prijs ligt boven het recente gemiddelde, negatief = eronder. Zelfde
"Python berekent een model, de LLM narrate het"-patroon als de andere drie
modellen in analysis/.

TOLERANCES: grondstoffen hebben zeer verschillende prijsniveaus EN
eenheden (dollar/vat, dollar/pond, dollar/bushel, ...) -- de waarden
hieronder zijn ruwe schattingen (~5% van een TYPISCH niveau), met MINDER
zekerheid dan bijv. sector_agent.py's ETF-tolerances (prijsniveaus en
eenheden voor bijv. WHEAT/COTTON zijn hier niet met zekerheid geverifieerd
tegen actuele marktdata). Nog sterker een kandidaat voor DD's eigen
latere finetuning dan de andere agents -- zie CLAUDE.md, "Werkwijze met
DD".
"""

from __future__ import annotations

import os
from datetime import timedelta

import requests

from agents.base import MetricSpec, run_deep_dive, run_monitoring
from analysis.moving_average_deviation import compute_deviation_from_average_pct, compute_moving_average
from contract.output_contract import Claim, Confidence, now_utc

DOMAIN = "commodity"
SOURCE_NAME = "ALPHA_VANTAGE_COMMODITY"
BASE_URL = "https://www.alphavantage.co/query"
MAX_AGE = timedelta(days=40)  # maandelijkse data (interval=monthly, zelfde keuze als analyst_agent.ai)
MOVING_AVERAGE_PERIODS = 6  # aantal maandpunten voor het voortschrijdend gemiddelde

# metric_key -> Alpha Vantage-functienaam. 1-op-1 uit analyst_agent.ai's
# SUPPORTED_COMMODITIES, zie moduledocstring.
COMMODITIES = {
    "wti": "WTI",
    "brent": "BRENT",
    "natural_gas": "NATURAL_GAS",
    "copper": "COPPER",
    "aluminum": "ALUMINUM",
    "wheat": "WHEAT",
    "corn": "CORN",
    "cotton": "COTTON",
    "sugar": "SUGAR",
    "coffee": "COFFEE",
}

METRIC_SPECS = {
    "wti": MetricSpec(label="WTI ruwe olie", tolerance=4.0, severity="medium"),
    "brent": MetricSpec(label="Brent ruwe olie", tolerance=4.0, severity="medium"),
    "natural_gas": MetricSpec(label="Aardgas", tolerance=0.20, severity="medium"),
    "copper": MetricSpec(label="Koper", tolerance=0.20, severity="high"),
    "aluminum": MetricSpec(label="Aluminium", tolerance=120.0, severity="medium"),
    "wheat": MetricSpec(label="Tarwe", tolerance=30.0, severity="medium"),
    "corn": MetricSpec(label="Maïs", tolerance=25.0, severity="medium"),
    "cotton": MetricSpec(label="Katoen", tolerance=4.0, severity="medium"),
    "sugar": MetricSpec(label="Suiker", tolerance=1.5, severity="medium"),
    "coffee": MetricSpec(label="Koffie", tolerance=10.0, severity="medium"),
}

DEEP_DIVE_SYSTEM_PROMPT = """Je bent een analist gespecialiseerd in grondstofprijzen \
(ruwe olie, aardgas, industriële metalen, landbouwgrondstoffen). Duid wat een \
significante prijsbeweging betekent -- alleen als de aangeleverde cijfers dat \
rechtvaardigen. Krijg je een claim met een voortschrijdend-gemiddelde-afwijking \
aangeleverd, gebruik die dan LETTERLIJK om te bepalen of de huidige prijs ver boven/onder \
het recente gemiddelde ligt -- schat dat niet zelf in, dat is al voor je berekend. (De \
algemene schrijfregels -- neutraliteit, alleen aangeleverde cijfers, onzekerheid expliciet \
-- staan al vóór dit stuk; dit is alleen de vakinhoudelijke aanvulling.)"""


def _fetch_commodity_data(function_name: str, api_key: str) -> list[dict] | None:
    """Haalt de recente maandpunten op voor een grondstof (meest recent
    eerst, zelfde volgorde als Alpha Vantage teruggeeft). None bij elke
    fout -- geen gok, gewoon niets voor deze grondstof."""
    try:
        resp = requests.get(
            BASE_URL, params={"function": function_name, "interval": "monthly", "apikey": api_key}, timeout=15,
        )
        resp.raise_for_status()
        data_points = resp.json().get("data", [])
    except Exception:
        return None
    valid_points = [p for p in data_points if p.get("value") not in (None, ".")]
    return valid_points or None


def fetch_snapshot() -> dict:
    """Haalt de meest recente maandwaarde per grondstof op. {"error": ...}
    alleen als GEEN ENKELE grondstof lukte."""
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        return {"error": "ALPHAVANTAGE_API_KEY niet gevonden in environment"}
    snapshot = {}
    for metric_key, function_name in COMMODITIES.items():
        data_points = _fetch_commodity_data(function_name, api_key)
        if data_points:
            snapshot[metric_key] = {"value": data_points[0]["value"], "date": data_points[0]["date"]}
    if not snapshot:
        return {"error": "geen enkele grondstof kon worden opgehaald"}
    return snapshot


def monitor(conn, now=None):
    """Eén monitoring-cyclus: zie agents.base.run_monitoring voor het
    volledige gedrag (data-health, claims opslaan, delta-triggers)."""
    return run_monitoring(conn, DOMAIN, SOURCE_NAME, fetch_snapshot, METRIC_SPECS, MAX_AGE, now=now)


def deep_dive(conn, client, claims, trigger_events, now=None):
    """Deep-dive mode na een trigger. Voegt, voor elke grondstof-claim in
    `claims`, de afwijking t.o.v. het 6-maands-gemiddelde toe als extra
    claim (zie moduledocstring en analysis/moving_average_deviation.py) --
    puur Python, geen LLM-inschatting. Eén extra API-call per grondstof
    (voor de historische punten) -- ontbreekt die data, dan wordt de
    verrijking voor die grondstof gewoon overgeslagen."""
    now = now or now_utc()
    enriched_claims = list(claims)
    commodity_claims = [c for c in claims if c.metric_key in COMMODITIES]
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")

    if commodity_claims and api_key:
        for commodity_claim in commodity_claims:
            function_name = COMMODITIES[commodity_claim.metric_key]
            data_points = _fetch_commodity_data(function_name, api_key)
            if data_points is None or len(data_points) < MOVING_AVERAGE_PERIODS:
                continue
            try:
                recent_values = [float(p["value"]) for p in data_points[:MOVING_AVERAGE_PERIODS]]
                current_value = float(commodity_claim.value)
            except (TypeError, ValueError):
                continue
            average = compute_moving_average(recent_values)
            deviation_pct = compute_deviation_from_average_pct(current_value, average)
            enriched_claims.append(
                Claim(
                    domain=DOMAIN,
                    claim=f"Afwijking {commodity_claim.claim} t.o.v. {MOVING_AVERAGE_PERIODS}-maands-gemiddelde",
                    value=round(deviation_pct, 2),
                    source=f"Berekend ({MOVING_AVERAGE_PERIODS}-maands voortschrijdend gemiddelde)",
                    confidence=Confidence.HIGH,
                    analysis_time=now,
                    source_time=now,
                    note=f"gemiddelde={average:.2f}, huidige waarde={current_value:.2f}",
                )
            )

    return run_deep_dive(conn, client, DOMAIN, DEEP_DIVE_SYSTEM_PROMPT, enriched_claims, trigger_events, now=now)
