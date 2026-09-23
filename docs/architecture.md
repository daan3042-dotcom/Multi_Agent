# Architecture — sectie A (fundament) + sectie B (eerste domain agents)

Zie `docs/roadmap.md` voor de volledige planning. Dit document beschrijft
alleen wat er al staat.

## Modulekaart (`src/`)

| Module | Rol | Roadmap-stap |
|---|---|---|
| `contract/output_contract.py` | `Claim` en `DomainOutput` — de vorm waar elke domain agent zich aan houdt | A.1 |
| `storage/schema.py` | SQLite source of truth: claims, trigger-events, data-health | A.2 |
| `health/data_health.py` | Staleness/onbereikbaarheid per databron, vóór de trigger-laag | A.3 |
| `triggers/trigger_engine.py` | Deterministische escalatiebeslissingen (drempel, verrassing, data-health) | A.4 |
| `qc/qc.py` | Deterministische consistentiecheck + `default_llm_review()` (concrete, pluggable LLM-review), `NEEDS_REVIEW` | A.5 |
| `manager/manager.py` | Dispatch: groepeert `TriggerEvent`s per domein, signaleert gelijktijdige triggers | A.6 |
| `agents/base.py` | Gedeelde scaffolding: `run_monitoring()` (databron → claims → delta-trigger) + `run_deep_dive()` (LLM-synthese → QC → opslag) + `SHARED_QUALITY_RULES` (centrale schrijfregels, voor élke deep-dive) | B.1/B.2 |
| `agents/monetary_policy_agent.py` | FRED (Fed funds rate, 10Y yield, CPI-index, werkloosheid) — alleen vakinhoudelijke deep-dive-prompt | B.1 |
| `agents/currency_agent.py` | Alpha Vantage FX (EUR/USD, USD/JPY, GBP/USD) — alleen vakinhoudelijke deep-dive-prompt | B.2 |
| `synthesizer/synthesizer.py` | Legt gelijktijdige deep-dives naast elkaar (nog geen cross-domein-synthese) | B.3 |

## Datastroom (zoals sectie A + B hem nu vastleggen)

```
agents.<domain>_agent.fetch_snapshot()  ── eigen databron (FRED / Alpha Vantage FX)
       │
       ▼
agents.base.run_monitoring()
       │  record_data_health() → health.data_health.check_source()
       │       └─► triggers.trigger_engine.evaluate_data_health()  (STALE/UNREACHABLE → eigen trigger, A.3)
       │  bouwt Claim(s) per metric → storage.schema.save_domain_output() (mode=MONITORING)
       │  vergelijkt elke nieuwe claim tegen de vorige observatie (load_latest_claims(), VÓÓR opslaan opgehaald)
       │       └─► triggers.trigger_engine.evaluate_surprise()  (delta > tolerance → TriggerEvent)
       ▼
manager.manager.dispatch(alle TriggerEvents uit deze cyclus, over alle domeinen)
       │  groepeert per domein tot een DispatchPlan; is_simultaneous als >1 domein escaleert
       ▼
agents.base.run_deep_dive()  (per geëscaleerd domein, met zijn eigen TriggerEvents + Claims)
       │  system-prompt = SHARED_QUALITY_RULES + domein-specifieke DEEP_DIVE_SYSTEM_PROMPT
       │  Claude-call (dependency-injected client)
       │  qc.qc.apply_qc() incl. qc.qc.default_llm_review() → NEEDS_REVIEW
       │  narrative-Claim (value=deep-dive-tekst) toegevoegd aan de claims
       │  storage.schema.save_domain_output() (mode=DEEP_DIVE)
       ▼
synthesizer.synthesizer.synthesize_simultaneous(plan, {domain: deep_dive_output, ...})
       │  legt de deep-dives van de domeinen in plan.domains naast elkaar
       ▼
[buiten scope van sectie B: cross-domein-synthese, confidence-weging → sectie F]
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
  die een vlag zet in plaats van iets tegenhoudt. `qc.qc.default_llm_review()`
  is de concrete default-implementatie daarvan: dependency-injected
  `client`-parameter (zelfde patroon als `self_consistency.py`), en geeft
  bij een mislukte call altijd minstens één issue-string terug — nooit
  stilzwijgend een lege lijst, want dat zou "gereviewd, niets gevonden"
  claimen zonder dat er echt gereviewd is.
- **SQLite via de standaardbibliotheek.** Geen nieuwe, mogelijk
  gecompileerde dependency — zelfde principe als `ADR-003` in
  `analyst_agent.ai` (geen gecompileerde dependencies waar vermijdbaar).
- **Eigen databron-implementatie per domain agent, geen import van
  `analyst_agent.ai`.** `agents/monetary_policy_agent.py` en
  `agents/currency_agent.py` volgen dezelfde conventie als diens
  `fred_data.py`/`commodity_data.py` (env-var API-key, `{"error": ...}` bij
  volledige mislukking, ontbrekende reeksen overslaan i.p.v. gokken) maar
  zijn zelfstandige code — dit is een nieuw systeem náást `analyst_agent.ai`
  (zie `CLAUDE.md`), alleen de equity agent (C.1) adapteert straks diens
  bestaande output rechtstreeks.
- **Trigger op delta, niet op een vaste absolute drempel.** B.1/B.2
  vergelijken elke nieuwe observatie tegen de vorige (`evaluate_surprise()`
  met `expected_value` = de vorige claim) in plaats van tegen een
  hardgecodeerd "hoog/laag"-niveau — welk absoluut niveau significant is,
  is een bewust open beslissing (sectie H). De `tolerance`-waarden in
  `METRIC_SPECS` zijn illustratieve plaatshouders.

## Gedeelde kwaliteitsregels voor élke deep-dive (`agents/base.py::SHARED_QUALITY_RULES`)

Elke domain agent schreef eerst zijn eigen neutraliteits-/kwaliteitsregels
los in zijn `DEEP_DIVE_SYSTEM_PROMPT` — dat zou bij elke nieuwe agent
(sectie C+) verder uit elkaar gaan lopen. Nu geldt: `run_deep_dive()` plakt
`SHARED_QUALITY_RULES` automatisch vóór de domein-specifieke prompt; een
domain agent levert alleen nog vakinhoud. Tegenhanger van
`analyst_agent.ai`'s `framework.py::SYSTEM_PROMPT` (concrete, verboden
formuleringen i.p.v. vage "wees neutraal"-instructies), hier centraal
gehouden in plaats van per rapport-sectie herhaald.

Wat de regels concreet afdwingen:
- **Geen koop/verkoop-advies of koersdoel**, met expliciet verboden
  formuleringen (zelfde stijl als `framework.py`'s "VERBODEN patronen").
- **Alleen de aangeleverde claims** — geen zelf berekende of verzonnen
  cijfers; ontbrekende afleidbaarheid moet met zoveel woorden benoemd
  worden in plaats van gegokt.
- **Onzekerheid expliciet** — een lage confidence-score op een claim
  rechtvaardigt geen stellige formulering in de tekst.
- **Aanleiding, geen overinterpretatie** — de trigger-reden mag verklaard
  worden, maar één afwijkende observatie is nog geen trend.

Voordeel: een kwaliteitsverbetering hier geldt meteen voor alle domeinen
(ook toekomstige, sectie C+), en een nieuwe agent kan de regels niet per
ongeluk vergeten — `run_deep_dive()` voegt ze toe, niet de aanroeper.
`tests/test_agents_base.py::test_run_deep_dive_prepends_shared_quality_rules_to_domain_prompt`
bewijst dat dit ook daadwerkelijk in de verstuurde API-call terechtkomt.

## Bewijs dat het fundament + B samenhangen

`tests/test_integration_section_a.py` doorloopt het A-pad end-to-end met
synthetische data. `tests/test_integration_section_b.py` bouwt daarop voort
met de twee echte domain agents (B.1/B.2, fetch en LLM-client beide
monkeypatched/fake — geen netwerk of API-key nodig): een baseline-run per
domein, dan een gesimuleerd Fed-besluit dat beide tegelijk raakt (het
voorbeeld dat het stappenplan zelf voor de manager noemt), door dispatch,
deep-dive en de synthesizer heen, met een check dat alles — monitoring-
claims én deep-dive-claims — daadwerkelijk in de database staat.

## Wat hierna komt

Sectie C (`docs/roadmap.md`): C.1, de equity agent als dunne adapter over
`analyst_agent.ai`'s bestaande pipeline-output — de eerste domain agent die
wél op die bestaande code voortbouwt in plaats van een eigen databron te
implementeren. Ook de eerste gelegenheid om `qc.qc.default_llm_review()` en
`agents.base.run_deep_dive()` tegen een échte Anthropic-call te draaien in
plaats van tegen een fake client.
