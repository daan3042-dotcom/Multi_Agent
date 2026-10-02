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


@pytest.fixture(autouse=True)
def _geen_echte_pauze_bij_alpha_vantage(monkeypatch):
    """De herhaalpoging van `sources/alpha_vantage.py` wacht 30 seconden. In een test mag dat nooit echt gebeuren:
    elke test waarbij een reeks mislukt zou anders een halve minuut stilstaan. Tests die de pauze willen zien, geven
    zelf een `slaap` mee of vervangen `_slaap` opnieuw."""
    from sources import alpha_vantage

    monkeypatch.setattr(alpha_vantage, "_slaap", lambda seconden: None)
