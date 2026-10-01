"""
test_evidence_sheet.py
De context die een agent bij zijn forecast-ronde krijgt (`scoring/evidence_sheet.py`, besluit DD 01-10-2026,
optie B). Zuiver Python, point-in-time, geen LLM.

De drie dingen die hier bewaakt worden, omdat een fout er niet aan af te zien is:
1. de getallen kloppen en gebruiken DEZELFDE definitie van "verandering over de horizon" als de baselines;
2. er lekt nooit iets uit de toekomst in (de pseudo-OOS-run bouwt hierop);
3. ontbrekende of verouderde data wordt benoemd en niet stil weggelaten (het model zou anders gaan raden).
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta, timezone

import pytest

from agents.base import ForecastTarget, _forecast_user_prompt, FORECAST_SYSTEM_RULES
from contract.horizons import ReleaseCadence
from contract.output_contract import Claim, Confidence, DomainOutput, Mode
from contract.prediction import HorizonKind, PredictionKind
from contract.resolution import ResolutionMethod
from scoring.baselines import _sample
from scoring.evidence_sheet import _g, build_evidence_sheet
from storage.schema import init_db, load_monitoring_claims, save_domain_output

NU = datetime(2026, 10, 13, 7, 15, tzinfo=timezone.utc)


def _db(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def _werkdagen(aantal: int, einde: datetime) -> list[datetime]:
    d, uit = einde, []
    while len(uit) < aantal:
        if d.weekday() < 5:
            uit.append(d)
        d -= timedelta(days=1)
    return list(reversed(uit))


def _opslaan(conn, key, waarden, dagen, label=None, eerste_gezien=None):
    claims = [
        Claim(
            domain="d", claim=label or key, value=w, source="test", confidence=Confidence.HIGH,
            analysis_time=(eerste_gezien[i] if eerste_gezien else dag), source_time=dag, metric_key=key,
        )
        for i, (w, dag) in enumerate(zip(waarden, dagen))
    ]
    save_domain_output(conn, DomainOutput(domain="d", mode=Mode.MONITORING, generated_at=dagen[0], claims=claims))


def _laatste_cyclus(conn, keys, label=None):
    """De claims van een cyclus op `NU`: één per reeks, zoals `load_monitoring_claims` ze teruggeeft."""
    vorige = {}
    for key in keys:
        rij = conn.execute(
            "SELECT value_json, source_time FROM claims WHERE metric_key = ? ORDER BY source_time DESC LIMIT 1", (key,)
        ).fetchone()
        vorige[key] = rij
    import json
    claims = [
        Claim(domain="d", claim=label or key, value=json.loads(v), source="test", confidence=Confidence.HIGH,
              analysis_time=NU, source_time=datetime.fromisoformat(t), metric_key=key)
        for key, (v, t) in vorige.items()
    ]
    save_domain_output(conn, DomainOutput(domain="d", mode=Mode.MONITORING, generated_at=NU, claims=claims))
    return load_monitoring_claims(conn, "d")


def _doel(key="x", horizons=(5, 21), **kw):
    basis = dict(
        metric_key=key, kind=PredictionKind.QUANTILE, horizon_kind=HorizonKind.TRADING_DAYS, horizons=horizons,
        resolution_method=ResolutionMethod.LEVEL_AT_OR_AFTER, resolution_rule="regel {horizon_n}",
    )
    basis.update(kw)
    return ForecastTarget(**basis)


def _lineair(conn, key="x", n=400, begin=100.0, stap=0.1):
    dagen = _werkdagen(n, NU - timedelta(days=1))
    waarden = [begin + stap * i for i in range(n)]
    _opslaan(conn, key, waarden, dagen)
    return dagen, waarden


# --------------------------------------------------------------------------
# 1. De getallen
# --------------------------------------------------------------------------


def test_laatste_waarde_datum_ouderdom_en_veranderingen_kloppen(tmp_path):
    conn = _db(tmp_path)
    dagen, waarden = _lineair(conn)
    claims = _laatste_cyclus(conn, ["x"])
    tekst = build_evidence_sheet(conn, [_doel()], claims, NU)

    assert f"laatste waarde {_g(waarden[-1])} van {dagen[-1].date()} (1 dag oud)" in tekst
    # Eén maand eerder: de laatste print op of vóór 30 kalenderdagen ervoor.
    een_maand = max(i for i, d in enumerate(dagen) if d <= dagen[-1] - timedelta(days=30))
    assert f"1 maand eerder {_g(waarden[een_maand])} (+{waarden[-1] - waarden[een_maand]:.4g})" in tekst
    assert "3 maanden eerder" in tekst and "te weinig historie" not in tekst


def test_het_bereik_van_52_weken_en_de_positie_daarin(tmp_path):
    conn = _db(tmp_path)
    dagen, waarden = _lineair(conn)
    claims = _laatste_cyclus(conn, ["x"])
    tekst = build_evidence_sheet(conn, [_doel()], claims, NU)
    jaar = [w for d, w in zip(dagen, waarden) if d > dagen[-1] - timedelta(days=365)]
    assert f"laag {_g(min(jaar))}, hoog {_g(max(jaar))}" in tekst
    assert "nu hoger dan 100%" in tekst  # een stijgende reeks staat op zijn hoogste punt


def test_een_reeks_die_een_jaar_niet_bewoog_zegt_ongewijzigd_en_niet_hoger_dan_100_procent(tmp_path):
    """Regressie: bij een stapreeks (de Fed-doelrange) suggereerde 'hoger dan 100%' een extreme stand."""
    conn = _db(tmp_path)
    dagen = _werkdagen(300, NU - timedelta(days=1))
    _opslaan(conn, "s", [4.0] * 300, dagen)
    tekst = build_evidence_sheet(conn, [], _laatste_cyclus(conn, ["s"]), NU)
    assert "ongewijzigd op 4" in tekst and "hoger dan" not in tekst


def test_de_spreiding_is_de_standaarddeviatie_van_dezelfde_vensters_als_de_baselines(tmp_path):
    """De kern: dezelfde definitie van 'verandering over de horizon' als de persistence-baseline en de resolutie."""
    import random
    random.seed(1)
    conn = _db(tmp_path)
    dagen = _werkdagen(1500, NU - timedelta(days=1))
    v, waarden = 50.0, []
    for _ in dagen:
        v += random.gauss(0, 0.5)
        waarden.append(v)
    _opslaan(conn, "x", waarden, dagen)
    doel = _doel(horizons=(21,))
    tekst = build_evidence_sheet(conn, [doel], _laatste_cyclus(conn, ["x"]), NU)

    sample = _sample(conn, doel, 21, NU)
    vijf = [d for d, s in zip(sample.deltas, sample.dates) if s >= NU - timedelta(days=5 * 365)]
    een = [d for d, s in zip(sample.deltas, sample.dates) if s >= NU - timedelta(days=365)]
    assert f"laatste 5 jaar {_g(statistics.stdev(vijf))} (n={len(vijf)})" in tekst
    assert f"laatste jaar {_g(statistics.stdev(een))} (n={len(een)})" in tekst


def test_er_staan_geen_kant_en_klare_kwantielen_in_de_sheet(tmp_path):
    """Bewust: alleen spreiding. Gaven we de baseline-kwantielen mee, dan meet de test of het model kan kopiëren."""
    conn = _db(tmp_path)
    _lineair(conn)
    tekst = build_evidence_sheet(conn, [_doel()], _laatste_cyclus(conn, ["x"]), NU)
    for verboden in ("q10", "q25", "q50", "q75", "q90", "kwantiel", "mediaan"):
        assert verboden not in tekst, verboden
    assert "standaarddeviatie" in tekst


def test_relatief_rendement_wordt_als_procentpunt_aangeduid(tmp_path):
    conn = _db(tmp_path)
    dagen = _werkdagen(400, NU - timedelta(days=1))
    _opslaan(conn, "etf", [100 + 0.2 * i + (i % 7) for i in range(400)], dagen)
    _opslaan(conn, "spy", [100 + 0.1 * i for i in range(400)], dagen)
    doel = _doel("etf", resolution_method=ResolutionMethod.RELATIVE_RETURN, benchmark_metric_key="spy")
    tekst = build_evidence_sheet(conn, [doel], _laatste_cyclus(conn, ["etf"]), NU)
    assert "procentpunt relatief rendement" in tekst


# --------------------------------------------------------------------------
# 2. Point-in-time: nooit iets uit de toekomst
# --------------------------------------------------------------------------


def test_waarnemingen_na_as_of_en_later_gezien_dan_as_of_tellen_niet_mee(tmp_path):
    conn = _db(tmp_path)
    dagen, waarden = _lineair(conn)
    toekomst = [NU + timedelta(days=i + 1) for i in range(3)]
    _opslaan(conn, "x", [9999.0] * 3, toekomst)  # periode ligt na as_of
    gisteren = dagen[-1]
    _opslaan(conn, "x", [8888.0], [gisteren - timedelta(days=400)], eerste_gezien=[NU + timedelta(days=5)])  # later gezien
    claims = _laatste_cyclus(conn, ["x"])
    tekst = build_evidence_sheet(conn, [_doel()], claims, NU)
    assert "9999" not in tekst and "8888" not in tekst
    assert f"laatste waarde {_g(waarden[-1])}" in tekst


def test_een_datum_in_het_verleden_geeft_de_stand_van_toen(tmp_path):
    """De functie is bedoeld voor de pseudo-OOS-run: dezelfde data, een eerdere `as_of`."""
    conn = _db(tmp_path)
    dagen, waarden = _lineair(conn, n=500)
    claims = _laatste_cyclus(conn, ["x"])
    eerder = dagen[-100] + timedelta(hours=8)
    tekst = build_evidence_sheet(conn, [_doel()], claims, eerder)
    assert f"laatste waarde {_g(waarden[-100])} van {dagen[-100].date()}" in tekst
    assert f"zoals bekend op {eerder.date()}" in tekst


def test_een_gerevideerde_waarde_toont_de_eerste_print(tmp_path):
    conn = _db(tmp_path)
    dagen = _werkdagen(60, NU - timedelta(days=1))
    _opslaan(conn, "x", [10.0] * 60, dagen)
    _opslaan(conn, "x", [12.0], [dagen[-1]], eerste_gezien=[NU - timedelta(hours=1)])  # revisie, later gezien
    tekst = build_evidence_sheet(conn, [], _laatste_cyclus(conn, ["x"]), NU)
    assert "laatste waarde 10 " in tekst and "12" not in tekst.split("laatste waarde")[1][:6]


# --------------------------------------------------------------------------
# 3. Ontbrekende of verouderde data wordt benoemd
# --------------------------------------------------------------------------


def test_een_reeks_zonder_historie_krijgt_een_regel_die_dat_zegt_en_geen_uitzondering(tmp_path):
    conn = _db(tmp_path)
    claim = Claim(domain="d", claim="Nieuw", value=1.0, source="t", confidence=Confidence.HIGH, analysis_time=NU, metric_key="nieuw")
    tekst = build_evidence_sheet(conn, [_doel("nieuw")], [claim], NU)
    assert "nieuw (Nieuw): geen opgeslagen waarnemingen" in tekst and "geen context beschikbaar" in tekst


def test_te_weinig_historie_voor_een_maand_of_bereik_wordt_benoemd(tmp_path):
    conn = _db(tmp_path)
    dagen = _werkdagen(4, NU - timedelta(days=1))
    _opslaan(conn, "x", [1.0, 2.0, 3.0, 4.0], dagen)
    tekst = build_evidence_sheet(conn, [], _laatste_cyclus(conn, ["x"]), NU)
    assert "1 maand eerder: te weinig historie" in tekst and "52 weken: slechts 4 waarnemingen" in tekst


def test_een_verouderde_reeks_geeft_de_reden_en_laat_de_spreiding_niet_stil_weg(tmp_path):
    """Een handelsdagen-doel op een reeks die 60 dagen oud is: de baselines weigeren dat ook. De sheet zegt waarom."""
    conn = _db(tmp_path)
    dagen = _werkdagen(400, NU - timedelta(days=60))
    _opslaan(conn, "x", [100 + 0.1 * i for i in range(400)], dagen)
    tekst = build_evidence_sheet(conn, [_doel(horizons=(5,))], _laatste_cyclus(conn, ["x"]), NU)
    assert "niet te berekenen" in tekst and "60 dagen" in tekst
    assert "(60 dagen oud)" in tekst


def test_een_spreiding_met_te_weinig_vensters_zegt_dat(tmp_path):
    conn = _db(tmp_path)
    _lineair(conn, n=60)
    tekst = build_evidence_sheet(conn, [_doel(horizons=(21,))], _laatste_cyclus(conn, ["x"]), NU)
    # 60 waarnemingen geven 39 vensters van 21 dagen in totaal, maar niet 8 in elk jaar-venster hoeft te lukken;
    # in elk geval mag er nooit een getal zonder zijn n staan.
    for stuk in tekst.split("Spreiding")[1].split(";"):
        assert "(n=" in stuk or "te weinig" in stuk or "niet te berekenen" in stuk


# --------------------------------------------------------------------------
# De FOMC-context
# --------------------------------------------------------------------------


def _fomc_doel():
    return _doel(
        "dfedtaru", horizons=(1, 2), kind=PredictionKind.BINARY, horizon_kind=HorizonKind.RELEASES,
        cadence=ReleaseCadence.FOMC, resolution_method=ResolutionMethod.DIRECTION_AFTER_FOMC, event_rule="hoger",
    )


def test_fomc_context_noemt_de_laatste_verandering_de_recente_veranderingen_en_de_komende_besluitdagen(tmp_path):
    conn = _db(tmp_path)
    dagen = _werkdagen(400, NU - timedelta(days=1))
    waarden = [4.50 if d < datetime(2025, 12, 10, tzinfo=timezone.utc) else 4.25 for d in dagen]
    _opslaan(conn, "dfedtaru", waarden, dagen)
    tekst = build_evidence_sheet(conn, [_fomc_doel()], _laatste_cyclus(conn, ["dfedtaru"]), NU)

    assert "huidige stand 4.25" in tekst
    assert "Laatste verandering van de doelrange: -0.25 op 2025-12-10" in tekst
    assert "-0.25 op 2025-12-10" in tekst.split("laatste 2 jaar:")[1]
    assert "2026-10-28 (over 15 dagen)" in tekst and "2026-12-09" in tekst  # twee vergaderingen: horizon 2


def test_fomc_context_voor_een_doelrange_die_nooit_veranderde_en_voor_een_lege_kalender(tmp_path, monkeypatch):
    from contract import resolution
    import scoring.evidence_sheet as es

    conn = _db(tmp_path)
    dagen = _werkdagen(300, NU - timedelta(days=1))
    _opslaan(conn, "dfedtaru", [4.0] * 300, dagen)
    claims = _laatste_cyclus(conn, ["dfedtaru"])
    assert "nooit veranderd" in build_evidence_sheet(conn, [_fomc_doel()], claims, NU)
    monkeypatch.setattr(es, "FOMC_MEETING_DATES", ())
    assert "onbekend (kalender is op)" in build_evidence_sheet(conn, [_fomc_doel()], claims, NU)


# --------------------------------------------------------------------------
# Vorm en omvang
# --------------------------------------------------------------------------


def test_de_sheet_is_deterministisch_en_klein(tmp_path):
    conn = _db(tmp_path)
    _lineair(conn, n=3000)
    claims = _laatste_cyclus(conn, ["x"])
    a = build_evidence_sheet(conn, [_doel(horizons=(5, 21, 63))], claims, NU)
    assert a == build_evidence_sheet(conn, [_doel(horizons=(5, 21, 63))], claims, NU)
    assert len(a) < 2_000  # één reeks met drie horizonnen; ruim onder de verzoekgrens van 100.000


def test_getalopmaak_blijft_leesbaar_voor_grote_en_kleine_waarden():
    assert _g(6_747_704.0) == "6747704" and _g(4.123456) == "4.123" and _g(0.0712345) == "0.07123"


# --------------------------------------------------------------------------
# In de prompt en in de ronde
# --------------------------------------------------------------------------


def test_de_context_staat_tussen_de_cijfers_en_de_opdracht_in_de_prompt():
    claim = Claim(domain="d", claim="X", value=1.0, source="t", confidence=Confidence.HIGH, analysis_time=NU, metric_key="x")
    prompt = _forecast_user_prompt([_doel()], [claim], evidence="CONTEXT-TEKST")
    assert prompt.index("Huidige, al berekende cijfers") < prompt.index("CONTEXT-TEKST") < prompt.index("Geef voor ELK")
    assert "CONTEXT-TEKST" not in _forecast_user_prompt([_doel()], [claim])  # zonder context verandert er niets


def test_de_systeemprompt_legt_uit_hoe_de_context_te_gebruiken_zonder_kwantielen_voor_te_schrijven():
    assert "6. GEBRUIK DE CONTEXT" in FORECAST_SYSTEM_RULES
    assert "wijk er alleen van af" in FORECAST_SYSTEM_RULES
    assert "1,28" not in FORECAST_SYSTEM_RULES  # geen omrekentabel naar kwantielen: dat zou kopiëren uitnodigen
