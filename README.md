# Market Intelligence Multi-Agent Systeem

Nieuw systeem naast [`analyst_agent.ai`](https://github.com/daan3042-dotcom/analyst_agent.ai),
later gekoppeld als equity-subagent. Doel: doorlopende monitoring per
vakgebied (monetary policy, currency, equity, financial, sector, commodity,
economic) die on-demand deep-dives triggert, gesynthetiseerd tot bruikbare
marktintelligentie — incl. een dagelijkse Nasdaq/NQ-regime-agent en een news
monitor agent.

Volledige planning: `docs/roadmap.md`. Huidige status: `docs/project-state.md`.

## Status

Sectie A (fundament) staat: elke domain agent zal straks tegen hetzelfde
contract, dezelfde database, dezelfde trigger- en QC-laag draaien.

## Setup

```bash
pip install -r requirements.txt
```

Geen API-keys nodig voor het fundament zelf (sectie A) — die komen met de
eerste domain agents (sectie B).

## Tests

```bash
pytest
```

`pytest.ini` zet `pythonpath = src`, geen handmatige setup nodig.

## Project structure & documentation

- `CLAUDE.md` — projectbriefing
- `docs/architecture.md` — modulekaart en datastroom van sectie A
- `docs/roadmap.md` — volledige planning (levend document, afvinkbaar)
- `docs/project-state.md` — actuele status

## Taal

Net als `analyst_agent.ai`: inline comments en documentatie zijn in het
Nederlands — een bewuste, consistente keuze.
