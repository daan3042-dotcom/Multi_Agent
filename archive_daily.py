#!/usr/bin/env python3
"""
archive_daily.py
Roadmap 1.2/1.4, docs/data-archive.md fase B: het dagelijkse ruwe archief voor
data die niet terug te halen is. NU alleen de SPY-samenstelling.

EIGEN PROCES, EIGEN LOG, GEEN DATABASE. Dit draait los van `run_daily.py` en
raakt `market_intelligence.db` niet aan (zie `src/archive/spy_holdings.py`).
Een mislukte archieftaak mag T₀ᵃ nooit raken, en andersom.

    python archive_daily.py            # ophalen en bewaren
    python archive_daily.py --status   # alleen lezen: wat staat er, wat ontbreekt

Exitcode 0 = gelukt (ook "was vandaag al gearchiveerd"), 1 = mislukt, niets
weggeschreven. Zie docs/deployment.md voor de dry-run en de cron-regel.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from archive import spy_holdings  # noqa: E402

log = logging.getLogger("archive_daily")


def main(argv=None) -> int:
    ouder = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ouder.add_argument("--status", action="store_true", help="alleen het archief tonen, niets ophalen")
    args = ouder.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    basis = spy_holdings.archive_dir()
    if args.status:
        print(spy_holdings.status_rapport(basis))
        return 0
    try:
        r = spy_holdings.archiveer(basis=basis)
    except spy_holdings.ArchiveError as e:
        log.error("%s: NIET gearchiveerd: %s", spy_holdings.SOURCE, e)
        return 1
    if r.already_archived:
        log.info("%s: vandaag al gearchiveerd (%s), niets gedaan", r.source, r.path)
        return 0
    for w in r.warnings:
        log.warning("%s: %s", r.source, w)
    log.info(
        "%s: gearchiveerd %s (%d B -> %d B gzip, as_of=%s, identiek aan gisteren=%s)",
        r.source, r.path, r.bytes_raw, r.bytes_gz, r.as_of, r.same_as_previous,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
