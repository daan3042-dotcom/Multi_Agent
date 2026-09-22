"""
test_integration_section_a.py
Sectie A's eigen claim is dat het "alles samenbindt" -- dat is per definitie
niet aan te tonen met losse unit-tests per module (die bewijzen alleen dat
elk onderdeel op zichzelf correct is). Deze test doorloopt het volledige pad
uit docs/architecture.md end-to-end, met synthetische data die doet alsof
hij van een domain agent komt (er bestaat nog geen echte domain agent --
dat is sectie B) om te bevestigen dat de zes A-stappen daadwerkelijk op
elkaar aansluiten:

    claim opslaan (A.1/A.2) -> data-health check (A.3) ->
    trigger-evaluatie (A.4) -> manager-dispatch (A.6) ->
    QC op een gesimuleerde deep-dive (A.5) -> deep-dive opslaan (A.2)

Twee scenario's: (1) het normale pad met een gezonde databron en een
drempeloverschrijding, en (2) het stille-faalscenario dat A.3 specifiek moet
voorkomen -- een kapotte databron die zonder A.3 gewoon "geen trigger" zou
opleveren, hier moet die zelf een trigger worden.
"""

from datetime import datetime, timedelta, timezone

from contract.output_contract import Claim, DomainOutput, Mode
from health.data_health import HealthStatus, check_source
from manager.manager import dispatch
from qc.qc import apply_qc
from storage.schema import (
    init_db,
    load_latest_claims,
    record_data_health,
    record_trigger_event,
    save_domain_output,
)
from triggers.trigger_engine import evaluate_data_health, evaluate_threshold


def test_full_monitoring_to_deep_dive_pipeline_healthy_source(tmp_path):
    conn = init_db(str(tmp_path / "integration.db"))
    now = datetime.now(timezone.utc)

    # -- A.3: databron rapporteert een succesvolle, verse pull --
    record_data_health(conn, "FRED", now, success=True)
    health = check_source(conn, "FRED", max_age=timedelta(days=2), now=now)
    assert health.status == HealthStatus.OK

    # -- A.1/A.2: monitoring-run van een (gesimuleerde) domain agent slaat een claim op --
    claim = Claim(
        domain="monetary_policy",
        claim="Fed funds rate",
        value=5.75,
        source="FRED",
        confidence=0.9,
        timestamp=now,
        metric_key="fed_funds_rate",
    )
    monitoring_output = DomainOutput(domain="monetary_policy", mode=Mode.MONITORING, generated_at=now, claims=[claim])
    save_domain_output(conn, monitoring_output)

    # -- A.2: de trigger-laag leest de zojuist opgeslagen claim terug --
    loaded = load_latest_claims(conn, "monetary_policy", metric_key="fed_funds_rate")
    assert len(loaded) == 1
    observed_value = loaded[0].value

    # -- A.4: deterministische trigger-evaluatie tegen een drempel --
    trigger = evaluate_threshold(
        domain="monetary_policy", metric_key="fed_funds_rate", observed_value=observed_value,
        operator=">", threshold=5.5, reason="Fed funds rate boven verwachting", severity="high", now=now,
    )
    assert trigger is not None
    record_trigger_event(
        conn, domain=trigger.domain, triggered_at=trigger.triggered_at, reason=trigger.reason,
        severity=trigger.severity, metric_key=trigger.metric_key, observed_value=trigger.observed_value,
        threshold=trigger.threshold,
    )

    # -- A.6: manager groepeert de trigger(s) tot een dispatch-plan --
    plan = dispatch([trigger], now=now)
    assert plan.domains == ["monetary_policy"]
    assert plan.is_simultaneous is False

    # -- A.5: QC op een gesimuleerde deep-dive-tekst (deep-dive mode zelf is sectie B) --
    deep_dive_text = (
        "De fed_funds_rate staat op 5.75%, ruim boven de eerdere marktverwachting "
        "van rond de 5.5%. Dit verhoogt de kans op een verkrappend beleid."
    )
    qc_result = apply_qc(loaded, deep_dive_text)
    assert qc_result.needs_review is False  # cijfer in de tekst klopt met de claim

    # -- A.2: de deep-dive-output wordt opgeslagen, needs_review komt uit A.5 --
    deep_dive_output = DomainOutput(
        domain="monetary_policy", mode=Mode.DEEP_DIVE, generated_at=now,
        claims=[claim], needs_review=qc_result.needs_review, review_issues=qc_result.issues,
    )
    deep_dive_id = save_domain_output(conn, deep_dive_output)
    assert deep_dive_id is not None

    stored = conn.execute(
        "SELECT mode, needs_review FROM domain_outputs WHERE id = ?", (deep_dive_id,)
    ).fetchone()
    assert stored == ("deep_dive", 0)


def test_stale_data_source_produces_its_own_trigger_instead_of_silence(tmp_path):
    """Dit is precies het scenario dat A.3 moet voorkomen: een kapotte bron
    mag NOOIT gewoon 'geen trigger' opleveren. Simuleert een bron die al 10
    dagen niet meer succesvol is opgehaald."""
    conn = init_db(str(tmp_path / "integration.db"))
    now = datetime.now(timezone.utc)
    ten_days_ago = now - timedelta(days=10)

    record_data_health(conn, "SEC_EDGAR", ten_days_ago, success=True)
    health = check_source(conn, "SEC_EDGAR", max_age=timedelta(days=2), now=now)
    assert health.status == HealthStatus.STALE

    # Zonder A.3+A.4 samen zou dit scenario simpelweg NIETS opleveren (geen
    # nieuwe claim om tegen een drempel te evalueren) -- de data-health-check
    # moet zelf een trigger produceren, dat is het hele punt van A.3.
    health_trigger = evaluate_data_health("equity", health, now=now)
    assert health_trigger is not None
    assert health_trigger.severity == "medium"
    assert "SEC_EDGAR" in health_trigger.reason

    plan = dispatch([health_trigger], now=now)
    assert "equity" in plan.domains
    assert plan.highest_severity("equity") == "medium"


def test_simultaneous_triggers_across_domains_flagged_by_manager(tmp_path):
    """Het expliciete voorbeeld uit het stappenplan: een Fed-besluit raakt
    monetary policy, currency en equity tegelijk. De manager moet dit als
    ÉÉN gelijktijdige dispatch-batch zien, niet als drie losse."""
    now = datetime.now(timezone.utc)
    events = [
        evaluate_threshold("monetary_policy", "fed_funds_rate", 5.75, ">", 5.5, "Fed-besluit", now=now),
        evaluate_threshold("currency", "dxy_change_pct", 1.2, ">", 0.8, "Fed-besluit raakt DXY", now=now),
        evaluate_threshold("equity", "spx_move_pct", -1.5, "<", -1.0, "Fed-besluit raakt equity-breadth", now=now),
    ]
    assert all(e is not None for e in events)

    plan = dispatch(events, now=now)
    assert set(plan.domains) == {"monetary_policy", "currency", "equity"}
    assert plan.is_simultaneous is True
    assert plan.batch_id  # elke gelijktijdige batch krijgt één gedeeld batch_id
