"""
env.py
Leest een `.env`-bestand in de omgeving, voor de scripts die je met de hand draait.

WAAROM DIT ER IS. `run_daily.sh` laadt `.env` (cron kent geen shell-profile),
maar `backfill.py` en `fit_baselines.py` worden met de hand gestart. Vergeet je
dan eerst `source .env`, dan mist de API-key -- en bij `fit_baselines.py`, dat
geen key nodig heeft, valt `MI_DB_PATH` stil terug op een database in de
huidige map: een lege, verkeerde database waarin alles 'mislukt', zonder dat
iets zegt waarom. Op 29-09 kostte alleen al het vergeten van `source .env` een
ronde heen en weer.

WAT HET NIET DOET. Bestaande omgevingsvariabelen worden NOOIT overschreven:
wat je expliciet zet (of wat cron/run_daily.sh al inlaadde) wint. Waarden worden
nooit getoond of gelogd.

Bewust een eigen mini-parser en geen `python-dotenv` (CLAUDE.md regel 2: geen
nieuwe dependency waar vermijdbaar). Ondersteund: `SLEUTEL=waarde`, optionele
enkele of dubbele aanhalingstekens, lege regels en `#`-commentaar. Geen
variabele-expansie, geen `export`-voorvoegsel: `.env.example` gebruikt ze niet.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | os.PathLike) -> list[str]:
    """Zet de variabelen uit `path` in `os.environ`, zonder bestaande te
    overschrijven. Geeft de NAMEN terug van de variabelen die zijn gezet (nooit
    de waarden). Ontbreekt het bestand, dan is dat geen fout: lege lijst."""
    bestand = Path(path)
    if not bestand.is_file():
        return []
    gezet: list[str] = []
    for regel in bestand.read_text(encoding="utf-8").splitlines():
        regel = regel.strip()
        if not regel or regel.startswith("#") or "=" not in regel:
            continue
        naam, _, waarde = regel.partition("=")
        naam, waarde = naam.strip(), waarde.strip()
        if len(waarde) >= 2 and waarde[0] == waarde[-1] and waarde[0] in "'\"":
            waarde = waarde[1:-1]
        if not naam or naam in os.environ:
            continue
        # Een lege waarde (bijv. `MI_COHORT=`) telt als 'niet ingesteld': het
        # bestand .env.example laat sleutels leeg staan met precies die betekenis.
        if waarde == "":
            continue
        os.environ[naam] = waarde
        gezet.append(naam)
    return gezet
