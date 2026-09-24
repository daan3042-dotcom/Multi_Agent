from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from contract.output_contract import Claim
from health.data_health import QualityStatus
from qc.qc import (
    QC_TRANSITIONS,
    InvalidQCTransitionError,
    QCCaseStatus,
    apply_qc,
    decide_qc_outcome,
    default_llm_review,
    deterministic_consistency_check,
    validate_qc_transition,
)


def _claim(**overrides):
    defaults = dict(
        domain="monetary_policy", claim="fed_funds_rate", value=5.5, source="FRED",
        confidence=0.85, analysis_time=datetime.now(timezone.utc), metric_key="fed_funds_rate",
    )
    defaults.update(overrides)
    return Claim(**defaults)


def test_no_issues_when_text_matches_claim():
    claim = _claim()
    text = "De fed_funds_rate staat momenteel op 5.5%, boven de marktverwachting."
    assert deterministic_consistency_check([claim], text) == []


def test_flags_inconsistent_number_near_metric_key():
    claim = _claim()
    text = "De fed_funds_rate staat momenteel op 4.0%, ruim onder verwachting."
    issues = deterministic_consistency_check([claim], text)
    assert len(issues) == 1
    assert "fed_funds_rate" in issues[0]


def test_ignores_metric_key_not_mentioned_in_text():
    claim = _claim()
    text = "Dit rapport gaat over iets heel anders."
    assert deterministic_consistency_check([claim], text) == []


def test_ignores_non_numeric_claims():
    claim = _claim(value="dovish", metric_key=None, claim="Fed toon is dovish")
    text = "De Fed toon is dovish deze week."
    assert deterministic_consistency_check([claim], text) == []


def test_apply_qc_needs_review_false_when_clean():
    claim = _claim()
    text = "fed_funds_rate: 5.5%"
    result = apply_qc([claim], text)
    assert result.needs_review is False
    assert result.issues == []


def test_apply_qc_needs_review_true_when_inconsistent():
    claim = _claim()
    text = "fed_funds_rate: 2.0%"
    result = apply_qc([claim], text)
    assert result.needs_review is True
    assert len(result.issues) == 1


def test_apply_qc_combines_llm_review_issues():
    claim = _claim()
    text = "fed_funds_rate: 5.5%"

    def fake_llm_review(claims, deep_dive_text):
        return ["LLM vond een neutraliteitsprobleem"]

    result = apply_qc([claim], text, llm_review_fn=fake_llm_review)
    assert result.needs_review is True
    assert "LLM vond een neutraliteitsprobleem" in result.issues


def _fake_client(response_text):
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text=response_text)]
    client.messages.create = lambda **kwargs: response
    return client


def test_default_llm_review_returns_empty_list_when_clean():
    client = _fake_client('{"issues": []}')
    claim = _claim()
    issues = default_llm_review(client, [claim], "fed_funds_rate: 5.5%, neutraal beschreven.")
    assert issues == []


def test_default_llm_review_returns_reported_issues():
    client = _fake_client('{"issues": ["Tekst suggereert een koopadvies zonder onderbouwing"]}')
    claim = _claim()
    issues = default_llm_review(client, [claim], "Dit is duidelijk een koopkans.")
    assert issues == ["Tekst suggereert een koopadvies zonder onderbouwing"]


def test_default_llm_review_handles_prose_wrapped_json():
    client = _fake_client('Hier is mijn beoordeling:\n{"issues": ["kleine inconsistentie"]}\nEinde.')
    claim = _claim()
    issues = default_llm_review(client, [claim], "tekst")
    assert issues == ["kleine inconsistentie"]


def test_default_llm_review_never_silently_returns_empty_on_unparseable_response():
    client = _fake_client("dit is geen JSON")
    claim = _claim()
    issues = default_llm_review(client, [claim], "tekst")
    assert len(issues) == 1
    assert "geen leesbare JSON" in issues[0]


def test_default_llm_review_never_silently_returns_empty_on_exception():
    client = MagicMock()
    client.messages.create = lambda **kwargs: (_ for _ in ()).throw(Exception("timeout"))
    claim = _claim()
    issues = default_llm_review(client, [claim], "tekst")
    assert len(issues) == 1
    assert "timeout" in issues[0]


def test_default_llm_review_wired_into_apply_qc_via_partial():
    import functools

    client = _fake_client('{"issues": ["LLM-bevinding"]}')
    claim = _claim()
    text = "fed_funds_rate: 5.5%"  # deterministisch schoon
    result = apply_qc([claim], text, llm_review_fn=functools.partial(default_llm_review, client))
    assert result.needs_review is True
    assert result.issues == ["LLM-bevinding"]


# -- Roadmap 1.6: het QC-statusmodel zelf --

def test_valid_transition_does_not_raise():
    validate_qc_transition(QCCaseStatus.TRIGGERED, QCCaseStatus.DEEP_DIVE_COMPLETE)  # geen exception = geslaagd


def test_invalid_transition_raises():
    with pytest.raises(InvalidQCTransitionError):
        validate_qc_transition(QCCaseStatus.TRIGGERED, QCCaseStatus.ARCHIVED)  # mag niet springen


def test_archived_is_a_terminal_state_with_no_further_transitions():
    assert QC_TRANSITIONS[QCCaseStatus.ARCHIVED] == frozenset()


def test_qc_passed_can_only_go_to_archived():
    assert QC_TRANSITIONS[QCCaseStatus.QC_PASSED] == frozenset({QCCaseStatus.ARCHIVED})


def test_qc_failed_can_only_go_to_needs_review():
    assert QC_TRANSITIONS[QCCaseStatus.QC_FAILED] == frozenset({QCCaseStatus.NEEDS_REVIEW})


def test_decide_qc_outcome_passes_when_clean_and_no_quality_signal():
    assert decide_qc_outcome(needs_review=False, quality_status=None) == QCCaseStatus.QC_PASSED


def test_decide_qc_outcome_fails_when_needs_review_true():
    assert decide_qc_outcome(needs_review=True, quality_status=None) == QCCaseStatus.QC_FAILED


def test_decide_qc_outcome_fails_on_invalid_quality_even_if_text_is_clean():
    """Kern van de afweging: onbetrouwbare data kan geen goede tekst
    'redden' -- INVALID faalt ALTIJD, ongeacht qc_result.needs_review."""
    assert decide_qc_outcome(needs_review=False, quality_status=QualityStatus.INVALID) == QCCaseStatus.QC_FAILED


def test_decide_qc_outcome_does_not_auto_fail_on_degraded_alone():
    """DEGRADED (bijv. een stale bron) dwingt GEEN automatische FAIL af --
    dat zou NEEDS_REVIEW te snel laten vollopen met bruikbare-maar-niet-
    perfecte gevallen. Blijft zichtbaar via qc_issues, niet via een
    verplichte FAIL (zie docs/architecture.md)."""
    assert decide_qc_outcome(needs_review=False, quality_status=QualityStatus.DEGRADED) == QCCaseStatus.QC_PASSED


def test_decide_qc_outcome_fails_when_both_needs_review_and_degraded():
    assert decide_qc_outcome(needs_review=True, quality_status=QualityStatus.DEGRADED) == QCCaseStatus.QC_FAILED
