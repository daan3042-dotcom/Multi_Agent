#!/usr/bin/env python3
"""
backfill.py
Roadmap 1.11, fase 0b-1 -- eenmalig, handmatig te draaien entrypoint voor
de historische back-fill. Zie `src/runtime/backfill.py` voor de volledige
uitleg (waarom andere AV-endpoints dan de dagelijkse cyclus, waarom
`generated_at` op de oudste datum staat, waarom er geen dedup is).

GEBRUIK OP DE VPS:

    # FRED-domeinen (monetary_policy, financial, economic): goedkoop, geen
    # quota-zorgen, kan los van alles.
    .venv/bin/python backfill.py --domain monetary_policy --domain financial --domain economic

    # Alpha Vantage-domeinen (currency, sector, commodity): 24 calls samen,
    # exact tegen de dagelijkse quota-limiet -- NIET dezelfde dag als de
    # reguliere cron-cyclus zonder een hogere AV-tier. Zie docs/data-sources.md.
    .venv/bin/python backfill.py --domain currency --domain sector --domain commodity

    # Alles in één keer (alleen doen met een tier die de AV-belasting aankan):
    .venv/bin/python backfill.py

BELANGRIJK: dit script heeft GEEN dedup. Twee keer draaien voor hetzelfde
domein voegt twee keer dezelfde historische claims toe. Alleen bedoeld om
één keer per domein gedraaid te worden.

Vereiste environment-variabelen: FRED_API_KEY (voor monetary_policy/
financial/economic), ALPHAVANTAGE_API_KEY (voor currency/sector/commodity).

EXIT CODES:
    0 -- elk gevraagd domein leverde minstens één claim op
    1 -- minstens één domein leverde niets op (mislukte fetch, of geen data)
    2 -- de database kon niet geopend worden, of een vereiste API-key ontbreekt
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from runtime import backfill  # noqa: E402
from storage.schema import DEFAULT_DB_PATH, init_db  # noqa: E402

FRED_DOMAINS = ("monetary_policy", "financial", "economic")
AV_DOMAINS = ("currency", "sector", "commodity")
ALL_DOMAINS = FRED_DOMAINS + AV_DOMAINS


def _backfill_one_domain(conn, domain: str, fred_api_key: str | None, av_api_key: str | None) -> int:
    """Importeert de bijbehorende agent-module PAS hier (zelfde reden als
    runtime/daily.py::default_agents(): geen requests-import/env-lookup
    nodig voor een domein dat niet gevraagd is)."""
    if domain == "monetary_policy":
        from agents import monetary_policy_agent as m

        return backfill.backfill_fred_domain(conn, m.DOMAIN, m.SOURCE_KEY, m.FRED_SERIES, m.METRIC_SPECS, fred_api_key)
    if domain == "financial":
        from agents import financial_agent as m

        return backfill.backfill_fred_domain(conn, m.DOMAIN, m.SOURCE_KEY, m.FRED_SERIES, m.METRIC_SPECS, fred_api_key)
    if domain == "economic":
        from agents import economic_agent as m

        return backfill.backfill_fred_domain(conn, m.DOMAIN, m.SOURCE_KEY, m.FRED_SERIES, m.METRIC_SPECS, fred_api_key)
    if domain == "currency":
        from agents import currency_agent as m

        return backfill.backfill_currency(conn, m.DOMAIN, m.SOURCE_KEY, m.FX_PAIRS, m.METRIC_SPECS, av_api_key)
    if domain == "sector":
        from agents import sector_agent as m

        return backfill.backfill_sector(conn, m.DOMAIN, m.SOURCE_KEY, m.SECTOR_ETFS, m.METRIC_SPECS, av_api_key)
    if domain == "commodity":
        from agents import commodity_agent as m

        return backfill.backfill_commodity(conn, m.DOMAIN, m.SOURCE_KEY, m.COMMODITIES, m.METRIC_SPECS, av_api_key)
    raise ValueError(f"onbekend domein: {domain!r}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Eenmalige historische back-fill (roadmap 1.11, 0b-1)")
    parser.add_argument("--db", default=os.environ.get("MI_DB_PATH", DEFAULT_DB_PATH))
    parser.add_argument(
        "--domain", action="append", choices=ALL_DOMAINS, default=None,
        help="meerdere keren op te geven; default (niets meegeven) = alle zes domeinen",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("backfill")

    domains = args.domain or list(ALL_DOMAINS)
    requested_av = [d for d in domains if d in AV_DOMAINS]
    if requested_av:
        av_call_estimate = sum({"currency": 3, "sector": 11, "commodity": 10}[d] for d in requested_av)
        log.warning(
            "Alpha Vantage-domeinen gevraagd (%s): dit kost naar schatting %d calls, "
            "exact tegen de dagelijkse quota-limiet aan als je de gratis tier gebruikt -- "
            "zie docs/data-sources.md. Niet combineren met de reguliere cron op dezelfde dag "
            "zonder een hogere tier.",
            ", ".join(requested_av), av_call_estimate,
        )

    fred_api_key = os.environ.get("FRED_API_KEY")
    av_api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if any(d in FRED_DOMAINS for d in domains) and not fred_api_key:
        log.critical("FRED_API_KEY niet gevonden in environment, nodig voor: %s", ", ".join(FRED_DOMAINS))
        return 2
    if requested_av and not av_api_key:
        log.critical("ALPHAVANTAGE_API_KEY niet gevonden in environment, nodig voor: %s", ", ".join(AV_DOMAINS))
        return 2

    try:
        conn = init_db(args.db)
    except (sqlite3.Error, OSError) as e:
        log.critical("Database %s kon niet geopend worden: %s: %s", args.db, type(e).__name__, e)
        return 2

    had_empty_domain = False
    try:
        for domain in domains:
            count = _backfill_one_domain(conn, domain, fred_api_key, av_api_key)
            if count == 0:
                had_empty_domain = True
                log.warning("%s: geen enkele claim opgehaald/opgeslagen", domain)
            else:
                log.info("%s: %d historische claims opgeslagen", domain, count)
    finally:
        conn.close()

    return 1 if had_empty_domain else 0


if __name__ == "__main__":
    sys.exit(main())
