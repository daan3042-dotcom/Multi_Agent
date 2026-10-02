<!-- Ongewijzigde kopie van DD's upload van 02-10-2026 (concept 3, DD's kant compleet). Niet bewerken: de vergelijking met v0 en de vragen staan in docs/causal-graph-vergelijking.md. -->
# Causale Graaf — de economische machine, expliciet

**Status: CONCEPT, DD's kant compleet.** Opgebouwd
uit het interview met DD op 30-09 en 01-10-2026: drie episodes
(2020–2022, 2008, 2023–2024), vier blokken pijlen en drie scenario's.
Wat nog ontbreekt voordat dit v0 mag heten: de blinde versie van de
partner en de open punten onderaan. Zie `docs/roadmap.md`, sectie 1.10.

Alle inhoud komt uit DD's eigen antwoorden. Waar een meetreeks of
agent-koppeling een voorstel is en niet door DD genoemd, staat dat erbij.

## Waarom dit bestand bestaat

Zonder gedeeld model produceert elke domain agent zijn eigen
vrijzwevende analyse. De currency agent kan dan stilzwijgend het
tegendeel beweren van de monetary agent zonder dat iemand het merkt — de
synthesizer plakt het dicht met vloeiend Nederlands. Met een gedeelde
graaf wordt tegenstrijdigheid een **meetbaar conflict op een knoop** in
plaats van een stijlkwestie.

## Wat dit bestand NIET is

- **Geen Bayesiaans netwerk.** Nu alleen de structuur: welke knopen,
  welke pijlen, welke richting, welke vertraging.
- **Geen volledig model van de economie.** 15 tot 25 knopen is genoeg.
- **Geen lijst van alles wat we meten.** Een knoop is een *concept*, niet
  een reeks. De reeks staat in de metric-kolom.

---

## Knopen (23)

| id | Knoop | Wat het is | Waarneembare metric(s) | Bediend door (concept) |
|---|---|---|---|---|
| `external_shock` | Externe schok en aanbodverstoring | Gebeurtenis van buiten de economie die vraag of aanbod verstoort (pandemie, geblokkeerde handelsroute, mislukte oogst) | Geen vaste reeks; gebeurtenis | news *(nog te bouwen)* |
| `growth` | Economische activiteit | Hoeveel er geproduceerd, geïnvesteerd en gebouwd wordt; bevat bedrijfsinvesteringen en huizenmarkt | *open — partner* | economic *(deels)* |
| `household_balance` | Balans van huishoudens | Koopkracht, spaarbuffer en vermogensschade. Bepaalt of de vraag na een schok direct terugkomt of jaren nodig heeft | Spaarquote (DD); CPI YoY tegenover inkomen | niemand |
| `labor_market` | Arbeidsmarkt | Krapte of zwakte van de arbeidsmarkt | Werkloosheidsaanvragen, werkloosheid tegenover U*, banenrevisies (DD) | economic |
| `inflation` | Inflatie | Stijging van het algemene prijspeil, inclusief inflatieverwachtingen | CPI, core CPI, PCE (DD) | *controleren* |
| `policy_rate` | Beleidsrente | Niveau én verandering van de Fed-rente; dat zijn twee verschillende werkingen | FEDFUNDS | monetary_policy |
| `stimulus_vs_damage` | Stimulus ten opzichte van de schade | Hoeveel nieuw geld er de economie in gaat, afgezet tegen hoeveel er werkelijk kapot is | Netto groei van de Fed-balans, TGA, stimuluspakketten, belastingverlagingen; rente en werkloosheid vóór de schok (DD) | niemand |
| `policy_room` | Beleidsruimte | Startpositie van rente en inflatie; bepaalt of een stap vanuit neutraal of uit nood komt | Inflatie tegenover 2%, renteniveau (DD) | monetary_policy *(deels)* |
| `policy_expectation` | Beleidsverwachting en verrassing | Wat de markt denkt dat de Fed gaat doen, en het verschil met wat er gebeurt | FedWatch, FOMC-speeches, forward guidance (DD) | monetary_policy *(deels)* |
| `fiscal` | Begroting en staatsschuld | Tekort, schuldgroei en rentelasten van de overheid; vertrouwen in de houdbaarheid | Tekort, schuldgroei jaar-op-jaar, schuld/bbp, rentelasten, bid-to-cover op veilingen (DD) | niemand |
| `debt_buildup` | Schuldopbouw | Gemak van lenen en schuld ten opzichte van bbp bij huishoudens en bedrijven | Uitstaande huishoudschuld, bedrijfsschuld, uitleencapaciteit grote banken (DD) | niemand |
| `collateral_prices` | Assetprijzen als onderpand | Prijzen van bezittingen waar leningen op rusten (huizen) | *open* | niemand |
| `financial_institutions` | Financiële instellingen en funding | Gezondheid van banken en verzekeraars; werking van de interbancaire markt | *open — partner* | financial *(deels)* |
| `credit_conditions` | Kredietcondities en financieringskosten | Hoe duur en hoe moeilijk lenen is | SOFR-spreads, yield curve (DD); NFCI en high-yield spread (bestaan al) | financial |
| `corporate_strength` | Balanssterkte en kapitaalkracht van bedrijven | Of bedrijven hun schuld kunnen dragen en ruimte hebben om te investeren | Free cash flow, schuldpositie (DD) | equity (adapter) |
| `long_rate` | Lange rente | Tienjaarsrente; gedreven door beleidsverwachting, inflatieverwachting en vertrouwen in de overheid | DGS10 | monetary_policy |
| `dollar` | Dollar | Sterkte van de dollar; twee regimes (renteverschil in rustige tijden, vlucht in een crisis) | DXY, valutaparen zoals BRL/USD (DD) | currency |
| `growth_driver` | Structurele groeidrijver | Technologiegolf of andere katalysator die capex en winstgroei aanjaagt | Capex in kwartaalcijfers van de grootste bedrijven (DD) | equity, sector *(deels)* |
| `valuation` | Waardering van toekomstige kasstromen | Wat toekomstige winst vandaag waard is | *open* | niemand |
| `tail_uncertainty` | Onzekerheid over het uiterste | Hoe onzeker de markt is over hoe erg (of hoe goed) het nog wordt. Het draaipunt voor aandelen | Sleutelcijfer over de piek (DD); VIX *(voorstel)* | financial *(deels)* |
| `sentiment_flows` | Sentiment en kapitaalstromen | Marktbreed sentiment, rotatie tussen sectoren en gedwongen verkoop | Niet met één datapunt te meten (DD); kruisreactie NQ, obligaties, DXY | sector *(deels)* |
| `equities` | Aandelen | Aandelenmarkt, met tech/NQ als gevoeligste deel | NQ, sector-ETF's | sector, equity |
| `commodities` | Energie en grondstoffen | Prijzen van energie en grondstoffen | Spotprijzen (DD) | commodity *(alleen monitoring)* |

## Pijlen (39)

**Richting**: `+` (versterkt), `−` (dempt). **Zekerheid** is DD's eigen
inschatting. `open` = niet ingevuld, vraag voor de partner.

### A. Beleid en inflatie

| # | Van | Naar | Richting | Vertraging | Hoe zie je dat hij werkt | Zekerheid |
|---|---|---|---|---|---|---|
| A1 | `external_shock` | `growth` | − | direct | open | midden |
| A2 | `external_shock` | `commodities` | + | direct | Verstoorde handelsweg → spotprijzen van de betrokken grondstoffen | hoog |
| A3a | `commodities` | `inflation` (headline) | + | weken | Benzineprijs zit rechtstreeks in de CPI | hoog |
| A3b | `commodities` | `inflation` (core) | + | 6–12 mnd | Transport- en productiekosten → core CPI, PCE | hoog |
| A4 | `stimulus_vs_damage` | `inflation` | + | 6–18 mnd | Belastingverlagingen, QE, TGA, stimuluspakketten; rente en werkloosheid vóór de schok | hoog |
| A5 | `inflation` | `policy_rate` | + | 3–9 mnd | Inflatiecijfers → FOMC-speeches, forward guidance, FedWatch | midden |
| A6 | `labor_market` | `policy_rate` | + (zwakkere arbeidsmarkt → lagere rente) | 3–12 mnd | Werkloosheidsaanvragen, werkloosheid tegenover U*, banenrevisies → reactie Fed | midden |
| A7 | `policy_rate` (niveau) | `growth` | − | 6–18 mnd | Duurdere leningen → minder lenen → minder activiteit | richting hoog; sterkte en timing midden |
| A8 | `inflation` | `household_balance` | − | direct | Prijzen in de winkel stijgen vóórdat het in CPI YoY staat | hoog |
| A9 | `commodities` | `growth` | − | direct | Transport wordt onrendabel, ladingen blijven liggen | midden |

### B. Krediet

De keten B5 → B6 → B7 duurt samen één tot tweeënhalf jaar van
renteverhoging tot oplopende werkloosheid (bevestigd door DD).

| # | Van | Naar | Richting | Vertraging | Hoe zie je dat hij werkt | Zekerheid |
|---|---|---|---|---|---|---|
| B1 | `policy_rate` | `debt_buildup` | − (lage rente → meer schuld) | jaren | Rente → groei van staatsschuld en bedrijfsschuld | hoog |
| B2 | `collateral_prices` | `debt_buildup` | + (lus, beide kanten op) | open | Uitstaande huishoudschuld, uitleencapaciteit grote banken | hoog |
| B3 | `collateral_prices` | `financial_institutions` | + (dalende prijzen → verliezen) | open | open | midden |
| B4 | `financial_institutions` | `credit_conditions` | + (verliezen → krapper) | open | open | hoog |
| B5 | `policy_rate` | `credit_conditions` | + | direct | Rente is de prijs van geld | hoog |
| B6 | `credit_conditions` | `growth` | − | 3–12 mnd | SOFR-spreads, yield curve | hoog |
| B7 | `growth` | `labor_market` | + | 6–18 mnd | open | midden |
| B8 | `household_balance` | `growth` | + | jaren bij schade, maanden bij buffer | De aard van de katalysator bepaalt het | hoog |

### C. Rente, begroting en dollar

| # | Van | Naar | Richting | Vertraging | Hoe zie je dat hij werkt | Zekerheid |
|---|---|---|---|---|---|---|
| C1 | `policy_expectation` | `long_rate` | + | direct (vooraf ingeprijsd) | Guidance of besluit → reactie obligatiemarkt. Werkt ook omlaag: zwakkere groei → verwachte verlaging → lagere lange rente | hoog |
| C2 | `inflation` | `long_rate` | + | direct via verwachtingen; gevolgen merkbaar na 1–3 jaar | Inflatieverwachtingen | midden |
| C3 | `fiscal` | `long_rate` | + | direct als het vertrouwen kantelt, anders 6–18 mnd | Tekort, schuldgroei jaar-op-jaar, schuld/bbp per datarelease; bid-to-cover op veilingen | hoog |
| C4 | `long_rate` | `fiscal` | + (lus met C3) | ±12 mnd | Rentelasten stijgen pas bij herfinanciering van aflopende schuld en bij nieuwe schuld | hoog |
| C5 | `long_rate` | `credit_conditions` | + | direct voor nieuwe leningen | Obligatierente → rentes → kosten van leningen | hoog |
| C6 | `policy_rate` / `long_rate` (renteverschil met andere landen) | `dollar` | + | direct | Rustige tijden: dollar beweegt mee met de Amerikaanse rente en renteverwachting | midden *(bevestigd door DD op voorstel)* |
| C7 | `sentiment_flows` (stress) | `dollar` | + | direct | Stijgende dollar bij hoge stress, rente omlaag | hoog |
| C8 | `dollar` | schuldlast en inflatie opkomende landen *(buiten de graaf)* | + | 6–18 mnd | Valutaparen (BRL/USD); heeft het land dollarschuld? | hoog |
| C9 | `equities` | buitenlandse markten *(buiten de graaf)* | + | direct | Hoeveel het buitenland in Amerikaanse aandelen belegd heeft | midden |
| C10 | `fiscal` (stress op de obligatiemarkt) | `stimulus_vs_damage` (Fed koopt op) | + | open | Telt alleen als de Fed-balans netto groeit; herbeleggen van aflossingen is geen nieuw geld | laag *(open — partner)* |

### D. Aandelen

Aandelen reageren als eerste: via onzekerheid (D3) en waardering (D1),
vóórdat er een cijfer of een Fed-besluit is.

| # | Van | Naar | Richting | Vertraging | Hoe zie je dat hij werkt | Zekerheid |
|---|---|---|---|---|---|---|
| D1 | `policy_rate` / `policy_expectation` (verandering) | `valuation` → `equities` | − | direct | open | hoog |
| D2 | `growth` | `equities` (via winst) | + | traag | open | midden |
| D3 | `tail_uncertainty` | `equities` | − | direct | Sleutelcijfer over de piek: inflatie in oktober 2022, ernst van de crisis in maart 2009 | hoog |
| D4 | `policy_rate` (stap uit nood) | `tail_uncertainty` | + | direct | Abrupte stap die de markt niet zag aankomen | hoog |
| D5 | `growth_driver` | `equities` | + | kwartaal op kwartaal; direct bij een verrassing | Capex in de kwartaalcijfers | hoog |
| D6 | `corporate_strength` | `growth_driver` (wie profiteert) | + | direct bij directe investeringen, langer bij indirecte | open | midden |
| D7 | `sentiment_flows` | `equities` | + | direct | Niet met één datapunt te meten | hoog |
| D8 | `household_balance` (omlaag) | `sentiment_flows` (gedwongen verkoop) | − | direct bij extreme cijfers, anders jaren | open | midden |
| D9 | `long_rate` (hoog niveau of snelle stijging) | `equities` | − | direct bij een snelle stijging | Kan worden overstemd door `growth_driver` | midden |
| D10 | `credit_conditions` | `corporate_strength` → `equities` | − | direct | open | hoog |
| D11 | `growth_driver` | `growth` | + | 3–12 mnd | Capex is investering; minder capex → geschrapte projecten → banen na minimaal 12 mnd | midden |

## Voorwaardelijke pijlen

Dit is de kern van DD's denken: veel pijlen werken alleen onder een
voorwaarde. Elke voorwaarde moet nog een meetbaar getal worden voordat de
pijl op de back-fill getoetst kan worden.

| Pijl | Voorwaarde |
|---|---|
| A4 | Werkt alleen als `household_balance` intact is (geen vermogensschade) en de vraag snel terugkomt. 2020: ja. 2009: nee. |
| A5 tegenover A6 | Bij stagflatie (inflatie omhoog, economie zwakker) wijzen ze tegen elkaar in. De Fed wacht dan tot de richting duidelijk is. Zekerheid laag. |
| A7 | Werkt sterker als huishoudens en bedrijven weinig buffer hebben. Faalde in 2022 door de buffers uit 2020–2021. |
| A7 en D1 | Rente werkt op twee manieren: het niveau traag via kosten (A7), de verandering direct via waardering en onzekerheid (D1). |
| A9 en A3 | Bij een olieschok verzwakt eerst de activiteit (A9) en verschijnt de inflatie daarna pas breed in de cijfers (A3b). |
| C2 | Werkt alleen als de inflatieverwachtingen meebewegen. |
| C3 | Direct als het vertrouwen kantelt, anders traag. |
| C6 en C7 | Twee regimes voor de dollar: renteverschil in rustige tijden, vlucht naar veiligheid in een crisis. Welke wint is een open punt. |
| C10 | Alleen bij netto groei van de Fed-balans. Dan loopt de lus door: tekort → hogere rente → Fed koopt op → inflatie (A4) → hogere lange rente (C2). |
| D3 | Werkt in beide richtingen: verdwijnen van onzekerheid geeft een bodem, twijfel over de drijver beëindigt een stijgende markt. |
| D4 | Het teken van een rentestap hangt af van `policy_room`: vanuit neutraal goed voor aandelen, uit nood slecht, welke kant de stap ook op gaat. |
| D8 | Vertraging hangt af van hoe extreem de situatie al is. |
| D9 | Wordt overstemd als `growth_driver` sterk is (2023–2024). |

## Regels voor agents (geen knopen)

Inzichten die te fijnmazig zijn voor de graaf, maar niet verloren mogen
gaan. Ze horen in de instructies van de betreffende agent.

- **Winnaars via de waardeketen (sector, equity).** Bij een schok: bepaal
  waar een bedrijf in de keten zit en welk deel van de keten de marge
  pakt. Voorbeeld van DD: raffinaderijen bij een olieschok.
- **Reactie lezen over meerdere markten (synthesizer).** Na een
  beleidsbesluit: wat doen NQ, obligaties en DXY tegelijk, en past dat
  bij het eigen beeld?
- **Eerst de aard van de schok vaststellen (news, synthesizer).** Is het
  financieel of niet, sector of macro? Dat bepaalt of het herstel maanden
  of jaren duurt (B8).

## Dekking per agent (concept — controleren tegen `docs/agents.md`)

| Agent | Bedient knopen | Gaten |
|---|---|---|
| monetary_policy | `policy_rate`, `long_rate`, deels `policy_expectation` en `policy_room` | Marktverwachting (FedWatch) |
| currency | `dollar` | Renteverschil met andere landen |
| financial | `credit_conditions`, deels `tail_uncertainty` en `financial_institutions` | Funding, gezondheid van instellingen |
| sector | `equities` (relatief), deels `sentiment_flows` en `growth_driver` | — |
| commodity | `commodities` | Alleen monitoring in cohort 0 |
| equity (adapter) | `corporate_strength`, `growth_driver` per ticker | Koppeling nog niet gebouwd |
| economic *(lean, nog te bouwen)* | `labor_market`, deels `growth` | Activiteit breder dan arbeidsmarkt |
| news *(nog te bouwen)* | `external_shock` | — |

**Knopen zonder agent:** `household_balance`, `stimulus_vs_damage`,
`fiscal`, `debt_buildup`, `collateral_prices`, `valuation`, en mogelijk
`inflation` (nagaan welke reeksen de monetary policy agent volgt).

## Open punten / oneens

**Voor de partner (DD gaf "weet ik niet" of "open")**
- **Dollar bij stress.** Wat bepaalt of de dollar stijgt (C7) of daalt als de stress uit Amerika zelf komt? In scenario 2 (mislukte veiling) liet DD hem stijgen, terwijl hij in april 2025 daalde. In scenario 3 (capex omlaag) laat DD hem dalen via de renteverwachting (C6), terwijl C7 een stijging geeft.
- **Stagflatie.** Wat doet de Fed als inflatie en zwakte tegelijk spelen? DD: wachten, met lage zekerheid.
- **De begrotingslus (C10).** Loopt de lus tekort → Fed koopt op → inflatie → hogere rente door, en wanneer?
- **Schade herkennen.** Aan welke cijfers zie je op het moment zelf dat een schok de balans van huishoudens beschadigt? DD: niet aan één of twee cijfers op te hangen.
- Bewijs voor A1, B7, D1, D2, D6, D8 en D10.
- Vertraging en bewijs voor B2, B3 en B4.
- Meetreeksen voor `growth`, `collateral_prices`, `financial_institutions` en `valuation`.

**Structureel**
- C8 en C9 wijzen naar het buitenland, maar daar is geen knoop voor. Eigen knoop, of buiten de graaf laten?
- `sentiment_flows` is volgens DD niet met één datapunt te meten. Zonder meetreeks is de knoop niet toetsbaar.
- Alle drie de episodes zijn Amerikaans; twee ervan zijn crises. Een niet-Amerikaanse episode ontbreekt.
- Het kredietblok (B) is niet met een scenario getoetst; DD kent 2008 naar eigen zeggen minder goed.
- De blinde versie van de partner bestaat nog niet. De verschillen daarmee horen hier te staan.

---

## Versiebeheer

Vanaf T₀ᵇ (10-11-2026) is deze graaf semi-bevroren. Elke wijziging krijgt
een versienummer hieronder en start effectief een nieuw cohort in de
scoring (roadmap 4.5).

| Versie | Datum | Wat er veranderde | Waarom |
|---|---|---|---|
| concept 1 | 01-10-2026 | Eerste invulling uit interview DD: 23 knopen, 36 pijlen | — |
| concept 2 | 01-10-2026 | Drie scenario's verwerkt: A9, C10 en D11 toegevoegd; A7, C3, C4, C5, D9 aangescherpt; regels voor agents | Scenario-toets |
| concept 3 | 01-10-2026 | D11 ingevuld; DD's kant compleet | — |
| v0 | *(na partner-versie)* | | |
