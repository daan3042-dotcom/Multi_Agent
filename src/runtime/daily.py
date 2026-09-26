"""
daily.py
Roadmap 1.11 (Scheduler & Runtime) -- de dagelijkse cyclus, en daarmee de
aanroeper waar drie eerdere secties op wachtten:

- **1.7's idempotency** (`event_id` + `has_successful_run`) is gebouwd maar
  werd door geen enkele agent gebruikt, omdat er geen orchestratielaag was
  die cycli van een stabiele identifier voorzag. Die is dit.
- **1.7's `system_health()`** was pull-only zonder aanroeper. Wordt hier
  na elke cyclus gedraaid en gekoppeld aan een notificatie
  (`runtime/notifications.py`).
- **1.8's manager-dispatch** groepeerde triggers per domein maar werd
  alleen in tests aangeroepen. Bepaalt hier welke deep-dives draaien.

WAAROM DIT BESTAAT (roadmap deel A, fase 0): LLM-agents zijn niet eerlijk
te backtesten, dus het track record moet vooruit worden opgebouwd. Een
forward test die van handmatig draaien afhangt krijgt gaten, en gaten
maken de kalibratie ongeldig -- als de moeilijke weken ontbreken omdat
niemand eraan dacht, ziet het track record er systematisch beter uit dan
het is. Deze module bestaat om die gaten te voorkomen, niet om werk te
besparen.

## Ontwerpkeuzes

**`event_id` is de UTC-datum, niet een UUID.** De eenheid van herhaling is
"is de cyclus van DEZE DAG al verwerkt". Met een UUID per aanroep zou elke
retry een nieuw id krijgen en zou 1.7's dedup nooit aanslaan -- precies het
scenario waar hij voor bedoeld is (cron vuurt twee keer, machine start
opnieuw op halverwege, DD draait 'm handmatig na een storing). Een
datum-gebaseerd id maakt een herhaling herkenbaar als herhaling.

**Eén stukke agent stopt de cyclus niet.** Elke agent draait in zijn eigen
try/except. Anders zou een bug in de commodity agent de monetary-reeks
laten ontbreken, en dat is een gat in de data van een agent die het prima
deed. Fouten worden verzameld en gerapporteerd, niet geslikt -- zie
`AgentOutcome.status`.

**Deep-dives zijn OPT-IN via een meegegeven `client`.** Zonder client
draait alleen monitoring: data binnenhalen, claims opslaan, triggers
vastleggen. Reden: monitoring is goedkoop en deterministisch, deep-dives
kosten geld per aanroep en draaien straks onbeheerd. De kosten van een
onbeheerd systeem horen een expliciete keuze van de aanroeper te zijn, geen
bijwerking van "de cron staat aan". De triggers blijven hoe dan ook
opgeslagen, dus een later gedraaide deep-dive mist niets.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Literal

from agents.base import AlreadyProcessedError
from contract.output_contract import DomainOutput
from health.system_health import SystemHealthReport, sources_from_registry, system_health
from manager.manager import DispatchPlan, dispatch
from runtime.notifications import Notification, Notifier, build_notification, log_notifier
from storage.schema import (
    has_successful_run,
    load_monitoring_claims,
    load_trigger_events_for_day,
    record_trigger_event,
)
from triggers.trigger_engine import TriggerEvent

logger = logging.getLogger(__name__)

AgentStatus = Literal["ok", "skipped", "failed", "crashed"]


@dataclass(frozen=True)
class AgentSpec:
    """Eén domain agent zoals de runner 'm ziet. Bewust géén import van de
    agent-modules in de dataclass zelf -- `default_agents()` doet dat, zodat
    een test een eigen, verzonnen agentlijst kan meegeven zonder dat er ook
    maar één echte databron in beeld komt (zelfde aanpak als de bestaande
    tests, die fetch-functies injecteren)."""

    domain: str
    monitor: Callable[..., tuple[DomainOutput | None, list[TriggerEvent]]]
    deep_dive: Callable[..., DomainOutput] | None = None


@dataclass(frozen=True)
class AgentOutcome:
    """`status` onderscheidt drie soorten niet-goed, omdat ze om verschillend
    handelen vragen:

    - `failed`   -- de datapull mislukte (bron plat, rate limit, API-key).
                    Het systeem werkt, de buitenwereld niet mee. Er is al
                    een data-health-trigger voor aangemaakt door
                    run_monitoring().
    - `crashed`  -- een onverwachte exception. Dit is een bug bij ons en
                    hoort altijd kritiek gemeld te worden.
    - `skipped`  -- deze cyclus was al succesvol verwerkt (1.7). Geen fout:
                    het bewijs dat de idempotency werkt.

    `deep_dive_error` staat LOS van `error`: een mislukte deep-dive mag het
    oorspronkelijke monitoring-probleem niet overschrijven. Zonder die
    scheiding rapporteert de nachtelijke melding "de datapull mislukte:
    LLM down" -- de verkeerde diagnose, precies wanneer er niemand is om
    het te corrigeren."""

    domain: str
    status: AgentStatus
    triggers: list[TriggerEvent] = field(default_factory=list)
    error: str | None = None
    deep_dive_ran: bool = False
    deep_dive_error: str | None = None
    claims: list = field(default_factory=list)


@dataclass
class DailyRunResult:
    event_id: str
    started_at: datetime
    outcomes: list[AgentOutcome] = field(default_factory=list)
    plan: DispatchPlan | None = None
    health: SystemHealthReport | None = None
    notification: Notification | None = None
    missed_days: list[str] = field(default_factory=list)

    @property
    def all_triggers(self) -> list[TriggerEvent]:
        return [t for o in self.outcomes for t in o.triggers]

    @property
    def succeeded(self) -> list[str]:
        return [o.domain for o in self.outcomes if o.status == "ok"]

    @property
    def has_problems(self) -> bool:
        """`skipped` telt NIET als probleem -- dat is idempotency die doet
        wat hij moet doen. Een mislukte deep-dive telt WEL, ook als
        monitoring slaagde: anders kan de deep-dive-helft van het systeem
        elke dag falen terwijl cron exit 0 teruggeeft."""
        if any(o.status in ("failed", "crashed") for o in self.outcomes):
            return True
        if any(o.deep_dive_error for o in self.outcomes):
            return True
        return bool(self.missed_days)

    def summary(self) -> str:
        parts = [f"{o.domain}={o.status}" for o in self.outcomes]
        return f"{self.event_id}: " + ", ".join(parts) + f" | triggers={len(self.all_triggers)}"


def daily_event_id(moment: datetime | date | None = None) -> str:
    """Stabiel per kalenderdag (UTC), zodat een tweede aanroep op dezelfde
    dag door 1.7's dedup wordt herkend. Zie de moduledocstring voor waarom
    dit geen UUID is."""
    if moment is None:
        moment = datetime.now(timezone.utc)
    day = moment.date() if isinstance(moment, datetime) else moment
    return f"daily:{day.isoformat()}"


def default_agents() -> list[AgentSpec]:
    """De vijf agents met een eigen live databron. `equity_agent` ontbreekt
    bewust: dat is een adapter zonder eigen fetch (roadmap 2.3) -- hij wordt
    gevoed door een afgeronde `analyst_agent.ai`-run, niet door een
    dagelijkse poll, en heeft hier dus niets te doen.

    De import staat IN de functie, niet bovenaan de module: zo kan een test
    `run_daily()` aanroepen met eigen agents zonder de echte agent-modules
    (en hun `requests`-imports en API-key-lookups) te laden."""
    from agents import commodity_agent, currency_agent, financial_agent, monetary_policy_agent, sector_agent

    return [
        AgentSpec("monetary_policy", monetary_policy_agent.monitor, monetary_policy_agent.deep_dive),
        AgentSpec("currency", currency_agent.monitor, currency_agent.deep_dive),
        AgentSpec("financial", financial_agent.monitor, financial_agent.deep_dive),
        AgentSpec("sector", sector_agent.monitor, sector_agent.deep_dive),
        AgentSpec("commodity", commodity_agent.monitor, commodity_agent.deep_dive),
    ]


def _run_one_agent(conn, spec: AgentSpec, now: datetime, event_id: str) -> AgentOutcome:
    try:
        output, triggers = spec.monitor(conn, now=now, event_id=event_id)
    except AlreadyProcessedError:
        return AgentOutcome(domain=spec.domain, status="skipped")
    except sqlite3.IntegrityError as e:
        # De dedup-index op agent_runs sloeg aan terwijl de applicatieve
        # check dat niet deed: twee runs draaiden tegelijk (cron vuurde
        # opnieuw terwijl de vorige nog liep) en beide kwamen langs
        # has_successful_run() voordat een van beide zijn agent_run
        # wegschreef. Dit is de databaselaag die precies doet waarvoor hij
        # er is -- geen bug, dus geen `crashed` en geen kritieke melding.
        if "agent_runs" in str(e):
            logger.warning("%s: gelijktijdige run gedetecteerd via de dedup-index (%s)", spec.domain, e)
            return AgentOutcome(domain=spec.domain, status="skipped")
        return AgentOutcome(domain=spec.domain, status="crashed", error=f"{type(e).__name__}: {e}")
    except Exception as e:  # noqa: BLE001 -- zie moduledocstring: één stukke agent stopt de cyclus niet
        return AgentOutcome(domain=spec.domain, status="crashed", error=f"{type(e).__name__}: {e}")

    if output is None:
        # run_monitoring() geeft (None, [data-health-trigger]) terug als de
        # pull mislukte. De trigger is er al; wij classificeren alleen.
        health_triggers = [t for t in triggers if "bron" in t.reason or "data" in t.reason.lower()]
        error = (health_triggers or triggers or [None])[0]
        return AgentOutcome(
            domain=spec.domain,
            status="failed",
            triggers=triggers,
            error=error.reason if error is not None else "datapull mislukt zonder nadere reden",
        )

    return AgentOutcome(domain=spec.domain, status="ok", triggers=triggers, claims=list(output.claims))


def _persist_triggers(conn, result: DailyRunResult) -> None:
    """Roadmap 1.2 (`trigger_events`) -- tot 1.11 werd `record_trigger_event()`
    alleen in tests aangeroepen, dus vuurden er triggers die nergens werden
    vastgelegd. Dat is precies de reeks die 1.5/4.2 straks nodig hebben om
    drempels te kalibreren ("hoe vaak vuurde deze regel, en volgde er iets
    betekenisvols"). Zonder deze stap bouwt het systeem zes maanden lang een
    track record op met een gat op de belangrijkste plek.

    Wordt alleen aangeroepen voor triggers uit DEZE cyclus (`status` ok of
    failed); een `skipped` agent heeft zijn triggers de vorige keer al
    opgeslagen."""
    batch_id = result.plan.batch_id if result.plan else None
    for outcome in result.outcomes:
        for trigger in outcome.triggers:
            record_trigger_event(
                conn,
                domain=trigger.domain,
                triggered_at=trigger.triggered_at,
                reason=trigger.reason,
                severity=trigger.severity,
                metric_key=trigger.metric_key,
                observed_value=trigger.observed_value,
                threshold=trigger.threshold,
                dispatch_batch_id=batch_id,
            )


def _escalations_for_deep_dives(conn, result: DailyRunResult, day) -> dict[str, list[TriggerEvent]]:
    """Welke domeinen krijgen een deep-dive.

    Twee bronnen, en de tweede is niet optioneel: op een HERHAALDE run van
    dezelfde dag is monitoring `skipped` en zijn er dus geen triggers meer
    in het geheugen. Zonder de opgeslagen triggers erbij te halen zou een
    deep-dive die de eerste keer mislukte (LLM plat, geen API-key, proces
    gedood) nooit meer opnieuw draaien -- een permanent gat, en uitgerekend
    in het scenario dat de aanbevolen werkwijze is (cron zonder
    `--deep-dives`, later met de hand).

    Domeinen waarvan de datapull mislukte krijgen GEEN deep-dive: er zijn
    dan geen claims om te duiden, dus dat zou een betaalde LLM-call zijn om
    over niets te schrijven -- en die call zou de dag vervolgens als
    "deep-dive gedaan" afstempelen."""
    escalations: dict[str, list[TriggerEvent]] = {}
    failed_domains = {o.domain for o in result.outcomes if o.status in ("failed", "crashed")}

    if result.plan:
        for domain, triggers in result.plan.escalations.items():
            if domain not in failed_domains:
                escalations[domain] = list(triggers)

    for outcome in result.outcomes:
        if outcome.status != "skipped" or outcome.domain in escalations:
            continue
        stored = load_trigger_events_for_day(conn, day, domain=outcome.domain)
        if stored:
            escalations[outcome.domain] = stored

    return escalations


def run_daily(
    conn,
    agents: list[AgentSpec] | None = None,
    now: datetime | None = None,
    client=None,
    notifier: Notifier | None = None,
    event_id: str | None = None,
) -> DailyRunResult:
    """Eén volledige dagelijkse cyclus. Idempotent per kalenderdag.

    `client` is de Anthropic-client voor deep-dives. Zonder client draait
    alleen monitoring -- zie de moduledocstring over kosten.

    `notifier` krijgt alleen een melding als er iets mis is
    (`notifications.build_notification` beslist dat). Default is
    `log_notifier`, dat bewust NIET echt luid is; zet op de VPS een
    `webhook_notifier` in.

    Geeft altijd een `DailyRunResult` terug, ook bij falen -- de aanroeper
    (cron) hoeft geen exceptions af te vangen om te weten wat er gebeurd is.
    """
    now = now or datetime.now(timezone.utc)
    event_id = event_id or daily_event_id(now)
    agents = agents if agents is not None else default_agents()
    notifier = notifier or log_notifier

    result = DailyRunResult(event_id=event_id, started_at=now)

    for spec in agents:
        result.outcomes.append(_run_one_agent(conn, spec, now, event_id))

    # Alles hierna is orchestratie op al-gecommitte data. Eén exception hier
    # zou een run waarvan het echte werk gelukt is laten eindigen als een
    # stacktrace -- en op een onbeheerde machine is dat niet te
    # onderscheiden van "er is niets gebeurd". Vandaar de brede vangnetten:
    # ze verbergen niets (alles gaat naar de log en naar het resultaat),
    # ze voorkomen alleen dat een randgeval de dag weggooit.
    try:
        result.plan = dispatch(result.all_triggers, now=now)
        _persist_triggers(conn, result)
    except Exception as e:  # noqa: BLE001
        logger.error("Triggers konden niet opgeslagen worden: %s: %s", type(e).__name__, e)

    if client is not None:
        try:
            _run_deep_dives(conn, agents, result, client, now, event_id)
        except Exception as e:  # noqa: BLE001
            logger.error("Deep-dive-fase afgebroken: %s: %s", type(e).__name__, e)

    try:
        result.missed_days = _missed_days(conn, agents, now)
    except Exception as e:  # noqa: BLE001
        logger.error("Gatendetectie mislukt: %s: %s", type(e).__name__, e)

    try:
        result.health = system_health(
            conn,
            sources=sources_from_registry(conn),
            domains=[spec.domain for spec in agents],
            now=now,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("System health kon niet bepaald worden: %s: %s", type(e).__name__, e)

    try:
        result.notification = build_notification(result, result.health)
    except Exception as e:  # noqa: BLE001
        logger.error("Notificatie kon niet opgebouwd worden: %s: %s", type(e).__name__, e)

    if result.notification is not None:
        _notify_safely(notifier, result.notification)

    return result


def _missed_days(conn, agents: list[AgentSpec], now: datetime, lookback: int = 7) -> list[str]:
    """Kijkt terug of er dagen zijn zonder ENKELE succesvolle monitoring-run.

    Dekt gedeeltelijk het faalscenario dat alle andere meldingen missen: een
    run die nooit gebeurde. Elke melding in dit systeem wordt verstuurd
    DOOR een draaiende run, dus als cron uitstaat, de venv stuk is of de
    VPS uit was, is er geen run, geen melding, en ziet stilte eruit als een
    gezonde dag. De eerstvolgende run die wél draait, meldt het gat alsnog.

    BEPERKING, bewust: dit vindt een gat pas als er daarna weer een run
    draait. Als de machine drie weken uit staat, hoort niemand iets. Een
    echte dead man's switch hoort BUITEN dit systeem te draaien (een
    externe heartbeat-ping die alarmeert bij uitblijven) -- staat als
    openstaand punt bij 1.11 in de roadmap."""
    if not agents:
        return []
    today = now.date()
    missed: list[str] = []
    for offset in range(1, lookback + 1):
        day = today - timedelta(days=offset)
        ran = any(
            has_successful_run(conn, spec.domain, "monitoring", daily_event_id(day))
            for spec in agents
        )
        if not ran:
            missed.append(day.isoformat())
    # Alleen melden als er ook ECHT al eens gedraaid is -- op dag 1 is de
    # hele week leeg, en dat is geen storing maar een nieuw systeem.
    if len(missed) == lookback:
        return []
    return sorted(missed)


def _notify_safely(notifier: Notifier, notification: Notification) -> None:
    """Een mislukte notificatie mag de cyclus NOOIT laten crashen. Op dit
    punt is de data al opgehaald, geparsed en gecommit; als `run_daily()`
    hier alsnog een exception doorlaat, eindigt de cron-run met een
    stacktrace terwijl het echte werk gelukt is -- en dan lijkt een geslaagde
    dag op een mislukte. `webhook_notifier` vangt zijn eigen fouten al af,
    maar een zelfgeschreven notifier hoeft dat niet te doen; deze laag maakt
    het een eigenschap van de runner in plaats van een belofte per kanaal.

    De fout zelf verdwijnt niet: hij gaat naar de log, samen met de
    notificatie die niet verstuurd kon worden -- anders zou uitgerekend de
    fail-loud-laag stil falen."""
    try:
        notifier(notification)
    except Exception as e:  # noqa: BLE001 -- zie docstring
        logger.error(
            "Notificatie kon niet afgeleverd worden (%s: %s). Inhoud:\n%s",
            type(e).__name__, e, notification.as_text(),
        )


def _replace_outcome(result: DailyRunResult, domain: str, **changes) -> None:
    """`AgentOutcome` is frozen, dus een wijziging is een vervanging.
    Aparte helper zodat elke plek dezelfde velden meeneemt -- eerder werd
    hier `error` per ongeluk overschreven met de deep-dive-fout, waardoor
    de melding de verkeerde oorzaak noemde."""
    for i, outcome in enumerate(result.outcomes):
        if outcome.domain != domain:
            continue
        result.outcomes[i] = replace(outcome, **changes)
        return


def _run_deep_dives(conn, agents, result: DailyRunResult, client, now, event_id: str) -> None:
    """Draait een deep-dive per geëscaleerd domein, in dezelfde
    fout-isolatie als monitoring: een mislukte deep-dive mag de andere niet
    meeslepen. De claims zijn op dit punt al opgeslagen, dus er gaat geen
    data verloren als dit deel faalt.

    De `event_id` krijgt geen eigen achtervoegsel -- `has_successful_run`
    kijkt naar (domain, mode, event_id), en mode verschilt al. Zelfde id
    dus, andere mode.

    Welke claims erin gaan is kritiek: `load_monitoring_claims()`, dus
    alleen de LAATSTE monitoring-cyclus. `load_latest_claims()` zou de hele
    historie teruggeven, en omdat `run_deep_dive()` de aangeleverde claims
    opnieuw wegschrijft, verdubbelt dat de claims-tabel elke dag (gemeten:
    255 rijen na 8 dagen)."""
    by_domain = {spec.domain: spec for spec in agents}
    outcomes_by_domain = {o.domain: o for o in result.outcomes}
    escalations = _escalations_for_deep_dives(conn, result, now.date())

    for domain, triggers in escalations.items():
        spec = by_domain.get(domain)
        if spec is None or spec.deep_dive is None:
            continue

        # Eerst de claims van DEZE cyclus; alleen op het retry-pad (monitoring
        # overgeslagen) uit de database, want dan is er geen verse output.
        outcome = outcomes_by_domain.get(domain)
        claims = list(outcome.claims) if outcome and outcome.claims else load_monitoring_claims(conn, domain)
        if not claims:
            logger.warning("%s: deep-dive overgeslagen, geen monitoring-claims om te duiden", domain)
            continue
        try:
            spec.deep_dive(conn, client, claims, triggers, now=now, event_id=event_id)
        except AlreadyProcessedError:
            # Deze deep-dive is voor dit event_id al succesvol gedraaid --
            # dat is "gedaan", niet "niet gedaan".
            _replace_outcome(result, domain, deep_dive_ran=True)
            continue
        except Exception as e:  # noqa: BLE001 -- zie docstring
            _replace_outcome(result, domain, deep_dive_ran=False, deep_dive_error=f"{type(e).__name__}: {e}")
            continue
        _replace_outcome(result, domain, deep_dive_ran=True, deep_dive_error=None)
