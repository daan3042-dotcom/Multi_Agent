"""
archive/spy_holdings.py
Roadmap 1.2/1.4 + docs/data-archive.md, fase B: het ruwe archief (laag 1) voor
de ENIGE bron die de probe van 01-10-2026 als "archief NU (niet terug te
halen)" aanwees: de dagelijkse SPY-samenstelling van State Street.

WAT DIT DOET. Eén keer per dag het bestand ophalen, controleren dat het echt
een xlsx-werkboek is, gzippen en bewaren onder de datum van ophalen, plus één
regel in een manifest. Het bestand wordt NIET geparsed: dat zou openpyxl of
pandas nodig hebben (gecompileerde dependencies, CLAUDE.md regel 2), en
parsen kan altijd later vanuit de ruwe bytes. Het ruwe bestand is het
archief; alles wat eruit afgeleid wordt is vervangbaar.

WAAROM LOS VAN DE DATABASE EN DE DAGELIJKSE RUN (docs/data-archive.md,
"Randvoorwaarden"). T₀ᵃ hangt van de ingestie-run af; het archief mag die nooit
kunnen vertragen of laten falen. Daarom: eigen proces, eigen map, eigen log,
en GEEN schrijfactie in `market_intelligence.db`. De index is een
`manifest.jsonl` naast de bestanden (één JSON-regel per dag, alleen
toevoegen). Dat wijkt af van het eerdere voorstel "index in SQLite" en is
bewust: een archief dat de database kan vergrendelen of vervuilen is een
risico voor het enige dat niet mag falen.

ONBEKEND TOT DE EERSTE ECHTE RUN OP DE VPS (checkpoint 4). Deze module is
gebouwd in een omgeving die State Street niet kan bereiken. Dus niet
geverifieerd: (1) of de bron een User-Agent eist, (2) wélke datum de bron
bedoelt ("as of") en hoe laat die 's avonds of 's ochtends ververst wordt,
(3) of de tekst "As of" in het bestand staat zoals `lees_as_of` aanneemt. Het
laatste is bewust best-effort: lukt het niet, dan is `as_of` gewoon `null` in
het manifest en wordt er niets geweigerd. De dry-run (docs/deployment.md)
meet 1 en 2.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import requests

SOURCE = "spy_holdings"
URL = (
    "https://www.ssga.com/us/en/intermediary/etfs/library-content/products/"
    "fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
)
USER_AGENT = "Mozilla/5.0 (compatible; multi-agent-archive/1.0)"
TIMEOUT_SECONDEN = 30.0
MIN_BYTES = 10_000
"""Het bestand was 54 KB op 01-10-2026. Alles onder 10 KB is een foutpagina of
een leeg antwoord, geen holdings-bestand."""
MAX_ACHTERSTAND_DAGEN = 5
"""Een `as_of` die meer dan 5 dagen achterloopt op de ophaaldatum is een signaal
dat de bron niet meer ververst (een lang weekend is 4 dagen). Waarschuwing,
geen weigering: we bewaren wat de bron levert."""
ARCHIVE_DIR_ENV = "MI_ARCHIVE_DIR"
DEFAULT_ARCHIVE_DIR = "archive"


class ArchiveError(Exception):
    """Ophalen of controleren mislukt. Er is NIETS weggeschreven."""


@dataclass(frozen=True)
class ArchiveRecord:
    source: str
    fetched_at: str  # ISO, UTC
    as_of: str | None  # ISO-datum uit het bestand zelf, als die te lezen was
    bytes_raw: int
    bytes_gz: int
    sha256: str  # van de ruwe bytes
    path: str  # relatief aan de archiefmap
    same_as_previous: bool  # byte-identiek aan de vorige dag (weekend/feestdag)
    warnings: list[str] = field(default_factory=list)
    already_archived: bool = False  # alleen in het geheugen; niet in het manifest


def archive_dir(environ=None) -> Path:
    env = os.environ if environ is None else environ
    return Path(env.get(ARCHIVE_DIR_ENV) or DEFAULT_ARCHIVE_DIR)


def fetch(get: Callable = requests.get) -> bytes:
    """Het ruwe bestand, of een `ArchiveError`. Een 200 met HTML erin (een
    foutpagina of een cookie-muur) komt hier doorheen en wordt door
    `valideer_xlsx` tegengehouden."""
    try:
        resp = get(URL, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDEN)
    except requests.RequestException as e:
        raise ArchiveError(f"ophalen mislukt: {type(e).__name__}") from None
    if resp.status_code != 200:
        raise ArchiveError(f"bron gaf HTTP {resp.status_code}")
    return resp.content


def valideer_xlsx(data: bytes) -> None:
    """Weigert alles wat geen xlsx-werkboek is. Een xlsx is een zip met een
    `xl/workbook.xml`; zo'n controle is stdlib en vangt de gevallen die er toe
    doen (HTML-foutpagina, lege respons, afgekapte download)."""
    if len(data) < MIN_BYTES:
        raise ArchiveError(f"bestand te klein ({len(data)} bytes, minimaal {MIN_BYTES})")
    if not data.startswith(b"PK\x03\x04"):
        raise ArchiveError("geen zip/xlsx (begint niet met PK): waarschijnlijk een foutpagina")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if "xl/workbook.xml" not in z.namelist():
                raise ArchiveError("zip zonder xl/workbook.xml: geen xlsx-werkboek")
    except zipfile.BadZipFile:
        raise ArchiveError("beschadigde zip: download waarschijnlijk afgekapt") from None


_MAANDEN = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_AS_OF = re.compile(r"as\s+of[:\s]+(\d{1,2})[-\s/]([A-Za-z]{3})[A-Za-z]*[-\s/,]+(\d{4})", re.IGNORECASE)
_AS_OF_ISO = re.compile(r"as\s+of[:\s]+(\d{4})-(\d{2})-(\d{2})", re.IGNORECASE)


def lees_as_of(data: bytes) -> date | None:
    """Best-effort: de 'As of'-datum uit de gedeelde teksten van het werkboek.
    Geeft `None` bij elk probleem -- dit is een hulpmiddel voor de meting, geen
    voorwaarde voor archiveren."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            tekst = z.read("xl/sharedStrings.xml").decode("utf-8", errors="replace")
    except Exception:
        return None
    try:
        m = _AS_OF_ISO.search(tekst)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _AS_OF.search(tekst)
        if m:
            maand = _MAANDEN.get(m.group(2).lower())
            if maand:
                return date(int(m.group(3)), maand, int(m.group(1)))
    except ValueError:
        return None
    return None


def _manifest(basis: Path) -> Path:
    return basis / SOURCE / "manifest.jsonl"


def lees_manifest(basis: Path) -> list[dict]:
    pad = _manifest(basis)
    if not pad.exists():
        return []
    regels = []
    for regel in pad.read_text(encoding="utf-8").splitlines():
        if regel.strip():
            regels.append(json.loads(regel))
    return regels


def bewaar(data: bytes, nu: datetime, basis: Path) -> ArchiveRecord:
    """Valideert, gzipt, schrijft atomair, controleert het teruglezen en
    voegt één regel aan het manifest toe. Idempotent per UTC-dag: een tweede
    aanroep op dezelfde dag schrijft niets en meldt `already_archived`."""
    valideer_xlsx(data)
    dag = nu.astimezone(timezone.utc).date()
    relatief = f"{SOURCE}/{dag.year}/{SOURCE}_{dag.isoformat()}.xlsx.gz"
    doel = basis / relatief
    sha = hashlib.sha256(data).hexdigest()
    vorige = lees_manifest(basis)

    bestaand = next((r for r in vorige if r["path"] == relatief), None)
    if bestaand is not None:
        return ArchiveRecord(
            source=SOURCE, fetched_at=bestaand["fetched_at"], as_of=bestaand["as_of"],
            bytes_raw=bestaand["bytes_raw"], bytes_gz=bestaand["bytes_gz"], sha256=bestaand["sha256"],
            path=relatief, same_as_previous=bestaand["same_as_previous"], warnings=[],
            already_archived=True,
        )

    # mtime=0: dezelfde bytes geven dezelfde gz, dus het bestand is reproduceerbaar.
    gz = gzip.compress(data, compresslevel=9, mtime=0)
    doel.parent.mkdir(parents=True, exist_ok=True)
    tmp = doel.with_name(doel.name + ".tmp")
    tmp.write_bytes(gz)
    if hashlib.sha256(gzip.decompress(tmp.read_bytes())).hexdigest() != sha:
        tmp.unlink(missing_ok=True)
        raise ArchiveError("teruglezen gaf andere bytes dan weggeschreven: niets bewaard")
    os.replace(tmp, doel)

    as_of = lees_as_of(data)
    waarschuwingen: list[str] = []
    if as_of is None:
        waarschuwingen.append("as_of niet te lezen uit het bestand (formaat onbekend of veranderd)")
    elif (dag - as_of) > timedelta(days=MAX_ACHTERSTAND_DAGEN):
        waarschuwingen.append(f"as_of {as_of} loopt {(dag - as_of).days} dagen achter: ververst de bron nog?")

    record = ArchiveRecord(
        source=SOURCE,
        fetched_at=nu.astimezone(timezone.utc).isoformat(),
        as_of=as_of.isoformat() if as_of else None,
        bytes_raw=len(data),
        bytes_gz=len(gz),
        sha256=sha,
        path=relatief,
        same_as_previous=bool(vorige) and vorige[-1]["sha256"] == sha,
        warnings=waarschuwingen,
    )
    regel = {k: v for k, v in record.__dict__.items() if k != "already_archived"}
    with open(_manifest(basis), "a", encoding="utf-8") as f:
        f.write(json.dumps(regel, ensure_ascii=False) + "\n")
    return record


def archiveer(
    nu: datetime | None = None,
    basis: Path | None = None,
    get: Callable = requests.get,
) -> ArchiveRecord:
    """Ophalen + bewaren. `get` en `nu` zijn injecteerbaar zodat de tests
    nooit het netwerk of de klok aanraken."""
    nu = nu or datetime.now(timezone.utc)
    basis = basis or archive_dir()
    return bewaar(fetch(get), nu, basis)


def status_rapport(basis: Path, nu: datetime | None = None) -> str:
    """Voor de dry-run: wat staat er, en welke werkdagen ontbreken sinds de
    eerste ophaaldag. Alleen lezen."""
    nu = nu or datetime.now(timezone.utc)
    regels = lees_manifest(basis)
    if not regels:
        return f"Archief {SOURCE}: nog leeg ({basis})"
    gehad = {datetime.fromisoformat(r["fetched_at"]).date() for r in regels}
    eerste, vandaag = min(gehad), nu.astimezone(timezone.utc).date()
    ontbreekt = []
    d = eerste
    while d <= vandaag:
        if d.weekday() < 5 and d not in gehad:
            ontbreekt.append(d.isoformat())
        d += timedelta(days=1)
    totaal_gz = sum(r["bytes_gz"] for r in regels)
    identiek = sum(1 for r in regels if r["same_as_previous"])
    zonder_as_of = sum(1 for r in regels if not r["as_of"])
    uit = [
        f"Archief {SOURCE}: {len(regels)} dagen, {eerste} t/m {max(gehad)}, {totaal_gz / 1024:.0f} KB gzip in totaal",
        f"  byte-identiek aan de dag ervoor: {identiek}; zonder leesbare as_of: {zonder_as_of}",
        f"  ontbrekende werkdagen sinds de eerste ophaaldag: {', '.join(ontbreekt) if ontbreekt else 'geen'}",
    ]
    for r in regels[-5:]:
        w = f"  [{'; '.join(r['warnings'])}]" if r["warnings"] else ""
        uit.append(f"  {r['fetched_at'][:16]}  as_of={r['as_of']}  {r['bytes_raw']} B -> {r['bytes_gz']} B{w}")
    return "\n".join(uit)
