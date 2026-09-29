# CLAUDE.md — Market Intelligence Multi-Agent Systeem

Dit bestand wordt automatisch gelezen aan het begin van elke Claude Code
sessie in deze repository.

## Wat dit project is

Een doorlopend, grotendeels onbeheerd multi-agent systeem dat per vakgebied
(monetary policy, currency, equity, financial, sector, commodity, economic)
monitort en bij significante afwijkingen escaleert naar een LLM-deep-dive,
gesynthetiseerd tot marktintelligentie. Bouwt naast, en later bovenop,
[`analyst_agent.ai`](https://github.com/daan3042-dotcom/analyst_agent.ai)
(de bestaande single-ticker equity-researchpijplijn voor **The Collective
Edge (TCE)**).

**Volledige planning (bron van waarheid): `docs/roadmap.md`.** De vijf
pijlers — Infrastructuur & Data → Domain Agents → Synthese & Intelligence
→ Evaluatie & Learning Loop → Output & Interfaces — zijn de **catalogus**
en hun nummering is stabiel. Sinds 26-09-2026 bepaalt die nummering NIET
meer de volgorde van werken: dat doet het kritieke pad naar **T₀**
(streefdatum 10-11-2026), het moment waarop het systeem dagelijks draait
en elke voorspelling gescoord wordt.

Reden: LLM-agents zijn niet eerlijk te backtesten — een model dat nu naar
2020 kijkt, weet al wat er volgde. Forward testing is daarmee de enige
geldige weg, en dat kost kalendertijd in plaats van werktijd. Alles wat
geen voorwaarde is voor "de klok kan lopen" schuift naar achteren.

**Herzien op 27-09-2026 (externe review):** twee klokken — T₀ᵃ
(ingestieklok, streefdatum 3-10-2026) en T₀ᵇ (predictieklok, 10-11-2026);
kwantielen i.p.v. binaire richting; drie baselines; pseudo-out-of-sample
vóór T₀ᵇ; economic agent lean vóór T₀; mensen als gescoorde
voorspellers; `graph_node` optioneel in cohort 0. Alle correcties met
onderbouwing in `docs/roadmap.md`, "Wat er op 27-09-2026 veranderd is".

**Huidige focus: sectie 1.11 (Scheduler & Runtime), T₀ᵃ.** Zie
`docs/roadmap.md` deel A, `docs/roadmap.html` (afvinkbare handleiding)
en `docs/project-state.md`.

## De regels die uit `analyst_agent.ai` zijn overgenomen (en waarom)

1. **Deterministisch waar mogelijk, LLM alleen waar het moet.** De
   trigger-laag en de manager-dispatch zijn met opzet LLM-vrij — dit systeem
   draait onbeheerd, dus "wanneer escaleren we" moet reproduceerbaar en
   goedkoop zijn. LLM-synthese hoort alleen in deep-dive mode en de
   synthesizer.
2. **Geen gecompileerde/native dependencies waar vermijdbaar.** Zelfde
   ontwikkelmachine-beperking als `analyst_agent.ai` (zie diens
   `docs/decisions/ADR-003-http-api-over-sdk-for-native-deps.md`). Check dit
   voordat je een nieuwe dependency toevoegt.
3. **`NEEDS_REVIEW` i.p.v. blokkeren.** Elke QC-laag zet een vlag bij
   twijfel, in plaats van output tegen te houden — zie
   `src/qc/qc.py`. Behandel `NEEDS_REVIEW` niet als een bug om weg te
   maken.

## Waar dingen staan

| Zoek je... | Bestand |
|---|---|
| Het output-contract (Claim/DomainOutput) | `src/contract/output_contract.py` |
| De database (source of truth) | `src/storage/schema.py` |
| Data-health/staleness-checks | `src/health/data_health.py` |
| Deterministische trigger-logica | `src/triggers/trigger_engine.py` |
| QC + `NEEDS_REVIEW` | `src/qc/qc.py` |
| Manager-dispatch (gelijktijdige triggers) | `src/manager/manager.py` |
| Volledige planning | `docs/roadmap.md` |
| **De causale graaf (fase 1, handwerk)** | `docs/causal-graph.md` |
| Huidige status | `docs/project-state.md` |
| Architectuur/datastroom van het fundament | `docs/architecture.md` |
| **Wat elke agent doet, in gewone taal (geen code lezen nodig)** | `docs/agents.md` |
| API-quota/callvolume per bron | `docs/data-sources.md` |
| VPS-inrichting + dry-run-plan (checkpoint 3) | `docs/deployment.md` |
| Eenmalige historische back-fill | `backfill.py`, `src/runtime/backfill.py` |
| **De resolver + scoringsregels (4.5)** | `src/scoring/` |
| Hoe een voorspelling wordt afgewikkeld | `src/contract/resolution.py` |
| **De drie baselines (4.6)** | `src/scoring/baselines.py`, `ridge.py`, `baseline_round.py` |
| Ridge fitten en bevriezen (VPS, eenmalig) | `fit_baselines.py` |
| **Trigger-kalibratierapport (1.5), alleen lezen** | `calibrate_triggers.py`, `src/calibration/` |
| **Trigger-versienummer + vingerafdruk-waakhond (1.5)** | `src/contract/trigger_version.py`, `src/runtime/trigger_guard.py` |
| Tests | `tests/` |

## Eerst kijken of iemand het al bouwt (verplicht, niet optioneel)

**Op 28-09-2026 hebben twee sessies dezelfde vier roadmap-items
onafhankelijk gebouwd** — atomiciteit, ouderdomsgrens, API-quota en de
economic agent. Beide branches stonden gewoon op GitHub; er keek alleen
niemand. Dat kostte een halve dag en leverde twee versies op die met de
hand samengevoegd moesten worden.

Daarom, vóór je aan een roadmap-item begint:

1. **Lees de banner van de SessionStart-hook** (`.claude/hooks/session-start.sh`).
   Die draait automatisch en somt elke branch op met commits die nog niet
   in de default branch zitten. Staat daar iets tussen, kijk dan met
   `git log --oneline <default>..<branch>` of jouw item er al op staat.
2. **Staat het er al op? Bouw het niet.** Meld het, en vraag of je verder
   moet op die branch in plaats van een nieuwe.
3. **Push je eigen branch na de EERSTE commit, niet pas aan het eind.**
   Een branch die alleen lokaal bestaat, is voor elke andere sessie
   onzichtbaar. Dit is de hele reden dat de hook iets kan vinden.

En het belangrijkste tegengif tegen dit hele probleem: **merge per
afgerond item naar de default branch, niet per sessie.** Zolang werk op
een branch blijft staan, lopen `docs/roadmap.md` en
`docs/project-state.md` op de default branch achter — en dat zijn precies
de bestanden waaruit een volgende sessie (en de project knowledge in de
Claude-webversie) afleidt wat er nog te doen is. Een achterlopende
default branch is niet "netjes opruimen later", het is de directe oorzaak
van dubbel werk.

## Voordat je iets verandert

- Lees `docs/roadmap.md` — deel A bepaalt de volgorde (kritiek pad naar
  T₀), deel B is de catalogus met de vaste pijlernummers. De volgorde
  binnen een sectie is een bewuste afhankelijkheidsketen, geen
  willekeurige lijst.
- Draai `pytest` voor en na elke wijziging.
- Nieuwe deterministische logica krijgt een test in `tests/`, naar het
  patroon van de bestaande testbestanden (één "correct"-geval, één
  regressiegeval waar relevant).
- Vink een roadmap-item pas af in `docs/roadmap.md` als de bijbehorende
  tests groen zijn.
- Een nieuwe domain agent is pas "af" als hij ook een sectie heeft in
  `docs/agents.md` (wat volgt hij, wanneer triggert hij, waar gaat de
  deep-dive over) — DD moet nooit de code hoeven lezen om te weten wat een
  agent doet. Wijzig je een bestaande agent (databron, tolerances,
  deep-dive-onderwerp)? Werk dan ook zijn sectie in `docs/agents.md` bij.

## Wat NIET te doen zonder te vragen

- Geen 4-parallelle-reviewers-QC hier overnemen uit `analyst_agent.ai` — dat
  paste bij de kosten/waarde van één 18-sectie-rapport, niet bij doorlopend
  achtergronddraaien over meerdere domain agents. Zie `docs/architecture.md`.
- Geen LLM-arithmetiek in de trigger-laag of manager — die blijven
  deterministisch.
- Geen roadmap-items oppakken die niet op het kritieke pad naar T₀ liggen
  zolang T₀ niet gehaald is (zie `docs/roadmap.md` deel A, "Huidige
  focus"). Dat betekent concreet: **geen nieuwe agents, geen
  Finetune-modellen en geen synthese-uitbreidingen** tot de punten van
  de T₀-checklist staan, hoe verleidelijk ook. **Eén uitzondering,
  beslist op 27-09-2026:** de economic agent komt *lean* vóór T₀ (2.7:
  ICSA/UNRATE/PAYEMS + Sahm Rule, meer niet), omdat de graaf anders geen
  groei-knopen heeft. Twijfel je of iets op het kritieke pad ligt? Eerst
  voorleggen.
- **Wie berekent de kans (27-09-2026).** In cohort 0 spreekt het LLM per
  agent zelf kwantielen/een kans uit op een gestructureerde
  evidence-sheet — dat is precies wat er forward-getest wordt. Python
  weigert (QC), resolvet en scoort, en **aggregeert nooit over agents
  heen**; dat is 3.4. Een LLM berekent nooit een baseline, score of
  gewicht. Zie de LLM-taken-tabel in `docs/architecture.md` (1.8).
- **Elke prediction draagt `model_id` en `prompt_version`.** Een
  modelwissel of promptwijziging binnen een cohort is een covariaat, geen
  nieuw cohort; een wijziging aan contract, graaf of resolution rules
  wél. Pin het model per cohort; Anthropic deprecateert modellen binnen
  de cohortduur van zes maanden, dus plan de migratie in plaats van 'm
  te ondergaan.
- **Nooit `cohort_0` hardcoderen.** Het cohort van nieuwe voorspellingen
  komt uit `MI_COHORT` via `contract/prediction.py::current_cohort()`, met
  `dry_run` als default (29-09-2026). Reden: `predictions` heeft geen
  update-pad, dus een voorspelling van vóór de freeze die als `cohort_0`
  wordt opgeslagen is definitief vervuild. Een nieuwe voorspeller (mensen,
  synthesizer) hoeft niets te doen: `Prediction.cohort` volgt de omgeving
  vanzelf. Geef alleen expliciet een cohort mee als het bewust afwijkt
  (`pseudo_oos` in de pseudo-OOS-run).
- **Trigger-regels dragen een versienummer (29-09-2026).** Elke opgeslagen
  trigger en elke voorspelling draagt `trigger_version`. Verander je een
  drempel, ouderdomsgrens of trigger-gedrag, dan faalt
  `tests/test_trigger_version.py` totdat je `TRIGGER_VERSION` in
  `contract/trigger_version.py` ophoogt en de nieuwe vingerafdruk toevoegt.
  Dat is geen bug in de test. Onder `MI_COHORT=cohort_0` weigert
  `run_daily.py` te starten als de versie niet bevroren (checkpoint 5) of niet
  ongewijzigd is.
- **Na T₀ (streefdatum 10-11-2026): niet sleutelen aan de causale graaf
  (1.10), het predictiecontract (4.1), de `resolution_rule`s of de
  trigger-drempels zonder versienummer.** Elke zo'n wijziging start
  effectief een nieuw cohort in de scoring. Een drempel verschuiven
  omdat de resultaten tegenvallen, levert geen track record op maar een
  overfit. Adaptieve thresholds (4.2) mogen pas na het
  T₀+6-maanden-herzieningsmoment.

## Checkpoints — wanneer stoppen voor menselijke review

Dit systeem draait doorgaans zonder tussenkomst door — dat mag, behalve op
de volgende momenten. Daar wordt altijd gestopt en gewacht op DD's review,
ook als de wijziging correct en laag-risico lijkt:

1. **Na elke nieuwe domain/functionele agent, vóór hij aan de trigger-
   engine of manager wordt gekoppeld.** Laat zien: wat hij monitort, welke
   triggers hij kan geven, hoe zijn output op het output-contract
   aansluit.
2. **Vóór elke wijziging aan de deterministische trigger-engine of QC-
   logica** (`src/triggers/`, `src/qc/`). Dit zijn de veiligheidsgordels
   van het hele systeem — nooit verzwakken of omzeilen om een nieuwe
   agent's output te laten passen.
3. **Vóór elke uitrol naar de VPS of elke wijziging die onbeheerd draaien
   beïnvloedt** (scheduler, cron, `run_daily.py`). Stel eerst een
   dry-run-plan voor: hoe lang alleen-loggen draait voordat het vertrouwd
   wordt, en wat DD in de logs moet controleren. De dry-run-week vóór
   T₀ᵇ staat op de T₀-checklist in `docs/roadmap.md`.
5. **Bij de freeze vóór T₀ᵇ** (contract v0, resolution rules, drempels,
   prompts, `model_id`, de prior voor de skill-posterior): expliciet
   laten bevestigen, met versienummers, voordat de klok gaat lopen.
4. **Zodra een databron, drempel of aanname niet met vertrouwen te
   verifiëren is** (vergelijkbaar met de FINRA-schema-discovery in
   `analyst_agent.ai`). Nooit stilzwijgend doorgaan met een beste gok —
   expliciet vlaggen als het minst zekere deel van het werk.

Niet-onderhandelbare kwaliteitseisen, doorlopend, niet alleen bij de
checkpoints hierboven:
- Elke nieuwe module krijgt tests, naar het patroon van `tests/`. Nooit
  "tests komen later".
- Elke agent-beslissing/output blijft herleidbaar (welke data, welke
  drempel/trigger vuurde, tijdstempel) — dit is al het bestaande patroon
  via `agent_runs`/lineage, geen nieuwe aanpak verzinnen.
- Python rekent, Claude vertelt — geen numeriek werk via een LLM-call waar
  deterministische code het kan doen.
- Nooit stilzwijgend een check overslaan voor een pad met ontbrekende/
  onvolledige data (terugkerend bugpatroon in dit project — checks die na
  een early-return staan, worden overgeslagen).

Sluit een werksessie altijd af met: wat is gebouwd, wat is bewust
uitgesteld en waarom, wat is nog ongetest of onzeker, en wat is het
volgende checkpoint.

## Werkwijze met DD

- Na elke coderonde: een korte samenvatting van welke bestanden zijn
  toegevoegd/gewijzigd en wat dat betekent — niet pas aan het einde van een
  hele sectie, maar elke keer dat er iets gecodeerd is.
- Alle domain agents delen bewust hetzelfde framework (`contract/`,
  `agents/base.py`) zodat de manager/synthesizer ze uniform kunnen
  behandelen — zie `docs/architecture.md`. Nieuwe agents haken hierop aan,
  ze bouwen geen eigen losstaande monitoring/deep-dive-logica.
- Kwaliteit van de deep-dive-analyses is een expliciet, doorlopend
  aandachtspunt — niet alleen "werkt het", maar "is de analyse oprecht
  goed". Bij twijfel over een kwaliteitsafweging (bijv. hoeveel regels
  centraal vastleggen vs. per domein vrij laten): eerst voorleggen, niet
  in stilte kiezen.
- Elke keer dat we iets uitdenken (een ontwerpvoorstel) of uitvoeren
  (een coderonde) expliciet verwijzen naar waar dat in `docs/roadmap.md`
  staat (welke pijler/sectienummer) — zodat DD zonder de code te lezen
  kan volgen waar we mee bezig zijn en wat het volgende is. Een
  afgerond item wordt in diezelfde ronde in de roadmap afgevinkt, niet
  pas later.

## Taal

Inline comments en documentatie zijn in het Nederlands, consistent met
`analyst_agent.ai` — DD's project, Nederlandstalig ontwikkeld.
