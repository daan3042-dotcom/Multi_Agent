"""
test_alpha_vantage.py
De gedeelde Alpha Vantage-aanroep (`sources/alpha_vantage.py`) en haar gebruik door de sector-, currency- en
commodity-agent. 02-10-2026.

Aanleiding: de eerste T₀ᵃ-dag miste `xlp_consumer_staples` en het log zei niet waarom. Wat hier bewaakt wordt:
  1. elke mislukte reeks krijgt een gelogde REDEN;
  2. wat ontbreekt wordt na ÉÉN pauze ÉÉN keer opnieuw geprobeerd, en alleen dat;
  3. een gat dat blijft, blijft een volledigheidstrigger (de herhaling verbergt niets);
  4. de API-sleutel komt nooit in het log;
  5. op een goede dag gebeurt er niets extra (geen pauze, geen extra aanroepen).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import requests

import agents.commodity_agent as commodity
import agents.currency_agent as currency
import agents.sector_agent as sector
from sources import alpha_vantage as av
from storage.schema import init_db

SLEUTEL = "GEHEIMSLEUTEL123"
NU = datetime(2026, 10, 2, 7, 15, tzinfo=timezone.utc)


def _antwoord(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json = lambda: payload
    if status >= 400:
        err = requests.HTTPError("fout")
        err.response = resp
        resp.raise_for_status = MagicMock(side_effect=err)
    else:
        resp.raise_for_status = lambda: None
    return resp


def _get_met(antwoord):
    return lambda url, params, timeout: antwoord


# --------------------------------------------------------------------------
# haal_json: de reden bij elke soort mislukking
# --------------------------------------------------------------------------


def test_een_goed_antwoord_komt_ongewijzigd_terug():
    payload, reden = av.haal_json({"apikey": SLEUTEL}, get=_get_met(_antwoord({"Global Quote": {"05. price": "1"}})))
    assert reden is None and payload == {"Global Quote": {"05. price": "1"}}


@pytest.mark.parametrize("sleutel", ["Note", "Information", "Error Message"])
def test_een_melding_van_alpha_vantage_zelf_wordt_de_reden(sleutel):
    tekst = "Thank you for using Alpha Vantage! Our standard API call frequency is 5 calls per minute."
    payload, reden = av.haal_json({"apikey": SLEUTEL}, get=_get_met(_antwoord({sleutel: tekst})))
    assert payload is None
    assert reden.startswith(f"Alpha Vantage meldt ({sleutel}): Thank you for using") and "5 calls per minute" in reden


def test_de_sleutel_wordt_uit_een_melding_van_alpha_vantage_gehaald():
    payload, reden = av.haal_json({"apikey": SLEUTEL}, get=_get_met(_antwoord({"Information": f"ongeldige key {SLEUTEL}"})))
    assert SLEUTEL not in reden and "***" in reden


def test_een_lange_melding_wordt_afgekapt():
    _, reden = av.haal_json({"apikey": SLEUTEL}, get=_get_met(_antwoord({"Note": "x" * 5000})))
    assert len(reden) < av.MAX_REDEN_TEKENS + 60


@pytest.mark.parametrize("uitzondering, verwacht", [
    (requests.Timeout("traag"), "time-out"),
    (requests.ConnectTimeout("traag"), "time-out"),
    (requests.ConnectionError("weg"), "verbindingsfout"),
])
def test_netwerkfouten_krijgen_een_vaste_leesbare_reden(uitzondering, verwacht):
    def get(url, params, timeout):
        raise uitzondering

    assert av.haal_json({"apikey": SLEUTEL}, get=get) == (None, verwacht)


def test_een_http_fout_noemt_de_statuscode():
    assert av.haal_json({"apikey": SLEUTEL}, get=_get_met(_antwoord({}, status=503))) == (None, "HTTP 503")


def test_een_antwoord_dat_geen_json_is():
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.json = MagicMock(side_effect=ValueError("geen json"))
    assert av.haal_json({"apikey": SLEUTEL}, get=_get_met(resp)) == (None, "antwoord is geen geldige JSON")


def test_een_antwoord_dat_geen_object_is():
    assert av.haal_json({"apikey": SLEUTEL}, get=_get_met(_antwoord(["a"]))) == (None, "onverwacht antwoordtype")


def test_een_onbekende_fout_toont_alleen_het_type_nooit_de_tekst_met_de_sleutel():
    """requests-uitzonderingen bevatten vaak de hele URL, inclusief apikey=. Die mag nooit in een reden terechtkomen."""
    def get(url, params, timeout):
        raise RuntimeError(f"fout bij https://www.alphavantage.co/query?function=X&apikey={SLEUTEL}")

    payload, reden = av.haal_json({"apikey": SLEUTEL}, get=get)
    assert payload is None and reden == "onverwachte fout (RuntimeError)" and SLEUTEL not in reden


# --------------------------------------------------------------------------
# verzamel: één herhaalronde, alleen voor wat ontbrak
# --------------------------------------------------------------------------


def _bron(uitval: dict[str, list[str | None]]):
    """haal_een-stub: per sleutel een lijst van uitkomsten per poging (None = gelukt, tekst = reden van falen)."""
    aanroepen: list[str] = []

    def haal_een(sleutel):
        aanroepen.append(sleutel)
        pogingen = uitval.get(sleutel, [])
        n = aanroepen.count(sleutel) - 1
        reden = pogingen[n] if n < len(pogingen) else None
        return (None, reden) if reden else ({"waarde": sleutel}, None)

    return haal_een, aanroepen


def test_op_een_goede_dag_gebeurt_er_niets_extra(caplog):
    pauzes = []
    haal_een, aanroepen = _bron({})
    with caplog.at_level(logging.INFO, logger="sources.alpha_vantage"):
        uit = av.verzamel("sector", ["a", "b", "c"], haal_een, slaap=pauzes.append)
    assert set(uit) == {"a", "b", "c"} and aanroepen == ["a", "b", "c"]
    assert pauzes == [] and caplog.records == []


def test_een_gat_dat_bij_de_herhaling_lukt_is_hersteld_en_heeft_een_gelogde_reden(caplog):
    pauzes = []
    haal_een, aanroepen = _bron({"b": ["Alpha Vantage meldt (Note): te snel"]})
    with caplog.at_level(logging.INFO, logger="sources.alpha_vantage"):
        uit = av.verzamel("sector", ["a", "b", "c"], haal_een, slaap=pauzes.append)
    assert set(uit) == {"a", "b", "c"}
    assert aanroepen == ["a", "b", "c", "b"]  # alleen b opnieuw
    assert pauzes == [av.RETRY_PAUZE_SECONDEN]
    tekst = caplog.text
    assert "b mislukt in de eerste ronde: Alpha Vantage meldt (Note): te snel" in tekst
    assert "b hersteld bij herhaling" in tekst and "3 van 3 reeksen na herhaling" in tekst


def test_een_gat_dat_blijft_blijft_ontbreken_en_wordt_niet_verzonnen(caplog):
    pauzes = []
    haal_een, aanroepen = _bron({"b": ["HTTP 503", "HTTP 503"]})
    with caplog.at_level(logging.INFO, logger="sources.alpha_vantage"):
        uit = av.verzamel("sector", ["a", "b", "c"], haal_een, slaap=pauzes.append)
    assert set(uit) == {"a", "c"}
    assert aanroepen.count("b") == 2  # één herhaling, geen tweede
    assert "b blijft ontbreken na herhaling: HTTP 503 (eerste ronde: HTTP 503)" in caplog.text
    assert "2 van 3 reeksen na herhaling" in caplog.text


def test_meerdere_gaten_delen_een_pauze(caplog):
    pauzes = []
    haal_een, aanroepen = _bron({"a": ["x"], "c": ["y"]})
    av.verzamel("sector", ["a", "b", "c"], haal_een, slaap=pauzes.append)
    assert pauzes == [av.RETRY_PAUZE_SECONDEN]  # één pauze, niet één per gat
    assert aanroepen == ["a", "b", "c", "a", "c"]


def test_als_alles_mislukt_komt_er_niets_terug_zodat_de_agent_zijn_fout_geeft():
    haal_een, _ = _bron({s: ["weg", "weg"] for s in "abc"})
    assert av.verzamel("sector", "abc", haal_een, slaap=lambda s: None) == {}


def test_de_tests_wachten_nooit_echt(monkeypatch):
    """tests/conftest.py vervangt de pauze: een mislukte reeks mag een test geen halve minuut laten stilstaan."""
    import time

    def mag_niet():
        raise AssertionError("er is echt geslapen")

    monkeypatch.setattr(time, "sleep", lambda s: mag_niet())
    haal_een, _ = _bron({"a": ["x"]})
    assert set(av.verzamel("sector", ["a"], haal_een)) == {"a"}  # zonder `slaap=`: de standaardpauze, door conftest vervangen


# --------------------------------------------------------------------------
# De drie agents, met de echte aanroep-keten tot aan requests.get
# --------------------------------------------------------------------------


def _sector_get(uitval_eerste_ronde=(), blijvend=()):
    """requests.get-stub voor de sector-agent. `uitval_eerste_ronde`: symbolen die de eerste keer een Note geven.
    `blijvend`: symbolen die altijd een Note geven."""
    gezien: dict[str, int] = {}

    def get(url, params, timeout):
        sym = params["symbol"]
        gezien[sym] = gezien.get(sym, 0) + 1
        if sym in blijvend or (sym in uitval_eerste_ronde and gezien[sym] == 1):
            return _antwoord({"Note": "Our standard API call frequency is 5 calls per minute."})
        return _antwoord({"Global Quote": {
            "05. price": "100.0", "07. latest trading day": "2026-10-01", "10. change percent": "0.5%",
        }})

    return get, gezien


def test_sector_herstelt_het_gat_van_2_oktober_en_logt_waarom(monkeypatch, caplog):
    """Het echte geval: 11 van de 12 reeksen, XLP ontbreekt. Na de herhaling is de snapshot compleet."""
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", SLEUTEL)
    get, gezien = _sector_get(uitval_eerste_ronde={"XLP"})
    monkeypatch.setattr(requests, "get", get)
    with caplog.at_level(logging.INFO, logger="sources.alpha_vantage"):
        snapshot = sector.fetch_snapshot()
    assert "xlp_consumer_staples" in snapshot
    assert sum(1 for k in snapshot if k in sector.SECTOR_ETFS) == 12
    assert gezien["XLP"] == 2 and all(n == 1 for s, n in gezien.items() if s != "XLP")
    assert "xlp_consumer_staples mislukt in de eerste ronde: Alpha Vantage meldt (Note)" in caplog.text
    assert "xlp_consumer_staples hersteld bij herhaling" in caplog.text
    assert SLEUTEL not in caplog.text


def test_sector_met_een_blijvend_gat_geeft_nog_steeds_een_volledigheidstrigger(monkeypatch, tmp_path, caplog):
    """De herhaling mag een gat dichten, nooit verbergen: blijft XLP weg, dan telt de dag niet-schoon."""
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", SLEUTEL)
    get, gezien = _sector_get(blijvend={"XLP"})
    monkeypatch.setattr(requests, "get", get)
    conn = init_db(str(tmp_path / "t.db"))
    with caplog.at_level(logging.INFO, logger="sources.alpha_vantage"):
        output, triggers = sector.monitor(conn, now=NU)
    assert gezien["XLP"] == 2  # precies één herhaling
    completeness = [t for t in triggers if t.metric_key is None and "completeness" in t.reason]
    assert len(completeness) == 1 and "xlp_consumer_staples" in completeness[0].reason
    assert "xlp_consumer_staples blijft ontbreken na herhaling" in caplog.text


def test_sector_op_een_goede_dag_doet_geen_extra_aanroepen_en_logt_niets(monkeypatch, caplog):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", SLEUTEL)
    get, gezien = _sector_get()
    monkeypatch.setattr(requests, "get", get)
    with caplog.at_level(logging.INFO, logger="sources.alpha_vantage"):
        sector.fetch_snapshot()
    assert set(gezien.values()) == {1} and caplog.records == []


def test_een_uitzondering_met_de_sleutel_erin_komt_niet_in_het_log(monkeypatch, caplog):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", SLEUTEL)

    def get(url, params, timeout):
        raise RuntimeError(f"Max retries exceeded with url: /query?function=GLOBAL_QUOTE&apikey={SLEUTEL}")

    monkeypatch.setattr(requests, "get", get)
    with caplog.at_level(logging.DEBUG, logger="sources.alpha_vantage"):
        assert "error" in sector.fetch_snapshot()
    assert "onverwachte fout (RuntimeError)" in caplog.text
    assert SLEUTEL not in caplog.text


def test_currency_herstelt_een_gat_bij_de_herhaling(monkeypatch, caplog):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", SLEUTEL)
    gezien: dict[str, int] = {}

    def get(url, params, timeout):
        paar = params["from_currency"] + params["to_currency"]
        gezien[paar] = gezien.get(paar, 0) + 1
        if paar == "USDJPY" and gezien[paar] == 1:
            return _antwoord({"Information": "rate limit"})
        return _antwoord({"Realtime Currency Exchange Rate": {"5. Exchange Rate": "1.1", "6. Last Refreshed": "x"}})

    monkeypatch.setattr(requests, "get", get)
    with caplog.at_level(logging.INFO, logger="sources.alpha_vantage"):
        snapshot = currency.fetch_snapshot()
    assert set(snapshot) == set(currency.FX_PAIRS) and gezien["USDJPY"] == 2
    assert "Alpha Vantage currency:" in caplog.text and "hersteld bij herhaling" in caplog.text


def test_commodity_herstelt_een_gat_bij_de_herhaling_en_behoudt_de_vorm(monkeypatch, caplog):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", SLEUTEL)
    eerste = next(iter(commodity.COMMODITIES.values()))
    gezien: dict[str, int] = {}

    def get(url, params, timeout):
        f = params["function"]
        gezien[f] = gezien.get(f, 0) + 1
        if f == eerste and gezien[f] == 1:
            return _antwoord({"Note": "te snel"})
        return _antwoord({"data": [{"date": "2026-07-01", "value": "4.40"}, {"date": "2026-06-01", "value": "4.30"}]})

    monkeypatch.setattr(requests, "get", get)
    with caplog.at_level(logging.INFO, logger="sources.alpha_vantage"):
        snapshot = commodity.fetch_snapshot()
    assert set(snapshot) == set(commodity.COMMODITIES) and gezien[eerste] == 2
    assert all(v == {"value": "4.40", "date": "2026-07-01"} for v in snapshot.values())  # zelfde vorm als voor de wijziging
    assert "hersteld bij herhaling" in caplog.text


def test_de_wijziging_raakt_de_triggerregels_niet():
    """Fetch-gedrag zit buiten de vingerafdruk van de trigger-regels: de versie hoeft niet omhoog (checkpoint 2)."""
    from contract.trigger_version import TRIGGER_FINGERPRINTS, TRIGGER_VERSION
    from runtime.trigger_guard import trigger_fingerprint

    assert trigger_fingerprint() == TRIGGER_FINGERPRINTS[TRIGGER_VERSION]
