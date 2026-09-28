# Causale Graaf v0 — de economische machine, expliciet

**Status: v0, vastgelegd op 28-09-2026.** 17 toestandsknopen, 41 pijlen.
Zie "Herkomst en wat dat betekent voor de forward test" hieronder — dit is
GEEN volledig handgeschreven graaf, en dat heeft consequenties die
expliciet vastgelegd moeten blijven.

Hoort bij `docs/roadmap.md` sectie 1.10 (fase 1). Machine-leesbare
tegenhanger: `src/contract/graph.py`.

## Waarom dit bestand bestaat

Zonder gedeeld model produceert elke domain agent zijn eigen
vrijzwevende analyse. De currency agent kan dan stilzwijgend het
tegendeel beweren van de monetary agent zonder dat iemand het merkt — de
synthesizer plakt het dicht met vloeiend Nederlands. Met een gedeelde
graaf wordt tegenstrijdigheid een **meetbaar conflict op een knoop** in
plaats van een stijlkwestie.

De causale structuur is expliciet en door mensen vastgesteld, de
inferentie is deterministisch en reproduceerbaar, en het taalmodel voedt
hem alleen met waarnemingen. Het LLM raakt de kansen nooit aan (zie
`docs/architecture.md`, 1.8).

## Herkomst en wat dat betekent voor de forward test

De oorspronkelijke opzet was: handwerk door DD en zijn partner, geen
LLM. Dat is op 28-09-2026 bewust losgelaten — er ís nog geen partner, DD
bouwt alleen een basis, en het uitgangspunt is "eerst een werkende basis,
daarna optimaliseren".

Deze v0 is daarom tot stand gekomen als: een knopenvoorstel van Claude →
herzien en aangescherpt door een ChatGPT-sessie (die de driedeling
observaties/toestanden/outputs introduceerde en de 17 knopen vaststelde)
→ door Claude uitgewerkt tot pijlen, meetbaarheid en toetsbaarheid.

**Wat dat kost, expliciet:** wat er over zes maanden forward-getest
wordt, is niet uitsluitend DD's eigen economische wereldbeeld maar deels
het gemiddelde wereldbeeld van twee taalmodellen. Dat is geen ramp — de
structuur hieronder is grotendeels standaard macro-economische
transmissie, geen exotische these — maar het betekent wél dat een goed
kalibratieresultaat in mei 2027 **niet** bewijst dat DD een edge heeft.
Het bewijst hooguit dat een conventioneel transmissiemodel plus
LLM-oordeel gekalibreerd is.

De plek waar een echte, eigen these alsnog kan binnenkomen is
"Open punten" onderaan, plus elke wijziging die DD zelf aanbrengt vóór de
freeze. Elke door DD zelf veranderde of toegevoegde pijl wordt daar
gemarkeerd met `[DD]`, zodat achteraf te scheiden is wat van wie kwam.

## Drie lagen — en waarom dit de belangrijkste ontwerpkeuze is

Zonder deze scheiding wordt de graaf een verzameling indicatoren in
plaats van een model.

```
LAAG 1 — OBSERVATIES        CPI, core PCE, NFP, ICSA, NFCI, VIX, HY OAS,
(wat we ophalen)            DGS10, DTWEXBGS, WTI, koper, ETF-koersen, ...
                                          |
                                          v
LAAG 2 — TOESTANDEN         de 17 knopen hieronder. Niet direct
(wat we schatten)           waarneembaar; geschat uit meerdere observaties.
                                          |
                                          v
LAAG 3 — OUTPUTS            sectorrotatie, asset returns, instrument-
(wat eruit komt)            voorspellingen (NQ/ZN/CL/6E), synthese-tekst
```

Concreet:

- `CPILFESL` is **geen knoop**. Het is één observatie waaruit de toestand
  `inflation_persistence` geschat wordt, samen met core PCE en
  dienstenprijzen.
- **Sectorrotatie is geen knoop.** Het is een output. De sector agent is
  een cross-sectionele interpreet van de toestand, geen bediener van een
  eigen knoop. Zie "Dekking per agent".
- **`headline_inflation` is geen knoop.** Het is een observatie waaruit
  zowel `inflation_persistence` als `inflation_expectations` geschat
  worden.

## Wat dit bestand NIET is

- **Geen Bayesiaans netwerk.** De kansen op de pijlen komen niet uit dit
  bestand. Zie roadmap 1.10: met ~10–15 macrocycli in bruikbare data
  blijven pijlkansen jarenlang prior-gedomineerd.
- **Geen regime-afhankelijke gewichten.** Het ChatGPT-voorstel stelde
  voor om per pijl een `sign` per regime vast te leggen
  (`supply_shock: -0.9`, `demand_expansion: 0.4`). Dat is bewust NIET
  overgenomen in v0: dat zijn drie parameters per pijl in plaats van
  één, geschat op dezelfde ~12 onafhankelijke episodes, en regime als
  latente variabele staat als 3.3 expliciet post-T₀. Het veld
  `regime_dependent` (ja/nee) staat er wél in, zodat later bekend is
  welke pijlen kandidaat zijn — dat kost niets en is niet in te halen.
- **Geen numerieke confidence.** `0.85` suggereert precisie die er niet
  is. Zekerheid is ordinaal: hoog / midden / laag.

## Het pijlbudget, en waarom 41

Niet het aantal knopen is de bindende beperking maar het aantal pijlen,
afgezet tegen het aantal **onafhankelijke episodes** in de data.

Elke pijl wordt straks deterministisch getoetst op de back-fill
(lead-lag-correlatie, roadmap 1.10). Bij 41 toetsen op p<0,05 verwacht je
~2 valse treffers puur door toeval; bij 100 toetsen ~5. En de effectieve
steekproef voor een macro-pijl is niet het aantal dagpunten maar het
aantal cycli: ~10–15 in bruikbare historie.

**Werkregel:** houd het aantal pijlen onder ~5× het aantal macrocycli,
dus onder de ~60. 41 zit daar comfortabel onder, met ruimte voor de
pijlen die DD zelf nog toevoegt.

---

## Laag 2 — de 17 toestandsknopen

"Hoog" legt vast welke kant op de as staat. Zonder die kolom klopt het
teken van de pijlen niet.

| # | id | Knoop | "Hoog" betekent | Observaties waaruit geschat | Primaire agent |
|---|---|---|---|---|---|
| 1 | `growth` | Economische groei | harder groeien | PAYEMS, INDPRO, GDPC1 | economic |
| 2 | `labor_tightness` | Arbeidsmarktkrapte | moeilijker personeel vinden | UNRATE, ICSA, JOLTS-vacatures | economic |
| 3 | `wage_growth` | Loongroei | arbeidskosten stijgen sneller | AHETPI, ECI | economic |
| 4 | `inflation_persistence` | Inflatiepersistentie | onderliggende prijsdruk hoger | core CPI (CPILFESL), core PCE (PCEPILFE), dienstenprijzen, trimmed mean | economic |
| 5 | `inflation_expectations` | Inflatieverwachtingen | markt rekent op meer inflatie | T5YIE, T10YIE, T5YIFR, MICH | monetary |
| 6 | `policy_stance` | Beleidsstance | restrictiever t.o.v. wat de economie vraagt | FEDFUNDS/DFF vs. Taylor-impliciet, reële beleidsrente | monetary |
| 7 | `policy_expectations` | Verwachte beleidskoers | markt prijst meer verkrapping in | DGS2, fed funds futures | monetary |
| 8 | `liquidity` | Systeemliquiditeit | meer liquiditeit beschikbaar | WALCL, RRP, TGA, bankreserves, M2 | monetary |
| 9 | `term_premium` | Termijnpremie | meer compensatie voor looptijdrisico | ACM term premium (NY Fed), T10Y2Y als ruwe proxy | monetary |
| 10 | `financial_conditions` | Financiële condities | krapper | NFCI, ANFCI | financial |
| 11 | `credit_risk_premium` | Kredietrisicopremie | markt vraagt meer voor kredietrisico | HY OAS (BAMLH0A0HYM2), IG OAS | financial |
| 12 | `risk_appetite` | Risicobereidheid | meer bereidheid risico te dragen | VIX (invers), HY OAS (invers), XLY/XLP | financial |
| 13 | `dollar` | Dollarsterkte | sterkere USD | DTWEXBGS, EUR/USD, USD/JPY, GBP/USD | currency |
| 14 | `energy_prices` | Energieprijzen | duurdere energie | WTI, Brent, Henry Hub gas | commodity |
| 15 | `industrial_metals` | Industriële metalen | duurder koper/aluminium | koper, aluminium | commodity |
| 16 | `earnings_growth` | Winstgroei | winsten groeien sneller | S&P 500 EPS, equity-adapter-fundamentals | equity |
| 17 | `equity_valuation` | Aandelenwaardering | duurder t.o.v. verwachte kasstromen | earnings yield − DGS10, reverse-DCF uit de adapter | equity |

### Wat er bewust NIET als knoop in zit

| Overwogen | Waarom niet | Waar het wél zit |
|---|---|---|
| `headline_inflation` | observatie, geen toestand | input voor knoop 4 en 5 |
| `consumer_demand` | grotendeels dezelfde toestand als `growth`, met dezelfde observaties | opgenomen in knoop 1 |
| `sector_rotation` | **output**, geen oorzaak — rotatie is wat je zíét als `risk_appetite` of `growth` beweegt | laag 3, sector agent |
| `output_gap` | niveau vs. tempo; overlapt met 1 en 2, zit al in de Taylor Rule | conditie op pijl `growth → inflation_persistence` |
| `fiscal_impulse` | kwartaalcadans, geen agent op de roadmap die hem ooit bedient | — |
| `bank_lending_standards` | kwartaalenquête, grotendeels al in 10 en 11 | Open punten |
| `food_ags` | beweegt op weer en oogsten, niet op de machine; zat er alleen in omdat de commodity agent de reeksen toevallig ophaalt | — |
| `rate_differential` | echte kandidaat, maar vraagt ECB/BOJ/BOE-rentes die we niet hebben | Open punten |

---

## Laag 2 — de 41 pijlen

**Kolommen.** *Teken*: `+` = beide dezelfde kant op, `−` = tegengesteld,
t.o.v. de "hoog"-definitie van beide knopen. *Vertraging*: waar de
lead-lag-toets naar kijkt. *Sterkte* en *zekerheid*: onze eigen
inschatting, niet die van de literatuur. *Toetsbaar*: of de pijl
betekenisvol op de back-fill te toetsen is — zie "Wat niet toetsbaar is"
hieronder, dit is geen detail.

### A. Reële economie

| # | Van | Naar | Teken | Vertraging | Sterkte | Zekerheid | Toetsbaar | Hoe je ziet dat hij werkt |
|---|---|---|---|---|---|---|---|---|
| 1 | `growth` | `labor_tightness` | + | 1–6 mnd | sterk | hoog | ja | PAYEMS-versnelling gaat vooraf aan dalende ICSA |
| 2 | `labor_tightness` | `wage_growth` | + | 3–12 mnd | midden | midden | ja | lage UNRATE gaat vooraf aan stijgende AHETPI YoY |
| 3 | `wage_growth` | `inflation_persistence` | + | 2–4 kw | midden | midden | zwak | AHETPI YoY loopt vooruit op core services CPI |
| 4 | `growth` | `inflation_persistence` | + | 2–4 kw | midden | midden | zwak | sterker bij positieve output gap; conditioneel |
| 5 | `financial_conditions` | `growth` | − | 2–6 kw | sterk | hoog | zwak | NFCI-piek gaat vooraf aan dalende INDPRO/PAYEMS |
| 6 | `financial_conditions` | `labor_tightness` | − | 2–4 kw | midden | midden | zwak | NFCI-piek gaat vooraf aan stijgende ICSA |

### B. Inflatie en de beleidsreactie

| # | Van | Naar | Teken | Vertraging | Sterkte | Zekerheid | Toetsbaar | Hoe je ziet dat hij werkt |
|---|---|---|---|---|---|---|---|---|
| 7 | `inflation_persistence` | `policy_stance` | + | 1–3 mnd | sterk | hoog | ja | core PCE-versnelling gaat vooraf aan een hogere Taylor-afwijking |
| 8 | `inflation_expectations` | `policy_stance` | + | 1–3 mnd | midden | midden | ja | stijgende T5YIFR gaat vooraf aan hawkisher beleid |
| 9 | `inflation_persistence` | `inflation_expectations` | + | 1–6 mnd | midden | midden | ja | core-verrassingen trekken breakevens mee |
| 10 | `labor_tightness` | `policy_stance` | + | 1–3 mnd | midden | midden | ja | dual mandate; UNRATE zit al in de Taylor Rule |
| 11 | `energy_prices` | `inflation_expectations` | + | 0–3 mnd | midden | midden | ja | benzineprijs trekt korte breakevens en MICH mee |

### C. Beleid naar markten

| # | Van | Naar | Teken | Vertraging | Sterkte | Zekerheid | Toetsbaar | Hoe je ziet dat hij werkt |
|---|---|---|---|---|---|---|---|---|
| 12 | `policy_stance` | `policy_expectations` | + | 0–1 wk | sterk | hoog | **nee** | gelijktijdig; alleen zichtbaar rond FOMC-verrassingen |
| 13 | `policy_stance` | `financial_conditions` | + | 0–4 wk | sterk | hoog | zwak | verkrapping gaat vooraf aan stijgende NFCI |
| 14 | `policy_expectations` | `financial_conditions` | + | 0–2 wk | sterk | hoog | zwak | DGS2 loopt vooruit op NFCI — markt wacht niet op de Fed |
| 15 | `policy_stance` | `liquidity` | − | 1–2 kw | midden | laag | ja | alleen actief als het balansbeleid meebeweegt; QT ≠ rentebeleid |
| 16 | `policy_stance` | `dollar` | + | 0–4 wk | midden | midden | zwak | relatief restrictiever VS-beleid steunt USD |
| 17 | `policy_expectations` | `dollar` | + | 0–2 wk | sterk | midden | zwak | DGS2-bewegingen trekken DTWEXBGS mee |

### D. Financiële condities, krediet en risico

| # | Van | Naar | Teken | Vertraging | Sterkte | Zekerheid | Toetsbaar | Hoe je ziet dat hij werkt |
|---|---|---|---|---|---|---|---|---|
| 18 | `liquidity` | `financial_conditions` | − | 1–3 mnd | midden | midden | ja | dalende WALCL/reserves gaan vooraf aan stijgende NFCI |
| 19 | `liquidity` | `risk_appetite` | + | 1–3 mnd | midden | laag | ja | reserve-groei gaat vooraf aan dalende VIX |
| 20 | `term_premium` | `financial_conditions` | + | 0–4 wk | midden | midden | **nee** | definitie-overlap, zie hieronder |
| 21 | `term_premium` | `equity_valuation` | − | 0–4 wk | midden | midden | zwak | hogere discontovoet drukt long-duration-waarderingen |
| 22 | `credit_risk_premium` | `financial_conditions` | + | 0–2 wk | sterk | hoog | **nee** | HY OAS is een NFCI-component; grotendeels definitie |
| 23 | `financial_conditions` | `credit_risk_premium` | + | 0–4 wk | midden | midden | **nee** | feedback-richting, niet identificeerbaar |
| 24 | `financial_conditions` | `risk_appetite` | − | 0–2 wk | sterk | hoog | **nee** | VIX en spreads zitten in beide; grotendeels definitie |
| 25 | `risk_appetite` | `financial_conditions` | − | 0–2 wk | midden | midden | **nee** | feedback-richting |
| 26 | `risk_appetite` | `credit_risk_premium` | − | 0–2 wk | sterk | midden | **nee** | VIX en HY OAS delen een component |

### E. Dollar, grondstoffen en groei

| # | Van | Naar | Teken | Vertraging | Sterkte | Zekerheid | Toetsbaar | Hoe je ziet dat hij werkt |
|---|---|---|---|---|---|---|---|---|
| 27 | `dollar` | `energy_prices` | − | 0–3 mnd | midden | midden | ja | USD-appreciatie drukt in USD genoteerde olie |
| 28 | `dollar` | `industrial_metals` | − | 0–3 mnd | midden | midden | ja | idem, plus duurder voor buitenlandse kopers |
| 29 | `dollar` | `financial_conditions` | + | 0–4 wk | midden | laag | zwak | vooral buiten de VS; ons NFCI meet de VS |
| 30 | `growth` | `industrial_metals` | + | 0–2 kw | midden | midden | ja | koper als vraagsensor, niet als inflatiesignaal |
| 31 | `financial_conditions` | `industrial_metals` | − | 1–3 kw | midden | laag | zwak | krappere condities drukken industriële vraag |
| 32 | `energy_prices` | `inflation_persistence` | + | 1–3 kw | zwak | laag | zwak | **alleen tweede-ronde-effecten** — zie hieronder |
| 33 | `industrial_metals` | `inflation_persistence` | + | 2–4 kw | zwak | laag | zwak | via productieketens; zwakker dan energie |

### F. Bedrijven en aandelen

| # | Van | Naar | Teken | Vertraging | Sterkte | Zekerheid | Toetsbaar | Hoe je ziet dat hij werkt |
|---|---|---|---|---|---|---|---|---|
| 34 | `growth` | `earnings_growth` | + | 1–2 kw | sterk | hoog | ja | nominale bbp-groei loopt vooruit op omzetgroei |
| 35 | `financial_conditions` | `earnings_growth` | − | 2–4 kw | midden | midden | zwak | hogere rentelasten, lagere investeringen |
| 36 | `earnings_growth` | `equity_valuation` | + | 0–1 kw | midden | midden | zwak | verbeterende winstvooruitzichten verhogen de waarde |
| 37 | `financial_conditions` | `equity_valuation` | − | 0–1 kw | midden | midden | zwak | — |
| 38 | `risk_appetite` | `equity_valuation` | + | 0–2 wk | sterk | midden | **nee** | aandelenkoersen zitten in beide |
| 39 | `equity_valuation` | `risk_appetite` | + | 0–2 wk | midden | laag | **nee** | feedback-richting |
| 40 | `equity_valuation` | `financial_conditions` | − | 0–4 wk | midden | midden | **nee** | aandelenkoersen zijn een NFCI-component |
| 41 | `energy_prices` | `earnings_growth` | ? | 1–2 kw | zwak | laag | zwak | positief voor energiesector, negatief voor de rest — netto omstreden, zie Open punten |

---

## Wat niet toetsbaar is, en waarom dat nu al vastligt

Roadmap 1.10 belooft dat elke pijl deterministisch op de back-fill
getoetst wordt. Dat kan **niet** voor alle 41. Dit nu vastleggen voorkomt
dat de toets straks nepresultaten oplevert die als bevestiging worden
gelezen.

**1. Definitie-overlap (pijlen 20, 22, 24, 26, 38, 40).** De NFCI is een
samengestelde index die kredietspreads, aandelenvolatiliteit en
aandelenkoersen zélf als componenten bevat. Een lead-lag-correlatie
tussen `credit_risk_premium` en `financial_conditions` meet daarom voor
een groot deel dat een getal met zichzelf correleert. Dat levert een
schitterende, betekenisloze uitslag op. Deze pijlen blijven in de graaf
staan omdat ze conceptueel kloppen, maar worden **niet** als bevestigd
geteld. Wie ze ooit echt wil toetsen, moet een NFCI-subindex gebruiken
die de betreffende component uitsluit.

**2. Feedbacklussen (pijlen 23, 25, 39).** De graaf is bewust **geen
DAG**. Bij een lus is de richting niet uit correlatie af te leiden: als
A en B elkaar beïnvloeden, correleren ze op elke lag. Werkregel: per lus
wordt alleen de pijl met de **langste** vertraging getoetst; de korte
tegenpijl staat als structurele aanname in de graaf en krijgt nooit een
"houdt stand".

**3. Gelijktijdigheid (pijl 12).** `policy_stance → policy_expectations`
speelt zich af binnen uren. Op dagdata is dat geen lead-lag maar
gelijktijdige correlatie. Alleen te onderzoeken met een
event-study rond FOMC-data, en dat is post-T₀-werk.

**4. Lange vertragingen (alle pijlen met 2–6 kwartalen).** Met ~12
onafhankelijke episodes in de historie is een 4-kwartaals-pijl in de
praktijk op een handvol waarnemingen getoetst. "Zwak" in de
toetsbaar-kolom betekent: de toets draait, maar een niet-significante
uitslag is geen bewijs tegen de pijl. Alleen een uitslag met het
**verkeerde teken** is informatief.

**5. Meetfout bij pijl 32 (`energy_prices → inflation_persistence`).**
`inflation_persistence` wordt geschat uit **core** CPI/PCE, en core sluit
energie per definitie uit. Deze pijl gaat dus uitsluitend over
tweede-ronde-effecten (energie in transport- en productiekosten die in
de kernprijzen doorsijpelen). Zou hij op headline getoetst worden, dan is
de uitslag opnieuw grotendeels definitie. Dit staat hier omdat het anders
gegarandeerd verkeerd geïnterpreteerd wordt.

**Netto:** van de 41 pijlen zijn er **14 volwaardig toetsbaar**, 17 zwak,
en 10 niet. Dat is geen tekortkoming van de graaf maar van wat data over
een economie kan zeggen — en het is beter om dat nu te weten dan in mei
2027.

## De vier feedbacklussen

Lussen zijn waarom een lineaire macro-analyse dingen mist. Ze staan hier
apart omdat ze niet uit de pijltabel af te lezen zijn.

**Lus 1 — monetaire verkrapping (stabiliserend).**
`inflation_persistence ↑ → policy_stance ↑ → financial_conditions ↑ →
growth ↓ → labor_tightness ↓ → wage_growth ↓ → inflation_persistence ↓`
Doorlooptijd: 6–10 kwartalen. Dit is de lus waar het hele
transmissiemechanisme op rust.

**Lus 2 — financiële stress (versterkend).**
`financial_conditions ↑ → risk_appetite ↓ → credit_risk_premium ↑ →
financial_conditions ↑`
Doorlooptijd: dagen tot weken. Dit is de lus die niet-lineair is: onder
een drempel gebeurt er weinig, erboven versnelt hij. **Let op:** deze lus
loopt volledig over de definitie-overlap uit punt 1 hierboven, dus hij is
niet empirisch te bevestigen met onze huidige reeksen.

**Lus 3 — vermogenseffect (versterkend).**
`equity_valuation ↓ → risk_appetite ↓ → financial_conditions ↑ →
growth ↓ → earnings_growth ↓ → equity_valuation ↓`
Doorlooptijd: kwartalen.

**Lus 4 — grondstofschok (gemengd).**
`energy_prices ↑ → inflation_expectations ↑ → policy_stance ↑ →
financial_conditions ↑ → growth ↓ → industrial_metals ↓`
Dit is de stagflatie-lus. Cruciaal: hij loopt anders als de energieprijs
stijgt door **vraag** (dan samen met sterke groei) dan door **aanbod**
(dan stagflatoir). Onze commodity agent kan dat onderscheid nu niet
maken — zie Open punten.

---

## Laag 3 — outputs

Geen knopen. Wat het systeem produceert nádat de toestand geschat is.

| Output | Geproduceerd door | Uit welke knopen |
|---|---|---|
| Sectorrotatie / relatieve sterkte | sector agent | `growth`, `policy_expectations`, `term_premium`, `energy_prices`, `risk_appetite` |
| Instrumentvoorspellingen (NQ, ZN, CL, 6E) | synthesizer | de volledige toestand |
| Cross-domein-synthese | synthesizer | de volledige toestand |
| Tegenstrijdigheid-detectie | synthesizer (3.1) | conflicten op één knoop |

## Dekking per agent

Elke knoop heeft **één primaire eigenaar**; andere agents mogen hem
lezen. Dat voorkomt dat vijf agents dezelfde toestand onafhankelijk
opnieuw schatten en er vijf verschillende getallen uit komen.

| Agent | Bedient knopen | Status in cohort 0 | Gaten |
|---|---|---|---|
| economic | 1 `growth`, 2 `labor_tightness`, 3 `wage_growth`, 4 `inflation_persistence` | **nog te bouwen** (2.7 lean) | lean-versie dekt alleen ICSA/UNRATE/PAYEMS → knoop 3 en 4 blijven vóór T₀ onbediend |
| monetary | 5 `inflation_expectations`, 6 `policy_stance`, 7 `policy_expectations`, 8 `liquidity`, 9 `term_premium` | voorspelt | **[28-09] vrijwel gedekt** — DGS2, T5YIE/T10YIE en WALCL toegevoegd; alleen 9 `term_premium` draait nog op T10Y2Y als ruwe proxy |
| financial | 10 `financial_conditions`, 11 `credit_risk_premium`, 12 `risk_appetite` | voorspelt | **volledig gedekt** — enige agent zonder gat |
| currency | 13 `dollar` | voorspelt (controlegroep) | DTWEXBGS ontbreekt; nu alleen drie losse paren |
| commodity | 14 `energy_prices`, 15 `industrial_metals` | **alleen monitoring** | maandelijkse AV-bron niet resolvbaar op 5/21/63 hd |
| equity | 16 `earnings_growth`, 17 `equity_valuation` | **buiten cohort 0** | adapter, kwartaalcadans, geen index-brede EPS |
| sector | — (interpreteert, bedient niet) | voorspelt (rijkste testbron) | n.v.t. |

### De harde conclusie uit deze tabel

**Van de 17 knopen worden er in cohort 0 maar 8 bediend door een agent
die daadwerkelijk voorspelt** (5 t/m 13 minus de nog te bouwen
economic-knopen). De rest is:

- 4 knopen bij de economic agent, waarvan er 2 (`growth`,
  `labor_tightness`) door de lean-versie gedekt worden en 2
  (`wage_growth`, `inflation_persistence`) niet;
- 2 knopen bij commodity, die in cohort 0 alleen monitort;
- 2 knopen bij equity, die buiten cohort 0 valt.

Dat is geen fout — het is precies waar de graaf voor bedoeld is: de gaten
zichtbaar maken. Maar het betekent wel dat `graph_node` in cohort 0
terecht optioneel is (roadmap 1.10, correctie 6): op negen van de
zeventien knopen valt er het eerste half jaar niets te scoren.

### Vier gaten zijn goedkoop te dichten, en alle vier via FRED

Deze reeksen zijn gratis, komen van een bron die al werkt, en dichten
elk een knoop die nu leeg is:

| Knoop | Ontbrekende reeks | Status |
|---|---|---|
| 5 `inflation_expectations` | `T5YIE`, `T10YIE` | **gedicht 28-09-2026** — monetary agent |
| 7 `policy_expectations` | `DGS2` | **gedicht 28-09-2026** — scheidt beleidsverwachting van termijnpremie |
| 8 `liquidity` | `WALCL` | **gedicht 28-09-2026** — tolerance nog onzeker, zie `docs/agents.md` |
| 13 `dollar` | `DTWEXBGS` | **nog open** — zie hieronder |

**Waarom `dollar` niet in dezelfde ronde gedicht is.** De andere drie
gingen naar de monetary agent, die al op FRED zit: reeks toevoegen, spec
toevoegen, klaar. `DTWEXBGS` hoort bij de currency agent, en die haalt
zijn data bij Alpha Vantage. Dat zou de eerste agent met **twee
providers** maken, en daar is de infrastructuur nu niet op gebouwd:

- De Source Registry (1.4) kent één entry per (provider, domain). Twee
  providers in één agent betekent twee `source_key`s, dus twee
  `data_health`-rijen — precies goed, want anders zou een werkende
  Alpha Vantage een kapotte FRED verbergen (de bug die 1.4 oploste).
- Maar `run_monitoring()` schrijft per aanroep één `data_health`-rij en
  opent bij een trigger een `qc_case`. Twee keer aanroepen voor hetzelfde
  domein in één cyclus betekent mogelijk twee TRIGGERED-cases, en
  `run_deep_dive()` pakt dan de meest recente — de oudere blijft voor
  altijd in TRIGGERED steken. Dat staat al als bekende grens in
  `docs/project-state.md` en zou hiermee van theoretisch naar structureel
  gaan.

Multi-provider-ondersteuning in `agents/base.py` is dus de echte
voorwaarde, en dat raakt gedeelde infrastructuur voor alle zes agents.
Bewust niet in stilte gebouwd.

**Te verifiëren, mogelijk waardevoller dan alle bovenstaande:** FRED
publiceert dagelijkse olie- en gasprijzen (o.a. WTI spot). Als dat klopt,
kan de commodity agent van maandelijkse Alpha Vantage-data naar
dagelijkse FRED-data, en dan is hij **wél** resolvbaar op 5/21/63
handelsdagen — dan kan hij in cohort 0 voorspellen in plaats van pas in
cohort v1. Reeks-id's zijn hier niet met zekerheid geverifieerd (geen
netwerktoegang in deze omgeving); dit is expliciet het minst zekere deel
van dit document.

---

## Open punten / oneens

Dit is de plek waar DD's eigen these binnenkomt. Nu grotendeels leeg, en
dat is de eerlijke weergave van de stand van zaken.

1. **`equity_valuation` is misschien een output, geen toestand.** Het is
   een prijs, en prijzen horen in laag 3. Hij staat nu in laag 2 omdat
   het ChatGPT-voorstel hem daar zette en omdat hij causale kinderen
   heeft (pijl 39, 40). Maar met `risk_appetite ↔ equity_valuation` als
   lus binnen twee weken is de vraag of dit twee toestanden zijn of één.
   **Niet blokkerend in cohort 0** — equity voorspelt daar toch niet.
2. **Pijl 41 (`energy_prices → earnings_growth`) heeft geen eenduidig
   teken.** Positief voor de energiesector, negatief voor de rest. Staat
   nu als `?`. Dit is precies het soort pijl dat in laag 3 (sector agent)
   thuishoort in plaats van op index-niveau.
3. **Vraag- vs. aanbodgedreven grondstofbewegingen zijn niet
   onderscheiden.** Lus 4 loopt totaal anders per geval, en de commodity
   agent classificeert dit nu niet. Het ChatGPT-voorstel om prijsbewegingen
   te labelen (demand/supply/liquidity/currency/geopolitical) is goed,
   maar vraagt de news agent (2.8) en is dus post-T₀.
4. **`rate_differential` ontbreekt als knoop.** De currency agent draait
   nu op "de koers veranderde meer dan een geraden drempel", zonder
   onderbouwingsmodel — `docs/project-state.md` noteert dit al als gat.
   Een rentedifferentieel zou de tegenhanger van de Taylor Rule zijn,
   maar vraagt ECB/BOJ/BOE-rentes die we niet hebben. Kandidaat-knoop 18.
5. **`bank_lending_standards` (SLOOS) is geschrapt** op de aanname dat
   hij grotendeels in `financial_conditions` en `credit_risk_premium`
   zit. Als hij daar juist op **vooruitloopt**, is dat een eigen knoop
   waard — en dat is een toetsbare vraag.
6. **Niets in deze graaf komt van DD zelf.** Zie "Herkomst". Elke pijl of
   knoop die DD toevoegt, schrapt of van teken verandert, wordt hier
   genoteerd met `[DD]`.

---

## Versiebeheer

Vanaf T₀ᵇ (10-11-2026) is deze graaf semi-bevroren. Elke wijziging krijgt
een versienummer hieronder en start effectief een nieuw cohort in de
scoring (roadmap 4.5). Reden: als de structuur verschuift terwijl er
gemeten wordt, is er geen track record meer maar een overfit.

| Versie | Datum | Wat er veranderde | Waarom |
|---|---|---|---|
| v0 | 28-09-2026 | Eerste versie: 17 toestandsknopen, 41 pijlen, drie lagen | Fase 1, roadmap 1.10 |
