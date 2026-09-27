# Data-sources & API-quota

Roadmap 1.11, taak 0a-3 ("API-quota meten tegen het dagelijkse
callvolume"), fase 0 (`docs/roadmap.md` deel A). Doel: weten of het
dagelijkse callvolume onder de limiet van de gebruikte tier blijft
**voordat** T₀ᵃ draait op de VPS — niet er op dag 1 achter komen dat de
cyclus halverwege afbreekt.

## Wat hieronder wél en niet geverifieerd is

- **Het callvolume per cyclus is EXACT**, geteld uit de code zelf (elke
  `FRED_SERIES`/`SECTOR_ETFS`/`COMMODITIES`/`FX_PAIRS`-dict en elke losse
  `_fetch_*()`-aanroep in de vijf agent-modules) — geen schatting.
- **De Alpha Vantage-tierlimiet hieronder is NIET tegen DD's eigen key
  geverifieerd.** FRED en Alpha Vantage zijn in deze sandbox-omgeving
  hard geblokkeerd op netwerkniveau (organisatie-egress-policy, `CONNECT`
  wordt geweigerd — zelfde blokkade als vastgelegd in
  `docs/project-state.md`, "Known problems", 24-09-2026; opnieuw
  bevestigd op 27-09-2026 voor deze sessie). Het cijfer hieronder (25
  calls/dag) is Alpha Vantage's publiek gedocumenteerde standaard
  free-tier-limiet, GEEN aanname over DD's specifieke abonnement.
  **Expliciet open punt (checkpoint 4 uit `CLAUDE.md`): DD moet dit op de
  VPS tegen de eigen key bevestigen** (een enkele `GLOBAL_QUOTE`-call en
  het antwoord-JSON checken op een rate-limit-melding, of het
  Alpha Vantage-dashboard van het eigen account raadplegen) vóór T₀ᵃ.

## Callvolume per cyclus, per agent

| Agent | Provider | Monitoring (elke cyclus) | Deep-dive (alleen bij trigger, per keer) |
|---|---|---|---|
| monetary_policy | FRED | 4 (`FEDFUNDS`, `DGS10`, `CPIAUCSL`, `UNRATE`) | +4 (`_fetch_taylor_rule_inputs()`: CPI nu, CPI 12 mnd terug, `GDPC1`, `GDPPOT`) — alleen als `fed_funds_rate` triggerde |
| financial | FRED | 4 (`NFCI`, `BAMLH0A0HYM2`, `VIXCLS`, `T10Y2Y`) | +0 (NFCI-interpretatie is pure Python, geen extra call) |
| currency | Alpha Vantage | 3 (EUR/USD, USD/JPY, GBP/USD) | +0 |
| sector | Alpha Vantage | 11 (elk van de 11 SPDR-ETF's) | +1 (SPY-benchmark, één keer per deep-dive) +1 per getriggerde ETF (t/m 11) |
| commodity | Alpha Vantage | 10 (elk van de 10 grondstoffen) | +1 per getriggerde grondstof (t/m 10) |

`equity_agent.py` staat hier niet bij: die heeft geen eigen live databron
(adapter op een al-afgeronde `analyst_agent.ai`-run, zie
`docs/architecture.md`) en draait niet mee in `runtime/daily.py`'s
`default_agents()`.

## Totalen per dag

**Monitoring-only (elke dag, gegarandeerd — dit is de bodem):**
- FRED: 4 + 4 = **8 calls/dag**
- Alpha Vantage: 3 + 11 + 10 = **24 calls/dag**

**Worst case (alle vijf domeinen triggeren tegelijk een deep-dive op
dezelfde dag):**
- FRED: 8 + 4 (Taylor Rule) = **12 calls/dag**
- Alpha Vantage: 24 + (1 SPY + 11 sector) + 10 commodity = **46 calls/dag**
- Anthropic (LLM): t/m 5 deep-dive-calls (één per getriggerd domein) — geen
  vast quotum-probleem zoals FRED/AV, wel een kostenpost, zie
  `docs/architecture.md`'s LLM-taken-tabel (1.8).

## Conclusie en aanbeveling

FRED's rate limit (publiek gedocumenteerd: ~120 requests/minuut) is voor
dit volume (8–12 calls/dag) geen enkel risico.

**Alpha Vantage is het risico, en het manifesteert zich al zonder één
enkele deep-dive:** de monitoring-only bodem van 24 calls/dag zit al
tegen de publiek gedocumenteerde free-tier-limiet van 25/dag aan — één
extra call (bijv. een retry, of een dag met een sector- of
commodity-deep-dive) breekt de cyclus. Dit is precies de reden dat
1.11's DoD "anders bron wisselen vóór T₀ᵃ" als uitkomst noemt naast
"binnen de limiet passen".

**Twee opties, DD's keuze (niet hier beslist):**
1. Alpha Vantage-tier upgraden naar een betaald plan met een hogere
   daglimiet — kleinste wijziging, geen codewerk.
2. Alpha Vantage vervangen door een bron zonder deze beperking voor
   sector/commodity/FX (bijv. `yfinance`, zoals de roadmap zelf als
   voorbeeld noemt) — codewerk, en een nieuwe dependency om eerst tegen
   CLAUDE.md-regel 2 (geen gecompileerde dependencies) te checken.

Zonder een van beide gebeurt op dag 1 van T₀ᵃ precies het scenario dat
1.11's `system_health()`/notificatielaag moet opvangen: een
`data_health`-falen op `ALPHA_VANTAGE_EQUITY:sector` en/of
`ALPHA_VANTAGE_COMMODITY:commodity`, zichtbaar als kritieke melding, maar
dan wel een gat in de back-fill/track record voor die dag.
