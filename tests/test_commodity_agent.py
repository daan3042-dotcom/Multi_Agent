from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import agents.commodity_agent as ca
from storage.schema import init_db


def test_fetch_snapshot_without_api_key_returns_error(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    result = ca.fetch_snapshot()
    assert "error" in result


def test_fetch_snapshot_returns_available_commodities(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        if params["function"] == "COPPER":
            resp.json = lambda: {"data": [{"date": "2026-09-01", "value": "4.25"}, {"date": "2026-08-01", "value": "4.10"}]}
        else:
            resp.json = lambda: {"data": [{"date": "2026-09-01", "value": "."}]}  # placeholder, geen echte data
        return resp

    monkeypatch.setattr(ca.requests, "get", fake_get)
    result = ca.fetch_snapshot()

    assert "error" not in result
    assert result["copper"]["value"] == "4.25"
    assert "wti" not in result


def test_fetch_snapshot_all_commodities_fail_returns_error(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        raise ConnectionError("netwerkfout")

    monkeypatch.setattr(ca.requests, "get", fake_get)
    result = ca.fetch_snapshot()
    assert "error" in result


def test_monitor_wires_into_run_monitoring(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(ca, "fetch_snapshot", lambda: {"copper": {"value": "4.25", "date": "2026-09-01"}})

    output, triggers = ca.monitor(conn, now=now)
    assert output is not None
    assert output.domain == "commodity"
    assert triggers == []


def test_monitor_triggers_on_significant_price_move(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=30)

    monkeypatch.setattr(ca, "fetch_snapshot", lambda: {"copper": {"value": "4.10", "date": "x"}})
    ca.monitor(conn, now=t1)

    monkeypatch.setattr(ca, "fetch_snapshot", lambda: {"copper": {"value": "4.45", "date": "y"}})
    output, triggers = ca.monitor(conn, now=t2)

    assert len(triggers) == 1
    assert triggers[0].metric_key == "copper"
    assert triggers[0].severity == "high"


def test_deep_dive_wires_into_run_deep_dive(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(ca, "fetch_snapshot", lambda: {"copper": {"value": "4.45", "date": "x"}})
    output, triggers = ca.monitor(conn, now=now)

    # Ontkoppeld van de moving-average-verrijking -- die heeft zijn eigen
    # tests hieronder; voorkomt ook een echte netwerkaanroep als
    # ALPHAVANTAGE_API_KEY toevallig in de omgeving staat.
    monkeypatch.setattr(ca, "_fetch_commodity_data", lambda function_name, api_key: None)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Neutrale duiding van de koperprijs.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = ca.deep_dive(conn, client, output.claims, triggers, now=now)
    assert deep_dive_output.domain == "commodity"


def test_deep_dive_adds_moving_average_deviation_claim_when_available(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")
    monkeypatch.setattr(ca, "fetch_snapshot", lambda: {"copper": {"value": "4.40", "date": "x"}})
    output, triggers = ca.monitor(conn, now=now)

    history = [{"value": "4.40"}, {"value": "4.20"}, {"value": "4.00"}, {"value": "4.10"}, {"value": "4.00"}, {"value": "4.10"}]
    monkeypatch.setattr(ca, "_fetch_commodity_data", lambda function_name, api_key: history)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Duiding met voortschrijdend-gemiddelde-context.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = ca.deep_dive(conn, client, output.claims, triggers, now=now)

    deviation_claim = next((c for c in deep_dive_output.claims if c.claim.startswith("Afwijking")), None)
    assert deviation_claim is not None
    # gemiddelde van [4.40, 4.20, 4.00, 4.10, 4.00, 4.10] = 4.1333..., afwijking van 4.40 t.o.v. dat gemiddelde
    assert deviation_claim.value > 0  # huidige waarde ligt boven het gemiddelde


def test_deep_dive_no_deviation_claim_when_history_too_short(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")
    monkeypatch.setattr(ca, "fetch_snapshot", lambda: {"copper": {"value": "4.40", "date": "x"}})
    output, triggers = ca.monitor(conn, now=now)

    monkeypatch.setattr(ca, "_fetch_commodity_data", lambda function_name, api_key: [{"value": "4.40"}])  # te weinig punten

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Duiding zonder gemiddelde-context.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = ca.deep_dive(conn, client, output.claims, triggers, now=now)
    assert not any(c.claim.startswith("Afwijking") for c in deep_dive_output.claims)
