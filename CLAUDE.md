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
Edge (TCE)**). Volledige planning: `docs/roadmap.md`.

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
| Huidige status | `docs/project-state.md` |
| Architectuur/datastroom van het fundament | `docs/architecture.md` |
| Tests | `tests/` |

## Voordat je iets verandert

- Lees `docs/roadmap.md` — de volgorde binnen elke sectie is een bewuste
  afhankelijkheidsketen, geen willekeurige lijst. Sectie A moet blijven
  werken voordat sectie B erop bouwt, enzovoort.
- Draai `pytest` voor en na elke wijziging.
- Nieuwe deterministische logica krijgt een test in `tests/`, naar het
  patroon van de bestaande testbestanden (één "correct"-geval, één
  regressiegeval waar relevant).
- Vink een roadmap-item pas af in `docs/roadmap.md` als de bijbehorende
  tests groen zijn.

## Wat NIET te doen zonder te vragen

- Geen 4-parallelle-reviewers-QC hier overnemen uit `analyst_agent.ai` — dat
  paste bij de kosten/waarde van één 18-sectie-rapport, niet bij doorlopend
  achtergronddraaien over meerdere domain agents. Zie `docs/architecture.md`.
- Geen LLM-arithmetiek in de trigger-laag of manager — die blijven
  deterministisch.
- Geen roadmap-secties overslaan of herordenen zonder de afhankelijkheid in
  `docs/roadmap.md` te checken (bijv. sectie C.1 kan pas nadat sectie B
  bewijst dat het monitoring→trigger→deep-dive→database-pad werkt).

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

## Taal

Inline comments en documentatie zijn in het Nederlands, consistent met
`analyst_agent.ai` — DD's project, Nederlandstalig ontwikkeld.
