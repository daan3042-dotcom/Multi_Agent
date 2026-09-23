"""
taylor_rule.py
Tweede model in analysis/ (zie nfci_interpretation.py voor het eerste en
de bredere uitleg van dit patroon). De Taylor Rule (Taylor, 1993) is een
gevestigde, veelgeciteerde formule die een "passende" nominale beleidsrente
berekent uit inflatie en de output gap. Geeft de monetary policy agent een
citeerbaar referentiepunt -- "wijkt het daadwerkelijke Fed-beleid af van
wat dit model als passend berekent" -- in plaats van alleen "het cijfer
veranderde sinds de vorige keer".

i = r* + π + 0,5(π - π*) + 0,5(output gap)

r* = 2% hieronder is een AANNAME, afgestemd met DD (zie docs/project-
state.md): de meest gangbare waarde in recente toepassingen van dit model,
niet zelf uit data afgeleid -- net als ROIC's "aanname: 25% belastingtarief"
in analyst_agent.ai's forensics.py, een expliciet gedocumenteerde
modelkeuze, geen verborgen constante. π* = 2% is GEEN aanname -- dat is de
Fed's eigen, officieel gepubliceerde inflatiedoelstelling.

Alle percentages als "gewone" getallen (5.0 voor 5%), niet als fractie --
zelfde conventie als de rest van deze codebase (FRED levert ze al zo aan).
"""

R_STAR_PCT = 2.0  # aanname, afgestemd met DD -- zie docs/project-state.md
INFLATION_TARGET_PCT = 2.0  # Fed's officiële, gepubliceerde inflatiedoel


def compute_output_gap_pct(actual_real_gdp: float, potential_real_gdp: float) -> float:
    """(actual - potential) / potential * 100 -- positief = economie draait
    boven potentieel (oververhittingssignaal), negatief = eronder."""
    return (actual_real_gdp - potential_real_gdp) / potential_real_gdp * 100


def compute_taylor_rule_rate(
    inflation_yoy_pct: float,
    output_gap_pct: float,
    r_star_pct: float = R_STAR_PCT,
    inflation_target_pct: float = INFLATION_TARGET_PCT,
) -> float:
    """i = r* + π + 0,5(π - π*) + 0,5(output gap). r_star_pct/
    inflation_target_pct zijn overrideable (bijv. voor een gevoeligheids-
    analyse), maar de module-defaults zijn de afgestemde waarden."""
    return (
        r_star_pct
        + inflation_yoy_pct
        + 0.5 * (inflation_yoy_pct - inflation_target_pct)
        + 0.5 * output_gap_pct
    )
