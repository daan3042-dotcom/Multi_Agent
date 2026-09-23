from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from agents.base import MetricSpec, run_deep_dive, run_monitoring
from contract.output_contract import Mode
from storage.schema import init_db

SPECS = {"fed_funds_rate": MetricSpec(label="Fed funds rate", tolerance=0.25, severity="high")}


def _db(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def test_run_monitoring_saves_claims_and_no_trigger_on_first_observation(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    fetch = lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}

    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", fetch, SPECS, timedelta(days=35), now=now)

    assert output is not None
    assert output.mode == Mode.MONITORING
    assert output.claims[0].value == 5.5
    assert triggers == []  # eerste observatie, niets om tegen te vergelijken


def test_run_monitoring_triggers_on_significant_delta(tmp_path):
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=30)

    run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}, SPECS, timedelta(days=35), now=t1)
    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "2026-01-31"}}, SPECS, timedelta(days=35), now=t2)

    assert output is not None
    assert len(triggers) == 1
    assert triggers[0].metric_key == "fed_funds_rate"
    assert triggers[0].severity == "high"


def test_run_monitoring_no_trigger_within_tolerance(tmp_path):
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=30)

    run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}, SPECS, timedelta(days=35), now=t1)
    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.55", "date": "2026-01-31"}}, SPECS, timedelta(days=35), now=t2)

    assert output is not None
    assert triggers == []


def test_run_monitoring_total_failure_produces_data_health_trigger_no_output(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    fetch = lambda: {"error": "FRED_API_KEY niet gevonden"}

    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", fetch, SPECS, timedelta(days=35), now=now)

    assert output is None
    assert len(triggers) == 1
    assert triggers[0].reason.startswith("data_health:")


def test_run_monitoring_fetch_exception_is_caught(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)

    def fetch():
        raise ConnectionError("timeout")

    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", fetch, SPECS, timedelta(days=35), now=now)

    assert output is None
    assert len(triggers) == 1


def _fake_client(response_text):
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text=response_text)]
    client.messages.create = lambda **kwargs: response
    return client


def test_run_deep_dive_saves_narrative_claim_and_needs_review_false_when_clean(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "x"}}, SPECS, timedelta(days=35), now=now)

    client = _fake_client('{"issues": []}')
    deep_dive_output = run_deep_dive(conn, client, "monetary_policy", "systeemprompt", output.claims, [], now=now)

    assert deep_dive_output.mode == Mode.DEEP_DIVE
    assert deep_dive_output.needs_review is False
    assert any(c.claim == "Deep-dive synthese" for c in deep_dive_output.claims)


def test_run_deep_dive_needs_review_true_when_llm_review_flags_issue(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    output, _ = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "x"}}, SPECS, timedelta(days=35), now=now)

    client = MagicMock()
    responses = iter([
        MagicMock(content=[MagicMock(type="text", text="Dit is de deep-dive tekst.")]),
        MagicMock(content=[MagicMock(type="text", text='{"issues": ["gevonden probleem"]}')]),
    ])
    client.messages.create = lambda **kwargs: next(responses)

    deep_dive_output = run_deep_dive(conn, client, "monetary_policy", "systeemprompt", output.claims, [], now=now)
    assert deep_dive_output.needs_review is True
    assert "gevonden probleem" in deep_dive_output.review_issues


def test_run_deep_dive_llm_failure_is_never_silent(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    output, _ = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "x"}}, SPECS, timedelta(days=35), now=now)

    client = MagicMock()
    client.messages.create = lambda **kwargs: (_ for _ in ()).throw(Exception("API-fout"))

    deep_dive_output = run_deep_dive(conn, client, "monetary_policy", "systeemprompt", output.claims, [], now=now)
    assert deep_dive_output.needs_review is True
    assert any("Deep-dive mislukt" in c.claim for c in deep_dive_output.claims)
