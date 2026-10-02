"""
test_dagcontrole.py
De dagelijkse controle (`runtime/dagcontrole.py`, `dagcontrole.py`): alleen lezen, ÉÉN scherm voor de begeleide weken en de dry-run-week.
Wat bewaakt wordt: elke check kan op ok, LET OP, ONBEKEND of "nog niet" uitkomen; ontbrekende bestanden zijn ONBEKEND (nooit stilzwijgend ok);
een tijdstip dat nog niet verstreken is geeft geen LET OP; de database blijft ongewijzigd; het script opent de database read-only.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from contract.trigger_version import TRIGGER_VERSION
from runtime import dagcontrole as dc
from storage.schema import init_db

DOMEINEN = ["a", "b"]
DAG = date(2026, 10, 6)          # dinsdag
MAANDAG = date(2026, 10, 5)


def _t(d: date, uur=7, minuut=15) -> datetime:
    return datetime(d.year, d.month, d.day, uur, minuut, tzinfo=timezone.utc)


def _status(regels, onderwerp):
    return [r.status for r in regels if r.onderwerp == onderwerp]


@pytest.fixture
def conn(tmp_path):
    c = init_db(str(tmp_path / "t.db"))
    yield c
    c.close()


def _run(conn, d, domein, success=True, uur=7, error=None):
    conn.execute("INSERT INTO agent_runs (domain, mode, run_at, success, trigger_count, error) VALUES (?, 'monitoring', ?, ?, 0, ?)",
                 (domein, _t(d, uur).isoformat(), int(success), error))
    conn.commit()


def _claim(conn, d, domein):
    cur = conn.execute("INSERT INTO domain_outputs (domain, mode, generated_at) VALUES (?, 'monitoring', ?)", (domein, _t(d).isoformat()))
    conn.execute(
        "INSERT INTO claims (domain_output_id, domain, claim, value_json, source, confidence, ingestion_time, analysis_time, metric_key) "
        "VALUES (?, ?, 'x', '1', 's', 0.9, ?, ?, 'm')", (cur.lastrowid, domein, _t(d).isoformat(), _t(d).isoformat()))
    conn.commit()


def _goede_dag(conn, d):
    for dom in DOMEINEN:
        _run(conn, d, dom)
        _claim(conn, d, dom)


def _prediction(conn, d, cohort="dry_run"):
    conn.execute(
        "INSERT INTO predictions (agent, domain, target_metric_key, kind, horizon_kind, horizon_n, created_at, resolves_at, resolution_rule, "
        "model_id, prompt_version, q10, q25, q50, q75, q90, cohort, contract_version, graph_version, causal_chain_json, "
        "evidence_claim_ids_json, resolution_method) VALUES ('a','a','m','quantile','trading_days',5,?,?,'r','mod','p',1,2,3,4,5,?,'v0','v0','[]','[]','level_at_or_after')",
        (_t(d).isoformat(), _t(d + timedelta(days=7)).isoformat(), cohort))
    conn.commit()


def test_een_schone_dag_geeft_ok_op_run_en_claims(conn):
    _goede_dag(conn, DAG)
    nu = _t(DAG, 12)
    regels = dc.controleer_run(conn, DAG, nu, DOMEINEN) + dc.controleer_claims(conn, DAG, DOMEINEN)
    assert [r.status for r in regels] == [dc.OK, dc.OK]


def test_een_mislukte_agent_is_let_op_met_de_reden(conn):
    _run(conn, DAG, "a")
    _run(conn, DAG, "b", success=False, error="HTTP 500 van de bron")
    regels = dc.controleer_run(conn, DAG, _t(DAG, 12), DOMEINEN)
    assert regels[0].status == dc.LET_OP and "b" in regels[0].tekst and "HTTP 500" in regels[0].tekst


def test_een_completeness_trigger_maakt_de_dag_niet_schoon(conn):
    _goede_dag(conn, DAG)
    conn.execute("INSERT INTO trigger_events (domain, triggered_at, reason, severity, trigger_version) VALUES "
                 "('a', ?, 'completeness: 11 van 12, ontbreekt: xlp', 'medium', ?)", (_t(DAG).isoformat(), TRIGGER_VERSION))
    conn.commit()
    regels = dc.controleer_run(conn, DAG, _t(DAG, 12), DOMEINEN)
    assert regels[0].status == dc.LET_OP and "completeness" in regels[0].tekst


def test_geen_run_voor_de_cron_is_nog_niet_en_erna_let_op(conn):
    assert dc.controleer_run(conn, DAG, _t(DAG, 6, 0), DOMEINEN)[0].status == dc.NOG_NIET
    assert dc.controleer_run(conn, DAG, _t(DAG, 9, 0), DOMEINEN)[0].status == dc.LET_OP


def test_weekend_is_info_geen_let_op(conn):
    zaterdag = date(2026, 10, 3)
    assert dc.controleer_run(conn, zaterdag, _t(zaterdag, 12), DOMEINEN)[0].status == dc.INFO


def test_run_buiten_het_cron_venster_wordt_gemeld(conn):
    for dom in DOMEINEN:
        _run(conn, DAG, dom, uur=15)
    regels = dc.controleer_run(conn, DAG, _t(DAG, 20), DOMEINEN)
    assert dc.LET_OP in [r.status for r in regels] and any("handmatig" in r.tekst for r in regels)


def test_trigger_met_een_andere_versie_dan_de_code_is_let_op(conn):
    conn.execute("INSERT INTO trigger_events (domain, triggered_at, reason, severity, trigger_version) VALUES ('a', ?, 'r', 'low', 'v0')",
                 (_t(DAG).isoformat(),))
    conn.commit()
    regels = dc.controleer_triggers(conn, DAG)
    assert dc.LET_OP in [r.status for r in regels]
    conn.execute("DELETE FROM trigger_events")
    conn.execute("INSERT INTO trigger_events (domain, triggered_at, reason, severity, trigger_version) VALUES ('a', ?, 'r', 'low', ?)",
                 (_t(DAG).isoformat(), TRIGGER_VERSION))
    conn.commit()
    assert dc.LET_OP not in [r.status for r in dc.controleer_triggers(conn, DAG)]


def test_een_domein_zonder_claims_is_let_op(conn):
    _claim(conn, DAG, "a")
    regels = dc.controleer_claims(conn, DAG, DOMEINEN)
    assert regels[0].status == dc.LET_OP and "b" in regels[0].tekst


def test_mislukte_bronchecks_worden_per_bron_gemeld(conn):
    conn.execute("INSERT INTO data_health (source, checked_at, success, detail) VALUES ('AV:sector', ?, 0, 'lege respons')", (_t(DAG).isoformat(),))
    conn.execute("INSERT INTO data_health (source, checked_at, success, detail) VALUES ('FRED', ?, 1, '')", (_t(DAG).isoformat(),))
    conn.commit()
    regels = dc.controleer_bronnen(conn, DAG)
    assert len(regels) == 1 and regels[0].status == dc.LET_OP and "AV:sector" in regels[0].tekst
    assert dc.controleer_bronnen(conn, DAG - timedelta(days=1))[0].status == dc.OK


def test_maandag_zonder_forecast_ronde_is_let_op_en_mee_ok(conn):
    assert dc.controleer_voorspellingen(conn, MAANDAG, _t(MAANDAG, 6))[0].status == dc.NOG_NIET
    assert dc.controleer_voorspellingen(conn, MAANDAG, _t(MAANDAG, 12))[0].status == dc.LET_OP
    _prediction(conn, MAANDAG)
    regel = dc.controleer_voorspellingen(conn, MAANDAG, _t(MAANDAG, 12))[0]
    assert regel.status == dc.OK and "dry_run 1" in regel.tekst
    assert dc.controleer_voorspellingen(conn, DAG, _t(DAG, 12))[0].status == dc.INFO   # dinsdag: geen ronde verwacht


def test_llm_verbruik_waarschuwt_vanaf_de_helft_van_de_grens(conn):
    nu = _t(DAG, 12)
    assert dc.controleer_llm(conn, nu)[0].status == dc.OK
    conn.execute("INSERT INTO llm_usage (called_at, model, input_tokens, output_tokens, cost_usd) VALUES (?, 'm', 1, 1, 120.0)", (nu.isoformat(),))
    conn.commit()
    assert dc.controleer_llm(conn, nu)[0].status == dc.LET_OP


def test_ontbrekend_logbestand_is_onbekend_en_nooit_ok(tmp_path):
    assert dc.controleer_log(tmp_path / "bestaat_niet.log", DAG)[0].status == dc.ONBEKEND
    assert dc.controleer_log(None, DAG)[0].status == dc.ONBEKEND


def test_log_toont_warnings_van_de_dag_en_negeert_andere_dagen(tmp_path):
    log = tmp_path / "daily.log"
    log.write_text(
        "2026-10-05 07:15:01,100 WARNING sources.alpha_vantage: sector xlp: Note: rate limit\n"
        "2026-10-06 07:15:01,100 INFO run_daily: Cohort voor nieuwe voorspellingen: dry_run (telt NIET mee; zet MI_COHORT=cohort_0 op T₀ᵇ)\n"
        "2026-10-06 07:15:02,200 INFO run_daily: Trigger-versie: v4\n"
        "2026-10-06 07:15:09,300 WARNING run_daily: Forecast-probleem: iets\n", encoding="utf-8")
    regels = dc.controleer_log(log, DAG)
    let_op = [r for r in regels if r.status == dc.LET_OP]
    assert len(let_op) == 1 and "Forecast-probleem" in let_op[0].tekst
    assert not any("rate limit" in r.tekst for r in regels)                       # regel van een andere dag
    assert any("Trigger-versie: v4" in r.tekst for r in regels if r.status == dc.INFO)
    assert any("Cohort" in r.tekst for r in regels if r.status == dc.INFO)


def test_schoon_log_is_ok_en_een_log_zonder_regels_van_vandaag_is_let_op(tmp_path):
    log = tmp_path / "daily.log"
    log.write_text("2026-10-06 07:15:02,200 INFO run_daily: Trigger-versie: v4\n", encoding="utf-8")
    assert dc.OK in [r.status for r in dc.controleer_log(log, DAG)]
    assert dc.controleer_log(log, date(2026, 10, 7))[0].status == dc.LET_OP


def test_backup_ok_fout_oud_en_nog_niet(tmp_path):
    pad = tmp_path / "backup.log"
    pad.write_text("2026-10-06 08:00:03 Transferred: 1 / 1, 100%\n", encoding="utf-8")
    nu_na = datetime.now(timezone.utc)
    dag = nu_na.date()
    assert dc.controleer_backup(pad, dag, nu_na)[0].status == dc.OK                 # bijgewerkt vandaag, geen fout
    pad.write_text("rclone: Failed to copy: AccessDenied\n", encoding="utf-8")
    assert dc.controleer_backup(pad, dag, nu_na)[0].status == dc.LET_OP
    pad.write_text("alles goed\n", encoding="utf-8")
    oud = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc).timestamp()
    os.utime(pad, (oud, oud))
    assert dc.controleer_backup(pad, dag, datetime.combine(dag, datetime.min.time(), tzinfo=timezone.utc).replace(hour=6))[0].status == dc.NOG_NIET
    assert dc.controleer_backup(pad, dag, datetime.combine(dag, datetime.min.time(), tzinfo=timezone.utc).replace(hour=12))[0].status == dc.LET_OP
    assert dc.controleer_backup(tmp_path / "weg.log", dag, nu_na)[0].status == dc.ONBEKEND


def _manifest(basis: Path, dag: date):
    (basis / "spy_holdings").mkdir(parents=True, exist_ok=True)
    rel = f"spy_holdings/{dag.year}/spy_holdings_{dag.isoformat()}.xlsx.gz"
    (basis / "spy_holdings" / "manifest.jsonl").write_text(json.dumps({"path": rel, "as_of": "2026-10-05"}) + "\n", encoding="utf-8")


def test_archief_ok_nog_niet_let_op_en_onbekend(tmp_path):
    from archive import spy_holdings
    basis = tmp_path / "archive"
    assert dc.controleer_archief(basis, DAG, _t(DAG, 12))[0].status == dc.ONBEKEND   # map bestaat niet
    basis.mkdir()
    assert dc.controleer_archief(basis, DAG, _t(DAG, 8, 0))[0].status == dc.NOG_NIET
    assert dc.controleer_archief(basis, DAG, _t(DAG, 12))[0].status == dc.LET_OP
    _manifest(basis, DAG)
    assert spy_holdings.lees_manifest(basis)                                          # het manifestformaat klopt met de echte lezer
    assert dc.controleer_archief(basis, DAG, _t(DAG, 12))[0].status == dc.OK


def test_schijf_waarschuwt_vanaf_de_grens():
    assert dc.controleer_schijf(gebruikt=0.11)[0].status == dc.OK
    assert dc.controleer_schijf(gebruikt=0.90)[0].status == dc.LET_OP


def test_controleer_alles_wijzigt_de_database_niet_en_meldt_alles_ontbrekende_als_onbekend(conn, tmp_path):
    _goede_dag(conn, DAG)
    tabellen = ("agent_runs", "claims", "trigger_events", "predictions", "data_health", "llm_usage")
    voor = [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tabellen]
    regels = dc.controleer_alles(conn, DAG, _t(DAG, 12), log=tmp_path / "x.log", backup_log=tmp_path / "y.log",
                                 archief=tmp_path / "z", domeinen=DOMEINEN)
    na = [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tabellen]
    assert voor == na
    assert {r.onderwerp for r in regels if r.status == dc.ONBEKEND} == {"log", "back-up", "archief"}
    assert dc.heeft_aandacht(regels)
    tekst = dc.format_controle(DAG, regels)
    assert "ONBEKEND" in tekst and "niet gecontroleerd, dus niet goedgekeurd" in tekst


def test_alles_goed_geeft_geen_aandacht(conn, tmp_path):
    nu = datetime.now(timezone.utc)
    dag = nu.date()
    while dag.weekday() >= 5:
        dag -= timedelta(days=1)
    nu = datetime.combine(dag, datetime.min.time(), tzinfo=timezone.utc).replace(hour=23)
    _goede_dag(conn, dag)
    log = tmp_path / "daily.log"
    log.write_text(f"{dag} 07:15:02,200 INFO run_daily: Trigger-versie: {TRIGGER_VERSION}\n", encoding="utf-8")
    backup = tmp_path / "backup.log"
    backup.write_text("ok\n", encoding="utf-8")
    basis = tmp_path / "archive"
    _manifest(basis, dag)
    # Het back-upbestand is "vandaag" gewijzigd alleen als de testdag vandaag is; dwing de wijzigingstijd af.
    ts = datetime.combine(dag, datetime.min.time(), tzinfo=timezone.utc).replace(hour=8).timestamp()
    os.utime(backup, (ts, ts))
    regels = dc.controleer_alles(conn, dag, nu, log=log, backup_log=backup, archief=basis, domeinen=DOMEINEN)
    if dag.weekday() == 0:
        _prediction(conn, dag)
        regels = dc.controleer_alles(conn, dag, nu, log=log, backup_log=backup, archief=basis, domeinen=DOMEINEN)
    # Alleen de schijf van de testmachine zelf mag een LET OP geven; al het andere is hier in orde.
    problemen = [r for r in regels if r.status in (dc.LET_OP, dc.ONBEKEND) and r.onderwerp != "schijf"]
    assert problemen == []


def _laad_script():
    spec = importlib.util.spec_from_file_location("dagcontrole_script", Path(__file__).parent.parent / "dagcontrole.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_opent_de_database_read_only_en_geeft_exitcode(tmp_path, capsys):
    db = tmp_path / "t.db"
    c = init_db(str(db))
    _goede_dag(c, DAG)
    c.close()
    script = _laad_script()
    code = script.main(["--db", str(db), "--dag", DAG.isoformat(), "--log", str(tmp_path / "geen.log"),
                        "--backup-log", str(tmp_path / "geen2.log"), "--archief", str(tmp_path / "geenmap")])
    uit = capsys.readouterr().out
    assert code == 1 and "DAGCONTROLE 2026-10-06" in uit and "ONBEKEND" in uit
    assert script.main(["--db", str(tmp_path / "bestaat_niet.db")]) == 2
    assert "mode=ro" in (Path(__file__).parent.parent / "dagcontrole.py").read_text(encoding="utf-8")
