"""
test_resolution.py
Tests voor de resolutiemethoden (roadmap 4.5), `src/contract/resolution.py`.

WAAROM DEZE TESTS ZWAARDER WEGEN DAN DE MEESTE. Een fout hier is
onzichtbaar: een verkeerd afgewikkelde voorspelling ziet er precies zo uit
als een goede, en de evaluations-tabel kent geen update-pad. De bug komt
dus niet als storing binnen maar als een track record dat nét iets anders
meet dan afgesproken.

Twee dingen worden hier het scherpst bewaakt: de vintage-regel (een revisie
mag de uitkomst nooit veranderen) en het onderscheid tussen NotYetResolvable
en Unresolvable (wachten versus opgeven).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from contract.resolution import (
    NotYetResolvable,
    Observation,
    Unresolvable,
    direction_after_fomc,
    level_at_or_after,
    nth_release,
    relative_return,
)

NU = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _obs(dag: int, waarde: float, gezien_dag: int | None = None, claim_id: int = 0) -> Observation:
    """Waarneming van 2026-10-<dag>, standaard dezelfde dag gezien."""
    periode = datetime(2026, 10, dag, tzinfo=timezone.utc)
    gezien = datetime(2026, 10, gezien_dag if gezien_dag is not None else dag, tzinfo=timezone.utc)
    return Observation(source_time=periode, value=waarde, first_seen=gezien, claim_id=claim_id or dag)


# --------------------------------------------------------------------------
# level_at_or_after -- dagreeksen met een handelsdagen-horizon
# --------------------------------------------------------------------------


def test_level_pakt_de_eerste_observatie_op_of_na_resolves_at():
    reeks = [_obs(5, 4.0), _obs(6, 4.1), _obs(9, 4.3)]
    uitkomst = level_at_or_after(reeks, datetime(2026, 10, 7, tzinfo=timezone.utc))
    assert uitkomst.value == 4.3
    assert uitkomst.realised_at == datetime(2026, 10, 9, tzinfo=timezone.utc)


def test_level_pakt_de_dag_zelf_als_die_bestaat():
    """'Op of na', niet 'na'. Een horizon die precies op een handelsdag
    landt mag niet stilzwijgend een dag opschuiven."""
    reeks = [_obs(5, 4.0), _obs(7, 4.2), _obs(9, 4.3)]
    assert level_at_or_after(reeks, datetime(2026, 10, 7, tzinfo=timezone.utc)).value == 4.2


def test_level_wacht_als_de_reeks_nog_niet_zo_ver_is():
    reeks = [_obs(5, 4.0), _obs(6, 4.1)]
    with pytest.raises(NotYetResolvable):
        level_at_or_after(reeks, datetime(2026, 10, 20, tzinfo=timezone.utc))


def test_level_wacht_ook_bij_een_lege_reeks():
    """Leeg is 'nog niets binnen', niet 'nooit' -- een nieuwe reeks heeft
    op dag één ook geen historie."""
    with pytest.raises(NotYetResolvable):
        level_at_or_after([], NU)


def test_een_revisie_verandert_de_uitkomst_niet():
    """De vintage-regel, en het belangrijkste regressiegeval van dit
    bestand. Elke resolution_rule in dit systeem zegt "EERSTE print". Zou
    een latere revisie tellen, dan verschuift een score maanden nadat hij
    is vastgesteld."""
    eerste_print = _obs(9, 4.3, gezien_dag=9, claim_id=100)
    revisie = Observation(
        source_time=datetime(2026, 10, 9, tzinfo=timezone.utc),
        value=99.0,
        first_seen=datetime(2026, 10, 25, tzinfo=timezone.utc),
        claim_id=200,
    )
    uitkomst = level_at_or_after(
        [revisie, eerste_print], datetime(2026, 10, 8, tzinfo=timezone.utc)
    )
    assert uitkomst.value == 4.3
    assert uitkomst.claim_ids == (100,)


# --------------------------------------------------------------------------
# nth_release -- week- en maandreeksen
# --------------------------------------------------------------------------


def test_nth_release_telt_periodes_en_geen_dagen():
    reeks = [_obs(1, 200.0), _obs(8, 210.0), _obs(15, 220.0), _obs(22, 230.0)]
    created = datetime(2026, 10, 2, tzinfo=timezone.utc)
    assert nth_release(reeks, created, 1).value == 210.0
    assert nth_release(reeks, created, 3).value == 230.0


def test_nth_release_wacht_tot_er_genoeg_publicaties_zijn():
    reeks = [_obs(1, 200.0), _obs(8, 210.0)]
    with pytest.raises(NotYetResolvable):
        nth_release(reeks, datetime(2026, 10, 2, tzinfo=timezone.utc), 4)


def test_een_revisie_telt_niet_als_publicatie():
    """Regressiegeval. Een revisie van een OUDE periode komt binnen als een
    nieuwe claim na created_at. Zou die als publicatie meetellen, dan
    verschuift de telling en wikkelt een 3-publicaties-voorspelling af op de
    tweede echte print."""
    revisie_van_oude_periode = Observation(
        source_time=datetime(2026, 10, 1, tzinfo=timezone.utc),
        value=205.0,
        first_seen=datetime(2026, 10, 10, tzinfo=timezone.utc),
        claim_id=999,
    )
    reeks = [_obs(1, 200.0), revisie_van_oude_periode, _obs(8, 210.0), _obs(15, 220.0)]
    created = datetime(2026, 10, 2, tzinfo=timezone.utc)

    assert nth_release(reeks, created, 1).value == 210.0
    assert nth_release(reeks, created, 2).value == 220.0


def test_nth_release_zonder_historie_bij_voorspellen_is_definitief_onafwikkelbaar():
    """Niet 'nog wachten': zonder een bekende laatste periode is 'de
    volgende publicatie' niet vast te stellen, en dat wordt het later ook
    niet meer."""
    reeks = [_obs(8, 210.0), _obs(15, 220.0)]
    with pytest.raises(Unresolvable):
        nth_release(reeks, datetime(2026, 10, 2, tzinfo=timezone.utc), 1)


# --------------------------------------------------------------------------
# relative_return -- de sector agent
# --------------------------------------------------------------------------


def test_relatief_rendement_trekt_de_markt_eruit():
    """De ETF stijgt 10%, de markt 4% -- het antwoord is 6 procentpunt, en
    niet 10."""
    etf = [_obs(1, 100.0), _obs(20, 110.0)]
    spy = [_obs(1, 500.0), _obs(20, 520.0)]
    uitkomst = relative_return(etf, spy, NU, datetime(2026, 10, 20, tzinfo=timezone.utc))
    assert uitkomst.value == pytest.approx(6.0)


def test_relatief_rendement_is_negatief_als_de_sector_achterblijft():
    etf = [_obs(1, 100.0), _obs(20, 102.0)]
    spy = [_obs(1, 500.0), _obs(20, 525.0)]
    assert relative_return(etf, spy, NU, datetime(2026, 10, 20, tzinfo=timezone.utc)).value == pytest.approx(-3.0)


def test_relatief_rendement_gebruikt_alleen_gedeelde_momenten():
    """Het regressiegeval waarvoor deze functie bestaat in plaats van twee
    losse aanroepen. De ETF mist 20 oktober; zou hij op 21 gemeten worden
    en SPY op 20, dan zit er een dag marktbeweging in het antwoord die
    niets met rotatie te maken heeft."""
    etf = [_obs(1, 100.0), _obs(21, 110.0)]
    spy = [_obs(1, 500.0), _obs(20, 520.0), _obs(21, 530.0)]
    uitkomst = relative_return(etf, spy, NU, datetime(2026, 10, 20, tzinfo=timezone.utc))
    assert uitkomst.realised_at == datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert uitkomst.value == pytest.approx(10.0 - 6.0)


def test_relatief_rendement_wacht_als_de_horizon_nog_niet_bereikt_is():
    etf = [_obs(1, 100.0), _obs(5, 101.0)]
    spy = [_obs(1, 500.0), _obs(5, 505.0)]
    with pytest.raises(NotYetResolvable):
        relative_return(etf, spy, NU, datetime(2026, 10, 20, tzinfo=timezone.utc))


def test_relatief_rendement_zonder_startpunt_is_onafwikkelbaar():
    etf = [_obs(20, 110.0)]
    spy = [_obs(20, 520.0)]
    with pytest.raises(Unresolvable):
        relative_return(etf, spy, NU, datetime(2026, 10, 20, tzinfo=timezone.utc))


def test_relatief_rendement_zonder_gedeelde_momenten_is_onafwikkelbaar():
    etf = [_obs(1, 100.0), _obs(20, 110.0)]
    spy = [_obs(2, 500.0), _obs(21, 520.0)]
    with pytest.raises(Unresolvable):
        relative_return(etf, spy, NU, datetime(2026, 10, 20, tzinfo=timezone.utc))


# --------------------------------------------------------------------------
# direction_after_fomc -- bewust nog niet bruikbaar
# --------------------------------------------------------------------------


def test_zonder_fomc_kalender_wordt_er_niet_benaderd():
    """CLAUDE.md: nooit stilzwijgend doorgaan met een beste gok. FEDFUNDS
    publiceert twaalf keer per jaar en de FOMC vergadert acht keer, dus
    'de n-de print' is een andere gebeurtenis dan 'na de n-de vergadering'."""
    with pytest.raises(Unresolvable, match="FOMC-kalender"):
        direction_after_fomc([_obs(1, 4.0)], NU, 1)


def test_met_kalender_werkt_de_methode_wel():
    """Zodra FOMC_MEETING_DATES gevuld is, werkt dit zonder codewijziging."""
    kalender = (date(2026, 10, 28), date(2026, 12, 9))
    reeks = [_obs(1, 4.00, claim_id=1), _obs(30, 4.25, claim_id=2)]
    uitkomst = direction_after_fomc(reeks, NU, 1, meetings=kalender)
    assert uitkomst.value == 1.0
    assert uitkomst.claim_ids == (1, 2)


def test_gelijk_blijven_telt_als_niet_verhoogd():
    """Staat zo in de resolution_rule van de monetary agent. De
    conservatieve kant: wie 'hoger' zei krijgt geen punt voor niets."""
    kalender = (date(2026, 10, 28),)
    reeks = [_obs(1, 4.00), _obs(30, 4.00)]
    assert direction_after_fomc(reeks, NU, 1, meetings=kalender).value == 0.0


def test_te_korte_kalender_is_onafwikkelbaar_en_zegt_wat_eraan_ontbreekt():
    kalender = (date(2026, 10, 28),)
    with pytest.raises(Unresolvable, match="FOMC_MEETING_DATES"):
        direction_after_fomc([_obs(1, 4.0)], NU, 2, meetings=kalender)


def test_wachten_op_een_waarneming_na_de_vergadering():
    kalender = (date(2026, 10, 28),)
    reeks = [_obs(1, 4.00), _obs(20, 4.10)]
    with pytest.raises(NotYetResolvable):
        direction_after_fomc(reeks, NU, 1, meetings=kalender)
