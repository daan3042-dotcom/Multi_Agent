"""
test_env.py
Tests voor `runtime/env.py` en het gebruik ervan in `backfill.py` en
`fit_baselines.py`.

Aanleiding (29-09): beide scripts verwachtten dat je eerst `source .env` deed.
Vergeten gaf bij backfill.py een 'key niet gevonden', en bij fit_baselines.py
(dat geen key nodig heeft) een stille terugval op een database in de huidige
map -- een lege, verkeerde database waarin alles 'mislukt' zonder aanwijzing.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from runtime.env import load_env_file

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _schone_omgeving():
    """Begin zonder de variabelen die deze tests gebruiken, en zet de HELE
    omgeving na afloop terug. `load_env_file` schrijft in `os.environ`, en
    `monkeypatch` herstelt alleen wat het zelf heeft gezet: zonder dit lekt
    een MI_DB_PATH of API-key uit deze tests naar alle tests erna."""
    bewaard = dict(os.environ)
    for naam in ("TEST_A", "TEST_B", "TEST_C", "TEST_D", "MI_DB_PATH", "ALPHAVANTAGE_API_KEY", "FRED_API_KEY"):
        os.environ.pop(naam, None)
    yield
    os.environ.clear()
    os.environ.update(bewaard)


def _env(tmp_path, tekst):
    pad = tmp_path / ".env"
    pad.write_text(tekst, encoding="utf-8")
    return pad


def test_leest_gewone_regels_en_geeft_alleen_namen_terug(tmp_path):
    pad = _env(tmp_path, "TEST_A=een\nTEST_B=twee\n")

    gezet = load_env_file(pad)

    assert gezet == ["TEST_A", "TEST_B"]
    assert os.environ["TEST_A"] == "een" and os.environ["TEST_B"] == "twee"


def test_overschrijft_nooit_een_bestaande_variabele(tmp_path, monkeypatch):
    """Wat je expliciet zet, of wat run_daily.sh al inlaadde, wint."""
    monkeypatch.setenv("TEST_A", "expliciet")
    gezet = load_env_file(_env(tmp_path, "TEST_A=uit_bestand\n"))

    assert gezet == []
    assert os.environ["TEST_A"] == "expliciet"


def test_commentaar_lege_regels_en_aanhalingstekens(tmp_path):
    load_env_file(_env(tmp_path, '# een opmerking\n\nTEST_A="met aanhalingstekens"\nTEST_B=\'enkel\'\n   \n'))

    assert os.environ["TEST_A"] == "met aanhalingstekens"
    assert os.environ["TEST_B"] == "enkel"


def test_waarde_met_een_isgelijkteken_blijft_heel(tmp_path):
    """API-keys en urls bevatten vaak een `=`; alleen op het eerste splitsen."""
    load_env_file(_env(tmp_path, "TEST_A=abc=def==\n"))
    assert os.environ["TEST_A"] == "abc=def=="


def test_lege_waarde_telt_als_niet_ingesteld(tmp_path):
    """`.env.example` laat `MI_COHORT=` leeg met de betekenis 'niet instellen'.
    Een lege string in de omgeving zou anders een echte, lege waarde worden."""
    gezet = load_env_file(_env(tmp_path, "TEST_A=\n"))
    assert gezet == [] and "TEST_A" not in os.environ


def test_ontbrekend_bestand_is_geen_fout(tmp_path):
    assert load_env_file(tmp_path / "bestaat_niet.env") == []


# --------------------------------------------------------------------------
# De scripts zelf
# --------------------------------------------------------------------------


def _cli(naam):
    spec = importlib.util.spec_from_file_location(f"cli_{naam}", ROOT / f"{naam}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fit_baselines_leest_mi_db_path_uit_env_zonder_source(tmp_path):
    """Het echte risico: zonder MI_DB_PATH viel dit script stil terug op een
    database in de huidige map. Nu volgt hij het .env-bestand."""
    db = tmp_path / "echte_database.db"
    cli = _cli("fit_baselines")
    cli.ENV_PATH = str(_env(tmp_path, f"MI_DB_PATH={db}\n"))

    cli.main([])

    assert db.exists(), "het script gebruikte niet de database uit .env"


def test_backfill_vindt_zijn_api_key_zonder_source(tmp_path, monkeypatch, capsys):
    """Het probleem van vandaag: 'ALPHAVANTAGE_API_KEY niet gevonden' terwijl de
    key gewoon in .env staat."""
    import runtime.backfill as bf

    cli = _cli("backfill")
    cli.ENV_PATH = str(_env(tmp_path, f"ALPHAVANTAGE_API_KEY=uit-env-bestand\nMI_DB_PATH={tmp_path / 'db.db'}\n"))
    gezien = []

    def nep(url, params, timeout):
        gezien.append(params.get("apikey"))
        raise ConnectionError("geen netwerk in deze test")

    monkeypatch.setattr(bf.requests, "get", nep)

    code = cli.main(["--domain", "currency"])

    assert code == 1, "de key is gevonden; alleen het ophalen mislukte (geen exit 2)"
    assert set(gezien) == {"uit-env-bestand"}


def test_backfill_zonder_key_ergens_geeft_nog_steeds_exit_twee(tmp_path):
    cli = _cli("backfill")
    cli.ENV_PATH = str(tmp_path / "bestaat_niet.env")
    assert cli.main(["--db", str(tmp_path / "t.db"), "--domain", "currency"]) == 2
