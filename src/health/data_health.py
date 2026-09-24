"""
data_health.py
Stap A.3. Dit systeem draait onbeheerd op de achtergrond -- in tegenstelling
tot analyst_agent.ai, waar een gebruiker een rapport meteen zelf doorleest en
een rare waarde opvalt, ziet hier niemand live mee. Een stille kapotte
databron levert dan niet "een fout rapport" op maar "gewoon geen trigger" --
en dat is het gevaarlijkste scenario dat dit systeem kent: een probleem dat
zich voordoet als rust.

Daarom staat dit vóór de trigger-laag (A.4): een trigger die evalueert tegen
data die stiekem al drie dagen niet ververst is, geeft vals vertrouwen. Elke
databron krijgt een verwachte ververssnelheid; overschrijding daarvan is zelf
een gebeurtenis die iemand moet zien (via de manager, A.6), niet een stille
non-actie.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from contract.output_contract import Claim


class HealthStatus(str, Enum):
    OK = "ok"
    STALE = "stale"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"  # nog nooit een succesvolle pull gezien voor deze bron


@dataclass(frozen=True)
class HealthCheckResult:
    source: str
    status: HealthStatus
    last_success_at: datetime | None
    checked_at: datetime
    detail: str | None = None

    @property
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.OK


def evaluate_staleness(
    source: str,
    last_success_at: datetime | None,
    max_age: timedelta,
    now: datetime | None = None,
    last_failure_detail: str | None = None,
) -> HealthCheckResult:
    """Zuiver deterministisch, geen I/O -- neemt de laatst bekende succesvolle
    pull-tijd aan als input (die wordt elders opgehaald uit storage.schema)
    en oordeelt puur op leeftijd. Los van de databron-specifieke ophaal-logica
    gehouden zodat dit voor élke bron (FRED, SEC, een RSS-feed, ...) hetzelfde
    werkt."""
    now = now or datetime.now(timezone.utc)
    if last_success_at is None:
        return HealthCheckResult(
            source=source,
            status=HealthStatus.UNKNOWN,
            last_success_at=None,
            checked_at=now,
            detail=last_failure_detail or "Nog nooit een succesvolle pull geregistreerd",
        )
    age = now - last_success_at
    if age > max_age:
        return HealthCheckResult(
            source=source,
            status=HealthStatus.STALE,
            last_success_at=last_success_at,
            checked_at=now,
            detail=f"Laatste succesvolle pull is {age} oud, verwacht binnen {max_age}",
        )
    return HealthCheckResult(source=source, status=HealthStatus.OK, last_success_at=last_success_at, checked_at=now)


def evaluate_pull_failure(source: str, now: datetime | None = None, detail: str | None = None) -> HealthCheckResult:
    """Voor het geval waarin de pull zelf faalt (netwerkfout, API-fout) --
    apart van staleness, want een bron kan onbereikbaar zijn ook al is de
    laatst bekende waarde nog niet 'oud' volgens de klok."""
    now = now or datetime.now(timezone.utc)
    return HealthCheckResult(
        source=source,
        status=HealthStatus.UNREACHABLE,
        last_success_at=None,
        checked_at=now,
        detail=detail or "Pull mislukt",
    )


# Verwachte ververssnelheid per databron-categorie. Bewust hier als losse,
# aanpasbare mapping i.p.v. hardcoded in elke domain agent -- sectie H
# ("open beslissingen") noemt expliciet dat drempelwaarden nog niet
# dichtgetimmerd zijn; dit is de plek waar dat straks per bron wordt getuned.
DEFAULT_MAX_AGE_BY_SOURCE_KIND = {
    "intraday_market_data": timedelta(hours=1),
    "daily_market_data": timedelta(days=2),
    "macro_release": timedelta(days=35),  # de meeste FRED-reeksen zijn maandelijks
    "news_feed": timedelta(hours=4),
    "filing_data": timedelta(days=95),  # kwartaalcijfers
}


def check_source(
    conn,
    source: str,
    max_age: timedelta,
    now: datetime | None = None,
) -> HealthCheckResult:
    """Gemakslaag rond evaluate_staleness die de laatst bekende succesvolle
    pull zelf uit storage.schema.latest_data_health opzoekt -- de vorm die
    de trigger-laag (A.4) en de manager (A.6) daadwerkelijk aanroepen."""
    from storage.schema import latest_data_health  # lazy import: voorkomt cirkelvoorkomen als storage health ooit zelf gebruikt

    now = now or datetime.now(timezone.utc)
    record = latest_data_health(conn, source)
    if record is None:
        return HealthCheckResult(source=source, status=HealthStatus.UNKNOWN, last_success_at=None, checked_at=now)
    if not record["success"]:
        # Er is wel een poging geregistreerd maar die mislukte -- check of er
        # daarvoor ooit een succesvolle was, anders blijft het UNKNOWN i.p.v.
        # UNREACHABLE (een bron die nog nooit heeft gewerkt is geen "opeens
        # onbereikbaar", dat verwart de manager onnodig).
        return evaluate_pull_failure(source, now=now, detail=record["detail"])
    return evaluate_staleness(source, record["checked_at"], max_age, now=now)


def detect_revision(
    previous_claims: list[Claim],
    source_time: datetime | None,
    value: float,
    tolerance: float = 1e-9,
) -> Claim | None:
    """Roadmap 1.3, "revisie-detectie": macro-cijfers worden later herzien
    (bijv. een eerste BBP-schatting wijkt af van de definitieve) -- dat is
    geen gewone delta (nieuwe periode, nieuwe waarde), maar een gewijzigde
    waarde voor een periode die AL eerder gerapporteerd is (zelfde
    source_time). Werkt tegen de al-bestaande claims-geschiedenis (elke
    monitoring-poll blijft bewaard, nooit overschreven) -- geen aparte
    observations-tabel nodig, dat zou nu alleen data dupliceren die claims
    al heeft.

    `previous_claims` is de VOLLEDIGE historie voor deze metric (zoals
    run_monitoring() 'm al ophaalt voor de delta-trigger, hier hergebruikt),
    niet alleen de laatste -- een revisie kan een periode van meerdere
    cycli geleden raken, niet per se de vorige poll. `source_time=None`
    (brondatum niet parsebaar) levert altijd None op: zonder betrouwbare
    periode-identificatie is een "revisie" niet van een gewone nieuwe
    waarde te onderscheiden, geen gok."""
    if source_time is None:
        return None
    for claim in previous_claims:
        if claim.source_time is None or claim.source_time != source_time:
            continue
        if not isinstance(claim.value, (int, float)):
            continue
        if abs(claim.value - value) > tolerance:
            return claim
    return None
