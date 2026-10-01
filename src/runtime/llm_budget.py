"""
llm_budget.py
Roadmap 1.11, checkpoint 3 (dry-run-plan voor `--deep-dives`, 30-09-2026):
tokenverbruik vastleggen per LLM-aanroep, en een harde maandrem.

WAAROM DIT BESTAAT. Zodra `--deep-dives` aanstaat, maakt een onbeheerd systeem
betaalde aanroepen. Verwacht is ~$0,15 tot $0,25 per week; een fout (een lus
die zichzelf herhaalt, een prompt die per ongeluk 100x groter wordt) kan dat in
één nacht vertienvoudigen zonder dat iemand het ziet. De rem staat op
$200 per maand (DD, 30-09): ruim boven alles wat normaal is, dus hij grijpt
alleen in bij een echte ontsporing. Het Anthropic-console blijft de
autoriteit aan de factuurkant; dit is de tweede lijn, die het systeem zelf
ziet en waarvan de melding in de log en in de exit code terechtkomt.

HOE HET INGRIJPT. Niet stil. De aanroep die de grens raakt gooit
`BudgetExceeded`; de bestaande foutisolatie vangt die op zoals elke andere
mislukte LLM-aanroep (de deep-dive wordt `needs_review`, de forecast-ronde een
mislukte agent_run met reden, de QC-review een issue). Dat zet
`has_problems` en dus exit code 1 en de melding. Geen enkele agent blokkeert
de ingestie: monitoring draait vóór de LLM-fase.

BEWUST GEEN "STOPPEN ZONDER MELDING": een voorspelling die door de rem
wegvalt is een gat in het cohort, en dat mag nooit onzichtbaar zijn.

PRIJZEN staan hier hardcoded, met de datum waarop ze zijn gecontroleerd. Een
prijsverandering maakt de schatting scheef, niet de rem stuk; het console
geeft de echte kosten. Een onbekend model wordt tegen de DUURSTE bekende prijs
geteld: liever te vroeg remmen dan te laat.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from storage.schema import llm_usage_since, record_llm_call, record_llm_usage

logger = logging.getLogger(__name__)

MAX_VERZOEK_TEKENS = 100_000
"""Grootste verzoek dat een aanroep mag sturen, in tekens van het hele verzoek (systeemprompt en berichten). Een
normale aanroep is nu 5.000 tot 15.000 tekens; dit is ruim tien keer zoveel. Waarom het bestaat: op 01-10-2026
bleek de forecast-ronde per ongeluk de VOLLEDIGE claims-historie mee te sturen (~4 miljoen tekens). De maandrem
telt alleen wat er al is uitgegeven en ziet zo'n verzoek niet aankomen. Zegt de prompt-opbouw ooit weer iets
onverwachts groots, dan stopt de aanroep zichtbaar (zoals de maandrem) in plaats van duur of onleesbaar door te
gaan. Bewust verhoogbaar zodra een rijkere evidence-sheet dat nodig maakt: dan is het een beslissing, geen bijwerking."""

MAX_MAANDBEDRAG_ENV = "MI_MAX_MAANDBEDRAG_USD"
STANDAARD_MAX_MAANDBEDRAG_USD = 200.0
WAARSCHUWING_VANAF = 0.5
"""Vanaf welk aandeel van de maandgrens elke aanroep een WARNING in de log geeft."""

PRIJS_PEILDATUM = "2026-09-25"
# (dollar per miljoen invoertokens, dollar per miljoen uitvoertokens)
PRIJZEN_USD_PER_MILJOEN: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
DUURSTE_PRIJS = max(PRIJZEN_USD_PER_MILJOEN.values())


class VerzoekTeGroot(Exception):
    """Het verzoek is groter dan `MAX_VERZOEK_TEKENS`. Er is niets verstuurd en er is niets uitgegeven."""


class BudgetExceeded(RuntimeError):
    """De maandgrens voor LLM-kosten is bereikt; er wordt niet meer aangeroepen."""


def max_maandbedrag(environ=None) -> float:
    """De maandgrens in USD uit `MI_MAX_MAANDBEDRAG_USD`, default $200. Een
    onleesbare of niet-positieve waarde is een fout (ValueError), zoals bij een
    onbekend cohort: een rem die stil naar 0 of oneindig valt is erger dan geen
    rem, en `run_daily.py` stopt er dan met exit 2 voor er iets gebeurt."""
    environ = os.environ if environ is None else environ
    ruw = (environ.get(MAX_MAANDBEDRAG_ENV) or "").strip()
    if not ruw:
        return STANDAARD_MAX_MAANDBEDRAG_USD
    try:
        waarde = float(ruw)
    except ValueError:
        raise ValueError(f"{MAX_MAANDBEDRAG_ENV}={ruw!r} is geen getal") from None
    if not waarde > 0:
        raise ValueError(f"{MAX_MAANDBEDRAG_ENV}={ruw!r} moet groter dan nul zijn")
    return waarde


def kosten_usd(model: str, input_tokens: int, output_tokens: int) -> tuple[float, str]:
    """Geschatte kosten in USD, plus een notitie over welke prijs is gebruikt."""
    prijs = PRIJZEN_USD_PER_MILJOEN.get(model)
    notitie = f"prijzen {PRIJS_PEILDATUM}"
    if prijs is None:
        prijs = DUURSTE_PRIJS
        notitie = f"ONBEKEND MODEL, duurste prijs aangenomen ({PRIJS_PEILDATUM})"
    return (input_tokens * prijs[0] + output_tokens * prijs[1]) / 1_000_000, notitie


def begin_van_de_maand(nu: datetime) -> datetime:
    nu = nu.astimezone(timezone.utc)
    return nu.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class MaandVerbruik:
    kosten_usd: float
    aanroepen: int
    input_tokens: int
    output_tokens: int


def maandverbruik(conn, nu: datetime | None = None) -> MaandVerbruik:
    nu = nu or datetime.now(timezone.utc)
    kosten, n, tin, tuit = llm_usage_since(conn, begin_van_de_maand(nu))
    return MaandVerbruik(kosten, n, tin, tuit)


DENKEN_UIT = {"type": "between_tools"}
"""Het `thinking`-verzoek dat denken uitzet op Claude Sonnet 5.5. Op dat model staat denken STANDAARD AAN
(op Sonnet 4.6 stond het uit als je niets meestuurde), `{"type": "disabled"}` geeft er een 400, en
`between_tools` is de manier om het uit te zetten (alleen toegestaan bij effort `high` of lager, zonder
andere velden).

WAAROM DIT HIER STAAT. Onze aanroepen sturen geen `thinking` mee en hebben een kleine `max_tokens` (500 voor
de QC-review, 800 voor de deep-dive, 2000 voor de forecast-ronde). Met denken aan telt het denken mee voor die
limiet: het antwoord kan dan leeg of afgekapt terugkomen, en de QC-review zou stil verzwakken. Dit is het
enige punt waar elke aanroep doorheen loopt, dus één beleid dekt ze allemaal zonder `src/qc/` aan te raken
(checkpoint 2). Een bewuste keuze, geen eindoordeel: denken AAN voor de forecast-ronde is een
experiment voor de begeleide testrun (de instelling staat in `llm_calls.request_json`)."""
MODELLEN_ZONDER_STANDAARD_DENKEN = frozenset({"claude-sonnet-5-5"})


def met_denkbeleid(kwargs: dict) -> dict:
    """Zet denken uit voor modellen waar het standaard aanstaat, tenzij de aanroeper zelf iets koos."""
    if kwargs.get("model") in MODELLEN_ZONDER_STANDAARD_DENKEN and "thinking" not in kwargs:
        return {**kwargs, "thinking": dict(DENKEN_UIT)}
    return kwargs


class _Berichten:
    def __init__(self, gemeterd: "MeteredClient"):
        self._g = gemeterd

    def create(self, **kwargs):
        return self._g._create(**kwargs)


class MeteredClient:
    """Wikkelt een Anthropic-client: controleert vooraf de maandgrens, legt na
    afloop het verbruik vast en logt het.

    Alles wat de agents gebruiken is `client.messages.create(...)`; andere
    attributen worden doorgegeven aan de echte client. `nu` is injecteerbaar zodat
    tests de maandwissel kunnen nabootsen zonder te wachten."""

    def __init__(self, client, conn, max_maandbedrag: float = STANDAARD_MAX_MAANDBEDRAG_USD, nu=None):
        self._client = client
        self._conn = conn
        self.max_maandbedrag = max_maandbedrag
        self._nu = nu or (lambda: datetime.now(timezone.utc))
        self.messages = _Berichten(self)
        self.aanroepen_deze_run = 0
        self.kosten_deze_run = 0.0
        self._context: dict = {}

    def __getattr__(self, naam):
        return getattr(self._client, naam)

    @contextmanager
    def context(self, domain: str | None = None, purpose: str | None = None, event_id: str | None = None):
        """Legt vast voor WELKE agent, WELK doel en WELK event de aanroepen binnen dit blok zijn
        (komt in `llm_calls`). Binnen elkaar te gebruiken; het binnenste wint."""
        vorige = self._context
        self._context = {"domain": domain, "purpose": purpose, "event_id": event_id}
        try:
            yield self
        finally:
            self._context = vorige

    def _leg_aanroep_vast(self, nu, kwargs, antwoord=None, fout=None) -> None:
        """Schrijft het ruwe verzoek en antwoord weg. Een mislukte schrijfactie mag NOOIT het antwoord van het
        model kosten (de aanroep is al betaald) en nooit de run laten crashen, maar wordt wel hard gelogd:
        een gat in het logboek mag niet onzichtbaar zijn."""
        try:
            tekst = stop = tin = tuit = None
            if antwoord is not None:
                tekst = "".join(
                    getattr(b, "text", "") or "" for b in (getattr(antwoord, "content", None) or [])
                    if getattr(b, "type", None) == "text"
                )
                stop = getattr(antwoord, "stop_reason", None)
                gebruik = getattr(antwoord, "usage", None)
                tin = getattr(gebruik, "input_tokens", None)
                tuit = getattr(gebruik, "output_tokens", None)
            record_llm_call(
                self._conn, nu, str(kwargs.get("model") or "onbekend"), kwargs,
                response_text=tekst, stop_reason=stop if isinstance(stop, str) else None,
                input_tokens=tin if isinstance(tin, (int, float)) else None,
                output_tokens=tuit if isinstance(tuit, (int, float)) else None,
                error=fout, **self._context,
            )
        except Exception as e:  # noqa: BLE001 -- bewust breed: dit logboek mag de run nooit breken
            logger.error("LLM-aanroep kon niet in het logboek (llm_calls) worden vastgelegd: %s: %s", type(e).__name__, e)

    def _create(self, **kwargs):
        nu = self._nu()
        tot_nu = maandverbruik(self._conn, nu).kosten_usd
        if tot_nu >= self.max_maandbedrag:
            raise BudgetExceeded(
                f"maandgrens voor LLM-kosten bereikt: ${tot_nu:.2f} van ${self.max_maandbedrag:.2f} "
                f"deze maand ({MAX_MAANDBEDRAG_ENV}); er wordt niet meer aangeroepen tot de volgende maand "
                f"of tot de grens bewust is verhoogd"
            )

        kwargs = met_denkbeleid(kwargs)
        omvang = len(json.dumps(kwargs, ensure_ascii=False, default=str))
        if omvang > MAX_VERZOEK_TEKENS:
            raise VerzoekTeGroot(
                f"verzoek van {omvang:,} tekens is groter dan de grens van {MAX_VERZOEK_TEKENS:,}; niet verstuurd. "
                f"Waarschijnlijk stuurt een agent te veel claims mee (een volledige historie in plaats van de laatste "
                f"cyclus)."
            )
        try:
            antwoord = self._client.messages.create(**kwargs)
        except Exception as e:
            self._leg_aanroep_vast(nu, kwargs, fout=f"{type(e).__name__}: {e}")
            raise
        self._leg_aanroep_vast(nu, kwargs, antwoord=antwoord)

        model = kwargs.get("model") or getattr(antwoord, "model", None) or "onbekend"
        gebruik = getattr(antwoord, "usage", None)
        tin = int(getattr(gebruik, "input_tokens", 0) or 0)
        tuit = int(getattr(gebruik, "output_tokens", 0) or 0)
        kosten, notitie = kosten_usd(model, tin, tuit)
        record_llm_usage(self._conn, nu, model, tin, tuit, kosten, notitie)

        self.aanroepen_deze_run += 1
        self.kosten_deze_run += kosten
        nieuw_totaal = tot_nu + kosten
        logger.info(
            "LLM-aanroep %s: %d in, %d uit, ~$%.4f (maand tot nu ~$%.2f van $%.0f)",
            model, tin, tuit, kosten, nieuw_totaal, self.max_maandbedrag,
        )
        if nieuw_totaal >= self.max_maandbedrag * WAARSCHUWING_VANAF:
            logger.warning(
                "LLM-kosten deze maand ~$%.2f, %.0f%% van de grens van $%.0f",
                nieuw_totaal, 100 * nieuw_totaal / self.max_maandbedrag, self.max_maandbedrag,
            )
        if not tin and not tuit:
            logger.warning("LLM-aanroep %s gaf geen tokenverbruik terug; kosten onbekend geteld als $0", model)
        return antwoord

    def samenvatting(self) -> str:
        m = maandverbruik(self._conn, self._nu())
        return (
            f"LLM-verbruik: deze run {self.aanroepen_deze_run} aanroep(en) ~${self.kosten_deze_run:.4f}; "
            f"deze maand {m.aanroepen} aanroepen, {m.input_tokens} in / {m.output_tokens} uit, "
            f"~${m.kosten_usd:.2f} van ${self.max_maandbedrag:.0f}"
        )
