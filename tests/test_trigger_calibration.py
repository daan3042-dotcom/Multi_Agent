"""
test_trigger_calibration.py
Tests voor het trigger-kalibratierapport (roadmap 1.5), `src/calibration/`.

WAT HIER OP HET SPEL STAAT. Het rapport onderbouwt een keuze die na T0b niet meer
terug te draaien is zonder een nieuw cohort te starten. Een rapport dat net iets anders
telt dan het echte systeem, laat DD kiezen op basis van getallen die niet kloppen -- en
dat is niet te zien. Daarom: (1) een test die het rapport vergelijkt met de ECHTE
`evaluate_surprise`, inclusief de randgevallen waar de verandering precies gelijk is aan
de tolerance, en (2) verwachte uitkomsten die met de hand zijn nagerekend.
"""

from __future__ import annotations

import importlib.util
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from calibration.trigger_calibration import (
    MIN_PAIRS,
    TARGET_PER_YEAR,
    abs_changes,
    calibrate_all,
    calibrate_series,
    fires,
    metric_registry,
    render_report,
    threshold_for_events_per_year,
)
from contract.output_contract import Claim, Confidence, DomainOutput, Mode
from storage.schema import init_db, save_domain_output
from triggers.trigger_engine import evaluate_surprise

ROOT = Path(__file__).resolve().parent.parent
START = datetime(2020, 1, 1, tzinfo=timezone.utc)
NU = datetime(2026, 9, 29, tzinfo=timezone.utc)


def _dagen(waarden, start=START, stap=1):
    return [(start + timedelta(days=i * stap), float(w)) for i, w in enumerate(waarden)]


# --------------------------------------------------------------------------
# De telregel: exact die van het echte systeem
# --------------------------------------------------------------------------


def test_verschillen_met_de_hand():
    """Waarden 1, 3, 2, 6: |verschil| = 2, 1, 4 en de vorige waarde = 1, 3, 2."""
    uitkomst = abs_changes(_dagen([1, 3, 2, 6]))
    assert [(dev, prev) for _, dev, prev in uitkomst] == [(2.0, 1.0), (1.0, 3.0), (4.0, 2.0)]


def test_gelijk_aan_de_tolerance_vuurt_niet():
    """Strikt groter dan, zoals in evaluate_surprise. Een verandering precies gelijk
    aan de tolerance is geen trigger."""
    assert not fires(2.0, 2.0)
    assert fires(2.0001, 2.0)


def test_het_rapport_telt_exact_zoals_evaluate_surprise():
    """DE test die de rest draagt. Hele getallen, zodat er veel paren precies op de
    grens zitten, en elk paar wordt door de ECHTE trigger-functie beoordeeld."""
    rng = random.Random(20260929)
    for _ in range(20):
        waarden = [rng.randint(0, 6) for _ in range(120)]
        tolerance = float(rng.randint(0, 5))

        met_engine = sum(
            1 for i in range(1, len(waarden))
            if evaluate_surprise("d", "m", float(waarden[i]), float(waarden[i - 1]), tolerance, "t") is not None
        )
        met_rapport = calibrate_series("d", "m", tolerance, _dagen(waarden)).stats["alles"].fires

        assert met_rapport == met_engine, f"tolerance {tolerance}: rapport {met_rapport}, engine {met_engine}"


def test_alle_verschillen_precies_op_de_grens_vuren_niet():
    """0, 2, 4, 6, ...: elk verschil is 2. Met tolerance 2 vuurt niets; net eronder alles."""
    reeks = _dagen(range(0, 120, 2))
    assert calibrate_series("d", "m", 2.0, reeks).stats["alles"].fires == 0
    assert calibrate_series("d", "m", 1.99, reeks).stats["alles"].fires == 59


# --------------------------------------------------------------------------
# Per jaar en per venster
# --------------------------------------------------------------------------


def test_aantal_per_jaar_met_de_hand():
    """366 dagelijkse waarnemingen die steeds tussen 0 en 1 wisselen: 365 paren, elk met
    verschil 1. Tolerance 0,5: alle 365 vuren, over 365/365,25 jaar = 365,25 per jaar."""
    stat = calibrate_series("d", "m", 0.5, _dagen([i % 2 for i in range(366)])).stats["alles"]

    assert (stat.pairs, stat.fires) == (365, 365)
    assert stat.per_year == pytest.approx(365.25, rel=1e-3)
    assert stat.fraction == 1.0


def test_een_rustige_laatste_periode_verschijnt_in_de_vensters():
    """Vijf jaar heftig (verschil 2 per dag), dan ruim een jaar rustig (0,1). Tolerance 1:
    het korte venster vuurt niet, het lange wel, en dat is een teken dat de drempel sterk
    afhangt van de periode. De rustige periode is langer dan het venster (400 dagen), want
    een venster van 365,25 dagen pakt anders nog het laatste heftige paar mee."""
    heftig = [2.0 * (i % 2) for i in range(5 * 365)]
    rustig = [0.1 * (i % 2) for i in range(400)]
    cal = calibrate_series("d", "m", 1.0, _dagen(heftig + rustig))

    assert cal.stats["1j"].fires == 0
    assert cal.stats["alles"].per_year > 100
    assert "wisselt sterk per periode" in cal.flags


def test_venster_is_gerekend_vanaf_de_laatste_waarneming_niet_vanaf_nu():
    """Een reeks die al maanden stilligt mag geen leeg '1j'-venster krijgen."""
    oud = datetime(2015, 1, 1, tzinfo=timezone.utc)
    cal = calibrate_series("d", "m", 0.5, _dagen([i % 2 for i in range(800)], start=oud))
    assert cal.stats["1j"].pairs > 300


# --------------------------------------------------------------------------
# Niveau-afhankelijkheid: waarom een absolute drempel voor een koers verouderd raakt
# --------------------------------------------------------------------------


def test_een_absolute_drempel_schuift_niet_mee_met_het_niveau():
    """Anderhalf jaar op ~10 (elke dag $1 verschil, dus 10%), dan een sprong naar ~100
    en anderhalf jaar waarin diezelfde $1 nog maar 1% is. Tolerance 2 (dollar):

    - absoluut vuurt alleen de sprong zelf (verschil ~89), want $1 < $2;
    - niveau-gecorrigeerd is de drempel 2% van het huidige niveau (100): de eerste
      periode vuurt elke dag (10% > 2%), de tweede niet (1% < 2%).

    De vaste dollardrempel is dus in de eerste periode nooit afgegaan waar hij in
    verhouding tot het niveau constant had moeten vuren. Dat is wat een sectoragent met
    'ruwweg 3%' gekalibreerde dollars over een decennium overkomt."""
    n1 = n2 = int(1.5 * 365)
    laag = [10.0 + (i % 2) for i in range(n1)]          # 10, 11, 10, 11, ...  verschil 1
    hoog = [100.0 + (i % 2) for i in range(n2)]         # 100, 101, ...         verschil 1
    cal = calibrate_series("d", "m", 2.0, _dagen(laag + hoog))

    assert cal.stats["3j"].fires == 1                    # alleen de sprong
    assert cal.level_adjusted_3y.fires == n1             # (n1 - 1) paren in de lage periode + de sprong
    assert "niveau-afhankelijk" in cal.flags


def test_een_reeks_die_door_nul_gaat_krijgt_geen_niveau_gecorrigeerde_telling():
    """Regressiegeval uit de eerste echte run: `yield_curve_10y_2y` (niveau 0,32, in de
    afgelopen jaren negatief) gaf een absolute telling van 0 per jaar en een
    'gecorrigeerde' van 11,7, met de vlag niveau-afhankelijk. Een percentage van een
    niveau rond nul is geen maat. De gecorrigeerde telling ontbreekt dan, en dus de vlag."""
    golf = [0.3 * ((i % 40) - 20) / 20 for i in range(1000)]      # beweegt tussen -0,3 en +0,3
    cal = calibrate_series("d", "m", 0.5, _dagen(golf + [0.32]))

    assert cal.level_adjusted_3y is None
    assert "niveau-afhankelijk" not in cal.flags
    assert cal.tolerance_pct_of_level is not None       # de breuk zelf bestaat wel; de weergave verbergt hem


def test_een_koers_krijgt_wel_een_niveau_gecorrigeerde_telling():
    cal = calibrate_series("d", "m", 2.0, _dagen([100.0 + (i % 2) for i in range(400)]))
    assert cal.level_adjusted_3y is not None


def test_tolerance_als_percentage_van_het_niveau():
    cal = calibrate_series("d", "m", 6.0, _dagen([100.0 + (i % 2) for i in range(100)]))
    assert cal.tolerance_pct_of_level == pytest.approx(6.0 / 101.0 * 100)


# --------------------------------------------------------------------------
# Drempels bij een doelfrequentie
# --------------------------------------------------------------------------


def test_drempel_bij_een_aantal_triggers_per_jaar_met_de_hand():
    """Verschillen 1, 2, ..., 100 bij 100 waarnemingen per jaar. Eén trigger per jaar =
    1% van de waarnemingen = het 99e percentiel; een empirisch kwantiel met lineaire
    interpolatie: positie 0,99 * 99 = 98,01, dus 99 + 0,01 = 99,01. Twee per jaar: 98,02.
    Vijf per jaar: 95,05."""
    devs = [float(i) for i in range(1, 101)]
    assert threshold_for_events_per_year(devs, 100.0, 1) == pytest.approx(99.01)
    assert threshold_for_events_per_year(devs, 100.0, 2) == pytest.approx(98.02)
    assert threshold_for_events_per_year(devs, 100.0, 5) == pytest.approx(95.05)


def test_een_maandreeks_heeft_een_veel_lagere_drempel_bij_hetzelfde_aantal_per_jaar():
    """DE reden dat de tabel per jaar telt en niet als percentage van de dagen. Bij 12
    waarnemingen per jaar betekent '2 per jaar' een zesde van de waarnemingen (het 83e
    percentiel), bij 252 per jaar minder dan 1%."""
    devs = [float(i) for i in range(1, 101)]
    maand = threshold_for_events_per_year(devs, 12.0, 2)      # 2/12 = 16,7% -> 83e percentiel
    dag = threshold_for_events_per_year(devs, 252.0, 2)       # 2/252 = 0,79% -> 99,2e percentiel
    assert maand == pytest.approx(1 + 0.8333333 * 99, abs=1e-3)
    assert dag > maand + 10


def test_een_doel_dat_niet_haalbaar_is_geeft_geen_drempel():
    """Twee triggers per jaar bij een reeks met maar twee waarnemingen per jaar is
    'altijd vuren', dus geen drempel."""
    assert threshold_for_events_per_year([1.0, 2.0, 3.0], 2.0, 2) is None
    assert threshold_for_events_per_year([1.0, 2.0, 3.0], 0.0, 2) is None


def test_de_gekozen_drempel_vuurt_daadwerkelijk_ongeveer_zo_vaak():
    """Terugrekenen: drie jaar dagelijkse, willekeurige (geseede) veranderingen. De
    drempel bij 5 per jaar moet, toegepast op diezelfde reeks, ongeveer 5 keer per jaar
    vuren."""
    rng = random.Random(11)
    waarden, v = [0.0], 0.0
    for _ in range(3 * 365):
        v += rng.gauss(0, 1)
        waarden.append(v)
    cal = calibrate_series("d", "m", 1.0, _dagen(waarden))

    assert set(cal.quantile_thresholds) == set(TARGET_PER_YEAR)
    assert cal.quantile_thresholds[2] >= cal.quantile_thresholds[5] >= cal.quantile_thresholds[10]
    teruggerekend = calibrate_series("d", "m", cal.quantile_thresholds[5], _dagen(waarden)).stats["3j"].per_year
    assert teruggerekend == pytest.approx(5.0, abs=2.0)


def test_te_weinig_paren_geeft_geen_drempelvoorstel():
    cal = calibrate_series("d", "m", 1.0, _dagen(range(10)))
    assert cal.quantile_thresholds == {}
    assert "te weinig historie" in cal.flags


# --------------------------------------------------------------------------
# De oordeel-kolom
# --------------------------------------------------------------------------


def test_een_verschil_tussen_vensters_met_bijna_geen_triggers_is_geen_teken():
    """De eerste versie zette 'wisselt sterk per periode' op 25 van de 40 regels, ook
    als er in een venster maar één of twee triggers waren: een factor drie tussen 1 en 3
    triggers is toeval. Nu tellen alleen vensters met minstens vijf triggers mee."""
    # Eén enkele uitschieter in de laatste maand van een verder rustige reeks.
    rustig = [0.0] * 900 + [5.0] + [0.0] * 100
    cal = calibrate_series("d", "m", 1.0, _dagen(rustig))
    assert "wisselt sterk per periode" not in cal.flags


def test_geen_waarnemingen_is_geen_historie():
    assert calibrate_series("d", "m", 1.0, []).flags == ("geen historie",)
    assert calibrate_series("d", "m", 1.0, _dagen([5])).flags == ("geen historie",)


def test_een_te_hoge_drempel_vuurt_nooit():
    cal = calibrate_series("d", "m", 1000.0, _dagen([i % 2 for i in range(400)]))
    assert "vuurt nooit" in cal.flags


def test_een_te_lage_drempel_vuurt_vaak():
    cal = calibrate_series("d", "m", 0.01, _dagen([i % 2 for i in range(400)]))
    assert any(f.startswith("vuurt vaak") for f in cal.flags)


def _maanden(waarden):
    """Zoals `_dagen`, maar één waarneming per maand (30 dagen): een maandreeks."""
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return [(start + timedelta(days=30 * i), w) for i, w in enumerate(waarden)]


def test_vijf_keer_per_jaar_op_een_maandreeks_is_niet_vaak():
    """Regressie op de eerste vlag ('vuurt op meer dan 10% van de waarnemingen'): die gaf
    'vuurt vaak (42%)' bij elke maandreeks die precies op het doel van 5 per jaar zat, omdat
    5 van de 12 publicaties per ontwerp 42% is. Het gaat om het aantal per jaar."""
    # Elke tweede maand een sprong van 1: ~6 triggers per jaar bij tolerance 0,5.
    reeks = [(i % 2) * 1.0 for i in range(60)]
    cal = calibrate_series("d", "m", 0.5, _maanden(reeks))
    assert not any(f.startswith("vuurt vaak") for f in cal.flags), cal.flags


def test_een_dagreeks_met_zestig_triggers_per_jaar_is_wel_vaak():
    """De vlag is niet weggehaald, alleen gelijkgetrokken: 60 per jaar is voor elke cadans veel."""
    reeks = [0.0] * 6 + [1.0] * 6
    reeks = (reeks * 200)[: 3 * 365]
    cal = calibrate_series("d", "m", 0.5, _dagen(reeks))
    assert any(f.startswith("vuurt vaak") for f in cal.flags), cal.flags


def test_een_regel_die_bijna_nooit_vuurt_krijgt_de_vlag_zelden():
    reeks = [0.0] * 1000
    reeks[500] = 5.0  # één sprong in ~2,7 jaar (twee veranderingen: op en neer)
    cal = calibrate_series("d", "m", 1.0, _dagen(reeks))
    assert "vuurt zelden" in cal.flags, cal.flags


def test_korte_historie_wordt_gemeld():
    """`high_yield_credit_spread` heeft maar ~3 jaar: 'alles' zegt daar niet meer dan '3j'."""
    cal = calibrate_series("d", "m", 0.5, _dagen([i % 2 for i in range(3 * 365)]))
    assert any(f.startswith("korte historie") for f in cal.flags)


# --------------------------------------------------------------------------
# Tegen de database en de echte agent-drempels
# --------------------------------------------------------------------------


def _reeks_in_db(conn, domain, key, waarden, laatste=NU - timedelta(days=1)):
    n = len(waarden)
    claims = []
    for i, w in enumerate(waarden):
        dag = laatste - timedelta(days=n - 1 - i)
        claims.append(Claim(
            domain=domain, claim=key, value=float(w), source="test", confidence=Confidence.HIGH,
            analysis_time=dag, source_time=dag, metric_key=key,
        ))
    save_domain_output(conn, DomainOutput(domain=domain, mode=Mode.MONITORING, generated_at=claims[0].analysis_time, claims=claims))


def test_de_registry_leest_elke_drempel_rechtstreeks_uit_de_agents():
    """Geen kopie: verandert een tolerance in de code, dan verandert het rapport mee. En
    elke gemonitorde reeks staat erin."""
    from agents import (
        commodity_agent, currency_agent, economic_agent, financial_agent,
        monetary_policy_agent, sector_agent,
    )

    verwacht = {
        (m.DOMAIN, key): spec.tolerance
        for m in (monetary_policy_agent, currency_agent, financial_agent, sector_agent, commodity_agent, economic_agent)
        for key, spec in m.METRIC_SPECS.items()
    }
    werkelijk = {(d, k): s.tolerance for d, k, s in metric_registry()}

    assert werkelijk == verwacht
    assert len(werkelijk) == 41  # 40 + fed_funds_target_upper (01-10-2026)


def test_calibrate_all_gebruikt_de_echte_tolerance_en_markeert_wat_zonder_historie_is(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _reeks_in_db(conn, "monetary_policy", "10y_treasury_yield", [4.0 + 0.05 * (i % 7) for i in range(400)])

    resultaten = {(r.domain, r.metric_key): r for r in calibrate_all(conn, NU)}
    tien_jaar = resultaten[("monetary_policy", "10y_treasury_yield")]

    # De echte tolerance uit de agent, niet een getal dat bij elke
    # kalibratie moet meeveranderen: dit is wat de test bewaakt.
    from agents import monetary_policy_agent

    assert tien_jaar.tolerance == monetary_policy_agent.METRIC_SPECS["10y_treasury_yield"].tolerance
    assert tien_jaar.n_pairs == 399
    assert resultaten[("currency", "eur_usd")].flags == ("geen historie",)


def test_waarnemingen_na_nu_tellen_niet_mee(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _reeks_in_db(conn, "monetary_policy", "10y_treasury_yield", [4.0 + 0.05 * (i % 7) for i in range(200)])
    voor = {(r.domain, r.metric_key): r.n_pairs for r in calibrate_all(conn, NU)}

    _reeks_in_db(conn, "monetary_policy", "10y_treasury_yield", [9.0] * 20, laatste=NU + timedelta(days=30))
    na = {(r.domain, r.metric_key): r.n_pairs for r in calibrate_all(conn, NU)}

    assert voor == na


def test_domeinfilter(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    resultaten = calibrate_all(conn, NU, domain="currency")
    assert {r.domain for r in resultaten} == {"currency"}
    assert len(resultaten) == 3


# --------------------------------------------------------------------------
# Weergave en CLI
# --------------------------------------------------------------------------


def test_het_rapport_bevat_alle_drie_de_tabellen_en_een_leeswijzer():
    tekst = render_report([calibrate_series("d", "m", 0.5, _dagen([i % 2 for i in range(400)]))])
    for kop in ("TABEL 1", "TABEL 2", "TABEL 3", "HOE TE LEZEN"):
        assert kop in tekst
    assert "TOTAAL" in tekst


def _cli():
    spec = importlib.util.spec_from_file_location("cli_calibrate", ROOT / "calibrate_triggers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_toont_het_rapport_en_geeft_nul(tmp_path, capsys):
    conn = init_db(str(tmp_path / "t.db"))
    _reeks_in_db(conn, "monetary_policy", "10y_treasury_yield", [4.0 + 0.05 * (i % 7) for i in range(400)])
    conn.close()
    cli = _cli()
    cli.ENV_PATH = str(tmp_path / "geen.env")

    code = cli.main(["--db", str(tmp_path / "t.db"), "--domain", "monetary_policy"])

    uitvoer = capsys.readouterr().out
    assert code == 0
    assert "TABEL 1" in uitvoer and "10y_treasury_yield" in uitvoer
    assert "eur_usd" not in uitvoer, "--domain moet het rapport beperken"


def test_cli_wijzigt_niets_in_de_database(tmp_path):
    """Alleen lezen. Het aantal rijen in elke tabel is na afloop gelijk."""
    pad = str(tmp_path / "t.db")
    conn = init_db(pad)
    _reeks_in_db(conn, "monetary_policy", "10y_treasury_yield", [4.0 + 0.05 * (i % 7) for i in range(300)])

    def telling(c):
        tabellen = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tabellen}

    voor = telling(conn)
    conn.close()
    cli = _cli()
    cli.ENV_PATH = str(tmp_path / "geen.env")
    cli.main(["--db", pad])

    na_conn = init_db(pad)
    assert telling(na_conn) == voor


def test_cli_onbereikbare_database_geeft_exitcode_twee(tmp_path):
    cli = _cli()
    cli.ENV_PATH = str(tmp_path / "geen.env")
    assert cli.main(["--db", "/proc/geen/toegang/t.db"]) == 2
