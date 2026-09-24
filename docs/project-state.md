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
alleen "het cijfer veranderde". 154 tests groen (`pytest`).

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

154 tests groen (`pytest`).

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
  te bepalen wat de volgende stap is (1.3, 1.4, 1.5, 1.6 of 1.7).
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
