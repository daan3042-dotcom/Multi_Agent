"""
test_spy_meting.py
De alleen-lezen meting van de SPY-bron (`archive/spy_meting.py`, `meet_spy_asof.py`). 02-10-2026.
Geen netwerk, geen echte klok: `get` en `nu` worden meegegeven.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import requests

from archive import spy_meting as sm

ROOT = Path(__file__).resolve().parent.parent
NU = datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc)


def _xlsx(tekst="Holdings: As of 01-Oct-2026", vulling=12_000) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/sharedStrings.xml", f"<sst><si><t>{tekst}</t></si></sst>")
        z.writestr("xl/worksheets/sheet1.xml", "x" * vulling)
    return buf.getvalue()


def test_de_regel_toont_tijdstip_as_of_grootte_vingerafdruk_en_de_koppen_van_de_bron():
    data = _xlsx()

    def get(url, headers, timeout):
        return SimpleNamespace(status_code=200, content=data, headers={
            "Last-Modified": "Thu, 01 Oct 2026 21:05:00 GMT", "ETag": '"abc"', "Date": "Fri, 02 Oct 2026 16:00:01 GMT",
        })

    regel, gelukt = sm.meet(get, nu=NU)
    assert gelukt
    assert regel.startswith("2026-10-02 16:00 UTC  as_of=2026-10-01  bytes=")
    assert f"bytes={len(data)}" in regel and f"sha={hashlib.sha256(data).hexdigest()[:12]}" in regel
    assert "last-modified=Thu, 01 Oct 2026 21:05:00 GMT" in regel and 'etag="abc"' in regel and "date=Fri, 02 Oct 2026" in regel


def test_ontbrekende_koppen_worden_een_streepje_en_een_onleesbare_as_of_wordt_gemeld():
    data = _xlsx(tekst="geen datum hier")

    def get(url, headers, timeout):
        return SimpleNamespace(status_code=200, content=data, headers={})

    regel, gelukt = sm.meet(get, nu=NU)
    assert gelukt and "as_of=onleesbaar" in regel and "last-modified=-" in regel and "etag=-" in regel


def test_een_mislukking_wordt_een_regel_en_nooit_een_crash():
    def weg(url, headers, timeout):
        raise requests.ConnectionError("netwerk met intern adres 10.0.0.1")

    regel, gelukt = sm.meet(weg, nu=NU)
    assert not gelukt and regel.endswith("FOUT ophalen mislukt: ConnectionError") and "10.0.0.1" not in regel

    def fout(url, headers, timeout):
        return SimpleNamespace(status_code=503, content=b"", headers={})

    assert sm.meet(fout, nu=NU) == ("2026-10-02 16:00 UTC  FOUT bron gaf HTTP 503", False)

    def html(url, headers, timeout):
        return SimpleNamespace(status_code=200, content=b"<html>cookie-muur</html>" * 1000, headers={})

    regel, gelukt = sm.meet(html, nu=NU)
    assert not gelukt and "FOUT geen geldig werkboek" in regel


def test_de_meting_gebruikt_dezelfde_bron_en_user_agent_als_het_archief():
    gezien = {}
    data = _xlsx()

    def get(url, headers, timeout):
        gezien.update(url=url, ua=headers["User-Agent"], timeout=timeout)
        return SimpleNamespace(status_code=200, content=data, headers={})

    sm.meet(get, nu=NU)
    from archive import spy_holdings as sh

    assert gezien == {"url": sh.URL, "ua": sh.USER_AGENT, "timeout": sh.TIMEOUT_SECONDEN}


def test_het_script_schrijft_niets_en_geeft_de_juiste_exitcode(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MI_ARCHIVE_DIR", str(tmp_path / "archief"))
    data = _xlsx()
    monkeypatch.setattr(requests, "get", lambda url, headers, timeout: SimpleNamespace(
        status_code=200, content=data, headers={}))
    spec = importlib.util.spec_from_file_location("meet_spy_asof_script", ROOT / "meet_spy_asof.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main([]) == 0
    assert "as_of=2026-10-01" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []  # geen archief, geen manifest, niets

    monkeypatch.setattr(requests, "get", lambda url, headers, timeout: SimpleNamespace(status_code=500, content=b"", headers={}))
    assert script.main([]) == 1


def test_de_module_schrijft_niets_weg():
    tekst = (ROOT / "src" / "archive" / "spy_meting.py").read_text()
    code = "\n".join(r for r in tekst.splitlines() if not r.lstrip().startswith("#"))
    for verboden in ("open(", "write_", ".write(", "bewaar(", "archiveer(", "sqlite3", "os.replace", "mkdir"):
        assert verboden not in code, verboden
