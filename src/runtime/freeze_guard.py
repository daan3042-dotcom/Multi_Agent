"""
runtime/freeze_guard.py
De vingerafdrukken voor de freeze (CLAUDE.md, checkpoint 5): van de DOELENLIJST en van de EVIDENCE-SHEET. Zie
`contract/freeze_versions.py` voor waarom. Alleen lezen en rekenen: dit bevriest niets en raakt de database niet aan.

DE EVIDENCE-VINGERAFDRUK is de tekst die `build_evidence_sheet` produceert voor een vaste, gesimuleerde
database. Die dekt wat de agent ECHT te zien krijgt (opmaak, afronding, welke regels, welke vensters), in plaats van
de broncode te hashen (dan zou een opmerking of een naamsverandering de afdruk veranderen). De fixture bevat bewust
elk soort regel: een gewone reeks met spreiding, een relatief rendement, een FOMC-stapreeks, een verouderde reeks en
een reeks zonder historie. Alles is rekenkundig (geen toeval, geen klok), dus identiek op elke machine.

DE DOELENVINGERAFDRUK is de lijst van alle voorspeldoelen van de agents met alles wat bepaalt WAT er gemeten wordt
en HOE het later wordt afgewikkeld. De prompt-versie zit er niet in (die heeft zijn eigen bewaking).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from agents.base import FORECAST_SYSTEM_RULES, ForecastTarget
from contract.output_contract import Claim, Confidence, DomainOutput, Mode
from contract.prediction import HorizonKind, PredictionKind
from contract.resolution import ResolutionMethod
from scoring.evidence_sheet import build_evidence_sheet
from storage.schema import init_db, load_monitoring_claims, save_domain_output

_AS_OF = datetime(2026, 10, 13, 7, 15, tzinfo=timezone.utc)


def _hash(tekst: str) -> str:
    return hashlib.sha256(tekst.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# De doelenlijst
# --------------------------------------------------------------------------


def doelen_beschrijving() -> list[dict]:
    """Elk voorspeldoel van elke agent, met alles wat meetbaar of afwikkelbaar bepaalt. Gesorteerd, dus
    onafhankelijk van de volgorde waarin agents zijn geregistreerd."""
    from runtime.daily import default_agents

    uit = []
    for spec in default_agents():
        for t in spec.forecast_targets:
            uit.append({
                "domein": spec.domain,
                "metric_key": t.metric_key,
                "soort": t.kind.value,
                "horizon_soort": t.horizon_kind.value,
                "horizonnen": list(t.horizons),
                "cadans": t.cadence.value if t.cadence is not None else None,
                "graafknoop": t.graph_node.value if t.graph_node is not None else None,
                "resolutiemethode": t.resolution_method.value,
                "resolutieregel": t.resolution_rule,
                "gebeurtenis": t.event_rule,
                "benchmark": t.benchmark_metric_key,
            })
    return sorted(uit, key=lambda d: (d["domein"], d["metric_key"]))


def doelen_fingerprint() -> str:
    return _hash(json.dumps(doelen_beschrijving(), sort_keys=True, ensure_ascii=True))


def aantal_kwantielreeksen_voor_ridge() -> int:
    """Het aantal (agent, doel, horizon)-combinaties met een kwantielvoorspelling: de plekken waar een ridge
    gefit en bevroren zou kunnen worden. De FOMC-doelen (binair) tellen niet mee."""
    return sum(
        len(d["horizonnen"]) for d in doelen_beschrijving() if d["soort"] == PredictionKind.QUANTILE.value
    )


# --------------------------------------------------------------------------
# De evidence-sheet
# --------------------------------------------------------------------------


def _werkdagen(aantal: int, einde: datetime) -> list[datetime]:
    d, uit = einde, []
    while len(uit) < aantal:
        if d.weekday() < 5:
            uit.append(d)
        d -= timedelta(days=1)
    return list(reversed(uit))


def _opslaan(conn, key: str, waarden: list[float], dagen: list[datetime], label: str) -> None:
    claims = [
        Claim(domain="fixture", claim=label, value=w, source="fixture", confidence=Confidence.HIGH,
              analysis_time=d, source_time=d, metric_key=key)
        for w, d in zip(waarden, dagen)
    ]
    save_domain_output(conn, DomainOutput(domain="fixture", mode=Mode.MONITORING, generated_at=dagen[0], claims=claims))


def evidence_fixture_tekst() -> str:
    """De sheet voor de vaste fixture. Deterministisch: alleen rekenkunde op indexen."""
    conn = init_db(":memory:")
    try:
        dagen = _werkdagen(1500, _AS_OF - timedelta(days=1))
        niveau = [100 + 0.01 * i + ((i * 7) % 13) * 0.1 for i in range(1500)]
        benchmark = [400 + 0.02 * i + ((i * 5) % 11) * 0.2 for i in range(1500)]
        etf = [50 + 0.015 * i + ((i * 3) % 17) * 0.15 for i in range(1500)]
        fomc = [4.5 if i < 900 else (4.25 if i < 1300 else 4.0) for i in range(1500)]
        _opslaan(conn, "fx_niveau", niveau, dagen, "Niveaureeks")
        _opslaan(conn, "fx_bench", benchmark, dagen, "Benchmark")
        _opslaan(conn, "fx_etf", etf, dagen, "Relatieve reeks")
        _opslaan(conn, "fx_fomc", fomc, dagen, "Doelrange")
        oud = _werkdagen(400, _AS_OF - timedelta(days=80))
        _opslaan(conn, "fx_oud", [10 + 0.05 * i for i in range(400)], oud, "Verouderde reeks")

        laatste = []
        for key, label, waarden, ref in (
            ("fx_niveau", "Niveaureeks", niveau, dagen), ("fx_bench", "Benchmark", benchmark, dagen),
            ("fx_etf", "Relatieve reeks", etf, dagen), ("fx_fomc", "Doelrange", fomc, dagen),
            ("fx_oud", "Verouderde reeks", [10 + 0.05 * i for i in range(400)], oud),
        ):
            laatste.append(Claim(domain="fixture", claim=label, value=waarden[-1], source="fixture",
                                 confidence=Confidence.HIGH, analysis_time=_AS_OF, source_time=ref[-1], metric_key=key))
        laatste.append(Claim(domain="fixture", claim="Zonder historie", value=1.0, source="fixture",
                             confidence=Confidence.HIGH, analysis_time=_AS_OF, metric_key="fx_geen"))
        save_domain_output(conn, DomainOutput(domain="fixture", mode=Mode.MONITORING, generated_at=_AS_OF, claims=laatste))
        claims = load_monitoring_claims(conn, "fixture")

        def kw(key, horizons, **extra):
            basis = dict(
                metric_key=key, kind=PredictionKind.QUANTILE, horizon_kind=HorizonKind.TRADING_DAYS, horizons=horizons,
                resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER, resolution_rule="fixture",
            )
            basis.update(extra)
            return ForecastTarget(**basis)

        doelen = [
            kw("fx_niveau", (5, 21, 63)),
            kw("fx_etf", (21,), resolution_method=ResolutionMethod.RELATIVE_RETURN, benchmark_metric_key="fx_bench"),
            kw("fx_oud", (5,)),
            kw("fx_geen", (5,)),
            ForecastTarget(
                metric_key="fx_fomc", kind=PredictionKind.BINARY, horizon_kind=HorizonKind.RELEASES, horizons=(1, 2),
                resolution_method=ResolutionMethod.DIRECTION_AFTER_FOMC, resolution_rule="fixture", event_rule="hoger",
                cadence=__import__("contract.horizons", fromlist=["ReleaseCadence"]).ReleaseCadence.FOMC,
            ),
        ]
        return build_evidence_sheet(conn, doelen, claims, _AS_OF)
    finally:
        conn.close()


def evidence_fingerprint() -> str:
    return _hash(evidence_fixture_tekst())


# --------------------------------------------------------------------------
# De prompt-hash (systeemprompt + evidence-sheet)
# --------------------------------------------------------------------------


def forecast_prompt_hash(module, evidence_fp: str | None = None) -> str:
    """Wat er bij een agent bepaalt WAT het model te zien krijgt: de regels, zijn vakparagraaf en de
    evidence-sheet. De enige definitie; `tests/test_forecast_prompt_version.py` gebruikt hem ook."""
    fp = evidence_fp if evidence_fp is not None else evidence_fingerprint()
    return _hash(f"{FORECAST_SYSTEM_RULES}\n\n{module.DEEP_DIVE_SYSTEM_PROMPT}\n\nEVIDENCE:{fp}")
