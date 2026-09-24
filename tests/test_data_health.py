from datetime import datetime, timedelta, timezone

from contract.output_contract import Claim
from health.data_health import HealthStatus, check_source, detect_revision, evaluate_pull_failure, evaluate_staleness
from storage.schema import init_db, record_data_health


def _claim(value, source_time, analysis_time=None):
    analysis_time = analysis_time or (source_time or datetime.now(timezone.utc))
    return Claim(
        domain="economic", claim="test", value=value, source="FRED", confidence=0.85,
        analysis_time=analysis_time, source_time=source_time, metric_key="gdp_growth",
    )


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


def test_detect_revision_returns_none_without_previous_claims():
    period = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert detect_revision([], period, value=2.5) is None


def test_detect_revision_returns_none_when_source_time_unknown():
    period = datetime(2026, 6, 1, tzinfo=timezone.utc)
    previous = [_claim(2.5, source_time=period)]
    assert detect_revision(previous, source_time=None, value=3.0) is None


def test_detect_revision_returns_none_when_same_period_same_value():
    period = datetime(2026, 6, 1, tzinfo=timezone.utc)
    previous = [_claim(2.5, source_time=period)]
    assert detect_revision(previous, source_time=period, value=2.5) is None


def test_detect_revision_returns_none_for_a_new_period():
    old_period = datetime(2026, 5, 1, tzinfo=timezone.utc)
    new_period = datetime(2026, 6, 1, tzinfo=timezone.utc)
    previous = [_claim(2.5, source_time=old_period)]
    assert detect_revision(previous, source_time=new_period, value=9.9) is None


def test_detect_revision_flags_changed_value_for_already_seen_period():
    period = datetime(2026, 6, 1, tzinfo=timezone.utc)
    previous = [_claim(2.5, source_time=period)]
    revised = detect_revision(previous, source_time=period, value=2.1)
    assert revised is not None
    assert revised.value == 2.5


def test_detect_revision_scans_full_history_not_just_most_recent():
    """Een revisie kan een periode van meerdere cycli geleden raken, niet
    per se de allerlaatste poll -- previous_claims moet dus volledig
    doorzocht worden, niet alleen index 0."""
    old_period = datetime(2026, 5, 1, tzinfo=timezone.utc)
    new_period = datetime(2026, 6, 1, tzinfo=timezone.utc)
    previous = [
        _claim(3.0, source_time=new_period),  # meest recente poll, andere periode
        _claim(2.5, source_time=old_period),  # oudere poll, de periode die nu herzien wordt
    ]
    revised = detect_revision(previous, source_time=old_period, value=2.1)
    assert revised is not None
    assert revised.value == 2.5
