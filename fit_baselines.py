#!/usr/bin/env python3
"""
fit_baselines.py
Roadmap 4.6 -- fit en BEVRIES de ridge-baseline (de derde baseline) op de
back-fill. Eenmalig, handmatig, op de VPS (daar staat de historie).

GEBRUIK OP DE VPS:

    # 1. Droog: fit alles en toon de diagnostiek. Schrijft NIETS.
    .venv/bin/python fit_baselines.py

    # 2. Pas als je tevreden bent: bevries.
    .venv/bin/python fit_baselines.py --freeze

WAAROM STANDAARD DROOG. Bevriezen is onomkeerbaar: de tabel
`baseline_models` kent geen update- of delete-pad, en een tweede fit onder
dezelfde specversie botst. "Gefit op de back-fill en daarna bevroren" is
precies wat de roadmap vraagt, en dat maakt dit een FREEZE-BESLISSING
(CLAUDE.md checkpoint 5): niet iets om per ongeluk uit te voeren.

WANNEER. Pas NA de volledige back-fill (ook de Alpha Vantage-helft, anders
hebben currency en sector te weinig historie en worden ze overgeslagen) en
VÓÓR T₀ᵇ. Een ridge die gefit is op een halve back-fill is een ridge die
je moet vervangen, en vervangen betekent een nieuwe RIDGE_SPEC_VERSION.

WAT JE IN DE UITVOER MOET BEKIJKEN:
  - `oos/rw`  De uit-de-steekproef-MSE gedeeld door die van "geen verandering".
              Het model kiest uit een raster dat "geen verandering" bevat, dus
              deze waarde kan niet meer ruim boven 1,000 uitkomen; staat er
              toch iets als 1,01 of hoger, dan is dat een bug: meld het en
              bevries niet. WAARDEN NET ONDER 1 (0,97-1,00) ZIJN GEEN BEWIJS
              VAN VOORSPELKRACHT: de cross-validatie kiest de toevallig beste
              uit 14 combinaties (winner's curse). Echte structuur zie je aan
              duidelijk lagere waarden, zoals VIX h=63 op 0,88.
  - `rijen`   Trainingsrijen. Ze overlappen (vensters van 21 of 63 dagen), dus
              de effectieve n is veel lager; kijk naar de orde van grootte.
  - `weggelaten` Inputs die uit het model zijn gelaten wegens te korte
              historie (minder dan 80% van de trainingsrijen). Zie de noot in
              docs/project-state.md: dat zijn ook reeksen die het LLM wél ziet.

EXIT CODES: 0 = alles gefit (en bij --freeze: bevroren), 1 = ten minste één
doel kon niet gefit worden, 2 = database niet te openen.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from contract.prediction import PredictionKind  # noqa: E402
from contract.resolution import ResolutionMethod  # noqa: E402
from runtime.daily import default_agents  # noqa: E402
from scoring.baselines import _Insufficient  # noqa: E402
from scoring.ridge import (  # noqa: E402
    RIDGE_NAME,
    RIDGE_SPEC_VERSION,
    fit_ridge_model,
    freeze_ridge_model,
)
from runtime.env import load_env_file  # noqa: E402
from storage.schema import DEFAULT_DB_PATH, init_db, load_baseline_model  # noqa: E402

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def main(argv: list[str] | None = None) -> int:
    # `.env` naast dit script inlezen als je het niet zelf hebt gesourced: zie
    # runtime/env.py. Bestaande omgevingsvariabelen winnen altijd.
    load_env_file(ENV_PATH)
    parser = argparse.ArgumentParser(description="Fit en bevries de ridge-baseline (roadmap 4.6)")
    parser.add_argument("--db", default=os.environ.get("MI_DB_PATH", DEFAULT_DB_PATH))
    parser.add_argument(
        "--freeze", action="store_true",
        help="schrijf de modellen weg. ONOMKEERBAAR (checkpoint 5). Zonder deze vlag alleen tonen.",
    )
    parser.add_argument(
        "--as-of", default=None,
        help="ISO-datum waarop gefit wordt (default: nu). Alleen data tot dan telt mee.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("fit_baselines")

    try:
        conn = init_db(args.db)
    except (sqlite3.Error, OSError) as e:
        log.critical("Database %s kon niet geopend worden: %s: %s", args.db, type(e).__name__, e)
        return 2

    now = datetime.now(timezone.utc)
    as_of = datetime.fromisoformat(args.as_of).astimezone(timezone.utc) if args.as_of else now

    print(f"ridge {RIDGE_SPEC_VERSION} -- as_of {as_of.date()} -- "
          f"{'BEVRIEZEN' if args.freeze else 'droog (schrijft niets)'}\n")
    print(f"{'domein':<16}{'doel':<28}{'h':>3} {'rijen':>6} {'lambda':>7} {'oos/rw':>7}  status")

    mislukt = 0
    for spec in default_agents():
        for target in spec.forecast_targets:
            if target.kind is not PredictionKind.QUANTILE:
                continue
            if target.resolution_method is ResolutionMethod.DIRECTION_AFTER_FOMC:
                continue
            for horizon_n in target.horizons:
                sleutel = f"{spec.domain:<16}{target.metric_key:<28}{horizon_n:>3}"
                if load_baseline_model(conn, RIDGE_NAME, RIDGE_SPEC_VERSION, spec.domain, target.metric_key, horizon_n):
                    print(f"{sleutel} {'':>6} {'':>7} {'':>7}  al bevroren, overgeslagen")
                    continue
                try:
                    fit = fit_ridge_model(conn, spec.domain, target, horizon_n, as_of)
                except _Insufficient as e:
                    mislukt += 1
                    print(f"{sleutel} {'':>6} {'':>7} {'':>7}  MISLUKT: {e}")
                    continue
                m = fit.model
                status = f"{len(m['features'])} inputs, {'met' if m['drift'] else 'zonder'} drift"
                if m["dropped"]:
                    status += f", weggelaten: {'; '.join(m['dropped'])}"
                if args.freeze:
                    freeze_ridge_model(conn, spec.domain, target, horizon_n, fit, now, as_of)
                    status += " -- BEVROREN"
                print(f"{sleutel} {m['n_rows']:>6} {m['lambda']:>7g} {fit.mse_oos / fit.mse_random_walk:>7.3f}  {status}")

    print()
    if mislukt:
        print(f"{mislukt} doel(en) niet gefit -- meestal een onvolledige back-fill. "
              f"Los dat op en draai opnieuw voordat je bevriest.")
    elif not args.freeze:
        print("Alles gefit. Tevreden? Draai opnieuw met --freeze.")
    conn.close()
    return 1 if mislukt else 0


if __name__ == "__main__":
    sys.exit(main())
