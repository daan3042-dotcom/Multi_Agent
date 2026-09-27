# Roadmap — Market Intelligence Platform

**Bron van waarheid: dit document.** De artifact ["Market Intelligence
Platform — Systeemoverzicht"](https://claude.ai/artifact/PpSZ4yrbWyHRVifuAjoffn)
(DD, 23-09-2026) blijft de **catalogus** van wat er uiteindelijk moet
staan; de pijlernummering in deel B komt daaruit en verandert niet.

Deel A bepaalt **wat er wanneer gebeurt**. Deel B is de catalogus met de
vaste nummers (1.x t/m 5.x) waar code-comments naar verwijzen. Een
stap-voor-stap-handleiding met afvinkbare taken staat in
`docs/roadmap.html` — die volgt deel A en is er de weergave van, niet de
bron.

Vink items af zodra ze klaar zijn én groen zijn in de testsuite.

## Herzieningen

| Datum | Wat | Waarom |
|---|---|---|
| 24-09-2026 | Vijf pijlers ingevoerd, oude secties A–I vervangen | Preciezere doelarchitectuur (Systeemoverzicht-artifact) |
| 26-09-2026 | Uitvoeringsvolgorde losgekoppeld van pijlernummering; pijler 4 naar voren | LLM-agents zijn niet eerlijk te backtesten → forward testing is het kritieke pad → kalendertijd is de schaarse resource |
| 27-09-2026 | Zie hieronder | Externe review van de roadmap (Claude Fable 5.1) |
| 28-09-2026 | Synthesizer-doelen op verhandelbare instrumenten, instrument-mapping, referentieprijs in de `resolution_rule`, en extra niet-reconstrueerbare data (consensus, expected moves, ruwe headlines). Gemarkeerd met **[28-09]** | Voorbereiding op een mogelijke swing-trading-laag (1–3 dagen) over 1–1,5 jaar, zonder die nu te bouwen. Zie "Beslist op 28-09-2026" |

**Mapping oude lettering → nieuwe nummering** (voor code-comments als
"stap B.1" of "sectie C.1"): A→1, B+C→2, D→2.8, E→2.9, F→3.1, G→5,
H→Open beslissingen, I→Finetune-lijsten en 4.1.

## Wat er op 27-09-2026 veranderd is, en waarom

De volgorde van 26-09 (deblokkeren → graaf → contract → scoring → T₀ →
verdiepen → Bayesiaans) blijft. Zeven correcties erop, elk met de
mechaniek erachter:

1. **Wie berekent de kans vóór 3.4?** Fase 2 zei "het LLM is evidence
   extractor, geen forecaster; kansen in Python", maar de Python-laag die
   kansen produceert is 3.4 (mei 2027). Daartussen berekende niemand de
   verplichte `probability`. **Besluit:** in cohort 0 spreekt het LLM per
   agent zelf een kans/kwantiel uit op een gestructureerde evidence-sheet;
   Python weigert, resolvet en scoort, en **aggregeert nooit over agents
   heen** — dat is 3.4. Wat we forward-testen is dus expliciet: "is
   LLM-oordeel op Python-berekende cijfers gekalibreerd". Zie 1.8 en 4.1.
2. **De power-berekening telde voorspellingen, geen onafhankelijke
   episodes.** Vijf voorspellingen per week op één knoop over 63 dagen
   overlappen negen weken lang — dezelfde weddenschap twaalf keer. Effectieve
   n per agent op 63 dagen is ~3–4 episodes in zes maanden, niet ~130.
   **Besluiten:** (a) kwantielen (q10/q50/q90) i.p.v. binaire richting+
   drempel voor numerieke doelen — meer informatie per resolutie; (b) veel
   *onafhankelijke doelen* per agent i.p.v. herhaling op één knoop (de
   sector agent met 11 ETF's is daarom de rijkste testbron); (c) de
   herzieningsmomenten spreken over richting en mechaniek, niet over
   significantie; (d) een agent wordt na zes maanden alleen verwijderd bij
   *bewijs van geen skill* (posterior P(skill>0) < 0,2 onder een expliciete
   prior, block-bootstrap over overlappende horizonnen), niet bij
   *ontbreken van bewijs*. Zie 4.5.
3. **Agents zonder informatievoordeel testen niets.** Een deep-dive ziet
   alleen cijfers die Python al berekend heeft; een logistische regressie
   op dezelfde z-scores ziet hetzelfde. **Besluit:** derde baseline — een
   deterministisch model op de agent's eigen inputs (4.6). Verslaat het
   LLM dát niet, dan zit de winst in de inputs (tekst), niet in het
   redeneren, en is 2.8 de eerstvolgende bouwstap. Optioneel pre-T₀: het
   FOMC-statement als tekstinput voor de monetary agent (geen nieuwe
   agent, wel de enige input die Python niet kan lezen).
4. **Forward testing is niet de énige geldige weg.** Een model weet niets
   van de periode ná zijn knowledge cutoff. Met point-in-time-data en
   web search uit is juli–september 2026 (cutoff Fable 5.1: juni 2026) nu
   al een echte out-of-sample-periode; met een ouder model (cutoff begin
   2025) is dat ~18 maanden. **Besluit:** pseudo-out-of-sample-run vóór T₀
   (4.4), gelabeld als indicatief. Daarnaast is de causale graaf zelf
   deterministisch en over 50 jaar FRED-data te toetsen — dat is het enige
   deel van jullie model dat vóór mei 2027 iets kan bewijzen (1.10).
5. **Operationele gaten op de checklist.** Back-up van SQLite (het track
   record zelf), externe heartbeat, API-quota versus dagelijks callvolume,
   `model_id`/`prompt_version` per prediction (Anthropic deprecateert
   modellen binnen een cohortduur), dry-run-week. Alle vijf op de
   T₀-checklist, niet als losse open punten.
6. **`graph_node` optioneel in cohort 0.** Resolutie gebeurt op metrics,
   niet op knopen. De graaf is een label voor attributie en contradictie,
   geen voorwaarde om te scoren. Zo hangt T₀ niet af van wanneer DD en
   zijn partner het eens zijn over de pijlen. Verplicht vanaf cohort v1.
   Nieuw: `node_state` als entiteit (1.2), want een label op een claim
   maakt tegenstrijdigheid nog niet meetbaar.
7. **Twee klokken.** T₀ᵃ (ingestieklok: dagelijkse pull, triggers
   opgeslagen, back-fill) start zodra de VPS draait — streefdatum 3
   oktober. T₀ᵇ (predictieklok) op 10 november. Elke dag zonder VPS is een
   verloren dag point-in-time-data voor de Alpha Vantage-reeksen.

Verder: een expliciete **forecast-ronde** naast de trigger-keten (2.0),
de synthesizer wordt als achtste "agent" gescoord (4.5), DD en partner
loggen wekelijks eigen kansen in dezelfde tabel (4.8), 3.4 is
teruggebracht tot een gewogen pool met shrinkage — het Bayesiaanse
netwerk over de graaf en Black-Litterman/Kelly staan apart en later.

**De volgorde:**

> deblokkeren + ingestieklok → contract → scoring + baselines → pseudo-OOS
> → dry-run → **T₀ᵇ** → verdiepen terwijl het draait → Bayesiaanse laag

---

# DEEL A — Uitvoeringsvolgorde

## Huidige focus

**Fase 0 — sectie 1.11.** Code voor runner, notificaties en entrypoint
staat (280 tests groen). Open is niet-code: VPS bestellen, keys, cron,
back-up, heartbeat, quota-check. Tot de ingestieklok loopt is elke
andere taak voorbarig.

## De agents van cohort 0

Niet "hoeveel agents" is de vraag, maar "hoeveel onafhankelijke,
dagelijks resolvbare doelen". Cohort 0 draait **alle zes bestaande agents
in monitoring** (goedkoop, deterministisch) en laat **vijf** ervan
voorspellen; de economic agent komt er lean bij omdat de graaf anders
geen groei-knopen heeft.

| Agent | Rol in cohort 0 | Doelen (voorbeeld, definitief in 2.0) |
|---|---|---|
| monetary_policy | voorspelt | DGS10 (5/21/63 hd, kwantielen); FEDFUNDS richting volgende 1/2 FOMC |
| financial | voorspelt | HY OAS, VIX, T10Y2Y (5/21/63 hd); NFCI volgende 1/4/12 weekprints |
| sector | voorspelt — rijkste testbron | relatieve sterkte vs SPY per ETF, 11 doelen, 5/21 hd |
| economic (nieuw, lean) | voorspelt | ICSA volgende 1/4 weekprints; UNRATE, PAYEMS volgende 1/3 maandprints |
| currency | voorspelt — controlegroep | EUR/USD, USD/JPY, GBP/USD 5/21/63 hd; verwachting ≈ random walk |
| commodity | alleen monitoring | AV-commodity-endpoint is maandelijks (40 dagen vers) — niet resolvbaar op korte horizon; predictions vanaf cohort v1 met dagelijkse bron |
| equity (adapter) | buiten cohort 0 | Company Intelligence, eigen spoor via `analyst_agent.ai`; kwartaalfundamentals passen niet op 5/21/63 |
| synthesizer | wordt gescoord | zelfde doelen als de domain agents, cross-domein; **[28-09]** plus log-rendement NQ, ZN, CL, 6E over 5 hd (kwantielen) |
| DD, partner | worden gescoord | wekelijks, vrije keuze uit dezelfde doelen (4.8) |

Wat er bewust NIET bij komt vóór T₀, en waar het wél thuishoort: news
(2.8, eerste post-T₀), NQ daily bias (2.9, conditionele verdeling),
bonds (2.1 uitsplitsen zodra de rentes eigen doelen krijgen),
geopolitics (specialisatie van 2.8, geen eigen agent), seasonals
(deterministische baseline in 4.6, geen agent), financial philosophy
(kennislaag/RAG die prompts voedt — Open beslissingen, "Library"),
intraday (buiten scope, zie Scope-afbakening).

## De blokkades

| # | Blokkade | Waarom | Sectie |
|---|---|---|---|
| 1 | Geen live data (403 in de sandbox) | Zonder live data geen forward test | 1.11 |
| 2 | Geen scheduler op eigen infra | Gaten in de reeks maken kalibratie ongeldig — de moeilijke weken ontbreken systematisch | 1.11 |
| 3 | `predictions` bestaat niet | Er is niets te scoren | 1.2 / 4.1 |
| 4 | Geen resolver, geen baselines | Een ongescoorde voorspelling is een mening | 4.5 / 4.6 |

## Fase 0 — Deblokkeren + ingestieklok (29 sep – 12 okt)

**Doel:** het systeem haalt elke dag zonder tussenkomst echte data op en
legt triggers vast. **T₀ᵃ streefdatum 3 oktober.**

| Taak | Sectie | Definition of done | Wie |
|---|---|---|---|
| ~~`run_daily.py` + cron, idempotent~~ | 1.11 | ✅ `tests/test_runtime_daily.py` | — |
| ~~Fail-loud-notificatie~~ | 1.7/1.11 | ✅ | — |
| VPS bestellen en inrichten: keys, `MI_DB_PATH`, `MI_WEBHOOK_URL`, cron met `flock` | 1.11 | eerste geslaagde `run_daily` op de VPS, melding ontvangen op je telefoon | DD |
| API-quota meten | 1.11 | dagelijks callvolume (monitoring + deep-dives) < limiet van de gebruikte tier, gedocumenteerd in `docs/data-sources.md`; anders bron wisselen vóór T₀ᵃ | Claude Code |
| Geautomatiseerde offsite back-up | 1.11 | dagelijkse kopie buiten de VPS (Litestream of `.backup` + rclone) én één keer daadwerkelijk hersteld op een andere machine | DD |
| Externe heartbeat / dead man's switch | 1.11 | alarm bij UITBLIJVEN van een run, getest door de machine bewust een dag uit te zetten | DD |
| **T₀ᵃ: ingestieklok loopt** | 1.11 | 7 dagen op rij data zonder handmatige actie | — |
| Back-fill: volledige historie waar de bron dat toelaat (FRED: alles; AV: wat er is) | 1.11 | elke gemonitorde metric heeft historie; macro ≥ 20 jaar | Claude Code |
| Economic agent, lean | 2.7 | monitoring + Sahm Rule + ICSA/UNRATE/PAYEMS, sectie in `docs/agents.md`, checkpoint 1 uit `CLAUDE.md` | Claude Code |
| Atomiciteit claims/dedup | 1.11 | crash tussen `save_domain_output` en `record_agent_run` laat geen wezen achter | Claude Code |
| Ouderdomsgrens in `system_health()` | 1.11 | één mislukte deep-dive geeft niet elke dag een kritieke melding | Claude Code |

## Fase 1 — De causale graaf (parallel, 6 – 26 okt, niet blokkerend)

Handwerk voor DD en partner. Sjabloon: `docs/causal-graph.md`.
Deliverables: 15–25 knopen, pijlen met vertraging, dekking per agent,
`src/contract/graph.py` (enum). Sectie 1.10.

**Nieuw:** elke pijl wordt deterministisch getoetst op de back-fill
(lead-lag-correlatie op de gekozen vertraging, volledige historie).
Een pijl die niet standhoudt gaat naar "Open punten", niet naar de
enum. Dit is de enige plek waar vóór mei 2027 iets over jullie eigen
model te leren valt.

**Niet blokkerend:** `graph_node` is optioneel in cohort 0. Is de graaf
op 10 november klaar, dan gaat hij mee als v0; zo niet, dan wordt hij
vanaf cohort v1 verplicht.

## Fase 2 — Het voorspellingscontract (6 – 19 okt)

**Doel:** agents produceren falsifieerbare uitspraken. Secties 1.2, 2.0,
4.1.

- `predictions`-tabel, onveranderlijk; velden in 4.1, inclusief
  `model_id`, `prompt_version`, `contract_version`, `cohort`.
- **Twee vormen:** kwantielen (q10/q50/q90) voor numerieke doelen,
  kans op een binaire gebeurtenis (bijv. "FOMC verhoogt") waar geen
  continue waarde bestaat. Richtings- en drempelkansen worden uit
  kwantielen afgeleid, niet apart gevraagd.
- **Horizonnen cadans-bewust:** handelsdagen (5/21/63) voor
  dagreeksen, *releases* (volgende 1/2/3 prints) voor maand- en
  weekreeksen. Een 5-daagse voorspelling op CPI bestaat niet.
- **`resolution_rule` verplicht, inclusief vintage:** resolutie tegen
  de *eerste print* zoals opgeslagen in de eigen claims-historie op
  `resolves_at + 3 dagen`; revisies wijzigen een uitkomst nooit.
- **Forecast-ronde** (2.0): wekelijks, vaste dag, één LLM-call per agent
  die alle doelen van die agent in één JSON zet; los van de trigger-
  keten. Triggers mogen extra predictions opleveren, gevlagd
  `trigger_conditioned=1`.
- **Mechanische QC weigert** een prediction zonder kans/kwantielen,
  regel, horizon of `model_id` (1.6).
- **Menselijke invoer** (4.8): CLI/formulier waarmee DD en partner
  wekelijks eigen kwantielen/kansen op dezelfde doelen vastleggen.
- Marktimpliciete referenties opslaan waar gratis beschikbaar (fed
  funds futures, forwards) — niet om nu tegen te scoren, wel omdat ze
  niet retroactief te reconstrueren zijn (1.2 `expectations`).
- **[28-09]** Synthesizer krijgt vier extra doelen op verhandelbare
  instrumenten (NQ, ZN, CL, 6E; log-rendement over 5 hd, kwantielen),
  met referentieprijs, contractmaand en roll-regel in de
  `resolution_rule` (4.1). Instrument-mapping in de ontologie (1.1).
  Moet vóór de freeze in fase 3b staan; daarna is het een nieuw cohort.

## Fase 3 — Scoring engine en baselines (13 okt – 2 nov)

Secties 4.5, 4.6.

- Resolver dagelijks in `run_daily`; `evaluations`-tabel.
- Scores: pinball loss + CRPS (kwantielen), Brier + log loss (binair),
  kalibratiecurve, discriminatie (AUC), en **effectieve n** via
  block-bootstrap over overlappende horizonnen — naast de nominale n.
- **Drie baselines**, alle als agent gescoord: persistence,
  climatology (onvoorwaardelijke basisrate uit de volledige historie;
  seizoenscomponent hoort hier), en een deterministisch model op de
  agent's eigen inputs (ridge/logistisch op dezelfde z-scores).
- Synthesizer als gescoorde agent.
- Trigger-versioning (1.5) en drempelkalibratie tegen de back-fill.

## Fase 3b — Pseudo-out-of-sample en dry-run (27 okt – 9 nov)

- **Pseudo-OOS** (4.4): agents draaien over juli–sept 2026 op
  point-in-time-data met web search uit; daarna over 2025 met een
  model waarvan de cutoff vóór 2025 ligt. Output gelabeld
  `cohort=pseudo_oos`, nooit gemengd met het echte cohort. Doel:
  contractfouten en resolver-bugs vinden vóór de klok loopt, en een
  eerste indicatie van kalibratie. Geen bewijs — residuele lekkage via
  latere fine-tuning is niet uit te sluiten.
- **Dry-run-week** (checkpoint 3 in `CLAUDE.md`): volledige cyclus incl.
  forecast-ronde en resolver, alleen loggen, DD controleert dagelijks de
  logs tegen een vaste lijst.
- **Freeze:** contract v0, resolution rules, drempels, prompts, model_id.

## T₀ᵇ — de predictieklok loopt

**Streefdatum: 10 november 2026.**

**Checklist (alle verplicht):**

- [ ] Dagelijkse automatische run met live data, 14 dagen op rij zonder handmatige actie (1.11)
- [ ] Offsite back-up loopt dagelijks én is één keer hersteld (1.11)
- [ ] Externe heartbeat actief en getest door de machine uit te zetten (1.11)
- [ ] API-quota gemeten tegen het dagelijkse callvolume incl. deep-dives (1.11)
- [ ] Back-fill klaar; triggerdrempels gekalibreerd tegen de volledige historie, per regel bekend hoe vaak hij gevuurd zou hebben (1.5/4.2)
- [ ] Economic agent lean gebouwd en gekoppeld (2.7)
- [ ] `predictions`-tabel met verplichte kwantielen/kans, `resolution_rule` incl. vintage, `model_id`, `prompt_version` (1.2/4.1)
- [ ] Forecast-ronde draait wekelijks voor vijf agents + synthesizer; menselijke invoer werkt (2.0/4.8)
- [ ] Resolver heeft minstens één cohort correct afgewikkeld, inclusief een release-gebaseerde horizon (4.5)
- [ ] Drie baselines draaien mee (4.6)
- [ ] Pseudo-OOS-run uitgevoerd en bevindingen verwerkt (4.4)
- [ ] Dry-run-week doorlopen, freeze vastgelegd met versienummers (CLAUDE.md checkpoint 3)
- [ ] Causale graaf: v0 vastgelegd óf expliciet uitgesteld naar cohort v1 (1.10)

**Cohort-semantiek na T₀ᵇ:** een wijziging aan contract, graaf of
resolution rules start een nieuw cohort. Een prompt-woordwijziging,
bugfix of modelwissel is een covariaat (`prompt_version`/`model_id`) in
hetzelfde cohort — anders zijn er in mei acht cohorten van drie weken.
Drempels verschuiven omdat de resultaten tegenvallen: nooit (zie
`CLAUDE.md`).

## Fase 4 — Verdiepen terwijl het draait (nov 2026 – apr 2027)

Parallel aan de klok, niet blokkerend. Volgorde op waarde:

**Hoog**
1. **News Monitor Agent** (2.8), smal: 3–5 feeds, handmatige entiteiten,
   event extraction naar knopen. Dit is de enige agent waar het LLM
   iets ziet dat Python niet ziet; als de derde baseline (4.6) de LLM's
   evenaart, is dit de reden.
2. **Minimaal dashboard** (5.2): kalibratie, CRPS/Brier, effectieve n,
   per agent incl. mensen en baselines.
3. **Contradictie-detectie** (3.1) op `node_state`.
4. **Causale graaf v1** verplicht op elke prediction; economic agent
   uitbreiden (output gap, ISM).

**Midden**
5. **Regime als latente variabele** (3.3) — HMM op *dagelijkse
   marktdata* (vol-regimes), niet op macroreeksen (zelfde overfit-profiel
   als PCA).
6. **NQ als conditionele verdeling** (2.9), pas als 3.3 en de kalibratie
   van de domain agents er zijn.
7. Kalman filter (3.2); commodity naar dagelijkse bron en in het cohort.

**Laag — bewust uitgesteld:** alle Finetune-items in sectie 2 (pas als
de kalibratie laat zien welk domein zwak is), PCA (3.2), overige
1.2-entiteiten, API-laag (5.1), query-interface (5.4), analyst-koppeling
(5.5).

## Fase 5 — De Bayesiaanse laag (vanaf mei 2027)

Sectie 3.4, **alleen** de gewogen pool: gewichten uit 4.5 met partial
pooling, correlatiecorrectie met shrinkage (Ledoit-Wolf) omdat een 7×7
correlatiematrix uit ~25 effectieve episodes ruis is, extremizing van
de gepoolde kans. Het Bayesiaanse netwerk over de graaf blijft
prior-gedomineerd zolang er ~10–15 macrocycli in de data zitten — dat
is een apart, later project, geen onderdeel van 3.4. Black-Litterman en
Kelly zijn een beslissingslaag en horen niet in dit systeem.

## Tijdlijn

| Periode | Fase | Uitkomst |
|---|---|---|
| 29 sep – 5 okt | 0a. VPS, back-up, heartbeat, quota | **T₀ᵃ 3 okt: ingestieklok loopt** |
| 6 – 12 okt | 0b. Back-fill, economic agent lean, runtime-fixes | historie in de DB, groei-knopen bediend |
| 6 – 19 okt | 2. Contract + forecast-ronde + mensinvoer | agents en mensen produceren kwantielen/kansen |
| 6 – 26 okt | 1. Causale graaf (parallel, partner) | knopen, pijlen, deterministische toets |
| 13 okt – 2 nov | 3. Resolver, scores, drie baselines, trigger-kalibratie | alles wordt gescoord |
| 27 okt – 9 nov | 3b. Pseudo-OOS + dry-run + freeze | bugs eruit vóór de klok loopt |
| **10 nov 2026** | **T₀ᵇ** | **de predictieklok loopt** |
| nov – apr | 4. Verdiepen | news, dashboard, contradictie, graaf v1, regime |
| **mei 2027** | 5. Gewogen pool | gewichten uit echt track record |

Rolverdeling: DD fase 0a en de mensinvoer, partner fase 1, Claude Code
fase 0b/2/3/3b onder de checkpoints uit `CLAUDE.md`.

## Herzieningsmomenten

| Moment | Datum | Vraag |
|---|---|---|
| T₀ᵇ + 6 weken | ~22 dec 2026 | **Alleen mechanica**: draait het elke dag, resolven predictions correct incl. release-horizonnen, zitten er gaten in? Niet naar scores kijken |
| T₀ᵇ + 3 maanden | ~10 feb 2027 | Mechanica + **richting**: is het teken van (agent − baseline) consistent over horizonnen en doelen? Geen significantie — effectieve n is dan nog enkelcijferig op 63 dagen. Wél: pseudo-OOS en echt cohort naast elkaar leggen |
| T₀ᵇ + 6 maanden | ~10 mei 2027 | Volledige evaluatie met effectieve n en posterior P(skill>0) per agent. Verwijderen alleen bij posterior < 0,2 onder de vooraf vastgelegde prior. Dán 3.4 |

## Scope-afbakening

Dit systeem verbetert DD's kortetermijn-ICT-daytrading op MNQ vrijwel
niet: horizonnen zitten op dagen tot maanden, het daghandelen op minuten
tot uren. Het kan hooguit de directionele bias en het risicobudget per
dag kleuren, en zelfs dat moet met de scoring engine bewezen worden.
Dit is de CTA-/macro-kant van TCE die naast de daghandel wordt
opgebouwd. Bevestigd door DD op 26-09-2026.

---

# DEEL B — De pijlers (catalogus)

Nummering ongewijzigd t.o.v. 24-09-2026, zodat code-comments blijven
kloppen. Secties sinds 26-09-2026 zijn gemarkeerd met **[nieuw]**,
wijzigingen van 27-09-2026 met **[27-09]**. De volgorde waarin dit
gebouwd wordt staat in deel A, niet hier.

## 1. Infrastructuur & Data — fundament, geen agents

### 1.1 Output Contract & Domain Ontologie
- [x] Claim-contract: waarde, bron, confidence (`src/contract/output_contract.py`)
- [x] Vier tijdstempels: event_time / source_time / ingestion_time /
      analysis_time (`src/contract/output_contract.py`)
- [x] Domain ontologie vastleggen (Equities, Rates, FX, Commodities,
      Credit, Macro, Sectors, Companies) (`src/contract/domain_ontology.py`)
- [ ] **[nieuw]** `graph_node` als veld op `Claim` en `Prediction` —
      welke knoop uit de causale graaf (1.10) dit raakt. **[27-09]**
      Optioneel in cohort 0, verplicht vanaf cohort v1: resolutie
      gebeurt op metrics, dus de graaf is geen voorwaarde om te scoren.
- [ ] **[28-09]** Instrument-mapping in `src/contract/domain_ontology.py`:
      per `metric_key` het bijbehorende verhandelbare contract (bijv.
      NQ, ZN, CL, 6E; DXY als index-referentie) en de eenheid waarin
      een doel daarop wordt uitgedrukt (log-rendement, bp). Een paar
      regels nu; voorkomt dat een latere trading-laag moet raden welk
      instrument bij welke voorspelling hoort. Metrics zonder
      verhandelbaar equivalent krijgen expliciet `None`. Vóór de freeze
      (fase 3b).

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
      prediction (resolved_value, outcome, pinball/CRPS, Brier, log
      loss). Apart van `predictions` omdat een prediction
      onveranderlijk is en een evaluation later ontstaat. Zie 4.5.
- [ ] **[27-09]** Entiteit: node_state — (knoop, agent, datum, richting,
      sterkte/kans, horizon). Een `graph_node`-label op een claim maakt
      tegenstrijdigheid nog niet meetbaar; twee agents met een
      tegengestelde richting op dezelfde knoop en horizon wél. Dit is
      waar 3.1's contradictie-detectie op draait. Post-T₀, samen met
      graaf v1.
- [ ] **[27-09]** Entiteit: human_forecasters — DD en partner als
      voorspellers in dezelfde `predictions`-tabel (`agent='human:dd'`),
      zie 4.8. Geen aparte tabel; alleen een agent-naamruimte plus een
      invoerpad.
- [ ] Entiteit: observations — bewust NIET gebouwd als aparte tabel:
      revisie-detectie (1.3) is de enige huidige reden om ze los van
      claims te zien, en dat werkt al tegen de bestaande claims-historie
      (elke poll blijft bewaard). Pas een eigen tabel zodra er een
      andere reden is om ze te scheiden (bijv. claims gaan prunen).
- [ ] Entiteit: entities (het "wat wordt hier gemeten"-register)
- [ ] Entiteit: measurements (afgeleide/berekende waarden, nu impliciet
      onderdeel van claims met source="Berekend (...)")
- [ ] Entiteit: events (nieuws/agenda-gebeurtenissen, hoort bij 2.8 News
      Monitor Agent). **[28-09]** Ruwe headlines met eigen tijdstempel
      (bron, `source_time`, `ingestion_time`, titel, eventueel
      ticker/topic-tags) bewaren, niet alleen de samenvatting van de
      agent. Het nieuws zoals het toen bekend was is achteraf niet
      betrouwbaar te reconstrueren. Begint zodra er een feed draait —
      bij voorkeur al mee in de ingestieklok (T₀ᵃ) als een gratis bron
      past (1.4), anders uiterlijk met 2.8. Niet T₀-blokkerend.
- [ ] Entiteit: expectations (echte marktverwachting i.p.v. "vorige
      observatie" als trigger-referentie). **[27-09]** Deels naar voren:
      vanaf T₀ᵇ worden marktimpliciete referenties (fed funds futures,
      forwards) *opgeslagen* waar gratis beschikbaar — niet om tegen te
      scoren, wel omdat ze niet retroactief te reconstrueren zijn. De
      trigger-referentie zelf blijft post-T₀.
      **[28-09]** Uitgebreid met twee reeksen, zelfde logica
      (niet-reconstrueerbaar, dus nu opslaan, later pas gebruiken):
      - **Consensusverwachting vóór elke release** (CPI, NFP/PAYEMS,
        UNRATE, ICSA, FOMC) — de verrassing t.o.v. consensus is later
        het echte signaal, niet de print zelf.
      - **Opties-geïmpliceerde expected move rond grote events** (FOMC,
        CPI, big-tech earnings voor NQ) — nodig voor stop-afstanden en
        sizing in een eventuele trading-laag.
      Beide alleen waar een gratis/goedkope bron bestaat (1.4); welke
      bron is nog open. Niet T₀-blokkerend.
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
- [ ] **[nieuw]** Plausibiliteitscheck tussen bronnen, los van
      `evaluate_consistency`. Die laatste vergelijkt een gestelde waarde
      tegen een herberekende waarde uit dezelfde bron — vangt geen waarde
      die binnen een geldig bereik valt maar sterk afwijkt van wat
      gerelateerde reeksen elders in de causale graaf (1.10) zouden doen
      verwachten (bijv. een FX-koers die geldig is maar niet past bij de
      bijbehorende rentedifferentie-beweging). Relevant zodra een bron
      gecorrumpeerd of gemanipuleerd raakt zonder buiten zijn eigen
      geldige bereik te vallen — dat scenario wordt nu niet gedekt door
      HEALTHY/DEGRADED/INVALID.

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
- [ ] **Drempels kalibreren tegen de volledige historie (fase 0)** — hoe
      vaak zou elke regel gevuurd hebben? Vervangt de huidige
      illustratieve waarden. **[27-09]** Niet "≥5 jaar" maar alles wat
      de bron geeft: FRED levert 50+ jaar gratis, en vijf jaar (2021–2026)
      is één verkrappings- en één verruimingsbeweging — te dun om een
      drempel op te ijken.
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
      prediction zonder kwantielen/kans, `resolution_rule`, `resolves_at`
      of **[27-09]** `model_id`/`prompt_version` wordt geweigerd, niet
      gevlagd. Ook geweigerd: kwantielen die niet monotoon zijn
      (q10 > q50) en een release-horizon op een dagreeks of andersom.
      Dit is de ene plek waar `NEEDS_REVIEW` niet volstaat — een
      onscoorbare voorspelling vervuilt het track record permanent.

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
- [ ] **[nieuw]** Decision-latency als bewaakte metric per agent-cyclus
      (monitoring én deep-dive), naast het bestaande succes/faal-signaal in
      `agent_runs`. Geen risico bij de huidige dagelijkse cadans, maar wel
      relevant zodra 2.9 (NQ regime/bias) korter-cyclisch wordt — dan is
      vooraf al bekend welke agent de bottleneck zou worden.

### 1.8 Orchestrator / Manager
- [x] Deterministische dispatch-logica (`src/manager/manager.py`)
- [x] Gelijktijdige triggers over meerdere domeinen (bv. een Fed-besluit
      dat monetary policy + currency tegelijk raakt — bewezen in
      `tests/test_integration_section_b.py`)
- [x] LLM-taken-tabel expliciet vastleggen (wat mag wel/niet door een LLM
      gedaan worden, systeembreed) (`docs/architecture.md`, sectie
      "LLM-taken-tabel")
- [ ] **[27-09]** LLM-taken-tabel uitbreiden met de cohort-0-regel: een
      LLM mag per agent kwantielen/een kans uitspreken op een
      gestructureerde evidence-sheet (dat is precies wat er getest wordt),
      en mag waarnemingen extraheren en een causale keten formuleren. Een
      LLM **aggregeert nooit over agents heen** en berekent nooit een
      baseline, score of gewicht — dat is Python (4.5, 4.6, 3.4). De
      oude formulering ("nooit de uiteindelijke kans berekenen") gold voor
      de eindsituatie na 3.4 en liet tussen T₀ en mei 2027 niemand over om
      de verplichte kans te leveren.
- [ ] **[27-09]** Forecast-ronde in de dispatch: wekelijks, vaste dag,
      één call per voorspellende agent, los van de trigger-keten (2.0).

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
- [ ] **[27-09]** Elke pijl deterministisch toetsen op de back-fill:
      lead-lag-correlatie op de opgegeven vertraging over de volledige
      historie, plus een kolom "houdt stand / niet / onbeslist" in
      `docs/causal-graph.md`. Geen LLM in de lus, dus geen hindsight —
      dit is de enige toets van jullie eigen model die vóór mei 2027
      iets kan bewijzen. Een pijl die niet standhoudt gaat naar "Open
      punten", niet naar de enum.
- [ ] **[27-09]** `graph_node` optioneel in cohort 0, verplicht vanaf
      cohort v1 (zie deel A, correctie 6). De graaf is daarmee van het
      kritieke pad naar T₀ᵇ gehaald.

**Bewust NIET nu:** de graaf omzetten in een Bayesiaans netwerk met
kansen. **[27-09]** En ook niet in mei 2027: met ~10–15 macrocycli in
de data blijven de pijlkansen jarenlang prior-gedomineerd. Het
Bayesiaanse netwerk is een apart, later project; 3.4 is alleen de
gewogen pool.

### 1.11 Scheduler & Runtime — **[nieuw]**, fase 0, T₀-BLOKKADE

Blokkades 1 en 2 uit deel A. Dit is de sectie waaraan nu gewerkt wordt;
fase 2 en 3 lopen erachteraan.

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
- [ ] **Back-fill** van elke gemonitorde metric — **[27-09]** volledige
      historie waar de bron dat toelaat (FRED: alles; Alpha Vantage: wat
      het endpoint geeft), niet "≥5 jaar"
- [ ] **[27-09]** **API-quota meten** tegen het dagelijkse callvolume.
      Sector (11 ETF's + SPY) + commodity (10) + FX (3) = 25 calls per
      monitoring-cyclus, vóór deep-dive-verrijking. Verifieer de limiet
      van de gebruikte Alpha Vantage-tier op de eigen key; zit die op
      25/dag, dan breekt de cyclus op dag 1 op de VPS. Uitkomst in
      `docs/data-sources.md`; bron wisselen (bijv. yfinance zoals
      `analyst_agent.ai`) vóór T₀ᵃ als het niet past.
- [ ] **[27-09]** **Geautomatiseerde offsite back-up van de SQLite.** Dat
      bestand *is* het track record; verlies betekent dat de klok
      opnieuw begint. Litestream of dagelijks `sqlite3 .backup` + rclone
      naar object storage; één keer daadwerkelijk hersteld op een andere
      machine vóór T₀ᵇ. Op de T₀-checklist.
- [ ] Per-domein cadans: welke agent draait dagelijks, welke wekelijks.
      **[27-09] Beslist voor cohort 0:** alle zes agents dagelijks in
      monitoring (goedkoop, deterministisch, en de klok mag geen gaten
      hebben); forecast-ronde wekelijks; deep-dives op trigger.
- [ ] **Externe dead man's switch.** `run_daily()` detecteert nu zelf
      gaten in de afgelopen 7 dagen, maar alleen bij de eerstvolgende run
      die wél draait. Staat de machine drie weken uit, dan hoort niemand
      iets — elke melding komt uit een draaiende run. Een externe
      heartbeat-ping die alarmeert bij UITBLIJVEN hoort buiten dit systeem
      te draaien. **[27-09]** Op de T₀-checklist, getest door de machine
      bewust een dag uit te zetten.
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
Finetune-items zijn post-T₀. **[27-09] Eén uitzondering:** de economic
agent komt lean vóór T₀ (2.7), omdat de graaf anders geen groei-knopen
heeft en de forward test dan een half jaar lang niets over groei leert.
De Finetune-lijsten blijven staan als catalogus, maar worden pas
aangeraakt als de kalibratie laat zien welk domein zwak is.

### 2.0 Predictions per agent — **[nieuw]**, fase 2, geldt voor 2.1 t/m 2.9

- [ ] `agents/base.py` uitbreiden met een **forecast-ronde** naast
      monitoring en deep-dive: wekelijks, vaste dag, één LLM-call per
      voorspellende agent die alle doelen van die agent in één JSON zet
      volgens 4.1. **[27-09]** Los van de trigger-keten: predictions die
      alleen bij triggers ontstaan geven selectiebias (alleen voorspellen
      in volatiele weken) en onregelmatige aantallen. Een trigger mag
      wél extra predictions opleveren, gevlagd `trigger_conditioned=1`.
- [ ] Per agent vastleggen welke doelen (metric_keys) hij voorspelt, op
      welke horizonnen, en — vanaf cohort v1 — welke graafknopen (1.10)
- [ ] **[27-09]** Richtlijn vervangen: niet "~5 voorspellingen per week"
      maar **zoveel mogelijk onafhankelijke doelen** per agent, elk op
      cadans-bewuste horizonnen (handelsdagen 5/21/63 voor dagreeksen,
      releases 1/2/3 voor week-/maandreeksen). Herhaling op één doel
      levert geen statistische power op; breedte wel. Startlijst per
      agent staat in deel A ("De agents van cohort 0").
- [ ] **[27-09]** Wat de agent ziet in de forecast-ronde: eigen
      domein-claims + de `src/analysis/`-modellen + (vanaf v1) een
      compacte graafstand. Bewust niet alle domeinen: dat maakt agents
      sterker maar volledig gecorreleerd, en dan meet 4.5 de synthesizer
      zeven keer. Cross-domein is de rol van de synthesizer, die apart
      gescoord wordt.

### 2.1 Monetary Policy Agent
- [x] Monitoring mode + deep-dive mode (`src/agents/monetary_policy_agent.py`)
- [x] Taylor Rule (`src/analysis/taylor_rule.py`)
- [ ] Yield curve spreads (2s10s, 3m10y)
- [ ] Fed funds futures-implied rate & surprise-metric — **[27-09]** het
      *opslaan* van de implied rate schuift naar T₀ᵇ (1.2 expectations);
      de surprise-metric blijft post-T₀
- [ ] **[27-09]** Optioneel pre-T₀, geen nieuwe agent: het FOMC-statement
      (tekst, acht keer per jaar, gratis) als input in de deep-dive en
      forecast-ronde. De enige input in cohort 0 die Python niet kan
      lezen; zonder tekst heeft het LLM geen informatievoordeel op de
      derde baseline (4.6). DD beslist.
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
- [ ] **[27-09]** In cohort 0 alleen monitoring, geen predictions: het
      Alpha Vantage-commodity-endpoint is maandelijks (40 dagen vers),
      dus een 5/21/63-daagse voorspelling is er niet tegen te resolven.
      Predictions vanaf cohort v1, na overstap op een dagelijkse bron.
- [ ] Cost-of-carry-model (contango/backwardation)
- [ ] Stocks-to-use ratio
- [ ] Crack/crush/spark spread
- [ ] WTI-Brent-spread & term-structure-slope
- **Finetune (post-T₀):** CFTC COT-positionering, inventory
  days-of-supply, seizoensindex, copper/gold-ratio

### 2.7 Economic Agent — **[27-09]** lean vóór T₀, uitbreiden in fase 4
De graaf (1.10) krijgt groei-knopen die door geen enkele bestaande agent
bediend worden. Zonder deze agent leert de forward test een half jaar
lang niets over groei en arbeidsmarkt — daarom komt de kern vóór T₀,
als enige uitzondering op "geen nieuwe agents". Lean betekent: één
FRED-bron, drie reeksen, één model, checkpoint 1 uit `CLAUDE.md`.
- [ ] **Pre-T₀ (lean):** monitoring mode + deep-dive mode op ICSA
      (initial claims, wekelijks — de snelst resolvende macroreeks die er
      is), UNRATE en PAYEMS (maandelijks); eigen registry-entry
      `FRED:economic`; sectie in `docs/agents.md`
- [ ] **Pre-T₀:** Sahm Rule (`src/analysis/sahm_rule.py`), gebouwd uit
      UNRATE die al opgehaald wordt
- [ ] **Pre-T₀:** doelen in de forecast-ronde: ICSA volgende 1/4
      weekprints, UNRATE en PAYEMS volgende 1/3 maandprints (kwantielen)
- [ ] Output gap (HP-filter op bbp-reeks) — post-T₀
- [ ] Misery Index — post-T₀
- [ ] ISM-diffusie-interpretatie — post-T₀ (ISM zit niet meer op FRED;
      vraagt een eigen bron)
- [ ] Phillips Curve-residual — post-T₀
- **Finetune (post-T₀):** Leading Economic Index (LEI), Okun's Law,
  Beveridge Curve, soft-vs-hard-data-gap, regionale Fed-surveys (Philly
  Fed, Empire State)

### 2.8 News Monitor Agent — post-T₀, eerste agent van fase 4, bewust smal
Het LLM is hier op zijn sterkst: ongestructureerde tekst omzetten in
gestructureerde waarnemingen op graafknopen. Entity resolution, dedup en
novelty detection zijn elk een eigen project en zijn NIET nodig voor een
eerste bruikbare versie.
- [ ] 3–5 betrouwbare feeds, handmatig gedefinieerde entiteiten
- [ ] Event extraction naar graafknopen (who/did what/when/expected impact)
- [ ] Koppeling aan de trigger-laag (1.5) als aanvullende triggerbron
- [ ] **[nieuw]** Provenance-eis vóór een claim de trigger-laag bereikt:
      bron + publicatietijdstip vastleggen, en waar het feitelijk beweerbaar
      is (een cijfer, een besluit) bevestiging door minstens één tweede,
      onafhankelijke feed. Dit is de enige agent die ongestructureerde
      tekst van externe bronnen omzet in claims — de mechanische QC (1.6)
      checkt interne consistentie, niet of de brontekst zelf betrouwbaar of
      gemanipuleerd is. Zonder dit staat de deur open voor een enkele
      vervuilde of nep-bron die zich voordoet als een geldige triggerbron.
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
      door 1.10**: een conflict op een graafknoop, geen tekstvergelijking.
      **[27-09]** Vereist de `node_state`-entiteit (1.2): twee agents met
      tegengestelde richting op dezelfde knoop en horizon. Een
      `graph_node`-label op een claim is daarvoor niet genoeg.
- [ ] Cross-domein implicaties combineren tot één leesbaar geheel
- [ ] Event-chain-reconstructie: nieuws en numerieke data in hetzelfde
      event-model (hangt af van 1.2's event-model)
- [ ] ~~Confidence-weging (Bayesiaans)~~ → **verplaatst naar 3.4**; kan
      niet hier blijven omdat het track record uit 4.5 een harde
      voorwaarde is
- [ ] **[nieuw]** Gedeelde-bron-vlag als tussenstap vóór 3.4 er is: als
      meerdere domain agents in dezelfde dispatch-batch (1.8) in dezelfde
      richting escaleren, expliciet markeren of dat samenvalt met een
      gedeelde onderliggende gebeurtenis (bijv. één Fed-besluit dat
      monetary + currency + equity tegelijk raakt — verwacht en gewenst)
      of dat er geen gedeelde oorzaak zichtbaar is (verdacht: mogelijk
      hetzelfde signaal vijf keer geteld, precies het probleem dat 3.4
      later statistisch oplost). Puur een vlag op de `DispatchPlan`, geen
      correctie — de correctie zelf blijft terecht in 3.4, dit dekt alleen
      het gat tussen nu en mei 2027.

### 3.2 Statistische synthese-laag — post-T₀
- [ ] Z-score-normalisatie over domeinen heen
- [ ] Rolling correlation / correlatiebreuk-detectie
- [ ] Kalman filter voor ruizige reeksen
- [ ] ~~PCA op macro-reeksen~~ — **bewust naar de achtergrond**: met
      ~10–15 echte cycli in bruikbare data is factorreductie op macro een
      overfit-machine. Niet geschrapt, wel expliciet laag geprioriteerd

### 3.3 Market State & Regime Engine — post-T₀
- [ ] Regime als **latente variabele**: Markov-switching / HMM die een
      posterior over regimes geeft, geen label. **[27-09]** Op
      *dagelijkse marktdata* (volatiliteits-/correlatieregimes), niet op
      macroreeksen: met ~10–15 macrocycli heeft een macro-HMM hetzelfde
      overfit-profiel als de PCA die in 3.2 terecht is uitgesteld.
- [ ] Cross-asset regime-aggregatie (breder dan alleen NQ, zie 2.9)
- [ ] Regime/bias/trade-setup strikt gescheiden houden op systeemniveau

### 3.4 Probabilistische aggregatie — **[nieuw]**, fase 5 (mei 2027)

**[27-09] Afgebakend tot één ding:** de gewogen pool over agents. Draait
volledig in Python; **het LLM raakt deze laag nooit aan**. Voorwaarde:
≥6 maanden gescoorde predictions uit 4.5, met effectieve n erbij.

- [ ] **Logarithmic opinion pool / Bayesian model averaging**, met
      gewichten uit 4.5, mensen en baselines als volwaardige leden
- [ ] **Hiërarchisch model met partial pooling.** Met een enkelcijferige
      effectieve n per agent op 63 dagen is een aparte schatting per
      agent per regime hopeloos dun; partial pooling laat elke agent naar
      het groepsgemiddelde krimpen naarmate hij minder data heeft. Dit is
      het verschil tussen bruikbare en onzinnige gewichten in jaar één
- [ ] **Correlatiecorrectie tussen agents.** De agents zijn níet
      onafhankelijk: ze lezen deels dezelfde bronnen en draaien op
      hetzelfde model. Vijf agents die het eens zijn is vaak één
      waarneming vijf keer geteld; een naïeve update produceert dan
      posteriors die structureel te zelfverzekerd zijn — precies op de
      momenten waarop we op het systeem zouden leunen. **[27-09]** Een
      7×7-correlatiematrix uit ~25 effectieve episodes is ruis: shrinkage
      (Ledoit-Wolf) naar een gedeelde correlatie, plus extremizing van
      de gepoolde kans. De gedeelde-bron-vlag uit 3.1 is de covariaat.
- [ ] Gewichten conditioneel op regime (3.3) — pas als de
      onvoorwaardelijke gewichten stabiel zijn, waarschijnlijk jaar twee

**[27-09] Uit 3.4 gehaald en apart gezet:**
- *Bayesiaans netwerk over de causale graaf* (1.10) — blijft
  prior-gedomineerd zolang er ~10–15 macrocycli in de data zitten. Eigen
  project, na 3.4, geen onderdeel ervan.
- *Black-Litterman + fractional Kelly* — een beslissings-/portefeuillelaag,
  geen intelligence. Hoort niet in dit systeem; views en positionering
  apart scoren blijft het principe, maar dan in het portefeuilleproject.

---

## 4. Evaluatie & Learning Loop — het kritieke pad, niet de sluitpost

**Herzien op 26-09-2026.** Dit was pijler 4 in volgorde; het is nu de
pijler die T₀ definieert. 4.1, 4.5 en 4.6 zijn T₀-blokkades; 4.2 en 4.3
lopen mee vanaf T₀; 4.4 is **[27-09]** deels naar voren gehaald
(pseudo-out-of-sample vóór T₀ᵇ); 4.8 (mensen) is nieuw en pre-T₀.

### 4.1 Predictions & Outcome Tracking — T₀-BLOKKADE, fase 2

Elke uitspraak van het systeem wordt een falsifieerbare claim:
onveranderlijk, met tijdstempel, en met de regel waarmee hij later
gescoord wordt er al in.

- [ ] `Prediction`-contract met minimaal deze velden (**[27-09]**
      herzien):

  | Veld | Waarom |
  |---|---|
  | `prediction_id`, `agent`, `created_at` | identiteit en `analysis_time`; `agent` omvat ook `human:dd`, `human:partner`, `baseline:*`, `synthesizer` |
  | `cohort`, `contract_version`, `graph_version` | welke set regels gold; een nieuw cohort bij een contract-/graaf-/resolutiewijziging |
  | `model_id`, `prompt_version` | **[27-09]** covariaten binnen een cohort — een modelwissel halverwege is anders niet te scheiden van een prestatieverandering |
  | `target_metric_key`, `domain` | wat er voorspeld wordt; resolutie gebeurt hierop |
  | `graph_node` | welke knoop uit 1.10 — optioneel in cohort 0, verplicht vanaf v1 |
  | `kind` | `quantile` (numeriek doel) of `binary` (gebeurtenis) |
  | `q10`, `q50`, `q90` | **[27-09]** voor `kind=quantile`; richtings- en drempelkansen worden hieruit afgeleid, niet apart gevraagd |
  | `probability`, `event_rule` | voor `kind=binary`: expliciete kans 0–1 op een machine-uitvoerbare gebeurtenis ("FOMC verhoogt op 2026-12-10") |
  | `horizon_kind`, `horizon_n` | **[27-09]** `trading_days` (5/21/63) voor dagreeksen, `releases` (1/2/3) voor week-/maandreeksen |
  | `causal_chain` | welke pijlen uit de graaf dit onderbouwen (vanaf v1) |
  | `evidence_claim_ids` | de claims waarop dit rust |
  | `trigger_version`, `trigger_conditioned` | welke regelversie actief was (1.5); of dit uit een trigger of uit de forecast-ronde kwam |
  | `regime_at_creation` | later invulbaar (3.3) |
  | `resolves_at`, `resolution_rule` | **de machine-uitvoerbare regel, inclusief vintage** — eerste print zoals opgeslagen in de eigen claims-historie op `resolves_at + 3 dagen`; latere revisies wijzigen een uitkomst nooit |
  | `market_implied_ref` | **[27-09]** waar gratis beschikbaar (futures/forwards) op het moment van voorspellen; niet reconstrueerbaar achteraf |

- [ ] `resolution_rule` verplicht en machine-uitvoerbaar. Zonder dit veld
      volgt over zes maanden een discussie over wat de agent "eigenlijk
      bedoelde" en is het track record waardeloos
- [ ] Predictions als first-class data naast claims, onveranderlijk;
      scores in de aparte `evaluations`-tabel (1.2)
- [ ] Mechanische QC weigert een prediction zonder kwantielen/kans, regel,
      horizon of model_id (zie 1.6)
- [ ] **[28-09]** Prijsdoelen (instrument-doelen van de synthesizer,
      zie 1.1) hebben een `resolution_rule` die expliciet vastlegt:
      welke prijs (settlement van de dag van `created_at`), welke
      contractmaand, en de roll-regel — het contract dat bij
      `created_at` front is wordt tot `resolves_at` aangehouden; valt
      de expiratie binnen de horizon, dan geldt vanaf creatie het
      volgende contract. Geen vintage-probleem (settlements worden niet
      gereviseerd), wel een dubbelzinnigheidsprobleem zonder deze regel.
      Daarmee is een schaduw-P&L van de synthesizer later met
      terugwerkende kracht te berekenen vanaf T₀ᵇ, zonder die nu te
      bouwen.

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
- [ ] **[nieuw]** Root-cause bij een verkeerd gescoorde prediction: niet
      alleen dat hij faalde, maar via `causal_chain`/`evidence_claim_ids`
      (4.1) terugvinden welke schakel brak — een verkeerde claim, een
      goede claim met een verkeerde causale aanname, of een correcte keten
      die alsnog niet uitkwam. Zonder dit blijft 4.3 tellen wát fout ging,
      nooit waarom, en mist het systeem het equivalent van FinCon's
      belief-revisie tussen episodes.

### 4.4 Historical Replay Engine — **[27-09]** deels pre-T₀
Blijft nuttig voor de **deterministische** lagen (triggers, berekende
modellen, de pijlen van de causale graaf), waar geen LLM in de lus zit.
Voor LLM-agents lost het de look-ahead bias niet op voor periodes vóór
de knowledge cutoff — dat is de reden dat forward testing het kritieke
pad is. Maar ná de cutoff van het gebruikte model weet het model niets,
en dat window is nu al beschikbaar.
- [ ] Point-in-time-correcte snapshots per databron (FRED via ALFRED-
      vintages; de eigen claims-historie is al point-in-time)
- [ ] Systeem laten draaien alsof het een historische datum is
- [ ] Look-ahead/hindsight bias structureel voorkomen (voor de
      deterministische lagen)
- [ ] **[27-09] Pseudo-out-of-sample-run vóór T₀ᵇ (fase 3b).** Agents
      draaien de forecast-ronde over juli–september 2026 (cutoff Fable
      5.1: juni 2026) op point-in-time-data, web search uit, geen data
      van na de voorspeldatum in de prompt; daarna over 2025 met een
      model waarvan de cutoff vóór 2025 ligt. Output onder
      `cohort=pseudo_oos`, nooit gemengd met het echte cohort. Doel:
      contract- en resolverfouten vinden vóór de klok loopt en een
      eerste, indicatieve kalibratie. Geen bewijs — residuele lekkage
      via latere fine-tuning is niet uit te sluiten; daarom apart
      gelabeld en bij T₀ᵇ+3 maanden náást het echte cohort gelegd.
- [ ] **[27-09] Deterministische toets van de graaf** (zie 1.10) draait
      op dezelfde replay-machinerie.

### 4.5 Scoring Engine — **[nieuw]**, T₀-BLOKKADE, fase 3

- [ ] **Resolver**: draait dagelijks in `run_daily`, pakt elke prediction
      waarvan `resolves_at` verstreken is, past `resolution_rule` toe
      (incl. vintage-regel), schrijft een `evaluation`-rij weg. Kan een
      release-horizon afwikkelen (wacht op de print, niet op de datum).
- [ ] **[27-09] Pinball loss + CRPS** per kwantielvoorspelling; **Brier +
      log loss** per binaire voorspelling. Proper scoring rules: belonen
      eerlijkheid, straffen zowel overmoed als lafheid. Richtings- en
      drempelscores worden uit de kwantielen afgeleid, zodat ze
      vergelijkbaar blijven met de oude binaire vorm.
- [ ] **Kalibratiecurve per agent** — zegt een agent tien keer "70%",
      gebeurt het dan zeven keer? Voor kwantielen: PIT-histogram.
- [ ] **Discrimination (AUC) per agent.** Onmisbaar: kalibratie zonder
      discriminatie is nutteloos. Een agent die altijd het
      basispercentage roept is perfect gekalibreerd en volstrekt
      waardeloos
- [ ] **[27-09] Effectieve n** naast de nominale n, via block-bootstrap
      over overlappende horizonnen en gecorreleerde doelen. Elke score
      krijgt een onzekerheidsband uit dezelfde bootstrap. Zonder dit
      leest iemand in februari "n=130" en trekt een conclusie uit n≈4.
- [ ] **[27-09] Skill-posterior per agent:** P(skill > 0 t.o.v. de beste
      baseline) onder een vooraf vastgelegde prior. Dit is het getal
      waarop het T₀ᵇ+6-maanden-moment beslist — niet een p-waarde en
      niet een puntschatting.
- [ ] **[27-09] Synthesizer wordt gescoord** als eigen agent — het is
      het enige wat DD en partner uiteindelijk lezen.
- [ ] Uitsplitsing per domein, per horizon, per `model_id` en (later)
      per regime

### 4.6 Baselines — **[nieuw]**, T₀-BLOKKADE, fase 3

Zonder baseline is niet vast te stellen of we iets gebouwd hebben of
alleen kosten gemaakt. **[27-09] Drie** baselines draaien vanaf T₀ mee als
volwaardige "agents" in de scoring, met dezelfde kwantielvorm.

- [ ] **Random walk / persistence** — "het blijft zoals het is";
      kwantielen uit de historische verdeling van veranderingen over de
      horizon. Verrassend moeilijk te verslaan
- [ ] **Climatology** — de onvoorwaardelijke historische verdeling uit de
      volledige back-fill. **[27-09]** Seizoenscomponent hoort hier
      (climatology conditioneel op kalender), niet in een aparte
      "seasonals agent"
- [ ] **[27-09] Deterministisch model op de agent's eigen inputs** —
      ridge/logistische regressie op precies de z-scores en
      `src/analysis/`-uitkomsten die het LLM in de forecast-ronde ziet,
      gefit op de back-fill vóór T₀ᵇ en daarna bevroren. Als het LLM dít
      niet verslaat, voegt het niets toe boven zijn inputs, en zit de
      winst in tekst (2.8) — dat is een uitkomst, geen mislukking.
- [ ] **[27-09] Afspraak herzien:** een agent gaat er na zes maanden
      alleen uit bij *bewijs van geen skill* — skill-posterior (4.5)
      < 0,2 onder de vooraf vastgelegde prior — niet bij *ontbreken van
      bewijs*. Met een enkelcijferige effectieve n op 63 dagen zou de
      oude regel ("verslaat geen van beide") op ruis beslissen.

### 4.7 Systeembrede noodstop — **[nieuw]**, loopt mee vanaf T₀

`NEEDS_REVIEW` (1.6) en de per-item kill-criteria (`analyst_agent.ai`'s
patroon) vangen elk een individueel geval. Geen van beide vangt het
scenario waarin de kalibratie zelf (4.5) structureel verslechtert — dat
zou nu alleen zichtbaar worden als iemand toevallig de kalibratiecurve
bekijkt.

- [ ] Harde, niet-optionele drempel: als de kalibratie (Brier/AUC, 4.5)
      over een gedefinieerde periode significant onder de baselines (4.6)
      zakt, gaat er een melding uit die om review van de **hele
      trigger-configuratie** vraagt — niet van één agent of één
      kill-criterium. Zelfde notificatiepad als 1.7's stille-run-melding,
      andere trigger.
- [ ] Dit is bewust geen automatische ingreep (geen auto-freeze van
      agents) — alleen een verplichte melding. Een automatische reactie op
      een ruwe kalibratiemeting met weinig data zou zelf een nieuwe bron
      van overfit worden, precies wat de bevriezingsafspraak (zie "Wat
      NIET te doen zonder te vragen" in `CLAUDE.md`) probeert te voorkomen.

### 4.8 Menselijke voorspellers — **[27-09]**, fase 2, pre-T₀

DD en zijn partner zijn de analisten van TCE. Hun oordeel hoort in
dezelfde tabel als dat van de agents — niet als "de waarheid", maar als
twee extra gescoorde voorspellers. Drie redenen: het is de baseline die
er voor TCE echt toe doet; het maakt het systeem vanaf T₀ᵇ direct
bruikbaar als kalibratie-instrument voor jullie eigen macro-oordeel,
ongeacht hoe de agents presteren; en het is de eerste echte inhoud voor
de thesis-mode van 5.4.

- [ ] Invoerpad: CLI of eenvoudig formulier waarmee elk van beiden
      wekelijks kwantielen/kansen vastlegt op een vrije keuze uit de
      doelen van cohort 0, onder hetzelfde contract (4.1), met
      `agent='human:dd'` / `'human:partner'`. Zelfde mechanische QC.
- [ ] Blind: de invoer gebeurt vóórdat de forecast-ronde van die week
      zichtbaar is, anders meet 4.5 de agents twee keer.
- [ ] In het dashboard (5.2) naast agents en baselines, zonder
      onderscheid in weergave.

---

## 5. Output & Interfaces — de database is de waarheid, dit is de weergave

Nog niets van gebouwd. Alles post-T₀, met één uitzondering: het
kalibratie-deel van 5.2.

### 5.1 API-laag — post-T₀
- [ ] Eén centrale API op de database
- [ ] Dashboard, alerts, CLI en chat lezen allemaal uit dezelfde bron

### 5.2 Dashboard — kalibratiedeel vroeg, rest post-T₀
- [ ] **Kalibratiecurves, CRPS/Brier, effectieve n en skill-posterior
      per agent** — incl. mensen, baselines en synthesizer, zonder
      onderscheid in weergave. Hoog in fase 4. Als we het eigen track
      record niet dagelijks zien, stuurt niemand bij
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

- [ ] **Welke VPS-provider?** Richting (VPS) is beslist; provider en
      instance nog niet. De code veronderstelt niets over de machine.
      Blokkeert T₀ᵃ — eerstvolgende beslissing.
- [ ] Statische vs. adaptieve trigger-thresholds per domein (hangt samen
      met 4.2). **Deels beslist:** statisch tot T₀+6 maanden, daarna pas
      adaptief — anders is er geen cohort om tegen te meten
- [ ] **[27-09]** FOMC-statement als tekstinput voor de monetary agent
      vóór T₀ (2.1) — DD beslist; zonder tekst is correctie 3 uit deel A
      geaccepteerd.
- [ ] **[27-09]** De definitieve doelenlijst per agent voor cohort 0
      (startlijst in deel A) en de prior voor de skill-posterior (4.5) —
      vast te leggen bij de freeze in fase 3b, niet later.
- [ ] Library + bronnen-hiërarchie per agent, uitgroeiend tot een eigen
      database-hiërarchie: boeken > academische papers > investor letters
      > artikelen > YouTube-video's > nieuwsberichten > X-posts. Analoog
      aan `analyst_agent.ai/src/knowledge/` — dat project heeft dit zelf
      ook als open vraagstuk (`docs/rejected-alternatives.md`,
      evidence-tiering). Raakt waarschijnlijk `Claim`'s `confidence`-veld
      (1.1) zodra dit gebouwd wordt. **[27-09]** Dit is ook waar de
      "financial philosophy agent" uit DD's eindbeeld thuishoort: geen
      voorspeller, maar een kennislaag (RAG) die de prompts van de
      andere agents voedt.

## Beslist op 28-09-2026

- **Voorbereiding op een swing-trading-laag (1–3 dagen), zonder die te
  bouwen.** DD overweegt over 1–1,5 jaar een trading agent bovenop dit
  systeem. Die komt pas na de 6-maandenevaluatie (T₀ᵇ + 6 maanden) en
  staat bewust niet in deze roadmap. Wat nu wél gebeurt, omdat het
  goedkoop is en later niet in te halen: instrument-doelen voor de
  synthesizer (deel A cohort 0, 4.1), instrument-mapping (1.1),
  referentieprijs/roll-regel in de `resolution_rule` (4.1), en
  consensus, expected moves en ruwe headlines opslaan (1.2).
- **Bewust niet toegevoegd:** een 1–3-dagenhorizon in cohort 0 (de
  macro-laag wordt voor swing-trades waarschijnlijk een filter/bias op
  5 hd, niet de timing), een apart conviction-veld (richting en
  overtuiging volgen uit de kwantielen, en zijn dan wél gekalibreerd en
  gescoord), en een schaduw-P&L-module (met terugwerkende kracht te
  berekenen uit predictions + referentieprijzen).
- **Aandachtspunt:** CL-doel van de synthesizer vraagt een dagelijkse
  prijsbron; de commodity agent blijft alleen-monitoring omdat de
  huidige AV-bron maandelijks is. Kiezen in 1.4 vóór de freeze.

## Beslist op 27-09-2026 (was open)

- **Hoeveel agents draaien continu vs. op aanvraag.** Alle zes dagelijks
  in monitoring; forecast-ronde wekelijks; deep-dives op trigger. Zie
  1.11.
- **Hoeveel predictions per agent per week, en op welke knopen.** Niet
  een aantal per week maar zoveel mogelijk onafhankelijke doelen op
  cadans-bewuste horizonnen; startlijst in deel A. Knopen pas vanaf
  cohort v1.
- **Welke agents in cohort 0.** Vijf voorspellend (monetary, financial,
  sector, economic-lean, currency als controlegroep), commodity alleen
  monitoring, equity buiten het cohort, synthesizer en twee mensen
  gescoord. Zie deel A, "De agents van cohort 0".

## Beslist op 26-09-2026 (was open)

- **Prioritering ICT-trading (kort) vs. macro/mid-term (lang).** Beslist:
  dit systeem is de macro/mid-term-kant. Het verbetert de intraday-
  handel niet en dat is geen doel. Zie "Scope-afbakening" in deel A
- **Volgorde van de pijlers.** Beslist: niet meer 1→2→3→4→5, maar het
  kritieke pad naar T₀. Pijler 4 is grotendeels naar voren gehaald
