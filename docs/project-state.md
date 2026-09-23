# Current Project State

**Last updated:** 2026-09-22

## Current architecture

Zie `docs/architecture.md`. Sectie A (fundament) en sectie B (eerste twee
domain agents + synthesizer) uit `docs/roadmap.md` staan volledig. 77 tests
groen (`pytest`).

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

77 tests groen (`pytest`).

## Currently working on / just finished

- Sectie B (skeleton met eerste twee domeinen) afgerond. Nog niet gestart:
  sectie C (equity/financial/sector/commodity/economic agents).

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

## Next priorities

1. Sectie C.1: de equity agent als dunne adapter over `analyst_agent.ai`'s
   bestaande pipeline-output — snelste winst, want het grootste deel
   bestaat al.
2. Daarna C.2-C.5 (financial, sector, commodity, economic agents), in de
   volgorde die `docs/roadmap.md` aangeeft.
3. Zodra een echte ANTHROPIC_API_KEY beschikbaar is: één keer een echte
   deep-dive-run doen om `default_llm_review()`/`run_deep_dive()` ook
   praktisch te valideren, niet alleen met fake clients.

## Open questions needing the project owner's input

Zie `docs/roadmap.md` sectie H — met name: welke domeinen continu draaien
vs. alleen on-demand, en de prioritering ICT-trading (kort) vs. macro/
mid-term (lang), aangezien dat de volgorde van sectie C kan beïnvloeden.
Ook: zijn de illustratieve tolerance-waarden in B.1/B.2 bruikbaar als
startpunt, of moeten die eerst vervangen worden voordat dit tegen live data
draait?
