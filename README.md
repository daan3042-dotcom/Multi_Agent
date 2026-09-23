# Market Intelligence Multi-Agent Systeem

Nieuw systeem naast [`analyst_agent.ai`](https://github.com/daan3042-dotcom/analyst_agent.ai),
later gekoppeld als equity-subagent. Doel: doorlopende monitoring per
vakgebied (monetary policy, currency, equity, financial, sector, commodity,
economic) die on-demand deep-dives triggert, gesynthetiseerd tot bruikbare
marktintelligentie — incl. een dagelijkse Nasdaq/NQ-regime-agent en een news
monitor agent.

Volledige planning: `docs/roadmap.md`. Huidige status: `docs/project-state.md`.
**Wat elke agent daadwerkelijk doet (zonder code te lezen): `docs/agents.md`.**

## Status

Fundament (sectie A) + de eerste drie domain agents staan: monetary policy,
currency (sectie B) en equity (C.1, een adapter over `analyst_agent.ai`'s
bestaande output). Zie `docs/agents.md` voor wat elk van hen concreet volgt
en wanneer ze triggeren.

## Setup

```bash
pip install -r requirements.txt
```

Voor de monetary policy en currency agent: `FRED_API_KEY` resp.
`ALPHAVANTAGE_API_KEY` in de environment. Voor een echte deep-dive-call
(i.p.v. de fake client die de tests gebruiken): `ANTHROPIC_API_KEY`.

## Tests

```bash
pytest
```

`pytest.ini` zet `pythonpath = src`, geen handmatige setup nodig.

## Project structure & documentation

- `CLAUDE.md` — projectbriefing
- `docs/agents.md` — wat elke agent doet, in gewone taal (start hier)
- `docs/architecture.md` — modulekaart en datastroom
- `docs/roadmap.md` — volledige planning (levend document, afvinkbaar)
- `docs/project-state.md` — actuele status

## Taal

Net als `analyst_agent.ai`: inline comments en documentatie zijn in het
Nederlands — een bewuste, consistente keuze.
