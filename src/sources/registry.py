"""
registry.py
Roadmap 1.4: Source Registry -- centraal register per databron (provider,
frequency, latency, cost, quality_score).

AANLEIDING (24-09-2026): 1.7's system_health() maakte een bestaande
beperking zichtbaar. monetary_policy_agent.py en financial_agent.py
gebruikten allebei de RUWE providernaam "FRED" als source_name richting
data_health -- dus ÉÉN gedeelde data_health-rij voor twee agents met een
verschillende verwachte ververssnelheid (35 dagen vs. 10 dagen). Erger dan
een verkeerde max_age: een succesvolle poll van agent A ververst de
GEDEELDE checked_at, waardoor agent B's eigen staleness (die misschien al
dagen niet zelf gelukt is) wordt VERBORGEN achter agent A's frequente
successen. Dat is geen tolerantie-kwestie maar een gat in A.3's eigen
"fail loudly, not silently"-principe.

ONTWERPBESLISSING: één registry-entry PER (provider, domain)-combinatie,
niet één entry per provider met losse, aparte per-consument-config. Zie
docs/architecture.md ("Ontwerpkeuzes") voor de volledige afweging --
samengevat: een entry per provider zou het probleem niet oplossen, want
data_health zou dan nog steeds op de kale providernaam gekeyed blijven en
dus nog steeds gedeeld tussen agents. Deze registry's `source_key` (bv.
"FRED:monetary_policy") IS de nieuwe, per-consument-gescopete identifier
die record_data_health()/check_source() voortaan gebruiken -- geen
wijziging aan agents/base.py of health/data_health.py zelf nodig, alleen
aan welke string de gemigreerde agents als source_name doorgeven.

storage.schema.register_source() is een UPSERT, geen append-only log zoals
agent_runs/data_health -- dit is CONFIGURATIE, geen gebeurtenis-
geschiedenis. Een agent mag 'm daarom veilig op elke monitoring-cyclus
aanroepen (zelfde gedachte als record_data_health()) om zijn eigen config
te "declareren", zonder duplicaten te riskeren.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class SourceConfig:
    """Eén geregistreerde bron: een (provider, domain)-combinatie met de
    verwachte ververssnelheid (max_age) en beschrijvende metadata.

    quality_score en fallback_source_key mogen leeg zijn:
    - quality_score wacht op de Bayesiaanse weging uit de synthese-laag
      (sectie 3, nog niet gebouwd) -- het VELD bestaat al, er is nog geen
      logica die 'm berekent of gebruikt.
    - fallback_source_key is het VELD voor 1.4's fallback-bron-logica,
      maar geen enkele agent heeft momenteel een daadwerkelijke
      alternatieve bron geïmplementeerd om naar te verwijzen -- de
      registry-kant staat klaar, de wiring in een agent is expliciet
      open vervolgwerk, niet geforceerd binnen deze sectie."""

    source_key: str
    provider: str
    domain: str
    max_age: timedelta
    frequency: str | None = None
    latency: str | None = None
    cost: str | None = None
    quality_score: float | None = None
    fallback_source_key: str | None = None
