from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

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

    # Ontkoppeld van de Taylor Rule-verrijking -- die heeft zijn eigen
    # tests hieronder; dit test alleen de basale deep_dive-bedrading, en
    # voorkomt een eventuele echte netwerkaanroep als FRED_API_KEY
    # toevallig al in de omgeving staat.
    monkeypatch.setattr(mpa, "_fetch_taylor_rule_inputs", lambda: None)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Neutrale duiding van de Fed funds rate.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = mpa.deep_dive(conn, client, output.claims, triggers, now=now)
    assert deep_dive_output.domain == "monetary_policy"


def test_fetch_taylor_rule_inputs_without_api_key_returns_none(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert mpa._fetch_taylor_rule_inputs() is None


def test_fetch_taylor_rule_inputs_happy_path(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        series_id = params["series_id"]
        if series_id == "CPIAUCSL" and params["limit"] == 1:
            resp.json = lambda: {"observations": [{"value": "312.0", "date": "2026-08-01"}]}
        elif series_id == "CPIAUCSL" and params["limit"] == 13:
            resp.json = lambda: {"observations": [{"value": f"{312.0 - i}", "date": f"2026-{8-i if i < 8 else 1}-01"} for i in range(13)]}
        elif series_id == "GDPC1":
            resp.json = lambda: {"observations": [{"value": "22500.0", "date": "2026-04-01"}]}
        elif series_id == "GDPPOT":
            resp.json = lambda: {"observations": [{"value": "22000.0", "date": "2026-04-01"}]}
        else:
            resp.json = lambda: {"observations": []}
        return resp

    monkeypatch.setattr(mpa.requests, "get", fake_get)
    result = mpa._fetch_taylor_rule_inputs()

    assert result is not None
    assert result["output_gap_pct"] == pytest.approx((22500.0 - 22000.0) / 22000.0 * 100)
    # CPI nu (index 0 van de 13-lange lijst) vs. 12 maanden terug (index 12)
    cpi_now = 312.0
    cpi_year_ago = 312.0 - 12
    assert result["inflation_yoy_pct"] == pytest.approx((cpi_now - cpi_year_ago) / cpi_year_ago * 100)


def test_fetch_taylor_rule_inputs_missing_gdp_data_returns_none(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        series_id = params["series_id"]
        if series_id == "CPIAUCSL":
            resp.json = lambda: {"observations": [{"value": "312.0", "date": "2026-08-01"}] * params["limit"]}
        else:
            resp.json = lambda: {"observations": []}  # GDPC1/GDPPOT niet beschikbaar
        return resp

    monkeypatch.setattr(mpa.requests, "get", fake_get)
    assert mpa._fetch_taylor_rule_inputs() is None


def test_deep_dive_adds_taylor_rule_claims_when_inputs_available(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(mpa, "fetch_snapshot", lambda: {"fed_funds_rate": {"value": "5.50", "date": "x"}})
    output, triggers = mpa.monitor(conn, now=now)

    monkeypatch.setattr(
        mpa, "_fetch_taylor_rule_inputs",
        lambda: {"inflation_yoy_pct": 3.0, "output_gap_pct": 0.0, "cpi_date": "2026-08-01", "gdp_date": "2026-04-01"},
    )
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Duiding met Taylor Rule-context.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = mpa.deep_dive(conn, client, output.claims, triggers, now=now)

    implied = next((c for c in deep_dive_output.claims if c.claim == "Taylor Rule-impliciete Fed funds rate"), None)
    deviation = next((c for c in deep_dive_output.claims if c.claim.startswith("Afwijking daadwerkelijke")), None)
    assert implied is not None and implied.value == 5.5  # 2 + 3 + 0.5(3-2) + 0.5(0)
    assert deviation is not None and deviation.value == 0.0  # 5.50 - 5.50


def test_deep_dive_no_taylor_rule_claims_when_inputs_unavailable(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(mpa, "fetch_snapshot", lambda: {"fed_funds_rate": {"value": "5.50", "date": "x"}})
    output, triggers = mpa.monitor(conn, now=now)

    monkeypatch.setattr(mpa, "_fetch_taylor_rule_inputs", lambda: None)
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Duiding zonder Taylor Rule-context.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = mpa.deep_dive(conn, client, output.claims, triggers, now=now)
    assert not any(c.claim.startswith("Taylor Rule") or c.claim.startswith("Afwijking daadwerkelijke") for c in deep_dive_output.claims)


def test_deep_dive_no_taylor_rule_claims_when_fed_funds_rate_absent(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(mpa, "fetch_snapshot", lambda: {"unemployment_rate": {"value": "4.1", "date": "x"}})
    output, triggers = mpa.monitor(conn, now=now)

    calls = []
    monkeypatch.setattr(mpa, "_fetch_taylor_rule_inputs", lambda: calls.append(1))
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Duiding.")]
    client.messages.create = lambda **kwargs: response

    mpa.deep_dive(conn, client, output.claims, triggers, now=now)
    assert calls == []  # _fetch_taylor_rule_inputs wordt niet eens aangeroepen zonder fed_funds_rate-claim
