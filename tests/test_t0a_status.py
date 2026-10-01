"""
test_t0a_status.py
De T₀ᵃ-teller (roadmap 1.11): `runtime/t0a_status.py` en `t0a_status.py`.
Definitie van schoon (01-10-2026): alle agents ok én geen volledigheidstrigger.
"""

from __future__ import annotations

import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from runtime.t0a_status import (
    GEEN_RUN, NIET_SCHOON, NOG_NIET, SCHOON, bereken_stand, beoordeel_dag, verwachte_domeinen, werkdagen,
)
from storage.schema import init_db

DOMEINEN = ["a", "b", "c"]
START = date(2026, 10, 2)  # vrijdag


def _tijd(d: date, uur=7, minuut=15) -> datetime:
    return datetime(d.year, d.month, d.day, uur, minuut, tzinfo=timezone.utc)


def _run(conn, d, domein, success=True, uur=7, error=None):
    conn.execute(
        "INSERT INTO agent_runs (domain, mode, run_at, success, trigger_count, error) VALUES (?, 'monitoring', ?, ?, 0, ?)",
        (domein, _tijd(d, uur).isoformat(), int(success), error),
    )
    conn.commit()


def _goede_dag(conn, d, uur=7):
    for dom in DOMEINEN:
        _run(conn, d, dom, uur=uur)


def _trigger(conn, d, reden, versie="v3"):
    conn.execute(
        "INSERT INTO trigger_events (domain, triggered_at, reason, severity, trigger_version) VALUES ('sector', ?, ?, 'medium', ?)",
        (_tijd(d).isoformat(), reden, versie),
    )
    conn.commit()


def _db(tmp_path):
    return init_db(str(tmp_path / "t.db"))


# --------------------------------------------------------------------------
# Correct geval
# --------------------------------------------------------------------------


def test_zeven_schone_werkdagen_op_rij_halen_t0a_en_het_weekend_breekt_niets(tmp_path):
    conn = _db(tmp_path)
    dagen = werkdagen(START, date(2026, 10, 12))  # vr 2, ma 5 ... ma 12 = 7 werkdagen
    assert len(dagen) == 7
    for d in dagen:
        _goede_dag(conn, d)
    stand = bereken_stand(conn, nu=_tijd(date(2026, 10, 12), 9), start=START, domeinen=DOMEINEN)
    assert stand.gehaald_op == date(2026, 10, 12)
    assert stand.huidige_reeks == 7


def test_de_vroegste_datum_telt_door_vanaf_de_lopende_reeks(tmp_path):
    conn = _db(tmp_path)
    _goede_dag(conn, date(2026, 10, 2))
    stand = bereken_stand(conn, nu=_tijd(date(2026, 10, 2), 9), start=START, domeinen=DOMEINEN)
    assert stand.huidige_reeks == 1 and stand.gehaald_op is None
    assert stand.vroegste_datum == date(2026, 10, 12)  # 5,6,7,8,9,12 = nog zes werkdagen


# --------------------------------------------------------------------------
# De definitie: regressies
# --------------------------------------------------------------------------


def test_alle_agents_ok_maar_een_volledigheidstrigger_is_niet_schoon(tmp_path):
    """Precies het geval van 01-10: agents `ok`, sector 10 van 12 reeksen."""
    conn = _db(tmp_path)
    _goede_dag(conn, START)
    _trigger(conn, START, "completeness: 10 van de 12 verwachte reeksen opgehaald bij bron 'X' -- ontbreekt: spy_benchmark")
    s = beoordeel_dag(conn, START, DOMEINEN)
    assert s.status == NIET_SCHOON
    assert any("spy_benchmark" in r for r in s.redenen)


def test_een_gewone_trigger_maakt_een_dag_niet_onschoon(tmp_path):
    """Een echte marktbeweging (hier: een revisie) is data, geen gat."""
    conn = _db(tmp_path)
    _goede_dag(conn, START)
    _trigger(conn, START, "Revisie: Fed funds rate voor periode 2026-09-01 gewijzigd")
    assert beoordeel_dag(conn, START, DOMEINEN).status == SCHOON


def test_een_mislukte_agent_maakt_de_dag_niet_schoon_en_noemt_welke(tmp_path):
    conn = _db(tmp_path)
    _run(conn, START, "a"); _run(conn, START, "b")
    _run(conn, START, "c", success=False, error="ReadTimeout bij Alpha Vantage")
    s = beoordeel_dag(conn, START, DOMEINEN)
    assert s.status == NIET_SCHOON and "c: mislukt (ReadTimeout" in s.redenen[0]


def test_een_agent_zonder_enige_run_telt_niet_als_schoon(tmp_path):
    """Onbekend is geen schoon."""
    conn = _db(tmp_path)
    _run(conn, START, "a"); _run(conn, START, "b")  # c ontbreekt
    s = beoordeel_dag(conn, START, DOMEINEN)
    assert s.status == NIET_SCHOON and "c: geen succesvolle run" in s.redenen[0]


def test_een_mislukte_poging_gevolgd_door_een_geslaagde_retry_is_schoon(tmp_path):
    conn = _db(tmp_path)
    _run(conn, START, "a"); _run(conn, START, "b")
    _run(conn, START, "c", success=False, error="x")
    _run(conn, START, "c")
    assert beoordeel_dag(conn, START, DOMEINEN).status == SCHOON


def test_een_dag_zonder_run_is_geen_run_en_breekt_de_reeks(tmp_path):
    conn = _db(tmp_path)
    _goede_dag(conn, date(2026, 10, 2))
    # ma 5 okt: geen run
    _goede_dag(conn, date(2026, 10, 6))
    stand = bereken_stand(conn, nu=_tijd(date(2026, 10, 6), 9), start=START, domeinen=DOMEINEN)
    assert [d.status for d in stand.dagen] == [SCHOON, GEEN_RUN, SCHOON]
    assert stand.huidige_reeks == 1


def test_een_niet_schone_dag_zet_de_teller_op_nul(tmp_path):
    conn = _db(tmp_path)
    for d in (date(2026, 10, 2), date(2026, 10, 5)):
        _goede_dag(conn, d)
    _goede_dag(conn, date(2026, 10, 6))
    _trigger(conn, date(2026, 10, 6), "completeness: 11 van 12 -- ontbreekt: x")
    _goede_dag(conn, date(2026, 10, 7))
    stand = bereken_stand(conn, nu=_tijd(date(2026, 10, 7), 9), start=START, domeinen=DOMEINEN)
    assert stand.huidige_reeks == 1  # alleen 7 okt; 2 en 5 okt zijn niet meer van belang


def test_vandaag_nog_niet_gedraaid_breekt_niets_maar_een_gemiste_dag_in_het_verleden_wel(tmp_path):
    conn = _db(tmp_path)
    _goede_dag(conn, date(2026, 10, 2))
    stand = bereken_stand(conn, nu=_tijd(date(2026, 10, 5), 6), start=START, domeinen=DOMEINEN)  # 06:00, cron nog niet geweest
    assert stand.dagen[-1].status == NOG_NIET and stand.huidige_reeks == 1


def test_eenmaal_gehaald_blijft_gehaald_ook_na_een_latere_breuk(tmp_path):
    conn = _db(tmp_path)
    dagen = werkdagen(START, date(2026, 10, 13))
    for d in dagen[:7]:
        _goede_dag(conn, d)  # t/m 12 okt schoon
    # 13 okt: niets
    stand = bereken_stand(conn, nu=_tijd(date(2026, 10, 14), 9), start=START, domeinen=DOMEINEN)
    assert stand.gehaald_op == date(2026, 10, 12)


# --------------------------------------------------------------------------
# Markeringen
# --------------------------------------------------------------------------


def test_een_run_buiten_het_cron_venster_wordt_gemarkeerd_maar_telt_nog_steeds_als_schoon(tmp_path):
    conn = _db(tmp_path)
    _goede_dag(conn, START, uur=15)  # 15:00 UTC: met de hand
    s = beoordeel_dag(conn, START, DOMEINEN)
    assert s.status == SCHOON and s.mogelijk_handmatig is True


def test_een_wisselende_trigger_versie_binnen_de_schone_dagen_wordt_gemeld(tmp_path):
    conn = _db(tmp_path)
    for d, v in ((date(2026, 10, 2), "v3"), (date(2026, 10, 5), "v4")):
        _goede_dag(conn, d)
        _trigger(conn, d, "Revisie: x", versie=v)
    stand = bereken_stand(conn, nu=_tijd(date(2026, 10, 5), 9), start=START, domeinen=DOMEINEN)
    assert stand.versie_wisselt is True


# --------------------------------------------------------------------------
# Koppeling aan de echte agentlijst, en het script
# --------------------------------------------------------------------------


def test_de_verwachte_domeinen_zijn_de_zes_agents_van_de_dagelijkse_run():
    assert sorted(verwachte_domeinen()) == sorted(
        ["monetary_policy", "currency", "financial", "sector", "commodity", "economic"]
    )


def test_script_leest_alleen_en_geeft_exit_een_zonder_database(tmp_path, capsys):
    pad = tmp_path / "t.db"
    conn = init_db(str(pad))
    for dom in verwachte_domeinen():
        _run(conn, date(2026, 10, 2), dom)
    conn.close()
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("t0a_status_cli", root / "t0a_status.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    voor = pad.read_bytes()
    assert cli.main(["--db", str(pad)]) == 0
    uit = capsys.readouterr().out
    assert "T₀ᵃ-TELLER" in uit and "2026-10-02" in uit
    assert pad.read_bytes() == voor
    assert cli.main(["--db", str(tmp_path / "weg.db")]) == 1
