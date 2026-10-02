#!/usr/bin/env python3
"""
calibrate_triggers.py
Roadmap 1.5 ("Drempels kalibreren tegen de volledige historie") -- een RAPPORT over
hoe vaak elke triggerdrempel zou hebben gevuurd. Het wijzigt NIETS: geen drempel, geen
agent, niets in de database. Alleen lezen.

GEBRUIK OP DE VPS:

    .venv/bin/python calibrate_triggers.py                 # alle 40 reeksen
    .venv/bin/python calibrate_triggers.py --domain sector # één domein (korter om te plakken)

Zie `src/calibration/trigger_calibration.py` voor hoe er precies geteld wordt en waarom
er twee tellingen zijn (absoluut zoals het systeem, en gecorrigeerd voor het niveau).

WAAROM DIT VÓÓR T0b. Na T0b mag een drempel niet meer verschuiven zonder een nieuw cohort
te starten (CLAUDE.md). De huidige tolerances zijn illustratieve plaatshouders; dit is het
moment om ze met open ogen te vervangen.

EXIT CODES: 0 = rapport getoond, 2 = database niet te openen.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from calibration.atr_proef import atr_proef_alles, render_atr_rapport  # noqa: E402
from calibration.trigger_calibration import calibrate_all, render_report, render_split_vergelijking  # noqa: E402
from runtime.env import load_env_file  # noqa: E402
from storage.schema import DEFAULT_DB_PATH, init_db  # noqa: E402

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
DOMAINS = ("monetary_policy", "currency", "financial", "sector", "commodity", "economic")


def main(argv: list[str] | None = None) -> int:
    load_env_file(ENV_PATH)
    parser = argparse.ArgumentParser(description="Trigger-kalibratierapport (roadmap 1.5) -- alleen lezen")
    parser.add_argument("--db", default=os.environ.get("MI_DB_PATH", DEFAULT_DB_PATH))
    parser.add_argument("--domain", choices=DOMAINS, default=None, help="beperk het rapport tot één domein")
    parser.add_argument("--ongecorrigeerd", action="store_true",
                        help="rapport op de ruwe reeksen, zonder de correctie voor aandelensplitsingen (zoals de kalibratie van 29-09)")
    parser.add_argument("--vergelijk-splitsingen", action="store_true",
                        help="alleen de reeksen met een splitsing, ruw naast gecorrigeerd")
    parser.add_argument("--atr-proef", action="store_true",
                        help="proefrapport voor het volatiliteitsidee (roadmap 4.2): triggers per jaar bij N keer de gemiddelde beweging van 30 dagen")
    args = parser.parse_args(argv)

    try:
        conn = init_db(args.db)
    except (sqlite3.Error, OSError) as e:
        print(f"Database {args.db} kon niet geopend worden: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    try:
        nu = datetime.now(timezone.utc)
        if args.atr_proef:
            print(f"ATR-proef -- {nu.date()} -- alleen lezen, wijzigt niets\n")
            print(render_atr_rapport(atr_proef_alles(conn, nu, domain=args.domain)))
            return 0
        if args.vergelijk_splitsingen:
            ruw = calibrate_all(conn, nu, domain="sector", corrigeer_splitsingen=False)
            gecorrigeerd = calibrate_all(conn, nu, domain="sector", corrigeer_splitsingen=True)
            print(render_split_vergelijking(ruw, gecorrigeerd))
            return 0
        resultaten = calibrate_all(conn, nu, domain=args.domain, corrigeer_splitsingen=not args.ongecorrigeerd)
    finally:
        conn.close()

    print(f"Trigger-kalibratie -- {datetime.now(timezone.utc).date()} -- alleen lezen, wijzigt niets\n")
    print(render_report(resultaten))
    return 0


if __name__ == "__main__":
    sys.exit(main())
