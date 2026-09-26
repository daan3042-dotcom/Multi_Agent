# Roadmap — Market Intelligence Platform

**Bron van waarheid vanaf nu:** dit document. De artifact ["Market
Intelligence Platform — Systeemoverzicht"](https://claude.ai/artifact/PpSZ4yrbWyHRVifuAjoffn)
(DD, 23-09-2026) blijft de **catalogus** van wat er uiteindelijk moet
staan — de vijf pijlers en hun nummering hieronder zijn daaruit
overgenomen en veranderen niet. Wat op 26-09-2026 wél veranderd is, is de
**uitvoeringsvolgorde**: die wordt niet meer bepaald door de
pijlernummering maar door het kritieke pad naar T₀ (zie hieronder).

Vink items af zodra ze klaar zijn én groen zijn in de testsuite.

## Wat er op 26-09-2026 veranderd is, en waarom

De oude volgorde was pijler 1 → 2 → 3 → 4 → 5, met **Evaluatie & Learning
Loop als pijler 4**, ná agents en synthese. Dat is omgedraaid. De reden is
niet dat pijler 4 belangrijker is, maar dat hij als enige **kalendertijd**
kost in plaats van werktijd.

**LLM-agents zijn niet eerlijk te backtesten.** Vraag een model in 2026 om
maart 2020 te analyseren en het weet al wat er volgde. Elke historische
evaluatie van een LLM-agent is besmet met look-ahead bias, hoe netjes de
point-in-time-snapshots van 4.4 ook zijn — 4.4 lost dat op voor de *data*,
niet voor het *model*. Gevolg: **forward testing is niet een optie maar de
enige geldige weg**, en de klok kan pas gaan lopen als er een
voorspellings- en scoringlaag staat.

Praktische implicatie: alles wat géén voorwaarde is voor "de klok kan
lopen" schuift naar achteren — ook wat intellectueel interessanter is
(Wu-Xia shadow rate, GEX, PCA). Alles wat wél voorwaarde is, schuift naar
voren, ook als het saai is.

**De nieuwe volgorde:**

> deblokkeren → causaal model → voorspellingscontract → scoring → **T₀** →
> verdiepen terwijl het draait → Bayesiaanse laag

De pijlernummering (1.x t/m 5.x) blijft ongewijzigd, zodat code-comments
die naar "roadmap 1.7" of "sectie 2.4" verwijzen blijven kloppen. De fasen
hieronder verwijzen naar die nummers; ze vervangen ze niet.

**Mapping oud → nieuw** (voor code-comments met de oorspronkelijke
lettering, bijv. "stap B.1" of "sectie C.1"):

| Oud | Nieuw |
|---|---|
| A (Fundament) | 1. Infrastructuur & Data |
| B (monetary+currency skeleton) + C (Domain Agents) | 2. Domain Agents |
| D (News monitor) | 2.8 News Monitor Agent |
| E (Nasdaq/NQ regime) | 2.9 Nasdaq/NQ Regime & Bias Agent |
| F (Synthesizer volwassen maken) | 3.1 Cross-Domain Synthesizer |
| G (Output & interface) | 5. Output & Interfaces |
| H (Open beslissingen) | Open beslissingen (onderaan) |
| I (Later/optioneel) | Finetune-lijsten per agent (sectie 2) en 4.1 |

---

# DEEL A — Uitvoeringsvolgorde

Dit deel bepaalt **wat er wanneer gebeurt**. Deel B is de catalogus van
alle onderdelen met hun vaste nummers.

## Huidige focus

**Fase 0 (Deblokkeren) — sectie 1.11.** Stand per 26-09-2026: de runner,
de notificatielaag en het entrypoint zijn gebouwd en getest (280 tests
groen). Wat nog open is, is niet-code: de VPS kiezen en uitrollen (API-keys
+ `MI_WEBHOOK_URL` + cron), en daarna de back-fill. Zolang dat niet draait,
is elke andere taak voorbarig.

## De drie harde blokkades

Deze staan tussen ons en T₀. Zolang er één openstaat, kan de klok niet
lopen. Ze gaan vóór elk ander item op deze hele roadmap.

| # | Blokkade | Waarom dit blokkeert | Sectie |
|---|---|---|---|
| 1 | Geen live data (403 op FRED/Alpha Vantage, org-egress-policy) | Zonder live data is forward testing per definitie onmogelijk | 1.11 |
| 2 | Geen scheduler — alles draait handmatig | Een forward test die van handmatig draaien afhangt krijgt gaten, en gaten maken de kalibratie ongeldig: als we de moeilijke weken missen omdat we het vergaten, ziet het track record er systematisch beter uit dan het is | 1.11 |
| 3 | `predictions` bestaat niet als entiteit | Er is niets te scoren | 1.2 / 4.1 |

Blokkade 3 verschuift een grens die eerder bewust getrokken was: in 1.2
stond `predictions` als "hoort bij pijler 4/5, bewust nog niet nu". Die
grens is per 26-09-2026 verlegd.

## Fase 0 — Deblokkeren (week 1–2)

**Doel:** het systeem draait elke dag zonder tussenkomst, met echte data.

| Taak | Sectie | Definition of done |
|---|---|---|
| ~~`run_daily.py` + cron-entrypoint, idempotent via `event_id`~~ **gebouwd** | 1.11 | ✅ Twee keer draaien op dezelfde dag geeft geen dubbele rijen (`tests/test_runtime_daily.py`) |
| ~~Fail-loud-notificatie bij een mislukte of stille run~~ **gebouwd** | 1.7 / 1.11 | ✅ Melding zodra een bron zijn `max_age` overschrijdt of een agent faalt |
| VPS kiezen en uitrollen (API-keys, `MI_WEBHOOK_URL`, cron) | 1.11 | FRED + Alpha Vantage leveren 7 dagen op rij data zonder handmatige actie |
| Back-fill van de historische reeksen | 1.11 | Elke gemonitorde metric heeft ≥5 jaar historie in de database |
| Triggerdrempels kalibreren tegen die historie | 1.5 / 4.2 | Per regel bekend hoe vaak hij de afgelopen 5 jaar zou zijn gevuurd |

**Waarom de back-fill nu al:** de triggerdrempels staan op illustratieve
waarden (zie Open beslissingen). Met historie is uit te rekenen hoe vaak
elke drempel de afgelopen vijf jaar geraakt zou zijn. Een drempel die 200
keer per jaar vuurt is ruis, één die twee keer vuurt is blind. Dit is de
enige vorm van backtesten die hier wél geldig is, omdat het puur
deterministisch is — geen LLM in de lus, dus geen hindsight.

**Ontkoppeling die hieruit volgt:** ingestion draait op eigen infra, agents
en LLM-calls mogen blijven waar ze zijn. Dat was toch al wenselijk.

## Fase 1 — De causale graaf (week 2–4, parallel aan fase 0)

**Doel:** één gedeeld model van de economische machine waar alle agents op
schrijven. Sectie 1.10.

Dit is handwerk voor DD en zijn partner, geen codeerwerk. Het is ook het
enige deel van het plan waar echte edge kan ontstaan — de rest is
infrastructuur die iedereen kan bouwen.

**Waarom dit de architectuur verandert:** de zes bestaande domain agents
produceren nu elk hun eigen vrijzwevende analyse. Zonder gedeeld model kan
de currency agent stilzwijgend het tegendeel beweren van de monetary agent
en merkt niemand het — de synthesizer plakt het dicht met vloeiend
Nederlands. 3.1 noemt "cross-agent tegenstrijdigheid-detectie" als taak,
maar dat is op vrije tekst niet betrouwbaar op te lossen. Met een gedeelde
graaf wordt tegenstrijdigheid een **meetbaar conflict op een knoop**, geen
stijlkwestie.

Deliverables: `docs/causal-graph.md` (het sjabloon staat er al) en
`src/contract/graph.py` met de knopen als enum. Meer niet.

## Fase 2 — Het voorspellingscontract (week 3–6)

**Doel:** agents produceren falsifieerbare uitspraken in plaats van
rapporten. Secties 1.2 (entiteit) en 4.1 (contract).

Dit is de belangrijkste inhoudelijke omkering in het plan: **het LLM wordt
evidence extractor, niet forecaster.** Taalmodellen zijn slecht in
kansschatting en getallen, en goed in het lezen van ongestructureerde
tekst. Laat ze dus notulen, persconferenties en nieuws omzetten in
gestructureerde waarnemingen op graafknopen, en houd de probabilistiek in
Python. Dit is dezelfde regel als "Python computes, Claude narrates" uit
`analyst_agent.ai`, hier toegepast op kansen.

Zie 4.1 voor de velden. Drie punten die de volgorde bepalen:

**`resolution_rule` is verplicht.** De exacte, machine-uitvoerbare regel
waarmee straks bepaald wordt of een voorspelling uitkwam. Zonder dat veld
volgt over zes maanden een discussie over wat de agent "eigenlijk
bedoelde", en dan is het hele track record waardeloos.

**Kansen zijn verplicht, geen "waarschijnlijk".** Zonder expliciete kansen
zijn er geen proper scoring rules, zonder scoring rules geen
betrouwbaarheidsgewichten, en dan is de "Bayesiaanse weging op basis van
track record" van 3.1 een gemiddelde met extra stappen.

**Horizonnen kort genoeg voor statistische power.** Gerekend met de
eindsituatie van ~7 voorspellende agents (de zes die er nu zijn plus de
economic agent) × ~5 voorspellingen per week: ~35/week, ~900 na zes
maanden, waarvan per agent ~130 resolved. Dat is genoeg voor ruwe
kalibratie per agent, te dun voor regime-conditionele weging. Daarom:
**5, 21 en 63 dagen**, niet 6 en 12 maanden — een 12-maands voorspelling
levert binnen het tijdsbestek nul datapunten op. De
lange-termijn-views komen later, gebouwd op agents waarvan op korte
horizon al bekend is dat ze gekalibreerd zijn.

## Fase 3 — De scoring engine (week 5–8)

**Doel:** voorspellingen worden automatisch en onherroepelijk gescoord.
Secties 4.5 (scoring) en 4.6 (baselines).

Dit is de saaiste component en verreweg de waardevolste. Vrijwel niemand
bouwt hem, en zonder deze laag heeft de Bayesiaanse weging geen priors om
mee te werken.

**De baselines zijn geen bijzaak.** Zonder baseline is niet vast te
stellen of hier iets gebouwd is of alleen kosten gemaakt zijn. Een agent
die na zes maanden noch random-walk noch climatology verslaat, gaat eruit.

## T₀ — de klok gaat lopen

**Streefdatum: 10 november 2026.**

Vanaf T₀ draait het systeem dagelijks en wordt elke voorspelling
vastgelegd en gescoord.

**Checklist (alle zes verplicht):**

- [ ] Dagelijkse automatische run met live data, 14 dagen op rij zonder handmatige actie (1.11)
- [ ] Causale graaf vastgelegd; agents schrijven op knopen (1.10)
- [ ] `predictions`-tabel met verplichte kans en `resolution_rule` (1.2 / 4.1)
- [ ] Resolver draait en heeft minstens één cohort correct afgewikkeld (4.5)
- [ ] Beide baselines draaien mee (4.6)
- [ ] Triggerdrempels gekalibreerd tegen ≥5 jaar historie (1.5 / 4.2)

**Wat er ná T₀ verandert aan de werkwijze:** de causale graaf, het
predictiecontract en de resolution rules worden semi-bevroren. Elke
wijziging krijgt een versienummer en start effectief een nieuw cohort. Als
we halverwege de drempels verschuiven omdat de resultaten tegenvallen,
hebben we geen track record meer maar een overfit. Zie de afspraak
hierover in `CLAUDE.md`.

## Fase 4 — Verdiepen terwijl het draait (nov 2026 – apr 2027)

Vanaf T₀ loopt de klok vanzelf. Alles hieronder loopt daar parallel aan en
is **niet blokkerend**. Volgorde op waarde, niet op pijlernummer:

**Prioriteit hoog**

1. **Economic Agent** (2.7) — Sahm Rule eerst. De graaf heeft groei-knopen
   die nu door niemand bediend worden.
2. **News Monitor Agent** (2.8), maar smal: alleen event extraction naar
   graafknopen. Entity resolution, novelty detection en dedup zijn een
   eigen project; begin met 3–5 betrouwbare feeds en handmatig
   gedefinieerde entiteiten.
3. **Contradictie-detectie** (3.1) — nu eenvoudig, want het is een
   conflict op een knoop, geen tekstvergelijking.
4. **Minimaal dashboard** (5.2) — kalibratiecurves en Brier per agent. Als
   we het eigen track record niet dagelijks zien, stuurt niemand bij.

**Prioriteit midden**

5. **Regime als latente variabele** (2.9 / 3.3) — Markov-switching / HMM
   die een *posterior over regimes* geeft in plaats van een label. De
   NQ-agent wordt dan geen aparte analist maar een conditionele verdeling:
   gegeven de regimeposterior en de graafstand, wat is de verwachte
   verdeling van NQ over horizon X.
6. **Kalman filter** (3.2) voor ruizige reeksen.

**Prioriteit laag — bewust uitgesteld**

- Alle **Finetune-items** in sectie 2. Dit zijn tientallen taken die stuk
  voor stuk iets toevoegen en samen maanden kosten. Ze mogen pas als de
  kalibratie laat zien welk domein zwak is — dán is bekend welke tien van
  de vijftig het waard zijn.
- **PCA op macro-reeksen** (3.2). Met ~10–15 echte cycli in bruikbare data
  is factorreductie op macro een overfit-machine.
- De resterende 1.2-entiteiten, de API-laag (5.1) en de on-demand
  query-interface (5.4).

## Fase 5 — De Bayesiaanse laag (vanaf mei 2027)

Sectie 3.4. Pas nu is er waar deze laag op draait: een half jaar
gescoorde, gekalibreerde voorspellingen.

## Tijdlijn

| Periode | Fase | Uitkomst |
|---|---|---|
| 29 sep – 12 okt | 0. Deblokkeren | Dagelijks automatisch, live data |
| 6 okt – 20 okt | 1. Causale graaf | 15–25 knopen vastgelegd (handwerk) |
| 13 okt – 3 nov | 2. Voorspellingscontract | Agents produceren falsifieerbare kansen |
| 27 okt – 10 nov | 3. Scoring engine | Resolver + Brier + baselines |
| **10 nov 2026** | **T₀** | **De klok loopt** |
| nov – apr | 4. Verdiepen | Economic + news agent, regime-HMM, dashboard |
| **mei 2027** | 5. Bayesiaanse laag | Gewichten uit echt track record |

Fase 0 en 1 lopen parallel omdat de een code is en de ander handwerk —
meteen de natuurlijke rolverdeling: DD fase 0, partner fase 1, samen
fase 2.

## Herzieningsmomenten

Vaste momenten, zodat dit niet "als we eraan denken" wordt:

| Moment | Datum (bij T₀ = 10-11-2026) | Wat we bekijken |
|---|---|---|
| T₀ + 6 weken | ~22 december 2026 | **Alleen mechanica**: draait het elke dag, resolven voorspellingen correct, zitten er gaten in de reeks? Nog **niet** naar de scores kijken — die zeggen bij n≈50 niets en uitnodigen tot sleutelen |
| T₀ + 3 maanden | ~10 februari 2027 | Eerste voorlopige kalibratie. Eén vraag: verslaat *enige* agent de baselines, inclusief onzekerheidsband? Zo nee, dan is er iets fundamenteel mis met het voorspellingscontract — beter nu te weten dan in mei |
| T₀ + 6 maanden | ~10 mei 2027 | Volledige evaluatie, niet-presterende agents eruit, dán pas de Bayesiaanse laag (3.4) |

## Scope-afbakening die expliciet is gemaakt

Dit systeem verbetert DD's kortetermijn-ICT-daytrading op MNQ vrijwel
niet: de horizonnen zitten op dagen tot maanden, het daghandelen op
minuten tot uren. Het kan hooguit de directionele bias en het risicobudget
per dag kleuren, en zelfs dat moet met de scoring engine bewezen worden
voordat erop geleund wordt. Dit is de CTA-/macro-kant van TCE die naast de
daghandel wordt opgebouwd, niet een verbetering ervan. DD heeft dit op
26-09-2026 bevestigd als bewuste keuze.

---

# DEEL B — De pijlers (catalogus)

Nummering ongewijzigd t.o.v. 24-09-2026, zodat code-comments blijven
kloppen. Nieuwe secties sinds 26-09-2026 zijn gemarkeerd met **[nieuw]**.
De volgorde waarin dit gebouwd wordt staat in deel A, niet hier.

## 1. Infrastructuur & Data — fundament, geen agents

### 1.1 Output Contract & Domain Ontologie
- [x] Claim-contract: waarde, bron, confidence (`src/contract/output_contract.py`)
- [x] Vier tijdstempels: event_time / source_time / ingestion_time /
      analysis_time (`src/contract/output_contract.py`)
- [x] Domain ontologie vastleggen (Equities, Rates, FX, Commodities,
      Credit, Macro, Sectors, Companies) (`src/contract/domain_ontology.py`)
- [ ] **[nieuw]** `graph_node` als veld op `Claim` — welke knoop uit de
      causale graaf (1.10) deze claim raakt. Optioneel tijdens de
      overgang, verplicht vanaf T₀.

### 1.2 Database & Event Store
- [x] Database-schema als source of truth (`src/storage/schema.py`)
- [ ] Event-model: raw data → observation → event (conceptueel pad, wordt
      concreet zodra de entiteiten hieronder er zijn om het te dragen)
- [x] Entiteit: claims (`src/storage/schema.py`, al vanaf de start)
- [x] Entiteit: triggers (`trigger_events`-tabel, al vanaf de start;
      **sinds 1.11 ook daadwerkelijk gevuld** — `record_trigger_event()`
      werd tot dan toe alleen in tests aangeroepen, dus vuurden er triggers
      die nergens werden vastgelegd. Dat gat zat in precies de reeks die
      1.5/4.2 nodig hebben om drempels te kalibreren)
- [x] Entiteit: agent_runs — audit-log per monitoring/deep-dive-run
      (`src/storage/schema.py::record_agent_run/list_agent_runs`)
- [x] Entiteit: sources (`src/storage/schema.py` — `sources`-tabel,
      gebouwd samen met 1.4 Source Registry, zie daar)
- [ ] **Entiteit: predictions — T₀-BLOKKADE, hoogste prioriteit binnen
      1.2.** Stond hier eerder als "hoort bij pijler 4/5, bewust nog niet
      nu"; die grens is op 26-09-2026 verlegd omdat er zonder deze tabel
      niets te scoren valt. Velden en semantiek: zie 4.1.
- [ ] **[nieuw]** Entiteit: evaluations — de uitkomst per resolved
      prediction (outcome, Brier, log loss). Apart van `predictions`
      omdat een prediction onveranderlijk is en een evaluation later
      ontstaat. Zie 4.5.
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
- [ ] Entiteiten: alerts, regimes, theses (horen bij pijler 3/5, bewust
      nog niet nu)

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
- [ ] **Trigger-versioning (welke regel-versie was actief toen dit
      triggerde) — T₀-BLOKKADE.** Dit stond hier al, maar is nu kritiek
      pad: zonder versienummer is een kalibratie over een periode waarin
      een drempel verschoven is niet te interpreteren. Zie 4.2.
- [ ] **Drempels kalibreren tegen ≥5 jaar historie (fase 0)** — hoe vaak
      zou elke regel gevuurd hebben? Vervangt de huidige illustratieve
      waarden.
- [ ] Trigger severity: INFO / WATCH / SIGNIFICANT / CRITICAL (nu:
      low/medium/high)
- [ ] Vier triggertypes: threshold, regime-transitie, event, cross-
      variable/correlatiebreuk (nu: threshold + surprise + revisie +
      data-health — regime-transitie en cross-variable ontbreken nog;
      regime-transitie wacht op 3.3, cross-variable is post-T₀)

### 1.6 QC & State Machine
- [x] Layer 1 — mechanische QC (`src/qc/qc.py::deterministic_consistency_check`)
- [x] Layer 2 — domain QC, lichte LLM-review, geen 4 parallelle reviewers
      (`src/qc/qc.py::default_llm_review`)
- [x] Statusmodel: RAW → VALIDATED → TRIGGERED → DEEP_DIVE_COMPLETE →
      QC_PASSED/FAILED → NEEDS_REVIEW → ARCHIVED
      (`src/qc/qc.py::QCCaseStatus/QC_TRANSITIONS`, eigen `qc_cases`-tabel
      in `src/storage/schema.py`, automatisch gewired in
      `agents/base.py::run_monitoring/run_deep_dive`; ARCHIVED is de enige
      handmatige overgang, `storage.schema.archive_qc_case()`).
      `DomainOutput.needs_review` blijft bestaan — een case volgt de
      VOLLEDIGE levenscyclus, `needs_review` blijft het eindoordeel dat de
      synthesizer/manager direct leest.
- [x] `QualityStatus` (roadmap 1.3) gewired als (mede-)input voor
      QC_PASSED/FAILED (`qc.qc.decide_qc_outcome`) — een data_health-
      oorsprong-trigger met severity high (INVALID) faalt een case ALTIJD,
      ongeacht een verder schone tekst. GEEN vanzelfsprekende 1-op-1-
      mapping, uitgebreid beargumenteerd in `docs/architecture.md`
      ("Ontwerpkeuzes"). De vier 1.3-checks zelf (completeness/validity/
      consistency/continuity) blijven bewust ongewired, zoals bij 1.3
      afgesproken.
- [ ] **[nieuw]** Mechanische QC uitbreiden naar predictions: een
      prediction zonder `probability`, `resolution_rule` of `resolves_at`
      wordt geweigerd, niet gevlagd. Dit is de ene plek waar `NEEDS_REVIEW`
      niet volstaat — een onscoorbare voorspelling vervuilt het track
      record permanent.

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
      afweging. **Sinds 1.11 daadwerkelijk in gebruik:** `runtime/daily.py`
      geeft `daily:<UTC-datum>` mee en alle 5 agent-wrappers zetten 'm
      door, dus een tweede run op dezelfde dag wordt overgeslagen i.p.v.
      dubbel geteld)
- [x] **Uitgaande notificatie bij een stille run** — de bestaande
      `system_health()` was een functie die iemand moest aanroepen. Vanaf
      T₀ draait niemand handmatig, dus er moet iets actief melden.
      Gebouwd in `src/runtime/notifications.py`, aangeroepen aan het eind
      van elke `run_daily()`-cyclus

### 1.8 Orchestrator / Manager
- [x] Deterministische dispatch-logica (`src/manager/manager.py`)
- [x] Gelijktijdige triggers over meerdere domeinen (bv. een Fed-besluit
      dat monetary policy + currency tegelijk raakt — bewezen in
      `tests/test_integration_section_b.py`)
- [x] LLM-taken-tabel expliciet vastleggen (wat mag wel/niet door een LLM
      gedaan worden, systeembreed) (`docs/architecture.md`, sectie
      "LLM-taken-tabel")
- [ ] **[nieuw]** LLM-taken-tabel uitbreiden met de regel uit fase 2: een
      LLM mag waarnemingen extraheren en een causale keten formuleren,
      maar **nooit** de uiteindelijke kans berekenen of aggregeren. Dat is
      Python (3.4).

### 1.9 Documentatie
- [x] `docs/agents.md` — leesbaar overzicht per agent, geen code lezen nodig
- [x] `docs/architecture.md` — modulekaart, datastroom, ontwerpkeuzes
- [x] `docs/roadmap.md` — dit document
- [x] `docs/project-state.md` — status, grenzen, openstaande vragen
- [x] `CLAUDE.md` — projectbriefing + werkafspraken
- [x] **[nieuw]** `docs/causal-graph.md` — sjabloon staat, invullen is
      fase 1 (zie 1.10)

### 1.10 Causale Graaf & Knoop-ontologie — **[nieuw]**, fase 1

Eén expliciet, door mensen geschreven model van de economische machine.
Dit is wat een Dalio-achtig systeem onderscheidt van een verzameling
losse analisten: de causale structuur is expliciet en handgeschreven, de
inferentie deterministisch, en het taalmodel voedt hem alleen met
waarnemingen.

- [ ] 15–25 knopen vastleggen in `docs/causal-graph.md` (handwerk, DD +
      partner). Voorbeelden van knooptypen: groei, inflatie,
      kredietimpuls, liquiditeit, beleidsstance, financiële condities,
      risicopremie, dollar, termijnpremie
- [ ] Per pijl: richting, verwachte vertraging, en de waarneembare metric
      die hem het beste meet
- [ ] `src/contract/graph.py` — de knopen als enum, zodat een claim of
      prediction er machine-checkbaar naar kan verwijzen
- [ ] Per domain agent vastleggen welke knopen hij bedient (in
      `docs/agents.md`)
- [ ] Graaf-versionering: elke wijziging na T₀ krijgt een versienummer en
      start een nieuw cohort

**Bewust NIET nu:** de graaf omzetten in een Bayesiaans netwerk met
kansen. Dat is 3.4, ná zes maanden data. Nu alleen de structuur.

### 1.11 Scheduler & Runtime — **[nieuw]**, fase 0, T₀-BLOKKADE

De drie blokkades uit deel A. Dit is de enige sectie waaraan nu gewerkt
wordt.

- [ ] **Ingestion uit de sandbox.** Fetch-runner op eigen infra (VPS,
      Pi, of een van onze machines) die alleen ruwe data ophaalt en in de
      SQLite schrijft. Agents en LLM-calls mogen blijven waar ze zijn.
      Lost de 403/org-egress-policy op die sinds 24-09-2026 live
      validatie blokkeert. **Code is klaar (zie hieronder); wat rest is
      het uitrollen op de gekozen machine met echte API-keys.**
- [x] **`run_daily.py` + cron.** Idempotent via de `event_id` uit 1.7 —
      die was gebouwd maar werd door geen enkele agent meegegeven; dit is
      de aanroeper waarop 1.7 wachtte. `src/runtime/daily.py` (cyclus,
      foutisolatie per agent, opt-in deep-dives), `run_daily.py`
      (entrypoint + exit codes), `event_id` doorgezet in alle 5
      monitor/deep_dive-wrappers. Cron-regel staat in `run_daily.py`'s
      docstring. Zie `docs/architecture.md` ("Ontwerpkeuzes in de
      runtime-laag") voor de afwegingen
- [x] **Actieve fail-loud-notificatie** (zie 1.7):
      `src/runtime/notifications.py` — kanaal-onafhankelijk
      (`webhook_notifier` werkt met ntfy/Telegram/Discord/Slack), meldt
      alleen als er iets mis is, en drempels komen uit de Source Registry
      in plaats van uit een eigen constante. **Let op:** zonder
      `MI_WEBHOOK_URL` gaat een melding alleen naar de log, en dat is op
      een onbeheerde machine geen fail-loud — die URL is onderdeel van het
      uitrollen
- [ ] **Back-fill** van elke gemonitorde metric, ≥5 jaar
- [ ] Per-domein cadans: welke agent draait dagelijks, welke wekelijks.
      Dit was bewust uitgesteld "tot er een scheduler is" — die is er nu,
      dus de beslissing komt hier terug
- [ ] **Externe dead man's switch.** `run_daily()` detecteert nu zelf
      gaten in de afgelopen 7 dagen, maar alleen bij de eerstvolgende run
      die wél draait. Staat de machine drie weken uit, dan hoort niemand
      iets — elke melding komt uit een draaiende run. Een externe
      heartbeat-ping die alarmeert bij UITBLIJVEN hoort buiten dit systeem
      te draaien
- [ ] **Atomiciteit tussen claims en de dedup-rij** (`agents/base.py::
      run_monitoring`). `schema.py` commit per insert, dus een crash tussen
      `save_domain_output()` en `record_agent_run()` laat claims achter
      zonder dedup-rij, en de volgende run slaat dezelfde claims nog een
      keer op. Vraagt om transactiecontrole in `schema.py` — raakt alle
      bestaande aanroepers, dus bewust niet stilletjes meegenomen in 1.11
- [ ] **Ouderdomsgrens in `system_health()`**: één mislukte deep-dive maakt
      `llm` en `agent:<domein>` permanent `unreachable`, wat elke dag een
      kritieke melding geeft — precies de alert-moeheid die de
      notificatielaag moet voorkomen

---

## 2. Domain Agents — de reasoning-laag (interpretatie, niet berekening)

**Prioriteit binnen deze pijler is per 26-09-2026 gewijzigd.** Niet meer
"pijler 1 eerst, dan meer modellen", maar: elke bestaande agent moet
predictions kunnen produceren (fase 2) vóór T₀; nieuwe agents en alle
Finetune-items zijn post-T₀. De Finetune-lijsten blijven staan als
catalogus, maar worden pas aangeraakt als de kalibratie laat zien welk
domein zwak is.

### 2.0 Predictions per agent — **[nieuw]**, fase 2, geldt voor 2.1 t/m 2.9

- [ ] `agents/base.py` uitbreiden: elke agent produceert naast claims ook
      predictions volgens het contract van 4.1
- [ ] Per agent vastleggen welke graafknopen hij bedient (1.10) en op
      welke horizonnen hij voorspelt
- [ ] Richtlijn: ~5 voorspellingen per agent per week, horizonnen 5/21/63
      dagen (zie fase 2 voor de rekensom achter die aantallen)

### 2.1 Monetary Policy Agent
- [x] Monitoring mode + deep-dive mode (`src/agents/monetary_policy_agent.py`)
- [x] Taylor Rule (`src/analysis/taylor_rule.py`)
- [ ] Yield curve spreads (2s10s, 3m10y)
- [ ] Fed funds futures-implied rate & surprise-metric
- [ ] Reële rente (nominaal − breakeven inflatie)
- **Finetune (post-T₀):** Wu-Xia shadow rate, ACM term premium-model,
  MOVE-index, FOMC dot-plot-dispersie, Fed-balansveranderingen
  (QT/QE-tempo)

### 2.2 Currency Agent
- [x] Monitoring mode + deep-dive mode (`src/agents/currency_agent.py`)
- [ ] UIP / carry-analyse
- [ ] Interest Rate Parity forward-berekening
- [ ] REER-afwijking (mean-reversion)
- [ ] Carry-to-vol ratio
- **Finetune (post-T₀):** PPP-afwijking, reëel renteverschil,
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
- **Finetune (post-T₀):** Senior Loan Officer Survey, VIX-termstructuur,
  Absorption Ratio (Kritzman)

### 2.5 Sector Agent
- [x] Monitoring mode + deep-dive mode (`src/agents/sector_agent.py`)
- [x] Relatieve sterkte t.o.v. de brede markt (`src/analysis/relative_strength.py`)
- [ ] Sector breadth (% boven 200-daags gemiddelde)
- [ ] Cycle-gebaseerd rotatiemodel (voedt uit de economic agent, 2.7)
- **Finetune (post-T₀):** earnings revision breadth, Investment
  Clock-model, sector-bèta's naar macro-factoren

### 2.6 Commodity Agent
- [x] Monitoring mode + deep-dive mode (`src/agents/commodity_agent.py`)
- [x] Afwijking t.o.v. 6-maands voortschrijdend gemiddelde
      (`src/analysis/moving_average_deviation.py`) — alternatieve, al
      geïmplementeerde methode; onderstaande zijn de eigenlijke doelmodellen
- [ ] Cost-of-carry-model (contango/backwardation)
- [ ] Stocks-to-use ratio
- [ ] Crack/crush/spark spread
- [ ] WTI-Brent-spread & term-structure-slope
- **Finetune (post-T₀):** CFTC COT-positionering, inventory
  days-of-supply, seizoensindex, copper/gold-ratio

### 2.7 Economic Agent — post-T₀, hoogste prioriteit in fase 4
De graaf (1.10) krijgt groei-knopen die door geen enkele bestaande agent
bediend worden. Dat is de reden dat deze agent bovenaan fase 4 staat en
niet lager.
- [ ] Monitoring mode + deep-dive mode
- [ ] Sahm Rule (eerste implementatie, hoogste prioriteit binnen deze agent)
- [ ] Output gap (HP-filter op bbp-reeks)
- [ ] Misery Index
- [ ] ISM-diffusie-interpretatie
- [ ] Phillips Curve-residual
- **Finetune (post-T₀):** Leading Economic Index (LEI), Okun's Law,
  Beveridge Curve, soft-vs-hard-data-gap, regionale Fed-surveys (Philly
  Fed, Empire State)

### 2.8 News Monitor Agent — post-T₀, bewust smal beginnen
Het LLM is hier op zijn sterkst: ongestructureerde tekst omzetten in
gestructureerde waarnemingen op graafknopen. Entity resolution, dedup en
novelty detection zijn elk een eigen project en zijn NIET nodig voor een
eerste bruikbare versie.
- [ ] 3–5 betrouwbare feeds, handmatig gedefinieerde entiteiten
- [ ] Event extraction naar graafknopen (who/did what/when/expected impact)
- [ ] Koppeling aan de trigger-laag (1.5) als aanvullende triggerbron
- [ ] **Later:** entity resolution, deduplicatie tussen bronnen, novelty
      detection

### 2.9 Nasdaq/NQ Regime & Bias Agent — post-T₀
**Herzien op 26-09-2026:** dit wordt geen aparte analist maar een
conditionele verdeling. Gegeven de regimeposterior (3.3) en de stand van
de causale graaf: wat is de verwachte verdeling van NQ over horizon X.
Reden: deze agent consumeert de output van alle andere en versterkt hun
fouten in plaats van ze uit te middelen — hij is dus pas zinvol als van
die andere agents bekend is hoe betrouwbaar ze zijn.
- [ ] Beslissing: specifiek NQ of generieke "instrument regime/bias agent"
- [ ] Regime als latente variabele, niet als label — posterior over
      regimes uit 3.3
- [ ] Kwalitatieve bias-synthese uit alle domain agents
- [ ] Regime ≠ bias ≠ trade-setup — expliciet gescheiden houden, ook in
      het datamodel
- [ ] Dagelijkse auto-update (monitoring mode) + on-demand interface
- **Finetune (post-T₀):** realized volatility (Parkinson/Garman-Klass),
  market breadth (advance-decline), put/call-ratio & VIX-termstructuur,
  gamma exposure (GEX), concentratie-/correlatierisico in de index

---

## 3. Synthese & Intelligence — waar losse signalen marktinzicht worden

### 3.1 Cross-Domain Synthesizer
- [x] Eerste, simpele versie: gelijktijdige deep-dives naast elkaar
      (`src/synthesizer/synthesizer.py`) — nog geen tegenstrijdigheid-
      detectie of echte cross-domein-redenering
- [ ] Cross-agent tegenstrijdigheid-detectie — **eenvoudiger geworden
      door 1.10**: een conflict op een graafknoop, geen tekstvergelijking
- [ ] Cross-domein implicaties combineren tot één leesbaar geheel
- [ ] Event-chain-reconstructie: nieuws en numerieke data in hetzelfde
      event-model (hangt af van 1.2's event-model)
- [ ] ~~Confidence-weging (Bayesiaans)~~ → **verplaatst naar 3.4**; kan
      niet hier blijven omdat het track record uit 4.5 een harde
      voorwaarde is

### 3.2 Statistische synthese-laag — post-T₀
- [ ] Z-score-normalisatie over domeinen heen
- [ ] Rolling correlation / correlatiebreuk-detectie
- [ ] Kalman filter voor ruizige reeksen
- [ ] ~~PCA op macro-reeksen~~ — **bewust naar de achtergrond**: met
      ~10–15 echte cycli in bruikbare data is factorreductie op macro een
      overfit-machine. Niet geschrapt, wel expliciet laag geprioriteerd

### 3.3 Market State & Regime Engine — post-T₀
- [ ] Regime als **latente variabele**: Markov-switching / HMM op macro-
      en marktdata die een posterior over regimes geeft, geen label
- [ ] Cross-asset regime-aggregatie (breder dan alleen NQ, zie 2.9)
- [ ] Regime/bias/trade-setup strikt gescheiden houden op systeemniveau

### 3.4 Probabilistische aggregatie — **[nieuw]**, fase 5 (mei 2027)

De eigenlijke Bayesiaanse laag. Draait volledig in Python (PyMC / NumPyro
/ pgmpy); **het LLM raakt deze laag nooit aan**. Voorwaarde: ≥6 maanden
gescoorde predictions uit 4.5.

- [ ] **Correlatiecorrectie tussen agents.** Het moeilijkste punt hier.
      De agents zijn níet onafhankelijk: ze lezen deels dezelfde bronnen
      en draaien op hetzelfde onderliggende model. Vijf agents die het
      eens zijn is vaak één waarneming die vijf keer geteld wordt. Een
      naïeve Bayesiaanse update behandelt dat als vijf bevestigingen en
      produceert posteriors die structureel te zelfverzekerd zijn —
      precies op de momenten waarop we op het systeem zouden willen
      leunen. Nodig: empirische correlatiematrix uit de historische
      forecasterrors (die hebben we dan), plus extremizing van de
      gepoolde kans
- [ ] **Logarithmic opinion pool / Bayesian model averaging**, met
      gewichten uit 4.3/4.5
- [ ] **Hiërarchisch model met partial pooling.** Met ~130 resolved
      predictions per agent is een aparte schatting per agent per regime
      hopeloos dun; partial pooling laat elke agent naar het
      groepsgemiddelde krimpen naarmate hij minder data heeft. Dit is het
      verschil tussen bruikbare en onzinnige gewichten in jaar één
- [ ] **Bayesiaans netwerk over de causale graaf** (1.10): knopen,
      pijlen, vertragingen uit fase 1, met kansen die uit de data komen
- [ ] Gewichten conditioneel op regime (3.3) — een agent die goed is in
      een verkrappingscyclus is dat niet automatisch in een verruiming
- [ ] **Beslissing gescheiden van view**: Black-Litterman (marktprior +
      views met confidence), sizing via fractional Kelly op de posterior,
      niet op overtuiging. Views en positionering apart scoren

---

## 4. Evaluatie & Learning Loop — het kritieke pad, niet de sluitpost

**Herzien op 26-09-2026.** Dit was pijler 4 in volgorde; het is nu de
pijler die T₀ definieert. 4.1, 4.5 en 4.6 zijn T₀-blokkades; 4.2 en 4.3
lopen mee vanaf T₀; 4.4 blijft post-T₀.

### 4.1 Predictions & Outcome Tracking — T₀-BLOKKADE, fase 2

Elke uitspraak van het systeem wordt een falsifieerbare claim:
onveranderlijk, met tijdstempel, en met de regel waarmee hij later
gescoord wordt er al in.

- [ ] `Prediction`-contract met minimaal deze velden:

  | Veld | Waarom |
  |---|---|
  | `prediction_id`, `agent`, `created_at` | identiteit en `analysis_time` |
  | `graph_node` | welke knoop uit 1.10 |
  | `direction` | up / down / unchanged |
  | `magnitude` | drempelwaarde, bijv. "> +25bp" |
  | `horizon_days` | 5 / 21 / 63 |
  | `probability` | expliciete kans 0–1, **verplicht** |
  | `causal_chain` | welke pijlen uit de graaf dit onderbouwen |
  | `evidence_claim_ids` | de claims waarop dit rust |
  | `trigger_version` | welke regelversie actief was (1.5) |
  | `regime_at_creation` | later invulbaar (3.3) |
  | `resolves_at`, `resolution_rule` | **de machine-uitvoerbare regel** |
  | `resolved_value`, `outcome`, `brier_score` | ingevuld door 4.5 |

- [ ] `resolution_rule` verplicht en machine-uitvoerbaar. Zonder dit veld
      volgt over zes maanden een discussie over wat de agent "eigenlijk
      bedoelde" en is het track record waardeloos
- [ ] Predictions als first-class data naast claims, onveranderlijk
- [ ] Mechanische QC weigert een prediction zonder kans/regel/horizon
      (zie 1.6)

### 4.2 Trigger-kalibratie — loopt mee vanaf T₀
- [ ] Held-vs-breached-tracking per trigger-regel, per `trigger_version`
- [ ] Beta-Binomiaal-model (posterior-onzekerheid bij weinig data) i.p.v.
      alleen een held/breached-telling — precies wat nodig is in maand 2,
      wanneer n klein is
- [ ] Adaptieve thresholds op basis van kalibratie-resultaten — **pas na
      het T₀+6-maanden-herzieningsmoment**, niet tussendoor (zie de
      bevriezingsafspraak)

### 4.3 Agent Track Records — loopt mee vanaf T₀
- [ ] Precision/recall/hallucination-rate per agent (QC-kant)
- [ ] Agent-reliability-scores als input voor de aggregatie (3.4)

### 4.4 Historical Replay Engine — post-T₀
Blijft nuttig voor de **deterministische** lagen (triggers, berekende
modellen), waar geen LLM in de lus zit. Voor LLM-agents lost het de
look-ahead bias niet op — dat is precies de reden dat forward testing het
kritieke pad is.
- [ ] Point-in-time-correcte snapshots per databron
- [ ] Systeem laten draaien alsof het een historische datum is
- [ ] Look-ahead/hindsight bias structureel voorkomen (voor de
      deterministische lagen)

### 4.5 Scoring Engine — **[nieuw]**, T₀-BLOKKADE, fase 3

- [ ] **Resolver**: draait dagelijks, pakt elke prediction waarvan
      `resolves_at` verstreken is, past `resolution_rule` toe, schrijft
      een `evaluation`-rij weg
- [ ] **Brier score + log loss** per voorspelling. Proper scoring rules:
      belonen eerlijkheid, straffen zowel overmoed als lafheid
- [ ] **Kalibratiecurve per agent** — zegt een agent tien keer "70%",
      gebeurt het dan zeven keer?
- [ ] **Discrimination (AUC) per agent.** Stond niet in de oude 4.3 en is
      onmisbaar: kalibratie zonder discriminatie is nutteloos. Een agent
      die altijd het basispercentage roept is perfect gekalibreerd en
      volstrekt waardeloos
- [ ] Uitsplitsing per domein, per horizon en (later) per regime

### 4.6 Baselines — **[nieuw]**, T₀-BLOKKADE, fase 3

Zonder baseline is niet vast te stellen of we iets gebouwd hebben of
alleen kosten gemaakt. Beide draaien vanaf T₀ mee als volwaardige
"agents" in de scoring.

- [ ] **Random walk / persistence** — "het blijft zoals het is".
      Verrassend moeilijk te verslaan
- [ ] **Climatology** — de onvoorwaardelijke historische basisrate
- [ ] Afspraak: een agent die na zes maanden geen van beide verslaat,
      gaat eruit

---

## 5. Output & Interfaces — de database is de waarheid, dit is de weergave

Nog niets van gebouwd. Alles post-T₀, met één uitzondering: het
kalibratie-deel van 5.2.

### 5.1 API-laag — post-T₀
- [ ] Eén centrale API op de database
- [ ] Dashboard, alerts, CLI en chat lezen allemaal uit dezelfde bron

### 5.2 Dashboard — kalibratiedeel vroeg, rest post-T₀
- [ ] **Kalibratiecurves en Brier per agent** — hoog in fase 4. Als we
      het eigen track record niet dagelijks zien, stuurt niemand bij
- [ ] Dagelijkse stand van zaken per domein
- [ ] Nasdaq-regime/bias prominent zichtbaar

### 5.3 Alert-mechanisme — deels naar voren
- [ ] De fail-loud-notificatie uit 1.11 is de eerste, minimale versie
      hiervan (T₀-blokkade)
- [ ] Notificatie bij trigger/escalatie — post-T₀

### 5.4 On-demand Query-interface — post-T₀
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

### 5.5 Analyst Agent-koppeling — post-T₀
- [ ] `analyst_agent.py` als subagent binnen Company Intelligence
- [ ] Company Intelligence naast Market Intelligence in één platform

---

## Open beslissingen (bewust nog niet dichtgetimmerd)

- [ ] **Waar draait de fetch-runner?** VPS, Raspberry Pi, of een van onze
      eigen machines. Blokkeert 1.11, dus dit is de eerstvolgende
      beslissing die genomen moet worden
- [ ] Statische vs. adaptieve trigger-thresholds per domein (hangt samen
      met 4.2). **Deels beslist:** statisch tot T₀+6 maanden, daarna pas
      adaptief — anders is er geen cohort om tegen te meten
- [ ] Hoeveel domain agents draaien continu vs. alleen op aanvraag —
      komt terug bij 1.11, nu er een scheduler is
- [ ] Hoeveel predictions per agent per week precies, en op welke knopen.
      De richtlijn van ~5 is een startpunt, geen uitkomst van een
      berekening
- [ ] Library + bronnen-hiërarchie per agent, uitgroeiend tot een eigen
      database-hiërarchie: boeken > academische papers > investor letters
      > artikelen > YouTube-video's > nieuwsberichten > X-posts. Analoog
      aan `analyst_agent.ai/src/knowledge/` — dat project heeft dit zelf
      ook als open vraagstuk (`docs/rejected-alternatives.md`,
      evidence-tiering). Raakt waarschijnlijk `Claim`'s `confidence`-veld
      (1.1) zodra dit gebouwd wordt

## Beslist op 26-09-2026 (was open)

- **Prioritering ICT-trading (kort) vs. macro/mid-term (lang).** Beslist:
  dit systeem is de macro/mid-term-kant. Het verbetert de intraday-
  handel niet en dat is geen doel. Zie "Scope-afbakening" in deel A
- **Volgorde van de pijlers.** Beslist: niet meer 1→2→3→4→5, maar het
  kritieke pad naar T₀. Pijler 4 is grotendeels naar voren gehaald
