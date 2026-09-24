# Current Project State

**Last updated:** 2026-09-24

## Belangrijke koerswijziging (24-09-2026)

`docs/roadmap.md` is volledig herschreven rond een nieuwe, veel preciezere
doelarchitectuur (DD's artifact "Market Intelligence Platform —
Systeemoverzicht"), georganiseerd in vijf pijlers: Infrastructuur & Data →
Domain Agents → Synthese & Intelligence → Evaluatie & Learning Loop →
Output & Interfaces. De oude, eenvoudigere planning (secties A–I) is
vervangen, niet aangevuld — zie de mapping-tabel bovenaan de nieuwe
roadmap. Geen deadline meer; **huidige prioriteit is sectie 1
(Infrastructuur & Data) écht solide maken vóórdat er verder gebouwd wordt
aan sectie 2 (meer agents/modellen)**. Dit document (project-state.md)
volgt hieronder nog de oude, kleinere scope tot het is bijgewerkt naar de
nieuwe structuur.

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
alleen "het cijfer veranderde". 231 tests groen (`pytest`).

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

231 tests groen (`pytest`).

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
  niet aangepast. 231 tests groen.
- Vóór de koerswijziging afgerond (oude, kleinere scope): sectie B +
  gedeelde kwaliteitsregels + C.1-C.4 (equity-adapter, financial agent,
  sector agent, commodity agent) + `docs/agents.md` + `src/analysis/`
  (NFCI-interpretatie, Taylor Rule, relatieve sterkte, voortschrijdend-
  gemiddelde-afwijking).

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

## Next priorities

**Herzien op 24-09-2026 — sectie 1 (Infrastructuur & Data) eerst, niet
meer agents.** Concreet, in volgorde:

1. Sectie 1's openstaande items dichten (zie `docs/roadmap.md`). **1.1
   afgerond (24-09-2026)**: vier tijdstempels op `Claim`
   (event/source/ingestion/analysis-time, `src/contract/output_contract.py`)
   en de domain-ontologie (`src/contract/domain_ontology.py`) — eerste,
   afgebakende slice, incrementeel gemigreerd over alle 6 agents +
   testsuite, 154 tests groen. Nog open: het rijkere event-model in de
   database (observations/entities/measurements/events i.p.v. alleen
   claims/triggers, 1.2), de volledige data-quality-dimensies
   (completeness/validity/consistency/continuity + revisie-detectie, 1.3),
   een Source Registry (1.4), trigger-severity/-versioning en de twee
   ontbrekende triggertypes (1.5), en de QC-state-machine
   (RAW→...→ARCHIVED, 1.6). Volgorde daarvan nog te bevestigen met DD.
2. Live validatie tegen echte databronnen (FRED/Alpha Vantage), zodra
   netwerktoegang dat toelaat — zie "Known problems" hieronder
   (24-09-2026: beide geblokkeerd in de huidige sandbox-omgeving,
   organisatie-egress-policy, 403). Anthropic-calls werken al wel
   (gevalideerd op 24-09-2026).
3. C.5 (economic agent) en verdere Finetune-modellen: bewust NA sectie 1,
   niet ervoor.
4. De daadwerkelijke koppeling voor C.1/2.3 (hoe een `analyst_agent.ai`-run
   zijn output naar `AnalystAgentReport` vertaald krijgt) — nog geen
   concrete trigger wanneer dit relevant wordt.

## Open questions needing the project owner's input

Zie `docs/roadmap.md` sectie H — met name: welke domeinen continu draaien
vs. alleen on-demand, en de prioritering ICT-trading (kort) vs. macro/
mid-term (lang), aangezien dat de volgorde van sectie C kan beïnvloeden.
Ook: zijn de illustratieve tolerance-waarden in B.1/B.2 bruikbaar als
startpunt, of moeten die eerst vervangen worden voordat dit tegen live data
draait?
