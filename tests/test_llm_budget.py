"""
test_llm_budget.py
Tests voor `runtime/llm_budget.py` en de time-out in `run_daily.build_client`
(roadmap 1.11, checkpoint 3, 30-09-2026).

WAT HIER OP HET SPEL STAAT. Zodra `--deep-dives` aanstaat, maakt een onbeheerd
systeem betaalde aanroepen. De maandrem moet (1) het verbruik werkelijk optellen,
(2) echt stoppen bij de grens, (3) NIET stil stoppen maar als een gewone mislukte
LLM-aanroep in de bestaande foutpaden terechtkomen, zodat het exit code 1 en een
melding geeft, en (4) niet onderuit gaan bij de maandwissel of een onbekend model.
"""

from __future__ import annotations

import importlib.util
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agents.base import run_deep_dive
from runtime.llm_budget import (
    DUURSTE_PRIJS,
    BudgetExceeded,
    MeteredClient,
    kosten_usd,
    max_maandbedrag,
    maandverbruik,
)
from storage.schema import init_db, list_agent_runs

ROOT = Path(__file__).resolve().parent.parent
NU = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)


class _Client:
    """Nep-client met een vast tokenverbruik per aanroep."""

    def __init__(self, input_tokens=1000, output_tokens=500, tekst="ok"):
        self.calls = []
        self._gebruik = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
        self._tekst = tekst
        self.messages = SimpleNamespace(create=self._create)
        self.overig = "doorgegeven"

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._tekst)],
            usage=self._gebruik, model=kwargs.get("model"),
        )


def _db(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def _gemeterd(conn, client, cap=200.0, nu=NU):
    return MeteredClient(client, conn, cap, nu=lambda: nu)


# --------------------------------------------------------------------------
# Kosten
# --------------------------------------------------------------------------


def test_de_kosten_kloppen_met_de_hand_nagerekend():
    # 1000 in x $3 + 500 uit x $15 = $0,003 + $0,0075 = $0,0105
    kosten, _ = kosten_usd("claude-sonnet-4-6", 1000, 500)
    assert kosten == pytest.approx(0.0105)


def test_een_onbekend_model_wordt_tegen_de_duurste_prijs_geteld():
    """Liever te vroeg remmen dan te laat."""
    kosten, notitie = kosten_usd("claude-iets-nieuws", 1_000_000, 1_000_000)
    assert kosten == pytest.approx(DUURSTE_PRIJS[0] + DUURSTE_PRIJS[1])
    assert "ONBEKEND" in notitie


# --------------------------------------------------------------------------
# Vastleggen
# --------------------------------------------------------------------------


def test_elke_aanroep_wordt_vastgelegd_en_opgeteld(tmp_path):
    conn = _db(tmp_path)
    client = _Client(1000, 500)
    g = _gemeterd(conn, client)

    g.messages.create(model="claude-sonnet-4-6", max_tokens=10, messages=[])
    g.messages.create(model="claude-sonnet-4-6", max_tokens=10, messages=[])

    m = maandverbruik(conn, NU)
    assert m.aanroepen == 2
    assert (m.input_tokens, m.output_tokens) == (2000, 1000)
    assert m.kosten_usd == pytest.approx(0.021)
    assert len(client.calls) == 2


def test_de_aanroep_zelf_wordt_ongewijzigd_doorgegeven(tmp_path):
    conn = _db(tmp_path)
    client = _Client()
    g = _gemeterd(conn, client)
    antwoord = g.messages.create(model="m", max_tokens=7, system="s", messages=[{"role": "user", "content": "x"}])

    assert client.calls == [{"model": "m", "max_tokens": 7, "system": "s", "messages": [{"role": "user", "content": "x"}]}]
    assert antwoord.content[0].text == "ok"
    assert g.overig == "doorgegeven"  # andere attributen gaan naar de echte client


def test_het_verbruik_overleeft_een_nieuwe_run(tmp_path):
    """De teller staat in de database, niet in het geheugen: een cron-run is een nieuw proces."""
    conn = _db(tmp_path)
    _gemeterd(conn, _Client(1_000_000, 0)).messages.create(model="claude-sonnet-4-6", messages=[])
    nieuw = _gemeterd(conn, _Client())  # nieuwe wrapper, zelfde database

    assert maandverbruik(conn, NU).kosten_usd == pytest.approx(3.0)
    assert nieuw.kosten_deze_run == 0.0


def test_een_aanroep_zonder_tokenverbruik_wordt_gemeld_en_niet_stil_genegeerd(tmp_path, caplog):
    conn = _db(tmp_path)
    client = _Client()
    client._gebruik = None
    caplog.set_level(logging.WARNING)

    _gemeterd(conn, client).messages.create(model="claude-sonnet-4-6", messages=[])

    assert "geen tokenverbruik" in caplog.text


# --------------------------------------------------------------------------
# De rem
# --------------------------------------------------------------------------


def test_bij_de_grens_wordt_er_niet_meer_aangeroepen(tmp_path):
    conn = _db(tmp_path)
    client = _Client(1_000_000, 0)  # $3 per aanroep op Sonnet 4.6
    g = _gemeterd(conn, client, cap=5.0)

    g.messages.create(model="claude-sonnet-4-6", messages=[])  # $3
    g.messages.create(model="claude-sonnet-4-6", messages=[])  # $6, grens nu overschreden
    with pytest.raises(BudgetExceeded, match="maandgrens"):
        g.messages.create(model="claude-sonnet-4-6", messages=[])

    assert len(client.calls) == 2, "de derde aanroep mag de API niet bereiken"


def test_de_grens_zelf_telt_als_bereikt(tmp_path):
    conn = _db(tmp_path)
    client = _Client(1_000_000, 0)
    g = _gemeterd(conn, client, cap=3.0)
    g.messages.create(model="claude-sonnet-4-6", messages=[])  # precies $3

    with pytest.raises(BudgetExceeded):
        g.messages.create(model="claude-sonnet-4-6", messages=[])


def test_de_volgende_maand_begint_weer_bij_nul(tmp_path):
    conn = _db(tmp_path)
    client = _Client(1_000_000, 0)
    oktober = _gemeterd(conn, client, cap=3.0, nu=NU)
    oktober.messages.create(model="claude-sonnet-4-6", messages=[])
    with pytest.raises(BudgetExceeded):
        oktober.messages.create(model="claude-sonnet-4-6", messages=[])

    november = _gemeterd(conn, client, cap=3.0, nu=datetime(2026, 11, 2, 7, 15, tzinfo=timezone.utc))
    november.messages.create(model="claude-sonnet-4-6", messages=[])  # geen uitzondering

    assert maandverbruik(conn, datetime(2026, 11, 2, tzinfo=timezone.utc)).kosten_usd == pytest.approx(3.0)


def test_de_maand_wisselt_op_utc_en_niet_op_lokale_tijd(tmp_path):
    """Een aanroep om 23:30 op 31 oktober (UTC) hoort bij oktober."""
    conn = _db(tmp_path)
    laat = datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)
    _gemeterd(conn, _Client(1_000_000, 0), nu=laat).messages.create(model="claude-sonnet-4-6", messages=[])

    assert maandverbruik(conn, datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc)).aanroepen == 1
    assert maandverbruik(conn, datetime(2026, 11, 1, 0, 1, tzinfo=timezone.utc)).aanroepen == 0


def test_boven_de_helft_van_de_grens_komt_een_waarschuwing(tmp_path, caplog):
    conn = _db(tmp_path)
    g = _gemeterd(conn, _Client(1_000_000, 0), cap=5.0)
    caplog.set_level(logging.WARNING)

    g.messages.create(model="claude-sonnet-4-6", messages=[])  # $3 = 60% van $5

    assert "60%" in caplog.text


# --------------------------------------------------------------------------
# De rem is NIET stil: hij komt in de bestaande foutpaden terecht
# --------------------------------------------------------------------------


def test_een_geremde_deep_dive_wordt_needs_review_en_niet_weggegooid(tmp_path):
    """`run_deep_dive` vangt een mislukte LLM-aanroep op en maakt er een zichtbare
    `needs_review`-uitkomst van. De rem moet daar precies zo in vallen."""
    from contract.output_contract import Claim, Confidence

    conn = _db(tmp_path)
    client = _Client(1_000_000, 0)
    g = _gemeterd(conn, client, cap=1.0)
    g.messages.create(model="claude-sonnet-4-6", messages=[])  # grens gehaald

    claim = Claim(domain="d", claim="c", value=1.0, source="s", confidence=Confidence.HIGH, analysis_time=NU)
    uitkomst = run_deep_dive(conn, g, "d", "prompt", [claim], [], now=NU, event_id="daily:2026-10-09")

    assert uitkomst.needs_review is True
    assert "maandgrens" in " ".join(str(c.value) for c in uitkomst.claims), "de reden moet zichtbaar zijn"
    runs = list_agent_runs(conn, "d")
    assert any(not r["success"] and "maandgrens" in (r["error"] or "") for r in runs)


# --------------------------------------------------------------------------
# De instelling
# --------------------------------------------------------------------------


def test_de_standaardgrens_is_tweehonderd_dollar():
    assert max_maandbedrag({}) == 200.0
    assert max_maandbedrag({"MI_MAX_MAANDBEDRAG_USD": ""}) == 200.0


def test_de_grens_is_instelbaar():
    assert max_maandbedrag({"MI_MAX_MAANDBEDRAG_USD": "50"}) == 50.0


@pytest.mark.parametrize("waarde", ["twintig", "0", "-5", "nan"])
def test_een_ongeldige_grens_is_een_fout_en_geen_stille_default(waarde):
    with pytest.raises(ValueError):
        max_maandbedrag({"MI_MAX_MAANDBEDRAG_USD": waarde})


# --------------------------------------------------------------------------
# run_daily.py: time-out en aansluiting
# --------------------------------------------------------------------------


def _run_daily_module():
    spec = importlib.util.spec_from_file_location("run_daily_cli", ROOT / "run_daily.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_de_client_krijgt_een_timeout_en_een_beperkt_aantal_herhalingen(monkeypatch):
    """De SDK-standaard (10 minuten, twee herhalingen) kon één hangende aanroep een
    half uur laten duren; `flock` liet de run van de volgende dag dan overslaan."""
    module = _run_daily_module()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-sleutel")
    gebouwd = {}

    import anthropic

    class _Nep:
        def __init__(self, **kw):
            gebouwd.update(kw)

    monkeypatch.setattr(anthropic, "Anthropic", _Nep)
    module.build_client()

    assert gebouwd["timeout"] == 90.0
    assert gebouwd["max_retries"] == 2
    assert gebouwd["api_key"] == "test-sleutel"


def test_een_ongeldige_maandgrens_stopt_run_daily_met_exit_twee(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-sleutel")
    monkeypatch.setenv("MI_MAX_MAANDBEDRAG_USD", "veel")
    module = _run_daily_module()

    assert module.main(["--db", str(tmp_path / "t.db"), "--deep-dives"]) == 2


def test_de_maandgrens_is_niet_nodig_zonder_deep_dives(tmp_path, monkeypatch):
    """Een typefout in een variabele die niet gebruikt wordt mag de ingestie niet stoppen."""
    import runtime.daily as daily

    monkeypatch.setenv("MI_MAX_MAANDBEDRAG_USD", "veel")
    monkeypatch.setattr(daily, "default_agents", lambda: [])
    module = _run_daily_module()

    assert module.main(["--db", str(tmp_path / "t.db")]) == 0


def test_run_daily_logt_het_verbruik_met_deep_dives(tmp_path, monkeypatch, caplog):
    import anthropic
    import runtime.daily as daily

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-sleutel")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: _Client())
    monkeypatch.setattr(daily, "default_agents", lambda: [])
    caplog.set_level(logging.INFO)

    _run_daily_module().main(["--db", str(tmp_path / "t.db"), "--deep-dives"])

    assert "LLM-verbruik" in caplog.text
    assert "van $200" in caplog.text
