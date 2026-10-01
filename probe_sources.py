#!/usr/bin/env python3
"""
probe_sources.py
Roadmap 1.2 en 1.4, fase A van `docs/data-archive.md` -- ALLEEN LEZEN. Meet kandidaatbronnen
voor het brede ruwe archief en geeft per bron een advies: archief nu, archief later, of een
beslissing voor DD. Zie `src/sources/probe.py` voor de volledige uitleg.

Het script slaat niets op en schrijft niets in de database. Alleen met `--json` wordt een
kopie van het rapport in een bestand gezet.

GEBRUIK OP DE VPS (in /opt/multi_agent):

    .venv/bin/python probe_sources.py                  # alles, ongeveer 4 minuten
    .venv/bin/python probe_sources.py --zonder-av      # geen Alpha Vantage-aanroepen
    .venv/bin/python probe_sources.py --alleen opties intraday
    .venv/bin/python probe_sources.py --json probe.json

NIET met `-v` of een debug-vlag draaien: urllib3 logt dan volledige url's, en daar staat de
API-key in. Het script zelf toont nooit een sleutel.

CALLVOLUME: ongeveer 15 Alpha Vantage-aanroepen (een seconde pauze, ruim onder de 75 per
minuut van het betaalde plan) en 50 tot 60 FRED-aanroepen. Draai het niet op dezelfde minuut
als de cron van 07:15.

EXIT CODES:
    0 -- het rapport is gemaakt (ook als sommige bronnen niet bereikbaar waren: dat is de meting)
    2 -- ongeldige argumenten
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from runtime.env import load_env_file  # noqa: E402
from sources import probe  # noqa: E402

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _kort(tekst, breedte: int) -> str:
    tekst = "-" if tekst is None else str(tekst)
    return tekst if len(tekst) <= breedte else tekst[: breedte - 1] + "…"


KOLOMMEN = (
    ("id", 26), ("categorie", 15), ("status", 16), ("kosten", 12), ("herstelb.", 9),
    ("laatste", 10), ("achter", 6), ("advies", 44),
)


def render(resultaten) -> str:
    regels = []
    kop = " ".join(naam.ljust(b) for naam, b in KOLOMMEN)
    regels.append(kop)
    regels.append("-" * len(kop))
    for r in resultaten:
        waarden = (r.id, r.categorie, r.status, r.kosten, r.herstelbaar, r.laatste,
                   "-" if r.achterstand_dagen is None else f"{r.achterstand_dagen}d", r.advies)
        regels.append(" ".join(_kort(w, b).ljust(b) for w, (_, b) in zip(waarden, KOLOMMEN)))
    regels.append("")
    regels.append("DETAILS (wat de bron zei, en de eenheid waar bekend)")
    for r in resultaten:
        extra = f" [eenheid: {r.eenheid}]" if r.eenheid else ""
        eerste = f" [vanaf {r.eerste}]" if r.eerste else ""
        regels.append(f"- {r.id}: {r.detail}{eerste}{extra}")
    regels.append("")
    regels.append("SAMENVATTING")
    for advies, aantal in probe.samenvatting(resultaten).items():
        regels.append(f"  {aantal:3d}  {advies}")
    return "\n".join(regels)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Meet kandidaatbronnen voor het brede ruwe archief (alleen lezen)")
    parser.add_argument("--zonder-av", action="store_true", help="sla Alpha Vantage over (nul aanroepen)")
    parser.add_argument("--alleen", nargs="+", metavar="CATEGORIE", help="toon alleen deze categorieën")
    parser.add_argument("--json", metavar="PAD", help="schrijf ook een kopie van het rapport als JSON")
    args = parser.parse_args(argv)

    load_env_file(ENV_PATH)
    ctx = probe.Context(
        av_key=os.environ.get("ALPHAVANTAGE_API_KEY") or None,
        fred_key=os.environ.get("FRED_API_KEY") or None,
    )
    resultaten = probe.voer_uit(ctx, categorieen=set(args.alleen) if args.alleen else None, zonder_av=args.zonder_av)

    print(render(resultaten))
    print(f"\nAanroepen: Alpha Vantage {ctx.aanroepen_av}, FRED {ctx.aanroepen_fred}.")
    if not ctx.av_key and not args.zonder_av:
        print("LET OP: geen ALPHAVANTAGE_API_KEY gevonden; de Alpha Vantage-rijen zijn 'niet geprobeerd'.")
    if not ctx.fred_key:
        print("LET OP: geen FRED_API_KEY gevonden; de FRED-rijen zijn 'niet geprobeerd'.")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(probe.naar_dict(resultaten), f, ensure_ascii=False, indent=2)
        print(f"JSON-kopie: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
