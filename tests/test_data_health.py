from datetime import datetime, timedelta, timezone

from health.data_health import HealthStatus, check_source, evaluate_pull_failure, evaluate_staleness
from storage.schema import init_db, record_data_health


def test_evaluate_staleness_ok_within_max_age():
    now = datetime.now(timezone.utc)
    result = evaluate_staleness("FRED", last_success_at=now - timedelta(hours=1), max_age=timedelta(days=2), now=now)
    assert result.status == HealthStatus.OK
    assert result.is_healthy


def test_evaluate_staleness_stale_beyond_max_age():
    now = datetime.now(timezone.utc)
    result = evaluate_staleness("FRED", last_success_at=now - timedelta(days=10), max_age=timedelta(days=2), now=now)
    assert result.status == HealthStatus.STALE
    assert not result.is_healthy


def test_evaluate_staleness_unknown_when_never_succeeded():
    now = datetime.now(timezone.utc)
    result = evaluate_staleness("FRED", last_success_at=None, max_age=timedelta(days=2), now=now)
    assert result.status == HealthStatus.UNKNOWN


def test_evaluate_pull_failure_is_unreachable():
    result = evaluate_pull_failure("SEC EDGAR", detail="503 Service Unavailable")
    assert result.status == HealthStatus.UNREACHABLE
    assert "503" in result.detail


def test_check_source_unknown_when_no_record(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    result = check_source(conn, "FRED", max_age=timedelta(days=2))
    assert result.status == HealthStatus.UNKNOWN


def test_check_source_ok_after_recent_success(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    record_data_health(conn, "FRED", now, success=True)
    result = check_source(conn, "FRED", max_age=timedelta(days=2), now=now)
    assert result.status == HealthStatus.OK


def test_check_source_stale_after_old_success(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    old = datetime.now(timezone.utc) - timedelta(days=30)
    record_data_health(conn, "FRED", old, success=True)
    result = check_source(conn, "FRED", max_age=timedelta(days=2))
    assert result.status == HealthStatus.STALE


def test_check_source_unreachable_after_recorded_failure(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    record_data_health(conn, "FRED", now, success=False, detail="timeout")
    result = check_source(conn, "FRED", max_age=timedelta(days=2))
    assert result.status == HealthStatus.UNREACHABLE
    assert result.detail == "timeout"
