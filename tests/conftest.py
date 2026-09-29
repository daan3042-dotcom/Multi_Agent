"""
conftest.py
Zorgt dat de omgeving van de machine waarop de tests draaien de tests niet
kan beïnvloeden.

WAAROM DIT BESTAAT. Op de VPS staat `MI_COHORT` straks in de omgeving (op
T₀ᵇ: `MI_COHORT=cohort_0`), en het deployment-runbook draait `pytest` vóór
elke uitrol. Zonder deze fixture zouden tests die de default `dry_run`
verwachten daar falen -- of erger: tests die voorspellingen aanmaken zouden
ze onder het ECHTE cohort wegschrijven. Elke test begint dus zonder
`MI_COHORT`; tests die het nodig hebben zetten het zelf.
"""

import pytest


@pytest.fixture(autouse=True)
def _geen_cohort_uit_de_omgeving(monkeypatch):
    monkeypatch.delenv("MI_COHORT", raising=False)
