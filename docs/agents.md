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

## De forecast-ronde: waar agents voorspellingen doen (roadmap 2.0)

Sinds 28-09-2026 kent elke agent een **derde modus** naast monitoring en
deep-dive. Dit is de enige plek in het hele systeem waar een taalmodel een
kans of een verdeling mag uitspreken — overal elders is dat verboden.

**Wekelijks, en bewust los van de trigger-keten.** Voorspellingen die
alleen bij triggers ontstaan geven selectiebias: dan voorspel je
uitsluitend in volatiele weken, en is de score niet te vergelijken met een
baseline die elke week draait. Een trigger mág extra voorspellingen
opleveren; die worden gevlagd met `trigger_conditioned`.

**Wanneer precies: maandagochtend**, meeliftend op de dagelijkse cyclus
(`run_daily.py --deep-dives`). Verse week, en de slotkoersen van vrijdag
staan er al in zonder dat er een nieuwe handelsdag overheen is gegaan.

De ronde draait één keer per ISO-week, niet één keer per dag: het
`event_id` is de week (`2026-W40`). Lukt de maandag niet — VPS uit, API
plat, onparseerbare respons — dan draait hij op de eerstvolgende dag die
wél lukt. Dat is een bewuste asymmetrie: een voorspelling van woensdag is
minder goed vergelijkbaar met één van maandag, maar dat is achteraf te
zien aan `created_at`. Een week zonder voorspellingen is niet te
repareren — voorspellen met de kennis van later is geen voorspelling meer.

**Vier inhaalkansen, niet zes.** De code kijkt naar de ISO-week (maandag
t/m zondag), maar de cron op de VPS draait alleen op werkdagen
(`15 7 * * 1-5`). In het weekend gebeurt er dus niets, en dan redt het
weekend een verloren week ook niet: mislukken maandag t/m vrijdag
allemaal, dan is die week definitief leeg. Dat is ruim genoeg om niet
naar zeven dagen per week uit te wijken — in het weekend zou de
monitoring ook marktdata ophalen terwijl de beurzen dicht zijn, en dat
kost Alpha Vantage-calls zonder dat er nieuwe informatie tegenover
staat.

Zonder API-key (dus zonder `--deep-dives`) draait de ronde niet. Dat is
prima tijdens een dry-run, maar na T₀ᵇ is elke zo'n week een gat in de
meting.

## De baselines: waar de agents mee vergeleken worden (roadmap 4.6)

Een score zegt niets zonder iets om hem tegen af te zetten. Naast de agents
voorspellen daarom **drie deterministische baselines** mee, elke week, op
exact dezelfde doelen, horizonnen en afloopdata. Ze gebruiken geen
taalmodel — alles is rekenwerk uit de opgeslagen historie, en de `note` van
elke voorspelling zegt waarop hij rust.

| Baseline | Wat hij zegt | In gewone taal |
|---|---|---|
| `baseline:persistence` | mediaan = het laatste niveau; spreiding uit historische veranderingen | "Het blijft zoals het is." Verrassend moeilijk te verslaan. |
| `baseline:climatology` | de historische verdeling, indien mogelijk voor dezelfde kalendermaand | "Zo ziet dit cijfer er normaal uit." |
| `baseline:ridge` | een lineair model op de z-scores van alle reeksen van het domein | "Wat zou een simpel model doen met precies de cijfers die de agent ziet?" |

**De ridge beantwoordt een andere vraag dan de andere twee.** Persistence en
climatology zeggen of een agent iets weet dat een simpele regel niet weet.
De ridge zegt of het taalmodel iets toevoegt BOVEN zijn eigen inputs. Als het
LLM dat model niet verslaat, zit de meerwaarde niet in het redeneren maar
hooguit in de tekst — dat is een uitkomst, geen mislukking.

**Wanneer een baseline NIETS voorspelt.** Bij te weinig historie (minder dan
30 vensters) of een verouderd laatste cijfer komt er geen voorspelling maar
een melding. Een baseline die met te weinig data toch iets zegt, laat elke
agent er beter uitzien dan hij is.

**Wat geen baseline voorspelt:** de richting van de Fed-doelrange (DFEDTARU) van
de monetary agent (kans dat de Fed verhoogt). Dat is een gebeurtenis op
FOMC-vergaderingen, en een basisrate uit rentecijfers per dag of per maand zou
een andere gebeurtenis scoren. Die twee voorspellingen worden alleen tegen de agent zelf gescoord.

**De ridge moet nog gefit worden.** Dat kan pas na de volledige back-fill en
is een freeze-beslissing: `fit_baselines.py` toont eerst alleen wat er zou
gebeuren, `--freeze` legt het onomkeerbaar vast. Tot dan meldt de wekelijkse
ronde dat de derde baseline ontbreekt.

## Hoe een voorspelling wordt afgewikkeld (roadmap 4.5)

De resolver draait **dagelijks** mee in dezelfde cyclus — voorspellingen
lopen af op hun eigen moment (5, 21 of 63 handelsdagen; 1, 2 of 3
publicaties), niet op maandag. Hij kost niets: geen API-calls, geen LLM.
Alles wat hij nodig heeft staat al in de database.

**Hij beoordeelt nooit zelf.** Elke voorspelling draagt een regel in
mensentaal (`resolution_rule`) én een verwijzing naar de functie die hem
uitvoert (`resolution_method`). Een taalmodel komt er niet aan te pas —
anders zou het model dat de voorspelling deed, ook bepalen of hij uitkwam.

| Methode | Voor welke doelen | Wat hij doet |
|---|---|---|
| `level_at_or_after` | DGS10, DGS2, VIX, HY-spread, 10Y-2Y, de drie FX-paren | het niveau op de eerste observatie op of na de afloopdatum |
| `nth_release` | ICSA, UNRATE, PAYEMS, NFCI | de n-de nieuwe publicatie ná het moment van voorspellen |
| `relative_return` | de elf sector-ETF's | rendement van de ETF minus dat van SPY, over precies dezelfde twee observatiemomenten |
| `direction_after_fomc` | richting van de doelrange (DFEDTARU, dagelijks; tot 01-10-2026 FEDFUNDS) | ligt de bovengrens van de doelrange hoger na de n-de FOMC-vergadering? De eerste waarneming NA de besluitdag beslist, dus de uitkomst is er een dag later (met het maandgemiddelde duurde het vijf tot zes weken) Gebruikt `FOMC_MEETING_DATES` (besluitdagen 28-10-2026 t/m 8-12-2027, van de officiële Fed-pagina; vergaderingen van vóór oktober 2026 ontbreken nog) |

**"Eerste print" is geen extra werk maar een gevolg van het ontwerp.**
Omdat we elke cyclus opslaan wat de bron op dát moment zei, is de
claims-historie een vintage-archief. Komt er later een revisie binnen, dan
is dat een nieuwe claim met dezelfde periode — en die telt niet mee. Bij
PAYEMS is dat geen formaliteit: die revisies zijn fors.

**Wachten is een normale uitkomst.** Ontbreekt de observatie nog (een
feestdagenweek, een vertraagde publicatie), dan gebeurt er niets en
probeert de resolver het de volgende dag opnieuw. Pas na 30 dagen wordt de
voorspelling als onafwikkelbaar weggeschreven, mét reden, en verschijnt
dat in de melding — een voorspelling die nooit gescoord wordt, is stil uit
het cohort verdwenen.

**Wat er gemeten wordt, in gewone taal:**

- **Pinball loss** — per kwantiel, asymmetrisch. Bij het 10%-punt is te
  hoog voorspellen negen keer zo duur als te laag. Daardoor loont het om
  je echte 10%-punt op te schrijven en niet een veilige marge.
- **CRPS** — de vijf pinball losses (q10, q25, q50, q75, q90) samengevat in één getal.
- **Brier** en **log loss** — voor kansvoorspellingen. Log loss straft
  overmoed veel harder: 99% zeggen en ernaast zitten kost een veelvoud van
  90% zeggen en ernaast zitten.
- **Binnen het interval?** — over veel voorspellingen hoort de uitkomst in
  ~80% van de gevallen tussen q10 en q90 te vallen, en in ~50% tussen q25 en q75
  (die tweede check is bij weinig data de informatiefste). Zit een agent op 50%, dan is hij overmoedig; zit hij op 98%, dan
  zijn zijn voorspellingen zo breed dat ze niets zeggen. Allebei
  onzichtbaar in een gemiddelde pinball loss.

Bij alle vier geldt: **lager is beter.**

**Eén LLM-call per agent**, alle doelen in één JSON. Niet per doel een
call: dat is duurder en maakt de voorspellingen onderling inconsistent,
terwijl een agent zijn eigen doelen juist samenhangend hoort te zien.

**Wat de agent te zien krijgt (sinds 01-10-2026).** Per reeks de laatste waarde, en daarbij **context die Python uit onze eigen
historie berekent** (geen LLM): de datum van de laatste waarde en hoe oud die is (CPI is van augustus, een yield van gisteren); de
verandering ten opzichte van ongeveer een en drie maanden eerder; het bereik van de laatste 52 weken en waar de waarde daarin staat; en
per kwantieldoel en horizon de **standaarddeviatie van de verandering** over de laatste vijf jaar en het laatste jaar. Voor de FOMC-vragen:
de laatste verandering van de doelrange, de veranderingen van de afgelopen twee jaar en de eerstvolgende besluitdagen. Alles is
point-in-time (alleen wat er op de dag zelf bekend was). **Bewust geen kant-en-klare kwantielen:** alleen spreiding, zodat de agent zelf
van spreiding naar kwantielen moet en de test niet meet of het model de baseline kan kopiëren. Er staat bewust niets in over releasedata
van CPI of banen (er is geen kalender van) en niets over FOMC-uitkomsten van vóór oktober 2026. Vensters overlappen, dus het getal `n`
in de context is geen aantal onafhankelijke waarnemingen; dat staat er ook bij.

**De agent ziet alleen zijn eigen domein-claims.** Bewust niet alle
domeinen — dat maakt agents sterker maar volledig gecorreleerd, en dan
meet de scoring straks zeven keer dezelfde synthesizer. Cross-domein is de
rol van de synthesizer, die apart gescoord wordt.

| Agent | Doelen | Voorspellingen per ronde |
|---|---|---|
| monetary_policy | DGS10, DGS2 (5/21/63 hd), richting van de doelrange DFEDTARU (1/2 FOMC) | 8 |
| financial | HY-spread, VIX, 10Y-2Y (5/21/63 hd), NFCI (1/4/12 weekprints) | 12 |
| economic | ICSA (1/4 weekprints), UNRATE en PAYEMS (1/3 maandprints) | 6 |
| currency | EUR/USD, USD/JPY, GBP/USD (5/21/63 hd) | 9 |
| sector | relatief rendement t.o.v. SPY per ETF (5/21 hd) | 22 |
| commodity | geen — maandelijkse bron, niet resolvbaar op korte horizon | — |
| equity | geen — buiten cohort 0 | — |

**Waarom currency de controlegroep is:** de verwachting is dat die agent
een random walk niet verslaat. Blijkt dat zo, dan is het geen mislukking
maar de bevestiging dat de meetopstelling werkt.

**De sector agent voorspelt relatief rendement, niet koersen.** Op DD's
beslissing van 28-09 wordt SPY nu elke cyclus opgehaald en opgeslagen,
naast de elf sector-ETF's. Daarmee is het relatieve rendement over een
horizon achteraf uit de claims-historie te berekenen: de procentuele
koersverandering van de ETF tussen twee observatiemomenten, minus die van
SPY over precies dezelfde twee momenten.

Waarom niet gewoon de koers voorspellen: dat meet vooral of de markt
omhoog of omlaag ging, en dat is precies wat hier uitgesloten moet worden.
Rotatie is de vraag.

Daarnaast wordt de **dagelijkse** relatieve sterkte per ETF nu ook
opgeslagen (`<etf>_rel_spy`), berekend uit de dagverandering die de quote
toch al meelevert — dat kost geen extra API-call. Die waarden triggeren
bewust NIET: de escalatie blijft op de ruwe prijs lopen, want een
delta-trigger hierop zou de dagverandering van vandaag met die van
gisteren vergelijken, en dat is ruis.

## Welke knoop van de causale graaf bedient welke agent (roadmap 1.10)

Sinds 28-09-2026 ligt er één gedeeld model van de economische machine vast:
17 toestandsknopen met 41 pijlen ertussen, in `docs/causal-graph.md` (en
machine-leesbaar in `src/contract/graph.py`). Elke knoop heeft **precies
één primaire eigenaar**; andere agents mogen hem lezen. Zonder die regel
zouden vijf agents dezelfde toestand onafhankelijk schatten en er vijf
verschillende getallen uit komen — precies de vrijzwevende analyse die de
graaf moet voorkomen.

| Agent | Bedient knopen | Nu al gedekt door zijn databron? |
|---|---|---|
| economic *(nieuw, 28-09)* | `growth`, `labor_tightness`, `wage_growth`, `inflation_persistence` | deels — de lean-versie dekt de eerste twee; `wage_growth` en `inflation_persistence` blijven post-T₀ |
| monetary_policy | `inflation_expectations`, `policy_stance`, `policy_expectations`, `liquidity`, `term_premium` | deels — alleen `policy_stance`; de andere vier vragen nieuwe FRED-reeksen |
| financial | `financial_conditions`, `credit_risk_premium`, `risk_appetite` | **ja, volledig** — enige agent zonder gat |
| currency | `dollar` | deels — drie losse paren, brede dollarindex ontbreekt |
| commodity | `energy_prices`, `industrial_metals` | ja, maar op maandcadans |
| equity (adapter) | `earnings_growth`, `equity_valuation` | nee — per ticker, geen index-brede cijfers |
| sector | **geen** | n.v.t. — zie hieronder |

**De sector agent bedient bewust geen knoop.** Sectorrotatie is een
*output*, geen oorzaak: rotatie is wat je zíét wanneer `risk_appetite` of
`growth` beweegt. De sector agent is daarmee een cross-sectionele
interpreet van de toestand, niet de eigenaar van een eigen toestand.

Dit verandert niets aan wat een agent monitort of triggert. Het legt vast
wélke toestand welke agent schat, zodat `graph_node` op een prediction
(roadmap 4.1) naar iets verwijst dat één eigenaar heeft.

### Per reeks: welke knoop helpt hij schatten (`GRAPH_MAPPING`)

Sinds 28-09-2026 declareert **elke agent per opgehaalde reeks** welke knoop
die reeks helpt schatten — of expliciet `None` als hij bij geen enkele
knoop hoort. Staat in elk agent-bestand naast `METRIC_SPECS`, bewaakt door
`tests/test_graph_mapping.py`.

Waarom dat de moeite waard is: een reeks ophalen zonder te beslissen welke
toestand hij schat, is hoe je ongemerkt een dashboard bouwt in plaats van
een model. Nu dwingt het toevoegen van een reeks die vraag af, en een test
controleert of elke knoop die een agent bezit ook echt een waarneming
heeft. Precies dát gat zat er tot 28-09 bij de monetary agent: vijf knopen
op zijn naam, één meetbaar.

Twee dingen die deze mapping meteen zichtbaar maakte:

- **Vijf van de tien commodity-reeksen voeden geen enkele knoop** (tarwe,
  maïs, katoen, suiker, koffie). Landbouwprijzen bewegen op weer en
  oogsten, niet op de economische machine; ze zaten alleen in beeld omdat
  de agent ze toch al ophaalde. Ze blijven gemonitord — dezelfde API-call,
  dus gratis — maar ze schatten niets.
- **Alle elf sector-ETF's staan op `None`**, en dat is het ontwerp. De
  sector agent bezit geen knoop; hij interpreteert de toestand
  cross-sectioneel.

Drie van de zeventien knopen worden op dit moment door niets gevoed:
`wage_growth` en `inflation_persistence` (wachten op AHETPI/ECI en core
PCE, post-T₀) en `equity_valuation` (vraagt een index-brede earnings yield
die we niet hebben). Alle drie staan als test vastgelegd, zodat het aantal
niet ongemerkt kan groeien.

## Monetary policy agent (`agents/monetary_policy_agent.py`)

**Wat het volgt:** vier kernreeksen van FRED (Federal Reserve Economic
Data), elk gezien als "vers" tot 35 dagen oud (het zijn maandelijkse
reeksen). Sinds roadmap 1.4 (Source Registry) heeft deze agent zijn EIGEN
databron-registratie (`FRED:monetary_policy`), los van de financial agent
hieronder — die gebruikt óók FRED, maar met een andere ververssnelheid
(10 dagen). Vóór 1.4 deelden ze onbedoeld dezelfde status, waardoor de
ene agent's verse pulls de andere's veroudering kon verbergen.

| Metric | FRED-reeks | Bedient welke graafknoop |
|---|---|---|
| Fed funds rate | FEDFUNDS | `policy_stance` |
| Fed funds doelrange (bovengrens) | DFEDTARU | `policy_stance` |
| 10-jaars Treasury yield | DGS10 | `term_premium` |
| CPI-index | CPIAUCSL | (input voor `inflation_persistence`) |
| Werkloosheidspercentage | UNRATE | (input voor `labor_tightness`) |
| 2-jaars Treasury yield | DGS2 | `policy_expectations` |
| 5-jaars break-even inflatie | T5YIE | `inflation_expectations` |
| 10-jaars break-even inflatie | T10YIE | `inflation_expectations` |
| Fed-balanstotaal | WALCL | `liquidity` |

**DFEDTARU (01-10-2026)** is de bovengrens van de doelrange van de Fed, per dag. Hij bedient
de twee FOMC-vragen ("verhoogt de Fed op de n-de vergadering?") en vuurt op de besluitdag
zelf (de rente springt in stappen van 0,25; drempel 0,125). FEDFUNDS (het maandgemiddelde van
de werkelijke rente) blijft staan voor de trend en voor de Taylor Rule; een renteverandering
geeft daardoor twee triggers, de eerste meteen en de tweede weken later.

De onderste vier uit de tabel zijn toegevoegd op 28-09-2026. Reden: de causale graaf
(1.10) wees deze agent aan als eigenaar van `policy_expectations`,
`inflation_expectations` en `liquidity`, maar hij had geen enkele
waarneming om die knopen uit te schatten. Het onderscheid dat hiermee
mogelijk wordt: **wat de Fed doet** (FEDFUNDS) is iets anders dan **wat de
markt denkt dat de Fed gaat doen** (DGS2) en dan **wat de markt aan
inflatie verwacht** (de break-evens). Zonder die drie apart bewoog er van
alles in de 10-jaars yield dat de agent niet kon duiden.

**Wanneer het triggert:** bij elke nieuwe waarde vergelijkt het agent met
de vorige observatie (geen vaste absolute drempel, zie hieronder bij
"Belangrijk voorbehoud"):

| Metric | Afwijking die triggert | Severity |
|---|---|---|
| Fed funds rate | > 0,15 procentpunt | high |
| 10-jaars Treasury yield | > 0,14 procentpunt | medium |
| CPI-index | > 2,0 punten | medium |
| Werkloosheidspercentage | > 0,15 procentpunt | high |
| 2-jaars Treasury yield | > 0,14 procentpunt | medium |
| 5-jaars break-even inflatie | > 0,085 procentpunt | medium |
| 10-jaars break-even inflatie | > 0,055 procentpunt | medium |
| Fed-balanstotaal | > 33.000 (miljoen USD, ≈ $33 mrd) | medium |

**Deze drempels zijn trigger-versie v1 (29-09-2026)**: gekozen met het
kalibratierapport (`calibrate_triggers.py`) op de laatste drie jaar, met als
doel ~5 triggers per jaar per reeks. Onder v0 stonden ze op 0,25 /
0,25 / 2,0 / 0,3 / 0,25 / 0,10 / 0,10 / 25.000, en vuurden vijf ervan in
drie jaar nooit. Twee uitzonderingen op "5 per jaar", met reden:

- **Reeksen die in stapjes bewegen** (fed funds, werkloosheid,
  break-evens) krijgen een drempel *halverwege twee stapjes*. Een
  drempel precies op een stap (0,2 bij werkloosheid) is een loterij: 4,3
  min 4,1 geeft in floats 0,2000000000000002 en vuurt dan soms wel en soms
  niet. 0,15 vuurt bij een verandering van minstens 0,2 punt. Fed funds
  beweegt maar een paar keer per jaar, dus daar is 5 per jaar niet te
  halen; 0,15 is ~2 per jaar.
- **CPI blijft 2,0.** De CPI-index heeft een groeitrend; "5 per jaar" zou
  ongeveer de gewone maandgroei worden (~0,9 punt) en dus bij elke maand
  met bovengemiddelde inflatie vuren, wat geen verrassing is. Een goede
  regel vergelijkt met trend of verwachting; dat is een wijziging in de
  trigger-engine en staat als open punt in `docs/roadmap.md`.

De break-even-drempels staan bewust lager dan de rente-drempels:
inflatieverwachtingen bewegen in honderdsten van procentpunten.
**De WALCL-eenheid is op 28-09-2026 geverifieerd** tegen de live API: de
eerste run op de VPS leverde 6.747.704, dus miljoenen USD (~$6,75 biljoen).

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

*Ophalen (02-10-2026):* een mislukte Alpha Vantage-reeks krijgt een gelogde reden en wordt na één pauze van 30 s één keer opnieuw geprobeerd (`sources/alpha_vantage.py`). Een gat dat blijft, blijft een volledigheidstrigger.

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
| EUR/USD | > 0,016 | medium |
| USD/JPY | > 3,0 | medium |
| GBP/USD | > 0,016 | medium |

**Trigger-versie v1 (29-09-2026): ~2 triggers per jaar per paar.** Currency
is de controlegroep, niet de agent waar de meeste deep-dives van gewenst
zijn. Voor v1 stonden de drempels op 0,01 / 1,0 / 0,01, en usd_jpy vuurde
toen op 22% van de dagen (~57 keer per jaar): een normale dag, geen
signaal. Currency gaf daarmee de helft van alle triggers van het systeem.

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
| Financial Conditions Index | > 0,0125 punt | high |
| High-yield credit spread | > 0,205 procentpunt | high |
| VIX | > 4,805 punten | medium |
| 10Y-2Y yield curve | > 0,105 procentpunt | medium |

**Trigger-versie v1 (29-09-2026): ~5 per jaar per reeks.** De NFCI-drempel
was 0,1 terwijl een uitzonderlijke wekelijkse beweging ~0,018 is: de
regel vuurde in drie jaar nooit, dus de agent zou ook in een echte
stressperiode gezwegen hebben. Zelfde voor de rentecurve (0,15 tegen 0,11).
De HY-spread heeft maar ~3 jaar historie (waarschijnlijk een
licentiebeperking van FRED op de ICE-data, niet geverifieerd) en is daarom
voorlopig.

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

*Splitsingen (02-10-2026):* vijf ETF's (XLB, XLE, XLK, XLU, XLY) halveerden op 5 december 2025 door een 2-voor-1-splitsing. Alles wat over de historie rekent (evidence-sheet, baselines, afrekenen, kalibratie) leest de reeks gecorrigeerd (`contract/corporate_actions.py`); de ruwe claims blijven ongewijzigd, en een waakhond meldt in het log een nieuwe, nog niet geregistreerde splitsing. De triggerdrempels van deze agent zijn bewust nog niet aangepast (beslissing DD, `docs/deployment.md`).

*Ophalen (02-10-2026):* een mislukte Alpha Vantage-reeks krijgt een gelogde reden en wordt na één pauze van 30 s één keer opnieuw geprobeerd (`sources/alpha_vantage.py`). Een gat dat blijft, blijft een volledigheidstrigger.

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
delta-mechanisme als de andere agents), tolerances per ETF, sinds
trigger-versie v1 (29-09-2026) gekozen op ~5 triggers per jaar over de
laatste drie jaar. **Sinds trigger-versie v4 (02-10-2026)** zijn de drempels van vijf ETF's die op 5
december 2025 splitsten opnieuw gekalibreerd op de gecorrigeerde reeks (XLK 8,9 → 5,4, XLE 2,6 → 1,6,
XLY 6,2 → 3,2, XLB 2,0 → 1,2, XLU 1,8 → 1,0). Huidige drempels: XLK 5,4 · XLF 1,2 · XLE 1,6 · XLV 3,5 ·
XLY 3,2 · XLP 1,6 · XLI 3,9 · XLB 1,2 · XLU 1,0 · XLRE 1,0 · XLC 2,9 · SPY 13,4 dollar. ETF's
hebben sterk verschillende prijsniveaus — XLK rond de $200, XLRE rond de $40 —
een uniforme dollartolerantie zou niet kloppen. De elf sectoren bewegen
samen: één schokdag geeft snel meerdere triggers tegelijk, die de manager
bundelt. Belangrijker voorbehoud dan
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

*Ophalen (02-10-2026):* een mislukte Alpha Vantage-reeks krijgt een gelogde reden en wordt na één pauze van 30 s één keer opnieuw geprobeerd (`sources/alpha_vantage.py`). Een gat dat blijft, blijft een volledigheidstrigger.

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
andere agents). Sinds **trigger-versie v2 (29-09-2026)** zijn de drempels
gekalibreerd op 35 jaar back-fill, ~5 triggers per jaar per reeks:

| Metric | Afwijking die triggert | Severity |
|---|---|---|
| WTI | > 4,1 | medium |
| Brent | > 4,4 | medium |
| Natural gas | > 0,3 | medium |
| Copper | > 356 (dollar per metrische ton) | high |
| Aluminum | > 73 | medium |
| Wheat | > 11,7 | medium |
| Corn | > 9,6 | medium |
| Cotton | > 1,9 | medium |
| Sugar | > 0,9 | medium |
| Coffee | > 14,6 | medium |

De bron is **maandelijks**: een reeks kan dus hooguit twaalf keer per jaar
vuren, en 5 per jaar is 5 van de 12 publicaties. Alle tien de reeksen
veranderen op dezelfde dag, dus dat wordt in de praktijk één deep-dive per
maand-dag (de manager bundelt per domein).

**Waarom het veranderde.** Onder v0 gaven deze tien samen 46 triggers per
jaar, heel ongelijk verdeeld. Koper stond op 0,20 omdat de eerste versie
dollar per pond aannam; de bron levert dollar per **metrische ton** (niveau
~13.500), dus koper vuurde bij elke publicatie en gaf geen informatie. Tarwe
(30) en maïs (25) vuurden daarentegen bijna nooit. De eenheden zijn nu
geverifieerd tegen de opgeslagen data, niet meer aangenomen.

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

## Economic agent (`agents/economic_agent.py`) — **nieuw, 28-09-2026**

**Status:** draait mee in de dagelijkse cyclus (`src/runtime/daily.py`).
Checkpoint 1 uit `CLAUDE.md` is op 28-09-2026 gepasseerd — DD heeft de
agent beoordeeld en akkoord gegeven; de test die vastlegde dat hij nog
niet gekoppeld was, is in diezelfde ronde vervangen door een die bewaakt
dat hij niet stilletjes weer uit de cyclus verdwijnt. Hiermee draaien er
zes agents dagelijks.

**Waarom hij er is, als enige uitzondering op "geen nieuwe agents vóór
T₀".** De causale graaf (1.10) heeft vier knopen in de reële economie en
géén van de zes bestaande agents bediende er ook maar één. Zonder deze
agent leert de forward test een half jaar lang niets over groei en
arbeidsmarkt — en dat is de bovenkant van de transmissieketen. Een graaf
die daar blind is, ziet alleen gevolgen en nooit de oorzaak.

**Wat het volgt:** drie FRED-reeksen, "vers" tot 10 dagen (strakker dan de
monetary agent's 35 dagen, omdat hier een wekelijkse reeks tussen zit).
Eigen databron-registratie `FRED:economic` — de derde FRED-agent, dus
zonder eigen `source_key` zouden drie agents dezelfde data_health-rij
delen.

| Metric | FRED-reeks | Cadans | Bedient welke graafknoop |
|---|---|---|---|
| Wekelijkse WW-aanvragen | ICSA | wekelijks | `labor_tightness` |
| Werkloosheidspercentage | UNRATE | maandelijks | `labor_tightness` |
| Banen buiten de landbouw | PAYEMS | maandelijks | `growth` |

ICSA is de snelst resolvende macroreeks die er is. Daarmee is dit de enige
macro-agent met een voorspeldoel dat op korte horizon af te rekenen valt —
zie `docs/roadmap.md` deel A, "De agents van cohort 0".

**Wanneer het triggert:**

| Metric | Afwijking die triggert | Severity |
|---|---|---|
| Wekelijkse WW-aanvragen | > 16.000 aanvragen | medium |
| Werkloosheidspercentage | > 0,15 procentpunt | high |
| Banen buiten de landbouw | > 250 (duizend) | high |

**Trigger-versie v1 (29-09-2026).** WW-aanvragen ~5 per jaar (was 25.000,
~1 per jaar); werkloosheid gelijkgetrokken met de monetary agent (0,15, zie
daar). **PAYEMS blijft 250, bewust niet gekalibreerd:** het is een niveau met
groeitrend, dus "5 per jaar" zou 130 duizend worden, ongeveer de gewone
maandgroei. De regel vuurt daardoor in drie jaar nooit; een trigger die met
trend of verwachting vergelijkt is een wijziging in de trigger-engine en
staat als open punt in `docs/roadmap.md`. De economic agent heeft dus
voorlopig maar twee levende triggers; de wekelijkse voorspelronde draait
onafhankelijk daarvan.

PAYEMS is een **niveau** in duizenden personen, dus het verschil tussen
twee waarnemingen ís de maandelijkse banengroei. Een normale maand is +100
tot +200; de drempel van 250 vangt dus de uitzonderlijke maanden en de
banenverliezen, niet de gewone.

**Waar de deep-dive over gaat:** de staat van de arbeidsmarkt en het tempo
van de economische activiteit. De prompt waarschuwt expliciet voor drie
dingen die hier misgaan: PAYEMS is een niveau en geen groeicijfer,
wekelijkse WW-aanvragen zijn rumoerig (één week is zelden een signaal), en
de Sahm Rule moet letterlijk overgenomen worden inclusief zijn
voorbehoud.

**Onderbouwing — de Sahm Rule** (`src/analysis/sahm_rule.py`, vijfde model
in die map): bij een werkloosheidsclaim haalt Python 15 maanden UNRATE op
en berekent of het 3-maands gemiddelde 0,50 procentpunt of meer boven het
laagste 3-maands gemiddelde van de voorgaande twaalf maanden ligt. De LLM
krijgt de uitkomst én de duiding als kant-en-klare claim en mag niet zelf
inschatten of de arbeidsmarkt verslechtert.

Twee dingen die hier bewust zo zijn:
- **De drempel van 0,50 is géén plaatshouder.** Anders dan de tolerances
  hierboven komt dat getal uit het gepubliceerde model (Sahm, 2019) en mag
  het niet "gekalibreerd" worden — dan meet je een eigen model onder de
  naam van een gevestigd model.
- **Minder dan 15 maanden data levert géén berekening op**, geen kortere
  variant. Dezelfde weiger-in-plaats-van-gokken-regel als de Taylor Rule.

De agent geeft altijd mee dat de Sahm Rule **beschrijvend** is: hij
signaleert dat een recessie waarschijnlijk al begonnen is, niet dat er een
aankomt.

**Bewust NIET in de lean versie** (alles post-T₀, staat zo in roadmap
2.7): output gap via HP-filter, Misery Index, ISM-diffusie, Phillips
Curve-residual. Elk daarvan vraagt een nieuwe bron of een parameterkeuze,
en dat is precies wat vóór T₀ niet moet gebeuren. Gevolg: de graafknopen
`wage_growth` en `inflation_persistence` blijven voorlopig onbediend —
een vastgelegde grens, geen vergeten reeks.

**Bewuste overlap met de monetary agent.** Die monitort UNRATE ook. Geen
kopieerfout: de monetary agent leest werkloosheid als input voor de
beleidsreactie (dual mandate), deze agent schat er de toestand
`labor_tightness` uit. Gevolg dat je moet kennen: bij een
werkloosheidscijfer dat de drempel haalt vuren er (sinds v1 hebben beide
agents dezelfde drempel) altijd **twee** triggers en
kunnen er twee deep-dives volgen over dezelfde publicatie, elk met een
andere invalshoek. Of dat wenselijk is, staat als open vraag in
`docs/project-state.md`.

## Belangrijk voorbehoud, voor alle zes agents

De tolerances in de tabellen hierboven zijn sinds **29-09-2026
trigger-versie v2**: gekozen met het kalibratierapport op de back-fill en niet
langer plaatshouders. Uitzonderingen: de HY-spread (maar 3 jaar data), en
CPI en payrolls, die bewust niet gekalibreerd zijn (groeitrend, zie
`docs/roadmap.md`, open beslissingen). Elke wijziging van een drempel, ouderdomsgrens of trigger-gedrag verandert de
vingerafdruk in `runtime/trigger_guard.py` en laat een test falen totdat
`TRIGGER_VERSION` omhoog gaat (`contract/trigger_version.py`). Na T₀ᵇ start
zo'n wijziging een nieuw cohort.
