import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from contract.output_contract import Claim, DomainOutput, Mode
from health.data_health import QualityStatus
from qc.qc import InvalidQCTransitionError, QCCaseStatus
from storage.schema import (
    advance_qc_case,
    archive_qc_case,
    get_qc_case,
    get_source,
    has_successful_run,
    init_db,
    latest_data_health,
    latest_qc_case,
    list_agent_runs,
    list_qc_cases,
    list_sources,
    load_latest_claims,
    open_qc_case,
    record_agent_run,
    record_data_health,
    record_trigger_event,
    register_source,
    save_domain_output,
)


def _db(tmp_path):
    return init_db(str(tmp_path / "test.db"))


def _output():
    now = datetime.now(timezone.utc)
    claim = Claim(
        domain="monetary_policy",
        claim="Fed funds rate boven marktverwachting",
        value=5.5,
        source="FRED",
        confidence=0.85,
        analysis_time=now,
        event_time=now - timedelta(days=1),
        source_time=now - timedelta(hours=2),
        metric_key="fed_funds_rate",
    )
    return DomainOutput(domain="monetary_policy", mode=Mode.MONITORING, generated_at=now, claims=[claim])


def test_init_db_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    conn1 = init_db(path)
    conn1.close()
    conn2 = init_db(path)  # opnieuw aanroepen op bestaande db mag niet crashen
    conn2.close()


def test_save_and_load_domain_output(tmp_path):
    conn = _db(tmp_path)
    output = _output()
    save_domain_output(conn, output)

    claims = load_latest_claims(conn, "monetary_policy")
    assert len(claims) == 1
    assert claims[0].value == 5.5
    assert claims[0].metric_key == "fed_funds_rate"

    # DB-round-trip van de vier tijdvelden zelf (niet alleen .value/.metric_key) --
    # bewijst dat save_domain_output/load_latest_claims elk veld apart door
    # SQLite heen krijgt, niet alleen de in-memory dataclass-round-trip.
    original = output.claims[0]
    assert claims[0].analysis_time == original.analysis_time
    assert claims[0].event_time == original.event_time
    assert claims[0].source_time == original.source_time
    assert claims[0].ingestion_time == original.ingestion_time


def test_load_latest_claims_filters_by_metric_key(tmp_path):
    conn = _db(tmp_path)
    save_domain_output(conn, _output())

    assert len(load_latest_claims(conn, "monetary_policy", metric_key="fed_funds_rate")) == 1
    assert len(load_latest_claims(conn, "monetary_policy", metric_key="does_not_exist")) == 0
    assert len(load_latest_claims(conn, "currency")) == 0


def test_load_latest_claims_orders_newest_first(tmp_path):
    conn = _db(tmp_path)
    older = _output()
    save_domain_output(conn, older)

    now = datetime.now(timezone.utc)
    newer_claim = Claim(
        domain="monetary_policy", claim="Nieuwere claim", value=5.75, source="FRED",
        confidence=0.9, analysis_time=now, metric_key="fed_funds_rate",
    )
    save_domain_output(conn, DomainOutput(domain="monetary_policy", mode=Mode.MONITORING, generated_at=now, claims=[newer_claim]))

    claims = load_latest_claims(conn, "monetary_policy", metric_key="fed_funds_rate")
    assert claims[0].value == 5.75


def test_record_and_read_data_health(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    record_data_health(conn, "FRED", now, success=True)

    result = latest_data_health(conn, "FRED")
    assert result["success"] is True
    assert result["source"] == "FRED"


def test_latest_data_health_returns_none_for_unknown_source(tmp_path):
    conn = _db(tmp_path)
    assert latest_data_health(conn, "unknown") is None


def test_record_trigger_event(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    trigger_id = record_trigger_event(
        conn, domain="monetary_policy", triggered_at=now, reason="test", severity="high",
        metric_key="fed_funds_rate", observed_value=5.5, threshold=5.25, dispatch_batch_id="batch-1",
    )
    assert trigger_id is not None
    row = conn.execute("SELECT domain, severity, dispatch_batch_id FROM trigger_events WHERE id = ?", (trigger_id,)).fetchone()
    assert row == ("monetary_policy", "high", "batch-1")


def test_record_and_list_agent_runs(tmp_path):
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(minutes=5)

    output_id = save_domain_output(conn, _output())
    record_agent_run(conn, "monetary_policy", "monitoring", t1, success=True, domain_output_id=output_id, trigger_count=1)
    record_agent_run(conn, "monetary_policy", "deep_dive", t2, success=False, trigger_count=0, error="LLM-call mislukt")

    runs = list_agent_runs(conn, "monetary_policy")
    assert len(runs) == 2
    # nieuwste eerst
    assert runs[0]["mode"] == "deep_dive"
    assert runs[0]["success"] is False
    assert runs[0]["error"] == "LLM-call mislukt"
    assert runs[0]["domain_output_id"] is None
    assert runs[1]["mode"] == "monitoring"
    assert runs[1]["success"] is True
    assert runs[1]["domain_output_id"] == output_id
    assert runs[1]["trigger_count"] == 1


def test_list_agent_runs_returns_empty_for_unknown_domain(tmp_path):
    conn = _db(tmp_path)
    assert list_agent_runs(conn, "unknown") == []


def test_list_agent_runs_filters_by_mode(tmp_path):
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(minutes=5)
    record_agent_run(conn, "monetary_policy", "monitoring", t1, success=True)
    record_agent_run(conn, "monetary_policy", "deep_dive", t2, success=True)

    monitoring_runs = list_agent_runs(conn, "monetary_policy", mode="monitoring")
    assert len(monitoring_runs) == 1
    assert monitoring_runs[0]["mode"] == "monitoring"

    deep_dive_runs = list_agent_runs(conn, "monetary_policy", mode="deep_dive")
    assert len(deep_dive_runs) == 1
    assert deep_dive_runs[0]["mode"] == "deep_dive"


def test_has_successful_run_false_without_any_run(tmp_path):
    conn = _db(tmp_path)
    assert has_successful_run(conn, "monetary_policy", "monitoring", "cycle-2026-01-01") is False


def test_has_successful_run_true_after_a_successful_run_with_that_event_id(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    record_agent_run(conn, "monetary_policy", "monitoring", now, success=True, event_id="cycle-2026-01-01")
    assert has_successful_run(conn, "monetary_policy", "monitoring", "cycle-2026-01-01") is True


def test_has_successful_run_false_after_only_a_failed_run_with_that_event_id(tmp_path):
    """Een mislukte poging mag NOOIT als 'al verwerkt' tellen -- anders zou
    een terechte retry na een echte fout stilzwijgend geblokkeerd worden."""
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    record_agent_run(conn, "monetary_policy", "monitoring", now, success=False, event_id="cycle-2026-01-01", error="timeout")
    assert has_successful_run(conn, "monetary_policy", "monitoring", "cycle-2026-01-01") is False


def test_has_successful_run_is_scoped_to_domain_and_mode(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    record_agent_run(conn, "monetary_policy", "monitoring", now, success=True, event_id="cycle-2026-01-01")

    assert has_successful_run(conn, "currency", "monitoring", "cycle-2026-01-01") is False
    assert has_successful_run(conn, "monetary_policy", "deep_dive", "cycle-2026-01-01") is False


def test_agent_runs_rejects_duplicate_successful_event_id(tmp_path):
    """Databaseniveau-afdwinging (partial unique index), niet alleen een
    applicatie-check -- een tweede succesvolle rij met hetzelfde
    domain+mode+event_id mag nooit stil worden toegestaan."""
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    record_agent_run(conn, "monetary_policy", "monitoring", now, success=True, event_id="cycle-2026-01-01")

    with pytest.raises(sqlite3.IntegrityError):
        record_agent_run(conn, "monetary_policy", "monitoring", now, success=True, event_id="cycle-2026-01-01")


def test_agent_runs_allows_retry_after_a_failed_attempt_with_same_event_id(tmp_path):
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(minutes=1)
    record_agent_run(conn, "monetary_policy", "monitoring", t1, success=False, event_id="cycle-2026-01-01", error="timeout")
    # geen crash: een tweede POGING (nog steeds mislukt, of nu wel gelukt) met
    # hetzelfde event_id is een legitieme retry, geen duplicaat
    record_id = record_agent_run(conn, "monetary_policy", "monitoring", t2, success=True, event_id="cycle-2026-01-01")
    assert record_id is not None


def test_register_source_and_get_source(tmp_path):
    conn = _db(tmp_path)
    register_source(
        conn, "FRED:monetary_policy", provider="FRED", domain="monetary_policy",
        max_age=timedelta(days=35), frequency="maandelijks", latency="~1s per call", cost="gratis",
    )

    source = get_source(conn, "FRED:monetary_policy")
    assert source is not None
    assert source.source_key == "FRED:monetary_policy"
    assert source.provider == "FRED"
    assert source.domain == "monetary_policy"
    assert source.max_age == timedelta(days=35)
    assert source.frequency == "maandelijks"
    assert source.quality_score is None
    assert source.fallback_source_key is None


def test_get_source_returns_none_for_unknown_key(tmp_path):
    conn = _db(tmp_path)
    assert get_source(conn, "does_not_exist") is None


def test_register_source_is_an_idempotent_upsert(tmp_path):
    """register_source() is CONFIGURATIE, geen gebeurtenis-log -- een
    tweede aanroep met hetzelfde source_key mag geen duplicaat aanmaken,
    en moet de nieuwe waarden overnemen (bijv. een aangepaste max_age)."""
    conn = _db(tmp_path)
    register_source(conn, "FRED:monetary_policy", provider="FRED", domain="monetary_policy", max_age=timedelta(days=35))
    register_source(conn, "FRED:monetary_policy", provider="FRED", domain="monetary_policy", max_age=timedelta(days=40))

    assert len(list_sources(conn)) == 1
    assert get_source(conn, "FRED:monetary_policy").max_age == timedelta(days=40)


def test_list_sources_returns_all_registered_sources_sorted(tmp_path):
    conn = _db(tmp_path)
    register_source(conn, "FRED:financial", provider="FRED", domain="financial", max_age=timedelta(days=10))
    register_source(conn, "FRED:monetary_policy", provider="FRED", domain="monetary_policy", max_age=timedelta(days=35))

    sources = list_sources(conn)
    assert [s.source_key for s in sources] == ["FRED:financial", "FRED:monetary_policy"]


def test_register_source_with_fallback_pointing_to_unknown_source_raises(tmp_path):
    """fallback_source_key is een FK naar sources.source_key (foreign_keys
    staat aan in init_db) -- verwijzen naar een niet-bestaande bron mag
    niet stilzwijgend geaccepteerd worden."""
    conn = _db(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        register_source(
            conn, "FRED:monetary_policy", provider="FRED", domain="monetary_policy",
            max_age=timedelta(days=35), fallback_source_key="does_not_exist",
        )


def test_register_source_with_valid_fallback(tmp_path):
    conn = _db(tmp_path)
    register_source(conn, "FRED:monetary_policy", provider="FRED", domain="monetary_policy", max_age=timedelta(days=35))
    register_source(
        conn, "ALTERNATIVE:monetary_policy", provider="ALTERNATIVE", domain="monetary_policy",
        max_age=timedelta(days=35), fallback_source_key="FRED:monetary_policy",
    )
    source = get_source(conn, "ALTERNATIVE:monetary_policy")
    assert source.fallback_source_key == "FRED:monetary_policy"


# -- Roadmap 1.6: qc_cases --

def test_open_qc_case_starts_at_triggered(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    case_id = open_qc_case(conn, "monetary_policy", ["Fed funds rate significant gewijzigd"], now)

    case = get_qc_case(conn, case_id)
    assert case is not None
    assert case.domain == "monetary_policy"
    assert case.status == QCCaseStatus.TRIGGERED
    assert case.trigger_reasons == ["Fed funds rate significant gewijzigd"]
    assert case.domain_output_id is None
    assert case.quality_status is None
    assert case.qc_issues == []
    assert case.created_at == now
    assert case.updated_at == now


def test_get_qc_case_returns_none_for_unknown_id(tmp_path):
    conn = _db(tmp_path)
    assert get_qc_case(conn, 999) is None


def test_advance_qc_case_along_valid_path(tmp_path):
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(seconds=5)
    output_id = save_domain_output(conn, _output())
    case_id = open_qc_case(conn, "monetary_policy", ["test"], t1)

    advance_qc_case(conn, case_id, QCCaseStatus.DEEP_DIVE_COMPLETE, t2, domain_output_id=output_id)
    case = get_qc_case(conn, case_id)
    assert case.status == QCCaseStatus.DEEP_DIVE_COMPLETE
    assert case.domain_output_id == output_id
    assert case.updated_at == t2
    assert case.created_at == t1  # created_at blijft ongewijzigd


def test_advance_qc_case_rejects_invalid_transition(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    case_id = open_qc_case(conn, "monetary_policy", ["test"], now)

    with pytest.raises(InvalidQCTransitionError):
        advance_qc_case(conn, case_id, QCCaseStatus.ARCHIVED, now)  # mag niet springen


def test_advance_qc_case_stores_quality_status_and_issues(tmp_path):
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    output_id = save_domain_output(conn, _output())
    case_id = open_qc_case(conn, "monetary_policy", ["test"], t1)
    advance_qc_case(conn, case_id, QCCaseStatus.DEEP_DIVE_COMPLETE, t1, domain_output_id=output_id)

    advance_qc_case(
        conn, case_id, QCCaseStatus.QC_FAILED, t1,
        quality_status=QualityStatus.INVALID, qc_issues=["bron onbereikbaar"],
    )
    case = get_qc_case(conn, case_id)
    assert case.status == QCCaseStatus.QC_FAILED
    assert case.quality_status == QualityStatus.INVALID
    assert case.qc_issues == ["bron onbereikbaar"]


def test_advance_qc_case_with_empty_issues_list_is_stored_not_skipped(tmp_path):
    """Een LEGE issue-lijst betekent 'gecontroleerd, niets gevonden' -- dat
    moet onderscheiden blijven van 'nog niet gecontroleerd' (None)."""
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    case_id = open_qc_case(conn, "monetary_policy", ["test"], t1)
    advance_qc_case(conn, case_id, QCCaseStatus.DEEP_DIVE_COMPLETE, t1)
    advance_qc_case(conn, case_id, QCCaseStatus.QC_PASSED, t1, qc_issues=[])

    case = get_qc_case(conn, case_id)
    assert case.qc_issues == []


def test_full_lifecycle_qc_failed_to_needs_review_to_archived(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    output_id = save_domain_output(conn, _output())
    case_id = open_qc_case(conn, "monetary_policy", ["test"], now)

    advance_qc_case(conn, case_id, QCCaseStatus.DEEP_DIVE_COMPLETE, now, domain_output_id=output_id)
    advance_qc_case(conn, case_id, QCCaseStatus.QC_FAILED, now, qc_issues=["inconsistentie"])
    advance_qc_case(conn, case_id, QCCaseStatus.NEEDS_REVIEW, now)
    assert get_qc_case(conn, case_id).status == QCCaseStatus.NEEDS_REVIEW

    archive_qc_case(conn, case_id, now)
    assert get_qc_case(conn, case_id).status == QCCaseStatus.ARCHIVED


def test_full_lifecycle_qc_passed_to_archived(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    output_id = save_domain_output(conn, _output())
    case_id = open_qc_case(conn, "monetary_policy", ["test"], now)

    advance_qc_case(conn, case_id, QCCaseStatus.DEEP_DIVE_COMPLETE, now, domain_output_id=output_id)
    advance_qc_case(conn, case_id, QCCaseStatus.QC_PASSED, now)
    archive_qc_case(conn, case_id, now)
    assert get_qc_case(conn, case_id).status == QCCaseStatus.ARCHIVED


def test_archive_qc_case_rejects_from_deep_dive_complete(tmp_path):
    """Archivering mag alleen vanuit QC_PASSED of NEEDS_REVIEW -- niet
    zomaar vanuit elke status."""
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    case_id = open_qc_case(conn, "monetary_policy", ["test"], now)
    advance_qc_case(conn, case_id, QCCaseStatus.DEEP_DIVE_COMPLETE, now)

    with pytest.raises(InvalidQCTransitionError):
        archive_qc_case(conn, case_id, now)


def test_latest_qc_case_returns_most_recent_matching_status(tmp_path):
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(minutes=5)
    older = open_qc_case(conn, "monetary_policy", ["eerste"], t1)
    newer = open_qc_case(conn, "monetary_policy", ["tweede"], t2)

    case = latest_qc_case(conn, "monetary_policy", QCCaseStatus.TRIGGERED)
    assert case.id == newer


def test_latest_qc_case_none_when_no_case_in_that_status(tmp_path):
    conn = _db(tmp_path)
    assert latest_qc_case(conn, "monetary_policy", QCCaseStatus.TRIGGERED) is None


def test_latest_qc_case_scoped_to_domain(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    open_qc_case(conn, "currency", ["ander domein"], now)
    assert latest_qc_case(conn, "monetary_policy", QCCaseStatus.TRIGGERED) is None


def test_list_qc_cases_filters_by_status(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    c1 = open_qc_case(conn, "monetary_policy", ["a"], now)
    c2 = open_qc_case(conn, "monetary_policy", ["b"], now)
    advance_qc_case(conn, c2, QCCaseStatus.DEEP_DIVE_COMPLETE, now)

    triggered = list_qc_cases(conn, "monetary_policy", status=QCCaseStatus.TRIGGERED)
    assert [c.id for c in triggered] == [c1]

    all_cases = list_qc_cases(conn, "monetary_policy")
    assert {c.id for c in all_cases} == {c1, c2}
