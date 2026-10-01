"""
test_probe_sources.py
Tests voor `sources/probe.py` en `probe_sources.py` (roadmap 1.2 en 1.4, fase A van
`docs/data-archive.md`, 30-09-2026).

WAT HIER OP HET SPEL STAAT. Het probe-script draait op de VPS met echte sleutels. Drie dingen
mogen daar nooit misgaan: (1) een API-key mag nooit in de uitvoer of het JSON-bestand komen,
(2) het script mag niets opslaan behalve op verzoek een JSON-kopie, en (3) het advies moet
volgen uit wat gemeten is, niet uit wat verwacht werd. Er wordt hier niets echt aangeroepen:
alle netwerkverkeer is een nep-functie.
"""

from __future__ import annotations

import importlib.util
import json
import os
from datetime import date
from pathlib import Path

import pytest

from sources import probe
from sources.probe import (
    ADVIES_BESLISSING,
    ADVIES_LATER,
    ADVIES_METEN,
    ADVIES_NU,
    HERSTELBAAR_JA,
    HERSTELBAAR_NEE,
    HERSTELBAAR_ONBEKEND,
    STATUS_FOUT,
    STATUS_GEEN_TOEGANG,
    STATUS_LEEG,
    STATUS_LIMIET,
    STATUS_NIET_BEREIKBAAR,
    STATUS_NIET_GEPROBEERD,
    STATUS_OK,
    Context,
    ProbeResult,
    av_status,
    bepaal_advies,
    koppel_herstelbaarheid,
    laatste_werkdag_op_of_voor,
    probe_av,
    probe_fred,
)

ROOT = Path(__file__).resolve().parent.parent
NU = date(2026, 9, 30)
GEHEIM = "GEHEIMEKEY123"


class _Antwoord:
    def __init__(self, payload=None, tekst="", status=200, content=b"", headers=None):
        self._payload = payload
        self.text = tekst if tekst or payload is None else json.dumps(payload)
        self.status_code = status
        self.content = content or self.text.encode()
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("geen JSON")
        return self._payload


def _ctx(get, av=GEHEIM, fred=GEHEIM):
    return Context(av_key=av, fred_key=fred, nu=NU, get=get, slaap=lambda s: None)


# --------------------------------------------------------------------------
# De adviesregel
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, herstelbaar, verwacht",
    [
        (STATUS_OK, HERSTELBAAR_NEE, ADVIES_NU),
        (STATUS_OK, HERSTELBAAR_JA, ADVIES_LATER),
        (STATUS_OK, HERSTELBAAR_ONBEKEND, ADVIES_METEN),
        (STATUS_FOUT, HERSTELBAAR_NEE, ADVIES_BESLISSING),
        (STATUS_NIET_GEPROBEERD, HERSTELBAAR_JA, ADVIES_BESLISSING),
        (STATUS_GEEN_TOEGANG, HERSTELBAAR_NEE, ADVIES_BESLISSING),
        (STATUS_LEEG, HERSTELBAAR_JA, ADVIES_BESLISSING),
    ],
)
def test_de_adviesregel(status, herstelbaar, verwacht):
    assert bepaal_advies(status, herstelbaar) == verwacht


def test_nog_niet_onderzocht_is_een_onderzoeksvraag_en_geen_beslissing_voor_dd():
    """Regressie 01-10-2026: Atlanta Fed en de regionale Fed-enquêtes stonden als
    'beslissing DD (niet beschikbaar of betaald)', terwijl ze alleen nog niet
    bekeken waren. Wat wél betaald of niet beschikbaar is, blijft een beslissing."""
    from sources.probe import ADVIES_UITGESLOTEN, ADVIES_UITZOEKEN, STATUS_BEWUST_NIET

    assert bepaal_advies(STATUS_NIET_GEPROBEERD, HERSTELBAAR_ONBEKEND, "gratis") == ADVIES_UITZOEKEN
    assert bepaal_advies(STATUS_NIET_GEPROBEERD, HERSTELBAAR_ONBEKEND, "betaald") == ADVIES_BESLISSING
    assert bepaal_advies(STATUS_NIET_GEPROBEERD, HERSTELBAAR_NEE, "gratis") == ADVIES_BESLISSING
    assert bepaal_advies(STATUS_BEWUST_NIET, HERSTELBAAR_ONBEKEND, "gratis") == ADVIES_UITGESLOTEN


def test_de_statische_rijen_krijgen_het_juiste_advies():
    from sources.probe import ADVIES_UITGESLOTEN, ADVIES_UITZOEKEN, _niet_geprobeerd

    per_id = {r.id: r.advies for r in _niet_geprobeerd()}
    assert per_id["atlanta_mpt"] == ADVIES_UITZOEKEN
    assert per_id["regionale_fed_surveys"] == ADVIES_UITZOEKEN
    assert per_id["yahoo_tickers"] == ADVIES_UITGESLOTEN
    for betaald in ("consensus_macro", "fedfunds_futures", "earnings_consensus", "ism_pmi", "cme_cvol", "futures_intraday"):
        assert per_id[betaald] == ADVIES_BESLISSING, betaald


def test_niet_bereikbaar_en_niet_terug_te_halen_is_nooit_archief_nu():
    """Je kunt niet archiveren wat je niet kunt ophalen: dat is een beslissing (vaak een prijs)."""
    assert bepaal_advies(STATUS_NIET_BEREIKBAAR, HERSTELBAAR_NEE) == ADVIES_BESLISSING


# --------------------------------------------------------------------------
# Alpha Vantage: de manieren waarop 'nee' klinkt
# --------------------------------------------------------------------------


def test_een_leeg_antwoord_is_niet_hetzelfde_als_geen_data():
    """Het incident van 29-09: `{}` met HTTP 200 voor élk endpoint."""
    assert av_status({})[0] == STATUS_LEEG


def test_premium_en_limiet_worden_onderscheiden():
    assert av_status({"Information": "This is a premium endpoint. Please subscribe."})[0] == STATUS_GEEN_TOEGANG
    assert av_status({"Note": "Our standard API rate limit is 25 requests per day."})[0] == STATUS_LIMIET
    assert av_status({"Error Message": "Invalid API call."})[0] == STATUS_FOUT


def test_een_normaal_antwoord_wordt_niet_als_afwijking_gezien():
    assert av_status({"data": [1]}) is None


def _opties_ok(get_calls):
    def get(url, params=None, headers=None, timeout=None):
        get_calls.append((url, dict(params or {})))
        return _Antwoord({"data": [{"strike": 500}] * 3})
    return get


def test_een_gelukte_meting_krijgt_status_ok_en_detail(tmp_path):
    calls = []
    ctx = _ctx(_opties_ok(calls))
    r = probe_av(ctx, "x", "opties", {"function": "HISTORICAL_OPTIONS"},
                 lambda p: (True, "3 contracten", None, "2026-09-28"), herstelbaar=HERSTELBAAR_JA)

    assert r.status == STATUS_OK
    assert r.advies == ADVIES_LATER
    assert r.achterstand_dagen == 2  # 30-09 min 28-09
    assert ctx.aanroepen_av == 1


def test_zonder_sleutel_wordt_er_niet_aangeroepen():
    calls = []
    ctx = _ctx(_opties_ok(calls), av=None)
    r = probe_av(ctx, "x", "opties", {"function": "F"}, lambda p: (True, "", None, None))

    assert r.status == STATUS_NIET_GEPROBEERD
    assert calls == []
    assert ctx.aanroepen_av == 0


# --------------------------------------------------------------------------
# Sleutels komen nooit in de uitvoer
# --------------------------------------------------------------------------


def test_een_sleutel_in_een_foutmelding_wordt_verborgen():
    """`requests` neemt de url mee in zijn foutmeldingen, en daar staat `apikey=` in."""
    def kapot(url, params=None, headers=None, timeout=None):
        raise ConnectionError(f"HTTPSConnectionPool: url: /query?function=X&apikey={GEHEIM} (Caused by timeout)")

    r = probe_av(_ctx(kapot), "x", "opties", {"function": "X"}, lambda p: (True, "", None, None))

    assert r.status == STATUS_NIET_BEREIKBAAR
    assert GEHEIM not in r.detail
    assert "<verborgen>" in r.detail


def test_de_sleutelfilter_werkt_ook_als_de_aanroeper_hem_vergeet():
    """Laatste verdediging: `ProbeResult` filtert zelf, ook bij een handmatig gebouwd detail."""
    r = ProbeResult(id="x", categorie="c", bron="b", status=STATUS_FOUT, detail=f"mislukt: apikey={GEHEIM}&x=1")
    assert GEHEIM not in r.detail
    assert GEHEIM not in json.dumps(probe.naar_dict([r]))


# --------------------------------------------------------------------------
# FRED
# --------------------------------------------------------------------------


def _fred_get(series):
    def get(url, params=None, headers=None, timeout=None):
        if url.endswith("/series/vintagedates"):
            return _Antwoord({"count": 900, "vintage_dates": ["1955-01-01", "1955-02-01", "1955-03-01"]})
        sid = params["series_id"]
        if sid not in series:
            return _Antwoord({"error_code": 400, "error_message": "Bad Request.  The series does not exist."}, status=400)
        return _Antwoord({"seriess": [series[sid]]})
    return get


PAYEMS = {"title": "All Employees, Total Nonfarm", "frequency_short": "M", "units_short": "Thous. of Persons",
          "observation_start": "1939-01-01", "observation_end": "2026-08-01"}


def test_fred_geeft_historie_achterstand_en_eenheid():
    r = probe_fred(_ctx(_fred_get({"PAYEMS": PAYEMS})), "PAYEMS", "economic")

    assert r.status == STATUS_OK
    assert (r.eerste, r.laatste) == ("1939-01-01", "2026-08-01")
    assert r.achterstand_dagen == (NU - date(2026, 8, 1)).days
    assert r.eenheid == "Thous. of Persons"
    assert "Thous. of Persons" in r.detail
    assert r.advies == ADVIES_LATER


def test_een_onbekende_fred_reeks_is_een_bevinding_en_geen_crash():
    """De ID's komen uit het hoofd: een verkeerde moet als 'fout' in het rapport staan."""
    r = probe_fred(_ctx(_fred_get({})), "NIETBESTAAND", "economic")

    assert r.status == STATUS_FOUT
    assert "does not exist" in r.detail
    assert r.advies == ADVIES_BESLISSING


def test_fred_zonder_json_is_een_fout():
    r = probe_fred(_ctx(lambda url, params=None, headers=None, timeout=None: _Antwoord(None, tekst="<html>", status=502)), "X", "c")
    assert r.status == STATUS_FOUT and "502" in r.detail


def test_alfred_meldt_of_er_een_vintage_archief_is():
    r = probe.probe_alfred_vintages(_ctx(_fred_get({})))

    assert r.status == STATUS_OK
    assert "900 vintages" in r.detail
    assert r.eerste == "1955-01-01"


# --------------------------------------------------------------------------
# Herstelbaarheid volgt uit een meting
# --------------------------------------------------------------------------


def _r(id, status, via=None, herstelbaar=HERSTELBAAR_ONBEKEND):
    return ProbeResult(id=id, categorie="c", bron="b", status=status, herstelbaar=herstelbaar, herstelbaar_via=via)


def test_een_nu_meting_is_terug_te_halen_als_de_historische_meting_lukte():
    rijen = [_r("historie", STATUS_OK, herstelbaar=HERSTELBAAR_JA), _r("nu", STATUS_OK, via="historie")]
    koppel_herstelbaarheid(rijen)

    assert rijen[1].herstelbaar == HERSTELBAAR_JA
    assert rijen[1].advies == ADVIES_LATER


def test_een_nu_meting_is_niet_terug_te_halen_als_de_historische_meting_mislukte():
    """Dit is de meting die telt: lukt de historie niet, dan is elke dag zonder archief verloren."""
    rijen = [_r("historie", STATUS_GEEN_TOEGANG), _r("nu", STATUS_OK, via="historie")]
    koppel_herstelbaarheid(rijen)

    assert rijen[1].herstelbaar == HERSTELBAAR_NEE
    assert rijen[1].advies == ADVIES_NU


# --------------------------------------------------------------------------
# Hulpfuncties
# --------------------------------------------------------------------------


def test_een_dieptemeting_toont_geen_achterstand():
    """De geteste datum (een jaar of tien jaar terug) in de kolom 'achterstand' las als verouderde data."""
    resultaten = {r.id: r for r in probe.voer_uit(_ctx(_router()))}

    for id in ("av_options_historie_1j", "av_options_historie_5j", "av_intraday_10j", "av_intraday_1j"):
        assert resultaten[id].laatste is None and resultaten[id].achterstand_dagen is None, id
    assert "2016-01-04" in resultaten["av_intraday_10j"].detail  # het bereik staat wel in het detail


def test_een_weekend_valt_terug_op_de_vrijdag():
    assert laatste_werkdag_op_of_voor(date(2025, 9, 28)) == date(2025, 9, 26)  # zondag
    assert laatste_werkdag_op_of_voor(date(2025, 9, 27)) == date(2025, 9, 26)  # zaterdag
    assert laatste_werkdag_op_of_voor(date(2025, 9, 26)) == date(2025, 9, 26)  # vrijdag


def test_cboe_csv_datums_worden_herkend_in_beide_notaties():
    n, eerste, laatste = probe._datum_uit_csv("DATE,OPEN,CLOSE\n01/02/2007,1,2\n03/04/2026,3,4\n")
    assert (n, eerste, laatste) == (2, "2007-01-02", "2026-03-04")
    n, eerste, laatste = probe._datum_uit_csv("date,v\n2020-01-01,1\n2026-09-29,2\n")
    assert (n, eerste, laatste) == (2, "2020-01-01", "2026-09-29")
    assert probe._datum_uit_csv("alleen tekst\n") == (0, None, None)


def test_een_url_die_niet_200_geeft_is_een_bevinding():
    ctx = _ctx(lambda url, params=None, headers=None, timeout=None: _Antwoord(None, tekst="", status=403))
    r = probe.probe_url(ctx, "x", "c", "b", "https://voorbeeld.test", lambda a: (True, "", None, None), HERSTELBAAR_JA)
    assert r.status == STATUS_FOUT and "403" in r.detail


def test_een_onverwacht_formaat_crasht_het_script_niet():
    def kapot(antwoord):
        raise KeyError("verwacht veld ontbreekt")

    ctx = _ctx(lambda url, params=None, headers=None, timeout=None: _Antwoord({"a": 1}))
    r = probe.probe_url(ctx, "x", "c", "b", "https://voorbeeld.test", kapot, HERSTELBAAR_JA)
    assert r.status == STATUS_FOUT and "KeyError" in r.detail


# --------------------------------------------------------------------------
# Het geheel
# --------------------------------------------------------------------------


def _router(av_calls=None, fred_calls=None):
    """Nep-internet: elk adres geeft een antwoord dat past bij wat er gevraagd wordt."""
    def get(url, params=None, headers=None, timeout=None):
        if "alphavantage" in url:
            if av_calls is not None:
                av_calls.append(dict(params or {}))
            f = (params or {}).get("function")
            if f in ("HISTORICAL_OPTIONS", "REALTIME_OPTIONS"):
                return _Antwoord({"data": [{"strike": 1}]})
            if f == "TIME_SERIES_INTRADAY":
                return _Antwoord({"Time Series (5min)": {"2016-01-04 09:35:00": {}, "2016-01-29 15:55:00": {}}})
            if f == "NEWS_SENTIMENT":
                return _Antwoord({"feed": [{"title": "x"}]})
            if f == "EARNINGS_CALL_TRANSCRIPT":
                return _Antwoord({"transcript": [{"speaker": "x"}]})
            if f == "GLOBAL_QUOTE":
                return _Antwoord({"Global Quote": {"05. price": "10.0", "07. latest trading day": "2026-09-29"}})
        if "stlouisfed" in url:
            if fred_calls is not None:
                fred_calls.append(url)
            return _fred_get({s: PAYEMS for s, _ in probe.FRED_KANDIDATEN})(url, params, headers, timeout)
        if "cboe" in url:
            return _Antwoord(None, tekst="DATE,CLOSE\n01/02/2007,1\n09/29/2026,2\n")
        if url.endswith(".xlsx"):
            return _Antwoord(None, tekst="x", content=b"x" * 5000, headers={"Content-Type": "application/vnd.ms-excel"})
        if "cftc" in url:
            return _Antwoord([{"a": 1}])
        if "newyorkfed" in url:
            return _Antwoord({"refRates": [{"rate": 4.3}]})
        if "fiscaldata" in url:
            return _Antwoord({"data": [{"x": 1}]})
        if "ecb.europa" in url:
            return _Antwoord(None, tekst="KEY,OBS\nEXR,1.1\n")
        if "kalshi" in url:
            return _Antwoord({"markets": [{"t": 1}]})
        if "polymarket" in url:
            return _Antwoord([{"q": 1}])
        return _Antwoord(None, tekst="<html>ok</html>")
    return get


def test_een_volledige_run_geeft_een_rapport_met_alles_en_advies_per_rij():
    resultaten = probe.voer_uit(_ctx(_router()))

    ids = {r.id for r in resultaten}
    assert "fred_dfedtaru" in ids and "av_options_historie_1j" in ids and "spy_holdings" in ids
    assert "consensus_macro" in ids, "wat niet te meten is, staat er toch in, met reden"
    assert all(r.advies in probe.ALLE_ADVIEZEN for r in resultaten)
    assert len({r.id for r in resultaten}) == len(resultaten), "geen dubbele id's"


def test_de_niet_terug_te_halen_bron_krijgt_advies_archief_nu():
    """SPY-holdings bestaan alleen als de huidige stand: dat is het echte urgente geval."""
    resultaten = {r.id: r for r in probe.voer_uit(_ctx(_router()))}

    assert resultaten["spy_holdings"].advies == ADVIES_NU
    assert resultaten["cboe_vix3m"].advies == ADVIES_LATER
    assert resultaten["fred_dfedtaru"].advies == ADVIES_LATER


def test_betaalde_bronnen_zonder_bron_zijn_een_beslissing_voor_dd():
    resultaten = {r.id: r for r in probe.voer_uit(_ctx(_router()))}

    for id in ("consensus_macro", "fedfunds_futures", "ism_pmi"):
        assert resultaten[id].status == STATUS_NIET_GEPROBEERD
        assert resultaten[id].advies == ADVIES_BESLISSING
    # Yahoo is geen beslissing maar een bewuste uitsluiting (CLAUDE.md regel 2), sinds 01-10-2026.
    assert resultaten["yahoo_tickers"].advies == "bewust niet (zie reden)"


def test_het_callvolume_van_alpha_vantage_blijft_klein():
    """Na het incident van 29-09 (lege antwoorden na ruim 100 aanroepen) is dit een eis."""
    av = []
    probe.voer_uit(_ctx(_router(av_calls=av)))

    assert 0 < len(av) <= 20


def test_zonder_av_wordt_alpha_vantage_niet_aangeroepen():
    av = []
    ctx = _ctx(_router(av_calls=av))
    resultaten = probe.voer_uit(ctx, zonder_av=True)

    assert av == [] and ctx.aanroepen_av == 0
    assert not any(r.id.startswith("av_") for r in resultaten)


def test_elke_fred_kandidaat_kost_precies_een_aanroep_plus_de_vintagecontrole():
    fred = []
    ctx = _ctx(_router(fred_calls=fred))
    probe.voer_uit(ctx)

    assert ctx.aanroepen_fred == len(probe.FRED_KANDIDATEN) + 1


def test_categoriefilter_beperkt_de_uitvoer():
    resultaten = probe.voer_uit(_ctx(_router()), categorieen={"opties"})
    assert resultaten and all(r.categorie == "opties" for r in resultaten)


def test_geen_enkele_sleutel_komt_in_de_json_van_een_volledige_run():
    resultaten = probe.voer_uit(_ctx(_router()))
    assert GEHEIM not in json.dumps(probe.naar_dict(resultaten))


def test_zonder_sleutels_wordt_alles_wat_een_sleutel_vraagt_niet_geprobeerd():
    resultaten = probe.voer_uit(_ctx(_router(), av=None, fred=None))
    sleutelrijen = [r for r in resultaten if r.id.startswith(("av_", "fred_", "alfred_"))]

    assert sleutelrijen and all(r.status == STATUS_NIET_GEPROBEERD for r in sleutelrijen)


# --------------------------------------------------------------------------
# Het script
# --------------------------------------------------------------------------


def _script():
    spec = importlib.util.spec_from_file_location("probe_sources_cli", ROOT / "probe_sources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_het_script_draait_schrijft_alleen_de_json_en_toont_geen_sleutel(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", GEHEIM)
    monkeypatch.setenv("FRED_API_KEY", GEHEIM)
    monkeypatch.setattr(probe.requests, "get", _router())
    monkeypatch.setattr(probe.time, "sleep", lambda s: None)
    monkeypatch.chdir(tmp_path)
    script = _script()

    uitvoer_pad = tmp_path / "rapport.json"
    code = script.main(["--zonder-av", "--json", str(uitvoer_pad)])
    tekst = capsys.readouterr().out

    assert code == 0
    assert GEHEIM not in tekst
    assert GEHEIM not in uitvoer_pad.read_text()
    assert "SAMENVATTING" in tekst
    assert sorted(os.listdir(tmp_path)) == ["rapport.json"], "het script mag verder niets aanmaken"
    assert isinstance(json.loads(uitvoer_pad.read_text()), list)


def test_het_probe_script_raakt_de_database_niet_aan():
    """Alleen lezen: geen import van de opslaglaag."""
    bron = (ROOT / "src" / "sources" / "probe.py").read_text() + (ROOT / "probe_sources.py").read_text()
    assert "storage" not in bron and "sqlite3" not in bron
