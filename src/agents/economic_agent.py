"""
economic_agent.py
Roadmap 2.7, LEAN versie -- de enige nieuwe agent die vóór T₀ gebouwd mag
worden, als expliciete uitzondering op "geen nieuwe agents tot de
T₀-checklist staat" (CLAUDE.md, besloten 27-09-2026).

WAAROM DEZE UITZONDERING. De causale graaf (1.10) heeft vier knopen in de
reële economie -- `growth`, `labor_tightness`, `wage_growth`,
`inflation_persistence` -- en geen van de zes bestaande agents bedient er
ook maar één. Zonder deze agent leert de forward test een half jaar lang
niets over groei en arbeidsmarkt, en dat is precies de bovenkant van de
transmissieketen: financiële condities werken via groei en arbeidsmarkt
door naar inflatie en beleid. Een graaf die daar blind is, mist de
oorzaak en ziet alleen het gevolg.

LEAN BETEKENT HIER: één bron (FRED), drie reeksen, één model (de Sahm
Rule). Bewust NIET meegenomen en expliciet post-T₀ in de roadmap: output
gap via HP-filter, Misery Index, ISM-diffusie, Phillips Curve-residual.
Die vragen elk een nieuwe bron of een parameterkeuze, en dat is precies
wat vóór T₀ niet moet gebeuren.

WELKE KNOPEN DEZE AGENT BEDIENT (contract/graph.py::NODE_OWNER):
  `growth`             <- PAYEMS (banengroei als maandelijkse activiteitsmaat)
  `labor_tightness`    <- UNRATE + ICSA, met de Sahm Rule als duiding
  `wage_growth`        <- NIET BEDIEND in de lean versie (vraagt AHETPI/ECI)
  `inflation_persistence` <- NIET BEDIEND in de lean versie (vraagt core PCE)
Die laatste twee blijven dus bewust leeg tot na T₀. Dat is een bekende,
vastgelegde grens, geen vergeten reeks.

ICSA IS DE SNELST RESOLVENDE MACROREEKS DIE ER IS (wekelijks). Dat maakt
deze agent de enige macro-agent met een doel dat op korte horizon
resolvbaar is -- zie roadmap deel A, "De agents van cohort 0": ICSA
volgende 1/4 weekprints, UNRATE en PAYEMS volgende 1/3 maandprints.

OVERLAP MET DE MONETARY AGENT, BEWUST EN OPEN. monetary_policy_agent.py
monitort UNRATE ook. Dat is geen kopieerfout maar het volgt uit een
verschil in rol: die agent leest werkloosheid als input voor de
beleidsreactie (dual mandate), deze agent schat er de toestand
`labor_tightness` uit. Gevolg dat DD moet kennen: bij een
werkloosheidscijfer dat beide drempels haalt, vuren er TWEE triggers en
kunnen er twee deep-dives volgen over dezelfde publicatie, elk met een
andere invalshoek. Of dat wenselijk is, is een openstaande vraag -- zie
docs/project-state.md. Niet in stilte opgelost door een van de twee te
schrappen.

Tolerances in METRIC_SPECS zijn illustratieve plaatshouders (docs/
roadmap.md sectie H). De niveaus/eenheden van ICSA en PAYEMS zijn NIET
tegen de live API geverifieerd -- geen netwerktoegang in de
ontwikkelomgeving. Zie de opmerking bij METRIC_SPECS.
"""

from __future__ import annotations

import os
from datetime import timedelta

import requests

from agents.base import MetricSpec, run_deep_dive, run_monitoring
from analysis.sahm_rule import MIN_OBSERVATIONS, compute_sahm_gap, describe_sahm_gap
from contract.graph import Node
from contract.output_contract import Claim, Confidence, now_utc
from storage.schema import register_source

DOMAIN = "economic"
PROVIDER = "FRED"
# Roadmap 1.4: eigen, per-agent-gescopete source_key. Derde FRED-agent naast
# FRED:monetary_policy en FRED:financial -- zonder deze scoping zouden drie
# agents met verschillende ververssnelheden dezelfde data_health-rij delen.
SOURCE_KEY = f"{PROVIDER}:{DOMAIN}"
BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
# 10 dagen i.p.v. de 35 van monetary_policy_agent.py: die waarde bewaakt de
# BRON-polling (hoe lang geleden haalden we FRED voor dit domein succesvol
# op), niet de leeftijd van een losse reeks. Deze agent draait dagelijks en
# heeft een wekelijkse reeks, dus een storing hoort binnen anderhalve week
# zichtbaar te zijn en niet pas na vijf weken. Zelfde keuze als
# financial_agent.py, om dezelfde reden.
MAX_AGE = timedelta(days=10)

FRED_SERIES = {
    "initial_claims": "ICSA",  # wekelijks -> labor_tightness
    "unemployment_rate": "UNRATE",  # maandelijks -> labor_tightness
    "nonfarm_payrolls": "PAYEMS",  # maandelijks -> growth
}

UNRATE_SERIES_ID = FRED_SERIES["unemployment_rate"]

METRIC_SPECS = {
    # ICSA staat in aantallen aanvragen (niveau in de orde van 200.000-250.000);
    # 25.000 is ruwweg een beweging die boven de normale weekruis uitkomt.
    "initial_claims": MetricSpec(label="Wekelijkse WW-aanvragen (ICSA)", tolerance=25_000.0, severity="medium"),
    # Strakker dan monetary_policy_agent.py's 0,3 voor dezelfde reeks: die
    # agent kijkt naar werkloosheid als beleidsinput, deze agent bezit de
    # knoop labor_tightness en hoort dus eerder wakker te worden.
    "unemployment_rate": MetricSpec(label="Werkloosheidspercentage", tolerance=0.2, severity="high"),
    # PAYEMS is een NIVEAU in duizenden personen (orde 155.000-160.000), dus
    # de delta tussen twee observaties IS de maandelijkse banengroei. Een
    # normale maand is +100 tot +200 (duizend); 250 vangt de uitzonderlijke
    # maanden en de banenverliezen.
    "nonfarm_payrolls": MetricSpec(label="Banen buiten de landbouw (PAYEMS)", tolerance=250.0, severity="high"),
}
"""NIET GEVERIFIEERD TEGEN DE LIVE API: de niveaus en eenheden hierboven
(ICSA in aantallen, PAYEMS in duizenden personen) komen uit kennis van de
reeksen, niet uit een echte respons -- de ontwikkelomgeving heeft geen
netwerktoegang naar FRED. Klopt de eenheid van PAYEMS niet, dan staat de
tolerance er drie ordes van grootte naast en triggert hij nooit of altijd.
Dit is het eerste dat op de VPS gecontroleerd moet worden (CLAUDE.md,
checkpoint 4)."""

GRAPH_MAPPING: dict[str, Node | None] = {
    "initial_claims": Node.LABOR_TIGHTNESS,
    "unemployment_rate": Node.LABOR_TIGHTNESS,
    "nonfarm_payrolls": Node.GROWTH,
}
"""Twee van de vier knopen die deze agent bezit worden bediend. `wage_growth`
(vraagt AHETPI/ECI) en `inflation_persistence` (vraagt core PCE) blijven
bewust leeg in de lean versie -- post-T0, zie roadmap 2.7. Dat is een
vastgelegde grens, en `unserved_owned_nodes()` maakt hem elke testronde
opnieuw zichtbaar in plaats van dat hij wegzakt."""

DEEP_DIVE_SYSTEM_PROMPT = """Je bent een macro-analist gespecialiseerd in de reële \
Amerikaanse economie: arbeidsmarkt en groei. Je volgt wekelijkse WW-aanvragen (ICSA), \
het werkloosheidspercentage en de banengroei buiten de landbouw (PAYEMS). Duid wat de \
aangeleverde cijfers zeggen over de staat van de arbeidsmarkt en het tempo van de \
economische activiteit -- alleen als de cijfers dat zelf rechtvaardigen.

Let op drie dingen die hier makkelijk misgaan. Ten eerste: PAYEMS is een NIVEAU, dus de \
verandering tussen twee waarnemingen is de maandelijkse banengroei -- interpreteer een \
niveau nooit als een groeicijfer. Ten tweede: wekelijkse WW-aanvragen zijn rumoerig; één \
week is zelden een signaal, een aanhoudende richting over meerdere weken wel. Ten derde: \
krijg je een Sahm Rule-claim aangeleverd, gebruik die dan LETTERLIJK -- inclusief de \
bijbehorende waarschuwing dat het een beschrijvende indicator is die aangeeft dat een \
recessie al begonnen zou zijn, en nadrukkelijk geen voorspelling dat er een aankomt. \
Schat zelf niet in of de arbeidsmarkt "verslechtert"; dat is al voor je berekend. \
(De algemene schrijfregels -- neutraliteit, alleen aangeleverde cijfers, onzekerheid \
expliciet -- staan al vóór dit stuk; dit is alleen de vakinhoudelijke aanvulling.)"""


def _fetch_series(series_id: str, api_key: str) -> dict | None:
    """Meest recente observatie van één reeks. None bij elke fout (netwerk,
    lege respons, FRED's '.'-placeholder) -- geen gok, gewoon niets voor
    deze reeks. Zelfde conventie als monetary_policy_agent.py en
    financial_agent.py."""
    try:
        resp = requests.get(
            BASE_URL,
            params={
                "series_id": series_id, "api_key": api_key, "file_type": "json",
                "sort_order": "desc", "limit": 1,
            },
            timeout=15,
        )
        resp.raise_for_status()
        observations = resp.json().get("observations", [])
    except Exception:
        return None
    if not observations:
        return None
    obs = observations[0]
    if obs.get("value") in (None, "."):
        return None
    return {"value": obs["value"], "date": obs["date"]}


def _fetch_series_history(series_id: str, api_key: str, count: int) -> list[float] | None:
    """De laatste `count` waarden van een reeks, CHRONOLOGISCH (oudste
    eerst) -- de volgorde die analysis/sahm_rule.py verwacht. FRED levert
    aflopend, dus de lijst wordt hier omgedraaid.

    Geeft None als er minder dan `count` bruikbare waarden zijn. Bewust
    STRENG: een Sahm-berekening op een gaten-reeks zou stilzwijgend een
    ander venster gebruiken dan het gepubliceerde model. Placeholders ('.')
    tellen daarom niet mee als waarde."""
    try:
        resp = requests.get(
            BASE_URL,
            params={
                "series_id": series_id, "api_key": api_key, "file_type": "json",
                "sort_order": "desc", "limit": count,
            },
            timeout=15,
        )
        resp.raise_for_status()
        observations = resp.json().get("observations", [])
    except Exception:
        return None

    values: list[float] = []
    for obs in observations:
        raw = obs.get("value")
        if raw in (None, "."):
            return None
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            return None

    if len(values) < count:
        return None
    return list(reversed(values))


def fetch_snapshot() -> dict:
    """Haalt de meest recente waarde per FRED-reeks op. {"error": ...} alleen
    als GEEN ENKELE reeks lukte -- een gedeeltelijk mislukte pull is normaal
    en geen bronstoring."""
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
    register_source() is een idempotente upsert (roadmap 1.4)."""
    register_source(
        conn, SOURCE_KEY, provider=PROVIDER, domain=DOMAIN, max_age=MAX_AGE,
        frequency="wekelijks (ICSA) en maandelijks (UNRATE, PAYEMS)",
        latency="~1s per call (REST)", cost="gratis (FRED API)",
    )
    return run_monitoring(conn, DOMAIN, SOURCE_KEY, fetch_snapshot, METRIC_SPECS, MAX_AGE, now=now, event_id=event_id)


def _fetch_sahm_inputs() -> list[float] | None:
    """De 15 maandelijkse werkloosheidscijfers die de Sahm Rule nodig heeft.
    Leest FRED_API_KEY zelf uit de environment, zelfde patroon als
    fetch_snapshot() -- daardoor in tests rechtstreeks monkeypatchbaar."""
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return None
    return _fetch_series_history(UNRATE_SERIES_ID, api_key, MIN_OBSERVATIONS)


def deep_dive(conn, client, claims, trigger_events, now=None, event_id=None):
    """Deep-dive mode na een trigger. Voegt, als er een unemployment_rate-
    claim tussen zit, de Sahm Rule-gap en de bijbehorende duiding toe als
    extra claims -- puur Python, geen LLM-inschatting (zelfde patroon als
    monetary_policy_agent.py's Taylor Rule en financial_agent.py's
    NFCI-interpretatie).

    Ontbreken de inputs (geen API-key, netwerkfout, te korte historie), dan
    wordt de verrijking overgeslagen en gaat de deep-dive gewoon door
    zonder. Geen halve Sahm-berekening op minder maanden."""
    now = now or now_utc()
    enriched_claims = list(claims)
    unemployment_claim = next((c for c in claims if c.metric_key == "unemployment_rate"), None)
    if unemployment_claim is not None:
        history = _fetch_sahm_inputs()
        if history is not None:
            gap = compute_sahm_gap(history)
            if gap is not None:
                enriched_claims.append(
                    Claim(
                        domain=DOMAIN,
                        claim="Sahm Rule-gap (3-maands gemiddelde werkloosheid t.o.v. laagste van de voorgaande 12 maanden)",
                        value=round(gap, 2),
                        source="Berekend (Sahm Rule, 2019)",
                        confidence=Confidence.MEDIUM,
                        analysis_time=now,
                        source_time=now,
                        note=f"Berekend over {len(history)} maandelijkse UNRATE-waarnemingen",
                    )
                )
                enriched_claims.append(
                    Claim(
                        domain=DOMAIN,
                        claim=describe_sahm_gap(gap),
                        value=round(gap, 2),
                        source="Berekend (Sahm Rule, 2019)",
                        confidence=Confidence.MEDIUM,
                        analysis_time=now,
                        source_time=now,
                    )
                )
    return run_deep_dive(conn, client, DOMAIN, DEEP_DIVE_SYSTEM_PROMPT, enriched_claims, trigger_events, now=now, event_id=event_id)
