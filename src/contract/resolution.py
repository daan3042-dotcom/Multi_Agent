"""
resolution.py
Hoe een voorspelling afgewikkeld wordt (roadmap 4.5).

HET PROBLEEM DAT DEZE MODULE OPLOST. Elke `Prediction` draagt een
`resolution_rule`: vrije tekst die exact beschrijft wat er gescoord wordt.
Die tekst is de AUTORITEIT -- hij staat in de database, hij wordt bevroren
bij T₀ᵇ, en hij is wat een mens leest als er straks ruzie is over een
score. Maar Python kan geen vrije tekst uitvoeren, en een LLM de regel
laten interpreteren is precies wat CLAUDE.md verbiedt ("Python rekent,
Claude vertelt") -- dan zou het model dat de voorspelling deed, ook mogen
bepalen of hij uitkwam.

Daarom draagt elke voorspelling naast de tekst een `ResolutionMethod`: een
machine-leesbare verwijzing naar een van de functies hieronder. De tekst
zegt WAT er gebeurt in mensentaal, de methode DOET het. Dat die twee bij
elkaar horen is een menselijke controle, geen automatische -- de test
`test_resolution_methods_matchen_de_regeltekst` pint per doel welke
combinatie is afgesproken, zodat een wijziging aan één van beide opvalt.

DE VINTAGE-REGEL ZIT IN DE DATA, NIET IN EEN AANNAME. Bijna elke
resolution_rule in dit systeem zegt "EERSTE print, latere revisies wijzigen
de uitkomst nooit". Dat is hier gratis: we slaan elke cyclus op wat de bron
op dat moment zei, dus onze eigen claims-historie IS een vintage-archief.
De eerste print van een periode is de claim met die `source_time` die wij
als eerste zagen (`first_seen`). Een revisie komt binnen als een nieuwe
claim met dezelfde `source_time` en een andere waarde -- die wordt hier
genegeerd, en dat is de bedoeling.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class ResolutionMethod(str, Enum):
    """De vier manieren waarop cohort 0 een voorspelling afwikkelt.

    Bewust een kleine, gesloten lijst. Elke methode erbij is een nieuwe
    manier waarop een score kan ontstaan, en dus iets dat vóór de freeze
    (fase 3b) begrepen en getest moet zijn."""

    LEVEL_AT_OR_AFTER = "level_at_or_after"
    """Het NIVEAU van de reeks op de eerste observatie op of na
    `resolves_at`. Voor dagreeksen met een handelsdagen-horizon: DGS10,
    VIX, FX-koersen. 'Op of na' en niet 'op': feestdagen en weekenden
    bestaan, en een horizon van 21 handelsdagen landt niet altijd op een
    dag waarop de bron publiceert."""

    NTH_RELEASE = "nth_release"
    """De n-de NIEUWE publicatie na `created_at`, eerste print. Voor
    week- en maandreeksen: ICSA, UNRATE, PAYEMS, NFCI. Telt periodes en
    geen dagen -- dat is het hele bestaansrecht van HorizonKind.RELEASES."""

    RELATIVE_RETURN = "relative_return"
    """Het rendement van de reeks MINUS dat van een benchmark, over
    precies dezelfde twee observatiemomenten. Voor de sector agent, die
    rotatie voorspelt en niet de markt."""

    DIRECTION_AFTER_FOMC = "direction_after_fomc"
    """Binair: ligt de reeks na de n-de FOMC-vergadering hoger dan bij
    `created_at`? Vereist een FOMC-kalender (zie FOMC_MEETING_DATES) --
    zonder die kalender is dit NIET af te wikkelen, en de resolver zegt
    dat met zoveel woorden in plaats van een benadering te verzinnen."""


FOMC_MEETING_DATES: tuple[date, ...] = (
    date(2026, 10, 28),
    date(2026, 12, 9),
    date(2027, 1, 27),
    date(2027, 3, 17),
    date(2027, 4, 28),
    date(2027, 6, 9),
    date(2027, 7, 28),
    date(2027, 9, 15),
    date(2027, 10, 27),
    date(2027, 12, 8),
)
"""De geplande FOMC-vergaderdata, in oplopende volgorde.

BRON EN CONVENTIE (ingevuld op 30-09-2026, checkpoint 4 opgelost). DD heeft de
data van de officiële pagina (federalreserve.gov/monetarypolicy/fomccalendars.htm,
"2026 FOMC Meetings" en "2027 FOMC Meetings") als screenshot aangeleverd; ik
kon die pagina zelf niet bereiken (geen uitgaand netwerk naar federalreserve.gov).
Elke datum is de BESLUITDAG: de tweede dag van de tweedaagse vergadering, altijd
een woensdag. De Fed noemt de vergaderingen "27-28 oktober" en publiceert de
rentebeslissing op de tweede dag. `tests/test_fomc_calendar.py` bewaakt dat de
datums oplopend zijn, op een woensdag vallen en aannemelijk ver uit elkaar liggen.

Elke datum is "tentative until confirmed at the meeting immediately preceding it",
zegt de Fed zelf. Een verschoven of geannuleerde vergadering vraagt dus om een
aanpassing hier; een onverwachte (niet-geplande) vergadering staat er bewust niet in.

NOG NIET AANWEZIG: de vergaderingen van vóór oktober 2026. De pseudo-OOS-run
(4.4) laat agents juli-september 2026 voorspellen en heeft daarvoor de data van
juli en september 2026 nodig. Voeg die toe zodra ze van dezelfde pagina zijn
gecontroleerd; tot dan meldt de resolver voor een voorspelling waarvan de
vergadering buiten de lijst valt per stuk waarom.

Een lege of te korte lijst maakt een voorspelling onafwikkelbaar met een reden,
en geeft nooit een benadering: de resolver zegt hoeveel vergaderingen er ontbreken.

WAAROM NIET BENADEREN met "de n-de FEDFUNDS-print": FEDFUNDS publiceert
twaalf keer per jaar, de FOMC vergadert acht keer. Die twee lopen niet
gelijk, dus zo'n benadering zou een andere gebeurtenis scoren dan de
voorspelling beschrijft -- en dat merk je nergens aan de data."""


@dataclass(frozen=True)
class Observation:
    """Eén waarneming uit de claims-historie, klaar om mee te rekenen.

    `source_time` is wat de BRON als periode opgeeft; `first_seen` is
    wanneer WIJ die waarde voor het eerst zagen. Het onderscheid is de
    vintage-regel: bij twee claims met dezelfde `source_time` telt die met
    de vroegste `first_seen`."""

    source_time: datetime
    value: float
    first_seen: datetime
    claim_id: int


@dataclass(frozen=True)
class Resolution:
    """Een afgewikkelde uitkomst, met de claims die hem opleverden.

    `claim_ids` staat er omdat elke agent-beslissing herleidbaar moet
    blijven (CLAUDE.md): welke waarneming heeft deze score veroorzaakt."""

    value: float
    realised_at: datetime
    claim_ids: tuple[int, ...]


class NotYetResolvable(Exception):
    """De data die nodig is bestaat nog niet. Opnieuw proberen heeft zin.

    Gescheiden van `Unresolvable` omdat het verschil bepaalt wat de
    resolver doet: wachten of opgeven. Die twee door elkaar halen kost
    ofwel een voorspelling die eeuwig blijft hangen, ofwel een die te
    vroeg als mislukt wordt weggeschreven."""


class Unresolvable(Exception):
    """Deze voorspelling wordt nooit meer afwikkelbaar -- ontbrekende
    kalender, ontbrekende benchmark, een gat in de reeks dat niet meer
    gevuld wordt. Opnieuw proberen heeft geen zin."""


def eerste_prints(observations: list[Observation]) -> list[Observation]:
    """Per `source_time` de waarneming die wij als eerste zagen, oplopend
    gesorteerd op periode. Dit IS de vintage-regel; elke functie hieronder
    begint hiermee."""
    per_periode: dict[datetime, Observation] = {}
    for obs in observations:
        bestaand = per_periode.get(obs.source_time)
        if bestaand is None or obs.first_seen < bestaand.first_seen:
            per_periode[obs.source_time] = obs
    return sorted(per_periode.values(), key=lambda o: o.source_time)


def level_at_or_after(observations: list[Observation], resolves_at: datetime) -> Resolution:
    """Het niveau op de eerste observatie op of na `resolves_at`.

    VERGELIJKT OP DATUM EN NIET OP TIJDSTIP, en dat is geen slordigheid.
    `resolves_at` erft het tijdstip van `created_at` -- de forecast-ronde
    draait maandagochtend, dus dat is 07:15 UTC. De `source_time` van een
    dagreeks is een kale datum (FRED geeft "2026-10-22", wij lezen dat als
    middernacht). Op tijdstip vergelijken zou de observatie van de
    afwikkeldag zelf dus stelselmatig overslaan en de volgende pakken: elke
    handelsdagen-horizon één waarneming te ver.

    Dat is precies het soort fout dat nergens zichtbaar is -- de scores
    komen binnen, ze zijn alleen van de verkeerde dag."""
    prints = eerste_prints(observations)
    if not prints:
        raise NotYetResolvable("geen enkele waarneming voor deze reeks")
    doeldatum = resolves_at.date()
    for obs in prints:
        if obs.source_time.date() >= doeldatum:
            return Resolution(obs.value, obs.source_time, (obs.claim_id,))
    raise NotYetResolvable(
        f"laatste waarneming is {prints[-1].source_time.date()}, "
        f"nog geen observatie op of na {resolves_at.date()}"
    )


def nth_release(observations: list[Observation], created_at: datetime, n: int) -> Resolution:
    """De n-de NIEUWE periode die na `created_at` is gepubliceerd.

    'Nieuw' betekent: een `source_time` die later ligt dan de laatste die
    we op het moment van voorspellen al kenden. Dat is bewust niet "een
    claim die we na created_at zagen" -- een REVISIE van een oude periode
    is ook een nieuwe claim, en die zou anders als publicatie meetellen en
    de telling laten verschuiven."""
    if n <= 0:
        raise Unresolvable(f"horizon_n moet positief zijn, was {n}")
    prints = eerste_prints(observations)
    if not prints:
        raise NotYetResolvable("geen enkele waarneming voor deze reeks")

    bekend_bij_voorspellen = [o for o in prints if o.first_seen <= created_at]
    if not bekend_bij_voorspellen:
        # De agent voorspelde zonder dat er ook maar één print in de
        # historie stond. Dan is "de volgende print" niet te bepalen
        # zonder te gokken welke periode de eerste was.
        raise Unresolvable(
            "geen enkele waarneming was bekend op het moment van voorspellen, "
            "dus 'de volgende publicatie' is niet vast te stellen"
        )
    laatste_bekende_periode = max(o.source_time for o in bekend_bij_voorspellen)

    nieuwe = [o for o in prints if o.source_time > laatste_bekende_periode]
    if len(nieuwe) < n:
        raise NotYetResolvable(
            f"{len(nieuwe)} nieuwe publicatie(s) sinds {laatste_bekende_periode.date()}, "
            f"er zijn er {n} nodig"
        )
    gekozen = nieuwe[n - 1]
    return Resolution(gekozen.value, gekozen.source_time, (gekozen.claim_id,))


def relative_return(
    observations: list[Observation],
    benchmark: list[Observation],
    created_at: datetime,
    resolves_at: datetime,
) -> Resolution:
    """Procentueel rendement van de reeks minus dat van de benchmark, over
    PRECIES dezelfde twee observatiemomenten.

    Die laatste eis is de hele reden dat deze functie bestaat en er geen
    twee losse `level_at_or_after`-aanroepen staan. Zouden de reeks en de
    benchmark op verschillende dagen gemeten worden -- bijvoorbeeld omdat
    de ETF een dag mist die SPY wel heeft -- dan zit er marktbeweging in
    het verschil die niets met rotatie te maken heeft. Dan meet je ruis en
    noemt het relatieve sterkte."""
    reeks = {o.source_time: o for o in eerste_prints(observations)}
    bench = {o.source_time: o for o in eerste_prints(benchmark)}
    if not reeks:
        raise NotYetResolvable("geen enkele waarneming voor deze reeks")
    if not bench:
        raise NotYetResolvable("geen enkele waarneming voor de benchmark")

    gedeeld = sorted(set(reeks) & set(bench))
    if not gedeeld:
        raise Unresolvable(
            "reeks en benchmark hebben geen enkel gemeenschappelijk "
            "observatiemoment -- relatief rendement is dan niet te meten"
        )

    # Het startpunt is wat we bij het VOORSPELLEN al wisten, niet wat
    # achteraf op die datum bleek te staan. Een koers die pas later is
    # binnengekomen, kon de agent niet zien; hem toch als vertrekpunt
    # gebruiken zou een rendement meten dat niemand kon voorspellen.
    startmomenten = [
        t for t in gedeeld
        if reeks[t].first_seen <= created_at and bench[t].first_seen <= created_at
    ]
    if not startmomenten:
        raise Unresolvable(
            f"geen gemeenschappelijke observatie die op {created_at.date()} al bekend was; "
            f"het startpunt van het rendement ligt niet vast"
        )
    start = startmomenten[-1]

    # Het eindpunt op DATUM, om dezelfde reden als in level_at_or_after.
    eindmomenten = [t for t in gedeeld if t.date() >= resolves_at.date()]
    if not eindmomenten:
        raise NotYetResolvable(
            f"laatste gemeenschappelijke observatie is {gedeeld[-1].date()}, "
            f"nog geen moment op of na {resolves_at.date()}"
        )
    eind = eindmomenten[0]

    if reeks[start].value == 0 or bench[start].value == 0:
        raise Unresolvable("startkoers is nul; procentueel rendement is niet gedefinieerd")

    reeks_rendement = (reeks[eind].value / reeks[start].value - 1) * 100
    bench_rendement = (bench[eind].value / bench[start].value - 1) * 100
    return Resolution(
        reeks_rendement - bench_rendement,
        eind,
        (reeks[start].claim_id, reeks[eind].claim_id, bench[start].claim_id, bench[eind].claim_id),
    )


def direction_after_fomc(
    observations: list[Observation],
    created_at: datetime,
    n: int,
    meetings: tuple[date, ...] | None = None,
) -> Resolution:
    """Binair: ligt de reeks na de n-de FOMC-vergadering hoger dan de
    laatst bekende waarde bij `created_at`? Gelijk blijven telt als NIET
    hoger -- dat staat zo in de resolution_rule van de monetary agent, en
    het is de conservatieve kant: een voorspeller die "hoger" zei krijgt
    geen punt voor niets gebeuren.

    Geeft 1.0 of 0.0 terug, zodat de binaire scores (Brier, log loss)
    dezelfde vorm zien als de kwantielscores.

    `meetings` wordt bij AANROEP uit FOMC_MEETING_DATES gelezen en niet als
    default-waarde meegebakken. Een default wordt in Python één keer
    geëvalueerd, bij het definiëren van de functie -- dan zou het vullen van
    de kalender pas na een herstart effect hebben, en dat is precies het
    soort verschil tussen test en productie dat je niet wilt."""
    meetings = FOMC_MEETING_DATES if meetings is None else meetings
    if not meetings:
        raise Unresolvable(
            "FOMC-kalender is leeg (contract/resolution.py, FOMC_MEETING_DATES). "
            "Zonder de officiële vergaderdata is niet vast te stellen wannéér "
            "deze voorspelling afloopt"
        )
    if n <= 0:
        raise Unresolvable(f"horizon_n moet positief zijn, was {n}")

    komende = [m for m in sorted(meetings) if m > created_at.date()]
    if len(komende) < n:
        raise Unresolvable(
            f"de kalender kent {len(komende)} vergadering(en) na "
            f"{created_at.date()}, er zijn er {n} nodig -- vul FOMC_MEETING_DATES aan"
        )
    vergadering = komende[n - 1]

    prints = eerste_prints(observations)
    bij_voorspellen = [o for o in prints if o.first_seen <= created_at]
    if not bij_voorspellen:
        raise Unresolvable(
            "geen waarneming bekend op het moment van voorspellen, dus er is "
            "geen vertrekpunt om 'hoger' tegen af te zetten"
        )
    vertrekpunt = max(bij_voorspellen, key=lambda o: o.source_time)

    na_vergadering = [o for o in prints if o.source_time.date() > vergadering]
    if not na_vergadering:
        raise NotYetResolvable(
            f"nog geen waarneming na de vergadering van {vergadering}"
        )
    uitkomst = na_vergadering[0]
    hoger = 1.0 if uitkomst.value > vertrekpunt.value else 0.0
    return Resolution(hoger, uitkomst.source_time, (vertrekpunt.claim_id, uitkomst.claim_id))
