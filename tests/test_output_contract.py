from datetime import datetime, timezone

import pytest
from contract.output_contract import Claim, DomainOutput, Mode


def _claim(**overrides):
    defaults = dict(
        domain="monetary_policy",
        claim="Fed funds rate boven marktverwachting",
        value=5.5,
        source="FRED",
        confidence=0.85,
        analysis_time=datetime.now(timezone.utc),
        metric_key="fed_funds_rate",
    )
    defaults.update(overrides)
    return Claim(**defaults)


def test_valid_claim_roundtrips_through_dict():
    c = _claim()
    restored = Claim.from_dict(c.to_dict())
    assert restored == c


def test_claim_roundtrip_preserves_four_distinct_timestamps():
    """Sterkere versie van de basis-roundtrip-test: vier VERSCHILLENDE
    tz-aware datetimes per veld, zodat een per-ongeluk-verwisseld veld
    (bijv. event_time en source_time omgedraaid in to_dict/from_dict) niet
    onopgemerkt zou blijven doordat de waarden toevallig gelijk zijn."""
    c = _claim(
        analysis_time=datetime(2026, 1, 4, tzinfo=timezone.utc),
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ingestion_time=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    restored = Claim.from_dict(c.to_dict())
    assert restored.analysis_time == c.analysis_time
    assert restored.event_time == c.event_time
    assert restored.source_time == c.source_time
    assert restored.ingestion_time == c.ingestion_time


def test_claim_ingestion_time_defaults_to_analysis_time():
    now = datetime.now(timezone.utc)
    c = _claim(analysis_time=now)
    assert c.ingestion_time == now
    assert c.event_time is None
    assert c.source_time is None


def test_claim_without_source_is_rejected():
    with pytest.raises(ValueError):
        _claim(source="")


def test_claim_without_value_is_rejected():
    with pytest.raises(ValueError):
        _claim(value=None)


def test_claim_confidence_out_of_range_is_rejected():
    with pytest.raises(ValueError):
        _claim(confidence=1.5)


def test_claim_naive_analysis_time_is_rejected():
    with pytest.raises(ValueError):
        _claim(analysis_time=datetime(2026, 1, 1))


def test_claim_naive_source_time_is_rejected():
    with pytest.raises(ValueError):
        _claim(source_time=datetime(2026, 1, 1))


def test_claim_naive_event_time_is_rejected():
    with pytest.raises(ValueError):
        _claim(event_time=datetime(2026, 1, 1))


def test_domain_output_rejects_claim_from_other_domain():
    mismatched = _claim(domain="currency")
    with pytest.raises(ValueError):
        DomainOutput(
            domain="monetary_policy",
            mode=Mode.MONITORING,
            generated_at=datetime.now(timezone.utc),
            claims=[mismatched],
        )


def test_checkable_claims_filters_on_metric_key():
    with_key = _claim(metric_key="fed_funds_rate")
    without_key = _claim(claim="Kwalitatieve duiding", metric_key=None)
    output = DomainOutput(
        domain="monetary_policy",
        mode=Mode.MONITORING,
        generated_at=datetime.now(timezone.utc),
        claims=[with_key, without_key],
    )
    assert output.checkable_claims() == [with_key]


def test_domain_output_json_roundtrip():
    output = DomainOutput(
        domain="monetary_policy",
        mode=Mode.DEEP_DIVE,
        generated_at=datetime.now(timezone.utc),
        claims=[_claim()],
        needs_review=True,
        review_issues=["mogelijke inconsistentie"],
    )
    restored = DomainOutput.from_dict(output.to_dict())
    assert restored.domain == output.domain
    assert restored.mode == output.mode
    assert restored.needs_review is True
    assert restored.claims == output.claims
