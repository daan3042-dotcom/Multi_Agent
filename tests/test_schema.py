from datetime import datetime, timedelta, timezone

from contract.output_contract import Claim, DomainOutput, Mode
from storage.schema import (
    init_db,
    latest_data_health,
    load_latest_claims,
    record_data_health,
    record_trigger_event,
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
