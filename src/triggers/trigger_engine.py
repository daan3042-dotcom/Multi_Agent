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

from health.data_health import CompletenessResult, HealthCheckResult, HealthStatus

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


def evaluate_revision(
    domain: str,
    metric_key: str,
    previous_value: float,
    revised_value: float,
    reason: str,
    severity: Severity = "medium",
    now: datetime | None = None,
) -> TriggerEvent:
    """Roadmap 1.3, revisie-detectie (health.data_health.detect_revision()
    heeft de vergelijking al gemaakt vóórdat dit aangeroepen wordt). Anders
    dan evaluate_surprise(): GEEN tolerantie-afweging -- een gewijzigde
    waarde voor een periode die al eerder is gerapporteerd is per definitie
    op zichzelf al nieuws (bijv. een BBP-schatting die naar beneden wordt
    bijgesteld), niet een "is dit significant genoeg"-vraag."""
    return TriggerEvent(
        domain=domain,
        triggered_at=now or datetime.now(timezone.utc),
        reason=reason,
        severity=severity,
        metric_key=metric_key,
        observed_value=revised_value,
        threshold=previous_value,
    )


def evaluate_completeness_result(
    domain: str, result: CompletenessResult, now: datetime | None = None
) -> TriggerEvent | None:
    """Zet een onvolledige pull (health.data_health.evaluate_completeness())
    om in EEN trigger. Roadmap 1.3, gewired op 28-09-2026.

    WAAROM DIT ER PAS NU IS. De check bestond sinds 1.3 maar was bewust niet
    gekoppeld: hem aanzetten is een gedragswijziging voor alle zes agents
    tegelijk, en een gedeeltelijke pull werd tot dan getolereerd (zie de
    fetch_snapshot()-docstrings: ontbrekende reeksen worden overgeslagen
    i.p.v. gegokt). De eerste live run op de VPS maakte duidelijk waarom dat
    niet houdbaar is: de sector agent haalde 2 van de 11 ETF's op, commodity
    2 van de 10, currency 1 van de 3 -- en alle drie rapporteerden
    `success=True`. `fetch_snapshot()` geeft namelijk alleen een fout terug
    als GEEN ENKELE reeks lukte. Zonder deze trigger is een bron die voor
    80% wegvalt niet te onderscheiden van een gezonde dag.

    EEN trigger per cyclus, niet een per ontbrekende reeks: negen missende
    ETF's zijn een probleem, niet negen problemen. De ontbrekende sleutels
    staan in de reden, gesorteerd zodat de tekst stabiel is tussen runs.

    Severity naar rato, omdat het verschil uitmaakt: een enkele reeks die
    een keer niet meekomt is ruis (FRED publiceert nu eenmaal niet alles op
    hetzelfde moment), de helft die wegvalt is een storing.
    """
    if result.is_complete:
        return None

    ontbrekend = len(result.missing_metric_keys)
    verwacht = len(result.expected_metric_keys)
    aandeel = ontbrekend / verwacht if verwacht else 1.0
    severity: Severity = "high" if aandeel >= 0.5 else "medium"

    return TriggerEvent(
        domain=domain,
        triggered_at=now or (result.checked_at or datetime.now(timezone.utc)),
        reason=(
            f"completeness: {verwacht - ontbrekend} van de {verwacht} verwachte reeksen "
            f"opgehaald bij bron '{result.source}' -- ontbreekt: "
            f"{', '.join(sorted(result.missing_metric_keys))}"
        ),
        severity=severity,
        metric_key=None,
        observed_value=verwacht - ontbrekend,
        threshold=verwacht,
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
