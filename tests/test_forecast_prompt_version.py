"""
test_forecast_prompt_version.py
Bewaakt dat `FORECAST_PROMPT_VERSION` meebeweegt met de prompt waarmee een
agent voorspelt (roadmap 2.0 / 4.1).

WAAROM DIT EEN TEST IS. Elke prediction draagt `prompt_version` (CLAUDE.md,
"Wie berekent de kans"). Een promptwijziging binnen een cohort is een
covariaat en geen nieuw cohort -- maar dan moet je achteraf wél kunnen zien
wélke voorspellingen onder welke prompt zijn gedaan. Verandert iemand een
prompt zonder het versienummer op te hogen, dan staan er twee verschillende
prompts onder hetzelfde label en is dat deel van het cohort niet meer te
analyseren. Dat merk je pas bij de evaluatie, maanden later, als de data er
al is en er niets meer aan te doen valt.

Een prompt bewerken is één regel; het effect op de scoring is onzichtbaar.
Deze test maakt het zichtbaar op het moment dat de regel geschreven wordt --
zelfde patroon als test_api_budget.py.

ALS DEZE TEST FAALT: dat is geen bug in de test. Verhoog
FORECAST_PROMPT_VERSION in de betrokken agent-module (v1 -> v2) en werk de
hash hieronder bij, in dezelfde commit als de promptwijziging.
"""

from __future__ import annotations

import hashlib

import pytest

from agents import (
    currency_agent,
    economic_agent,
    financial_agent,
    monetary_policy_agent,
    sector_agent,
)
from agents.base import FORECAST_SYSTEM_RULES

AGENTS = {
    "monetary_policy": monetary_policy_agent,
    "currency": currency_agent,
    "financial": financial_agent,
    "sector": sector_agent,
    "economic": economic_agent,
}

# Vastgelegd op 28-09-2026 (v1) en bijgewerkt op 01-10-2026 (v2: vijf kwantielen in
# FORECAST_SYSTEM_RULES, contract v1; v3: regel 6 over de context + de evidence-sheet;
# 02-10-2026: de hash bevat nu ook de vingerafdruk van de evidence-sheet, zie runtime/freeze_guard.py).
# Versie + hash horen bij elkaar: verandert de prompt, dan verandert de
# hash, en dan hoort de versie mee te veranderen.
VERWACHT = {
    "monetary_policy": ("v3", "0a7fd2010f1e18fe"),
    "currency": ("v3", "603aef030d01c3c8"),
    "financial": ("v3", "35b9c3f6d622bf2d"),
    "sector": ("v3", "4c61a11a74a11437"),
    "economic": ("v3", "c73f8f5ac5651b61"),
}


def _forecast_prompt(module) -> str:
    """Exact wat `run_forecast_round` als system prompt meestuurt."""
    return f"{FORECAST_SYSTEM_RULES}\n\n{module.DEEP_DIVE_SYSTEM_PROMPT}"


def _hash(module) -> str:
    """Systeemprompt + evidence-sheet (sinds 02-10-2026): verandert de context die een agent krijgt, dan verandert deze
    hash, en moet FORECAST_PROMPT_VERSION omhoog. De ene definitie staat in runtime/freeze_guard.py."""
    from runtime.freeze_guard import forecast_prompt_hash

    return forecast_prompt_hash(module)


@pytest.mark.parametrize("domain", sorted(AGENTS))
def test_prompt_is_unchanged_or_version_was_bumped(domain):
    module = AGENTS[domain]
    verwachte_versie, verwachte_hash = VERWACHT[domain]
    werkelijke_hash = _hash(module)

    assert module.FORECAST_PROMPT_VERSION == verwachte_versie, (
        f"{domain}: FORECAST_PROMPT_VERSION staat op "
        f"{module.FORECAST_PROMPT_VERSION}, deze test verwacht "
        f"{verwachte_versie}. Werk VERWACHT hierboven bij (versie + hash "
        f"{werkelijke_hash})."
    )
    assert werkelijke_hash == verwachte_hash, (
        f"{domain}: de forecast-prompt is gewijzigd (hash {werkelijke_hash}, "
        f"verwacht {verwachte_hash}) zonder dat FORECAST_PROMPT_VERSION "
        f"omhoog ging. Verhoog hem in src/agents/{domain}_agent.py en zet "
        f"hier ('{module.FORECAST_PROMPT_VERSION}' -> nieuwe versie, "
        f"'{werkelijke_hash}')."
    )


def test_every_forecasting_agent_has_a_version():
    """Een nieuwe voorspellende agent zonder versienummer zou stilzwijgend
    'v0' krijgen van `runtime.daily._spec` -- dat mag niet onopgemerkt
    blijven."""
    for domain, module in AGENTS.items():
        assert getattr(module, "FORECAST_PROMPT_VERSION", None), domain


def test_de_vormregels_tellen_mee_in_de_versie():
    """FORECAST_SYSTEM_RULES staat in agents/base.py en geldt voor ALLE
    agents. Een wijziging daar raakt dus alle vijf de versienummers -- dat
    is de bedoeling, en daarom zit hij in de hash."""
    assert FORECAST_SYSTEM_RULES in _forecast_prompt(monetary_policy_agent)
