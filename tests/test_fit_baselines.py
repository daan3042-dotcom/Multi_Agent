"""
test_fit_baselines.py
Tests voor `fit_baselines.py` (roadmap 4.6): de CLI die de ridge-baseline
fit en bevriest.

WAT HIER BEWAAKT WORDT: dat de veilige stand ook echt veilig is. Bevriezen is
onomkeerbaar (checkpoint 5), dus 'droog' mag NIETS wegschrijven, en een
tweede run mag niet botsen op wat al bevroren is.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from contract.output_contract import Claim, Confidence, DomainOutput, Mode
from scoring.ridge import RIDGE_NAME, RIDGE_SPEC_VERSION
from storage.schema import count_baseline_models, init_db, save_domain_output

ROOT = Path(__file__).resolve().parent.parent
VRIJDAG = datetime(2026, 10, 2, tzinfo=timezone.utc)
AS_OF = "2026-10-05T07:15:00+00:00"


def _cli():
    spec = importlib.util.spec_from_file_location("fit_baselines", ROOT / "fit_baselines.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(pad):
    """Alleen het monetary-domein, twee doelen (DGS10 en DGS2), 600 dagen.
    De andere domeinen blijven leeg -- dat is bewust, zie de exit-code-test."""
    conn = init_db(pad)
    rng = random.Random(5)
    for key in ("10y_treasury_yield", "2y_treasury_yield"):
        waarde, claims = 4.0, []
        for i in range(600):
            waarde += rng.gauss(0, 0.05)
            dag = VRIJDAG - timedelta(days=599 - i)
            claims.append(Claim(
                domain="monetary_policy", claim=key, value=waarde, source="test",
                confidence=Confidence.HIGH, analysis_time=dag, source_time=dag, metric_key=key,
            ))
        save_domain_output(conn, DomainOutput(
            domain="monetary_policy", mode=Mode.MONITORING,
            generated_at=claims[0].analysis_time, claims=claims,
        ))
    return conn


def _aantal(pad):
    conn = init_db(pad)
    n = count_baseline_models(conn, RIDGE_NAME, RIDGE_SPEC_VERSION, "monetary_policy")
    conn.close()
    return n


def test_droog_schrijft_niets_weg(tmp_path, capsys):
    pad = str(tmp_path / "t.db")
    _seed(pad).close()

    _cli().main(["--db", pad, "--as-of", AS_OF])

    assert _aantal(pad) == 0
    uitvoer = capsys.readouterr().out
    assert "droog (schrijft niets)" in uitvoer
    assert "BEVROREN" not in uitvoer


def test_freeze_bevriest_wat_te_fitten_valt(tmp_path):
    """DGS10 en DGS2 x horizonnen 5/21/63 = 6 modellen."""
    pad = str(tmp_path / "t.db")
    _seed(pad).close()

    _cli().main(["--db", pad, "--as-of", AS_OF, "--freeze"])

    assert _aantal(pad) == 6


def test_tweede_freeze_botst_niet_en_wijzigt_niets(tmp_path, capsys):
    """Idempotent: wat al bevroren is wordt overgeslagen met een melding, in
    plaats van te crashen op de UNIQUE-constraint of stil te overschrijven."""
    pad = str(tmp_path / "t.db")
    _seed(pad).close()
    cli = _cli()
    cli.main(["--db", pad, "--as-of", AS_OF, "--freeze"])
    capsys.readouterr()

    cli.main(["--db", pad, "--as-of", AS_OF, "--freeze"])

    assert _aantal(pad) == 6
    assert "al bevroren, overgeslagen" in capsys.readouterr().out


def test_exitcode_is_een_als_er_doelen_niet_te_fitten_zijn(tmp_path):
    """De andere vier domeinen hebben hier geen historie. Dat is een
    onvolledige back-fill, en de exit-code moet dat zeggen -- niet stil 0."""
    pad = str(tmp_path / "t.db")
    _seed(pad).close()
    assert _cli().main(["--db", pad, "--as-of", AS_OF]) == 1


def test_onbereikbare_database_geeft_exitcode_twee(tmp_path):
    assert _cli().main(["--db", "/proc/geen/toegang/t.db"]) == 2
