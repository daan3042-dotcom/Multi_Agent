"""
domain_ontology.py
Stap 1.1 (tweede helft): een classificatielaag bovenop de bestaande, vrije
domain-strings ("monetary_policy", "currency", "equity:<TICKER>", ...) --
puur additief, niets bestaands hoeft dit aan te roepen om te blijven
werken. Bedoeld voor de cross-domain synthesizer (pijler 3.1), die later
wil kunnen vragen "welke domeinen raken FX" of "welke claims gaan over
Macro" zonder dat elke agent zijn eigen categorie-aanname hoeft te
hardcoden.

Bewust een los bestand naast output_contract.py, niet erin: dat contract
houdt zich expliciet minimaal (zie de eigen moduledocstring, "alles hierna
vertrouwt op deze vorm") -- domain-classificatie is een aparte, latere
laag, geen onderdeel van wat een Claim zelf is.
"""

from __future__ import annotations

from enum import Enum


class DomainCategory(str, Enum):
    """De acht assetklassen/thema's uit roadmap 1.1. Eén domain kan meerdere
    categorieën hebben (bijv. "sector" is zowel Sectors als Equities) --
    classify_domain() geeft daarom altijd een lijst terug, nooit één enkele
    waarde."""

    EQUITIES = "equities"
    RATES = "rates"
    FX = "fx"
    COMMODITIES = "commodities"
    CREDIT = "credit"
    MACRO = "macro"
    SECTORS = "sectors"
    COMPANIES = "companies"


_EXACT_DOMAIN_MAP: dict[str, list[DomainCategory]] = {
    "monetary_policy": [DomainCategory.RATES, DomainCategory.MACRO],
    "currency": [DomainCategory.FX],
    "financial": [DomainCategory.CREDIT, DomainCategory.MACRO],
    "sector": [DomainCategory.SECTORS, DomainCategory.EQUITIES],
    "commodity": [DomainCategory.COMMODITIES],
}


def classify_domain(domain: str) -> list[DomainCategory]:
    """Vertaalt een domain-string naar zijn categorieën. Een "equity:<TICKER>"-
    genamespacet domain (zie agents/equity_agent.py::equity_domain) is zowel
    Equities (de assetklasse) als Companies (de onderliggende, bedrijfs-
    specifieke claims zoals Altman Z-Score/Piotroski). Een onbekend domain
    is een programmeerfout, geen twijfelgeval -- fail loud (ValueError),
    zelfde precedent als Claim/DomainOutput in output_contract.py."""
    if domain.startswith("equity:"):
        return [DomainCategory.EQUITIES, DomainCategory.COMPANIES]
    if domain in _EXACT_DOMAIN_MAP:
        return list(_EXACT_DOMAIN_MAP[domain])
    raise ValueError(f"Onbekend domain: {domain!r}")
