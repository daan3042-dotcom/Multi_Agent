"""
test_ridge.py
Tests voor de derde baseline (roadmap 4.6), `src/scoring/ridge.py`.

DE BELANGRIJKSTE TESTS ZIJN DE TWEE MET GEPLANTE DATA. Er is geen echte
back-fill in deze omgeving, dus of het model 'goed' fit is hier niet te
zeggen. Wat WEL kan: data bouwen waarvan de waarheid bekend is.
- Planten we een verband (de toekomst hangt met coëfficiënt 2 van een
  feature af), dan moet het model dat vinden -- anders is de machinerie stuk.
- Geven we alleen ruis, dan mag het model NIET slechter zijn dan 'geen
  verandering' -- anders is de baseline een risico voor elke vergelijking.
Beide samen zeggen: de code doet wat hij hoort te doen. Ze zeggen niets over
of de echte inputs voorspellend zijn; dat is precies wat de forward-test
moet uitwijzen.
"""

from __future__ import annotations

import math
import random
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from agents.base import ForecastTarget
from contract.output_contract import Claim, Confidence, DomainOutput, Mode
from contract.prediction import HorizonKind, PredictionKind
from contract.resolution import Observation, ResolutionMethod
from scoring.baseline_round import run_baseline_round
from scoring.baselines import CLIMATOLOGY, PERSISTENCE
from scoring.ridge import (
    LAMBDA_GRID,
    RIDGE,
    FeatureSeries,
    fit_ridge,
    fit_ridge_model,
    freeze_ridge_model,
    infer_cadence,
    ridge_predictions,
    solve_linear,
)
from storage.schema import init_db, list_predictions, save_baseline_model, save_domain_output

VRIJDAG = datetime(2026, 10, 2, tzinfo=timezone.utc)
MAANDAG = datetime(2026, 10, 5, 7, 15, tzinfo=timezone.utc)
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _db(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def _reeks(conn, key, waarden, laatste=VRIJDAG, domain="d", stap=1):
    n = len(waarden)
    claims = []
    for i, w in enumerate(waarden):
        dag = laatste - timedelta(days=(n - 1 - i) * stap)
        claims.append(Claim(
            domain=domain, claim=key, value=float(w), source="test",
            confidence=Confidence.HIGH, analysis_time=dag, source_time=dag, metric_key=key,
        ))
    save_domain_output(conn, DomainOutput(
        domain=domain, mode=Mode.MONITORING, generated_at=claims[0].analysis_time, claims=claims,
    ))


def _doel(metric_key="x", horizons=(1,)) -> ForecastTarget:
    return ForecastTarget(
        metric_key=metric_key, kind=PredictionKind.QUANTILE,
        horizon_kind=HorizonKind.TRADING_DAYS, horizons=horizons,
        resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER,
        resolution_rule="x op of na resolves_at ({horizon_n} handelsdagen)",
    )


def _geplant(n=600, coefficient=2.0, seed=7):
    """x_{t+1} = x_t + coefficient * f_{t-1} + ruis, met f i.i.d. N(0,1).

    Het verband loopt via f_{t-1} en niet f_t: het model mag een daglijkse
    waarneming pas de dag erna gebruiken (publicatievertraging), dus alleen
    f_{t-1} is op tijdstip t bekend."""
    rng = random.Random(seed)
    f = [rng.gauss(0, 1) for _ in range(n)]
    x = [100.0]
    for i in range(n - 1):
        x.append(x[-1] + coefficient * (f[i - 1] if i >= 1 else 0.0) + 0.1 * rng.gauss(0, 1))
    return x, f


# --------------------------------------------------------------------------
# De rekenkern
# --------------------------------------------------------------------------


def test_lineair_stelsel_met_de_hand():
    """2x + y = 5 en x + 3y = 10 hebben x=1, y=3 als oplossing."""
    assert solve_linear([[2.0, 1.0], [1.0, 3.0]], [5.0, 10.0]) == pytest.approx([1.0, 3.0])


def test_singuliere_matrix_faalt_hard():
    with pytest.raises(ValueError):
        solve_linear([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0])


def test_ridge_vindt_een_exact_lineair_verband_terug():
    rng = random.Random(1)
    x = [[rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(400)]
    y = [3.0 + 2.0 * a - 1.0 * b for a, b in x]
    intercept, beta = fit_ridge(x, y, lam=1e-9)
    assert intercept == pytest.approx(3.0, abs=1e-6)
    assert beta == pytest.approx([2.0, -1.0], abs=1e-6)


def test_grote_lambda_krimpt_de_coefficienten():
    rng = random.Random(2)
    x = [[rng.gauss(0, 1)] for _ in range(300)]
    y = [2.0 * a for (a,) in x]
    _, klein = fit_ridge(x, y, lam=0.01)
    _, groot = fit_ridge(x, y, lam=100.0)
    assert abs(groot[0]) < 0.05 < abs(klein[0])


def test_lambda_betekent_hetzelfde_bij_meer_rijen():
    """De penalty staat op X'X/n en niet op X'X. Verdubbel je exact dezelfde
    data, dan moet er dezelfde fit uitkomen -- anders is het raster niet
    te vergelijken over doelen met 200 en met 5000 rijen."""
    rng = random.Random(3)
    x = [[rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(150)]
    y = [a + 0.5 * b + rng.gauss(0, 0.3) for a, b in x]
    een = fit_ridge(x, y, lam=1.0)
    twee = fit_ridge(x + x, y + y, lam=1.0)
    assert een[0] == pytest.approx(twee[0]) and een[1] == pytest.approx(twee[1])


# --------------------------------------------------------------------------
# Cadans en z-scores
# --------------------------------------------------------------------------


def _obs(waarden, stap=1, start=START):
    return [
        Observation(source_time=start + timedelta(days=i * stap), value=float(w), first_seen=start, claim_id=i)
        for i, w in enumerate(waarden)
    ]


def test_cadans_wordt_uit_de_reeks_afgeleid():
    def tijden(stap, n=10):
        return [START + timedelta(days=i * stap) for i in range(n)]

    assert infer_cadence(tijden(1)) == "daily"
    assert infer_cadence(tijden(7)) == "weekly"
    assert infer_cadence(tijden(31)) == "monthly"
    assert infer_cadence(tijden(91)) is None  # kwartaal: geen geraden vertraging
    assert infer_cadence(tijden(1, n=2)) is None


def test_weekenden_maken_van_een_dagreeks_geen_weekreeks():
    dagen = [START + timedelta(days=d) for d in range(60) if (START + timedelta(days=d)).weekday() < 5]
    assert infer_cadence(dagen) == "daily"


def test_z_score_met_de_hand_nagerekend():
    """Waarden 1..40. Op het moment dat de laatste bekend is: gemiddelde
    20,5, variantie (40^2-1)/12, dus z = (40-20,5)/sqrt(133,25)."""
    reeks = FeatureSeries("k", _obs(range(1, 41)))
    laatste = START + timedelta(days=39)
    z = reeks.z_at(laatste + timedelta(days=1))  # vertraging daily = 1 dag
    assert z == pytest.approx((40 - 20.5) / math.sqrt((40 ** 2 - 1) / 12))


def test_een_waarneming_is_pas_bekend_na_de_publicatievertraging():
    """Regressiegeval voor het lek dat dit hele ontwerp moet dichten. Op het
    tijdstip van de laatste waarneming zelf is die nog NIET bekend; de
    voorlaatste wel."""
    reeks = FeatureSeries("k", _obs(range(1, 41)))
    laatste = START + timedelta(days=39)
    z = reeks.z_at(laatste)  # de laatste is pas een dag later bekend
    assert z == pytest.approx((39 - 20.0) / math.sqrt((39 ** 2 - 1) / 12))


def test_maandreeks_gebruikt_zijn_lange_vertraging():
    """Een maandcijfer is ~5 weken na zijn referentiedatum bekend. Twintig
    dagen na de laatste waarneming is die er dus nog niet."""
    reeks = FeatureSeries("k", _obs(range(1, 41), stap=31))
    laatste = START + timedelta(days=39 * 31)
    voor = reeks.z_at(laatste + timedelta(days=20))
    na = reeks.z_at(laatste + timedelta(days=60))
    assert voor == pytest.approx((39 - 20.0) / math.sqrt((39 ** 2 - 1) / 12))
    assert na == pytest.approx((40 - 20.5) / math.sqrt((40 ** 2 - 1) / 12))


def test_verouderde_waarneming_telt_als_ontbrekend():
    reeks = FeatureSeries("k", _obs(range(1, 41)))
    assert reeks.z_at(START + timedelta(days=39 + 200)) is None


def test_te_weinig_historie_geeft_geen_z_score():
    assert FeatureSeries("k", _obs(range(1, 20))).z_at(START + timedelta(days=100)) is None


def test_extreme_z_wordt_afgekapt():
    """Een eenheidswijziging of glitch (WALCL bleek op 28-09 in miljoenen te
    staan) geeft anders een z van tientallen, en een lineair model
    extrapoleert die gedwee."""
    reeks = FeatureSeries("k", _obs([0.0] * 40 + [1000.0]))
    assert reeks.z_at(START + timedelta(days=41)) == 5.0


def test_constante_reeks_geeft_z_nul_en_geen_deling_door_nul():
    assert FeatureSeries("k", _obs([3.0] * 40)).z_at(START + timedelta(days=41)) == 0.0


# --------------------------------------------------------------------------
# Fitten met geplante data
# --------------------------------------------------------------------------


def _geplante_db(tmp_path, **kw):
    conn = _db(tmp_path)
    x, f = _geplant(**kw)
    _reeks(conn, "x", x)
    _reeks(conn, "f", f)
    return conn


def test_model_vindt_het_geplante_verband(tmp_path):
    conn = _geplante_db(tmp_path)

    fit = fit_ridge_model(conn, "d", _doel(), 1, MAANDAG)

    model = fit.model
    coef = dict(zip(model["features"], model["coefficients"]))
    assert model["features"] == ["f", "x"]  # alfabetisch, dus reproduceerbaar
    assert coef["f"] == pytest.approx(2.0, abs=0.3)
    assert abs(coef["x"]) < 0.3
    assert fit.mse_oos < 0.3 * fit.mse_random_walk
    assert model["lambda"] in LAMBDA_GRID
    assert model["resid_q"][0] <= model["resid_q"][1] <= model["resid_q"][2]
    assert model["n_oos"] > 100


def test_model_kan_een_nog_niet_gepubliceerde_waarde_niet_gebruiken(tmp_path):
    """DE LEK-TEST. Hier hangt de toekomst van x af van f_t: de waarde van
    DEZELFDE dag, die op dat moment nog niet gepubliceerd is (vertraging
    één dag). Een model dat die relatie vindt, kijkt in de toekomst -- en
    dat is onzichtbaar in de scores, want ze zien er alleen beter uit.

    Het model hoort hier NIETS te vinden: coëfficiënt ~0 en geen winst t.o.v.
    'geen verandering'. Bewezen door dezelfde data met de vertraging op nul
    te zetten: dan vindt het model 'm wél (zie de mutatiecontrole in de
    commit)."""
    conn = _db(tmp_path)
    rng = random.Random(9)
    f = [rng.gauss(0, 1) for _ in range(600)]
    x = [100.0]
    for i in range(599):
        x.append(x[-1] + 2.0 * f[i] + 0.1 * rng.gauss(0, 1))  # f_t, niet f_{t-1}
    _reeks(conn, "x", x)
    _reeks(conn, "f", f)

    fit = fit_ridge_model(conn, "d", _doel(), 1, MAANDAG)

    coef = dict(zip(fit.model["features"], fit.model["coefficients"]))
    assert abs(coef["f"]) < 0.3
    assert fit.mse_oos > 0.9 * fit.mse_random_walk


def test_model_is_niet_slechter_dan_geen_verandering_op_pure_ruis(tmp_path):
    """De tweede geplante test: geen verband. Een baseline die op ruis
    slechter is dan 'niets doen' zou elke vergelijking vertekenen, en dat is
    precies waar cross-validatie voor de regularisatie voor is."""
    conn = _db(tmp_path)
    rng = random.Random(11)
    x = [100.0]
    for _ in range(599):
        x.append(x[-1] + rng.gauss(0, 1))
    _reeks(conn, "x", x)
    _reeks(conn, "f", [rng.gauss(0, 1) for _ in range(600)])

    fit = fit_ridge_model(conn, "d", _doel(), 1, MAANDAG)

    assert fit.mse_oos <= 1.10 * fit.mse_random_walk


def test_feature_met_te_korte_historie_wordt_weggelaten_en_genoteerd(tmp_path):
    conn = _geplante_db(tmp_path)
    _reeks(conn, "kort", [float(i) for i in range(50)])

    model = fit_ridge_model(conn, "d", _doel(), 1, MAANDAG).model

    assert "kort" not in model["features"]
    assert any(d.startswith("kort") for d in model["dropped"])


def test_te_weinig_rijen_geeft_een_probleem(tmp_path):
    from scoring.baselines import _Insufficient

    conn = _db(tmp_path)
    _reeks(conn, "x", [100.0 + (i % 7) for i in range(60)])
    with pytest.raises(_Insufficient):
        fit_ridge_model(conn, "d", _doel(), 1, MAANDAG)


def test_fit_kijkt_niet_in_de_toekomst(tmp_path):
    """Point-in-time, zoals bij de andere baselines: data van na `as_of` mag
    het model niet veranderen. Wat de pseudo-OOS-run (4.4) nodig heeft."""
    conn = _geplante_db(tmp_path)
    voor = fit_ridge_model(conn, "d", _doel(), 1, MAANDAG - timedelta(days=100)).model

    _reeks(conn, "x", [9999.0], laatste=MAANDAG - timedelta(days=10))
    _reeks(conn, "f", [9999.0], laatste=MAANDAG - timedelta(days=10))
    na = fit_ridge_model(conn, "d", _doel(), 1, MAANDAG - timedelta(days=100)).model

    assert voor == na


# --------------------------------------------------------------------------
# Bevriezen
# --------------------------------------------------------------------------


def test_een_model_wordt_maar_een_keer_bevroren(tmp_path):
    """'Gefit op de back-fill en daarna bevroren.' Opnieuw fitten onder
    dezelfde specversie moet botsen: een verschoven baseline is een
    verschoven meetlat."""
    conn = _geplante_db(tmp_path)
    fit = fit_ridge_model(conn, "d", _doel(), 1, MAANDAG)
    freeze_ridge_model(conn, "d", _doel(), 1, fit, MAANDAG, MAANDAG)

    with pytest.raises(sqlite3.IntegrityError):
        freeze_ridge_model(conn, "d", _doel(), 1, fit, MAANDAG, MAANDAG)


# --------------------------------------------------------------------------
# Voorspellen
# --------------------------------------------------------------------------


def _bevroren(tmp_path):
    conn = _geplante_db(tmp_path)
    fit = fit_ridge_model(conn, "d", _doel(), 1, MAANDAG)
    freeze_ridge_model(conn, "d", _doel(), 1, fit, MAANDAG, MAANDAG)
    return conn, fit


def test_voorspelling_volgt_het_geplante_verband(tmp_path):
    """De laatste x is het anker; het verband zegt +2 * f_{t-1}. Ruimte voor
    de schattingsfout in de coëfficiënt (±0,3 bij |f| tot ~3)."""
    conn, fit = _bevroren(tmp_path)
    x, f = _geplant()

    uitkomst = ridge_predictions(conn, "d", [_doel()], MAANDAG)

    assert uitkomst.issues == ()
    (p,) = uitkomst.predictions
    verwacht = x[-1] + 2.0 * f[-2]
    assert p.q50 == pytest.approx(verwacht, abs=1.0)
    assert p.q10 < p.q50 < p.q90
    assert p.agent == RIDGE
    assert p.model_id == "deterministic"
    assert "lambda=" in p.note and "rijen" in p.note


def test_zonder_bevroren_model_een_melding_en_geen_voorspelling(tmp_path):
    """Een melding per domein, niet per doel: het is één oorzaak (er is nog
    niet gefit), en 55 regels in een telefoonmelding worden niet gelezen."""
    conn = _geplante_db(tmp_path)

    uitkomst = ridge_predictions(conn, "d", [_doel(horizons=(1, 5, 21))], MAANDAG)

    assert uitkomst.predictions == ()
    assert len(uitkomst.issues) == 1
    assert "geen enkel bevroren" in uitkomst.issues[0]


def test_ontbrekende_input_bij_gebruik_is_een_probleem(tmp_path):
    """Het model is bevroren met input `f`. Ontbreekt die in de live data,
    dan mag er niets uitkomen -- ook geen voorspelling zonder die input."""
    conn, fit = _bevroren(tmp_path)
    schoon = _db(tmp_path / "leeg") if False else init_db(":memory:")
    x, _ = _geplant()
    _reeks(schoon, "x", x)  # wel het doel, niet de input f
    save_baseline_model(
        schoon, "ridge", "v1", "d", "x", 1, MAANDAG, MAANDAG, fit.model["n_rows"], fit.model
    )

    uitkomst = ridge_predictions(schoon, "d", [_doel()], MAANDAG)

    assert uitkomst.predictions == ()
    assert "ridge-input f niet beschikbaar" in uitkomst.issues[0]


def test_fomc_doelen_worden_door_ridge_genegeerd(tmp_path):
    from agents import monetary_policy_agent

    conn = _geplante_db(tmp_path)
    fomc = [t for t in monetary_policy_agent.FORECAST_TARGETS if t.metric_key == "fed_funds_rate"]
    uitkomst = ridge_predictions(conn, "d", fomc, MAANDAG)
    assert uitkomst.predictions == () and uitkomst.issues == ()


def test_de_ronde_schrijft_alle_drie_de_baselines(tmp_path):
    conn, _ = _bevroren(tmp_path)

    resultaat = run_baseline_round(conn, "d", [_doel()], MAANDAG, event_id="2026-W41")

    assert resultaat.is_complete
    assert sorted(p.agent for p in list_predictions(conn)) == [CLIMATOLOGY, PERSISTENCE, RIDGE]


# --------------------------------------------------------------------------
# Nooit slechter dan 'geen verandering' (droge run op echte data, 29-09)
#
# De eerste droge run op de VPS gaf bij een aantal doelen een oos/rw BOVEN 1
# (gbp_usd h=63: 1,175). Oorzaken: een geschatte trend (intercept) die uit-de-
# steekproef niet klopt, en een lambda-raster dat bij 100 stopte terwijl de CV
# bijna overal die bovengrens koos. Bevriezen zou een baseline hebben vastgelegd
# die verliest van niets doen.
# --------------------------------------------------------------------------


def _random_walk_db(tmp_path, stappen):
    conn = _db(tmp_path)
    waarden = [100.0]
    for s in stappen:
        waarden.append(waarden[-1] + s)
    _reeks(conn, "x", waarden)
    rng = random.Random(3)
    _reeks(conn, "f", [rng.gauss(0, 1) for _ in range(len(waarden))])
    return conn


@pytest.mark.parametrize("seed", range(6))
def test_model_is_nooit_slechter_dan_geen_verandering(tmp_path, seed):
    """De eigenschap zelf, over meerdere soorten reeksen: een trend die van
    regime wisselt (de valuta-situatie), pure ruis, en een stabiele trend. De
    cross-validatie kiest uit een raster dat het 'niets doen'-model bevat, dus
    het resultaat kan dat model niet met meer dan afrondingsverschil verliezen."""
    rng = random.Random(seed)
    n = 700
    soorten = [
        [rng.gauss(0, 1) + (0.5 if i < n // 2 else -0.5) for i in range(n)],   # trend wisselt van teken
        [rng.gauss(0, 1) for _ in range(n)],                                    # ruis zonder trend
        [rng.gauss(0, 1) + 0.3 for _ in range(n)],                              # stabiele trend
    ]
    for stappen in soorten:
        conn = _random_walk_db(tmp_path / f"s{seed}_{id(stappen)}", stappen)
        fit = fit_ridge_model(conn, "d", _doel(), 5, MAANDAG)
        assert fit.mse_oos <= fit.mse_random_walk * 1.0005, (
            f"oos/rw = {fit.mse_oos / fit.mse_random_walk:.4f}: het model verliest van 'geen verandering'"
        )


def test_een_stabiele_trend_wordt_wel_meegenomen(tmp_path):
    """De keerzijde. Banen en prijzen hebben een echte, stabiele trend, en daar
    is 'geen verandering' een strohalm. Het model moet dan ruim winnen. Of dat via
    de drift-vlag gaat of via de z-score van de eigen (stijgende) reeks, dat de
    trend zelf al draagt, maakt niet uit: het resultaat telt, niet de route."""
    rng = random.Random(4)
    conn = _random_walk_db(tmp_path, [1.0 + 0.3 * rng.gauss(0, 1) for _ in range(600)])

    fit = fit_ridge_model(conn, "d", _doel(), 1, MAANDAG)

    assert fit.mse_oos < 0.3 * fit.mse_random_walk


def test_op_ruis_claimt_het_model_geen_echte_winst(tmp_path):
    """Zonder enig signaal mag het model niet verliezen (bovengrens) en hoort het
    ook niet veel te winnen (ondergrens).

    Dat het model iets onder 1,0 uitkomt (hier ~0,98) is winst uit TOEVAL: de
    cross-validatie kiest uit 14 combinaties van drift en lambda en pakt dus de
    toevallig beste (winner's curse). Consequentie voor het lezen van de echte
    uitvoer: een oos/rw van 0,98 is GEEN bewijs van voorspelkracht. Echte
    structuur zie je aan duidelijk lagere waarden (VIX h=63: 0,884)."""
    rng = random.Random(5)
    conn = _random_walk_db(tmp_path, [rng.gauss(0, 1) for _ in range(600)])

    fit = fit_ridge_model(conn, "d", _doel(), 5, MAANDAG)

    verhouding = fit.mse_oos / fit.mse_random_walk
    assert 0.95 <= verhouding <= 1.0005


def test_het_raster_bevat_het_nulmodel():
    """Het eerste raster stopte bij 100 en de CV koos bijna overal die grens: dat
    is het teken van een te klein raster. Bij lambda = 10.000 zijn alle
    coefficienten praktisch nul."""
    assert max(LAMBDA_GRID) >= 10_000


def test_fit_zonder_drift_heeft_geen_intercept():
    rng = random.Random(6)
    x = [[rng.gauss(0, 1)] for _ in range(200)]
    y = [5.0 + 2.0 * a for (a,) in x]
    intercept, _ = fit_ridge(x, y, lam=1e-9, drift=False)
    assert intercept == 0.0
