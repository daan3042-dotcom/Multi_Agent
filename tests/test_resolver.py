"""
test_resolver.py
Tests voor de resolver (roadmap 4.5), `src/scoring/resolver.py` -- van
opgeslagen claims naar een evaluation-rij met scores.

Waar `test_resolution.py` de rekenregels test, test dit bestand het GEDRAG
eromheen: wat er gebeurt bij ontbrekende data, bij een bug, bij twee runs
op dezelfde dag, en of de uitkomst onherroepelijk wordt vastgelegd.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from contract.output_contract import Claim, Confidence, DomainOutput, Mode
from contract.prediction import HorizonKind, Prediction, PredictionKind
from contract import resolution
from contract.resolution import ResolutionMethod
from scoring.resolver import MAX_WACHTTIJD, resolve_due_predictions
from scoring.scores import SCORER_VERSION
from storage.schema import (
    init_db,
    list_evaluations,
    list_unevaluated_due_predictions,
    save_domain_output,
    save_prediction,
)

NU = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
STRAKS = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
NA_AFLOOP = datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc)


def _db(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def _claim(conn, metric_key, dag, waarde, gezien_dag=None, domain="monetary_policy"):
    """Slaat één waarneming op zoals de monitoring dat doet: source_time is
    de periode van de bron, analysis_time is wanneer wij hem zagen."""
    gezien = datetime(2026, 10, gezien_dag if gezien_dag is not None else dag, 7, 0, tzinfo=timezone.utc)
    save_domain_output(
        conn,
        DomainOutput(
            domain=domain, mode=Mode.MONITORING, generated_at=gezien,
            claims=[
                Claim(
                    domain=domain, claim=metric_key, value=waarde, source="test",
                    confidence=Confidence.HIGH, analysis_time=gezien,
                    source_time=datetime(2026, 10, dag, tzinfo=timezone.utc),
                    metric_key=metric_key,
                )
            ],
        ),
    )


def _kwantiel(**overrides) -> Prediction:
    basis = dict(
        agent="monetary_policy", domain="monetary_policy",
        target_metric_key="10y_treasury_yield",
        kind=PredictionKind.QUANTILE,
        horizon_kind=HorizonKind.TRADING_DAYS, horizon_n=21,
        created_at=NU, resolves_at=STRAKS,
        resolution_rule="DGS10 eerste print op of na resolves_at",
        resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER,
        model_id="claude-x", prompt_version="mp-v1",
        q10=3.9, q50=4.1, q90=4.4,
    )
    basis.update(overrides)
    return Prediction(**basis)


# --------------------------------------------------------------------------
# De gelukkige weg
# --------------------------------------------------------------------------


def test_afgelopen_voorspelling_wordt_afgewikkeld_en_gescoord(tmp_path):
    conn = _db(tmp_path)
    _claim(conn, "10y_treasury_yield", 1, 4.00)
    _claim(conn, "10y_treasury_yield", 22, 4.20)
    save_prediction(conn, _kwantiel())

    resultaat = resolve_due_predictions(conn, now=NA_AFLOOP)

    assert resultaat.resolved == 1
    assert not resultaat.has_problems

    (evaluatie,) = list_evaluations(conn)
    assert evaluatie["status"] == "resolved"
    assert evaluatie["realised_value"] == pytest.approx(4.20)
    assert evaluatie["scorer_version"] == SCORER_VERSION
    assert evaluatie["within_interval"] == 1
    assert evaluatie["crps"] > 0
    assert evaluatie["brier"] is None  # kwantiel, geen binaire score


def test_de_gebruikte_waarneming_staat_erbij(tmp_path):
    """CLAUDE.md: elke agent-beslissing blijft herleidbaar. Een score
    zonder de claim die hem veroorzaakte is niet na te rekenen."""
    import json

    conn = _db(tmp_path)
    _claim(conn, "10y_treasury_yield", 1, 4.00)
    _claim(conn, "10y_treasury_yield", 22, 4.20)
    save_prediction(conn, _kwantiel())
    resolve_due_predictions(conn, now=NA_AFLOOP)

    (evaluatie,) = list_evaluations(conn)
    claim_ids = json.loads(evaluatie["evidence_claim_ids_json"])
    assert len(claim_ids) == 1
    rij = conn.execute("SELECT value_json FROM claims WHERE id = ?", (claim_ids[0],)).fetchone()
    assert json.loads(rij[0]) == 4.20


def test_binaire_voorspelling_krijgt_brier_en_log_loss(tmp_path):
    from contract import resolution

    conn = _db(tmp_path)
    _claim(conn, "fed_funds_target_upper", 1, 4.00)
    _claim(conn, "fed_funds_target_upper", 30, 4.25)
    save_prediction(conn, _kwantiel(
        target_metric_key="fed_funds_target_upper",
        kind=PredictionKind.BINARY,
        horizon_kind=HorizonKind.RELEASES, horizon_n=1,
        resolution_method=ResolutionMethod.DIRECTION_AFTER_FOMC,
        q10=None, q50=None, q90=None,
        probability=0.7, event_rule="FEDFUNDS hoger na de volgende vergadering",
    ))

    # De kalender tijdelijk vullen: zonder die data weigert de methode,
    # en dat is precies wat test_resolution.py bewaakt.
    origineel = resolution.FOMC_MEETING_DATES
    resolution.FOMC_MEETING_DATES = (datetime(2026, 10, 28).date(),)
    try:
        resultaat = resolve_due_predictions(conn, now=datetime(2026, 10, 31, tzinfo=timezone.utc))
    finally:
        resolution.FOMC_MEETING_DATES = origineel

    assert resultaat.resolved == 1
    (evaluatie,) = list_evaluations(conn)
    assert evaluatie["realised_value"] == 1.0
    assert evaluatie["brier"] == pytest.approx(0.09)
    assert evaluatie["log_loss"] > 0
    assert evaluatie["crps"] is None


# --------------------------------------------------------------------------
# Wachten versus opgeven -- het onderscheid waar alles op hangt
# --------------------------------------------------------------------------


def test_zonder_data_wordt_er_gewacht_en_niets_weggeschreven(tmp_path):
    """Een ontbrekende waarneming is geen uitkomst. Zou hier een rij
    ontstaan, dan was die definitief -- evaluations kent geen update-pad."""
    conn = _db(tmp_path)
    _claim(conn, "10y_treasury_yield", 1, 4.00)
    save_prediction(conn, _kwantiel())

    resultaat = resolve_due_predictions(conn, now=NA_AFLOOP)

    assert resultaat.still_waiting == 1
    assert resultaat.resolved == 0
    assert list_evaluations(conn) == []


def test_een_dag_later_alsnog_afgewikkeld(tmp_path):
    """Het hele bestaansrecht van 'wachten': de data komt later binnen en
    de voorspelling telt gewoon mee."""
    conn = _db(tmp_path)
    _claim(conn, "10y_treasury_yield", 1, 4.00)
    save_prediction(conn, _kwantiel())
    resolve_due_predictions(conn, now=NA_AFLOOP)

    _claim(conn, "10y_treasury_yield", 23, 4.15)
    resultaat = resolve_due_predictions(conn, now=datetime(2026, 10, 24, 7, 0, tzinfo=timezone.utc))

    assert resultaat.resolved == 1
    assert list_evaluations(conn)[0]["realised_value"] == pytest.approx(4.15)


def test_na_de_wachttijd_wordt_het_onafwikkelbaar_met_reden(tmp_path):
    """Zonder deze grens blijft een reeks die stil gestopt is met
    publiceren elke dag opnieuw geprobeerd worden, en valt dat nooit op."""
    conn = _db(tmp_path)
    _claim(conn, "10y_treasury_yield", 1, 4.00)
    save_prediction(conn, _kwantiel())

    veel_later = STRAKS + MAX_WACHTTIJD + timedelta(days=1)
    resultaat = resolve_due_predictions(conn, now=veel_later)

    assert resultaat.unresolvable == 1
    assert resultaat.has_problems
    (evaluatie,) = list_evaluations(conn)
    assert evaluatie["status"] == "unresolvable"
    assert "wachttijd" in evaluatie["reason"]
    assert evaluatie["realised_value"] is None


def test_ontbrekende_fomc_kalender_is_meteen_onafwikkelbaar(tmp_path, monkeypatch):
    """Niet wachten: de kalender komt niet vanzelf. De reden noemt het
    bestand waar hij ingevuld moet worden. De standaardkalender is sinds
    30-09-2026 gevuld, dus deze test maakt hem expliciet leeg."""
    monkeypatch.setattr(resolution, "FOMC_MEETING_DATES", ())
    conn = _db(tmp_path)
    _claim(conn, "fed_funds_target_upper", 1, 4.00)
    save_prediction(conn, _kwantiel(
        target_metric_key="fed_funds_target_upper",
        kind=PredictionKind.BINARY, horizon_kind=HorizonKind.RELEASES, horizon_n=1,
        resolution_method=ResolutionMethod.DIRECTION_AFTER_FOMC,
        q10=None, q50=None, q90=None,
        probability=0.7, event_rule="hoger",
    ))

    resultaat = resolve_due_predictions(conn, now=NA_AFLOOP)

    assert resultaat.unresolvable == 1
    assert "FOMC" in list_evaluations(conn)[0]["reason"]


# --------------------------------------------------------------------------
# Administratie
# --------------------------------------------------------------------------


def test_een_voorspelling_wordt_maar_een_keer_afgewikkeld(tmp_path):
    """Regressiegeval: de resolver draait dagelijks. Zonder de filter op
    al-beoordeelde voorspellingen zou elke dag elke afgelopen voorspelling
    opnieuw langskomen, en groeit dat ongelimiteerd mee met het cohort."""
    conn = _db(tmp_path)
    _claim(conn, "10y_treasury_yield", 1, 4.00)
    _claim(conn, "10y_treasury_yield", 22, 4.20)
    save_prediction(conn, _kwantiel())

    eerste = resolve_due_predictions(conn, now=NA_AFLOOP)
    tweede = resolve_due_predictions(conn, now=NA_AFLOOP + timedelta(days=1))

    assert eerste.resolved == 1
    assert tweede.resolved == 0
    assert len(list_evaluations(conn)) == 1


def test_nog_niet_afgelopen_voorspellingen_blijven_met_rust(tmp_path):
    conn = _db(tmp_path)
    _claim(conn, "10y_treasury_yield", 1, 4.00)
    save_prediction(conn, _kwantiel())

    resultaat = resolve_due_predictions(conn, now=datetime(2026, 10, 10, tzinfo=timezone.utc))

    assert (resultaat.resolved, resultaat.still_waiting, resultaat.unresolvable) == (0, 0, 0)
    assert list_unevaluated_due_predictions(conn, datetime(2026, 10, 10, tzinfo=timezone.utc)) == []


def test_een_kapotte_voorspelling_kost_de_rest_niet_hun_score(tmp_path, monkeypatch):
    """Zelfde isolatie als bij monitoring en de forecast-ronde. En: een BUG
    levert geen evaluation-rij op, want die zou onherroepelijk zijn terwijl
    een bug te repareren is."""
    conn = _db(tmp_path)
    _claim(conn, "10y_treasury_yield", 1, 4.00)
    _claim(conn, "10y_treasury_yield", 22, 4.20)
    _claim(conn, "vix", 1, 15.0, domain="financial")
    _claim(conn, "vix", 22, 17.0, domain="financial")
    save_prediction(conn, _kwantiel(target_metric_key="vix", domain="financial", agent="financial"))
    save_prediction(conn, _kwantiel())

    import scoring.resolver as resolver_module

    echte = resolver_module.level_at_or_after

    def kapot(obs, resolves_at):
        if any(o.value == 17.0 for o in obs):
            raise RuntimeError("onverwachte bug")
        return echte(obs, resolves_at)

    monkeypatch.setattr(resolver_module, "level_at_or_after", kapot)
    resultaat = resolve_due_predictions(conn, now=NA_AFLOOP)

    assert resultaat.resolved == 1
    assert len(resultaat.errors) == 1
    assert "vix" in resultaat.errors[0]
    assert [e["status"] for e in list_evaluations(conn)] == ["resolved"]


def test_resolver_draait_mee_in_de_dagelijkse_cyclus(tmp_path):
    """De koppeling zelf: zonder deze aanroep wikkelt er nooit iets af."""
    from runtime.daily import run_daily

    conn = _db(tmp_path)
    _claim(conn, "10y_treasury_yield", 1, 4.00)
    _claim(conn, "10y_treasury_yield", 22, 4.20)
    save_prediction(conn, _kwantiel())

    resultaat = run_daily(conn, agents=[], now=NA_AFLOOP)

    assert resultaat.resolver is not None
    assert resultaat.resolver.resolved == 1


def test_onafwikkelbare_voorspelling_belandt_in_de_melding(tmp_path):
    """Het terugkerende bugpatroon uit CLAUDE.md: een check die wel iets
    vaststelt maar nergens uitkomt. Een voorspelling die nooit gescoord
    wordt, is stil uit het cohort verdwenen."""
    from runtime.daily import run_daily

    conn = _db(tmp_path)
    _claim(conn, "10y_treasury_yield", 1, 4.00)
    save_prediction(conn, _kwantiel())

    meldingen = []
    resultaat = run_daily(
        conn, agents=[], now=STRAKS + MAX_WACHTTIJD + timedelta(days=1),
        notifier=meldingen.append,
    )

    assert resultaat.has_problems
    assert len(meldingen) == 1
    assert "nooit meer gescoord" in meldingen[0].body
