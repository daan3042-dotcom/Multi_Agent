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

IDEMPOTENT PER REEKS (29-09-2026; was: "geen dedup, één keer per domein").
Vóór 29-09 slikten de fetchers elke fout in en gaven `[]` terug -- ook Alpha
Vantage's antwoord "limiet bereikt" of "premium endpoint", dat als HTTP 200
met tekst in plaats van data komt. Een domein telde als geslaagd zodra ÉÉN
reeks data gaf, en omdat er geen dedup was, kon je de ontbrekende reeksen niet
bijvullen zonder de gelukte dubbel op te slaan. Een half gevulde back-fill was
dus niet te herstellen -- hetzelfde patroon als de 6-van-24-reeksen van
28-09, waarbij alle agents `success=1` meldden.

Nu geldt per reeks:
  - een fetch-fout is een `BackfillFetchError` met de tekst van de bron, en die
    komt per reeks in de uitvoer (`failed`);
  - een reeks die al historie heeft (>=20 claims ouder dan 30 dagen) wordt
    OVERGESLAGEN (`skipped`), dus opnieuw draaien is altijd veilig;
  - elke reeks wordt apart en atomair opgeslagen.
Mislukte reeksen kun je gewoon opnieuw draaien: alleen die worden opgehaald.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

import requests

from contract.output_contract import Claim, Confidence, DomainOutput, Mode, now_utc
from storage.schema import count_claims_before, save_domain_output

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
AV_BASE_URL = "https://www.alphavantage.co/query"


def _parse_date(raw: str) -> datetime:
    """FRED/Alpha Vantage geven allebei een kale 'YYYY-MM-DD'-datum terug
    voor een observatiepunt -- geen tijdcomponent, dus middernacht UTC."""
    return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)


class BackfillFetchError(Exception):
    """Een fetch leverde geen bruikbare historie. Bevat waar mogelijk de
    tekst van de bron zelf, want die zegt WAAROM (limiet, premium, verkeerde
    key) en dat is precies wat je op de VPS wilt lezen."""


def _get_json(url: str, params: dict, timeout: int = 30) -> dict:
    """Eén HTTP-call, en alles wat misgaat wordt een `BackfillFetchError`.
    Bewust breed afgevangen: netwerkfout, HTTP-fout en ongeldige JSON zijn
    voor de aanroeper hetzelfde -- deze reeks is er niet."""
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:  # noqa: BLE001
        raise BackfillFetchError(f"{type(e).__name__}: {e}") from e
    if not isinstance(payload, dict):
        raise BackfillFetchError(f"onverwacht antwoord van de bron: {str(payload)[:200]}")
    return payload


def _av_series(payload: dict, series_key: str) -> dict:
    """De tijdreeks uit een Alpha Vantage-antwoord, of een fout mét de tekst
    van de bron.

    DIT IS HET STUKJE DAT 28-09 ONTBRAK. Alpha Vantage meldt "limiet bereikt"
    en "premium endpoint" met HTTP 200 en een JSON met alleen een `Note` of
    `Information`-veld. Zonder deze controle is dat een antwoord zonder
    tijdreeks, en dus stilletjes een lege reeks."""
    for veld in ("Error Message", "Information", "Note"):
        if veld in payload:
            raise BackfillFetchError(f"Alpha Vantage: {str(payload[veld])[:300]}")
    series = payload.get(series_key)
    if not series:
        raise BackfillFetchError(f"Alpha Vantage: geen '{series_key}' in het antwoord")
    return series


def fetch_fred_full_history(series_id: str, api_key: str) -> list[dict]:
    """Volledige historie voor ÉÉN FRED-reeks, oudste eerst. Geen `limit`
    meegeven -- FRED's default (100.000) is ruim boven wat een reeks ooit
    bevat, dus geen paginering nodig. Gooit `BackfillFetchError` als er niets
    bruikbaars uitkomt (geen stille lege lijst meer)."""
    payload = _get_json(
        FRED_BASE_URL,
        {"series_id": series_id, "api_key": api_key, "file_type": "json", "sort_order": "asc"},
    )
    if "error_message" in payload:
        raise BackfillFetchError(f"FRED: {str(payload['error_message'])[:300]}")
    geldig = [
        {"value": o["value"], "date": o["date"]}
        for o in payload.get("observations", []) if o.get("value") not in (None, ".")
    ]
    if not geldig:
        raise BackfillFetchError(f"FRED: geen bruikbare waarnemingen voor {series_id}")
    return geldig


def fetch_av_time_series_daily_full_history(symbol: str, api_key: str) -> list[dict]:
    """Volledige dagelijkse slotkoers-historie voor één aandeel/ETF via
    Alpha Vantage's TIME_SERIES_DAILY (outputsize=full) -- ANDER endpoint
    dan sector_agent.py's dagelijkse GLOBAL_QUOTE, die geeft geen historie."""
    payload = _get_json(
        AV_BASE_URL,
        {"function": "TIME_SERIES_DAILY", "symbol": symbol, "outputsize": "full", "apikey": api_key},
    )
    series = _av_series(payload, "Time Series (Daily)")
    return [{"value": point["4. close"], "date": date} for date, point in series.items()]


def fetch_av_fx_daily_full_history(from_currency: str, to_currency: str, api_key: str) -> list[dict]:
    """Volledige dagelijkse-slotkoers-historie voor één valutapaar via
    Alpha Vantage's FX_DAILY (outputsize=full) -- ANDER endpoint dan
    currency_agent.py's dagelijkse CURRENCY_EXCHANGE_RATE, die geeft geen
    historie."""
    payload = _get_json(
        AV_BASE_URL,
        {
            "function": "FX_DAILY", "from_symbol": from_currency, "to_symbol": to_currency,
            "outputsize": "full", "apikey": api_key,
        },
    )
    series = _av_series(payload, "Time Series FX (Daily)")
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


HISTORY_MIN_OLD_CLAIMS = 20
HISTORY_OLD_AFTER_DAYS = 30
"""Een reeks telt als 'al gebackfilld' met minstens 20 claims van ouder dan 30
dagen. De dagelijkse cyclus maakt één claim per dag, dus in de eerste dagen
staan er een handvol -- ruim onder de grens. Een reeks die deze grens haalt
heeft hoe dan ook een echte historie, ook als hij op een eerdere (FRED-)
back-fill is binnengekomen vóórdat deze controle bestond."""


@dataclass(frozen=True)
class MetricOutcome:
    """Wat er met één reeks gebeurde. Per reeks en niet per domein: 'domein
    geslaagd' was precies de zin die een half gevulde back-fill verborg."""

    metric_key: str
    status: Literal["saved", "skipped", "failed"]
    n_claims: int = 0
    detail: str = ""


@dataclass(frozen=True)
class BackfillResult:
    domain: str
    outcomes: tuple[MetricOutcome, ...]

    @property
    def saved(self) -> int:
        """Aantal opgeslagen claims."""
        return sum(o.n_claims for o in self.outcomes if o.status == "saved")

    @property
    def failed(self) -> tuple[MetricOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status == "failed")

    @property
    def is_complete(self) -> bool:
        """Elke reeks heeft nu historie: opgeslagen of al aanwezig. Alleen dit
        mag 'geslaagd' heten."""
        return not self.failed


def _backfill_metric(
    conn, domain: str, metric_key: str, label: str, source_key: str,
    fetch: Callable[[], list[dict]], now: datetime,
) -> MetricOutcome:
    """Eén reeks: overslaan als hij al historie heeft, anders ophalen en
    atomair opslaan (één DomainOutput, één commit). `generated_at` staat op de
    oudste source_time -- zie de moduledocstring."""
    grens = now - timedelta(days=HISTORY_OLD_AFTER_DAYS)
    bestaand = count_claims_before(conn, metric_key, grens)
    if bestaand >= HISTORY_MIN_OLD_CLAIMS:
        return MetricOutcome(
            metric_key, "skipped", detail=f"al historie aanwezig ({bestaand} claims ouder dan {HISTORY_OLD_AFTER_DAYS} dagen)"
        )
    try:
        history = fetch()
    except BackfillFetchError as e:
        return MetricOutcome(metric_key, "failed", detail=str(e))
    claims = _claims_from_history(domain, metric_key, label, source_key, history)
    if not claims:
        return MetricOutcome(metric_key, "failed", detail="geen enkele waarneming was numeriek bruikbaar")
    oldest = min(c.source_time for c in claims)
    save_domain_output(conn, DomainOutput(domain=domain, mode=Mode.MONITORING, generated_at=oldest, claims=claims))
    return MetricOutcome(metric_key, "saved", n_claims=len(claims))


def _backfill_domain(conn, domain: str, source_key: str, metric_specs: dict, jobs: dict[str, Callable[[], list[dict]]]) -> BackfillResult:
    now = now_utc()
    outcomes = []
    for metric_key, fetch in jobs.items():
        spec = metric_specs.get(metric_key)
        label = spec.label if spec else metric_key
        outcomes.append(_backfill_metric(conn, domain, metric_key, label, source_key, fetch, now))
    return BackfillResult(domain, tuple(outcomes))


def backfill_fred_domain(conn, domain: str, source_key: str, fred_series: dict, metric_specs: dict, api_key: str) -> BackfillResult:
    """Back-fill voor één FRED-gebaseerde agent (monetary_policy, financial of
    economic): de volledige historie per reeks in `fred_series`."""
    jobs = {key: (lambda sid=sid: fetch_fred_full_history(sid, api_key)) for key, sid in fred_series.items()}
    return _backfill_domain(conn, domain, source_key, metric_specs, jobs)


def backfill_sector(conn, domain: str, source_key: str, sector_etfs: dict, metric_specs: dict, api_key: str) -> BackfillResult:
    """Back-fill voor sector_agent.py -- TIME_SERIES_DAILY per ETF (12 calls,
    inclusief de SPY-benchmark), niet de dagelijkse GLOBAL_QUOTE."""
    jobs = {key: (lambda sym=sym: fetch_av_time_series_daily_full_history(sym, api_key)) for key, sym in sector_etfs.items()}
    return _backfill_domain(conn, domain, source_key, metric_specs, jobs)


def backfill_currency(conn, domain: str, source_key: str, fx_pairs: dict, metric_specs: dict, api_key: str) -> BackfillResult:
    """Back-fill voor currency_agent.py -- FX_DAILY per paar (3 calls), niet
    de dagelijkse CURRENCY_EXCHANGE_RATE."""
    jobs = {
        key: (lambda van=van, naar=naar: fetch_av_fx_daily_full_history(van, naar, api_key))
        for key, (van, naar) in fx_pairs.items()
    }
    return _backfill_domain(conn, domain, source_key, metric_specs, jobs)


def backfill_commodity(conn, domain: str, source_key: str, commodities: dict, metric_specs: dict, api_key: str) -> BackfillResult:
    """Back-fill voor commodity_agent.py -- hergebruikt die module se EIGEN
    _fetch_commodity_data() (geeft al de volledige beschikbare historie terug,
    precies wat deep_dive()'s voortschrijdend-gemiddelde-model ook al
    gebruikt) in plaats van een tweede, functioneel identieke fetch-helper te
    schrijven.

    Die functie geeft bij elke fout `None`, dus hier is de REDEN niet te
    achterhalen (limiet, premium, verkeerde key): de melding zegt dat eerlijk."""
    from agents.commodity_agent import _fetch_commodity_data

    def haal_op(function_name: str) -> list[dict]:
        history = _fetch_commodity_data(function_name, api_key)
        if not history:
            raise BackfillFetchError(
                f"Alpha Vantage {function_name}: geen data (reden onbekend -- limiet, premium of key; "
                f"probeer de reeks los opnieuw)"
            )
        return history

    jobs = {key: (lambda fn=fn: haal_op(fn)) for key, fn in commodities.items()}
    return _backfill_domain(conn, domain, source_key, metric_specs, jobs)
