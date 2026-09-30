#!/usr/bin/env python3
"""
run_daily.py
Roadmap 1.11 -- het bestand dat cron aanroept. Bewust dun: alle logica
zit in `src/runtime/daily.py`, hier staat alleen wat een entrypoint moet
doen (argumenten, database openen, exit code).

Gebruik op de VPS (zie docs/deployment.md voor de volledige inrichting):

    # elke werkdag om 07:15 UTC. `flock` voorkomt dat een trage run overlapt
    # met de volgende -- twee gelijktijdige runs komen allebei langs de
    # idempotency-check voordat een van beide zijn agent_run wegschrijft.
    # run_daily.sh laadt eerst .env (deze module leest environment-
    # variabelen, geen dotenv-dependency, zie run_daily.sh se eigen
    # commentaar) en start dan dit bestand.
    15 7 * * 1-5 /usr/bin/flock -n /tmp/mi-daily.lock /opt/multi_agent/run_daily.sh >> /var/log/mi/daily.log 2>&1

Zet ook logrotatie op `/var/log/mi/daily.log` -- die groeit anders
ongelimiteerd.

Vereiste environment-variabelen (zie .env.example):

    FRED_API_KEY            -- monetary_policy + financial + economic agent
    ALPHAVANTAGE_API_KEY    -- currency + sector + commodity agent
    MI_DB_PATH              -- pad naar de SQLite (default: ./market_intelligence.db)
    MI_COHORT               -- cohort voor nieuwe voorspellingen: dry_run (default),
                               pseudo_oos of cohort_0. ZET cohort_0 pas op T₀ᵇ.
    MI_WEBHOOK_URL          -- optioneel; zonder deze gaat een melding
                               ALLEEN naar de log, en een log op een VPS
                               die niemand leest is geen fail-loud.
                               Zie src/runtime/notifications.py.
    ANTHROPIC_API_KEY       -- alleen nodig met --deep-dives
    MI_MAX_MAANDBEDRAG_USD  -- maandgrens voor LLM-kosten (default 200), alleen met --deep-dives

Deep-dives staan standaard UIT. Monitoring is goedkoop en deterministisch;
deep-dives kosten geld per aanroep en draaien straks onbeheerd. Die kosten
horen een expliciete keuze te zijn, geen bijwerking van "de cron staat
aan". De triggers worden hoe dan ook opgeslagen, dus een later gedraaide
deep-dive mist niets.

EXIT CODES (cron/monitoring kan hierop sturen):
    0 -- cyclus voltooid, niets mis
    1 -- cyclus voltooid, maar minstens één agent faalde of crashte
    2 -- de cyclus zelf kon niet draaien (database onbereikbaar, onbekende MI_COHORT,
         MI_COHORT=cohort_0 met een trigger-regelset die niet bevroren is, of met
         --deep-dives een onleesbare MI_MAX_MAANDBEDRAG_USD / ontbrekende API-key)
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from contract.prediction import COHORT_0, current_cohort  # noqa: E402
from runtime.daily import daily_event_id, run_daily  # noqa: E402
from contract.trigger_version import TRIGGER_VERSION  # noqa: E402
from runtime.llm_budget import MeteredClient, max_maandbedrag  # noqa: E402
from runtime.notifications import log_notifier, webhook_notifier  # noqa: E402
from runtime.trigger_guard import TriggerPinError, check_trigger_pin  # noqa: E402
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


LLM_TIMEOUT_SECONDEN = 90.0
LLM_MAX_HERHALINGEN = 2
"""Time-out per LLM-aanroep. De SDK-standaard is 10 minuten per poging met twee
herhalingen: één hangende aanroep kon de run dan een half uur vasthouden, en
`flock` laat de run van de volgende dag dan overslaan. Een forecast- of
deep-dive-aanroep duurt normaal tientallen seconden; 90 is ruim, en na twee
herhalingen (elk met dezelfde grens) is het ergste geval een paar minuten."""


def build_client():
    """Alleen geladen als --deep-dives meegegeven is, zodat de dagelijkse
    monitoring-cyclus geen Anthropic-import of API-key nodig heeft.

    LET OP: zonder deze client draait óók de wekelijkse forecast-ronde niet
    (roadmap 2.0). Een dry-run zonder --deep-dives is dus een dry-run
    zonder voorspellingen -- dat is prima vóór T₀ᵇ, maar na T₀ᵇ is elke
    zo'n week een gat in het cohort."""
    from anthropic import Anthropic

    return Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=LLM_TIMEOUT_SECONDEN,
        max_retries=LLM_MAX_HERHALINGEN,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Dagelijkse monitoring-cyclus (roadmap 1.11)")
    parser.add_argument("--db", default=os.environ.get("MI_DB_PATH", DEFAULT_DB_PATH))
    parser.add_argument(
        "--deep-dives",
        action="store_true",
        help=(
            "draai ook de LLM-fasen: deep-dives voor geëscaleerde domeinen én "
            "de wekelijkse forecast-ronde op maandag (kost geld per aanroep). "
            "Vanaf T₀ᵇ is dit geen optie meer maar de meting zelf."
        ),
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

    # Het cohort VOOR er iets gebeurt, en hard falen bij een typefout. Een
    # onbekende MI_COHORT (`cohort0`) zou anders pas bij de eerste
    # voorspelling opvallen, midden in de wekelijkse ronde, en dan is een
    # week verloren. Exit 2 = de cyclus kon niet starten zoals bedoeld.
    try:
        cohort = current_cohort()
    except ValueError as e:
        log.critical("%s", e)
        return 2
    # Elke run zegt onder welk cohort hij voorspelt. Dit is de plek waar je op
    # T₀ᵇ ziet dat de schakelaar om is -- en waar je ziet dat hij NIET om is
    # als je hem vergeten bent.
    if cohort == COHORT_0:
        log.info("Cohort voor nieuwe voorspellingen: %s (ECHT COHORT -- telt mee in het track record)", cohort)
    else:
        log.info("Cohort voor nieuwe voorspellingen: %s (telt NIET mee; zet MI_COHORT=cohort_0 op T₀ᵇ)", cohort)

    # De regelset van de triggers (roadmap 1.5). Onder het echte cohort moet
    # die exact de bevroren versie zijn; een drempel die na de klokstart
    # verschuift start een nieuw cohort. Voor dry_run/pseudo_oos is alleen de
    # melding relevant: zo zie je in de log met welke regels er gedraaid is.
    try:
        check_trigger_pin(cohort)
    except TriggerPinError as e:
        log.critical("%s", e)
        return 2
    log.info("Trigger-versie: %s", TRIGGER_VERSION)

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
        if client is not None:
            # De maandrem (runtime/llm_budget.py): elke aanroep wordt vastgelegd
            # en de maandgrens (default $200) is een harde stop. Een onleesbare
            # MI_MAX_MAANDBEDRAG_USD stopt hier met exit 2, net als een onbekend cohort.
            client = MeteredClient(client, conn, max_maandbedrag())
    except Exception as e:  # noqa: BLE001
        # Ontbrekende ANTHROPIC_API_KEY of een niet-geïnstalleerde anthropic-
        # package. De cyclus zelf kon niet starten zoals gevraagd, dus exit
        # 2 en niet 1.
        conn.close()
        log.critical("Deep-dives gevraagd maar de client kon niet opgezet worden: %s: %s", type(e).__name__, e)
        return 2

    verbruik = None
    try:
        result = run_daily(conn, client=client, notifier=build_notifier(), event_id=event_id)
        # Vóór conn.close(): de samenvatting leest het maandverbruik uit de database.
        if isinstance(client, MeteredClient):
            verbruik = client.samenvatting()
    finally:
        conn.close()

    log.info(result.summary())
    if verbruik:
        log.info(verbruik)
    if result.health is not None:
        log.info("System health: %s", result.health.overall_status.value)
    if result.missed_days:
        log.warning("Dagen zonder succesvolle run: %s", ", ".join(result.missed_days))
    if result.forecast_results:
        aantal = sum(len(r.predictions) for r in result.forecast_results)
        log.info("Forecast-ronde: %d voorspellingen opgeslagen", aantal)
    if result.resolver is not None:
        log.info(result.resolver.summary())
        for fout in result.resolver.errors:
            log.error("Resolver-fout: %s", fout)
    if result.baseline_results:
        aantal = sum(len(r.predictions) for r in result.baseline_results)
        log.info("Baseline-ronde: %d voorspellingen opgeslagen", aantal)
    for probleem in result.baseline_issues:
        log.warning("Baseline-probleem: %s", probleem)
    for probleem in result.forecast_issues:
        # Niet stil: een onvolledige ronde is een gat in de meting, en de
        # ronde haalt zichzelf alleen in binnen dezelfde ISO-week.
        log.warning("Forecast-probleem: %s", probleem)

    return 1 if result.has_problems else 0


if __name__ == "__main__":
    sys.exit(main())
