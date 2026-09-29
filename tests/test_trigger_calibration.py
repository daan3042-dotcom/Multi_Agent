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
    TARGET_FRACTIONS,
    abs_changes,
    calibrate_all,
    calibrate_series,
    fires,
    metric_registry,
    render_report,
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


def test_tolerance_als_percentage_van_het_niveau():
    cal = calibrate_series("d", "m", 6.0, _dagen([100.0 + (i % 2) for i in range(100)]))
    assert cal.tolerance_pct_of_level == pytest.approx(6.0 / 101.0 * 100)


# --------------------------------------------------------------------------
# Drempels bij een doelfrequentie
# --------------------------------------------------------------------------


def test_drempel_bij_een_doelfrequentie_met_de_hand():
    """Verschillen 1, 2, ..., 100 (v0=0, v1=1, v2=-1, v3=2, ...). Een empirisch kwantiel
    met lineaire interpolatie: 99% -> positie 0,99 * 99 = 98,01 -> 99 + 0,01 = 99,01;
    98% -> 98,02; 95% -> 95,05. Dus een drempel van 99,01 laat ~1% van de paren vuren."""
    waarden, v = [0.0], 0.0
    for i in range(1, 101):
        v += i if i % 2 else -i
        waarden.append(v)
    cal = calibrate_series("d", "m", 10.0, _dagen(waarden))

    assert [abs(waarden[i] - waarden[i - 1]) for i in range(1, 6)] == [1, 2, 3, 4, 5]
    assert cal.quantile_thresholds[0.01] == pytest.approx(99.01)
    assert cal.quantile_thresholds[0.02] == pytest.approx(98.02)
    assert cal.quantile_thresholds[0.05] == pytest.approx(95.05)


def test_te_weinig_paren_geeft_geen_drempelvoorstel():
    cal = calibrate_series("d", "m", 1.0, _dagen(range(10)))
    assert cal.quantile_thresholds == {}
    assert "te weinig historie" in cal.flags


# --------------------------------------------------------------------------
# De oordeel-kolom
# --------------------------------------------------------------------------


def test_geen_waarnemingen_is_geen_historie():
    assert calibrate_series("d", "m", 1.0, []).flags == ("geen historie",)
    assert calibrate_series("d", "m", 1.0, _dagen([5])).flags == ("geen historie",)


def test_een_te_hoge_drempel_vuurt_nooit():
    cal = calibrate_series("d", "m", 1000.0, _dagen([i % 2 for i in range(400)]))
    assert "vuurt nooit" in cal.flags


def test_een_te_lage_drempel_vuurt_vaak():
    cal = calibrate_series("d", "m", 0.01, _dagen([i % 2 for i in range(400)]))
    assert any(f.startswith("vuurt vaak") for f in cal.flags)


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
    assert len(werkelijk) == 40


def test_calibrate_all_gebruikt_de_echte_tolerance_en_markeert_wat_zonder_historie_is(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _reeks_in_db(conn, "monetary_policy", "10y_treasury_yield", [4.0 + 0.05 * (i % 7) for i in range(400)])

    resultaten = {(r.domain, r.metric_key): r for r in calibrate_all(conn, NU)}
    tien_jaar = resultaten[("monetary_policy", "10y_treasury_yield")]

    assert tien_jaar.tolerance == 0.25
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
