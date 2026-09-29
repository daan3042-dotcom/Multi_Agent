"""
test_cohort.py
Tests voor het cohort van nieuwe voorspellingen (roadmap 4.1, open beslissing
van 29-09): `contract/prediction.py::current_cohort` en `MI_COHORT`.

WAT HIER OP HET SPEL STAAT. `predictions` heeft bewust geen update-pad, dus
een verkeerd cohort-label is definitief. Voor 29-09 stond `cohort_0` als vaste
default: zodra de wekelijkse ronde op de VPS draaide, zouden de
voorspellingen van oktober als het ECHTE cohort zijn opgeslagen, vóór de
freeze van contract, prompts en drempels.

De tests hieronder bewaken dat de veilige kant de default is, dat één plek het
voor alle voorspellers beslist (agents, baselines, later mensen), en dat een
typefout hard faalt in plaats van een zwevend cohort te maken.
"""

from __future__ import annotations

import importlib.util
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agents.base import ForecastTarget, run_forecast_round
from contract.output_contract import Claim, Confidence, DomainOutput, Mode
from contract.prediction import (
    COHORT_0,
    DRY_RUN_COHORT,
    KNOWN_COHORTS,
    PSEUDO_OOS_COHORT,
    HorizonKind,
    Prediction,
    PredictionKind,
    current_cohort,
)
from contract.resolution import ResolutionMethod
from scoring.baseline_round import run_baseline_round
from storage.schema import init_db, list_predictions, save_domain_output

ROOT = Path(__file__).resolve().parent.parent
NU = datetime(2026, 10, 5, 7, 15, tzinfo=timezone.utc)
VRIJDAG = datetime(2026, 10, 2, tzinfo=timezone.utc)


def _prediction(**kw) -> Prediction:
    basis = dict(
        agent="monetary_policy", domain="monetary_policy",
        target_metric_key="10y_treasury_yield",
        kind=PredictionKind.QUANTILE,
        horizon_kind=HorizonKind.TRADING_DAYS, horizon_n=5,
        created_at=NU, resolves_at=NU + timedelta(days=7),
        resolution_rule="regel", resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER,
        model_id="m", prompt_version="p", q10=1.0, q50=2.0, q90=3.0,
    )
    basis.update(kw)
    return Prediction(**basis)


# --------------------------------------------------------------------------
# De functie zelf
# --------------------------------------------------------------------------


def test_zonder_mi_cohort_is_het_dry_run():
    """De veilige kant is de default. Niets zetten mag NOOIT het echte cohort
    opleveren."""
    assert current_cohort({}) == DRY_RUN_COHORT
    assert current_cohort({}) != COHORT_0


def test_lege_waarde_is_dry_run():
    """`MI_COHORT=` staat leeg in .env.example. Dat moet hetzelfde zijn als
    niet gezet, en geen fout."""
    assert current_cohort({"MI_COHORT": ""}) == DRY_RUN_COHORT
    assert current_cohort({"MI_COHORT": "   "}) == DRY_RUN_COHORT


def test_expliciet_aanzetten_van_het_echte_cohort_werkt():
    assert current_cohort({"MI_COHORT": "cohort_0"}) == COHORT_0
    assert current_cohort({"MI_COHORT": " cohort_0 "}) == COHORT_0  # spatie uit een .env-regel
    assert current_cohort({"MI_COHORT": "pseudo_oos"}) == PSEUDO_OOS_COHORT


@pytest.mark.parametrize("fout", ["cohort0", "Cohort_0", "cohort-0", "prod", "dryrun", "1"])
def test_typefout_faalt_hard_en_zegt_wat_wel_mag(fout):
    """Regressiegeval. Een stille terugval op de default zou 'cohort0' als
    dry_run wegschrijven -- en juist op T₀ᵇ, als je cohort_0 wílde, merk je
    dat pas weken later. Een fout die meteen stopt kost een uur."""
    with pytest.raises(ValueError) as e:
        current_cohort({"MI_COHORT": fout})
    for bekend in KNOWN_COHORTS:
        assert bekend in str(e.value)


def test_leest_de_echte_omgeving(monkeypatch):
    monkeypatch.setenv("MI_COHORT", "cohort_0")
    assert current_cohort() == COHORT_0
    monkeypatch.delenv("MI_COHORT")
    assert current_cohort() == DRY_RUN_COHORT


# --------------------------------------------------------------------------
# Eén plek voor alle voorspellers
# --------------------------------------------------------------------------


def test_prediction_volgt_de_omgeving_bij_aanmaken(monkeypatch):
    assert _prediction().cohort == DRY_RUN_COHORT
    monkeypatch.setenv("MI_COHORT", "cohort_0")
    assert _prediction().cohort == COHORT_0


def test_expliciet_cohort_wint_van_de_omgeving(monkeypatch):
    """De pseudo-OOS-run (4.4) geeft zijn cohort zelf mee en mag niet van
    de omgeving van de VPS afhangen."""
    monkeypatch.setenv("MI_COHORT", "cohort_0")
    assert _prediction(cohort="pseudo_oos").cohort == "pseudo_oos"


def test_onbekend_expliciet_cohort_wordt_geweigerd():
    with pytest.raises(ValueError, match="onbekend cohort"):
        _prediction(cohort="cohort0")


def test_teruglezen_raadpleegt_de_omgeving_niet(tmp_path, monkeypatch):
    """Het cohort van een opgeslagen voorspelling staat vast. Een
    `MI_COHORT`-wijziging op T₀ᵇ mag de oude rijen niet van label
    veranderen, en de default_factory mag bij het teruglezen niet meedoen."""
    from storage.schema import save_prediction

    conn = init_db(str(tmp_path / "t.db"))
    save_prediction(conn, _prediction())  # dry_run
    monkeypatch.setenv("MI_COHORT", "cohort_0")

    (teruggelezen,) = list_predictions(conn)

    assert teruggelezen.cohort == DRY_RUN_COHORT


# --------------------------------------------------------------------------
# De echte paden: agents en baselines
# --------------------------------------------------------------------------


def _client(tekst):
    client = MagicMock()
    blok = MagicMock()
    blok.type = "text"
    blok.text = tekst
    client.messages.create.return_value = MagicMock(content=[blok])
    return client


_DOEL = ForecastTarget(
    metric_key="x", kind=PredictionKind.QUANTILE, horizon_kind=HorizonKind.TRADING_DAYS,
    horizons=(5,), resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER,
    resolution_rule="x op of na resolves_at ({horizon_n} handelsdagen)",
)
_ANTWOORD = '{"forecasts": [{"metric_key": "x", "horizon_n": 5, "q10": 1.0, "q50": 2.0, "q90": 3.0}]}'


def _historie(conn):
    claims = []
    for i in range(80):
        dag = VRIJDAG - timedelta(days=79 - i)
        claims.append(Claim(
            domain="d", claim="x", value=100.0 + ((i * 7) % 11), source="test",
            confidence=Confidence.HIGH, analysis_time=dag, source_time=dag, metric_key="x",
        ))
    save_domain_output(conn, DomainOutput(
        domain="d", mode=Mode.MONITORING, generated_at=claims[0].analysis_time, claims=claims,
    ))


def test_llm_forecast_ronde_schrijft_onder_dry_run_zonder_configuratie(tmp_path):
    """HET PUNT VAN DE HELE WIJZIGING: de ronde die op de VPS draait, zonder
    dat iemand iets heeft ingesteld, levert geen cohort_0 op."""
    conn = init_db(str(tmp_path / "t.db"))

    run_forecast_round(conn, _client(_ANTWOORD), "d", "prompt", [_DOEL], [], prompt_version="d-v1", now=NU)

    assert {p.cohort for p in list_predictions(conn)} == {DRY_RUN_COHORT}


def test_llm_forecast_ronde_volgt_mi_cohort(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    monkeypatch.setenv("MI_COHORT", "cohort_0")

    run_forecast_round(conn, _client(_ANTWOORD), "d", "prompt", [_DOEL], [], prompt_version="d-v1", now=NU)

    assert {p.cohort for p in list_predictions(conn)} == {COHORT_0}


def test_baselines_volgen_hetzelfde_cohort_als_de_agents(tmp_path, monkeypatch):
    """Agent en baseline moeten in HETZELFDE cohort staan, anders is er
    niets om ze mee te vergelijken. Eén plek (current_cohort) beslist voor
    beide, en deze test bewaakt dat er geen tweede plek bij komt."""
    conn = init_db(str(tmp_path / "t.db"))
    _historie(conn)

    run_baseline_round(conn, "d", [_DOEL], NU, event_id="2026-W41", ridge=False)
    onder_dry_run = {p.cohort for p in list_predictions(conn)}

    monkeypatch.setenv("MI_COHORT", "cohort_0")
    run_baseline_round(conn, "d", [_DOEL], NU + timedelta(days=7), event_id="2026-W42", ridge=False)
    alles = {(p.created_at.day, p.cohort) for p in list_predictions(conn)}

    assert onder_dry_run == {DRY_RUN_COHORT}
    assert alles == {(5, DRY_RUN_COHORT), (12, COHORT_0)}


def test_dry_run_voorspellingen_worden_wel_afgewikkeld(tmp_path):
    """Dry-run is geen weggooien: de resolver en de scores moeten in de
    dry-run-week al bewezen worden (dat is er de bedoeling van). Alleen het
    LABEL scheidt ze van het echte cohort."""
    from scoring.resolver import resolve_due_predictions

    conn = init_db(str(tmp_path / "t.db"))
    _historie(conn)
    run_baseline_round(conn, "d", [_DOEL], NU, event_id="2026-W41", ridge=False)
    claims = [Claim(
        domain="d", claim="x", value=101.0, source="test", confidence=Confidence.HIGH,
        analysis_time=NU + timedelta(days=8), source_time=NU + timedelta(days=8), metric_key="x",
    )]
    save_domain_output(conn, DomainOutput(
        domain="d", mode=Mode.MONITORING, generated_at=claims[0].analysis_time, claims=claims,
    ))

    resultaat = resolve_due_predictions(conn, now=NU + timedelta(days=9))

    assert resultaat.resolved == 2


# --------------------------------------------------------------------------
# run_daily.py: valideren en zichtbaar maken
# --------------------------------------------------------------------------


def _run_daily_main():
    spec = importlib.util.spec_from_file_location("run_daily_cli", ROOT / "run_daily.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def test_typefout_in_mi_cohort_stopt_run_daily_met_exit_twee(tmp_path, monkeypatch):
    """Voor er iets gebeurt: geen database geopend, geen agent gedraaid."""
    monkeypatch.setenv("MI_COHORT", "cohort0")
    pad = tmp_path / "t.db"

    assert _run_daily_main()(["--db", str(pad)]) == 2

    assert not pad.exists(), "de database mag niet eens aangemaakt zijn"


def test_run_daily_meldt_het_cohort_in_het_log(tmp_path, monkeypatch, caplog):
    """Op T₀ᵇ moet je in daily.log kunnen zien dat de schakelaar om is -- en
    dat hij NIET om is als je hem vergeten bent."""
    import runtime.daily as daily

    monkeypatch.setattr(daily, "default_agents", lambda: [])
    caplog.set_level(logging.INFO)

    _run_daily_main()(["--db", str(tmp_path / "t.db")])
    assert "Cohort voor nieuwe voorspellingen: dry_run" in caplog.text
    assert "telt NIET mee" in caplog.text

    caplog.clear()
    monkeypatch.setenv("MI_COHORT", "cohort_0")
    _run_daily_main()(["--db", str(tmp_path / "t2.db")])
    assert "ECHT COHORT" in caplog.text
