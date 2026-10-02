"""
trigger_version.py
Roadmap 1.5 (Trigger-versioning), T₀-blokkade -- beslist en gebouwd op
29-09-2026.

WAT DIT IS. Eén versienummer voor "de regels die bepalen of er een trigger
vuurt": de drempels (tolerance + severity) per reeks, de ouderdomsgrenzen per
bron en het gedrag van de trigger-laag zelf (strikt groter dan, de
completeness-verhouding, staleness, manager-dispatch). Elke opgeslagen
trigger en elke voorspelling draagt dit nummer.

WAAROM. Kalibreren en scoren gaan over "hoe vaak vuurde deze regel en wat
volgde erop". Is een drempel halverwege verschoven zonder dat dat ergens
staat, dan staan er twee verschillende regels onder één label en is de
reeks niet meer te interpreteren -- en dat merk je pas maanden later,
wanneer er niets meer aan te doen valt. CLAUDE.md: na T₀ᵇ niet sleutelen
aan drempels zonder versienummer.

HOE HET BEWAAKT WORDT. Een nummer dat je met de hand moet ophogen wordt
vergeten. `runtime/trigger_guard.py::trigger_fingerprint()` rekent een
vingerafdruk uit van alles wat bepaalt of een trigger vuurt, en
`tests/test_trigger_version.py` faalt zodra die niet meer bij de versie
hieronder past. Labels en teksten tellen NIET mee: een gecorrigeerde
schrijfwijze is geen andere regel.

ALS DE TEST FAALT: dat is geen bug in de test. Een regel is veranderd.
Verhoog TRIGGER_VERSION, voeg de nieuwe vingerafdruk toe aan
TRIGGER_FINGERPRINTS (de oude blijft staan als historie) en vermeld in
docs/roadmap.md wat er veranderd is en waarom.

VERSIES.
  v0  de illustratieve plaatshouders waarmee het systeem is opgezet.
  v1  de gekalibreerde set (29-09-2026, 5 triggers/jaar, currency 2), zie
      docs/roadmap.md "Beslist op 29-09-2026". Commodity bleef op v0-waarden
      omdat er nog geen historie was.
  v2  v1 + commodity gekalibreerd op de back-fill (29-09-2026, dezelfde dag,
      ~5 per jaar). Alleen de tien commodity-drempels zijn veranderd.
  v3  v2 + één nieuwe spec: `fed_funds_target_upper` (DFEDTARU, tolerance
      0,125 = de halve stap van 0,25) in de monetary agent (01-10-2026,
      vóór de freeze). Bestaande drempels zijn niet veranderd. De reeks
      bedient de FOMC-resolutie en vuurt op de besluitdag.

  v4  v3 + de drempels van vijf sector-ETF's gecorrigeerd voor de splitsing van
      2025-12-05 (02-10-2026, vóór de freeze, DD akkoord): XLK 8,9 -> 5,4,
      XLE 2,6 -> 1,6, XLY 6,2 -> 3,2, XLB 2,0 -> 1,2, XLU 1,8 -> 1,0. Alleen
      die vijf; de rest is ongewijzigd. Reden en cijfers: docs/roadmap.md.

ONBEKEND IS GEEN v0. Triggers van vóór deze module hebben `NULL` in
`trigger_events.trigger_version`: ze zijn gemaakt met drempels die
ondertussen zijn veranderd (WALCL, sector), en `v0` zou daar te veel
beloven.
"""

from __future__ import annotations

TRIGGER_VERSION = "v4"

# versie -> vingerafdruk van de regels zoals die bij die versie golden.
# Alleen de vingerafdruk van TRIGGER_VERSION wordt bewaakt; de oudere blijven
# staan als vastgelegde historie.
TRIGGER_FINGERPRINTS: dict[str, str] = {
    "v0": "d075e95a2b069acf",
    "v1": "6d38e5eadaa613b3",
    "v2": "f80c151df5175293",
    "v3": "1d72aeed38fc97ec",
    "v4": "26f1dcf7937e4f86",
}

# De versie die bij de freeze vóór T₀ᵇ is bevestigd (CLAUDE.md, checkpoint 5).
# `None` = nog niet bevroren. Zolang MI_COHORT=cohort_0 staat en deze niet
# gelijk is aan TRIGGER_VERSION, weigert run_daily.py te starten (exit 2):
# een drempel die na de klokstart verschuift start een nieuw cohort, en dat
# hoort een bewuste stap te zijn, geen bijwerking.
FROZEN_TRIGGER_VERSION: str | None = None


def current_trigger_version() -> str:
    """Zelfde patroon als `current_cohort()`: nieuwe voorspellingen en triggers
    volgen de code vanzelf, niemand hoeft het door te geven."""
    return TRIGGER_VERSION
