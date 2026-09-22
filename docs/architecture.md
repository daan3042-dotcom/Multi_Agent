# Architecture — sectie A (fundament)

Zie `docs/roadmap.md` voor de volledige planning. Dit document beschrijft
alleen wat er al staat.

## Modulekaart (`src/`)

| Module | Rol | Roadmap-stap |
|---|---|---|
| `contract/output_contract.py` | `Claim` en `DomainOutput` — de vorm waar elke domain agent zich aan houdt | A.1 |
| `storage/schema.py` | SQLite source of truth: claims, trigger-events, data-health | A.2 |
| `health/data_health.py` | Staleness/onbereikbaarheid per databron, vóór de trigger-laag | A.3 |
| `triggers/trigger_engine.py` | Deterministische escalatiebeslissingen (drempel, verrassing, data-health) | A.4 |
| `qc/qc.py` | Deterministische consistentiecheck + optionele lichte LLM-review, `NEEDS_REVIEW` | A.5 |
| `manager/manager.py` | Dispatch: groepeert `TriggerEvent`s per domein, signaleert gelijktijdige triggers | A.6 |

## Datastroom (zoals sectie A hem vastlegt)

```
domain agent (monitoring mode, buiten scope van dit fundament — sectie B+)
       │  produceert Claim(s), leest data-health voor de bronnen die het gebruikt
       ▼
storage.schema.save_domain_output()      ── source of truth
       │
       ▼
health.data_health.check_source()  ──►  triggers.trigger_engine.evaluate_data_health()
storage.schema.load_latest_claims() ──► triggers.trigger_engine.evaluate_threshold() /
                                          evaluate_surprise()
       │  (TriggerEvent, of None als niets significant is)
       ▼
manager.manager.dispatch()  ── groepeert TriggerEvents tot een DispatchPlan
       │  (welke domain agent(s) moeten escaleren naar deep-dive mode,
       │   is_simultaneous voor de synthesizer)
       ▼
[buiten scope van sectie A: domain agent deep-dive mode → qc.qc.apply_qc() →
 storage.schema.save_domain_output() (mode=DEEP_DIVE) → synthesizer (sectie F)]
```

## Ontwerpkeuzes die van `analyst_agent.ai` zijn overgenomen (en waarom)

- **Deterministisch waar mogelijk, LLM alleen waar het moet.** De hele
  trigger-laag (A.4) en de manager (A.6) zijn LLM-vrij — dezelfde
  "Python computes, Claude narrates"-regel als `analyst_agent.ai/CLAUDE.md`,
  hier toegepast op "moet dit escaleren" in plaats van op cijfers in een
  rapport.
- **Claim-structuur i.p.v. los cijfer.** `Claim` generaliseert
  `lineage.py::build_lineage_manifest()`'s `{metric, value, source, period,
  note}`-items, met `confidence` en `timestamp` toegevoegd omdat dit systeem
  doorlopend draait (claims verouderen) in plaats van één rapport op één
  moment.
- **`metric_key` als optioneel, machine-checkbaar veld.** Zelfde onderscheid
  als `track_record.py` maakt tussen de platte tekst van sectie 17 en de
  `structured_kill_criteria`: alleen claims met een `metric_key` zijn later
  automatisch tegen een drempel te controleren.
- **`NEEDS_REVIEW` i.p.v. blokkeren.** `qc.qc.apply_qc()` volgt
  `analyst_agent.ai`'s eigen regel ("don't let `NEEDS_REVIEW` reports be
  treated as a bug to fix away") — een lichte, pluggable review (géén 4
  parallelle reviewers, dat past niet bij doorlopend achtergronddraaien),
  die een vlag zet in plaats van iets tegenhoudt.
- **SQLite via de standaardbibliotheek.** Geen nieuwe, mogelijk
  gecompileerde dependency — zelfde principe als `ADR-003` in
  `analyst_agent.ai` (geen gecompileerde dependencies waar vermijdbaar).

## Wat hierna komt

Sectie B (`docs/roadmap.md`): monetary policy + currency agent als eerste
twee domain agents, elk met monitoring- en deep-dive-mode, gebouwd bovenop
dit fundament.
