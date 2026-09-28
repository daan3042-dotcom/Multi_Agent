from datetime import datetime, timezone
from unittest.mock import MagicMock

from runtime.backfill import (
    backfill_commodity,
    backfill_currency,
    backfill_fred_domain,
    backfill_sector,
    fetch_av_fx_daily_full_history,
    fetch_av_time_series_daily_full_history,
    fetch_fred_full_history,
)
from storage.schema import init_db, load_latest_claims, load_monitoring_claims


def _db(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def _fred_response(observations):
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.json = lambda: {"observations": observations}
    return resp


def test_fetch_fred_full_history_happy_path(monkeypatch):
    import runtime.backfill as bf

    monkeypatch.setattr(
        bf.requests, "get",
        lambda url, params, timeout: _fred_response([
            {"value": "5.00", "date": "2020-01-01"},
            {"value": "5.25", "date": "2020-02-01"},
        ]),
    )
    history = fetch_fred_full_history("FEDFUNDS", "fake-key")
    assert history == [{"value": "5.00", "date": "2020-01-01"}, {"value": "5.25", "date": "2020-02-01"}]


def test_fetch_fred_full_history_skips_placeholder_values(monkeypatch):
    import runtime.backfill as bf

    monkeypatch.setattr(
        bf.requests, "get",
        lambda url, params, timeout: _fred_response([{"value": ".", "date": "2020-01-01"}]),
    )
    assert fetch_fred_full_history("FEDFUNDS", "fake-key") == []


def test_fetch_fred_full_history_network_error_returns_empty_list(monkeypatch):
    import runtime.backfill as bf

    monkeypatch.setattr(bf.requests, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("netwerkfout")))
    assert fetch_fred_full_history("FEDFUNDS", "fake-key") == []


def test_fetch_av_time_series_daily_full_history_happy_path(monkeypatch):
    import runtime.backfill as bf

    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.json = lambda: {"Time Series (Daily)": {"2020-01-02": {"4. close": "200.00"}}}
    monkeypatch.setattr(bf.requests, "get", lambda url, params, timeout: resp)

    history = fetch_av_time_series_daily_full_history("XLK", "fake-key")
    assert history == [{"value": "200.00", "date": "2020-01-02"}]


def test_fetch_av_fx_daily_full_history_happy_path(monkeypatch):
    import runtime.backfill as bf

    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.json = lambda: {"Time Series FX (Daily)": {"2020-01-02": {"4. close": "1.10"}}}
    monkeypatch.setattr(bf.requests, "get", lambda url, params, timeout: resp)

    history = fetch_av_fx_daily_full_history("EUR", "USD", "fake-key")
    assert history == [{"value": "1.10", "date": "2020-01-02"}]


def test_backfill_fred_domain_stores_claims_with_analysis_time_equal_to_source_time(tmp_path, monkeypatch):
    import runtime.backfill as bf

    conn = _db(tmp_path)
    monkeypatch.setattr(
        bf.requests, "get",
        lambda url, params, timeout: _fred_response([
            {"value": "5.00", "date": "2020-01-01"},
            {"value": "5.25", "date": "2020-02-01"},
        ]),
    )

    count = backfill_fred_domain(
        conn, "monetary_policy", "FRED:monetary_policy",
        {"fed_funds_rate": "FEDFUNDS"}, {}, "fake-key",
    )
    assert count == 2

    claims = load_latest_claims(conn, "monetary_policy", metric_key="fed_funds_rate")
    assert len(claims) == 2
    for c in claims:
        assert c.analysis_time == c.source_time
        assert c.note == "back-fill (roadmap 1.11, 0b-1)"
    # Nieuwste eerst (ORDER BY analysis_time DESC)
    assert claims[0].source_time > claims[1].source_time


def test_backfill_does_not_hijack_load_monitoring_claims_from_a_real_cycle(tmp_path, monkeypatch):
    """De kern-regressietest voor de moduledocstring se uitleg: een back-
    fill met oude data mag een LATERE, echte monitoring-cyclus nooit
    verdringen als "de laatste cyclus" voor load_monitoring_claims() (dat
    zou een deep-dive de hele historie i.p.v. de laatste cijfers geven)."""
    import runtime.backfill as bf
    from contract.output_contract import Claim, Confidence, DomainOutput, Mode
    from storage.schema import save_domain_output

    conn = _db(tmp_path)
    real_now = datetime(2026, 9, 28, tzinfo=timezone.utc)
    real_output = DomainOutput(
        domain="monetary_policy", mode=Mode.MONITORING, generated_at=real_now,
        claims=[
            Claim(
                domain="monetary_policy", claim="Fed funds rate", value=5.5, source="FRED:monetary_policy",
                confidence=Confidence.HIGH, analysis_time=real_now, source_time=real_now,
                metric_key="fed_funds_rate",
            )
        ],
    )
    save_domain_output(conn, real_output)

    monkeypatch.setattr(
        bf.requests, "get",
        lambda url, params, timeout: _fred_response([{"value": "1.00", "date": "1990-01-01"}]),
    )
    backfill_fred_domain(conn, "monetary_policy", "FRED:monetary_policy", {"fed_funds_rate": "FEDFUNDS"}, {}, "fake-key")

    latest_cycle_claims = load_monitoring_claims(conn, "monetary_policy")
    assert len(latest_cycle_claims) == 1
    assert latest_cycle_claims[0].value == 5.5


def test_backfill_sector_uses_time_series_daily_not_global_quote(tmp_path, monkeypatch):
    import runtime.backfill as bf

    conn = _db(tmp_path)
    captured_params = []

    def fake_get(url, params, timeout):
        captured_params.append(params)
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"Time Series (Daily)": {"2020-01-02": {"4. close": "200.00"}}}
        return resp

    monkeypatch.setattr(bf.requests, "get", fake_get)
    count = backfill_sector(conn, "sector", "ALPHA_VANTAGE_EQUITY:sector", {"xlk_technology": "XLK"}, {}, "fake-key")

    assert count == 1
    assert captured_params[0]["function"] == "TIME_SERIES_DAILY"
    assert captured_params[0]["outputsize"] == "full"


def test_backfill_currency_uses_fx_daily_not_exchange_rate(tmp_path, monkeypatch):
    import runtime.backfill as bf

    conn = _db(tmp_path)
    captured_params = []

    def fake_get(url, params, timeout):
        captured_params.append(params)
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"Time Series FX (Daily)": {"2020-01-02": {"4. close": "1.10"}}}
        return resp

    monkeypatch.setattr(bf.requests, "get", fake_get)
    count = backfill_currency(conn, "currency", "ALPHA_VANTAGE_FX:currency", {"eur_usd": ("EUR", "USD")}, {}, "fake-key")

    assert count == 1
    assert captured_params[0]["function"] == "FX_DAILY"


def test_backfill_commodity_reuses_existing_historical_fetch(tmp_path, monkeypatch):
    """commodity_agent._fetch_commodity_data() geeft al historie terug --
    backfill_commodity() hergebruikt 'm i.p.v. een eigen fetch te schrijven."""
    import agents.commodity_agent as commodity_agent

    conn = _db(tmp_path)
    monkeypatch.setattr(
        commodity_agent, "_fetch_commodity_data",
        lambda function_name, api_key: [{"value": "70.00", "date": "2020-01-01"}, {"value": "72.00", "date": "2020-02-01"}],
    )
    count = backfill_commodity(conn, "commodity", "ALPHA_VANTAGE_COMMODITY:commodity", {"wti": "WTI"}, {}, "fake-key")
    assert count == 2


def test_backfill_returns_zero_and_saves_nothing_when_history_is_empty(tmp_path, monkeypatch):
    import runtime.backfill as bf

    conn = _db(tmp_path)
    monkeypatch.setattr(bf.requests, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("netwerkfout")))

    count = backfill_fred_domain(conn, "monetary_policy", "FRED:monetary_policy", {"fed_funds_rate": "FEDFUNDS"}, {}, "fake-key")
    assert count == 0
    assert load_monitoring_claims(conn, "monetary_policy") == []
