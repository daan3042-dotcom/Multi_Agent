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

Triggerlogica hier is "afwijking sinds de vorige observatie" (delta), NIET
een vaste absolute drempel -- welk absoluut niveau per domein "significant"
is, staat bewust nog open (zie docs/roadmap.md sectie H). Een delta-check is
zinvol ongeacht dat besluit: gebruikt geen aannames over wat een "hoog" of
"laag" niveau is, alleen "is dit meer veranderd dan normaal sinds de vorige
keer".
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from contract.output_contract import Claim, Confidence, DomainOutput, Mode, now_utc
from health.data_health import check_source
from qc.qc import DEFAULT_LLM_REVIEW_MODEL, apply_qc, default_llm_review
from storage.schema import load_latest_claims, record_data_health, save_domain_output
from triggers.trigger_engine import Severity, TriggerEvent, evaluate_data_health, evaluate_surprise

DEFAULT_DEEP_DIVE_MODEL = DEFAULT_LLM_REVIEW_MODEL


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


def run_monitoring(
    conn,
    domain: str,
    source_name: str,
    fetch_snapshot_fn: Callable[[], dict],
    metric_specs: dict[str, MetricSpec],
    max_age: timedelta,
    now=None,
) -> tuple[DomainOutput | None, list[TriggerEvent]]:
    """Eén monitoring-cyclus: data ophalen, health registreren, claims
    opslaan, en per metric met een spec checken of de afwijking t.o.v. de
    vorige observatie significant is. Geeft (None, [data-health-trigger])
    terug als de pull volledig mislukte -- er is dan niets om claims van te
    bouwen, maar het falen zelf mag nooit stilzwijgend verdwijnen (A.3)."""
    now = now or now_utc()
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
        claims.append(
            Claim(
                domain=domain,
                claim=spec.label if spec else metric_key,
                value=value,
                source=source_name,
                confidence=Confidence.HIGH,
                timestamp=now,
                metric_key=metric_key,
                note=entry.get("date"),
            )
        )

    if not claims:
        return None, triggers

    output = DomainOutput(domain=domain, mode=Mode.MONITORING, generated_at=now, claims=claims)
    save_domain_output(conn, output)

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

    return output, triggers


def run_deep_dive(
    conn,
    client,
    domain: str,
    system_prompt: str,
    claims: list[Claim],
    trigger_events: list[TriggerEvent],
    model: str = DEFAULT_DEEP_DIVE_MODEL,
    now=None,
) -> DomainOutput:
    """Deep-dive mode: één LLM-call die de aangeleverde, al-berekende claims
    duidt (Python computes, Claude narrates -- zelfde regel als
    analyst_agent.ai/CLAUDE.md). `client` is dependency-injected, zelfde
    patroon als qc.qc.default_llm_review() en analyst_agent.ai's
    self_consistency.py -- test baar met een fake client, geen hardcoded
    Anthropic-afhankelijkheid.

    Een mislukte call wordt NOOIT stilzwijgend een lege/ontbrekende output --
    het wordt een eigen DomainOutput met needs_review=True en een claim die
    de fout zelf benoemt, zodat het zichtbaar blijft voor de manager/
    synthesizer in plaats van gewoon te verdwijnen."""
    now = now or now_utc()

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
            system=system_prompt,
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
            timestamp=now,
        )
        output = DomainOutput(
            domain=domain,
            mode=Mode.DEEP_DIVE,
            generated_at=now,
            claims=claims + [failure_claim],
            needs_review=True,
            review_issues=[str(e)],
        )
        save_domain_output(conn, output)
        return output

    qc_result = apply_qc(claims, deep_dive_text, llm_review_fn=functools.partial(default_llm_review, client))

    narrative_claim = Claim(
        domain=domain,
        claim="Deep-dive synthese",
        value=deep_dive_text,
        source=f"Claude deep-dive ({model})",
        confidence=Confidence.MEDIUM,
        timestamp=now,
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
    save_domain_output(conn, output)
    return output
