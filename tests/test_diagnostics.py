"""
test_diagnostics.py
Kalibratie, AUC en effectieve n (roadmap 4.5): `scoring/diagnostics.py`,
`scoring/evaluation_report.py` en `evaluate_scores.py`. Geen netwerk, geen LLM.
"""

from __future__ import annotations

import importlib.util
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from contract.prediction import HorizonKind, Prediction, PredictionKind
from contract.resolution import ResolutionMethod
from scoring.diagnostics import (
    MIN_PERIODS,
    auc,
    effective_n,
    quantile_coverage,
    reliability_bins,
)
from scoring.evaluation_report import build_report, format_report
from storage.schema import init_db, save_prediction

START = datetime(2026, 11, 2, 7, 15, tzinfo=timezone.utc)  # maandag


# --------------------------------------------------------------------------
# Kalibratie
# --------------------------------------------------------------------------


def test_reliability_perfect_gekalibreerd_en_overmoedig():
    # 10 voorspellingen "0,7": 7 gebeurd = gekalibreerd; 3 gebeurd = overmoedig.
    goed = reliability_bins([0.7] * 10, [True] * 7 + [False] * 3)
    slecht = reliability_bins([0.7] * 10, [True] * 3 + [False] * 7)
    klasse = lambda b: next(x for x in b if x.n)
    assert klasse(goed).observed_frequency == pytest.approx(0.7)
    assert klasse(slecht).observed_frequency == pytest.approx(0.3)
    assert klasse(goed).mean_forecast == pytest.approx(0.7)


def test_reliability_lege_klasse_is_none_en_kans_een_valt_in_de_bovenste():
    bins = reliability_bins([1.0, 0.0], [True, False], n_bins=5)
    assert bins[-1].n == 1 and bins[0].n == 1
    assert bins[2].n == 0 and bins[2].observed_frequency is None  # nooit gezien is niet "gebeurde nooit"


def test_reliability_weigert_kans_buiten_bereik():
    with pytest.raises(ValueError):
        reliability_bins([1.2], [True])


def test_quantile_coverage_gekalibreerd_en_scheef():
    # 10 uitkomsten: 1 onder q10, 4 tot q50, 4 tot q90, 1 erboven.
    rijen = [(0, 5, 10, w) for w in (-1, 1, 2, 3, 4, 6, 7, 8, 9, 11)]
    c = quantile_coverage(rijen)
    assert (c.below_q10, c.q10_to_q50, c.q50_to_q90, c.above_q90) == (0.1, 0.4, 0.4, 0.1)
    # Een agent die steeds te laag zit: alles boven q90.
    assert quantile_coverage([(0, 5, 10, 50)] * 4).above_q90 == 1.0


def test_quantile_coverage_precies_op_een_kwantiel_telt_naar_binnen():
    c = quantile_coverage([(0, 5, 10, 0), (0, 5, 10, 10)])
    assert c.below_q10 == 0.0 and c.above_q90 == 0.0


def test_quantile_coverage_leeg_is_none():
    assert quantile_coverage([]) is None


# --------------------------------------------------------------------------
# AUC
# --------------------------------------------------------------------------


def test_auc_perfect_omgekeerd_en_gelijk():
    assert auc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == 1.0
    assert auc([0.1, 0.2, 0.8, 0.9], [True, True, False, False]) == 0.0
    assert auc([0.5, 0.5], [True, False]) == 0.5


def test_auc_van_een_agent_die_altijd_het_basispercentage_roept_is_een_half():
    """Het punt van AUC: perfect gekalibreerd en toch waardeloos."""
    uitkomsten = [True] * 3 + [False] * 7
    assert auc([0.3] * 10, uitkomsten) == 0.5
    wel_gekalibreerd = reliability_bins([0.3] * 10, uitkomsten)
    assert next(b for b in wel_gekalibreerd if b.n).observed_frequency == pytest.approx(0.3)


def test_auc_is_none_bij_een_enkele_soort_uitkomst():
    """Regressie: de Fed verhoogt zelden. Een verzonnen 0,5 zou 'geen vermogen'
    zeggen terwijl het 'nog niet te meten' is."""
    assert auc([0.2, 0.3], [False, False]) is None
    assert auc([], []) is None


# --------------------------------------------------------------------------
# Effectieve n
# --------------------------------------------------------------------------


def _rondes(waarden):
    return [(START + timedelta(weeks=i), w) for i, w in enumerate(waarden)]


def test_overlappende_horizonnen_geven_een_veel_lagere_effectieve_n_dan_onafhankelijke():
    """Het hele punt: 60 wekelijkse voorspellingen op 63 dagen overlappen negen
    weken. Een gladde reeks (zoals die overlap oplevert) hoort veel minder
    onafhankelijke waarnemingen te geven dan witte ruis."""
    rng = random.Random(7)
    ruis = [rng.gauss(0, 1) for _ in range(80)]
    glad = [sum(ruis[i : i + 9]) / 9 for i in range(60)]
    onafhankelijk = ruis[:60]

    gelijk = effective_n(_rondes(onafhankelijk), horizon_days=63)
    overlap = effective_n(_rondes(glad), horizon_days=63)

    assert gelijk.reliable and overlap.reliable
    assert overlap.n_nominal == gelijk.n_nominal == 60
    assert overlap.n_effective < 0.5 * gelijk.n_effective
    assert 1 <= overlap.n_effective <= overlap.n_nominal  # nooit boven nominaal


def test_effectieve_n_is_reproduceerbaar_en_heeft_een_band():
    rng = random.Random(3)
    reeks = _rondes([rng.gauss(0, 1) for _ in range(40)])
    a = effective_n(reeks, 21)
    b = effective_n(reeks, 21)
    assert a == b
    assert a.ci_low < a.mean < a.ci_high


def test_te_weinig_rondes_geeft_geen_getal_en_zegt_waarom():
    """Regressie op het bugpatroon 'stil een getal geven': met enkele rondes
    is een bootstrap betekenisloos, en de functie moet dat zeggen."""
    r = effective_n(_rondes([0.1, 0.2, 0.3]), horizon_days=63)
    assert r.n_effective is None and r.reliable is False
    assert "te weinig" in r.note
    assert MIN_PERIODS == 8


def test_horizon_langer_dan_de_helft_van_de_reeks_is_onbetrouwbaar():
    """Twee blokken van elk 9 rondes vragen minstens 18 rondes."""
    r = effective_n(_rondes([0.1 * (i % 3) for i in range(12)]), horizon_days=63)
    assert r.reliable is False


def test_scores_van_dezelfde_dag_zijn_een_cluster_en_geen_losse_trekkingen():
    # Drie doelen per ronde: nominaal 3x zoveel scores, maar evenveel rondes.
    scores = []
    for i in range(20):
        for w in (0.1, 0.2, 0.3):
            scores.append((START + timedelta(weeks=i), w))
    r = effective_n(scores, horizon_days=7)
    assert r.n_nominal == 60 and r.periods == 20


def test_constante_scores_geven_geen_deling_door_nul():
    r = effective_n(_rondes([0.5] * 30), horizon_days=14)
    assert r.reliable and r.n_effective == pytest.approx(r.n_nominal)


def test_horizon_nul_wordt_geweigerd():
    with pytest.raises(ValueError):
        effective_n(_rondes([1.0] * 10), horizon_days=0)


# --------------------------------------------------------------------------
# Rapport op de database
# --------------------------------------------------------------------------


def _voorspel_en_beoordeel(conn, *, agent, cohort, i, kind, realised, **kw):
    created = START + timedelta(weeks=i)
    basis = dict(
        agent=agent, domain="monetary_policy",
        target_metric_key="10y_treasury_yield" if kind == "quantile" else "fed_funds_target_upper",
        horizon_kind=HorizonKind.TRADING_DAYS if kind == "quantile" else HorizonKind.RELEASES,
        horizon_n=5 if kind == "quantile" else 1,
        created_at=created, resolves_at=created + timedelta(days=7),
        resolution_rule="regel", model_id="claude-x", prompt_version="v1", cohort=cohort,
    )
    if kind == "quantile":
        basis.update(kind=PredictionKind.QUANTILE, q10=3.9, q50=4.1, q90=4.4,
                     resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER)
    else:
        basis.update(kind=PredictionKind.BINARY, probability=kw.get("probability", 0.7), event_rule="hoger",
                     resolution_method=ResolutionMethod.DIRECTION_AFTER_FOMC)
    pid = save_prediction(conn, Prediction(**basis))
    conn.execute(
        "INSERT INTO evaluations (prediction_id, status, resolved_at, realised_value, realised_at, "
        "evidence_claim_ids_json, crps, brier, pinball_mean, scorer_version) "
        "VALUES (?, 'resolved', ?, ?, ?, '[]', ?, ?, ?, 'v1')",
        (pid, created.isoformat(), realised, created.isoformat(),
         kw.get("crps"), kw.get("brier"), kw.get("pinball")),
    )
    conn.commit()


def test_rapport_scheidt_cohorten_en_soorten(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    for i in range(10):
        _voorspel_en_beoordeel(conn, agent="monetary_policy", cohort="dry_run", i=i, kind="quantile",
                               realised=4.0, crps=0.1, pinball=0.05)
        _voorspel_en_beoordeel(conn, agent="monetary_policy", cohort="cohort_0", i=i, kind="quantile",
                               realised=4.0, crps=0.5, pinball=0.2)
        _voorspel_en_beoordeel(conn, agent="monetary_policy", cohort="dry_run", i=i, kind="binary",
                               realised=float(i % 2), brier=0.2, probability=0.7)
    groepen = {(g.cohort, g.kind): g for g in build_report(conn)}

    assert set(groepen) == {("dry_run", "quantile"), ("cohort_0", "quantile"), ("dry_run", "binary")}
    assert groepen[("dry_run", "quantile")].primary_score_mean == pytest.approx(0.1)  # niet gemengd met 0,5
    assert groepen[("cohort_0", "quantile")].primary_score_mean == pytest.approx(0.5)
    assert groepen[("dry_run", "binary")].primary_score_name == "brier"
    assert groepen[("dry_run", "binary")].n_positive == 5
    assert build_report(conn, cohort="cohort_0")[0].cohort == "cohort_0"
    assert len(build_report(conn, cohort="cohort_0")) == 1


def test_rapport_negeert_onafwikkelbare_voorspellingen(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _voorspel_en_beoordeel(conn, agent="a", cohort="dry_run", i=0, kind="quantile", realised=4.0, crps=0.1, pinball=0.1)
    conn.execute("UPDATE evaluations SET status='unresolvable', realised_value=NULL, realised_at=NULL, reason='x'")
    conn.commit()
    assert build_report(conn) == []


def test_tekst_zegt_eerlijk_dat_er_niets_te_rapporteren_valt_en_waarschuwt_bij_kleine_n(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    assert "Nog geen afgewikkelde" in format_report(build_report(conn))
    for i in range(3):
        _voorspel_en_beoordeel(conn, agent="a", cohort="dry_run", i=i, kind="quantile", realised=4.0, crps=0.1, pinball=0.1)
    tekst = format_report(build_report(conn))
    assert "NIET BETROUWBAAR" in tekst and "n.v.t." in tekst


def test_script_opent_de_database_alleen_lezen(tmp_path, capsys):
    pad = tmp_path / "t.db"
    conn = init_db(str(pad))
    _voorspel_en_beoordeel(conn, agent="a", cohort="dry_run", i=0, kind="quantile", realised=4.0, crps=0.1, pinball=0.1)
    conn.close()
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("evaluate_scores_cli", root / "evaluate_scores.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    voor = pad.read_bytes()
    assert cli.main(["--db", str(pad)]) == 0
    assert "KALIBRATIE" in capsys.readouterr().out
    assert pad.read_bytes() == voor  # niets gewijzigd
    assert cli.main(["--db", str(tmp_path / "bestaat_niet.db")]) == 1
