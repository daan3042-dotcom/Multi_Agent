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
eenheden (dollar/vat, dollar/ton, dollar/mmbtu, cent/pond, ...). Tot
29-09-2026 waren de waarden ruwe schattingen; sinds trigger-versie v2 zijn ze
gekalibreerd op 35 jaar back-fill (`calibrate_triggers.py`), zie de opmerking
bij METRIC_SPECS hieronder. Kwaliteitsvoorbehoud dat blijft: de bron geeft
maandgemiddelden, en een vast bedrag veroudert als het prijsniveau
wegdrijft (zie docs/roadmap.md, open beslissing over niveau-afhankelijke
drempels).
"""

from __future__ import annotations

import os
from datetime import timedelta

import requests

from agents.base import MetricSpec, run_deep_dive, run_monitoring
from analysis.moving_average_deviation import compute_deviation_from_average_pct, compute_moving_average
from contract.graph import Node
from contract.output_contract import Claim, Confidence, now_utc
from storage.schema import register_source

DOMAIN = "commodity"
PROVIDER = "ALPHA_VANTAGE_COMMODITY"
SOURCE_KEY = f"{PROVIDER}:{DOMAIN}"  # roadmap 1.4 (Source Registry); zie monetary_policy_agent.py::SOURCE_KEY voor de volledige toelichting
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

# Trigger-versie v2 (29-09-2026): gekalibreerd op de back-fill, ~5 keer per jaar
# over de laatste drie jaar (kalibratierapport, Tabel 2). De bron is MAANDELIJKS,
# dus 5 per jaar is 5 van de 12 publicaties, en alle tien de reeksen springen op
# dezelfde dag: de manager bundelt dat tot een deep-dive per dag.
#
# EENHEDEN, nu geverifieerd tegen de opgeslagen data (voorheen een aanname):
# koper staat in dollar per METRISCHE TON (niveau ~13.500), niet per pond zoals
# de v0-tolerantie van 0,20 aannam. Die regel vuurde daardoor bij ELKE
# publicatie (100% van de waarnemingen) en was dus geen drempel maar een
# constante. Tarwe en maïs (v0: 30 en 25) vuurden in drie jaar bijna nooit
# (0,3 per jaar).
METRIC_SPECS = {
    "wti": MetricSpec(label="WTI ruwe olie", tolerance=4.1, severity="medium"),
    "brent": MetricSpec(label="Brent ruwe olie", tolerance=4.4, severity="medium"),
    "natural_gas": MetricSpec(label="Aardgas", tolerance=0.3, severity="medium"),
    "copper": MetricSpec(label="Koper", tolerance=356.0, severity="high"),
    "aluminum": MetricSpec(label="Aluminium", tolerance=73.0, severity="medium"),
    "wheat": MetricSpec(label="Tarwe", tolerance=11.7, severity="medium"),
    "corn": MetricSpec(label="Maïs", tolerance=9.6, severity="medium"),
    "cotton": MetricSpec(label="Katoen", tolerance=1.9, severity="medium"),
    "sugar": MetricSpec(label="Suiker", tolerance=0.9, severity="medium"),
    "coffee": MetricSpec(label="Koffie", tolerance=14.6, severity="medium"),
}


GRAPH_MAPPING: dict[str, Node | None] = {
    "wti": Node.ENERGY_PRICES,
    "brent": Node.ENERGY_PRICES,
    "natural_gas": Node.ENERGY_PRICES,
    "copper": Node.INDUSTRIAL_METALS,
    "aluminum": Node.INDUSTRIAL_METALS,
    # De vijf hieronder voeden GEEN knoop. `food_ags` is bij het opstellen
    # van de graaf bewust geschrapt: landbouwprijzen bewegen op weer en
    # oogsten, niet op de economische machine, en ze zaten alleen in beeld
    # omdat deze agent die reeksen toch al ophaalde -- de verkeerde reden om
    # een knoop te maken. Ze blijven wel gemonitord (goedkoop, zelfde call),
    # maar ze schatten niets.
    "wheat": None,
    "corn": None,
    "cotton": None,
    "sugar": None,
    "coffee": None,
}
"""Vijf van de tien reeksen voeden geen enkele knoop. Dat is zichtbaar
gemaakt in plaats van weggemoffeld: het is de scherpste illustratie van het
verschil tussen data ophalen en een model hebben."""

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


def monitor(conn, now=None, event_id=None):
    """Eén monitoring-cyclus: zie agents.base.run_monitoring voor het
    volledige gedrag (data-health, claims opslaan, delta-triggers).
    register_source() is een idempotente upsert (roadmap 1.4) -- veilig
    om op elke cyclus te herhalen."""
    register_source(
        conn, SOURCE_KEY, provider=PROVIDER, domain=DOMAIN, max_age=MAX_AGE,
        frequency="maandelijks (interval=monthly)", latency="~1s per call (REST)", cost="gratis (Alpha Vantage, rate-limited)",
    )
    return run_monitoring(conn, DOMAIN, SOURCE_KEY, fetch_snapshot, METRIC_SPECS, MAX_AGE, now=now, event_id=event_id)


def deep_dive(conn, client, claims, trigger_events, now=None, event_id=None):
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

    return run_deep_dive(conn, client, DOMAIN, DEEP_DIVE_SYSTEM_PROMPT, enriched_claims, trigger_events, now=now, event_id=event_id)
