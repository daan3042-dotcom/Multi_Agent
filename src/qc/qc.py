"""
qc.py
Stap A.5. Expliciet NIET 1-op-1 gekopieerd uit analyst_agent.ai: dat systeem
draait 4 parallelle LLM-reviewers plus tot 2 correctierondes rond een enkel,
duur, 18-sectie-rapport -- passend bij de kosten/waarde-verhouding van dat
ene rapport. Hier draaien mogelijk meerdere domain agents doorlopend op de
achtergrond; 4 reviewers per deep-dive zou de kosten van dit systeem
disproportioneel maken t.o.v. wat een deep-dive oplevert.

Principe: deterministisch waar mogelijk (dezelfde soort tekst-vs-cijfer-
consistentiecheck als consistency_check.py, maar dan tegen Claims uit het
A.1-contract i.p.v. tegen verified_metrics), één lichte LLM-review per
domain-deep-dive in plaats van vier, en een NEEDS_REVIEW-vlag i.p.v. een harde
blokkade -- net als analyst_agent.ai's eigen filosofie (zie CLAUDE.md: "Don't
let NEEDS_REVIEW reports be treated as a bug to fix away").

De LLM-review zelf is een pluggable callback (llm_review_fn), niet hier
hardcoded aan de Anthropic SDK gekoppeld -- dat houdt deze module getest en
bruikbaar zonder API-key, en de daadwerkelijke prompt/model-keuze hoort
sowieso bij de synthesizer-uitwerking (sectie F), niet bij het fundament.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Protocol

from contract.output_contract import Claim

_NUMBER_PATTERN = re.compile(r"-?\d[\d,]*\.?\d*\s*%?")


@dataclass
class QCResult:
    needs_review: bool
    issues: list[str] = field(default_factory=list)


class LLMReviewFn(Protocol):
    def __call__(self, claims: list[Claim], deep_dive_text: str) -> list[str]:
        """Moet een lijst issue-strings teruggeven (leeg = geen bevindingen).
        Mag zelf beslissen hoe het reviewt (prompt, model); qc.py bemoeit
        zich daar niet mee."""
        ...


def deterministic_consistency_check(claims: list[Claim], deep_dive_text: str) -> list[str]:
    """Zelfde soort vangnet als analyst_agent.ai's consistency_check.py:
    controleert of een cijfer dat de deep-dive-tekst noemt in de buurt komt
    van wat de onderliggende, al berekende Claim zegt. Alleen numerieke
    Claims worden gecheckt -- kwalitatieve claims (bijv. een tekstuele
    duiding) zijn hier niet deterministisch te verifiëren."""
    issues = []
    text_lower = deep_dive_text.lower()
    for c in claims:
        if not isinstance(c.value, (int, float)):
            continue
        # Zoek de claim-tekst zelf terug in de deep-dive -- als de claim
        # helemaal niet aan bod komt, is dat op zichzelf geen fout (de LLM
        # hoeft niet elke claim letterlijk te citeren), dus alleen checken
        # als er een gerelateerd getal in de buurt van soortgelijke taal
        # staat maar met een andere waarde.
        keyword = c.metric_key or c.claim
        idx = text_lower.find(keyword.lower())
        if idx == -1:
            continue
        window = deep_dive_text[max(0, idx - 80): idx + len(keyword) + 80]
        numbers_in_window = [
            float(m.group().replace(",", "").rstrip("%"))
            for m in _NUMBER_PATTERN.finditer(window)
            if m.group().strip() not in ("", "-")
        ]
        if not numbers_in_window:
            continue
        expected = float(c.value)
        closest = min(numbers_in_window, key=lambda n: abs(n - expected))
        # Ruime marge (1% relatief, of 0.01 absoluut bij waarden rond 0) --
        # dit is een vangnet tegen grove afwijkingen, geen exacte-match-eis;
        # afronding/eenheidsverschillen in de tekst zijn geen bug.
        tolerance = max(abs(expected) * 0.01, 0.01)
        if abs(closest - expected) > tolerance:
            issues.append(
                f"Mogelijke inconsistentie bij '{keyword}': claim zegt {expected:g}, "
                f"tekst noemt in de buurt {closest:g}"
            )
    return issues


def apply_qc(
    claims: list[Claim],
    deep_dive_text: str,
    llm_review_fn: Callable[[list[Claim], str], list[str]] | None = None,
) -> QCResult:
    """Combineert de deterministische check met een optionele lichte
    LLM-review. needs_review wordt True zodra er ÉÉN issue is -- dit blokkeert
    niets, het is puur een vlag die de manager/synthesizer (A.6, sectie F)
    kan tonen of ermee kan wegen, exact zoals analyst_agent.ai's eigen
    NEEDS_REVIEW-gedrag."""
    issues = deterministic_consistency_check(claims, deep_dive_text)
    if llm_review_fn is not None:
        issues = issues + list(llm_review_fn(claims, deep_dive_text))
    return QCResult(needs_review=bool(issues), issues=issues)
