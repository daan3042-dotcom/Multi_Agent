from datetime import datetime, timedelta, timezone

from health.data_health import HealthStatus
from health.system_health import sources_from_registry, system_health
from storage.schema import init_db, record_agent_run, record_data_health, register_source


def _db(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def test_database_component_is_ok_for_a_working_connection(tmp_path):
    conn = _db(tmp_path)
    report = system_health(conn, sources={}, domains=[])
    assert report.status_for("database") == HealthStatus.OK


def test_source_component_reuses_existing_data_health(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    record_data_health(conn, "FRED", now, success=True)

    report = system_health(conn, sources={"FRED": timedelta(days=2)}, domains=[], now=now)
    assert report.status_for("source:FRED") == HealthStatus.OK


def test_source_component_stale_beyond_max_age(tmp_path):
    conn = _db(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(days=10)
    now = datetime.now(timezone.utc)
    record_data_health(conn, "FRED", old, success=True)

    report = system_health(conn, sources={"FRED": timedelta(days=2)}, domains=[], now=now)
    assert report.status_for("source:FRED") == HealthStatus.STALE


def test_source_component_unknown_without_any_record(tmp_path):
    conn = _db(tmp_path)
    report = system_health(conn, sources={"FRED": timedelta(days=2)}, domains=[])
    assert report.status_for("source:FRED") == HealthStatus.UNKNOWN


def test_ingestion_component_unknown_without_any_run(tmp_path):
    conn = _db(tmp_path)
    report = system_health(conn, sources={}, domains=["monetary_policy"])
    assert report.status_for("ingestion:monetary_policy") == HealthStatus.UNKNOWN


def test_ingestion_component_ok_after_successful_monitoring_run(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    record_agent_run(conn, "monetary_policy", "monitoring", now, success=True)

    report = system_health(conn, sources={}, domains=["monetary_policy"], now=now)
    assert report.status_for("ingestion:monetary_policy") == HealthStatus.OK


def test_ingestion_component_unreachable_after_failed_monitoring_run(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    record_agent_run(conn, "monetary_policy", "monitoring", now, success=False, error="FRED_API_KEY niet gevonden")

    report = system_health(conn, sources={}, domains=["monetary_policy"], now=now)
    assert report.status_for("ingestion:monetary_policy") == HealthStatus.UNREACHABLE


def test_ingestion_component_reflects_only_the_most_recent_run(tmp_path):
    """Een oude mislukking die inmiddels is opgevolgd door een succesvolle
    run mag niet als huidige status blijven hangen."""
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(minutes=5)
    record_agent_run(conn, "monetary_policy", "monitoring", t1, success=False, error="timeout")
    record_agent_run(conn, "monetary_policy", "monitoring", t2, success=True)

    report = system_health(conn, sources={}, domains=["monetary_policy"], now=t2)
    assert report.status_for("ingestion:monetary_policy") == HealthStatus.OK


def test_llm_component_reflects_latest_deep_dive_run_across_domains(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    record_agent_run(conn, "monetary_policy", "deep_dive", now, success=True)
    record_agent_run(conn, "financial", "deep_dive", now, success=False, error="API-fout")

    report = system_health(conn, sources={}, domains=["monetary_policy", "financial"], now=now)
    # worst-of over beide domeinen: één mislukte deep-dive maakt de LLM-status UNREACHABLE
    assert report.status_for("llm") == HealthStatus.UNREACHABLE


def test_llm_component_unknown_without_any_deep_dive_run(tmp_path):
    conn = _db(tmp_path)
    report = system_health(conn, sources={}, domains=["monetary_policy"])
    assert report.status_for("llm") == HealthStatus.UNKNOWN


def test_agent_component_combines_monitoring_and_deep_dive_status(tmp_path):
    """agent:<domain> is de OVERALL status -- ook slecht als alleen de
    deep-dive-kant faalt terwijl de monitoring-pull prima werkt."""
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    record_agent_run(conn, "monetary_policy", "monitoring", now, success=True)
    record_agent_run(conn, "monetary_policy", "deep_dive", now, success=False, error="API-fout")

    report = system_health(conn, sources={}, domains=["monetary_policy"], now=now)
    assert report.status_for("ingestion:monetary_policy") == HealthStatus.OK
    assert report.status_for("agent:monetary_policy") == HealthStatus.UNREACHABLE


def test_trigger_component_derives_from_worst_ingestion_status(tmp_path):
    """De trigger-laag heeft geen eigen, apart bijgehouden faalstatus --
    trigger-evaluatie draait inline binnen run_monitoring(), dus 'trigger'
    volgt uit de worst-of van alle ingestion-statussen."""
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    record_agent_run(conn, "monetary_policy", "monitoring", now, success=True)
    record_agent_run(conn, "currency", "monitoring", now, success=False, error="netwerkfout")

    report = system_health(conn, sources={}, domains=["monetary_policy", "currency"], now=now)
    assert report.status_for("trigger") == HealthStatus.UNREACHABLE


def test_trigger_component_unknown_without_any_domain(tmp_path):
    conn = _db(tmp_path)
    report = system_health(conn, sources={}, domains=[])
    assert report.status_for("trigger") == HealthStatus.UNKNOWN


def test_overall_status_is_worst_of_all_components(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    record_data_health(conn, "FRED", now, success=True)
    record_agent_run(conn, "monetary_policy", "monitoring", now, success=False, error="timeout")

    report = system_health(conn, sources={"FRED": timedelta(days=2)}, domains=["monetary_policy"], now=now)
    assert report.overall_status == HealthStatus.UNREACHABLE


def test_overall_status_ok_when_everything_healthy(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    record_data_health(conn, "FRED", now, success=True)
    record_agent_run(conn, "monetary_policy", "monitoring", now, success=True)
    record_agent_run(conn, "monetary_policy", "deep_dive", now, success=True)

    report = system_health(conn, sources={"FRED": timedelta(days=2)}, domains=["monetary_policy"], now=now)
    assert report.overall_status == HealthStatus.OK


def test_status_for_unknown_component_returns_none(tmp_path):
    conn = _db(tmp_path)
    report = system_health(conn, sources={}, domains=[])
    assert report.status_for("does_not_exist") is None


def test_sources_from_registry_derives_max_age_dict(tmp_path):
    conn = _db(tmp_path)
    register_source(conn, "FRED:monetary_policy", provider="FRED", domain="monetary_policy", max_age=timedelta(days=35))
    register_source(conn, "FRED:financial", provider="FRED", domain="financial", max_age=timedelta(days=10))

    assert sources_from_registry(conn) == {
        "FRED:monetary_policy": timedelta(days=35),
        "FRED:financial": timedelta(days=10),
    }


def test_sources_from_registry_empty_without_registrations(tmp_path):
    conn = _db(tmp_path)
    assert sources_from_registry(conn) == {}


def test_system_health_with_registry_sources_keeps_two_fred_consumers_independent(tmp_path):
    """De kern-regressietest voor de aanleiding van 1.4: monetary_policy en
    financial delen de PROVIDER "FRED" maar hebben nu elk hun eigen
    source_key -- de een succesvol en vers, de ander allang niet meer
    succesvol gepolld, mag elkaars status niet meer beïnvloeden."""
    conn = _db(tmp_path)
    register_source(conn, "FRED:monetary_policy", provider="FRED", domain="monetary_policy", max_age=timedelta(days=35))
    register_source(conn, "FRED:financial", provider="FRED", domain="financial", max_age=timedelta(days=10))

    now = datetime.now(timezone.utc)
    long_ago = now - timedelta(days=20)  # ruim voorbij financial's 10-dagen max_age, ruim binnen monetary_policy's 35

    record_data_health(conn, "FRED:monetary_policy", now, success=True)
    record_data_health(conn, "FRED:financial", long_ago, success=True)

    report = system_health(conn, sources=sources_from_registry(conn), domains=[], now=now)
    assert report.status_for("source:FRED:monetary_policy") == HealthStatus.OK
    assert report.status_for("source:FRED:financial") == HealthStatus.STALE
