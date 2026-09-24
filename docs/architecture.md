# Architecture — wat er nu staat (gebouwd tegen de oude, kleinere roadmap-scope)

Zie `docs/roadmap.md` voor de volledige, huidige planning (vijf pijlers,
sinds 24-09-2026). Dit document beschrijft alleen wat er al staat, nog
grotendeels beschreven met de OUDE sectie-lettering (A/B/C.1-C.4) — zie de
mapping-tabel bovenaan `docs/roadmap.md` voor hoe dat zich verhoudt tot de
nieuwe pijlers 1-5. Inhoudelijk nog correct; dekt vooral pijler 1
(gedeeltelijk) en de kernopzet van pijler 2's eerste vijf agents.

## Modulekaart (`src/`)

| Module | Rol | Roadmap-stap |
|---|---|---|
| `contract/output_contract.py` | `Claim` en `DomainOutput` — de vorm waar elke domain agent zich aan houdt | A.1 |
| `storage/schema.py` | SQLite source of truth: claims, trigger-events, data-health, agent-runs (audit-log per monitoring/deep-dive-cyclus, roadmap 1.2, nu ook idempotency-dedup via `event_id`, roadmap 1.7), sources (Source Registry, roadmap 1.4) | A.2 / 1.2 / 1.4 / 1.7 |
| `sources/registry.py` | `SourceConfig` — de vorm van één geregistreerde bron (provider, domain, max_age, frequency, latency, cost, quality_score, fallback_source_key) | 1.4 |
| `health/data_health.py` | Staleness/onbereikbaarheid per databron, revisie-detectie, completeness/validity/consistency/continuity-checks, en het `QualityStatus`-rollup (HEALTHY/DEGRADED/INVALID) — allemaal roadmap 1.3, vóór de trigger-laag | A.3 / 1.3 |
| `health/system_health.py` | Centrale status-per-component-functie (source/ingestion/database/trigger/agent/LLM), roadmap 1.7 deel 1 — backend voor de latere Dashboard-laag (5.2). `sources_from_registry()` vult de `sources`-parameter automatisch vanuit 1.4's register | 1.7 |
| `triggers/trigger_engine.py` | Deterministische escalatiebeslissingen (drempel, verrassing, data-health) | A.4 |
| `qc/qc.py` | Deterministische consistentiecheck + `default_llm_review()` (concrete, pluggable LLM-review), `NEEDS_REVIEW` | A.5 |
| `manager/manager.py` | Dispatch: groepeert `TriggerEvent`s per domein, signaleert gelijktijdige triggers | A.6 |
| `agents/base.py` | Gedeelde scaffolding: `run_monitoring()`, `evaluate_deltas()` (delta-trigger, losgetrokken zodat C.1 'm ook kan gebruiken), `run_deep_dive()`, `SHARED_QUALITY_RULES` | B.1/B.2 |
| `agents/monetary_policy_agent.py` | FRED (Fed funds rate, 10Y yield, CPI-index, werkloosheid) — alleen vakinhoudelijke deep-dive-prompt | B.1 |
| `agents/currency_agent.py` | Alpha Vantage FX (EUR/USD, USD/JPY, GBP/USD) — alleen vakinhoudelijke deep-dive-prompt | B.2 |
| `synthesizer/synthesizer.py` | Legt gelijktijdige deep-dives naast elkaar (nog geen cross-domein-synthese) | B.3 |
| `agents/equity_agent.py` | Adapter: analyst_agent.ai-output (`AnalystAgentReport`) → Claims/DomainOutput, per ticker genamespaced (`equity:<TICKER>`) | C.1 |
| `agents/financial_agent.py` | FRED (NFCI, high-yield credit spread, VIX, 10Y-2Y yield curve) — financiële-marktcondities, losstaand van equity/monetary policy | C.2 |
| `analysis/nfci_interpretation.py` | Eerste bestand in een groeiende `analysis/`-map (één citeerbaar model per bestand, zelfde patroon als `analyst_agent.ai/src/analysis/`) — NFCI's eigen gepubliceerde interpretatie | C.2-uitbreiding |
| `analysis/taylor_rule.py` | Taylor Rule (Taylor, 1993) — impliciete "passende" Fed funds rate uit YoY-inflatie + output gap; r*=2% aanname afgestemd met DD, π*=2% is Fed's eigen doel | B.1-uitbreiding |
| `agents/sector_agent.py` | Alpha Vantage (alle 11 SPDR Select Sector-ETF's) — trigger op ruwe prijs, één plat domain (`sector`) | C.3 |
| `analysis/relative_strength.py` | Relatieve sterkte van een sector-ETF t.o.v. SPY (S&P 500) — onderscheidt sector-rotatie van een bredere marktbeweging | C.3-uitbreiding |
| `agents/commodity_agent.py` | Alpha Vantage (10 grondstoffen, 1-op-1 uit analyst_agent.ai's SUPPORTED_COMMODITIES, incl. koper) — eerste databron zonder overlap met B/C.1-C.3 | C.4 |
| `analysis/moving_average_deviation.py` | Procentuele afwijking t.o.v. een 6-maands voortschrijdend gemiddelde — mean-reversion/trend-signaal | C.4-uitbreiding |

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
  note}`-items, met `confidence` toegevoegd omdat dit systeem doorlopend
  draait (claims verouderen) in plaats van één rapport op één moment.
  In plaats van één `timestamp` heeft een Claim vier tijdstempels
  (`event_time` / `source_time` / `ingestion_time` / `analysis_time`,
  zie roadmap 1.1) — nodig om later onderscheid te kunnen maken tussen
  wanneer iets écht gebeurde, wat de bron als datum opgeeft, wanneer wij
  het ophaalden, en wanneer een claim daadwerkelijk werd vastgesteld.
  Alleen `analysis_time` is nu overal betrouwbaar gevuld; `source_time`
  volgt uit de bron waar bekend, `event_time` is nog een gedocumenteerd
  gat (komt met de Source Registry, 1.4).
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
- **Revisie-detectie tegen `claims`, geen aparte `observations`-tabel
  (roadmap 1.3).** De roadmap noemt `observations` als eigen entiteit
  (1.2), maar `claims` bewaart al elke monitoring-poll historisch (nooit
  overschreven) met `source_time` erbij — voldoende om te zien of een
  waarde voor een al-eerder-geziene periode is gewijzigd. Een aparte
  tabel nu zou vooral data dupliceren zonder een andere consument dan
  deze check. `health.data_health.detect_revision()` scant de volledige
  historie voor een metric (niet alleen de laatste claim — een revisie
  kan een periode van meerdere cycli geleden raken) op een gewijzigde
  waarde bij gelijke `source_time`; `triggers.trigger_engine.
  evaluate_revision()` heeft, anders dan `evaluate_surprise()`, GEEN
  tolerantie: elke revisie is per definitie al nieuws.
- **Idempotency op `agent_runs`-niveau, niet op `claims`-niveau (roadmap
  1.7, deel 2).** Bewust een ANDERE keuze dan revisie-detectie hierboven,
  met een andere reden: de eenheid van herhaling is hier "is deze
  CYCLUS al verwerkt" (één keer fetchen, één keer de LLM aanroepen), niet
  "is deze WAARDE al gezien" (dat is revisie-detectie, een apart
  concern dat over individuele metric-waarden gaat). `agent_runs` is al
  precies één rij per monitoring-/deep-dive-cyclus (roadmap 1.2) — de
  natuurlijke plek voor een dedup-key, geen nieuwe tabel nodig. Een
  optionele `event_id`-kolom + partial unique index
  (`idx_agent_runs_event_id`, alleen op succesvolle rijen: `WHERE
  event_id IS NOT NULL AND success = 1`) dwingt op databaseniveau af dat
  een event_id maximaal één succesvolle verwerking krijgt, terwijl een
  mislukte poging een retry met hetzelfde event_id niet blokkeert.
  `agents/base.py::AlreadyProcessedError` is de vroege, applicatieve
  check (vóór een onnodige fetch/LLM-call); de databaseconstraint is het
  laatste vangnet. `event_id` is optioneel — geen enkele bestaande
  domain agent geeft er nu een mee (er is nog geen scheduler/
  orchestratielaag die cycli van een stabiele identifier voorziet), dus
  dit verandert niets aan het huidige gedrag totdat een toekomstige
  aanroeper er gebruik van maakt.
- **Source Registry: één entry per (provider, domain)-combinatie, niet
  één entry per provider met losse per-consument-config (roadmap 1.4).**
  Dit is bewust NIET de voor de hand liggende keuze — een registry-rij
  per PROVIDER (met max_age als apart, per-consument veld ernaast) is
  op het eerste gezicht netter (geen duplicatie van providerfeiten als
  latency/cost), en was serieus overwogen.

  Reden om die aanpak toch AF te wijzen: het lost de aanleiding niet op.
  `monetary_policy_agent.py` en `financial_agent.py` gebruiken beide
  provider "FRED", met een verschillende verwachte ververssnelheid (35
  vs. 10 dagen). Zolang `data_health` zelf op de KALE providernaam
  "FRED" gekeyed blijft, delen beide agents nog steeds ÉÉN
  `checked_at`-rij — ongeacht welke max_age je er los naast zet. Erger:
  een succesvolle poll van de ene agent ververst die gedeelde rij, en
  verbergt daarmee de andere agent's eigen staleness (die misschien al
  dagen niet zelf gelukt is) achter de eerste agent's frequente
  successen. Dat is precies het "stille-faalscenario" dat A.3's "fail
  loudly, not silently"-principe wil voorkomen — een registry die alleen
  de max_age-parameter oplost maar niet de gedeelde `data_health`-rij,
  lost het echte probleem dus niet op.

  De gekozen aanpak fixt dit bij de bron: elke registry-entry krijgt een
  eigen `source_key`, format `<provider>:<domain>` (bv.
  `"FRED:monetary_policy"`, `"FRED:financial"`), en DIE string — niet de
  kale providernaam — is wat de gemigreerde agents voortaan als `source_name`
  doorgeven aan `record_data_health()`/`check_source()`
  (`agents/base.py`/`health/data_health.py` zelf zijn ONGEWIJZIGD; ze
  namen altijd al een vrije string aan). Twee agents die dezelfde
  provider delen krijgen zo gegarandeerd hun EIGEN, onafhankelijke
  `data_health`-geschiedenis. Prijs: providerfeiten (latency, cost) die
  écht gedeeld zijn tussen consumenten van dezelfde provider worden
  letterlijk gedupliceerd over meerdere rijen — een bewust geaccepteerde
  kleine redundantie tegenover een registry die de kernbug niet had
  opgelost. Zie `sources/registry.py`'s moduledocstring voor dezelfde
  afweging in code-vorm, en `tests/test_system_health.py::
  test_system_health_with_registry_sources_keeps_two_fred_consumers_independent`
  voor het regressiebewijs.
- **1.3's statusmodel (HEALTHY/DEGRADED/INVALID): GEEN hernoeming van
  `HealthStatus`, wel een nieuw, complementair `QualityStatus`-rollup.**
  De roadmap-notitie ("nu: OK/STALE/UNREACHABLE/UNKNOWN — andere
  vocabulaire, vergelijkbaar idee") suggereert dat dit vooral een
  woordenschat-kwestie is. Dat bleek bij nader inzien niet te kloppen, en
  dat is de kern van deze beslissing.

  **Optie (a), een echte hernoeming, is overwogen en afgewezen.**
  `HealthStatus` wordt gebruikt in `health/data_health.py`,
  `health/system_health.py` (severity-ordering, rollup, elk component),
  `triggers/trigger_engine.py::evaluate_data_health`, `sources/
  registry.py` (indirect, via `check_source()`), en in drie testbestanden
  (`test_data_health.py`, `test_trigger_engine.py`, `test_system_
  health.py`) — een reële, meervoudige-modules-brede blast radius. Erger
  dan de omvang: de mapping is niet eens 1-op-1. OK/STALE/UNREACHABLE/
  UNKNOWN zijn VIER waarden, HEALTHY/DEGRADED/INVALID zijn er DRIE — een
  hernoeming moet dus sowieso al lossy keuzes maken (hoort STALE bij
  DEGRADED of ergens anders; waar landt UNKNOWN). Een hernoeming die toch
  al niet 1-op-1 kan, is geen hernoeming meer, maar een nieuw ontwerp
  vermomd als opschoning.

  **Het echte probleem met optie (a): de vier nieuwe checks (Deel 1) meten
  assen die `HealthStatus` nooit heeft proberen te vangen.**
  `HealthStatus` beschrijft specifiek "is de bron bereikbaar en vers"
  (A.3) — één as. Completeness (kwam alles binnen déze pull), validity
  (is DEZE waarde plausibel), consistency (klopt een afgeleide claim met
  zijn eigen input) en continuity (zit er een gat verderop in de reeks)
  zijn elk een ANDERE, orthogonale as. Een waarde kan perfect VERS zijn
  (`HealthStatus.OK`) en toch ONGELDIG (een negatieve werkloosheid) —
  deze twee feiten samenpersen in één enkele 3- of 4-waarden-enum verliest
  precies het onderscheid dat de vier nieuwe checks juist willen maken.

  **Gekozen aanpak: `HealthStatus` blijft ONGEWIJZIGD** (nul call sites
  geraakt), elk van de vier nieuwe checks krijgt een EIGEN, smal
  resultaat-type (`CompletenessResult`/`ValidityResult`/
  `ConsistencyResult`/`ContinuityResult`, allen in `health/data_health.py`
  — zie Deel 1 hieronder), en `QualityStatus` (HEALTHY/DEGRADED/INVALID)
  is een NIEUW, TOEGEVOEGD rollup-type dat de vijf signalen (de vier
  nieuwe checks + optioneel `HealthStatus`) samenvat tot één oordeel per
  claim/metric — geen vervanging, een extra, hogere laag.
  `rollup_quality_status()` combineert ze met een simpel worst-of (zelfde
  patroon als `system_health.py`'s `_worst()`, geen uitgevonden
  weegfactoren) — dat hoeft geen "geen gok"-schending te zijn omdat er
  geen gewicht wordt geraden, alleen een volgorde (HEALTHY < DEGRADED <
  INVALID) toegepast op signalen die zelf al puur deterministisch zijn.

  Zelfs deze rollup is niet perfect 1-op-1: `HealthStatus.STALE` en
  `HealthStatus.UNKNOWN` landen allebei op `QualityStatus.DEGRADED` (een
  bewuste keuze: "nog geen oordeel mogelijk" verdient geen valse
  geruststelling als HEALTHY), en `HealthStatus.UNREACHABLE` landt op
  `QualityStatus.INVALID` bij gebrek aan een vierde bucket — een
  eerlijk-benoemde onvolkomenheid, geen verborgen aanname. Zie de
  mapping-tabel en `health/data_health.py::QualityStatus`'s docstring.

  | `HealthStatus` (bron-freshness) | → | `QualityStatus` (kwaliteits-rollup) | Notitie |
  |---|---|---|---|
  | `OK` | → | `HEALTHY` | — |
  | `STALE` | → | `DEGRADED` | bruikbaar, niet perfect |
  | `UNKNOWN` | → | `DEGRADED` | geen data ≠ HEALTHY, maar ook geen bewezen fout |
  | `UNREACHABLE` | → | `INVALID` | geen vierde bucket beschikbaar; enigszins oneigenlijk (INVALID impliceert een FOUTE waarde, niet AFWEZIGHEID van een waarde) — bewust benoemd, niet verdoezeld |

  Nog niet gebouwd, expliciet vervolgwerk: een ECHTE gewogen synthese
  over meerdere metrics/domeinen (bijv. "hoe erg is één INVALID-claim
  tussen tien HEALTHY-claims voor het hele domein") hoort bij de
  synthese-laag (sectie 3), net als `quality_score` uit 1.4 — deze
  rollup oordeelt bewust alleen per losse claim/metric, geen aggregatie
  eroverheen.
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

## LLM-taken-tabel (roadmap 1.8): wat mag wel/niet door een LLM

Legt CLAUDE.md-principe 1 ("Deterministisch waar mogelijk, LLM alleen waar
het moet") systeembreed en expliciet vast — voorheen impliciet verspreid
over losse moduledocstrings (`trigger_engine.py`, `manager.py`, `qc.py`,
`agents/base.py`). Dit is de ÉÉN plek om te checken of een component een
LLM gebruikt, en waarom (niet). **Governance-regel**: een nieuwe LLM-call
die hier niet in staat is een bug, geen feature — deze tabel wordt
bijgewerkt VOORDAT zo'n aanroep wordt toegevoegd, niet erna (zie ook
CLAUDE.md, "eerst voorleggen, niet in stilte kiezen").

| Component | LLM? | Taak / reden |
|---|---|---|
| `triggers/trigger_engine.py` (`evaluate_threshold`, `evaluate_surprise`, `evaluate_data_health`) | Nee | "Is deze afwijking significant" moet reproduceerbaar en goedkoop zijn — dit systeem draait onbeheerd en polled continu op de achtergrond. |
| `health/data_health.py` | Nee | Pure leeftijdscontrole van de laatst bekende succesvolle pull, revisie-detectie, en de vier nieuwe 1.3-checks (completeness/validity/consistency/continuity) + `rollup_quality_status()` — allemaal deterministische vergelijkingen, geen LLM. |
| `health/system_health.py::system_health()` | Nee | Leest alleen al-bestaande, deterministische statussen (`data_health`, `agent_runs`) uit en rolt ze op — geen eigen oordeel, geen LLM. |
| `sources/registry.py`, `storage/schema.py::register_source`/`get_source`/`list_sources` | Nee | Puur configuratie lezen/schrijven (Source Registry, roadmap 1.4) — geen interpretatie, geen LLM. `quality_score` is nu een leeg veld; de toekomstige berekening ervan (sectie 3) krijgt hier een eigen rij zodra die gebouwd wordt. |
| `manager/manager.py::dispatch()` | Nee | Groepeert al-genomen triggerbeslissingen tot een `DispatchPlan` — coördineert, oordeelt niet opnieuw over "is dit significant". |
| Domain agent monitoring mode (`agents/*.py::monitor()`, `agents/base.py::run_monitoring()`) | Nee | Data ophalen + delta-berekening tegen de vorige observatie — puur cijferwerk, geen duiding. |
| `src/analysis/*` (Taylor Rule, NFCI-interpretatie, relatieve sterkte, moving-average-deviation) | Nee | Citeerbare, deterministische modellen berekend in Python, aan de LLM gegeven als kant-en-klare claim om te **duiden**, nooit om zelf te **schatten** ("Python computes, Claude narrates"). |
| `qc/qc.py::deterministic_consistency_check` | Nee | Regex/cijfer-matching tussen een Claim en de deep-dive-tekst. |
| Domain agent deep-dive mode (`agents/base.py::run_deep_dive()`) | **Ja** | Eén call per getriggerd domein: vat de al-berekende claims samen tot een korte, neutrale synthese. Gebonden aan `SHARED_QUALITY_RULES` (alleen aangeleverde claims, geen koop/verkoop-advies, onzekerheid expliciet) — zie sectie hieronder. |
| `qc/qc.py::default_llm_review` | **Ja** | Eén lichte review-call per deep-dive: checkt neutraliteit/volledigheid/zelfconsistentie van de tekst — GEEN herbeoordeling van de cijfers zelf (dat doet de deterministische laag hierboven al). Bewust niet de 4-parallelle-reviewers-aanpak van `analyst_agent.ai` (zie `qc.py`'s moduledocstring). |
| `synthesizer/synthesizer.py::synthesize_simultaneous` | Nee (nu) | Zet op dit moment al-gegenereerde deep-dive-teksten naief naast elkaar, geen eigen LLM-call. Pijler 3.1 (nog te bouwen: contradictie-detectie, cross-domain-samenvoeging) voegt hier WEL LLM-gebruik toe — deze rij wordt dan bijgewerkt. |
| `agents/equity_agent.py` (adapter) | Nee (hier) | Adapteert een AL gegenereerd `analyst_agent.ai`-rapport naar claims — het LLM-gebruik zit in dat losse systeem, niet in deze adapter. |
| Toekomstige "thesis-mode" (roadmap 5.4, nog niet gebouwd) | Ja (gepland) | Enige geplande plek waar EXPLICIET gevraagde directionele/probabilistische redenering is toegestaan (analoog aan `analyst_agent.ai` sectie 18, Variant Perception) — een apart, duidelijk gelabeld kanaal, GEEN aanpassing van `SHARED_QUALITY_RULES` elders (zie `agents/base.py`'s moduledocstring). |

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

**Scope van de neutraliteitsregel (expliciet met DD besproken):** dit geldt
voor de AUTOMATISCHE, onbeheerde monitoring/deep-dive-laag hier in sectie
B/C — niet als permanente blokkade op elke directionele/probabilistische
uitspraak in het hele systeem. Sectie G.3 (on-demand vraag-interface)
krijgt een aparte "thesis-mode" die WEL expliciet gevraagde directionele
antwoorden mag geven (DD's voorbeeld: "wat is de kans dat de Fed de rente
verhoogt, met een thesis") — analoog aan `analyst_agent.ai`'s sectie 18
(Variant Perception): overal elders strikt neutraal, met één duidelijk
gelabeld, geïsoleerd kanaal voor opinie. Zie `agents/base.py`'s docstring
voor de volledige onderbouwing, en `docs/roadmap.md` sectie G.3.

## Onderbouwing van deep-dives met echte modellen (`src/analysis/`)

Tot nu toe waren de deep-dives van monetary_policy/currency/financial
"cijfer veranderde meer dan een geraden drempel, laat de LLM erover
schrijven" — geen vakinhoudelijke methode erachter, in tegenstelling tot
equity (C.1), die leunt op gepubliceerde, citeerbare modellen (Altman
Z-Score, Piotroski F-Score, reverse-DCF). `src/analysis/` is waar dat voor
de andere domeinen ook komt te staan — zelfde patroon als
`analyst_agent.ai/src/analysis/`: één citeerbaar, deterministisch model per
bestand, dat een domain agent's `deep_dive()` als extra claim meegeeft
zodat de LLM het NARREERT in plaats van zelf INSCHAT.

**Eerste model:** `analysis/nfci_interpretation.py::classify_nfci()` — de
NFCI's eigen, door de Chicago Fed gepubliceerde interpretatie (0 =
historisch gemiddelde, teken bepaalt krapper/ruimer), geen zelfbedachte
tussenband. `financial_agent.py::deep_dive()` voegt die classificatie toe
als aparte claim vóór de LLM-call.

**Tweede model:** `analysis/taylor_rule.py::compute_taylor_rule_rate()` —
de Taylor Rule (Taylor, 1993): `i = r* + π + 0,5(π−π*) + 0,5(output gap)`.
`monetary_policy_agent.py::deep_dive()` haalt hiervoor, ALLEEN op
deep-dive-tijd (niet via de reguliere `FRED_SERIES`-monitoring, want
bbp-data is kwartaalcijfers met een andere ververssnelheid dan de rest van
de agent — zou de gedeelde `MAX_AGE`-staleness-check verstoren), de
YoY-inflatie (CPI nu vs. 12 maanden terug, via `_fetch_series()`'s nieuwe
`lag_observations`-parameter) en de output gap (GDPC1 vs. GDPPOT) op, en
voegt de impliciete rente + de afwijking t.o.v. de daadwerkelijke Fed
funds rate toe als claims. r*=2% is een AANNAME, expliciet met DD
afgestemd (zie `docs/project-state.md`) — niet een door Claude zelf
gekozen getal; π*=2% is het Fed's eigen, gepubliceerde doel.

**Derde model:** `analysis/relative_strength.py::compute_relative_strength_pct()`
— het verschil tussen een sector-ETF's dagverandering en die van de S&P
500 (via SPY). `sector_agent.py::deep_dive()` haalt hiervoor SPY's
dagverandering ÉÉN keer op (niet per sector, ook al triggeren er soms
meerdere tegelijk), berekent per getriggerde sector het verschil, en voegt
de classificatie (outperform/underperform) toe als claim. Onderscheidt zo
een sector-specifieke beweging (mogelijke rotatie) van een bredere
marktbeweging — DD's eigen voorbeeld ("XLB daalt t.o.v. S&P 500") is hier
letterlijk het ontwerp geweest.

**Vierde model:** `analysis/moving_average_deviation.py::compute_deviation_from_average_pct()`
— de procentuele afwijking van een grondstofprijs t.o.v. het 6-maands
voortschrijdend gemiddelde. Bijzonderheid t.o.v. de andere drie modellen:
Alpha Vantage's commodity-endpoint geeft de historische punten die dit
model nodig heeft AL terug in dezelfde respons als de huidige prijs (geen
los kwartaal-/dagcijfer zoals bij GDP/SPY) — `commodity_agent.py::deep_dive()`
haalt die historie desondanks opnieuw op (voor verse data op deep-dive-
tijd), maar had 'm in theorie ook uit de oorspronkelijke monitoring-pull
kunnen bewaren.

Geplande volgende modellen (zie `docs/roadmap.md` sectie I, DD's eigen
voorbeelden): een Phillips-curve-model voor de nog te bouwen economic
agent, een model voor 1e/2e/3e-orde-inflatie-effecten bij monetary policy.
Elk nieuw model: een nieuw bestand hier, geen herstructurering van
bestaande agents.

## Bewijs dat het fundament + B samenhangen

`tests/test_integration_section_a.py` doorloopt het A-pad end-to-end met
synthetische data. `tests/test_integration_section_b.py` bouwt daarop voort
met de twee echte domain agents (B.1/B.2, fetch en LLM-client beide
monkeypatched/fake — geen netwerk of API-key nodig): een baseline-run per
domein, dan een gesimuleerd Fed-besluit dat beide tegelijk raakt (het
voorbeeld dat het stappenplan zelf voor de manager noemt), door dispatch,
deep-dive en de synthesizer heen, met een check dat alles — monitoring-
claims én deep-dive-claims — daadwerkelijk in de database staat.

## C.1: de equity-adapter — anders dan B, en waarom

`agents/equity_agent.py` is de eerste domain agent die op `analyst_agent.ai`'s
bestaande output voortbouwt in plaats van een eigen databron te
implementeren — letterlijk de stappenplan-bewoording ("dunne adapter").
Twee dingen wijken daardoor bewust af van het B-patroon:

- **Geen eigen LLM-deep-dive-call.** `analyst_agent.ai`'s rapporttekst is al
  gegenereerd, mét zijn eigen 4-reviewer-QC — dat IS de deep-dive.
  `ingest_report()` neemt `needs_review` 1-op-1 over in plaats van er
  `qc.qc.apply_qc()` overheen te draaien (zie CLAUDE.md: "Geen 4-parallelle-
  reviewers-QC hier overnemen" — dat geldt ook omgekeerd: niet een lichte
  review overheen draaien op iets dat al zwaar gereviewd is).
- **Per-ticker domain-namespacing.** Monetary policy en currency hebben elk
  ÉÉN instantie; equity heeft er evenveel als er tickers gevolgd worden, en
  verschillende tickers delen dezelfde metric_key-namen (`sec_operating_margin`
  voor zowel NKE als AAPL). Zonder namespacing zou `evaluate_deltas()` de
  ene ticker per ongeluk tegen de andere afzetten. Oplossing:
  `equity_domain(ticker)` geeft elke ticker zijn eigen domain-string
  (`equity:NKE`, `equity:AAPL`, ...) — dit werkt zonder ENIGE aanpassing in
  `manager.py`, `synthesizer.py` of `storage/schema.py`, omdat "domain"
  daar altijd al een kale string was, geen vaste enum over de zeven
  benoemde domeinen. Een mooie bevestiging dat die oorspronkelijke A.1-keuze
  klopte. `tests/test_equity_agent.py::test_ingest_report_different_tickers_never_cross_trigger`
  bewijst dat de collision-bug die dit voorkomt ook echt niet optreedt, en
  `test_equity_triggers_integrate_with_manager_dispatch` dat een
  equity-trigger door dezelfde `manager.dispatch()` gaat als B.1/B.2 —
  zonder wijziging daar.

**Scope-grens (bewust):** `AnalystAgentReport` is het contract waar de
adapter op werkt, maar dit bestand roept `analyst_agent.ai` niet zelf aan
(geen subprocess, geen cross-repo import). Hoe de output van een
daadwerkelijke run hier terechtkomt is de "latere koppeling" uit
`CLAUDE.md` — nog niet gebouwd.

## Bewijs dat het fundament + B + C.1 samenhangen

`tests/test_integration_section_a.py` doorloopt het A-pad end-to-end met
synthetische data. `tests/test_integration_section_b.py` bouwt daarop voort
met de twee echte domain agents (B.1/B.2, fetch en LLM-client beide
monkeypatched/fake — geen netwerk of API-key nodig): een baseline-run per
domein, dan een gesimuleerd Fed-besluit dat beide tegelijk raakt (het
voorbeeld dat het stappenplan zelf voor de manager noemt), door dispatch,
deep-dive en de synthesizer heen, met een check dat alles — monitoring-
claims én deep-dive-claims — daadwerkelijk in de database staat.
`tests/test_equity_agent.py` bewijst hetzelfde voor C.1, plus specifiek de
ticker-namespacing en de interoperabiliteit met de al-bestaande manager.

## Wat hierna komt

Sectie C.2-C.5 (`docs/roadmap.md`): financial, sector, commodity, economic
agents, in die volgorde. Ook de eerste gelegenheid om `qc.qc.default_llm_review()`
en `agents.base.run_deep_dive()` (B.1/B.2) tegen een échte Anthropic-call te
draaien in plaats van tegen een fake client — dat gebeurt niet via C.1 zelf
(die heeft geen eigen LLM-call, zie hierboven).
