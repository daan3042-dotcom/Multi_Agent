from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import agents.monetary_policy_agent as mpa
from storage.schema import get_source, init_db, latest_data_health


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
    # Deze test gaat over het delta-mechanisme, niet over completeness.
    # De stub levert bewust maar een deel van de verwachte reeksen, wat
    # sinds 28-09-2026 een completeness-trigger geeft (metric_key=None);
    # filteren op metric_key houdt de oorspronkelijke bedoeling scherp.
    metric_triggers = [t for t in triggers if t.metric_key is not None]
    assert metric_triggers == []


def test_monitor_registers_itself_in_the_source_registry(tmp_path, monkeypatch):
    """Roadmap 1.4: monitor() moet zijn EIGEN, per-agent-gescopete
    source_key gebruiken (niet de kale providernaam "FRED") -- dat is de
    daadwerkelijke fix voor het gedeelde-databron-probleem met
    financial_agent.py."""
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(mpa, "fetch_snapshot", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}})

    mpa.monitor(conn, now=now)

    source = get_source(conn, mpa.SOURCE_KEY)
    assert source is not None
    assert source.provider == "FRED"
    assert source.domain == "monetary_policy"
    assert source.max_age == mpa.MAX_AGE

    # data_health wordt onder de PER-AGENT source_key geregistreerd, niet
    # onder de kale providernaam "FRED" (die financial_agent.py ook gebruikt)
    assert latest_data_health(conn, mpa.SOURCE_KEY) is not None
    assert latest_data_health(conn, "FRED") is None


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


# --- Uitbreiding 28-09-2026: reeksen voor drie knopen van de causale graaf ---


def test_nieuwe_reeksen_bedienen_de_lege_graafknopen():
    """Het correcte geval: DGS2, T5YIE/T10YIE en WALCL zitten in FRED_SERIES.
    Zonder deze reeksen bezit deze agent policy_expectations,
    inflation_expectations en liquidity wel volgens contract/graph.py, maar
    heeft hij geen enkele waarneming om ze uit te schatten."""
    assert mpa.FRED_SERIES["2y_treasury_yield"] == "DGS2"
    assert mpa.FRED_SERIES["inflation_expectations_5y"] == "T5YIE"
    assert mpa.FRED_SERIES["inflation_expectations_10y"] == "T10YIE"
    assert mpa.FRED_SERIES["fed_balance_sheet"] == "WALCL"


def test_elke_opgehaalde_reeks_heeft_een_metric_spec():
    """REGRESSIE. run_monitoring() doet `metric_specs.get(metric_key)` en slaat
    een metric zonder spec stilzwijgend over voor de delta-trigger: de claim
    wordt wél opgeslagen, maar er kan nooit een trigger op vuren. Een reeks
    toevoegen aan FRED_SERIES en de spec vergeten levert dus data op die
    niemand ooit ziet -- precies het stille-faal-patroon dat A.3 moet
    voorkomen."""
    assert set(mpa.FRED_SERIES) == set(mpa.METRIC_SPECS)


def test_monitoring_maakt_claims_voor_de_nieuwe_reeksen(tmp_path, monkeypatch):
    from storage.schema import load_latest_claims

    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(mpa, "fetch_snapshot", lambda: {
        "2y_treasury_yield": {"value": "4.10", "date": "2026-09-28"},
        "inflation_expectations_5y": {"value": "2.35", "date": "2026-09-28"},
        "fed_balance_sheet": {"value": "6650000", "date": "2026-09-24"},
    })

    output, triggers = mpa.monitor(conn, now=now)

    assert output is not None
    # Deze test gaat over het delta-mechanisme, niet over completeness.
    # De stub levert bewust maar een deel van de verwachte reeksen, wat
    # sinds 28-09-2026 een completeness-trigger geeft (metric_key=None);
    # filteren op metric_key houdt de oorspronkelijke bedoeling scherp.
    metric_triggers = [t for t in triggers if t.metric_key is not None]
    assert metric_triggers == []  # eerste observatie: geen vorige waarde
    metrics = {c.metric_key for c in load_latest_claims(conn, "monetary_policy")}
    assert {"2y_treasury_yield", "inflation_expectations_5y", "fed_balance_sheet"} <= metrics


def test_breakeven_beweging_boven_de_tolerance_triggert(tmp_path, monkeypatch):
    """REGRESSIE op de tolerance zelf: break-evens bewegen in honderdsten van
    procentpunten, dus een tolerance in dezelfde orde als die van de Fed funds
    rate (0,25) zou vrijwel nooit vuren. 0,10 wél."""
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)

    monkeypatch.setattr(mpa, "fetch_snapshot", lambda: {
        "inflation_expectations_5y": {"value": "2.30", "date": "2026-09-27"}})
    mpa.monitor(conn, now=now)

    monkeypatch.setattr(mpa, "fetch_snapshot", lambda: {
        "inflation_expectations_5y": {"value": "2.48", "date": "2026-09-28"}})
    _, triggers = mpa.monitor(conn, now=now + timedelta(days=1))

    assert any(t.metric_key == "inflation_expectations_5y" for t in triggers)


def test_walcl_drempel_vuurt_op_een_realistische_weekverandering(tmp_path, monkeypatch):
    """REGRESSIE op de drempelverlaging van 28-09-2026. Het niveau is live
    gemeten op 6.747.704 (miljoenen USD). Een balansverandering van ~$40
    miljard in een week is fors maar niet uitzonderlijk; met de oude
    drempel van 100.000 vuurde dat niet en bleef de knoop `liquidity`
    blind voor het tempo van de afbouw."""
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)

    monkeypatch.setattr(mpa, "fetch_snapshot", lambda: {
        "fed_balance_sheet": {"value": "6747704", "date": "2026-09-24"}})
    mpa.monitor(conn, now=now)

    monkeypatch.setattr(mpa, "fetch_snapshot", lambda: {
        "fed_balance_sheet": {"value": "6707704", "date": "2026-10-01"}})  # -40.000
    _, triggers = mpa.monitor(conn, now=now + timedelta(days=7))

    assert any(t.metric_key == "fed_balance_sheet" for t in triggers)


def test_walcl_drempel_negeert_een_rustige_week(tmp_path, monkeypatch):
    """De tegenhanger: ~$10 miljard is het normale afbouwtempo en hoort de
    deep-dive-machinerie niet wakker te maken."""
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)

    monkeypatch.setattr(mpa, "fetch_snapshot", lambda: {
        "fed_balance_sheet": {"value": "6747704", "date": "2026-09-24"}})
    mpa.monitor(conn, now=now)

    monkeypatch.setattr(mpa, "fetch_snapshot", lambda: {
        "fed_balance_sheet": {"value": "6737704", "date": "2026-10-01"}})  # -10.000
    _, triggers = mpa.monitor(conn, now=now + timedelta(days=7))

    assert not any(t.metric_key == "fed_balance_sheet" for t in triggers)
