"""
test_graph_mapping.py
Bewaakt de brug tussen de agents en de causale graaf (roadmap 1.10 -> 4.1):
elke opgehaalde reeks declareert welke toestand hij helpt schatten.

WAAROM DIT BESTAAT. Op 28-09-2026 bezat de monetary agent vijf graafknopen
en kon hij er één meten -- policy_expectations, inflation_expectations en
liquidity stonden op zijn naam zonder dat er een reeks voor werd opgehaald.
Dat is met de hand gevonden door de graaf naast de agents te leggen. Dit
bestand maakt er een test van, zodat het de volgende keer vanzelf opvalt.

De urgentie zit in de klok: een gat dat je in maand drie van de meetperiode
ontdekt, betekent drie maanden blinde data op die knoop, en een forward test
is niet met terugwerkende kracht aan te vullen.
"""

from __future__ import annotations

import pytest

from agents import (
    commodity_agent,
    currency_agent,
    economic_agent,
    equity_agent,
    financial_agent,
    monetary_policy_agent,
    sector_agent,
)
from contract.graph import (
    Node,
    nodes_for_agent,
    unserved_owned_nodes,
    validate_agent_mapping,
)

# (domein, module, de metric-specs van die module)
AGENTS = [
    ("monetary_policy", monetary_policy_agent, monetary_policy_agent.METRIC_SPECS),
    ("currency", currency_agent, currency_agent.METRIC_SPECS),
    ("financial", financial_agent, financial_agent.METRIC_SPECS),
    ("sector", sector_agent, sector_agent.METRIC_SPECS),
    ("commodity", commodity_agent, commodity_agent.METRIC_SPECS),
    ("economic", economic_agent, economic_agent.METRIC_SPECS),
    ("equity", equity_agent, equity_agent.EQUITY_METRIC_SPECS),
]


@pytest.mark.parametrize("domain,module,specs", AGENTS, ids=[a[0] for a in AGENTS])
def test_elke_reeks_declareert_een_knoop_of_expliciet_geen(domain, module, specs):
    """Het correcte geval: mapping en metric_specs dekken elkaar precies.

    Een reeks ophalen zonder te beslissen welke toestand hij schat, is hoe je
    ongemerkt een dashboard bouwt in plaats van een model. `None` is een
    geldig antwoord -- maar dan staat het er wel."""
    validate_agent_mapping(domain, module.GRAPH_MAPPING, specs.keys())


@pytest.mark.parametrize("domain,module,specs", AGENTS, ids=[a[0] for a in AGENTS])
def test_ontbrekende_mapping_wordt_geweigerd(domain, module, specs):
    """REGRESSIE. Voeg je een reeks toe en vergeet je de mapping, dan hoort
    dat hard te falen -- niet stilzwijgend door te gaan."""
    with pytest.raises(ValueError, match="zonder mapping"):
        validate_agent_mapping(domain, module.GRAPH_MAPPING, [*specs, "nieuwe_reeks"])


def test_onbekende_metric_in_de_mapping_wordt_geweigerd():
    """REGRESSIE op de andere kant: een hernoemde reeks waarvan de oude
    mapping-regel is blijven staan."""
    with pytest.raises(ValueError, match="niet-bestaande metric_keys"):
        validate_agent_mapping("economic", {"verdwenen_reeks": Node.GROWTH}, [])


# --- Welke knopen nog onbediend zijn: vastgelegd, niet weggemoffeld ---


def test_monetary_dekt_al_zijn_knopen():
    """Dit is het gat dat op 28-09-2026 gevonden en gedicht werd. Valt deze
    test om, dan is er een reeks verdwenen en meet de agent een knoop die hij
    volgens de graaf wel bezit niet meer."""
    assert unserved_owned_nodes("monetary_policy", monetary_policy_agent.GRAPH_MAPPING) == ()


def test_financial_dekt_al_zijn_knopen():
    assert unserved_owned_nodes("financial", financial_agent.GRAPH_MAPPING) == ()


def test_currency_en_commodity_dekken_al_hun_knopen():
    assert unserved_owned_nodes("currency", currency_agent.GRAPH_MAPPING) == ()
    assert unserved_owned_nodes("commodity", commodity_agent.GRAPH_MAPPING) == ()


def test_economic_mist_bewust_twee_knopen():
    """De lean versie (roadmap 2.7) dekt `growth` en `labor_tightness`.
    `wage_growth` vraagt AHETPI/ECI en `inflation_persistence` vraagt core
    PCE -- allebei post-T₀, een vastgelegde grens.

    Deze test legt die grens vast in plaats van hem te laten wegzakken:
    worden ze ooit gedicht, dan faalt hij en wordt de wijziging zichtbaar
    gemaakt in dezelfde ronde."""
    assert set(unserved_owned_nodes("economic", economic_agent.GRAPH_MAPPING)) == {
        Node.WAGE_GROWTH,
        Node.INFLATION_PERSISTENCE,
    }


def test_equity_mist_bewust_de_waarderingsknoop():
    """`equity_valuation` vraagt een index-brede earnings yield; de adapter
    levert fundamentals per ticker. Equity valt sowieso buiten cohort 0, dus
    geen blokkade voor T₀."""
    assert unserved_owned_nodes("equity", equity_agent.GRAPH_MAPPING) == (Node.EQUITY_VALUATION,)


def test_sector_bezit_geen_knopen_en_mapt_dus_naar_niets():
    """Sectorrotatie is een output (laag 3), geen toestand. De agent
    interpreteert de toestand cross-sectioneel; zou je de elf ETF's als
    knopen opnemen, dan krijg je een graaf waarin alle pijlen binnenkomen en
    geen enkele vertrekt."""
    assert nodes_for_agent("sector") == ()
    assert set(sector_agent.GRAPH_MAPPING.values()) == {None}


# --- Dekking over het geheel ---


def test_elke_knoop_met_een_eigenaar_is_te_herleiden_tot_een_agent():
    """Elke van de 17 knopen hoort bij precies één agent, en die agent is een
    van de zeven hierboven. Een knoop die naar een niet-bestaande agent
    verwijst zou nooit bediend worden zonder dat iemand het merkt."""
    bekende_domeinen = {domain for domain, _, _ in AGENTS}
    for node in Node:
        eigenaren = [d for d in bekende_domeinen if node in nodes_for_agent(d)]
        assert len(eigenaren) == 1, f"{node.value} heeft eigenaren {eigenaren}"


def test_alle_onbediende_knopen_staan_hierboven_vastgelegd():
    """Overzicht over alle agents heen: precies drie van de 17 knopen worden
    op dit moment door geen enkele waarneming gevoed. Groeit dat getal, dan
    is er ergens een reeks weggevallen; krimpt het, dan is een gat gedicht en
    hoort de bijbehorende test hierboven in dezelfde ronde bijgewerkt te
    worden."""
    onbediend = set()
    for domain, module, _ in AGENTS:
        onbediend |= set(unserved_owned_nodes(domain, module.GRAPH_MAPPING))

    assert onbediend == {
        Node.WAGE_GROWTH,
        Node.INFLATION_PERSISTENCE,
        Node.EQUITY_VALUATION,
    }
