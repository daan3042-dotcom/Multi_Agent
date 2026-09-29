from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from runtime.backfill import (
    BackfillFetchError,
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
    with pytest.raises(BackfillFetchError, match="geen bruikbare waarnemingen"):
        fetch_fred_full_history("FEDFUNDS", "fake-key")


def test_fetch_fred_full_history_network_error_raises_with_the_reason(monkeypatch):
    """Was: geef een lege lijst terug. Dat is precies hoe een half gevulde
    back-fill als geslaagd kon eindigen (zie de moduledocstring)."""
    import runtime.backfill as bf

    monkeypatch.setattr(bf.requests, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("netwerkfout")))
    with pytest.raises(BackfillFetchError, match="netwerkfout"):
        fetch_fred_full_history("FEDFUNDS", "fake-key")


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

    resultaat = backfill_fred_domain(
        conn, "monetary_policy", "FRED:monetary_policy",
        {"fed_funds_rate": "FEDFUNDS"}, {}, "fake-key",
    )
    assert resultaat.saved == 2
    assert resultaat.is_complete

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
    resultaat = backfill_sector(conn, "sector", "ALPHA_VANTAGE_EQUITY:sector", {"xlk_technology": "XLK"}, {}, "fake-key")

    assert resultaat.saved == 1
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
    resultaat = backfill_currency(conn, "currency", "ALPHA_VANTAGE_FX:currency", {"eur_usd": ("EUR", "USD")}, {}, "fake-key")

    assert resultaat.saved == 1
    assert captured_params[0]["function"] == "FX_DAILY"


def test_backfill_commodity_haalt_maandelijkse_historie_op(tmp_path, monkeypatch):
    import runtime.backfill as bf

    conn = _db(tmp_path)
    captured = []

    def fake_get(url, params, timeout):
        captured.append((params, timeout))
        return _av_json({"data": [{"value": "70.00", "date": "2020-01-01"}, {"value": "72.00", "date": "2020-02-01"}]})

    monkeypatch.setattr(bf.requests, "get", fake_get)
    resultaat = backfill_commodity(conn, "commodity", "ALPHA_VANTAGE_COMMODITY:commodity", {"wti": "WTI"}, {}, "fake-key")

    assert resultaat.saved == 2
    params, timeout = captured[0]
    assert params["function"] == "WTI" and params["interval"] == "monthly"
    assert timeout == 120, "eigen fetch met de lange back-fill-timeout, niet de 15 s van de dagelijkse agent"


def test_backfill_saves_nothing_and_says_so_when_the_fetch_fails(tmp_path, monkeypatch):
    import runtime.backfill as bf

    conn = _db(tmp_path)
    monkeypatch.setattr(bf.requests, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("netwerkfout")))

    resultaat = backfill_fred_domain(conn, "monetary_policy", "FRED:monetary_policy", {"fed_funds_rate": "FEDFUNDS"}, {}, "fake-key")

    assert resultaat.saved == 0
    assert not resultaat.is_complete
    assert "netwerkfout" in resultaat.failed[0].detail
    assert load_monitoring_claims(conn, "monetary_policy") == []


# --------------------------------------------------------------------------
# Gedeeltelijke back-fill: melden, en veilig herstellen (29-09)
#
# De aanleiding: de fetchers gaven bij elke fout `[]`, ook bij Alpha Vantage's
# "limiet bereikt" (HTTP 200 met alleen een tekstveld). Een domein telde als
# geslaagd zodra één reeks data gaf, en zonder dedup was een gedeeltelijke
# run niet bij te vullen zonder de gelukte reeksen dubbel op te slaan.
# --------------------------------------------------------------------------


def _av_json(payload):
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.json = lambda: payload
    return resp


def _dagreeks(n=30, start_jaar=2020):
    """n dagen historie, ruim ouder dan 30 dagen, in het AV-formaat."""
    from datetime import timedelta

    start = datetime(start_jaar, 1, 1)
    return {(start + timedelta(days=i)).date().isoformat(): {"4. close": f"{100 + i}"} for i in range(n)}


@pytest.mark.parametrize("veld", ["Note", "Information", "Error Message"])
def test_alpha_vantage_limietbericht_wordt_een_fout_met_de_tekst_van_de_bron(monkeypatch, veld):
    """HET geval van 28-09. AV meldt 'limiet bereikt' met HTTP 200 en zonder
    tijdreeks. Vroeger: lege lijst, dus stil. Nu: een fout die zegt waarom."""
    import runtime.backfill as bf

    monkeypatch.setattr(
        bf.requests, "get",
        lambda url, params, timeout: _av_json({veld: "You have reached the 25 requests per day limit"}),
    )
    with pytest.raises(BackfillFetchError, match="25 requests per day"):
        fetch_av_time_series_daily_full_history("XLK", "fake-key")
    with pytest.raises(BackfillFetchError, match="25 requests per day"):
        fetch_av_fx_daily_full_history("EUR", "USD", "fake-key")


def test_antwoord_zonder_tijdreeks_is_een_fout(monkeypatch):
    import runtime.backfill as bf

    monkeypatch.setattr(bf.requests, "get", lambda url, params, timeout: _av_json({"Meta Data": {}}))
    with pytest.raises(BackfillFetchError, match="geen 'Time Series"):
        fetch_av_time_series_daily_full_history("XLK", "fake-key")


def test_fred_foutbericht_wordt_een_fout_met_de_tekst_van_de_bron(monkeypatch):
    import runtime.backfill as bf

    monkeypatch.setattr(
        bf.requests, "get",
        lambda url, params, timeout: _av_json({"error_code": 400, "error_message": "Bad Request. api_key is invalid"}),
    )
    with pytest.raises(BackfillFetchError, match="api_key is invalid"):
        fetch_fred_full_history("FEDFUNDS", "fake-key")


def test_een_domein_met_een_mislukte_reeks_is_niet_geslaagd(tmp_path, monkeypatch):
    """Regressiegeval voor 'geslaagd zodra één reeks data gaf'. Vijf van de
    elf ETF's is geen geslaagde back-fill."""
    import runtime.backfill as bf

    conn = _db(tmp_path)

    def fake_get(url, params, timeout):
        if params["symbol"] == "XLE":
            return _av_json({"Note": "rate limit"})
        return _av_json({"Time Series (Daily)": _dagreeks()})

    monkeypatch.setattr(bf.requests, "get", fake_get)

    resultaat = backfill_sector(
        conn, "sector", "AV:sector", {"xlk_technology": "XLK", "xle_energy": "XLE"}, {}, "fake-key",
    )

    assert not resultaat.is_complete
    assert [o.metric_key for o in resultaat.failed] == ["xle_energy"]
    assert resultaat.saved == 30  # de gelukte reeks staat er wél


def test_opnieuw_draaien_vult_alleen_het_ontbrekende_en_dupliceert_niets(tmp_path, monkeypatch):
    """Het herstelpad, en de reden voor de hele ombouw: na een gedeeltelijke
    run mag je gewoon opnieuw draaien. De gelukte reeks wordt overgeslagen
    (geen dubbele claims), de mislukte wordt alsnog opgehaald."""
    import runtime.backfill as bf

    conn = _db(tmp_path)
    limiet_bereikt = {"aan": True}
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params["symbol"])
        if params["symbol"] == "XLE" and limiet_bereikt["aan"]:
            return _av_json({"Note": "rate limit"})
        return _av_json({"Time Series (Daily)": _dagreeks()})

    monkeypatch.setattr(bf.requests, "get", fake_get)
    etfs = {"xlk_technology": "XLK", "xle_energy": "XLE"}

    eerste = backfill_sector(conn, "sector", "AV:sector", etfs, {}, "fake-key")
    assert not eerste.is_complete

    limiet_bereikt["aan"] = False
    calls.clear()
    tweede = backfill_sector(conn, "sector", "AV:sector", etfs, {}, "fake-key")

    assert tweede.is_complete
    assert calls == ["XLE"], "alleen de ontbrekende reeks mag opnieuw worden opgehaald"
    statussen = {o.metric_key: o.status for o in tweede.outcomes}
    assert statussen == {"xlk_technology": "skipped", "xle_energy": "saved"}
    assert len(load_latest_claims(conn, "sector", metric_key="xlk_technology")) == 30, "geen dubbele claims"
    assert len(load_latest_claims(conn, "sector", metric_key="xle_energy")) == 30


def test_derde_run_doet_niets_meer(tmp_path, monkeypatch):
    import runtime.backfill as bf

    conn = _db(tmp_path)
    monkeypatch.setattr(bf.requests, "get", lambda url, params, timeout: _av_json({"Time Series (Daily)": _dagreeks()}))
    etfs = {"xlk_technology": "XLK"}
    backfill_sector(conn, "sector", "AV:sector", etfs, {}, "fake-key")

    monkeypatch.setattr(bf.requests, "get", lambda *a, **k: pytest.fail("mag niet meer ophalen"))
    resultaat = backfill_sector(conn, "sector", "AV:sector", etfs, {}, "fake-key")

    assert resultaat.saved == 0 and resultaat.is_complete


def test_een_paar_claims_uit_de_dagelijkse_cyclus_telt_niet_als_historie(tmp_path, monkeypatch):
    """De dagelijkse cyclus maakt één claim per dag. Twee dagen monitoring
    zijn geen back-fill: de reeks moet dan nog steeds worden opgehaald."""
    import runtime.backfill as bf
    from contract.output_contract import Claim, Confidence, DomainOutput, Mode
    from storage.schema import save_domain_output

    conn = _db(tmp_path)
    nu = datetime.now(timezone.utc)
    claims = [
        Claim(domain="sector", claim="XLK", value=200.0, source="test", confidence=Confidence.HIGH,
              analysis_time=nu, source_time=nu, metric_key="xlk_technology")
    ]
    save_domain_output(conn, DomainOutput(domain="sector", mode=Mode.MONITORING, generated_at=nu, claims=claims))
    monkeypatch.setattr(bf.requests, "get", lambda url, params, timeout: _av_json({"Time Series (Daily)": _dagreeks()}))

    resultaat = backfill_sector(conn, "sector", "AV:sector", {"xlk_technology": "XLK"}, {}, "fake-key")

    assert resultaat.outcomes[0].status == "saved"


@pytest.mark.parametrize("veld", ["Note", "Information"])
def test_commodity_meldt_de_werkelijke_reden_van_alpha_vantage(tmp_path, monkeypatch, veld):
    """Regressiegeval van 29-09: alle tien grondstoffen mislukten en de melding
    zei alleen 'reden onbekend', omdat de back-fill de fetch van de dagelijkse
    agent hergebruikte en die elke fout inslikt. Nu staat de tekst van Alpha
    Vantage in de uitvoer."""
    import runtime.backfill as bf

    conn = _db(tmp_path)
    monkeypatch.setattr(bf.requests, "get", lambda url, params, timeout: _av_json({veld: "premium endpoint (test)"}))

    resultaat = backfill_commodity(conn, "commodity", "AV:commodity", {"wti": "WTI"}, {}, "fake-key")

    assert not resultaat.is_complete
    assert "premium endpoint (test)" in resultaat.failed[0].detail


def test_commodity_antwoord_zonder_data_is_een_fout(tmp_path, monkeypatch):
    import runtime.backfill as bf

    conn = _db(tmp_path)
    monkeypatch.setattr(bf.requests, "get", lambda url, params, timeout: _av_json({"name": "WTI", "data": []}))
    resultaat = backfill_commodity(conn, "commodity", "AV:commodity", {"wti": "WTI"}, {}, "fake-key")
    assert not resultaat.is_complete


# --------------------------------------------------------------------------
# De API-key mag nooit in een foutmelding staan (29-09)
#
# `requests` zet de volledige url, query inclusief, in zijn foutmeldingen. Zonder
# redactie staat de key in de uitvoer van het script, en dus in elk logbestand en
# elke chat waar die uitvoer in geplakt wordt.
# --------------------------------------------------------------------------


def test_netwerkfout_lekt_de_api_key_niet(monkeypatch):
    import runtime.backfill as bf

    def stuk(*a, **k):
        raise ConnectionError(
            "HTTPSConnectionPool(host='www.alphavantage.co', port=443): Max retries exceeded "
            "with url: /query?function=WTI&interval=monthly&apikey=GEHEIME_KEY_123 (Caused by ...)"
        )

    monkeypatch.setattr(bf.requests, "get", stuk)
    with pytest.raises(BackfillFetchError) as e:
        fetch_av_time_series_daily_full_history("XLK", "GEHEIME_KEY_123")

    assert "GEHEIME_KEY_123" not in str(e.value)
    assert "<verborgen>" in str(e.value)


def test_http_fout_lekt_de_api_key_niet(monkeypatch):
    """`raise_for_status()` zet de url met de key in de foutmelding."""
    import requests
    import runtime.backfill as bf

    def antwoord(url, params, timeout):
        resp = requests.models.Response()
        resp.status_code = 429
        resp.reason = "Too Many Requests"
        resp.url = "https://www.alphavantage.co/query?function=X&apikey=GEHEIME_KEY_123"
        return resp

    monkeypatch.setattr(bf.requests, "get", antwoord)
    with pytest.raises(BackfillFetchError) as e:
        fetch_av_time_series_daily_full_history("XLK", "GEHEIME_KEY_123")

    assert "429" in str(e.value)
    assert "GEHEIME_KEY_123" not in str(e.value)


def test_de_key_staat_ook_niet_in_de_cli_uitvoer(tmp_path, monkeypatch, capsys):
    """Het echte pad: wat de gebruiker op zijn scherm ziet en hier plakt."""
    import runtime.backfill as bf

    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "GEHEIME_KEY_123")

    def stuk(*a, **k):
        raise ConnectionError("Max retries exceeded with url: /query?function=FX_DAILY&apikey=GEHEIME_KEY_123")

    monkeypatch.setattr(bf.requests, "get", stuk)
    _cli().main(["--db", str(tmp_path / "t.db"), "--domain", "currency"])

    assert "GEHEIME_KEY_123" not in capsys.readouterr().out


def test_redactie_pakt_alle_varianten():
    from runtime.backfill import redact_secrets

    for tekst in (
        "url: https://x/query?function=A&apikey=SECRET&z=1",
        "url: https://x/query?api_key=SECRET",
        "url: /query?function=A&APIKEY=SECRET (Caused by",
        "url: 'https://x/query?apikey=SECRET'",
    ):
        assert "SECRET" not in redact_secrets(tekst)


# --------------------------------------------------------------------------
# Overslaan per (domein, reeks), niet per reeks alleen
# --------------------------------------------------------------------------


def test_reeks_in_een_ander_domein_telt_niet_als_historie(tmp_path, monkeypatch):
    """`unemployment_rate` staat bij monetary_policy én economic, en elk domein
    leest zijn EIGEN claims voor de delta-trigger. Historie in het ene domein
    mag het andere niet laten overslaan."""
    import runtime.backfill as bf

    conn = _db(tmp_path)
    monkeypatch.setattr(bf.requests, "get", lambda url, params, timeout: _av_json({"observations": [
        {"value": str(4.0 + i / 100), "date": f"{1990 + i // 12}-{i % 12 + 1:02d}-01"} for i in range(60)
    ]}))
    reeks = {"unemployment_rate": "UNRATE"}

    eerste = backfill_fred_domain(conn, "economic", "FRED:economic", reeks, {}, "fake-key")
    tweede = backfill_fred_domain(conn, "monetary_policy", "FRED:monetary_policy", reeks, {}, "fake-key")

    assert eerste.outcomes[0].status == "saved"
    assert tweede.outcomes[0].status == "saved", "monetary_policy had nog geen eigen historie"
    assert len(load_latest_claims(conn, "monetary_policy", metric_key="unemployment_rate")) == 60
    assert len(load_latest_claims(conn, "economic", metric_key="unemployment_rate")) == 60


# --------------------------------------------------------------------------
# De CLI
# --------------------------------------------------------------------------


def _cli():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("backfill_cli", Path(__file__).resolve().parent.parent / "backfill.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_exitcode_en_uitvoer_bij_een_mislukte_reeks(tmp_path, monkeypatch, capsys):
    """Exit 1 met de reden van de bron en de melding dat opnieuw draaien
    veilig is. Vroeger was dit exit 0 zodra één reeks data gaf."""
    import runtime.backfill as bf

    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")
    monkeypatch.setattr(bf.requests, "get", lambda url, params, timeout: _av_json({"Note": "limiet bereikt (test)"}))
    pad = str(tmp_path / "t.db")

    code = _cli().main(["--db", pad, "--domain", "currency"])

    uitvoer = capsys.readouterr().out
    assert code == 1
    assert "MISLUKT" in uitvoer and "limiet bereikt (test)" in uitvoer
    assert "veilig opnieuw te draaien" in uitvoer


def test_cli_tweede_run_slaat_over_en_geeft_nul(tmp_path, monkeypatch, capsys):
    import runtime.backfill as bf

    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")
    monkeypatch.setattr(bf.requests, "get", lambda url, params, timeout: _av_json({"Time Series FX (Daily)": _dagreeks()}))
    pad = str(tmp_path / "t.db")
    cli = _cli()

    assert cli.main(["--db", pad, "--domain", "currency"]) == 0
    capsys.readouterr()
    assert cli.main(["--db", pad, "--domain", "currency"]) == 0

    uitvoer = capsys.readouterr().out
    assert uitvoer.count("overgeslagen") == 3  # de drie FX-paren
    assert "OPGESLAGEN" not in uitvoer
