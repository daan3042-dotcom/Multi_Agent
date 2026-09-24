"""
sector_agent.py
Stap C.3: sector-ETF's als eigen databron (bevestigd met DD) -- zelfde
opzet als B.1/B.2/C.2, maar met meerdere instrumenten onder ÉÉN plat
domain="sector" (zoals currency_agent.py's drie FX-paren, NIET zoals
equity_agent.py's per-ticker namespacing: elke sector-ETF heeft van nature
een unieke metric_key, dus geen collision-risico zoals bij tickers, die
allemaal dezelfde metric-namen delen).

Elf sector-ETF's (SPDR Select Sector SPDR's, de standaard GICS-uitgelijnde
taxonomie) -- bewust ALLE elf, niet een kleine selectie zoals bij de
FX-paren: het hele punt van een sector agent is brede dekking, en een
arbitraire keuze van "majeure" sectoren zou precies iets als Materials
(relevant voor DD's eigen koper-positie, ERO Copper) kunnen missen.

Data via Alpha Vantage GLOBAL_QUOTE (hergebruikt ALPHAVANTAGE_API_KEY,
zelfde als currency_agent.py -- geen nieuwe API-key nodig).

TRIGGER OP RUWE PRIJS, NIET OP RELATIEVE STERKTE (bewuste ontwerpkeuze):
de reguliere monitoring/delta-trigger volgt de ETF-prijs zelf (zelfde
mechanisme als elke andere agent hier), niet de relatieve-sterkte-waarde
-- dat laatste zou een "delta-van-een-delta" zijn (evaluate_surprise zou
dan een teruggerekende metric tegen zijn eigen vorige waarde vergelijken,
geen betekenisvolle vergelijking) en zou agents/base.py's gedeelde
trigger-machinery moeten uitbreiden, wat hier bewust niet gedaan is. In
plaats daarvan: een prijstrigger escaleert naar deep-dive mode, en PAS
DAAR wordt de relatieve sterkte t.o.v. SPY (S&P 500) berekend en als
citeerbare claim toegevoegd (analysis/relative_strength.py) -- exact het
"Python berekent een model, de LLM narrate het"-patroon van
financial_agent.py (NFCI) en monetary_policy_agent.py (Taylor Rule).

TOLERANCES: per-ETF, ruwweg gekalibreerd op ~3% van een typisch
prijsniveau PER ETF (ETF's hebben sterk verschillende prijsniveaus, een
uniforme dollartolerantie zou niet kloppen). Illustratieve plaatshouders
zoals overal (zie agents/base.py's docstring, docs/roadmap.md sectie H) --
met een EXTRA kanttekening t.o.v. andere agents: een vast dollarbedrag
veroudert sneller dan bijv. een rentepercentage, omdat ETF-prijsniveaus
over maanden/jaren kunnen wegdriften. Een percentage-gebaseerde tolerantie
zou robuuster zijn -- een goede kandidaat voor DD's eigen latere
finetuning (zie CLAUDE.md, "Werkwijze met DD").
"""

from __future__ import annotations

import os
from datetime import timedelta

import requests

from agents.base import MetricSpec, run_deep_dive, run_monitoring
from analysis.relative_strength import classify_relative_strength, compute_relative_strength_pct
from contract.output_contract import Claim, Confidence, now_utc

DOMAIN = "sector"
SOURCE_NAME = "ALPHA_VANTAGE_EQUITY"
BASE_URL = "https://www.alphavantage.co/query"
MAX_AGE = timedelta(days=5)  # dagelijkse slotkoersen; buffer voor een weekend + feestdag
BENCHMARK_SYMBOL = "SPY"  # S&P 500-proxy voor de relatieve-sterkte-berekening

SECTOR_ETFS = {
    "xlk_technology": "XLK",
    "xlf_financials": "XLF",
    "xle_energy": "XLE",
    "xlv_health_care": "XLV",
    "xly_consumer_discretionary": "XLY",
    "xlp_consumer_staples": "XLP",
    "xli_industrials": "XLI",
    "xlb_materials": "XLB",
    "xlu_utilities": "XLU",
    "xlre_real_estate": "XLRE",
    "xlc_communication_services": "XLC",
}

METRIC_SPECS = {
    "xlk_technology": MetricSpec(label="XLK (Technology)", tolerance=6.0, severity="medium"),
    "xlf_financials": MetricSpec(label="XLF (Financials)", tolerance=1.5, severity="medium"),
    "xle_energy": MetricSpec(label="XLE (Energy)", tolerance=3.0, severity="medium"),
    "xlv_health_care": MetricSpec(label="XLV (Health Care)", tolerance=4.0, severity="medium"),
    "xly_consumer_discretionary": MetricSpec(label="XLY (Consumer Discretionary)", tolerance=5.0, severity="medium"),
    "xlp_consumer_staples": MetricSpec(label="XLP (Consumer Staples)", tolerance=2.0, severity="medium"),
    "xli_industrials": MetricSpec(label="XLI (Industrials)", tolerance=4.0, severity="medium"),
    "xlb_materials": MetricSpec(label="XLB (Materials)", tolerance=2.5, severity="medium"),
    "xlu_utilities": MetricSpec(label="XLU (Utilities)", tolerance=2.0, severity="medium"),
    "xlre_real_estate": MetricSpec(label="XLRE (Real Estate)", tolerance=1.5, severity="medium"),
    "xlc_communication_services": MetricSpec(label="XLC (Communication Services)", tolerance=3.0, severity="medium"),
}

DEEP_DIVE_SYSTEM_PROMPT = """Je bent een analist gespecialiseerd in sector-rotatie binnen \
Amerikaanse aandelenmarkten (de 11 SPDR Select Sector-ETF's). Duid wat een significante \
prijsbeweging in een sector betekent -- alleen als de aangeleverde cijfers dat \
rechtvaardigen. Krijg je een claim met een relatieve-sterkte-classificatie aangeleverd \
(t.o.v. de S&P 500/SPY), gebruik die dan LETTERLIJK om te bepalen of dit sector-specifiek \
is (mogelijke rotatie) of onderdeel van een bredere marktbeweging -- schat dat niet zelf \
in, dat is al voor je berekend. (De algemene schrijfregels -- neutraliteit, alleen \
aangeleverde cijfers, onzekerheid expliciet -- staan al vóór dit stuk; dit is alleen de \
vakinhoudelijke aanvulling.)"""


def _fetch_quote(symbol: str, api_key: str) -> dict | None:
    """Zelfde aanpak als andere _fetch_*-helpers in deze codebase: None
    bij elke fout, geen gok. Geeft ook 'change_percent' mee (Alpha Vantage
    berekent dat al zelf) -- fetch_snapshot() gebruikt alleen 'value'/
    'date' (voor de reguliere prijstrigger), _fetch_change_percent()
    hieronder gebruikt 'change_percent' (voor de deep-dive-verrijking)."""
    try:
        resp = requests.get(
            BASE_URL, params={"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": api_key}, timeout=15,
        )
        resp.raise_for_status()
        quote = resp.json().get("Global Quote")
    except Exception:
        return None
    if not quote or not quote.get("05. price"):
        return None
    change_percent_raw = quote.get("10. change percent", "")
    try:
        change_percent = float(change_percent_raw.rstrip("%"))
    except (ValueError, AttributeError):
        change_percent = None
    return {
        "value": quote["05. price"],
        "date": quote.get("07. latest trading day", ""),
        "change_percent": change_percent,
    }


def fetch_snapshot() -> dict:
    """Haalt de meest recente slotkoers per sector-ETF op. {"error": ...}
    alleen als GEEN ENKELE ETF lukte."""
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        return {"error": "ALPHAVANTAGE_API_KEY niet gevonden in environment"}
    snapshot = {}
    for metric_key, symbol in SECTOR_ETFS.items():
        result = _fetch_quote(symbol, api_key)
        if result:
            snapshot[metric_key] = result
    if not snapshot:
        return {"error": "geen enkele sector-ETF kon worden opgehaald"}
    return snapshot


def monitor(conn, now=None):
    """Eén monitoring-cyclus: zie agents.base.run_monitoring voor het
    volledige gedrag (data-health, claims opslaan, delta-triggers)."""
    return run_monitoring(conn, DOMAIN, SOURCE_NAME, fetch_snapshot, METRIC_SPECS, MAX_AGE, now=now)


def _fetch_change_percent(symbol: str, api_key: str) -> float | None:
    """Alleen de day-change% voor een symbool (sector-ETF of de SPY-
    benchmark) -- gebruikt door deep_dive() voor de relatieve-sterkte-
    verrijking. None bij elke fout of ontbrekend veld, geen gok."""
    quote = _fetch_quote(symbol, api_key)
    if quote is None:
        return None
    return quote["change_percent"]


def deep_dive(conn, client, claims, trigger_events, now=None):
    """Deep-dive mode na een trigger. Voegt, voor elke sector-ETF-claim in
    `claims`, de relatieve sterkte t.o.v. SPY toe als extra claim (zie
    moduledocstring en analysis/relative_strength.py) -- puur Python, geen
    LLM-inschatting. SPY wordt maar ÉÉN keer opgehaald (niet per sector),
    ook als er meerdere sectoren tegelijk in `claims` zitten. Ontbreken de
    benodigde inputs (geen API-key, een netwerkfout), dan wordt de
    verrijking voor de betrokken sector(en) gewoon overgeslagen."""
    now = now or now_utc()
    enriched_claims = list(claims)
    sector_claims = [c for c in claims if c.metric_key in SECTOR_ETFS]
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")

    if sector_claims and api_key:
        benchmark_change_pct = _fetch_change_percent(BENCHMARK_SYMBOL, api_key)
        if benchmark_change_pct is not None:
            for sector_claim in sector_claims:
                symbol = SECTOR_ETFS[sector_claim.metric_key]
                sector_change_pct = _fetch_change_percent(symbol, api_key)
                if sector_change_pct is None:
                    continue
                relative_strength = compute_relative_strength_pct(sector_change_pct, benchmark_change_pct)
                enriched_claims.append(
                    Claim(
                        domain=DOMAIN,
                        claim=f"Relatieve sterkte {symbol} t.o.v. S&P 500",
                        value=classify_relative_strength(relative_strength),
                        source="Berekend (relatieve sterkte t.o.v. SPY)",
                        confidence=Confidence.HIGH,
                        analysis_time=now,
                        source_time=now,
                        note=(
                            f"{symbol} dagverandering={sector_change_pct:.2f}%, "
                            f"SPY dagverandering={benchmark_change_pct:.2f}%, "
                            f"verschil={relative_strength:.2f}pp"
                        ),
                    )
                )

    return run_deep_dive(conn, client, DOMAIN, DEEP_DIVE_SYSTEM_PROMPT, enriched_claims, trigger_events, now=now)
