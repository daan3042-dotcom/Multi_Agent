"""
test_economic_agent.py
Tests voor de lean economic agent (roadmap 2.7).

Patroon zoals test_monetary_policy_agent.py en test_financial_agent.py:
fetch-gedrag, wiring in run_monitoring/run_deep_dive, registratie in de
Source Registry, plus de verrijking met het onderbouwingsmodel (hier de
Sahm Rule, zoals daar de Taylor Rule).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import agents.economic_agent as eco
from analysis.sahm_rule import MIN_OBSERVATIONS
from storage.schema import get_source, init_db, load_latest_claims


def test_fetch_snapshot_without_api_key_returns_error(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert "error" in eco.fetch_snapshot()


def test_fetch_snapshot_returns_available_series(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        if params["series_id"] == "ICSA":
            resp.json = lambda: {"observations": [{"value": "223000", "date": "2026-09-20"}]}
        else:
            resp.json = lambda: {"observations": [{"value": ".", "date": "2026-09-01"}]}
        return resp

    monkeypatch.setattr(eco.requests, "get", fake_get)
    result = eco.fetch_snapshot()

    assert result["initial_claims"]["value"] == "223000"
    assert "unemployment_rate" not in result  # placeholder wordt overgeslagen, geen gok


def test_fetch_snapshot_all_series_fail_returns_error(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")
    monkeypatch.setattr(eco.requests, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("netwerkfout")))
    assert "error" in eco.fetch_snapshot()


def test_elke_opgehaalde_reeks_heeft_een_metric_spec():
    """REGRESSIE, zelfde reden als bij de monetary agent: een reeks zonder
    spec levert wel claims maar nooit een trigger -- data die niemand ziet."""
    assert set(eco.FRED_SERIES) == set(eco.METRIC_SPECS)


def test_monitor_wires_into_run_monitoring(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(eco, "fetch_snapshot", lambda: {
        "initial_claims": {"value": "223000", "date": "2026-09-20"},
        "nonfarm_payrolls": {"value": "159200", "date": "2026-09-01"},
    })

    output, triggers = eco.monitor(conn, now=now)

    assert output is not None
    assert output.domain == "economic"
    assert triggers == []  # eerste observatie, geen vorige waarde
    metrics = {c.metric_key for c in load_latest_claims(conn, "economic")}
    assert {"initial_claims", "nonfarm_payrolls"} <= metrics


def test_monitor_registreert_eigen_source_key(tmp_path, monkeypatch):
    """Roadmap 1.4: derde FRED-agent, dus een eigen gescopete source_key --
    anders zouden monetary, financial en economic dezelfde data_health-rij
    delen en kan de ene agent's succes de andere's storing verbergen."""
    conn = init_db(str(tmp_path / "t.db"))
    monkeypatch.setattr(eco, "fetch_snapshot", lambda: {"initial_claims": {"value": "223000", "date": "2026-09-20"}})
    eco.monitor(conn, now=datetime.now(timezone.utc))

    source = get_source(conn, "FRED:economic")
    assert source is not None
    assert source.provider == "FRED"
    assert source.domain == "economic"


def test_banenverlies_triggert(tmp_path, monkeypatch):
    """PAYEMS is een NIVEAU, dus de delta tussen twee observaties is de
    maandelijkse banengroei. Een daling van 159.200 naar 158.900 is een
    verlies van 300 duizend banen en moet vuren (tolerance 250)."""
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)

    monkeypatch.setattr(eco, "fetch_snapshot", lambda: {"nonfarm_payrolls": {"value": "159200", "date": "2026-08-01"}})
    eco.monitor(conn, now=now)

    monkeypatch.setattr(eco, "fetch_snapshot", lambda: {"nonfarm_payrolls": {"value": "158900", "date": "2026-09-01"}})
    _, triggers = eco.monitor(conn, now=now + timedelta(days=30))

    assert any(t.metric_key == "nonfarm_payrolls" for t in triggers)


def test_normale_maand_banengroei_triggert_niet(tmp_path, monkeypatch):
    """REGRESSIE op de tolerance: +150 duizend banen is een gewone maand en
    mag de deep-dive-machinerie niet elke maand wakker maken."""
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)

    monkeypatch.setattr(eco, "fetch_snapshot", lambda: {"nonfarm_payrolls": {"value": "159000", "date": "2026-08-01"}})
    eco.monitor(conn, now=now)

    monkeypatch.setattr(eco, "fetch_snapshot", lambda: {"nonfarm_payrolls": {"value": "159150", "date": "2026-09-01"}})
    _, triggers = eco.monitor(conn, now=now + timedelta(days=30))

    assert not any(t.metric_key == "nonfarm_payrolls" for t in triggers)


# --- Sahm Rule-verrijking ---


def test_fetch_series_history_draait_de_volgorde_om(monkeypatch):
    """REGRESSIE die er echt toe doet: FRED levert AFLOPEND (nieuwste
    eerst), sahm_rule.py verwacht CHRONOLOGISCH (oudste eerst). Zonder de
    omkering berekent de Sahm Rule het spiegelbeeld van de werkelijkheid --
    een dalende werkloosheid zou dan als oplopend gelezen worden."""
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"observations": [
            {"value": "4.3", "date": "2026-09-01"},
            {"value": "4.1", "date": "2026-08-01"},
            {"value": "3.9", "date": "2026-07-01"},
        ]}
        return resp

    monkeypatch.setattr(eco.requests, "get", fake_get)
    assert eco._fetch_series_history("UNRATE", "fake-key", 3) == [3.9, 4.1, 4.3]


def test_fetch_series_history_weigert_een_te_korte_reeks(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"observations": [{"value": "4.0", "date": "2026-09-01"}]}
        return resp

    monkeypatch.setattr(eco.requests, "get", fake_get)
    assert eco._fetch_series_history("UNRATE", "fake-key", MIN_OBSERVATIONS) is None


def test_fetch_series_history_weigert_bij_een_placeholder(monkeypatch):
    """Een gat in de reeks zou stilzwijgend een ander venster opleveren dan
    het gepubliceerde model gebruikt."""
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"observations": [
            {"value": "4.3", "date": "2026-09-01"},
            {"value": ".", "date": "2026-08-01"},
            {"value": "3.9", "date": "2026-07-01"},
        ]}
        return resp

    monkeypatch.setattr(eco.requests, "get", fake_get)
    assert eco._fetch_series_history("UNRATE", "fake-key", 3) is None


def _deep_dive_setup(tmp_path):
    from contract.output_contract import Claim, Confidence

    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    claim = Claim(
        domain="economic", claim="Werkloosheidspercentage", value=4.4,
        source="FRED", confidence=Confidence.HIGH, analysis_time=now,
        metric_key="unemployment_rate",
    )
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[MagicMock(text="analyse")])
    return conn, now, claim, client


def test_deep_dive_voegt_sahm_claims_toe(tmp_path, monkeypatch):
    conn, now, claim, client = _deep_dive_setup(tmp_path)
    # 12 maanden vlak op 3,5 daarna oplopend: gap 0,60 -> getriggerd
    monkeypatch.setattr(eco, "_fetch_sahm_inputs", lambda: [3.5] * 12 + [3.8, 4.1, 4.4])

    output = eco.deep_dive(conn, client, [claim], [], now=now)

    teksten = [c.claim for c in output.claims]
    assert any("Sahm Rule-gap" in t for t in teksten)
    assert any("GETRIGGERD" in t for t in teksten)


def test_deep_dive_slaat_sahm_over_zonder_inputs(tmp_path, monkeypatch):
    """Geen API-key of een te korte historie: de deep-dive gaat door zonder
    verrijking, hij faalt niet en verzint geen halve berekening."""
    conn, now, claim, client = _deep_dive_setup(tmp_path)
    monkeypatch.setattr(eco, "_fetch_sahm_inputs", lambda: None)

    output = eco.deep_dive(conn, client, [claim], [], now=now)

    assert not any("Sahm" in c.claim for c in output.claims)


def test_deep_dive_zonder_werkloosheidsclaim_doet_geen_sahm(tmp_path, monkeypatch):
    """REGRESSIE tegen een onnodige netwerkcall: triggert alleen ICSA, dan
    is er geen werkloosheidscijfer en hoeft de Sahm-historie niet
    opgehaald te worden."""
    from contract.output_contract import Claim, Confidence

    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[MagicMock(text="analyse")])
    claim = Claim(
        domain="economic", claim="Wekelijkse WW-aanvragen", value=223000.0,
        source="FRED", confidence=Confidence.HIGH, analysis_time=now,
        metric_key="initial_claims",
    )

    def boom():
        raise AssertionError("_fetch_sahm_inputs had niet aangeroepen mogen worden")

    monkeypatch.setattr(eco, "_fetch_sahm_inputs", boom)
    output = eco.deep_dive(conn, client, [claim], [], now=now)

    assert not any("Sahm" in c.claim for c in output.claims)


def test_economic_domain_is_classificeerbaar():
    """REGRESSIE. classify_domain() faalt hard op een onbekend domain. Een
    nieuwe agent die daar niet in staat, laat de synthesizer omvallen zodra
    hij het domein wil indelen."""
    from contract.domain_ontology import DomainCategory, classify_domain

    assert classify_domain("economic") == [DomainCategory.MACRO]


def test_agent_staat_nog_niet_in_de_dagelijkse_runner():
    """CHECKPOINT 1 uit CLAUDE.md: een nieuwe agent wordt pas aan de
    onbeheerde cyclus gekoppeld nadat DD hem heeft gezien. Deze test legt
    die grens vast -- valt hij om, dan is de koppeling gemaakt en hoort
    deze test in dezelfde ronde geschrapt te worden, bewust en zichtbaar."""
    import inspect

    from runtime import daily

    assert "economic_agent" not in inspect.getsource(daily)
