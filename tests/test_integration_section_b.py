"""
test_integration_section_b.py
Stap B.4: "End-to-end testen: monitoring -> trigger -> escalatie -> synthese
-> database". Draait het monetary-policy- en currency-duo (B.1/B.2) samen
door de volledige keten, met een gesimuleerd Fed-besluit dat BEIDE domeinen
tegelijk raakt (het expliciete voorbeeld uit het stappenplan zelf) -- geen
echte netwerkcalls of API-keys nodig, fetch_snapshot() en de Anthropic-
client zijn beide monkeypatched/fake, zelfde aanpak als analyst_agent.ai's
eigen testsuite.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import agents.currency_agent as ca
import agents.monetary_policy_agent as mpa
from manager.manager import dispatch
from storage.schema import init_db, load_latest_claims
from synthesizer.synthesizer import synthesize_simultaneous


def _fake_client(narrative_text, qc_issues=None):
    client = MagicMock()
    responses = [MagicMock(content=[MagicMock(type="text", text=narrative_text)])]
    import json

    responses.append(MagicMock(content=[MagicMock(type="text", text=json.dumps({"issues": qc_issues or []}))]))
    it = iter(responses)
    client.messages.create = lambda **kwargs: next(it)
    return client


def test_full_monitoring_trigger_escalation_synthesis_database_pipeline(tmp_path):
    conn = init_db(str(tmp_path / "b_integration.db"))
    t_baseline = datetime.now(timezone.utc)
    t_fed_decision = t_baseline + timedelta(days=30)

    # -- Baseline-run voor beide domeinen: eerste observatie, geen trigger mogelijk --
    mpa_original = mpa.fetch_snapshot
    ca_original = ca.fetch_snapshot
    try:
        mpa.fetch_snapshot = lambda: {"fed_funds_rate": {"value": "5.25", "date": "2026-01-01"}}
        ca.fetch_snapshot = lambda: {"eur_usd": {"value": "1.0800", "date": "2026-01-01"}}

        baseline_mpa_output, baseline_mpa_triggers = mpa.monitor(conn, now=t_baseline)
        baseline_ca_output, baseline_ca_triggers = ca.monitor(conn, now=t_baseline)
        assert baseline_mpa_triggers == []
        assert baseline_ca_triggers == []

        # -- Fed-besluit: raakt monetary policy EN currency tegelijk (het
        # voorbeeld dat het stappenplan zelf noemt voor de manager, A.6) --
        mpa.fetch_snapshot = lambda: {"fed_funds_rate": {"value": "5.75", "date": "2026-01-31"}}  # +0.50pp, > tolerance 0.25
        ca.fetch_snapshot = lambda: {"eur_usd": {"value": "1.0650", "date": "2026-01-31"}}  # -0.015, > tolerance 0.01

        mpa_output, mpa_triggers = mpa.monitor(conn, now=t_fed_decision)
        ca_output, ca_triggers = ca.monitor(conn, now=t_fed_decision)
    finally:
        mpa.fetch_snapshot = mpa_original
        ca.fetch_snapshot = ca_original

    assert len(mpa_triggers) == 1
    assert len(ca_triggers) == 1

    # -- A.6: manager groepeert de gelijktijdige triggers --
    all_triggers = mpa_triggers + ca_triggers
    plan = dispatch(all_triggers, now=t_fed_decision)
    assert set(plan.domains) == {"monetary_policy", "currency"}
    assert plan.is_simultaneous is True

    # -- B.1/B.2 deep-dive mode voor elk geëscaleerd domein --
    mpa_client = _fake_client("De Fed funds rate steeg 0.50pp naar 5.75%, boven de eerdere waarde.")
    ca_client = _fake_client("EUR/USD daalde naar 1.0650, een significante beweging t.o.v. de vorige observatie.")

    mpa_deep_dive = mpa.deep_dive(conn, mpa_client, mpa_output.claims, plan.escalations["monetary_policy"], now=t_fed_decision)
    ca_deep_dive = ca.deep_dive(conn, ca_client, ca_output.claims, plan.escalations["currency"], now=t_fed_decision)

    assert mpa_deep_dive.needs_review is False
    assert ca_deep_dive.needs_review is False

    # -- B.3: synthese legt beide deep-dives naast elkaar --
    synthesis = synthesize_simultaneous(plan, {"monetary_policy": mpa_deep_dive, "currency": ca_deep_dive})
    assert set(synthesis.domains) == {"monetary_policy", "currency"}
    assert synthesis.any_needs_review is False
    markdown = synthesis.to_markdown()
    assert "5.75%" in markdown
    assert "1.0650" in markdown

    # -- database: alles is daadwerkelijk terug te lezen (source of truth, A.2) --
    stored_mpa_claims = load_latest_claims(conn, "monetary_policy", metric_key="fed_funds_rate")
    assert stored_mpa_claims[0].value == 5.75
    stored_ca_claims = load_latest_claims(conn, "currency", metric_key="eur_usd")
    assert stored_ca_claims[0].value == 1.065

    trigger_rows = conn.execute("SELECT domain, dispatch_batch_id FROM trigger_events").fetchall()
    # De trigger_events-tabel is er (A.2), maar dispatch() zelf schrijft er
    # nog niet automatisch naar -- dat gebeurt expliciet door de aanroeper
    # (zie test_integration_section_a.py). Hier verifiëren we alleen dat de
    # tabel bestaat en leeg is zolang niemand het expliciet vastlegt.
    assert trigger_rows == []

    domain_output_rows = conn.execute("SELECT domain, mode FROM domain_outputs ORDER BY id").fetchall()
    assert ("monetary_policy", "monitoring") in domain_output_rows
    assert ("currency", "monitoring") in domain_output_rows
    assert ("monetary_policy", "deep_dive") in domain_output_rows
    assert ("currency", "deep_dive") in domain_output_rows
