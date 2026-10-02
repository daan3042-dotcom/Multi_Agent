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

**[30-09: opgelost] `FOMC_MEETING_DATES` was leeg, is nu gevuld.** Zie het
kopje "FOMC-kalender ingevuld" hieronder. De rest van deze alinea beschrijft
waarom hij tot dan bewust leeg was. De Fed publiceert de vergaderdata jaren
vooruit, maar ze waren vanuit deze ontwikkelomgeving niet te verifiëren en
een verkeerde datum wikkelt een voorspelling stilzwijgend op het verkeerde
moment af. Benaderen met "de n-de
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

### Cohort vóór T₀ᵇ: `MI_COHORT` (29-09) — 610 tests groen

`Prediction.cohort` stond hard op `cohort_0`. Zodra de wekelijkse ronde op
de VPS draaide, waren de voorspellingen van 5, 12, 19 en 26 oktober en 2 en
9 november als het ECHTE cohort opgeslagen — vóór de freeze van contract,
prompts en drempels. `predictions` heeft bewust geen update-pad, dus een
verkeerd label is definitief. Eén bestaande test (`test_prediction.py`) had
dat gedrag zelfs als "correct" vastgelegd, wat bevestigt dat het nooit
bewust was bedoeld.

**De oplossing:** `current_cohort()` leest `MI_COHORT`, met `dry_run` als
default. `Prediction.cohort` gebruikt die als `default_factory`, dus **één
plek beslist voor elke voorspeller** — de LLM-agents, de drie baselines en
later de menselijke invoer (4.8). Er is geen tweede plek die uit de pas kan
lopen; een test bewaakt dat agent en baseline in hetzelfde cohort landen,
want anders is er niets om ze mee te vergelijken.

**De veilige kant is de default.** Niets zetten geeft `dry_run`, nooit
`cohort_0`. Wat overblijft is de omgekeerde fout — vergeten om op T₀ᵇ te
schakelen — en die is zichtbaar (elke run logt het cohort) en herstelbaar
(de klok een dag later starten). De andere kant was dat niet.

**Een typefout is een fout.** `MI_COHORT=cohort0` zou bij een stille
terugval als `dry_run` worden weggeschreven, en juist op T₀ᵇ merk je dat
pas weken later. `run_daily.py` stopt daarom met exit 2 voor er iets
gebeurt, en `Prediction` weigert een onbekend cohort bij constructie.

**Teruglezen raadpleegt de omgeving niet.** Het cohort van een opgeslagen
rij staat vast; een wijziging van `MI_COHORT` op T₀ᵇ verandert geen oude
rijen. Een test bewijst dat.

**Dry-run wordt gewoon afgewikkeld.** Resolver en scores moeten in de
dry-run-week bewezen worden — dat is de bedoeling ervan. Alleen het label
scheidt die voorspellingen van het echte cohort.

**`tests/conftest.py`** haalt `MI_COHORT` uit de omgeving voor elke test.
Het deployment-runbook draait `pytest` vóór elke uitrol, en op T₀ᵇ staat
`cohort_0` dan in de omgeving van de VPS: zonder dit zouden tests daar
voorspellingen onder het echte cohort kunnen wegschrijven.

**Op T₀ᵇ is er één handeling van DD:** `MI_COHORT=cohort_0` in `.env`, na
de freeze, plus controle. Staat op de T₀ᵇ-checklist in de roadmap.

### Back-fill: gedeeltelijk mislukken kon stil (29-09) — 622 tests groen

Ontdekt vlak voordat de Alpha Vantage-helft zou draaien. De fetchers gaven bij
elke fout `[]`, ook bij Alpha Vantage's "limiet bereikt" of "premium endpoint" —
die komen als HTTP 200 met alleen een `Note`/`Information`-veld en zijn dus
gewoon een antwoord zonder tijdreeks. Een domein telde als geslaagd (exit 0)
zodra ÉÉN reeks data gaf, en omdat het script geen dedup had, was een
gedeeltelijke run niet bij te vullen zonder de gelukte reeksen dubbel op te
slaan. Zelfde patroon als 28-09, waar alle agents `success=1` meldden terwijl
er 6 van 24 reeksen binnenkwamen.

**Nu:** een fetch-fout is een `BackfillFetchError` met de tekst van de bron,
per reeks in de uitvoer. Een reeks met ≥20 claims ouder dan 30 dagen wordt
overgeslagen, dus opnieuw draaien is altijd veilig en vult alleen wat
ontbreekt. Elke reeks wordt apart en atomair opgeslagen. Exit 0 betekent nu:
elke gevraagde reeks heeft historie. Vier tests falen als het overslaan uitstaat.

**Bijvangst:** dit maakt het opnieuw draaien van de FRED-domeinen veilig en
nuttig. DGS2, T5YIE, T10YIE en WALCL zijn ná de eerste FRED-back-fill aan de
monetary agent toegevoegd en hebben dus nog geen historie; die worden nu
alsnog gevuld terwijl de rest wordt overgeslagen.

**Niet te verifiëren zonder de echte API:** of `TIME_SERIES_DAILY` met
`outputsize=full` in de betaalde tier van DD zit. Zo niet, dan zegt de uitvoer
dat nu met de tekst van Alpha Vantage in plaats van stil te falen.

### Weekenden telden als gemiste dagen (29-09) — 625 tests groen

`_missed_days` telde alle kalenderdagen, terwijl de cron alleen ma t/m vr draait.
Elk weekend zou als "dag zonder succesvolle run" zijn gemeld, als KRITIEKE melding,
bij elke run van ma t/m vr (het weekend blijft zeven dagen in beeld). Gevonden in
de eerste echte run op de VPS, die de dagen vóór de start van het systeem meldde.
Een alarm dat dagelijks afgaat wordt genegeerd, en dan is het ook onzichtbaar op de
dag dat er wél een run ontbreekt.

**Nu:** alleen dagen in `EXPECTED_RUN_WEEKDAYS` (ma t/m vr) tellen mee. Een test
leest de crontab-regel uit `docs/deployment.md` en faalt als de constante en de cron
uit de pas lopen. Een echt gat op een werkdag wordt nog steeds gemeld (aparte test).
Met het oude gedrag terug falen drie tests.

**De back-fill-timeout** is ook opgerekt naar 120 s: op de VPS duurde één simpele
Alpha Vantage-call 28 seconden. De dagelijkse agents hebben nog 15 s; of dat te krap
is, hangt van de latentiemeting op de VPS af (open).

### De eerste echte back-fill (29-09) — 632 tests groen

Gedraaid op de VPS met de betaalde Alpha Vantage-key. Resultaat, per domein:

| Domein | Uitkomst |
|---|---|
| monetary_policy | 4 nieuwe reeksen gevuld (DGS2 12.577, T5YIE 5.939, T10YIE 5.939, WALCL 1.241 claims); de andere 4 overgeslagen |
| financial, economic | alles al aanwezig, overgeslagen |
| currency | 3 × 5.000 claims |
| sector | 12 reeksen, 72.508 claims (9 ETF's sinds 1999, XLRE sinds 2015, XLC sinds 2018, SPY) |
| commodity | **10 van 10 mislukt** (zie onder) |

Het overslaan per reeks werkte zoals bedoeld: de FRED-domeinen zijn niet dubbel
gevuld, en alleen de vier nieuwe monetary-reeksen zijn opgehaald.

**Commodity mislukte, en de melding zei niet waarom.** De back-fill hergebruikte
`commodity_agent._fetch_commodity_data`, en die geeft bij elke fout `None`. De
melding was 'reden onbekend'. Alle tien faalden binnen 2 seconden, dus het was geen
timeout. Nu heeft de back-fill een eigen fetch (`fetch_av_commodity_full_history`)
met de tekst van Alpha Vantage in de uitvoer en de lange timeout. De werkelijke
oorzaak is nog niet vastgesteld: eerst opnieuw draaien en de melding lezen.

**Een beveiligingsprobleem dat ik zelf had geïntroduceerd, en vond vóór het
gebeurde:** `requests` zet de VOLLEDIGE url, query inclusief, in zijn foutmeldingen
(`... for url: https://...&apikey=<KEY>`). Mijn `BackfillFetchError` gaf die tekst
ongefilterd door, dus bij een netwerk- of HTTP-fout had de uitvoer van het script
je API-key bevat, en daarmee elk log en elke chat waar die uitvoer in geplakt werd.
Nu vervangt `redact_secrets()` elke `apikey=`/`api_key=`-waarde door `<verborgen>`.
Drie tests (netwerkfout, HTTP-fout, de echte CLI-uitvoer) falen zonder de redactie.

**Overslaan is nu per (domein, reeks).** `unemployment_rate` staat bij zowel
monetary_policy als economic, en elk domein leest zijn eigen claims voor de
delta-trigger. Alleen op reeks kijken zou een domein zonder historie overslaan
omdat het andere er wél een heeft.

**Een gegeven om te kennen: `high_yield_credit_spread` heeft maar 768
waarnemingen**, ongeveer precies drie jaar aan werkdagen. Alle andere dagreeksen
hebben tientallen jaren. Ik heb niet kunnen verifiëren waarom; het lijkt een
begrenzing van de bron (FRED beperkt de ICE BofA-reeksen tot een recent venster),
maar dat is een aanname. Gevolg: de drempelkalibratie (1.5/4.2) voor die reeks ziet
alleen een rustige periode zonder 2008 of 2020, en de DoD "macro ≥ 20 jaar" is
voor deze reeks niet te halen via FRED. **Checkpoint 4.**

### Evidence-sheet: de agent krijgt berekende context (2.0/4.1, 01-10, optie B) — 903 tests groen

**Besluit DD:** de agent krijgt meer dan het laatste getal ("beter voor de toekomst van de agent"). `scoring/evidence_sheet.py::build_evidence_sheet(conn, targets, claims, as_of)` is een zuivere
functie (geen LLM, alleen lezen) die per reeks de ouderdom, de verandering over 1 en 3 maanden, het 52-wekenbereik en per kwantieldoel en horizon de standaarddeviatie van de verandering geeft (laatste 5 jaar en
laatste jaar), en voor de FOMC-doelen de laatste en recente veranderingen plus de komende besluitdagen. Hergebruikt `baselines._history/_sample`, dus **dezelfde vensters en dezelfde point-in-time-regel**
als de persistence-baseline en de resolutie. Vier voorzorgen: (1) **geen kant-en-klare kwantielen** (zou kopiëren uitnodigen; een test bewaakt dat er geen "q10", "kwantiel" of "mediaan" in staat);
(2) point-in-time, getest met toekomstige en later-gezien waarnemingen; (3) ontbrekende of verouderde data wordt benoemd (nooit stil weggelaten); (4) een fout bij het bouwen breekt de ronde van die
agent zichtbaar af, zodat niemand stilletjes blind voorspelt. `FORECAST_SYSTEM_RULES` kreeg regel 6 (gebruik de context; wijk alleen af met reden), zonder omrekentabel naar kwantielen; **prompt v3** voor alle vijf agents.
Gecontroleerd dat de tests falen bij een bewuste fout (verkeerd venster, point-in-time uit, kwantielen in de tekst).
**Onzeker/ongetest:** nooit met echte data of een echt model; de keuze van de velden is van mij en moet door DD beoordeeld worden aan de hand van een echte prompt uit `llm_calls`; of het model de spreiding
daadwerkelijk gebruikt, is de eerste meting van de testrun. **Bewust niet:** releasekalender van CPI en banen (bestaat niet), FOMC-uitkomsten van vóór oktober 2026, historische kans op een verhoging per vergadering.
**Gevolg voor de vergelijking:** de agent en de baselines krijgen nu vergelijkbare informatie; een nieuwe (kleine) vorm van lekkage is dat de agent de spreiding kent die de persistence-baseline ook gebruikt, dat is de bedoeling.

### BUG gevonden vóór de eerste echte ronde: de forecast-prompt bevatte de volledige historie (2.0/1.11, 01-10) — 882 tests groen

**Wat.** `runtime/daily.py::_run_forecast_round` gebruikte `load_latest_claims(conn, domain)`. Die functie geeft ondanks zijn naam de VOLLEDIGE claims-historie van het domein
terug (de trigger-laag heeft dat nodig; de docstring waarschuwt er zelf voor). De deep-dive gebruikt wel de juiste (`load_monitoring_claims`, alleen de laatste cyclus). Tot de
back-fill van 29-09 viel dit niet op: er was weinig historie. Met de back-fill is de monetary-prompt naar schatting ~51.000 claims, ~4 miljoen tekens, ruim 1,3 miljoen tokens: **te
groot voor het contextvenster van 1 miljoen**, dus elke ronde zou zijn mislukt (zichtbaar, geen kosten), en als het wel paste ~$2,70 per aanroep. Nooit gebeurd: `--deep-dives` staat nog niet aan.
**Mijn eerdere uitleg ("de agent krijgt alleen de laatste waarde per reeks") was dus onjuist voor de code zoals die stond; ze klopt pas sinds deze reparatie.**

**Reparatie.** `load_monitoring_claims` (laatste cyclus). Regressietest met een back-fill van 400 oude claims: de prompt moet precies één regel per reeks bevatten (met de oude code: 401).
**Tweede vangrail:** `MeteredClient` weigert een verzoek groter dan `MAX_VERZOEK_TEKENS` (100.000 tekens; een normaal verzoek is 5.000 tot 15.000) met `VerzoekTeGroot`, zichtbaar en vóór er iets is uitgegeven;
de maandrem ziet zo'n verzoek niet aankomen. Verhoogbaar zodra een rijkere evidence-sheet dat bewust nodig maakt.
**Les:** de tests gebruikten kleine databases. Een test met een realistisch gevulde database (back-fill) had dit vroeger gevangen; die staat er nu.

### Ruw LLM-logboek en Sonnet 5.5 (1.2/1.11, 01-10) — 880 tests groen

**Logboek (`llm_calls`, onveranderlijk).** `MeteredClient` legt bij elke LLM-aanroep het volledige verzoek (alle parameters, geen sleutel) en het
antwoord (tekst, stop_reason, tokens) of de fout vast, met agent, doel en event-id via `client.context(...)`; `agents/base.py` zet dat voor de
forecast-ronde, de deep-dive en de QC-review. Een mislukte schrijfactie kost het antwoord niet en laat de run niet crashen maar wordt als ERROR gelogd; er is
geen regel als de maandrem de aanroep tegenhoudt. `list_llm_calls` leest het terug. Een nieuwe tabel: geen migratie.

**Model: `claude-sonnet-5-5` (besluit DD).** Geverifieerd via de naslag: bestaat, $2/$10, 1M context. Gevonden gevaar: **denken staat daar standaard aan** en telt mee in
onze kleine `max_tokens`; zonder maatregel zouden antwoorden leeg of afgekapt kunnen komen en de QC-review stil verzwakken. Opgelost centraal in `MeteredClient`
(`thinking={"type": "between_tools"}`, alleen voor dit model; op 4.6 zou het een 400 zijn), dus `src/qc/` is NIET gewijzigd (checkpoint 2); de QC-review krijgt het model
via de bestaande `model`-parameter. `DEFAULT_DEEP_DIVE_MODEL` staat nu los in `base.py`. Kostenschatting bijgewerkt (~$0,10 tot $0,17 per week, met denken uit).
**Niet getest tegen de echte API:** modeltoegang van het account, en of de geïnstalleerde `anthropic`-versie `between_tools` doorgeeft (faalt zichtbaar). Denken aan voor de
forecast-ronde is een experiment voor de testrun. De kennisgrens juni 2026 is bevestigd in het Anthropic-modeloverzicht (01-10); uittreding niet eerder dan 28-09-2027.
**node_state uitgesteld (DD):** vastgelegd in de roadmap (1.2) met de twee ontwerpopties en de prijs van uitstel; niet gebouwd.

### Vijf kwantielen, optie B (4.1/4.5, 01-10) — 867 tests groen

**Besluit (DD):** niveaus .10 .25 .50 .75 .90. DD koos eerst zeven (optie D) en draaide dat terug naar vijf (optie B). De D-keuze was alleen
documentatie (geen code); die is met een `git revert` ongedaan gemaakt (commit fe0b2e4), en B is daarna van nul opgebouwd. Contract v0 -> v1.

**Wat er is veranderd:** `QUANTILE_LEVELS`/`QUANTILE_FIELDS` in `contract/prediction.py` als enige bron (prompt, validatie, scoring, baselines en
kalibratie lezen ze); `Prediction` met `q25` en `q75` en een middenkruising-controle; schema met vijf kolommen en CHECK-constraints (ook `evaluations`:
`pinball_q25`, `pinball_q75`); `scoring/scores.py` v2 (`pinball_losses(kwantielen, y)`, CRPS = 2 × gemiddelde pinball, geweigerd bij een verkeerd
aantal); `baselines.py` v2 (persistence en climatology op vijf niveaus), `ridge.py` v2 (residu-kwantielen op vijf niveaus; een bevroren model met een
ander aantal wordt niet geladen); `agents/base.py` (regel 2 van `FORECAST_SYSTEM_RULES`, JSON-vorm, parser) en `FORECAST_PROMPT_VERSION` v1 -> v2 voor alle vijf
agents (hashes in `test_forecast_prompt_version.py`); `diagnostics.py` en het rapport (zes gebieden, verwacht 10/15/25/25/15/10%, plus binnen q25-q75 en q10-q90).

**De migratie van een bestaande database (het risicovolste deel, `_migreer_predictions_kwantielen`).** `init_db` draait elke ochtend, dus een crash daar raakt T₀ᵃ.
Lege `predictions` en `evaluations` worden vervangen door de nieuwe vorm. Staan er rijen in, dan worden beide tabellen NIET weggegooid en NIET gerepareerd maar
hernoemd naar `predictions_legacy_v0` en `evaluations_legacy_v0` (indexen losgekoppeld, vreemde sleutel volgt de hernoeming), met een warning. Dit wijkt bewust af van
de eerdere migratie voor `resolution_method`, die hard weigert en daarmee de dagelijkse run zou laten crashen. Getest tegen de EXACTE oude tabelvorm uit git
(`tests/test_quantile_migration.py`): leeg, met rijen, idempotent, nieuwe voorspellingen en uitkomsten werken erna, de indexen horen bij de nieuwe tabellen.

**Gemeten voor de keuze van de CRPS-weging** (synthetisch, voorspeller die de echte verdeling kent): gelijk gewogen over vijf niveaus 1,9% (normaal) en 0,7% (dikke
staarten) onder de echte CRPS; weging naar kansbreedte 2,1 en 2,5% erboven; trapezium 4,1 en 4,5% eronder. Gelijk gewogen is dus de dichtste en de eenvoudigste, en is
niet veranderd. Voor drie niveaus was het ~11% en voor zeven gelijk gewogen 16 tot 19% te laag. De rangorde van voorspellers was bij elke keuze gelijk.

**Ongetest/onzeker:** of een taalmodel vijf kwantielen betrouwbaar en gekalibreerd uitspreekt (nog nooit gemeten; de begeleide `--deep-dives`-testrun is de eerste echte
meting; meer dan 5% afgewezen kruisingen is het signaal om te heroverwegen); de migratie is niet op de echte VPS-database gedraaid (alleen tegen de oude tabelvorm uit git).
Staartrisico's (q05/q95) zijn bewust niet vastgelegd. **Op de VPS vóór het uitrollen:** `SELECT COUNT(*) FROM predictions;` (verwacht 0). Is het meer dan 0, dan werkt de migratie
nog steeds, maar de rijen belanden in de legacy-tabellen. **Dit is een contractwijziging en dus een freeze-item (checkpoint 5), vóór de eerste echte voorspelling.**

### SPY-bron: eerste meting van het verversmoment (02-10, 12:13 UTC)

`as_of=2026-10-01`, `Last-Modified` 02-10 **10:15:20 GMT**: de bron plaatst het bestand van gisteren om ~10:15 UTC, ná de archief-cron van 08:30 UTC. Het archief loopt daardoor één dag achter, maar verliest niets zolang de bron één keer per werkdag rond dat uur ververst (de cron valt dan steeds in het venster van het bestand van de vorige werkdag). Risico aan de vroege kant: publiceert de bron vóór 08:30 UTC, dan wordt het bestand van de dag ervoor nooit bewaard; de cron dus niet later zetten. **Eén meetpunt**: de uurlijkse meting tot maandag 5 oktober 12:00 UTC (voorstel, nog niet geïnstalleerd) moet de schommeling en het weekendgedrag laten zien. Zie `docs/deployment.md`.

### SPY-bron: meetscript voor het verversmoment (02-10) — 982 tests groen

`meet_spy_asof.py` + `src/archive/spy_meting.py` (alleen lezen, schrijft niets): één regel met `as_of`, grootte, vingerafdruk en de koppen `Last-Modified`/`ETag`/`Date`, om te meten op welk uur de bron een nieuwe `as_of` toont (`archive_daily.py` archiveert maximaal één keer per UTC-dag en kan dat niet). **Voorstel (checkpoint 3, door DD te bevestigen):** drie dagen lang elk uur via een tijdelijke cron-regel; staat in `docs/deployment.md`, niet geïnstalleerd. 6 tests; vier mutaties gevangen. Een test vond onderweg dat de standaard-`get` te vroeg werd vastgelegd (een test haalde echt het netwerk op); dat is nu bij het aanroepen opgezocht.

### T₀ᵃ verschoven naar op zijn vroegst 13 oktober (02-10) — de bestaande regel, geen nieuwe beslissing

De run van 02-10 (dag 1 van de herstarte telling) was `ok` voor alle zes agents maar niet compleet: sector 11 van 12 reeksen, `xlp_consumer_staples` ontbrak. Met de definitie van 01-10 staat de teller dan op nul en begint de nieuwe telling op maandag 05-10: zeven schone werkdagen zijn op zijn vroegst vol op **dinsdag 13 oktober** (`t0a_status.py` rekent dit uit). Mee verschoven (voorstellen, door DD te bevestigen): de `--deep-dives`-testrun naar woensdag 14 oktober en de cron met `--deep-dives` naar donderdag 15 oktober; de drie begeleide weken lopen dan tot 5 november en overlappen de dry-run-week nog steeds. Aangepast in CLAUDE.md, roadmap (tabel Herzieningen, deel A, 1.11), `roadmap.html` en `docs/deployment.md`.
**Risico, niet te negeren:** er zijn op vier van de vijf dagen sinds 28-09 Alpha Vantage-gaten geweest (28-09, 29-09, 01-10 en 02-10; alleen 30-09 was compleet). Zonder dat de herhaalpoging helpt kan de reeks van zeven schone dagen lang uitblijven. De datum is dus echt "op zijn vroegst".

### DD's besluiten over de graaf (1.10, 02-10) — alleen documentatie

DD beantwoordde de acht vragen (`docs/causal-graph-vergelijking.md` §9–10): `nonfarm_payrolls` hoort bij `labor_market` (verandert bij v1 de doelenlijst); voorwaarden blijven tekst tot ze meetbaar zijn; aandelen worden een knoop; D1, D10 en C6 worden gesplitst en A3a/A3b blijven twee pijlen met een `kanaal`-label (nieuw veld); C8/C9 gaan buiten de graaf en worden tekst bij de agents; alle tien knopen zonder reeks blijven in v1 als "uitgesteld in cohort 0" (welke later een reeks krijgen valt onder "reeksenlijst definitief"); en de "hoog"-definities per knoop zijn goedgekeurd. `sentiment_flows` (drie tegenstrijdige betekenissen in D7, C7 en D8) wordt twee knopen: `sentiment` (hoog = positiever) en `stress_gedwongen_verkoop` (hoog = meer stress); 24 knopen, elf zonder reeks. **Open:** of vier v0-knopen bewust ontbreken (DD weet het niet; het concept komt uit een interview met Claude Fable 5.1) en de blinde versie van de partner (9 oktober). Niets in de code gewijzigd.

### DD's causale graaf ontvangen en naast v0 gelegd (1.10, 02-10) — alleen documentatie

DD leverde zijn graafconcept aan (`docs/causal-graph-dd-concept.md`, ongewijzigde kopie: 23 knopen, 39 pijlrijen, voorwaardelijke pijlen, regels voor agents, open punten voor de partner). **Vergelijking:** `docs/causal-graph-vergelijking.md`. Kern: het is een graaf van mechanismen uit drie episodes en dus rijker maar minder meetbaar dan v0 (tien van de 23 knopen hebben geen reeks bij ons; 19 van ~42 pijlen hebben aan beide kanten een reeks die we al ophalen); knopen zijn samengevoegd (inflatie, kredietcondities, grondstoffen), gesplitst (risicobereidheid → `tail_uncertainty` + `sentiment_flows`, met omgekeerde as) of nieuw (negen); het document mist per knoop wat "hoog" betekent, dus het teken is niet eenduidig; de voorwaarden zijn tekst en nog geen meetbaar getal. **Correctie op mijn eerdere uitspraak:** 13 doelen dragen een `graph_node` (ik schreef tien). Niets in de code gewijzigd; v1 en `TARGETS_VERSION` v2 volgen in één keer na de blinde versie van de partner (9 oktober). Acht vragen staan klaar voor DD.

### Trigger-versie v4: vijf sector-drempels gecorrigeerd voor de splitsing (1.5, 02-10) — 1046 tests groen

**Besluit DD (02-10), na de vergelijking van `calibrate_triggers.py --vergelijk-splitsingen` op de echte database.** Op de gecorrigeerde reeks vuurden de oude drempels van XLB, XLE, XLK, XLU en XLY 0,7 / 1,7 / 1,0 / 0,7 / 0,3 keer per jaar in plaats van ~5 (ze waren op de koersen van vóór de splitsing gekalibreerd, toen een gewone beweging in dollars dubbel zo groot was). **Nieuwe drempels** (de 5-per-jaar-drempel op de gecorrigeerde laatste drie jaar, afgerond op één decimaal): XLK 8,9 → 5,4, XLE 2,6 → 1,6, XLY 6,2 → 3,2, XLB 2,0 → 1,2, XLU 1,8 → 1,0; als percentage van de koers 2,4 tot 3,0% (XLF en XLI ~2%). `TRIGGER_VERSION` v4, vingerafdruk `26f1dcf7937e4f86`.
**Niet gewijzigd:** `src/triggers/`, `src/qc/`, de andere zes sector-ETF's, SPY en alle andere agents. **Getest:** de vingerafdruk-test dwong de versie af; een test die de pin op "v3" hardcodeerde gebruikt nu de huidige versie. **Niet bevestigd:** het aantal triggers per jaar na de wijziging is afgeleid uit het rapport, niet gemeten; `calibrate_triggers.py --domain sector` op de VPS bevestigt het (verwacht 4 tot 6 per jaar voor de vijf). Verwachte extra triggers: ~20 per jaar uit sector. De T₀ᵃ-teller meldt de wissel als LET OP; een niet-schone dag is het niet.
**Idee van DD vastgelegd (roadmap 4.2):** een volatiliteitsgebonden drempel (N keer de gemiddelde dagbeweging over 30 dagen), met de vijf punten die eerst uitgezocht moeten worden. Niet gebouwd; hoort bij het herzieningsmoment na T₀+6 maanden.

### Aandelensplitsingen in de ETF-reeksen: correctie, waakhond en vergelijking (1.5/4.5, 02-10) — 1045 tests groen

**Gevonden** via de pseudo-OOS-prompt en bevestigd met een alleen-lezen controle van DD: XLB, XLE, XLK, XLU en XLY halveerden op 2025-12-05 (verhoudingen 0,495-0,504) door een 2-voor-1-splitsing in een niet-gecorrigeerde reeks (`TIME_SERIES_DAILY`); geen andere ETF, SPY niet.
**Gebouwd:** `contract/corporate_actions.py` (expliciete lijst `SPLITSINGEN`, vooraf delen door de verhouding; alleen aan het eind aanvullen), toegepast in `scoring/resolver.py::observations_for`, het ene leespad voor evidence-sheet, baselines, ridge, resolver en kalibratie (`corrigeer_splitsingen=False` geeft de ruwe reeks). `runtime/split_waakhond.py`: onverklaarde sprong (>~35%), afwijkende verhouding, onbevestigde splitsing; als logregel in elke dagelijkse run (een fout laat de run nooit mislukken) en als rij in `freeze_status.py`. Baseline-versie v2 -> v3. `calibrate_triggers.py` kreeg `--ongecorrigeerd` en `--vergelijk-splitsingen`.
**Bewust niet gewijzigd:** de ruwe claims, `src/triggers/`, `src/qc/`, de triggerdrempels en `TRIGGER_VERSION` (de vingerafdruk is gelijk gebleven). De sectordrempels (absolute prijsverschillen, op de ongecorrigeerde historie gekalibreerd; XLK 8,9 en XLY 6,2 zijn ~5% van de koers) zijn mogelijk te grof: dat is **DD's beslissing** na de vergelijking (checkpoint 2 en 5).
**Getest:** 24 nieuwe tests tegen een bron-database met een echte halvering (de reeks wordt doorlopend, de ruwe claims blijven ruw, de spreiding in de evidence-sheet is niet meer opgeblazen, een voorspelling over de splitsingsdatum wordt op het echte rendement afgerekend, de waakhond vangt een nieuwe, een afwijkende en een onbevestigde splitsing en meldt een gewone crashdag niet, de run logt en crasht niet); negen mutaties gevangen. Een bestaande test pinde `baseline-v2` en is op v3 gezet.
**Niet gedraaid tegen de echte database.** Cosmetische beperking: de correctie kent de toekomst (voor een `as_of` van vóór de splitsing zijn oude niveaus al in nieuwe aandelen); alle huidige runs liggen erna. Live geeft een splitsing één valse trigger op de dag zelf (de trigger-engine ziet de ruwe koers).

### Pseudo-OOS-run: harness gebouwd (roadmap 4.4, 02-10) — 1018 tests groen, echte run nog niet gedraaid

**Gebouwd:** `pseudo_oos.py` (CLI: voorbereiden, audit, prompt, schatting, draaien, afwikkelen, rapport) en `src/scoring/pseudo_oos.py`. De run draait op een KOPIE van de database, waarin
`analysis_time` van de back-fill-claims is verschoven met een aangenomen publicatievertraging per reeks, zodat de bestaande point-in-time-code (evidence-sheet, baselines, resolver) het verleden
eerlijk ziet; de echte database wordt alleen gelezen. Dertien maandagen (6 juli t/m 28 september), vijf agents, persistence en climatology als baselines, **geen ridge**. `claims_op_datum` geeft per reeks de laatste op die datum
bekende waarneming. De run weigert te starten zonder voorbereide kopie, en zonder FOMC-besluitdagen die het venster dekken. Een kostenschatting uit de echte promptlengtes komt vóór elke betaalde stap; draaien zonder `--ja` is een droge run.
**Gevonden onderweg (checkpoint 4):** de back-fill zet `first_seen` gelijk aan de waarnemingsdatum, dus zonder correctie lekt de publicatievertraging (een maandcijfer van 1 juli is op 6 juli "zichtbaar"). De vertragingen zijn mijn inschatting en niet te verifiëren; ze zijn conservatief.
`freeze_status.py` ziet de kopie (`pseudo_oos.db` naast de echte database).
**Getest:** 33 tests tegen een bron-database met alle reeksen van de vijf agents (dag-, week- en maandfrequentie, waarnemingen na het venster, een planted piek); tien mutaties getest; twee overleefden eerst (waarnemingsdatum en ridge) en kregen een eigen test, daarna zijn alle gevangen (geen verschuiving, dagvertraging 0, te korte maandvertraging, claims negeren `first_seen` of waarnemingsdatum, geen FOMC-controle, cohort niet gezet, geen voorbereidcheck, ridge doet mee, live claims verschoven). **Niet gedraaid tegen de echte database of het echte model.**
**FOMC-besluitdagen (02-10 opgelost):** 29 juli en 16 september 2026 staan in `FOMC_MEETING_DATES`, op basis van de twee FOMC-persberichten die DD als PDF aanleverde (juli: ongewijzigd op 3,50-3,75; september: verhoogd naar 3,75-4,00). Geverifieerd met die documenten, niet met de kalenderpagina zelf. **Gevonden bij de eerste `audit` op de echte database (02-10):** `fed_funds_rate` is FEDFUNDS, een maandgemiddelde, en stond op 1 dag vertraging; op 6 juli was de julistand zichtbaar. Hersteld (35 dagen) én `voorbereiden` toetst voortaan elke vertraging aan de werkelijke frequentie in de data (3 tests, 3 mutaties gevangen), zodat zo'n aanname niet meer stil fout kan staan. De overige 29 reeksen kloppen met de publicatiekalender (payrolls en CPI zijn conservatiever dan de werkelijkheid: de junicijfers verschenen op 2 juli en 14 juli, wij tonen ze later). Een kopie van vóór de correctie moet opnieuw worden gemaakt.
**Open (DD):** akkoord op de aangenomen vertragingen; de tweede run over 2025 bewust uitgesteld. Plan en stappen: `docs/deployment.md`.

### Alpha Vantage: reden loggen en één herhaalpoging (1.11, 02-10) — 976 tests groen

**Aanleiding.** De eerste T₀ᵃ-dag (02-10) was niet schoon: 11 van de 12 sectorreeksen, `xlp_consumer_staples` ontbrak (zie ook `t0a_status.py`, dat de teller op 0 zet; streefdatum nu 13-10, zie hieronder). Het log zei niet waarom: `_fetch_quote`/`_fetch_pair`/`_fetch_commodity_data` vingen elke fout stil op.
**Gebouwd (`src/sources/alpha_vantage.py`, nieuw; sector/currency/commodity gebruiken het):** `haal_json` geeft bij mislukking een reden (time-out, verbindingsfout, HTTP-status, Alpha Vantage's eigen "Note"/"Information"/"Error Message", lege respons, ongeldige JSON); `verzamel` haalt alles op, logt elke mislukking en probeert wat ontbrak één keer opnieuw na één gezamenlijke pauze van 30 s. **De sleutel komt nooit in het log** (van een uitzondering alleen het type; in Alpha Vantage's tekst wordt de sleutel vervangen). Completeness-check, `src/triggers/` en `src/qc/` zijn niet aangeraakt; `TRIGGER_VERSION` blijft v3 (test bewijst dat de vingerafdruk gelijk is).
**Getest:** 26 nieuwe tests (`tests/test_alpha_vantage.py`) tegen de echte aanroep-keten tot `requests.get`, inclusief het echte geval (XLP ontbreekt, herstel bij herhaling) en het geval waarin het gat blijft (nog steeds een volledigheidstrigger). Zeven mutaties (geen herhaling, twee keer, pauze op een goede dag, sleutel in het log, geen maskering, geen pauze, alles opnieuw proberen) zijn allemaal gevangen. `tests/conftest.py` vervangt de pauze, zodat geen test echt wacht. In de bestaande agent-tests is `sa.requests.get` nu `requests.get` (de ongebruikte `requests`-import is uit de agents gehaald).
**Niet bekend / niet getest:** de oorzaak van het gat; het gedrag tegen de echte Alpha Vantage (nooit gedraaid); of 30 s pauze genoeg is bij een minutenlimiet. Dry-run-plan: `docs/deployment.md`.

### Voorwaarden vóór de klok in het freeze-overzicht (roadmap T₀ᵇ-checklist, 02-10) — 950 tests groen

`freeze_status.py` heeft een tweede blok, **"Voorwaarden vóór de klok"** (`src/runtime/freeze_voorwaarden.py`, alleen lezen, `mode=ro`): T₀ᵃ en 14 werkdagen op rij zonder handmatige actie (uit dezelfde dagbeoordeling als `t0a_status.py`), begeleide deep-dive-testrun en forecast-rondes (uit `llm_calls`/`agent_runs`; meer dan 5% gemiste voorspellingen = LET OP), resolver (incl. release-horizon), pseudo-OOS-run, dry-run-week (27-10 t/m 09-11, constante), reeksenlijst (onbediende graafknopen: economic `wage_growth`/`inflation_persistence` bewust post-T₀, equity `equity_valuation` buiten het cohort) en de drie punten die de data niet kan bewijzen (back-up-herstel, heartbeat-test, API-quota). **AF is alleen mogelijk voor T₀ᵃ en de 14 werkdagen**; al het andere is NOG NIET AF of ZELF CONTROLEREN. Acht mutaties (grenzen, cohort, onafwikkelbaar, AF-status) zijn door de tests gevangen. **Niet getest tegen de echte VPS-database.**

### Freeze-overzicht en waakhond (roadmap T₀ᵇ-checklist, 01-10) — 926 tests groen

**`freeze_status.py` (alleen lezen)** toont alle freeze-punten met huidige waarde en status; voert de freeze niet uit (geen pin, geen ridge-freeze, geen `MI_COHORT`). **Waakhond:** doelenlijst (`TARGETS_VERSION v1`, afdruk `52b89e72c6ea2743`) en evidence-sheet (`EVIDENCE_SHEET_VERSION v1`, `94e8923819c07998`) dragen versienummer + vingerafdruk (`contract/freeze_versions.py`, `runtime/freeze_guard.py`). De prompt-afdruk bevat nu de evidence-sheet, dus de vijf `FORECAST_PROMPT_VERSION`-afdrukken in `test_forecast_prompt_version.py` zijn vernieuwd (versies blijven v3, niets gewijzigd voor de agents). Mutatietests bewezen: een wijziging in evidence-sheet-tekst of een resolutieregel laat de tests falen.

### T₀ᵃ-teller, roadmap.html en probe-advies (1.11, 01-10) — 842 tests groen

**`t0a_status.py` + `src/runtime/t0a_status.py` (alleen lezen, database `mode=ro`).** Rekent uit `agent_runs` en `trigger_events` per werkdag
vanaf 02-10 uit of die schoon was (alle zes agents `ok` én geen volledigheidstrigger), de lopende reeks, en de vroegste datum voor T₀ᵃ. Een dag
zonder run is "GEEN RUN" en breekt de reeks; vandaag-nog-niet-gedraaid breekt niets; eenmaal gehaald blijft gehaald. Markeert een run buiten
het cron-venster als "mogelijk handmatig" (vermoeden, telt niet als niet-schoon) en een wisselende trigger-versie. De lijst van zes agents komt uit
`runtime.daily.default_agents()`. **Kan niet bewijzen dat er geen handmatige actie was; nog nooit gedraaid op de echte database.**
**`docs/roadmap.html`:** T₀ᵃ op zijn vroegst 12 oktober met de nieuwe definitie, `t0-8` (synthesizer nog niet, menselijke invoer op pauze) en
een nieuw punt `t0-14` voor de reeksenlijst; alle bestaande ID's gelijk, dus afvinkingen blijven staan; de JavaScript is syntactisch gecontroleerd.
**Probe-advies:** "nog niet onderzocht" (Atlanta Fed, regionale Fed-enquêtes) is nu "eerst uitzoeken", Yahoo "bewust niet"; betaald blijft "beslissing DD".

### Kalibratie, AUC en effectieve n (4.5, 01-10) — 826 tests groen

Nieuw: `src/scoring/diagnostics.py` (zuivere rekenregels, alleen stdlib, vaste seed), `src/scoring/evaluation_report.py`
(leest `evaluations` + `predictions`, schrijft niets) en `evaluate_scores.py` (opent de database `mode=ro`; een test bewijst dat
het bestand ongewijzigd blijft). **Cohorten en soorten (kwantiel/binair) staan altijd in aparte regels**: CRPS en Brier liggen op
andere schalen, en `dry_run`, `pseudo_oos` en `cohort_0` mogen nooit gemiddeld worden. Per groep: n, n_eff, hoofdscore met 90%-band,
kalibratie (kwantiel: waar de uitkomst viel; binair: voorspeld versus gebeurd per klasse) en AUC.
**Effectieve n:** rondegemiddelden, moving-block bootstrap met blokken van `horizon / afstand tussen rondes`, ontwerpeffect =
variantie met blokken gedeeld door variantie zonder; n_eff = n / ontwerpeffect, nooit boven nominaal. Een test bewijst het punt:
een gladde (overlappende) reeks geeft minder dan de helft van de effectieve n van witte ruis. **Bewust eerlijk bij weinig data:** onder
8 rondes of twee blokken is `n_effective=None` en staat er "NIET BETROUWBAAR", want een getal dat vertrouwen wekt zonder grond is erger
dan geen getal. AUC is `None` bij één soort uitkomst (de Fed verhoogt zelden, dus lang is er geen enkele "gebeurd").
**Onzeker/ongetest:** nog nooit gedraaid op echte afgewikkelde voorspellingen (die bestaan pas na de eerste horizon, 5 handelsdagen na
de eerste ronde); de bootstrap is getest op synthetische data. Eén blokgrootte per groep is een vereenvoudiging bij gemengde horizonnen.
**Bewust niet gedaan:** skill-posterior (heeft een vooraf vastgelegde prior nodig: freeze-item, DD), uitsplitsing per horizon en
`model_id`, dashboard (5.2). Raakt geen cron, geen trigger, geen QC, geen `run_daily.py`.

### T₀ᵃ verschoven naar op zijn vroegst 12 oktober (01-10) — checkpoint 4

De run van 01-10 was `ok` voor alle zes agents maar niet compleet: sector kreeg 10 van de 12 reeksen (`spy_benchmark`,
`xlp_consumer_staples` ontbraken; Alpha Vantage, oorzaak onbekend, zelfde bron als de gaten van 28-09 en 29-09). De roadmap
definieerde "schone dag" nergens. **DD koos de strenge definitie:** alle agents `ok` én geen volledigheidstrigger. Daarmee
telde 29-09 en 30-09 mee, 01-10 niet, en herstart de telling op 02-10: zeven schone werkdagen zijn op zijn vroegst vol op
maandag 12 oktober. Mijn eerdere schatting "een dag opschuiven, donderdag 8 oktober" was fout: een niet-schone dag schuift niets
op, hij zet de teller op nul. De datums van de `--deep-dives`-testrun (13 oktober) en de cron (14 oktober) schuiven mee en de
begeleide periode overlapt nu de dry-run-week; zie `docs/deployment.md` (voorstel, door DD te bevestigen).
**Risico:** elke volgende niet-schone dag verschuift T₀ᵃ opnieuw. Alpha Vantage gaf op 3 van de 4 dagen sinds 28-09 gaten.
Een herhaalpoging per ontbrekende reeks binnen dezelfde run zou dat verkleinen, maar het is een wijziging aan het onbeheerde
draaien (checkpoint 3) en is nog niet voorgesteld in detail.

### Probe-uitkomst, DFEDTARU voor de FOMC-doelen en het SPY-archief (1.2/1.4, 4.5, 01-10) — 805 tests groen

**Probe gedraaid op de VPS** (66 aanroepen, geen fouten, 0 sleutels in de uitvoer). Uitkomst en kanttekeningen
(ICE BofA-spreads maar drie jaar op FRED; nieuws "leeg" is geen bewijs; realtime-opties een zwakke meting) staan in
`docs/data-archive.md`, "Uitkomst van de probe op de VPS".

**DFEDTARU voor de FOMC-doelen (roadmap 4.5, vóór de freeze).** `agents/monetary_policy_agent.py`: nieuwe reeks
`fed_funds_target_upper` (DFEDTARU, dagelijks) in `FRED_SERIES`, `METRIC_SPECS` (tolerance 0,125 = halve stap, severity
high) en `GRAPH_MAPPING` (`policy_stance`); de twee FOMC-doelen (`direction_after_fomc`, horizon 1 en 2) wijzen ernaar
i.p.v. naar FEDFUNDS, met bijgewerkte `event_rule` en `resolution_rule`. `direction_after_fomc` zelf is niet veranderd: de
eerste waarneming NA de besluitdag beslist, en dat werkt voor een dagreeks net zo goed. Winst: de uitkomst is er een dag
na de vergadering in plaats van vijf tot zes weken. **Trigger-versie v2 -> v3** (alleen deze ene spec erbij; de
vingerafdruk `1d72aeed38fc97ec` staat in `TRIGGER_FINGERPRINTS`). FRED-volume 15 -> 16 per dag (`test_api_budget`,
`data-sources.md`). Nieuwe tests: reeks/spec/doelen kloppen; de trigger vuurt op een stap en nooit op geen verandering;
afwikkelen op de dag na de besluitdag; de besluitdag zelf telt niet als "na". Bestaande tests bijgewerkt waar ze
`fed_funds_rate` als FOMC-doel noemden (resolver, mapping, baselines, kalibratie-telling 40 -> 41).
**Bewuste keuze:** FEDFUNDS blijft staan (trend, Taylor Rule), dus een renteverandering geeft twee triggers; zelfde
afweging als UNRATE in twee agents.

**SPY-holdings-archief (docs/data-archive.md, fase B).** `archive_daily.py` + `src/archive/spy_holdings.py` +
`archive_daily.sh`: haalt het State Street-bestand op, valideert dat het een echte xlsx is (een HTTP 200 met een
foutpagina wordt geweigerd), gzipt het, schrijft atomair, leest het terug en vergelijkt de sha256, en voegt een regel
aan `manifest.jsonl` toe. Eigen proces, eigen map (`MI_ARCHIVE_DIR`, standaard `archive/`, in `.gitignore`), **geen
databasetoegang** (een test bewaakt dat). `--status` toont ontbrekende werkdagen. 20 tests in `tests/test_archive_spy.py`.

**Niet geverifieerd:** de bron is vanuit de bouwomgeving niet bereikbaar (proxy weigert het domein). Dus pas bekend na de
eerste run op de VPS: of een User-Agent volstaat, welke datum "as of" betekent, hoe laat de bron ververst, en of de
as-of-regex het echte bestand leest (best-effort, `null` is geen fout). Staat **niet in de cron**: dry-run-plan in
`docs/deployment.md`, "Het ruwe archief". De archiefmap zit nog niet in `backup.sh` (handmatige stap, beschreven).

**Bewust niet gedaan:** Kalshi/Polymarket-diepte meten, nieuws opnieuw testen met een kort venster, de probe-adviesregel
corrigeren voor "nog niet onderzocht", `roadmap.html` bijwerken, reeksenlijst-beslissingen (loonstijging, core CPI,
commodity-ETF's) vastleggen (DD: "prima" = het voorstel volgen: uitstellen, want FRED-reeksen zijn herstelbaar).

### Probe-script voor het brede archief (1.2/1.4, 30-09) — 781 tests groen

DD legde een uitgebreid onderzoek (met een ander model) voor over data die niet terug te halen is. Het is
beoordeeld in `docs/data-archive.md`: het kernprincipe (een breed ruw archief plus een smalle set per agent) is
overgenomen en staat al in de roadmap (1.2 `expectations` en `events`); een deel van wat "niet terug te halen" heette is dat
wel (ALFRED, CFTC, Cboe-indexen, mogelijk optieketens en intraday via het betaalde Alpha Vantage-plan).

**Gebouwd: `probe_sources.py` en `src/sources/probe.py`, fase A, alleen lezen.** Meet ~14 Alpha Vantage-aanroepen
(optieketens historisch en realtime, intraday met maandparameter, nieuws, transcripts, zeven ETF's als grondstofproxy),
51 FRED-reeksen (titel, frequentie, **eenheid**, eerste en laatste waarneming, achterstand), de ALFRED-vintages, en tien
openbare bronnen (Cboe, SPY-holdings, CFTC, NY Fed, Treasury, ECB, Kalshi, Polymarket, de Fed). Wat niet te meten valt
(consensus, fed funds futures, ISM, Yahoo bewust niet) staat er toch in, met reden. Per rij een advies uit één kleine regel.

**Ontwerpkeuzes.** Geen opslag en geen database (een test bewaakt dat de module de opslaglaag niet importeert). Sleutels komen
nooit in de uitvoer: `redact_secrets` in zowel de fetch als `ProbeResult`, en een test over het volledige JSON. De herstelbaarheid
van een "nu"-meting volgt uit de historische meting, niet uit een aanname. Het Alpha Vantage-volume is beperkt tot ~15 aanroepen
met een seconde pauze (het incident van 29-09), en een test bewaakt dat. Dieptemetingen tonen bewust geen achterstand: de geteste
datum in die kolom las als verouderde data (gevonden bij het bekijken van het eerste rapport).

**Ongetest.** Niet tegen de echte bronnen gedraaid: dat is de eerste run op de VPS. Een deel van de url's en dataset-ID's komt uit
het hoofd en kan een 404 geven; dat is dan een bevinding. De volgende stap is die run, en op basis daarvan het ontwerp van
het archief zelf (eigen job, gecomprimeerde bestanden in de DigitalOcean Space).

### Menselijke voorspelinvoer (4.8) op pauze, console-limiet ingesteld (30-09)

DD zette de menselijke invoer bewust op pauze: zijn expertise ligt bij daytrading en deels bij
macro, en de doelen van cohort 0 zijn breder. Hij komt er zelf op terug; Claude Code bouwt het niet
uit zichzelf. Gemiste weken zijn niet in te halen (dat weet DD), maar er verandert niets aan het
contract of de scoring en T₀ᵇ wordt er niet door geblokkeerd. De ontwerpvoorstellen (kernset van
~12 doelen, alleen op de dag van de agents-ronde, blind, bevestigen vóór opslaan, en mogelijk
aansluiten op de verhandelbare doelen van de synthesizer) staan bij 4.8 in `docs/roadmap.md`.
Daarnaast stelde DD de uitgavenlimiet van $200 per maand in het Anthropic-console in.

### Tokenverbruik, time-out en maandrem voor `--deep-dives` (1.11, 30-09) — 744 tests groen

Bij het dry-run-plan voor `--deep-dives` (checkpoint 3, `docs/deployment.md`) keurde DD de
codewijzigingen goed, met één aanpassing: een maandgrens van **$200** in plaats van de
voorgestelde $20.

**Wat er is.** `runtime/llm_budget.py` wikkelt de Anthropic-client in `MeteredClient`
(alleen in `run_daily.py`, niet in de agents): vóór elke aanroep controleert hij het
maandverbruik, na afloop legt hij invoer- en uitvoertokens en de geschatte kosten vast in de
nieuwe tabel `llm_usage` en logt hij ze. De grens (`MI_MAX_MAANDBEDRAG_USD`, default 200)
werkt op de kalendermaand in UTC en telt uit de database, dus over runs heen. Bij het
bereiken gooit de aanroep `BudgetExceeded`, en de bestaande foutisolatie behandelt dat als
elke mislukte LLM-aanroep: de deep-dive wordt `needs_review`, de forecast-ronde een mislukte
`agent_run` met reden. Dat geeft exit code 1 en een melding, en is dus nooit stil. Vanaf 50%
komt een WARNING. Daarnaast heeft de client nu een time-out van 90 seconden met twee
herhalingen (de SDK-standaard was 10 minuten per poging).

**Ontwerpkeuzes.** Geen stille stop: een voorspelling die door de rem wegvalt is een gat in
het cohort, en dat mag nooit onzichtbaar zijn. Prijzen hardcoded met peildatum 25-09-2026;
een onbekend model telt tegen de duurste prijs (liever te vroeg remmen). De rem geldt alleen
met `--deep-dives`; een typefout in de variabele stopt dan met exit 2 en raakt de ingestie
zonder de vlag niet. Een aanroep zonder `usage` telt als $0 met een WARNING: dat is het
enige gat, en het is zichtbaar.

**De test vond een echte fout in mijn eigen wijziging.** De samenvatting van het verbruik
werd gelezen ná `conn.close()` in `run_daily.py`, wat elke run met `--deep-dives` aan het
eind had laten crashen. Mutatiecontroles (rem uit, vastleggen uit, time-out weg, samenvatting
na close) worden alle vier gevangen.

**Ongetest.** Niet tegen de echte API gedraaid; de nep-client bootst `usage` na. De eerste
begeleide testrun (8 oktober) is het echte bewijs, met het Anthropic-console ernaast om de
geschatte kosten te vergelijken. Het console-limiet van $200 is DD's eigen handeling.

### FOMC-kalender ingevuld (4.5, 30-09) — checkpoint 4 opgelost

**Bron en werkwijze.** Ik kon federalreserve.gov niet bereiken vanuit deze
omgeving en heb dus niets uit mijn geheugen ingevuld. DD opende de officiële
pagina en stuurde screenshots van de tabellen "2026 FOMC Meetings" (oktober,
december) en "2027 FOMC Meetings" (alle acht). Ik las de datums er zelf uit en
zette de tweede dag van elke vergadering in de tuple: 28 oktober en 9 december
2026, en 27 januari, 17 maart, 28 april, 9 juni, 28 juli, 15 september, 27
oktober en 8 december 2027. Alle tien vallen op een woensdag (gecontroleerd).

**Wat dit ontgrendelt.** De twee FEDFUNDS-richtingsdoelen van de monetary
agent (`direction_after_fomc`) waren tot nu toe onafwikkelbaar en zijn dat
niet meer, zolang er genoeg vergaderingen na `created_at` staan. Drie punten
om te weten:

- **Convention: besluitdag.** Voor de resolver maakt het niet uit welke dag van
  de twee, want FEDFUNDS-waarnemingen hebben een `source_time` op de eerste van
  de maand. Voor de leesbaarheid en de test (altijd een woensdag) staat de
  besluitdag erin.
- **"Tentative".** De Fed zegt zelf dat elke datum voorlopig is tot de vorige
  vergadering hem bevestigt. Een verschoven of geannuleerde vergadering vraagt
  een aanpassing van de tuple. Een niet-geplande vergadering staat er bewust niet
  in.
- **[02-10 opgelost voor het pseudo-OOS-venster] 29 juli en 16 september 2026 zijn toegevoegd.** Bron: de twee
  FOMC-persberichten ("For release at 2:00 p.m. EDT"), door DD als PDF aangeleverd: 29 juli (doelrange ongewijzigd op
  3,50-3,75) en 16 september (verhoogd naar 3,75-4,00, 12-0). De vergaderingen van januari tot en met juni 2026 ontbreken nog en
  zijn daar niet nodig. Een voorspelling waarvan de vergadering buiten de lijst valt is onafwikkelbaar, met de reden erbij, en
  is geen benadering.

**Tests.** Een bestaande test (`test_zonder_fomc_kalender_wordt_er_niet_benaderd`)
riep de methode zonder kalender aan en verwachtte een lege. Nu de standaard
gevuld is geeft ze expliciet `meetings=()` mee; de intentie blijft dezelfde.
De vier tests uit `tests/test_fomc_calendar.py` draaien nu tegen echte data:
oplopend, woensdag, vier tot tien weken uit elkaar, hooguit acht per jaar.

### Controle-run van v1 en commodity als v2 (1.5, 29-09) — 714 tests groen

**De controle-run van v1 klopt.** DD draaide `calibrate_triggers.py` na de merge
van PR #17. Kolom `3j` staat per reeks op ~5: monetary 4,0-5,3 (fed funds 2,3,
werkloosheid 2,3, CPI onveranderd), financial 3,3-5,0, sector 4,3-6,0, economic
ICSA 5,0, currency 2,3-2,7. Totaal zonder commodity 124 per jaar tegen de
voorspelde ~125. Twee afwijkingen zijn verklaard en geen fout: fed funds beweegt
maar een paar keer per jaar, en het "5 per jaar" van het rapport voor werkloosheid
was een float-artefact (zie roadmap), dus de echte 2,3 is juist.

**Commodity-back-fill geslaagd.** 4.221 claims, alle tien de reeksen, geen
mislukking, geen key in het log. Daarmee kon commodity voor het eerst worden
gekalibreerd, als **trigger-versie v2** (alleen die tien drempels veranderen).

**Een eenhedenfout uit v0 ontdekt.** De koper-tolerantie was 0,20, gebaseerd op
dollar per pond; de bron levert dollar per metrische ton (~13.500). Die regel
vuurde bij 100% van de publicaties: geen drempel maar een constante. Nieuwe
waarde 356. Een bestaande test gebruikte ook prijzen per pond (4,10 naar 4,45) en
is aangepast op realistische eenheden, met de reden erbij.

**Bewust niet aangepast:** `3j,rel` liet zien dat de sectordrempels per reeks
anders zullen uitpakken dan `3j` suggereert (SPY 12,7 tegen 5,0; XLY, XLB en XLU
rond 1). Het sectortotaal blijft gelijk. Dat is het bekende open punt over
niveau-afhankelijke drempels en vraagt een wijziging in de trigger-engine
(checkpoint 2).

**Ongetest / onzeker.** De v2-aantallen voor commodity komen uit het rapport
(Tabel 2), niet uit een tweede run. De commodity-reeksen zijn maandgemiddelden;
of de cron-run van elke dag exact dezelfde maandwaarde blijft opleveren tot de
bron publiceert, is uit de data af te leiden maar niet apart gemeten.

### Trigger-versioning en drempelset v1 (1.5, 29-09) — 712 tests groen

**Twee stappen, in deze volgorde, zodat de geschiedenis het toont.** Eerst de
versioning met `v0` als de huidige plaatshouders (commit 74d5872), daarna de
nieuwe drempels als `v1`. Tussen die twee commits liet de waakhond de test falen
op het moment dat de eerste drempel veranderde: precies wat hij moet doen.

**Wat er is.** `contract/trigger_version.py` heeft `TRIGGER_VERSION`, een
registratie `TRIGGER_FINGERPRINTS` (v0 en v1, oude blijven als historie) en
`FROZEN_TRIGGER_VERSION` (nu `None`). `runtime/trigger_guard.py` rekent de
vingerafdruk uit over (1) de configuratie: `tolerance` + `severity` per reeks en
`MAX_AGE` per agent, en (2) het gedrag: vaste invoer door de echte
trigger-functies (strikt groter dan, de verhouding waarbij een onvolledige pull
`high` wordt, de staleness-grens, vergelijking met de LAATSTE claim, revisie,
manager-dispatch). Dat staat bewust buiten `src/triggers/`: checkpoint 2
verbiedt het verzwakken van de engine, en de probes lezen hem alleen. Labels en
redenteksten tellen niet mee. `trigger_events.trigger_version` is een nieuwe
kolom (ALTER TABLE-migratie); `record_trigger_event` is het enige punt waar
triggers worden opgeslagen en stempelt de huidige versie.
`Prediction.trigger_version` volgt de code via `default_factory`, zoals het
cohort, dus baselines en (later) mensen doen niets.

**De pin.** `run_daily.py` stopt met exit 2 als `MI_COHORT=cohort_0` staat en
(a) `FROZEN_TRIGGER_VERSION` niet gezet is, (b) die anders is dan
`TRIGGER_VERSION`, of (c) de vingerafdruk niet bij die versie past (ook op de
VPS, waar niemand pytest draait als iemand een bestand aanpast). Voor `dry_run`
en `pseudo_oos` doet hij niets.

**Bewijs dat de tests iets bewaken.** Vier mutaties, alle gevangen: de stempel
uit `record_trigger_event` (4 tests falen), de migratie niet aanroepen (de
oude-database-test faalt met een OperationalError), de pin niet aanroepen in
`run_daily.py`, `Prediction.trigger_version` op `None`. Daarnaast verschuiven
drie tests een grens in de trigger-laag zelf (`>` → `>=`, high vanaf 40% in
plaats van 50%, stale vanaf de grens) en eisen dat de vingerafdruk meebeweegt.

**v1.** 5 triggers per jaar per reeks, currency 2, gekozen met het
kalibratierapport op de laatste drie jaar, zie "Beslist op 29-09-2026" in
`docs/roadmap.md` voor de uitzonderingen (stapreeksen halverwege twee stapjes,
één UNRATE-drempel, CPI en payrolls ongewijzigd, commodity voorlopig). Twee
bestaande tests hardcodeerden oude drempels en zijn aangepast op hun bedoeling,
niet versoepeld: de integratietest (EUR/USD-beweging groter dan 0,016) en de
kalibratietest (leest de tolerance uit de agent).

**Ongetest.** De aantallen per jaar onder v1 zijn afgeleid uit het rapport, niet
gemeten: alleen een nieuwe run van `calibrate_triggers.py` op de VPS
bevestigt of Tabel 1 (kolom `3j`) nu ~5 toont. Bij een afrondingsverschil of
een tie op een stapreeks is bijsturen een nieuwe versie, geen correctie.

### Trigger-kalibratierapport (1.5) — 676 tests groen

Een rapport dat alleen leest: hoe vaak zou elke drempel gevuurd hebben over de
historie. Het wijzigt niets en raakt `src/triggers/` niet (geen checkpoint 2). De
KEUZE van de drempels is aan DD, en na T₀ᵇ mag ze niet meer verschuiven zonder een
nieuw cohort.

**Het telt zoals het systeem telt.** `run_monitoring` vergelijkt elke cyclus de
nieuwste waarde met de vorige opgeslagen waarde en vuurt bij `|nu - vorige| >
tolerance`, strikt groter dan. Het rapport telt per paar opeenvolgende waarnemingen,
en een test vergelijkt de tellingen op 20 willekeurige reeksen met de echte
`evaluate_surprise`, inclusief de randgevallen waar de verandering precies gelijk is
aan de tolerance. Met `>=` in plaats van `>` falen drie tests.

**Twee tellingen, omdat de tolerances absoluut zijn.** Voor een rente of spread is dat
goed. Voor een koers niet: een ETF stond in 1999 op ~$25 en nu op ~$250, dus een vaste
$6 (XLK) vuurt in het verleden veel minder vaak dan nu. Daarom staat er naast de
absolute telling (zoals het systeem) een niveau-gecorrigeerde: dezelfde drempel als
percentage van het huidige niveau. Verschillen die twee sterk, dan is de drempel
`niveau-afhankelijk`.

**Drie tabellen:** hoe vaak vuurt de huidige drempel (alles/10j/3j/1j), welke drempel
hoort bij 1%, 2% en 5% van de waarnemingen, en het verwachte aantal triggers per jaar
per domein. De registry leest elke tolerance rechtstreeks uit de agent-modules (40
reeksen), zodat een wijziging in de code het rapport meeverandert.

**Beperkingen.** De historie is de back-fill zoals die nu is (gereviseerd, niet de
eerste print). `high_yield_credit_spread` heeft ~3 jaar, dus daar zegt "alles" niets.
De commodity-reeksen hebben nog geen historie.

**Drie fouten in mijn eigen eerste versie, gevonden in de eerste echte run (29-09):**
(1) `yield_curve_10y_2y` toonde een absolute telling van 0 per jaar maar een
"gecorrigeerde" van 11,7 met de vlag `niveau-afhankelijk`. Dat is een artefact: de
reeks staat op 0,32 en is de afgelopen jaren negatief geweest, en een percentage van
een niveau rond nul is geen maat. De gecorrigeerde telling ontbreekt nu bij een reeks
die van teken wisselt. (2) Tabel 2 gaf drempels bij "1% van de dagen", wat per reeks
iets heel anders betekent: bij `unemployment_rate` stond overal 0,2, want maandwaarden
bewegen in stapjes van 0,1. Nu per jaar (2, 5 en 10 triggers). (3) De vlag `wisselt
sterk per periode` stond op 25 van de 40 regels, ook bij één trigger in een venster.
Nu tellen alleen vensters met minstens vijf triggers, of vensters waarin je er op basis
van het hoogste tempo vijf verwachtte (nul triggers in een jaar waarin je er
driehonderd verwachtte blijft dus een signaal).

### De eerste droge run van de ridge op echte data (29-09) — 653 tests groen

Voor het eerst tegen de echte back-fill. Alle 55 doelen zijn gefit, zonder
`MISLUKT`. Het model vindt echte structuur waar die te verwachten is: **VIX h=63
op 0,884** en **h=21 op 0,945** (de VIX keert terug naar zijn gemiddelde, dus de
z-score voorspelt de verandering) en nonfarm payrolls op 0,931 en 0,976 (stabiele
trend). Bij de meeste doelen ligt `oos/rw` rond 1,00: de inputs zeggen op deze
horizonnen bijna niets, het klassieke beeld voor koersen. Het LLM moet dus een
bijna-random-walk verslaan.

**De run vond ook een echte fout, en die is de reden dat we niet bevroren.** Een
aantal doelen scoorde *slechter* dan "geen verandering": **gbp_usd h=63 op 1,175**,
usd_jpy h=63 op 1,093, 2y-rente h=63 op 1,066, xlc op 1,059. Twee oorzaken, allebei
in mijn ontwerp: (1) het model schatte een gemiddelde trend (intercept) uit de
historie, en bij valutakoersen is dat ruis die uit-de-steekproef niet klopt; (2) het
λ-raster stopte bij 100 terwijl de cross-validatie bij bijna elk doel precies die
bovengrens koos, het teken dat nog sterkere regularisatie beter was en het
"niets doen"-model niet bereikbaar.

**De fix:** de cross-validatie kiest per doel tussen *mét* en *zonder* drift, en het
raster loopt nu tot 10.000. Daarmee is "geen verandering" altijd beschikbaar en kan
de ridge niet meer met meer dan afrondingsverschil van de random walk verliezen.
Een eigenschapstest over 18 reeksen (trend die van teken wisselt, ruis, stabiele
trend) bewaakt dat; op de oude versie geeft die oos/rw van 1,03 tot 1,07, dezelfde
orde als op de VPS. **De run moet opnieuw voordat er iets bevroren wordt.**

**Wat `oos/rw` onder 1 wel en niet betekent.** Een waarde van 0,98 is geen bewijs van
voorspelkracht: de cross-validatie kiest uit 14 combinaties, dus de toevallig beste
(winner's curse). Op pure ruis komt het model ook op ~0,98 uit; een test legt dat
vast met een ondergrens. Echte structuur zie je aan duidelijk lagere waarden.

**[30-09: beslist door DD, optie A] Weggelaten inputs.** DD koos de huidige regel (een input met minder dan 80% van de trainingsrijen wordt weggelaten); zie "Beslist op 30-09-2026" in `docs/roadmap.md`. De analyse hieronder is de onderbouwing van die keuze. **Oorspronkelijk open punt voor de freeze: weggelaten inputs.** Een input met minder dan 80% van
de trainingsrijen wordt weggelaten, en dat is bij de lange doelen systematisch:
de 10-jaars rente (sinds 1962) verliest de balans van de Fed (2002), de
inflatieverwachtingen (2003) en de 2-jaars rente; de negen oudste sector-ETF's
verliezen XLC (2018) en XLRE (2015). Het LLM ziet die reeksen wél. Alternatief:
alle inputs meenemen en trainen op het gemeenschappelijke venster (10-jaars:
~5.900 rijen sinds 2003 in plaats van 16.100). Dat is trouwer aan "de inputs die
het LLM ziet", maar levert veel minder rijen en jaren op (bij sector: 2.000 rijen,
7,5 jaar, incl. COVID). Voor een baseline waarvan de inputs bijna niets voorspellen
is het effect klein, maar het is een keuze tussen trouw en steekproefgrootte, dus
van DD. Standaard blijft de huidige regel.

### Alpha Vantage gaf een lege `{}` voor élk endpoint (29-09) — hersteld, oorzaak onbekend

Na ruim 100 calls op één dag (dagelijkse runs, testruns, experimenten en de
back-fill) begon Alpha Vantage rond 11:07 UTC voor **elk** endpoint `{}` terug te
geven, met HTTP 200 en zonder tekst: koersen, grondstoffen en macro, ook een
endpoint dat een uur eerder nog een volledige koers gaf. Key en plan kloppen
(bevestigingsmail: premium, 75 calls per minuut). Het is niet gedocumenteerd
gedrag, dus de oorzaak is niet vastgesteld; alleen Alpha Vantage kan dat zien.

**Wat het verandert aan eerdere aannames.** De ontbrekende reeksen van de eerste
testrun (cotton, wti, xlb, xli, gbp_usd) heb ik toegeschreven aan calls die
langer dan de timeout van 15 s duurden. Een deel klopt (er zijn echte antwoorden
van 30 s gemeten), maar een deel was mogelijk al `{}`. Een langere timeout lost een
leeg antwoord niet op en een herhaling direct erna krijgt hetzelfde antwoord, dus
het voorstel voor 60 s timeout plus één herhaalpoging bij de dagelijkse agents is
**ingetrokken tot de oorzaak bekend is**.

**Wat er nu is:** de back-fill meldt een leeg antwoord als zodanig ("LEEG antwoord
({})") in plaats van "geen 'data'", en noemt bij een onbekend antwoord de velden
die er wel waren. Een mail aan Alpha Vantage support is opgesteld. **Uitkomst (30-09).**
Rond 13:25 UTC op 29-09 gaf hetzelfde endpoint weer een volledige koers, dus de
`{}` was tijdelijk. De commodity-back-fill draaide daarna zonder één mislukking
(4.221 claims, alle tien de reeksen), en de dagelijkse run van 30-09 07:15 was
compleet: zes van zes agents `ok`, geen completeness-trigger. De mail aan support
is niet verstuurd. **De oorzaak is niet vastgesteld** en het kan terugkomen: zie je
weer een `completeness:`-trigger voor currency, sector of commodity, noteer dan de
tijd en het aantal calls van die dag. Het voorstel voor 60 s timeout plus één
herhaalpoging blijft ingetrokken zolang er geen tweede voorval is dat het patroon
duidelijker maakt.

### `.env` voor de handmatige scripts (29-09) — 641 tests groen

`run_daily.sh` laadt `.env` (cron kent geen shell-profile), maar `backfill.py` en
`fit_baselines.py` worden met de hand gestart en verwachtten dat je eerst
`source .env` deed. Vergeten kostte vandaag een ronde ("API-key niet gevonden"
terwijl hij gewoon in `.env` staat), en bij `fit_baselines.py`, dat geen key nodig
heeft, was het gevaarlijker: `MI_DB_PATH` viel stil terug op een database in de
huidige map, een lege waarin alles "mislukt" zonder aanwijzing waarom.

Beide scripts lezen nu het `.env` naast het script zelf in (`runtime/env.py`, een
eigen mini-parser, geen nieuwe dependency). Bestaande omgevingsvariabelen worden
nooit overschreven en waarden worden nooit getoond of gelogd. Een lege waarde
(`MI_COHORT=`) telt als "niet ingesteld", zoals `.env.example` bedoelt.

`run_daily.py` is bewust niet aangepast: dat draait via `run_daily.sh`, dat `.env`
al inlaadt, en het is de onbeheerde kant (checkpoint 3).

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
- ~~`commodity_agent.py`'s tolerances zijn NOG minder zeker dan
  `sector_agent.py`'s~~ **[29-09 opgelost, trigger-versie v2]**: gekalibreerd op
  35 jaar back-fill, en de eenheden zijn geverifieerd tegen de opgeslagen data
  (koper staat in dollar per metrische ton; de oude tolerantie nam per pond aan en
  vuurde bij elke publicatie). Zie project-state, "Controle-run van v1 en commodity
  als v2".
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

**ATR-proef en besluit (02-10).** `calibrate_triggers.py --atr-proef` (alleen lezen, `src/calibration/atr_proef.py`, 10 tests, 1056 groen) toonde op de echte sector-reeksen: factor 2 geeft ~33 triggers per reeks per jaar, ~5 per jaar komt bij N≈3,5; één N geeft een kleinere spreiding tussen reeksen dan de vaste drempels. **Besluit DD:** cohort 0 begint met de vaste drempels (v4); de ATR-regel komt later als schaduwtelling (roadmap 4.2), niet als invoering. Back-up (nieuwste bestand 02-10, integriteit ok, archief meegekopieerd) en DFEDTARU (6.500 rijen vanaf 2008-12-16) zijn gecontroleerd; geen back-fill nodig.

**Dagelijkse controle (02-10) — 1076 tests groen.** `dagcontrole.py` + `src/runtime/dagcontrole.py` (alleen lezen, `mode=ro`): één scherm voor de begeleide weken en de dry-run-week. Hergebruikt de definitie van een schone dag uit `t0a_status` (geen tweede regelset). Ontbrekend log, back-uplog of archiefmap = ONBEKEND (nooit stilzwijgend ok); een tijdstip dat nog niet verstreken is (07:15 / 08:00 / 08:30 UTC) = `nog niet`. 20 tests; acht bewuste fouten (o.a. ONBEKEND→ok, de nog-niet-regel, de trigger-versiecontrole, de maandagcontrole) lieten een test falen. **Niet gedaan:** nog niet tegen de echte VPS-bestanden gedraaid; de paden `/var/log/mi/daily.log` en `backup.log` komen uit de documentatie en zijn niet met de bestanden zelf vergeleken. Raakt `src/triggers/`, `src/qc/` en de trigger-versie niet.
