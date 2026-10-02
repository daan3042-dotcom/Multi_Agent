"""
test_freeze_guard.py
De bewaking van de doelenlijst en de evidence-sheet (`contract/freeze_versions.py`, `runtime/freeze_guard.py`) en het
freeze-overzicht (`runtime/freeze_status.py`, `freeze_status.py`). 02-10-2026.

ALS DE EERSTE TWEE TESTS FALEN: dat is geen bug in de test. De doelenlijst, een resolutieregel of de evidence-sheet is
veranderd. Verhoog het versienummer in src/contract/freeze_versions.py, voeg de nieuwe vingerafdruk toe aan het register
en beschrijf de wijziging in docs/roadmap.md. Bij een wijziging aan de evidence-sheet moet ook FORECAST_PROMPT_VERSION
van de agents omhoog (de prompt-hash bevat de evidence-vingerafdruk).

DIT BEVRIEST NIETS. Het freeze-overzicht leest alleen; er is hier geen test die iets zet.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sqlite3
from pathlib import Path

import pytest

from contract import freeze_versions as fv
from runtime import freeze_guard as fg
from runtime import freeze_status as fs
from scoring import evidence_sheet as es
from storage.schema import init_db, save_baseline_model

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# De waakhond
# --------------------------------------------------------------------------


def test_doelenlijst_is_ongewijzigd_of_versie_is_opgehoogd():
    verwacht = fv.TARGETS_FINGERPRINTS.get(fv.TARGETS_VERSION)
    assert verwacht, f"TARGETS_VERSION {fv.TARGETS_VERSION} staat niet in het register"
    assert fg.doelen_fingerprint() == verwacht, (
        f"De doelenlijst of een resolutieregel is gewijzigd (afdruk {fg.doelen_fingerprint()}, verwacht {verwacht}). "
        f"Verhoog TARGETS_VERSION en voeg de nieuwe afdruk toe aan TARGETS_FINGERPRINTS. Na T₀ᵇ start dit een nieuw cohort."
    )


def test_evidence_sheet_is_ongewijzigd_of_versie_is_opgehoogd():
    verwacht = fv.EVIDENCE_SHEET_FINGERPRINTS.get(fv.EVIDENCE_SHEET_VERSION)
    assert verwacht, f"EVIDENCE_SHEET_VERSION {fv.EVIDENCE_SHEET_VERSION} staat niet in het register"
    assert fg.evidence_fingerprint() == verwacht, (
        f"De evidence-sheet is gewijzigd (afdruk {fg.evidence_fingerprint()}, verwacht {verwacht}). Verhoog "
        f"EVIDENCE_SHEET_VERSION, voeg de afdruk toe aan het register EN verhoog FORECAST_PROMPT_VERSION van de agents."
    )


def test_registers_hebben_geen_dubbele_afdrukken_en_geen_placeholders():
    for register in (fv.TARGETS_FINGERPRINTS, fv.EVIDENCE_SHEET_FINGERPRINTS):
        assert len(set(register.values())) == len(register)
        assert all(len(v) == 16 and v != "TE_BEPALEN" for v in register.values())


def test_de_fixture_dekt_elk_soort_regel_van_de_evidence_sheet():
    """Een afdruk over een te magere fixture zou wijzigingen aan een ongebruikt pad niet zien."""
    tekst = fg.evidence_fixture_tekst()
    for stuk in (
        "laatste waarde", "1 maand eerder", "laatste 52 weken", "Spreiding van de verandering",
        "procentpunt relatief rendement",        # relatief rendement
        "ongewijzigd",                           # stapreeks
        "niet te berekenen",                     # verouderde reeks
        "geen opgeslagen waarnemingen",          # reeks zonder historie
        "Context voor de FOMC-vragen", "Laatste verandering van de doelrange", "Eerstvolgende FOMC-besluitdagen",
    ):
        assert stuk in tekst, stuk


def test_afdrukken_zijn_herhaalbaar():
    assert fg.evidence_fingerprint() == fg.evidence_fingerprint()
    assert fg.doelen_fingerprint() == fg.doelen_fingerprint()


# --- de waakhond reageert echt op wat hij moet bewaken ---


def test_een_wijziging_aan_de_opmaak_van_de_sheet_verandert_de_afdruk(monkeypatch):
    voor = fg.evidence_fingerprint()
    monkeypatch.setattr(es, "_g", lambda x: f"{x:.2f}")
    assert fg.evidence_fingerprint() != voor


def test_een_wijziging_aan_de_vensters_van_de_spreiding_verandert_de_afdruk(monkeypatch):
    voor = fg.evidence_fingerprint()
    monkeypatch.setattr(es, "DAGEN_VIJF_JAAR", 3 * 365)
    assert fg.evidence_fingerprint() != voor


def test_een_gewijzigde_resolutieregel_horizon_of_methode_verandert_de_doelenafdruk(monkeypatch):
    from agents import monetary_policy_agent as mp

    voor = fg.doelen_fingerprint()
    origineel = mp.FORECAST_TARGETS
    eerste = origineel[0]
    for wijziging in (
        {"resolution_rule": eerste.resolution_rule + " (aangepast)"},
        {"horizons": (5, 21)},
        {"event_rule": "iets anders"},
    ):
        monkeypatch.setattr(mp, "FORECAST_TARGETS", (dataclasses.replace(eerste, **wijziging), *origineel[1:]))
        assert fg.doelen_fingerprint() != voor, wijziging
    monkeypatch.setattr(mp, "FORECAST_TARGETS", origineel)
    assert fg.doelen_fingerprint() == voor


def test_de_doelenafdruk_negeert_de_volgorde_van_registratie(monkeypatch):
    from runtime import daily

    voor = fg.doelen_fingerprint()
    echt = daily.default_agents
    monkeypatch.setattr(daily, "default_agents", lambda: list(reversed(echt())))
    assert fg.doelen_fingerprint() == voor


def test_de_prompt_hash_bevat_de_evidence_sheet(monkeypatch):
    """Verandert wat een agent te zien krijgt, dan moet de prompt-versie omhoog: daarom zit de afdruk in de hash."""
    from agents import monetary_policy_agent as mp

    voor = fg.forecast_prompt_hash(mp)
    monkeypatch.setattr(fg, "evidence_fingerprint", lambda: "anders")
    assert fg.forecast_prompt_hash(mp) != voor


# --------------------------------------------------------------------------
# Het freeze-overzicht
# --------------------------------------------------------------------------


def _punt(punten, naam):
    return next(p for p in punten if p.naam == naam)


def test_het_overzicht_heeft_voor_elk_punt_een_geldige_status_en_een_bron():
    punten = fs.bepaal_punten(None)
    geldig = {*fs.TELLEN_MEE, fs.INFO}
    assert punten and all(p.status in geldig and p.bron and p.waarde for p in punten)


def test_de_waarden_komen_live_uit_de_code_en_zijn_geen_kopie(monkeypatch):
    from contract import prediction as pred, trigger_version as tv

    monkeypatch.setattr(pred, "CONTRACT_VERSION", "v9")
    monkeypatch.setattr(tv, "TRIGGER_VERSION", "v9")
    punten = fs.bepaal_punten(None)
    assert _punt(punten, "Predictiecontract").waarde == "v9"
    assert _punt(punten, "Trigger-regels").waarde.startswith("v9")
    # Een versienummer waarvan de afdruk niet in het register staat is een wijziging zonder versie.
    assert _punt(punten, "Trigger-regels").status == fs.ZONDER_VERSIE


def test_zonder_pin_en_zonder_ridge_staat_alles_nog_niet_bevroren_en_de_open_beslissingen_zijn_zichtbaar():
    punten = fs.bepaal_punten(None)
    assert _punt(punten, "Trigger-pin (FROZEN_TRIGGER_VERSION)").status == fs.TE_BEVESTIGEN
    assert _punt(punten, "Prior voor de skill-posterior").status == fs.OPEN_BESLISSING
    assert _punt(punten, "Causale graaf").status == fs.OPEN_BESLISSING
    assert _punt(punten, "Richtlijnen van DD voor de agents").status == fs.OPEN_BESLISSING
    assert fs.samenvatting(punten)[fs.BEVROREN] == 0  # er is niets bevroren: dit overzicht doet dat nooit zelf


@pytest.mark.parametrize("pin, verwacht", [(None, fs.TE_BEVESTIGEN), ("huidige", fs.BEVROREN), ("v1", fs.LET_OP)])
def test_de_trigger_pin_wordt_juist_beoordeeld(monkeypatch, pin, verwacht):
    from contract import trigger_version as tv

    pin = tv.TRIGGER_VERSION if pin == "huidige" else pin  # niet hardcoden: de versie gaat omhoog bij elke regelwijziging
    monkeypatch.setattr(tv, "FROZEN_TRIGGER_VERSION", pin)
    assert _punt(fs.bepaal_punten(None), "Trigger-pin (FROZEN_TRIGGER_VERSION)").status == verwacht


def test_het_echte_cohort_zonder_trigger_pin_is_een_waarschuwing():
    punten = fs.bepaal_punten(None, environ={"MI_COHORT": "cohort_0"})
    assert _punt(punten, "Cohort voor nieuwe voorspellingen").status == fs.LET_OP
    assert _punt(fs.bepaal_punten(None, environ={}), "Cohort voor nieuwe voorspellingen").status == fs.TE_BEVESTIGEN


def test_de_ridge_telling_komt_uit_de_database_en_alleen_volledig_bevroren_telt_als_bevroren(tmp_path):
    from datetime import datetime, timezone
    from scoring import ridge as rg

    pad = str(tmp_path / "t.db")
    conn = init_db(pad)
    nu = datetime(2026, 10, 13, tzinfo=timezone.utc)
    save_baseline_model(conn, "ridge", rg.RIDGE_SPEC_VERSION, "monetary_policy", "10y_treasury_yield", 5, nu, nu, 100, {"x": 1})
    save_baseline_model(conn, "ridge", "v1", "monetary_policy", "oud", 5, nu, nu, 100, {"x": 1})  # oude spec telt niet
    conn.close()

    ridge = _punt(fs.bepaal_punten(pad), "Ridge-baseline")
    assert f"1 van {fg.aantal_kwantielreeksen_voor_ridge()} bevroren" in ridge.waarde
    assert ridge.status == fs.TE_BEVESTIGEN  # niet alles bevroren


def test_de_voorspellingen_per_cohort_staan_erbij_als_de_database_er_is(tmp_path):
    pad = str(tmp_path / "t.db")
    init_db(pad).close()
    assert _punt(fs.bepaal_punten(pad), "Voorspellingen per cohort").waarde == "geen"


def test_een_ontbrekende_database_geeft_geen_fout_maar_zegt_onbekend(tmp_path):
    punten = fs.bepaal_punten(str(tmp_path / "bestaat_niet.db"))
    assert "onbekend" in _punt(punten, "Ridge-baseline").waarde
    assert not any(p.naam == "Voorspellingen per cohort" for p in punten)


def test_de_tekst_toont_groepen_statussen_en_een_samenvatting():
    tekst = fs.format_overzicht(fs.bepaal_punten(None))
    for stuk in ("FREEZE-OVERZICHT", "bevriest niets", "CONTRACT EN REGELS", "DREMPELS", "LLM", "BASELINES", "STAND VAN ZAKEN",
                 "[TE BEVESTIGEN]", "[OPEN BESLISSING]", "SAMENVATTING:", "100.000 tekens"):
        assert stuk in tekst, stuk
    assert "WIJZIGING ZONDER VERSIE" not in tekst.split("SAMENVATTING")[1]


def _cli():
    spec = importlib.util.spec_from_file_location("freeze_status_cli", ROOT / "freeze_status.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_het_script_schrijft_niets_en_geeft_exit_nul(tmp_path, capsys):
    pad = tmp_path / "t.db"
    init_db(str(pad)).close()
    voor = pad.read_bytes()
    assert _cli().main(["--db", str(pad)]) == 0
    assert "FREEZE-OVERZICHT" in capsys.readouterr().out
    assert pad.read_bytes() == voor  # niets gewijzigd


def test_de_database_gaat_alleen_lezen_open(tmp_path):
    """Een schrijfpoging via dezelfde route moet mislukken: dat bewijst `mode=ro`."""
    pad = tmp_path / "t.db"
    init_db(str(pad)).close()
    conn = sqlite3.connect(f"file:{pad}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("CREATE TABLE x (a)")
    conn.close()
    # En het overzicht zelf schrijft dus ook nooit: de module bevat geen schrijfopdracht.
    bron = (ROOT / "src/runtime/freeze_status.py").read_text(encoding="utf-8")
    for verboden in ("INSERT", "UPDATE ", "DELETE", "DROP ", "CREATE ", ".commit("):
        assert verboden not in bron.replace("alleen lezen", ""), verboden


# --------------------------------------------------------------------------
# DD's voorlopige akkoord (02-10-2026): hangt aan de waarde, vervalt vanzelf
# --------------------------------------------------------------------------

AKKOORD_NAMEN = (
    "Predictiecontract", "Kwantielniveaus", "Aandelensplitsingen (correctie bij het lezen)", "FOMC-kalender",
    "Persistence en climatology", "Model (model_id)",
)


def test_de_zes_punten_met_dd_akkoord_staan_als_akkoord_dd_en_de_rest_blijft_te_bevestigen():
    from contract.freeze_versions import AKKOORDEN_DD

    assert set(AKKOORDEN_DD) == set(AKKOORD_NAMEN)
    punten = fs.bepaal_punten(None)
    for naam in AKKOORD_NAMEN:
        p = _punt(punten, naam)
        assert p.status == fs.AKKOORD_DD, (naam, p.waarde)
        assert "voorlopig akkoord DD 02-10-2026" in p.opmerking
    # Niet in het register: blijft wachten (graaf, doelenlijst, prompts, evidence-sheet, ridge, denkinstelling, pin, cohort, drempels, resolver, scorer)
    for naam in ("Doelenlijst en resolutieregels", "Prompt sector", "Evidence-sheet", "Ridge-baseline", "Denkinstelling",
                 "Trigger-pin (FROZEN_TRIGGER_VERSION)", "Trigger-regels", "Resolver-wachttijd", "Scorer"):
        assert _punt(punten, naam).status in (fs.TE_BEVESTIGEN, fs.ZONDER_VERSIE), naam


def test_een_akkoord_vervalt_vanzelf_als_de_waarde_verandert(monkeypatch):
    from contract import prediction as pred

    monkeypatch.setattr(pred, "CONTRACT_VERSION", "v2")
    p = _punt(fs.bepaal_punten(None), "Predictiecontract")
    assert p.status == fs.TE_BEVESTIGEN and "VERVALLEN" in p.opmerking and "'v1'" in p.opmerking and "'v2'" in p.opmerking


def test_akkoord_dd_is_geen_bevroren_en_een_andere_status_blijft_zoals_ze_is(monkeypatch):
    punten = fs.bepaal_punten(None)
    tel = fs.samenvatting(punten)
    assert tel[fs.BEVROREN] == 0 and tel[fs.AKKOORD_DD] == 6
    # een LET OP (hier: de splitsingswaakhond) wordt NIET door een akkoord overschreven
    from runtime import split_waakhond

    monkeypatch.setattr(split_waakhond, "waarschuwingen", lambda conn: ["onverklaarde sprong xlf"], raising=False)
    from contract import freeze_versions as fv

    monkeypatch.setitem(fv.AKKOORDEN_DD, "Model (model_id)", ("een-ander-model", "01-01-2026"))
    punten = [fs.Punt("G", "Model (model_id)", "claude-sonnet-5-5", "x", fs.LET_OP)]
    assert fs._pas_akkoorden_toe(punten)[0].status == fs.LET_OP


def test_de_tekst_toont_het_akkoord_en_het_register_heeft_geen_spelfouten():
    from contract.freeze_versions import AKKOORDEN_DD

    punten = fs.bepaal_punten(None)
    namen = {p.naam for p in punten}
    assert set(AKKOORDEN_DD) <= namen        # een typfout in een naam zou het akkoord stil wegnemen
    tekst = fs.format_overzicht(punten)
    assert "[AKKOORD DD]" in tekst and "6 akkoord dd" in tekst
