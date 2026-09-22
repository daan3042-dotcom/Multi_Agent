# Current Project State

**Last updated:** 2026-09-22

## Current architecture

Zie `docs/architecture.md`. Sectie A (fundament) uit `docs/roadmap.md` staat
volledig: output-contract, database-schema, data-health-checks, trigger-laag,
QC-principe, manager-dispatch. 45 tests groen (`pytest`).

## Completed

- A.1 `src/contract/output_contract.py` — `Claim` + `DomainOutput`.
- A.2 `src/storage/schema.py` — SQLite source of truth.
- A.3 `src/health/data_health.py` — staleness/onbereikbaarheid.
- A.4 `src/triggers/trigger_engine.py` — deterministische trigger-logica.
- A.5 `src/qc/qc.py` — deterministische consistentiecheck + een concrete
  default LLM-review-implementatie (`default_llm_review()`, zelfde
  dependency-injection-patroon als `analyst_agent.ai`'s
  `self_consistency.py::assess_with_consistency`), niet meer alleen een
  interface.
- A.6 `src/manager/manager.py` — dispatch-logica, gelijktijdige triggers.
- Integratietest (`tests/test_integration_section_a.py`) die het volledige
  pad — claim opslaan → data-health-check → trigger → dispatch → QC →
  deep-dive opslaan — end-to-end doorloopt met synthetische data, inclusief
  het stille-faalscenario dat A.3 specifiek moet voorkomen. Bewijst dat de
  zes A-stappen daadwerkelijk op elkaar aansluiten, niet alleen los werken.

54 tests groen (`pytest`).

## Currently working on / just finished

- Fundament (sectie A) volledig afgerond, inclusief de twee gaten die eerder
  open stonden (LLM-review was een stub, en er was geen bewijs dat de
  onderdelen samen werken). Nog niet gestart: sectie B (monetary policy +
  currency agent skeleton).

## Known problems

Geen openstaande gaten binnen sectie A's eigen scope. Bewuste grenzen (niet
gaten): A bevat geen echte domain-specifieke drempelwaarden (bijv. wélk
getal een Fed-verrassing significant maakt) — dat hoort bij sectie B/C per
domein, en staat expliciet als open beslissing in sectie H. `default_llm_review()`
is nog nooit tegen een echte Anthropic-call getest (alleen tegen een fake
client in de tests) omdat er nog geen productie-aanroep is — dat gebeurt
vanzelf zodra sectie B een domain agent bouwt die 'm daadwerkelijk aanroept.

## Next priorities

1. Sectie B: monetary policy agent (monitoring + deep-dive mode), dan
   currency agent, dan een eerste synthesizer-versie, dan end-to-end testen
   — dit is ook de eerste keer dat `default_llm_review()` tegen een echte
   Anthropic-call loopt.
2. Zodra B werkt: sectie C.1, de equity agent als dunne adapter over
   `analyst_agent.ai`'s bestaande pipeline-output.

## Open questions needing the project owner's input

Zie `docs/roadmap.md` sectie H — met name: welke domeinen continu draaien
vs. alleen on-demand, en de prioritering ICT-trading (kort) vs. macro/
mid-term (lang), aangezien dat de volgorde van sectie C kan beïnvloeden.
