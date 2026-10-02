import pytest
import requests

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import agents.sector_agent as sa
from storage.schema import get_source, init_db


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

    monkeypatch.setattr(requests, "get", fake_get)
    result = sa.fetch_snapshot()

    assert "error" not in result
    assert result["xlb_materials"]["value"] == "85.32"
    assert "xlk_technology" not in result


def test_fetch_snapshot_all_series_fail_returns_error(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        raise ConnectionError("netwerkfout")

    monkeypatch.setattr(requests, "get", fake_get)
    result = sa.fetch_snapshot()
    assert "error" in result


def test_monitor_wires_into_run_monitoring(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(sa, "fetch_snapshot", lambda: {"xlb_materials": {"value": "85.32", "date": "2026-09-22"}})

    output, triggers = sa.monitor(conn, now=now)
    assert output is not None
    assert output.domain == "sector"
    # Deze test gaat over het delta-mechanisme, niet over completeness.
    # De stub levert bewust maar een deel van de verwachte reeksen, wat
    # sinds 28-09-2026 een completeness-trigger geeft (metric_key=None);
    # filteren op metric_key houdt de oorspronkelijke bedoeling scherp.
    metric_triggers = [t for t in triggers if t.metric_key is not None]
    assert metric_triggers == []


def test_monitor_registers_itself_in_the_source_registry(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(sa, "fetch_snapshot", lambda: {"xlb_materials": {"value": "85.32", "date": "2026-09-22"}})

    sa.monitor(conn, now=now)

    source = get_source(conn, sa.SOURCE_KEY)
    assert source is not None
    assert source.provider == "ALPHA_VANTAGE_EQUITY"
    assert source.domain == "sector"
    assert source.max_age == sa.MAX_AGE


def test_monitor_triggers_on_significant_price_move(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=1)

    monkeypatch.setattr(sa, "fetch_snapshot", lambda: {"xlb_materials": {"value": "85.00", "date": "x"}})
    sa.monitor(conn, now=t1)

    monkeypatch.setattr(sa, "fetch_snapshot", lambda: {"xlb_materials": {"value": "82.00", "date": "y"}})
    output, triggers = sa.monitor(conn, now=t2)

    # Deze test gaat over het delta-mechanisme, niet over completeness.
    # De stub levert bewust maar een deel van de verwachte reeksen, wat
    # sinds 28-09-2026 een completeness-trigger geeft (metric_key=None);
    # filteren op metric_key houdt de oorspronkelijke bedoeling scherp.
    metric_triggers = [t for t in triggers if t.metric_key is not None]
    assert len(metric_triggers) == 1
    assert metric_triggers[0].metric_key == "xlb_materials"


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


# --- Relatieve sterkte tijdens monitoring (28-09-2026) ---


def _quote(prijs, change_pct, datum="2026-09-28"):
    return {"value": str(prijs), "date": datum, "change_percent": change_pct}


def test_spy_wordt_elke_cyclus_opgehaald_en_opgeslagen(tmp_path, monkeypatch):
    """Zonder SPY in de claims-historie is relatieve sterkte achteraf niet
    te berekenen, en kan de rijkste testbron van het cohort geen
    voorspellingen doen. Dat was tot 28-09 het geval."""
    from storage.schema import load_latest_claims

    conn = init_db(str(tmp_path / "t.db"))
    monkeypatch.setattr(sa, "fetch_snapshot", lambda: {
        "xlk_technology": _quote(200.0, 1.5),
        "spy_benchmark": _quote(500.0, 0.5),
    })
    sa.monitor(conn, now=datetime.now(timezone.utc))

    metrics = {c.metric_key for c in load_latest_claims(conn, "sector")}
    assert "spy_benchmark" in metrics


def test_relatieve_sterkte_wordt_berekend_en_opgeslagen(tmp_path, monkeypatch):
    """XLK +1,5% tegen SPY +0,5% is een relatieve sterkte van +1,0
    procentpunt. Kost geen extra API-call: change_percent zat al in de
    quote die toch al opgehaald werd."""
    from storage.schema import load_latest_claims

    conn = init_db(str(tmp_path / "t.db"))
    snapshot = {
        "xlk_technology": _quote(200.0, 1.5),
        "spy_benchmark": _quote(500.0, 0.5),
    }
    snapshot.update(sa._relative_strength_entries(snapshot))
    monkeypatch.setattr(sa, "fetch_snapshot", lambda: snapshot)
    sa.monitor(conn, now=datetime.now(timezone.utc))

    claims = {c.metric_key: c.value for c in load_latest_claims(conn, "sector")}
    assert claims["xlk_technology_rel_spy"] == pytest.approx(1.0)


def test_zonder_spy_geen_relatieve_sterkte(tmp_path):
    """REGRESSIE: geen gok. Valt SPY weg, dan is er niets om tegen te
    vergelijken en komt er niets terug -- in plaats van een getal dat
    stilzwijgend iets anders betekent."""
    zonder_spy = {"xlk_technology": _quote(200.0, 1.5)}
    assert sa._relative_strength_entries(zonder_spy) == {}


def test_etf_zonder_change_percent_wordt_overgeslagen():
    snapshot = {
        "xlk_technology": {"value": "200", "date": "x", "change_percent": None},
        "spy_benchmark": _quote(500.0, 0.5),
    }
    assert sa._relative_strength_entries(snapshot) == {}


def test_relatieve_sterkte_triggert_bewust_niet(tmp_path, monkeypatch):
    """REGRESSIE op een bewuste keuze. De escalatie blijft op de ruwe prijs
    lopen. Een delta-trigger op relatieve sterkte zou de dagverandering van
    vandaag met die van gisteren vergelijken -- een tweede verschil, en dat
    is ruis."""
    assert not any(k.endswith("_rel_spy") for k in sa.METRIC_SPECS)


def test_elf_forecast_doelen_op_relatief_rendement():
    """Deel A vraagt 11 doelen, en dat is meer breedte dan de andere vier
    agents samen leveren."""
    assert len(sa.FORECAST_TARGETS) == 11
    assert not any(t.metric_key == "spy_benchmark" for t in sa.FORECAST_TARGETS)
    for t in sa.FORECAST_TARGETS:
        assert "RELATIEVE rendement" in t.resolution_rule
        assert "spy_benchmark" in t.resolution_rule
