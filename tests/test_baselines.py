"""
test_baselines.py
Tests voor persistence en climatology (roadmap 4.6), `src/scoring/baselines.py`.

WAT HIER OP HET SPEL STAAT. Een baseline die te goed of te slecht is, laat
elke agent er beter of slechter uitzien dan hij is -- en dat is precies de
fout die je niet aan de scores ziet. Daarom zijn de verwachte getallen hier
met de hand nagerekend en niet berekend met dezelfde functie die getest
wordt. Waar staat "hand", staat de rekensom erbij.

De tweede reden voor deze tests: een baseline die met te weinig data toch
iets uitspreekt, is een strohalm. Elk 'te weinig'-pad heeft dus een test die
bewijst dat er NIETS wordt voorspeld en dat dat zichtbaar is.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from agents import monetary_policy_agent
from agents.base import AlreadyProcessedError, ForecastTarget
from contract.horizons import ReleaseCadence, resolves_at_for
from contract.output_contract import Claim, Confidence, DomainOutput, Mode
from contract.prediction import HorizonKind, PredictionKind
from contract.resolution import ResolutionMethod
from scoring.baselines import (
    CLIMATOLOGY,
    MIN_SAMPLES,
    PERSISTENCE,
    baseline_predictions,
    empirical_quantile,
)
from scoring.baseline_round import run_baseline_round
from scoring.resolver import resolve_due_predictions
from storage.schema import (
    init_db,
    list_agent_runs,
    list_evaluations,
    list_predictions,
    save_domain_output,
)

VRIJDAG = datetime(2026, 10, 2, tzinfo=timezone.utc)
MAANDAG = datetime(2026, 10, 5, 7, 15, tzinfo=timezone.utc)


def _db(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def _reeks(conn, metric_key, waarden, laatste=VRIJDAG, domain="monetary_policy", stap=1):
    """Slaat een reeks op zoals de back-fill dat doet: analysis_time =
    source_time, één claim per waarneming, oplopend in de tijd tot en met
    `laatste`."""
    n = len(waarden)
    claims = []
    for i, waarde in enumerate(waarden):
        dag = laatste - timedelta(days=(n - 1 - i) * stap)
        claims.append(Claim(
            domain=domain, claim=metric_key, value=float(waarde), source="test",
            confidence=Confidence.HIGH, analysis_time=dag, source_time=dag,
            metric_key=metric_key,
        ))
    save_domain_output(conn, DomainOutput(
        domain=domain, mode=Mode.MONITORING, generated_at=claims[0].analysis_time, claims=claims,
    ))


def _doel(metric_key="x", horizons=(1,), **kw) -> ForecastTarget:
    basis = dict(
        metric_key=metric_key, kind=PredictionKind.QUANTILE,
        horizon_kind=HorizonKind.TRADING_DAYS, horizons=horizons,
        resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER,
        resolution_rule="x op of na resolves_at ({horizon_n} handelsdagen)",
    )
    basis.update(kw)
    return ForecastTarget(**basis)


def _per_agent(resultaat):
    return {p.agent: p for p in resultaat.predictions}


# --------------------------------------------------------------------------
# De statistiek zelf
# --------------------------------------------------------------------------


def test_empirisch_kwantiel_met_de_hand_nagerekend():
    """Waarden 1..100. Positie = q * 99. q=0,10 -> 9,9 -> tussen index 9
    (=10) en index 10 (=11): 10 + 0,9 * 1 = 10,9."""
    waarden = [float(i) for i in range(1, 101)]
    assert empirical_quantile(waarden, 0.10) == pytest.approx(10.9)
    assert empirical_quantile(waarden, 0.50) == pytest.approx(50.5)
    assert empirical_quantile(waarden, 0.90) == pytest.approx(90.1)
    assert empirical_quantile(waarden, 0.0) == 1.0
    assert empirical_quantile(waarden, 1.0) == 100.0


def test_kwantiel_van_een_lege_lijst_of_ongeldig_niveau_faalt_hard():
    with pytest.raises(ValueError):
        empirical_quantile([], 0.5)
    with pytest.raises(ValueError):
        empirical_quantile([1.0], 1.5)


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def test_persistence_mediaan_is_het_anker_en_spreiding_komt_uit_de_historie(tmp_path):
    """Hand: veranderingen [-2,-1,0,1,2] acht keer herhaald (40 vensters,
    h=1), beginwaarde 100. Elke cyclus telt op tot 0, dus het anker is 100.
    Gesorteerd: acht keer elk. q10: positie 3,9 -> index 3 en 4, beide -2.
    q50: positie 19,5 -> index 19 en 20, beide 0. q90: positie 35,1 -> index
    35 en 36, beide 2. Persistence = anker + (q - q50) = (98, 100, 102)."""
    conn = _db(tmp_path)
    stappen = [-2, -1, 0, 1, 2] * 8
    waarden = [100.0]
    for s in stappen:
        waarden.append(waarden[-1] + s)
    _reeks(conn, "x", waarden)

    uitkomst = baseline_predictions(conn, "monetary_policy", [_doel()], MAANDAG)

    p = _per_agent(uitkomst)[PERSISTENCE]
    assert (p.q10, p.q50, p.q90) == (98.0, 100.0, 102.0)
    assert uitkomst.issues == ()


def test_persistence_neemt_de_drift_niet_mee(tmp_path):
    """Regressiegeval. Een reeks die elke dag +1 stijgt heeft als enige
    verandering +1. Zonder centrering zou de mediaan anker+1 zijn en is het
    een random walk MET trend -- een baseline met een ingebouwde trend
    verslaat een agent die dat niet weet, om de verkeerde reden."""
    conn = _db(tmp_path)
    _reeks(conn, "x", [float(i) for i in range(60)])

    p = _per_agent(baseline_predictions(conn, "monetary_policy", [_doel()], MAANDAG))[PERSISTENCE]

    assert p.q50 == 59.0  # het laatste niveau, geen 60
    assert (p.q10, p.q90) == (59.0, 59.0)  # alle veranderingen gelijk -> geen spreiding


# --------------------------------------------------------------------------
# Climatology
# --------------------------------------------------------------------------


def test_climatology_onvoorwaardelijk_met_de_hand_nagerekend(tmp_path):
    """Niveaus 1..100 (honderd opeenvolgende dagen), resolves_at in oktober
    met slechts twee waarnemingen in die maand: te dun voor seizoen, dus de
    onvoorwaardelijke verdeling. Hand: (10,9; 50,5; 90,1) -- zie de
    kwantieltest hierboven."""
    conn = _db(tmp_path)
    _reeks(conn, "x", [float(i) for i in range(1, 101)])

    p = _per_agent(baseline_predictions(conn, "monetary_policy", [_doel(horizons=(5,))], MAANDAG))[CLIMATOLOGY]

    assert (p.q10, p.q50, p.q90) == pytest.approx((10.9, 50.5, 90.1))
    assert "onvoorwaardelijk" in p.note
    assert "n=100" in p.note


def test_climatology_conditioneert_op_seizoen_als_er_genoeg_data_is(tmp_path):
    """Drie jaar dagdata waarin oktober structureel hoger ligt (200) dan de
    rest (100). Voor een voorspelling die in oktober afloopt hoort de
    seizoensverdeling gebruikt te worden."""
    conn = _db(tmp_path)
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    dagen = (VRIJDAG - start).days + 1
    waarden = []
    for i in range(dagen):
        dag = start + timedelta(days=i)
        waarden.append((200.0 if dag.month == 10 else 100.0) + (i % 3))
    _reeks(conn, "x", waarden)

    p = _per_agent(baseline_predictions(conn, "monetary_policy", [_doel(horizons=(5,))], MAANDAG))[CLIMATOLOGY]

    assert p.q10 >= 200.0, "seizoensverdeling van oktober verwacht, niet de onvoorwaardelijke"
    assert "seizoen: maand 10" in p.note


def test_climatology_valt_terug_op_onvoorwaardelijk_en_zegt_dat(tmp_path):
    """Dezelfde jaren, maar een voorspelling die in maart afloopt terwijl de
    reeks pas in augustus begint: geen enkele maartwaarneming. De terugval
    mag, maar niet stil."""
    conn = _db(tmp_path)
    _reeks(conn, "x", [float(i) for i in range(1, 101)])
    maandag_maart = datetime(2026, 10, 5, 7, 15, tzinfo=timezone.utc)

    uitkomst = baseline_predictions(
        conn, "monetary_policy", [_doel(horizons=(63,))], maandag_maart
    )
    p = _per_agent(uitkomst)[CLIMATOLOGY]
    assert "onvoorwaardelijk" in p.note
    assert "minimaal 60 nodig" in p.note


# --------------------------------------------------------------------------
# Relatief rendement (sector)
# --------------------------------------------------------------------------


def _relatief_doel():
    return _doel(
        "etf", horizons=(5,),
        resolution_method=ResolutionMethod.RELATIVE_RETURN,
        benchmark_metric_key="spy",
        resolution_rule="relatief rendement van etf t.o.v. spy over {horizon_n} handelsdagen",
    )


def test_relatief_rendement_met_de_hand_nagerekend(tmp_path):
    """ETF groeit elke dag exact 1%, SPY staat stil. Elk 5-daags venster:
    (1,01^5 - 1) * 100 = 5,101005 procentpunt. Alle vensters gelijk, dus
    climatology is overal 5,101005 en persistence (anker 0, gecentreerd)
    overal 0."""
    conn = _db(tmp_path)
    _reeks(conn, "etf", [100 * 1.01 ** i for i in range(60)], domain="sector")
    _reeks(conn, "spy", [100.0] * 60, domain="sector")

    uitkomst = baseline_predictions(conn, "sector", [_relatief_doel()], MAANDAG)
    per_agent = _per_agent(uitkomst)

    assert (per_agent[CLIMATOLOGY].q10, per_agent[CLIMATOLOGY].q50, per_agent[CLIMATOLOGY].q90) == pytest.approx(
        (5.101005, 5.101005, 5.101005)
    )
    # 1,01^i wordt per dag afgerond, dus 'gelijke' vensters verschillen op
    # ~1e-14: abs-tolerantie, geen exacte gelijkheid.
    assert (per_agent[PERSISTENCE].q10, per_agent[PERSISTENCE].q50, per_agent[PERSISTENCE].q90) == pytest.approx(
        (0.0, 0.0, 0.0), abs=1e-9
    )
    assert per_agent[PERSISTENCE].benchmark_metric_key == "spy"


def test_relatief_rendement_zonder_benchmark_is_een_probleem_geen_gok(tmp_path):
    conn = _db(tmp_path)
    _reeks(conn, "etf", [100.0 + i for i in range(60)], domain="sector")

    uitkomst = baseline_predictions(conn, "sector", [_relatief_doel()], MAANDAG)

    assert uitkomst.predictions == ()
    assert uitkomst.issues and "gemeenschappelijk" in uitkomst.issues[0]


# --------------------------------------------------------------------------
# Wat er NIET voorspeld mag worden
# --------------------------------------------------------------------------


def test_te_weinig_historie_geeft_een_probleem_en_geen_voorspelling(tmp_path):
    """Regressiegeval voor de strohalm-baseline: met 20 waarnemingen kan er
    geen zinnig 10%-kwantiel geschat worden, en een baseline die het toch
    doet maakt elke agent er beter uit zien."""
    conn = _db(tmp_path)
    _reeks(conn, "x", [float(i) for i in range(20)])

    uitkomst = baseline_predictions(conn, "monetary_policy", [_doel()], MAANDAG)

    assert uitkomst.predictions == ()
    assert len(uitkomst.issues) == 1
    assert f"minimaal {MIN_SAMPLES} nodig" in uitkomst.issues[0]
    assert not uitkomst.is_complete


def test_geen_enkele_waarneming_is_een_probleem(tmp_path):
    conn = _db(tmp_path)
    uitkomst = baseline_predictions(conn, "monetary_policy", [_doel("bestaat_niet")], MAANDAG)
    assert uitkomst.predictions == ()
    assert "geen enkele waarneming" in uitkomst.issues[0]


def test_verouderd_anker_wordt_geweigerd(tmp_path):
    """Regressiegeval. Persistence vanaf een anker van zeven weken oud zegt
    'het blijft zoals het in augustus was' en ziet er verder normaal uit."""
    conn = _db(tmp_path)
    _reeks(conn, "x", [float(i) for i in range(60)], laatste=datetime(2026, 8, 20, tzinfo=timezone.utc))

    uitkomst = baseline_predictions(conn, "monetary_policy", [_doel()], MAANDAG)

    assert uitkomst.predictions == ()
    assert "dagen oud" in uitkomst.issues[0]


def test_maandreeks_mag_een_ouder_anker_hebben_dan_een_dagreeks(tmp_path):
    """UNRATE voor de vorige maand komt legitiem pas begin de maand daarna
    binnen. Een maandreeks van 55 dagen oud is dus gezond; een dagreeks van
    55 dagen oud is dat niet."""
    conn = _db(tmp_path)
    laatste = MAANDAG - timedelta(days=55)
    _reeks(conn, "unrate", [4.0 + (i % 5) * 0.1 for i in range(60)], laatste=laatste, stap=31)

    doel = _doel(
        "unrate", horizons=(1,), horizon_kind=HorizonKind.RELEASES,
        cadence=ReleaseCadence.MONTHLY, resolution_method=ResolutionMethod.NTH_RELEASE,
        resolution_rule="{horizon_n}-de UNRATE-publicatie, eerste print",
    )
    uitkomst = baseline_predictions(conn, "economic", [doel], MAANDAG)
    assert uitkomst.issues == ()
    assert len(uitkomst.predictions) == 2


def test_fomc_doelen_worden_bewust_overgeslagen_en_zijn_geen_probleem(tmp_path):
    """De richting van de Fed-doelrange is een gebeurtenis op FOMC-vergaderingen. Een
    basisrate uit maandvensters zou een andere gebeurtenis scoren. Dat staat
    onder `skipped` (ontwerp) en niet onder `issues` (probleem): het hoort
    niet in de melding."""
    conn = _db(tmp_path)
    _reeks(conn, "fed_funds_target_upper", [4.0 + (i % 4) * 0.25 for i in range(80)])

    fomc = [t for t in monetary_policy_agent.FORECAST_TARGETS if t.metric_key == "fed_funds_target_upper"]
    uitkomst = baseline_predictions(conn, "monetary_policy", fomc, MAANDAG)

    assert uitkomst.predictions == ()
    assert uitkomst.issues == ()
    assert len(uitkomst.skipped) == 2  # horizon 1 en 2
    assert all("FOMC" in s for s in uitkomst.skipped)


# --------------------------------------------------------------------------
# Point-in-time
# --------------------------------------------------------------------------


def test_waarnemingen_uit_de_toekomst_tellen_niet_mee(tmp_path):
    """Waar de pseudo-OOS-run (4.4) op leunt: dezelfde code over het
    verleden. Een waarneming van ná `as_of` mag de baseline niet
    beïnvloeden, anders is hij daar onzichtbaar te goed."""
    conn = _db(tmp_path)
    stappen = [-2, -1, 0, 1, 2] * 8
    waarden = [100.0]
    for s in stappen:
        waarden.append(waarden[-1] + s)
    _reeks(conn, "x", waarden)
    voor = baseline_predictions(conn, "monetary_policy", [_doel()], MAANDAG)

    # Een absurde waarde op een latere dag.
    _reeks(conn, "x", [1_000_000.0], laatste=VRIJDAG + timedelta(days=10))
    na = baseline_predictions(conn, "monetary_policy", [_doel()], MAANDAG)

    assert [(p.q10, p.q50, p.q90) for p in voor.predictions] == [
        (p.q10, p.q50, p.q90) for p in na.predictions
    ]


def test_laat_binnengekomen_waarneming_telt_niet_mee(tmp_path):
    """Een waarneming waarvan de periode vóór `as_of` ligt maar die wij pas
    ná `as_of` zagen, bestond op dat moment niet voor ons."""
    conn = _db(tmp_path)
    _reeks(conn, "x", [float(i) for i in range(60)])
    voor = baseline_predictions(conn, "monetary_policy", [_doel()], MAANDAG)

    laat = Claim(
        domain="monetary_policy", claim="x", value=999_999.0, source="test",
        confidence=Confidence.HIGH,
        analysis_time=MAANDAG + timedelta(days=30),   # pas later gezien
        source_time=VRIJDAG - timedelta(days=400),    # periode ver vóór as_of
        metric_key="x",
    )
    save_domain_output(conn, DomainOutput(
        domain="monetary_policy", mode=Mode.MONITORING,
        generated_at=laat.analysis_time, claims=[laat],
    ))
    na = baseline_predictions(conn, "monetary_policy", [_doel()], MAANDAG)

    assert [(p.q10, p.q50, p.q90) for p in voor.predictions] == [
        (p.q10, p.q50, p.q90) for p in na.predictions
    ]


# --------------------------------------------------------------------------
# Vergelijkbaarheid met de agents
# --------------------------------------------------------------------------


def test_baseline_voorspelt_exact_wat_de_agent_voorspelt(tmp_path):
    """Het punt van een baseline is dat hij op dezelfde meetlat ligt. Zelfde
    doel, horizon, afloopdatum, regel en methode als het ForecastTarget van
    de echte monetary agent."""
    conn = _db(tmp_path)
    for key in ("10y_treasury_yield", "2y_treasury_yield"):
        _reeks(conn, key, [4.0 + 0.01 * ((i * 7) % 13) for i in range(200)])

    doelen = monetary_policy_agent.FORECAST_TARGETS
    uitkomst = baseline_predictions(conn, "monetary_policy", doelen, MAANDAG)

    # 2 reeksen x 3 horizonnen x 2 baselines; FEDFUNDS (2 horizonnen) overgeslagen.
    assert len(uitkomst.predictions) == 12
    assert len(uitkomst.skipped) == 2
    assert uitkomst.issues == ()

    per_doel = {t.metric_key: t for t in doelen}
    for p in uitkomst.predictions:
        doel = per_doel[p.target_metric_key]
        assert p.resolves_at == resolves_at_for(MAANDAG, doel.horizon_kind, p.horizon_n, doel.cadence)
        assert p.resolution_rule == doel.resolution_rule.format(horizon_n=p.horizon_n)
        assert p.resolution_method is doel.resolution_method
        assert p.created_at == MAANDAG
        assert p.graph_node is doel.graph_node
        assert p.model_id == "deterministic"
        assert p.prompt_version == "baseline-v1"
        assert p.q10 <= p.q50 <= p.q90


def test_kwantielen_zijn_altijd_oplopend(tmp_path):
    """De Prediction weigert niet-oplopende kwantielen bij constructie, dus
    dit zou een crash zijn en geen stille fout -- maar een baseline die
    crasht op echte data is even onbruikbaar. Willekeurige (geseede)
    reeksen, allebei de baselines."""
    rng = random.Random(20260929)
    for ronde in range(10):
        conn = _db(tmp_path / f"r{ronde}") if False else init_db(":memory:")
        _reeks(conn, "x", [50 + rng.gauss(0, 5) for _ in range(150)])
        uitkomst = baseline_predictions(conn, "monetary_policy", [_doel(horizons=(1, 5, 21))], MAANDAG)
        assert len(uitkomst.predictions) == 6
        for p in uitkomst.predictions:
            assert p.q10 <= p.q50 <= p.q90


# --------------------------------------------------------------------------
# De ronde: atomair, idempotent, en door de resolver te scoren
# --------------------------------------------------------------------------


def _gevulde_db(tmp_path):
    conn = _db(tmp_path)
    _reeks(conn, "x", [100.0 + ((i * 7) % 11) for i in range(80)])
    return conn


def test_ronde_slaat_beide_baselines_op_met_een_run_regel(tmp_path):
    conn = _gevulde_db(tmp_path)

    uitkomst = run_baseline_round(conn, "monetary_policy", [_doel(horizons=(1, 5))], MAANDAG, event_id="2026-W41", ridge=False)

    rijen = list_predictions(conn)
    assert len(rijen) == 4
    assert {p.agent for p in rijen} == {PERSISTENCE, CLIMATOLOGY}
    runs = list_agent_runs(conn, "baseline:monetary_policy")
    assert len(runs) == 1
    assert runs[0]["mode"] == "forecast" and runs[0]["success"] == 1
    assert uitkomst.is_complete


def test_tweede_ronde_in_dezelfde_week_schrijft_niets(tmp_path):
    conn = _gevulde_db(tmp_path)
    run_baseline_round(conn, "monetary_policy", [_doel()], MAANDAG, event_id="2026-W41", ridge=False)

    with pytest.raises(AlreadyProcessedError):
        run_baseline_round(conn, "monetary_policy", [_doel()], MAANDAG + timedelta(days=1), event_id="2026-W41", ridge=False)

    assert len(list_predictions(conn)) == 2


def test_een_mislukte_run_regel_rolt_de_voorspellingen_terug(tmp_path, monkeypatch):
    """Het regressiegeval van de atomiciteit. Zonder één transactie staan de
    voorspellingen er wél en de run-regel niet: de herhaling van morgen
    schrijft ze een tweede keer, en de week telt dubbel mee in het track
    record."""
    import storage.schema as schema

    conn = _gevulde_db(tmp_path)

    def stuk(*a, **kw):
        raise RuntimeError("schijf vol")

    monkeypatch.setattr(schema, "_insert_agent_run", stuk)

    with pytest.raises(RuntimeError):
        run_baseline_round(conn, "monetary_policy", [_doel()], MAANDAG, event_id="2026-W41", ridge=False)

    assert list_predictions(conn) == []


def test_baselines_worden_door_de_resolver_gescoord(tmp_path):
    """Het bewijs dat het contract past: geen aparte evaluatiepijplijn. De
    resolver wikkelt baseline-voorspellingen af zoals elke andere."""
    conn = _gevulde_db(tmp_path)
    run_baseline_round(conn, "monetary_policy", [_doel(horizons=(5,))], MAANDAG, event_id="2026-W41", ridge=False)
    _reeks(conn, "x", [101.0], laatste=MAANDAG + timedelta(days=8))

    resultaat = resolve_due_predictions(conn, now=MAANDAG + timedelta(days=9))

    assert resultaat.resolved == 2
    evaluaties = list_evaluations(conn, status="resolved")
    assert len(evaluaties) == 2
    assert all(e["pinball_mean"] is not None and e["crps"] is not None for e in evaluaties)


def test_aantal_baseline_voorspellingen_per_ronde_is_vastgepind():
    """55 kwantieldoelen per baseline (57 minus de twee FEDFUNDS-doelen), dus
    110 baseline-voorspellingen per wekelijkse ronde bij volledige historie.
    Verandert dit getal, dan verandert de steekproef waartegen de agents
    gemeten worden -- bewust, niet per ongeluk."""
    from runtime.daily import default_agents

    kwantiel = sum(
        len(t.horizons)
        for spec in default_agents()
        for t in spec.forecast_targets
        if t.kind is PredictionKind.QUANTILE
    )
    assert kwantiel == 55
    assert 2 * kwantiel == 110
