"""
evaluation_report.py
Het kalibratie- en effectieve-n-rapport per agent (roadmap 4.5), gebouwd op
`diagnostics.py`. ALLEEN LEZEN: er wordt niets in de database geschreven, en
de evaluations-tabel krijgt geen nieuwe kolommen (de scores van een
afgewikkelde voorspelling staan vast; dit zijn afgeleiden die op elk moment
opnieuw te berekenen zijn).

COHORTEN WORDEN NOOIT GEMENGD. De sleutel is (cohort, agent, soort): `dry_run`,
`pseudo_oos` en `cohort_0` staan in aparte regels. Een gemiddelde over twee
cohorten zou precies de vervuiling zijn waar `MI_COHORT` voor bestaat.

KWANTIEL EN BINAIR APART. CRPS (kwantiel) en Brier (binair) liggen op andere
schalen en zijn niet te middelen. Per soort één hoofdscore: CRPS resp. Brier.

HORIZON VOOR DE EFFECTIEVE N: de mediaan van `resolves_at - created_at` van de
voorspellingen in de groep, in kalenderdagen. Een groep met verschillende
horizonnen (5, 21 en 63 handelsdagen) krijgt dus één blokgrootte; dat is
bewust eenvoudig en conservatief genoeg voor een eerste schatting, en de
uitsplitsing per horizon (roadmap: "per domein, per horizon, per model_id")
is een volgende stap.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime

from scoring.diagnostics import (
    EffectiveN,
    QuantileCoverage,
    ReliabilityBin,
    auc,
    effective_n,
    quantile_coverage,
    reliability_bins,
)

_QUERY = """
SELECT p.cohort, p.agent, p.kind, p.model_id, p.created_at, p.resolves_at,
       p.q10, p.q25, p.q50, p.q75, p.q90, p.probability,
       e.realised_value, e.crps, e.brier, e.pinball_mean
FROM evaluations e JOIN predictions p ON p.id = e.prediction_id
WHERE e.status = 'resolved'
ORDER BY p.created_at
"""


# Kolomposities in _QUERY. De vijf kwantielen staan aaneen (q10..q90), in de volgorde van
# contract.prediction.QUANTILE_FIELDS.
_Q10, _Q90, _PROBABILITY, _REALISED, _CRPS, _BRIER = 6, 10, 11, 12, 13, 14


@dataclass
class GroupReport:
    cohort: str
    agent: str
    kind: str  # 'quantile' | 'binary'
    n: int
    model_ids: list[str]
    primary_score_name: str  # 'crps' | 'brier'
    primary_score_mean: float
    effective: EffectiveN
    coverage: QuantileCoverage | None = None
    reliability: list[ReliabilityBin] = field(default_factory=list)
    auc: float | None = None
    n_positive: int | None = None


def _dt(tekst: str) -> datetime:
    return datetime.fromisoformat(tekst)


def build_report(conn, cohort: str | None = None) -> list[GroupReport]:
    rijen = conn.execute(_QUERY).fetchall()
    groepen: dict[tuple, list] = {}
    for r in rijen:
        if cohort is not None and r[0] != cohort:
            continue
        groepen.setdefault((r[0], r[1], r[2]), []).append(r)

    rapport = []
    for (coh, agent, soort), leden in sorted(groepen.items()):
        naam = "crps" if soort == "quantile" else "brier"
        idx = _CRPS if soort == "quantile" else _BRIER
        scores = [(_dt(r[4]), r[idx]) for r in leden if r[idx] is not None]
        horizon = statistics.median((_dt(r[5]) - _dt(r[4])).total_seconds() / 86400 for r in leden)
        groep = GroupReport(
            cohort=coh, agent=agent, kind=soort, n=len(leden),
            model_ids=sorted({r[3] for r in leden}),
            primary_score_name=naam,
            primary_score_mean=(sum(s for _, s in scores) / len(scores)) if scores else float("nan"),
            effective=effective_n(scores, max(horizon, 1.0)),
        )
        if soort == "quantile":
            groep.coverage = quantile_coverage([(*r[_Q10:_Q90 + 1], r[_REALISED]) for r in leden])
        else:
            kansen = [r[_PROBABILITY] for r in leden]
            uitkomsten = [r[_REALISED] >= 0.5 for r in leden]
            groep.reliability = reliability_bins(kansen, uitkomsten)
            groep.auc = auc(kansen, uitkomsten)
            groep.n_positive = sum(uitkomsten)
        rapport.append(groep)
    return rapport


def _pct(x: float | None) -> str:
    return "  -  " if x is None else f"{100 * x:4.0f}%"


def format_report(groepen: list[GroupReport]) -> str:
    if not groepen:
        return (
            "Nog geen afgewikkelde voorspellingen: er valt niets te rapporteren.\n"
            "(Dat is verwacht zolang de eerste horizon niet verstreken is.)"
        )
    uit = [
        "KALIBRATIE EN EFFECTIEVE N PER AGENT (alleen lezen; cohorten staan apart)",
        "Lagere score is beter. n = afgewikkelde voorspellingen; n_eff = onafhankelijke waarnemingen (schatting).",
        "",
    ]
    for g in groepen:
        e = g.effective
        neff = "n.v.t. (te weinig rondes)" if e.n_effective is None else f"{e.n_effective:.1f}"
        band = "" if e.ci_low is None else f"  band 90%: {e.ci_low:.3f} .. {e.ci_high:.3f}"
        uit.append(f"[{g.cohort}] {g.agent} ({'kwantiel' if g.kind == 'quantile' else 'binair'}) model={','.join(g.model_ids)}")
        uit.append(f"  n={g.n}  n_eff={neff}  {g.primary_score_name}={g.primary_score_mean:.3f}{band}")
        uit.append(f"  {e.note}" + ("" if e.reliable else "  -> NIET BETROUWBAAR: geen conclusies trekken"))
        if g.coverage is not None:
            c = g.coverage
            namen = ("onder q10", "q10-q25", "q25-q50", "q50-q75", "q75-q90", "boven q90")
            verwacht = QuantileCoverage.expected()
            uit.append(
                "  uitkomst valt: " + " | ".join(
                    f"{naam} {_pct(deel)} ({100 * v:.0f}%)" for naam, deel, v in zip(namen, c.shares, verwacht)
                )
            )
            uit.append(
                f"  binnen q25-q75: {_pct(c.central_share())} (verwacht 50%)  |  "
                f"binnen q10-q90: {_pct(c.within_80())} (verwacht 80%)"
            )
        else:
            a = "niet te meten (maar één soort uitkomst)" if g.auc is None else f"{g.auc:.2f}"
            uit.append(f"  AUC={a}  (gebeurd: {g.n_positive} van {g.n})")
            for b in g.reliability:
                if b.n:
                    uit.append(
                        f"  kans {b.low:.1f}-{b.high:.1f}: n={b.n:<3} voorspeld {100 * b.mean_forecast:3.0f}%  "
                        f"gebeurd {100 * b.observed_frequency:3.0f}%"
                    )
        uit.append("")
    return "\n".join(uit).rstrip() + "\n"
