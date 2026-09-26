"""Tests voor roadmap 1.11 (Scheduler & Runtime) -- de dagelijkse cyclus.

Alle tests injecteren verzonnen agents (`AgentSpec` met een eigen
monitor-functie), zelfde aanpak als de bestaande agent-tests die
fetch-functies injecteren: geen netwerk, geen API-keys, geen echte
domain-agent-module in beeld.
"""

from datetime import date, datetime, timedelta, timezone

import sqlite3

from agents.base import AlreadyProcessedError, MetricSpec, run_monitoring
from contract.output_contract import Claim, Confidence, DomainOutput, Mode
from health.data_health import HealthStatus
from runtime.daily import AgentSpec, daily_event_id, run_daily
from storage.schema import init_db, list_agent_runs, register_source
from triggers.trigger_engine import TriggerEvent


def _db(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def _output(domain, now):
    return DomainOutput(
        domain=domain,
        mode=Mode.MONITORING,
        generated_at=now,
        claims=[
            Claim(
                domain=domain,
                claim="Testmetric",
                value=1.0,
                source="test",
                confidence=Confidence.HIGH,
                analysis_time=now,
                metric_key="testmetric",
            )
        ],
    )


def _ok_agent(domain, triggers=None):
    """Een agent die het altijd goed doet."""

    def monitor(conn, now=None, event_id=None):
        return _output(domain, now), list(triggers or [])

    return AgentSpec(domain, monitor)


def _failing_agent(domain, reason="bron onbereikbaar"):
    """Bootst run_monitoring()'s gedrag bij een mislukte pull na:
    (None, [data-health-trigger]) -- geen exception."""

    def monitor(conn, now=None, event_id=None):
        trigger = TriggerEvent(domain=domain, triggered_at=now, reason=reason, severity="high")
        return None, [trigger]

    return AgentSpec(domain, monitor)


def _crashing_agent(domain):
    def monitor(conn, now=None, event_id=None):
        raise RuntimeError("onverwachte bug")

    return AgentSpec(domain, monitor)


# --------------------------------------------------------------------------
# event_id -- de kern van de idempotency (roadmap 1.7, hier eindelijk gebruikt)
# --------------------------------------------------------------------------


def test_daily_event_id_is_stable_per_calendar_day():
    morning = datetime(2026, 11, 10, 7, 15, tzinfo=timezone.utc)
    evening = datetime(2026, 11, 10, 23, 59, tzinfo=timezone.utc)
    assert daily_event_id(morning) == daily_event_id(evening) == "daily:2026-11-10"


def test_daily_event_id_differs_across_days():
    assert daily_event_id(date(2026, 11, 10)) != daily_event_id(date(2026, 11, 11))


def test_second_run_on_same_day_is_skipped_not_refetched(tmp_path):
    """Het regressiegeval waar 1.7 voor gebouwd is: cron vuurt twee keer,
    of DD draait 'm handmatig na. De tweede keer mag NIET opnieuw fetchen."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, 7, 15, tzinfo=timezone.utc)
    calls = []

    def monitor(conn_, now=None, event_id=None):
        calls.append(event_id)
        return run_monitoring(
            conn_,
            "testdomain",
            "TEST_SOURCE",
            lambda: {"testmetric": {"value": 1.0, "date": "2026-11-09"}},
            {"testmetric": MetricSpec(label="Testmetric", tolerance=0.5)},
            timedelta(days=2),
            now=now,
            event_id=event_id,
        )

    agents = [AgentSpec("testdomain", monitor)]

    first = run_daily(conn, agents=agents, now=now)
    second = run_daily(conn, agents=agents, now=now)

    assert [o.status for o in first.outcomes] == ["ok"]
    assert [o.status for o in second.outcomes] == ["skipped"]
    assert len(calls) == 2  # de wrapper werd wel aangeroepen...
    # ...maar run_monitoring gooide AlreadyProcessedError vóór de fetch, dus
    # er staat maar ÉÉN succesvolle run in de audit-log.
    runs = list_agent_runs(conn, "testdomain", mode="monitoring")
    assert len([r for r in runs if r["success"]]) == 1


def test_next_day_runs_again(tmp_path):
    conn = _db(tmp_path)
    day1 = datetime(2026, 11, 10, 7, 15, tzinfo=timezone.utc)
    day2 = datetime(2026, 11, 11, 7, 15, tzinfo=timezone.utc)
    agents = [_ok_agent("testdomain")]

    assert run_daily(conn, agents=agents, now=day1).outcomes[0].status == "ok"
    assert run_daily(conn, agents=agents, now=day2).outcomes[0].status == "ok"


# --------------------------------------------------------------------------
# Foutisolatie -- één stukke agent mag de rest niet meeslepen
# --------------------------------------------------------------------------


def test_one_crashing_agent_does_not_stop_the_others(tmp_path):
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    agents = [_crashing_agent("kapot"), _ok_agent("werkt")]

    result = run_daily(conn, agents=agents, now=now)

    by_domain = {o.domain: o for o in result.outcomes}
    assert by_domain["kapot"].status == "crashed"
    assert "onverwachte bug" in by_domain["kapot"].error
    assert by_domain["werkt"].status == "ok"


def test_failed_pull_is_distinguished_from_a_crash(tmp_path):
    """Een onbereikbare bron is iets anders dan een bug bij ons -- ze vragen
    om ander handelen, dus ze krijgen een andere status."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)

    result = run_daily(conn, agents=[_failing_agent("stil")], now=now)

    assert result.outcomes[0].status == "failed"
    assert result.has_problems


def test_skipped_is_not_counted_as_a_problem(tmp_path):
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)

    def monitor(conn_, now=None, event_id=None):
        raise AlreadyProcessedError("testdomain", "monitoring", event_id)

    result = run_daily(conn, agents=[AgentSpec("testdomain", monitor)], now=now)

    assert result.outcomes[0].status == "skipped"
    assert not result.has_problems


# --------------------------------------------------------------------------
# Deep-dives -- opt-in, kosten zijn een expliciete keuze
# --------------------------------------------------------------------------


def test_no_deep_dives_without_a_client(tmp_path):
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    called = []

    def deep_dive(conn_, client, claims, trigger_events, now=None, event_id=None):
        called.append(True)
        return _output("testdomain", now)

    trigger = TriggerEvent(domain="testdomain", triggered_at=now, reason="iets", severity="high")
    spec = AgentSpec("testdomain", _ok_agent("testdomain", [trigger]).monitor, deep_dive)

    run_daily(conn, agents=[spec], now=now, client=None)

    assert called == []


def test_deep_dive_runs_for_escalated_domain_when_client_given(tmp_path):
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    called = []

    def deep_dive(conn_, client, claims, trigger_events, now=None, event_id=None):
        called.append(event_id)
        return _output("testdomain", now)

    trigger = TriggerEvent(domain="testdomain", triggered_at=now, reason="iets", severity="high")
    spec = AgentSpec("testdomain", _ok_agent("testdomain", [trigger]).monitor, deep_dive)

    result = run_daily(conn, agents=[spec], now=now, client=object())

    assert called == ["daily:2026-11-10"]
    assert result.outcomes[0].deep_dive_ran


def test_deep_dive_only_for_domains_that_triggered(tmp_path):
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    called = []

    def deep_dive(conn_, client, claims, trigger_events, now=None, event_id=None):
        called.append("rustig")
        return _output("rustig", now)

    spec = AgentSpec("rustig", _ok_agent("rustig").monitor, deep_dive)
    run_daily(conn, agents=[spec], now=now, client=object())

    assert called == []


def test_failing_deep_dive_does_not_lose_the_monitoring_result(tmp_path):
    """De claims zijn al opgeslagen als de deep-dive stukgaat -- die data
    mag niet verloren gaan omdat een LLM-call faalde. Controleert de
    DATABASE, niet alleen het object in het geheugen."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)

    def deep_dive(conn_, client, claims, trigger_events, now=None, event_id=None):
        raise RuntimeError("LLM down")

    trigger = TriggerEvent(domain="d", triggered_at=now, reason="iets", severity="high")
    spec = AgentSpec("d", _real_monitor("d"), deep_dive)

    # Baseline-dag zodat er op dag 2 een delta-trigger vuurt.
    run_daily(conn, agents=[AgentSpec("d", _real_monitor("d", value=1.0))], now=now - timedelta(days=1), notifier=lambda n: None)
    spec = AgentSpec("d", _real_monitor("d", value=5.0), deep_dive)
    result = run_daily(conn, agents=[spec], now=now, client=object(), notifier=lambda n: None)

    assert result.outcomes[0].status == "ok"  # monitoring slaagde
    assert not result.outcomes[0].deep_dive_ran
    assert "LLM down" in result.outcomes[0].deep_dive_error
    assert result.outcomes[0].error is None  # de monitoring-fout blijft leeg
    # En de data staat écht in de database:
    rows = conn.execute("SELECT count(*) FROM claims WHERE domain = 'd'").fetchone()[0]
    assert rows >= 2


# --------------------------------------------------------------------------
# Fail-loud-notificatie (roadmap 1.7 deel 2 / 1.11)
# --------------------------------------------------------------------------


def test_no_notification_when_everything_is_fine(tmp_path):
    """Een dagelijkse 'alles goed'-melding traint je om meldingen te
    negeren -- dan is de melding die er wel toe doet ook onzichtbaar."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    sent = []

    result = run_daily(conn, agents=[_ok_agent("testdomain")], now=now, notifier=sent.append)

    assert result.notification is None
    assert sent == []


def test_crash_produces_a_critical_notification(tmp_path):
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    sent = []

    result = run_daily(conn, agents=[_crashing_agent("kapot")], now=now, notifier=sent.append)

    assert result.notification is not None
    assert result.notification.severity == "critical"
    assert len(sent) == 1
    assert "kapot" in sent[0].body


def test_all_agents_failing_is_critical_not_merely_a_warning(tmp_path):
    """Alle agents tegelijk stuk wijst op iets gedeelds (netwerk, DNS,
    rate limit), niet op één stukke bron."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)

    result = run_daily(conn, agents=[_failing_agent("a"), _failing_agent("b")], now=now, notifier=lambda n: None)

    assert result.notification.severity == "critical"


def test_one_of_several_failing_is_a_warning(tmp_path):
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)

    result = run_daily(conn, agents=[_failing_agent("a"), _ok_agent("b")], now=now, notifier=lambda n: None)

    assert result.notification.severity == "warning"


def test_stale_source_is_reported_even_when_every_agent_succeeds(tmp_path):
    """Het faalscenario waar de hele notificatielaag voor bestaat: het
    systeem meldt 'alles ok' terwijl een bron al dagen niet ververst is."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    register_source(conn, "OUDE_BRON", provider="TEST", domain="testdomain", max_age=timedelta(days=1))

    from storage.schema import record_data_health

    record_data_health(conn, "OUDE_BRON", now - timedelta(days=5), success=True)

    result = run_daily(conn, agents=[_ok_agent("testdomain")], now=now, notifier=lambda n: None)

    assert result.notification is not None
    assert result.health.status_for("source:OUDE_BRON") == HealthStatus.STALE
    assert "OUDE_BRON" in result.notification.body


def test_unknown_component_alone_does_not_trigger_a_notification(tmp_path):
    """Dag 1: de bron is geregistreerd maar heeft nog nooit gedraaid, dus
    zijn status is UNKNOWN. Dat is normaal, geen storing -- anders geeft
    elke allereerste run een valse melding en leert DD ze te negeren."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    register_source(conn, "NIEUWE_BRON", provider="TEST", domain="testdomain", max_age=timedelta(days=1))

    result = run_daily(conn, agents=[_ok_agent("testdomain")], now=now, notifier=lambda n: None)

    assert result.health.status_for("source:NIEUWE_BRON") == HealthStatus.UNKNOWN
    assert result.notification is None


def test_notifier_failure_does_not_crash_the_cycle(tmp_path):
    """De data is op dit punt al opgehaald en gecommit. Als een kapotte
    webhook de run alsnog laat crashen, ziet een geslaagde dag eruit als een
    mislukte -- en dan faalt uitgerekend de fail-loud-laag stil."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)

    def broken_notifier(notification):
        raise ConnectionError("webhook down")

    result = run_daily(conn, agents=[_crashing_agent("kapot")], now=now, notifier=broken_notifier)

    assert result.notification is not None  # de melding is wel opgebouwd
    assert result.outcomes[0].status == "crashed"  # en het resultaat klopt nog


def test_notifier_failure_is_logged_with_the_undelivered_content(tmp_path, caplog):
    """Regressiegeval bij de test hierboven: 'niet crashen' mag niet
    verworden tot 'stilzwijgend slikken'."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)

    def broken_notifier(notification):
        raise ConnectionError("webhook down")

    with caplog.at_level("ERROR"):
        run_daily(conn, agents=[_crashing_agent("kapot")], now=now, notifier=broken_notifier)

    assert "webhook down" in caplog.text
    assert "kapot" in caplog.text  # de inhoud die niet aankwam staat er ook in


# --------------------------------------------------------------------------
# Regressietests uit de code-review van 26-09-2026. Elk van deze dekt een
# bug die daadwerkelijk in de eerste versie zat -- ze zijn geschreven nadat
# het gedrag gemeten was, niet vooraf bedacht.
# --------------------------------------------------------------------------


def _real_monitor(domain, value=1.0, source="TEST_SOURCE"):
    """Een agent die ECHT door run_monitoring gaat, i.p.v. de fakes
    hierboven. Nodig voor de tests die databasegedrag controleren."""

    def monitor(conn, now=None, event_id=None):
        return run_monitoring(
            conn,
            domain,
            source,
            lambda: {"m": {"value": value, "date": "2026-11-09"}},
            {"m": MetricSpec(label="M", tolerance=0.0001)},
            timedelta(days=2),
            now=now,
            event_id=event_id,
        )

    return monitor


def _fake_deep_dive(calls):
    def deep_dive(conn, client, claims, trigger_events, now=None, event_id=None):
        calls.append({"claims": len(claims), "triggers": len(trigger_events), "event_id": event_id})
        return _output("d", now)

    return deep_dive


def test_claims_do_not_grow_exponentially_across_deep_dive_days(tmp_path):
    """Gemeten bug: `load_latest_claims()` geeft de HELE historie terug, en
    `run_deep_dive()` slaat de aangeleverde claims opnieuw op -- 2ⁿ groei
    (255 rijen na 8 dagen). Over zes maanden onbruikbaar."""
    conn = _db(tmp_path)

    def deep_dive(conn_, client, claims, trigger_events, now=None, event_id=None):
        from agents.base import run_deep_dive

        class FakeClient:
            class messages:
                @staticmethod
                def create(**kw):
                    return type("R", (), {"content": [type("B", (), {"text": "tekst"})()]})()

        return run_deep_dive(conn_, FakeClient(), "d", "p", claims, trigger_events, now=now, event_id=event_id)

    # Waarde verandert elke dag, dus er vuurt elke dag een delta-trigger.
    base = datetime(2026, 11, 1, tzinfo=timezone.utc)
    for i in range(8):
        spec = AgentSpec("d", _real_monitor("d", value=1.0 + i), deep_dive)
        run_daily(conn, agents=[spec], now=base + timedelta(days=i), client=object(), notifier=lambda n: None)

    rows = conn.execute("SELECT count(*) FROM claims").fetchone()[0]
    # Lineair, niet exponentieel: per dag één monitoring-claim plus de
    # deep-dive die diezelfde claim + een narratief opnieuw wegschrijft.
    assert rows < 40, f"claims groeien te hard: {rows} rijen na 8 dagen"


def test_triggers_are_persisted_to_the_database(tmp_path):
    """Gemeten bug: `record_trigger_event()` werd alleen in tests
    aangeroepen, dus vuurden er triggers die nergens werden vastgelegd --
    precies de reeks die 4.2's drempelkalibratie nodig heeft."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    trigger = TriggerEvent(
        domain="d", triggered_at=now, reason="iets", severity="high", metric_key="m", observed_value=2.0
    )

    run_daily(conn, agents=[_ok_agent("d", [trigger])], now=now, notifier=lambda n: None)

    rows = conn.execute("SELECT domain, reason, severity, metric_key FROM trigger_events").fetchall()
    assert rows == [("d", "iets", "high", "m")]


def test_failed_deep_dive_is_retried_on_a_rerun_of_the_same_day(tmp_path):
    """Gemeten bug, en de ergste: bij een herhaalde run is monitoring
    `skipped`, dus stonden er geen triggers meer in het geheugen en werd de
    deep-dive NOOIT opnieuw geprobeerd. Dat maakt het gat permanent -- juist
    in de aanbevolen werkwijze (cron zonder --deep-dives, later met de hand)."""
    conn = _db(tmp_path)
    baseline = datetime(2026, 11, 9, 7, 0, tzinfo=timezone.utc)
    now = datetime(2026, 11, 10, 7, 0, tzinfo=timezone.utc)
    later = datetime(2026, 11, 10, 19, 0, tzinfo=timezone.utc)
    calls = []

    # Baseline-dag: eerste observatie, dus nog niets om tegen te vergelijken.
    run_daily(conn, agents=[AgentSpec("d", _real_monitor("d", value=1.0))], now=baseline, notifier=lambda n: None)

    # Dag 2 vuurt een delta-trigger. Cron draait zonder --deep-dives.
    monitor = _real_monitor("d", value=9.0)
    run_daily(conn, agents=[AgentSpec("d", monitor, _fake_deep_dive(calls))], now=now, notifier=lambda n: None)
    assert calls == []
    assert conn.execute("SELECT count(*) FROM trigger_events").fetchone()[0] >= 1

    # Tweede run dezelfde dag, nu mét client: monitoring wordt overgeslagen,
    # maar de deep-dive moet alsnog draaien op de opgeslagen triggers.
    result = run_daily(
        conn,
        agents=[AgentSpec("d", monitor, _fake_deep_dive(calls))],
        now=later,
        client=object(),
        notifier=lambda n: None,
    )

    assert result.outcomes[0].status == "skipped"
    assert len(calls) == 1, "deep-dive is niet opnieuw geprobeerd na een overgeslagen monitoring"
    assert calls[0]["triggers"] >= 1, "de opgeslagen triggers zijn niet teruggehaald"
    assert calls[0]["claims"] >= 1, "de deep-dive kreeg geen claims mee"


def test_no_deep_dive_for_a_domain_whose_pull_failed(tmp_path):
    """Een mislukte pull levert een data-health-trigger op, die escaleert.
    Zonder deze regel betaalt het systeem een LLM-call om over nul claims te
    schrijven -- en stempelt het de dag daarna af als 'deep-dive gedaan'."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    calls = []

    spec = AgentSpec("stil", _failing_agent("stil").monitor, _fake_deep_dive(calls))
    run_daily(conn, agents=[spec], now=now, client=object(), notifier=lambda n: None)

    assert calls == []


def test_deep_dive_error_does_not_overwrite_the_monitoring_error(tmp_path):
    """Gemeten bug: de deep-dive-fout overschreef `error`, waardoor de
    nachtelijke melding 'de datapull mislukte: LLM down' rapporteerde -- de
    verkeerde diagnose, precies als er niemand is om 'm te corrigeren."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)

    def broken_deep_dive(conn_, client, claims, trigger_events, now=None, event_id=None):
        raise RuntimeError("LLM ook stuk")

    trigger = TriggerEvent(domain="d", triggered_at=now, reason="echte oorzaak", severity="high")
    spec = AgentSpec("d", _ok_agent("d", [trigger]).monitor, broken_deep_dive)

    result = run_daily(conn, agents=[spec], now=now, client=object(), notifier=lambda n: None)

    assert result.outcomes[0].deep_dive_error is not None
    assert "LLM ook stuk" in result.outcomes[0].deep_dive_error
    assert result.outcomes[0].error is None  # het monitoring-veld blijft onaangeroerd


def test_failed_deep_dive_counts_as_a_problem_and_is_notified(tmp_path):
    """Gemeten bug: een deep-dive kon elke dag falen terwijl
    `has_problems` False bleef, cron exit 0 gaf en er geen melding uitging."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)

    def broken_deep_dive(conn_, client, claims, trigger_events, now=None, event_id=None):
        raise RuntimeError("LLM down")

    trigger = TriggerEvent(domain="d", triggered_at=now, reason="iets", severity="high")
    spec = AgentSpec("d", _ok_agent("d", [trigger]).monitor, broken_deep_dive)

    result = run_daily(conn, agents=[spec], now=now, client=object(), notifier=lambda n: None)

    assert result.has_problems
    assert result.notification is not None
    assert "LLM down" in result.notification.body


def test_a_missing_day_is_detected_and_reported(tmp_path):
    """Het faalscenario dat alle andere meldingen missen: een run die nooit
    gebeurde. Cron uit, venv stuk, VPS uit -- geen run, geen melding, en
    stilte ziet eruit als een gezonde dag."""
    conn = _db(tmp_path)
    monitor = _real_monitor("d")
    agents = [AgentSpec("d", monitor)]

    # Dag 1 draait, dag 2 en 3 worden overgeslagen, dag 4 draait weer.
    run_daily(conn, agents=agents, now=datetime(2026, 11, 10, tzinfo=timezone.utc), notifier=lambda n: None)
    result = run_daily(conn, agents=agents, now=datetime(2026, 11, 13, tzinfo=timezone.utc), notifier=lambda n: None)

    assert "2026-11-11" in result.missed_days
    assert "2026-11-12" in result.missed_days
    assert result.has_problems
    assert result.notification.severity == "critical"


def test_first_ever_run_does_not_report_the_whole_week_as_missed(tmp_path):
    """Regressiegeval bij de test hierboven: op dag 1 is de hele
    terugblikperiode leeg, en dat is een nieuw systeem, geen storing."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)

    result = run_daily(conn, agents=[AgentSpec("d", _real_monitor("d"))], now=now, notifier=lambda n: None)

    assert result.missed_days == []
    assert not result.has_problems


def test_concurrent_run_is_skipped_not_crashed(tmp_path):
    """Twee overlappende cron-runs komen allebei langs de applicatieve
    idempotency-check voordat een van beide zijn agent_run wegschrijft; de
    tweede loopt dan tegen de unique index aan. Dat is de database die doet
    waarvoor hij er is -- geen bug, dus geen kritieke melding om 3 uur 's
    nachts."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)

    def monitor(conn_, now=None, event_id=None):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: agent_runs.event_id")

    result = run_daily(conn, agents=[AgentSpec("d", monitor)], now=now, notifier=lambda n: None)

    assert result.outcomes[0].status == "skipped"
    assert not result.has_problems
    assert result.notification is None


def test_second_run_does_not_refetch_the_source(tmp_path):
    """Scherpere versie van de idempotency-test: telt de FETCH, niet de
    wrapper-aanroep. Dat is waar `AlreadyProcessedError` vóór de fetch voor
    bedoeld is -- geen dubbele netwerkcall en geen dubbele kosten."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    fetches = []

    def monitor(conn_, now=None, event_id=None):
        def fetch():
            fetches.append(1)
            return {"m": {"value": 1.0, "date": "2026-11-09"}}

        return run_monitoring(
            conn_, "d", "S", fetch, {"m": MetricSpec(label="M", tolerance=0.5)},
            timedelta(days=2), now=now, event_id=event_id,
        )

    agents = [AgentSpec("d", monitor)]
    run_daily(conn, agents=agents, now=now, notifier=lambda n: None)
    run_daily(conn, agents=agents, now=now, notifier=lambda n: None)

    assert len(fetches) == 1


def test_orchestration_failure_does_not_kill_the_run(tmp_path, monkeypatch):
    """De data is op dit punt al gecommit. Een randgeval in de
    health/notificatie-fase mag een geslaagde dag niet als stacktrace laten
    eindigen -- op een onbeheerde machine is dat niet te onderscheiden van
    'er is niets gebeurd'."""
    conn = _db(tmp_path)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)

    import runtime.daily as daily_mod

    def boom(*a, **kw):
        raise RuntimeError("health kapot")

    monkeypatch.setattr(daily_mod, "system_health", boom)

    result = run_daily(conn, agents=[AgentSpec("d", _real_monitor("d"))], now=now, notifier=lambda n: None)

    assert result.outcomes[0].status == "ok"
    assert result.health is None
