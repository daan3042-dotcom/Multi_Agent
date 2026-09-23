from datetime import datetime, timezone

from contract.output_contract import Claim, DomainOutput, Mode
from manager.manager import dispatch
from synthesizer.synthesizer import synthesize_simultaneous
from triggers.trigger_engine import TriggerEvent


def _deep_dive_output(domain, narrative, needs_review=False):
    now = datetime.now(timezone.utc)
    narrative_claim = Claim(domain=domain, claim="Deep-dive synthese", value=narrative, source="Claude deep-dive (test)", confidence=0.6, timestamp=now)
    return DomainOutput(domain=domain, mode=Mode.DEEP_DIVE, generated_at=now, claims=[narrative_claim], needs_review=needs_review)


def _event(domain):
    return TriggerEvent(domain=domain, triggered_at=datetime.now(timezone.utc), reason="test", severity="medium")


def test_synthesize_simultaneous_includes_only_plan_domains():
    plan = dispatch([_event("monetary_policy"), _event("currency")])
    outputs = {
        "monetary_policy": _deep_dive_output("monetary_policy", "Fed-tekst"),
        "currency": _deep_dive_output("currency", "FX-tekst"),
        "equity": _deep_dive_output("equity", "niet in deze batch"),
    }
    result = synthesize_simultaneous(plan, outputs)
    assert set(result.domains) == {"monetary_policy", "currency"}


def test_synthesize_simultaneous_skips_missing_domain_output():
    plan = dispatch([_event("monetary_policy"), _event("currency")])
    outputs = {"monetary_policy": _deep_dive_output("monetary_policy", "Fed-tekst")}
    result = synthesize_simultaneous(plan, outputs)
    assert result.domains == ["monetary_policy"]


def test_any_needs_review_true_when_one_domain_flagged():
    plan = dispatch([_event("monetary_policy"), _event("currency")])
    outputs = {
        "monetary_policy": _deep_dive_output("monetary_policy", "Fed-tekst", needs_review=True),
        "currency": _deep_dive_output("currency", "FX-tekst"),
    }
    result = synthesize_simultaneous(plan, outputs)
    assert result.any_needs_review is True


def test_to_markdown_includes_narratives_and_review_flag():
    plan = dispatch([_event("monetary_policy"), _event("currency")])
    outputs = {
        "monetary_policy": _deep_dive_output("monetary_policy", "Fed-tekst hier.", needs_review=True),
        "currency": _deep_dive_output("currency", "FX-tekst hier."),
    }
    md = synthesize_simultaneous(plan, outputs).to_markdown()
    assert "Fed-tekst hier." in md
    assert "FX-tekst hier." in md
    assert "NEEDS_REVIEW" in md
    assert "monetary_policy" in md and "currency" in md


def test_to_markdown_falls_back_to_claims_without_narrative():
    now = datetime.now(timezone.utc)
    numeric_claim = Claim(domain="monetary_policy", claim="Fed funds rate", value=5.5, source="FRED", confidence=0.9, timestamp=now, metric_key="fed_funds_rate")
    output = DomainOutput(domain="monetary_policy", mode=Mode.DEEP_DIVE, generated_at=now, claims=[numeric_claim])
    plan = dispatch([_event("monetary_policy")])
    md = synthesize_simultaneous(plan, {"monetary_policy": output}).to_markdown()
    assert "Fed funds rate" in md
