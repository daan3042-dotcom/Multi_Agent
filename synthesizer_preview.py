#!/usr/bin/env python3
"""
synthesizer_preview.py
Wat de synthesizer (roadmap 4.5, slanke v1) bij zijn forecast-ronde te zien zou krijgen, en wat dat naar schatting kost.
ALLEEN LEZEN: de database gaat open met `mode=ro`, er is GEEN LLM-aanroep en er wordt niets opgeslagen.

    python synthesizer_preview.py                # groottes, schatting en het begin van de prompt
    python synthesizer_preview.py --volledig     # de hele prompt (lang!)

De schatting is ruw (3 tekens per token, ~55 tokens uitvoer per voorspelling); de begeleide testrun geeft de echte cijfers.
De synthesizer draait nog NIET mee in `run_daily`: dit is alleen een blik vooraf (CLAUDE.md, checkpoint 1 en 3).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from agents.base import DEFAULT_DEEP_DIVE_MODEL  # noqa: E402
from runtime.llm_budget import kosten_usd, max_maandbedrag  # noqa: E402
from storage.schema import DEFAULT_DB_PATH  # noqa: E402
from synthesizer import forecast as sf  # noqa: E402

TEKENS_PER_TOKEN = 3
UITVOER_TOKENS_PER_VOORSPELLING = 55
WEKEN_PER_MAAND = 4.35


def main(argv=None) -> int:
    ouder = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ouder.add_argument("--db", default=os.environ.get("MI_DB_PATH", DEFAULT_DB_PATH))
    ouder.add_argument("--volledig", action="store_true", help="toon de hele prompt")
    args = ouder.parse_args(argv)
    if not Path(args.db).exists():
        print(f"Database niet gevonden: {args.db}", file=sys.stderr)
        return 2

    nu = datetime.now(timezone.utc)
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        d = sf.doelen()
        claims = sf.laad_claims(conn)
        systeem, gebruiker = sf.bouw_prompt(conn, nu, claims=claims)
    finally:
        conn.close()

    voorspellingen = sum(len(t.horizons) for t in d.targets)
    n_in = (len(systeem) + len(gebruiker)) // TEKENS_PER_TOKEN
    n_uit = 100 + UITVOER_TOKENS_PER_VOORSPELLING * voorspellingen
    kosten, _ = kosten_usd(DEFAULT_DEEP_DIVE_MODEL, n_in, n_uit)
    grens = max_maandbedrag()
    print(f"SYNTHESIZER-VOORBLIK {nu:%Y-%m-%d %H:%M} UTC -- alleen lezen, geen LLM-aanroep, niets opgeslagen\n")
    print(f"  doelen                {len(d.targets)} reeksen, {voorspellingen} voorspellingen per ronde")
    print(f"  claims (alle domeinen) {len(claims)}")
    print(f"  prompt                {len(systeem):,} tekens systeem + {len(gebruiker):,} tekens gebruiker".replace(",", "."))
    print(f"  geschat per ronde     ~{n_in:,} tokens in, ~{n_uit:,} tokens uit, ~${kosten:.2f} ({DEFAULT_DEEP_DIVE_MODEL})".replace(",", "."))
    print(f"  geschat per maand     ~${kosten * WEKEN_PER_MAAND:.2f} bij één ronde per week, naast de domain agents (maandrem ${grens:.0f})")
    print(f"  prompt_version        synthesizer-{sf.FORECAST_PROMPT_VERSION}")
    print(f"  max_tokens antwoord   {sf.MAX_TOKENS:,}".replace(",", "."))
    if not claims:
        print("\nLET OP: geen enkele claim in de database; de prompt hieronder is leeg van cijfers.")
    print("\n" + "=" * 78 + "\nSYSTEEMPROMPT\n" + "=" * 78)
    print(systeem)
    print("\n" + "=" * 78 + "\nGEBRUIKERSPROMPT" + ("" if args.volledig else " (begin; --volledig voor alles)") + "\n" + "=" * 78)
    print(gebruiker if args.volledig else gebruiker[:3000] + ("\n[...]" if len(gebruiker) > 3000 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
