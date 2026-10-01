#!/usr/bin/env python3
"""
t0a_status.py
Roadmap 1.11: de T₀ᵃ-teller. ALLEEN LEZEN (database `mode=ro`).

    python t0a_status.py                      # telling vanaf 2026-10-02
    python t0a_status.py --vanaf 2026-10-05   # na een eerdere breuk anders starten

Toont per werkdag of hij schoon was (alle agents ok en geen volledigheidstrigger),
de lopende reeks en de vroegste datum waarop T₀ᵃ gehaald is. Definitie en
beperkingen: `src/runtime/t0a_status.py`.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from runtime.t0a_status import STARTDATUM, bereken_stand, format_stand  # noqa: E402
from storage.schema import DEFAULT_DB_PATH  # noqa: E402


def main(argv=None) -> int:
    ouder = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ouder.add_argument("--db", default=os.environ.get("MI_DB_PATH", DEFAULT_DB_PATH))
    ouder.add_argument("--vanaf", type=date.fromisoformat, default=STARTDATUM)
    args = ouder.parse_args(argv)
    if not Path(args.db).exists():
        print(f"Database niet gevonden: {args.db}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        print(format_stand(bereken_stand(conn, start=args.vanaf)))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
