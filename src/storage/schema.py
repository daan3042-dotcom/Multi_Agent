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
from datetime import datetime
from pathlib import Path
from typing import Iterator

from contract.output_contract import Claim, DomainOutput, Mode

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
    """Geeft de meest recente claims voor een domein terug (optioneel
    gefilterd op metric_key), gesorteerd nieuw naar oud -- de trigger-laag
    (A.4) vergelijkt hiermee de nieuwste waarde tegen een eerdere."""
    query = (
        "SELECT domain, claim, value_json, source, confidence, event_time, source_time, "
        "ingestion_time, analysis_time, metric_key, note FROM claims WHERE domain = ?"
    )
    params: list = [domain]
    if metric_key is not None:
        query += " AND metric_key = ?"
        params.append(metric_key)
    query += " ORDER BY analysis_time DESC"
    rows = conn.execute(query, params).fetchall()
    claims = []
    for domain_, claim_, value_json, source, confidence, event_time, source_time, ingestion_time, analysis_time, metric_key_, note in rows:
        claims.append(
            Claim(
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
        )
    return claims


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
