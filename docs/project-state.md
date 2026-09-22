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
- A.5 `src/qc/qc.py` — deterministische consistentiecheck + pluggable LLM-review.
- A.6 `src/manager/manager.py` — dispatch-logica, gelijktijdige triggers.

## Currently working on / just finished

- Fundament (sectie A) zojuist afgerond. Nog niet gestart: sectie B
  (monetary policy + currency agent skeleton).

## Known problems

Geen — dit is nieuwe code zonder productie-gebruik. `qc.qc.apply_qc()`'s
deterministische check is een eerste, ruwe versie (zoekt cijfers dicht bij
een `metric_key`/claim-tekst) — kan false positives geven bij zeer dichte
tekst; nog niet tegen echte deep-dive-output getest omdat er nog geen
domain agent bestaat die deep-dive-tekst produceert.

## Next priorities

1. Sectie B: monetary policy agent (monitoring + deep-dive mode), dan
   currency agent, dan een eerste synthesizer-versie, dan end-to-end testen.
2. Zodra B werkt: sectie C.1, de equity agent als dunne adapter over
   `analyst_agent.ai`'s bestaande pipeline-output.

## Open questions needing the project owner's input

Zie `docs/roadmap.md` sectie H — met name: welke domeinen continu draaien
vs. alleen on-demand, en de prioritering ICT-trading (kort) vs. macro/
mid-term (lang), aangezien dat de volgorde van sectie C kan beïnvloeden.
