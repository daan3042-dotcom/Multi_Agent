"""
archive/spy_meting.py
Eén regel meting van de SPY-holdingsbron, ALLEEN LEZEN: wanneer verschijnt welke `as_of`? (docs/data-archive.md,
checkpoint 4, 02-10-2026).

AANLEIDING. Op 02-10 om 08:30 UTC stond de `as_of` van het archief nog op 30-09, twee handelsdagen achter. Het archief
bewaart per UTC-dag maar één bestand (het eerste), dus als de bron pas later op de dag ververst, bewaart de cron elke dag
een verouderde versie. Dat is alleen te beoordelen met metingen over de dag heen. `archive_daily.py` kan dat niet: een
tweede aanroep op dezelfde dag doet bewust niets.

WAT DIT DOET. Het bestand ophalen (zelfde URL en User-Agent als het archief), de `as_of` lezen, en één regel teruggeven met
ook wat de bron zelf over verversing zegt (Last-Modified, ETag, Date). WAT HET NIET DOET: niets bewaren, het manifest of het
archief niet aanraken, geen database. Een mislukking wordt een regel, geen crash.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable

import requests

from archive import spy_holdings as sh


def meet(get: Callable | None = None, nu: datetime | None = None) -> tuple[str, bool]:
    """(regel, gelukt). Gooit nooit."""
    aanroep = get or requests.get  # opgezocht bij het aanroepen, zodat een test requests.get kan vervangen
    nu = (nu or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stempel = nu.strftime("%Y-%m-%d %H:%M UTC")
    try:
        resp = aanroep(sh.URL, headers={"User-Agent": sh.USER_AGENT}, timeout=sh.TIMEOUT_SECONDEN)
    except requests.RequestException as e:
        return f"{stempel}  FOUT ophalen mislukt: {type(e).__name__}", False
    if resp.status_code != 200:
        return f"{stempel}  FOUT bron gaf HTTP {resp.status_code}", False
    data = resp.content
    try:
        sh.valideer_xlsx(data)
    except sh.ArchiveError as e:
        return f"{stempel}  FOUT geen geldig werkboek: {e}", False
    as_of = sh.lees_as_of(data)
    koppen = getattr(resp, "headers", None) or {}

    def kop(naam: str) -> str:
        waarde = koppen.get(naam)
        return str(waarde) if waarde else "-"

    regel = (
        f"{stempel}  as_of={as_of.isoformat() if as_of else 'onleesbaar'}  bytes={len(data)}  "
        f"sha={hashlib.sha256(data).hexdigest()[:12]}  last-modified={kop('Last-Modified')}  "
        f"etag={kop('ETag')}  date={kop('Date')}"
    )
    return regel, True
