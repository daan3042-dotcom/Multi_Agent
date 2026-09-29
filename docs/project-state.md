# Current Project State

**Last updated:** 2026-09-28

## 28-09-2026 — Causale graaf v0 vastgelegd (1.10, fase 1)

Fase 1 is af op de back-fill-toets na, twee weken vóór schema. 309 tests
groen (was 291).

- `docs/causal-graph.md` — volledig herschreven van leeg sjabloon naar
  v0: **17 toestandsknopen, 41 pijlen**, plus de driedeling
  **observaties → toestanden → outputs**. Die driedeling is de
  belangrijkste ontwerpkeuze: zonder haar wordt de graaf een verzameling
  indicatoren. `CPILFESL` is geen knoop maar een observatie waaruit
  `inflation_persistence` geschat wordt; sectorrotatie is geen knoop maar
  een output.
- `src/contract/graph.py` — dezelfde graaf machine-leesbaar: `Node`-enum,
  `Edge` als bevroren dataclass met vertragingsvenster in dagen,
  `NODE_OWNER`, `find_cycles()`, `validate_graph()`.
- `tests/test_graph.py` — 18 tests.
- `docs/agents.md` — nieuwe gedeelde sectie: welke agent welke knoop
  bedient.

**Procesafwijking, expliciet vastgelegd.** 1.10 stond als handwerk voor
DD + partner, zonder LLM. Dat is op 28-09 bewust losgelaten: er is nog
geen partner, DD bouwt alleen een basis, uitgangspunt "eerst een
werkende basis, daarna optimaliseren". v0 is dus opgesteld door Claude +
een ChatGPT-sessie (die de driedeling en de 17 knopen aandroeg), door
Claude uitgewerkt tot pijlen en toetsbaarheid. **Consequentie:** wat er
over zes maanden forward-getest wordt is niet DD's eigen wereldbeeld
maar een conventioneel transmissiemodel. Een goed kalibratieresultaat in
mei 2027 bewijst dus geen edge. Vastgelegd in `docs/causal-graph.md`
("Herkomst") en in roadmap fase 1. Elke pijl die DD zelf wijzigt of
toevoegt wordt met `[DD]` gemarkeerd.

**Belangrijkste inhoudelijke vondst — niet elke pijl is toetsbaar.**
Roadmap 1.10 belooft dat elke pijl deterministisch op de back-fill
getoetst wordt. Dat kan voor 14 van de 41; 17 zijn zwak en 10 helemaal
niet. Drie structurele oorzaken:
1. **Definitie-overlap.** De NFCI bevat kredietspreads, VIX én
   aandelenkoersen als componenten. Een lead-lag-correlatie tussen
   `credit_risk_premium` en `financial_conditions` meet daarom grotendeels
   dat een getal met zichzelf correleert — een schitterende,
   betekenisloze uitslag. Zes pijlen.
2. **Feedbackrichting.** De graaf is bewust géén DAG. In een lus
   correleren A en B op elke lag, dus is de richting niet identificeerbaar.
   Per lus wordt alleen de pijl met de langste vertraging getoetst.
3. **Gelijktijdigheid.** `policy_stance → policy_expectations` speelt
   binnen uren; op dagdata is dat geen lead-lag.

Plus een meetvalkuil die apart genoemd staat: `energy_prices →
inflation_persistence` gaat uitsluitend over tweede-ronde-effecten, want
`inflation_persistence` wordt uit **core** CPI/PCE geschat en core sluit
energie per definitie uit. Zonder die notitie wordt een nul-uitslag
gelezen als "de pijl klopt niet" terwijl de meting het probleem is.

**Wat de graaf zichtbaar maakt over cohort 0.** Van de 17 knopen worden
er maar ~8 bediend door een agent die in cohort 0 daadwerkelijk
voorspelt: 2 economic-knopen blijven buiten de lean-versie, commodity
monitort alleen, en equity valt buiten het cohort. Dat bevestigt
onafhankelijk dat `graph_node` in cohort 0 terecht optioneel is
(correctie 6 van 27-09).

**Vier gaten zijn goedkoop te dichten, alle vier via FRED** (`DTWEXBGS`
voor `dollar` — lost meteen het bekende DXY-gat op; `T5YIE`/`T10YIE` voor
`inflation_expectations`; `DGS2` voor `policy_expectations`; `WALCL` voor
`liquidity`). **Minst zekere deel van dit werk, expliciet gevlagd:** of
FRED dagelijkse olie-/gasreeksen heeft die de commodity agent van
maandcadans naar dagcadans zouden tillen (en hem daarmee alsnog
voorspellend in cohort 0 zouden maken) is hier niet te verifiëren — geen
netwerktoegang in deze omgeving.

### Vervolg dezelfde dag: drie van de vier goedkope graafgaten gedicht

`monetary_policy_agent.py` haalt er vier FRED-reeksen bij (313 tests
groen, was 309): `DGS2` → `policy_expectations`, `T5YIE`/`T10YIE` →
`inflation_expectations`, `WALCL` → `liquidity`. Daarmee bezit die agent
die knopen niet alleen op papier maar kan hij ze ook schatten. De
deep-dive-prompt maakt nu expliciet onderscheid tussen wat de Fed dóét,
wat de markt verwacht dát de Fed doet, en wat de markt aan inflatie
verwacht — dat liep eerder door elkaar in één 10-jaars yield.

Afgewogen en vastgelegd in de moduledocstring: `MAX_AGE` blijft 35 dagen
hoewel drie nieuwe reeksen dagelijks zijn. Dat kan, omdat
`run_monitoring()`'s `max_age` de **bron-polling** bewaakt (hoe lang
geleden haalden we FRED voor dit domein succesvol op), niet de leeftijd
van elke losse reeks. Blijvende bekende grens, niet nieuw: 35 dagen is
ruim voor een agent die dagelijks draait.

**Minst zekere deel, expliciet gevlagd (CLAUDE.md checkpoint 4):** de
tolerance voor `WALCL` (100.000, verondersteld miljoenen USD ≈ $100 mrd).
Niveau én eenheid zijn niet tegen de live API geverifieerd — geen
netwerktoegang. Zwakker onderbouwd dan zelfs de commodity-tolerances.

**Het vierde gat (`dollar` ← `DTWEXBGS`) is bewust NIET gedicht.** Dat
hoort bij de currency agent, die op Alpha Vantage zit; het zou de eerste
agent met twee providers maken. De Source Registry kan dat (één entry per
provider+domain), maar `run_monitoring()` twee keer aanroepen voor
hetzelfde domein kan twee TRIGGERED `qc_case`s opleveren waarvan er één
voor altijd blijft hangen — de bekende grens uit 1.6 zou dan van
theoretisch naar structureel gaan. Multi-provider-ondersteuning in
`agents/base.py` is de echte voorwaarde en raakt alle zes agents. Ligt
bij DD.

### Vervolg: economic agent (2.7 lean) gebouwd en GEKOPPELD

339 tests groen (was 313). De enige nieuwe agent die vóór T₀ mag, en
daarmee de grootste resterende gatenvuller van de graaf: hij bedient
`growth` (PAYEMS) en `labor_tightness` (UNRATE + ICSA).

- `src/analysis/sahm_rule.py` — vijfde onderbouwingsmodel. Recessie-
  indicator uit UNRATE die we toch al ophalen. De drempel van 0,50 pp is
  expliciet GEEN plaatshouder: dat komt uit het gepubliceerde model
  (Sahm, 2019) en mag niet gekalibreerd worden, anders meet je een eigen
  model onder de naam van een gevestigd model. Weigert te rekenen op
  minder dan 15 maanden i.p.v. een korter venster te verzinnen.
- `src/agents/economic_agent.py` — ICSA (wekelijks), UNRATE en PAYEMS
  (maandelijks). Eigen registry-entry `FRED:economic`, `MAX_AGE` 10 dagen
  (strakker dan monetary's 35, omdat er een wekelijkse reeks tussen zit).
- `src/contract/domain_ontology.py` — `"economic"` toegevoegd als MACRO.
  Zonder dat faalt `classify_domain()` hard op het nieuwe domein.
- 26 tests, sectie in `docs/agents.md`.

**Checkpoint 1 gepasseerd op 28-09-2026.** DD heeft de agent beoordeeld
en akkoord gegeven; hij staat nu in `runtime/daily.py::default_agents()`.
Daarmee draaien er zes agents dagelijks in plaats van vijf. De test die
vastlegde dat hij nog NIET gekoppeld was, is in diezelfde ronde vervangen
door `test_agent_draait_mee_in_de_dagelijkse_runner` — die bewaakt nu het
omgekeerde, want een agent die stilletjes uit de cyclus verdwijnt levert
een gat in de reeks en dat maakt de kalibratie ongeldig.

**Besloten op 28-09: UNRATE blijft bij beide agents.** De dubbele
monitoring (monetary als beleidsinput, economic als eigenaar van
`labor_tightness`) is een bewuste keuze, geen gat. Gevolg dat blijft
staan: één werkloosheidscijfer dat beide drempels haalt geeft twee
triggers en mogelijk twee deep-dives over dezelfde publicatie, met een
andere invalshoek per agent.

**Minst zekere deel (CLAUDE.md checkpoint 4):** de tolerances voor ICSA
(25.000 aanvragen) en PAYEMS (250 duizend banen) veronderstellen dat ICSA
in aantallen staat en PAYEMS in duizenden personen. Niet tegen de live API
geverifieerd — geen netwerktoegang. Klopt PAYEMS' eenheid niet, dan staat
de tolerance drie ordes van grootte naast de werkelijkheid en triggert hij
nooit of altijd. Samen met `WALCL` het eerste wat op de VPS gecontroleerd
moet worden.

### Vervolg: `GRAPH_MAPPING` per agent (28-09, 362 tests groen)

Elke agent declareert nu per opgehaalde reeks welke graafknoop die reeks
helpt schatten, of expliciet `None`. Plus `validate_agent_mapping()` en
`unserved_owned_nodes()` in `contract/graph.py`, en
`tests/test_graph_mapping.py` (23 tests).

Wat dit vangt: een reeks toevoegen zonder te beslissen welke toestand hij
schat. Dat is hoe je ongemerkt een dashboard bouwt in plaats van een
model — en het is precies het gat dat de monetary agent had (vijf knopen
op zijn naam, één meetbaar), met de hand gevonden in plaats van door een
test. Urgentie zit in de klok: een gat dat je in maand drie van de
meetperiode ontdekt betekent drie maanden blinde data, en een forward
test is niet achteraf aan te vullen.

Twee vondsten uit het invullen zelf:
- **Vijf van de tien commodity-reeksen voeden geen knoop** (tarwe, maïs,
  katoen, suiker, koffie). Blijven gemonitord — zelfde API-call, dus
  gratis — maar schatten niets.
- **Alle elf sector-ETF's staan op `None`**, als ontwerp: sectorrotatie is
  een output, geen toestand.

Drie van de 17 knopen zijn onbediend en staan als test vastgelegd:
`wage_growth`, `inflation_persistence` (allebei post-T₀) en
`equity_valuation` (vraagt index-brede earnings yield).

**Nog niet gedaan, bewust:** de mapping wordt nog nergens gelézen. Geen
agent schrijft een `graph_node` op een claim of prediction, en `run_daily`
raakt `graph.py` niet aan. De mapping is nu een declaratie plus een test;
hij wordt dragend bij 4.1 (`predictions`-tabel), waar elke prediction een
`graph_node` moet krijgen.

## Eerdere stand

## Belangrijke koerswijziging (26-09-2026) — volgorde omgedraaid rond T₀

`docs/roadmap.md` is opnieuw herzien. De vijf pijlers en hun nummering
blijven ongewijzigd (code-comments die naar "roadmap 1.7" verwijzen
kloppen nog), maar de **uitvoeringsvolgorde** wordt niet meer door die
nummering bepaald. Reden: LLM-agents zijn niet eerlijk te backtesten —
elk model dat in 2026 naar maart 2020 kijkt, weet al wat er volgde.
Forward testing is daarmee de enige geldige weg, en dat kost
kalendertijd in plaats van werktijd. Pijler 4 (Evaluatie & Learning
Loop) is daarom grotendeels naar voren gehaald.

Nieuwe volgorde: deblokkeren → causale graaf → voorspellingscontract →
scoring → **T₀ (streefdatum 10-11-2026)** → verdiepen terwijl het draait
→ Bayesiaanse laag (mei 2027).

**De regel "pijler 1 helemaal af vóór pijler 2" vervalt** en wordt
vervangen door: alles op het kritieke pad naar T₀ eerst, ongeacht in
welke pijler het staat. Zie `docs/roadmap.md` deel A.

Nieuwe secties sinds deze herziening: 1.10 (causale graaf), 1.11
(scheduler & runtime), 3.4 (probabilistische aggregatie), 4.5 (scoring
engine), 4.6 (baselines). Nieuw bestand: `docs/causal-graph.md`
(sjabloon, in te vullen in fase 1).

## Eerdere koerswijziging (24-09-2026)

`docs/roadmap.md` is volledig herschreven rond een nieuwe, veel preciezere
doelarchitectuur (DD's artifact "Market Intelligence Platform —
Systeemoverzicht"), georganiseerd in vijf pijlers: Infrastructuur & Data →
Domain Agents → Synthese & Intelligence → Evaluatie & Learning Loop →
Output & Interfaces. De oude, eenvoudigere planning (secties A–I) is
vervangen, niet aangevuld — zie de mapping-tabel bovenaan de nieuwe
roadmap. De prioritering uit die ronde ("sectie 1 eerst volledig af") is
op 26-09-2026 vervangen, zie hierboven.

## Current architecture

Zie `docs/architecture.md`. Wat hieronder staat is gebouwd tegen de OUDE,
eenvoudigere roadmap-structuur (secties A–C.4) — inhoudelijk nog correct,
maar dekt maar een deel van de nieuwe doelarchitectuur (zie hierboven). In
de nieuwe telling: sectie 1.1/1.2/1.3(deels)/1.5(deels)/1.6/1.8/1.9 en
sectie 2.1-2.6 (kernmodellen, geen Finetune-items) staan. Een gedeelde
kwaliteitsregels-module (`agents/base.py::SHARED_QUALITY_RULES`) die elke
deep-dive automatisch meekrijgt, een leesbaar overzicht per agent
(`docs/agents.md`), en `src/analysis/` — citeerbare, Python-berekende
modellen (NFCI-interpretatie, Taylor Rule, relatieve sterkte,
voortschrijdend-gemiddelde-afwijking) die deep-dives onderbouwen i.p.v.
alleen "het cijfer veranderde". 261 tests groen (`pytest`).

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
  A-pad — claim opslaan → data-health-check → trigger → dispatch → QC →
  deep-dive opslaan — end-to-end doorloopt met synthetische data, inclusief
  het stille-faalscenario dat A.3 specifiek moet voorkomen.
- B.1 `src/agents/monetary_policy_agent.py` + gedeelde scaffolding
  `src/agents/base.py` — monitoring mode (FRED) + deep-dive mode.
- B.2 `src/agents/currency_agent.py` — zelfde opzet, Alpha Vantage FX,
  gestart als duo met B.1.
- B.3 `src/synthesizer/synthesizer.py` — legt gelijktijdige deep-dives
  naast elkaar (nog geen cross-domein-synthese, dat is F).
- B.4 `tests/test_integration_section_b.py` — end-to-end met het
  Fed-besluit-scenario (raakt monetary policy + currency tegelijk).
- `agents/base.py::SHARED_QUALITY_RULES` — centrale, niet-onderhandelbare
  schrijfregels (neutraliteit + verboden formuleringen, alleen aangeleverde
  claims, onzekerheid expliciet, aanleiding-zonder-overinterpretatie),
  automatisch door `run_deep_dive()` vóór elke domein-specifieke prompt
  geplakt. `monetary_policy_agent.py`/`currency_agent.py`'s
  `DEEP_DIVE_SYSTEM_PROMPT` bevat nu alleen nog vakinhoud — de gedupliceerde
  neutraliteitszinnen zijn eruit. Naar aanleiding van DD's vraag of alle
  agents straks goed kunnen samenwerken en hoe we de analysekwaliteit
  structureel hoog houden (zie `CLAUDE.md`, "Werkwijze met DD").
- C.1 `src/agents/equity_agent.py` — dunne adapter die analyst_agent.ai's
  bestaande output (`AnalystAgentReport`: verified_metrics, Altman/
  Piotroski/reverse-DCF, rapporttekst) in het A-contract giet. Geen eigen
  LLM-deep-dive-call: `needs_review` wordt 1-op-1 overgenomen van
  analyst_agent.ai's eigen QC. Elke ticker krijgt zijn eigen domain
  (`equity:<TICKER>`) om te voorkomen dat de delta-trigger verschillende
  tickers' gelijknamige metrics (bijv. "operating margin") met elkaar
  vergelijkt — deze fix hergebruikt `agents/base.py`'s nieuw uitgepakte
  `evaluate_deltas()`, en bewijst dat equity-triggers zonder enige
  aanpassing door dezelfde `manager.dispatch()` gaan als B.1/B.2.
- C.2 `src/agents/financial_agent.py` — financiële-marktcondities (NFCI,
  high-yield credit spread, VIX, 10Y-2Y yield curve, allemaal FRED), zelfde
  opzet als B.1/B.2. Losstaand van equity (bedrijfsfundamentals) en
  monetary policy (Fed-beleid zelf) — scope bevestigd met DD voordat
  gebouwd, want "financial" was zonder die check een dubbelzinnige naam.
- `docs/agents.md` — leesbaar overzicht per agent (wat volgt hij, wanneer
  triggert hij, waar gaat de deep-dive over), tegenhanger van
  `analyst_agent.ai`'s `framework.py`. Nieuwe regel in `CLAUDE.md`: een
  agent is pas "af" met een sectie hierin.
- `src/analysis/` (nieuw, mirrors `analyst_agent.ai/src/analysis/`): eerste
  bestand `nfci_interpretation.py`, de Chicago Fed's eigen gepubliceerde
  NFCI-interpretatie i.p.v. de LLM zelf te laten inschatten wat "krap"/
  "ruim" betekent. `financial_agent.py::deep_dive()` gebruikt dit al.
  Naar aanleiding van DD's kernvraag: hoe weet ik dat deze agents
  betrouwbare analyses doen? Antwoord: door onderbouwing in citeerbare,
  Python-berekende modellen te bouwen (zoals equity al had via Altman Z/
  Piotroski), niet alleen "cijfer veranderde, LLM schrijft erover".
- Neutraliteitsregel expliciet ge-scoped (`agents/base.py`'s docstring):
  geldt voor de automatische monitoring/deep-dive-laag, niet als blokkade
  voor een toekomstige, apart te bouwen "thesis-mode" (sectie G.3) — DD wil
  daar wél expliciet gevraagde directionele/probabilistische antwoorden
  (zijn FOMC-voorbeeld). Vastgelegd in `docs/roadmap.md` sectie G.3 en I.
- `src/analysis/taylor_rule.py` — de Taylor Rule (Taylor, 1993), tweede
  onderbouwingsmodel. `monetary_policy_agent.py::deep_dive()` haalt hiervoor
  op deep-dive-tijd extra data op (CPI 12 maanden terug voor YoY-inflatie,
  via `_fetch_series()`'s nieuwe `lag_observations`-parameter; GDPC1/GDPPOT
  voor de output gap) en voegt de impliciete "passende" Fed funds rate + de
  afwijking t.o.v. de daadwerkelijke rente toe als claims. r*=2% is een
  AANNAME, expliciet met DD afgestemd (was de openstaande vraag hieronder,
  nu beantwoord); π*=2% is het Fed's eigen, gepubliceerde doel. Bewust
  losstaand van de reguliere `FRED_SERIES`-monitoring — bbp-data is
  kwartaalcijfers, andere ververssnelheid, zou de gedeelde
  staleness-check verstoren.
- C.3 `src/agents/sector_agent.py` — alle 11 SPDR Select Sector-ETF's via
  Alpha Vantage, één plat domain (`sector`, zoals currency's FX-paren —
  geen per-ticker-namespacing nodig, elke ETF heeft een unieke metric_key).
  Trigger op ruwe prijs (delta-mechanisme); scope ("eigen databron", niet
  een aggregatie van al-gevolgde tickers) bevestigd met DD voordat
  gebouwd. Derde onderbouwingsmodel: `src/analysis/relative_strength.py`
  — het verschil tussen een sector-ETF's dagverandering en die van SPY
  (S&P 500), onderscheidt sector-rotatie van een bredere marktbeweging.
  DD's eigen voorbeeld ("XLB daalt t.o.v. S&P 500") is hier letterlijk het
  ontwerp geweest.
- C.4 `src/agents/commodity_agent.py` — 10 grondstoffen via Alpha Vantage,
  1-op-1 uit `analyst_agent.ai`'s bestaande `SUPPORTED_COMMODITIES`-lijst
  (incl. koper — ERO Copper). Eén plat domain (`commodity`). Trigger op
  ruwe prijs. Vierde onderbouwingsmodel:
  `src/analysis/moving_average_deviation.py` — afwijking t.o.v. het
  6-maands voortschrijdend gemiddelde, berekend uit dezelfde API-respons
  als de huidige prijs (geen extra databron nodig, in tegenstelling tot
  de andere drie modellen). Eerste agent met een databron die écht geen
  overlap heeft met B/C.1-C.3.

261 tests groen (`pytest`).

## Currently working on / just finished

- 24-09-2026: koerswijziging naar de nieuwe, vijf-pijler-doelarchitectuur
  (zie bovenaan) — `docs/roadmap.md` herschreven. Daarna: eerste,
  afgebakende slice van pijler 1.1 gebouwd — vier tijdstempels op `Claim`
  (`src/contract/output_contract.py`) en de domain-ontologie
  (`src/contract/domain_ontology.py`), incrementeel gemigreerd over alle
  6 agents, `agents/base.py` en de testsuite (154 tests groen). Daarna
  1.8 (LLM-taken-tabel) afgerond — puur documentatie, legt expliciet
  vast welk component wel/niet een LLM gebruikt (`docs/architecture.md`).
  Bewust NIET meegenomen: 1.2's volledige event-model (observations/
  entities/measurements/events) — dat is losstaand vervolgwerk, met DD
  te bepalen wat de volgende stap is (1.3, 1.4, 1.5, 1.6 of 1.7). Daarna
  1.2's eerste entiteit gebouwd: `agent_runs` — een audit-log per
  monitoring/deep-dive-cyclus (`src/storage/schema.py::record_agent_run/
  list_agent_runs`, aangeroepen vanuit `agents/base.py` op elk pad,
  ook bij falen), voorbereidend op 1.7 (Observability). 157 tests groen.
  1.2's checklist is nu opgesplitst per entiteit i.p.v. twee brede
  bundel-bullets, zodat voortgang zichtbaar is zonder op alle 8-9
  entiteiten tegelijk te wachten. Daarna, na overleg met DD: 1.3's
  revisie-detectie gebouwd (`health/data_health.py::detect_revision`,
  `triggers/trigger_engine.py::evaluate_revision`, gewired in
  `agents/base.py::run_monitoring`) — bewust TEGEN de bestaande
  `claims`-historie i.p.v. een nieuwe `observations`-tabel, die nu geen
  andere consument zou hebben dan deze ene check (zie
  `docs/architecture.md`, Ontwerpkeuzes). 1.2's observations-entiteit
  blijft daarom open totdat er een échte reden is om 'm van claims te
  scheiden. 166 tests groen. Daarna: 1.7 (Observability) in twee delen
  afgerond. Deel 1 — `src/health/system_health.py::system_health()`: één
  centrale functie die de status per component teruggeeft (source,
  ingestion, database, trigger, agent, LLM), gebouwd op `agent_runs`
  (1.2) en `data_health` (A.3) — geen nieuw statusmodel, hergebruikt
  overal `HealthStatus`. Puur de backend-functie, nog geen dashboard
  (dat is 5.2). Deel 2 — idempotency: `event_id` + partial unique index
  op `agent_runs` (`src/storage/schema.py::has_successful_run`), en
  `agents/base.py::AlreadyProcessedError` die `run_monitoring`/
  `run_deep_dive` VÓÓR een fetch/LLM-call laat weigeren als een
  event_id al succesvol verwerkt is. Bewust op `agent_runs`-niveau
  gebouwd, niet `claims`-niveau (afweging vastgelegd in
  `docs/architecture.md`, Ontwerpkeuzes). Optioneel/backward-compatible:
  geen enkele van de 6 bestaande agents geeft nu een event_id mee — dat
  wacht op een toekomstige scheduler/orchestratielaag. `docs/agents.md`
  is NIET bijgewerkt: dit werk verandert niets aan wat een agent
  monitort/triggert/deep-dived, puur infrastructuur. 194 tests groen.
  Daarna: 1.4 (Source Registry). Aanleiding: system_health() maakte
  zichtbaar dat monetary_policy_agent.py en financial_agent.py allebei
  de kale providernaam "FRED" als data_health-source_name gebruikten —
  één gedeelde rij voor twee agents met een andere verwachte
  ververssnelheid, waarbij de ene agent's successen de andere's
  staleness konden verbergen. Nieuw: `src/storage/schema.py`'s
  `sources`-tabel + `register_source`/`get_source`/`list_sources`
  (UPSERT, geen event-log), `src/sources/registry.py::SourceConfig`.
  Ontwerpbeslissing (uitgebreid beargumenteerd in `docs/architecture.md`,
  Ontwerpkeuzes): één registry-entry per (provider, domain)-combinatie,
  NIET per provider — een entry per provider alleen zou de kernbug niet
  oplossen (data_health zou nog steeds gedeeld blijven). `monetary_policy_
  agent.py`/`financial_agent.py` gemigreerd naar eigen source_keys
  (`FRED:monetary_policy`/`FRED:financial`) — regressietest bewijst dat
  hun data_health-geschiedenis nu écht onafhankelijk is. `health/
  system_health.py::sources_from_registry()` (nieuw) leest de registry
  uit en vult `system_health()`'s `sources`-parameter automatisch.
  `docs/agents.md` kreeg een korte toelichting bij monetary_policy/
  financial (de enige twee waar dit voor een lezer relevant is). Daarna,
  op DD's verzoek: `currency_agent.py`, `sector_agent.py`,
  `commodity_agent.py` ook naar het register gemigreerd (zelfde patroon,
  geen bug om op te lossen maar wel consistentie — alle 5 agents met een
  eigen live databron staan nu op dezelfde manier geregistreerd). 208
  tests groen. Daarna: 1.3's laatste twee bullets afgerond. Vier nieuwe,
  pure checkfuncties in `health/data_health.py`: `evaluate_completeness`
  (verwachte metric ontbreekt in één pull), `evaluate_validity` (type/
  bereik-check op een losse waarde), `evaluate_consistency` (klopt een
  afgeleide claim met zijn eigen input), `evaluate_continuity` (gat in de
  tijdreeks, los van of de laatste waarde zelf stale is). Plus
  `QualityStatus` (HEALTHY/DEGRADED/INVALID) als NIEUW, complementair
  rollup-type — geen hernoeming van `HealthStatus`, uitgebreid
  beargumenteerd in `docs/architecture.md` (Ontwerpkeuzes: een hernoeming
  zou ~4 modules + 3 testbestanden raken én is niet eens 1-op-1 mogelijk
  tussen 4 en 3 waarden). Geen enkele wiring in agents/base.py of
  trigger_engine.py geforceerd (zie Known problems) — dit blijft dus
  onzichtbaar in het gedrag van de 6 agents, `docs/agents.md` is daarom
  niet aangepast. 231 tests groen. Daarna: 1.6 (QC & State Machine)
  afgerond, de LAATSTE volledig openstaande sectie-1-post (1.2's overige
  entiteiten blijven bewust open, zie de losse regels onder 1.2 in
  `docs/roadmap.md`). Nieuwe `qc_cases`-tabel + `qc.qc.QCCaseStatus`/
  `QC_TRANSITIONS`/`decide_qc_outcome()` — een ECHTE state machine
  (overgangen gevalideerd, geen vrij label). Automatisch gewired in
  `agents/base.py`: een case ontstaat bij TRIGGERED zodra
  `run_monitoring()` triggert, en `run_deep_dive()` zoekt 'm zelf op
  (geen signatuurwijziging, geen wijziging aan de 6 agent-wrappers) en
  zet 'm door tot QC_PASSED/QC_FAILED/NEEDS_REVIEW. `QualityStatus`
  (1.3) is nu ECHT gewired als input voor die beslissing — sluit de open
  lus die 1.3 liet liggen. `DomainOutput.needs_review` en de qc_case-
  status volgen nu dezelfde ene beslissing, nooit meer los van elkaar.
  ARCHIVED is de enige handmatige overgang. `docs/agents.md` kreeg een
  korte, gedeelde toelichting (geldt voor alle 6 agents gelijk, geen
  per-agent secties aangepast). Ook vastgelegd: de domeinprioritering-
  vraag (continu vs. on-demand) blijft bewust open tot er een scheduler
  is — zie "Open questions" hieronder. 261 tests groen.
- Vóór de koerswijziging afgerond (oude, kleinere scope): sectie B +
  gedeelde kwaliteitsregels + C.1-C.4 (equity-adapter, financial agent,
  sector agent, commodity agent) + `docs/agents.md` + `src/analysis/`
  (NFCI-interpretatie, Taylor Rule, relatieve sterkte, voortschrijdend-
  gemiddelde-afwijking).

### Vervolg: API-budget gemeten — Alpha Vantage past waarschijnlijk niet (28-09)

367 tests groen. Nieuw: `docs/data-sources.md` + `tests/test_api_budget.py`.
Dit is het checklistpunt "API-quota meten" uit fase 0, dat vóór T₀ᵃ af moest
met de clausule "anders bron wisselen".

**De telling, rechtstreeks uit de code:**

| Provider | Monitoring/dag | Worst case met deep-dives |
|---|---|---|
| FRED | 15 | 20 |
| Alpha Vantage | **24** | **46** |

FRED is ruim en gratis, geen zorg. **Alpha Vantage is het knelpunt:** de
gratis tier ligt in de orde van 25 requests per dag, dus de monitoring
alléén zit al tegen het plafond en elke deep-dive-dag gaat eroverheen.

**Waarom dit erger is dan het lijkt:** het Alpha Vantage-volume piekt
precies op de dagen dat er veel triggert. Vallen de calls daar stil, dan
ontbreken systematisch de volatiele weken — en een gat dat samenhangt met
marktbeweging maakt het track record beter dan het is. Dat is het ene
faalpatroon dat de hele forward test ongeldig maakt, en je merkt het pas
bij de evaluatie.

**Niet geverifieerd (checkpoint 4):** het exacte quotum van de tier die bij
DD's key hoort. Geen netwerktoegang vanuit de ontwikkelomgeving. Mogelijk
heeft de key uit `analyst_agent.ai` een betaalde tier — dan verandert de
conclusie. **DD moet dit op zijn accountpagina controleren.** De
call-aantallen zelf staan wel vast; die komen uit de code.

**Vier opties, uitgewerkt in `docs/data-sources.md`.** De interessantste is
optie 1: commodity van Alpha Vantage naar FRED. Dat haalt 10 calls weg én
tilt die agent van maand- naar dagcadans, waardoor hij in cohort 0 kan
voorspellen in plaats van pas in cohort v1. Twee problemen in één keer.

**Ook toegevoegd op DD's verzoek:** een nieuw checklistpunt bij T₀ᵇ —
reeksenlijst per agent definitief, elke graafknoop bediend of expliciet
uitgesteld. Met de notitie dat dat punt vóór de drempelkalibratie valt en
niet bij de freeze: je kunt geen drempel kalibreren voor een reeks die nog
niet gekozen is. De freeze bevroor wél de doelenlijst, de drempels en de
prompts, maar nergens de monitoring-scope waaruit die doelen gekozen
worden.

### Vervolg: de laatste twee fase-0-codeitems (28-09, 375 tests groen)

Hiermee zijn alle fase-0-items die niet op de VPS wachten afgerond. Wat
rest in fase 0 is de back-fill (geblokkeerd tot er live data is) en vier
punten op DD's naam.

**1. Atomiciteit claims/agent_runs.** `storage/schema.py::
save_output_with_run()` zet de DomainOutput, zijn claims én de
`agent_runs`-regel in één transactie; `agents/base.py` gebruikt 'm op alle
drie de opslagpaden (monitoring, geslaagde deep-dive, mislukte deep-dive).
`save_domain_output()` en `record_agent_run()` blijven bestaan voor
losse aanroepers.

Het venster tussen de twee oude commits had twee uitgangen, en de tweede
was erger dan waar het item voor bedoeld was:
- **Crash ertussen** → claims zonder audit-regel. En omdat
  `has_successful_run()` naar `agent_runs` kijkt, zag 1.7's idempotency de
  cyclus als niet-gedaan: een herstart haalde alles opnieuw op en schreef
  de claims er nóg een keer bij.
- **Dubbele `event_id`** → de partial unique index weigerde de tweede
  agent_run, maar de claims waren al gecommit. De bescherming tegen
  dubbele verwerking leverde dus zelf dubbele claims op. Dat staat nu als
  regressietest vast (`test_dubbele_event_id_laat_geen_dubbele_claims_achter`).

Eén volgordewijziging in `run_monitoring()`: `evaluate_deltas()` draait nu
vóór het opslaan in plaats van erna, omdat `trigger_count` in dezelfde
transactie mee moet. Het leest alleen `previous_by_metric`, dat al
opgehaald was, dus de uitkomst verandert niet.

**2. Ouderdomsgrens in `system_health()`.** Een run ouder dan de grens
telt niet meer als actuele status. Bewust asymmetrisch tussen de twee
modi:
- **monitoring** ouder dan 2 dagen → `STALE`. Deze hoort elke dag te
  draaien, dus 'al dagen niets' betekent dat de cyclus stilstaat en dat
  moet juist wél alarmeren.
- **deep_dive** ouder dan 7 dagen → `UNKNOWN`. Deze draait alleen na een
  trigger; weken niets is normaal en zegt niets over de gezondheid.

Het probleem dat dit oplost: deep-dives zijn event-gedreven, dus na één
mislukking kon het weken duren voor er een nieuwe run overheen kwam. Tot
die tijd gaf `system_health()` elke dag opnieuw een kritieke melding over
hetzelfde oude voorval — de manier waarop een monitoringsysteem zichzelf
nutteloos maakt, omdat je leert de dagelijkse melding weg te klikken en
daarmee ook de echte mist. Een oude *geslaagde* run wordt hetzelfde
behandeld: even oud is even weinig informatief.

Beide grenzen zijn parameters met een default, instelbaar door de
aanroeper — zelfde dependency-injection-gedachte als de rest van die
module.

### 28-09-2026, avond: eerste live runs op de VPS — drie bevindingen

398 tests groen (was 389). De VPS staat sinds vandaag op de default branch
en heeft twee keer gedraaid met de nieuwe code. Dat leverde meer op dan een
bevestiging.

**1. De nieuwe code werkt op de FRED-kant, volledig.** Monetary haalde 8
reeksen op (was 4), financial 4, economic 3 — 15 van de 15. De economic
agent draait mee in de dagelijkse cyclus.

**2. De drie onzekere eenheden kloppen allemaal.** Dit was het als minst
zeker gevlagde deel van het werk (checkpoint 4):

| Metric | Gemeten | Aanname | |
|---|---|---|---|
| `fed_balance_sheet` | 6.747.704 | miljoenen USD | ✅ |
| `initial_claims` | 197.000 | aantal aanvragen | ✅ |
| `nonfarm_payrolls` | 159.075 | duizenden personen | ✅ |

De vlaggen zijn weggehaald. Eén drempel bleek wel fout: WALCL stond op
100.000 (~$100 mrd per week), wat alleen bij crisis-QE voorkomt terwijl een
normale week $5–30 mrd is. Die zou dus nooit gevuurd hebben en liet de
knoop `liquidity` blind voor het afbouwtempo. Nu 25.000.

**3. Alpha Vantage leverde 6 van de 24 — en niemand had het gemerkt.**
Twee runs, hetzelfde beeld: currency 1/3, sector 2/11, commodity 2-3/10.
FRED leverde beide keren alles. **Alle vijf agents rapporteerden
`success=True`**, omdat `fetch_snapshot()` alleen faalt als geen enkele
reeks lukt.

Dat laatste was het echte probleem: een bron die voor 80% wegvalt was niet
te onderscheiden van een gezonde dag, en dat is precies het faalpatroon dat
een forward test ongeldig maakt — de uitval piekt op volatiele dagen, dus
je verliest systematisch de weken die ertoe doen.

**Daarom is de completeness-check (1.3) gewired**, na anderhalve dag
bewust ongewired te zijn gebleven. `trigger_engine.
evaluate_completeness_result()` zet een gedeeltelijke pull om in één
trigger per cyclus (niet één per missende reeks), met severity naar rato.
Elf bestaande tests voerden een gedeeltelijke stub-snapshot en gingen
ervan uit dat dat geen trigger gaf; die filteren nu op `metric_key`,
waarmee hun eigenlijke bedoeling — het delta-mechanisme, niet
completeness — expliciet wordt.

**Beslist door DD: betaalde Alpha Vantage-tier**, niet de commodity agent
naar FRED migreren. Een migratie kost engineeringtijd en introduceert
nieuwe onzekere reeks-id's én andere eenheden (koper per ton in plaats van
per pond), terwijl T₀ᵃ vlakbij ligt en de klok geen kalendertijd
terugkrijgt. Wat het NIET oplost: het commodity-endpoint blijft
maandelijks, dus die agent blijft in cohort 0 monitoring-only — zoals al
gepland. De completeness-check is meteen de controle op de upgrade.

### Fase 2 begonnen: het voorspellingscontract (4.1) — 417 tests groen

Blokkade 3 van de vier uit deel A: "`predictions` bestaat niet — er is
niets te scoren." De tabel en het contract staan nu; het PRODUCEREN van
voorspellingen is de forecast-ronde (2.0) en komt hierna.

- `src/contract/prediction.py` — `Prediction` als bevroren dataclass met
  alle velden uit 4.1. Twee vormen: `QUANTILE` (q10/q50/q90) voor
  numerieke doelen en `BINARY` (kans + `event_rule`) alleen waar geen
  continue waarde bestaat. Horizonnen cadans-bewust: `TRADING_DAYS`
  (5/21/63) voor dagreeksen, `RELEASES` (1/2/3 prints) voor week- en
  maandreeksen — een 5-daagse voorspelling op CPI bestaat niet.
- `src/storage/schema.py` — `predictions`-tabel, bewust **zonder update-
  of delete-pad**. Achteraf bijstellen is de fout die het hele
  forward-testopzet probeert te vermijden, dus die mogelijkheid hoort niet
  te bestaan. Plus `save_prediction()`, `list_predictions()` en
  `list_due_predictions()` (de invoer voor de resolver uit 4.5).
- `tests/test_prediction.py` — 19 tests.

**Waar de mechanische QC zit, en waarom daar.** Roadmap 4.1 vraagt dat een
prediction zonder kwantielen/kans, regel, horizon of `model_id` geweigerd
wordt. Dat is in het CONTRACT geïmplementeerd en niet in `src/qc/`:
`src/qc/` is de veiligheidsgordel voor TEKST (klopt de deep-dive met de
cijfers), dit is een vormcheck op data. Zelfde fail-loud-precedent als
`Claim`. Daarmee blijft `src/qc/` onaangeroerd en was checkpoint 2 niet
aan de orde.

Het schema herhaalt dezelfde eisen als CHECK-constraints. Dubbelop met
opzet: een bug in het contract kan dan geen ongeldige rij opleveren, en er
staat een test die dat met ruwe SQL bewijst.

**Contract- en cohortversies liggen vast.** `CONTRACT_VERSION = "v0"`,
`COHORT_0`, en `graph_version` wordt overgenomen uit `contract/graph.py`.
Een wijziging aan het contract start een nieuw cohort; een modelwissel of
promptwijziging is een covariaat binnen hetzelfde cohort (`model_id`,
`prompt_version`) — anders zijn er in mei acht cohorten van drie weken.

**Mensen en baselines gebruiken hetzelfde contract.** `agent` accepteert
`human:dd`, `human:partner`, `baseline:*` en `synthesizer`. Zonder dat
zijn mens en model niet op dezelfde meetlat te leggen, en dat is precies
wat 4.8 wil.

**Nog niet gedaan, bewust:** de forecast-ronde die de voorspellingen
maakt (2.0), de resolver en de `evaluations`-tabel (4.5), de menselijke
invoer (4.8), en de instrument-doelen van de synthesizer met hun
roll-regel (4.1, laatste bullet — wacht op de instrument-mapping in 1.1).

### Forecast-ronde gebouwd (2.0) — 449 tests groen

De derde modus naast monitoring en deep-dive, en daarmee wat de
predictions-tabel gaat vullen.

- `src/contract/horizons.py` — horizon naar `resolves_at`. Het onderscheid
  dat deze module draagt: `resolution_rule` is de AUTORITEIT over wat er
  gescoord wordt, `resolves_at` zegt alleen wanneer de resolver gaat
  kijken. De eerste moet exact zijn, de tweede niet — anders zou je de
  publicatiekalender van FRED moeten voorspellen om een voorspelling te
  mogen doen.
- `agents/base.py` — `ForecastTarget`, `ForecastRoundResult` en
  `run_forecast_round()`.
- `FORECAST_TARGETS` in monetary, financial, economic en currency: 8, 12,
  6 en 9 voorspellingen per ronde.
- `tests/test_horizons.py` (13) + `tests/test_forecast_round.py` (15).

**Een ronde die deels mislukt wordt niet weggegooid.** Levert het model 9
van de 11 doelen, dan worden die 9 opgeslagen en komen de ontbrekende in
`issues`. Negen goede voorspellingen weggooien omdat de tiende niet klopte
kost meetbare data die niet in te halen is — dezelfde les als de
completeness-check van vanmiddag.

**Databasemigratie, en waarom die nodig was.** `agent_runs.mode` had een
CHECK die alleen `monitoring` en `deep_dive` toestond. `CREATE TABLE IF
NOT EXISTS` raakt een bestaande tabel niet aan, dus de VPS-database had die
oude constraint nog: de forecast-ronde zou op een verse testdatabase
slagen en daar falen. `_migreer_agent_runs_mode()` herbouwt de tabel als
het nodig is, idempotent, en maakt de indexen opnieuw aan — de partial
unique index op `event_id` stil kwijtraken zou 1.7's idempotency ongemerkt
uitschakelen. Vier tests, waaronder een die bewijst dat bestaande rijen
behouden blijven.

**De sector agent heeft doelen gekregen (DD, 28-09).** SPY wordt nu elke
cyclus opgehaald en opgeslagen naast de elf ETF's, zodat het relatieve
rendement over een horizon achteraf uit de claims-historie te berekenen
is. 11 doelen op relatief rendement (5/21 hd) = 22 voorspellingen per
ronde — meer breedte dan de andere vier agents samen, en dat telt omdat
breedte statistische kracht oplevert en herhaling niet.

De dagelijkse relatieve sterkte per ETF wordt nu óók opgeslagen
(`<etf>_rel_spy`), berekend uit de `change_percent` die de quote toch al
meelevert. Nul extra API-calls. Die waarden hebben bewust GEEN MetricSpec
en triggeren dus niet: de escalatie blijft op de ruwe prijs lopen, want een
delta-trigger hierop zou de dagverandering van vandaag met die van
gisteren vergelijken — een tweede verschil, en dat is ruis.

Kosten: één extra Alpha Vantage-call per cyclus, 24 → 25. Twee tests die
ik eerder deze dag bouwde sloegen daarop meteen aan (het API-budget en de
graafmapping), en dat is precies waarvoor ze er zijn.

**Totaal: 57 voorspellingen per wekelijkse ronde over vijf agents.**

### De wekelijkse aanroep draait (2.0) — 474 tests groen

De ronde zat in `agents/base.py` maar werd nergens aangeroepen. Nu wel, in
`runtime/daily.py`, en daarmee is 2.0 als geheel af.

**Maandagochtend, DD's keuze.** Verse week, en de slotkoersen van vrijdag
staan er al in zonder dat er een nieuwe handelsdag overheen is gegaan.

**Het `event_id` is de ISO-week, niet de dag** (`2026-W40`). Daarmee is de
eenheid van herhaling de week. Cron vuurt elke ochtend; zonder dit zouden
dat zeven sets voorspellingen per week zijn, en dan meet de scoring straks
iets anders dan bedoeld. Een test pint dat maandag, dinsdag en de zondag
erna hetzelfde `event_id` opleveren.

**Met inhaalslag, en dat is een afweging.** Mislukt de maandag (VPS uit,
API plat, onparseerbare respons), dan draait de ronde op de eerstvolgende
dag die wél lukt binnen dezelfde ISO-week. In de praktijk zijn dat vier
kansen en niet zes: de cron draait ma t/m vr, dus in het weekend wordt de
code niet aangeroepen en redt het weekend een verloren week niet. Dat
staat nu expliciet in de docstring van `_forecast_due()`, omdat het
verschil tussen "de week" en "de werkweek" vanuit de code alleen niet te
zien is (DD merkte dat op, 28-09). De prijs: een
voorspelling van woensdag is niet volledig vergelijkbaar met één van
maandag. De opbrengst: geen lege week. Die keuze is asymmetrisch — een
verschoven dag is achteraf te analyseren (`created_at` legt de werkelijke
dag vast), een ontbrekende week niet. Voorspellen met de kennis van later
is geen voorspelling meer.

In de code staat daarom géén expliciete maandag-check. Die zou overbodig
zijn: de ISO-week begint op maandag, dus "eens per ISO-week, zodra de
cyclus draait" ÍS maandag zolang de maandag lukt. Eén regel met één
betekenis, in plaats van twee die elkaar overlappen.

**Forecast-problemen komen ergens uit.** `DailyRunResult.forecast_issues`
→ `has_problems` → exit-code van `run_daily.py` én de notificatie
(warning, niet critical: de ronde haalt zichzelf in binnen de week, dus
een mislukte maandag is nog geen verloren week; de melding herhaalt
dagelijks tot het gerepareerd is). Zonder die koppeling zou een ronde
kunnen mislukken terwijl cron exit 0 teruggeeft — het terugkerende
bugpatroon uit CLAUDE.md, een check die wel iets vaststelt maar nergens
uitkomt.

**Welke agents voorspellen, wordt afgeleid en niet opgeschreven.**
`_spec()` leest `FORECAST_TARGETS` uit de agent-module; geen doelen = geen
ronde. Zo is er geen tweede lijst die uit de pas kan lopen met de agents
zelf. Commodity heeft bewust geen doelen (maandelijkse bron, niet
resolvbaar op 5/21/63 handelsdagen) en een test legt dát als beslissing
vast, zodat het geen vergeten regel wordt.

**`FORECAST_PROMPT_VERSION` per agent, bewaakt met een hash.** Elke
prediction draagt `prompt_version`. Verandert iemand een prompt zonder het
versienummer op te hogen, dan staan er achteraf twee verschillende prompts
onder hetzelfde label en is dat deel van het cohort niet meer te
analyseren — en dat merk je pas bij de evaluatie, maanden later.
`tests/test_forecast_prompt_version.py` hasht de daadwerkelijk verstuurde
system prompt (FORECAST_SYSTEM_RULES + de vakinhoudelijke prompt) en faalt
met de nieuwe hash in de foutmelding. Zelfde patroon als
`test_api_budget.py`: een onzichtbaar effect zichtbaar maken op het moment
dat de regel geschreven wordt.

**De `--deep-dives`-vlag schakelt nu twee LLM-fasen in.** Een dry-run
zonder die vlag is dus een dry-run zonder voorspellingen. Vóór T₀ᵇ is dat
prima; daarna is elke zo'n week een gat in het cohort.

### Resolver, evaluations en scores (4.5) — 529 tests groen

Het systeem kon voorspellen maar niets afwikkelen. Blokkade 4 is daarmee
voor de helft weg; de drie baselines (4.6) staan nog open.

**De regeltekst is niet uitvoerbaar, en dat was het hele probleem.** Elke
prediction draagt een `resolution_rule` in vrije taal. Python kan die niet
uitvoeren, en een LLM hem laten interpreteren zou betekenen dat het model
dat de voorspelling deed ook bepaalt of hij uitkwam. Daarom draagt elke
prediction nu ook een `resolution_method`: een enum met vier waarden die
verwijst naar een functie in `src/contract/resolution.py`. De tekst is de
autoriteit voor mensen, de methode doet het rekenwerk. Dat ze hetzelfde
zeggen is een menselijk oordeel — `tests/test_resolution_mapping.py` pint
de afgesproken combinatie per doel vast, zodat een wijziging aan één van
beide opvalt.

De vier methoden: `level_at_or_after` (dagreeksen op een
handelsdagen-horizon), `nth_release` (week- en maandreeksen),
`relative_return` (de sector agent) en `direction_after_fomc` (de twee
binaire monetary-doelen).

**De vintage-regel kwam gratis.** Bijna elke regel zegt "eerste print,
latere revisies wijzigen de uitkomst nooit". Dat is hier geen extra werk:
we slaan elke cyclus op wat de bron op dat moment zei, dus de
claims-historie ís een vintage-archief. De eerste print van een periode is
de claim met die `source_time` die wij als eerste zagen.

**Drie toestanden, niet twee.** Afgewikkeld, nog-niet-afwikkelbaar en
onafwikkelbaar. De middelste krijgt bewust GEEN rij: dan blijft de
voorspelling vanzelf in beeld bij de volgende run. Pas na 30 dagen wachten
wordt hij als `unresolvable` weggeschreven, met reden. Zonder die grens
zou een reeks die stil gestopt is met publiceren een groeiende stapel
opleveren die elke dag opnieuw geprobeerd wordt en nooit opvalt; zonder
het wachten zou een normale publicatievertraging een geldige meting uit
het cohort gooien. De 30 dagen zijn een keuze, geen berekening — ruim
boven de grootste vertraging die we kennen (PAYEMS, ~14 dagen), ruim onder
een kwartaal. **Hoort bij de freeze bevestigd te worden.**

**Scores.** Pinball loss per kwantiel, CRPS, Brier, log loss, en
`within_interval` als directe kalibratiecheck. Allemaal proper scoring
rules: wie zijn echte verdeling opschrijft scoort gemiddeld beter dan wie
iets anders opschrijft. Dat is de eigenschap waar de hele meetopstelling
op rust, dus er staat een test die het bewíjst op een steekproef van
20.000 trekkingen in plaats van het aan te nemen — overmoed én lafheid
verliezen allebei.

CRPS is **benaderd** uit drie kwantielniveaus (2 × de gemiddelde pinball
loss). De echte CRPS integreert over alle niveaus; wij hebben er drie. Dat
mag omdat agents en baselines exact dezelfde behandeling krijgen en de
vertekening dus wegvalt in het verschil. Wat er niet mee mag: dit getal
vergelijken met een CRPS uit de literatuur.

**Twee bugs die de tests vonden, allebei van het stille soort:**

1. `resolves_at` erft het tijdstip van `created_at` (maandag 07:15 UTC),
   terwijl `source_time` van een dagreeks een kale datum is. Op tijdstip
   vergelijken sloeg de observatie van de afwikkeldag zelf over: elke
   handelsdagen-horizon zou één waarneming te ver gemeten hebben. De
   scores zouden gewoon binnenkomen — alleen van de verkeerde dag.
2. De FOMC-kalender stond als default-argument, en die wordt in Python één
   keer geëvalueerd bij het definiëren van de functie. Het invullen van de
   kalender zou dan pas na een herstart effect hebben gehad.

**Openstaand, en bewust: `FOMC_MEETING_DATES` is leeg.** De Fed publiceert
de vergaderdata jaren vooruit, maar ze zijn vanuit deze ontwikkelomgeving
niet te verifiëren en een verkeerde datum wikkelt een voorspelling
stilzwijgend op het verkeerde moment af. Benaderen met "de n-de
FEDFUNDS-print" mag niet: FEDFUNDS publiceert twaalf keer per jaar, de
FOMC vergadert acht keer, dus dat zou een andere gebeurtenis scoren dan de
voorspelling beschrijft. Zolang de tuple leeg is, blijven de twee
FEDFUNDS-doelen onafwikkelbaar en zegt de resolver per stuk waarom.
**Checkpoint 4 — DD vult de kalender vóór T₀ᵇ.**

### Baselines (4.6) — 590 tests groen

De meetlat. Zonder baseline zegt een score niets: een agent met een
pinball loss van 0,8 is goed of slecht afhankelijk van wat "het blijft zoals
het is" haalt. De baselines schrijven voorspellingen in EXACT hetzelfde
contract als de agents (zelfde doelen, horizonnen, afloopdatum, regel en
methode) en worden door dezelfde resolver met dezelfde scoringsregels
gescoord. Er is geen aparte evaluatiepijplijn.

**Persistence** (`src/scoring/baselines.py`): mediaan = het laatste niveau,
spreiding uit de historische veranderingen over de horizon. De
veranderingen zijn gecentreerd op hun eigen mediaan; zonder dat loopt de
historische drift mee en is het geen random walk meer maar een random walk
mét trend.

**Climatology**: de historische verdeling, conditioneel op de kalendermaand
van `resolves_at` als daar ≥60 waarnemingen voor zijn, anders
onvoorwaardelijk. De `note` van elke voorspelling zegt welke van de twee
het werd — een stille terugval zou twee methoden onder één label zetten.

**Ridge** (`src/scoring/ridge.py`): een lineair model op de z-scores van
alle reeksen van het domein. Puur Python, geen numpy (CLAUDE.md regel 2).
Kwantielen zijn anker + voorspelling + de residuen uit een expanding-window
cross-validatie, NIET uit de fit zelf: residuen van de trainingsdata zijn te
klein, en een overmoedige baseline is te verslaan door alleen breder te
voorspellen. Tussen trainings- en validatieblok zit een gat van `horizon_n`
rijen, want de vensters overlappen.

**Een baseline die niets weet, zegt niets.** Met minder dan 30 vensters, of
een laatste waarneming die te oud is, komt er GEEN voorspelling maar een
melding. Een baseline die met te weinig historie toch iets uitspreekt is een
strohalm, en die laat elke agent er beter uitzien dan hij is. Ridge-inputs
worden op ±5 afgekapt: een eenheidswijziging (WALCL bleek op 28-09 in
miljoenen te staan) geeft anders een z van tientallen die een lineair model
gedwee extrapoleert.

**Point-in-time, en waarom dat hier zwaarder weegt dan elders.** Een
maandcijfer heeft als `source_time` de eerste van de referentiemaand maar is
pas ~5 weken later bekend. Wie dat als "beschikbaar op de eerste"
behandelt, laat het model in de trainingsdata de toekomst zien — en dat is
onzichtbaar, want de scores zien er alleen beter uit. Elke reeks krijgt
daarom een conservatieve publicatievertraging per cadans, afgeleid uit de
reeks zelf. Er staat een lek-test: data waarin de toekomst afhangt van een
nog-niet-gepubliceerde waarde; het model hoort dat NIET te vinden. Bewezen
gevoelig: met het lek opzettelijk aan vindt het model de relatie
(coëfficiënt 2,013 bij een geplante 2) en faalt de test.

**Bevroren, en waarom de fit nog niet gedraaid is.** De ridge is "gefit op de
back-fill vóór T₀ᵇ en daarna bevroren" (roadmap 4.6). De historie staat op
de VPS, en de Alpha Vantage-helft ontbreekt nog — currency en sector hebben
zonder die back-fill te weinig historie. `fit_baselines.py` is standaard
droog; `--freeze` schrijft naar `baseline_models`, een tabel zonder
update-pad met een UNIQUE per specversie: opnieuw fitten is een nieuwe
`RIDGE_SPEC_VERSION` en dus zichtbaar. Tot dan meldt de ronde één regel per
domein ("nog geen enkel bevroren ridge-model") en draaien de andere twee
baselines gewoon door.

**Bewust niet voorspeld door een baseline:** de FEDFUNDS-richting. Zelfde
reden als de lege FOMC-kalender in 4.5: de gebeurtenis ligt op
FOMC-vergaderingen, en een basisrate uit maandelijkse FEDFUNDS-vensters zou
een andere gebeurtenis scoren. Die twee doelen worden alleen tegen de agent
zelf gescoord.

**Per wekelijkse ronde met volledige historie:** 55 kwantieldoelen × 3
baselines = **165 baseline-voorspellingen** naast de 57 van de agents.

**Ook gefixt in dezelfde ronde, en dat raakte de bestaande forecast-ronde:**
`run_forecast_round` bewaarde voorspellingen één voor één en schreef daarna
pas de `agent_runs`-regel. Crasht het proces ertussen, dan staat de ronde
niet als geslaagd geregistreerd terwijl de voorspellingen er wél staan, en
levert de herhaling van morgen dezelfde voorspellingen een tweede keer op.
In een track record is dat geen ruis: de week telt dubbel mee in kalibratie
en skill-posterior. Nu één transactie (`save_predictions_with_run`), met een
regressietest die op de oude code aantoonbaar faalt.

**Openstaand na dit werk:**
1. Ridge fitten en bevriezen (na de volledige back-fill, freeze-beslissing).
2. De publicatievertragingen per cadans (1/7/50 dagen) zijn conservatief
   maar niet per reeks geverifieerd — checkpoint 4.
3. Voor week- en maanddoelen ziet de ridge oudere inputs dan het LLM (tot
   ~5 weken). Te bevestigen bij de freeze.
4. De drempels `MIN_SAMPLES=30`, `MIN_SEASONAL_SAMPLES=60` en de
   ankerleeftijden zijn keuzes, geen berekeningen. Bij de freeze bevestigen.

## Known problems

Geen openstaande gaten binnen sectie A of B's eigen scope. Bewuste grenzen
(niet gaten):
- De tolerance-waarden in `agents/monetary_policy_agent.py` en
  `agents/currency_agent.py`'s `METRIC_SPECS` zijn illustratieve
  plaatshouders, geen door DD gevalideerde drempels — expliciet open
  beslissing, zie sectie H.
- De trigger-logica is "afwijking t.o.v. de vorige observatie" (delta), niet
  tegen een externe marktverwachting (die data hebben we niet) — een
  bewuste, praktische invulling van "tegen verwachting/thresholds leggen"
  uit B.1.
- **24-09-2026, live-validatiepoging:** FRED en Alpha Vantage zijn in de
  Claude Code-sandbox-omgeving hard geblokkeerd op netwerkniveau
  (organisatie-egress-policy, 403 op de CONNECT — "do not retry or route
  around it"). Geen bug in onze code; niet oplosbaar vanuit deze sessie.
  De Anthropic-API werkt wél (staat op de noProxy-allowlist) — key
  gevalideerd, een echte `models`-lijst opgehaald. `default_llm_review()`/
  `run_deep_dive()` zijn dus nog steeds nooit tegen ECHTE marktdata getest
  (wel tegen een echte Anthropic-call, met handmatig ingevulde
  voorbeeldclaims, mogelijk als vervolgstap). Volledige live-validatie
  vraagt een omgeving met onbeperkt uitgaand netwerkverkeer — relevant
  voor de nog openstaande deployment-vraag (waar draait dit straks 24/7).
- B.3's synthesizer combineert nog niet inhoudelijk (geen tegenstrijdigheid-
  detectie, geen weging) — dat is sectie F, bewust nog niet hier.
- C.1's `AnalystAgentReport` is een contract, geen werkende koppeling: er is
  nog geen code die een analyst_agent.ai-run daadwerkelijk uitvoert en zijn
  output in die vorm hierheen stuurt (subprocess, bestand, API — nog niet
  gekozen). Bewust uit scope van "de adapter bouwen"; zie `docs/architecture.md`.
- `currency_agent.py` heeft nog geen eigen onderbouwingsmodel (draait nog
  puur op "cijfer veranderde meer dan een geraden drempel") — een
  rentedifferentieel/carry-raamwerk (uncovered interest rate parity) zou
  hier de tegenhanger van de Taylor Rule kunnen zijn, maar vraagt extra
  databronnen (ECB/BOJ/BOE-rentes) die we nu niet hebben. Nog niet
  opgepakt.
- Taylor Rule's inflatiemaatstaf is CPI YoY (wat we al ophalen) i.p.v.
  core PCE (preciezer, maar een nieuwe databron) — een bewuste, praktische
  keuze om geen nieuwe dependency toe te voegen voor het eerste model.
- `sector_agent.py`'s tolerances zijn dollarbedragen per ETF, ruwweg op
  ~3% gekalibreerd — deze verouderen sneller dan bijv. een rentepercentage
  omdat ETF-prijsniveaus over maanden kunnen wegdriften. Een percentage-
  gebaseerde tolerantie zou robuuster zijn; expliciet genoemd als
  kandidaat voor DD's eigen latere finetuning, niet stilzwijgend als
  "goed genoeg" gepresenteerd.
- `sector_agent.py` triggert op de RUWE PRIJS van elke ETF, niet op de
  relatieve sterkte zelf (die wordt pas bij de deep-dive berekend) — een
  bewuste keuze om agents/base.py's gedeelde trigger-machinery niet te
  hoeven uitbreiden. Zie `docs/architecture.md` voor de volledige
  afweging; mocht DD liever een trigger ZIEN OP relatieve sterkte zelf,
  is dat een grotere wijziging (raakt gedeelde infrastructuur) die eerst
  besproken moet worden.
- `commodity_agent.py`'s tolerances zijn NOG minder zeker dan
  `sector_agent.py`'s — grondstofprijzen/eenheden zijn hier niet met
  zekerheid geverifieerd tegen actuele marktdata (in tegenstelling tot de
  ETF-prijzen, waar de schattingen redelijk vertrouwd zijn). Sterkste
  kandidaat tot nu toe voor DD's eigen latere finetuning.
- **1.7's `system_health()` — bewuste grenzen, geen gaten:**
  - "trigger"-component heeft GEEN eigen, apart bijgehouden faalstatus —
    trigger-evaluatie draait inline binnen `run_monitoring()`, dus de
    status is afgeleid (worst-of alle `ingestion:*`-statussen), niet
    onafhankelijk gemeten. Zie de moduledocstring van `system_health.py`.
  - "database"-component is een lichte `SELECT 1`-check — geen
    schijfruimte-, corruptie- of schrijfbaarheidscontrole.
  - `sources`/`domains` werden door de AANROEPER meegegeven, geen
    auto-discovery — **inmiddels opgelost door 1.4**: `health/
    system_health.py::sources_from_registry()` kan `sources` nu
    automatisch vullen vanuit de Source Registry, voor elke agent die
    zichzelf via `register_source()` declareert.
  - ~~Twee agents die dezelfde bronnaam delen... schrijven naar dezelfde
    `data_health`-rij~~ — **opgelost door 1.4**: `monetary_policy_agent.py`
    en `financial_agent.py` hebben nu elk hun eigen `source_key`
    (`FRED:monetary_policy`/`FRED:financial`). Zie hieronder voor de drie
    agents die dit patroon nog niet hebben (geen aantoonbaar conflict).
  - Idempotency (`event_id`) is volledig opt-in en wordt door NIETS in de
    huidige codebase gebruikt — er is nog geen scheduler/orchestratielaag
    die een stabiele event_id per cyclus zou kunnen leveren. Voorkomt nu
    dus nog geen enkele dubbele verwerking in de praktijk, alleen de
    infrastructuur staat klaar.
- **1.4's Source Registry — bewuste grenzen, geen gaten:**
  - `currency_agent.py`, `sector_agent.py`, `commodity_agent.py` zijn
    inmiddels óók gemigreerd (op DD's verzoek, tweede ronde na de eerste
    twee) — elk gebruikte al een unieke bronnaam (geen
    aantoonbaar FRED-achtig conflict), dus geen bug om op te lossen,
    maar wel voor consistentie: alle 5 agents met een eigen live databron
    staan nu op dezelfde manier in de registry. `equity_agent.py` heeft
    geen eigen live databron (adapter) en komt sowieso niet in
    aanmerking.
  - `fallback_source_key` bestaat als veld + FK-constraint, maar GEEN
    agent heeft een daadwerkelijke alternatieve bron geïmplementeerd —
    er is dus nergens iets om naar te verwijzen. Wiring van echte
    failover-logica in `agents/base.py::run_monitoring()` (proberen op
    de primaire bron, bij totale mislukking de fallback proberen) is
    open vervolgwerk, expliciet niet geforceerd binnen 1.4.
  - `quality_score` bestaat als veld, altijd `None` — de berekening
    ervan wacht op de Bayesiaanse weging uit de synthese-laag (sectie 3,
    nog niet gebouwd), zoals afgesproken.
  - Providerfeiten (latency, cost) worden gedupliceerd over meerdere
    registry-rijen als twee agents dezelfde provider delen (nu:
    `FRED:monetary_policy` en `FRED:financial` herhalen allebei "FRED
    API, gratis, ~1s per call") — een bewust geaccepteerde kleine
    redundantie, zie `docs/architecture.md` ("Ontwerpkeuzes") voor de
    volledige afweging tegenover het alternatief (dat de kernbug niet
    had opgelost).
- **1.3's laatste twee bullets — bewuste grenzen, geen gaten:**
  - Geen van de vier nieuwe checks is gewired in `agents/base.py` of
    `triggers/trigger_engine.py`, per check een andere reden:
    - **Completeness** is mechanisch het meest triviaal om te wiren
      (`run_monitoring()` heeft `metric_specs.keys()` en `snapshot` al in
      scope) — bewust NIET gedaan omdat het een gedragswijziging voor
      alle 6 agents tegelijk zou zijn (nieuwe triggers bij een normale,
      tot nu toe getolereerde gedeeltelijke pull — zie de
      `fetch_snapshot()`-moduledocstrings: "ontbrekende reeksen worden
      overgeslagen i.p.v. gegokt", dat is bewust bestaand gedrag). Een
      vraag voor DD, niet stilzwijgend besloten.
    - **Validity** heeft een `valid_range` per metric nodig die nog
      nergens is vastgelegd — zelfde categorie open beslissing als
      METRIC_SPECS' tolerances (sectie H), geen gok hier.
    - **Consistency** vraagt domein-specifieke herberekeningslogica per
      agent (bijv. de Taylor Rule-formule) — niet generiek te wiren
      vanuit `agents/base.py`, dat kent de formules niet.
    - **Continuity** heeft een "verwachte cadans" nodig die nu nergens
      apart van MAX_AGE bestaat (MAX_AGE bevat al een staleness-marge,
      is geen zuivere cadans) — zelfde categorie als validity's bereik.
  - `QualityStatus`/`rollup_quality_status()` oordeelt alleen per LOSSE
    claim/metric, geen aggregatie over meerdere metrics/domeinen heen
    (bijv. "hoe erg is één INVALID-claim tussen tien HEALTHY-claims voor
    het hele domein") — die synthese hoort bij sectie 3, net als
    `quality_score` uit 1.4.
  - Geen wiring betekent: `docs/agents.md` is NIET aangepast, dit werk is
    onzichtbaar in hoe de 6 agents zich nu gedragen — puur nieuwe,
    beschikbare infrastructuur.
- **1.6's QC-state-machine — bewuste grenzen, geen gaten:**
  - Alleen het data_health-oorsprong-triggersignaal wordt vertaald naar
    een `QualityStatus` voor de QC_PASSED/FAILED-beslissing — de vier
    1.3-checks zelf (completeness/validity/consistency/continuity)
    blijven ongewijzigd ONGEWIRED, zoals bij 1.3 afgesproken. Zodra één
    van de vier ooit gewired wordt, kan `decide_qc_outcome()` er zo bij.
  - `QualityStatus.DEGRADED` faalt een QC-case NIET automatisch (alleen
    zichtbaar via `qc_issues`) — een bewuste keuze om NEEDS_REVIEW niet
    te laten vollopen met bruikbare-maar-niet-perfecte gevallen, zie
    `docs/architecture.md` ("Ontwerpkeuzes") voor de volledige afweging.
  - Een `qc_case` wordt gekoppeld aan een deep-dive via een lookup op
    domein+status (meest recente TRIGGERED case), niet via een
    doorgegeven `case_id` — correct zolang een domein maximaal één open
    TRIGGERED case tegelijk heeft. Bij twee opeenvolgende
    `run_monitoring()`-triggers vóór de eerste deep-dive draait, pakt
    `run_deep_dive()` de MEEST RECENTE case; de oudere blijft voor altijd
    in TRIGGERED steken (geen automatische opruiming/samenvoeging
    gebouwd). Onwaarschijnlijk bij het huidige handmatige/on-demand-
    gebruik (zie "Open questions"), maar wordt relevanter zodra er een
    scheduler is die snel na elkaar kan draaien.
  - `archive_qc_case()` heeft geen enkele aanroeper — er is nog geen
    review-workflow/UI die 'm zou aanroepen. Cases die QC_PASSED of
    NEEDS_REVIEW bereiken, blijven daar dus vooralsnog staan (zichtbaar
    via `list_qc_cases()`, niet stilzwijgend verloren).

## Next priorities

**Herzien op 26-09-2026 — kritiek pad naar T₀, niet meer pijler-op-
volgorde.** Alles hieronder in strikte volgorde; `docs/roadmap.md` deel A
heeft de uitgebreide onderbouwing per fase.

1. **1.11 Scheduler & Runtime — code klaar, uitrollen open.**
   Gebouwd op 26-09-2026: `src/runtime/daily.py` (dagelijkse cyclus,
   foutisolatie per agent, opt-in deep-dives), `src/runtime/notifications.py`
   (fail-loud, kanaal-onafhankelijk), `run_daily.py` (cron-entrypoint),
   en `event_id` doorgezet in alle 5 monitor/deep_dive-wrappers — waarmee
   1.7's idempotency voor het eerst daadwerkelijk gebruikt wordt. 280
   tests groen (was 261).
   Nog te doen, en dat is geen codewerk:
   a. **VPS kiezen en uitrollen.** FRED/Alpha Vantage zijn hier 403 door
      de org-egress-policy; de code is provider-onafhankelijk en draait
      overal. Nodig op de machine: `FRED_API_KEY`,
      `ALPHAVANTAGE_API_KEY`, `MI_DB_PATH`, `MI_WEBHOOK_URL` en de
      cron-regel uit `run_daily.py`'s docstring.
   b. **Back-up van het SQLite-bestand.** Dat bestand *is* het track
      record; kwijtraken betekent dat de klok opnieuw begint.
   c. **Back-fill** ≥5 jaar per gemonitorde metric.
   d. **Per-domein cadans** — welke agent dagelijks, welke wekelijks. Was
      uitgesteld "tot er een scheduler is"; die is er nu.
2. **1.10 Causale graaf** — handwerk voor DD + partner, parallel aan 1.
   Sjabloon staat in `docs/causal-graph.md`. Levert daarna
   `src/contract/graph.py` op (knopen als enum).
3. **1.2 + 4.1 Predictions als entiteit en contract.** `predictions` stond
   onder 1.2 als "bewust nog niet nu" (pijler 4/5) — die grens is verlegd,
   want zonder deze tabel is er niets te scoren. Verplichte velden:
   `probability`, `resolution_rule`, `resolves_at`, `graph_node`,
   `trigger_version`.
4. **4.5 + 4.6 Scoring engine en baselines.** Resolver, Brier, log loss,
   kalibratiecurve, discrimination (AUC), plus random-walk en climatology
   als meedraaiende baselines.
5. **1.5 trigger-versioning + drempelkalibratie tegen de back-fill.**
   Versioning is kritiek pad: zonder versienummer is een kalibratie over
   een periode waarin een drempel verschoof niet te interpreteren. De
   overige 1.5-items (severity-model, regime-transitie- en
   cross-variable-triggertypes) zijn post-T₀.
6. **T₀ — streefdatum 10-11-2026.** Checklist staat in `docs/roadmap.md`.
   Vanaf dan zijn graaf, predictiecontract en resolution rules
   semi-bevroren; elke wijziging krijgt een versienummer en start een
   nieuw cohort.

Post-T₀, in volgorde van waarde (fase 4): economic agent (2.7, de graaf
heeft groei-knopen die niemand bedient), news monitor smal opgezet (2.8),
contradictie-detectie (3.1), kalibratiedashboard (5.2). Alle
Finetune-items en PCA (3.2) blijven bewust laag geprioriteerd tot de
kalibratie laat zien welk domein zwak is.

1.2's overige entiteiten (observations/entities/measurements/events/
expectations/evidence/deep_dives/syntheses) blijven BEWUST open, elk met
een vastgelegde reden — geen "nog te doen"-lijst, een bewuste grens.
`predictions` en `evaluations` vallen daar per 26-09-2026 niet meer
onder.

De daadwerkelijke koppeling voor C.1/2.3 (hoe een `analyst_agent.ai`-run
zijn output naar `AnalystAgentReport` vertaald krijgt) blijft zonder
concrete trigger — post-T₀.

## Open questions needing the project owner's input

- **[29-09] BLOKKEREND vóór `--deep-dives` aan gaat: cohort vóór T₀ᵇ.**
  Zie `docs/roadmap.md`, "Open beslissingen". `Prediction.cohort` staat hard
  op `cohort_0`; zonder ingreep worden de dry-run-voorspellingen van oktober
  het echte cohort, en dat is niet te herstellen (geen update-pad).

- **[28-09] `DTWEXBGS` → knoop `dollar`: uitgesteld tot na T₀ᵃ** (optie 3,
  besloten 28-09). Vraagt multi-provider-ondersteuning in
  `agents/base.py`; currency is in cohort 0 toch de controlegroep, dus
  deze knoop is daar het minst kritisch.

- **Waar draait de fetch-runner? — DD kiest een VPS (26-09-2026).**
  Richting bepaald; de concrete provider/instance moet nog besteld en
  ingericht worden. De code veronderstelt niets over de machine.
- **Domeinprioritering (continu vs. on-demand per domein) — komt nu
  terug.** Was bewust uitgesteld "tot er een scheduler is" (vastgelegd
  tijdens 1.6): geen scheduler, geen cadans-veld, ook geen stub, en
  daarom geeft geen enkele agent een `event_id` mee (1.7's idempotency
  bleef daardoor ongebruikt). Met 1.11 komt die scheduler er, dus de
  beslissing is weer aan de orde: welke agent draait dagelijks, welke
  wekelijks.
- **Hoeveel predictions per agent per week, en op welke graafknopen.**
  De richtlijn van ~5 per agent per week (horizonnen 5/21/63 dagen) komt
  uit de rekensom over statistische power in `docs/roadmap.md` fase 2, en
  is een startpunt, geen uitkomst.
- De illustratieve tolerance-waarden in B.1/B.2 worden vervangen door de
  drempelkalibratie tegen de back-fill (fase 0). Dat is nu ingepland en
  geen open vraag meer.
- ~~Prioritering ICT-trading (kort) vs. macro/mid-term (lang)~~ —
  **beslist op 26-09-2026**: dit systeem is de macro/mid-term-kant van
  TCE. Het verbetert DD's intraday-handel op MNQ niet en dat is geen
  doel; het kan hooguit de directionele bias en het risicobudget per dag
  kleuren, en zelfs dat pas nadat de scoring engine het aantoont. Zie
  "Scope-afbakening" in `docs/roadmap.md` deel A.
