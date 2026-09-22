from datetime import datetime, timezone

from manager.manager import dispatch
from triggers.trigger_engine import TriggerEvent


def _event(domain, severity="medium"):
    return TriggerEvent(domain=domain, triggered_at=datetime.now(timezone.utc), reason="test", severity=severity)


def test_dispatch_single_domain_is_not_simultaneous():
    plan = dispatch([_event("monetary_policy")])
    assert plan.domains == ["monetary_policy"]
    assert plan.is_simultaneous is False


def test_dispatch_groups_multiple_domains_as_simultaneous():
    plan = dispatch([_event("monetary_policy"), _event("currency"), _event("equity")])
    assert set(plan.domains) == {"monetary_policy", "currency", "equity"}
    assert plan.is_simultaneous is True


def test_dispatch_groups_multiple_events_per_domain():
    plan = dispatch([_event("monetary_policy"), _event("monetary_policy")])
    assert len(plan.escalations["monetary_policy"]) == 2
    assert plan.is_simultaneous is False


def test_dispatch_empty_list_produces_empty_plan():
    plan = dispatch([])
    assert plan.domains == []
    assert plan.is_simultaneous is False


def test_highest_severity_picks_max():
    plan = dispatch([_event("monetary_policy", "low"), _event("monetary_policy", "high")])
    assert plan.highest_severity("monetary_policy") == "high"


def test_highest_severity_none_for_unknown_domain():
    plan = dispatch([_event("monetary_policy")])
    assert plan.highest_severity("currency") is None


def test_each_dispatch_gets_unique_batch_id():
    plan1 = dispatch([_event("monetary_policy")])
    plan2 = dispatch([_event("monetary_policy")])
    assert plan1.batch_id != plan2.batch_id
