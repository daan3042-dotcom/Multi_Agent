from datetime import datetime, timezone
from unittest.mock import MagicMock

import agents.currency_agent as ca
from storage.schema import get_source, init_db


def test_fetch_snapshot_without_api_key_returns_error(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    result = ca.fetch_snapshot()
    assert "error" in result


def test_fetch_snapshot_returns_available_pairs(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        if params["from_currency"] == "EUR":
            resp.json = lambda: {
                "Realtime Currency Exchange Rate": {"5. Exchange Rate": "1.0850", "6. Last Refreshed": "2026-01-01"}
            }
        else:
            resp.json = lambda: {}  # geen data voor dit paar
        return resp

    monkeypatch.setattr(ca.requests, "get", fake_get)
    result = ca.fetch_snapshot()

    assert "error" not in result
    assert result["eur_usd"]["value"] == "1.0850"
    assert "usd_jpy" not in result


def test_fetch_snapshot_all_pairs_fail_returns_error(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        raise ConnectionError("netwerkfout")

    monkeypatch.setattr(ca.requests, "get", fake_get)
    result = ca.fetch_snapshot()
    assert "error" in result


def test_monitor_wires_into_run_monitoring(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(ca, "fetch_snapshot", lambda: {"eur_usd": {"value": "1.0850", "date": "2026-01-01"}})

    output, triggers = ca.monitor(conn, now=now)
    assert output is not None
    assert output.domain == "currency"
    assert triggers == []


def test_monitor_registers_itself_in_the_source_registry(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(ca, "fetch_snapshot", lambda: {"eur_usd": {"value": "1.0850", "date": "2026-01-01"}})

    ca.monitor(conn, now=now)

    source = get_source(conn, ca.SOURCE_KEY)
    assert source is not None
    assert source.provider == "ALPHA_VANTAGE_FX"
    assert source.domain == "currency"
    assert source.max_age == ca.MAX_AGE
