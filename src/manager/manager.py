"""
manager.py
Stap A.6, laatste stap van het fundament: dispatch-logica die bepaalt welke
domain agent(s) escaleren naar deep-dive mode bij een trigger, inclusief
gelijktijdige triggers over meerdere domeinen heen (bijv. een Fed-besluit
raakt monetary + currency + equity tegelijk). Coördineert alles uit A.1-A.5:
neemt TriggerEvents (A.4, eventueel inclusief data-health-triggers uit A.3)
en groepeert ze tot een DispatchPlan die de synthesizer (sectie B.3, F) later
gebruikt om te weten welke deep-dives bij elkaar horen.

Bewust GEEN LLM hier -- dispatchen ("welke agent(s) triggeren dit domein")
is nog steeds pure regelbepaling. De LLM-synthese gebeurt pas in de
deep-dive-mode van de domain agents zelf (buiten scope van dit fundament,
zie sectie B) en in de synthesizer (sectie F).

Zie docs/architecture.md ("LLM-taken-tabel", roadmap 1.8) voor het
systeembrede overzicht van welk component wel/niet een LLM gebruikt en
waarom -- dit bestand is daar één rij van, niet de plek om dat overzicht
te herhalen.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from triggers.trigger_engine import TriggerEvent


@dataclass
class DispatchPlan:
    batch_id: str
    generated_at: datetime
    escalations: dict[str, list[TriggerEvent]] = field(default_factory=dict)

    @property
    def domains(self) -> list[str]:
        return list(self.escalations.keys())

    @property
    def is_simultaneous(self) -> bool:
        """True als meer dan één domein in dezelfde dispatch-batch escaleert
        -- het signaal dat de synthesizer nodig heeft om te weten of losse
        deep-dives naast elkaar gelegd moeten worden (stappenplan B.3)."""
        return len(self.escalations) > 1

    def highest_severity(self, domain: str) -> str | None:
        events = self.escalations.get(domain)
        if not events:
            return None
        order = {"low": 0, "medium": 1, "high": 2}
        return max(events, key=lambda e: order[e.severity]).severity


def dispatch(trigger_events: list[TriggerEvent], now: datetime | None = None) -> DispatchPlan:
    """Groepeert een lijst TriggerEvents (typisch: het resultaat van één
    monitoring-cyclus over alle domain agents) per domein tot een
    DispatchPlan. Elke trigger in de invoerlijst escaleert -- de beslissing
    "is dit significant genoeg" is al door de trigger-laag (A.4) genomen;
    de manager oordeelt daar niet opnieuw over, hij coördineert alleen."""
    escalations: dict[str, list[TriggerEvent]] = {}
    for event in trigger_events:
        escalations.setdefault(event.domain, []).append(event)
    return DispatchPlan(
        batch_id=str(uuid.uuid4()),
        generated_at=now or datetime.now(timezone.utc),
        escalations=escalations,
    )
