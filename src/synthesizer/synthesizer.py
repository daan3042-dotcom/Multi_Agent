"""
synthesizer.py
Stap B.3: eerste, bewust simpele versie. Legt de deep-dive-output van
gelijktijdig getriggerde domeinen NAAST ELKAAR -- nog GEEN cross-domein-
synthese. Tegenstrijdigheid-detectie, confidence-weging en "cross-domein
implicaties combineren tot één leesbaar geheel" zijn sectie F, en vereisen
onderdelen die hier nog niet bestaan (o.a. de Bayesiaanse prior-gewichten
per domain agent). Deze versie bewijst alleen dat de manager's DispatchPlan
(A.6) en de deep-dive-outputs van meerdere domain agents (B.1/B.2) samen tot
iets leesbaars te combineren zijn -- de bouwsteen waar sectie F later op
voortbouwt, niet die synthese zelf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from contract.output_contract import DomainOutput


@dataclass
class SynthesisResult:
    batch_id: str
    generated_at: datetime
    domain_outputs: dict[str, DomainOutput] = field(default_factory=dict)

    @property
    def domains(self) -> list[str]:
        return list(self.domain_outputs.keys())

    @property
    def any_needs_review(self) -> bool:
        return any(o.needs_review for o in self.domain_outputs.values())

    def _narrative_for(self, output: DomainOutput) -> str | None:
        """Pakt de meest recente kwalitatieve claim (metric_key=None, tekst-
        waarde) -- dat is de deep-dive-synthese die agents.base.run_deep_dive
        toevoegt. Geeft None terug als die er niet is (bijv. een mislukte
        deep-dive, zie run_deep_dive's foutpad) zodat to_markdown() dan op de
        losse claims terugvalt in plaats van te crashen."""
        for claim in reversed(output.claims):
            if claim.metric_key is None and isinstance(claim.value, str):
                return claim.value
        return None

    def to_markdown(self) -> str:
        """Puur deterministisch, geen LLM -- de daadwerkelijke cross-domein-
        duiding (sectie F) komt later; dit legt de deep-dives alleen naast
        elkaar in leesbare vorm."""
        lines = [f"# Gelijktijdige marktintelligentie-update ({self.generated_at.isoformat()})", ""]
        for domain, output in self.domain_outputs.items():
            lines.append(f"## {domain}")
            if output.needs_review:
                lines.append("**NEEDS_REVIEW**")
            narrative = self._narrative_for(output)
            if narrative:
                lines.append(narrative)
            else:
                for c in output.checkable_claims():
                    lines.append(f"- {c.claim}: {c.value}")
            lines.append("")
        return "\n".join(lines)


def synthesize_simultaneous(plan, domain_outputs: dict[str, DomainOutput]) -> SynthesisResult:
    """plan: manager.manager.DispatchPlan. domain_outputs: de deep-dive
    DomainOutput per domein dat daadwerkelijk escaleerde. Een domein in
    plan.domains zonder bijpassende entry hier wordt overgeslagen (bijv.
    als die deep-dive nog niet is afgerond) -- geen gok, gewoon weglaten."""
    outputs = {domain: domain_outputs[domain] for domain in plan.domains if domain in domain_outputs}
    return SynthesisResult(batch_id=plan.batch_id, generated_at=plan.generated_at, domain_outputs=outputs)
