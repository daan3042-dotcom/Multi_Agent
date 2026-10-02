#!/usr/bin/env python3
"""
meet_spy_asof.py
ALLEEN LEZEN. Haalt het SPY-holdingsbestand op en print één regel: tijdstip, `as_of`, grootte, vingerafdruk en wat de
bron zelf over verversing zegt. Bewaart niets en raakt het archief, het manifest en de database niet aan.

    python meet_spy_asof.py

Doel: meten OP WELK MOMENT VAN DE DAG de bron een nieuwe `as_of` toont (docs/data-archive.md, 02-10-2026). `archive_daily.py`
kan dat niet, want dat archiveert maximaal één keer per UTC-dag. Exitcode 0 = regel met meting, 1 = mislukt (de regel zegt waarom).
Zie docs/deployment.md voor de (tijdelijke) cron-regel.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from archive.spy_meting import meet  # noqa: E402


def main(argv=None) -> int:
    regel, gelukt = meet()
    print(regel)
    return 0 if gelukt else 1


if __name__ == "__main__":
    sys.exit(main())
