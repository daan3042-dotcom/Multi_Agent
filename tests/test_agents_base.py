from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from agents.base import SHARED_QUALITY_RULES, AlreadyProcessedError, MetricSpec, evaluate_deltas, run_deep_dive, run_monitoring
from contract.output_contract import Claim, Confidence, Mode
from health.data_health import QualityStatus
from qc.qc import QCCaseStatus
from storage.schema import init_db, latest_qc_case, list_agent_runs, list_qc_cases

SPECS = {"fed_funds_rate": MetricSpec(label="Fed funds rate", tolerance=0.25, severity="high")}


def _db(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def test_run_monitoring_saves_claims_and_no_trigger_on_first_observation(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    fetch = lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}

    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", fetch, SPECS, timedelta(days=35), now=now)

    assert output is not None
    assert output.mode == Mode.MONITORING
    assert output.claims[0].value == 5.5
    assert triggers == []  # eerste observatie, niets om tegen te vergelijken

    runs = list_agent_runs(conn, "monetary_policy")
    assert len(runs) == 1
    assert runs[0]["mode"] == "monitoring"
    assert runs[0]["success"] is True
    assert runs[0]["domain_output_id"] is not None
    assert runs[0]["trigger_count"] == 0


def test_run_monitoring_triggers_on_significant_delta(tmp_path):
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=30)

    run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}, SPECS, timedelta(days=35), now=t1)
    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "2026-01-31"}}, SPECS, timedelta(days=35), now=t2)

    assert output is not None
    assert len(triggers) == 1
    assert triggers[0].metric_key == "fed_funds_rate"
    assert triggers[0].severity == "high"


def test_run_monitoring_triggers_on_revision_of_already_reported_period(tmp_path):
    """Zelfde source_time (periode) tweemaal, een kleine waardewijziging
    ruim binnen de delta-tolerantie -- toont dat het een REVISIE-trigger
    is (geen delta-trigger), roadmap 1.3."""
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=1)

    run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}, SPECS, timedelta(days=35), now=t1)
    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.45", "date": "2026-01-01"}}, SPECS, timedelta(days=35), now=t2)

    assert output is not None
    assert len(triggers) == 1  # geen delta-trigger (0.05 < tolerantie 0.25), wel een revisie
    assert triggers[0].reason.startswith("Revisie:")
    assert triggers[0].metric_key == "fed_funds_rate"


def test_run_monitoring_no_revision_trigger_for_unchanged_repeated_period(tmp_path):
    """Dagelijks pollen van een maandcijfer dat nog niet is bijgewerkt mag
    NOOIT als revisie tellen -- alleen een daadwerkelijk andere waarde
    voor dezelfde periode is een revisie."""
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=1)

    run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}, SPECS, timedelta(days=35), now=t1)
    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}, SPECS, timedelta(days=35), now=t2)

    assert output is not None
    assert triggers == []


def test_run_monitoring_no_trigger_within_tolerance(tmp_path):
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=30)

    run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}, SPECS, timedelta(days=35), now=t1)
    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.55", "date": "2026-01-31"}}, SPECS, timedelta(days=35), now=t2)

    assert output is not None
    assert triggers == []


def test_run_monitoring_total_failure_produces_data_health_trigger_no_output(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    fetch = lambda: {"error": "FRED_API_KEY niet gevonden"}

    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", fetch, SPECS, timedelta(days=35), now=now)

    assert output is None
    assert len(triggers) == 1
    assert triggers[0].reason.startswith("data_health:")

    runs = list_agent_runs(conn, "monetary_policy")
    assert len(runs) == 1
    assert runs[0]["success"] is False
    assert runs[0]["domain_output_id"] is None
    assert "FRED_API_KEY" in runs[0]["error"]


def test_run_monitoring_no_parseable_metrics_still_records_agent_run(tmp_path):
    """Snapshot zelf is geen fout (geen "error"-key), maar geen enkele
    entry is als float te parsen -- ander faalpad dan een totale pull-
    mislukking, moet ook een eigen agent_run wegschrijven."""
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    fetch = lambda: {"fed_funds_rate": {"value": "niet-een-getal"}}

    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", fetch, SPECS, timedelta(days=35), now=now)

    assert output is None
    runs = list_agent_runs(conn, "monetary_policy")
    assert len(runs) == 1
    assert runs[0]["success"] is False
    assert runs[0]["domain_output_id"] is None


def _claim(metric_key, value, now):
    return Claim(domain="monetary_policy", claim="test", value=value, source="test", confidence=Confidence.HIGH, analysis_time=now, metric_key=metric_key)


def test_evaluate_deltas_triggers_on_significant_change():
    now = datetime.now(timezone.utc)
    new_claim = _claim("fed_funds_rate", 5.85, now)
    previous_by_metric = {"fed_funds_rate": [_claim("fed_funds_rate", 5.50, now - timedelta(days=1))]}

    triggers = evaluate_deltas("monetary_policy", [new_claim], SPECS, previous_by_metric, now=now)
    assert len(triggers) == 1
    assert triggers[0].metric_key == "fed_funds_rate"


def test_evaluate_deltas_no_trigger_without_previous_observation():
    now = datetime.now(timezone.utc)
    new_claim = _claim("fed_funds_rate", 5.85, now)
    triggers = evaluate_deltas("monetary_policy", [new_claim], SPECS, previous_by_metric={}, now=now)
    assert triggers == []


def test_evaluate_deltas_ignores_claims_without_a_spec():
    now = datetime.now(timezone.utc)
    new_claim = _claim("unspecced_metric", 999.0, now)
    previous_by_metric = {"unspecced_metric": [_claim("unspecced_metric", 0.0, now - timedelta(days=1))]}
    triggers = evaluate_deltas("monetary_policy", [new_claim], SPECS, previous_by_metric, now=now)
    assert triggers == []


def test_run_monitoring_fetch_exception_is_caught(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)

    def fetch():
        raise ConnectionError("timeout")

    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", fetch, SPECS, timedelta(days=35), now=now)

    assert output is None
    assert len(triggers) == 1


def _fake_client(response_text):
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text=response_text)]
    client.messages.create = lambda **kwargs: response
    return client


def test_run_deep_dive_saves_narrative_claim_and_needs_review_false_when_clean(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "x"}}, SPECS, timedelta(days=35), now=now)

    client = _fake_client('{"issues": []}')
    deep_dive_output = run_deep_dive(conn, client, "monetary_policy", "systeemprompt", output.claims, [], now=now)

    assert deep_dive_output.mode == Mode.DEEP_DIVE
    assert deep_dive_output.needs_review is False
    assert any(c.claim == "Deep-dive synthese" for c in deep_dive_output.claims)

    deep_dive_runs = [r for r in list_agent_runs(conn, "monetary_policy") if r["mode"] == "deep_dive"]
    assert len(deep_dive_runs) == 1
    assert deep_dive_runs[0]["success"] is True
    assert deep_dive_runs[0]["domain_output_id"] is not None


def test_run_deep_dive_needs_review_true_when_llm_review_flags_issue(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    output, _ = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "x"}}, SPECS, timedelta(days=35), now=now)

    client = MagicMock()
    responses = iter([
        MagicMock(content=[MagicMock(type="text", text="Dit is de deep-dive tekst.")]),
        MagicMock(content=[MagicMock(type="text", text='{"issues": ["gevonden probleem"]}')]),
    ])
    client.messages.create = lambda **kwargs: next(responses)

    deep_dive_output = run_deep_dive(conn, client, "monetary_policy", "systeemprompt", output.claims, [], now=now)
    assert deep_dive_output.needs_review is True
    assert "gevonden probleem" in deep_dive_output.review_issues


def test_run_deep_dive_llm_failure_is_never_silent(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    output, _ = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "x"}}, SPECS, timedelta(days=35), now=now)

    client = MagicMock()
    client.messages.create = lambda **kwargs: (_ for _ in ()).throw(Exception("API-fout"))

    deep_dive_output = run_deep_dive(conn, client, "monetary_policy", "systeemprompt", output.claims, [], now=now)
    assert deep_dive_output.needs_review is True
    assert any("Deep-dive mislukt" in c.claim for c in deep_dive_output.claims)

    deep_dive_runs = [r for r in list_agent_runs(conn, "monetary_policy") if r["mode"] == "deep_dive"]
    assert len(deep_dive_runs) == 1
    assert deep_dive_runs[0]["success"] is False
    assert "API-fout" in deep_dive_runs[0]["error"]


def test_run_deep_dive_prepends_shared_quality_rules_to_domain_prompt(tmp_path):
    """Bewijst dat elke domain agent de gedeelde huisstijl-regels ECHT
    meekrijgt in de daadwerkelijke API-call, niet alleen dat het los
    getest is -- geen enkele domain agent kan dit per ongeluk overslaan,
    want dit gebeurt in run_deep_dive() zelf, niet in de aanroeper."""
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    output, _ = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "x"}}, SPECS, timedelta(days=35), now=now)

    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Neutrale duiding.")]
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return response

    client.messages.create = fake_create

    domain_specific_prompt = "Je bent een unieke, domeinspecifieke testinstructie."
    run_deep_dive(conn, client, "monetary_policy", domain_specific_prompt, output.claims, [], now=now)

    # run_deep_dive doet ZELF ook een LLM-review-call (qc.default_llm_review) na
    # de deep-dive-call zelf -- expliciet de deep-dive-call opzoeken (die met de
    # domeinspecifieke instructie) in plaats van blind de laatste call te pakken.
    deep_dive_call = next(c for c in calls if domain_specific_prompt in c["system"])
    sent_system_prompt = deep_dive_call["system"]
    assert SHARED_QUALITY_RULES in sent_system_prompt
    assert sent_system_prompt.index(SHARED_QUALITY_RULES) < sent_system_prompt.index(domain_specific_prompt)


def test_run_monitoring_raises_when_event_id_already_successfully_processed(tmp_path):
    """Roadmap 1.7 deel 2: een tweede aanroep met hetzelfde event_id mag
    NIET opnieuw fetchen -- de fetch-functie mag daarom niet eens
    aangeroepen worden."""
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    fetch = lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}

    run_monitoring(conn, "monetary_policy", "FRED", fetch, SPECS, timedelta(days=35), now=now, event_id="cycle-1")

    def fetch_should_not_be_called():
        raise AssertionError("fetch_snapshot_fn werd aangeroepen ondanks al-verwerkt event_id")

    with pytest.raises(AlreadyProcessedError):
        run_monitoring(conn, "monetary_policy", "FRED", fetch_should_not_be_called, SPECS, timedelta(days=35), now=now, event_id="cycle-1")

    # geen dubbele claims/agent_run door de geweigerde tweede aanroep
    assert len(list_agent_runs(conn, "monetary_policy")) == 1


def test_run_monitoring_allows_retry_with_same_event_id_after_a_failure(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    failing_fetch = lambda: {"error": "timeout"}
    working_fetch = lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}

    output1, _ = run_monitoring(conn, "monetary_policy", "FRED", failing_fetch, SPECS, timedelta(days=35), now=now, event_id="cycle-1")
    assert output1 is None

    # geen AlreadyProcessedError: de vorige poging mislukte, dit is een legitieme retry
    output2, _ = run_monitoring(conn, "monetary_policy", "FRED", working_fetch, SPECS, timedelta(days=35), now=now, event_id="cycle-1")
    assert output2 is not None


def test_run_monitoring_without_event_id_never_raises(tmp_path):
    """Backward-compatible: bestaande aanroepers die geen event_id
    meegeven (alle 6 domain agents op dit moment) merken niets van deze
    uitbreiding."""
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    fetch = lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}

    run_monitoring(conn, "monetary_policy", "FRED", fetch, SPECS, timedelta(days=35), now=now)
    output, _ = run_monitoring(conn, "monetary_policy", "FRED", fetch, SPECS, timedelta(days=35), now=now)
    assert output is not None  # geen AlreadyProcessedError zonder event_id


def test_run_deep_dive_raises_when_event_id_already_successfully_processed(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    output, _ = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "x"}}, SPECS, timedelta(days=35), now=now)

    client = _fake_client('{"issues": []}')
    run_deep_dive(conn, client, "monetary_policy", "systeemprompt", output.claims, [], now=now, event_id="batch-1")

    def create_should_not_be_called(**kwargs):
        raise AssertionError("client.messages.create werd aangeroepen ondanks al-verwerkt event_id")

    client_should_not_be_called = MagicMock()
    client_should_not_be_called.messages.create = create_should_not_be_called

    with pytest.raises(AlreadyProcessedError):
        run_deep_dive(conn, client_should_not_be_called, "monetary_policy", "systeemprompt", output.claims, [], now=now, event_id="batch-1")

    deep_dive_runs = [r for r in list_agent_runs(conn, "monetary_policy") if r["mode"] == "deep_dive"]
    assert len(deep_dive_runs) == 1


def test_run_deep_dive_without_event_id_never_raises(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    output, _ = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "x"}}, SPECS, timedelta(days=35), now=now)

    client = _fake_client('{"issues": []}')
    run_deep_dive(conn, client, "monetary_policy", "systeemprompt", output.claims, [], now=now)
    deep_dive_output = run_deep_dive(conn, client, "monetary_policy", "systeemprompt", output.claims, [], now=now)
    assert deep_dive_output is not None


def test_run_monitoring_opens_qc_case_when_triggered(tmp_path):
    """Roadmap 1.6: een case ontstaat pas zodra er ECHT een trigger is --
    geen losse rij voor elke rustige, niet-triggerende poll."""
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=30)
    run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}, SPECS, timedelta(days=35), now=t1)
    run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "2026-01-31"}}, SPECS, timedelta(days=35), now=t2)

    case = latest_qc_case(conn, "monetary_policy", QCCaseStatus.TRIGGERED)
    assert case is not None
    assert case.domain == "monetary_policy"
    assert any("Fed funds rate" in r for r in case.trigger_reasons)


def test_run_monitoring_no_qc_case_without_a_trigger(tmp_path):
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}, SPECS, timedelta(days=35), now=now)

    assert list_qc_cases(conn, "monetary_policy") == []


def test_full_pipeline_ends_at_qc_passed_when_clean(tmp_path):
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=30)
    run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}, SPECS, timedelta(days=35), now=t1)
    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "2026-01-31"}}, SPECS, timedelta(days=35), now=t2)

    client = _fake_client('{"issues": []}')
    run_deep_dive(conn, client, "monetary_policy", "systeemprompt", output.claims, triggers, now=t2)

    case = latest_qc_case(conn, "monetary_policy", QCCaseStatus.QC_PASSED)
    assert case is not None
    assert case.domain_output_id is not None
    assert case.qc_issues == []


def test_full_pipeline_ends_at_needs_review_when_qc_flags_issue(tmp_path):
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=30)
    run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}, SPECS, timedelta(days=35), now=t1)
    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "2026-01-31"}}, SPECS, timedelta(days=35), now=t2)

    client = MagicMock()
    responses = iter([
        MagicMock(content=[MagicMock(type="text", text="Dit is de deep-dive tekst.")]),
        MagicMock(content=[MagicMock(type="text", text='{"issues": ["gevonden probleem"]}')]),
    ])
    client.messages.create = lambda **kwargs: next(responses)
    run_deep_dive(conn, client, "monetary_policy", "systeemprompt", output.claims, triggers, now=t2)

    case = latest_qc_case(conn, "monetary_policy", QCCaseStatus.NEEDS_REVIEW)
    assert case is not None
    assert case.qc_issues == ["gevonden probleem"]


def test_full_pipeline_ends_at_needs_review_when_llm_call_fails(tmp_path):
    conn = _db(tmp_path)
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=30)
    run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.50", "date": "2026-01-01"}}, SPECS, timedelta(days=35), now=t1)
    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", lambda: {"fed_funds_rate": {"value": "5.85", "date": "2026-01-31"}}, SPECS, timedelta(days=35), now=t2)

    client = MagicMock()
    client.messages.create = lambda **kwargs: (_ for _ in ()).throw(Exception("API-fout"))
    run_deep_dive(conn, client, "monetary_policy", "systeemprompt", output.claims, triggers, now=t2)

    case = latest_qc_case(conn, "monetary_policy", QCCaseStatus.NEEDS_REVIEW)
    assert case is not None
    assert case.qc_issues == ["API-fout"]


def test_data_health_trigger_forces_qc_failed_even_with_clean_text(tmp_path):
    """DEEL 2, kernafweging: een QualityStatus.INVALID-signaal (hier: een
    data_health-trigger met severity high, oftewel een onbereikbare bron)
    faalt de QC-case ALTIJD, ongeacht een verder perfect geschreven tekst
    -- en forceert ook DomainOutput.needs_review=True."""
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)

    def failing_fetch():
        raise ConnectionError("FRED onbereikbaar")

    output, triggers = run_monitoring(conn, "monetary_policy", "FRED", failing_fetch, SPECS, timedelta(days=35), now=now)
    assert any(t.reason.startswith("data_health:") for t in triggers)

    client = _fake_client('{"issues": []}')  # tekst-QC zelf is brandschoon
    deep_dive_output = run_deep_dive(conn, client, "monetary_policy", "systeemprompt", [], triggers, now=now)

    assert deep_dive_output.needs_review is True
    assert any("INVALID" in issue for issue in deep_dive_output.review_issues)

    case = latest_qc_case(conn, "monetary_policy", QCCaseStatus.NEEDS_REVIEW)
    assert case is not None
    assert case.quality_status == QualityStatus.INVALID


def test_run_deep_dive_without_an_open_case_does_not_crash(tmp_path):
    """On-demand/handmatige deep-dive zonder voorafgaande trigger (bestaand,
    ondersteund gebruik -- zie run_deep_dive()'s eigen 'on-demand
    aangevraagd'-fallback) -- er is dan simpelweg geen case om te volgen,
    geen foutmelding."""
    conn = _db(tmp_path)
    now = datetime.now(timezone.utc)
    client = _fake_client('{"issues": []}')

    output = run_deep_dive(conn, client, "monetary_policy", "systeemprompt", [], [], now=now)
    assert output is not None
    assert list_qc_cases(conn, "monetary_policy") == []


def test_shared_quality_rules_bans_directional_advice_language():
    """Vangnet tegen zelf een keer per ongeluk de kernregels verzwakken --
    dit zijn de concrete, niet-onderhandelbare eisen uit de afspraak in
    CLAUDE.md ('Werkwijze met DD'), niet alleen losse sfeerbewoording."""
    assert "koop/verkoop-advies" in SHARED_QUALITY_RULES
    assert "VERBODEN patronen" in SHARED_QUALITY_RULES
    assert "ALLEEN DE AANGELEVERDE CLAIMS" in SHARED_QUALITY_RULES
    assert "ONZEKERHEID EXPLICIET" in SHARED_QUALITY_RULES
