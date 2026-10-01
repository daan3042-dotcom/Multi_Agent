"""
test_llm_calls.py
Het ruwe LLM-logboek (`llm_calls`, 01-10-2026, DD) en het denkbeleid voor Claude Sonnet 5.5
(`runtime/llm_budget.py`), plus de modelkeuze in `agents/base.py`.

WAAROM DIT BELANGRIJK IS. (1) Zonder logboek is achteraf niet te zien waarom een voorspelling zo uitviel.
(2) Sonnet 5.5 zet denken STANDAARD AAN; onze aanroepen hebben een kleine `max_tokens`, dus zonder beleid kan
een antwoord leeg of afgekapt terugkomen en zou de QC-review stil verzwakken. Beide moeten blijven kloppen
als iemand het model of de wrapper aanraakt.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agents import base
from agents.base import DEFAULT_DEEP_DIVE_MODEL, ForecastTarget, run_deep_dive, run_forecast_round
from contract.horizons import ReleaseCadence  # noqa: F401  (zelfde importpatroon als de forecast-tests)
from contract.prediction import HorizonKind, PredictionKind
from contract.resolution import ResolutionMethod
from qc import qc
from runtime.llm_budget import BudgetExceeded, DENKEN_UIT, MeteredClient, met_denkbeleid
from storage.schema import init_db, list_llm_calls, list_predictions

NU = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
SONNET_5_5 = "claude-sonnet-5-5"


class _Client:
    def __init__(self, teksten=("ok",), stop="end_turn"):
        self.calls = []
        self._teksten = list(teksten)
        self._stop = stop
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        tekst = self._teksten.pop(0) if self._teksten else "ok"
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=tekst)],
            usage=SimpleNamespace(input_tokens=120, output_tokens=45), stop_reason=self._stop, model=kwargs.get("model"),
        )


def _db(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def _gemeterd(conn, client, cap=200.0):
    return MeteredClient(client, conn, cap, nu=lambda: NU)


# --------------------------------------------------------------------------
# Het logboek
# --------------------------------------------------------------------------


def test_elke_aanroep_wordt_ruw_vastgelegd_met_verzoek_antwoord_en_tokens(tmp_path):
    conn = _db(tmp_path)
    g = _gemeterd(conn, _Client(("het antwoord",)))
    g.messages.create(model=SONNET_5_5, max_tokens=500, system="systeemprompt",
                      messages=[{"role": "user", "content": "de cijfers"}])

    (rij,) = list_llm_calls(conn)
    assert rij["model"] == SONNET_5_5 and rij["response_text"] == "het antwoord"
    assert rij["stop_reason"] == "end_turn" and (rij["input_tokens"], rij["output_tokens"]) == (120, 45)
    assert rij["error"] is None and rij["called_at"] == NU.isoformat()
    import json
    verzoek = json.loads(rij["request_json"])
    assert verzoek["system"] == "systeemprompt" and verzoek["messages"][0]["content"] == "de cijfers"
    assert verzoek["max_tokens"] == 500


def test_thinking_blokken_komen_niet_in_de_antwoordtekst(tmp_path):
    """Op Sonnet 5.5 kan een antwoord thinking-blokken bevatten; alleen de tekst is het antwoord."""
    conn = _db(tmp_path)
    _gemeterd(conn, _Client(("alleen dit",))).messages.create(model=SONNET_5_5, max_tokens=10, messages=[])
    assert list_llm_calls(conn)[0]["response_text"] == "alleen dit"


def test_context_koppelt_de_aanroep_aan_agent_doel_en_event_en_herstelt_zich(tmp_path):
    conn = _db(tmp_path)
    g = _gemeterd(conn, _Client())
    with g.context(domain="monetary_policy", purpose="deep_dive", event_id="daily:2026-10-13"):
        g.messages.create(model=SONNET_5_5, max_tokens=10, messages=[])
        with g.context(domain="monetary_policy", purpose="qc_review", event_id="daily:2026-10-13"):
            g.messages.create(model=SONNET_5_5, max_tokens=10, messages=[])
    g.messages.create(model=SONNET_5_5, max_tokens=10, messages=[])  # buiten elk blok

    doelen = [r["purpose"] for r in reversed(list_llm_calls(conn))]
    assert doelen == ["deep_dive", "qc_review", None]
    assert list_llm_calls(conn, purpose="qc_review")[0]["domain"] == "monetary_policy"
    assert list_llm_calls(conn)[0]["event_id"] is None  # de laatste aanroep: context is hersteld


def test_een_mislukte_aanroep_wordt_met_de_fout_vastgelegd_en_blijft_een_uitzondering(tmp_path):
    conn = _db(tmp_path)

    class _Stuk:
        messages = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(TimeoutError("te traag")))

    g = _gemeterd(conn, _Stuk())
    with pytest.raises(TimeoutError):
        g.messages.create(model=SONNET_5_5, max_tokens=10, messages=[])
    (rij,) = list_llm_calls(conn)
    assert "TimeoutError: te traag" in rij["error"] and rij["response_text"] is None


def test_mislukt_wegschrijven_kost_het_antwoord_niet_en_crasht_niet_maar_wordt_hard_gelogd(tmp_path, monkeypatch, caplog):
    """De aanroep is al betaald. Het logboek is nuttig, maar mag nooit het antwoord of de run kosten."""
    from runtime import llm_budget

    conn = _db(tmp_path)
    monkeypatch.setattr(llm_budget, "record_llm_call", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("schijf vol")))
    with caplog.at_level(logging.ERROR):
        antwoord = _gemeterd(conn, _Client(("toch binnen",))).messages.create(model=SONNET_5_5, max_tokens=10, messages=[])

    assert antwoord.content[-1].text == "toch binnen"
    assert any("logboek" in r.message and "schijf vol" in r.message for r in caplog.records)
    assert list_llm_calls(conn) == []
    # De tokentelling voor de maandrem bleef intact.
    assert conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0] == 1


def test_geen_aanroep_door_de_maandrem_betekent_geen_logboekregel(tmp_path):
    conn = _db(tmp_path)
    g = _gemeterd(conn, _Client(), cap=0.0)
    with pytest.raises(BudgetExceeded):
        g.messages.create(model=SONNET_5_5, max_tokens=10, messages=[])
    assert list_llm_calls(conn) == []


# --------------------------------------------------------------------------
# Denkbeleid voor Sonnet 5.5
# --------------------------------------------------------------------------


def test_sonnet_5_5_krijgt_denken_uit_en_dat_staat_in_het_logboek(tmp_path):
    conn = _db(tmp_path)
    client = _Client()
    _gemeterd(conn, client).messages.create(model=SONNET_5_5, max_tokens=500, messages=[])
    assert client.calls[0]["thinking"] == {"type": "between_tools"}
    import json
    assert json.loads(list_llm_calls(conn)[0]["request_json"])["thinking"] == {"type": "between_tools"}


def test_andere_modellen_krijgen_geen_thinking_mee(tmp_path):
    """Regressie: `between_tools` is een 400 op Sonnet 4.6. Het beleid mag dus alleen 5.5 raken."""
    client = _Client()
    _gemeterd(_db(tmp_path), client).messages.create(model="claude-sonnet-4-6", max_tokens=500, messages=[])
    assert "thinking" not in client.calls[0]


def test_een_bewuste_keuze_van_de_aanroeper_wint_en_de_invoer_wordt_niet_gewijzigd():
    invoer = {"model": SONNET_5_5, "max_tokens": 5, "thinking": {"type": "adaptive"}}
    assert met_denkbeleid(invoer)["thinking"] == {"type": "adaptive"}
    kaal = {"model": SONNET_5_5, "max_tokens": 5}
    uit = met_denkbeleid(kaal)
    assert "thinking" in uit and "thinking" not in kaal  # de aanroeper zijn dict is niet aangepast
    uit["thinking"]["type"] = "x"
    assert DENKEN_UIT == {"type": "between_tools"}  # en de constante is niet gedeeld met de kopie


# --------------------------------------------------------------------------
# Het model en de koppeling met de agents
# --------------------------------------------------------------------------


def test_het_standaardmodel_is_sonnet_5_5_en_qc_py_is_niet_aangeraakt():
    assert DEFAULT_DEEP_DIVE_MODEL == SONNET_5_5
    assert qc.DEFAULT_LLM_REVIEW_MODEL == "claude-sonnet-4-6"  # checkpoint 2: qc.py ongewijzigd


DOEL = [ForecastTarget(
    metric_key="10y_treasury_yield", kind=PredictionKind.QUANTILE, horizon_kind=HorizonKind.TRADING_DAYS,
    horizons=(5,), resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER, resolution_rule="regel {horizon_n}",
)]
ANTWOORD = (
    '{"forecasts": [{"metric_key": "10y_treasury_yield", "horizon_n": 5, "q10": 3.9, "q25": 4.0, '
    '"q50": 4.1, "q75": 4.2, "q90": 4.3}]}'
)


def test_een_forecast_ronde_wordt_vastgelegd_met_domein_doel_event_en_het_nieuwe_model(tmp_path):
    conn = _db(tmp_path)
    g = _gemeterd(conn, _Client((ANTWOORD,)))
    resultaat = run_forecast_round(
        conn, g, "monetary_policy", "domeinprompt", DOEL, [], prompt_version="v2", now=NU, event_id="forecast:2026-W42",
    )
    assert len(resultaat.predictions) == 1 and len(list_predictions(conn)) == 1
    (rij,) = list_llm_calls(conn, purpose="forecast")
    assert (rij["domain"], rij["event_id"], rij["model"]) == ("monetary_policy", "forecast:2026-W42", SONNET_5_5)
    assert rij["response_text"] == ANTWOORD
    assert list_predictions(conn)[0].model_id == SONNET_5_5  # en het model gaat mee in de voorspelling


def test_een_deep_dive_legt_de_duiding_en_de_qc_review_apart_vast_en_beide_draaien_op_sonnet_5_5(tmp_path):
    conn = _db(tmp_path)
    g = _gemeterd(conn, _Client(("De duiding van de cijfers.", '{"issues": []}')))
    from contract.output_contract import Claim, Confidence

    claim = Claim(domain="monetary_policy", claim="Fed funds rate", value=5.5, source="FRED",
                  confidence=Confidence.HIGH, analysis_time=NU, metric_key="fed_funds_rate")
    run_deep_dive(conn, g, "monetary_policy", "systeemprompt", [claim], [], now=NU, event_id="daily:2026-10-13")

    rijen = {r["purpose"]: r for r in list_llm_calls(conn)}
    assert set(rijen) == {"deep_dive", "qc_review"}
    for r in rijen.values():
        assert r["domain"] == "monetary_policy" and r["event_id"] == "daily:2026-10-13"
        assert r["model"] == SONNET_5_5  # óók de QC-review, via de bestaande model-parameter
    assert rijen["qc_review"]["response_text"] == '{"issues": []}'


def test_een_client_zonder_context_werkt_gewoon_door(tmp_path):
    """Test-dubbels en kale Anthropic-clients hebben geen `context`; de agents mogen daar niet op stuklopen."""
    conn = _db(tmp_path)
    client = MagicMock()
    blok = MagicMock(type="text", text=ANTWOORD)
    client.messages.create.return_value = MagicMock(content=[blok])
    del client.context  # MagicMock verzint anders zelf een attribuut
    resultaat = run_forecast_round(conn, client, "monetary_policy", "p", DOEL, [], prompt_version="v2", now=NU)
    assert len(resultaat.predictions) == 1
