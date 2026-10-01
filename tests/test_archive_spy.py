"""
test_archive_spy.py
Het ruwe SPY-holdings-archief (docs/data-archive.md, fase B). Geen netwerk, geen
echte klok, geen database: `get` en `nu` worden meegegeven, de map is tmp_path.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from archive import spy_holdings as sh

NU = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)  # vrijdag


def _xlsx(tekst: str = "Holdings: As of 01-Oct-2026", vulling: int = 12_000) -> bytes:
    """Een minimaal, geldig xlsx-werkboek (zip met xl/workbook.xml)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/sharedStrings.xml", f"<sst><si><t>{tekst}</t></si></sst>")
        z.writestr("xl/worksheets/sheet1.xml", "x" * vulling)
    return buf.getvalue()


def _get(inhoud: bytes, status: int = 200):
    return lambda url, headers=None, timeout=None: SimpleNamespace(status_code=status, content=inhoud)


# --------------------------------------------------------------------------
# Correct geval
# --------------------------------------------------------------------------


def test_bewaart_het_bestand_gzip_en_schrijft_een_manifestregel(tmp_path):
    data = _xlsx()
    r = sh.archiveer(nu=NU, basis=tmp_path, get=_get(data))

    assert r.path == "spy_holdings/2026/spy_holdings_2026-10-02.xlsx.gz"
    assert gzip.decompress((tmp_path / r.path).read_bytes()) == data  # ruwe bytes, onaangeraakt
    (regel,) = sh.lees_manifest(tmp_path)
    assert regel["sha256"] == hashlib.sha256(data).hexdigest()
    assert regel["as_of"] == "2026-10-01"
    assert regel["same_as_previous"] is False
    assert not list(tmp_path.rglob("*.tmp"))  # geen halve bestanden achtergelaten


def test_tweede_aanroep_op_dezelfde_dag_schrijft_niets_extra(tmp_path):
    sh.archiveer(nu=NU, basis=tmp_path, get=_get(_xlsx()))
    r = sh.archiveer(nu=NU.replace(hour=20), basis=tmp_path, get=_get(_xlsx()))

    assert r.already_archived is True
    assert len(sh.lees_manifest(tmp_path)) == 1


def test_byte_identiek_aan_de_vorige_dag_wordt_gemarkeerd_maar_wel_bewaard(tmp_path):
    """Weekend en feestdag: de bron verandert niet. We bewaren het toch (een
    gat in de reeks is erger dan 40 KB), maar de markering maakt het zichtbaar."""
    data = _xlsx()
    sh.archiveer(nu=NU, basis=tmp_path, get=_get(data))
    r = sh.archiveer(nu=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc), basis=tmp_path, get=_get(data))

    assert r.same_as_previous is True
    assert len(sh.lees_manifest(tmp_path)) == 2


# --------------------------------------------------------------------------
# Regressie: niets weggeschreven bij een slechte bron
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "inhoud, status, fragment",
    [
        (b"<html>" + b"x" * 20_000 + b"</html>", 200, "PK"),  # HTTP 200 met een foutpagina
        (b"", 200, "te klein"),
        (_xlsx()[:5_000], 200, "te klein"),  # afgekapte download
        (b"PK\x03\x04" + b"0" * 20_000, 200, "beschadigd"),  # zip-kop, rest rommel
        (_xlsx(), 503, "HTTP 503"),
    ],
)
def test_slechte_bron_wordt_geweigerd_en_laat_geen_spoor_na(tmp_path, inhoud, status, fragment):
    with pytest.raises(sh.ArchiveError, match=fragment):
        sh.archiveer(nu=NU, basis=tmp_path, get=_get(inhoud, status))
    assert not any(tmp_path.rglob("*.gz")) and not any(tmp_path.rglob("manifest.jsonl"))


def test_netwerkfout_wordt_een_archiveerror_zonder_url_of_sleutel(tmp_path):
    def stuk(url, headers=None, timeout=None):
        raise requests.ConnectionError("https://geheim.example/?apikey=SECRET")

    with pytest.raises(sh.ArchiveError) as e:
        sh.archiveer(nu=NU, basis=tmp_path, get=stuk)
    assert "SECRET" not in str(e.value)


def test_werkboek_zonder_workbook_xml_is_geen_xlsx(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("iets.txt", "x" * 20_000)
    with pytest.raises(sh.ArchiveError, match="workbook"):
        sh.valideer_xlsx(buf.getvalue())


# --------------------------------------------------------------------------
# as_of is best-effort: nooit een reden om te weigeren
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tekst, verwacht",
    [
        ("Holdings: As of 01-Oct-2026", "2026-10-01"),
        ("As of Sep 30, 2026", None),  # onbekend formaat: geen gok
        ("As of 2026-09-30", "2026-09-30"),
        ("geen datum hier", None),
    ],
)
def test_as_of_lezen(tekst, verwacht):
    uit = sh.lees_as_of(_xlsx(tekst))
    assert (uit.isoformat() if uit else None) == verwacht


def test_onleesbare_as_of_geeft_een_waarschuwing_maar_wordt_wel_bewaard(tmp_path):
    r = sh.archiveer(nu=NU, basis=tmp_path, get=_get(_xlsx("geen datum hier")))
    assert r.as_of is None
    assert any("as_of" in w for w in r.warnings)
    assert (tmp_path / r.path).exists()


def test_een_bron_die_niet_meer_ververst_geeft_een_waarschuwing(tmp_path):
    r = sh.archiveer(nu=NU, basis=tmp_path, get=_get(_xlsx("Holdings: As of 01-Sep-2026")))
    assert any("achter" in w for w in r.warnings)


# --------------------------------------------------------------------------
# Status voor de dry-run
# --------------------------------------------------------------------------


def test_status_noemt_ontbrekende_werkdagen_en_negeert_het_weekend(tmp_path):
    sh.archiveer(nu=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc), basis=tmp_path, get=_get(_xlsx()))
    sh.archiveer(nu=datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc), basis=tmp_path, get=_get(_xlsx("As of 02-Oct-2026")))
    rapport = sh.status_rapport(tmp_path, nu=datetime(2026, 10, 6, 9, 0, tzinfo=timezone.utc))

    assert "2026-10-02" in rapport  # vrijdag ontbreekt
    assert "2026-10-03" not in rapport and "2026-10-04" not in rapport  # weekend telt niet
    assert "2026-10-06" in rapport  # dinsdag is vandaag en nog niet binnen


def test_status_van_een_leeg_archief_zegt_dat_het_leeg_is(tmp_path):
    assert "leeg" in sh.status_rapport(tmp_path, nu=NU)


# --------------------------------------------------------------------------
# De CLI en de scheiding van de database
# --------------------------------------------------------------------------


def _cli():
    import importlib.util
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("archive_daily_cli", root / "archive_daily.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_cli_geeft_exit_een_bij_een_mislukte_ophaalactie_en_nul_bij_succes(tmp_path, monkeypatch):
    monkeypatch.setenv(sh.ARCHIVE_DIR_ENV, str(tmp_path))
    cli = _cli()
    monkeypatch.setattr(sh, "fetch", lambda get=None: (_ for _ in ()).throw(sh.ArchiveError("kapot")))
    assert cli.main([]) == 1

    monkeypatch.setattr(sh, "fetch", lambda get=None: _xlsx())
    assert cli.main([]) == 0
    assert cli.main([]) == 0  # tweede keer op dezelfde dag: nog steeds gelukt, niets dubbel
    assert len(sh.lees_manifest(tmp_path)) == 1


def test_archief_raakt_de_database_nooit_aan():
    """Het hele punt van een eigen proces. Geen import van storage in de module,
    dus geen schrijfactie in market_intelligence.db mogelijk."""
    bron = Path(sh.__file__).read_text(encoding="utf-8")
    assert "storage" not in bron and "sqlite3" not in bron


def test_gitignore_negeert_alleen_de_datamap_en_niet_de_code():
    """Regressie 01-10-2026: de regel `archive/` in .gitignore gold ook voor
    `src/archive/`, waardoor de module nooit gecommit werd. Lokaal werkte alles
    (het bestand bestond), op de VPS faalde de import. De datamap is alleen
    `/archive/` in de root."""
    import subprocess
    root = Path(__file__).resolve().parent.parent
    try:
        def genegeerd(pad):
            return subprocess.run(["git", "check-ignore", "-q", pad], cwd=root).returncode == 0
        code = genegeerd("src/archive/spy_holdings.py")
        data = genegeerd("archive/spy_holdings/manifest.jsonl")
    except FileNotFoundError:
        pytest.skip("git niet beschikbaar")
    assert not code, "src/archive/ wordt door .gitignore genegeerd: de code komt niet in git"
    assert data, "de datamap archive/ hoort wel genegeerd te worden"
