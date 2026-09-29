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

from calibration.trigger_calibration import calibrate_all, render_report  # noqa: E402
from runtime.env import load_env_file  # noqa: E402
from storage.schema import DEFAULT_DB_PATH, init_db  # noqa: E402

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
DOMAINS = ("monetary_policy", "currency", "financial", "sector", "commodity", "economic")


def main(argv: list[str] | None = None) -> int:
    load_env_file(ENV_PATH)
    parser = argparse.ArgumentParser(description="Trigger-kalibratierapport (roadmap 1.5) -- alleen lezen")
    parser.add_argument("--db", default=os.environ.get("MI_DB_PATH", DEFAULT_DB_PATH))
    parser.add_argument("--domain", choices=DOMAINS, default=None, help="beperk het rapport tot één domein")
    args = parser.parse_args(argv)

    try:
        conn = init_db(args.db)
    except (sqlite3.Error, OSError) as e:
        print(f"Database {args.db} kon niet geopend worden: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    try:
        resultaten = calibrate_all(conn, datetime.now(timezone.utc), domain=args.domain)
    finally:
        conn.close()

    print(f"Trigger-kalibratie -- {datetime.now(timezone.utc).date()} -- alleen lezen, wijzigt niets\n")
    print(render_report(resultaten))
    return 0


if __name__ == "__main__":
    sys.exit(main())
