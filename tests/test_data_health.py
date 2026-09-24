from datetime import datetime, timedelta, timezone

import pytest
from contract.output_contract import Claim
from health.data_health import (
    HealthStatus,
    QualityStatus,
    check_source,
    detect_revision,
    evaluate_completeness,
    evaluate_consistency,
    evaluate_continuity,
    evaluate_pull_failure,
    evaluate_staleness,
    evaluate_validity,
    rollup_quality_status,
)
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


# -- Completeness: verwachte metric(s) uitgebleven in DEZE pull --

def test_evaluate_completeness_all_expected_present():
    result = evaluate_completeness("FRED", expected_metric_keys={"a", "b"}, present_metric_keys={"a", "b"})
    assert result.is_complete
    assert result.missing_metric_keys == frozenset()


def test_evaluate_completeness_flags_missing_metrics():
    result = evaluate_completeness("FRED", expected_metric_keys={"a", "b", "c"}, present_metric_keys={"a"})
    assert not result.is_complete
    assert result.missing_metric_keys == frozenset({"b", "c"})


def test_evaluate_completeness_ignores_unexpected_extra_metrics():
    """Een metric die WEL binnenkomt maar niet verwacht was, is geen
    completeness-probleem (dat zou eerder een configuratiefout zijn) --
    alleen ONTBREKENDE verwachte metrics tellen mee."""
    result = evaluate_completeness("FRED", expected_metric_keys={"a"}, present_metric_keys={"a", "verrassing"})
    assert result.is_complete


# -- Validity: waarde valt buiten een plausibel bereik/type --

def test_evaluate_validity_accepts_a_number_without_range():
    result = evaluate_validity("vix", 18.5)
    assert result.is_valid
    assert result.reason is None


def test_evaluate_validity_rejects_non_numeric_value():
    result = evaluate_validity("vix", "achttien-komma-vijf")
    assert not result.is_valid
    assert "getal" in result.reason


def test_evaluate_validity_accepts_value_within_range():
    result = evaluate_validity("unemployment_rate", 4.2, valid_range=(0.0, 30.0))
    assert result.is_valid


def test_evaluate_validity_rejects_value_outside_range():
    result = evaluate_validity("unemployment_rate", -1.5, valid_range=(0.0, 30.0))
    assert not result.is_valid
    assert "bereik" in result.reason


def test_evaluate_validity_accepts_range_boundary_values():
    assert evaluate_validity("x", 0.0, valid_range=(0.0, 30.0)).is_valid
    assert evaluate_validity("x", 30.0, valid_range=(0.0, 30.0)).is_valid


# -- Consistency: een afgeleide claim klopt niet met zijn eigen input --

def test_evaluate_consistency_matches_within_tolerance():
    result = evaluate_consistency("Afwijking t.o.v. Taylor Rule", stated_value=1.20, recomputed_value=1.2000001)
    assert result.is_consistent


def test_evaluate_consistency_flags_mismatch():
    result = evaluate_consistency("Afwijking t.o.v. Taylor Rule", stated_value=1.20, recomputed_value=0.80)
    assert not result.is_consistent


# -- Continuity: een gat in de tijdreeks, los van staleness van de laatste waarde --

def test_evaluate_continuity_no_gap_for_regular_cadence():
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    timestamps = [datetime(2026, m, 1, tzinfo=timezone.utc) for m in (1, 2, 3, 4)]
    result = evaluate_continuity("FRED", "cpi", timestamps, expected_cadence=timedelta(days=31), now=now)
    assert not result.has_gap


def test_evaluate_continuity_flags_a_gap_even_when_latest_point_is_fresh():
    """Kernonderscheid met staleness: de LAATSTE waarde is vers (recent),
    maar er zit een gat VERDER TERUG in de reeks -- staleness alleen kijkt
    naar 'hoe oud is de laatste pull nu', dit kijkt naar de hele reeks."""
    now = datetime(2026, 6, 2, tzinfo=timezone.utc)
    timestamps = [
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 2, 1, tzinfo=timezone.utc),
        # -- gat van januari/februari naar juni, ruim boven de maandelijkse cadans --
        datetime(2026, 6, 1, tzinfo=timezone.utc),  # de laatste waarde is hier vers t.o.v. `now`
    ]
    result = evaluate_continuity("FRED", "cpi", timestamps, expected_cadence=timedelta(days=31), now=now)
    assert result.has_gap
    assert len(result.gaps) == 1
    assert result.gaps[0].before == datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert result.gaps[0].after == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_evaluate_continuity_tolerates_normal_jitter():
    """Een paar dagen speling t.o.v. de verwachte cadans is normaal
    (release-datums schuiven), geen gat -- vandaar tolerance_factor."""
    now = datetime(2026, 3, 5, tzinfo=timezone.utc)
    timestamps = [
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 2, 3, tzinfo=timezone.utc),  # iets later dan precies 31 dagen
        datetime(2026, 3, 4, tzinfo=timezone.utc),
    ]
    result = evaluate_continuity("FRED", "cpi", timestamps, expected_cadence=timedelta(days=31), tolerance_factor=1.5, now=now)
    assert not result.has_gap


def test_evaluate_continuity_no_gap_with_fewer_than_two_points():
    result = evaluate_continuity("FRED", "cpi", [datetime(2026, 1, 1, tzinfo=timezone.utc)], expected_cadence=timedelta(days=31))
    assert not result.has_gap


# -- QualityStatus-rollup: worst-of over de meegegeven signalen --

def test_rollup_quality_status_healthy_when_all_signals_clean():
    status = rollup_quality_status(
        source_status=HealthStatus.OK,
        completeness=evaluate_completeness("FRED", {"a"}, {"a"}),
        validity=evaluate_validity("a", 1.0),
        consistency=evaluate_consistency("a", 1.0, 1.0),
        continuity=evaluate_continuity("FRED", "a", [datetime(2026, 1, 1, tzinfo=timezone.utc)], timedelta(days=31)),
    )
    assert status == QualityStatus.HEALTHY


def test_rollup_quality_status_degraded_on_stale_source():
    status = rollup_quality_status(source_status=HealthStatus.STALE)
    assert status == QualityStatus.DEGRADED


def test_rollup_quality_status_degraded_on_incomplete_snapshot():
    status = rollup_quality_status(completeness=evaluate_completeness("FRED", {"a", "b"}, {"a"}))
    assert status == QualityStatus.DEGRADED


def test_rollup_quality_status_degraded_on_continuity_gap():
    result = evaluate_continuity(
        "FRED", "cpi",
        [datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 6, 1, tzinfo=timezone.utc)],
        expected_cadence=timedelta(days=31),
    )
    assert rollup_quality_status(continuity=result) == QualityStatus.DEGRADED


def test_rollup_quality_status_invalid_on_unreachable_source():
    status = rollup_quality_status(source_status=HealthStatus.UNREACHABLE)
    assert status == QualityStatus.INVALID


def test_rollup_quality_status_invalid_on_bad_validity():
    status = rollup_quality_status(validity=evaluate_validity("a", -5.0, valid_range=(0.0, 10.0)))
    assert status == QualityStatus.INVALID


def test_rollup_quality_status_invalid_on_inconsistent_claim():
    status = rollup_quality_status(consistency=evaluate_consistency("a", 1.0, 5.0))
    assert status == QualityStatus.INVALID


def test_rollup_quality_status_takes_the_worst_of_multiple_signals():
    status = rollup_quality_status(
        source_status=HealthStatus.OK,  # HEALTHY
        validity=evaluate_validity("a", -5.0, valid_range=(0.0, 10.0)),  # INVALID -- moet winnen
    )
    assert status == QualityStatus.INVALID


def test_rollup_quality_status_requires_at_least_one_signal():
    with pytest.raises(ValueError):
        rollup_quality_status()
