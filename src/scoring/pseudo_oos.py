"""
scoring/pseudo_oos.py
De pseudo-out-of-sample-run (roadmap 4.4, fase 3b): de agents doen de wekelijkse forecast-ronde over het verleden
(juli tot en met september 2026, ná de kennisgrens van het model), op data zoals die op dat moment bekend was.

DOEL, EERLIJK. Contract- en resolverfouten vinden vóór de klok loopt, en meten hoe vaak het model vijf kwantielen
betrouwbaar uitspreekt (meer dan 5% niet opgeleverd = het contract heroverwegen). GEEN bewijs van kalibratie: het
venster is kort, de lange horizonnen lopen nog, en de uitkomsten overlappen. Apart gelabeld (`cohort=pseudo_oos`).

HOE HET VERLEDEN EERLIJK BLIJFT. Het systeem bepaalt "wat was er bekend" met `first_seen` (= `analysis_time` van de
claim). De back-fill zet die gelijk aan de waarnemingsdatum, en dat is voor de back-fill zelf juist, maar niet
voor de VERSCHIJNING: een maandcijfer met datum 1 juli verscheen pas in augustus. Zonder correctie zou de agent op 6 juli
het cijfer van juli zien. Daarom werkt deze run op een KOPIE van de database waarin `analysis_time` van de back-fill-claims
wordt verschoven met een AANGENOMEN publicatievertraging per reeks (`PUBLICATIE_VERTRAGING_DAGEN`). Alle bestaande
point-in-time-code (evidence-sheet, baselines, resolver) werkt dan ongewijzigd, en de ECHTE database wordt nooit aangeraakt.

DE AANNAMES ZIJN NIET MET ZEKERHEID TE VERIFIËREN (CLAUDE.md, checkpoint 4). Ze zijn conservatief: een te grote vertraging laat
de agent oudere data zien, nooit nieuwere. De waarden zijn mijn inschatting van de publicatiekalenders; `audit` toont per reeks
de laatste zichtbare waarneming op elke datum, zodat DD dat kan naast de werkelijke kalender leggen.

WAT DIT NIET DOET
  - Geen ridge-baseline. Die wordt op ALLE historie gefit en kent het venster dus al; vergelijken zou de baseline
    onzichtbaar te goed maken. Alleen persistence en climatology (point-in-time) doen mee.
  - Geen herziene-versus-eerste-print-correctie: de back-fill is gereviseerd (vooral payrolls, weekcijfers). Bekende beperking.
  - Geen tweede run over 2025 met een ouder model (roadmap: "daarna over 2025"): er is geen passend model gekozen; bewust uitgesteld.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from contract.output_contract import Claim
from contract.prediction import PSEUDO_OOS_COHORT
from scoring.baselines import _history
from storage.schema import _claim_from_row, load_observations

VENSTER_VAN = date(2026, 7, 6)  # maandag
VENSTER_TOT = date(2026, 9, 28)  # maandag
FORECAST_TIJD = time(7, 15)  # zoals de cron: 07:15 UTC
MAX_AFGEWEZEN_AANDEEL = 0.05  # zelfde grens als het freeze-overzicht

META_TABEL = "pseudo_oos_meta"

# Dagen tussen de waarnemingsdatum (`source_time`) en het moment waarop de waarde publiek bekend is. CONSERVATIEF en
# AANGENOMEN, niet geverifieerd. Voor maandseries is `source_time` de EERSTE van de referentiemaand (FRED). De
# dagseries krijgen 1 dag: de run van maandag 07:15 UTC ziet de slotstand van vrijdag, niet die van maandag.
PUBLICATIE_VERTRAGING_DAGEN: dict[str, int] = {
    # monetary_policy (FRED)
    # FEDFUNDS is een MAANDGEMIDDELDE (866 waarnemingen sinds 1954), geen dagreeks: de waarde met datum 1 juli bestaat pas
    # na afloop van juli. Eerst op 1 dag gezet (aanname dat het de dagreeks was); `audit` op de echte data liet zien dat
    # op 6 juli de julistand zichtbaar was. Daarom controleert `bereid_voor` nu de werkelijke frequentie (zie hieronder).
    "fed_funds_rate": 35,
    "fed_funds_target_upper": 1,
    "10y_treasury_yield": 1,
    "2y_treasury_yield": 1,
    "inflation_expectations_5y": 1,
    "inflation_expectations_10y": 1,
    "fed_balance_sheet": 2,  # weekreeks, woensdagstand, donderdag gepubliceerd
    "cpi_inflation_index": 45,  # maandreeks, ~tweede week van de volgende maand
    "unemployment_rate": 38,  # maandreeks, eerste vrijdag (soms de 9e) van de volgende maand
    # financial (FRED)
    "financial_conditions_index": 6,  # NFCI: weekreeks, woensdag voor de week die vrijdag eindigde
    "high_yield_credit_spread": 1,
    "vix": 1,
    "yield_curve_10y_2y": 1,
    # economic (FRED)
    "initial_claims": 6,  # weekreeks, donderdag na het weekeinde
    "nonfarm_payrolls": 38,  # zelfde publicatie als de werkloosheid
    # currency (Alpha Vantage)
    "eur_usd": 1,
    "usd_jpy": 1,
    "gbp_usd": 1,
    # sector (Alpha Vantage)
    "xlk_technology": 1, "xlf_financials": 1, "xle_energy": 1, "xlv_health_care": 1,
    "xly_consumer_discretionary": 1, "xlp_consumer_staples": 1, "xli_industrials": 1, "xlb_materials": 1,
    "xlu_utilities": 1, "xlre_real_estate": 1, "xlc_communication_services": 1, "spy_benchmark": 1,
}


# Minimale vertraging per werkelijke frequentie, afgeleid van de afstand tussen waarnemingen in de data zelf.
MIN_VERTRAGING_PER_FREQUENTIE = (  # (mediane afstand in dagen, minimale vertraging, naam)
    (25, 30, "maandreeks"),
    (6, 2, "weekreeks"),
    (0, 1, "dagreeks"),
)


def werkelijke_frequentie(waarnemingsdagen: list[date]) -> tuple[int, str] | None:
    """(minimale vertraging, naam) volgens de mediane afstand tussen de waarnemingsdata, of None bij te weinig data."""
    dagen = sorted(set(waarnemingsdagen))
    if len(dagen) < 6:
        return None
    afstanden = sorted((b - a).days for a, b in zip(dagen, dagen[1:]))
    mediaan = afstanden[len(afstanden) // 2]
    for drempel, minimum, naam in MIN_VERTRAGING_PER_FREQUENTIE:
        if mediaan >= drempel:
            return minimum, naam
    return None


class PseudoOosFout(Exception):
    """De voorbereiding of de run kan niet veilig doorgaan. Er is niets weggeschreven dat een echte database raakt."""


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------


def voorspeldata(van: date = VENSTER_VAN, tot: date = VENSTER_TOT) -> list[datetime]:
    """Elke maandag in het venster, om 07:15 UTC (de tijd van de echte cron)."""
    uit, d = [], van
    while d <= tot:
        if d.weekday() == 0:
            uit.append(datetime.combine(d, FORECAST_TIJD, tzinfo=timezone.utc))
        d += timedelta(days=1)
    return uit


def vertraging_voor(metric_key: str) -> int | None:
    """Dagen vertraging voor een reeks, of None als die ontbreekt. Afgeleide `<reeks>_rel_spy` volgt zijn basisreeks."""
    if metric_key in PUBLICATIE_VERTRAGING_DAGEN:
        return PUBLICATIE_VERTRAGING_DAGEN[metric_key]
    if metric_key.endswith("_rel_spy"):
        return PUBLICATIE_VERTRAGING_DAGEN.get(metric_key[: -len("_rel_spy")])
    return None


MAX_DAGEN_TOT_VOLGENDE_FOMC = 56
"""De Fed vergadert acht keer per jaar; de grootste afstand tussen twee besluitdagen is zeven weken. Ligt de eerstvolgende
besluitdag na een voorspeldatum verder weg dan acht weken, dan ontbreekt er een vergadering in de kalender."""


def controleer_fomc_kalender(datums, kalender=None) -> None:
    """Weigert te draaien als de FOMC-kalender het venster niet dekt. Zonder de besluitdagen van juli en september 2026
    zou de agent op 6 juli horen dat de eerstvolgende besluitdag 28 oktober is, en zou de resolver de FOMC-doelen op de
    verkeerde vergadering afrekenen: een stille fout die nergens aan de data te zien is. Kan de volledigheid niet bewijzen,
    wel dat er een gat zit; de datums zelf moet DD op federalreserve.gov verifiëren."""
    from contract import resolution as res

    kalender = sorted(res.FOMC_MEETING_DATES if kalender is None else kalender)
    for d in datums:
        komend = [m for m in kalender if m > d.date()]
        if not komend or (komend[0] - d.date()).days > MAX_DAGEN_TOT_VOLGENDE_FOMC:
            eerstvolgende = komend[0].isoformat() if komend else "geen"
            raise PseudoOosFout(
                f"de FOMC-kalender mist besluitdagen rond {d.date()}: de eerstvolgende bekende is {eerstvolgende}, "
                f"meer dan {MAX_DAGEN_TOT_VOLGENDE_FOMC} dagen later. Voeg de besluitdagen van juli en september 2026 toe aan "
                f"FOMC_MEETING_DATES (contract/resolution.py), na controle op federalreserve.gov"
            )


def benodigde_reeksen(agents) -> set[str]:
    """Elke reeks die in de run een rol speelt: de doelen, hun benchmarks en alles wat de agents monitoren."""
    from agents import (
        currency_agent, economic_agent, financial_agent, monetary_policy_agent, sector_agent,
    )

    modules = {
        "monetary_policy": monetary_policy_agent, "currency": currency_agent, "financial": financial_agent,
        "sector": sector_agent, "economic": economic_agent,
    }
    reeksen: set[str] = set()
    for spec in agents:
        if not spec.forecasts:
            continue
        for t in spec.forecast_targets:
            reeksen.add(t.metric_key)
            if t.benchmark_metric_key:
                reeksen.add(t.benchmark_metric_key)
        reeksen.update(getattr(modules[spec.domain], "METRIC_SPECS", {}))
    return reeksen


# --------------------------------------------------------------------------
# Voorbereiden: de kopie met verschoven publicatiemomenten
# --------------------------------------------------------------------------


@dataclass
class VoorbereidRapport:
    doel: str
    verschoven: dict[str, int] = field(default_factory=dict)  # metric_key -> aantal verschoven claims
    niet_verschoven: dict[str, int] = field(default_factory=dict)  # eigen (live) claims: al correcte analysis_time

    @property
    def totaal_verschoven(self) -> int:
        return sum(self.verschoven.values())


def is_voorbereid(conn: sqlite3.Connection) -> bool:
    try:
        return conn.execute(f"SELECT 1 FROM {META_TABEL} WHERE key = 'voorbereid_op'").fetchone() is not None
    except sqlite3.Error:
        return False


def bereid_voor(bron: str, doel: str, agents=None) -> VoorbereidRapport:
    """Maakt `doel` als kopie van `bron` en verschuift daarin `analysis_time` van de back-fill-claims met de
    publicatievertraging. De bron wordt alleen gelezen (`mode=ro`) en nooit gewijzigd. Mislukt de voorbereiding, dan
    blijft er geen halve kopie achter."""
    from runtime.daily import default_agents

    agents = agents if agents is not None else default_agents()
    bron_pad, doel_pad = Path(bron), Path(doel)
    if not bron_pad.exists():
        raise PseudoOosFout(f"bron-database niet gevonden: {bron}")
    if doel_pad.exists():
        raise PseudoOosFout(f"{doel} bestaat al: kies een nieuwe naam (er wordt niets overschreven)")
    if doel_pad.resolve() == bron_pad.resolve():
        raise PseudoOosFout("doel en bron zijn dezelfde database")
    doel_pad.parent.mkdir(parents=True, exist_ok=True)

    rapport = VoorbereidRapport(doel=str(doel_pad))
    bron_conn = sqlite3.connect(f"file:{bron_pad}?mode=ro", uri=True)
    doel_conn = sqlite3.connect(doel_pad)
    try:
        bron_conn.backup(doel_conn)
        bron_conn.close()
        bron_conn = None

        # Elke reeks die we nodig hebben moet een vertraging hebben: een reeks zonder zou ongecorrigeerd (te vroeg)
        # zichtbaar zijn, en dat mag nooit stilzwijgend.
        in_gebruik = {r for (r,) in doel_conn.execute("SELECT DISTINCT metric_key FROM claims WHERE metric_key IS NOT NULL")}
        zonder = sorted(k for k in benodigde_reeksen(agents) & in_gebruik if vertraging_voor(k) is None)
        if zonder:
            raise PseudoOosFout(f"geen publicatievertraging vastgelegd voor: {', '.join(zonder)}")

        # Een aangenomen vertraging kan fout zijn als de reeks een andere frequentie blijkt te hebben dan gedacht (zo ging het
        # met FEDFUNDS). Daarom wordt elke vertraging getoetst aan de werkelijke afstand tussen de waarnemingen.
        te_kort = []
        for key in sorted(in_gebruik):
            dagen = vertraging_voor(key)
            if dagen is None or key not in benodigde_reeksen(agents):
                continue
            waargenomen = [date.fromisoformat(src[:10]) for (src,) in doel_conn.execute(
                "SELECT DISTINCT substr(source_time, 1, 10) FROM claims WHERE metric_key = ? AND source_time IS NOT NULL", (key,))]
            frequentie = werkelijke_frequentie(waargenomen)
            if frequentie and dagen < frequentie[0]:
                te_kort.append(f"{key}: {dagen} dagen, maar het is een {frequentie[1]} (minimaal {frequentie[0]} dagen)")
        if te_kort:
            raise PseudoOosFout("publicatievertraging te kort voor de werkelijke frequentie van de reeks: " + "; ".join(te_kort))

        for key in sorted(in_gebruik):
            dagen = vertraging_voor(key)
            if dagen is None:
                continue  # geen reeks van een voorspellende agent; niet gebruikt
            rijen = doel_conn.execute(
                "SELECT id, source_time, analysis_time FROM claims WHERE metric_key = ? AND source_time IS NOT NULL", (key,)
            ).fetchall()
            wijzigingen = []
            for claim_id, source_time, analysis_time in rijen:
                bron_dt = datetime.fromisoformat(source_time)
                if datetime.fromisoformat(analysis_time) != bron_dt:
                    rapport.niet_verschoven[key] = rapport.niet_verschoven.get(key, 0) + 1
                    continue  # een eigen, live claim: zijn analysis_time is al het echte moment
                wijzigingen.append(((bron_dt + timedelta(days=dagen)).isoformat(), claim_id))
            doel_conn.executemany("UPDATE claims SET analysis_time = ? WHERE id = ?", wijzigingen)
            if wijzigingen:
                rapport.verschoven[key] = len(wijzigingen)

        doel_conn.execute(f"CREATE TABLE {META_TABEL} (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        doel_conn.executemany(
            f"INSERT INTO {META_TABEL} (key, value) VALUES (?, ?)",
            [
                ("voorbereid_op", datetime.now(timezone.utc).isoformat()),
                ("bron", str(bron_pad)),
                ("vertraging_dagen", json.dumps(PUBLICATIE_VERTRAGING_DAGEN, sort_keys=True)),
                ("verschoven", json.dumps(rapport.verschoven, sort_keys=True)),
            ],
        )
        doel_conn.commit()
    except BaseException:
        doel_conn.close()
        if bron_conn is not None:
            bron_conn.close()
        doel_pad.unlink(missing_ok=True)
        raise
    doel_conn.close()
    return rapport


# --------------------------------------------------------------------------
# Wat de agent op een datum ziet
# --------------------------------------------------------------------------


def claims_op_datum(conn: sqlite3.Connection, domain: str, as_of: datetime) -> list[Claim]:
    """Per reeks van dit domein de laatste waarneming die op `as_of` bekend was: waargenomen op of voor die dag én
    al gezien (`first_seen` = `analysis_time`) op dat moment. Dit is de point-in-time-tegenhanger van
    `load_monitoring_claims` (die de laatste LIVE cyclus geeft)."""
    keys = [r for (r,) in conn.execute(
        "SELECT DISTINCT metric_key FROM claims WHERE domain = ? AND metric_key IS NOT NULL ORDER BY metric_key", (domain,)
    )]
    uit: list[Claim] = []
    for key in keys:
        zichtbaar = [
            (datetime.fromisoformat(src), claim_id) for claim_id, src, _w, ana in load_observations(conn, key)
            if datetime.fromisoformat(src).date() <= as_of.date() and datetime.fromisoformat(ana) <= as_of
        ]
        if not zichtbaar:
            continue
        _, claim_id = max(zichtbaar)
        rij = conn.execute(
            "SELECT domain, claim, value_json, source, confidence, event_time, source_time, ingestion_time, "
            "analysis_time, metric_key, note FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        uit.append(_claim_from_row(rij))
    return uit


def zichtbare_geschiedenis(conn: sqlite3.Connection, metric_key: str, as_of: datetime):
    """De eerste prints die op `as_of` bekend waren (zelfde regel als evidence-sheet en baselines)."""
    return _history(conn, metric_key, as_of)


# --------------------------------------------------------------------------
# Draaien
# --------------------------------------------------------------------------


@contextmanager
def pseudo_oos_cohort():
    """Zet het cohort van nieuwe voorspellingen op `pseudo_oos` zolang de run duurt (`current_cohort()` leest
    `MI_COHORT`) en herstelt het daarna, ook bij een fout."""
    oud = os.environ.get("MI_COHORT")
    os.environ["MI_COHORT"] = PSEUDO_OOS_COHORT
    try:
        yield
    finally:
        if oud is None:
            os.environ.pop("MI_COHORT", None)
        else:
            os.environ["MI_COHORT"] = oud


def _vereis_voorbereid(conn: sqlite3.Connection) -> None:
    if not is_voorbereid(conn):
        raise PseudoOosFout(
            "dit is geen voorbereide pseudo-OOS-database (de tabel `pseudo_oos_meta` ontbreekt). "
            "Draai eerst `pseudo_oos.py voorbereiden`; er wordt nooit in de echte database gedraaid."
        )


def _agents_met_voorspellingen(agents):
    return [a for a in agents if a.forecasts]


def bouw_prompt(conn: sqlite3.Connection, spec, datum: datetime) -> tuple[str, str]:
    """(systeemprompt, gebruikersprompt) die het model op `datum` zou krijgen. Geen LLM-aanroep."""
    from agents.base import FORECAST_SYSTEM_RULES, _forecast_user_prompt
    from scoring.evidence_sheet import build_evidence_sheet

    claims = claims_op_datum(conn, spec.domain, datum)
    evidence = build_evidence_sheet(conn, list(spec.forecast_targets), claims, datum)
    systeem = f"{FORECAST_SYSTEM_RULES}\n\n{spec.forecast_system_prompt}"
    return systeem, _forecast_user_prompt(list(spec.forecast_targets), claims, evidence)


@dataclass
class KostenSchatting:
    aanroepen: int
    input_tokens: int
    output_tokens: int
    kosten_usd: float
    model: str


def schat_kosten(conn: sqlite3.Connection, agents, datums, model: str) -> KostenSchatting:
    """Ruwe schatting uit de ECHTE promptlengtes (geen aanroep): 3 tekens per token (voorzichtig voor Nederlands) en
    ~30 tokens uitvoer per gevraagde voorspelling. Een schatting, geen meting; de testrun geeft de echte cijfers."""
    from runtime.llm_budget import kosten_usd

    n_in = n_uit = n = 0
    for d in datums:
        for spec in _agents_met_voorspellingen(agents):
            systeem, gebruiker = bouw_prompt(conn, spec, d)
            n_in += (len(systeem) + len(gebruiker)) // 3
            n_uit += 100 + 30 * sum(len(t.horizons) for t in spec.forecast_targets)
            n += 1
    kosten, _ = kosten_usd(model, n_in, n_uit)
    return KostenSchatting(n, n_in, n_uit, kosten, model)


@dataclass
class RondeUitkomst:
    datum: datetime
    domain: str
    verwacht: int
    gekregen: int
    issues: tuple[str, ...]


def draai(conn: sqlite3.Connection, client, agents, datums, model: str | None = None) -> list[RondeUitkomst]:
    """De forecast-rondes én de point-in-time-baselines (zonder ridge) voor elke datum en agent. Idempotent per ISO-week:
    een hervatting slaat af wat er al staat. Elke agent in zijn eigen try/except, zoals in de dagelijkse run."""
    from agents.base import DEFAULT_DEEP_DIVE_MODEL, AlreadyProcessedError, run_forecast_round
    from runtime.daily import weekly_event_id
    from scoring.baseline_round import run_baseline_round

    _vereis_voorbereid(conn)
    controleer_fomc_kalender(datums)
    model = model or DEFAULT_DEEP_DIVE_MODEL
    uitkomsten: list[RondeUitkomst] = []
    with pseudo_oos_cohort():
        for datum in datums:
            week = weekly_event_id(datum)
            for spec in _agents_met_voorspellingen(agents):
                verwacht = sum(len(t.horizons) for t in spec.forecast_targets)
                try:
                    claims = claims_op_datum(conn, spec.domain, datum)
                    from scoring.evidence_sheet import build_evidence_sheet

                    evidence = build_evidence_sheet(conn, list(spec.forecast_targets), claims, datum)
                    r = run_forecast_round(
                        conn, client, spec.domain, spec.forecast_system_prompt, list(spec.forecast_targets), claims,
                        prompt_version=spec.prompt_version, model=model, now=datum, event_id=week, evidence=evidence,
                    )
                    uitkomsten.append(RondeUitkomst(datum, spec.domain, verwacht, len(r.predictions), r.issues))
                except AlreadyProcessedError:
                    continue
                except Exception as e:  # noqa: BLE001
                    uitkomsten.append(RondeUitkomst(datum, spec.domain, verwacht, 0, (f"ronde afgebroken: {type(e).__name__}: {e}",)))
                try:
                    run_baseline_round(conn, spec.domain, spec.forecast_targets, datum, event_id=week, ridge=False)
                except AlreadyProcessedError:
                    pass
                except Exception as e:  # noqa: BLE001
                    uitkomsten.append(RondeUitkomst(datum, f"baseline:{spec.domain}", 0, 0, (f"{type(e).__name__}: {e}",)))
    return uitkomsten


# --------------------------------------------------------------------------
# Afwikkelen en rapporteren
# --------------------------------------------------------------------------


def afwikkelen(conn: sqlite3.Connection, now: datetime):
    """Wikkelt af wat op `now` afgewikkeld kan worden, in de kopie."""
    from scoring.resolver import resolve_due_predictions

    _vereis_voorbereid(conn)
    with pseudo_oos_cohort():
        return resolve_due_predictions(conn, now=now)


@dataclass
class AgentRapport:
    domain: str
    verwacht: int
    gekregen: int
    afgewikkeld: int
    onafwikkelbaar: int

    @property
    def gemist_aandeel(self) -> float:
        return (self.verwacht - self.gekregen) / self.verwacht if self.verwacht else 0.0


def rapport(conn: sqlite3.Connection, agents) -> list[AgentRapport]:
    """Per agent: hoeveel voorspellingen waren er gevraagd, hoeveel zijn er opgeleverd, hoeveel afgewikkeld.
    Gevraagd = het aantal doelen×horizonnen per ronde, maal elke ronde van deze agent in het venster (ook een mislukte:
    die levert nul op en telt dus als gemist)."""
    uit = []
    for spec in _agents_met_voorspellingen(agents):
        per_ronde = sum(len(t.horizons) for t in spec.forecast_targets)
        rondes, gekregen = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(trigger_count), 0) FROM agent_runs WHERE mode = 'forecast' AND domain = ? "
            "AND run_at >= ? AND run_at < ?",
            (spec.domain, VENSTER_VAN.isoformat(), (VENSTER_TOT + timedelta(days=1)).isoformat()),
        ).fetchone()

        def tel(status: str) -> int:
            return conn.execute(
                "SELECT COUNT(*) FROM evaluations e JOIN predictions p ON p.id = e.prediction_id "
                "WHERE p.agent = ? AND p.cohort = ? AND e.status = ?", (spec.domain, PSEUDO_OOS_COHORT, status),
            ).fetchone()[0]

        uit.append(AgentRapport(spec.domain, per_ronde * rondes, gekregen, tel("resolved"), tel("unresolvable")))
    return uit
