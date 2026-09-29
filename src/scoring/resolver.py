"""
resolver.py
De resolver (roadmap 4.5): wikkelt afgelopen voorspellingen af en scoort ze.

WAT HIER OP HET SPEL STAAT. Dit is de enige plek in het systeem waar wordt
vastgesteld of een agent gelijk had. Alles ervoor (monitoring, triggers,
deep-dives, de forecast-ronde) produceert materiaal; dit maakt er een
meting van. Een fout hier is niet zichtbaar in de output -- een verkeerd
afgewikkelde voorspelling ziet er precies zo uit als een goede -- en hij
is achteraf niet te repareren, want de evaluations-tabel kent geen
update-pad.

DAAROM DRIE REGELS:
1. Geen LLM. De methode staat als enum op de voorspelling, de bijbehorende
   functie staat in contract/resolution.py, en die rekent.
2. Nooit een beste gok. Ontbreekt er data, dan is de uitkomst "nog niet"
   (opnieuw proberen) of "nooit" (met reden), maar nooit een benadering.
3. Wat gebruikt is, staat erbij. Elke evaluation draagt de claim-ids die
   hem opleverden, zodat een score achteraf na te rekenen is.

DE DERDE TOESTAND DIE GEEN RIJ KRIJGT. Een voorspelling die nog niet
afwikkelbaar is, krijgt bewust geen evaluation-rij: hij blijft dan vanzelf
in beeld bij de volgende run. Pas als er te lang niets komt (zie
MAX_WACHTTIJD) wordt hij als `unresolvable` weggeschreven. Zonder die
grens zou een reeks die stilletjes stopt met publiceren een groeiende stapel
voorspellingen opleveren die elke dag opnieuw geprobeerd wordt en nooit
opvalt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from contract.prediction import Prediction, PredictionKind
from contract.resolution import (
    NotYetResolvable,
    Observation,
    Resolution,
    ResolutionMethod,
    Unresolvable,
    direction_after_fomc,
    level_at_or_after,
    nth_release,
    relative_return,
)
from scoring.scores import (
    SCORER_VERSION,
    brier_score,
    crps_from_quantiles,
    log_loss,
    pinball_losses,
    within_interval,
)
from storage.schema import (
    list_unevaluated_due_predictions,
    load_observations,
    save_evaluation,
)

logger = logging.getLogger(__name__)

MAX_WACHTTIJD = timedelta(days=30)
"""Hoe lang na `resolves_at` we blijven proberen voordat een voorspelling
als `unresolvable` wordt weggeschreven.

DERTIG DAGEN IS EEN KEUZE, GEEN BEREKENING. De afweging: te kort en een
normale publicatievertraging (een maandreeks die een week later komt dan de
schatting, een feestdagenweek) wordt onterecht als "nooit" geboekt, en dan
verdwijnt een geldige meting uit het cohort. Te lang en een bron die stil
kapot is, blijft maanden onzichtbaar. Dertig dagen ligt ruim boven de
grootste publicatievertraging die we kennen (PAYEMS, ~14 dagen) en ruim
onder een kwartaal.

Deze grens hoort bij de freeze vóór T₀ᵇ te worden bevestigd; hij bepaalt
mede welke voorspellingen in het cohort belanden."""


@dataclass
class ResolverResult:
    """Wat één resolver-ronde deed. Alle vier de getallen tellen: 'nog niet'
    is een normale, gezonde uitkomst, 'unresolvable' nooit."""

    resolved: int = 0
    still_waiting: int = 0
    unresolvable: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def has_problems(self) -> bool:
        return bool(self.errors) or self.unresolvable > 0

    def summary(self) -> str:
        return (
            f"resolver: {self.resolved} afgewikkeld, {self.still_waiting} nog wachtend, "
            f"{self.unresolvable} onafwikkelbaar, {len(self.errors)} fout(en)"
        )


def observations_for(conn, metric_key: str) -> list[Observation]:
    return [
        Observation(
            source_time=datetime.fromisoformat(source_time),
            value=waarde,
            first_seen=datetime.fromisoformat(analysis_time),
            claim_id=claim_id,
        )
        for claim_id, source_time, waarde, analysis_time in load_observations(conn, metric_key)
    ]


def resolve_one(conn, prediction: Prediction) -> Resolution:
    """Past de methode van deze voorspelling toe. Gooit `NotYetResolvable`
    of `Unresolvable` -- de aanroeper beslist wat dat betekent.

    Losse functie zodat hij zonder database-schrijfacties te testen is, en
    zodat de back-fill hem straks kan hergebruiken voor de pseudo-OOS-run
    (4.4)."""
    obs = observations_for(conn, prediction.target_metric_key)
    methode = prediction.resolution_method

    if methode is ResolutionMethod.LEVEL_AT_OR_AFTER:
        return level_at_or_after(obs, prediction.resolves_at)

    if methode is ResolutionMethod.NTH_RELEASE:
        return nth_release(obs, prediction.created_at, prediction.horizon_n)

    if methode is ResolutionMethod.RELATIVE_RETURN:
        if not prediction.benchmark_metric_key:
            raise Unresolvable("relatief rendement zonder benchmark_metric_key")
        return relative_return(
            obs,
            observations_for(conn, prediction.benchmark_metric_key),
            prediction.created_at,
            prediction.resolves_at,
        )

    if methode is ResolutionMethod.DIRECTION_AFTER_FOMC:
        return direction_after_fomc(obs, prediction.created_at, prediction.horizon_n)

    # Onbereikbaar zolang de enum en deze functie gelijk lopen. Staat er
    # toch, omdat een nieuwe methode zonder tak hier anders stilzwijgend
    # niets zou doen -- en dat is precies het faalpatroon dat CLAUDE.md
    # als terugkerend aanwijst.
    raise Unresolvable(f"onbekende resolutiemethode: {methode}")


def score_prediction(prediction: Prediction, realised: float) -> dict[str, float]:
    """De scores voor één afgewikkelde voorspelling. Zuivere functie."""
    if prediction.kind is PredictionKind.QUANTILE:
        verliezen = pinball_losses(prediction.q10, prediction.q50, prediction.q90, realised)
        return {
            "pinball_q10": verliezen["q10"],
            "pinball_q50": verliezen["q50"],
            "pinball_q90": verliezen["q90"],
            "pinball_mean": verliezen["mean"],
            "crps": crps_from_quantiles(
                prediction.q10, prediction.q50, prediction.q90, realised
            ),
            "within_interval": within_interval(prediction.q10, prediction.q90, realised),
        }
    gebeurde = realised >= 0.5
    return {
        "brier": brier_score(prediction.probability, gebeurde),
        "log_loss": log_loss(prediction.probability, gebeurde),
    }


def resolve_due_predictions(
    conn, now: datetime | None = None, max_wachttijd: timedelta = MAX_WACHTTIJD
) -> ResolverResult:
    """Wikkelt elke afgelopen, nog niet beoordeelde voorspelling af.

    Draait dagelijks mee in `run_daily` (1.11). Elke voorspelling in zijn
    eigen try/except: één stukke reeks mag de rest van het cohort niet
    tegenhouden -- zelfde isolatie als bij monitoring en de
    forecast-ronde."""
    now = now or datetime.now(timezone.utc)
    resultaat = ResolverResult()

    for prediction_id, prediction in list_unevaluated_due_predictions(conn, now):
        te_laat = now - prediction.resolves_at > max_wachttijd
        try:
            uitkomst = resolve_one(conn, prediction)
        except NotYetResolvable as e:
            if not te_laat:
                resultaat.still_waiting += 1
                continue
            # De wachttijd is om. Wat "nog niet" was, is nu "nooit" --
            # anders blijft deze voorspelling eeuwig meedraaien zonder dat
            # iemand het merkt.
            save_evaluation(
                conn, prediction_id, "unresolvable", now, SCORER_VERSION,
                reason=f"wachttijd van {max_wachttijd.days} dagen verstreken: {e}",
            )
            resultaat.unresolvable += 1
            logger.warning(
                "Voorspelling %d (%s/%s) onafwikkelbaar na %d dagen: %s",
                prediction_id, prediction.domain, prediction.target_metric_key,
                max_wachttijd.days, e,
            )
            continue
        except Unresolvable as e:
            save_evaluation(
                conn, prediction_id, "unresolvable", now, SCORER_VERSION, reason=str(e)
            )
            resultaat.unresolvable += 1
            logger.warning(
                "Voorspelling %d (%s/%s) onafwikkelbaar: %s",
                prediction_id, prediction.domain, prediction.target_metric_key, e,
            )
            continue
        except Exception as e:  # noqa: BLE001
            # Een bug in de resolutielogica. GEEN evaluation-rij: die zou
            # onherroepelijk zijn, en een bug is te repareren. Wel luid.
            resultaat.errors.append(
                f"voorspelling {prediction_id} ({prediction.domain}/"
                f"{prediction.target_metric_key}): {type(e).__name__}: {e}"
            )
            logger.error("Resolver-fout bij voorspelling %d: %s", prediction_id, e)
            continue

        try:
            scores = score_prediction(prediction, uitkomst.value)
        except Exception as e:  # noqa: BLE001
            resultaat.errors.append(f"score voor voorspelling {prediction_id} mislukt: {e}")
            logger.error("Score-fout bij voorspelling %d: %s", prediction_id, e)
            continue

        save_evaluation(
            conn, prediction_id, "resolved", now, SCORER_VERSION,
            realised_value=uitkomst.value,
            realised_at=uitkomst.realised_at,
            claim_ids=uitkomst.claim_ids,
            scores=scores,
        )
        resultaat.resolved += 1

    return resultaat
