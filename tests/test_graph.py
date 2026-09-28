"""
test_graph.py
Tests voor de causale graaf v0 (roadmap 1.10, src/contract/graph.py).

Patroon zoals de rest van tests/: per onderdeel een "correct"-geval en,
waar er een echt bugpatroon te beschermen valt, een regressiegeval. De
regressiegevallen hier beschermen twee dingen die makkelijk per ongeluk
"gerepareerd" worden:

1. de niet-toetsbare pijlen (definitie-overlap) -- wie die op FULL zet,
   laat de back-fill-toets een getal met zichzelf correleren en leest de
   uitslag als bevestiging;
2. het bestaan van feedbacklussen -- wie de graaf tot een DAG "opschoont",
   gooit precies het interessantste deel van het model weg.
"""

from __future__ import annotations

import pytest

from src.contract.graph import (
    EDGES,
    GRAPH_VERSION,
    NODE_OWNER,
    Certainty,
    Edge,
    Node,
    Sign,
    Strength,
    Verifiability,
    children,
    edges_by_verifiability,
    find_cycles,
    nodes_for_agent,
    parents,
    validate_graph,
)


# --- De graaf zelf ---


def test_graaf_is_integer():
    """Het correcte geval: de vastgelegde v0-graaf doorstaat zijn eigen
    integriteitscheck (geen dubbele pijlen, elke knoop heeft een eigenaar,
    geen losse knopen)."""
    validate_graph()


def test_v0_heeft_17_knopen_en_41_pijlen():
    """De omvang is een bewuste keuze, geen toeval: 17 knopen zit binnen de
    15-25 uit roadmap 1.10, en 41 pijlen blijft onder het budget van ~5x het
    aantal macrocycli (~60). Groeit dit ongemerkt, dan groeit het aantal
    valse treffers in de back-fill-toets mee."""
    assert len(Node) == 17
    assert len(EDGES) == 41
    assert GRAPH_VERSION == "v0"


def test_elke_knoop_heeft_precies_een_eigenaar():
    assert set(NODE_OWNER) == set(Node)
    assert len(NODE_OWNER) == len(Node)


def test_elke_knoop_hangt_aan_minstens_een_pijl():
    """Een knoop zonder pijlen is decoratie -- zie de toets in
    validate_graph()."""
    for node in Node:
        assert parents(node) or children(node), node.value


# --- Eigenaarschap per agent ---


def test_knopen_per_agent():
    assert nodes_for_agent("economic") == (
        Node.GROWTH,
        Node.LABOR_TIGHTNESS,
        Node.WAGE_GROWTH,
        Node.INFLATION_PERSISTENCE,
    )
    assert nodes_for_agent("financial") == (
        Node.FINANCIAL_CONDITIONS,
        Node.CREDIT_RISK_PREMIUM,
        Node.RISK_APPETITE,
    )
    assert nodes_for_agent("currency") == (Node.DOLLAR,)


def test_sector_agent_bedient_geen_knoop():
    """De sector agent interpreteert de toestand cross-sectioneel (laag 3) en
    bedient bewust geen eigen knoop -- sectorrotatie is een output, geen
    oorzaak. Een lege tuple is hier het juiste antwoord, geen ValueError."""
    assert nodes_for_agent("sector") == ()


# --- Toetsbaarheid: het regressiegeval ---


def test_definitie_overlap_pijlen_blijven_niet_toetsbaar():
    """REGRESSIE. De NFCI bevat kredietspreads, VIX en aandelenkoersen als
    componenten. Een lead-lag-toets tussen credit_risk_premium en
    financial_conditions meet daarom grotendeels dat een getal met zichzelf
    correleert: een schitterende, betekenisloze uitslag.

    Wie deze pijlen op FULL zet omdat "de correlatie toch hoog is", voert
    precies die fout in. Ze blijven in de graaf staan (ze kloppen
    conceptueel) maar tellen nooit als bevestigd."""
    overlappend = {
        (Node.CREDIT_RISK_PREMIUM, Node.FINANCIAL_CONDITIONS),
        (Node.FINANCIAL_CONDITIONS, Node.RISK_APPETITE),
        (Node.RISK_APPETITE, Node.CREDIT_RISK_PREMIUM),
        (Node.TERM_PREMIUM, Node.FINANCIAL_CONDITIONS),
        (Node.RISK_APPETITE, Node.EQUITY_VALUATION),
        (Node.EQUITY_VALUATION, Node.FINANCIAL_CONDITIONS),
    }
    for edge in EDGES:
        if (edge.source, edge.target) in overlappend:
            assert edge.verifiability is Verifiability.NONE, (
                f"{edge.source.value}->{edge.target.value} is definitie-overlap "
                f"en mag nooit als toetsbaar gelden"
            )


def test_verdeling_over_toetsbaarheidsklassen():
    """Van de 41 pijlen zijn er 14 volwaardig toetsbaar, 17 zwak en 10 niet.
    Dat is geen tekortkoming van de graaf maar van wat data over een economie
    kan zeggen -- het staat hier vast zodat het niet ongemerkt verschuift."""
    assert len(edges_by_verifiability(Verifiability.FULL)) == 14
    assert len(edges_by_verifiability(Verifiability.WEAK)) == 17
    assert len(edges_by_verifiability(Verifiability.NONE)) == 10


def test_niet_toetsbare_en_omstreden_pijlen_hebben_een_toelichting():
    for edge in EDGES:
        if edge.verifiability is Verifiability.NONE or edge.sign is Sign.CONTESTED:
            assert edge.note, f"{edge.source.value}->{edge.target.value}"


# --- Feedbacklussen ---


def test_graaf_is_bewust_geen_dag():
    """REGRESSIE. De lussen zijn het punt, geen modelleerfout. Wie de graaf
    tot een DAG opschoont (bijvoorbeeld om er een Bayesiaans netwerk van te
    maken) verliest de financiele-stress- en vermogenseffect-lussen, precies
    de niet-lineariteit die een lineaire macro-analyse mist."""
    assert find_cycles(), "de graaf hoort feedbacklussen te bevatten"


def test_bekende_lussen_zitten_in_de_graaf():
    """Lus 2 (financiele stress) en lus 3 (vermogenseffect) uit
    docs/causal-graph.md, in hun kortste vorm."""
    cycles = {frozenset(c) for c in find_cycles()}
    assert frozenset({Node.FINANCIAL_CONDITIONS, Node.CREDIT_RISK_PREMIUM}) in cycles
    assert frozenset({Node.FINANCIAL_CONDITIONS, Node.RISK_APPETITE}) in cycles
    assert frozenset({Node.RISK_APPETITE, Node.EQUITY_VALUATION}) in cycles


def test_elke_lus_heeft_een_niet_toetsbare_tegenpijl():
    """In een lus correleren A en B op elke lag, dus is de richting niet uit
    correlatie af te leiden. Werkregel uit docs/causal-graph.md: per
    twee-knoops-lus is minstens een van beide richtingen NONE."""
    twee_knoops = [c for c in find_cycles() if len(c) == 2]
    assert twee_knoops
    for a, b in twee_knoops:
        richtingen = [
            e for e in EDGES if {e.source, e.target} == {a, b}
        ]
        assert any(e.verifiability is Verifiability.NONE for e in richtingen), (
            f"lus {a.value}<->{b.value} heeft geen niet-toetsbare tegenpijl"
        )


# --- Edge-validatie ---


def test_pijl_naar_zichzelf_wordt_geweigerd():
    with pytest.raises(ValueError, match="naar zichzelf"):
        Edge(
            Node.GROWTH,
            Node.GROWTH,
            Sign.POSITIVE,
            0,
            30,
            Strength.MEDIUM,
            Certainty.MEDIUM,
            Verifiability.FULL,
        )


def test_omgekeerd_vertragingsvenster_wordt_geweigerd():
    with pytest.raises(ValueError, match="lag_days_min"):
        Edge(
            Node.GROWTH,
            Node.LABOR_TIGHTNESS,
            Sign.POSITIVE,
            90,
            30,
            Strength.MEDIUM,
            Certainty.MEDIUM,
            Verifiability.FULL,
        )


def test_negatieve_vertraging_wordt_geweigerd():
    with pytest.raises(ValueError, match="Negatieve vertraging"):
        Edge(
            Node.GROWTH,
            Node.LABOR_TIGHTNESS,
            Sign.POSITIVE,
            -1,
            30,
            Strength.MEDIUM,
            Certainty.MEDIUM,
            Verifiability.FULL,
        )


def test_niet_toetsbare_pijl_zonder_toelichting_wordt_geweigerd():
    """Als een pijl niet te toetsen is, moet de reden in de graaf staan en
    niet alleen in het hoofd van wie hem tekende."""
    with pytest.raises(ValueError, match="toelichting"):
        Edge(
            Node.GROWTH,
            Node.LABOR_TIGHTNESS,
            Sign.POSITIVE,
            0,
            30,
            Strength.MEDIUM,
            Certainty.MEDIUM,
            Verifiability.NONE,
        )


def test_omstreden_teken_zonder_toelichting_wordt_geweigerd():
    with pytest.raises(ValueError, match="toelichting"):
        Edge(
            Node.GROWTH,
            Node.LABOR_TIGHTNESS,
            Sign.CONTESTED,
            0,
            30,
            Strength.MEDIUM,
            Certainty.MEDIUM,
            Verifiability.WEAK,
        )


def test_dubbele_pijl_wordt_door_validate_graph_gevonden():
    """validate_graph() draait tegen de module-constante EDGES; deze test
    bewijst dat de dubbele-pijl-check echt aanslaat, met een losse graaf."""
    import src.contract.graph as graph_module

    origineel = graph_module.EDGES
    dubbel = origineel[0]
    graph_module.EDGES = (*origineel, dubbel)
    try:
        with pytest.raises(ValueError, match="Dubbele pijl"):
            validate_graph()
    finally:
        graph_module.EDGES = origineel

    validate_graph()
