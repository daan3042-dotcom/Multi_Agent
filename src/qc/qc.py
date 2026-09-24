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

De LLM-review zelf is een pluggable callback (llm_review_fn) -- apply_qc()
kent geen hardcoded afhankelijkheid van de Anthropic SDK, zodat de
deterministische kern getest en bruikbaar blijft zonder API-key. Deze module
levert wel zelf een concrete default-implementatie (default_llm_review(),
hieronder), naar exact hetzelfde patroon als analyst_agent.ai's
self_consistency.py::assess_with_consistency(): een client-parameter i.p.v.
een globale Anthropic-instantie (testbaar met een fake client), JSON-only
system-prompt, robuuste extractie van het eerste {...}-blok, en NOOIT
stilzwijgend een lege issue-lijst teruggeven bij een mislukte call (dat zou
"geen problemen gevonden" claimen terwijl er helemaal geen review heeft
plaatsgevonden) -- zie CLAUDE.md-regel uit analyst_agent.ai: "Don't silently
swallow an error". De daadwerkelijke prompt-verfijning voor een specifiek
domein hoort bij de synthesizer-uitwerking (sectie F); dit is de generieke
default die voor elk domein bruikbaar is.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Protocol

from contract.output_contract import Claim
from health.data_health import QualityStatus

_NUMBER_PATTERN = re.compile(r"-?\d[\d,]*\.?\d*\s*%?")

LLM_REVIEW_SYSTEM_PROMPT = """Je bent een lichte, snelle kwaliteitscontrole voor een \
korte deep-dive van een domain agent binnen een doorlopend marktintelligentie-systeem. \
Dit is GEEN vervanging van de deterministische cijfercontrole (die gebeurt al elders) \
-- jij checkt alleen wat een computer niet kan checken: is de tekst neutraal (geen \
ongefundeerd koop/verkoop-advies of stellige richting zonder onderbouwing), is elke \
claim hieronder daadwerkelijk verwerkt in de tekst (niet genegeerd of tegengesproken), \
en spreekt de tekst zichzelf niet tegen. Wees spaarzaam: rapporteer alleen ECHTE \
problemen, geen stijlvoorkeuren. Antwoord UITSLUITEND met geldige JSON, geen \
inleidende tekst: {"issues": ["<probleem 1>", ...]} (lege lijst als er niets is)."""

DEFAULT_LLM_REVIEW_MODEL = "claude-sonnet-4-6"


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


def _extract_json_block(text: str) -> dict | None:
    """Zelfde aanpak als self_consistency.py::_extract_json_block: zoekt het
    eerste geldige {...}-blok, ook als het model er per ongeluk inleidende
    tekst voor zette."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def default_llm_review(
    client,
    claims: list[Claim],
    deep_dive_text: str,
    model: str = DEFAULT_LLM_REVIEW_MODEL,
) -> list[str]:
    """Concrete, bruikbare default voor de lichte LLM-review uit A.5. `client`
    is een al-geconstrueerde anthropic.Anthropic()-instantie (dependency
    injection, zelfde patroon als self_consistency.py::assess_with_consistency
    en analyst_agent.py::review_report) -- deze functie construeert 'm zelf
    niet, wat 'm zonder API-key testbaar houdt met een fake client.

    apply_qc() verwacht een callable met signatuur (claims, deep_dive_text);
    bind de client dus vast voor gebruik, bijv.:
        functools.partial(default_llm_review, anthropic.Anthropic())

    Geeft bij een mislukte call (netwerkfout, onleesbare JSON) een lijst met
    ÉÉN issue-string terug die dat expliciet benoemt -- NOOIT een lege lijst,
    want dat zou ten onrechte "gereviewd, niets gevonden" claimen terwijl er
    helemaal geen review heeft plaatsgevonden. Dat forceert needs_review=True
    in apply_qc(), wat hier de juiste, veilige kant op fout gaan is."""
    if not claims and not deep_dive_text.strip():
        return []

    claims_summary = "\n".join(
        f"- [{c.domain}] {c.claim}: {c.value} (bron: {c.source}, confidence: {c.confidence})"
        for c in claims
    ) or "(geen claims meegegeven)"
    user_prompt = f"Onderliggende claims:\n{claims_summary}\n\nDeep-dive tekst:\n{deep_dive_text}"

    try:
        response = client.messages.create(
            model=model,
            max_tokens=500,
            system=LLM_REVIEW_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw_text = "".join(b.text for b in response.content if b.type == "text").strip()
        parsed = _extract_json_block(raw_text)
        if parsed is None:
            return ["LLM-review gaf geen leesbare JSON terug -- kon niet automatisch beoordeeld worden"]
        return [str(issue) for issue in parsed.get("issues", [])]
    except Exception as e:
        return [f"LLM-review kon niet worden uitgevoerd: {e}"]


# ---------------------------------------------------------------------------
# Roadmap 1.6: het QC-statusmodel. RAW -> VALIDATED -> TRIGGERED ->
# DEEP_DIVE_COMPLETE -> QC_PASSED/QC_FAILED -> NEEDS_REVIEW -> ARCHIVED.
#
# EEN EIGEN ENTITEIT (storage.schema's nieuwe qc_cases-tabel), geen overload
# van een bestaand veld -- consistent met hoe 1.2 (agent_runs) en 1.4
# (sources) nieuwe concepten hebben ingebed. DomainOutput.needs_review
# blijft bestaan (het blijft de vlag die de synthesizer/manager direct
# leest), maar qc_cases volgt nu de VOLLEDIGE levenscyclus van een
# escalatie, niet alleen het eindoordeel.
#
# WAT AUTOMATISCH GEBEURT (allemaal in agents/base.py, geen aparte
# aanroeper nodig):
# - Een case wordt aangemaakt zodra run_monitoring() minstens één trigger
#   oplevert -- status start meteen op TRIGGERED. RAW en VALIDATED worden
#   BEWUST NIET als losse rijen gepersisteerd: RAW komt overeen met een
#   succesvolle monitoring-agent_run (die al apart bestaat, roadmap 1.2),
#   en VALIDATED zou vandaag altijd hetzelfde ogenblik zijn als RAW (de
#   1.3-checks die 'm echt zouden kunnen laten falen zijn bewust nog niet
#   gewired, zie 1.3's afronding) -- een aparte rij voor een overgang die
#   nu altijd meteen slaagt, zou alleen ruis toevoegen. RAW/VALIDATED
#   blijven wel in het model voor toekomstig gebruik.
# - TRIGGERED -> DEEP_DIVE_COMPLETE: automatisch in run_deep_dive(), zodra
#   de LLM-call is geprobeerd (geslaagd of mislukt, allebei "compleet").
# - DEEP_DIVE_COMPLETE -> QC_PASSED/QC_FAILED: automatisch, via
#   decide_qc_outcome() hieronder (zie DEEL 2 in de PR-samenvatting en
#   docs/architecture.md voor de volledige afweging).
# - QC_FAILED -> NEEDS_REVIEW: automatisch, direct aansluitend (een
#   mislukte QC-beoordeling is per definitie iets dat iemand moet zien).
#
# WAT EEN EXPLICIETE AANROEP NODIG HEEFT:
# - QC_PASSED -> ARCHIVED en NEEDS_REVIEW -> ARCHIVED: de ENIGE
#   handmatige stap (storage.schema.archive_qc_case()). Geen enkele
#   agents/base.py-aanroeper doet dit automatisch -- of een geval
#   "daadwerkelijk klaar" is, is een beslissing die een mens (of een
#   toekomstige scheduler/review-workflow) neemt, niet iets wat het
#   systeem zichzelf mag toekennen.
# ---------------------------------------------------------------------------


class QCCaseStatus(str, Enum):
    RAW = "raw"
    VALIDATED = "validated"
    TRIGGERED = "triggered"
    DEEP_DIVE_COMPLETE = "deep_dive_complete"
    QC_PASSED = "qc_passed"
    QC_FAILED = "qc_failed"
    NEEDS_REVIEW = "needs_review"
    ARCHIVED = "archived"


QC_TRANSITIONS: dict[QCCaseStatus, frozenset[QCCaseStatus]] = {
    QCCaseStatus.RAW: frozenset({QCCaseStatus.VALIDATED}),
    QCCaseStatus.VALIDATED: frozenset({QCCaseStatus.TRIGGERED}),
    QCCaseStatus.TRIGGERED: frozenset({QCCaseStatus.DEEP_DIVE_COMPLETE}),
    QCCaseStatus.DEEP_DIVE_COMPLETE: frozenset({QCCaseStatus.QC_PASSED, QCCaseStatus.QC_FAILED}),
    QCCaseStatus.QC_PASSED: frozenset({QCCaseStatus.ARCHIVED}),
    QCCaseStatus.QC_FAILED: frozenset({QCCaseStatus.NEEDS_REVIEW}),
    QCCaseStatus.NEEDS_REVIEW: frozenset({QCCaseStatus.ARCHIVED}),
    QCCaseStatus.ARCHIVED: frozenset(),
}


class InvalidQCTransitionError(Exception):
    """Een aangevraagde overgang staat niet in QC_TRANSITIONS -- fail loud
    (zelfde precedent als AlreadyProcessedError in agents/base.py), nooit
    stilzwijgend een status overschrijven die het model niet toestaat."""

    def __init__(self, current: QCCaseStatus, target: QCCaseStatus):
        self.current = current
        self.target = target
        super().__init__(f"{current.value} -> {target.value} is geen toegestane overgang")


def validate_qc_transition(current: QCCaseStatus, target: QCCaseStatus) -> None:
    if target not in QC_TRANSITIONS[current]:
        raise InvalidQCTransitionError(current, target)


@dataclass(frozen=True)
class QCCase:
    """Eén rij uit storage.schema's qc_cases-tabel -- de volledige
    levenscyclus van één escalatie, van trigger tot archivering."""

    id: int
    domain: str
    status: QCCaseStatus
    created_at: datetime
    updated_at: datetime
    trigger_reasons: list[str]
    domain_output_id: int | None = None
    quality_status: QualityStatus | None = None
    qc_issues: list[str] = field(default_factory=list)


def decide_qc_outcome(needs_review: bool, quality_status: QualityStatus | None = None) -> QCCaseStatus:
    """DEEL 2: vertaalt het bestaande QC-oordeel (Layer 1+2, `needs_review`)
    plus het optionele 1.3-kwaliteitsoordeel (`QualityStatus`) naar
    QC_PASSED/QC_FAILED. GEEN vanzelfsprekende 1-op-1-mapping (zie
    docs/architecture.md, "Ontwerpkeuzes", voor de volledige afweging):

    - QualityStatus.INVALID faalt ALTIJD, ongeacht een verder perfect
      geschreven tekst -- onbetrouwbare onderliggende data kan een
      QC-tekstcheck niet 'redden'.
    - `needs_review=True` (uit apply_qc(), tekst-vs-cijfer-inconsistentie
      of een LLM-neutraliteitsbevinding) faalt altijd, zoals nu al.
    - QualityStatus.DEGRADED faalt NIET automatisch -- dat zou NEEDS_REVIEW
      te snel laten vollopen met bruikbare-maar-niet-perfecte gevallen
      (bijv. een enigszins verouderde bron). Blijft wel zichtbaar via de
      qc_issues op het geval, alleen geen verplichte FAIL.
    - Geen enkel signaal (needs_review=False, quality_status=None of
      HEALTHY) -> QC_PASSED."""
    if quality_status == QualityStatus.INVALID:
        return QCCaseStatus.QC_FAILED
    if needs_review:
        return QCCaseStatus.QC_FAILED
    return QCCaseStatus.QC_PASSED
