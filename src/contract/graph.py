"""
graph.py
De causale graaf v0 als machine-leesbaar contract -- roadmap 1.10. De
leesbare, beargumenteerde versie staat in `docs/causal-graph.md`; dit
bestand is diezelfde graaf in een vorm waar code op kan controleren.

Waarom een enum en geen vrije strings: vanaf cohort v1 draagt elke
prediction een `graph_node` (roadmap 4.1). Een typefout in die kolom zou
stilzwijgend een knoop uit de scoring laten vallen -- dezelfde reden
waarom domain_ontology.py::classify_domain() bij een onbekend domain
hard faalt in plaats van een lege lijst terug te geven.

DRIE LAGEN (zie docs/causal-graph.md). Alleen laag 2 staat hier:
  laag 1  observaties   CPI, NFCI, VIX, DGS10, ... -- dat zijn metric_keys
                        in claims, geen knopen
  laag 2  toestanden    de 17 Node-waarden hieronder
  laag 3  outputs       sectorrotatie, instrumentvoorspellingen, synthese

BEWUST NIET hier: kansen, gewichten, of regime-afhankelijke tekens. De
graaf legt structuur vast, geen parameters -- die komen pas uit gescoorde
data (roadmap 3.4), en met ~10-15 macrocycli in bruikbare historie zouden
geschatte pijlgewichten jarenlang prior-gedomineerd blijven.

BEWUST GEEN DAG: de graaf bevat feedbacklussen (financiele stress,
vermogenseffect). Dat is geen modelleerfout maar het punt -- zie
find_cycles() en de waarschuwing bij Verifiability.NONE.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

GRAPH_VERSION = "v0"
"""Semi-bevroren vanaf T0-b (10-11-2026). Elke wijziging hierna verhoogt
dit nummer en start effectief een nieuw cohort in de scoring (roadmap
4.5). Zie de versietabel onderaan docs/causal-graph.md."""


class Node(str, Enum):
    """De 17 toestandsknopen. Een knoop is een CONCEPT dat we schatten uit
    meerdere observaties, nooit een reeks: `inflation_persistence` wordt
    geschat uit core CPI en core PCE samen, maar CPILFESL zelf is geen
    knoop."""

    GROWTH = "growth"
    LABOR_TIGHTNESS = "labor_tightness"
    WAGE_GROWTH = "wage_growth"
    INFLATION_PERSISTENCE = "inflation_persistence"
    INFLATION_EXPECTATIONS = "inflation_expectations"
    POLICY_STANCE = "policy_stance"
    POLICY_EXPECTATIONS = "policy_expectations"
    LIQUIDITY = "liquidity"
    TERM_PREMIUM = "term_premium"
    FINANCIAL_CONDITIONS = "financial_conditions"
    CREDIT_RISK_PREMIUM = "credit_risk_premium"
    RISK_APPETITE = "risk_appetite"
    DOLLAR = "dollar"
    ENERGY_PRICES = "energy_prices"
    INDUSTRIAL_METALS = "industrial_metals"
    EARNINGS_GROWTH = "earnings_growth"
    EQUITY_VALUATION = "equity_valuation"


class Sign(str, Enum):
    """Richting van de pijl, t.o.v. de "hoog betekent"-definitie van BEIDE
    knopen (die staan in de knopentabel van docs/causal-graph.md). Zonder
    die definitie is een teken betekenisloos."""

    POSITIVE = "+"
    NEGATIVE = "-"
    CONTESTED = "?"


class Strength(str, Enum):
    """Onze eigen inschatting van hoe hard de pijl doorwerkt."""

    WEAK = "weak"
    MEDIUM = "medium"
    STRONG = "strong"


class Certainty(str, Enum):
    """Onze eigen zekerheid DAT de pijl bestaat -- los van zijn sterkte.
    Bewust ordinaal en niet numeriek: een confidence van 0,85 suggereert
    een precisie die er niet is. "Laag" invullen is geen zwakte maar
    informatie: dit worden de plekken waar de data straks iets zegt."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Verifiability(str, Enum):
    """Of de pijl betekenisvol te toetsen is op de back-fill met een
    lead-lag-correlatie (roadmap 1.10). Dit veld bestaat omdat de toets
    anders nepresultaten oplevert die als bevestiging gelezen worden.

    FULL  te toetsen; een uitslag telt.
    WEAK  de toets draait, maar met ~12 onafhankelijke macro-episodes is
          een niet-significante uitslag GEEN bewijs tegen de pijl. Alleen
          een uitslag met het VERKEERDE TEKEN is informatief.
    NONE  niet te toetsen. Drie oorzaken, alle drie structureel:
          definitie-overlap (de NFCI bevat kredietspreads, VIX en
          aandelenkoersen als componenten, dus correleert die deels met
          zichzelf), feedbackrichting (in een lus correleren A en B op
          elke lag, dus is de richting niet te identificeren), en
          gelijktijdigheid (binnen uren; op dagdata geen lead-lag).
    """

    FULL = "full"
    WEAK = "weak"
    NONE = "none"


@dataclass(frozen=True)
class Edge:
    """Een pijl. `lag_days_min`/`lag_days_max` is het venster waarin de
    lead-lag-toets moet kijken -- bewust in dagen en niet in "kwartalen",
    zodat de toets er direct op kan rekenen zonder te interpreteren.

    `note` is verplicht bij CONTESTED of Verifiability.NONE: als een pijl
    niet te toetsen is of zijn teken omstreden is, moet de reden in de
    graaf staan en niet alleen in het hoofd van wie hem tekende."""

    source: Node
    target: Node
    sign: Sign
    lag_days_min: int
    lag_days_max: int
    strength: Strength
    certainty: Certainty
    verifiability: Verifiability
    note: str = ""

    def __post_init__(self) -> None:
        if self.source == self.target:
            raise ValueError(f"Pijl naar zichzelf: {self.source.value}")
        if self.lag_days_min < 0:
            raise ValueError(
                f"Negatieve vertraging op {self.source.value}->{self.target.value}"
            )
        if self.lag_days_min > self.lag_days_max:
            raise ValueError(
                f"lag_days_min > lag_days_max op "
                f"{self.source.value}->{self.target.value}"
            )
        if not self.note and (
            self.sign is Sign.CONTESTED or self.verifiability is Verifiability.NONE
        ):
            raise ValueError(
                f"Pijl {self.source.value}->{self.target.value} is omstreden of "
                f"niet-toetsbaar en heeft daarom een toelichting nodig"
            )


_WEEK = 7
_MONTH = 30
_QUARTER = 91
_YEAR = 365


EDGES: tuple[Edge, ...] = (
    # --- A. Reele economie ---
    Edge(Node.GROWTH, Node.LABOR_TIGHTNESS, Sign.POSITIVE,
         _MONTH, 6 * _MONTH, Strength.STRONG, Certainty.HIGH, Verifiability.FULL),
    Edge(Node.LABOR_TIGHTNESS, Node.WAGE_GROWTH, Sign.POSITIVE,
         _QUARTER, _YEAR, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.FULL),
    Edge(Node.WAGE_GROWTH, Node.INFLATION_PERSISTENCE, Sign.POSITIVE,
         2 * _QUARTER, 4 * _QUARTER, Strength.MEDIUM, Certainty.MEDIUM,
         Verifiability.WEAK),
    Edge(Node.GROWTH, Node.INFLATION_PERSISTENCE, Sign.POSITIVE,
         2 * _QUARTER, 4 * _QUARTER, Strength.MEDIUM, Certainty.MEDIUM,
         Verifiability.WEAK,
         note="Sterker bij een positieve output gap; conditioneel."),
    Edge(Node.FINANCIAL_CONDITIONS, Node.GROWTH, Sign.NEGATIVE,
         2 * _QUARTER, 6 * _QUARTER, Strength.STRONG, Certainty.HIGH,
         Verifiability.WEAK),
    Edge(Node.FINANCIAL_CONDITIONS, Node.LABOR_TIGHTNESS, Sign.NEGATIVE,
         2 * _QUARTER, 4 * _QUARTER, Strength.MEDIUM, Certainty.MEDIUM,
         Verifiability.WEAK),

    # --- B. Inflatie en de beleidsreactie ---
    Edge(Node.INFLATION_PERSISTENCE, Node.POLICY_STANCE, Sign.POSITIVE,
         _MONTH, _QUARTER, Strength.STRONG, Certainty.HIGH, Verifiability.FULL),
    Edge(Node.INFLATION_EXPECTATIONS, Node.POLICY_STANCE, Sign.POSITIVE,
         _MONTH, _QUARTER, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.FULL),
    Edge(Node.INFLATION_PERSISTENCE, Node.INFLATION_EXPECTATIONS, Sign.POSITIVE,
         _MONTH, 6 * _MONTH, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.FULL),
    Edge(Node.LABOR_TIGHTNESS, Node.POLICY_STANCE, Sign.POSITIVE,
         _MONTH, _QUARTER, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.FULL,
         note="Dual mandate; UNRATE zit al in de Taylor Rule (1.8/analysis)."),
    Edge(Node.ENERGY_PRICES, Node.INFLATION_EXPECTATIONS, Sign.POSITIVE,
         0, _QUARTER, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.FULL),

    # --- C. Beleid naar markten ---
    Edge(Node.POLICY_STANCE, Node.POLICY_EXPECTATIONS, Sign.POSITIVE,
         0, _WEEK, Strength.STRONG, Certainty.HIGH, Verifiability.NONE,
         note="Gelijktijdig (uren). Op dagdata geen lead-lag; alleen via een "
              "event-study rond FOMC-data te onderzoeken, en dat is post-T0."),
    Edge(Node.POLICY_STANCE, Node.FINANCIAL_CONDITIONS, Sign.POSITIVE,
         0, 4 * _WEEK, Strength.STRONG, Certainty.HIGH, Verifiability.WEAK),
    Edge(Node.POLICY_EXPECTATIONS, Node.FINANCIAL_CONDITIONS, Sign.POSITIVE,
         0, 2 * _WEEK, Strength.STRONG, Certainty.HIGH, Verifiability.WEAK,
         note="De markt wacht niet op de Fed; DGS2 loopt vooruit op de NFCI."),
    Edge(Node.POLICY_STANCE, Node.LIQUIDITY, Sign.NEGATIVE,
         _QUARTER, 2 * _QUARTER, Strength.MEDIUM, Certainty.LOW, Verifiability.FULL,
         note="Alleen actief als het balansbeleid meebeweegt; QT is niet "
              "hetzelfde als rentebeleid."),
    Edge(Node.POLICY_STANCE, Node.DOLLAR, Sign.POSITIVE,
         0, 4 * _WEEK, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.WEAK),
    Edge(Node.POLICY_EXPECTATIONS, Node.DOLLAR, Sign.POSITIVE,
         0, 2 * _WEEK, Strength.STRONG, Certainty.MEDIUM, Verifiability.WEAK),

    # --- D. Financiele condities, krediet en risico ---
    Edge(Node.LIQUIDITY, Node.FINANCIAL_CONDITIONS, Sign.NEGATIVE,
         _MONTH, _QUARTER, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.FULL),
    Edge(Node.LIQUIDITY, Node.RISK_APPETITE, Sign.POSITIVE,
         _MONTH, _QUARTER, Strength.MEDIUM, Certainty.LOW, Verifiability.FULL),
    Edge(Node.TERM_PREMIUM, Node.FINANCIAL_CONDITIONS, Sign.POSITIVE,
         0, 4 * _WEEK, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.NONE,
         note="Definitie-overlap: lange rentes zitten in de NFCI."),
    Edge(Node.TERM_PREMIUM, Node.EQUITY_VALUATION, Sign.NEGATIVE,
         0, 4 * _WEEK, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.WEAK),
    Edge(Node.CREDIT_RISK_PREMIUM, Node.FINANCIAL_CONDITIONS, Sign.POSITIVE,
         0, 2 * _WEEK, Strength.STRONG, Certainty.HIGH, Verifiability.NONE,
         note="Definitie-overlap: de HY OAS is zelf een NFCI-component."),
    Edge(Node.FINANCIAL_CONDITIONS, Node.CREDIT_RISK_PREMIUM, Sign.POSITIVE,
         0, 4 * _WEEK, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.NONE,
         note="Feedbackrichting binnen lus 2; richting niet identificeerbaar."),
    Edge(Node.FINANCIAL_CONDITIONS, Node.RISK_APPETITE, Sign.NEGATIVE,
         0, 2 * _WEEK, Strength.STRONG, Certainty.HIGH, Verifiability.NONE,
         note="Definitie-overlap: VIX en spreads zitten in beide knopen."),
    Edge(Node.RISK_APPETITE, Node.FINANCIAL_CONDITIONS, Sign.NEGATIVE,
         0, 2 * _WEEK, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.NONE,
         note="Feedbackrichting binnen lus 2."),
    Edge(Node.RISK_APPETITE, Node.CREDIT_RISK_PREMIUM, Sign.NEGATIVE,
         0, 2 * _WEEK, Strength.STRONG, Certainty.MEDIUM, Verifiability.NONE,
         note="Definitie-overlap: VIX en HY OAS delen een risicocomponent."),

    # --- E. Dollar, grondstoffen en groei ---
    Edge(Node.DOLLAR, Node.ENERGY_PRICES, Sign.NEGATIVE,
         0, _QUARTER, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.FULL),
    Edge(Node.DOLLAR, Node.INDUSTRIAL_METALS, Sign.NEGATIVE,
         0, _QUARTER, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.FULL),
    Edge(Node.DOLLAR, Node.FINANCIAL_CONDITIONS, Sign.POSITIVE,
         0, 4 * _WEEK, Strength.MEDIUM, Certainty.LOW, Verifiability.WEAK,
         note="Werkt vooral buiten de VS; onze NFCI meet de VS."),
    Edge(Node.GROWTH, Node.INDUSTRIAL_METALS, Sign.POSITIVE,
         0, 2 * _QUARTER, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.FULL,
         note="Koper als vraagsensor, niet als inflatiesignaal."),
    Edge(Node.FINANCIAL_CONDITIONS, Node.INDUSTRIAL_METALS, Sign.NEGATIVE,
         _QUARTER, 3 * _QUARTER, Strength.MEDIUM, Certainty.LOW, Verifiability.WEAK),
    Edge(Node.ENERGY_PRICES, Node.INFLATION_PERSISTENCE, Sign.POSITIVE,
         _QUARTER, 3 * _QUARTER, Strength.WEAK, Certainty.LOW, Verifiability.WEAK,
         note="ALLEEN tweede-ronde-effecten: inflation_persistence wordt "
              "geschat uit CORE CPI/PCE, en core sluit energie per definitie "
              "uit. Op headline getoetst is de uitslag opnieuw definitie."),
    Edge(Node.INDUSTRIAL_METALS, Node.INFLATION_PERSISTENCE, Sign.POSITIVE,
         2 * _QUARTER, 4 * _QUARTER, Strength.WEAK, Certainty.LOW,
         Verifiability.WEAK),

    # --- F. Bedrijven en aandelen ---
    Edge(Node.GROWTH, Node.EARNINGS_GROWTH, Sign.POSITIVE,
         _QUARTER, 2 * _QUARTER, Strength.STRONG, Certainty.HIGH, Verifiability.FULL),
    Edge(Node.FINANCIAL_CONDITIONS, Node.EARNINGS_GROWTH, Sign.NEGATIVE,
         2 * _QUARTER, 4 * _QUARTER, Strength.MEDIUM, Certainty.MEDIUM,
         Verifiability.WEAK),
    Edge(Node.EARNINGS_GROWTH, Node.EQUITY_VALUATION, Sign.POSITIVE,
         0, _QUARTER, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.WEAK),
    Edge(Node.FINANCIAL_CONDITIONS, Node.EQUITY_VALUATION, Sign.NEGATIVE,
         0, _QUARTER, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.WEAK),
    Edge(Node.RISK_APPETITE, Node.EQUITY_VALUATION, Sign.POSITIVE,
         0, 2 * _WEEK, Strength.STRONG, Certainty.MEDIUM, Verifiability.NONE,
         note="Definitie-overlap: aandelenkoersen zitten in beide knopen."),
    Edge(Node.EQUITY_VALUATION, Node.RISK_APPETITE, Sign.POSITIVE,
         0, 2 * _WEEK, Strength.MEDIUM, Certainty.LOW, Verifiability.NONE,
         note="Feedbackrichting binnen lus 3."),
    Edge(Node.EQUITY_VALUATION, Node.FINANCIAL_CONDITIONS, Sign.NEGATIVE,
         0, 4 * _WEEK, Strength.MEDIUM, Certainty.MEDIUM, Verifiability.NONE,
         note="Definitie-overlap: aandelenkoersen zijn een NFCI-component."),
    Edge(Node.ENERGY_PRICES, Node.EARNINGS_GROWTH, Sign.CONTESTED,
         _QUARTER, 2 * _QUARTER, Strength.WEAK, Certainty.LOW, Verifiability.WEAK,
         note="Positief voor de energiesector, negatief voor de rest. Netto "
              "teken omstreden; hoort waarschijnlijk in laag 3 (sector agent) "
              "in plaats van op indexniveau. Zie Open punten."),
)


NODE_OWNER: dict[Node, str] = {
    Node.GROWTH: "economic",
    Node.LABOR_TIGHTNESS: "economic",
    Node.WAGE_GROWTH: "economic",
    Node.INFLATION_PERSISTENCE: "economic",
    Node.INFLATION_EXPECTATIONS: "monetary_policy",
    Node.POLICY_STANCE: "monetary_policy",
    Node.POLICY_EXPECTATIONS: "monetary_policy",
    Node.LIQUIDITY: "monetary_policy",
    Node.TERM_PREMIUM: "monetary_policy",
    Node.FINANCIAL_CONDITIONS: "financial",
    Node.CREDIT_RISK_PREMIUM: "financial",
    Node.RISK_APPETITE: "financial",
    Node.DOLLAR: "currency",
    Node.ENERGY_PRICES: "commodity",
    Node.INDUSTRIAL_METALS: "commodity",
    Node.EARNINGS_GROWTH: "equity",
    Node.EQUITY_VALUATION: "equity",
}
"""Elke knoop heeft precies EEN primaire eigenaar; andere agents mogen hem
lezen. Zonder die regel schatten vijf agents dezelfde toestand onafhankelijk
en komen er vijf verschillende getallen uit -- precies de
vrijzwevende-analyse die de graaf moet voorkomen.

De sector agent staat hier bewust niet in: die bedient geen knoop maar
interpreteert de toestand cross-sectioneel (laag 3)."""


def parents(node: Node) -> tuple[Edge, ...]:
    """Pijlen die op `node` binnenkomen -- welke toestanden deze knoop
    beinvloeden."""
    return tuple(e for e in EDGES if e.target is node)


def children(node: Node) -> tuple[Edge, ...]:
    """Pijlen die uit `node` vertrekken -- wat deze toestand veroorzaakt."""
    return tuple(e for e in EDGES if e.source is node)


def edges_by_verifiability(verifiability: Verifiability) -> tuple[Edge, ...]:
    """De pijlen in een toetsbaarheidsklasse. De back-fill-toets uit roadmap
    1.10 draait op FULL en WEAK; bij WEAK is alleen een uitslag met het
    verkeerde teken informatief, en NONE wordt nooit als bevestigd geteld."""
    return tuple(e for e in EDGES if e.verifiability is verifiability)


def nodes_for_agent(domain: str) -> tuple[Node, ...]:
    """De knopen waarvan `domain` de primaire eigenaar is. Geeft een lege
    tuple voor een agent die geen knoop bedient (de sector agent) -- dat is
    geen fout, dus geen ValueError zoals in classify_domain()."""
    return tuple(n for n, owner in NODE_OWNER.items() if owner == domain)


def find_cycles() -> tuple[tuple[Node, ...], ...]:
    """Alle elementaire cykels in de graaf. Bestaat NIET om ze op te ruimen:
    de feedbacklussen zijn het interessantste deel van het model (zie
    docs/causal-graph.md, "De vier feedbacklussen"). Het bestaat om ze
    expliciet te kunnen opsommen, want in een lus is de richting niet uit
    correlatie af te leiden -- daarom staat elke tegenpijl in een lus op
    Verifiability.NONE.

    Elke cykel wordt genormaliseerd (laagste knoopnaam vooraan) zodat
    dezelfde lus niet meerdere keren met een andere startknoop terugkomt.
    """
    adjacency: dict[Node, list[Node]] = {n: [] for n in Node}
    for edge in EDGES:
        adjacency[edge.source].append(edge.target)

    found: set[tuple[Node, ...]] = set()

    def walk(start: Node, current: Node, path: list[Node]) -> None:
        for nxt in adjacency[current]:
            if nxt is start:
                found.add(_normalise_cycle(path))
            elif nxt not in path and nxt.value > start.value:
                walk(start, nxt, [*path, nxt])

    for node in Node:
        walk(node, node, [node])

    return tuple(sorted(found, key=lambda c: (len(c), [n.value for n in c])))


def _normalise_cycle(path: list[Node]) -> tuple[Node, ...]:
    """Roteert een cykel zodat de alfabetisch laagste knoop vooraan staat."""
    lowest = min(range(len(path)), key=lambda i: path[i].value)
    return tuple(path[lowest:] + path[:lowest])


def validate_graph() -> None:
    """Integriteitscheck op de graaf zelf. Draait in de testsuite, niet op
    elke import -- de graaf is een constante, dus een fout hierin is een
    programmeerfout die bij het schrijven zichtbaar moet worden, niet iets
    dat pas op de VPS om 6 uur 's ochtends opvalt.

    Fail loud (ValueError), zelfde precedent als output_contract.py."""
    seen: set[tuple[Node, Node]] = set()
    for edge in EDGES:
        key = (edge.source, edge.target)
        if key in seen:
            raise ValueError(
                f"Dubbele pijl {edge.source.value}->{edge.target.value}"
            )
        seen.add(key)

    for node in Node:
        if node not in NODE_OWNER:
            raise ValueError(f"Knoop zonder primaire eigenaar: {node.value}")
        if not parents(node) and not children(node):
            raise ValueError(
                f"Losse knoop zonder enige pijl: {node.value} -- een knoop "
                f"zonder gevolgen is decoratie, geen model"
            )
