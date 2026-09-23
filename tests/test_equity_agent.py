from datetime import datetime, timedelta, timezone

from agents.equity_agent import (
    AnalystAgentReport,
    adapt_narrative_claim,
    adapt_to_claims,
    equity_domain,
    ingest_report,
)
from contract.output_contract import Mode
from manager.manager import dispatch
from storage.schema import init_db, load_latest_claims


def _report(**overrides):
    defaults = dict(
        ticker="NKE",
        generated_at=datetime.now(timezone.utc),
        verified_metrics={
            "sec_operating_margin": {"value": 0.11, "fiscal_year": 2025},
            "sec_net_margin": {"value": 0.08, "fiscal_year": 2025},
        },
        altman_result={"z_score": 3.2},
        piotroski_result={"score": 7, "max_score": 9},
        reverse_dcf_result={"wacc": 0.085, "implied_annual_fcf_growth": 0.04},
        report_text="Dit is de volledige analyse-tekst.",
        needs_review=False,
        review_issues=[],
    )
    defaults.update(overrides)
    return AnalystAgentReport(**defaults)


def test_equity_domain_is_namespaced_per_ticker():
    assert equity_domain("nke") == "equity:NKE"
    assert equity_domain("AAPL") == "equity:AAPL"
    assert equity_domain("nke") != equity_domain("aapl")


def test_adapt_to_claims_builds_verified_metric_claims():
    claims = adapt_to_claims(_report())
    by_key = {c.metric_key: c for c in claims if c.metric_key}
    assert by_key["sec_operating_margin"].value == 0.11
    assert by_key["sec_operating_margin"].domain == "equity:NKE"
    assert by_key["sec_operating_margin"].source == "SEC EDGAR"


def test_adapt_to_claims_includes_altman_and_reverse_dcf():
    claims = adapt_to_claims(_report())
    by_key = {c.metric_key: c for c in claims if c.metric_key}
    assert by_key["altman_z_score"].value == 3.2
    assert by_key["reverse_dcf_wacc"].value == 0.085
    assert by_key["reverse_dcf_implied_growth"].value == 0.04


def test_adapt_to_claims_piotroski_has_no_metric_key():
    claims = adapt_to_claims(_report())
    piotroski = next(c for c in claims if c.claim == "Piotroski F-Score")
    assert piotroski.value == "7/9"
    assert piotroski.metric_key is None


def test_adapt_to_claims_skips_error_results():
    claims = adapt_to_claims(_report(altman_result={"error": "onvoldoende data"}))
    assert not any(c.metric_key == "altman_z_score" for c in claims)


def test_adapt_to_claims_skips_missing_verified_metrics():
    claims = adapt_to_claims(_report(verified_metrics={}))
    assert not any(c.metric_key in ("sec_operating_margin", "sec_net_margin") for c in claims)


def test_adapt_narrative_claim_confidence_reflects_needs_review():
    clean = adapt_narrative_claim(_report(needs_review=False))
    flagged = adapt_narrative_claim(_report(needs_review=True))
    assert clean.confidence > flagged.confidence


def test_ingest_report_with_no_claims_returns_none_triple(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    result = ingest_report(conn, _report(verified_metrics={}, altman_result=None, piotroski_result=None, reverse_dcf_result=None))
    assert result == (None, None, [])


def test_ingest_report_saves_monitoring_and_deep_dive_outputs(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    monitoring_output, deep_dive_output, triggers = ingest_report(conn, _report())

    assert monitoring_output.mode == Mode.MONITORING
    assert monitoring_output.needs_review is False
    assert deep_dive_output.mode == Mode.DEEP_DIVE
    assert deep_dive_output.needs_review is False
    assert any(c.claim == "analyst_agent.ai volledige analyse" for c in deep_dive_output.claims)
    assert triggers == []  # eerste analyse van deze ticker, niets om tegen te vergelijken


def test_ingest_report_propagates_needs_review_to_deep_dive_only(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _, deep_dive_output, _ = ingest_report(conn, _report(needs_review=True, review_issues=["neutraliteitsprobleem"]))
    assert deep_dive_output.needs_review is True
    assert deep_dive_output.review_issues == ["neutraliteitsprobleem"]


def test_ingest_report_triggers_on_significant_delta_for_same_ticker(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=90)

    ingest_report(conn, _report(generated_at=t1, verified_metrics={"sec_operating_margin": {"value": 0.11}}), now=t1)
    _, _, triggers = ingest_report(conn, _report(generated_at=t2, verified_metrics={"sec_operating_margin": {"value": 0.16}}), now=t2)

    assert len(triggers) == 1
    assert triggers[0].domain == "equity:NKE"
    assert triggers[0].metric_key == "sec_operating_margin"


def test_ingest_report_different_tickers_never_cross_trigger(tmp_path):
    """De kern van de namespacing-fix: NKE's marge mag NOOIT vergeleken
    worden met AAPL's marge, ook al heten beide 'sec_operating_margin'."""
    conn = init_db(str(tmp_path / "t.db"))
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=1)

    ingest_report(conn, _report(ticker="AAPL", generated_at=t1, verified_metrics={"sec_operating_margin": {"value": 0.30}}), now=t1)
    _, _, triggers = ingest_report(conn, _report(ticker="NKE", generated_at=t2, verified_metrics={"sec_operating_margin": {"value": 0.11}}), now=t2)

    # NKE's EERSTE observatie -- geen trigger, ook al wijkt 0.11 enorm af
    # van AAPL's 0.30. Zou dit wel triggeren, dan zou dat bewijzen dat de
    # twee tickers per ongeluk tegen elkaar vergeleken worden.
    assert triggers == []

    nke_claims = load_latest_claims(conn, "equity:NKE", metric_key="sec_operating_margin")
    aapl_claims = load_latest_claims(conn, "equity:AAPL", metric_key="sec_operating_margin")
    assert nke_claims[0].value == 0.11
    assert aapl_claims[0].value == 0.30


def test_equity_triggers_integrate_with_manager_dispatch(tmp_path):
    """Bewijst dat equity-triggers (met hun 'equity:<TICKER>'-domain) door
    dezelfde manager.dispatch() gaan als monetary_policy/currency, zonder
    enige aanpassing daar -- exact de interoperabiliteit die DD's vraag
    (kunnen alle agents straks goed samenwerken?) aankaartte."""
    conn = init_db(str(tmp_path / "t.db"))
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=90)

    ingest_report(conn, _report(generated_at=t1, verified_metrics={"sec_operating_margin": {"value": 0.11}}), now=t1)
    _, _, nke_triggers = ingest_report(conn, _report(generated_at=t2, verified_metrics={"sec_operating_margin": {"value": 0.16}}), now=t2)

    plan = dispatch(nke_triggers, now=t2)
    assert plan.domains == ["equity:NKE"]
