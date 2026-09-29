"""
baseline_round.py
De wekelijkse baseline-ronde (roadmap 4.6): alle drie de baselines voor de
doelen van één agent, in één transactie.

Los van `baselines.py` en `ridge.py` omdat de ronde beide nodig heeft en
`ridge.py` op zijn beurt de bouwstenen uit `baselines.py` gebruikt -- één
module die alles importeert voorkomt een circulaire import.
"""

from __future__ import annotations

from datetime import datetime

from agents.base import AlreadyProcessedError, ForecastTarget
from scoring.baselines import BaselineRoundResult, baseline_predictions
from scoring.ridge import ridge_predictions
from storage.schema import has_successful_run, save_predictions_with_run


def baseline_run_domain(domain: str) -> str:
    """De sleutel waaronder de baseline-ronde van dit domein in `agent_runs`
    staat. Los van het domein zelf, anders botst hij met de run-regel van de
    LLM-forecast-ronde (zelfde domein, zelfde modus, zelfde week)."""
    return f"baseline:{domain}"


def all_baseline_predictions(
    conn, domain: str, targets: list[ForecastTarget] | tuple[ForecastTarget, ...],
    now: datetime, ridge: bool = True,
) -> BaselineRoundResult:
    """Persistence, climatology en (tenzij `ridge=False`) ridge. Schrijft
    niets weg."""
    eenvoudig = baseline_predictions(conn, domain, targets, now)
    if not ridge:
        return eenvoudig
    model = ridge_predictions(conn, domain, targets, now)
    return BaselineRoundResult(
        domain,
        eenvoudig.predictions + model.predictions,
        eenvoudig.skipped + model.skipped,
        eenvoudig.issues + model.issues,
    )


def run_baseline_round(
    conn, domain: str, targets: list[ForecastTarget] | tuple[ForecastTarget, ...],
    now: datetime, event_id: str | None = None, ridge: bool = True,
) -> BaselineRoundResult:
    """De baseline-tegenhanger van `run_forecast_round()`: zelfde doelen,
    zelfde `now`, zelfde week, één transactie.

    Idempotent per `event_id` (de ISO-week), net als de LLM-ronde. Een
    tweede run in dezelfde week schrijft niets."""
    run_domain = baseline_run_domain(domain)
    if event_id is not None and has_successful_run(conn, run_domain, "forecast", event_id):
        raise AlreadyProcessedError(run_domain, "forecast", event_id)

    resultaat = all_baseline_predictions(conn, domain, targets, now, ridge=ridge)
    save_predictions_with_run(
        conn, resultaat.predictions, run_domain, now,
        success=bool(resultaat.predictions),
        event_id=event_id,
        error="; ".join(resultaat.issues) or None,
    )
    return resultaat
