"""
notifications.py
Roadmap 1.11 (Scheduler & Runtime), deel "actieve fail-loud-notificatie"
-- de ontbrekende helft van roadmap 1.7.

1.7 leverde `health/system_health.py::system_health()`: een functie die de
status per component TERUGGEEFT. Die is PULL-only en had tot nu toe geen
enkele aanroeper buiten de tests -- iemand moest 'm handmatig draaien.
Zolang DD elke cyclus zelf startte was dat genoeg; vanaf T₀ draait er
niemand meer handmatig, dus een stille kapotte databron blijft dan
onopgemerkt tot het track record al gaten heeft. Dat is precies het
faalscenario dat A.3's "fail loudly, not silently" moest voorkomen, maar
dan een laag hoger: niet "de trigger-laag zwijgt", maar "niemand kijkt".

Twee bewuste keuzes:

- **Het notificatiekanaal is dependency-injected**, zelfde patroon als
  `qc.qc.default_llm_review()`'s `client`-parameter en `system_health()`'s
  `sources`/`domains`. `run_daily()` weet niet of er een e-mail, een
  webhook of alleen een logregel uitgaat. Reden: DD heeft nog geen kanaal
  gekozen, en een half-geraden SMTP-configuratie in de repo is erger dan
  een expliciet lege plek.
- **`log_notifier` is de default, maar is NIET echt "loud".** Een logregel
  op een VPS die niemand leest is technisch een notificatie en praktisch
  stilte. Hij staat hier als veilige default zodat `run_daily()` nooit
  crasht op een ontbrekend kanaal, niet als eindoplossing --
  `webhook_notifier` is wat er op de VPS hoort te draaien.

Drempels worden hier NIET opnieuw gedefinieerd: "is deze bron te lang
stil" wordt al per bron beantwoord door de `max_age` in de Source
Registry (1.4), via `system_health()`. Een eigen "2 dagen"-constante hier
zou een tweede, concurrerende waarheid introduceren naast een register
dat er speciaal voor bestaat.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable, Literal

from health.data_health import HealthStatus
from health.system_health import SystemHealthReport

logger = logging.getLogger(__name__)

Severity = Literal["warning", "critical"]

# Welke component-status welke notificatie-ernst oplevert. STALE is een
# waarschuwing (de bron bestaat nog, hij is alleen te oud), UNREACHABLE is
# kritiek (de pull zelf lukt niet meer). UNKNOWN is BEWUST geen van beide
# als het de enige afwijking is: een component die nog nooit gedraaid heeft
# is normaal op dag 1 en zou anders elke eerste run een valse melding geven.
_STATUS_SEVERITY: dict[HealthStatus, Severity | None] = {
    HealthStatus.OK: None,
    HealthStatus.UNKNOWN: None,
    HealthStatus.STALE: "warning",
    HealthStatus.UNREACHABLE: "critical",
}


@dataclass(frozen=True)
class Notification:
    """Kanaal-onafhankelijk. `subject` is één regel (past in een
    push-melding of e-mail-onderwerp), `body` mag meerdere regels."""

    severity: Severity
    subject: str
    body: str

    def as_text(self) -> str:
        return f"[{self.severity.upper()}] {self.subject}\n\n{self.body}"


Notifier = Callable[[Notification], None]


def build_notification(result, health: SystemHealthReport | None) -> Notification | None:
    """Beslist of deze cyclus iets te melden heeft. Geeft `None` terug als
    alles in orde is -- een dagelijkse "alles goed"-melding traint je
    binnen twee weken om notificaties te negeren, en dan is de melding die
    er wél toe doet ook onzichtbaar.

    Getriggerde metrics zijn op zichzelf GEEN reden om te melden: dat is
    het systeem dat doet waarvoor het gebouwd is, en het hoort bij het
    alert-mechanisme (5.3, post-T₀), niet bij fail-loud. Ze worden wel in
    de body vermeld als er toch al een melding uitgaat, omdat een trigger
    tijdens een storing relevante context is.

    `result` is een `runtime.daily.DailyRunResult` (niet getypeerd om een
    cirkelvormige import te vermijden -- daily.py importeert deze module)."""
    lines: list[str] = []
    severity: Severity | None = None

    def escalate(candidate: Severity) -> None:
        nonlocal severity
        if candidate == "critical" or severity is None:
            severity = candidate

    crashed = [o for o in result.outcomes if o.status == "crashed"]
    failed = [o for o in result.outcomes if o.status == "failed"]
    deep_dive_failures = [o for o in result.outcomes if o.deep_dive_error]
    missed = list(getattr(result, "missed_days", []) or [])

    if missed:
        # Een dag zonder enkele succesvolle run betekent een gat in de
        # reeks, en een gat maakt de kalibratie ongeldig. Altijd kritiek --
        # dit is het faalscenario waar het hele forward-testing-plan op
        # stukloopt, en het valt nergens anders op.
        escalate("critical")
        lines.append(f"Dagen zonder enkele succesvolle monitoring-run: {', '.join(missed)}")

    if crashed:
        escalate("critical")
        lines.append("Agents met een onverwachte fout (bug, geen databron-probleem):")
        lines.extend(f"  - {o.domain}: {o.error}" for o in crashed)

    if failed:
        # Alle agents tegelijk mislukt wijst op iets gedeelds (netwerk, DNS,
        # API-key, rate limit) i.p.v. één stukke bron -- dat verdient een
        # zwaardere melding dan een enkele hapering.
        escalate("critical" if len(failed) == len(result.outcomes) else "warning")
        lines.append("Agents waarvan de datapull mislukte:")
        lines.extend(f"  - {o.domain}: {o.error}" for o in failed)

    if deep_dive_failures:
        # Apart van `failed`: monitoring kan prima geslaagd zijn. Zonder
        # deze regel kan de deep-dive-helft elke dag stukgaan terwijl cron
        # exit 0 teruggeeft en er nooit een melding uitgaat.
        escalate("warning")
        lines.append("Deep-dives die mislukten (de monitoring-data is wel binnen):")
        lines.extend(f"  - {o.domain}: {o.deep_dive_error}" for o in deep_dive_failures)

    unhealthy = [c for c in (health.components if health is not None else []) if _STATUS_SEVERITY.get(c.status) is not None]
    if unhealthy:
        for component in unhealthy:
            escalate(_STATUS_SEVERITY[component.status])  # type: ignore[arg-type]
        lines.append("Componenten die aandacht vragen:")
        lines.extend(
            f"  - {c.component}: {c.status.value}" + (f" ({c.detail})" if c.detail else "")
            for c in unhealthy
        )

    if severity is None:
        return None

    triggered = [o for o in result.outcomes if o.triggers]
    if triggered:
        lines.append("Triggers in dezelfde cyclus:")
        lines.extend(f"  - {o.domain}: {len(o.triggers)}" for o in triggered)

    subject = f"Market Intelligence {result.event_id}: {severity}"
    return Notification(severity=severity, subject=subject, body="\n".join(lines))


def log_notifier(notification: Notification) -> None:
    """Veilige default: schrijft naar de stdlib-logger. Zie de
    moduledocstring -- dit is geen vervanging voor een echt kanaal."""
    level = logging.CRITICAL if notification.severity == "critical" else logging.WARNING
    logger.log(level, notification.as_text())


def webhook_notifier(url: str, timeout: int = 10) -> Notifier:
    """POST't de notificatie als JSON. Generiek gehouden zodat het werkt met
    wat DD ook kiest (ntfy.sh, een Telegram-bot, Discord, Slack) zonder dat
    deze module een specifieke provider hardcodeert.

    Gebruikt `requests`, dat al een dependency is van de domain agents --
    geen nieuwe (en zeker geen gecompileerde) afhankelijkheid, conform
    CLAUDE.md-regel 2.

    Een mislukte notificatie mag de cyclus NOOIT laten crashen: de data is
    dan al binnen en opgeslagen, en die weggooien omdat een webhook 503
    geeft zou de schade vergroten in plaats van beperken. De fout gaat naar
    de log -- de laatste vangnet-laag."""
    import requests

    def notify(notification: Notification) -> None:
        payload = {
            "severity": notification.severity,
            "subject": notification.subject,
            "body": notification.body,
            "text": notification.as_text(),
        }
        try:
            response = requests.post(
                url, data=json.dumps(payload), headers={"Content-Type": "application/json"}, timeout=timeout
            )
            # `requests.post` gooit NIET bij 4xx/5xx. Zonder deze check zou
            # een webhook die elke keer 500 teruggeeft als succes tellen, en
            # dan is de fail-loud-laag stil zonder dat iemand het weet --
            # precies het probleem dat deze module moet oplossen.
            response.raise_for_status()
        except Exception as e:  # noqa: BLE001 -- zie docstring: nooit de cyclus laten vallen
            logger.error("Notificatie kon niet verstuurd worden (%s): %s", e, notification.as_text())

    return notify
