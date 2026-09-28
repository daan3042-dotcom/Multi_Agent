"""
test_forecast_round.py
Tests voor de forecast-ronde (roadmap 2.0) in agents/base.py.

De ronde is de derde modus naast monitoring en deep-dive, en de enige plek
in dit systeem waar een LLM een kans of verdeling uitspreekt. Deze tests
bewaken vooral wat er gebeurt als het model iets teruggeeft dat NIET klopt
-- want dat is het normale geval, niet de uitzondering.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from agents.base import (
    AlreadyProcessedError,
    ForecastTarget,
    run_forecast_round,
)
from contract.horizons import ReleaseCadence
from contract.prediction import HorizonKind, PredictionKind
from storage.schema import init_db, list_agent_runs, list_predictions

NU = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

DOELEN = [
    ForecastTarget(
        metric_key="10y_treasury_yield",
        kind=PredictionKind.QUANTILE,
        horizon_kind=HorizonKind.TRADING_DAYS,
        horizons=(5, 21),
        resolution_rule="DGS10 eerste print op of na resolves_at ({horizon_n} hd)",
    ),
]


def _client(tekst: str):
    client = MagicMock()
    blok = MagicMock()
    blok.type = "text"
    blok.text = tekst
    client.messages.create.return_value = MagicMock(content=[blok])
    return client


def _volledig_antwoord() -> str:
    return (
        '{"forecasts": ['
        '{"metric_key": "10y_treasury_yield", "horizon_n": 5, "q10": 3.9, "q50": 4.1, "q90": 4.3},'
        '{"metric_key": "10y_treasury_yield", "horizon_n": 21, "q10": 3.7, "q50": 4.1, "q90": 4.6}'
        "]}"
    )


def _ronde(conn, tekst, **kwargs):
    return run_forecast_round(
        conn, _client(tekst), "monetary_policy", "systeemprompt",
        DOELEN, [], prompt_version="mp-v1", now=NU, **kwargs,
    )


# --- Het correcte geval ---


def test_volledige_ronde_slaat_alle_voorspellingen_op(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    resultaat = _ronde(conn, _volledig_antwoord())

    assert resultaat.is_complete
    assert len(resultaat.predictions) == 2
    opgeslagen = list_predictions(conn)
    assert len(opgeslagen) == 2
    assert {p.horizon_n for p in opgeslagen} == {5, 21}
    assert all(p.model_id and p.prompt_version == "mp-v1" for p in opgeslagen)


def test_resolution_rule_krijgt_de_horizon_ingevuld(tmp_path):
    """Het sjabloon is de autoriteit over wat er gescoord wordt, dus de
    horizon moet er letterlijk in staan -- niet alleen in een los veld."""
    conn = init_db(str(tmp_path / "t.db"))
    _ronde(conn, _volledig_antwoord())

    regels = {p.horizon_n: p.resolution_rule for p in list_predictions(conn)}
    assert "5 hd" in regels[5]
    assert "21 hd" in regels[21]


def test_ronde_wordt_vastgelegd_in_agent_runs(tmp_path):
    """Een week waarin de forecast-ronde stil mislukt, is een week zonder
    voorspellingen -- en die zijn niet achteraf te maken."""
    conn = init_db(str(tmp_path / "t.db"))
    _ronde(conn, _volledig_antwoord())

    runs = [r for r in list_agent_runs(conn, "monetary_policy") if r["mode"] == "forecast"]
    assert len(runs) == 1
    assert runs[0]["success"] is True
    assert runs[0]["trigger_count"] == 2


# --- Wat er misgaat als het model niet meewerkt ---


def test_ontbrekend_doel_komt_in_issues_maar_gooit_de_rest_niet_weg(tmp_path):
    """REGRESSIE, en de belangrijkste keuze in deze module. Negen goede
    voorspellingen weggooien omdat de tiende niet klopte, kost meetbare data
    die niet in te halen is. Dus: opslaan wat geldig is, en zichtbaar maken
    wat ontbreekt -- dezelfde les als de completeness-check."""
    conn = init_db(str(tmp_path / "t.db"))
    half = (
        '{"forecasts": ['
        '{"metric_key": "10y_treasury_yield", "horizon_n": 5, "q10": 3.9, "q50": 4.1, "q90": 4.3}'
        "]}"
    )
    resultaat = _ronde(conn, half)

    assert len(resultaat.predictions) == 1
    assert not resultaat.is_complete
    assert any("horizon_n" in i or "21" in i for i in resultaat.issues)
    assert len(list_predictions(conn)) == 1


def test_niet_oplopende_kwantielen_worden_geweigerd(tmp_path):
    """Het contract weigert ze; de ronde moet dat overleven en melden."""
    conn = init_db(str(tmp_path / "t.db"))
    fout = (
        '{"forecasts": ['
        '{"metric_key": "10y_treasury_yield", "horizon_n": 5, "q10": 4.9, "q50": 4.1, "q90": 3.3},'
        '{"metric_key": "10y_treasury_yield", "horizon_n": 21, "q10": 3.7, "q50": 4.1, "q90": 4.6}'
        "]}"
    )
    resultaat = _ronde(conn, fout)

    assert len(resultaat.predictions) == 1
    assert any("ongeldige voorspelling" in i for i in resultaat.issues)


def test_onparseerbare_respons_levert_geen_halve_data_op(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    resultaat = _ronde(conn, "Ik denk dat de rente ongeveer gelijk blijft.")

    assert resultaat.predictions == ()
    assert any("JSON" in i for i in resultaat.issues)
    assert list_predictions(conn) == []


def test_onbekend_doel_in_de_respons_wordt_gemeld(tmp_path):
    """Het model mag niets verzinnen dat niet gevraagd is."""
    conn = init_db(str(tmp_path / "t.db"))
    extra = (
        '{"forecasts": ['
        '{"metric_key": "10y_treasury_yield", "horizon_n": 5, "q10": 3.9, "q50": 4.1, "q90": 4.3},'
        '{"metric_key": "10y_treasury_yield", "horizon_n": 21, "q10": 3.7, "q50": 4.1, "q90": 4.6},'
        '{"metric_key": "goud", "horizon_n": 5, "q10": 1, "q50": 2, "q90": 3}'
        "]}"
    )
    resultaat = _ronde(conn, extra)

    assert len(resultaat.predictions) == 2
    assert any("onbekend doel" in i for i in resultaat.issues)


def test_mislukte_llm_call_wordt_vastgelegd_en_niet_geslikt(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("API down")

    resultaat = run_forecast_round(
        conn, client, "monetary_policy", "sp", DOELEN, [], prompt_version="mp-v1", now=NU,
    )

    assert resultaat.predictions == ()
    runs = [r for r in list_agent_runs(conn, "monetary_policy") if r["mode"] == "forecast"]
    assert runs[0]["success"] is False
    assert "API down" in runs[0]["error"]


# --- Idempotency en trigger-conditionering ---


def test_dezelfde_event_id_draait_niet_twee_keer(tmp_path):
    """Roadmap 1.7: een dubbele ronde zou dubbele voorspellingen op dezelfde
    week opleveren, en dat vervuilt de scoring."""
    conn = init_db(str(tmp_path / "t.db"))
    _ronde(conn, _volledig_antwoord(), event_id="2026-W40")

    with pytest.raises(AlreadyProcessedError):
        _ronde(conn, _volledig_antwoord(), event_id="2026-W40")

    assert len(list_predictions(conn)) == 2


def test_trigger_conditioned_wordt_gevlagd(tmp_path):
    """Voorspellingen uit een trigger zijn niet vergelijkbaar met die uit de
    wekelijkse ronde -- alleen bij triggers voorspellen geeft selectiebias,
    dus het onderscheid moet in de data zitten."""
    conn = init_db(str(tmp_path / "t.db"))
    _ronde(conn, _volledig_antwoord(), trigger_conditioned=True)

    assert all(p.trigger_conditioned for p in list_predictions(conn))


def test_standaard_is_niet_trigger_conditioned(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _ronde(conn, _volledig_antwoord())
    assert not any(p.trigger_conditioned for p in list_predictions(conn))


# --- De doelen van de vijf voorspellende agents ---


def test_elke_voorspellende_agent_heeft_doelen():
    from agents import currency_agent, economic_agent, financial_agent, monetary_policy_agent

    for mod in (monetary_policy_agent, financial_agent, economic_agent, currency_agent):
        assert mod.FORECAST_TARGETS, mod.__name__


def test_doelen_verwijzen_naar_bestaande_metric_keys():
    """REGRESSIE. Een doel op een metric_key die de agent niet ophaalt, is
    nooit te resolven -- dan voorspel je iets waarvan de uitkomst nooit
    binnenkomt."""
    from agents import currency_agent, economic_agent, financial_agent, monetary_policy_agent

    for mod in (monetary_policy_agent, financial_agent, economic_agent, currency_agent):
        for target in mod.FORECAST_TARGETS:
            assert target.metric_key in mod.METRIC_SPECS, f"{mod.__name__}: {target.metric_key}"


def test_releasehorizonnen_hebben_altijd_een_cadans():
    """Zonder cadans is resolves_at niet te schatten en weigert
    contract/horizons.py -- dat moet bij het schrijven van de doelen al
    opvallen, niet pas als de ronde draait."""
    from agents import currency_agent, economic_agent, financial_agent, monetary_policy_agent

    for mod in (monetary_policy_agent, financial_agent, economic_agent, currency_agent):
        for target in mod.FORECAST_TARGETS:
            if target.horizon_kind is HorizonKind.RELEASES:
                assert target.cadence is not None, f"{mod.__name__}: {target.metric_key}"
            else:
                assert target.cadence is None, f"{mod.__name__}: {target.metric_key}"


def test_binair_doel_zonder_event_rule_wordt_geweigerd():
    with pytest.raises(ValueError, match="event_rule"):
        ForecastTarget(
            metric_key="x", kind=PredictionKind.BINARY,
            horizon_kind=HorizonKind.RELEASES, horizons=(1,),
            cadence=ReleaseCadence.FOMC, resolution_rule="regel",
        )
