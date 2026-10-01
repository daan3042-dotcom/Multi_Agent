"""
test_trigger_version.py
Tests voor de trigger-versioning (roadmap 1.5, T₀-blokkade, 29-09-2026):
`contract/trigger_version.py` en `runtime/trigger_guard.py`.

WAT HIER OP HET SPEL STAAT. Kalibratie en scoring gaan over "hoe vaak vuurde
deze regel, en wat volgde erop". Verschuift een drempel zonder dat dat ergens
staat, dan staan twee verschillende regels onder één label -- en dat merk je
pas maanden later, wanneer er niets meer aan te doen valt. Deze tests zorgen
dat het versienummer niet met de hand hoeft te worden bijgehouden.

De eerste testgroep is de waakhond zelf (zelfde patroon als
test_forecast_prompt_version.py). De rest bewijst dat de waakhond echt reageert
op wat hij moet bewaken (mutatie-achtige controles) en NIET op wat hij moet
negeren (labels).

ALS `test_regels_zijn_ongewijzigd_of_versie_is_opgehoogd` FAALT: dat is geen
bug in de test. Een drempel, ouderdomsgrens of trigger-gedrag is veranderd.
Verhoog TRIGGER_VERSION in src/contract/trigger_version.py, voeg de nieuwe
vingerafdruk toe aan TRIGGER_FINGERPRINTS en beschrijf de wijziging in
docs/roadmap.md.
"""

from __future__ import annotations

import importlib.util
import logging
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import contract.trigger_version as tv
import runtime.trigger_guard as guard
from agents import sector_agent
from calibration.trigger_calibration import metric_registry
from contract.prediction import HorizonKind, Prediction, PredictionKind
from contract.resolution import ResolutionMethod
from storage.schema import (
    _migreer_trigger_events_versie,
    init_db,
    list_predictions,
    record_trigger_event,
    save_prediction,
)

ROOT = Path(__file__).resolve().parent.parent
NU = datetime(2026, 10, 5, 7, 15, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# De waakhond
# --------------------------------------------------------------------------


def test_regels_zijn_ongewijzigd_of_versie_is_opgehoogd():
    verwacht = tv.TRIGGER_FINGERPRINTS.get(tv.TRIGGER_VERSION)
    assert verwacht is not None, f"geen vingerafdruk vastgelegd voor {tv.TRIGGER_VERSION}"
    werkelijk = guard.trigger_fingerprint()
    assert werkelijk == verwacht, (
        f"De trigger-regels zijn gewijzigd (vingerafdruk {werkelijk}, verwacht {verwacht} "
        f"voor {tv.TRIGGER_VERSION}) zonder dat de versie omhoog ging. Verhoog "
        f"TRIGGER_VERSION in src/contract/trigger_version.py en voeg '{werkelijk}' toe aan "
        f"TRIGGER_FINGERPRINTS."
    )


def test_de_vingerafdruk_is_stabiel_tussen_aanroepen():
    assert guard.trigger_fingerprint() == guard.trigger_fingerprint()


def test_elke_versie_heeft_een_eigen_vingerafdruk():
    """Twee versies met dezelfde vingerafdruk zijn dezelfde regels, en dan is
    de tweede versie een lege wijziging die het cohort onnodig opdeelt."""
    afdrukken = list(tv.TRIGGER_FINGERPRINTS.values())
    assert len(afdrukken) == len(set(afdrukken))


def test_de_huidige_versie_staat_in_de_registratie():
    assert tv.TRIGGER_VERSION in tv.TRIGGER_FINGERPRINTS


# --------------------------------------------------------------------------
# Reageert de vingerafdruk op wat hij moet bewaken?
# --------------------------------------------------------------------------


def test_een_andere_tolerance_verandert_de_vingerafdruk(monkeypatch):
    voor = guard.trigger_fingerprint()
    spec = sector_agent.METRIC_SPECS["xlk_technology"]
    monkeypatch.setitem(
        sector_agent.METRIC_SPECS, "xlk_technology", replace(spec, tolerance=spec.tolerance + 0.5)
    )
    assert guard.trigger_fingerprint() != voor


def test_een_andere_severity_verandert_de_vingerafdruk(monkeypatch):
    voor = guard.trigger_fingerprint()
    spec = sector_agent.METRIC_SPECS["xlk_technology"]
    monkeypatch.setitem(
        sector_agent.METRIC_SPECS, "xlk_technology", replace(spec, severity="high")
    )
    assert guard.trigger_fingerprint() != voor


def test_een_andere_ouderdomsgrens_verandert_de_vingerafdruk(monkeypatch):
    voor = guard.trigger_fingerprint()
    monkeypatch.setattr(sector_agent, "MAX_AGE", sector_agent.MAX_AGE + timedelta(days=1))
    assert guard.trigger_fingerprint() != voor


def test_een_extra_reeks_verandert_de_vingerafdruk(monkeypatch):
    voor = guard.trigger_fingerprint()
    spec = sector_agent.METRIC_SPECS["xlk_technology"]
    monkeypatch.setitem(sector_agent.METRIC_SPECS, "nieuwe_reeks", spec)
    assert guard.trigger_fingerprint() != voor


def test_een_ander_label_of_een_andere_reden_verandert_de_vingerafdruk_niet(monkeypatch):
    """Een gecorrigeerde schrijfwijze is geen andere regel."""
    voor = guard.trigger_fingerprint()
    spec = sector_agent.METRIC_SPECS["xlk_technology"]
    monkeypatch.setitem(
        sector_agent.METRIC_SPECS, "xlk_technology",
        replace(spec, label="Een compleet ander label", reason="Andere tekst"),
    )
    assert guard.trigger_fingerprint() == voor


def test_de_volgorde_van_reeksen_doet_er_niet_toe(monkeypatch):
    voor = guard.trigger_fingerprint()
    omgekeerd = dict(reversed(list(sector_agent.METRIC_SPECS.items())))
    monkeypatch.setattr(sector_agent, "METRIC_SPECS", omgekeerd)
    assert guard.trigger_fingerprint() == voor


@pytest.mark.parametrize(
    "functie, verlegd",
    [
        # Elk hiervan is een regel IN de trigger-laag, niet in de configuratie.
        # Een grens die daar verschuift moet de vingerafdruk raken.
        ("evaluate_surprise", "strikt-groter-dan-wordt-groter-of-gelijk"),
        ("evaluate_completeness_result", "high-vanaf-40-procent"),
        ("evaluate_staleness", "stale-vanaf-de-grens-zelf"),
    ],
)
def test_een_verlegde_grens_in_de_trigger_laag_verandert_de_vingerafdruk(monkeypatch, functie, verlegd):
    """Mutatiecontrole: verander het gedrag en de vingerafdruk moet mee."""
    voor = guard.trigger_fingerprint()

    if functie == "evaluate_surprise":
        origineel = guard.evaluate_surprise

        def gemuteerd(domain, metric_key, observed_value, expected_value, tolerance, *a, **kw):
            # >= in plaats van >: een afwijking exact gelijk aan de tolerantie vuurt nu.
            return origineel(domain, metric_key, observed_value, expected_value, tolerance - 1e-9, *a, **kw)

        monkeypatch.setattr(guard, "evaluate_surprise", gemuteerd)
    elif functie == "evaluate_completeness_result":
        origineel = guard.evaluate_completeness_result

        def gemuteerd(domain, result, now=None):
            trigger = origineel(domain, result, now=now)
            if trigger is None:
                return None
            aandeel = len(result.missing_metric_keys) / len(result.expected_metric_keys)
            return replace(trigger, severity="high" if aandeel >= 0.4 else "medium")

        monkeypatch.setattr(guard, "evaluate_completeness_result", gemuteerd)
    else:
        origineel = guard.evaluate_staleness

        def gemuteerd(source, last_success_at, max_age, now=None, last_failure_detail=None):
            return origineel(source, last_success_at, max_age - timedelta(seconds=1), now=now)

        monkeypatch.setattr(guard, "evaluate_staleness", gemuteerd)

    assert guard.trigger_fingerprint() != voor, verlegd


# --------------------------------------------------------------------------
# Opslag: elke trigger krijgt zijn versie
# --------------------------------------------------------------------------


def test_een_opgeslagen_trigger_draagt_de_huidige_versie(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    record_trigger_event(conn, "sector", NU, "reden", "medium", metric_key="xlk_technology")

    versie = conn.execute("SELECT trigger_version FROM trigger_events").fetchone()[0]
    assert versie == tv.TRIGGER_VERSION


def test_de_versie_volgt_de_code_en_hoeft_niet_te_worden_doorgegeven(tmp_path, monkeypatch):
    conn = init_db(str(tmp_path / "t.db"))
    monkeypatch.setattr("storage.schema.current_trigger_version", lambda: "v9")
    record_trigger_event(conn, "sector", NU, "reden", "medium")

    assert conn.execute("SELECT trigger_version FROM trigger_events").fetchone()[0] == "v9"


def test_expliciet_none_blijft_none(tmp_path):
    """Voor een trigger waarvan de versie echt onbekend is. Het verschil met
    'niet meegegeven' is precies waarom de default een sentinel is."""
    conn = init_db(str(tmp_path / "t.db"))
    record_trigger_event(conn, "sector", NU, "reden", "medium", trigger_version=None)

    assert conn.execute("SELECT trigger_version FROM trigger_events").fetchone()[0] is None


def test_een_dagelijkse_run_stempelt_de_triggers_die_hij_opslaat(tmp_path):
    """Regressie op het pad dat er echt toe doet: `_persist_triggers` in de
    dagelijkse cyclus, niet alleen de losse insert-functie."""
    from runtime.daily import AgentSpec, run_daily
    from triggers.trigger_engine import TriggerEvent

    conn = init_db(str(tmp_path / "t.db"))

    def monitor(conn_, now=None, event_id=None):
        return None, [TriggerEvent(domain="fake", triggered_at=NU, reason="test", severity="medium")]

    run_daily(conn, agents=[AgentSpec("fake", monitor)], now=NU, notifier=lambda n: None)

    versies = [r[0] for r in conn.execute("SELECT trigger_version FROM trigger_events WHERE domain='fake'")]
    assert versies, "de trigger is niet opgeslagen"
    assert set(versies) == {tv.TRIGGER_VERSION}


# --------------------------------------------------------------------------
# Migratie van een bestaande database
# --------------------------------------------------------------------------

_OUDE_TABEL = """
CREATE TABLE trigger_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    triggered_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    metric_key TEXT,
    observed_value_json TEXT,
    threshold_json TEXT,
    dispatch_batch_id TEXT,
    resolved INTEGER NOT NULL DEFAULT 0
);
"""


def test_migratie_voegt_de_kolom_toe_en_laat_oude_rijen_op_null(tmp_path):
    """De VPS heeft de tabel al, zonder kolom. Zonder migratie zou elke
    trigger-insert daar falen. Oude rijen blijven NULL: ze zijn gemaakt met
    drempels die inmiddels veranderd zijn, dus 'v0' zou te veel beloven."""
    pad = str(tmp_path / "oud.db")
    conn = sqlite3.connect(pad)
    conn.executescript(_OUDE_TABEL)
    conn.execute(
        "INSERT INTO trigger_events (domain, triggered_at, reason, severity) VALUES "
        "('sector', '2026-09-28T07:15:00+00:00', 'oude trigger', 'medium')"
    )
    conn.commit()
    conn.close()

    conn = init_db(pad)  # de echte opstartroute, zoals run_daily.py hem neemt
    record_trigger_event(conn, "sector", NU, "nieuwe trigger", "medium")

    rijen = dict(conn.execute("SELECT reason, trigger_version FROM trigger_events"))
    assert rijen["oude trigger"] is None
    assert rijen["nieuwe trigger"] == tv.TRIGGER_VERSION


def test_migratie_is_idempotent(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    assert _migreer_trigger_events_versie(conn) is False  # kolom bestaat al
    conn2 = sqlite3.connect(str(tmp_path / "oud.db"))
    conn2.executescript(_OUDE_TABEL)
    assert _migreer_trigger_events_versie(conn2) is True
    assert _migreer_trigger_events_versie(conn2) is False


# --------------------------------------------------------------------------
# Voorspellingen dragen de versie
# --------------------------------------------------------------------------


def _voorspelling(**kw) -> Prediction:
    basis = dict(
        agent="monetary_policy", domain="monetary_policy",
        target_metric_key="10y_treasury_yield",
        kind=PredictionKind.QUANTILE,
        horizon_kind=HorizonKind.TRADING_DAYS, horizon_n=5,
        created_at=NU, resolves_at=NU + timedelta(days=7),
        resolution_rule="regel", resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER,
        model_id="m", prompt_version="p", q10=1.0, q25=1.5, q50=2.0, q75=2.5, q90=3.0,
    )
    basis.update(kw)
    return Prediction(**basis)


def test_een_voorspelling_krijgt_de_versie_vanzelf(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    save_prediction(conn, _voorspelling())
    assert list_predictions(conn)[0].trigger_version == tv.TRIGGER_VERSION


def test_een_voorspelling_kan_bewust_een_andere_versie_krijgen():
    assert _voorspelling(trigger_version="v7").trigger_version == "v7"


def test_een_baseline_krijgt_dezelfde_versie_als_de_agents(tmp_path):
    """Een nieuwe voorspeller hoeft niets te doen -- zelfde afspraak als het
    cohort. Baselines gebruiken het contract, dus ze volgen vanzelf."""
    assert _voorspelling(agent="baseline:persistence").trigger_version == tv.TRIGGER_VERSION


# --------------------------------------------------------------------------
# De pin: het echte cohort draait alleen met de bevroren regelset
# --------------------------------------------------------------------------


def test_de_pin_doet_niets_buiten_het_echte_cohort(monkeypatch):
    monkeypatch.setattr(guard, "FROZEN_TRIGGER_VERSION", None)
    for cohort in ("dry_run", "pseudo_oos"):
        guard.check_trigger_pin(cohort)  # geen uitzondering


def test_zonder_freeze_weigert_het_echte_cohort(monkeypatch):
    monkeypatch.setattr(guard, "FROZEN_TRIGGER_VERSION", None)
    with pytest.raises(guard.TriggerPinError, match="geen freeze"):
        guard.check_trigger_pin("cohort_0")


def test_een_andere_versie_dan_de_freeze_weigert(monkeypatch):
    monkeypatch.setattr(guard, "FROZEN_TRIGGER_VERSION", "v0")
    monkeypatch.setattr(guard, "TRIGGER_VERSION", "v1")
    with pytest.raises(guard.TriggerPinError, match="nieuw cohort"):
        guard.check_trigger_pin("cohort_0")


def test_bevroren_versie_met_gewijzigde_regels_weigert(monkeypatch):
    """De situatie waar de pin voor bestaat: iemand past op de VPS een drempel
    aan zonder de versie te verhogen, en niemand draait daar pytest."""
    monkeypatch.setattr(guard, "FROZEN_TRIGGER_VERSION", tv.TRIGGER_VERSION)
    spec = sector_agent.METRIC_SPECS["xlk_technology"]
    monkeypatch.setitem(
        sector_agent.METRIC_SPECS, "xlk_technology", replace(spec, tolerance=spec.tolerance * 2)
    )
    with pytest.raises(guard.TriggerPinError, match="zonder nieuwe versie"):
        guard.check_trigger_pin("cohort_0")


def test_bevroren_versie_met_ongewijzigde_regels_mag(monkeypatch):
    monkeypatch.setattr(guard, "FROZEN_TRIGGER_VERSION", tv.TRIGGER_VERSION)
    guard.check_trigger_pin("cohort_0")  # geen uitzondering


def _run_daily_main():
    spec = importlib.util.spec_from_file_location("run_daily_cli", ROOT / "run_daily.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_daily_stopt_met_exit_twee_zonder_freeze_onder_cohort_0(tmp_path, monkeypatch):
    """Voor er iets gebeurt: geen database aangemaakt, geen agent gedraaid."""
    monkeypatch.setenv("MI_COHORT", "cohort_0")
    module = _run_daily_main()
    pad = tmp_path / "t.db"

    assert module.main(["--db", str(pad)]) == 2
    assert not pad.exists()


def test_run_daily_meldt_de_trigger_versie(tmp_path, monkeypatch, caplog):
    import runtime.daily as daily

    monkeypatch.setattr(daily, "default_agents", lambda: [])
    caplog.set_level(logging.INFO)
    _run_daily_main().main(["--db", str(tmp_path / "t.db")])

    assert f"Trigger-versie: {tv.TRIGGER_VERSION}" in caplog.text


def test_run_daily_draait_gewoon_onder_dry_run_zonder_freeze(tmp_path, monkeypatch):
    """De pin mag de dagelijkse ingestie vóór T₀ᵇ nooit in de weg zitten."""
    import runtime.daily as daily

    monkeypatch.setattr(daily, "default_agents", lambda: [])
    assert _run_daily_main().main(["--db", str(tmp_path / "t.db")]) == 0


# --------------------------------------------------------------------------
# Consistentie van de v1-set
# --------------------------------------------------------------------------


def test_dezelfde_reeks_heeft_in_elk_domein_dezelfde_drempel():
    """Regressie op een echte fout uit v0: `unemployment_rate` stond bij
    monetary op 0,3 en bij economic op 0,2 voor dezelfde publicatie, waardoor
    één UNRATE-print in het ene domein wel en in het andere geen trigger gaf
    (en de ene regel in drie jaar nooit vuurde)."""
    per_reeks: dict[str, set[float]] = {}
    for dom, key, spec in metric_registry():
        per_reeks.setdefault(key, set()).add(spec.tolerance)

    afwijkend = {key: waarden for key, waarden in per_reeks.items() if len(waarden) > 1}
    assert not afwijkend, f"zelfde reeks, verschillende drempels: {afwijkend}"


def test_geen_drempel_ligt_op_een_stap_van_een_stapreeks():
    """Reeksen die in stapjes bewegen krijgen een drempel HALVERWEGE twee
    stapjes. Een drempel precies op een stap is een loterij: 4,3 min 4,1 is in
    floats 0,2000000000000002 en vuurt dan wel of niet bij een drempel van 0,2."""
    stap = {"unemployment_rate": 0.1, "inflation_expectations_5y": 0.01,
            "inflation_expectations_10y": 0.01, "high_yield_credit_spread": 0.01,
            "yield_curve_10y_2y": 0.01, "financial_conditions_index": 0.001}
    for dom, key, spec in metric_registry():
        if key not in stap:
            continue
        aantal_stappen = spec.tolerance / stap[key]
        assert abs(aantal_stappen - round(aantal_stappen)) > 0.01, (
            f"{dom}.{key}: tolerance {spec.tolerance} ligt op een stap van {stap[key]}"
        )
