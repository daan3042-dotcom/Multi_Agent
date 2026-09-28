"""
test_prediction.py
Tests voor het voorspellingscontract (roadmap 4.1, fase 2) en de
predictions-tabel.

Patroon zoals de rest van tests/: per eis een "correct"-geval en een
regressiegeval. De regressiegevallen hier beschermen bijna allemaal
hetzelfde ding, want het is het enige dat er echt toe doet: een
voorspelling die achteraf niet meer fout kan blijken, is geen voorspelling.
"""

from datetime import datetime, timedelta, timezone

import pytest

from contract.graph import GRAPH_VERSION, Node
from contract.resolution import ResolutionMethod
from contract.prediction import (
    CONTRACT_VERSION,
    HorizonKind,
    Prediction,
    PredictionKind,
)
from storage.schema import init_db, list_due_predictions, list_predictions, save_prediction

NU = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
STRAKS = NU + timedelta(days=21)


def _kwantiel(**overrides) -> Prediction:
    basis = dict(
        agent="monetary_policy", domain="monetary_policy",
        target_metric_key="10y_treasury_yield",
        kind=PredictionKind.QUANTILE,
        horizon_kind=HorizonKind.TRADING_DAYS, horizon_n=21,
        created_at=NU, resolves_at=STRAKS,
        resolution_rule="eerste print van DGS10 op resolves_at + 3 dagen",
        resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER,
        model_id="claude-x", prompt_version="mp-v1",
        q10=3.9, q50=4.1, q90=4.4,
    )
    basis.update(overrides)
    return Prediction(**basis)


def _binair(**overrides) -> Prediction:
    basis = dict(
        agent="monetary_policy", domain="monetary_policy",
        target_metric_key="fed_funds_rate",
        kind=PredictionKind.BINARY,
        horizon_kind=HorizonKind.RELEASES, horizon_n=1,
        created_at=NU, resolves_at=STRAKS,
        resolution_rule="FOMC-besluit van 2026-10-28, target range vergeleken met de vorige",
        resolution_method=ResolutionMethod.DIRECTION_AFTER_FOMC,
        model_id="claude-x", prompt_version="mp-v1",
        probability=0.35, event_rule="FOMC verhoogt de target range op 2026-10-28",
    )
    basis.update(overrides)
    return Prediction(**basis)


# --- De twee geldige vormen ---


def test_kwantielvoorspelling_is_geldig():
    p = _kwantiel()
    assert p.kind is PredictionKind.QUANTILE
    assert (p.q10, p.q50, p.q90) == (3.9, 4.1, 4.4)
    assert p.cohort == "cohort_0"
    assert p.contract_version == CONTRACT_VERSION
    assert p.graph_version == GRAPH_VERSION


def test_binaire_voorspelling_is_geldig():
    p = _binair()
    assert p.probability == 0.35
    assert "FOMC" in p.event_rule


def test_prediction_is_onveranderlijk():
    """Frozen dataclass: achteraf bijstellen kan niet, ook niet per ongeluk."""
    p = _kwantiel()
    with pytest.raises(Exception):
        p.q50 = 9.9


# --- Wat er geweigerd wordt, en waarom dat het punt is ---


def test_zonder_resolution_rule_geweigerd():
    """REGRESSIE, en de belangrijkste van dit bestand. Zonder de regel
    waarmee hij gescoord wordt, volgt over zes maanden een discussie over
    wat de agent 'eigenlijk bedoelde' -- en dan is het track record
    waardeloos."""
    with pytest.raises(ValueError, match="resolution_rule"):
        _kwantiel(resolution_rule="")


def test_zonder_model_id_of_prompt_version_geweigerd():
    """Een modelwissel halverwege een cohort is anders niet te scheiden van
    een prestatieverandering (CLAUDE.md, covariaten)."""
    with pytest.raises(ValueError, match="model_id"):
        _kwantiel(model_id="")
    with pytest.raises(ValueError, match="prompt_version"):
        _kwantiel(prompt_version="")


def test_kwantielen_moeten_oplopen():
    with pytest.raises(ValueError, match="oplopen"):
        _kwantiel(q10=4.4, q50=4.1, q90=3.9)


def test_kwantielvorm_mag_geen_losse_kans_hebben():
    """REGRESSIE op correctie 2 van 27-09: richtings- en drempelkansen
    worden uit de kwantielen AFGELEID. Ze apart laten opgeven zou twee
    bronnen van waarheid opleveren die uit elkaar kunnen lopen."""
    with pytest.raises(ValueError, match="AFGELEID"):
        _kwantiel(probability=0.6)


def test_binaire_vorm_vereist_een_uitvoerbare_event_rule():
    with pytest.raises(ValueError, match="event_rule"):
        _binair(event_rule="")


def test_kans_buiten_0_1_geweigerd():
    with pytest.raises(ValueError, match="tussen 0 en 1"):
        _binair(probability=1.4)


def test_ontbrekende_kwantielen_geweigerd():
    with pytest.raises(ValueError, match="q90"):
        _kwantiel(q90=None)


def test_resolves_at_moet_na_created_at_liggen():
    """Anders is hij op het moment van maken al resolvbaar, en dan meet je
    niets."""
    with pytest.raises(ValueError, match="moet NA created_at"):
        _kwantiel(resolves_at=NU - timedelta(days=1))


def test_naive_tijdstempel_geweigerd():
    with pytest.raises(ValueError, match="timezone-aware"):
        _kwantiel(created_at=datetime(2026, 10, 1, 12, 0))


def test_horizon_moet_positief_zijn():
    with pytest.raises(ValueError, match="horizon_n"):
        _kwantiel(horizon_n=0)


# --- Opslag ---


def test_opslaan_en_teruglezen_behoudt_elk_veld(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    origineel = _kwantiel(
        graph_node=Node.TERM_PREMIUM,
        causal_chain=("policy_expectations->financial_conditions",),
        evidence_claim_ids=(3, 7),
        trigger_version="tv1", trigger_conditioned=True,
        market_implied_ref=4.05, note="uit de wekelijkse forecast-ronde",
    )
    save_prediction(conn, origineel)

    terug = list_predictions(conn)[0]
    assert terug == origineel


def test_binaire_voorspelling_overleeft_de_ronde(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    save_prediction(conn, _binair())
    assert list_predictions(conn)[0] == _binair()


def test_filteren_op_agent_en_cohort(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    save_prediction(conn, _kwantiel(agent="monetary_policy"))
    save_prediction(conn, _kwantiel(agent="human:dd"))
    save_prediction(conn, _kwantiel(agent="baseline:persistence", cohort="pseudo_oos"))

    assert len(list_predictions(conn)) == 3
    assert len(list_predictions(conn, agent="human:dd")) == 1
    assert len(list_predictions(conn, cohort="pseudo_oos")) == 1


def test_mensen_en_baselines_gebruiken_hetzelfde_contract(tmp_path):
    """Zonder dit zijn mens en model niet op dezelfde meetlat te leggen, en
    dat is precies wat 4.8 wil."""
    conn = init_db(str(tmp_path / "t.db"))
    for agent in ("human:dd", "human:partner", "baseline:climatology", "synthesizer"):
        save_prediction(conn, _kwantiel(agent=agent))
    assert {p.agent for p in list_predictions(conn)} == {
        "human:dd", "human:partner", "baseline:climatology", "synthesizer",
    }


def test_due_predictions_geeft_alleen_verstreken_voorspellingen(tmp_path):
    """De invoer voor de resolver (4.5): wat is er te scoren."""
    conn = init_db(str(tmp_path / "t.db"))
    save_prediction(conn, _kwantiel(resolves_at=NU + timedelta(days=5)))
    save_prediction(conn, _kwantiel(resolves_at=NU + timedelta(days=60)))

    due = list_due_predictions(conn, now=NU + timedelta(days=10))
    assert len(due) == 1
    assert due[0].resolves_at == NU + timedelta(days=5)


def test_database_weigert_ongeldige_vorm_ook_buiten_het_contract_om(tmp_path):
    """REGRESSIE. Het schema herhaalt de vormeisen als CHECK-constraints, zodat
    een bug in het contract geen ongeldige data kan opleveren. Hier geschreven
    met ruwe SQL, want via het contract kom je er niet langs."""
    import sqlite3

    conn = init_db(str(tmp_path / "t.db"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO predictions (
                agent, domain, target_metric_key, kind, horizon_kind, horizon_n,
                created_at, resolves_at, resolution_rule, model_id, prompt_version,
                q10, q50, q90, cohort, contract_version, graph_version,
                causal_chain_json, evidence_claim_ids_json
            ) VALUES ('a','b','c','quantile','trading_days',5,'2026-10-01','2026-10-22',
                      'regel','m','p', 9.0, 5.0, 1.0, 'cohort_0', 'v0', 'v0', '[]', '[]')""",
        )
