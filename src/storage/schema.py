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
    mode TEXT NOT NULL CHECK (mode IN ('monitoring', 'deep_dive')),
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
"""


def init_db(path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Maakt het schema aan als het nog niet bestaat (idempotent -- opnieuw
    aanroepen op een bestaande database doet niets kapot) en geeft een open
    connectie terug met foreign_keys aan."""
    Path(path).parent.mkdir(parents=True, exist_ok=True) if Path(path).parent != Path("") else None
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
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
    database in een staat achterlaten die het contract uit A.1 schendt."""
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
    conn.commit()
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
    cur = conn.execute(
        "INSERT INTO agent_runs (domain, mode, run_at, success, domain_output_id, trigger_count, error, event_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (domain, mode, run_at.isoformat(), int(success), domain_output_id, trigger_count, error, event_id),
    )
    conn.commit()
    return cur.lastrowid


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
