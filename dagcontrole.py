#!/usr/bin/env python3
"""
dagcontrole.py
De dagelijkse controle voor de begeleide weken en de dry-run-week (roadmap fase 3b, checkpoint 3). ALLEEN LEZEN.

    python dagcontrole.py                    # vandaag (UTC)
    python dagcontrole.py --dag 2026-10-05   # een eerdere dag

Eén scherm: run per agent, triggers, claims, bronnen, voorspellingen, LLM-verbruik, WARNING/ERROR-regels uit het log,
back-up, SPY-archief en schijf. De database gaat open met `mode=ro`; niets wordt gewijzigd. Netwerk alleen als je `--space` geeft
(een `rclone lsf` van de back-upmap, alleen een lijst). Wat niet te controleren is (bijvoorbeeld een ontbrekend logbestand) staat als ONBEKEND, niet als ok.
Uitleg en beperkingen: `src/runtime/dagcontrole.py`.

EXIT CODES: 0 = niets dat aandacht vraagt, 1 = minstens één LET OP of ONBEKEND, 2 = database niet gevonden.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from archive import spy_holdings  # noqa: E402
from runtime.dagcontrole import controleer_alles, format_controle, heeft_aandacht  # noqa: E402
from storage.schema import DEFAULT_DB_PATH  # noqa: E402

LOG_DIR = Path("/var/log/mi")


def main(argv=None) -> int:
    ouder = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ouder.add_argument("--db", default=os.environ.get("MI_DB_PATH", DEFAULT_DB_PATH))
    ouder.add_argument("--dag", type=date.fromisoformat, default=None, help="default: vandaag (UTC)")
    ouder.add_argument("--log", type=Path, default=LOG_DIR / "daily.log")
    ouder.add_argument("--backup-log", type=Path, default=LOG_DIR / "backup.log")
    ouder.add_argument("--archief", type=Path, default=None, help="default: de archiefmap van archive_daily.py")
    ouder.add_argument("--space", default=None, metavar="REMOTE:PAD",
                       help="controleer ook het nieuwste back-upbestand in de Space met `rclone lsf` (alleen een lijst), bijv. "
                            "do-spaces:mi-backups-multi-agent/backups/")
    args = ouder.parse_args(argv)

    if not Path(args.db).exists():
        print(f"Database niet gevonden: {args.db}", file=sys.stderr)
        return 2
    nu = datetime.now(timezone.utc)
    dag = args.dag or nu.date()
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        regels = controleer_alles(
            conn, dag, nu, log=args.log, backup_log=args.backup_log,
            archief=args.archief or spy_holdings.archive_dir(), space=args.space,
        )
    finally:
        conn.close()
    print(format_controle(dag, regels))
    return 1 if heeft_aandacht(regels) else 0


if __name__ == "__main__":
    sys.exit(main())
