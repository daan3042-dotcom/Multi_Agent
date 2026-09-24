from datetime import datetime, timezone
from unittest.mock import MagicMock

import agents.financial_agent as fa
from storage.schema import get_source, init_db, latest_data_health


def test_fetch_snapshot_without_api_key_returns_error(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    result = fa.fetch_snapshot()
    assert "error" in result


def test_fetch_snapshot_returns_available_series(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        if params["series_id"] == "VIXCLS":
            resp.json = lambda: {"observations": [{"value": "18.5", "date": "2026-01-01"}]}
        else:
            resp.json = lambda: {"observations": [{"value": ".", "date": "2026-01-01"}]}  # FRED-placeholder voor ontbrekend
        return resp

    monkeypatch.setattr(fa.requests, "get", fake_get)
    result = fa.fetch_snapshot()

    assert "error" not in result
    assert result["vix"]["value"] == "18.5"
    assert "financial_conditions_index" not in result  # placeholder-waarde wordt overgeslagen, geen gok


def test_fetch_snapshot_all_series_fail_returns_error(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        raise ConnectionError("netwerkfout")

    monkeypatch.setattr(fa.requests, "get", fake_get)
    result = fa.fetch_snapshot()
    assert "error" in result


def test_monitor_wires_into_run_monitoring(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(fa, "fetch_snapshot", lambda: {"vix": {"value": "18.5", "date": "2026-01-01"}})

    output, triggers = fa.monitor(conn, now=now)
    assert output is not None
    assert output.domain == "financial"
    assert triggers == []


def test_monitor_registers_itself_in_the_source_registry_with_its_own_key(tmp_path, monkeypatch):
    """Roadmap 1.4: dezelfde provider (FRED) als monetary_policy_agent,
    maar een EIGEN source_key en dus een eigen data_health-geschiedenis --
    dat is de kern van de fix (zie aanleiding in docs/architecture.md)."""
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(fa, "fetch_snapshot", lambda: {"vix": {"value": "18.5", "date": "2026-01-01"}})

    fa.monitor(conn, now=now)

    source = get_source(conn, fa.SOURCE_KEY)
    assert source is not None
    assert source.provider == "FRED"
    assert source.domain == "financial"
    assert source.max_age == fa.MAX_AGE
    assert fa.SOURCE_KEY != "FRED"

    assert latest_data_health(conn, fa.SOURCE_KEY) is not None
    assert latest_data_health(conn, "FRED") is None


def test_monitor_triggers_on_significant_vix_spike(tmp_path, monkeypatch):
    from datetime import timedelta

    conn = init_db(str(tmp_path / "t.db"))
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=1)

    monkeypatch.setattr(fa, "fetch_snapshot", lambda: {"vix": {"value": "18.5", "date": "x"}})
    fa.monitor(conn, now=t1)

    monkeypatch.setattr(fa, "fetch_snapshot", lambda: {"vix": {"value": "27.0", "date": "y"}})
    output, triggers = fa.monitor(conn, now=t2)

    assert len(triggers) == 1
    assert triggers[0].metric_key == "vix"
    assert triggers[0].severity == "medium"


def test_deep_dive_wires_into_run_deep_dive(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(fa, "fetch_snapshot", lambda: {"vix": {"value": "27.0", "date": "x"}})
    output, triggers = fa.monitor(conn, now=now)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Neutrale duiding van de VIX-stijging.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = fa.deep_dive(conn, client, output.claims, triggers, now=now)
    assert deep_dive_output.domain == "financial"


def test_deep_dive_adds_nfci_interpretation_claim_when_nfci_present(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(fa, "fetch_snapshot", lambda: {"financial_conditions_index": {"value": "0.35", "date": "x"}})
    output, triggers = fa.monitor(conn, now=now)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Duiding van krappere financiele condities.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = fa.deep_dive(conn, client, output.claims, triggers, now=now)
    interpretation = next((c for c in deep_dive_output.claims if c.claim.startswith("NFCI-interpretatie")), None)
    assert interpretation is not None
    assert interpretation.value == "krapper dan het historisch gemiddelde (sinds 1973)"


def test_deep_dive_no_nfci_interpretation_claim_when_nfci_absent(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(fa, "fetch_snapshot", lambda: {"vix": {"value": "18.5", "date": "x"}})
    output, triggers = fa.monitor(conn, now=now)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Duiding van de VIX.")]
    client.messages.create = lambda **kwargs: response

    deep_dive_output = fa.deep_dive(conn, client, output.claims, triggers, now=now)
    assert not any(c.claim.startswith("NFCI-interpretatie") for c in deep_dive_output.claims)
