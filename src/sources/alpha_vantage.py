"""
sources/alpha_vantage.py
Gedeelde Alpha Vantage-aanroep voor de sector-, currency- en commodity-agent (roadmap 1.3/1.11, 02-10-2026).

WAAROM DIT BESTAAT. Op 02-10-2026 miste de eerste T₀ᵃ-dag één van de twaalf sectorreeksen (`xlp_consumer_staples`) en
de dag telde niet. Het log zei niets over het waarom: de drie `_fetch_*`-helpers vingen elke fout op met
`except Exception: return None`, ook een "Note"/"Information"-melding van Alpha Vantage zelf. Dat botst met de
herleidbaarheidseis (elke beslissing is terug te vinden). Twee dingen, en niet meer:

1. ELKE MISLUKTE REEKS KRIJGT EEN GELOGDE REDEN (HTTP-status, time-out, verbindingsfout, de tekst van Alpha Vantage's
   eigen melding, een lege respons).
2. ÉÉN HERHAALPOGING voor wat in de eerste ronde ontbrak, na één gezamenlijke pauze. Op een goede dag verandert er
   niets (geen mislukking, geen pauze).

WAT DIT BEWUST NIET DOET
  - De completeness-check (`health/`, `triggers/`) blijft ongewijzigd. Een reeks die ook na de herhaling ontbreekt,
    blijft een volledigheidstrigger en laat de dag niet-schoon tellen. Een herhaling mag een gat dichten, nooit een
    gat verbergen: de uitkomst van de herhaling wordt gelogd.
  - Geen tweede herhaling, geen terugvalbron, geen gegokte waarde.

DE API-SLEUTEL STAAT NOOIT IN HET LOG. Een `requests`-uitzondering bevat in zijn tekst vaak de volledige URL, dus
inclusief `apikey=...`. Daarom loggen we van een uitzondering alleen het TYPE (en bij HTTP de statuscode), en wordt in
Alpha Vantage's eigen meldingen de sleutel vervangen. Een test bewaakt dit.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Iterable, TypeVar

import requests

BASE_URL = "https://www.alphavantage.co/query"
TIMEOUT_SECONDEN = 15

# Eén pauze vóór de herhaalronde. Alpha Vantage's limieten zijn per MINUUT en per dag; 30 seconden is geen garantie
# dat een minutenlimiet vrij is, maar de herhaling is bedoeld voor het incidentele gat (zo'n 1 van 12), niet voor een
# structureel tekort. Blijft hetzelfde gat terugkomen, dan staat de reden in het log en beslissen we met dat gegeven.
RETRY_PAUZE_SECONDEN = 30
MAX_REDEN_TEKENS = 160

# Sleutels waarmee Alpha Vantage zelf een probleem meldt, in een antwoord met HTTP 200.
MELDING_SLEUTELS = ("Note", "Information", "Error Message")

log = logging.getLogger("sources.alpha_vantage")
T = TypeVar("T")


def _slaap(seconden: float) -> None:
    """Apart zodat tests de pauze kunnen vervangen (tests/conftest.py) zonder `time.sleep` globaal aan te raken."""
    time.sleep(seconden)


def _schoon(tekst: str, sleutel: str | None) -> str:
    tekst = " ".join(str(tekst).split())
    if sleutel:
        tekst = tekst.replace(sleutel, "***")
    return tekst[:MAX_REDEN_TEKENS]


def haal_json(params: dict, get: Callable | None = None) -> tuple[dict | None, str | None]:
    """Eén Alpha Vantage-aanroep. Geeft (antwoord, None) bij succes of (None, reden) bij een mislukking. Gooit nooit."""
    sleutel = params.get("apikey")
    aanroep = get or requests.get  # opgezocht bij het aanroepen: tests vervangen `requests.get`
    try:
        resp = aanroep(BASE_URL, params=params, timeout=TIMEOUT_SECONDEN)
        resp.raise_for_status()
        payload = resp.json()
    except requests.Timeout:
        return None, "time-out"
    except requests.ConnectionError:
        return None, "verbindingsfout"
    except requests.HTTPError as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        return None, f"HTTP {status}" if status else "HTTP-fout"
    except ValueError:
        return None, "antwoord is geen geldige JSON"
    except Exception as e:  # noqa: BLE001 -- bewust breed, maar alleen het TYPE loggen (de tekst kan de sleutel bevatten)
        return None, f"onverwachte fout ({type(e).__name__})"
    if not isinstance(payload, dict):
        return None, "onverwacht antwoordtype"
    for naam in MELDING_SLEUTELS:
        if payload.get(naam):
            return None, f"Alpha Vantage meldt ({naam}): {_schoon(payload[naam], sleutel)}"
    return payload, None


def verzamel(
    domein: str,
    sleutels: Iterable[str],
    haal_een: Callable[[str], tuple[T | None, str | None]],
    slaap: Callable[[float], None] | None = None,
) -> dict[str, T]:
    """Haalt elke sleutel op; wat mislukt krijgt een gelogde reden en wordt na ÉÉN pauze ÉÉN keer opnieuw geprobeerd.

    `haal_een(sleutel)` geeft (resultaat, None) of (None, reden). Geeft alleen de gelukte sleutels terug: een
    ontbrekende reeks blijft ontbreken (de completeness-check ziet dat), er wordt nooit iets verzonnen."""
    sleutels = list(sleutels)
    uitkomst: dict[str, T] = {}
    mislukt: dict[str, str] = {}
    for s in sleutels:
        resultaat, reden = haal_een(s)
        if resultaat is None:
            mislukt[s] = reden or "geen reden bekend"
            log.warning("Alpha Vantage %s: %s mislukt in de eerste ronde: %s", domein, s, mislukt[s])
        else:
            uitkomst[s] = resultaat
    if not mislukt:
        return uitkomst

    log.info("Alpha Vantage %s: %d van %d reeksen ontbreken; herhaling na %d s", domein, len(mislukt), len(sleutels),
             RETRY_PAUZE_SECONDEN)
    (slaap or _slaap)(RETRY_PAUZE_SECONDEN)
    for s in list(mislukt):
        resultaat, reden = haal_een(s)
        if resultaat is None:
            log.warning("Alpha Vantage %s: %s blijft ontbreken na herhaling: %s (eerste ronde: %s)",
                        domein, s, reden or "geen reden bekend", mislukt[s])
        else:
            uitkomst[s] = resultaat
            log.info("Alpha Vantage %s: %s hersteld bij herhaling (eerste ronde: %s)", domein, s, mislukt[s])
    log.info("Alpha Vantage %s: %d van %d reeksen na herhaling", domein, len(uitkomst), len(sleutels))
    return uitkomst
