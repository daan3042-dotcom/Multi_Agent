from datetime import datetime, timezone

from contract.output_contract import Claim
from qc.qc import apply_qc, deterministic_consistency_check


def _claim(**overrides):
    defaults = dict(
        domain="monetary_policy", claim="fed_funds_rate", value=5.5, source="FRED",
        confidence=0.85, timestamp=datetime.now(timezone.utc), metric_key="fed_funds_rate",
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
