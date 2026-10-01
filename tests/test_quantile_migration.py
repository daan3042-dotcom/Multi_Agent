"""
test_quantile_migration.py
De overstap van drie naar vijf kwantielen (contract v0 -> v1, 01-10-2026, DD):
schema, CHECK-constraints en vooral de MIGRATIE van een bestaande database.

WAAROM DIT APART IS GETEST. `init_db` draait elke ochtend in `run_daily`. Een
migratie die crasht, of die stilletjes rijen kwijtraakt, raakt dus rechtstreeks
de T₀ᵃ-klok of het track record. `LEGACY_DDL` hieronder is de EXACTE tabelvorm
van vóór de wijziging (uit git, commit fe0b2e4), zodat de test echt een oude
database nabootst en niet een die toevallig al de nieuwe vorm heeft.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from contract.prediction import HorizonKind, Prediction, PredictionKind
from contract.resolution import ResolutionMethod
from scoring.resolver import score_prediction
from storage.schema import init_db, list_evaluations, save_evaluation, save_prediction

LEGACY_DDL = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    domain TEXT NOT NULL,
    target_metric_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('quantile', 'binary')),
    horizon_kind TEXT NOT NULL CHECK (horizon_kind IN ('trading_days', 'releases')),
    horizon_n INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    resolves_at TEXT NOT NULL,
    resolution_rule TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    q10 REAL,
    q50 REAL,
    q90 REAL,
    probability REAL,
    event_rule TEXT,
    cohort TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    graph_version TEXT NOT NULL,
    graph_node TEXT,
    causal_chain_json TEXT NOT NULL,
    evidence_claim_ids_json TEXT NOT NULL,
    trigger_version TEXT,
    trigger_conditioned INTEGER NOT NULL DEFAULT 0,
    regime_at_creation TEXT,
    market_implied_ref REAL,
    note TEXT,
    resolution_method TEXT NOT NULL CHECK (resolution_method IN (
        'level_at_or_after', 'nth_release', 'relative_return', 'direction_after_fomc'
    )),
    benchmark_metric_key TEXT,
    -- Dezelfde vormeisen als contract/prediction.py, maar dan in het
    -- schema: een prediction die langs het contract komt maar niet langs
    -- deze checks zou een bug in het contract blootleggen, en andersom.
    CHECK (horizon_n > 0),
    CHECK (resolution_method != 'relative_return' OR benchmark_metric_key IS NOT NULL),
    CHECK (
        (kind = 'quantile' AND q10 IS NOT NULL AND q50 IS NOT NULL AND q90 IS NOT NULL
             AND probability IS NULL AND event_rule IS NULL AND q10 <= q50 AND q50 <= q90)
        OR
        (kind = 'binary' AND probability IS NOT NULL AND event_rule IS NOT NULL
             AND probability BETWEEN 0 AND 1 AND q10 IS NULL AND q50 IS NULL AND q90 IS NULL)
    )
);
CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id INTEGER NOT NULL REFERENCES predictions(id),
    status TEXT NOT NULL CHECK (status IN ('resolved', 'unresolvable')),
    resolved_at TEXT NOT NULL,
    realised_value REAL,
    realised_at TEXT,
    evidence_claim_ids_json TEXT NOT NULL,
    reason TEXT,
    pinball_q10 REAL,
    pinball_q50 REAL,
    pinball_q90 REAL,
    pinball_mean REAL,
    crps REAL,
    brier REAL,
    log_loss REAL,
    within_interval INTEGER,
    scorer_version TEXT NOT NULL,
    -- Eén uitkomst per voorspelling, voor altijd. Een voorspelling die nog
    -- niet afgewikkeld KAN worden krijgt bewust GEEN rij: dan blijft hij
    -- vanzelf in beeld bij de volgende run, en is "nog wachten" niet te
    -- verwarren met "nooit gelukt".
    UNIQUE (prediction_id),
    CHECK (
        (status = 'resolved' AND realised_value IS NOT NULL AND realised_at IS NOT NULL)
        OR
        (status = 'unresolvable' AND reason IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_predictions_resolves_at ON predictions(resolves_at);
CREATE INDEX IF NOT EXISTS idx_predictions_agent_cohort ON predictions(agent, cohort);
CREATE INDEX IF NOT EXISTS idx_predictions_target ON predictions(domain, target_metric_key);
CREATE INDEX IF NOT EXISTS idx_evaluations_status ON evaluations(status);
"""

NU = datetime(2026, 10, 5, 7, 15, tzinfo=timezone.utc)


def _oude_db(pad, *, met_rij: bool):
    conn = sqlite3.connect(pad)
    conn.executescript(LEGACY_DDL)
    if met_rij:
        conn.execute(
            "INSERT INTO predictions (agent, domain, target_metric_key, kind, horizon_kind, horizon_n, created_at, "
            "resolves_at, resolution_rule, model_id, prompt_version, q10, q50, q90, cohort, contract_version, "
            "graph_version, causal_chain_json, evidence_claim_ids_json, resolution_method) "
            "VALUES ('monetary_policy','monetary_policy','dgs10','quantile','trading_days',5,?,?,'regel','m','p',"
            "3.9,4.1,4.4,'dry_run','v0','v0','[]','[]','level_at_or_after')",
            (NU.isoformat(), (NU + timedelta(days=7)).isoformat()),
        )
        conn.execute(
            "INSERT INTO evaluations (prediction_id, status, resolved_at, realised_value, realised_at, "
            "evidence_claim_ids_json, pinball_q10, pinball_q50, pinball_q90, pinball_mean, crps, scorer_version) "
            "VALUES (1,'resolved',?,4.0,?,'[]',0.01,0.05,0.04,0.03,0.06,'v1')",
            (NU.isoformat(), NU.isoformat()),
        )
    conn.commit()
    conn.close()


def _kolommen(conn, tabel):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({tabel})")}


def _tabellen(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _voorspelling(**kw):
    basis = dict(
        agent="monetary_policy", domain="monetary_policy", target_metric_key="dgs10",
        kind=PredictionKind.QUANTILE, horizon_kind=HorizonKind.TRADING_DAYS, horizon_n=5,
        created_at=NU, resolves_at=NU + timedelta(days=7), resolution_rule="regel",
        resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER, model_id="m", prompt_version="p",
        q10=3.9, q25=4.0, q50=4.1, q75=4.25, q90=4.4,
    )
    basis.update(kw)
    return Prediction(**basis)


# --------------------------------------------------------------------------
# Migratie
# --------------------------------------------------------------------------


def test_lege_oude_tabellen_worden_vervangen_door_de_nieuwe_vorm(tmp_path):
    pad = str(tmp_path / "t.db")
    _oude_db(pad, met_rij=False)
    conn = init_db(pad)

    assert {"q25", "q75"} <= _kolommen(conn, "predictions")
    assert {"pinball_q25", "pinball_q75"} <= _kolommen(conn, "evaluations")
    assert not any("legacy" in t for t in _tabellen(conn))  # niets om te bewaren
    save_prediction(conn, _voorspelling())  # en de nieuwe vorm werkt meteen


def test_oude_rijen_gaan_niet_verloren_en_de_run_crasht_niet(tmp_path):
    """Het regressiegeval waar het om gaat. De eerdere migratie (resolution_method)
    weigerde hard bij rijen; dat zou hier elke dagelijkse run laten crashen. Nu
    worden de tabellen hernoemd en blijft alles leesbaar."""
    pad = str(tmp_path / "t.db")
    _oude_db(pad, met_rij=True)
    conn = init_db(pad)  # geen uitzondering

    assert {"predictions_legacy_v0", "evaluations_legacy_v0"} <= _tabellen(conn)
    assert conn.execute("SELECT COUNT(*) FROM predictions_legacy_v0").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM evaluations_legacy_v0").fetchone()[0] == 1
    assert conn.execute("SELECT q10, q50, q90 FROM predictions_legacy_v0").fetchone() == (3.9, 4.1, 4.4)
    assert conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0  # verse, lege tabel
    # De oude uitkomst wijst nog naar de oude voorspelling, niet naar de nieuwe tabel.
    verwijzingen = [r[2] for r in conn.execute("PRAGMA foreign_key_list(evaluations_legacy_v0)")]
    assert verwijzingen == ["predictions_legacy_v0"]


def test_na_de_migratie_hebben_de_nieuwe_tabellen_hun_eigen_indexen(tmp_path):
    """Een hernoemde tabel neemt zijn indexen met naam mee; zonder ze los te koppelen slaat
    `CREATE INDEX IF NOT EXISTS` voor de nieuwe tabel stil over en is hij ongeindexeerd."""
    pad = str(tmp_path / "t.db")
    _oude_db(pad, met_rij=True)
    conn = init_db(pad)
    per_tabel = {
        r[0]: r[1] for r in conn.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
    }
    assert per_tabel["idx_predictions_resolves_at"] == "predictions"
    assert per_tabel["idx_predictions_agent_cohort"] == "predictions"
    assert per_tabel["idx_evaluations_status"] == "evaluations"


def test_migratie_is_idempotent_en_een_verse_database_migreert_niet(tmp_path):
    pad = str(tmp_path / "t.db")
    _oude_db(pad, met_rij=True)
    init_db(pad).close()
    conn = init_db(pad)  # tweede run: niets meer te doen, geen botsing met de legacy-tabellen
    assert conn.execute("SELECT COUNT(*) FROM predictions_legacy_v0").fetchone()[0] == 1

    vers = init_db(str(tmp_path / "vers.db"))
    assert not any("legacy" in t for t in _tabellen(vers))


def test_nieuwe_voorspellingen_en_uitkomsten_werken_na_een_migratie_met_rijen(tmp_path):
    pad = str(tmp_path / "t.db")
    _oude_db(pad, met_rij=True)
    conn = init_db(pad)
    p = _voorspelling()
    pid = save_prediction(conn, p)
    save_evaluation(
        conn, pid, "resolved", NU, "v2", realised_value=4.0, realised_at=NU, scores=score_prediction(p, 4.0),
    )
    assert len(list_evaluations(conn)) == 1


# --------------------------------------------------------------------------
# CHECK-constraints en scores
# --------------------------------------------------------------------------


def test_het_schema_weigert_een_kwantielvoorspelling_zonder_q25_of_q75(tmp_path):
    """Het contract weigert dit al bij constructie; het schema herhaalt de eis, zodat een bug in
    het contract geen ongeldige rij oplevert."""
    conn = init_db(str(tmp_path / "t.db"))
    kolommen = (
        "agent, domain, target_metric_key, kind, horizon_kind, horizon_n, created_at, resolves_at, "
        "resolution_rule, model_id, prompt_version, q10, q25, q50, q75, q90, cohort, contract_version, "
        "graph_version, causal_chain_json, evidence_claim_ids_json, resolution_method"
    )

    def invoegen(q10, q25, q50, q75, q90):
        conn.execute(
            f"INSERT INTO predictions ({kolommen}) VALUES ('a','d','m','quantile','trading_days',5,?,?,'r','m','p',"
            f"?,?,?,?,?,'dry_run','v1','v0','[]','[]','level_at_or_after')",
            (NU.isoformat(), (NU + timedelta(days=7)).isoformat(), q10, q25, q50, q75, q90),
        )

    invoegen(1, 2, 3, 4, 5)  # geldig
    with pytest.raises(sqlite3.IntegrityError):
        invoegen(1, None, 3, 4, 5)  # q25 ontbreekt
    with pytest.raises(sqlite3.IntegrityError):
        invoegen(1, 2, 3, None, 5)  # q75 ontbreekt
    with pytest.raises(sqlite3.IntegrityError):
        invoegen(1, 4, 3, 4, 5)  # q25 boven q50: kruisend


def test_een_afgewikkelde_voorspelling_bewaart_de_pinball_per_niveau(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    p = _voorspelling()
    pid = save_prediction(conn, p)
    scores = score_prediction(p, 4.3)
    save_evaluation(conn, pid, "resolved", NU, "v2", realised_value=4.3, realised_at=NU, scores=scores)

    (rij,) = list_evaluations(conn)
    for veld in ("q10", "q25", "q50", "q75", "q90"):
        assert rij[f"pinball_{veld}"] == pytest.approx(scores[f"pinball_{veld}"])
    assert rij["crps"] == pytest.approx(2 * rij["pinball_mean"])
    assert rij["scorer_version"] is not None
