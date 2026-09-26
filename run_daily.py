#!/usr/bin/env python3
"""
run_daily.py
Roadmap 1.11 -- het bestand dat cron aanroept. Bewust dun: alle logica
zit in `src/runtime/daily.py`, hier staat alleen wat een entrypoint moet
doen (argumenten, database openen, exit code).

Gebruik op de VPS:

    # elke werkdag om 07:15 UTC. `flock` voorkomt dat een trage run overlapt
    # met de volgende -- twee gelijktijdige runs komen allebei langs de
    # idempotency-check voordat een van beide zijn agent_run wegschrijft.
    15 7 * * 1-5 /usr/bin/flock -n /tmp/mi-daily.lock /opt/multi_agent/.venv/bin/python /opt/multi_agent/run_daily.py >> /var/log/mi/daily.log 2>&1

Zet ook logrotatie op `/var/log/mi/daily.log` -- die groeit anders
ongelimiteerd.

Vereiste environment-variabelen:

    FRED_API_KEY            -- monetary_policy + financial agent
    ALPHAVANTAGE_API_KEY    -- currency + sector + commodity agent
    MI_DB_PATH              -- pad naar de SQLite (default: ./market_intelligence.db)
    MI_WEBHOOK_URL          -- optioneel; zonder deze gaat een melding
                               ALLEEN naar de log, en een log op een VPS
                               die niemand leest is geen fail-loud.
                               Zie src/runtime/notifications.py.
    ANTHROPIC_API_KEY       -- alleen nodig met --deep-dives

Deep-dives staan standaard UIT. Monitoring is goedkoop en deterministisch;
deep-dives kosten geld per aanroep en draaien straks onbeheerd. Die kosten
horen een expliciete keuze te zijn, geen bijwerking van "de cron staat
aan". De triggers worden hoe dan ook opgeslagen, dus een later gedraaide
deep-dive mist niets.

EXIT CODES (cron/monitoring kan hierop sturen):
    0 -- cyclus voltooid, niets mis
    1 -- cyclus voltooid, maar minstens één agent faalde of crashte
    2 -- de cyclus zelf kon niet draaien (database onbereikbaar e.d.)
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from runtime.daily import daily_event_id, run_daily  # noqa: E402
from runtime.notifications import log_notifier, webhook_notifier  # noqa: E402
from storage.schema import DEFAULT_DB_PATH, init_db  # noqa: E402


def build_notifier():
    """Webhook als er een URL is, anders de log. Geen stille default-keuze:
    zonder URL wordt er expliciet gewaarschuwd, want dan is de fail-loud-
    laag in de praktijk stil."""
    url = os.environ.get("MI_WEBHOOK_URL")
    if url:
        return webhook_notifier(url)
    logging.getLogger(__name__).warning(
        "MI_WEBHOOK_URL niet gezet -- meldingen gaan alleen naar de log. "
        "Op een onbeheerde machine betekent dat: niemand ziet ze."
    )
    return log_notifier


def build_client():
    """Alleen geladen als --deep-dives meegegeven is, zodat de dagelijkse
    monitoring-cyclus geen Anthropic-import of API-key nodig heeft."""
    from anthropic import Anthropic

    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Dagelijkse monitoring-cyclus (roadmap 1.11)")
    parser.add_argument("--db", default=os.environ.get("MI_DB_PATH", DEFAULT_DB_PATH))
    parser.add_argument(
        "--deep-dives",
        action="store_true",
        help="draai ook LLM-deep-dives voor geëscaleerde domeinen (kost geld per aanroep)",
    )
    parser.add_argument(
        "--event-id",
        default=None,
        help="overschrijf het event_id (default: daily:<UTC-datum>). Alleen voor handmatig herstel.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("run_daily")

    event_id = args.event_id or daily_event_id()

    try:
        conn = init_db(args.db)
    except (sqlite3.Error, OSError) as e:
        # OSError hoort hier expliciet bij: init_db() maakt de bovenliggende
        # map aan, dus een verkeerd MI_DB_PATH, een read-only mount of een
        # volle schijf komt hier langs. Zonder deze vangst zou dat een kale
        # traceback met exit 1 geven -- niet te onderscheiden van "één agent
        # faalde", terwijl er in werkelijkheid niets gedraaid heeft.
        log.critical("Database %s kon niet geopend worden: %s: %s", args.db, type(e).__name__, e)
        return 2

    try:
        client = build_client() if args.deep_dives else None
    except Exception as e:  # noqa: BLE001
        # Ontbrekende ANTHROPIC_API_KEY of een niet-geïnstalleerde anthropic-
        # package. De cyclus zelf kon niet starten zoals gevraagd, dus exit
        # 2 en niet 1.
        conn.close()
        log.critical("Deep-dives gevraagd maar de client kon niet opgezet worden: %s: %s", type(e).__name__, e)
        return 2

    try:
        result = run_daily(conn, client=client, notifier=build_notifier(), event_id=event_id)
    finally:
        conn.close()

    log.info(result.summary())
    if result.health is not None:
        log.info("System health: %s", result.health.overall_status.value)
    if result.missed_days:
        log.warning("Dagen zonder succesvolle run: %s", ", ".join(result.missed_days))

    return 1 if result.has_problems else 0


if __name__ == "__main__":
    sys.exit(main())
