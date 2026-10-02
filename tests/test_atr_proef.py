"""
test_atr_proef.py
Het ATR-proefrapport (`calibration/atr_proef.py`, roadmap 4.2, idee van DD 02-10-2026): alleen lezen, wijzigt geen drempel.
Wat bewaakt wordt: het gemiddelde is point-in-time (een sprong trekt zijn eigen drempel niet op), strikt groter dan telt,
week-/maandreeksen en stapreeksen worden als 'niet te beoordelen' gemeld in plaats van stilzwijgend meegeteld, en de
database blijft ongewijzigd.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from calibration import atr_proef as ap
from calibration.trigger_calibration import calibrate_series
from storage.schema import init_db

UTC = timezone.utc


def _reeks(stappen: list[float], start: date = date(2024, 1, 1), elke_dagen: int = 1, begin: float = 100.0):
    """Waarnemingen waarbij elke stap de volgende verandering is (teken wisselt zodat het niveau rond begin blijft)."""
    waarde, uit = begin, [(datetime(start.year, start.month, start.day, tzinfo=UTC), begin)]
    for i, s in enumerate(stappen, start=1):
        waarde += s if i % 2 else -s
        uit.append((datetime(start.year, start.month, start.day, tzinfo=UTC) + timedelta(days=elke_dagen * i), waarde))
    return uit


def test_een_gewone_sprong_na_rust_vuurt_en_een_gewone_dag_niet():
    # 40 rustige dagen van 1,0 en dan een sprong van 5,0 (5 x het gemiddelde).
    waarden = _reeks([1.0] * 40 + [5.0])
    paren, beoordeeld, t = ap.atr_tellingen(waarden)
    assert paren == 41
    assert beoordeeld == 41 - ap.MIN_VENSTER
    # Alleen de sprong is groter dan N x 1,0 voor N=2,3,4; bij N=5 is 5,0 niet STRIKT groter, bij N=6 ook niet.
    assert t[2] == t[3] == t[4] == 1
    assert t[5] == 0 and t[6] == 0


def test_het_gemiddelde_is_point_in_time_een_sprong_trekt_zijn_eigen_drempel_niet_op():
    # Zou de sprong in zijn eigen venster zitten, dan was het gemiddelde (30*1+5)/31 en bleef N=5 net buiten bereik; dit is anders:
    waarden = _reeks([1.0] * 30 + [5.0])
    _, _, t = ap.atr_tellingen(waarden)
    assert t[4] == 1


def test_gelijk_aan_de_drempel_vuurt_niet():
    waarden = _reeks([1.0] * 30 + [3.0])
    _, _, t = ap.atr_tellingen(waarden)
    assert t[3] == 0 and t[2] == 1


def test_na_een_drukke_periode_stijgt_de_drempel_mee():
    # Dezelfde beweging van 5,0 vuurt na rust wel (N=4) maar niet midden in een drukke periode van 4,0 per dag.
    rustig = _reeks([1.0] * 30 + [5.0])
    druk = _reeks([4.0] * 30 + [5.0])
    assert ap.atr_tellingen(rustig)[2][4] == 1
    assert ap.atr_tellingen(druk)[2][2] == 0


def test_weekreeks_is_niet_te_beoordelen_en_telt_niet_stilzwijgend():
    waarden = _reeks([1.0] * 200 + [50.0], elke_dagen=7)
    paren, beoordeeld, t = ap.atr_tellingen(waarden)
    assert paren == 201 and beoordeeld == 0
    assert all(v == 0 for v in t.values())
    r = ap.atr_proef_reeks("economic", "weekreeks", 1.0, waarden)
    assert r.dekking == 0 and not r.vergelijkbaar and r.n_dichtst_bij_doel is None
    assert "niet te beoordelen" in ap.render_atr_rapport([r])


def test_stapreeks_met_gemiddelde_nul_wordt_niet_beoordeeld():
    waarden = [(datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i), 4.0) for i in range(60)]
    waarden.append((datetime(2024, 3, 1, tzinfo=UTC), 4.5))
    paren, beoordeeld, t = ap.atr_tellingen(waarden)
    assert beoordeeld == 0 and all(v == 0 for v in t.values())


def test_vanaf_beperkt_de_telling_tot_het_venster():
    waarden = _reeks([1.0] * 40 + [5.0])
    vanaf = waarden[-1][0]
    paren, _, t = ap.atr_tellingen(waarden, vanaf=vanaf)
    assert paren == 1 and t[2] == 1


def test_per_jaar_en_huidige_drempel_komen_overeen_met_het_bestaande_rapport():
    waarden = _reeks([1.0 + (i % 3) * 0.1 for i in range(900)] + [9.0])
    r = ap.atr_proef_reeks("sector", "x", 2.0, waarden)
    assert r.huidig_per_jaar == calibrate_series("sector", "x", 2.0, waarden).stats["3j"].per_year
    assert r.vergelijkbaar and r.per_jaar[2] is not None
    assert r.per_jaar[2] >= r.per_jaar[3] >= r.per_jaar[4] >= r.per_jaar[5] >= r.per_jaar[6]
    assert r.n_dichtst_bij_doel in ap.NS


def test_te_korte_reeks_geeft_een_leeg_resultaat_zonder_fout():
    r = ap.atr_proef_reeks("sector", "kort", 1.0, [(datetime(2024, 1, 1, tzinfo=UTC), 1.0)])
    assert r.pairs == 0 and r.huidig_per_jaar is None and r.dekking is None
    assert ap.render_atr_rapport([r])


def test_rapport_over_de_database_wijzigt_niets(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    voor = [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("claims", "agent_runs", "predictions")]
    uit = ap.atr_proef_alles(conn, datetime(2026, 10, 2, tzinfo=UTC))
    assert len(uit) > 20 and all(r.pairs == 0 for r in uit)      # lege database: geen fout, wel alle reeksen
    assert "TOTAAL" not in ap.render_atr_rapport(uit)
    na = [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("claims", "agent_runs", "predictions")]
    assert voor == na
