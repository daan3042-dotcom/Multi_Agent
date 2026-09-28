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

UITGEBREID OP 28-09-2026 MET VIER REEKSEN (DGS2, T5YIE, T10YIE, WALCL) om
drie knopen van de causale graaf te bedienen die deze agent volgens
contract/graph.py::NODE_OWNER bezit maar nergens uit kon schatten:
policy_expectations, inflation_expectations en liquidity. Twee dingen die
hierbij bewust zijn afgewogen:

1. MAX_AGE blijft 35 dagen, ook al zijn drie van de vier nieuwe reeksen
   dagelijks en is WALCL wekelijks. Dat kan, omdat run_monitoring()'s
   max_age de BRON-polling bewaakt (hoe lang geleden haalden we FRED voor
   dit domein voor het laatst succesvol op), niet de leeftijd van elke
   losse reeks. Een dagelijkse reeks toevoegen verkleint dus geen
   staleness-venster. Wat WEL blijft staan als bekende grens: 35 dagen is
   ruim voor een agent die dagelijks draait -- een FRED-storing zou pas na
   vijf weken een trigger geven. Dat is bestaand gedrag voor alle vier de
   oorspronkelijke reeksen, en het verscherpen ervan is een
   drempelwijziging die niet in deze ronde thuishoort.
2. WALCL's eenheid is op 28-09-2026 GEVERIFIEERD tegen de live API: de
   eerste run op de VPS leverde 6.747.704, wat de aanname bevestigt dat de
   reeks in MILJOENEN dollars staat (~$6,75 biljoen). De tolerance is bij
   diezelfde meting verlaagd van 100.000 naar 25.000 -- $100 miljard
   balansverandering in een week komt alleen bij crisis-QE voor, dus de
   oude drempel zou nooit gevuurd hebben en liet de knoop `liquidity`
   blind voor het tempo van de afbouw. Hiermee is de checkpoint-4-vlag op
   dit bestand vervallen.

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

from agents.base import ForecastTarget, MetricSpec, run_deep_dive, run_monitoring
from contract.horizons import ReleaseCadence
from contract.prediction import HorizonKind, PredictionKind
from analysis.taylor_rule import compute_output_gap_pct, compute_taylor_rule_rate
from contract.graph import Node
from contract.output_contract import Claim, Confidence, now_utc
from storage.schema import register_source

DOMAIN = "monetary_policy"
PROVIDER = "FRED"
# Roadmap 1.4 (Source Registry): EIGEN, per-agent-gescopete source_key i.p.v.
# de kale providernaam "FRED" -- financial_agent.py gebruikt dezelfde
# provider met een andere MAX_AGE (35 vs. 10 dagen); zonder deze scoping
# zouden beide agents naar dezelfde data_health-rij schrijven en zou de
# ene agent's succesvolle polls de andere's staleness verbergen. Zie
# sources/registry.py se moduledocstring en docs/architecture.md
# ("Ontwerpkeuzes") voor de volledige afweging.
SOURCE_KEY = f"{PROVIDER}:{DOMAIN}"
BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
MAX_AGE = timedelta(days=35)  # de meeste FRED-reeksen hier zijn maandelijks

FRED_SERIES = {
    "fed_funds_rate": "FEDFUNDS",
    "10y_treasury_yield": "DGS10",
    "cpi_inflation_index": "CPIAUCSL",
    "unemployment_rate": "UNRATE",
    # Toegevoegd 28-09-2026 om drie lege knopen van de causale graaf (1.10)
    # te bedienen -- zie contract/graph.py::NODE_OWNER, dat deze agent als
    # primaire eigenaar van policy_expectations, inflation_expectations en
    # liquidity aanwijst. Zonder deze reeksen had die agent die knopen op
    # papier wel, maar geen enkele waarneming om ze uit te schatten.
    "2y_treasury_yield": "DGS2",  # -> policy_expectations
    "inflation_expectations_5y": "T5YIE",  # -> inflation_expectations
    "inflation_expectations_10y": "T10YIE",  # -> inflation_expectations
    "fed_balance_sheet": "WALCL",  # -> liquidity
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
    # Zelfde status als de vier hierboven: illustratieve plaatshouders, geen
    # door DD gevalideerde drempels (docs/roadmap.md sectie H). De eerste
    # drie zijn percentagepunten en liggen in dezelfde orde van grootte als
    # de bestaande rente-tolerances; fed_balance_sheet is de MINST ZEKERE
    # van alle tolerances in dit project -- zie de moduledocstring.
    "2y_treasury_yield": MetricSpec(label="2-jaars Treasury yield", tolerance=0.25, severity="medium"),
    "inflation_expectations_5y": MetricSpec(label="5-jaars break-even inflatie", tolerance=0.10, severity="medium"),
    "inflation_expectations_10y": MetricSpec(label="10-jaars break-even inflatie", tolerance=0.10, severity="medium"),
    # 25.000 = ~$25 miljard balansverandering. Verlaagd van 100.000 op
    # 28-09-2026, nadat de eerste live run het niveau bevestigde op
    # 6.747.704 (miljoenen USD, dus ~$6,75 biljoen). Een normale week is
    # $5-30 miljard; $100 miljard zie je alleen bij crisis-QE, dus de oude
    # drempel zou in de praktijk nooit gevuurd hebben en liet de knoop
    # `liquidity` blind voor het tempo van de balansafbouw.
    "fed_balance_sheet": MetricSpec(label="Fed-balanstotaal", tolerance=25_000.0, severity="medium"),
}

GRAPH_MAPPING: dict[str, Node | None] = {
    "fed_funds_rate": Node.POLICY_STANCE,
    "10y_treasury_yield": Node.TERM_PREMIUM,
    "2y_treasury_yield": Node.POLICY_EXPECTATIONS,
    "inflation_expectations_5y": Node.INFLATION_EXPECTATIONS,
    "inflation_expectations_10y": Node.INFLATION_EXPECTATIONS,
    "fed_balance_sheet": Node.LIQUIDITY,
    # Waarnemingen voor knopen die de ECONOMIC agent bezit. Mag: eigenaarschap
    # bepaalt wie de toestand schat, niet wie ernaar mag kijken. Deze agent
    # leest ze als input voor de beleidsreactie (dual mandate).
    "cpi_inflation_index": Node.INFLATION_PERSISTENCE,
    "unemployment_rate": Node.LABOR_TIGHTNESS,
}
"""Welke graafknoop (1.10) elke opgehaalde reeks helpt schatten. Alle vijf
knopen die deze agent bezit worden bediend -- `unserved_owned_nodes()`
bewaakt dat. Tot 28-09-2026 gold dat voor maar een van de vijf."""

FORECAST_TARGETS = (
    ForecastTarget(
        metric_key="10y_treasury_yield",
        kind=PredictionKind.QUANTILE,
        horizon_kind=HorizonKind.TRADING_DAYS,
        horizons=(5, 21, 63),
        graph_node=Node.TERM_PREMIUM,
        resolution_rule=(
            "DGS10 zoals EERST gepubliceerd, gemeten op de eerste beschikbare observatie "
            "op of na resolves_at ({horizon_n} handelsdagen na created_at). Latere revisies "
            "wijzigen de uitkomst nooit."
        ),
    ),
    ForecastTarget(
        metric_key="2y_treasury_yield",
        kind=PredictionKind.QUANTILE,
        horizon_kind=HorizonKind.TRADING_DAYS,
        horizons=(5, 21, 63),
        graph_node=Node.POLICY_EXPECTATIONS,
        resolution_rule=(
            "DGS2 zoals EERST gepubliceerd, gemeten op de eerste beschikbare observatie "
            "op of na resolves_at ({horizon_n} handelsdagen na created_at). Latere revisies "
            "wijzigen de uitkomst nooit."
        ),
    ),
    ForecastTarget(
        metric_key="fed_funds_rate",
        kind=PredictionKind.BINARY,
        horizon_kind=HorizonKind.RELEASES,
        horizons=(1, 2),
        cadence=ReleaseCadence.FOMC,
        graph_node=Node.POLICY_STANCE,
        event_rule=(
            "De Fed funds rate ligt na de {horizon_n}-de FOMC-vergadering na created_at "
            "HOGER dan de laatst bekende waarde op created_at"
        ),
        resolution_rule=(
            "FEDFUNDS-waarde na de {horizon_n}-de FOMC-vergadering na created_at, "
            "eerste print, vergeleken met de laatst bekende waarde op created_at. "
            "Gelijk blijven telt als NIET verhoogd."
        ),
    ),
)
# Roadmap deel A, "De agents van cohort 0". DGS2 staat niet in de
# startlijst maar is hier toegevoegd: die reeks kwam er op 28-09 bij om de
# knoop policy_expectations te bedienen, en een extra ONAFHANKELIJK doel is
# precies wat de statistische kracht omhoog brengt (correctie 2 van 27-09:
# breedte telt, herhaling niet).


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


DEEP_DIVE_SYSTEM_PROMPT = """Je bent een macro-analist gespecialiseerd in Amerikaans \
monetair beleid: Fed funds rate, 2- en 10-jaars Treasury yield, CPI-index, werkloosheid, \
break-even inflatieverwachtingen (5 en 10 jaar) en het Fed-balanstotaal. Duid \
wat de aangeleverde cijfers betekenen in hun macro-context (bijv. verkrappend/verruimend \
beleidssignaal, een mogelijk verband tussen de aangeleverde reeksen onderling) -- alleen \
als de cijfers dat zelf rechtvaardigen. Houd daarbij drie dingen uit elkaar die makkelijk \
door elkaar lopen: wat de Fed DOET (de beleidsrente), wat de markt VERWACHT dat de Fed \
gaat doen (de 2-jaars yield is daar de gangbaarste maatstaf voor), en wat de markt aan \
INFLATIE verwacht (de break-evens). Een bewegende 10-jaars yield hoeft geen \
verandering in Fed-verwachtingen te zijn -- het kan ook de termijnpremie zijn. Krijg je een Taylor Rule-impliciete rente en een \
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


def monitor(conn, now=None, event_id=None):
    """Eén monitoring-cyclus: zie agents.base.run_monitoring voor het
    volledige gedrag (data-health, claims opslaan, delta-triggers).
    register_source() is een idempotente upsert (roadmap 1.4) -- veilig
    om op elke cyclus te herhalen, declareert alleen de actuele config."""
    register_source(
        conn, SOURCE_KEY, provider=PROVIDER, domain=DOMAIN, max_age=MAX_AGE,
        frequency="gemengd: maandelijks (FEDFUNDS/CPI/UNRATE), dagelijks (DGS2/DGS10/break-evens), wekelijks (WALCL)",
        latency="~1s per call (REST)", cost="gratis (FRED API)",
    )
    return run_monitoring(conn, DOMAIN, SOURCE_KEY, fetch_snapshot, METRIC_SPECS, MAX_AGE, now=now, event_id=event_id)


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


def deep_dive(conn, client, claims, trigger_events, now=None, event_id=None):
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
                    analysis_time=now,
                    source_time=now,
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
                    analysis_time=now,
                    source_time=now,
                )
            )
    return run_deep_dive(conn, client, DOMAIN, DEEP_DIVE_SYSTEM_PROMPT, enriched_claims, trigger_events, now=now, event_id=event_id)
