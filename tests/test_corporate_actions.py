"""
test_corporate_actions.py
Aandelensplitsingen: de lijst en de correctie (`contract/corporate_actions.py`), het ene leespad (`scoring/resolver.py::observations_for`),
de waakhond (`runtime/split_waakhond.py`) en de vergelijking in het kalibratierapport. 02-10-2026.

Aanleiding: op 5 december 2025 halveerde de koers van XLB, XLE, XLK, XLU en XLY door een 2-voor-1-splitsing, en de back-fill haalt
niet-gecorrigeerde koersen op. Wat bewaakt wordt: de ruwe claims blijven ongewijzigd, alles wat rekent over de historie (evidence-sheet,
baselines, afrekenen, kalibratie) ziet een doorlopende reeks, en een nieuwe of foutief geregistreerde splitsing wordt gemeld.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from agents.base import ForecastTarget
from calibration import trigger_calibration as tc
from contract import corporate_actions as ca
from contract.corporate_actions import Splitsing, factor_voor, pas_splitsingen_toe
from contract.output_contract import Claim, Confidence, DomainOutput, Mode
from contract.prediction import HorizonKind, Prediction, PredictionKind
from contract.resolution import Observation, ResolutionMethod
from runtime import split_waakhond as sw
from runtime.daily import AgentSpec, run_daily
from scoring.evidence_sheet import build_evidence_sheet
from scoring.resolver import observations_for, resolve_one
from storage.schema import init_db, save_domain_output

ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc
SPLITSDATUM = date(2025, 12, 5)


def _dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _werkdagen(van: date, tot: date) -> list[date]:
    uit, d = [], van
    while d <= tot:
        if d.weekday() < 5:
            uit.append(d)
        d += timedelta(days=1)
    return uit


DAGEN = _werkdagen(date(2025, 10, 1), date(2026, 1, 30))


def _pad(basis: float, helling: float, golf: float) -> list[float]:
    """Een doorlopend prijspad in HUIDIGE aandelen: een trend plus een rustige golf (ongeveer 1% per dag)."""
    return [basis + helling * i + golf * (((i * 7) % 11) - 5) / 5 for i in range(len(DAGEN))]


def _opslaan(conn, key: str, waarden: list[float], dagen: list[date] = DAGEN, domain: str = "sector") -> None:
    claims = [
        Claim(domain=domain, claim=f"Reeks {key}", value=w, source="bron", confidence=Confidence.HIGH,
              analysis_time=_dt(d), source_time=_dt(d), metric_key=key)
        for d, w in zip(dagen, waarden)
    ]
    save_domain_output(conn, DomainOutput(domain=domain, mode=Mode.MONITORING, generated_at=_dt(dagen[0]), claims=claims))


def _ruw(waarden: list[float], datum: date = SPLITSDATUM, verhouding: float = 2.0) -> list[float]:
    """Wat de bron leverde: vóór de splitsing de oude, hogere koers."""
    return [w * verhouding if d < datum else w for d, w in zip(DAGEN, waarden)]


@pytest.fixture
def conn(tmp_path):
    c = init_db(str(tmp_path / "t.db"))
    spy = _pad(740.0, 0.3, 4.0)
    _opslaan(c, "spy_benchmark", spy)
    _opslaan(c, "xlk_technology", _ruw(_pad(150.0, 0.1, 1.5)))  # gesplitst op 5 december
    _opslaan(c, "xlf_financials", _pad(55.0, 0.02, 0.5))  # nooit gesplitst
    yield c
    c.close()


# --------------------------------------------------------------------------
# De lijst en de correctie
# --------------------------------------------------------------------------


def test_de_vijf_gemeten_splitsingen_staan_in_de_lijst_met_hun_waarden():
    """Vastgepind: een bestaande regel wijzigen of verwijderen zou lopende voorspellingen anders afrekenen. Toevoegen mag wel."""
    verwacht = {"xlb_materials", "xle_energy", "xlk_technology", "xlu_utilities", "xly_consumer_discretionary"}
    gevonden = {s.metric_key: s for s in ca.SPLITSINGEN}
    assert verwacht <= set(gevonden)
    assert all(gevonden[k].datum == SPLITSDATUM and gevonden[k].verhouding == 2.0 for k in verwacht)
    assert "spy_benchmark" not in gevonden and "xlf_financials" not in gevonden


def test_een_ongeldige_verhouding_wordt_geweigerd():
    for fout in (0, -2.0, 1.0):
        with pytest.raises(ValueError):
            Splitsing("xlk_technology", SPLITSDATUM, fout, "x")


def _obs(dag: date, waarde: float) -> Observation:
    return Observation(source_time=_dt(dag), value=waarde, first_seen=_dt(dag), claim_id=int(_dt(dag).timestamp()) % 99999)


def test_vooraf_wordt_gedeeld_op_en_na_de_splitsingsdatum_niet():
    lijst = (Splitsing("k", date(2025, 12, 5), 2.0, "t"),)
    uit = pas_splitsingen_toe("k", [_obs(date(2025, 12, 4), 300.0), _obs(date(2025, 12, 5), 150.0), _obs(date(2025, 12, 8), 151.0)], lijst)
    assert [o.value for o in uit] == [150.0, 150.0, 151.0]  # de dag vóór de splitsing is gedeeld, de splitsingsdag zelf niet


def test_meerdere_splitsingen_stapelen_en_een_samenvoeging_vermenigvuldigt():
    lijst = (Splitsing("k", date(2024, 1, 10), 2.0, "t"), Splitsing("k", date(2025, 1, 10), 3.0, "t"))
    assert factor_voor("k", date(2023, 6, 1), lijst) == 6.0  # twee splitsingen daarna
    assert factor_voor("k", date(2024, 6, 1), lijst) == 3.0
    assert factor_voor("k", date(2025, 6, 1), lijst) == 1.0
    samenvoeging = (Splitsing("k", date(2025, 1, 10), 0.1, "t"),)  # 1-voor-10: de oude koers x10
    assert pas_splitsingen_toe("k", [_obs(date(2025, 1, 2), 5.0)], samenvoeging)[0].value == pytest.approx(50.0)


def test_andere_reeksen_blijven_ongemoeid_en_dezelfde_lijst_komt_terug_zonder_splitsing():
    lijst = (Splitsing("k", date(2025, 12, 5), 2.0, "t"),)
    waarnemingen = [_obs(date(2025, 12, 1), 10.0)]
    assert pas_splitsingen_toe("anders", waarnemingen, lijst) is waarnemingen


# --------------------------------------------------------------------------
# Het leespad: één doorlopende reeks, ruwe claims onaangeroerd
# --------------------------------------------------------------------------


def _sprongen(waarden: list[float]) -> int:
    return sum(1 for a, b in zip(waarden, waarden[1:]) if not 0.65 < b / a < 1.55)


def test_observations_for_geeft_een_doorlopende_reeks_en_de_ruwe_blijft_ruw(conn):
    gecorrigeerd = [o.value for o in observations_for(conn, "xlk_technology")]
    ruw = [o.value for o in observations_for(conn, "xlk_technology", corrigeer_splitsingen=False)]
    assert _sprongen(ruw) == 1 and _sprongen(gecorrigeerd) == 0
    assert min(ruw) < 200 < max(ruw) and max(gecorrigeerd) < 200  # alles in huidige aandelen
    # de claims zelf zijn niet aangeraakt: er staat nog steeds een halvering in de opgeslagen waarden
    rijen = conn.execute("SELECT value_json FROM claims WHERE metric_key = 'xlk_technology' ORDER BY source_time").fetchall()
    assert _sprongen([float(r[0]) for r in rijen]) == 1


def test_een_reeks_zonder_splitsing_is_identiek_aan_voor_de_wijziging(conn):
    a = [(o.source_time, o.value) for o in observations_for(conn, "xlf_financials")]
    b = [(o.source_time, o.value) for o in observations_for(conn, "xlf_financials", corrigeer_splitsingen=False)]
    assert a == b


def _spreiding(sheet: str, horizon: int) -> float:
    m = re.search(rf"over {horizon} handelsdagen: laatste 5 jaar ([0-9.]+)", sheet)
    assert m, sheet
    return float(m.group(1))


def _doel(key: str) -> ForecastTarget:
    return ForecastTarget(
        metric_key=key, kind=PredictionKind.QUANTILE, horizon_kind=HorizonKind.TRADING_DAYS, horizons=(5, 21),
        resolution_method=ResolutionMethod.RELATIVE_RETURN, resolution_rule="fixture", benchmark_metric_key="spy_benchmark",
    )


def test_de_spreiding_in_de_evidence_sheet_is_niet_meer_opgeblazen_door_de_splitsing(conn, monkeypatch):
    """De kern van het probleem: één halveringsdag laat de spreiding van een 5-daags venster ruim het drievoudige lijken."""
    as_of = _dt(date(2026, 2, 2))
    claims = [Claim(domain="sector", claim="XLK", value=1.0, source="b", confidence=Confidence.HIGH,
                    analysis_time=as_of, metric_key="xlk_technology")]
    doel = _doel("xlk_technology")
    mooi = _spreiding(build_evidence_sheet(conn, [doel], claims, as_of), 5)
    monkeypatch.setattr(ca, "SPLITSINGEN", ())
    opgeblazen = _spreiding(build_evidence_sheet(conn, [doel], claims, as_of), 5)
    assert opgeblazen > 3 * mooi and mooi < 5


def test_een_voorspelling_over_de_splitsingsdatum_wordt_op_het_echte_rendement_afgerekend(conn, monkeypatch):
    """Gemaakt op 28 november, afgerekend op 12 december: de splitsing ligt ertussen. Zonder correctie: een 'daling' van ongeveer 50 punten."""
    p = Prediction(
        agent="sector", domain="sector", target_metric_key="xlk_technology", kind=PredictionKind.QUANTILE,
        horizon_kind=HorizonKind.TRADING_DAYS, horizon_n=10, created_at=datetime(2025, 11, 28, 7, 15, tzinfo=UTC),
        resolves_at=datetime(2025, 12, 12, 7, 15, tzinfo=UTC), resolution_rule="regel",
        resolution_method=ResolutionMethod.RELATIVE_RETURN, benchmark_metric_key="spy_benchmark", model_id="m", prompt_version="p",
        q10=-4.0, q25=-2.0, q50=0.0, q75=2.0, q90=4.0,
    )
    juist = resolve_one(conn, p).value
    assert abs(juist) < 10  # een gewoon relatief rendement
    monkeypatch.setattr(ca, "SPLITSINGEN", ())
    fout = resolve_one(conn, p).value
    assert fout < -40  # de halvering als rendement


def test_het_kalibratierapport_leest_de_gecorrigeerde_reeks_en_kan_de_ruwe_ernaast_zetten(conn):
    nu = _dt(date(2026, 2, 2))
    ruw = tc.calibrate_all(conn, nu, domain="sector", corrigeer_splitsingen=False)
    corr = tc.calibrate_all(conn, nu, domain="sector", corrigeer_splitsingen=True)
    r_ruw = {r.metric_key: r for r in ruw}["xlk_technology"]
    r_corr = {r.metric_key: r for r in corr}["xlk_technology"]
    # Op de ruwe reeks bevat de laatste-3-jaar-telling de halvering, op de gecorrigeerde niet: de 5-per-jaar-drempel is veel kleiner.
    assert r_ruw.quantile_thresholds[5] != r_corr.quantile_thresholds[5]
    tekst = tc.render_split_vergelijking(ruw, corr)
    assert "xlk_technology" in tekst and "VERGELIJKING" in tekst and "nieuwe trigger-versie" in tekst
    assert "xlf_financials" not in tekst  # alleen reeksen met een splitsing


def test_het_script_toont_de_vergelijking_zonder_te_schrijven(conn, tmp_path, capsys):
    import importlib.util

    conn.close()
    spec = importlib.util.spec_from_file_location("calibrate_script", ROOT / "calibrate_triggers.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    pad = str(tmp_path / "t.db")
    assert script.main(["--db", pad, "--vergelijk-splitsingen"]) == 0
    uit = capsys.readouterr().out
    assert "VERGELIJKING VOOR REEKSEN MET EEN AANDELENSPLITSING" in uit and "xlk_technology" in uit


# --------------------------------------------------------------------------
# De waakhond
# --------------------------------------------------------------------------


LIJST = (Splitsing("xlk_technology", SPLITSDATUM, 2.0, "test"),)


def test_een_geregistreerde_splitsing_die_de_data_bevestigt_is_schoon(conn):
    assert sw.beoordeel(conn, ["xlk_technology", "xlf_financials", "spy_benchmark"], LIJST).is_schoon
    assert sw.waarschuwingen(conn, ["xlk_technology", "xlf_financials", "spy_benchmark"], LIJST) == []


def test_een_onverklaarde_sprong_wordt_gemeld_als_mogelijke_nieuwe_splitsing(conn):
    b = sw.beoordeel(conn, ["xlk_technology"], ())
    assert [(s.metric_key, s.datum) for s in b.onverklaard] == [("xlk_technology", SPLITSDATUM)]
    regel = sw.waarschuwingen(conn, ["xlk_technology"], ())[0]
    assert "NIET geregistreerd" in regel and "xlk_technology" in regel and "2025-12-05" in regel and "SPLITSINGEN" in regel


def test_een_verkeerde_verhouding_wordt_gemeld_als_afwijkend(conn):
    verkeerd = (Splitsing("xlk_technology", SPLITSDATUM, 3.0, "typefout"),)
    b = sw.beoordeel(conn, ["xlk_technology"], verkeerd)
    assert len(b.afwijkend) == 1 and not b.onverklaard
    assert "past niet bij de data" in sw.waarschuwingen(conn, ["xlk_technology"], verkeerd)[0]


def test_een_verkeerde_datum_geeft_twee_meldingen_onverklaard_en_onbevestigd(conn):
    verkeerd = (Splitsing("xlk_technology", date(2025, 12, 22), 2.0, "typefout in de datum"),)
    b = sw.beoordeel(conn, ["xlk_technology"], verkeerd)
    assert len(b.onverklaard) == 1 and len(b.onbevestigd) == 1
    regels = sw.waarschuwingen(conn, ["xlk_technology"], verkeerd)
    assert any("niet bevestigd door de data" in r for r in regels) and any("NIET geregistreerd" in r for r in regels)


def test_een_splitsing_in_het_weekend_valt_in_de_sprong_tussen_vrijdag_en_maandag(tmp_path):
    c = init_db(str(tmp_path / "w.db"))
    dagen = _werkdagen(date(2025, 11, 3), date(2025, 12, 31))
    na = date(2025, 12, 8)  # maandag
    waarden = [200.0 if d < na else 100.0 for d in dagen]
    _opslaan(c, "xle_energy", waarden, dagen)
    zaterdag = (Splitsing("xle_energy", date(2025, 12, 6), 2.0, "t"),)
    assert sw.beoordeel(c, ["xle_energy"], zaterdag).is_schoon
    c.close()


def test_een_gewone_crashdag_en_een_reeks_met_alleen_data_aan_een_kant_geven_geen_melding(tmp_path):
    c = init_db(str(tmp_path / "c.db"))
    dagen = _werkdagen(date(2025, 11, 3), date(2025, 12, 31))
    crash = [100.0] * 20 + [100.0 * 0.79] * (len(dagen) - 20)  # -21% in een dag, zoals XLE in maart 2020
    _opslaan(c, "xle_energy", crash, dagen)
    assert sw.beoordeel(c, ["xle_energy"], ()).is_schoon
    # een geregistreerde splitsing in een reeks die pas ná de splitsing begint: niets om te bevestigen, dus geen valse melding
    _opslaan(c, "xlk_technology", [150.0] * 15, _werkdagen(date(2025, 12, 8), date(2025, 12, 26))[:15])
    assert sw.beoordeel(c, ["xlk_technology"], LIJST).is_schoon
    c.close()


def test_de_sleutels_van_de_waakhond_zijn_de_sector_etfs_en_spy():
    sleutels = sw.etf_sleutels()
    assert len(sleutels) == 12 and "spy_benchmark" in sleutels and "xlk_technology" in sleutels


def test_de_echte_lijst_en_de_echte_reeksen_samen_zijn_schoon(conn):
    """Met de echte SPLITSINGEN: xlk heeft zijn sprong op 5 december, die is geregistreerd."""
    assert sw.beoordeel(conn, ["xlk_technology", "xlf_financials", "spy_benchmark"]).is_schoon


# --------------------------------------------------------------------------
# De dagelijkse run en het freeze-overzicht
# --------------------------------------------------------------------------


def _agent_zonder_data():
    def monitor(conn, now=None, event_id=None):
        return DomainOutput(domain="sector", mode=Mode.MONITORING, generated_at=now, claims=[
            Claim(domain="sector", claim="x", value=1.0, source="t", confidence=Confidence.HIGH, analysis_time=now,
                  metric_key="testmetric")]), []

    return AgentSpec("sector", monitor)


def test_de_dagelijkse_run_logt_een_waarschuwing_bij_een_onverklaarde_sprong(tmp_path, caplog):
    c = init_db(str(tmp_path / "d.db"))
    dagen = _werkdagen(date(2026, 8, 3), date(2026, 9, 25))
    waarden = [90.0 if d < date(2026, 9, 1) else 45.0 for d in dagen]  # een nieuwe, nog niet geregistreerde halvering
    _opslaan(c, "xlf_financials", waarden, dagen)
    with caplog.at_level(logging.WARNING):
        run_daily(c, agents=[_agent_zonder_data()], now=datetime(2026, 10, 5, 7, 15, tzinfo=UTC))
    assert any("NIET geregistreerd" in r.getMessage() and "xlf_financials" in r.getMessage() for r in caplog.records)
    c.close()


def test_een_fout_in_de_waakhond_laat_de_run_niet_mislukken(tmp_path, caplog, monkeypatch):
    c = init_db(str(tmp_path / "d.db"))

    def kapot(conn):
        raise RuntimeError("boem")

    monkeypatch.setattr("runtime.daily.splitsing_waarschuwingen", kapot)
    with caplog.at_level(logging.ERROR):
        r = run_daily(c, agents=[_agent_zonder_data()], now=datetime(2026, 10, 5, 7, 15, tzinfo=UTC))
    assert r.succeeded == ["sector"]  # de monitoring zelf is geslaagd
    assert any("Splitsingscontrole mislukt" in x.getMessage() for x in caplog.records)
    c.close()


def test_een_schone_run_logt_niets_over_splitsingen(conn, caplog):
    with caplog.at_level(logging.WARNING):
        run_daily(conn, agents=[_agent_zonder_data()], now=datetime(2026, 10, 5, 7, 15, tzinfo=UTC))
    assert not any("splitsing" in r.getMessage().lower() for r in caplog.records)


def test_het_freeze_overzicht_toont_de_splitsingen_en_meldt_een_onverklaarde_sprong(conn, tmp_path):
    from runtime import freeze_status as fs

    pad = str(tmp_path / "t.db")
    conn.commit()
    punten = {p.naam: p for p in fs.bepaal_punten(pad)}
    punt = punten["Aandelensplitsingen (correctie bij het lezen)"]
    assert punt.status == fs.AKKOORD_DD and "5 geregistreerd" in punt.waarde and "2025-12-05" in punt.waarde   # DD-akkoord 02-10

    # een onverklaarde sprong in de database maakt er een LET OP van
    ander = init_db(str(tmp_path / "ander.db"))
    dagen = _werkdagen(date(2026, 8, 3), date(2026, 9, 25))
    _opslaan(ander, "xlf_financials", [90.0 if d < date(2026, 9, 1) else 45.0 for d in dagen], dagen)
    ander.close()
    punt = {p.naam: p for p in fs.bepaal_punten(str(tmp_path / "ander.db"))}["Aandelensplitsingen (correctie bij het lezen)"]
    assert punt.status == fs.LET_OP and "xlf_financials" in punt.opmerking


def test_de_waakhond_en_de_correctie_schrijven_niets():
    for naam in ("src/runtime/split_waakhond.py", "src/contract/corporate_actions.py"):
        tekst = (ROOT / naam).read_text()
        code = "\n".join(r for r in tekst.splitlines() if not r.lstrip().startswith("#"))
        for verboden in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", ".commit()", "executemany"):
            assert verboden not in code, (naam, verboden)
