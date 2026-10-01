#!/usr/bin/env python3
"""
freeze_status.py
Het freeze-overzicht (CLAUDE.md checkpoint 5): alles wat bij de freeze vóór T₀ᵇ met versienummers bevestigd moet
worden, op één scherm, met per regel of het nog open staat. ALLEEN LEZEN, en het BEVRIEST NIETS.

    python freeze_status.py

De freeze zelf is een handeling van DD (zie `src/runtime/freeze_status.py`). Draai dit gerust elke week: het is ook
een voortgangsmeter richting T₀ᵇ.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from runtime.freeze_status import bepaal_punten, format_overzicht  # noqa: E402
from storage.schema import DEFAULT_DB_PATH  # noqa: E402


def main(argv=None) -> int:
    ouder = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ouder.add_argument("--db", default=os.environ.get("MI_DB_PATH", DEFAULT_DB_PATH))
    args = ouder.parse_args(argv)
    print(format_overzicht(bepaal_punten(args.db)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
