"""
test_synthesizer_forecast.py
De synthesizer als gescoorde voorspeller (`synthesizer/forecast.py`, roadmap 4.5, slanke v1, 02-10-2026).

Wat bewaakt wordt: (1) de synthesizer is BLIND voor de voorspellingen van anderen (besluit DD): in de prompt komt nooit een kwantiel
of kans van een agent, mens of baseline; (2) hij voorspelt dezelfde doelen als de domain agents, onder `agent="synthesizer"` met als
`domain` het vakgebied van het doel; (3) één call voor alles, idempotent per week; (4) zonder claims geen betaalde call; (5) de
domain agents zijn door de aanpassing van `run_forecast_round` niet veranderd.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from agents.base import AlreadyProcessedError, ForecastTarget
from contract.output_contract import Claim, Confidence, DomainOutput, Mode
from contract.prediction import HorizonKind, Prediction, PredictionKind
from contract.resolution import ResolutionMethod
from runtime.daily import AgentSpec, default_agents
from storage.schema import init_db, list_agent_runs, list_predictions, save_domain_output, save_predictions_with_run
from synthesizer import forecast as sf

NU = datetime(2026, 10, 5, 7, 15, tzinfo=timezone.utc)   # maandag


def _doel(key: str, horizons=(5, 21)) -> ForecastTarget:
    return ForecastTarget(
        metric_key=key, kind=PredictionKind.QUANTILE, horizon_kind=HorizonKind.TRADING_DAYS, horizons=horizons,
        resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER, resolution_rule=f"{key} eerste print op of na resolves_at ({{horizon_n}} hd)",
    )


def _spec(domain: str, *keys: str) -> AgentSpec:
    return AgentSpec(domain=domain, monitor=lambda *a, **k: None, deep_dive=lambda *a, **k: None,
                     forecast_targets=tuple(_doel(k) for k in keys), forecast_system_prompt="", prompt_version=f"{domain}-v0")


AGENTS = [_spec("financial", "vix", "hy"), _spec("currency", "eur_usd"), _spec("commodity")]


def _slaan_op(conn, domain: str, reeksen: dict[str, float], dagen: int = 400) -> None:
    """Eerst de historie (een oude cyclus), dan de laatste cyclus met één claim per reeks: zo ziet `load_monitoring_claims` precies
    de laatste waarden, zoals in het echt."""
    historie = [
        Claim(domain=domain, claim=f"{key} niveau", value=waarde + 0.01 * i, source="test", confidence=Confidence.HIGH,
              analysis_time=NU - timedelta(days=dagen - i), source_time=NU - timedelta(days=dagen - i), metric_key=key)
        for key, waarde in reeksen.items() for i in range(dagen)
    ]
    save_domain_output(conn, DomainOutput(domain=domain, mode=Mode.MONITORING, generated_at=NU - timedelta(days=dagen + 5), claims=historie))
    laatste = [
        Claim(domain=domain, claim=f"{key} niveau", value=waarde + 0.01 * dagen, source="test", confidence=Confidence.HIGH,
              analysis_time=NU - timedelta(days=1), source_time=NU - timedelta(days=1), metric_key=key)
        for key, waarde in reeksen.items()
    ]
    save_domain_output(conn, DomainOutput(domain=domain, mode=Mode.MONITORING, generated_at=NU - timedelta(days=1), claims=laatste))


@pytest.fixture
def conn(tmp_path):
    c = init_db(str(tmp_path / "t.db"))
    _slaan_op(c, "financial", {"vix": 15.0, "hy": 3.0})
    _slaan_op(c, "currency", {"eur_usd": 1.10})
    _slaan_op(c, "commodity", {"wti": 70.0})
    yield c
    c.close()


def _client(tekst: str):
    client = MagicMock()
    blok = MagicMock()
    blok.type = "text"
    blok.text = tekst
    client.messages.create.return_value = MagicMock(content=[blok])
    return client


def _antwoord() -> str:
    regels = []
    for key, mid in (("vix", 16.0), ("hy", 3.1), ("eur_usd", 1.1)):
        for n in (5, 21) if key != "eur_usd" else (5, 21):
            regels.append(f'{{"metric_key": "{key}", "horizon_n": {n}, "q10": {mid - 1}, "q25": {mid - .5}, "q50": {mid}, "q75": {mid + .5}, "q90": {mid + 1}}}')
    return '{"forecasts": [' + ",".join(regels) + "]}"


# --- De doelen ---


def test_doelen_zijn_de_doelen_van_de_agents_met_hun_vakgebied():
    d = sf.doelen(AGENTS)
    assert [t.metric_key for t in d.targets] == ["vix", "hy", "eur_usd"]
    assert d.domain_of == {"vix": "financial", "hy": "financial", "eur_usd": "currency"}


def test_een_doel_bij_twee_agents_wordt_geweigerd():
    with pytest.raises(ValueError, match="twee agents"):
        sf.doelen([_spec("financial", "vix"), _spec("economic", "vix")])


def test_de_echte_agents_hebben_geen_dubbele_doelen_en_het_zijn_er_57():
    d = sf.doelen()
    assert len({t.metric_key for t in d.targets}) == len(d.targets)
    assert sum(len(t.horizons) for t in d.targets) == 57


# --- Blind ---


def test_de_prompt_bevat_nooit_de_voorspellingen_van_anderen(conn):
    for agent, domain in (("financial", "financial"), ("baseline:persistence", "financial"), ("human:dd", "financial")):
        save_predictions_with_run(conn, [Prediction(
            agent=agent, domain=domain, target_metric_key="vix", kind=PredictionKind.QUANTILE, horizon_kind=HorizonKind.TRADING_DAYS,
            horizon_n=5, created_at=NU - timedelta(days=7), resolves_at=NU, resolution_rule="r", resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER,
            model_id="m", prompt_version="p", q10=987.1, q25=987.2, q50=987.3, q75=987.4, q90=987.5,
        )], agent, NU - timedelta(days=7), success=True, event_id=f"w-{agent}")
    systeem, gebruiker = sf.bouw_prompt(conn, NU, AGENTS)
    tekst = systeem + gebruiker
    assert "987." not in tekst
    for naam in ("baseline:", "human:", "persistence", "forecasts van de agents"):
        assert naam not in gebruiker
    # wat de agents wel zien, ziet hij ook: de cijfers van ALLE vakgebieden, ook commodity (alleen als context)
    assert "vix niveau" in gebruiker and "eur_usd niveau" in gebruiker and "wti niveau" in gebruiker
    assert "ALLE vakgebieden" in gebruiker


def test_het_systeemprompt_zegt_dat_hij_de_voorspellingen_van_anderen_niet_ziet():
    assert "NIET ziet" in sf.SYNTHESIZER_SYSTEM_PROMPT and "voorspellingen van de domain agents" in sf.SYNTHESIZER_SYSTEM_PROMPT


# --- De ronde ---


def test_een_ronde_slaat_voorspellingen_op_als_synthesizer_met_het_vakgebied_van_het_doel(conn):
    client = _client(_antwoord())
    uitkomst = sf.run_synthesizer_round(conn, client, now=NU, event_id="2026-W41", agents=AGENTS)
    assert uitkomst.is_complete and len(uitkomst.predictions) == 6
    opgeslagen = list_predictions(conn)
    assert {p.agent for p in opgeslagen} == {"synthesizer"}
    assert {(p.target_metric_key, p.domain) for p in opgeslagen} == {("vix", "financial"), ("hy", "financial"), ("eur_usd", "currency")}
    assert {p.prompt_version for p in opgeslagen} == {"synthesizer-v1"}
    assert all(p.model_id for p in opgeslagen)
    assert len(list_predictions(conn)) == 6


def test_een_call_met_genoeg_antwoordruimte_en_de_juiste_kop(conn):
    client = _client(_antwoord())
    sf.run_synthesizer_round(conn, client, now=NU, event_id="2026-W41", agents=AGENTS)
    assert client.messages.create.call_count == 1
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] == sf.MAX_TOKENS >= 4000
    assert "ALLE vakgebieden" in kwargs["messages"][0]["content"] and "voor jouw domein" not in kwargs["messages"][0]["content"]
    assert sf.SYNTHESIZER_SYSTEM_PROMPT in kwargs["system"]


def test_een_tweede_ronde_in_dezelfde_week_wordt_geweigerd(conn):
    sf.run_synthesizer_round(conn, _client(_antwoord()), now=NU, event_id="2026-W41", agents=AGENTS)
    with pytest.raises(AlreadyProcessedError):
        sf.run_synthesizer_round(conn, _client(_antwoord()), now=NU, event_id="2026-W41", agents=AGENTS)
    assert len(list_predictions(conn)) == 6
    runs = list_agent_runs(conn, "synthesizer")
    assert len(runs) == 1


def test_zonder_claims_geen_call_en_geen_run(tmp_path):
    leeg = init_db(str(tmp_path / "leeg.db"))
    client = _client(_antwoord())
    uitkomst = sf.run_synthesizer_round(leeg, client, now=NU, event_id="2026-W41", agents=AGENTS)
    assert not uitkomst.predictions and uitkomst.issues
    assert client.messages.create.call_count == 0
    assert list_agent_runs(leeg, "synthesizer") == []


def test_een_onvolledig_antwoord_is_een_probleem_maar_bewaart_de_rest(conn):
    antwoord = _antwoord().replace('"eur_usd"', '"onbekend"', 1)
    uitkomst = sf.run_synthesizer_round(conn, _client(antwoord), now=NU, event_id="2026-W41", agents=AGENTS)
    assert not uitkomst.is_complete and len(uitkomst.predictions) == 5
    assert any("geen voorspelling" in i for i in uitkomst.issues) and any("onbekend doel" in i for i in uitkomst.issues)


def test_een_mislukte_llm_call_wordt_als_mislukt_geregistreerd_en_blokkeert_een_herhaling_niet(conn):
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("API plat")
    uitkomst = sf.run_synthesizer_round(conn, client, now=NU, event_id="2026-W41", agents=AGENTS)
    assert not uitkomst.predictions and "API plat" in uitkomst.issues[0]
    sf.run_synthesizer_round(conn, _client(_antwoord()), now=NU, event_id="2026-W41", agents=AGENTS)
    assert len(list_predictions(conn)) == 6


# --- De domain agents zijn niet veranderd ---


def test_een_domain_agent_blijft_voorspellen_als_zichzelf(conn):
    from agents.base import run_forecast_round
    doel = _doel("vix", (5,))
    antwoord = '{"forecasts": [{"metric_key": "vix", "horizon_n": 5, "q10": 1, "q25": 2, "q50": 3, "q75": 4, "q90": 5}]}'
    run_forecast_round(conn, _client(antwoord), "financial", "prompt", [doel], [], prompt_version="financial-v3", now=NU)
    p = list_predictions(conn)[0]
    assert p.agent == "financial" and p.domain == "financial"


def test_de_echte_prompt_bevat_de_regels_en_is_niet_leeg_en_de_versie_staat_vast():
    assert sf.FORECAST_PROMPT_VERSION == "v1" and sf.AGENT == "synthesizer"
    assert sf.DEEP_DIVE_SYSTEM_PROMPT == sf.SYNTHESIZER_SYSTEM_PROMPT


# --- Het voorblik (alleen lezen) ---


def _laad_script():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("synthesizer_preview_script", Path(__file__).parent.parent / "synthesizer_preview.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_het_voorblik_is_read_only_roept_geen_llm_aan_en_wijzigt_niets(tmp_path, capsys, monkeypatch):
    from pathlib import Path
    db = tmp_path / "v.db"
    c = init_db(str(db))
    _slaan_op(c, "financial", {"vix": 15.0})
    voor = c.execute("SELECT COUNT(*) FROM claims").fetchone()[0], c.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    c.close()
    script = _laad_script()
    assert script.main(["--db", str(db)]) == 0
    uit = capsys.readouterr().out
    assert "SYNTHESIZER-VOORBLIK" in uit and "geen LLM-aanroep" in uit and "voorspellingen per ronde" in uit and "SYSTEEMPROMPT" in uit
    c = init_db(str(db))
    assert (c.execute("SELECT COUNT(*) FROM claims").fetchone()[0], c.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]) == voor
    c.close()
    assert script.main(["--db", str(tmp_path / "bestaat_niet.db")]) == 2
    assert "mode=ro" in (Path(__file__).parent.parent / "synthesizer_preview.py").read_text(encoding="utf-8")
