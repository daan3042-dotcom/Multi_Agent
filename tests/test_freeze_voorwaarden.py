"""
test_freeze_voorwaarden.py
De tweede helft van het freeze-overzicht: de VOORWAARDEN vóór de klok (`runtime/freeze_voorwaarden.py`). 02-10-2026.

De kernregel die hier bewaakt wordt: alleen wat uit de data af te leiden ÉN voldaan is, heet AF. Wat de data niet kan
bewijzen (kwaliteit van een analyse, een herstelde back-up, een doorlopen dry-run-week) blijft ZELF CONTROLEREN, ook als
alles er goed uitziet. En: dit schrijft niets.

De tests draaien tegen een gevulde database (agent_runs, llm_calls, predictions, evaluations), niet tegen een lege.
"""

from __future__ import annotations

import hashlib
import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from contract.prediction import HorizonKind, Prediction, PredictionKind
from contract.resolution import ResolutionMethod
from runtime import freeze_status as fs
from runtime import freeze_voorwaarden as fv
from runtime.daily import default_agents
from runtime.t0a_status import werkdagen
from storage.schema import init_db, record_agent_run, save_evaluation, record_llm_call, save_prediction

ROOT = Path(__file__).resolve().parent.parent
DOMEINEN = [a.domain for a in default_agents()]
START = date(2026, 10, 2)


def _tijd(d: date, uur=7, minuut=15) -> datetime:
    return datetime(d.year, d.month, d.day, uur, minuut, tzinfo=timezone.utc)


def _schone_dagen(conn, aantal: int, uur=7) -> date:
    """Vult `aantal` schone werkdagen vanaf de startdatum. Geeft de laatste dag terug."""
    dagen = werkdagen(START, START + timedelta(days=aantal * 2 + 5))[:aantal]
    for d in dagen:
        for dom in DOMEINEN:
            record_agent_run(conn, dom, "monitoring", _tijd(d, uur), True)
    return dagen[-1]


def _na(d: date) -> datetime:
    return _tijd(d + timedelta(days=1), 12)


def _voorwaarden(db, nu):
    return {naam: (waarde, status, opm) for naam, waarde, status, opm in fv.bepaal_voorwaarden(db, nu)}


def _voorspelling(**kw):
    basis = dict(
        agent="monetary_policy", domain="monetary_policy", target_metric_key="dgs10",
        kind=PredictionKind.QUANTILE, horizon_kind=HorizonKind.TRADING_DAYS, horizon_n=5,
        created_at=_tijd(START), resolves_at=_tijd(START) + timedelta(days=7), resolution_rule="regel",
        resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER, model_id="m", prompt_version="p",
        q10=3.9, q25=4.0, q50=4.1, q75=4.25, q90=4.4,
    )
    basis.update(kw)
    return Prediction(**basis)


def _db(tmp_path):
    pad = str(tmp_path / "t.db")
    return pad, init_db(pad)


# --------------------------------------------------------------------------
# Zonder database en met een lege database
# --------------------------------------------------------------------------


def test_zonder_database_is_niets_af_en_niets_nog_niet_af_voor_wat_onbekend_is(tmp_path):
    uit = _voorwaarden(str(tmp_path / "bestaat_niet.db"), _tijd(START))
    waarde, status, _ = uit["Datagedreven voorwaarden"]
    assert "onbekend" in waarde and status == fv.ZELF_CONTROLEREN
    assert fv.AF not in {s for _, s, _ in uit.values()}  # een kale checkout kan nooit "klaar" melden


def test_een_lege_database_zegt_voor_elke_datagedreven_voorwaarde_nog_niet_af(tmp_path):
    pad, conn = _db(tmp_path)
    conn.close()
    uit = _voorwaarden(pad, _tijd(START))
    for naam in ("T₀ᵃ (ingestieklok)", "14 werkdagen op rij zonder handmatige actie", "Begeleide deep-dive-testrun",
                 "Forecast-rondes met het echte model", "Resolver heeft afgewikkeld (incl. release-horizon)",
                 "Pseudo-OOS-run (4.4)"):
        assert uit[naam][1] == fv.NOG_NIET_AF, naam


# --------------------------------------------------------------------------
# T₀ᵃ en de 14 werkdagen
# --------------------------------------------------------------------------


def test_zeven_schone_werkdagen_halen_t0a_maar_nog_niet_de_veertien(tmp_path):
    pad, conn = _db(tmp_path)
    laatste = _schone_dagen(conn, 7)
    conn.close()
    uit = _voorwaarden(pad, _na(laatste))
    assert uit["T₀ᵃ (ingestieklok)"][1] == fv.AF
    assert uit["14 werkdagen op rij zonder handmatige actie"][1] == fv.NOG_NIET_AF
    assert uit["14 werkdagen op rij zonder handmatige actie"][0] == "7 van 14"


def test_veertien_schone_werkdagen_op_rij_halen_de_veertien(tmp_path):
    pad, conn = _db(tmp_path)
    laatste = _schone_dagen(conn, 14)
    conn.close()
    assert _voorwaarden(pad, _na(laatste))["14 werkdagen op rij zonder handmatige actie"][1] == fv.AF


def test_dertien_werkdagen_zijn_er_een_te_weinig(tmp_path):
    """Regressie op de grens: precies 13 mag niet als 14 tellen."""
    pad, conn = _db(tmp_path)
    laatste = _schone_dagen(conn, 13)
    conn.close()
    assert _voorwaarden(pad, _na(laatste))["14 werkdagen op rij zonder handmatige actie"][1] == fv.NOG_NIET_AF


def test_een_run_buiten_het_cronvenster_telt_niet_mee_voor_geen_handmatige_actie(tmp_path):
    pad, conn = _db(tmp_path)
    dagen = werkdagen(START, START + timedelta(days=40))[:15]
    for i, d in enumerate(dagen):
        for dom in DOMEINEN:
            record_agent_run(conn, dom, "monitoring", _tijd(d, 15 if i == 3 else 7), True)  # dag 4 om 15:00 = handmatig
    conn.close()
    uit = _voorwaarden(pad, _na(dagen[-1]))
    assert uit["14 werkdagen op rij zonder handmatige actie"][0] == "11 van 14"  # dag 5 t/m 15
    assert uit["14 werkdagen op rij zonder handmatige actie"][1] == fv.NOG_NIET_AF


def test_een_niet_schone_dag_zet_de_reeks_op_nul(tmp_path):
    pad, conn = _db(tmp_path)
    dagen = werkdagen(START, START + timedelta(days=40))[:9]
    for i, d in enumerate(dagen):
        for dom in DOMEINEN:
            record_agent_run(conn, dom, "monitoring", _tijd(d), success=not (i == 4 and dom == "sector"))
    conn.close()
    uit = _voorwaarden(pad, _na(dagen[-1]))
    assert uit["14 werkdagen op rij zonder handmatige actie"][0] == "4 van 14"
    assert uit["T₀ᵃ (ingestieklok)"][1] == fv.NOG_NIET_AF


# --------------------------------------------------------------------------
# Testrun, forecast, resolver, pseudo-OOS: gedaan is niet hetzelfde als goed
# --------------------------------------------------------------------------


def test_een_deep_dive_in_het_logboek_is_zelf_controleren_en_nooit_af(tmp_path):
    pad, conn = _db(tmp_path)
    nu = _tijd(date(2026, 10, 13), 13)
    record_llm_call(conn, nu, "claude-sonnet-5-5", {"x": 1}, response_text="analyse", domain="sector", purpose="deep_dive")
    record_llm_call(conn, nu, "claude-sonnet-5-5", {"x": 1}, response_text=None, error="boom", domain="currency",
                  purpose="deep_dive")  # een mislukte aanroep telt niet als testrun
    record_llm_call(conn, nu, "claude-sonnet-5-5", {"x": 1}, response_text="ok", domain="sector", purpose="forecast")
    conn.close()
    waarde, status, opm = _voorwaarden(pad, nu)["Begeleide deep-dive-testrun"]
    assert status == fv.ZELF_CONTROLEREN
    assert waarde.startswith("1 aanroepen, 1 domein(en)") and "2026-10-13" in waarde
    assert "OPRECHT GOED" in opm


def _forecast_ronde(conn, domein, aantal, dag=date(2026, 10, 5)):
    record_agent_run(conn, domein, "forecast", _tijd(dag), success=bool(aantal), trigger_count=aantal)


def test_volledige_forecast_rondes_zijn_zelf_controleren_en_een_tekort_boven_vijf_procent_is_let_op(tmp_path):
    verwacht = {a.domain: sum(len(t.horizons) for t in a.forecast_targets) for a in default_agents()}
    assert verwacht["sector"] == 22 and sum(verwacht.values()) == 57  # de bekende 57 per ronde

    pad, conn = _db(tmp_path)
    for dom, n in verwacht.items():
        if n:
            _forecast_ronde(conn, dom, n)
    conn.close()
    waarde, status, _ = _voorwaarden(pad, _tijd(date(2026, 10, 6)))["Forecast-rondes met het echte model"]
    assert status == fv.ZELF_CONTROLEREN and "57 van 57" in waarde and "0.0% gemist" in waarde


def test_de_grens_van_vijf_procent_ligt_op_de_goede_plek(tmp_path):
    pad, conn = _db(tmp_path)
    _forecast_ronde(conn, "sector", 21)  # 1 van 22 = 4,5%: onder de grens
    conn.close()
    assert _voorwaarden(pad, _tijd(date(2026, 10, 6)))["Forecast-rondes met het echte model"][1] == fv.ZELF_CONTROLEREN

    pad2 = str(tmp_path / "b.db")
    conn2 = init_db(pad2)
    _forecast_ronde(conn2, "sector", 20)  # 2 van 22 = 9,1%
    conn2.close()
    waarde, status, opm = _voorwaarden(pad2, _tijd(date(2026, 10, 6)))["Forecast-rondes met het echte model"]
    assert status == "LET OP" and "9.1% gemist" in waarde and "heroverwegen" in opm


def test_een_mislukte_llm_aanroep_telt_als_gemist(tmp_path):
    pad, conn = _db(tmp_path)
    _forecast_ronde(conn, "monetary_policy", 0)
    conn.close()
    waarde, status, _ = _voorwaarden(pad, _tijd(date(2026, 10, 6)))["Forecast-rondes met het echte model"]
    assert status == "LET OP" and "0 van 8" in waarde


def test_resolver_vraagt_ook_een_release_horizon_en_negeert_onafwikkelbare(tmp_path):
    pad, conn = _db(tmp_path)
    naam = "Resolver heeft afgewikkeld (incl. release-horizon)"
    nu = _tijd(date(2026, 10, 20))

    p1 = save_prediction(conn, _voorspelling())
    save_evaluation(conn, p1, "unresolvable", nu, "v2", reason="geen waarneming")
    assert _voorwaarden(pad, nu)[naam][1] == fv.NOG_NIET_AF  # onafwikkelbaar telt niet als afgewikkeld

    p2 = save_prediction(conn, _voorspelling(target_metric_key="dgs2"))
    save_evaluation(conn, p2, "resolved", nu, "v2", realised_value=4.0, realised_at=nu)
    waarde, status, _ = _voorwaarden(pad, nu)[naam]
    assert status == fv.NOG_NIET_AF and "geen release-horizon" in waarde

    p3 = save_prediction(conn, _voorspelling(target_metric_key="payems", horizon_kind=HorizonKind.RELEASES, horizon_n=1,
                                            resolution_method=ResolutionMethod.NTH_RELEASE))
    save_evaluation(conn, p3, "resolved", nu, "v2", realised_value=150.0, realised_at=nu)
    conn.close()
    waarde, status, _ = _voorwaarden(pad, nu)[naam]
    assert status == fv.ZELF_CONTROLEREN and "2 afgewikkeld, waarvan 1 release-gebaseerd" in waarde


def test_pseudo_oos_telt_alleen_dat_cohort_en_is_nooit_af(tmp_path):
    pad, conn = _db(tmp_path)
    save_prediction(conn, _voorspelling())  # dry_run: telt niet
    conn.close()
    assert _voorwaarden(pad, _tijd(START))["Pseudo-OOS-run (4.4)"][1] == fv.NOG_NIET_AF

    pad2 = str(tmp_path / "b.db")
    conn2 = init_db(pad2)
    save_prediction(conn2, _voorspelling(cohort="pseudo_oos"))
    conn2.close()
    waarde, status, opm = _voorwaarden(pad2, _tijd(START))["Pseudo-OOS-run (4.4)"]
    assert status == fv.ZELF_CONTROLEREN and "1 voorspellingen" in waarde and "jouw oordeel" in opm


# --------------------------------------------------------------------------
# Dry-run-week, reeksenlijst, handmatige punten
# --------------------------------------------------------------------------


@pytest.mark.parametrize("dag, status", [
    (date(2026, 10, 26), fv.NOG_NIET_AF),
    (date(2026, 10, 27), fv.ZELF_CONTROLEREN),
    (date(2026, 11, 20), fv.ZELF_CONTROLEREN),  # ook na afloop staat er nooit AF: de data kan het niet bewijzen
])
def test_dry_run_week_is_voor_de_start_nog_niet_af_en_daarna_nooit_af(dag, status, tmp_path):
    uit = _voorwaarden(str(tmp_path / "geen.db"), _tijd(dag))
    assert uit["Dry-run-week doorlopen (3b)"][1] == status


def test_de_dry_run_week_volgt_de_constante_en_geen_kopie(monkeypatch, tmp_path):
    monkeypatch.setattr(fv, "DRY_RUN_WEEK_VAN", date(2026, 12, 1))
    monkeypatch.setattr(fv, "DRY_RUN_WEEK_TOT", date(2026, 12, 14))
    waarde, status, _ = _voorwaarden(str(tmp_path / "geen.db"), _tijd(date(2026, 11, 20)))["Dry-run-week doorlopen (3b)"]
    assert status == fv.NOG_NIET_AF and "01-12-2026 t/m 14-12-2026" in waarde


def test_de_reeksenlijst_noemt_de_bewust_onbediende_knopen_en_is_nooit_af(tmp_path):
    waarde, status, opm = _voorwaarden(str(tmp_path / "geen.db"), _tijd(START))["Reeksenlijst per agent definitief (1.10/2.x)"]
    assert status == fv.ZELF_CONTROLEREN
    assert "wage_growth" in waarde and "inflation_persistence" in waarde and "equity_valuation" in waarde
    assert "equity valt buiten het cohort" in opm


def test_de_punten_die_de_data_niet_kan_bewijzen_zijn_nooit_af(tmp_path):
    pad, conn = _db(tmp_path)
    laatste = _schone_dagen(conn, 14)
    conn.close()
    uit = _voorwaarden(pad, _na(laatste))
    for naam in ("Offsite back-up één keer hersteld (1.11)", "Heartbeat getest met de machine uit (1.11)",
                 "API-quota gemeten incl. deep-dives (1.11)"):
        assert uit[naam][1] == fv.ZELF_CONTROLEREN and "niet af te leiden" in uit[naam][0], naam
    # In de best denkbare database zijn de enige AF-regels de twee die uit de data volgen.
    assert {n for n, (_, s, _) in uit.items() if s == fv.AF} == {
        "T₀ᵃ (ingestieklok)", "14 werkdagen op rij zonder handmatige actie",
    }


# --------------------------------------------------------------------------
# Samen met het freeze-overzicht, en alleen lezen
# --------------------------------------------------------------------------


def test_het_freeze_overzicht_bevat_de_voorwaarden_en_telt_ze_mee(tmp_path):
    pad, conn = _db(tmp_path)
    laatste = _schone_dagen(conn, 7)
    conn.close()
    punten = fs.bepaal_punten(pad, nu=_na(laatste))
    groep = [p for p in punten if p.groep == fv.GROEP]
    assert len(groep) >= 9 and all(p.status in fs.TELLEN_MEE for p in groep)
    tel = fs.samenvatting(punten)
    assert tel[fs.AF] == 1 and tel[fs.NOG_NIET_AF] >= 1 and tel[fs.ZELF_CONTROLEREN] >= 4

    tekst = fs.format_overzicht(punten)
    for stuk in ("VOORWAARDEN VÓÓR DE KLOK", "[AF]", "[NOG NIET AF]", "[ZELF CONTROLEREN]", "SAMENVATTING:"):
        assert stuk in tekst, stuk


def test_het_overzicht_zonder_database_blijft_werken_en_de_tekst_legt_de_drie_statussen_uit(tmp_path):
    tekst = fs.format_overzicht(fs.bepaal_punten(str(tmp_path / "geen.db")))
    assert "VOORWAARDEN VÓÓR DE KLOK" in tekst and "onbekend (database niet gevonden)" in tekst
    for uitleg in ("AF = ", "NOG NIET AF = ", "ZELF CONTROLEREN = "):
        assert uitleg in tekst, uitleg


def test_de_voorwaarden_schrijven_niets_in_de_database(tmp_path):
    pad, conn = _db(tmp_path)
    laatste = _schone_dagen(conn, 8)
    conn.close()
    voor = hashlib.sha256(Path(pad).read_bytes()).hexdigest()
    fs.bepaal_punten(pad, nu=_na(laatste))
    assert hashlib.sha256(Path(pad).read_bytes()).hexdigest() == voor
    assert not list(Path(pad).parent.glob("*-wal")) and not list(Path(pad).parent.glob("*-journal"))


def test_de_module_opent_de_database_alleen_lezend_en_schrijft_niet():
    tekst = (ROOT / "src" / "runtime" / "freeze_voorwaarden.py").read_text()
    code = "\n".join(r for r in tekst.splitlines() if not r.lstrip().startswith("#"))
    assert "mode=ro" in code
    for verboden in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "CREATE ", ".commit()", "init_db"):
        assert verboden not in code, verboden


def test_het_script_toont_de_voorwaarden_zonder_iets_te_schrijven(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("freeze_status_script", ROOT / "freeze_status.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    pad, conn = _db(tmp_path)
    conn.close()
    voor = hashlib.sha256(Path(pad).read_bytes()).hexdigest()
    assert script.main(["--db", pad]) == 0
    uit = capsys.readouterr().out
    assert "VOORWAARDEN VÓÓR DE KLOK" in uit and "NOG NIET AF" in uit
    assert hashlib.sha256(Path(pad).read_bytes()).hexdigest() == voor
