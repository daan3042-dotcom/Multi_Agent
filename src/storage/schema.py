"""
schema.py
Database-schema als source of truth (stap A.2). Bewust EERST de structured
data, met rendering/dashboard/alert als een laag erbovenop -- niet andersom.
Slaat het contract uit output_contract.py op (Claims/DomainOutput), plus de
trigger- en data-health-events die de latere stappen (A.3, A.4, A.6)
produceren.

SQLite via de standaardbibliotheek: geen nieuwe dependency, geen gecompileerde
extensie (zie CLAUDE.md-principe "geen gecompileerde dependencies waar
vermijdbaar" uit analyst_agent.ai, hier hergebruikt). Past bij de schaal van
dit systeem (twee gebruikers, geen concurrent-write-belasting) -- een zwaardere
database is pas relevant als dat verandert.

Zelfde foutafhandelingspatroon als de rest van de analyst_agent.ai-codebase:
nooit stilzwijgend een schrijfactie negeren; een write die niet kan slagen
(bijv. corrupt bestand) moet zichtbaar breken, niet een gat achterlaten dat
pas bij de synthesizer opvalt.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

from contract.graph import Node
from contract.prediction import HorizonKind, Prediction, PredictionKind
from contract.resolution import ResolutionMethod
from contract.output_contract import Claim, DomainOutput, Mode
from health.data_health import QualityStatus
from qc.qc import QCCase, QCCaseStatus, validate_qc_transition
from sources.registry import SourceConfig
from triggers.trigger_engine import TriggerEvent

DEFAULT_DB_PATH = "market_intelligence.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS domain_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('monitoring', 'deep_dive', 'forecast')),
    generated_at TEXT NOT NULL,
    needs_review INTEGER NOT NULL DEFAULT 0,
    review_issues_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_output_id INTEGER NOT NULL REFERENCES domain_outputs(id),
    domain TEXT NOT NULL,
    claim TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL,
    event_time TEXT,
    source_time TEXT,
    ingestion_time TEXT NOT NULL,
    analysis_time TEXT NOT NULL,
    metric_key TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_claims_domain ON claims(domain);
CREATE INDEX IF NOT EXISTS idx_claims_metric_key ON claims(metric_key);

CREATE TABLE IF NOT EXISTS data_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_data_health_source ON data_health(source, checked_at);

CREATE TABLE IF NOT EXISTS trigger_events (
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
CREATE INDEX IF NOT EXISTS idx_trigger_events_domain ON trigger_events(domain);
CREATE INDEX IF NOT EXISTS idx_trigger_events_batch ON trigger_events(dispatch_batch_id);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('monitoring', 'deep_dive')),
    run_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    domain_output_id INTEGER REFERENCES domain_outputs(id),
    trigger_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    event_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_domain ON agent_runs(domain, run_at);
-- Roadmap 1.7, deel 2 (idempotency): een event_id mag maximaal ÉÉN
-- succesvolle rij hebben per domain+mode -- afgedwongen op databaseniveau,
-- niet alleen in Python. Een MISLUKTE poging (success=0) telt bewust niet
-- mee (WHERE success = 1): een terechte retry na een echte fout moet
-- kunnen, alleen dubbele SUCCESVOLLE verwerking wordt geblokkeerd.
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_event_id
    ON agent_runs(domain, mode, event_id)
    WHERE event_id IS NOT NULL AND success = 1;

-- Roadmap 1.4: Source Registry. Eén rij per (provider, domain)-combinatie,
-- niet per provider -- zie sources/registry.py se moduledocstring voor de
-- volledige afweging. source_key (bv. "FRED:monetary_policy") is wat
-- record_data_health()/check_source() voortaan als source_name gebruiken.
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    domain TEXT NOT NULL,
    max_age_seconds INTEGER NOT NULL,
    frequency TEXT,
    latency TEXT,
    cost TEXT,
    quality_score REAL,
    fallback_source_key TEXT REFERENCES sources(source_key)
);
CREATE INDEX IF NOT EXISTS idx_sources_domain ON sources(domain);

-- Roadmap 1.6: QC & State Machine. Eén rij per escalatie, van trigger tot
-- archivering -- zie qc/qc.py se moduledocstring voor de volledige
-- toelichting op het statusmodel en welke overgangen automatisch/handmatig
-- zijn. RAW/VALIDATED worden bewust niet als losse rijen gepersisteerd,
-- een case begint daarom altijd bij TRIGGERED.
CREATE TABLE IF NOT EXISTS qc_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'raw', 'validated', 'triggered', 'deep_dive_complete',
        'qc_passed', 'qc_failed', 'needs_review', 'archived'
    )),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    trigger_reasons_json TEXT NOT NULL,
    domain_output_id INTEGER REFERENCES domain_outputs(id),
    quality_status TEXT CHECK (quality_status IN ('healthy', 'degraded', 'invalid')),
    qc_issues_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_qc_cases_domain_status ON qc_cases(domain, status);

-- Roadmap 4.1 (fase 2). ONVERANDERLIJK: er is bewust geen update-pad in
-- dit bestand. Een voorspelling achteraf bijstellen is precies de fout die
-- het hele forward-testopzet probeert te vermijden, dus die mogelijkheid
-- hoort niet te bestaan -- niet "hoort niet gebruikt te worden".
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
CREATE INDEX IF NOT EXISTS idx_predictions_resolves_at ON predictions(resolves_at);
CREATE INDEX IF NOT EXISTS idx_predictions_agent_cohort ON predictions(agent, cohort);
CREATE INDEX IF NOT EXISTS idx_predictions_target ON predictions(domain, target_metric_key);

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
CREATE INDEX IF NOT EXISTS idx_evaluations_status ON evaluations(status);

CREATE TABLE IF NOT EXISTS baseline_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    spec_version TEXT NOT NULL,
    domain TEXT NOT NULL,
    target_metric_key TEXT NOT NULL,
    horizon_n INTEGER NOT NULL,
    fitted_at TEXT NOT NULL,
    train_end TEXT NOT NULL,
    n_rows INTEGER NOT NULL,
    model_json TEXT NOT NULL,
    -- Eén model per (naam, specversie, doel, horizon), voor altijd. Een
    -- tweede fit onder dezelfde versie botst hier, en dat is de bedoeling:
    -- "gefit op de back-fill en daarna bevroren" (roadmap 4.6) betekent dat
    -- opnieuw fitten een NIEUWE specversie is, en dus zichtbaar.
    UNIQUE (model_name, spec_version, domain, target_metric_key, horizon_n)
);
"""


def init_db(path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Maakt het schema aan als het nog niet bestaat (idempotent -- opnieuw
    aanroepen op een bestaande database doet niets kapot) en geeft een open
    connectie terug met foreign_keys aan."""
    Path(path).parent.mkdir(parents=True, exist_ok=True) if Path(path).parent != Path("") else None
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    # Vóór het schema-script: deze migratie ruimt een tabelvorm op die de
    # nieuwe indexen niet aankunnen. Zie zijn docstring.
    _migreer_predictions_resolution_method(conn)
    conn.executescript(_SCHEMA)
    conn.commit()
    _migreer_agent_runs_mode(conn)
    return conn


@contextmanager
def open_db(path: str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = init_db(path)
    try:
        yield conn
    finally:
        conn.close()


def save_domain_output(conn: sqlite3.Connection, output: DomainOutput) -> int:
    """Slaat een volledige DomainOutput (en al zijn claims) op in één
    transactie -- een DomainOutput zonder zijn claims, of andersom, zou de
    database in een staat achterlaten die het contract uit A.1 schendt.

    LET OP: commit zelf. Wie dit in dezelfde transactie wil als de
    bijbehorende `agent_runs`-regel, gebruikt `save_output_with_run()`
    hieronder -- zie daar voor waarom dat uitmaakt."""
    domain_output_id = _insert_domain_output(conn, output)
    conn.commit()
    return domain_output_id


def _insert_domain_output(conn: sqlite3.Connection, output: DomainOutput) -> int:
    """De inserts zonder commit, zodat save_output_with_run() ze met de
    agent_run in één transactie kan zetten."""
    cur = conn.execute(
        "INSERT INTO domain_outputs (domain, mode, generated_at, needs_review, review_issues_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            output.domain,
            output.mode.value,
            output.generated_at.isoformat(),
            int(output.needs_review),
            json.dumps(output.review_issues, ensure_ascii=False),
        ),
    )
    domain_output_id = cur.lastrowid
    for c in output.claims:
        conn.execute(
            "INSERT INTO claims (domain_output_id, domain, claim, value_json, source, "
            "confidence, event_time, source_time, ingestion_time, analysis_time, metric_key, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                domain_output_id,
                c.domain,
                c.claim,
                json.dumps(c.value, ensure_ascii=False, default=str),
                c.source,
                c.confidence,
                c.event_time.isoformat() if c.event_time else None,
                c.source_time.isoformat() if c.source_time else None,
                c.ingestion_time.isoformat() if c.ingestion_time else None,
                c.analysis_time.isoformat(),
                c.metric_key,
                c.note,
            ),
        )
    return domain_output_id


def load_latest_claims(conn: sqlite3.Connection, domain: str, metric_key: str | None = None) -> list[Claim]:
    """Geeft de claims voor een domein terug (optioneel gefilterd op
    metric_key), gesorteerd nieuw naar oud -- de trigger-laag (A.4)
    vergelijkt hiermee de nieuwste waarde tegen een eerdere.

    LET OP de naam: dit is de VOLLEDIGE historie, niet "de laatste cyclus".
    Dat is wat de trigger-laag nodig heeft (een revisie kan een periode van
    meerdere cycli geleden raken), maar het is de verkeerde set om aan een
    deep-dive te voeren -- gebruik daarvoor `load_monitoring_claims()`."""
    query = (
        "SELECT domain, claim, value_json, source, confidence, event_time, source_time, "
        "ingestion_time, analysis_time, metric_key, note FROM claims WHERE domain = ?"
    )
    params: list = [domain]
    if metric_key is not None:
        query += " AND metric_key = ?"
        params.append(metric_key)
    query += " ORDER BY analysis_time DESC"
    return [_claim_from_row(row) for row in conn.execute(query, params).fetchall()]


def load_monitoring_claims(conn: sqlite3.Connection, domain: str) -> list[Claim]:
    """De claims van de MEEST RECENTE monitoring-cyclus voor dit domein --
    precies één cyclus, niet de hele historie.

    Bestaat naast `load_latest_claims()` omdat die ondanks zijn naam ALLE
    claims voor een domein teruggeeft (de trigger-laag heeft die historie
    nodig om een vorige observatie te vinden). Voor een deep-dive is dat de
    verkeerde set: `run_deep_dive()` slaat de aangeleverde claims opnieuw op
    als onderdeel van zijn eigen DomainOutput, dus de hele historie
    doorgeven verdubbelt de claims-tabel bij elke deep-dive -- 2ⁿ groei,
    gemeten op 255 rijen na 8 dagen. Zie `docs/architecture.md`
    ("Ontwerpkeuzes in de runtime-laag").

    Geeft een lege lijst terug als er nog geen monitoring-cyclus was."""
    row = conn.execute(
        "SELECT id FROM domain_outputs WHERE domain = ? AND mode = 'monitoring' "
        "ORDER BY generated_at DESC, id DESC LIMIT 1",
        (domain,),
    ).fetchone()
    if row is None:
        return []
    return _claims_for_output(conn, row[0])


def _claims_for_output(conn: sqlite3.Connection, domain_output_id: int) -> list[Claim]:
    rows = conn.execute(
        "SELECT domain, claim, value_json, source, confidence, event_time, source_time, "
        "ingestion_time, analysis_time, metric_key, note FROM claims "
        "WHERE domain_output_id = ? ORDER BY id",
        (domain_output_id,),
    ).fetchall()
    return [_claim_from_row(row) for row in rows]


def _claim_from_row(row: tuple) -> Claim:
    (domain_, claim_, value_json, source, confidence, event_time, source_time,
     ingestion_time, analysis_time, metric_key_, note) = row
    return Claim(
        domain=domain_,
        claim=claim_,
        value=json.loads(value_json),
        source=source,
        confidence=confidence,
        event_time=datetime.fromisoformat(event_time) if event_time else None,
        source_time=datetime.fromisoformat(source_time) if source_time else None,
        ingestion_time=datetime.fromisoformat(ingestion_time) if ingestion_time else None,
        analysis_time=datetime.fromisoformat(analysis_time),
        metric_key=metric_key_,
        note=note,
    )


def load_trigger_events_for_day(conn: sqlite3.Connection, day: date, domain: str | None = None) -> list[TriggerEvent]:
    """Alle opgeslagen triggers van één UTC-kalenderdag, optioneel per
    domein. Nodig voor het retry-pad van de dagelijkse cyclus (roadmap
    1.11): als monitoring al succesvol was en overgeslagen wordt, zijn de
    triggers van die dag alleen nog uit de database te halen -- zonder deze
    functie zou een deep-dive die de eerste keer mislukte nooit meer
    opnieuw kunnen draaien, en dat gat is permanent."""
    query = "SELECT domain, triggered_at, reason, severity, metric_key, observed_value_json, threshold_json FROM trigger_events WHERE date(triggered_at) = ?"
    params: list = [day.isoformat()]
    if domain is not None:
        query += " AND domain = ?"
        params.append(domain)
    query += " ORDER BY id"
    events = []
    for domain_, triggered_at, reason, severity, metric_key, observed_json, threshold_json in conn.execute(query, params):
        events.append(
            TriggerEvent(
                domain=domain_,
                triggered_at=datetime.fromisoformat(triggered_at),
                reason=reason,
                severity=severity,
                metric_key=metric_key,
                observed_value=json.loads(observed_json) if observed_json is not None else None,
                threshold=json.loads(threshold_json) if threshold_json is not None else None,
            )
        )
    return events


def record_trigger_event(
    conn: sqlite3.Connection,
    domain: str,
    triggered_at: datetime,
    reason: str,
    severity: str,
    metric_key: str | None = None,
    observed_value=None,
    threshold=None,
    dispatch_batch_id: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO trigger_events (domain, triggered_at, reason, severity, metric_key, "
        "observed_value_json, threshold_json, dispatch_batch_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            domain,
            triggered_at.isoformat(),
            reason,
            severity,
            metric_key,
            json.dumps(observed_value, ensure_ascii=False, default=str) if observed_value is not None else None,
            json.dumps(threshold, ensure_ascii=False, default=str) if threshold is not None else None,
            dispatch_batch_id,
        ),
    )
    conn.commit()
    return cur.lastrowid


def record_data_health(conn: sqlite3.Connection, source: str, checked_at: datetime, success: bool, detail: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO data_health (source, checked_at, success, detail) VALUES (?, ?, ?, ?)",
        (source, checked_at.isoformat(), int(success), detail),
    )
    conn.commit()
    return cur.lastrowid


def record_agent_run(
    conn: sqlite3.Connection,
    domain: str,
    mode: str,
    run_at: datetime,
    success: bool,
    domain_output_id: int | None = None,
    trigger_count: int = 0,
    error: str | None = None,
    event_id: str | None = None,
) -> int:
    """Audit-log-regel voor ÉÉN monitoring- of deep-dive-cyclus van een
    domain agent (roadmap 1.2, entiteit agent_runs) -- los van de claims
    die zo'n cyclus eventueel oplevert. Sluit de blinde vlek dat er nu wel
    resultaten (claims) bewaard worden, maar geen geschiedenis van de runs
    zelf: "heeft agent X vandaag gedraaid, is het gelukt". Wordt door
    run_monitoring()/run_deep_dive() (agents/base.py) op ELKE cyclus
    aangeroepen, ook bij falen -- net als data_health mag een mislukte run
    nooit stilzwijgend ontbreken.

    `event_id` is optioneel (roadmap 1.7, idempotency) -- een dedup-key die
    de AANROEPER meegeeft (bijv. een toekomstige scheduler: "cyclus van
    2026-01-01"). Een tweede succesvolle rij met hetzelfde domain+mode+
    event_id wordt door het schema zelf geweigerd (sqlite3.IntegrityError,
    zie idx_agent_runs_event_id) -- een mislukte poging blokkeert een
    retry met hetzelfde event_id NIET."""
    run_id = _insert_agent_run(
        conn, domain, mode, run_at, success,
        domain_output_id=domain_output_id, trigger_count=trigger_count,
        error=error, event_id=event_id,
    )
    conn.commit()
    return run_id


def _insert_agent_run(
    conn: sqlite3.Connection,
    domain: str,
    mode: str,
    run_at: datetime,
    success: bool,
    domain_output_id: int | None = None,
    trigger_count: int = 0,
    error: str | None = None,
    event_id: str | None = None,
) -> int:
    """De insert zonder commit -- zie _insert_domain_output()."""
    cur = conn.execute(
        "INSERT INTO agent_runs (domain, mode, run_at, success, domain_output_id, trigger_count, error, event_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (domain, mode, run_at.isoformat(), int(success), domain_output_id, trigger_count, error, event_id),
    )
    return cur.lastrowid


def save_output_with_run(
    conn: sqlite3.Connection,
    output: DomainOutput,
    mode: str,
    run_at: datetime,
    success: bool = True,
    trigger_count: int = 0,
    error: str | None = None,
    event_id: str | None = None,
) -> tuple[int, int]:
    """Slaat een DomainOutput én zijn `agent_runs`-regel op in ÉÉN
    transactie. Geeft (domain_output_id, agent_run_id) terug.

    ROADMAP 1.11, "atomiciteit claims/dedup". Het probleem dat dit oplost:
    `save_domain_output()` en `record_agent_run()` committen allebei apart.
    Daartussen zit een venster, en dat venster heeft twee uitgangen die
    allebei slecht zijn:

    1. **Crash ertussen.** De claims staan in de database, de audit-regel
       niet. Dat levert een wees op: data zonder spoor van de run die 'm
       maakte. Erger nog, `has_successful_run()` kijkt naar `agent_runs`,
       dus 1.7's idempotency ziet de cyclus als NIET gedaan -- een
       herstart haalt alles opnieuw op en schrijft de claims er nog een
       keer bij.
    2. **Dubbele `event_id`.** De partial unique index weigert een tweede
       succesvolle run met hetzelfde domain+mode+event_id, dus
       `record_agent_run()` gooit sqlite3.IntegrityError. Maar de claims
       zijn dan al gecommit. Precies het scenario waar idempotency voor
       bedoeld is, leverde dus dubbele claims op -- de bescherming sloeg
       toe NA de schrijfactie die hij moest voorkomen.

    Met één transactie rolt bij beide gevallen alles terug: geen claims,
    geen run, en een retry doet gewoon opnieuw wat er moest gebeuren.

    De IntegrityError wordt hier niet gevangen maar doorgegeven -- de
    aanroeper (`runtime/daily.py::_run_one_agent`) behandelt 'm al als
    "deze cyclus was al verwerkt". Wel wordt er eerst teruggerold, zodat de
    verbinding niet in een halve transactie achterblijft."""
    try:
        domain_output_id = _insert_domain_output(conn, output)
        agent_run_id = _insert_agent_run(
            conn, output.domain, mode, run_at, success,
            domain_output_id=domain_output_id, trigger_count=trigger_count,
            error=error, event_id=event_id,
        )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return domain_output_id, agent_run_id


def has_successful_run(conn: sqlite3.Connection, domain: str, mode: str, event_id: str) -> bool:
    """Roadmap 1.7, deel 2: is dit event_id al SUCCESVOL verwerkt voor dit
    domain+mode? De applicatie-check die run_monitoring()/run_deep_dive()
    vóóraf raadplegen (agents/base.py::AlreadyProcessedError) -- de
    databaseconstraint hierboven is het laatste vangnet, dit is de vroege,
    goedkope check die een onnodige fetch/LLM-call voorkomt."""
    row = conn.execute(
        "SELECT 1 FROM agent_runs WHERE domain = ? AND mode = ? AND event_id = ? AND success = 1 LIMIT 1",
        (domain, mode, event_id),
    ).fetchone()
    return row is not None


def list_agent_runs(conn: sqlite3.Connection, domain: str, mode: str | None = None, limit: int = 20) -> list[dict]:
    """Meest recente runs voor een domein, nieuw naar oud -- de leesvorm die
    1.7 (Observability, "system health per component") gebruikt. Optioneel
    filteren op mode ('monitoring'/'deep_dive') -- health.system_health
    heeft de LAATSTE run per modus apart nodig (ingestion vs. LLM-status),
    en zonder deze filter zou een domein met veel monitoring-runs de
    laatste deep-dive-run buiten een klein limit kunnen duwen."""
    query = "SELECT domain, mode, run_at, success, domain_output_id, trigger_count, error FROM agent_runs WHERE domain = ?"
    params: list = [domain]
    if mode is not None:
        query += " AND mode = ?"
        params.append(mode)
    query += " ORDER BY run_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [
        {
            "domain": domain_,
            "mode": mode,
            "run_at": datetime.fromisoformat(run_at),
            "success": bool(success),
            "domain_output_id": domain_output_id,
            "trigger_count": trigger_count,
            "error": error,
        }
        for domain_, mode, run_at, success, domain_output_id, trigger_count, error in rows
    ]


def latest_data_health(conn: sqlite3.Connection, source: str) -> dict | None:
    row = conn.execute(
        "SELECT checked_at, success, detail FROM data_health WHERE source = ? "
        "ORDER BY checked_at DESC LIMIT 1",
        (source,),
    ).fetchone()
    if row is None:
        return None
    checked_at, success, detail = row
    return {"source": source, "checked_at": datetime.fromisoformat(checked_at), "success": bool(success), "detail": detail}


def register_source(
    conn: sqlite3.Connection,
    source_key: str,
    provider: str,
    domain: str,
    max_age: timedelta,
    frequency: str | None = None,
    latency: str | None = None,
    cost: str | None = None,
    quality_score: float | None = None,
    fallback_source_key: str | None = None,
) -> None:
    """Roadmap 1.4: registreert/actualiseert ÉÉN bron in de Source Registry.
    UPSERT (ON CONFLICT DO UPDATE), niet een append-only log zoals
    record_agent_run()/record_data_health() -- dit is CONFIGURATIE, een
    agent mag 'm daarom veilig op elke monitoring-cyclus aanroepen om zijn
    eigen config te "declareren" zonder duplicaten te riskeren (zie
    sources/registry.py se moduledocstring). `fallback_source_key` is een
    FK naar sources.source_key (foreign_keys staat aan) -- verwijzen naar
    een niet-geregistreerde bron faalt zichtbaar (IntegrityError), geen
    stille no-op."""
    conn.execute(
        "INSERT INTO sources (source_key, provider, domain, max_age_seconds, frequency, latency, cost, "
        "quality_score, fallback_source_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(source_key) DO UPDATE SET provider=excluded.provider, domain=excluded.domain, "
        "max_age_seconds=excluded.max_age_seconds, frequency=excluded.frequency, latency=excluded.latency, "
        "cost=excluded.cost, quality_score=excluded.quality_score, "
        "fallback_source_key=excluded.fallback_source_key",
        (
            source_key, provider, domain, int(max_age.total_seconds()), frequency, latency, cost,
            quality_score, fallback_source_key,
        ),
    )
    conn.commit()


def _source_config_from_row(row: tuple) -> SourceConfig:
    source_key, provider, domain, max_age_seconds, frequency, latency, cost, quality_score, fallback_source_key = row
    return SourceConfig(
        source_key=source_key,
        provider=provider,
        domain=domain,
        max_age=timedelta(seconds=max_age_seconds),
        frequency=frequency,
        latency=latency,
        cost=cost,
        quality_score=quality_score,
        fallback_source_key=fallback_source_key,
    )


_SOURCES_SELECT = (
    "SELECT source_key, provider, domain, max_age_seconds, frequency, latency, cost, "
    "quality_score, fallback_source_key FROM sources"
)


def get_source(conn: sqlite3.Connection, source_key: str) -> SourceConfig | None:
    row = conn.execute(f"{_SOURCES_SELECT} WHERE source_key = ?", (source_key,)).fetchone()
    return _source_config_from_row(row) if row is not None else None


def list_sources(conn: sqlite3.Connection) -> list[SourceConfig]:
    """Alle geregistreerde bronnen, alfabetisch op source_key -- de vorm die
    health.system_health straks gebruikt om zijn `sources`-parameter
    automatisch te vullen i.p.v. met de hand samen te stellen."""
    rows = conn.execute(f"{_SOURCES_SELECT} ORDER BY source_key").fetchall()
    return [_source_config_from_row(row) for row in rows]


_QC_CASES_SELECT = (
    "SELECT id, domain, status, created_at, updated_at, trigger_reasons_json, "
    "domain_output_id, quality_status, qc_issues_json FROM qc_cases"
)


def _qc_case_from_row(row: tuple) -> QCCase:
    id_, domain, status, created_at, updated_at, trigger_reasons_json, domain_output_id, quality_status, qc_issues_json = row
    return QCCase(
        id=id_,
        domain=domain,
        status=QCCaseStatus(status),
        created_at=datetime.fromisoformat(created_at),
        updated_at=datetime.fromisoformat(updated_at),
        trigger_reasons=json.loads(trigger_reasons_json),
        domain_output_id=domain_output_id,
        quality_status=QualityStatus(quality_status) if quality_status else None,
        qc_issues=json.loads(qc_issues_json) if qc_issues_json else [],
    )


def open_qc_case(conn: sqlite3.Connection, domain: str, trigger_reasons: list[str], now: datetime) -> int:
    """Roadmap 1.6: nieuw QC-geval, status start meteen op TRIGGERED (zie
    qc.qc se moduledocstring voor waarom RAW/VALIDATED niet apart worden
    gepersisteerd). Wordt aangeroepen vanuit agents/base.py::
    run_monitoring() zodra er minstens één trigger is."""
    cur = conn.execute(
        "INSERT INTO qc_cases (domain, status, created_at, updated_at, trigger_reasons_json) VALUES (?, ?, ?, ?, ?)",
        (domain, QCCaseStatus.TRIGGERED.value, now.isoformat(), now.isoformat(), json.dumps(trigger_reasons, ensure_ascii=False)),
    )
    conn.commit()
    return cur.lastrowid


def get_qc_case(conn: sqlite3.Connection, case_id: int) -> QCCase | None:
    row = conn.execute(f"{_QC_CASES_SELECT} WHERE id = ?", (case_id,)).fetchone()
    return _qc_case_from_row(row) if row is not None else None


def latest_qc_case(conn: sqlite3.Connection, domain: str, status: QCCaseStatus) -> QCCase | None:
    """Meest recente case in een gegeven status voor dit domein -- de
    lookup die run_deep_dive() gebruikt om zijn TRIGGERED case te vinden
    zonder dat er een case_id doorgegeven hoeft te worden (geen wijziging
    nodig aan run_monitoring()/run_deep_dive()'s signatuur of aan de 6
    bestaande agent-wrappers)."""
    row = conn.execute(
        f"{_QC_CASES_SELECT} WHERE domain = ? AND status = ? ORDER BY created_at DESC LIMIT 1",
        (domain, status.value),
    ).fetchone()
    return _qc_case_from_row(row) if row is not None else None


def list_qc_cases(conn: sqlite3.Connection, domain: str, status: QCCaseStatus | None = None, limit: int = 20) -> list[QCCase]:
    query = f"{_QC_CASES_SELECT} WHERE domain = ?"
    params: list = [domain]
    if status is not None:
        query += " AND status = ?"
        params.append(status.value)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [_qc_case_from_row(row) for row in rows]


def advance_qc_case(
    conn: sqlite3.Connection,
    case_id: int,
    status: QCCaseStatus,
    now: datetime,
    domain_output_id: int | None = None,
    quality_status: QualityStatus | None = None,
    qc_issues: list[str] | None = None,
) -> None:
    """Zet een QC-geval een overgang verder. Valideert EERST tegen
    qc.qc.QC_TRANSITIONS (InvalidQCTransitionError bij een niet-
    toegestane sprong) -- dit is wat van `status` een echte state machine
    maakt, niet zomaar een vrij te overschrijven label. `domain_output_id`/
    `quality_status`/`qc_issues` worden alleen bijgewerkt als expliciet
    meegegeven (COALESCE): een latere overgang die deze niet meegeeft laat
    een eerder gezette waarde onaangeroerd."""
    current = get_qc_case(conn, case_id)
    if current is None:
        raise ValueError(f"qc_case {case_id} bestaat niet")
    validate_qc_transition(current.status, status)
    conn.execute(
        "UPDATE qc_cases SET status = ?, updated_at = ?, "
        "domain_output_id = COALESCE(?, domain_output_id), "
        "quality_status = COALESCE(?, quality_status), "
        "qc_issues_json = COALESCE(?, qc_issues_json) WHERE id = ?",
        (
            status.value,
            now.isoformat(),
            domain_output_id,
            quality_status.value if quality_status is not None else None,
            json.dumps(qc_issues, ensure_ascii=False) if qc_issues is not None else None,
            case_id,
        ),
    )
    conn.commit()


def archive_qc_case(conn: sqlite3.Connection, case_id: int, now: datetime) -> None:
    """De ENIGE overgang zonder aanroeper in agents/base.py -- expliciet,
    handmatig (bijv. later door een reviewer of scheduler). Alleen
    toegestaan vanuit QC_PASSED of NEEDS_REVIEW (zie QC_TRANSITIONS)."""
    advance_qc_case(conn, case_id, QCCaseStatus.ARCHIVED, now)


# --- Predictions (roadmap 4.1, fase 2) -------------------------------------
#
# BEWUST GEEN update_prediction() of delete_prediction(). Een voorspelling
# achteraf bijstellen is de fout die het hele forward-testopzet probeert te
# vermijden; die mogelijkheid hoort niet te bestaan, niet "hoort niet
# gebruikt te worden". Scores komen straks in een APARTE evaluations-tabel
# (4.5), zodat het resolveren de voorspelling zelf nooit aanraakt.


def _insert_prediction(conn: sqlite3.Connection, prediction: Prediction) -> int:
    """De insert zonder commit -- zie save_predictions_with_run().

    Slaat één voorspelling op en geeft zijn id terug. De vormcheck is al
    gebeurd bij constructie (contract/prediction.py::Prediction.__post_init__);
    het schema herhaalt dezelfde eisen als CHECK-constraints, zodat een bug
    in het contract niet stilzwijgend ongeldige data oplevert."""
    cur = conn.execute(
        """INSERT INTO predictions (
            agent, domain, target_metric_key, kind, horizon_kind, horizon_n,
            created_at, resolves_at, resolution_rule, model_id, prompt_version,
            q10, q50, q90, probability, event_rule,
            cohort, contract_version, graph_version, graph_node,
            causal_chain_json, evidence_claim_ids_json,
            trigger_version, trigger_conditioned, regime_at_creation,
            market_implied_ref, note, resolution_method, benchmark_metric_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            prediction.agent, prediction.domain, prediction.target_metric_key,
            prediction.kind.value, prediction.horizon_kind.value, prediction.horizon_n,
            prediction.created_at.isoformat(), prediction.resolves_at.isoformat(),
            prediction.resolution_rule, prediction.model_id, prediction.prompt_version,
            prediction.q10, prediction.q50, prediction.q90,
            prediction.probability, prediction.event_rule,
            prediction.cohort, prediction.contract_version, prediction.graph_version,
            prediction.graph_node.value if prediction.graph_node else None,
            json.dumps(list(prediction.causal_chain), ensure_ascii=False),
            json.dumps(list(prediction.evidence_claim_ids)),
            prediction.trigger_version, int(prediction.trigger_conditioned),
            prediction.regime_at_creation, prediction.market_implied_ref, prediction.note,
            prediction.resolution_method.value, prediction.benchmark_metric_key,
        ),
    )
    return cur.lastrowid


def save_prediction(conn: sqlite3.Connection, prediction: Prediction) -> int:
    """Slaat één voorspelling op en commit meteen. Voor losse voorspellingen
    (menselijke invoer, 4.8); een RONDE hoort `save_predictions_with_run()`
    te gebruiken, zodat hij niet half kan slagen."""
    prediction_id = _insert_prediction(conn, prediction)
    conn.commit()
    return prediction_id


def save_predictions_with_run(
    conn: sqlite3.Connection,
    predictions: list[Prediction] | tuple[Prediction, ...],
    run_domain: str,
    run_at: datetime,
    success: bool,
    event_id: str | None = None,
    error: str | None = None,
) -> list[int]:
    """Alle voorspellingen van een ronde PLUS de agent_runs-regel in één
    transactie: alles of niets.

    WAAROM. Vóór dit bestond bewaarde de forecast-ronde elke voorspelling
    met een eigen commit en schreef daarna pas de agent_runs-regel. Crasht
    het proces ertussen (of faalt die laatste insert), dan staat de ronde
    niet als geslaagd geregistreerd terwijl de voorspellingen er wél staan,
    en levert de herhaling van morgen dezelfde voorspellingen een tweede
    keer op. In een track record is dat geen ruis: de week telt dubbel mee
    in kalibratie en skill-posterior, en het is achteraf niet te zien welke
    van de twee 'echt' was. Zelfde faalpatroon en zelfde oplossing als
    `save_output_with_run()` voor claims.

    Een dubbele succes-run voor dezelfde `event_id` (de partial unique
    index) laat de HELE transactie terugrollen, voorspellingen inbegrepen --
    precies wat je wilt bij twee gelijktijdige runs."""
    try:
        ids = [_insert_prediction(conn, p) for p in predictions]
        _insert_agent_run(
            conn, run_domain, "forecast", run_at, success,
            trigger_count=len(predictions), error=error, event_id=event_id,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return ids


def _row_to_prediction(row: tuple) -> Prediction:
    (
        _id, agent, domain, target_metric_key, kind, horizon_kind, horizon_n,
        created_at, resolves_at, resolution_rule, model_id, prompt_version,
        q10, q50, q90, probability, event_rule, cohort, contract_version,
        graph_version, graph_node, causal_chain_json, evidence_claim_ids_json,
        trigger_version, trigger_conditioned, regime_at_creation,
        market_implied_ref, note, resolution_method, benchmark_metric_key,
    ) = row
    return Prediction(
        agent=agent, domain=domain, target_metric_key=target_metric_key,
        kind=PredictionKind(kind), horizon_kind=HorizonKind(horizon_kind),
        horizon_n=horizon_n,
        created_at=datetime.fromisoformat(created_at),
        resolves_at=datetime.fromisoformat(resolves_at),
        resolution_rule=resolution_rule, model_id=model_id, prompt_version=prompt_version,
        q10=q10, q50=q50, q90=q90, probability=probability, event_rule=event_rule,
        cohort=cohort, contract_version=contract_version, graph_version=graph_version,
        graph_node=Node(graph_node) if graph_node else None,
        causal_chain=tuple(json.loads(causal_chain_json)),
        evidence_claim_ids=tuple(json.loads(evidence_claim_ids_json)),
        trigger_version=trigger_version, trigger_conditioned=bool(trigger_conditioned),
        regime_at_creation=regime_at_creation, market_implied_ref=market_implied_ref,
        note=note,
        resolution_method=ResolutionMethod(resolution_method),
        benchmark_metric_key=benchmark_metric_key,
    )


def list_predictions(
    conn: sqlite3.Connection,
    agent: str | None = None,
    domain: str | None = None,
    cohort: str | None = None,
    limit: int = 100,
) -> list[Prediction]:
    """Voorspellingen, nieuwste eerst. Filters zijn optioneel en stapelbaar."""
    query = "SELECT * FROM predictions WHERE 1=1"
    params: list = []
    for kolom, waarde in (("agent", agent), ("domain", domain), ("cohort", cohort)):
        if waarde is not None:
            query += f" AND {kolom} = ?"
            params.append(waarde)
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    return [_row_to_prediction(r) for r in conn.execute(query, params).fetchall()]


def list_due_predictions(conn: sqlite3.Connection, now: datetime) -> list[Prediction]:
    """Voorspellingen waarvan `resolves_at` is verstreken -- de invoer voor
    de resolver (4.5, nog te bouwen). Oudste eerst, zodat resolveren in
    chronologische volgorde gebeurt.

    LET OP: dit filtert NIET op al-geresolveerde voorspellingen, want die
    administratie hoort in de evaluations-tabel en niet hier. De resolver
    bepaalt zelf wat hij al gezien heeft; deze functie blijft een zuivere
    vraag aan de predictions-tabel."""
    rows = conn.execute(
        "SELECT * FROM predictions WHERE resolves_at <= ? ORDER BY resolves_at ASC, id ASC",
        (now.isoformat(),),
    ).fetchall()
    return [_row_to_prediction(r) for r in rows]



def _migreer_predictions_resolution_method(conn: sqlite3.Connection) -> bool:
    """Voegt `resolution_method` en `benchmark_metric_key` toe aan een
    bestaande `predictions`-tabel. Geeft True terug als er gemigreerd is.

    Zelfde reden als `_migreer_agent_runs_mode()`: `CREATE TABLE IF NOT
    EXISTS` raakt een bestaande tabel niet aan, dus een database die vóór
    28-09 is aangemaakt heeft de oude vorm en zou bij de eerste
    forecast-ronde een OperationalError geven op een kolom die er niet is.

    WAAROM HERBOUWEN EN NIET `ALTER TABLE ADD COLUMN`. Die laatste kan geen
    NOT NULL-kolom toevoegen zonder default, en een default verzinnen zou
    betekenen dat oude rijen een resolutiemethode krijgen die niemand heeft
    afgesproken -- dan wordt een voorspelling straks afgewikkeld volgens
    een regel die er bij het voorspellen niet was. Herbouwen houdt de
    CHECK-constraints gelijk aan die van een verse database, zodat er geen
    twee soorten installaties ontstaan.

    DRAAIT VÓÓR HET SCHEMA-SCRIPT en laat het opnieuw opbouwen. Dat moet
    ook: de nieuwe indexen verwijzen naar kolommen die de oude tabel niet
    heeft, dus `CREATE INDEX IF NOT EXISTS` zou op de oude tabel stuklopen
    voordat de migratie überhaupt aan de beurt was.

    RIJEN GAAN NIET VERLOREN, maar ze kunnen ook niet compleet gemaakt
    worden: bestaande voorspellingen (die er in de praktijk niet zijn --
    de forecast-ronde draait nog nergens in productie) zouden een
    onbekende methode krijgen. Daarom weigert de migratie hard als er wél
    rijen staan, in plaats van te gokken."""
    huidige = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'predictions'"
    ).fetchone()
    if huidige is None or "resolution_method" in huidige[0]:
        return False

    aantal = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    if aantal:
        raise RuntimeError(
            f"predictions bevat {aantal} rij(en) zonder resolution_method. Die kunnen "
            f"niet automatisch een methode krijgen zonder te raden hoe ze afgewikkeld "
            f"moeten worden. Bepaal dat met de hand (zie contract/resolution.py) of "
            f"gooi de rijen weg als het testdata is."
        )

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with conn:
            conn.execute("DROP TABLE predictions")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return True

def _migreer_agent_runs_mode(conn: sqlite3.Connection) -> bool:
    """Voegt 'forecast' toe aan de toegestane modes van `agent_runs`.
    Geeft True terug als er daadwerkelijk gemigreerd is.

    WAAROM DIT BESTAAT. `CREATE TABLE IF NOT EXISTS` raakt een bestaande
    tabel niet aan, dus een CHECK-constraint die later verandert blijft op
    een draaiende database staan zoals hij was. Zonder deze migratie zou de
    forecast-ronde (2.0) op een verse testdatabase slagen en op de VPS
    falen met een IntegrityError -- het faalpatroon dat je pas in productie
    ziet, en dat hier extra duur is omdat die database het track record IS.

    SQLite kan een CHECK niet met ALTER TABLE wijzigen, dus de tabel wordt
    herbouwd: nieuwe tabel, rijen kopiëren, oude weg, hernoemen. Dat gebeurt
    in één transactie, en alleen als het nodig is -- de functie is
    idempotent en doet bij een al-gemigreerde database niets.

    De indexen worden bewust opnieuw aangemaakt: een DROP TABLE neemt ze
    mee, en de partial unique index op event_id (1.7's idempotency) stil
    kwijtraken zou dubbele verwerking weer mogelijk maken zonder dat iets
    dat meldt."""
    huidige_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'agent_runs'"
    ).fetchone()
    if huidige_sql is None or "'forecast'" in huidige_sql[0]:
        return False

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE agent_runs_nieuw (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    mode TEXT NOT NULL CHECK (mode IN ('monitoring', 'deep_dive', 'forecast')),
                    run_at TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    domain_output_id INTEGER REFERENCES domain_outputs(id),
                    trigger_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    event_id TEXT
                );
                INSERT INTO agent_runs_nieuw
                    SELECT id, domain, mode, run_at, success, domain_output_id,
                           trigger_count, error, event_id
                    FROM agent_runs;
                DROP TABLE agent_runs;
                ALTER TABLE agent_runs_nieuw RENAME TO agent_runs;
                CREATE INDEX IF NOT EXISTS idx_agent_runs_domain ON agent_runs(domain, run_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_event_id
                    ON agent_runs(domain, mode, event_id) WHERE success = 1;
                """
            )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return True


# ---------------------------------------------------------------------------
# Evaluations (roadmap 4.5) -- de uitkomst van een voorspelling
# ---------------------------------------------------------------------------


def list_unevaluated_due_predictions(
    conn: sqlite3.Connection, now: datetime
) -> list[tuple[int, Prediction]]:
    """Voorspellingen waarvan `resolves_at` verstreken is en die nog GEEN
    evaluation-rij hebben. De invoer van de resolver.

    Geeft (id, Prediction)-paren terug: de resolver heeft het id nodig om
    de uitkomst aan de voorspelling te koppelen, maar `Prediction` is het
    contract en draagt bewust geen databasesleutel.

    Bestaat naast `list_due_predictions()` (die NIET filtert op al
    afgewikkeld) omdat de resolver dagelijks draait: zonder deze filter
    zou hij elke dag opnieuw elke afgelopen voorspelling oppakken, en dat
    groeit ongelimiteerd mee met het cohort."""
    rows = conn.execute(
        "SELECT p.* FROM predictions p "
        "LEFT JOIN evaluations e ON e.prediction_id = p.id "
        "WHERE p.resolves_at <= ? AND e.id IS NULL "
        "ORDER BY p.resolves_at ASC, p.id ASC",
        (now.isoformat(),),
    ).fetchall()
    return [(r[0], _row_to_prediction(r)) for r in rows]


def save_evaluation(
    conn: sqlite3.Connection,
    prediction_id: int,
    status: str,
    resolved_at: datetime,
    scorer_version: str,
    realised_value: float | None = None,
    realised_at: datetime | None = None,
    claim_ids: tuple[int, ...] = (),
    reason: str | None = None,
    scores: dict[str, float] | None = None,
) -> int:
    """Schrijft één uitkomst weg. Onveranderlijk zodra geschreven: er is
    geen update-pad, net zomin als bij predictions.

    Dat is geen voorzichtigheid maar de kern van de meetopstelling. Een
    score die achteraf bijgesteld kan worden is geen track record."""
    scores = scores or {}
    cur = conn.execute(
        """INSERT INTO evaluations (
            prediction_id, status, resolved_at, realised_value, realised_at,
            evidence_claim_ids_json, reason,
            pinball_q10, pinball_q50, pinball_q90, pinball_mean, crps,
            brier, log_loss, within_interval, scorer_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            prediction_id, status, resolved_at.isoformat(), realised_value,
            realised_at.isoformat() if realised_at else None,
            json.dumps(list(claim_ids)), reason,
            scores.get("pinball_q10"), scores.get("pinball_q50"),
            scores.get("pinball_q90"), scores.get("pinball_mean"), scores.get("crps"),
            scores.get("brier"), scores.get("log_loss"),
            None if scores.get("within_interval") is None else int(scores["within_interval"]),
            scorer_version,
        ),
    )
    conn.commit()
    return cur.lastrowid


def list_evaluations(
    conn: sqlite3.Connection, status: str | None = None, limit: int | None = None
) -> list[dict]:
    """De evaluaties als dicts -- bewust geen dataclass.

    Een evaluation is een meetresultaat en geen contract: er gaat niets
    langs deze rijen heen dat gevalideerd moet worden, en de kolommen
    groeien mee met 4.5 (kalibratiecurve, AUC, effectieve n). Een
    dataclass zou daar elke keer achteraan lopen zonder iets te vangen."""
    query = "SELECT * FROM evaluations"
    params: list = []
    if status is not None:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id ASC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    kolommen = [d[0] for d in conn.execute("SELECT * FROM evaluations LIMIT 0").description]
    return [dict(zip(kolommen, row)) for row in conn.execute(query, params).fetchall()]


def load_observations(
    conn: sqlite3.Connection, metric_key: str
) -> list[tuple[int, str, float, str]]:
    """De ruwe waarnemingen voor één reeks: (claim_id, source_time, waarde,
    analysis_time), alleen de rijen met een bruikbare source_time en een
    numerieke waarde.

    Claims zonder `source_time` worden overgeslagen: dat veld is wat de
    BRON als observatiedatum opgeeft, en zonder die datum is niet te
    zeggen op welke periode een waarde slaat. Een fallback naar
    `analysis_time` zou de ophaaldatum als observatiedatum voorstellen en
    daarmee elke horizon stilzwijgend verschuiven."""
    rows = conn.execute(
        "SELECT id, source_time, value_json, analysis_time FROM claims "
        "WHERE metric_key = ? AND source_time IS NOT NULL ORDER BY source_time ASC",
        (metric_key,),
    ).fetchall()
    resultaat = []
    for claim_id, source_time, value_json, analysis_time in rows:
        try:
            waarde = float(json.loads(value_json))
        except (TypeError, ValueError):
            # Tekstclaims (deep-dive-verhalen) staan in dezelfde tabel en
            # hebben geen metric_key, maar een defensieve overslag kost
            # niets en voorkomt dat één rare rij de resolver laat vallen.
            continue
        resultaat.append((claim_id, source_time, waarde, analysis_time))
    return resultaat


# ---------------------------------------------------------------------------
# Bevroren baseline-modellen (roadmap 4.6)
# ---------------------------------------------------------------------------


def save_baseline_model(
    conn: sqlite3.Connection, model_name: str, spec_version: str, domain: str,
    target_metric_key: str, horizon_n: int, fitted_at: datetime, train_end: datetime,
    n_rows: int, model: dict,
) -> int:
    """Bevriest één gefit model. Onveranderlijk: geen update- of delete-pad,
    net als predictions en evaluations. Een tweede fit onder dezelfde
    specversie geeft een IntegrityError -- opnieuw fitten is een nieuwe
    versie, en dat hoort zichtbaar te zijn in het cohort."""
    cur = conn.execute(
        "INSERT INTO baseline_models (model_name, spec_version, domain, target_metric_key, "
        "horizon_n, fitted_at, train_end, n_rows, model_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            model_name, spec_version, domain, target_metric_key, horizon_n,
            fitted_at.isoformat(), train_end.isoformat(), n_rows,
            json.dumps(model, ensure_ascii=False, sort_keys=True),
        ),
    )
    conn.commit()
    return cur.lastrowid


def load_baseline_model(
    conn: sqlite3.Connection, model_name: str, spec_version: str, domain: str,
    target_metric_key: str, horizon_n: int,
) -> dict | None:
    row = conn.execute(
        "SELECT model_json FROM baseline_models WHERE model_name = ? AND spec_version = ? "
        "AND domain = ? AND target_metric_key = ? AND horizon_n = ?",
        (model_name, spec_version, domain, target_metric_key, horizon_n),
    ).fetchone()
    return json.loads(row[0]) if row else None


def count_baseline_models(conn: sqlite3.Connection, model_name: str, spec_version: str, domain: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM baseline_models WHERE model_name = ? AND spec_version = ? AND domain = ?",
        (model_name, spec_version, domain),
    ).fetchone()[0]


def list_domain_metric_keys(conn: sqlite3.Connection, domain: str) -> list[str]:
    """Alle metric_keys met tijdgebonden claims voor dit domein -- de
    kandidaat-inputs van het ridge-model. Alfabetisch, zodat de volgorde van
    features niet van de rijvolgorde in de database afhangt."""
    rows = conn.execute(
        "SELECT DISTINCT metric_key FROM claims WHERE domain = ? "
        "AND metric_key IS NOT NULL AND source_time IS NOT NULL ORDER BY metric_key",
        (domain,),
    ).fetchall()
    return [r[0] for r in rows]
