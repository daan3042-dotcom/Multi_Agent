# Roadmap — Market Intelligence Platform

**Bron van waarheid vanaf nu:** de artifact ["Market Intelligence Platform —
Systeemoverzicht"](https://claude.ai/artifact/PpSZ4yrbWyHRVifuAjoffn) (DD,
23-09-2026). Dit document is de vertaling daarvan naar de repo — dezelfde
vijf pijlers, dezelfde volgorde (infrastructuur → agents → synthese →
evaluatie → output), dezelfde onderdelen. Vink items af zodra ze klaar zijn
én groen zijn in de testsuite.

De oorspronkelijke, eenvoudigere planning (`market-intelligence-roadmap.html`,
secties A–I) is hiermee **vervangen, niet aangevuld** — dit is nu het
volledige einddoel. Geen deadline; kwaliteit en een solide fundament wegen
zwaarder dan snelheid.

**Mapping oud → nieuw** (voor wie een code-comment tegenkomt die naar de
oude lettering verwijst, bijv. "stap B.1" of "sectie C.1" — die comments
blijven inhoudelijk kloppen, alleen de sectie-nummers zijn vervangen):

| Oud | Nieuw |
|---|---|
| A (Fundament) | 1. Infrastructuur & Data |
| B (monetary+currency skeleton) + C (Domain Agents) | 2. Domain Agents |
| D (News monitor) | 2.8 News Monitor Agent |
| E (Nasdaq/NQ regime) | 2.9 Nasdaq/NQ Regime & Bias Agent |
| F (Synthesizer volwassen maken) | 3.1 Cross-Domain Synthesizer |
| G (Output & interface) | 5. Output & Interfaces |
| H (Open beslissingen) | Open beslissingen (onderaan, ongewijzigd relevant) |
| I (Later/optioneel) | Verwerkt in de Finetune-lijsten per agent (sectie 2) en 4.1 |

## Huidige focus

**Sectie 1 (Infrastructuur & Data) eerst écht solide maken, vóór er verder
gebouwd wordt aan sectie 2 (meer agents/modellen).** Veel van sectie 1 is
gebouwd in een eenvoudigere vorm dan wat hieronder staat (zie de
niet-afgevinkte items in 1.1–1.8) — dat gat dichten heeft nu prioriteit
boven C.5 (economic agent) of verdere Finetune-modellen. Testen (tegen
echte databronnen, zodra netwerktoegang dat toelaat) hoort bij dit werk,
niet erna.

---

## 1. Infrastructuur & Data — fundament, geen agents

### 1.1 Output Contract & Domain Ontologie
- [x] Claim-contract: waarde, bron, confidence (`src/contract/output_contract.py`)
- [x] Vier tijdstempels: event_time / source_time / ingestion_time /
      analysis_time (`src/contract/output_contract.py`)
- [x] Domain ontologie vastleggen (Equities, Rates, FX, Commodities,
      Credit, Macro, Sectors, Companies) (`src/contract/domain_ontology.py`)

### 1.2 Database & Event Store
- [x] Database-schema als source of truth (`src/storage/schema.py`)
- [ ] Event-model: raw data → observation → event (conceptueel pad, wordt
      concreet zodra de entiteiten hieronder er zijn om het te dragen)
- [x] Entiteit: claims (`src/storage/schema.py`, al vanaf de start)
- [x] Entiteit: triggers (`trigger_events`-tabel, al vanaf de start)
- [x] Entiteit: agent_runs — audit-log per monitoring/deep-dive-run
      (`src/storage/schema.py::record_agent_run/list_agent_runs`)
- [x] Entiteit: sources (`src/storage/schema.py` — `sources`-tabel,
      gebouwd samen met 1.4 Source Registry, zie daar)
- [ ] Entiteit: observations — bewust NIET gebouwd als aparte tabel:
      revisie-detectie (1.3) is de enige huidige reden om ze los van
      claims te zien, en dat werkt al tegen de bestaande claims-historie
      (elke poll blijft bewaard). Pas een eigen tabel zodra er een
      andere reden is om ze te scheiden (bijv. claims gaan prunen).
- [ ] Entiteit: entities (het "wat wordt hier gemeten"-register)
- [ ] Entiteit: measurements (afgeleide/berekende waarden, nu impliciet
      onderdeel van claims met source="Berekend (...)")
- [ ] Entiteit: events (nieuws/agenda-gebeurtenissen, hoort bij 2.8 News
      Monitor Agent)
- [ ] Entiteit: expectations (echte marktverwachting i.p.v. "vorige
      observatie" als trigger-referentie)
- [ ] Entiteit: evidence (brondocumenten/citaten bij een claim)
- [ ] Entiteit: deep_dives (nu impliciet: een DomainOutput met
      mode=DEEP_DIVE, geen eigen entiteit)
- [ ] Entiteit: syntheses (synthesizer's output is nu vluchtig, nooit
      persistent)
- [ ] Entiteiten: alerts, regimes, theses, predictions, evaluations (horen
      bij pijler 4/5, bewust nog niet nu)

### 1.3 Data Quality & Health Layer
- [x] Basale freshness-check (`src/health/data_health.py`)
- [x] Completeness / validity / consistency / continuity checks
      (`src/health/data_health.py::evaluate_completeness/evaluate_validity/
      evaluate_consistency/evaluate_continuity`). Elk als losstaande,
      pure functie — WIRING in `agents/base.py`/`trigger_engine.py` bewust
      niet geforceerd (zie `docs/project-state.md` voor per-check waarom),
      dat is expliciet open vervolgwerk.
- [x] Revisie-detectie (macro-cijfers worden later herzien — bijv. een
      eerste BBP-schatting wijkt af van de definitieve)
      (`src/health/data_health.py::detect_revision`,
      `src/triggers/trigger_engine.py::evaluate_revision`, gewired in
      `agents/base.py::run_monitoring`)
- [x] Statusmodel: HEALTHY / DEGRADED / INVALID
      (`src/health/data_health.py::QualityStatus/rollup_quality_status`).
      GEEN hernoeming van `HealthStatus` (die blijft ongewijzigd voor
      bron-freshness) — een nieuw, complementair rollup-type over de vier
      checks hierboven. Uitgebreid beargumenteerd in `docs/architecture.md`
      ("Ontwerpkeuzes"), inclusief mapping-tabel tussen beide vocabulaires.

### 1.4 Source Registry
- [x] Centraal register per databron: provider, frequency, latency, cost,
      quality_score (`src/storage/schema.py::register_source/get_source/
      list_sources`, `src/sources/registry.py::SourceConfig`). Eén entry
      per (provider, domain)-combinatie, niet per provider — zie
      `docs/architecture.md` ("Ontwerpkeuzes") voor de afweging.
      `quality_score` bestaat als veld, nog geen logica die 'm berekent
      (wacht op de synthese-laag, sectie 3).
- [x] Fallback-bron-logica per databron — VELD/mechanisme aanwezig
      (`fallback_source_key`, FK naar `sources.source_key`), maar GEEN
      agent heeft momenteel een daadwerkelijke alternatieve bron
      geïmplementeerd om naar te verwijzen. Wiring in een agent is
      expliciet open vervolgwerk, niet geforceerd binnen deze sectie.
- [x] Alle 5 agents met een eigen live databron gemigreerd naar het
      register: `monetary_policy_agent.py` (`FRED:monetary_policy`),
      `financial_agent.py` (`FRED:financial`) — lost het gedeelde-
      databron-probleem uit de aanleiding daadwerkelijk op, geen registry
      "voor de vorm" — en, in een tweede ronde zonder aantoonbaar
      conflict maar voor consistentie, `currency_agent.py`
      (`ALPHA_VANTAGE_FX:currency`), `sector_agent.py`
      (`ALPHA_VANTAGE_EQUITY:sector`), `commodity_agent.py`
      (`ALPHA_VANTAGE_COMMODITY:commodity`). `equity_agent.py` heeft geen
      eigen live databron (adapter) en valt hier sowieso buiten.

### 1.5 Trigger Engine
- [x] Deterministische thresholds, geen LLM (`src/triggers/trigger_engine.py`)
- [ ] Trigger severity: INFO / WATCH / SIGNIFICANT / CRITICAL (nu:
      low/medium/high)
- [ ] Trigger-versioning (welke regel-versie was actief toen dit
      triggerde)
- [ ] Vier triggertypes: threshold, regime-transitie, event, cross-
      variable/correlatiebreuk (nu: threshold + surprise + data-health —
      regime-transitie en cross-variable ontbreken nog)

### 1.6 QC & State Machine
- [x] Layer 1 — mechanische QC (`src/qc/qc.py::deterministic_consistency_check`)
- [x] Layer 2 — domain QC, lichte LLM-review, geen 4 parallelle reviewers
      (`src/qc/qc.py::default_llm_review`)
- [ ] Statusmodel: RAW → VALIDATED → TRIGGERED → DEEP_DIVE_COMPLETE →
      QC_PASSED/FAILED → NEEDS_REVIEW → ARCHIVED (nu: alleen een
      `needs_review`-vlag, geen volledige state machine)

### 1.7 Observability
- [x] System health per component (source, ingestion, database, trigger,
      agent, LLM) (`src/health/system_health.py::system_health`, bouwt op
      `agent_runs` (1.2) en `data_health` (A.3); backend-functie, nog geen
      dashboard-UI — dat is 5.2)
- [x] Fail loudly, not silently — data-health-triggers i.p.v. een stille
      "geen trigger" (A.3-principe, staat al in `health/data_health.py` +
      `triggers/trigger_engine.py::evaluate_data_health`)
- [x] Idempotency: event_id + dedup-key tegen dubbele verwerking
      (`src/storage/schema.py::has_successful_run`,
      `src/agents/base.py::AlreadyProcessedError`, gewired in
      `run_monitoring`/`run_deep_dive` — op `agent_runs`-niveau, niet
      `claims`; zie `docs/architecture.md` "Ontwerpkeuzes" voor de
      afweging. Optioneel/backward-compatible: geen enkele bestaande
      agent geeft nu al een event_id mee, dat komt met een toekomstige
      scheduler)

### 1.8 Orchestrator / Manager
- [x] Deterministische dispatch-logica (`src/manager/manager.py`)
- [x] Gelijktijdige triggers over meerdere domeinen (bv. een Fed-besluit
      dat monetary policy + currency tegelijk raakt — bewezen in
      `tests/test_integration_section_b.py`)
- [x] LLM-taken-tabel expliciet vastleggen (wat mag wel/niet door een LLM
      gedaan worden, systeembreed) (`docs/architecture.md`, sectie
      "LLM-taken-tabel")

### 1.9 Documentatie
- [x] `docs/agents.md` — leesbaar overzicht per agent, geen code lezen nodig
- [x] `docs/architecture.md` — modulekaart, datastroom, ontwerpkeuzes
- [x] `docs/roadmap.md` — dit document
- [x] `docs/project-state.md` — status, grenzen, openstaande vragen
- [x] `CLAUDE.md` — projectbriefing + werkafspraken

---

## 2. Domain Agents — de reasoning-laag (interpretatie, niet berekening)

Volgorde/diepte hier is bewust ONDERGESCHIKT aan sectie 1 — zie "Huidige
focus" hierboven. Per agent eerst de kernmodellen (must-have), dan een
Finetune-lijst (later, DD's eigen optimalisatieproces).

### 2.1 Monetary Policy Agent
- [x] Monitoring mode + deep-dive mode (`src/agents/monetary_policy_agent.py`)
- [x] Taylor Rule (`src/analysis/taylor_rule.py`)
- [ ] Yield curve spreads (2s10s, 3m10y)
- [ ] Fed funds futures-implied rate & surprise-metric
- [ ] Reële rente (nominaal − breakeven inflatie)
- **Finetune (later):** Wu-Xia shadow rate, ACM term premium-model,
  MOVE-index, FOMC dot-plot-dispersie, Fed-balansveranderingen
  (QT/QE-tempo)

### 2.2 Currency Agent
- [x] Monitoring mode + deep-dive mode (`src/agents/currency_agent.py`)
- [ ] UIP / carry-analyse
- [ ] Interest Rate Parity forward-berekening
- [ ] REER-afwijking (mean-reversion)
- [ ] Carry-to-vol ratio
- **Finetune (later):** PPP-afwijking, reëel renteverschil,
  terms-of-trade-index, CFTC COT-positionering, risk reversal-skew

### 2.3 Equity Agent (adapter)
- [x] Dunne adapter: `analyst_agent.ai`'s output in het contract
      (`src/agents/equity_agent.py`)
- [ ] De daadwerkelijke koppeling (hoe een `analyst_agent.ai`-run hier
      terechtkomt — bestand/subprocess/API, nog niet gekozen)
- [ ] Koppeling aan Company Intelligence naast Market Intelligence (zie
      5.5)

### 2.4 Financial Agent
- [x] Monitoring mode + deep-dive mode (`src/agents/financial_agent.py`)
- [ ] Financial Conditions Index als samengestelde z-score (nu: alleen
      NFCI's eigen teken-interpretatie, `src/analysis/nfci_interpretation.py`)
- [ ] Credit spread level & verandering (IG/HY OAS) (nu: alleen HY-spread
      ruw, geen IG-vergelijking)
- [ ] SOFR-OIS-spread
- **Finetune (later):** Senior Loan Officer Survey, VIX-termstructuur,
  Absorption Ratio (Kritzman)

### 2.5 Sector Agent
- [x] Monitoring mode + deep-dive mode (`src/agents/sector_agent.py`)
- [x] Relatieve sterkte t.o.v. de brede markt (`src/analysis/relative_strength.py`)
- [ ] Sector breadth (% boven 200-daags gemiddelde)
- [ ] Cycle-gebaseerd rotatiemodel (voedt uit de economic agent, 2.7)
- **Finetune (later):** earnings revision breadth, Investment Clock-model,
  sector-bèta's naar macro-factoren

### 2.6 Commodity Agent
- [x] Monitoring mode + deep-dive mode (`src/agents/commodity_agent.py`)
- [x] Afwijking t.o.v. 6-maands voortschrijdend gemiddelde
      (`src/analysis/moving_average_deviation.py`) — alternatieve, al
      geïmplementeerde methode; onderstaande zijn de eigenlijke doelmodellen
- [ ] Cost-of-carry-model (contango/backwardation)
- [ ] Stocks-to-use ratio
- [ ] Crack/crush/spark spread
- [ ] WTI-Brent-spread & term-structure-slope
- **Finetune (later):** CFTC COT-positionering, inventory
  days-of-supply, seizoensindex, copper/gold-ratio

### 2.7 Economic Agent — nog niet gestart
- [ ] Monitoring mode + deep-dive mode
- [ ] Sahm Rule (eerste implementatie, hoogste prioriteit binnen deze agent)
- [ ] Output gap (HP-filter op bbp-reeks)
- [ ] Misery Index
- [ ] ISM-diffusie-interpretatie
- [ ] Phillips Curve-residual
- **Finetune (later):** Leading Economic Index (LEI), Okun's Law,
  Beveridge Curve, soft-vs-hard-data-gap, regionale Fed-surveys (Philly
  Fed, Empire State)

### 2.8 News Monitor Agent — nog niet gestart
- [ ] Nieuwsbronnen/feeds bepalen
- [ ] Entity resolution (bv. "Apple" bedrijf vs. aandeel vs. tekstvermelding)
- [ ] Event extraction (who/did what/when/expected impact)
- [ ] Deduplicatie tussen bronnen
- [ ] Novelty detection (voegt een later artikel iets nieuws toe?)
- [ ] Koppeling aan de trigger-laag (1.5) als aanvullende triggerbron

### 2.9 Nasdaq/NQ Regime & Bias Agent — nog niet gestart
- [ ] Beslissing: specifiek NQ of generieke "instrument regime/bias agent"
- [ ] Kwantitatief regime: bestaande HMM (`analyst_agent.ai/src/analysis/simple_hmm.py`)
      toegepast op NQ-prijsdata
- [ ] Kwalitatieve bias-synthese uit alle domain agents
- [ ] Regime ≠ bias ≠ trade-setup — expliciet gescheiden houden, ook in
      het datamodel
- [ ] Dagelijkse auto-update (monitoring mode) + on-demand interface
- **Finetune (later):** realized volatility (Parkinson/Garman-Klass),
  market breadth (advance-decline), put/call-ratio & VIX-termstructuur,
  gamma exposure (GEX), concentratie-/correlatierisico in de index

---

## 3. Synthese & Intelligence — waar losse signalen marktinzicht worden

### 3.1 Cross-Domain Synthesizer
- [x] Eerste, simpele versie: gelijktijdige deep-dives naast elkaar
      (`src/synthesizer/synthesizer.py`) — nog geen tegenstrijdigheid-
      detectie of echte cross-domein-redenering
- [ ] Cross-agent tegenstrijdigheid-detectie
- [ ] Confidence-weging (Bayesiaans: prior-gewicht per domain agent op
      basis van track record, gewogen posterior)
- [ ] Cross-domein implicaties combineren tot één leesbaar geheel
- [ ] Event-chain-reconstructie: nieuws en numerieke data in hetzelfde
      event-model (hangt af van 1.2's event-model)

### 3.2 Statistische synthese-laag — nog niet gestart
- [ ] Z-score-normalisatie over domeinen heen
- [ ] PCA op macro-reeksen (factor-reductie)
- [ ] Rolling correlation / correlatiebreuk-detectie
- [ ] Kalman filter voor ruizige reeksen

### 3.3 Market State & Regime Engine — nog niet gestart
- [ ] Cross-asset regime-aggregatie (breder dan alleen NQ, zie 2.9)
- [ ] Regime/bias/trade-setup strikt gescheiden houden op systeemniveau

---

## 4. Evaluatie & Learning Loop — wat het systeem van chatbot naar
   intelligentie maakt

Nog niets van gebouwd. Dit is de laag die uiteindelijk bewijst of de
onderbouwingsmodellen (sectie 2) en trigger-thresholds (1.5) daadwerkelijk
kloppen — vergelijkbaar met `analyst_agent.ai`'s `compute_calibration_score()`,
maar dan voor dit hele systeem.

### 4.1 Predictions & Outcome Tracking
- [ ] Expliciete, timestamped hypotheses per agent opslaan
- [ ] `outcome_horizon` + actual vs. verwacht vastleggen
- [ ] Predictions als first-class data naast claims

### 4.2 Trigger-kalibratie & Backtesting
- [ ] Held-vs-breached-tracking per trigger-regel
- [ ] Beta-Binomiaal-model (posterior-onzekerheid bij weinig data) i.p.v.
      alleen een held/breached-telling
- [ ] Adaptieve thresholds op basis van kalibratie-resultaten

### 4.3 Agent Track Records
- [ ] Precision/recall/hallucination-rate per agent
- [ ] Agent-reliability-scores als input voor de Bayesiaanse weging (3.1)

### 4.4 Historical Replay Engine
- [ ] Point-in-time-correcte snapshots per databron
- [ ] Systeem laten draaien alsof het een historische datum is
- [ ] Look-ahead/hindsight bias structureel voorkomen

---

## 5. Output & Interfaces — de database is de waarheid, dit is de weergave

Nog niets van gebouwd.

### 5.1 API-laag
- [ ] Eén centrale API op de database
- [ ] Dashboard, alerts, CLI en chat lezen allemaal uit dezelfde bron

### 5.2 Dashboard
- [ ] Dagelijkse stand van zaken per domein
- [ ] Nasdaq-regime/bias prominent zichtbaar

### 5.3 Alert-mechanisme
- [ ] Notificatie bij trigger/escalatie

### 5.4 On-demand Query-interface
- [ ] Vragen kunnen stellen over het hele systeem heen, niet alleen NQ.
      Bevat een aparte "thesis-mode": in tegenstelling tot de automatische
      monitoring/deep-dive-laag (sectie 2, die strikt neutraal blijft —
      zie `agents/base.py`'s docstring) mag deze mode WEL expliciet
      gevraagde directionele/probabilistische antwoorden geven — bijv.
      "ik denk dat de Fed de rente gaat verhogen om deze en deze reden,
      hoe groot is die kans en wat is de thesis ervoor/ertegen" (DD's
      eigen FOMC-voorbeeld). Analoog aan `analyst_agent.ai`'s sectie 18
      (Variant Perception): overal elders neutraal, met één duidelijk
      gelabeld, geïsoleerd kanaal voor opinie.

### 5.5 Analyst Agent-koppeling
- [ ] `analyst_agent.py` als subagent binnen Company Intelligence
- [ ] Company Intelligence naast Market Intelligence in één platform

---

## Open beslissingen (bewust nog niet dichtgetimmerd)

- [ ] Statische vs. adaptieve trigger-thresholds per domein (hangt samen
      met 4.2).
- [ ] Prioritering van domeinen: dagelijkse ICT-trading (kort) vs.
      macro/mid-term-werk (lang) — kan de volgorde binnen sectie 2
      beïnvloeden.
- [ ] Hoeveel domain agents draaien continu vs. alleen op aanvraag.
- [ ] Library + bronnen-hiërarchie per agent, uitgroeiend tot een eigen
      database-hiërarchie: boeken > academische papers > investor letters
      > artikelen > YouTube-video's > nieuwsberichten > X-posts. Analoog
      aan `analyst_agent.ai/src/knowledge/` — dat project heeft dit zelf
      ook als open vraagstuk (`docs/rejected-alternatives.md`,
      evidence-tiering). Raakt waarschijnlijk `Claim`'s `confidence`-veld
      (1.1) zodra dit gebouwd wordt.
