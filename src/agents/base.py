"""
base.py
Gedeelde scaffolding voor domain agents met de tweeledige opzet uit
stappenplan B.1: monitoring mode (databron ophalen, tegen verwachting/
thresholds leggen) + deep-dive mode (LLM-synthese bij trigger). Monetary
policy (B.1) en currency (B.2) zijn de eerste twee, bewust als duo gebouwd
vanwege hun sterke onderlinge koppeling (renteveranderingen werken vaak
direct door in wisselkoersen) -- delen daarom deze scaffolding in plaats van
elk hun eigen, losstaande monitoring/deep-dive-logica te herschrijven.

Elke domain agent module (zie monetary_policy_agent.py, currency_agent.py)
levert alleen zijn eigen: fetch_snapshot(), METRIC_SPECS, DEEP_DIVE_SYSTEM_
PROMPT -- en roept run_monitoring()/run_deep_dive() hieronder aan. Dat houdt
de trigger-beslissing (A.4) en QC (A.5) consistent tussen domeinen, in
plaats van dat elke agent zijn eigen variant uitvindt.

Elke cyclus (monitoring EN deep-dive, geslaagd of niet) registreert zichzelf
via storage.schema.record_agent_run() (roadmap 1.2, entiteit agent_runs) --
los van de claims die de cyclus eventueel oplevert. Dit is de audit-log die
health.system_health.system_health() (roadmap 1.7, deel 1) leest: "heeft
agent X gedraaid, is het gelukt", onafhankelijk van of er een output/
trigger uitkwam.

IDEMPOTENCY (roadmap 1.7, deel 2): beide functies accepteren een optionele
`event_id` -- een dedup-key die de aanroeper (bijv. een toekomstige
scheduler) meegeeft. Is dit domain+mode+event_id al SUCCESVOL verwerkt
(storage.schema.has_successful_run), dan gooit de functie
AlreadyProcessedError VÓÓR er gefetcht of de LLM aangeroepen wordt -- geen
dubbele kosten, geen dubbele claims. Een mislukte eerdere poging blokkeert
een retry met hetzelfde event_id NIET. Zonder event_id (alle 6 bestaande
domain agents op dit moment) verandert er niets aan het gedrag.

Triggerlogica hier is "afwijking sinds de vorige observatie" (delta), NIET
een vaste absolute drempel -- welk absoluut niveau per domein "significant"
is, staat bewust nog open (zie docs/roadmap.md sectie H). Een delta-check is
zinvol ongeacht dat besluit: gebruikt geen aannames over wat een "hoog" of
"laag" niveau is, alleen "is dit meer veranderd dan normaal sinds de vorige
keer".

Naast een delta (nieuwe periode, nieuwe waarde) checkt run_monitoring() ook
op REVISIES (roadmap 1.3): een gewijzigde waarde voor een periode die al
eerder gerapporteerd is (zelfde source_time), bijv. een BBP-schatting die
wordt bijgesteld. health.data_health.detect_revision() vergelijkt hiervoor
tegen de al-opgehaalde claims-geschiedenis (previous_by_metric) -- geen
aparte observations-tabel nodig, claims bewaart elke poll al historisch.

KWALITEIT VAN DE DEEP-DIVES (zie CLAUDE.md, "Werkwijze met DD"): elk domain
agent's DEEP_DIVE_SYSTEM_PROMPT bevat ALLEEN vakinhoudelijke context --
SHARED_QUALITY_RULES hieronder wordt door run_deep_dive() automatisch
ervoor geplakt en geldt dus voor ELKE deep-dive, ongeacht domein. Dit is de
tegenhanger van analyst_agent.ai's framework.py::SYSTEM_PROMPT (dezelfde
soort concrete, niet-onderhandelbare schrijfregels), hier centraal gehouden
in plaats van per domein gedupliceerd -- zodat een kwaliteitsverbetering op
één plek meteen voor alle domeinen geldt, en nieuwe domeinen (sectie C+)
'm niet zelf hoeven te herschrijven of kunnen vergeten.

SCOPE VAN DE NEUTRALITEITSREGEL (belangrijk, expliciet besproken met DD):
SHARED_QUALITY_RULES geldt voor de AUTOMATISCHE, ONBEHEERDE monitoring/
deep-dive-laag hier in sectie B/C -- niemand kijkt live mee als dit
triggert, dus een voorbarige directionele claim is hier het gevaarlijkst.
Dit is NIET bedoeld als permanente blokkade op elke vorm van directionele/
probabilistische redenering in het hele systeem: sectie G.3 (on-demand
vraag-interface, nog te bouwen) krijgt een aparte "thesis-mode" die WEL
expliciet gevraagde directionele/probabilistische antwoorden mag geven
(bijv. "wat is de kans dat de Fed de rente verhoogt, met een thesis") --
analoog aan analyst_agent.ai's sectie 18 (Variant Perception): overal
elders strikt neutraal, met ÉÉN duidelijk gelabeld, geïsoleerd kanaal voor
opinie. SHARED_QUALITY_RULES hieronder blijft ongewijzigd voor de
bestaande automatische agents; de thesis-mode wordt een NIEUWE, aparte
bevoegdheid bij G.3, geen aanpassing van deze regels.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from contract.output_contract import Claim, Confidence, DomainOutput, Mode, now_utc
from health.data_health import check_source, detect_revision
from qc.qc import DEFAULT_LLM_REVIEW_MODEL, apply_qc, default_llm_review
from storage.schema import has_successful_run, load_latest_claims, record_agent_run, record_data_health, save_domain_output
from triggers.trigger_engine import Severity, TriggerEvent, evaluate_data_health, evaluate_revision, evaluate_surprise

DEFAULT_DEEP_DIVE_MODEL = DEFAULT_LLM_REVIEW_MODEL


class AlreadyProcessedError(Exception):
    """Roadmap 1.7, deel 2 (idempotency). Wordt gegooid door run_monitoring()/
    run_deep_dive() als de aanroeper een `event_id` meegeeft die voor dit
    domain+mode al SUCCESVOL verwerkt is (storage.schema.has_successful_run)
    -- vóórdat er gefetcht of een LLM aangeroepen wordt, dus geen dubbele
    kosten en geen dubbele claims/agent_run. Een expliciete exception i.p.v.
    stilzwijgend `None` teruggeven: run_deep_dive() geeft normaliter ALTIJD
    een echte DomainOutput terug (ook bij een mislukte LLM-call), dus een
    stille None zou dat contract breken. De aanroeper beslist zelf hoe
    hiermee om te gaan (negeren, loggen) -- geen impliciete aanname hier."""

    def __init__(self, domain: str, mode: str, event_id: str):
        self.domain = domain
        self.mode = mode
        self.event_id = event_id
        super().__init__(f"{domain}/{mode}: event_id {event_id!r} is al succesvol verwerkt")

SHARED_QUALITY_RULES = """Dit is een korte deep-dive-synthese binnen een doorlopend \
marktintelligentie-systeem, geen los rapport -- onderstaande regels gelden daarom voor \
ELKE domain agent, ongeacht vakgebied, en zijn niet onderhandelbaar. Je specifieke \
instructie hieronder vult alleen het vakinhoudelijke onderwerp in, niet deze regels.

NEUTRALITEIT, concreet (dit wordt vaak toch geschreven, dus expliciet): schrijf nooit een \
koop/verkoop-advies, koersdoel, of stellige richting-voorspelling. VERBODEN patronen: \
"lijkt onder-/overgewaardeerd", "de cijfers ondersteunen een stijging/daling", "zal \
waarschijnlijk stijgen/dalen naar X" zonder expliciete bron/voorbehoud. Vervang dit door \
feitelijke, vergelijkende taal: in plaats van "dit wijst op verdere verkrapping" schrijf \
bijvoorbeeld "dit is de op-een-na grootste stijging in de beschikbare data, alleen de \
observatie op [datum indien in de claims] was groter".

ALLEEN DE AANGELEVERDE CLAIMS: gebruik uitsluitend de cijfers die je expliciet krijgt \
aangereikt. Bereken, extrapoleer of verzin zelf geen cijfers -- als iets niet uit de \
claims valt af te leiden, benoem dat expliciet ("dit is niet af te leiden uit de \
beschikbare data") in plaats van te gokken.

ONZEKERHEID EXPLICIET: elke claim heeft een confidence-score en een bron; een lage \
confidence rechtvaardigt geen stellige formulering. Noem de bron bij een cijfer als dat de \
tekst leesbaarder maakt, en benoem expliciete twijfel als die er is.

AANLEIDING, GEEN OVERINTERPRETATIE: leg uit waarom dit een trigger opleverde (de afwijking \
t.o.v. de vorige observatie, zoals aangeleverd), maar trek geen grotere conclusie dan de \
cijfers zelf rechtvaardigen -- één afwijkende observatie is geen trend."""


@dataclass(frozen=True)
class MetricSpec:
    """Eén regel per metric_key: hoe heet 'ie leesbaar, en hoeveel afwijking
    sinds de vorige observatie geldt als significant genoeg om te triggeren.
    `tolerance` is een ABSOLUTE marge in de eenheid van de metric zelf (bijv.
    procentpunt voor een rente) -- illustratieve plaatshouder-waarden tot DD
    eigen, gevalideerde drempels aanlevert (sectie H)."""

    label: str
    tolerance: float
    severity: Severity = "medium"
    reason: str | None = None


def _parse_source_date(raw: str | None) -> datetime | None:
    """Vertaalt een ruwe brondatum (bijv. FRED's "as of"-datum uit
    fetch_snapshot()'s entry["date"]) naar een echte source_time i.p.v. 'm
    weg te gooien in het vrije-tekst note-veld. `None`/leeg en een
    onparseerbaar formaat geven allebei `None` terug (verdedigend tegen
    externe data, zelfde patroon als de KeyError/TypeError/ValueError-vang
    bij het parsen van entry["value"] hierboven) -- geen gok, dan blijft
    source_time gewoon ongezet."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def run_monitoring(
    conn,
    domain: str,
    source_name: str,
    fetch_snapshot_fn: Callable[[], dict],
    metric_specs: dict[str, MetricSpec],
    max_age: timedelta,
    now=None,
    event_id: str | None = None,
) -> tuple[DomainOutput | None, list[TriggerEvent]]:
    """Eén monitoring-cyclus: data ophalen, health registreren, claims
    opslaan, en per metric met een spec checken of de afwijking t.o.v. de
    vorige observatie significant is. Geeft (None, [data-health-trigger])
    terug als de pull volledig mislukte -- er is dan niets om claims van te
    bouwen, maar het falen zelf mag nooit stilzwijgend verdwijnen (A.3).

    `event_id` is optioneel (roadmap 1.7, idempotency) -- als meegegeven EN
    dit domain+mode+event_id al succesvol verwerkt is, gooit dit
    AlreadyProcessedError VÓÓR fetch_snapshot_fn() wordt aangeroepen (geen
    onnodige netwerkcall). Achterwaarts compatibel: bestaande aanroepers
    (alle 6 domain agents op dit moment) geven geen event_id mee en merken
    hier niets van."""
    now = now or now_utc()
    if event_id is not None and has_successful_run(conn, domain, "monitoring", event_id):
        raise AlreadyProcessedError(domain, "monitoring", event_id)

    triggers: list[TriggerEvent] = []

    try:
        snapshot = fetch_snapshot_fn()
    except Exception as e:
        snapshot = {"error": str(e)}

    success = "error" not in snapshot
    record_data_health(conn, source_name, now, success=success, detail=snapshot.get("error") if not success else None)

    health = check_source(conn, source_name, max_age=max_age, now=now)
    health_trigger = evaluate_data_health(domain, health, now=now)
    if health_trigger is not None:
        triggers.append(health_trigger)

    if not success:
        record_agent_run(conn, domain, "monitoring", now, success=False, trigger_count=len(triggers), error=snapshot.get("error"), event_id=event_id)
        return None, triggers

    # Vorige observatie per metric OPHALEN VOORDAT de nieuwe claims worden
    # opgeslagen -- anders zou "de vorige observatie" straks de claim zijn
    # die we net zelf hebben toegevoegd.
    previous_by_metric = {
        metric_key: load_latest_claims(conn, domain, metric_key=metric_key) for metric_key in snapshot
    }

    claims: list[Claim] = []
    for metric_key, entry in snapshot.items():
        spec = metric_specs.get(metric_key)
        try:
            value = float(entry["value"])
        except (KeyError, TypeError, ValueError):
            continue
        raw_date = entry.get("date")
        source_time = _parse_source_date(raw_date)

        revised_claim = detect_revision(previous_by_metric.get(metric_key) or [], source_time, value)
        if revised_claim is not None:
            label = spec.label if spec else metric_key
            triggers.append(evaluate_revision(
                domain=domain,
                metric_key=metric_key,
                previous_value=revised_claim.value,
                revised_value=value,
                reason=(
                    f"Revisie: {label} voor periode {source_time.date()} gewijzigd van "
                    f"{revised_claim.value:g} naar {value:g}"
                ),
                severity=spec.severity if spec else "medium",
                now=now,
            ))

        claims.append(
            Claim(
                domain=domain,
                claim=spec.label if spec else metric_key,
                value=value,
                source=source_name,
                confidence=Confidence.HIGH,
                analysis_time=now,
                source_time=source_time,
                metric_key=metric_key,
                note=None if source_time is not None else raw_date,
            )
        )

    if not claims:
        record_agent_run(
            conn, domain, "monitoring", now, success=False, trigger_count=len(triggers),
            error="Geen enkele metric kon geparsed worden uit de snapshot", event_id=event_id,
        )
        return None, triggers

    output = DomainOutput(domain=domain, mode=Mode.MONITORING, generated_at=now, claims=claims)
    domain_output_id = save_domain_output(conn, output)

    triggers.extend(evaluate_deltas(domain, claims, metric_specs, previous_by_metric, now=now))

    record_agent_run(conn, domain, "monitoring", now, success=True, domain_output_id=domain_output_id, trigger_count=len(triggers), event_id=event_id)

    return output, triggers


def evaluate_deltas(
    domain: str,
    claims: list[Claim],
    metric_specs: dict[str, MetricSpec],
    previous_by_metric: dict[str, list[Claim]],
    now=None,
) -> list[TriggerEvent]:
    """De delta-trigger-vergelijking zelf, losgetrokken uit run_monitoring()
    zodat ook een adapter die GEEN eigen fetch heeft (zie agents/
    equity_agent.py, C.1: de data komt al kant-en-klaar uit een afgeronde
    analyst_agent.ai-run) dezelfde triggerlogica kan hergebruiken in plaats
    van 'm te herschrijven.

    `previous_by_metric` moet VOOR het opslaan van `claims` zijn opgehaald
    (zie run_monitoring hierboven) -- deze functie bemoeit zich niet met
    volgorde/opslaan, alleen met de vergelijking zelf."""
    now = now or now_utc()
    triggers: list[TriggerEvent] = []
    for claim in claims:
        spec = metric_specs.get(claim.metric_key)
        if spec is None:
            continue
        previous = previous_by_metric.get(claim.metric_key) or []
        if not previous:
            continue  # eerste observatie voor deze metric -- niets om tegen te vergelijken
        trigger = evaluate_surprise(
            domain=domain,
            metric_key=claim.metric_key,
            observed_value=claim.value,
            expected_value=previous[0].value,
            tolerance=spec.tolerance,
            reason=spec.reason or f"{spec.label} significant gewijzigd sinds vorige observatie",
            severity=spec.severity,
            now=now,
        )
        if trigger is not None:
            triggers.append(trigger)
    return triggers


def run_deep_dive(
    conn,
    client,
    domain: str,
    system_prompt: str,
    claims: list[Claim],
    trigger_events: list[TriggerEvent],
    model: str = DEFAULT_DEEP_DIVE_MODEL,
    now=None,
    event_id: str | None = None,
) -> DomainOutput:
    """Deep-dive mode: één LLM-call die de aangeleverde, al-berekende claims
    duidt (Python computes, Claude narrates -- zelfde regel als
    analyst_agent.ai/CLAUDE.md). `client` is dependency-injected, zelfde
    patroon als qc.qc.default_llm_review() en analyst_agent.ai's
    self_consistency.py -- test baar met een fake client, geen hardcoded
    Anthropic-afhankelijkheid.

    `system_prompt` is de VAKINHOUDELIJKE instructie van de aanroepende
    domain agent -- SHARED_QUALITY_RULES wordt hier automatisch ervoor
    geplakt, dus de aanroeper hoeft neutraliteit/bronvermelding/onzekerheid
    niet zelf te herhalen (en kan dat ook niet per ongeluk overslaan).

    Een mislukte call wordt NOOIT stilzwijgend een lege/ontbrekende output --
    het wordt een eigen DomainOutput met needs_review=True en een claim die
    de fout zelf benoemt, zodat het zichtbaar blijft voor de manager/
    synthesizer in plaats van gewoon te verdwijnen.

    `event_id` is optioneel (roadmap 1.7, idempotency) -- zelfde gedrag als
    run_monitoring(): als dit domain+mode+event_id al succesvol verwerkt
    is, AlreadyProcessedError VÓÓR de (dure) LLM-call. Achterwaarts
    compatibel zonder event_id."""
    now = now or now_utc()
    if event_id is not None and has_successful_run(conn, domain, "deep_dive", event_id):
        raise AlreadyProcessedError(domain, "deep_dive", event_id)

    full_system_prompt = f"{SHARED_QUALITY_RULES}\n\n{system_prompt}"

    claims_summary = (
        "\n".join(f"- {c.claim}: {c.value} (bron: {c.source}, metric_key: {c.metric_key})" for c in claims)
        or "(geen onderliggende claims)"
    )
    triggers_summary = (
        "\n".join(f"- {t.reason} (severity: {t.severity})" for t in trigger_events)
        or "(geen expliciete trigger, on-demand aangevraagd)"
    )
    user_prompt = (
        f"Aanleiding voor deze deep-dive:\n{triggers_summary}\n\n"
        f"Onderliggende, al berekende claims (gebruik deze cijfers, verzin er geen bij):\n{claims_summary}\n\n"
        "Schrijf een korte, neutrale deep-dive-synthese (maximaal ~200 woorden) die deze "
        "cijfers in context duidt. Geen koop/verkoop-advies, geen koersvoorspelling."
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=800,
            system=full_system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        deep_dive_text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not deep_dive_text:
            raise ValueError("lege respons van het model")
    except Exception as e:
        failure_claim = Claim(
            domain=domain,
            claim="Deep-dive mislukt",
            value=f"Kon geen deep-dive genereren: {e}",
            source="Claude deep-dive (mislukt)",
            confidence=Confidence.LOW,
            analysis_time=now,
            source_time=now,
        )
        output = DomainOutput(
            domain=domain,
            mode=Mode.DEEP_DIVE,
            generated_at=now,
            claims=claims + [failure_claim],
            needs_review=True,
            review_issues=[str(e)],
        )
        domain_output_id = save_domain_output(conn, output)
        record_agent_run(
            conn, domain, "deep_dive", now, success=False, domain_output_id=domain_output_id,
            trigger_count=len(trigger_events), error=str(e), event_id=event_id,
        )
        return output

    qc_result = apply_qc(claims, deep_dive_text, llm_review_fn=functools.partial(default_llm_review, client))

    narrative_claim = Claim(
        domain=domain,
        claim="Deep-dive synthese",
        value=deep_dive_text,
        source=f"Claude deep-dive ({model})",
        confidence=Confidence.MEDIUM,
        analysis_time=now,
        source_time=now,
        note="; ".join(t.reason for t in trigger_events) or None,
    )
    output = DomainOutput(
        domain=domain,
        mode=Mode.DEEP_DIVE,
        generated_at=now,
        claims=claims + [narrative_claim],
        needs_review=qc_result.needs_review,
        review_issues=qc_result.issues,
    )
    domain_output_id = save_domain_output(conn, output)
    record_agent_run(conn, domain, "deep_dive", now, success=True, domain_output_id=domain_output_id, trigger_count=len(trigger_events), event_id=event_id)
    return output
