"""
trigger_engine.py
Stap A.4. Deterministische logica -- GEEN LLM -- die per domein bepaalt
wanneer een afwijking "significant" genoeg is om te escaleren naar deep-dive
mode. Bewust gescheiden van de QC-laag (A.5, die WEL een lichte LLM-review
kent): de vraag "moet dit escaleren" moet reproduceerbaar en goedkoop zijn,
zodat het continu op de achtergrond kan draaien zonder API-kosten per
databron-poll.

Een TriggerEvent hier is nog geen garantie op een deep-dive -- dat is de
manager (A.6) die over meerdere gelijktijdige triggers heen beslist. Deze
laag bepaalt alleen "is dit op zichzelf de moeite waard om te melden".

Data-health (A.3) is met opzet een eigen triggerpad: een STALE/UNREACHABLE
bron produceert een eigen, aparte trigger (severity "high", reason begint met
"data_health:") in plaats van gewoon niets op te leveren -- dat is precies
het stille-faalscenario dat A.3 wil voorkomen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from health.data_health import HealthCheckResult, HealthStatus

Severity = Literal["low", "medium", "high"]
Operator = Literal["<", "<=", ">", ">=", "=="]

_OPERATORS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
}


@dataclass(frozen=True)
class TriggerEvent:
    domain: str
    triggered_at: datetime
    reason: str
    severity: Severity
    metric_key: str | None = None
    observed_value: Any = None
    threshold: Any = None


def evaluate_threshold(
    domain: str,
    metric_key: str,
    observed_value: float,
    operator: Operator,
    threshold: float,
    reason: str,
    severity: Severity = "medium",
    now: datetime | None = None,
) -> TriggerEvent | None:
    """Vaste drempelwaarde: bijv. 'Fed funds rate verrassing > 0.25pp'.
    Geeft None terug als de drempel niet geraakt is -- geen trigger is het
    normale pad, geen foutstaat."""
    if operator not in _OPERATORS:
        raise ValueError(f"Onbekende operator: {operator!r}")
    if not _OPERATORS[operator](observed_value, threshold):
        return None
    return TriggerEvent(
        domain=domain,
        triggered_at=now or datetime.now(timezone.utc),
        reason=reason,
        severity=severity,
        metric_key=metric_key,
        observed_value=observed_value,
        threshold=threshold,
    )


def evaluate_surprise(
    domain: str,
    metric_key: str,
    observed_value: float,
    expected_value: float,
    tolerance: float,
    reason: str,
    severity: Severity = "medium",
    now: datetime | None = None,
) -> TriggerEvent | None:
    """Afwijking-tegen-verwachting i.p.v. een vaste drempel -- bijv. een
    CPI-print die van de consensusverwachting afwijkt. tolerance is een
    absolute marge; de aanroeper bepaalt de eenheid (procentpunt, dollar,
    ...) zodat deze functie domein-agnostisch blijft."""
    deviation = abs(observed_value - expected_value)
    if deviation <= tolerance:
        return None
    return TriggerEvent(
        domain=domain,
        triggered_at=now or datetime.now(timezone.utc),
        reason=f"{reason} (afwijking {deviation:g}, tolerantie {tolerance:g})",
        severity=severity,
        metric_key=metric_key,
        observed_value=observed_value,
        threshold=expected_value,
    )


def evaluate_data_health(domain: str, health: HealthCheckResult, now: datetime | None = None) -> TriggerEvent | None:
    """Zet een slechte HealthCheckResult (A.3) om in een eigen trigger. OK en
    UNKNOWN leveren bewust geen trigger op: UNKNOWN is de normale staat vóór
    de allereerste succesvolle pull, geen storing."""
    if health.status in (HealthStatus.OK, HealthStatus.UNKNOWN):
        return None
    severity: Severity = "high" if health.status == HealthStatus.UNREACHABLE else "medium"
    return TriggerEvent(
        domain=domain,
        triggered_at=now or datetime.now(timezone.utc),
        reason=f"data_health: bron '{health.source}' is {health.status.value} -- {health.detail}",
        severity=severity,
        metric_key=None,
        observed_value=health.status.value,
        threshold=None,
    )
