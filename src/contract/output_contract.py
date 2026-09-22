"""
output_contract.py
De vorm waar ELKE domain agent (monetary policy, currency, equity, ...) zich
aan houdt, ongeacht wat voor databron of analysemethode erachter zit. Dit is
stap A.1 uit het stappenplan -- expliciet eerst, omdat alles hierna (database-
schema, trigger-laag, QC, manager-dispatch, synthesizer) op deze vorm
vertrouwt.

Zelfde principe als de lineage-aanpak in analyst_agent.ai (zie
lineage.py::build_lineage_manifest): elk cijfer moet herleidbaar zijn tot een
bron. Hier generaliseren we dat van "een los manifest-item per verified
metric" naar "de enige eenheid waarin een domain agent iets beweert" --
inclusief een confidence-score en tijdstempel, die lineage.py niet nodig had
(een los rapport op een moment) maar een doorlopend, onbeheerd systeem wel
(claims verouderen, en de synthesizer moet later kunnen wegen welke claim
zekerder is dan een andere, zie stappenplan-sectie F.2).

Een Claim zonder bron of zonder waarde is per definitie ongeldig -- net als
lineage.py's `add()` die een item zonder value/source gewoon overslaat, maar
hier expliciet als fout behandeld (ValueError) in plaats van stilzwijgend
overgeslagen: een domain agent die dit contract schendt moet meteen zichtbaar
breken, niet een gat laten vallen dat pas bij de synthesizer opvalt.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Mode(str, Enum):
    """De twee bedrijfsmodi die elke domain agent kent (zie stappenplan-
    sectie B.1): MONITORING is goedkoop en draait continu op de achtergrond,
    DEEP_DIVE is de duurdere LLM-synthese die pas draait na een trigger."""

    MONITORING = "monitoring"
    DEEP_DIVE = "deep_dive"


class Confidence(float, Enum):
    """Vaste, herbruikbare confidence-niveaus in plaats van willekeurige
    floats per domain agent -- houdt de latere Bayesiaanse weging in de
    synthesizer (stappenplan F.2) vergelijkbaar tussen domeinen. Een domain
    agent mag ook een eigen float tussen 0 en 1 opgeven als geen van deze
    precies past; dit zijn alleen de aanbevolen ankerpunten."""

    LOW = 0.3
    MEDIUM = 0.6
    HIGH = 0.85
    VERY_HIGH = 0.97


@dataclass(frozen=True)
class Claim:
    """De enige eenheid waarin een domain agent iets beweert. Verplicht:
    claim (leesbare bewering), value (het onderliggende cijfer/object),
    source (waar het vandaan komt), confidence, timestamp. metric_key is
    optioneel maar sterk aanbevolen voor elk cijfer dat later automatisch
    tegen een drempelwaarde gecontroleerd moet kunnen worden (zelfde rol als
    track_record.py's structured_kill_criteria: alleen claims MET metric_key
    zijn machine-checkbaar, de rest is puur leesbare context)."""

    domain: str
    claim: str
    value: Any
    source: str
    confidence: float
    timestamp: datetime
    metric_key: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.domain:
            raise ValueError("Claim.domain mag niet leeg zijn")
        if not self.claim:
            raise ValueError("Claim.claim mag niet leeg zijn")
        if self.value is None:
            raise ValueError(f"Claim zonder waarde is ongeldig (domain={self.domain!r})")
        if not self.source:
            raise ValueError(f"Claim zonder bron is ongeldig (domain={self.domain!r}, claim={self.claim!r})")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence moet tussen 0 en 1 liggen, kreeg {self.confidence!r}")
        if self.timestamp.tzinfo is None:
            raise ValueError("Claim.timestamp moet timezone-aware zijn (gebruik timezone.utc)")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Claim":
        d = dict(d)
        d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        return cls(**d)


@dataclass
class DomainOutput:
    """Wat een domain agent daadwerkelijk oplevert aan de manager/synthesizer:
    een of meer Claims plus metadata over hoe ze tot stand kwamen. needs_review
    wordt door de QC-laag (stap A.5) gezet, niet door de domain agent zelf --
    een domain agent weet niet of zijn eigen output twijfelachtig is."""

    domain: str
    mode: Mode
    generated_at: datetime
    claims: list[Claim] = field(default_factory=list)
    needs_review: bool = False
    review_issues: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.domain:
            raise ValueError("DomainOutput.domain mag niet leeg zijn")
        for c in self.claims:
            if c.domain != self.domain:
                raise ValueError(
                    f"Claim.domain ({c.domain!r}) komt niet overeen met "
                    f"DomainOutput.domain ({self.domain!r})"
                )

    def checkable_claims(self) -> list[Claim]:
        """Alleen de claims met een metric_key -- de rest is context, geen
        machine-checkbaar cijfer (zelfde onderscheid als track_record.py
        maakt tussen sectie-17-platte-tekst en structured_kill_criteria)."""
        return [c for c in self.claims if c.metric_key is not None]

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "mode": self.mode.value,
            "generated_at": self.generated_at.isoformat(),
            "claims": [c.to_dict() for c in self.claims],
            "needs_review": self.needs_review,
            "review_issues": list(self.review_issues),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DomainOutput":
        return cls(
            domain=d["domain"],
            mode=Mode(d["mode"]),
            generated_at=datetime.fromisoformat(d["generated_at"]),
            claims=[Claim.from_dict(c) for c in d.get("claims", [])],
            needs_review=d.get("needs_review", False),
            review_issues=list(d.get("review_issues", [])),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def now_utc() -> datetime:
    """Enige plek waar 'nu' wordt opgevraagd voor claims/output -- zodat
    tests overal dezelfde functie kunnen monkeypatchen in plaats van losse
    datetime.now(timezone.utc)-aanroepen door de hele codebase."""
    return datetime.now(timezone.utc)
