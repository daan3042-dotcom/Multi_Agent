from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import agents.monetary_policy_agent as mpa
from storage.schema import init_db


def test_fetch_snapshot_without_api_key_returns_error(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    result = mpa.fetch_snapshot()
    assert "error" in result


def test_fetch_snapshot_returns_available_series(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        if params["series_id"] == "FEDFUNDS":
            resp.json = lambda: {"observations": [{"value": "5.50", "date": "2026-01-01"}]}
        else:
            resp.json = lambda: {"observations": [{"value": ".", "date": "2026-01-01"}]}  # FRED-placeholder voor ontbrekend
        return resp

    monkeypatch.setattr(mpa.requests, "get", fake_get)
    result = mpa.fetch_snapshot()

    assert "error" not in result
    assert result["fed_funds_rate"]["value"] == "5.50"
    assert "10y_treasury_yield" not in result  # placeholder-waarde wordt overgeslagen, geen gok


def test_fetch_snapshot_all_series_fail_returns_error(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        raise ConnectionError("netwerkfout")

    monkeypatch.setattr(mpa.requests, "get", fake_get)
    result = mpa.fetch_snapshot()
    assert "error" in result


def test_monitor_wires_into_run_monitoring(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(mpa, "fetch_snapshot", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}})

    output, triggers = mpa.monitor(conn, now=now)
    assert output is not None
    assert output.domain == "monetary_policy"
    assert triggers == []


def test_deep_dive_wires_into_run_deep_dive(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(mpa, "fetch_snapshot", lambda: {"fed_funds_rate": {"value": "5.85", "date": "x"}})
    output, triggers = mpa.monitor(conn, now=now)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Neutrale duiding van de Fed funds rate.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = mpa.deep_dive(conn, client, output.claims, triggers, now=now)
    assert deep_dive_output.domain == "monetary_policy"
