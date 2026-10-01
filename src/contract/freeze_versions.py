"""
contract/freeze_versions.py
Versienummers van twee dingen die bij de freeze (CLAUDE.md, checkpoint 5) vastliggen maar tot 02-10-2026 geen eigen
bewaking hadden: de DOELENLIJST met zijn resolutieregels, en de EVIDENCE-SHEET (de context die een agent bij zijn
forecast-ronde krijgt). Zelfde patroon als `contract/trigger_version.py`.

WAAROM DIT BESTAAT. Een wijziging aan een resolutieregel of aan wat een agent te zien krijgt, verandert wat er
getest wordt. Zonder bewaking kan dat stil gebeuren: de prompt-hash dekte alleen de systeemprompt, niet de
context-tekst die `scoring/evidence_sheet.py` bouwt, en niemand dwong af dat een wijziging aan de doelenlijst een
versienummer kreeg. Dan staan twee verschillende metingen onder één label, en dat merk je pas maanden later.

HOE HET WERKT. `runtime/freeze_guard.py` rekent van elk een vingerafdruk uit. De tests (`tests/test_freeze_guard.py`)
falen zodra de vingerafdruk niet meer bij het versienummer past. Dat is GEEN bug in de test: verhoog het
versienummer, voeg de nieuwe vingerafdruk toe aan het register en beschrijf de wijziging in docs/roadmap.md.

DE EVIDENCE-SHEET ZIT OOK IN DE PROMPT-HASH (`tests/test_forecast_prompt_version.py`): verandert de sheet, dan
verandert de hash van elke agent, en dan moet `FORECAST_PROMPT_VERSION` omhoog. Dat is de bedoeling: de
`prompt_version` op elke voorspelling is de enige plek waar achteraf te zien is wat de agent kreeg.

NA T₀ᵇ: een wijziging aan de doelenlijst of de resolutieregels start een nieuw cohort (CLAUDE.md). Een wijziging aan
de evidence-sheet is een covariaat (`prompt_version`), geen nieuw cohort.
"""

from __future__ import annotations

TARGETS_VERSION = "v1"
"""De doelenlijst: per agent welke metric, vorm, horizonnen, resolutiemethode en resolutieregel."""
TARGETS_FINGERPRINTS: dict[str, str] = {
    "v1": "52b89e72c6ea2743",
}

EVIDENCE_SHEET_VERSION = "v1"
"""De context-tekst bij de forecast-ronde (01-10-2026, optie B): ouderdom, veranderingen, 52-wekenbereik, spreiding
per horizon en de FOMC-context."""
EVIDENCE_SHEET_FINGERPRINTS: dict[str, str] = {
    "v1": "94e8923819c07998",
}
