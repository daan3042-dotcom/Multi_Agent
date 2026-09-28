from datetime import datetime, timezone

from health.data_health import HealthCheckResult, HealthStatus
from triggers.trigger_engine import evaluate_data_health, evaluate_revision, evaluate_surprise, evaluate_threshold


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


def test_evaluate_revision_always_fires_no_tolerance():
    """In tegenstelling tot evaluate_surprise() kent een revisie geen
    tolerantie -- elke gewijzigde waarde voor een al-gerapporteerde
    periode is op zichzelf al nieuws."""
    event = evaluate_revision(
        domain="economic", metric_key="gdp_growth", previous_value=2.5, revised_value=2.1,
        reason="Revisie: BBP-groei voor periode 2026-05-01 gewijzigd van 2.5 naar 2.1",
    )
    assert event.domain == "economic"
    assert event.metric_key == "gdp_growth"
    assert event.observed_value == 2.1
    assert event.threshold == 2.5
    assert event.severity == "medium"
    assert "Revisie" in event.reason


# --- Completeness-trigger (roadmap 1.3, gewired 28-09-2026) ---


def _completeness(source, verwacht, aanwezig):
    from health.data_health import evaluate_completeness

    return evaluate_completeness(source, verwacht, aanwezig)


def test_volledige_pull_geeft_geen_trigger():
    """Het correcte geval: alles binnen, niets te melden."""
    from triggers.trigger_engine import evaluate_completeness_result

    result = _completeness("FRED:economic", ["a", "b", "c"], ["a", "b", "c"])
    assert evaluate_completeness_result("economic", result) is None


def test_gedeeltelijke_pull_geeft_een_trigger_met_de_missende_reeksen():
    """REGRESSIE op de live meting van 28-09-2026: de sector agent haalde 2
    van de 11 ETF's op en rapporteerde success=True, omdat fetch_snapshot()
    alleen faalt als GEEN ENKELE reeks lukt. Zonder deze trigger is een bron
    die voor 80% wegvalt niet te onderscheiden van een gezonde dag."""
    from triggers.trigger_engine import evaluate_completeness_result

    result = _completeness("AV:sector", ["xlk", "xlf", "xle", "xlv"], ["xlk", "xlf"])
    trigger = evaluate_completeness_result("sector", result)

    assert trigger is not None
    assert trigger.metric_key is None  # een pull-probleem, geen metric-probleem
    assert trigger.observed_value == 2
    assert trigger.threshold == 4
    assert "xle" in trigger.reason and "xlv" in trigger.reason


def test_een_trigger_per_cyclus_niet_een_per_missende_reeks():
    """Negen missende ETF's zijn één probleem, niet negen problemen."""
    from triggers.trigger_engine import evaluate_completeness_result

    verwacht = [f"etf_{i}" for i in range(11)]
    result = _completeness("AV:sector", verwacht, ["etf_0", "etf_1"])
    trigger = evaluate_completeness_result("sector", result)

    assert trigger is not None
    assert trigger.observed_value == 2


def test_severity_schaalt_mee_met_hoeveel_er_ontbreekt():
    """Een enkele reeks die een keer niet meekomt is ruis; de helft die
    wegvalt is een storing. De grens ligt op 50%."""
    from triggers.trigger_engine import evaluate_completeness_result

    weinig = _completeness("FRED:monetary_policy", ["a", "b", "c", "d"], ["a", "b", "c"])
    veel = _completeness("AV:sector", ["a", "b", "c", "d"], ["a", "b"])

    assert evaluate_completeness_result("monetary_policy", weinig).severity == "medium"
    assert evaluate_completeness_result("sector", veel).severity == "high"


def test_reden_is_stabiel_tussen_runs():
    """De missende sleutels worden gesorteerd, zodat dezelfde storing niet
    elke run een andere tekst oplevert -- anders is een reden niet te
    vergelijken tussen dagen."""
    from triggers.trigger_engine import evaluate_completeness_result

    een = evaluate_completeness_result("sector", _completeness("s", ["a", "b", "c"], ["a"])).reason
    twee = evaluate_completeness_result("sector", _completeness("s", ["c", "b", "a"], ["a"])).reason
    assert een == twee
