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

## QC-statusmodel: wat er gebeurt ná een trigger (roadmap 1.6)

Elke keer dat een agent triggert, opent het systeem automatisch een
"geval" dat de hele weg volgt: TRIGGERED → DEEP_DIVE_COMPLETE →
QC_PASSED/QC_FAILED → (bij een fail) NEEDS_REVIEW. Dit gebeurt voor élke
agent gelijk, zonder dat een agent er zelf iets voor hoeft te doen.

Nieuw sinds 1.6: als de aanleiding voor een deep-dive een onbereikbare
bron was (een "data_health"-trigger, severity high), telt dat geval
ALTIJD als mislukt (QC_FAILED → NEEDS_REVIEW) — ook als de geschreven
tekst zelf verder brandschoon is. Onbetrouwbare onderliggende data kan
geen goed geschreven tekst "redden". Een verouderde (maar niet
onbereikbare) bron dwingt dit niet automatisch af.

## Monetary policy agent (`agents/monetary_policy_agent.py`)

**Wat het volgt:** vier kernreeksen van FRED (Federal Reserve Economic
Data), elk gezien als "vers" tot 35 dagen oud (het zijn maandelijkse
reeksen). Sinds roadmap 1.4 (Source Registry) heeft deze agent zijn EIGEN
databron-registratie (`FRED:monetary_policy`), los van de financial agent
hieronder — die gebruikt óók FRED, maar met een andere ververssnelheid
(10 dagen). Vóór 1.4 deelden ze onbedoeld dezelfde status, waardoor de
ene agent's verse pulls de andere's veroudering kon verbergen.

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

**Onderbouwing (niet alleen "het cijfer veranderde"):** als er een
fed_funds_rate-claim binnenkomt, berekent Python
(`src/analysis/taylor_rule.py`) de **Taylor Rule** (Taylor, 1993) — een
gevestigde formule voor een "passende" beleidsrente:

`i = r* + π + 0,5(π − π*) + 0,5(output gap)`

waarbij π de YoY-inflatie is (uit CPI, 12 maanden terug opgehaald) en de
output gap uit reëel vs. potentieel bbp (FRED: GDPC1/GDPPOT). π* = 2% is
het Fed's eigen, officieel gepubliceerde inflatiedoel. **r* = 2%** is een
AANNAME — de gangbare waarde in recente toepassingen van dit model,
expliciet afgestemd met DD (zie `docs/project-state.md`), geen door
Claude zelf gekozen getal. De LLM krijgt de impliciete rente én de
afwijking t.o.v. de daadwerkelijke Fed funds rate als kant-en-klare claims
en moet die letterlijk gebruiken, niet zelf inschatten of het beleid
krap/ruim is. Deze bbp-data wordt bewust NIET meegenomen in de reguliere
monitoring (andere, langzamere ververssnelheid — kwartaalcijfers versus de
rest van deze agent) — puur een deep-dive-tijd-verrijking.

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

## Financial agent (`agents/financial_agent.py`)

**Wat het volgt:** financiële-marktcondities — marktstress/liquiditeit,
niet bedrijfsfundamentals (dat is de equity agent hierboven) en niet
Fed-beleid zelf (dat is de monetary policy agent). Vier reeksen, alle van
FRED, elk gezien als "vers" tot 10 dagen oud (afgestemd op de traagste,
wekelijkse reeks — de andere drie zijn dagelijks). Eigen databron-
registratie (`FRED:financial`, roadmap 1.4), los van de monetary policy
agent hierboven — zie die sectie voor waarom.

| Metric | FRED-reeks | Wat het meet |
|---|---|---|
| Financial Conditions Index | NFCI | Chicago Fed's samengestelde maatstaf voor krappe/ruime financiële condities |
| High-yield credit spread | BAMLH0A0HYM2 | Kredietrisico-opslag — een snelle stijging is een klassiek stress-signaal |
| VIX | VIXCLS | Impliciete volatiliteit ("angstindex") |
| 10Y-2Y yield curve | T10Y2Y | Yield-curve-vorm, relevant voor recessierisico-inschatting |

**Wanneer het triggert:** zelfde delta-aanpak als de andere agents:

| Metric | Afwijking die triggert | Severity |
|---|---|---|
| Financial Conditions Index | > 0,1 punt | high |
| High-yield credit spread | > 0,5 procentpunt | high |
| VIX | > 5 punten | medium |
| 10Y-2Y yield curve | > 0,15 procentpunt | medium |

**Waar de deep-dive over gaat:** duidt wat de cijfers betekenen voor
marktstress/liquiditeit — bijv. verkrappende financiële condities of een
toegenomen kredietrisico-opslag — alleen als de cijfers dat zelf
rechtvaardigen.

**Onderbouwing (niet alleen "het cijfer veranderde"):** als er een NFCI-
waarde binnenkomt, berekent Python (`src/analysis/nfci_interpretation.py`)
eerst de classificatie volgens de Chicago Fed's EIGEN gepubliceerde
methodologie (0 = historisch gemiddelde sinds 1973, positief = krapper,
negatief = ruimer) — geen zelfbedachte tussenbanden. De LLM krijgt die
classificatie als kant-en-klare claim en moet 'm letterlijk gebruiken, niet
zelf inschatten wat de waarde betekent. Eerste toepassing van het patroon
"Python berekent een citeerbaar model, de LLM narrate het resultaat" —
zie `docs/roadmap.md` sectie I voor waar dit naartoe groeit (bijv. een
Taylor Rule voor monetary policy).

**Bijzonderheid:** één instantie (net als monetary policy/currency), geen
per-ticker-namespacing nodig zoals bij equity.

## Sector agent (`agents/sector_agent.py`)

**Wat het volgt:** alle 11 SPDR Select Sector-ETF's (de standaard,
GICS-uitgelijnde sector-taxonomie) — bewust ALLE elf, niet een kleine
selectie, want een arbitraire keuze zou precies Materials (relevant voor
DD's eigen ERO Copper-positie) kunnen missen. Data via Alpha Vantage,
elk gezien als "vers" tot 5 dagen oud (dagelijkse slotkoersen, buffer voor
een weekend + feestdag):

| Ticker | Sector |
|---|---|
| XLK | Technology |
| XLF | Financials |
| XLE | Energy |
| XLV | Health Care |
| XLY | Consumer Discretionary |
| XLP | Consumer Staples |
| XLI | Industrials |
| XLB | Materials |
| XLU | Utilities |
| XLRE | Real Estate |
| XLC | Communication Services |

**Wanneer het triggert:** op de RUWE PRIJS van elke ETF (zelfde
delta-mechanisme als de andere agents), tolerances per ETF ruwweg
gekalibreerd op ~3% van een typisch prijsniveau (ETF's hebben sterk
verschillende prijsniveaus — XLK rond de $200, XLRE rond de $40 — een
uniforme dollartolerantie zou niet kloppen). Belangrijker voorbehoud dan
bij de andere agents: een vast dollarbedrag veroudert sneller dan bijv.
een rentepercentage, omdat ETF-prijsniveaus over maanden kunnen wegdriften
— een goede kandidaat voor jouw eigen latere finetuning.

**Waar de deep-dive over gaat:** duidt wat een significante prijsbeweging
in een sector betekent — alleen als de cijfers dat rechtvaardigen.

**Onderbouwing (jouw eigen voorbeeld, letterlijk gebouwd):** bij een
trigger berekent Python (`src/analysis/relative_strength.py`) de
**relatieve sterkte** van die sector t.o.v. de S&P 500 (via SPY) — het
verschil tussen de dagverandering van de sector-ETF en die van SPY.
Positief = de sector outperformt de brede markt (mogelijk rotatie
ernaartoe), negatief = underperformt (mogelijk rotatie ervandaan). Dit
onderscheidt een sector-specifieke beweging van een bredere marktbeweging
(als de hele markt 3% daalt, is een sector die ook 3% daalt NIET aan het
roteren, ondanks de trigger) — precies het "XLB daalt t.o.v. S&P 500"
-voorbeeld waarmee dit agent is afgestemd. SPY wordt maar één keer
opgehaald per deep-dive, ook als meerdere sectoren tegelijk triggeren.

**Bijzonderheid:** één plat domain (`sector`), net als currency's drie
FX-paren — geen per-ticker-namespacing nodig zoals bij equity, want elke
sector-ETF heeft van nature een unieke metric_key (geen collision-risico).

## Commodity agent (`agents/commodity_agent.py`)

**Wat het volgt:** 10 grondstoffen via Alpha Vantage, 1-op-1 overgenomen
van `analyst_agent.ai`'s bestaande `SUPPORTED_COMMODITIES`-lijst (geen
eigen selectie) — inclusief koper, relevant voor DD's eigen ERO
Copper-positie. Elk gezien als "vers" tot 40 dagen oud (maandelijkse data,
zelfde keuze als `analyst_agent.ai` voor dit endpoint):

| Metric | Grondstof |
|---|---|
| WTI | Ruwe olie (WTI) |
| Brent | Ruwe olie (Brent) |
| Natural gas | Aardgas |
| Copper | Koper |
| Aluminum | Aluminium |
| Wheat | Tarwe |
| Corn | Maïs |
| Cotton | Katoen |
| Sugar | Suiker |
| Coffee | Koffie |

**Wanneer het triggert:** op de ruwe prijs (zelfde delta-mechanisme als de
andere agents). Tolerances zijn hier **minder zeker** dan bij sector_agent
— grondstofprijzen/eenheden (dollar/vat, dollar/pond, dollar/bushel, ...)
zijn hier niet met zekerheid geverifieerd tegen actuele marktdata. Nog
sterker een kandidaat voor jouw eigen latere finetuning dan de andere
agents.

**Waar de deep-dive over gaat:** duidt wat een significante prijsbeweging
betekent — alleen als de cijfers dat rechtvaardigen.

**Onderbouwing:** bij een trigger berekent Python
(`src/analysis/moving_average_deviation.py`) de procentuele afwijking van
de huidige prijs t.o.v. het 6-maands-gemiddelde — een gevestigd, eenvoudig
technisch-analyse-concept (mean reversion/trend-sterkte). Bijzonderheid:
de historische punten voor dit gemiddelde zitten al in dezelfde
API-respons als de huidige prijs (Alpha Vantage's commodity-endpoint geeft
een lijst terug, geen los kwartaal/dagcijfer) — kost dus geen extra
databron t.o.v. de andere modellen, wel een extra API-call per grondstof
op deep-dive-tijd.

**Bijzonderheid:** dit is de eerste agent met een databron die ECHT geen
overlap heeft met sectie B/C.1-C.3 (prijzen van fysieke grondstoffen,
i.p.v. rentes/koersen/bedrijfsfundamentals) — zie ook `docs/roadmap.md`
C.4's eigen bewoording. Supply-chain-signalen (bijv. een mijnverstoring)
horen bewust NIET hier — dat is kwalitatief/nieuws-vormig en hoort bij de
nog te bouwen news monitor agent (sectie D).

## Belangrijk voorbehoud, voor alle zes agents

Alle tolerances in de tabellen hierboven zijn **illustratieve
plaatshouders** — geen door DD gevalideerde drempels. Welk absoluut niveau
of welke afwijking "significant genoeg" is, staat bewust nog open (zie
`docs/roadmap.md` sectie H). Pas ze aan zodra daar een onderbouwd antwoord
op is.
