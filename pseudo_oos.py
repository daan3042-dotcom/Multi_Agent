#!/usr/bin/env python3
"""
pseudo_oos.py
Roadmap 4.4 (fase 3b): de pseudo-out-of-sample-run. Zie `src/scoring/pseudo_oos.py` voor het hele verhaal.

DRAAIT NOOIT OP DE ECHTE DATABASE. `voorbereiden` maakt een KOPIE met verschoven publicatiemomenten; alle andere
stappen weigeren een database zonder die voorbereiding. De echte database wordt alleen gelezen (`mode=ro`).

    python pseudo_oos.py voorbereiden --bron market_intelligence.db --doel pseudo_oos.db
    python pseudo_oos.py audit        --db pseudo_oos.db            # per reeks: laatste zichtbare waarneming per datum
    python pseudo_oos.py prompt       --db pseudo_oos.db --agent sector --datum 2026-07-06   # wat het model zou zien
    python pseudo_oos.py schatting    --db pseudo_oos.db            # ruwe kostenschatting uit echte promptlengtes
    python pseudo_oos.py draaien      --db pseudo_oos.db --ja       # KOST GELD; zonder --ja gebeurt er niets
    python pseudo_oos.py afwikkelen   --db pseudo_oos.db
    python pseudo_oos.py rapport      --db pseudo_oos.db
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from scoring import pseudo_oos as po  # noqa: E402

log = logging.getLogger("pseudo_oos")


def _db(pad: str) -> sqlite3.Connection:
    if not Path(pad).exists():
        raise po.PseudoOosFout(f"database niet gevonden: {pad}")
    return sqlite3.connect(pad)


def _model() -> str:
    from agents.base import DEFAULT_DEEP_DIVE_MODEL

    return DEFAULT_DEEP_DIVE_MODEL


def build_client(conn):
    """Echte client met de maandrem op de KOPIE. Alleen aangemaakt als er echt gedraaid wordt."""
    from anthropic import Anthropic

    from runtime.llm_budget import MeteredClient, max_maandbedrag

    echte = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=90.0, max_retries=2)
    return MeteredClient(echte, conn, max_maandbedrag())


def main(argv=None, client_fabriek=build_client, nu=None, uit=print) -> int:
    ouder = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ouder.add_subparsers(dest="stap", required=True)
    v = sub.add_parser("voorbereiden")
    v.add_argument("--bron", default=os.environ.get("MI_DB_PATH", "market_intelligence.db"))
    v.add_argument("--doel", required=True)
    for naam in ("audit", "prompt", "schatting", "draaien", "afwikkelen", "rapport"):
        p = sub.add_parser(naam)
        p.add_argument("--db", required=True)
    sub.choices["prompt"].add_argument("--agent", required=True)
    sub.choices["prompt"].add_argument("--datum", required=True, type=date.fromisoformat)
    sub.choices["draaien"].add_argument("--ja", action="store_true", help="bevestig dat dit geld mag kosten")
    sub.choices["draaien"].add_argument("--van", type=date.fromisoformat, default=po.VENSTER_VAN)
    sub.choices["draaien"].add_argument("--tot", type=date.fromisoformat, default=po.VENSTER_TOT)
    args = ouder.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from runtime.daily import default_agents

    agents = default_agents()
    try:
        if args.stap == "voorbereiden":
            r = po.bereid_voor(args.bron, args.doel, agents)
            uit(f"Kopie gemaakt: {r.doel}")
            uit(f"Publicatiemomenten verschoven voor {len(r.verschoven)} reeksen ({r.totaal_verschoven} claims):")
            for k, n in sorted(r.verschoven.items()):
                uit(f"  {k:<30} {n:>6} claims, +{po.vertraging_voor(k)} dagen")
            if r.niet_verschoven:
                uit("Eigen (live) claims, niet verschoven: " + ", ".join(f"{k}={n}" for k, n in sorted(r.niet_verschoven.items())))
            uit("Volgende stap: audit, dan prompt (eyeball), dan schatting. De echte database is niet gewijzigd.")
            return 0

        conn = _db(args.db)
        try:
            po._vereis_voorbereid(conn)
            datums = po.voorspeldata()
            if args.stap == "audit":
                uit("Laatste zichtbare waarneming per reeks op de eerste en de laatste datum van het venster:")
                for k in sorted(po.benodigde_reeksen(agents)):
                    regels = []
                    for d in (datums[0], datums[-1]):
                        h = po.zichtbare_geschiedenis(conn, k, d)
                        regels.append(f"{d.date()}: " + (f"{h[-1].source_time.date()} (n={len(h)})" if h else "GEEN DATA"))
                    uit(f"  {k:<30} " + "   ".join(regels))
                return 0
            if args.stap == "prompt":
                spec = next((a for a in agents if a.domain == args.agent and a.forecasts), None)
                if spec is None:
                    raise po.PseudoOosFout(f"onbekende of niet-voorspellende agent: {args.agent}")
                d = datetime.combine(args.datum, po.FORECAST_TIJD, tzinfo=timezone.utc)
                systeem, gebruiker = po.bouw_prompt(conn, spec, d)
                uit(f"=== SYSTEEMPROMPT ===\n{systeem}\n\n=== GEBRUIKERSPROMPT ({args.agent}, {args.datum}) ===\n{gebruiker}")
                return 0
            if args.stap == "schatting":
                s = po.schat_kosten(conn, agents, datums, _model())
                uit(f"{s.aanroepen} aanroepen, ~{s.input_tokens:,} tokens in, ~{s.output_tokens:,} tokens uit, "
                    f"ruwe schatting ${s.kosten_usd:.2f} ({s.model}). Een schatting, geen meting.".replace(",", "."))
                return 0
            if args.stap == "draaien":
                gekozen = [d for d in datums if args.van <= d.date() <= args.tot]
                po.controleer_fomc_kalender(gekozen)
                s = po.schat_kosten(conn, agents, gekozen, _model())
                uit(f"{len(gekozen)} datums, {s.aanroepen} aanroepen, ruwe schatting ${s.kosten_usd:.2f}.")
                if not args.ja:
                    uit("Dit was een droge run: er is niets aangeroepen. Voeg --ja toe om echt te draaien (kost geld).")
                    return 0
                client = client_fabriek(conn)
                resultaat = po.draai(conn, client, agents, gekozen)
                for r in resultaat:
                    uit(f"  {r.datum.date()} {r.domain:<22} {r.gekregen}/{r.verwacht}" + (f"  {len(r.issues)} probleem(en)" if r.issues else ""))
                return 0
            if args.stap == "afwikkelen":
                r = po.afwikkelen(conn, nu or datetime.now(timezone.utc))
                uit(r.summary())
                return 0
            if args.stap == "rapport":
                uit(f"{'agent':<18}{'gevraagd':>9}{'gekregen':>9}{'gemist':>8}{'afgewikkeld':>12}{'onafwikkelbaar':>15}")
                heroverwegen = False
                for a in po.rapport(conn, agents):
                    vlag = "  <- meer dan 5% gemist" if a.gemist_aandeel > po.MAX_AFGEWEZEN_AANDEEL else ""
                    heroverwegen |= bool(vlag)
                    uit(f"{a.domain:<18}{a.verwacht:>9}{a.gekregen:>9}{a.gemist_aandeel:>8.1%}{a.afgewikkeld:>12}{a.onafwikkelbaar:>15}{vlag}")
                if heroverwegen:
                    uit("Het contract (vijf kwantielen) heroverwegen bij meer dan 5% gemist; zie llm_calls voor het waarom.")
                return 0
        finally:
            conn.close()
    except po.PseudoOosFout as e:
        print(f"FOUT: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
