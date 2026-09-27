from datetime import datetime, timezone
from unittest.mock import MagicMock

import agents.economic_agent as eca
from storage.schema import get_source, init_db, latest_data_health


def test_fetch_snapshot_without_api_key_returns_error(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    result = eca.fetch_snapshot()
    assert "error" in result


def test_fetch_snapshot_returns_available_series(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        if params["series_id"] == "ICSA":
            resp.json = lambda: {"observations": [{"value": "220000", "date": "2026-09-20"}]}
        else:
            resp.json = lambda: {"observations": [{"value": ".", "date": "2026-09-01"}]}  # FRED-placeholder voor ontbrekend
        return resp

    monkeypatch.setattr(eca.requests, "get", fake_get)
    result = eca.fetch_snapshot()

    assert "error" not in result
    assert result["initial_claims"]["value"] == "220000"
    assert "unemployment_rate" not in result  # placeholder-waarde wordt overgeslagen, geen gok


def test_fetch_snapshot_all_series_fail_returns_error(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")
    monkeypatch.setattr(eca.requests, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("netwerkfout")))
    result = eca.fetch_snapshot()
    assert "error" in result


def test_monitor_wires_into_run_monitoring(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(eca, "fetch_snapshot", lambda: {"initial_claims": {"value": "220000", "date": "2026-09-20"}})

    output, triggers = eca.monitor(conn, now=now)
    assert output is not None
    assert output.domain == "economic"
    assert triggers == []


def test_monitor_registers_its_own_source_key_not_shared_with_other_fred_agents(tmp_path, monkeypatch):
    """Roadmap 1.4: dezelfde reden als monetary_policy_agent.py/
    financial_agent.py -- deze agent gebruikt ook FRED, maar met een eigen
    source_key ("FRED:economic"), niet de kale providernaam en niet
    "FRED:monetary_policy" (die UNRATE ook al gebruikt)."""
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(eca, "fetch_snapshot", lambda: {"initial_claims": {"value": "220000", "date": "2026-09-20"}})

    eca.monitor(conn, now=now)

    source = get_source(conn, eca.SOURCE_KEY)
    assert source is not None
    assert source.provider == "FRED"
    assert source.domain == "economic"
    assert source.max_age == eca.MAX_AGE
    assert eca.SOURCE_KEY == "FRED:economic"

    assert latest_data_health(conn, eca.SOURCE_KEY) is not None
    assert latest_data_health(conn, "FRED") is None
    assert latest_data_health(conn, "FRED:monetary_policy") is None


def test_deep_dive_wires_into_run_deep_dive(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(eca, "fetch_snapshot", lambda: {"initial_claims": {"value": "220000", "date": "x"}})
    output, triggers = eca.monitor(conn, now=now)

    # Geen unemployment_rate-claim -> Sahm Rule-verrijking wordt niet eens
    # geprobeerd; deze test dekt alleen de basale deep_dive-bedrading.
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Neutrale duiding van de arbeidsmarktdata.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = eca.deep_dive(conn, client, output.claims, triggers, now=now)
    assert deep_dive_output.domain == "economic"


def test_fetch_unrate_history_returns_none_without_enough_observations(monkeypatch):
    def fake_get(url, params, timeout):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"observations": [{"value": "4.0", "date": "2026-01-01"}] * 5}  # te weinig
        return resp

    monkeypatch.setattr(eca.requests, "get", fake_get)
    assert eca._fetch_unrate_history("fake-key") is None


def test_fetch_unrate_history_happy_path(monkeypatch):
    def fake_get(url, params, timeout):
        assert params["series_id"] == "UNRATE"
        assert params["sort_order"] == "asc"
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: {
            "observations": [{"value": f"{4.0 + i * 0.01}", "date": f"2025-{i + 1:02d}-01"} for i in range(14)]
        }
        return resp

    monkeypatch.setattr(eca.requests, "get", fake_get)
    history = eca._fetch_unrate_history("fake-key")
    assert history is not None
    assert len(history) == 14
    assert history[0] == 4.0  # oudste eerst, zelfde volgorde als sahm_rule.compute_sahm_rule() verwacht


def test_deep_dive_adds_sahm_rule_claims_when_unemployment_claim_present(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(eca, "fetch_snapshot", lambda: {"unemployment_rate": {"value": "5.0", "date": "x"}})
    output, triggers = eca.monitor(conn, now=now)

    # 12 maanden stabiel op 3.5%, dan een scherpe stijging -- triggert de Sahm Rule.
    history = [3.5] * 12 + [4.3, 4.6, 5.0]
    monkeypatch.setenv("FRED_API_KEY", "fake-key")
    monkeypatch.setattr(eca, "_fetch_unrate_history", lambda api_key, count=14: history)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Duiding met Sahm Rule-context.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = eca.deep_dive(conn, client, output.claims, triggers, now=now)

    value_claim = next((c for c in deep_dive_output.claims if c.claim == "Sahm Rule-waarde"), None)
    classification_claim = next((c for c in deep_dive_output.claims if c.claim == "Sahm Rule-classificatie"), None)
    assert value_claim is not None and value_claim.value > 0.5
    assert classification_claim is not None and "ACTIEF" in classification_claim.value


def test_deep_dive_no_sahm_rule_claims_when_unemployment_claim_absent(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(eca, "fetch_snapshot", lambda: {"initial_claims": {"value": "220000", "date": "x"}})
    output, triggers = eca.monitor(conn, now=now)

    calls = []
    monkeypatch.setenv("FRED_API_KEY", "fake-key")
    monkeypatch.setattr(eca, "_fetch_unrate_history", lambda *a, **k: calls.append(1))

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Duiding zonder Sahm Rule-context.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = eca.deep_dive(conn, client, output.claims, triggers, now=now)
    assert calls == []  # _fetch_unrate_history wordt niet eens aangeroepen zonder unemployment_rate-claim
    assert not any(c.claim.startswith("Sahm Rule") for c in deep_dive_output.claims)


def test_deep_dive_no_sahm_rule_claims_when_history_unavailable(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(eca, "fetch_snapshot", lambda: {"unemployment_rate": {"value": "4.1", "date": "x"}})
    output, triggers = eca.monitor(conn, now=now)

    monkeypatch.setenv("FRED_API_KEY", "fake-key")
    monkeypatch.setattr(eca, "_fetch_unrate_history", lambda *a, **k: None)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Duiding zonder Sahm Rule-context.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = eca.deep_dive(conn, client, output.claims, triggers, now=now)
    assert not any(c.claim.startswith("Sahm Rule") for c in deep_dive_output.claims)
