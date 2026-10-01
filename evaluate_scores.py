#!/usr/bin/env python3
"""
evaluate_scores.py
Roadmap 4.5: kalibratie, AUC en effectieve n per agent, uit de afgewikkelde
voorspellingen. ALLEEN LEZEN -- schrijft niets in de database.

    python evaluate_scores.py                  # alle cohorten, apart getoond
    python evaluate_scores.py --cohort cohort_0

Zolang er geen voorspelling is afgewikkeld (de eerste horizon is 5
handelsdagen) zegt het script dat, en dat is geen fout.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from scoring.evaluation_report import build_report, format_report  # noqa: E402
from storage.schema import DEFAULT_DB_PATH  # noqa: E402


def main(argv=None) -> int:
    ouder = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ouder.add_argument("--db", default=os.environ.get("MI_DB_PATH", DEFAULT_DB_PATH))
    ouder.add_argument("--cohort", default=None, help="alleen dit cohort tonen")
    args = ouder.parse_args(argv)
    if not Path(args.db).exists():
        print(f"Database niet gevonden: {args.db}", file=sys.stderr)
        return 1
    # mode=ro: de database openen als alleen-lezen, zodat dit script hem niet
    # eens per ongeluk kan wijzigen.
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        print(format_report(build_report(conn, args.cohort)))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
