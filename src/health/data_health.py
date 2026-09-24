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
from typing import Any, Iterable

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


# ---------------------------------------------------------------------------
# Roadmap 1.3, resterende vier checks: completeness / validity / consistency
# / continuity. Elk een EIGEN, smal resultaat-type i.p.v. geforceerd in
# HealthStatus -- HealthStatus beschrijft specifiek "is de bron bereikbaar en
# vers" (A.3); deze vier checks meten andere, orthogonale assen (breedte van
# een pull, plausibiliteit van een waarde, rekenkundige klopt-het van een
# afgeleide claim, gaten in een historische reeks) die daar niet onder
# vallen. Zie docs/architecture.md ("Ontwerpkeuzes") voor de volledige
# afweging, ook wat dit betekent voor het HEALTHY/DEGRADED/INVALID-
# statusmodel hieronder.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompletenessResult:
    """Completeness: is voor ÉÉN monitoring-pull elke VERWACHTE metric ook
    daadwerkelijk binnengekomen? Anders dan staleness (is de LAATSTE waarde
    oud) of continuity hieronder (gat OVER TIJD in de reeks) -- dit is een
    momentopname van ÉÉN cyclus: bijv. FRED_SERIES heeft 4 reeksen, maar
    deze keer kwamen er maar 3 terug. Een ontbrekende metric die WEL
    verwacht werd is geen gok-waardige situatie (fetch_snapshot() slaat 'm
    om goede reden over, zie de agent-moduledocstrings) maar wel iets om
    zichtbaar te houden."""

    source: str
    expected_metric_keys: frozenset[str]
    missing_metric_keys: frozenset[str]
    checked_at: datetime

    @property
    def is_complete(self) -> bool:
        return not self.missing_metric_keys


def evaluate_completeness(
    source: str,
    expected_metric_keys: Iterable[str],
    present_metric_keys: Iterable[str],
    now: datetime | None = None,
) -> CompletenessResult:
    """Zuiver deterministisch, geen I/O. `expected_metric_keys` komt in de
    praktijk uit een agent se METRIC_SPECS.keys() (of FRED_SERIES.keys());
    `present_metric_keys` uit de daadwerkelijke snapshot-dict van die
    cyclus -- beide al beschikbaar in agents.base.run_monitoring() zonder
    extra ophaalwerk. Een metric die WEL binnenkomt maar niet verwacht was
    telt niet mee als incompleteness (dat zou een configuratiefout zijn,
    geen data-kwaliteitsprobleem)."""
    now = now or datetime.now(timezone.utc)
    expected = frozenset(expected_metric_keys)
    present = frozenset(present_metric_keys)
    return CompletenessResult(
        source=source, expected_metric_keys=expected, missing_metric_keys=expected - present, checked_at=now,
    )


@dataclass(frozen=True)
class ValidityResult:
    """Validity: is DEZE waarde, op zichzelf, plausibel? Een type-check
    (is het een getal) plus een optioneel bereik. GEEN domein-specifieke
    bereiken hardcoded hier -- net als METRIC_SPECS' tolerances (zie
    agents/base.py's docstring, docs/roadmap.md sectie H) zijn plausibele
    bereiken per metric een DD-finetuning-kwestie, geen gok van deze
    check. `valid_range=None` betekent: alleen het type checken."""

    metric_key: str
    value: Any
    is_valid: bool
    reason: str | None
    checked_at: datetime


def evaluate_validity(
    metric_key: str,
    value: Any,
    valid_range: tuple[float, float] | None = None,
    now: datetime | None = None,
) -> ValidityResult:
    now = now or datetime.now(timezone.utc)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ValidityResult(
            metric_key=metric_key, value=value, is_valid=False,
            reason=f"geen getal (type {type(value).__name__})", checked_at=now,
        )
    if valid_range is not None:
        lo, hi = valid_range
        if not (lo <= value <= hi):
            return ValidityResult(
                metric_key=metric_key, value=value, is_valid=False,
                reason=f"{value:g} valt buiten het plausibele bereik [{lo:g}, {hi:g}]", checked_at=now,
            )
    return ValidityResult(metric_key=metric_key, value=value, is_valid=True, reason=None, checked_at=now)


@dataclass(frozen=True)
class ConsistencyResult:
    """Consistency: klopt een AFGELEIDE claim (source="Berekend (...)") met
    de ruwe claims waaruit hij is berekend? Bijv. of "Afwijking daadwerke-
    lijke Fed funds rate t.o.v. Taylor Rule" écht gelijk is aan
    fed_funds_rate - taylor_rule_implied_rate. De herberekening zelf is
    ONVERMIJDELIJK domein-specifiek (alleen de agent kent zijn eigen
    formule) -- deze functie is daarom bewust een generieke vergelijker,
    geen kant-en-klare per-agent-check."""

    claim_label: str
    stated_value: float
    recomputed_value: float
    is_consistent: bool
    checked_at: datetime


def evaluate_consistency(
    claim_label: str,
    stated_value: float,
    recomputed_value: float,
    tolerance: float = 1e-6,
    now: datetime | None = None,
) -> ConsistencyResult:
    now = now or datetime.now(timezone.utc)
    is_consistent = abs(stated_value - recomputed_value) <= tolerance
    return ConsistencyResult(
        claim_label=claim_label, stated_value=stated_value, recomputed_value=recomputed_value,
        is_consistent=is_consistent, checked_at=now,
    )


@dataclass(frozen=True)
class ContinuityGap:
    before: datetime
    after: datetime
    gap: timedelta


@dataclass(frozen=True)
class ContinuityResult:
    """Continuity: zit er een GAT in de tijdreeks van een metric dat groter
    is dan de verwachte polling-cadans -- OOK als de LAATSTE waarde zelf
    nog niet stale genoeg is om als HealthStatus.STALE te tellen. Kern-
    onderscheid met staleness: evaluate_staleness()/check_source() kijken
    alleen naar "hoe oud is de laatste succesvolle pull NU", niet naar of
    er verderop in de reeks een periode is overgeslagen. Een reeks met
    waarden in januari, februari, [gat], juni is voor staleness prima
    (juni is vers) maar voor continuity niet."""

    source: str
    metric_key: str
    expected_cadence: timedelta
    gaps: tuple[ContinuityGap, ...]
    checked_at: datetime

    @property
    def has_gap(self) -> bool:
        return bool(self.gaps)


def evaluate_continuity(
    source: str,
    metric_key: str,
    timestamps: list[datetime],
    expected_cadence: timedelta,
    tolerance_factor: float = 1.5,
    now: datetime | None = None,
) -> ContinuityResult:
    """Zuiver deterministisch, geen I/O. `timestamps` is typisch de
    source_time van elke historische Claim voor deze metric (uit
    storage.schema.load_latest_claims). `tolerance_factor` geeft normale
    jitter in release-datums speling (zelfde gedachte als MAX_AGE's eigen
    marge boven de kale cadans) -- pas een gat >
    expected_cadence * tolerance_factor telt mee, niet elke kleine
    afwijking."""
    now = now or datetime.now(timezone.utc)
    ordered = sorted(timestamps)
    threshold = expected_cadence * tolerance_factor
    gaps = tuple(
        ContinuityGap(before=a, after=b, gap=b - a)
        for a, b in zip(ordered, ordered[1:])
        if (b - a) > threshold
    )
    return ContinuityResult(
        source=source, metric_key=metric_key, expected_cadence=expected_cadence, gaps=gaps, checked_at=now,
    )


class QualityStatus(str, Enum):
    """Roadmap 1.3, statusmodel HEALTHY/DEGRADED/INVALID. Complementair aan
    HealthStatus, GEEN vervanging ervan: HealthStatus blijft de bron-
    freshness/bereikbaarheid-status (A.3, ongewijzigd, overal in de
    codebase gebruikt). QualityStatus is het rollup-oordeel over de
    KWALITEIT van één specifieke claim/metric, samengesteld uit de vier
    checks hierboven plus (optioneel) de bron se HealthStatus. Zie
    docs/architecture.md ("Ontwerpkeuzes") voor waarom dit bewust geen
    hernoeming van HealthStatus is."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    INVALID = "invalid"


_QUALITY_SEVERITY_ORDER = {QualityStatus.HEALTHY: 0, QualityStatus.DEGRADED: 1, QualityStatus.INVALID: 2}

# Vertaling van een bron se HealthStatus naar QualityStatus -- GEEN perfecte
# 1-op-1-mapping (zie docs/architecture.md): STALE/UNKNOWN landen allebei op
# DEGRADED ("bruikbaar maar niet perfect" resp. "nog geen oordeel mogelijk,
# geen valse geruststelling als HEALTHY"), UNREACHABLE op INVALID bij gebrek
# aan een vierde bucket -- een bewust geaccepteerde onvolkomenheid, geen
# verborgen aanname.
_SOURCE_STATUS_TO_QUALITY = {
    HealthStatus.OK: QualityStatus.HEALTHY,
    HealthStatus.UNKNOWN: QualityStatus.DEGRADED,
    HealthStatus.STALE: QualityStatus.DEGRADED,
    HealthStatus.UNREACHABLE: QualityStatus.INVALID,
}


def rollup_quality_status(
    *,
    source_status: HealthStatus | None = None,
    completeness: CompletenessResult | None = None,
    validity: ValidityResult | None = None,
    consistency: ConsistencyResult | None = None,
    continuity: ContinuityResult | None = None,
) -> QualityStatus:
    """Worst-of over alle MEEGEGEVEN signalen (elk optioneel -- niet elke
    check is voor elke metric zinvol/beschikbaar, bijv. validity zonder een
    DD-gevalideerd bereik, of consistency zonder een afgeleide claim). Geen
    gewogen score, geen aannames over welk signaal zwaarder telt dan een
    ander -- zelfde "worst-of, geen fancy weging"-patroon als
    health.system_health's _worst(). Geen enkel signaal meegegeven is een
    aanroepfout (ValueError), geen HEALTHY-by-default: een rollup zonder
    input zou een valse geruststelling zijn, zie system_health.py's
    zelfde principe bij een lege componentenlijst."""
    signals: list[QualityStatus] = []
    if source_status is not None:
        signals.append(_SOURCE_STATUS_TO_QUALITY[source_status])
    if completeness is not None:
        signals.append(QualityStatus.HEALTHY if completeness.is_complete else QualityStatus.DEGRADED)
    if validity is not None:
        signals.append(QualityStatus.HEALTHY if validity.is_valid else QualityStatus.INVALID)
    if consistency is not None:
        signals.append(QualityStatus.HEALTHY if consistency.is_consistent else QualityStatus.INVALID)
    if continuity is not None:
        signals.append(QualityStatus.HEALTHY if not continuity.has_gap else QualityStatus.DEGRADED)
    if not signals:
        raise ValueError("rollup_quality_status: geef minstens één signaal mee -- een rollup zonder input is geen oordeel")
    return max(signals, key=lambda s: _QUALITY_SEVERITY_ORDER[s])
