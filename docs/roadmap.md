# Roadmap — Market Intelligence Multi-Agent Systeem

Levend document, gespiegeld vanuit de oorspronkelijke planning-artifact
(`market-intelligence-roadmap.html`). Vink items af zodra ze klaar zijn en
groen zijn in de testsuite; volgorde binnen elke sectie is uitvoeringsvolgorde,
niet per se tijdsduur.

Nieuw systeem naast `analyst_agent.ai` (zie die repo), later gekoppeld als
equity-subagent. Doel: doorlopende monitoring per vakgebied die on-demand
deep-dives triggert, gesynthetiseerd tot bruikbare marktintelligentie — incl.
een dagelijkse Nasdaq/NQ-regime-agent en een news monitor agent.

## A. Fundament — moet eerst, bindt alles samen

- [x] 1. Output-contract vastleggen (`src/contract/output_contract.py`) —
      claim/waarde/bron/confidence/tijdstempel, zelfde principe als de
      lineage-aanpak in `analyst_agent.ai/src/reporting/lineage.py`.
- [x] 2. Database-schema als source of truth (`src/storage/schema.py`) —
      SQLite, slaat het A.1-contract op.
- [x] 3. Data-health/staleness-checks (`src/health/data_health.py`) — moet
      staan vóórdat er triggers op die data gebouwd worden.
- [x] 4. Trigger-laag (`src/triggers/trigger_engine.py`) — deterministisch,
      geen LLM.
- [x] 5. QC-principe (`src/qc/qc.py`) — deterministisch waar mogelijk, lichte
      LLM-review per domain-deep-dive (pluggable), NEEDS_REVIEW-vlag.
- [x] 6. Manager-agent (`src/manager/manager.py`) — dispatch-logica,
      gelijktijdige triggers over meerdere domeinen.

## B. Skeleton met eerste twee domeinen (monetary policy + currency)

- [ ] 1. Monetary policy agent: monitoring mode + deep-dive mode.
- [ ] 2. Currency agent: zelfde tweeledige opzet.
- [ ] 3. Synthesizer eerste versie: legt de twee deep-dives naast elkaar.
- [ ] 4. End-to-end testen: monitoring → trigger → escalatie → synthese →
      database.

## C. Domain Agents

- [ ] 1. Equity agent: dunne adapter die `analyst_agent.ai`'s bestaande
      output in het A-contract giet.
- [ ] 2. Financial agent.
- [ ] 3. Sector agent.
- [ ] 4. Commodity agent.
- [ ] 5. Economic agent.

## D. News monitor agent

- [ ] 1. Nieuwsbronnen/feeds bepalen.
- [ ] 2. Relevantie-filtering.
- [ ] 3. Koppeling aan de trigger-laag (A) als aanvullende triggerbron.
- [ ] 4. Dubbeltelling voorkomen.

## E. Nasdaq/NQ regime- en bias-agent

- [ ] 1. Beslissing: specifiek NQ of generieke "instrument regime/bias
      agent".
- [ ] 2. Kwantitatief regime: `analyst_agent.ai/src/analysis/simple_hmm.py`
      hergebruiken op NQ-prijsdata.
- [ ] 3. Kwalitatieve bias-synthese: LLM-call die HMM-regime combineert met
      de staat van alle domain agents (B t/m D).
- [ ] 4. Dagelijkse auto-update (monitoring mode).
- [ ] 5. On-demand vraag-interface.

## F. Synthesizer volwassen maken

- [ ] 1. Cross-agent tegenstrijdigheid-check.
- [ ] 2. Confidence-weging (Bayesiaans: prior-gewicht per domain agent op
      basis van track record, gewogen posterior).
- [ ] 3. Omgaan met tegenstrijdige signalen tussen domain agents.
- [ ] 4. Cross-domein implicaties combineren tot één leesbaar geheel.
- [ ] 5. Trigger-kalibratie/validatie (backtesten); uitbreiding:
      Beta-Binomiaal-model i.p.v. `analyst_agent.ai`'s huidige
      held-vs-breached-telling in `compute_calibration_score()`.

## G. Output & interface

- [ ] 1. Alert-mechanisme bij trigger/escalatie.
- [ ] 2. Dashboard (dagelijkse stand van zaken per domein + Nasdaq-bias).
- [ ] 3. On-demand query-interface over het hele systeem heen.

## H. Open beslissingen (bewust nog niet dichtgetimmerd)

- [ ] Statische vs. adaptieve trigger-thresholds per domein.
- [ ] Prioritering van domeinen: dagelijkse ICT-trading (kort) vs. macro/
      mid-term-werk (lang).
- [ ] Hoeveel domain agents draaien continu vs. alleen op aanvraag.

## I. Later / optioneel

- [ ] Regime/bias-agent generaliseren naar meerdere instrumenten (DXY, crude,
      Treasuries).
- [ ] Market expectations-vergelijking scherper maken, voortbouwend op
      `analyst_agent.ai/src/analysis/reverse_dcf.py`.
- [ ] Thesis-tracking per domein (zoals `track_record.py` voor equity, maar
      voor macro/currency-theses).
