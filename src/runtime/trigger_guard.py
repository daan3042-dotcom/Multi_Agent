"""
trigger_guard.py
Roadmap 1.5 (Trigger-versioning). De vingerafdruk van "alles wat bepaalt of
er een trigger vuurt", en de pin die voorkomt dat het echte cohort met een
andere regelset draait dan bij de freeze is bevestigd.

BEWUST BUITEN `src/triggers/`. Checkpoint 2 verbiedt het verzwakken of
omzeilen van de trigger-engine; dit bestand leest hem alleen. De vingerafdruk
bestaat uit twee delen:

1. DE CONFIGURATIE: per agent de ouderdomsgrens (MAX_AGE) en per reeks
   tolerance + severity. Labels en redenteksten staan er niet in.
2. HET GEDRAG: vaste invoer door de echte trigger-functies, met de uitkomst
   erin. Dat vangt wat in de code zelf zit -- "strikt groter dan", de
   verhouding waarbij een onvolledige pull `high` wordt, de grens waarop een
   bron `stale` heet, de vergelijking met de LAATSTE claim -- zonder dat
   `trigger_engine.py` er iets voor hoeft te exporteren. Wordt daar een
   grens verlegd, dan verandert een probe-uitkomst en dus de vingerafdruk.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from contract.output_contract import Claim, Confidence
from contract.trigger_version import (
    FROZEN_TRIGGER_VERSION,
    TRIGGER_FINGERPRINTS,
    TRIGGER_VERSION,
)
from health.data_health import (
    HealthCheckResult,
    HealthStatus,
    detect_revision,
    evaluate_completeness,
    evaluate_staleness,
)
from manager.manager import dispatch
from triggers.trigger_engine import (
    evaluate_completeness_result,
    evaluate_data_health,
    evaluate_surprise,
)

_NU = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _agent_modules():
    """Alle agents die in de dagelijkse cyclus triggers geven. Zelfde lijst
    als `calibration.trigger_calibration.metric_registry()`."""
    from agents import (
        commodity_agent, currency_agent, economic_agent, financial_agent,
        monetary_policy_agent, sector_agent,
    )

    return (
        monetary_policy_agent, currency_agent, financial_agent,
        sector_agent, commodity_agent, economic_agent,
    )


def configuratie() -> dict:
    """De drempels en ouderdomsgrenzen zoals de code ze nu heeft."""
    return {
        m.DOMAIN: {
            "max_age_seconden": int(m.MAX_AGE.total_seconds()),
            "reeksen": {
                key: [float(spec.tolerance), spec.severity]
                for key, spec in sorted(m.METRIC_SPECS.items())
            },
        }
        for m in sorted(_agent_modules(), key=lambda m: m.DOMAIN)
    }


def _claim(waarde: float, metric_key: str = "m", bron_tijd=None) -> Claim:
    return Claim(
        domain="d", claim="c", value=waarde, source="s", confidence=Confidence.HIGH,
        analysis_time=_NU, source_time=bron_tijd, metric_key=metric_key,
    )


def gedragsprobes() -> dict:
    """Vaste invoer door de echte trigger-functies. Elke uitkomst is een
    kleine waarde (severity, True/False) zodat een verandering in een grens
    direct zichtbaar is."""
    from agents.base import MetricSpec, evaluate_deltas

    probes: dict[str, object] = {}

    # Afwijking: strikt groter dan de tolerantie, in beide richtingen.
    for waargenomen in (8.9, 9.0, 10.0, 11.0, 11.0001):
        t = evaluate_surprise("d", "m", waargenomen, 10.0, 1.0, "r", severity="medium", now=_NU)
        probes[f"afwijking:{waargenomen}"] = None if t is None else t.severity

    # Vergelijking met de LAATSTE claim (previous[0]), niet met een oudere,
    # en geen trigger bij een eerste observatie of een reeks zonder spec.
    specs = {"m": MetricSpec(label="x", tolerance=1.0, severity="medium")}
    for naam, vorige in (
        ("laatste_claim", [_claim(10.0), _claim(0.0)]),
        ("eerste_observatie", []),
    ):
        uit = evaluate_deltas("d", [_claim(10.5)], specs, {"m": vorige}, now=_NU)
        probes[f"delta:{naam}"] = len(uit)
    uit = evaluate_deltas("d", [_claim(50.0, "zonder_spec")], specs, {"zonder_spec": [_claim(0.0, "zonder_spec")]}, now=_NU)
    probes["delta:zonder_spec"] = len(uit)

    # Onvolledige pull: geen trigger, medium, of high, naar verhouding.
    verwacht = [f"k{i}" for i in range(10)]
    for ontbrekend in (0, 1, 4, 5, 9, 10):
        resultaat = evaluate_completeness("s", verwacht, verwacht[ontbrekend:], now=_NU)
        t = evaluate_completeness_result("d", resultaat, now=_NU)
        probes[f"completeness:{ontbrekend}/10"] = None if t is None else t.severity

    # Data-health per status, en de grens waarop een bron 'stale' heet.
    for status in HealthStatus:
        gezondheid = HealthCheckResult(
            source="s", status=status, last_success_at=None, checked_at=_NU, detail="x",
        )
        t = evaluate_data_health("d", gezondheid, now=_NU)
        probes[f"health:{status.value}"] = None if t is None else t.severity
    max_leeftijd = timedelta(days=5)
    for seconden in (-1, 0, 1):
        laatste = _NU - max_leeftijd - timedelta(seconds=seconden)
        probes[f"staleness:{seconden:+d}s"] = evaluate_staleness("s", laatste, max_leeftijd, now=_NU).status.value

    # Revisie: een gewijzigde waarde voor een al gerapporteerde periode.
    periode = datetime(2025, 12, 1, tzinfo=timezone.utc)
    vorige = [_claim(4.0, bron_tijd=periode)]
    probes["revisie:gelijk"] = detect_revision(vorige, periode, 4.0) is not None
    probes["revisie:anders"] = detect_revision(vorige, periode, 4.1) is not None
    probes["revisie:zonder_periode"] = detect_revision(vorige, None, 9.9) is not None

    # De manager laat elke trigger doorgaan naar een deep-dive.
    from triggers.trigger_engine import TriggerEvent

    events = [
        TriggerEvent(domain="a", triggered_at=_NU, reason="r", severity=sev)
        for sev in ("low", "medium", "high")
    ]
    plan = dispatch(events, now=_NU)
    probes["dispatch:domeinen"] = plan.domains
    probes["dispatch:aantal"] = sum(len(v) for v in plan.escalations.values())

    return probes


def trigger_fingerprint() -> str:
    """16 hex-tekens over configuratie + gedrag. Stabiel tussen runs en
    machines: alleen getallen, severities en vaste probe-uitkomsten."""
    inhoud = json.dumps(
        {"configuratie": configuratie(), "gedrag": gedragsprobes()},
        sort_keys=True, ensure_ascii=True,
    )
    return hashlib.sha256(inhoud.encode()).hexdigest()[:16]


class TriggerPinError(RuntimeError):
    """De regelset klopt niet met wat bij de freeze is bevestigd."""


def check_trigger_pin(cohort: str, cohort_0: str = "cohort_0") -> None:
    """Weigert het echte cohort met een regelset die niet bevestigd is.

    Alleen voor `cohort_0`: dry-run en pseudo-OOS mogen met elke set draaien,
    want daar is verschuiven van drempels precies wat je wilt testen. Drie
    dingen moeten kloppen, en elk geeft een eigen melding:

    1. de freeze is vastgelegd (FROZEN_TRIGGER_VERSION is gezet);
    2. die versie is de versie waarmee de code nu draait;
    3. de vingerafdruk van de code past bij die versie -- ook op de VPS, waar
       niemand pytest draait op het moment dat iemand een bestand aanpast.
    """
    if cohort != cohort_0:
        return
    if FROZEN_TRIGGER_VERSION is None:
        raise TriggerPinError(
            "MI_COHORT=cohort_0 maar er is nog geen freeze vastgelegd: "
            "FROZEN_TRIGGER_VERSION in src/contract/trigger_version.py is niet gezet. "
            "Bevestig de freeze (checkpoint 5) voordat de klok gaat lopen."
        )
    if FROZEN_TRIGGER_VERSION != TRIGGER_VERSION:
        raise TriggerPinError(
            f"MI_COHORT=cohort_0 met trigger-versie {TRIGGER_VERSION}, maar de freeze is "
            f"{FROZEN_TRIGGER_VERSION}. Een andere regelset start een nieuw cohort."
        )
    verwacht = TRIGGER_FINGERPRINTS.get(TRIGGER_VERSION)
    werkelijk = trigger_fingerprint()
    if verwacht != werkelijk:
        raise TriggerPinError(
            f"De trigger-regels wijken af van versie {TRIGGER_VERSION} "
            f"(vingerafdruk {werkelijk}, bevroren {verwacht}). "
            "Iemand heeft een drempel of trigger-gedrag aangepast zonder nieuwe versie."
        )
