# Current Project State

**Last updated:** 2026-09-22

## Current architecture

Zie `docs/architecture.md`. Sectie A (fundament), sectie B (eerste twee
domain agents + synthesizer), en C.1-C.3 (equity-adapter, financial agent,
sector agent) uit `docs/roadmap.md` staan volledig, plus een tussentijdse
verbetering: een gedeelde kwaliteitsregels-module
(`agents/base.py::SHARED_QUALITY_RULES`) die elke deep-dive automatisch
meekrijgt, een leesbaar overzicht per agent (`docs/agents.md`) zodat je
nooit de code hoeft te lezen om te weten wat een agent doet, en
`src/analysis/` — citeerbare, Python-berekende modellen (NFCI-
interpretatie, Taylor Rule, relatieve sterkte) die deep-dives onderbouwen
i.p.v. alleen "het cijfer veranderde". 131 tests groen (`pytest`).

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

131 tests groen (`pytest`).

## Currently working on / just finished

- Sectie B + gedeelde kwaliteitsregels + C.1-C.3 (equity-adapter, financial
  agent, sector agent) + `docs/agents.md` + `src/analysis/` (NFCI-
  interpretatie, Taylor Rule, relatieve sterkte) afgerond. Nog niet
  gestart: C.4-C.5 (commodity/economic agents).

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
- `default_llm_review()` en `run_deep_dive()` zijn nog nooit tegen een
  échte Anthropic-call getest (alleen fake clients in tests) — er is nog
  geen ANTHROPIC_API_KEY in deze omgeving. Functioneel gedekt door tests;
  praktisch gevalideerd zodra dit tegen een echte API-key draait.
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

## Next priorities

1. C.4-C.5 (commodity, economic agents), in de volgorde die
   `docs/roadmap.md` aangeeft.
2. Zodra een echte ANTHROPIC_API_KEY beschikbaar is: één keer een echte
   deep-dive-run doen om `default_llm_review()`/`run_deep_dive()` ook
   praktisch te valideren, niet alleen met fake clients.
3. De daadwerkelijke koppeling voor C.1 (hoe een analyst_agent.ai-run zijn
   output naar `AnalystAgentReport` vertaald krijgt) — nog geen concrete
   trigger wanneer dit relevant wordt.

## Open questions needing the project owner's input

Zie `docs/roadmap.md` sectie H — met name: welke domeinen continu draaien
vs. alleen on-demand, en de prioritering ICT-trading (kort) vs. macro/
mid-term (lang), aangezien dat de volgorde van sectie C kan beïnvloeden.
Ook: zijn de illustratieve tolerance-waarden in B.1/B.2 bruikbaar als
startpunt, of moeten die eerst vervangen worden voordat dit tegen live data
draait?
