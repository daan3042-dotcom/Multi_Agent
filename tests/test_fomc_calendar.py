"""
test_fomc_calendar.py
Vangnet voor `contract/resolution.py::FOMC_MEETING_DATES` (roadmap 4.5,
CLAUDE.md checkpoint 4).

De kalender wordt met de hand ingevuld vanaf de officiële Fed-pagina, en een
typefout maakt een voorspelling stilzwijgend op het verkeerde moment af --
erger dan hem niet afwikkelen. Deze tests vangen de fouten die een mens bij
het overtypen maakt, zonder de datums zelf te kennen.

CONVENTIE: de datum is de BESLUITDAG, de tweede dag van de vergadering (de
FOMC vergadert dinsdag en woensdag, en de rentebeslissing komt woensdag).
Zolang de tuple leeg is (nu), slagen de tests vacuüm; de resolver meldt dan
per voorspelling dat de kalender leeg is.
"""

from __future__ import annotations

from datetime import timedelta

from contract.resolution import FOMC_MEETING_DATES

WOENSDAG = 2


def test_de_kalender_is_oplopend_en_zonder_dubbele_datums():
    assert list(FOMC_MEETING_DATES) == sorted(set(FOMC_MEETING_DATES))


def test_elke_datum_is_een_woensdag():
    """Een dinsdag betekent dat de eerste vergaderdag is overgetypt."""
    fout = [d for d in FOMC_MEETING_DATES if d.weekday() != WOENSDAG]
    assert not fout, f"geen woensdag (besluitdag): {fout}"


def test_de_afstand_tussen_vergaderingen_is_aannemelijk():
    """Acht per jaar, dus vier tot tien weken uit elkaar. Vangt een verkeerde
    maand of een vergeten vergadering."""
    for vorige, volgende in zip(FOMC_MEETING_DATES, FOMC_MEETING_DATES[1:]):
        weken = (volgende - vorige) / timedelta(weeks=1)
        assert 4 <= weken <= 10, f"{vorige} -> {volgende}: {weken:.1f} weken"


def test_niet_meer_dan_acht_per_kalenderjaar():
    per_jaar: dict[int, int] = {}
    for d in FOMC_MEETING_DATES:
        per_jaar[d.year] = per_jaar.get(d.year, 0) + 1
    assert all(n <= 8 for n in per_jaar.values()), per_jaar


def test_de_besluitdagen_uit_de_persberichten_van_juli_en_september_2026_staan_erin():
    """Bron: de FOMC-persberichten van 29 juli en 16 september 2026 (door DD aangeleverd). Vastgepind omdat de pseudo-OOS-run
    (4.4) op deze twee dagen de FOMC-doelen afrekent."""
    from datetime import date

    assert date(2026, 7, 29) in FOMC_MEETING_DATES and date(2026, 9, 16) in FOMC_MEETING_DATES
