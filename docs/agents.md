# Wat elke agent doet — leesbaar overzicht

Tegenhanger van `analyst_agent.ai`'s `framework.py`: daar kon je één bestand
lezen en precies zien wat die agent onderzoekt en hoe hij schrijft. Hier
zit diezelfde informatie verspreid over `agents/base.py` + elk domain-
agent-bestand — dit document bundelt het, in gewone taal, zodat je nooit
de code hoeft te lezen om te weten wie wat doet.

**Onderhoud:** elke nieuwe domain agent (sectie C.2+) krijgt hier een eigen
sectie vóórdat 'ie als "af" telt — zie `CLAUDE.md`, "Werkwijze met DD".
Verandert een bestaand agent-bestand (databron, tolerances, deep-dive-
onderwerp)? Werk dan ook de bijbehorende sectie hieronder bij.

## Regels die voor ÉLKE agent gelden (`agents/base.py::SHARED_QUALITY_RULES`)

Voordat een domain agent iets vakinhoudelijks schrijft, krijgt hij deze
regels automatisch opgelegd — geen enkele agent kan ze overslaan, want ze
worden door `run_deep_dive()` zelf toegevoegd, niet door de agent:

- **Nooit een koop/verkoop-advies, koersdoel, of stellige richting-
  voorspelling.** Met expliciet verboden formuleringen (bijv. "lijkt
  ondergewaardeerd", "zal waarschijnlijk stijgen naar X").
- **Alleen de aangeleverde cijfers gebruiken.** Niets zelf berekenen,
  extrapoleren of verzinnen; ontbrekende data wordt benoemd, niet gegokt.
- **Onzekerheid expliciet benoemen.** Een cijfer met een lage confidence-
  score krijgt geen stellige formulering.
- **Aanleiding uitleggen, niet overinterpreteren.** De trigger-reden mag
  verklaard worden, maar één afwijkende observatie is nog geen trend.

## Monetary policy agent (`agents/monetary_policy_agent.py`)

**Wat het volgt:** vier kernreeksen van FRED (Federal Reserve Economic
Data), elk gezien als "vers" tot 35 dagen oud (het zijn maandelijkse
reeksen):

| Metric | FRED-reeks |
|---|---|
| Fed funds rate | FEDFUNDS |
| 10-jaars Treasury yield | DGS10 |
| CPI-index | CPIAUCSL |
| Werkloosheidspercentage | UNRATE |

**Wanneer het triggert:** bij elke nieuwe waarde vergelijkt het agent met
de vorige observatie (geen vaste absolute drempel, zie hieronder bij
"Belangrijk voorbehoud"):

| Metric | Afwijking die triggert | Severity |
|---|---|---|
| Fed funds rate | > 0,25 procentpunt | high |
| 10-jaars Treasury yield | > 0,25 procentpunt | medium |
| CPI-index | > 2,0 punten | medium |
| Werkloosheidspercentage | > 0,3 procentpunt | high |

**Waar de deep-dive over gaat:** duidt wat de cijfers betekenen in hun
macro-context — bijv. een verkrappend of verruimend beleidssignaal, of een
mogelijk verband tussen de reeksen onderling — maar alléén als de cijfers
dat zelf rechtvaardigen (geen speculatie voorbij de data).

**Bijzonderheid:** bewust als "duo" gestart met de currency agent
hieronder, vanwege hun sterke onderlinge koppeling (renteveranderingen
werken vaak direct door in wisselkoersen).

## Currency agent (`agents/currency_agent.py`)

**Wat het volgt:** drie majeure wisselkoersparen via Alpha Vantage, elk
gezien als "vers" tot 6 uur oud (wisselkoersen bewegen continu, dus vaker
verse data nodig dan macro-reeksen):

| Metric | Paar |
|---|---|
| EUR/USD | EUR → USD |
| USD/JPY | USD → JPY |
| GBP/USD | GBP → USD |

**Wanneer het triggert:** zelfde delta-aanpak als de monetary policy agent:

| Metric | Afwijking die triggert | Severity |
|---|---|---|
| EUR/USD | > 0,01 | medium |
| USD/JPY | > 1,0 | medium |
| GBP/USD | > 0,01 | medium |

**Waar de deep-dive over gaat:** duidt wat een significante beweging
betekent, en mag een mogelijk verband met monetair beleid benoemen —
maar uitsluitend als de aangeleverde cijfers daar zelf aanleiding toe
geven (geen verzonnen causaliteit).

**Bijzonderheid:** DXY (de brede dollarindex) zit er bewust nog niet bij —
die is niet los op te vragen bij Alpha Vantage als standaard valutapaar.
Generaliseren naar meer instrumenten is sectie E/I, niet hier.

## Equity agent (`agents/equity_agent.py`)

**Anders dan de twee hierboven: geen eigen databron.** Dit agent haalt
niets zelf op — het is een adapter die de output van een AL AFGERONDE
`analyst_agent.ai`-analyse (per ticker) omzet naar ons contract. Zie
"Belangrijke scope-grens" hieronder voor wat dat concreet betekent.

**Wat het overneemt uit een analyst_agent.ai-run:**
- 12 verified metrics (operating margin, net margin, vrije kasstroom,
  omzetgroei YoY, nettowinstgroei YoY, EBITDA, net schuld, net debt/EBITDA,
  rentedekking, genormaliseerde EV/EBITDA, cash conversion cycle, ROIC) —
  zelfde selectie als `analyst_agent.ai`'s eigen herkomst-manifest.
- Altman Z-Score, Piotroski F-Score, reverse-DCF (WACC + geïmpliceerde
  FCF-groei).
- De volledige, al-geschreven rapporttekst.

**Wanneer het triggert:** alleen op 5 kernmetrics, t.o.v. de vorige
analyse van DEZELFDE ticker (dus pas zichtbaar bij een hernieuwde
analyse):

| Metric | Afwijking die triggert | Severity |
|---|---|---|
| Operating margin | > 2 procentpunt | medium |
| Net margin | > 2 procentpunt | medium |
| Net debt/EBITDA | > 0,5x | high |
| Rentedekking | > 1,0x | high |
| ROIC | > 2 procentpunt | medium |

**Waar de "deep-dive" over gaat:** er is GEEN eigen LLM-call — de
rapporttekst is al door `analyst_agent.ai` zelf geschreven, mét zijn eigen
4-reviewer-kwaliteitscontrole. We nemen die `NEEDS_REVIEW`-status 1-op-1
over in plaats van er nog een lichte review overheen te draaien.

**Belangrijke scope-grens:** de daadwerkelijke koppeling — hóe de output
van een `analyst_agent.ai`-run hier terechtkomt (bestand, subprocess,
API) — is nog niet gebouwd. `AnalystAgentReport` is het contract daarvoor.

**Bijzonderheid:** elke ticker krijgt zijn eigen "domein" (`equity:NKE`,
`equity:AAPL`, ...) in plaats van één plat "equity" — anders zou de
trigger-laag de ene ticker per ongeluk tegen een andere ticker afzetten
(zie `docs/architecture.md` voor de volledige uitleg).

## Belangrijk voorbehoud, voor alle drie agents

Alle tolerances in de tabellen hierboven zijn **illustratieve
plaatshouders** — geen door DD gevalideerde drempels. Welk absoluut niveau
of welke afwijking "significant genoeg" is, staat bewust nog open (zie
`docs/roadmap.md` sectie H). Pas ze aan zodra daar een onderbouwd antwoord
op is.
