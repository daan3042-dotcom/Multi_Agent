"""
synthesizer/forecast.py
De synthesizer als GESCOORDE voorspeller (roadmap 4.5 en fase 3; slanke v1, 02-10-2026). Naast de domain agents en de baselines
spreekt hij zelf kwantielen uit. Dit is de enige plek waar het LLM over vakgebieden heen kijkt.

WAT HIJ ZIET. De cijfers (claims) en de evidence-sheet van ALLE vakgebieden tegelijk, op dezelfde manier opgebouwd als bij de
domain agents: `load_monitoring_claims` per domein (de laatste cyclus, één waarde per reeks) en `build_evidence_sheet`
(point-in-time, spreiding per horizon). Commodity telt mee als context; die agent voorspelt zelf niets (maandreeks).

WAT HIJ NIET ZIET: DE VOORSPELLINGEN VAN ANDEREN (besluit DD, 02-10-2026). Niet de kwantielen of kansen van de domain agents,
van mensen of van baselines. Ziet hij die, dan is hij een verkapte aggregator, wordt gedeelde informatie dubbel geteld (en dus te
stellig, juist waar iedereen het eens is) en meet de scoring in mei iets anders dan we denken. Python aggregeert nooit over
agents heen en het LLM al helemaal niet: de gewogen pool is 3.4 (mei 2027), volledig in Python. De synthesizer is één lid daarvan.
Dit is afgedwongen door de bouw (de invoer komt uit `load_monitoring_claims`, die geen voorspellingen leest) en bewaakt door
`tests/test_synthesizer_forecast.py`.

WELKE DOELEN. De doelen van de domain agents zelf (dezelfde reeksen, horizonnen en resolutieregels), zodat de synthesizer en de agent
dezelfde vraag beantwoorden en de score rechtstreeks vergelijkbaar is, naast de baselines van dat doel. Een prediction draagt
`agent="synthesizer"` en als `domain` het vakgebied van het doel (zodat uitsplitsing per domein en de koppeling aan de baselines
werken). Dezelfde baselines gelden dus voor de synthesizer; er komt geen tweede baseline-ronde voor.

WAT HIER NIET IN ZIT, BEWUST. De vier instrumentdoelen (NQ, ZN, CL, 6E) vragen een log-rendement als resolutiemethode (het contract
kent die niet en het schema beperkt `resolution_method` met een CHECK) en een prijsbron per instrument. Dat is een eigen beslissing
(roadmap 4.1/4.6). Ook geen richtlijnen van DD (cross-domein-kaders) en geen causale graaf in de prompt: die komen als een nieuwe
`FORECAST_PROMPT_VERSION` (een covariaat, geen nieuw cohort).

NIET GEKOPPELD AAN `run_daily`. Dit bestand bevat alleen de bouwstenen; hij draait pas mee als DD de koppeling goedkeurt
(CLAUDE.md, checkpoint 1 en 3). De kosten zijn nul tot de eerste echte aanroep.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agents.base import (
    DEFAULT_DEEP_DIVE_MODEL, FORECAST_SYSTEM_RULES, ForecastRoundResult, ForecastTarget, _forecast_user_prompt,
    run_forecast_round,
)
from contract.output_contract import Claim, now_utc
from scoring.evidence_sheet import build_evidence_sheet
from storage.schema import load_monitoring_claims

AGENT = "synthesizer"
FORECAST_PROMPT_VERSION = "v1"
"""Versie van de prompt waarmee de synthesizer voorspelt (gaat mee in elke prediction als `synthesizer-v1`). De prompt is
FORECAST_SYSTEM_RULES plus SYNTHESIZER_SYSTEM_PROMPT hieronder, plus de evidence-sheet (zie `runtime/freeze_guard.py`)."""

MAX_TOKENS = 8000
"""Antwoordruimte voor één JSON met alle voorspellingen (57 per ronde, ~55 tokens elk). Een afgekapt antwoord is geen geldige
JSON en kost de hele ronde; de domain agents komen met 2.000 toe omdat ze er acht tot twaalf hebben."""

KOP = "Huidige, al berekende cijfers voor ALLE vakgebieden"

SYNTHESIZER_SYSTEM_PROMPT = """Je bent de cross-domein-voorspeller van een marktintelligentiesysteem. Anders dan de \
domain agents, die elk één vakgebied zien, krijg jij de cijfers van ALLE vakgebieden tegelijk: rente en beleid, valuta, \
krediet en volatiliteit, sectoren, grondstoffen en arbeidsmarkt. Je voorspelt dezelfde doelen als die agents.

Wat je NIET ziet en niet moet proberen te raden: de voorspellingen van de domain agents, van mensen of van referentiemodellen. \
Jouw verdeling komt uitsluitend uit de aangeleverde cijfers en de context erbij.

Hoe je kijkt:
- Gebruik de samenhang tussen vakgebieden: wijzen rente, krediet, dollar en sectoren dezelfde kant op, dan kan dat samen één \
beeld zijn; wijzen ze uiteen, dan is de tegenstrijdigheid zelf informatie en hoort je verdeling daar breder van te worden.
- Tel gedeelde informatie niet dubbel. Meerdere reeksen die hetzelfde verhaal vertellen zijn vaak één waarneming, geen vijf. \
Meer reeksen die hetzelfde zeggen maken je niet zekerder.
- 'Er is niets veranderd' is een geldig antwoord. Dwing geen verhaal af: zonder duidelijk signaal hoort je verdeling rond de \
huidige waarde te liggen, zo breed als de spreiding in de context aangeeft.
- Geef geen advies en schrijf geen verhaal. Je antwoord is uitsluitend de gevraagde JSON."""

DEEP_DIVE_SYSTEM_PROMPT = SYNTHESIZER_SYSTEM_PROMPT
"""Alias onder de naam die `runtime/freeze_guard.forecast_prompt_hash` van een agent-module verwacht, zodat de synthesizer in
dezelfde prompt-bewaking valt als de domain agents. Geen tweede prompt."""


@dataclass(frozen=True)
class SynthesizerDoelen:
    targets: tuple[ForecastTarget, ...]
    domain_of: dict[str, str]          # metric_key -> vakgebied van het doel


def doelen(agents=None) -> SynthesizerDoelen:
    """De doelen van alle voorspellende domain agents, met hun vakgebied. Afgeleid uit `default_agents()`, dus geen tweede lijst die
    uit de pas kan lopen met de agents zelf. Een metric_key die bij twee agents voorkomt is een fout (de respons zou dubbelzinnig
    worden en `Prediction.domain` is dan niet eenduidig)."""
    from runtime.daily import default_agents

    agents = agents if agents is not None else default_agents()
    targets: list[ForecastTarget] = []
    domain_of: dict[str, str] = {}
    for spec in agents:
        for t in spec.forecast_targets:
            if t.metric_key in domain_of:
                raise ValueError(
                    f"doel {t.metric_key!r} komt bij twee agents voor ({domain_of[t.metric_key]}, {spec.domain}): "
                    f"de synthesizer kan het niet eenduidig voorspellen"
                )
            targets.append(t)
            domain_of[t.metric_key] = spec.domain
    return SynthesizerDoelen(tuple(targets), domain_of)


def laad_claims(conn, agents=None) -> list[Claim]:
    """De laatste cyclus van elk domein, één waarde per reeks: precies wat de domain agents krijgen. Leest geen voorspellingen."""
    from runtime.daily import default_agents

    agents = agents if agents is not None else default_agents()
    claims: list[Claim] = []
    for spec in agents:
        claims.extend(load_monitoring_claims(conn, spec.domain))
    return claims


def bouw_prompt(conn, now: datetime, agents=None, claims: list[Claim] | None = None) -> tuple[str, str]:
    """(systeemprompt, gebruikersprompt) die de synthesizer op `now` zou krijgen. Geen LLM-aanroep. `claims` kan van buiten komen
    (de pseudo-OOS-run bouwt ze point-in-time voor een datum in het verleden)."""
    d = doelen(agents)
    claims = claims if claims is not None else laad_claims(conn, agents)
    evidence = build_evidence_sheet(conn, list(d.targets), claims, now)
    systeem = f"{FORECAST_SYSTEM_RULES}\n\n{SYNTHESIZER_SYSTEM_PROMPT}"
    return systeem, _forecast_user_prompt(list(d.targets), claims, evidence, KOP)


def run_synthesizer_round(
    conn, client, now: datetime | None = None, event_id: str | None = None, agents=None,
    model: str = DEFAULT_DEEP_DIVE_MODEL, claims: list[Claim] | None = None,
) -> ForecastRoundResult:
    """Eén LLM-call voor alle doelen, wekelijks (`event_id` = ISO-week), met dezelfde idempotentie als de agents. Zonder enige claim
    gebeurt er niets (geen betaalde call over niets, en de week blijft herhaalbaar)."""
    now = now or now_utc()
    d = doelen(agents)
    claims = claims if claims is not None else laad_claims(conn, agents)
    if not claims:
        return ForecastRoundResult(AGENT, (), ("geen enkele claim beschikbaar: geen aanroep gedaan",))
    evidence = build_evidence_sheet(conn, list(d.targets), claims, now)
    return run_forecast_round(
        conn, client, AGENT, SYNTHESIZER_SYSTEM_PROMPT, list(d.targets), claims,
        prompt_version=f"{AGENT}-{FORECAST_PROMPT_VERSION}", model=model, now=now, event_id=event_id,
        evidence=evidence, agent=AGENT, domain_of=d.domain_of, max_tokens=MAX_TOKENS, kop=KOP,
    )
