from datetime import datetime, timezone

from health.data_health import HealthCheckResult, HealthStatus
from triggers.trigger_engine import evaluate_data_health, evaluate_surprise, evaluate_threshold


def test_evaluate_threshold_fires_when_breached():
    event = evaluate_threshold(
        domain="monetary_policy", metric_key="fed_funds_rate", observed_value=5.75,
        operator=">", threshold=5.5, reason="Fed funds rate boven verwachting",
    )
    assert event is not None
    assert event.domain == "monetary_policy"
    assert event.severity == "medium"


def test_evaluate_threshold_does_not_fire_when_not_breached():
    event = evaluate_threshold(
        domain="monetary_policy", metric_key="fed_funds_rate", observed_value=5.25,
        operator=">", threshold=5.5, reason="test",
    )
    assert event is None


def test_evaluate_surprise_fires_beyond_tolerance():
    event = evaluate_surprise(
        domain="economic", metric_key="cpi_yoy", observed_value=3.8, expected_value=3.2,
        tolerance=0.3, reason="CPI verrassing",
    )
    assert event is not None
    assert "afwijking" in event.reason


def test_evaluate_surprise_does_not_fire_within_tolerance():
    event = evaluate_surprise(
        domain="economic", metric_key="cpi_yoy", observed_value=3.3, expected_value=3.2,
        tolerance=0.3, reason="test",
    )
    assert event is None


def test_evaluate_data_health_ok_produces_no_trigger():
    health = HealthCheckResult(source="FRED", status=HealthStatus.OK, last_success_at=None, checked_at=datetime.now(timezone.utc))
    assert evaluate_data_health("monetary_policy", health) is None


def test_evaluate_data_health_unknown_produces_no_trigger():
    health = HealthCheckResult(source="FRED", status=HealthStatus.UNKNOWN, last_success_at=None, checked_at=datetime.now(timezone.utc))
    assert evaluate_data_health("monetary_policy", health) is None


def test_evaluate_data_health_unreachable_produces_high_severity_trigger():
    health = HealthCheckResult(source="FRED", status=HealthStatus.UNREACHABLE, last_success_at=None, checked_at=datetime.now(timezone.utc), detail="timeout")
    event = evaluate_data_health("monetary_policy", health)
    assert event is not None
    assert event.severity == "high"
    assert event.reason.startswith("data_health:")


def test_evaluate_data_health_stale_produces_medium_severity_trigger():
    health = HealthCheckResult(source="FRED", status=HealthStatus.STALE, last_success_at=None, checked_at=datetime.now(timezone.utc), detail="10 dagen oud")
    event = evaluate_data_health("monetary_policy", health)
    assert event is not None
    assert event.severity == "medium"
