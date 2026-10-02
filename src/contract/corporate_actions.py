"""
contract/corporate_actions.py
Aandelensplitsingen (roadmap 1.5/4.5, 02-10-2026): de lijst met bekende splitsingen van ETF's in de koersreeksen, en de
correctie die ze bij het LEZEN toepast.

WAAROM DIT BESTAAT. De back-fill haalt `TIME_SERIES_DAILY` op: NIET gecorrigeerde koersen. Op 5 december 2025 halveerde de koers
van vijf Select Sector SPDR's (XLB, XLE, XLK, XLU, XLY) in één dag door een 2-voor-1-splitsing; de sprong staat als ruwe waarneming
in de claims. Alles wat over de historie rekent zag daardoor een "daling" van ~50%: de spreiding in de evidence-sheet, de baselines,
het afrekenen van voorspellingen over de splitsingsdatum, en het kalibratierapport van de triggers.

HOE. De ruwe claims blijven EXACT zoals ze zijn (immutabel, en het archief van wat de bron leverde). Bij het lezen
(`scoring.resolver.observations_for`, het ene pad voor evidence-sheet, baselines, ridge, resolver en kalibratie) worden de waarden
van VÓÓR een splitsing gedeeld door de verhouding, zodat de hele historie in dezelfde aandelen staat als de huidige koers.

`verhouding` = nieuwe aandelen per oud aandeel: 2.0 is een 2-voor-1-splitsing (koers halveert), 0.1 een 1-voor-10 samenvoeging
(koers keert x10). De datum is de EERSTE waarnemingsdag op het nieuwe niveau.

EEN NIEUWE SPLITSING TOEVOEGEN. Alleen AAN HET EIND toevoegen, nooit een bestaande wijzigen of verwijderen: dat zou voorspellingen die al
lopen op een ander moment of met een andere uitkomst afrekenen. De dagelijkse run waarschuwt (`runtime/split_waakhond.py`) als er een
sprong in een ETF-reeks staat die hier niet in staat, en ook als een hier geregistreerde splitsing niet door de data wordt bevestigd.
Een splitsing wordt niet in de doelenlijst-vingerafdruk meegenomen: een toevoeging is administratie, geen nieuwe regel.

BEKENDE BEPERKING (cosmetisch): de correctie kent de toekomst. Voor een `as_of` van vóór een splitsing worden de oudere waarden al in
nieuwe aandelen getoond. Alleen niveaus worden zo anders weergegeven; verhoudingen en rendementen niet. Geen van de huidige doelen of runs ligt
vóór 5 december 2025.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from contract.resolution import Observation


@dataclass(frozen=True)
class Splitsing:
    metric_key: str
    datum: date  # eerste waarnemingsdag op het nieuwe niveau
    verhouding: float  # nieuwe aandelen per oud aandeel (2.0 = 2-voor-1)
    bron: str

    def __post_init__(self) -> None:
        if self.verhouding <= 0 or self.verhouding == 1:
            raise ValueError(f"ongeldige verhouding {self.verhouding!r} voor {self.metric_key}")


_BRON_5_DEC_2025 = (
    "gemeten in de eigen claims (02-10-2026, DD): op 2025-12-05 halveert de koers (verhouding 0,495-0,504), alleen bij deze vijf ETF's, "
    "geen andere ETF en SPY niet"
)

SPLITSINGEN: tuple[Splitsing, ...] = (
    Splitsing("xlb_materials", date(2025, 12, 5), 2.0, _BRON_5_DEC_2025),
    Splitsing("xle_energy", date(2025, 12, 5), 2.0, _BRON_5_DEC_2025),
    Splitsing("xlk_technology", date(2025, 12, 5), 2.0, _BRON_5_DEC_2025),
    Splitsing("xlu_utilities", date(2025, 12, 5), 2.0, _BRON_5_DEC_2025),
    Splitsing("xly_consumer_discretionary", date(2025, 12, 5), 2.0, _BRON_5_DEC_2025),
)


def factor_voor(metric_key: str, waarneming: date, splitsingen: tuple[Splitsing, ...] | None = None) -> float:
    """De deler voor een waarneming van deze dag: het product van de verhoudingen van alle splitsingen die NA die dag liggen."""
    lijst = SPLITSINGEN if splitsingen is None else splitsingen  # bij AANROEP gelezen, zodat een test hem kan vervangen
    f = 1.0
    for s in lijst:
        if s.metric_key == metric_key and waarneming < s.datum:
            f *= s.verhouding
    return f


def pas_splitsingen_toe(
    metric_key: str, observations: list[Observation], splitsingen: tuple[Splitsing, ...] | None = None
) -> list[Observation]:
    """Dezelfde waarnemingen, met de waarden van vóór een splitsing omgerekend naar de huidige aandelen. Raakt andere reeksen
    niet aan, en geeft de oorspronkelijke lijst onveranderd terug als er niets te corrigeren valt."""
    lijst = SPLITSINGEN if splitsingen is None else splitsingen
    if not any(s.metric_key == metric_key for s in lijst):
        return observations
    uit = []
    for o in observations:
        f = factor_voor(metric_key, o.source_time.date(), lijst)
        uit.append(o if f == 1.0 else replace(o, value=o.value / f))
    return uit
