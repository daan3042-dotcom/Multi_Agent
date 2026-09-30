"""
probe.py
Roadmap 1.2 (`expectations`, `events`) en 1.4 (bronnen), fase A van het plan in
`docs/data-archive.md` (30-09-2026): een eenmalige, ALLEEN-LEZEN meting van
kandidaatbronnen voor het brede ruwe archief.

WAT DIT IS. Per bron één (of enkele) aanroep, en een rij in een rapport: bereikbaar,
gratis of betaald, hoe ver de historie gaat, hoe ver de nieuwste waarneming achterloopt,
in welke eenheid, en of de data achteraf terug te halen is. Uit die metingen volgt een
ADVIES per bron: archief nu, archief later, of een beslissing voor DD.

WAT DIT NIET IS. Geen archief, geen opslag, geen agent en geen trigger. Er wordt niets in
de database geschreven en er wordt geen bestand aangemaakt behalve, op verzoek, een
JSON-kopie van het rapport. Het bepaalt evenmin welke reeksen een agent krijgt (laag 2):
dat blijft een bewuste keuze met een trigger-versie.

WAAROM METEN. Het onderzoek waar dit uit voortkomt is deels uit het hoofd geschreven
(FRED-ID's, Yahoo-tickers, "gratis bronnen gaan maar 30 tot 60 dagen terug"). CLAUDE.md
checkpoint 4: geen beste gok. Het commodity-endpoint heeft dat al bewezen: het bleek
niet live te zijn, terwijl dat werd aangenomen. Hier staat elke aanname als meting.

VEILIGHEID.
- Sleutels staan alleen in de aanvraag en NOOIT in de uitvoer: elke tekst gaat door
  `redact_secrets` (dezelfde functie als de back-fill), ook foutmeldingen van `requests`
  die de url meenemen. Draai het script niet met `-v`: urllib3-debug logt volledige url's.
- Beperkt callvolume: ongeveer 15 Alpha Vantage-aanroepen met een seconde pauze, ruim onder
  75 per minuut, en één FRED-aanroep per reeks. Met `--zonder-av` nul Alpha Vantage.
- Geen `yfinance`: Yahoo is onofficieel en de bibliotheek haalt gecompileerde
  afhankelijkheden binnen (CLAUDE.md regel 2). Dat staat als bewust niet geprobeerd in het rapport.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import requests

from runtime.backfill import redact_secrets

AV_URL = "https://www.alphavantage.co/query"
FRED_URL = "https://api.stlouisfed.org/fred"
USER_AGENT = "market-intelligence-probe/1.0"
TIMEOUT_SECONDEN = 60

STATUS_OK = "ok"
STATUS_LEEG = "leeg"
STATUS_LIMIET = "limiet"
STATUS_GEEN_TOEGANG = "geen toegang (plan)"
STATUS_FOUT = "fout"
STATUS_NIET_BEREIKBAAR = "niet bereikbaar"
STATUS_NIET_GEPROBEERD = "niet geprobeerd"

ADVIES_NU = "archief NU (niet terug te halen)"
ADVIES_LATER = "archief later (terug te halen, geen haast)"
ADVIES_BESLISSING = "beslissing DD (niet beschikbaar of betaald)"
ADVIES_METEN = "eerst diepte meten (herstelbaarheid onbekend)"
ALLE_ADVIEZEN = (ADVIES_NU, ADVIES_LATER, ADVIES_METEN, ADVIES_BESLISSING)

HERSTELBAAR_JA = "ja"
HERSTELBAAR_NEE = "nee"
HERSTELBAAR_ONBEKEND = "onbekend"


def bepaal_advies(status: str, herstelbaar: str) -> str:
    """De ene adviesregel, bewust deterministisch en klein.

    - Niet gelukt te meten (of niet te krijgen): een beslissing voor DD, vaak met een
      prijs erbij. Geen advies om te archiveren wat er niet is.
    - Bereikbaar en NIET terug te halen: archief nu. Elke dag zonder is verloren.
    - Bereikbaar en terug te halen: archief later. Geen haast, geen testperiode kwijt.
    - Bereikbaar en onbekend: eerst de diepte meten, in plaats van te gokken."""
    if status != STATUS_OK:
        return ADVIES_BESLISSING
    if herstelbaar == HERSTELBAAR_NEE:
        return ADVIES_NU
    if herstelbaar == HERSTELBAAR_JA:
        return ADVIES_LATER
    return ADVIES_METEN


@dataclass
class ProbeResult:
    id: str
    categorie: str
    bron: str
    status: str
    detail: str = ""
    kosten: str = "onbekend"
    herstelbaar: str = HERSTELBAAR_ONBEKEND
    eerste: str | None = None
    laatste: str | None = None
    achterstand_dagen: int | None = None
    eenheid: str | None = None
    herstelbaar_via: str | None = None
    advies: str = ""

    def __post_init__(self):
        # Alles wat naar buiten gaat, gaat door de sleutelfilter. Ook als een aanroeper
        # vergeet het zelf te doen: dit is de laatste verdediging.
        self.detail = redact_secrets(self.detail)[:300]
        self.advies = bepaal_advies(self.status, self.herstelbaar)

    def hersteld_via_meting(self, herstelbaar: str) -> None:
        self.herstelbaar = herstelbaar
        self.advies = bepaal_advies(self.status, self.herstelbaar)


@dataclass
class Context:
    """Alles wat een meting van buiten nodig heeft, injecteerbaar voor tests."""

    av_key: str | None
    fred_key: str | None
    nu: date = field(default_factory=lambda: datetime.now(timezone.utc).date())
    # Bij AANROEP opgezocht en niet bij het definiëren van de klasse: zo kan een test
    # `requests.get` en `time.sleep` vervangen zonder dat het script echt wacht of belt.
    get: Callable = lambda *a, **k: requests.get(*a, **k)  # noqa: E731
    slaap: Callable = lambda s: time.sleep(s)  # noqa: E731
    timeout: int = TIMEOUT_SECONDEN
    av_pauze: float = 1.0
    fred_pauze: float = 0.3
    aanroepen_av: int = 0
    aanroepen_fred: int = 0


def laatste_werkdag_op_of_voor(d: date) -> date:
    """Optieketens bestaan alleen voor handelsdagen. Een weekend geeft een leeg antwoord
    dat er uitziet als 'geen historie'; dit voorkomt die valse conclusie. (Een feestdag kan
    nog steeds leeg zijn; dat staat dan in het detail.)"""
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _http(ctx: Context, url: str, params: dict | None = None):
    """(antwoord, fouttekst). Elke uitzondering wordt een fouttekst zonder sleutels."""
    try:
        antwoord = ctx.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=ctx.timeout)
    except Exception as e:  # noqa: BLE001 - netwerkfout, timeout en SSL zijn voor ons hetzelfde
        return None, redact_secrets(f"{type(e).__name__}: {e}")
    return antwoord, ""


def _json(antwoord):
    try:
        return antwoord.json()
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------
# Alpha Vantage
# --------------------------------------------------------------------------


def av_status(payload) -> tuple[str, str] | None:
    """Herkent de manieren waarop Alpha Vantage 'nee' zegt, ook bij HTTP 200. None als het
    antwoord er inhoudelijk normaal uitziet en de aanroeper zelf moet beoordelen.

    Het lege antwoord `{}` krijgt zijn eigen status: het is op 29-09-2026 voorgekomen (oorzaak
    onbekend) en moet in dit rapport niet verward worden met 'geen data'."""
    if not isinstance(payload, dict):
        return STATUS_FOUT, "geen JSON-object als antwoord"
    if not payload:
        return STATUS_LEEG, "leeg antwoord ({})"
    for sleutel in ("Information", "Note"):
        if sleutel in payload:
            tekst = str(payload[sleutel])
            laag = tekst.lower()
            if "premium" in laag or "subscribe" in laag:
                return STATUS_GEEN_TOEGANG, tekst[:200]
            if "rate limit" in laag or "requests per" in laag or "call frequency" in laag:
                return STATUS_LIMIET, tekst[:200]
            return STATUS_FOUT, tekst[:200]
    if "Error Message" in payload:
        return STATUS_FOUT, str(payload["Error Message"])[:200]
    return None


def probe_av(
    ctx: Context, id: str, categorie: str, params: dict,
    beoordeel: Callable[[dict], tuple[bool, str, str | None, str | None]],
    herstelbaar: str = HERSTELBAAR_ONBEKEND, herstelbaar_via: str | None = None,
    bron: str = "Alpha Vantage (betaald plan)",
) -> ProbeResult:
    """Eén Alpha Vantage-aanroep. `beoordeel(payload)` geeft (gelukt, detail, eerste, laatste)."""
    basis = dict(id=id, categorie=categorie, bron=bron, kosten="betaald plan",
                 herstelbaar=herstelbaar, herstelbaar_via=herstelbaar_via)
    if not ctx.av_key:
        return ProbeResult(status=STATUS_NIET_GEPROBEERD, detail="geen ALPHAVANTAGE_API_KEY", **basis)

    antwoord, fout = _http(ctx, AV_URL, {**params, "apikey": ctx.av_key})
    ctx.aanroepen_av += 1
    ctx.slaap(ctx.av_pauze)
    if antwoord is None:
        return ProbeResult(status=STATUS_NIET_BEREIKBAAR, detail=fout, **basis)
    payload = _json(antwoord)
    afwijking = av_status(payload)
    if afwijking is not None:
        return ProbeResult(status=afwijking[0], detail=afwijking[1], **basis)
    gelukt, detail, eerste, laatste = beoordeel(payload)
    achterstand = _achterstand(ctx.nu, laatste)
    return ProbeResult(
        status=STATUS_OK if gelukt else STATUS_LEEG, detail=detail, eerste=eerste, laatste=laatste,
        achterstand_dagen=achterstand, **basis,
    )


def _beoordeel_opties(datum: date):
    def f(p):
        data = p.get("data")
        if isinstance(data, list) and data:
            # Bewust geen `laatste`: dit is een DIEPTEmeting op een gekozen datum, en die datum in de
            # kolom 'achterstand' leest als verouderde data.
            return True, f"{len(data)} contracten voor {datum} (werkdag)", None, None
        return False, f"geen contracten voor {datum} (feestdag of buiten de historie)", None, None
    return f


def _beoordeel_intraday(p):
    for sleutel, reeks in p.items():
        if sleutel.startswith("Time Series") and isinstance(reeks, dict) and reeks:
            stempels = sorted(reeks)
            # Geen `eerste`/`laatste`: het is één geteste maand (diepte), geen actualiteit.
            return True, f"{len(reeks)} bars, van {stempels[0][:10]} tot {stempels[-1][:10]}", None, None
    return False, "geen tijdreeks in het antwoord", None, None


def _beoordeel_nieuws(p):
    feed = p.get("feed")
    if isinstance(feed, list) and feed:
        return True, f"{len(feed)} artikelen in het venster", None, None
    return False, "geen artikelen in het gevraagde venster", None, None


def _beoordeel_transcript(p):
    tekst = p.get("transcript")
    if isinstance(tekst, list) and tekst:
        return True, f"{len(tekst)} fragmenten", None, None
    return False, "geen transcript", None, None


def _beoordeel_koers(p):
    q = p.get("Global Quote") or {}
    prijs = q.get("05. price")
    if prijs:
        dag = q.get("07. latest trading day")
        return True, f"prijs {prijs}", None, dag
    return False, "geen koers in het antwoord", None, None


def _av_probes(ctx: Context) -> list[ProbeResult]:
    j1 = laatste_werkdag_op_of_voor(ctx.nu - timedelta(days=365))
    j5 = laatste_werkdag_op_of_voor(ctx.nu - timedelta(days=5 * 365))
    m1 = (ctx.nu - timedelta(days=365)).strftime("%Y-%m")
    m10 = (ctx.nu - timedelta(days=10 * 365)).strftime("%Y-%m")
    nieuws_van = (ctx.nu - timedelta(days=365)).strftime("%Y%m%dT0000")
    nieuws_tot = (ctx.nu - timedelta(days=364)).strftime("%Y%m%dT0000")

    r: list[ProbeResult] = []
    r.append(probe_av(ctx, "av_options_historie_1j", "opties", {"function": "HISTORICAL_OPTIONS", "symbol": "SPY", "date": str(j1)},
                      _beoordeel_opties(j1), herstelbaar=HERSTELBAAR_JA))
    r.append(probe_av(ctx, "av_options_historie_5j", "opties", {"function": "HISTORICAL_OPTIONS", "symbol": "SPY", "date": str(j5)},
                      _beoordeel_opties(j5), herstelbaar=HERSTELBAAR_JA))
    r.append(probe_av(ctx, "av_options_realtime", "opties", {"function": "REALTIME_OPTIONS", "symbol": "SPY"},
                      lambda p: (bool(p.get("data")), f"{len(p.get('data') or [])} contracten nu", None, str(ctx.nu)),
                      herstelbaar_via="av_options_historie_1j"))
    r.append(probe_av(ctx, "av_intraday_10j", "intraday", {"function": "TIME_SERIES_INTRADAY", "symbol": "SPY", "interval": "5min", "month": m10, "outputsize": "full"},
                      _beoordeel_intraday, herstelbaar=HERSTELBAAR_JA))
    r.append(probe_av(ctx, "av_intraday_1j", "intraday", {"function": "TIME_SERIES_INTRADAY", "symbol": "SPY", "interval": "5min", "month": m1, "outputsize": "full"},
                      _beoordeel_intraday, herstelbaar_via="av_intraday_10j"))
    r.append(probe_av(ctx, "av_nieuws_1j", "nieuws", {"function": "NEWS_SENTIMENT", "tickers": "SPY", "time_from": nieuws_van, "time_to": nieuws_tot, "limit": "5"},
                      _beoordeel_nieuws, herstelbaar=HERSTELBAAR_JA))
    r.append(probe_av(ctx, "av_transcript", "tekst", {"function": "EARNINGS_CALL_TRANSCRIPT", "symbol": "IBM", "quarter": "2024Q1"},
                      _beoordeel_transcript, herstelbaar=HERSTELBAAR_JA))
    # ETF-proxies voor grondstoffen: dezelfde route als de sector agent (GLOBAL_QUOTE en
    # TIME_SERIES_DAILY). De historie via TIME_SERIES_DAILY is voor de sector agent al bewezen.
    for symbool in ("USO", "BNO", "UNG", "CPER", "GLD", "SLV", "DBA"):
        r.append(probe_av(ctx, f"av_etf_{symbool.lower()}", "commodity-proxy", {"function": "GLOBAL_QUOTE", "symbol": symbool},
                          _beoordeel_koers, herstelbaar=HERSTELBAAR_JA))
    return r


# --------------------------------------------------------------------------
# FRED en ALFRED
# --------------------------------------------------------------------------

# (id, categorie). De ID's komen uit het onderzoek en uit het hoofd; dit script is de test.
FRED_KANDIDATEN: tuple[tuple[str, str], ...] = (
    # monetary policy
    ("DFEDTARU", "monetary"), ("DFEDTARL", "monetary"), ("DFF", "monetary"), ("SOFR", "monetary"),
    ("IORB", "monetary"), ("DGS3MO", "monetary"), ("DGS30", "monetary"), ("DFII10", "monetary"),
    ("T5YIFR", "monetary"), ("PCEPILFE", "monetary"), ("CPILFESL", "monetary"),
    ("RRPONTSYD", "monetary"), ("WTREGEN", "monetary"), ("WRESBAL", "monetary"),
    ("FEDTARMD", "monetary"), ("THREEFYTP10", "monetary"),
    # financial
    ("VXVCLS", "financial"), ("T10Y3M", "financial"), ("ANFCI", "financial"), ("STLFSI4", "financial"),
    ("BAMLC0A0CM", "financial"), ("BAMLH0A3HYC", "financial"), ("BAMLH0A0HYM2", "financial"),
    # economic
    ("CES0500000003", "economic"), ("JTSJOL", "economic"), ("INDPRO", "economic"), ("RSAFS", "economic"),
    ("HOUST", "economic"), ("PERMIT", "economic"), ("UMCSENT", "economic"), ("SAHMREALTIME", "economic"),
    ("GDPNOW", "economic"), ("GDPC1", "economic"), ("PCEPI", "economic"), ("PPIFIS", "economic"),
    ("DGORDER", "economic"), ("NEWORDER", "economic"), ("CFNAI", "economic"), ("CCSA", "economic"),
    ("WEI", "economic"),
    # currency
    ("DTWEXBGS", "currency"), ("DEXUSEU", "currency"), ("DEXJPUS", "currency"), ("DEXUSUK", "currency"),
    ("DEXCHUS", "currency"), ("DEXSZUS", "currency"), ("DEXUSAL", "currency"), ("DEXCAUS", "currency"),
    # commodity
    ("DCOILWTICO", "commodity"), ("DCOILBRENTEU", "commodity"), ("DHHNGSP", "commodity"),
)


def _achterstand(nu: date, laatste: str | None) -> int | None:
    if not laatste:
        return None
    try:
        return (nu - date.fromisoformat(laatste[:10])).days
    except ValueError:
        return None


def probe_fred(ctx: Context, series_id: str, categorie: str) -> ProbeResult:
    """Eén FRED-aanroep per reeks: titel, frequentie, eenheid, eerste en laatste waarneming.

    De EENHEID staat bewust in het rapport. De koper-tolerantie van 0,20 was een aangenomen
    eenheid (per pond) terwijl de bron per metrische ton levert; dat mag niet nog eens gebeuren."""
    basis = dict(id=f"fred_{series_id.lower()}", categorie=categorie, bron=f"FRED {series_id}",
                 kosten="gratis", herstelbaar=HERSTELBAAR_JA)
    if not ctx.fred_key:
        return ProbeResult(status=STATUS_NIET_GEPROBEERD, detail="geen FRED_API_KEY", **basis)
    antwoord, fout = _http(ctx, f"{FRED_URL}/series", {"series_id": series_id, "api_key": ctx.fred_key, "file_type": "json"})
    ctx.aanroepen_fred += 1
    ctx.slaap(ctx.fred_pauze)
    if antwoord is None:
        return ProbeResult(status=STATUS_NIET_BEREIKBAAR, detail=fout, **basis)
    payload = _json(antwoord)
    if not isinstance(payload, dict):
        return ProbeResult(status=STATUS_FOUT, detail=f"HTTP {getattr(antwoord, 'status_code', '?')}, geen JSON", **basis)
    if "error_message" in payload:
        return ProbeResult(status=STATUS_FOUT, detail=str(payload["error_message"])[:200], **basis)
    reeksen = payload.get("seriess") or []
    if not reeksen:
        return ProbeResult(status=STATUS_FOUT, detail="reeks niet gevonden", **basis)
    s = reeksen[0]
    eerste, laatste = s.get("observation_start"), s.get("observation_end")
    detail = f"{s.get('title', '?')} | {s.get('frequency_short', '?')} | {s.get('units_short', '?')}"
    return ProbeResult(
        status=STATUS_OK, detail=detail, eerste=eerste, laatste=laatste,
        achterstand_dagen=_achterstand(ctx.nu, laatste), eenheid=s.get("units_short"), **basis,
    )


def probe_alfred_vintages(ctx: Context, series_id: str = "PAYEMS") -> ProbeResult:
    """Bestaat er voor deze reeks een vintage-archief (ALFRED)? Bepaalt of eerste prints van
    FRED-reeksen achteraf terug te halen zijn."""
    basis = dict(id=f"alfred_{series_id.lower()}", categorie="eerste prints", bron=f"ALFRED {series_id}",
                 kosten="gratis", herstelbaar=HERSTELBAAR_JA)
    if not ctx.fred_key:
        return ProbeResult(status=STATUS_NIET_GEPROBEERD, detail="geen FRED_API_KEY", **basis)
    antwoord, fout = _http(ctx, f"{FRED_URL}/series/vintagedates",
                           {"series_id": series_id, "api_key": ctx.fred_key, "file_type": "json", "limit": 3})
    ctx.aanroepen_fred += 1
    ctx.slaap(ctx.fred_pauze)
    if antwoord is None:
        return ProbeResult(status=STATUS_NIET_BEREIKBAAR, detail=fout, **basis)
    payload = _json(antwoord)
    if not isinstance(payload, dict) or "error_message" in payload:
        return ProbeResult(status=STATUS_FOUT, detail=str((payload or {}).get("error_message", "geen JSON"))[:200], **basis)
    datums = payload.get("vintage_dates") or []
    aantal = payload.get("count", len(datums))
    if not datums:
        return ProbeResult(status=STATUS_LEEG, detail="geen vintagedatums", **basis)
    return ProbeResult(status=STATUS_OK, detail=f"{aantal} vintages, de oudste vanaf {datums[0]}", eerste=datums[0], **basis)


# --------------------------------------------------------------------------
# Openbare bronnen zonder sleutel
# --------------------------------------------------------------------------

_DATUM_REGEL = re.compile(r"^\s*(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})")


def _datum_uit_csv(tekst: str) -> tuple[int, str | None, str | None]:
    """(aantal datumregels, eerste, laatste) uit een CSV met een datum in de eerste kolom.
    Herkent MM/DD/JJJJ (Cboe) en JJJJ-MM-DD. Geeft ISO-datums terug."""
    def iso(s: str) -> str:
        if "/" in s:
            m, d, y = s.split("/")
            return f"{y}-{m}-{d}"
        return s

    datums = [iso(m.group(1)) for regel in tekst.splitlines() if (m := _DATUM_REGEL.match(regel))]
    if not datums:
        return 0, None, None
    return len(datums), datums[0], datums[-1]


def probe_url(
    ctx: Context, id: str, categorie: str, bron: str, url: str, beoordeel: Callable,
    herstelbaar: str, kosten: str = "gratis", params: dict | None = None,
) -> ProbeResult:
    """Een openbare url. `beoordeel(antwoord)` geeft (gelukt, detail, eerste, laatste)."""
    basis = dict(id=id, categorie=categorie, bron=bron, kosten=kosten, herstelbaar=herstelbaar)
    antwoord, fout = _http(ctx, url, params)
    if antwoord is None:
        return ProbeResult(status=STATUS_NIET_BEREIKBAAR, detail=fout, **basis)
    code = getattr(antwoord, "status_code", None)
    if code != 200:
        return ProbeResult(status=STATUS_FOUT, detail=f"HTTP {code}", **basis)
    try:
        gelukt, detail, eerste, laatste = beoordeel(antwoord)
    except Exception as e:  # noqa: BLE001 - een onverwacht antwoordformaat is een bevinding, geen crash
        return ProbeResult(status=STATUS_FOUT, detail=f"antwoord niet te lezen: {type(e).__name__}", **basis)
    return ProbeResult(
        status=STATUS_OK if gelukt else STATUS_LEEG, detail=detail, eerste=eerste, laatste=laatste,
        achterstand_dagen=_achterstand(ctx.nu, laatste), **basis,
    )


def _csv_met_datums(antwoord):
    n, eerste, laatste = _datum_uit_csv(antwoord.text)
    if not n:
        return False, "geen datumregels herkend", None, None
    return True, f"{n} regels", eerste, laatste


def _json_lijst(sleutel: str | None):
    def f(antwoord):
        p = antwoord.json()
        data = p.get(sleutel) if (sleutel and isinstance(p, dict)) else p
        if isinstance(data, list) and data:
            return True, f"{len(data)} record(s)", None, None
        return False, "leeg antwoord", None, None
    return f


def _bestand(antwoord):
    inhoud = getattr(antwoord, "content", b"") or b""
    soort = (getattr(antwoord, "headers", {}) or {}).get("Content-Type", "?")
    return len(inhoud) > 1000, f"{len(inhoud)} bytes, {soort}", None, None


def _pagina(antwoord):
    return True, "bereikbaar", None, None


def _csv_regels(antwoord):
    regels = [r for r in antwoord.text.splitlines() if r.strip()]
    return len(regels) > 1, f"{len(regels)} regels", None, None


def _openbare_probes(ctx: Context) -> list[ProbeResult]:
    cboe = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{}_History.csv"
    r: list[ProbeResult] = []
    for naam in ("VIX3M", "VIX9D", "VVIX", "SKEW"):
        r.append(probe_url(ctx, f"cboe_{naam.lower()}", "volatiliteit", f"Cboe {naam} (csv)", cboe.format(naam),
                           _csv_met_datums, HERSTELBAAR_JA))
    r.append(probe_url(ctx, "spy_holdings", "samenstelling", "State Street SPY-holdings (xlsx, alleen de huidige)",
                       "https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx",
                       _bestand, HERSTELBAAR_NEE))
    r.append(probe_url(ctx, "cftc_cot_legacy", "positionering", "CFTC COT (Socrata)",
                       "https://publicreporting.cftc.gov/resource/6dca-aqww.json",
                       _json_lijst(None), HERSTELBAAR_JA, params={"$limit": 1}))
    r.append(probe_url(ctx, "nyfed_sofr", "geldmarkt", "NY Fed Markets API (SOFR)",
                       "https://markets.newyorkfed.org/api/rates/secured/sofr/last/1.json",
                       _json_lijst("refRates"), HERSTELBAAR_JA))
    r.append(probe_url(ctx, "treasury_dts", "liquiditeit", "Treasury FiscalData (dagelijkse kassaldo)",
                       "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance",
                       _json_lijst("data"), HERSTELBAAR_JA, params={"sort": "-record_date", "page[size]": 1}))
    r.append(probe_url(ctx, "ecb_eurusd", "valuta", "ECB Data Portal (EUR/USD)",
                       "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A",
                       _csv_regels, HERSTELBAAR_JA, params={"lastNObservations": 1, "format": "csvdata"}))
    r.append(probe_url(ctx, "kalshi", "voorspellingsmarkt", "Kalshi (openbare markten)",
                       "https://api.elections.kalshi.com/trade-api/v2/markets",
                       _json_lijst("markets"), HERSTELBAAR_ONBEKEND, params={"limit": 1}))
    r.append(probe_url(ctx, "polymarket", "voorspellingsmarkt", "Polymarket (gamma)",
                       "https://gamma-api.polymarket.com/markets", _json_lijst(None), HERSTELBAAR_ONBEKEND, params={"limit": 1}))
    r.append(probe_url(ctx, "fed_fomc_kalender", "tekst", "Federal Reserve (FOMC-pagina; statements en notulen zijn gearchiveerd)",
                       "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", _pagina, HERSTELBAAR_JA))
    return r


# --------------------------------------------------------------------------
# Wat bewust niet geprobeerd wordt
# --------------------------------------------------------------------------

# (id, categorie, bron, reden, herstelbaar, kosten)
NIET_GEPROBEERD: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("consensus_macro", "verwachting", "Consensus vóór macro-releases (mediaan, hoog, laag, vorige)",
     "betaalde diensten; geen gratis betrouwbare bron bekend", HERSTELBAAR_NEE, "betaald"),
    ("fedfunds_futures", "verwachting", "Fed funds futures (ZQ), SOFR-futures, FedWatch-kansen",
     "CME-data is betaald; gratis routes geven hooguit het eerste contract en zijn kwetsbaar", HERSTELBAAR_NEE, "betaald"),
    ("earnings_consensus", "verwachting", "Earnings-consensus en forward EPS voor de megacaps",
     "betaalde diensten", HERSTELBAAR_NEE, "betaald"),
    ("ism_pmi", "eerste prints", "ISM Manufacturing en Services, S&P Global flash-PMI's",
     "gelicenseerd en niet te scrapen", HERSTELBAAR_NEE, "betaald"),
    ("cme_cvol", "volatiliteit", "CME CVOL (valuta- en rentevolatiliteit)",
     "alleen actuele waarde, meestal betaald", HERSTELBAAR_NEE, "betaald"),
    ("atlanta_mpt", "verwachting", "Atlanta Fed Market Probability Tracker",
     "url niet bekend; eerst uitzoeken of een csv-download met historie bestaat", HERSTELBAAR_ONBEKEND, "gratis"),
    ("regionale_fed_surveys", "eerste prints", "Empire, Philly, Richmond, Kansas City, Dallas",
     "nog niet uitgezocht; deels gratis bij de Fed-banken zelf", HERSTELBAAR_ONBEKEND, "gratis"),
    ("futures_intraday", "intraday", "Futures ES, NQ, RTY, ZN, CL, GC per minuut of vijf minuten",
     "futures staan niet op Alpha Vantage; vraagt een aparte bron", HERSTELBAAR_NEE, "onbekend"),
    ("yahoo_tickers", "prijzen", "Yahoo-tickers (^GSPC, ES=F, HG=F, EURUSD=X, ...)",
     "bewust niet: onofficieel, en yfinance haalt gecompileerde afhankelijkheden binnen (CLAUDE.md regel 2)",
     HERSTELBAAR_ONBEKEND, "gratis"),
)


def _niet_geprobeerd() -> list[ProbeResult]:
    return [
        ProbeResult(id=i, categorie=c, bron=b, status=STATUS_NIET_GEPROBEERD, detail=reden, kosten=kosten, herstelbaar=h)
        for i, c, b, reden, h, kosten in NIET_GEPROBEERD
    ]


# --------------------------------------------------------------------------
# Samenstellen
# --------------------------------------------------------------------------


def koppel_herstelbaarheid(resultaten: list[ProbeResult]) -> None:
    """Een 'nu'-meting (bijv. realtime optieketens) is achteraf terug te halen als de bijbehorende
    historische meting (`herstelbaar_via`) lukte, en anders niet. Zo volgt de herstelbaarheid uit
    een meting en niet uit een aanname."""
    per_id = {r.id: r for r in resultaten}
    for r in resultaten:
        if not r.herstelbaar_via:
            continue
        via = per_id.get(r.herstelbaar_via)
        if via is None:
            continue
        r.hersteld_via_meting(HERSTELBAAR_JA if via.status == STATUS_OK else HERSTELBAAR_NEE)


def voer_uit(ctx: Context, categorieen: set[str] | None = None, zonder_av: bool = False) -> list[ProbeResult]:
    """Draait alle metingen. `categorieen` filtert op de categoriekolom; `zonder_av` slaat Alpha
    Vantage over (nul aanroepen). Alles wat niet gemeten kan worden staat er toch in, met reden."""
    resultaten: list[ProbeResult] = []
    if not zonder_av:
        resultaten += _av_probes(ctx)
    for series_id, categorie in FRED_KANDIDATEN:
        resultaten.append(probe_fred(ctx, series_id, categorie))
    resultaten.append(probe_alfred_vintages(ctx))
    resultaten += _openbare_probes(ctx)
    resultaten += _niet_geprobeerd()
    koppel_herstelbaarheid(resultaten)
    if categorieen:
        resultaten = [r for r in resultaten if r.categorie in categorieen]
    return resultaten


def samenvatting(resultaten: list[ProbeResult]) -> dict[str, int]:
    tel = {a: 0 for a in ALLE_ADVIEZEN}
    for r in resultaten:
        tel[r.advies] += 1
    return tel


def naar_dict(resultaten: list[ProbeResult]) -> list[dict]:
    return [asdict(r) for r in resultaten]
