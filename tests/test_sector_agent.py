from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import agents.sector_agent as sa
from storage.schema import init_db


def test_fetch_snapshot_without_api_key_returns_error(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    result = sa.fetch_snapshot()
    assert "error" in result


def test_fetch_snapshot_returns_available_series(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        if params["symbol"] == "XLB":
            resp.json = lambda: {"Global Quote": {
                "05. price": "85.32", "07. latest trading day": "2026-09-22", "10. change percent": "1.45%",
            }}
        else:
            resp.json = lambda: {"Global Quote": {}}  # geen data voor deze ETF
        return resp

    monkeypatch.setattr(sa.requests, "get", fake_get)
    result = sa.fetch_snapshot()

    assert "error" not in result
    assert result["xlb_materials"]["value"] == "85.32"
    assert "xlk_technology" not in result


def test_fetch_snapshot_all_series_fail_returns_error(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        raise ConnectionError("netwerkfout")

    monkeypatch.setattr(sa.requests, "get", fake_get)
    result = sa.fetch_snapshot()
    assert "error" in result


def test_monitor_wires_into_run_monitoring(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(sa, "fetch_snapshot", lambda: {"xlb_materials": {"value": "85.32", "date": "2026-09-22"}})

    output, triggers = sa.monitor(conn, now=now)
    assert output is not None
    assert output.domain == "sector"
    assert triggers == []


def test_monitor_triggers_on_significant_price_move(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=1)

    monkeypatch.setattr(sa, "fetch_snapshot", lambda: {"xlb_materials": {"value": "85.00", "date": "x"}})
    sa.monitor(conn, now=t1)

    monkeypatch.setattr(sa, "fetch_snapshot", lambda: {"xlb_materials": {"value": "82.00", "date": "y"}})
    output, triggers = sa.monitor(conn, now=t2)

    assert len(triggers) == 1
    assert triggers[0].metric_key == "xlb_materials"


def test_deep_dive_wires_into_run_deep_dive(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(sa, "fetch_snapshot", lambda: {"xlb_materials": {"value": "82.00", "date": "x"}})
    output, triggers = sa.monitor(conn, now=now)

    # Ontkoppeld van de relatieve-sterkte-verrijking -- die heeft zijn
    # eigen tests hieronder; voorkomt ook een echte netwerkaanroep als
    # ALPHAVANTAGE_API_KEY toevallig in de omgeving staat.
    monkeypatch.setattr(sa, "_fetch_change_percent", lambda symbol, api_key: None)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Neutrale duiding van de XLB-beweging.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = sa.deep_dive(conn, client, output.claims, triggers, now=now)
    assert deep_dive_output.domain == "sector"


def test_deep_dive_adds_relative_strength_claim_when_available(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")
    monkeypatch.setattr(sa, "fetch_snapshot", lambda: {"xlb_materials": {"value": "82.00", "date": "x"}})
    output, triggers = sa.monitor(conn, now=now)

    def fake_change_percent(symbol, api_key):
        return {"XLB": -3.5, "SPY": -0.5}.get(symbol)

    monkeypatch.setattr(sa, "_fetch_change_percent", fake_change_percent)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Duiding met relatieve-sterkte-context.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = sa.deep_dive(conn, client, output.claims, triggers, now=now)

    rel_strength_claim = next((c for c in deep_dive_output.claims if c.claim.startswith("Relatieve sterkte XLB")), None)
    assert rel_strength_claim is not None
    assert rel_strength_claim.value == "underperformt de brede markt (S&P 500) vandaag"


def test_deep_dive_no_relative_strength_claim_when_benchmark_unavailable(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")
    monkeypatch.setattr(sa, "fetch_snapshot", lambda: {"xlb_materials": {"value": "82.00", "date": "x"}})
    output, triggers = sa.monitor(conn, now=now)

    monkeypatch.setattr(sa, "_fetch_change_percent", lambda symbol, api_key: None)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Duiding zonder relatieve-sterkte-context.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = sa.deep_dive(conn, client, output.claims, triggers, now=now)
    assert not any(c.claim.startswith("Relatieve sterkte") for c in deep_dive_output.claims)


def test_deep_dive_fetches_benchmark_only_once_for_multiple_sectors(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")
    monkeypatch.setattr(
        sa, "fetch_snapshot",
        lambda: {"xlb_materials": {"value": "82.00", "date": "x"}, "xle_energy": {"value": "90.00", "date": "x"}},
    )
    output, triggers = sa.monitor(conn, now=now)

    calls = []

    def fake_change_percent(symbol, api_key):
        calls.append(symbol)
        return {"XLB": -3.5, "XLE": 1.0, "SPY": -0.5}.get(symbol)

    monkeypatch.setattr(sa, "_fetch_change_percent", fake_change_percent)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Duiding.")]
    client.messages.create = lambda **kwargs: response

    sa.deep_dive(conn, client, output.claims, triggers, now=now)
    assert calls.count("SPY") == 1
