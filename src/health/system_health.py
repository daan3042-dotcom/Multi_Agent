"""
system_health.py
Roadmap 1.7, deel 1: "System health per component" -- ÉÉN centrale
functie die de actuele status per component teruggeeft (source,
ingestion, database, trigger, agent, LLM). Bouwt uitsluitend op wat al
bestaat, zoals gevraagd: health.data_health (per-bron staleness/
onbereikbaarheid, al A.3) en storage.schema's agent_runs (roadmap 1.2,
al gebouwd als expliciete voorbereiding op precies deze stap). Geen
nieuw, ongerelateerd statusmodel -- alles hergebruikt HealthStatus
(OK/STALE/UNREACHABLE/UNKNOWN).

Wat elk component concreet betekent (er bestaat geen apart bijgehouden
faalstatus per component -- dit leidt af uit wat er al gelogd wordt):
- source:<naam>    -- ongewijzigd health.data_health.check_source().
- database         -- lichte connectiviteitscheck (nieuw, minimaal: een
                       `SELECT 1`), er was nog geen signaal hiervoor.
- ingestion:<domain> -- status van de LAATSTE monitoring-agent_run: is de
                       data-pull + claims-opslag zelf gelukt (los van of
                       de onderliggende bron OOK gezond is -- dat is
                       source:<naam>; ingestion kan falen op een eigen
                       bug/parse-fout terwijl de bron prima bereikbaar is).
- agent:<domain>   -- OVERALL status van de agent: worst-of ingestion EN
                       de laatste deep-dive-run -- een agent die prima
                       pollt maar wiens deep-dive stuk is, is als geheel
                       niet gezond.
- trigger          -- GEEN eigen faalstatus: trigger-evaluatie
                       (evaluate_deltas/detect_revision/evaluate_data_
                       health) draait inline, ongevangen, binnen
                       run_monitoring() -- een falende trigger-laag ZOU
                       de monitoring-run zelf laten crashen (geen
                       agent_run-rij, geen claims). "trigger" is daarom
                       de worst-of van alle ingestion-statussen: het is
                       het beste indirecte signaal dat er is, geen gok.
- llm              -- worst-of de laatste deep-dive-agent_run per domein.
                       GEEN live ping naar Anthropic: dat zou geld kosten
                       en niet deterministisch testbaar zijn (zie
                       CLAUDE.md/sessieafspraken over live-calls in de
                       sandbox) -- leunt op de al-bestaande historie van
                       ECHTE deep-dive-cycli.

Dit levert alleen de backend-functie. De Dashboard-laag die dit later
toont (systeemoverzicht sectie 5.2) is aparte, latere scope -- hier
alleen de functie die daar straks de bron voor is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from health.data_health import HealthStatus, check_source
from storage.schema import list_agent_runs, list_sources

# Ernst-volgorde voor de ROLLUP (overall_status). Bewust anders dan
# triggers.trigger_engine.evaluate_data_health, waar OK en UNKNOWN gelijk
# (onschuldig) behandeld worden voor de vraag "moet dit escaleren naar een
# deep-dive". Hier, voor een statusoverzicht, is "nog nooit gezien" wel de
# moeite waard om apart te laten opvallen t.o.v. een bevestigd gezonde
# component -- vandaar een eigen plek in de volgorde i.p.v. gelijk aan OK.
_SEVERITY_ORDER = {
    HealthStatus.OK: 0,
    HealthStatus.UNKNOWN: 1,
    HealthStatus.STALE: 2,
    HealthStatus.UNREACHABLE: 3,
}


@dataclass(frozen=True)
class ComponentHealth:
    component: str
    status: HealthStatus
    detail: str | None = None


@dataclass
class SystemHealthReport:
    generated_at: datetime
    components: list[ComponentHealth] = field(default_factory=list)

    def status_for(self, component: str) -> HealthStatus | None:
        for c in self.components:
            if c.component == component:
                return c.status
        return None

    @property
    def overall_status(self) -> HealthStatus:
        """Worst-of over alle componenten. Een lege lijst geeft UNKNOWN
        terug, niet OK -- er is dan niets gecontroleerd, en dat als "alles
        gezond" presenteren zou een valse geruststelling zijn."""
        if not self.components:
            return HealthStatus.UNKNOWN
        return max((c.status for c in self.components), key=lambda s: _SEVERITY_ORDER[s])


def _database_status(conn) -> ComponentHealth:
    try:
        conn.execute("SELECT 1")
        return ComponentHealth(component="database", status=HealthStatus.OK)
    except Exception as e:
        return ComponentHealth(component="database", status=HealthStatus.UNREACHABLE, detail=str(e))


def _latest_run_status(conn, domain: str, mode: str) -> tuple[HealthStatus, str | None]:
    runs = list_agent_runs(conn, domain, mode=mode, limit=1)
    if not runs:
        return HealthStatus.UNKNOWN, None
    latest = runs[0]
    if latest["success"]:
        return HealthStatus.OK, None
    return HealthStatus.UNREACHABLE, latest["error"]


def _worst(pairs: list[tuple[HealthStatus, str | None]]) -> tuple[HealthStatus, str | None]:
    return max(pairs, key=lambda sd: _SEVERITY_ORDER[sd[0]])


def sources_from_registry(conn) -> dict[str, timedelta]:
    """Roadmap 1.4: leest alle geregistreerde bronnen (storage.schema.
    list_sources) uit en zet ze om naar de vorm die system_health()'s
    `sources`-parameter verwacht (source_key -> max_age). Sluit de cirkel
    uit de aanleiding voor 1.4: een aanroeper hoeft de sources-dict niet
    langer met de hand samen te stellen -- elke agent die zichzelf via
    storage.schema.register_source() declareert, verschijnt hier
    automatisch."""
    return {s.source_key: s.max_age for s in list_sources(conn)}


def system_health(
    conn,
    sources: dict[str, timedelta],
    domains: list[str],
    now: datetime | None = None,
) -> SystemHealthReport:
    """Roadmap 1.7: de ene centrale query/functie voor de actuele status
    per component. `sources` en `domains` worden door de aanroeper
    meegegeven (geen auto-discovery, geen hardcoded lijst hier) -- een
    echt centraal register per databron is de Source Registry (1.4),
    expliciet latere scope; deze functie blijft er bewust los van en
    neemt de topologie als parameter aan, zelfde dependency-injection-
    gedachte als qc.default_llm_review()'s client-parameter.

    LET OP, bestaande beperking (niet nieuw, hier alleen zichtbaar
    geworden): data_health.check_source() is per BRONNAAM, niet per
    domein. Twee agents die dezelfde bronnaam delen (bijv.
    monetary_policy_agent en financial_agent delen beide "FRED", met
    verschillende MAX_AGE) schrijven naar dezelfde data_health-rij -- de
    aanroeper moet zelf één max_age per bronnaam kiezen (bijv. de
    strengste). Oplossen hoort bij de Source Registry (1.4), niet hier."""
    now = now or datetime.now(timezone.utc)
    components: list[ComponentHealth] = [_database_status(conn)]

    for source, max_age in sources.items():
        health = check_source(conn, source, max_age=max_age, now=now)
        components.append(ComponentHealth(component=f"source:{source}", status=health.status, detail=health.detail))

    ingestion_results: list[tuple[HealthStatus, str | None]] = []
    deep_dive_results: list[tuple[HealthStatus, str | None]] = []
    for domain in domains:
        ingestion = _latest_run_status(conn, domain, "monitoring")
        deep_dive = _latest_run_status(conn, domain, "deep_dive")
        ingestion_results.append(ingestion)
        deep_dive_results.append(deep_dive)

        components.append(ComponentHealth(component=f"ingestion:{domain}", status=ingestion[0], detail=ingestion[1]))

        agent_status, agent_detail = _worst([ingestion, deep_dive])
        components.append(ComponentHealth(component=f"agent:{domain}", status=agent_status, detail=agent_detail))

    trigger_status, trigger_detail = _worst(ingestion_results) if ingestion_results else (HealthStatus.UNKNOWN, None)
    components.append(ComponentHealth(component="trigger", status=trigger_status, detail=trigger_detail))

    llm_status, llm_detail = _worst(deep_dive_results) if deep_dive_results else (HealthStatus.UNKNOWN, None)
    components.append(ComponentHealth(component="llm", status=llm_status, detail=llm_detail))

    return SystemHealthReport(generated_at=now, components=components)
