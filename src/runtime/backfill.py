"""
backfill.py
Roadmap 1.11, fase 0b-1: eenmalige historische back-fill -- "elke
gemonitorde metric heeft historie in de DB; macroreeksen >= 20 jaar" (zie
docs/roadmap.md, fase 0). Dit is BEWUST GEEN onderdeel van de dagelijkse
cyclus (`runtime/daily.py`) -- het is een handmatig, eenmalig te draaien
script (zie `backfill.py` in de repo-root), niet iets dat cron elke dag
opnieuw moet doen.

HERGEBRUIKT elk agent-bestand se eigen FRED_SERIES/SECTOR_ETFS/COMMODITIES/
FX_PAIRS/METRIC_SPECS/DOMAIN/SOURCE_KEY -- geen tweede, losse lijst van
dezelfde reeksen die uit de pas kan gaan lopen met de dagelijkse agents.

TWEE DATABRONNEN, TWEE ENDPOINTS PER PROVIDER dan de dagelijkse cyclus:
- FRED: dezelfde `series/observations`-endpoint, maar ZONDER `limit` --
  geeft dan de volledige historie in één call (FRED's default limit is
  100.000 observaties, ruim boven wat een enkele reeks ooit bevat). Geen
  quota-zorgen: FRED heeft geen praktisch relevante daglimiet op dit
  volume (zie docs/data-sources.md).
- Alpha Vantage: de dagelijkse cyclus gebruikt `GLOBAL_QUOTE` (sector) en
  `CURRENCY_EXCHANGE_RATE` (currency) -- BEIDE geven geen historie terug,
  alleen de laatste waarde. Back-fill gebruikt daarom ANDERE AV-endpoints
  (`TIME_SERIES_DAILY` voor sector, `FX_DAILY` voor currency) die wel een
  volledige reeks teruggeven. `commodity_agent`'s eigen endpoint geeft al
  historie (hergebruikt via die module se `_fetch_commodity_data()`).
  KOSTELIJK: 3 (FX) + 11 (sector) + 10 (commodity) = 24 AV-calls, exact
  tegen de dagelijkse quota-limiet van de gebruikte tier aan (zie
  docs/data-sources.md) -- dus NIET op dezelfde dag als de reguliere
  monitoring-cyclus draaien zonder een hogere tier, zie `backfill.py`'s
  eigen CLI-hulp.

WAAROM ÉÉN DOMAINOUTPUT MET EEN OUDE `generated_at`, NIET "NU"
(cruciaal, geen slordigheid): `storage.schema.load_monitoring_claims()`
pakt de MEEST RECENTE monitoring-DomainOutput per domein (ORDER BY
generated_at DESC) om aan een deep-dive te voeren. Zou de back-fill-
DomainOutput `generated_at=nu` krijgen, dan zou een deep-dive die
LATER VANDAAG triggert de VOLLEDIGE historie (honderden/duizenden claims)
aangeboden krijgen in plaats van alleen de laatste, actuele cijfers --
een enorme, onbedoelde prompt-bloat, en precies de verdubbelings-bug die
load_monitoring_claims()'s eigen docstring al beschrijft voor een andere
situatie. Door `generated_at` te zetten op de OUDSTE `source_time` in de
batch, wint de back-fill-DomainOutput die ORDER-BY-vergelijking NOOIT van
een echte cyclus (verleden of toekomst) -- de individuele CLAIMS blijven
wel hun eigen, correcte `analysis_time`/`source_time` houden (zie
_claims_from_history()), dus de trigger-laag se `load_latest_claims()`
(die queryt `claims` direct, niet via domain_outputs) werkt gewoon door.

GEEN DEDUP: dit script is bewust een eenmalige, handmatige actie (geen
event_id/agent_runs-idempotency zoals de dagelijkse cyclus) -- twee keer
draaien voor hetzelfde domein voegt twee keer dezelfde claims toe. Zie
`backfill.py`'s CLI-waarschuwing.
"""

from __future__ import annotations

from datetime import datetime, timezone

import requests

from contract.output_contract import Claim, Confidence, DomainOutput, Mode, now_utc
from storage.schema import save_domain_output

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
AV_BASE_URL = "https://www.alphavantage.co/query"


def _parse_date(raw: str) -> datetime:
    """FRED/Alpha Vantage geven allebei een kale 'YYYY-MM-DD'-datum terug
    voor een observatiepunt -- geen tijdcomponent, dus middernacht UTC."""
    return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)


def fetch_fred_full_history(series_id: str, api_key: str) -> list[dict]:
    """Volledige historie voor ÉÉN FRED-reeks, oudste eerst. Geen `limit`
    meegeven -- FRED's default (100.000) is ruim boven wat een reeks ooit
    bevat, dus geen paginering nodig. Lege lijst bij elke fout (geen gok,
    zelfde patroon als de dagelijkse _fetch_series()-helpers)."""
    try:
        resp = requests.get(
            FRED_BASE_URL,
            params={"series_id": series_id, "api_key": api_key, "file_type": "json", "sort_order": "asc"},
            timeout=30,
        )
        resp.raise_for_status()
        observations = resp.json().get("observations", [])
    except Exception:
        return []
    return [{"value": o["value"], "date": o["date"]} for o in observations if o.get("value") not in (None, ".")]


def fetch_av_time_series_daily_full_history(symbol: str, api_key: str) -> list[dict]:
    """Volledige dagelijkse slotkoers-historie voor één aandeel/ETF via
    Alpha Vantage's TIME_SERIES_DAILY (outputsize=full) -- ANDER endpoint
    dan sector_agent.py's dagelijkse GLOBAL_QUOTE, die geeft geen historie."""
    try:
        resp = requests.get(
            AV_BASE_URL,
            params={"function": "TIME_SERIES_DAILY", "symbol": symbol, "outputsize": "full", "apikey": api_key},
            timeout=30,
        )
        resp.raise_for_status()
        series = resp.json().get("Time Series (Daily)", {})
    except Exception:
        return []
    return [{"value": point["4. close"], "date": date} for date, point in series.items()]


def fetch_av_fx_daily_full_history(from_currency: str, to_currency: str, api_key: str) -> list[dict]:
    """Volledige dagelijkse-slotkoers-historie voor één valutapaar via
    Alpha Vantage's FX_DAILY (outputsize=full) -- ANDER endpoint dan
    currency_agent.py's dagelijkse CURRENCY_EXCHANGE_RATE, die geeft geen
    historie."""
    try:
        resp = requests.get(
            AV_BASE_URL,
            params={
                "function": "FX_DAILY", "from_symbol": from_currency, "to_symbol": to_currency,
                "outputsize": "full", "apikey": api_key,
            },
            timeout=30,
        )
        resp.raise_for_status()
        series = resp.json().get("Time Series FX (Daily)", {})
    except Exception:
        return []
    return [{"value": point["4. close"], "date": date} for date, point in series.items()]


def _claims_from_history(
    domain: str, metric_key: str, label: str, source_key: str, history: list[dict],
) -> list[Claim]:
    """Zet ruwe (value, date)-punten om in Claims -- `analysis_time` wordt
    hier BEWUST gelijk aan `source_time` gezet (in plaats van 'nu'): dat
    is wat load_latest_claims()'s ORDER BY analysis_time DESC nodig heeft
    om de claims in de juiste chronologische volgorde te zien (zie
    moduledocstring). `ingestion_time` blijft wel eerlijk 'nu' (wanneer
    WIJ dit daadwerkelijk hebben opgehaald, via Claim.__post_init__'s
    default zou dat anders analysis_time geworden zijn)."""
    claims = []
    now = now_utc()
    for point in history:
        try:
            value = float(point["value"])
        except (TypeError, ValueError):
            continue
        source_time = _parse_date(point["date"])
        claims.append(
            Claim(
                domain=domain,
                claim=label,
                value=value,
                source=source_key,
                confidence=Confidence.HIGH,
                analysis_time=source_time,
                source_time=source_time,
                ingestion_time=now,
                metric_key=metric_key,
                note="back-fill (roadmap 1.11, 0b-1)",
            )
        )
    return claims


def _save_backfill(conn, domain: str, claims: list[Claim]) -> int:
    """Slaat alle claims van één domein op als ÉÉN DomainOutput, met
    `generated_at` op de OUDSTE source_time in de batch -- zie
    moduledocstring voor waarom dat cruciaal is (voorkomt dat een latere
    deep-dive de hele historie krijgt aangeboden i.p.v. de laatste
    cijfers). Geeft 0 terug (geen output opgeslagen) als er geen enkele
    geldige claim was."""
    if not claims:
        return 0
    oldest = min(c.source_time for c in claims)
    output = DomainOutput(domain=domain, mode=Mode.MONITORING, generated_at=oldest, claims=claims)
    save_domain_output(conn, output)
    return len(claims)


def backfill_fred_domain(conn, domain: str, source_key: str, fred_series: dict, metric_specs: dict, api_key: str) -> int:
    """Back-fill voor één FRED-gebaseerde agent (monetary_policy,
    financial of economic) -- haalt de volledige historie op voor elke
    reeks in `fred_series` en slaat ze samen op. Geeft het aantal
    opgeslagen claims terug (0 als er niets kon worden opgehaald)."""
    claims: list[Claim] = []
    for metric_key, series_id in fred_series.items():
        history = fetch_fred_full_history(series_id, api_key)
        spec = metric_specs.get(metric_key)
        label = spec.label if spec else metric_key
        claims.extend(_claims_from_history(domain, metric_key, label, source_key, history))
    return _save_backfill(conn, domain, claims)


def backfill_sector(conn, domain: str, source_key: str, sector_etfs: dict, metric_specs: dict, api_key: str) -> int:
    """Back-fill voor sector_agent.py -- TIME_SERIES_DAILY per ETF (11
    calls), niet de dagelijkse GLOBAL_QUOTE."""
    claims: list[Claim] = []
    for metric_key, symbol in sector_etfs.items():
        history = fetch_av_time_series_daily_full_history(symbol, api_key)
        spec = metric_specs.get(metric_key)
        label = spec.label if spec else metric_key
        claims.extend(_claims_from_history(domain, metric_key, label, source_key, history))
    return _save_backfill(conn, domain, claims)


def backfill_currency(conn, domain: str, source_key: str, fx_pairs: dict, metric_specs: dict, api_key: str) -> int:
    """Back-fill voor currency_agent.py -- FX_DAILY per paar (3 calls),
    niet de dagelijkse CURRENCY_EXCHANGE_RATE."""
    claims: list[Claim] = []
    for metric_key, (from_currency, to_currency) in fx_pairs.items():
        history = fetch_av_fx_daily_full_history(from_currency, to_currency, api_key)
        spec = metric_specs.get(metric_key)
        label = spec.label if spec else metric_key
        claims.extend(_claims_from_history(domain, metric_key, label, source_key, history))
    return _save_backfill(conn, domain, claims)


def backfill_commodity(conn, domain: str, source_key: str, commodities: dict, metric_specs: dict, api_key: str) -> int:
    """Back-fill voor commodity_agent.py -- hergebruikt die module se
    EIGEN _fetch_commodity_data() (geeft al de volledige beschikbare
    historie terug, precies wat deep_dive()'s voortschrijdend-gemiddelde-
    model ook al gebruikt) in plaats van een tweede, functioneel
    identieke fetch-helper te schrijven."""
    from agents.commodity_agent import _fetch_commodity_data

    claims: list[Claim] = []
    for metric_key, function_name in commodities.items():
        history = _fetch_commodity_data(function_name, api_key) or []
        spec = metric_specs.get(metric_key)
        label = spec.label if spec else metric_key
        claims.extend(_claims_from_history(domain, metric_key, label, source_key, history))
    return _save_backfill(conn, domain, claims)
