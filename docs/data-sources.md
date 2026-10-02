# Databronnen en API-budget

Hoort bij roadmap 1.11, checklistpunt "API-quota meten" (fase 0, vóór
T₀ᵃ). De definition of done daar: *dagelijks callvolume (monitoring +
deep-dives) < limiet van de gebruikte tier, gedocumenteerd hier; anders
bron wisselen vóór T₀ᵃ*.

**Stand: 28-09-2026. Er is een probleem, en het staat hieronder.** **[30-09] Na de overstap naar een betaald plan was de run van 30-09 compleet (currency, sector en commodity `ok`, geen completeness-trigger). Dat is één run; de eerdere lege antwoorden van 29-09 rond 11:07 UTC zijn onverklaard, zie `docs/project-state.md`.**

## Waarom dit telt

Het systeem draait onbeheerd. Loopt het dagelijkse callvolume tegen een
quotum aan, dan mislukken de laatste agents van de cyclus stil — of nog
vervelender: ze mislukken pas op de drukke dagen, wanneer er deep-dives
bij komen. Dat is precies het scenario waar de kalibratie kapot van gaat,
want dan ontbreken **systematisch de moeilijke weken**. Een gat in de
reeks dat samenhangt met marktvolatiliteit is erger dan willekeurig
ontbrekende data: het maakt het track record beter dan het is.

## Call-volume per dag — monitoring

Afgeleid uit de code (`FRED_SERIES`, `FX_PAIRS`, `SECTOR_ETFS`,
`COMMODITIES`), niet geschat. Eén call per reeks per cyclus;
`run_daily.py` draait één cyclus per dag.

| Provider | Agent | Calls |
|---|---|---|
| FRED | monetary_policy | 9 |
| FRED | financial | 4 |
| FRED | economic | 3 |
| **FRED totaal** | | **16** |
| Alpha Vantage | currency | 3 |
| Alpha Vantage | sector | 11 |
| Alpha Vantage | commodity | 10 |
| **Alpha Vantage totaal** | | **24** |

## Call-volume per dag — deep-dives erbij

Deep-dives zijn opt-in (alleen met een meegegeven `client`), maar op een
dag dat ze aanstaan komt dit erbovenop:

| Provider | Waarvoor | Calls |
|---|---|---|
| FRED | Taylor Rule (CPI nu + 12 mnd terug, GDPC1, GDPPOT) | 4 |
| FRED | Sahm Rule (15 UNRATE-waarnemingen in één call) | 1 |
| Alpha Vantage | relatieve sterkte: 1 per getriggerde sector + SPY één keer | 1–12 |
| Alpha Vantage | voortschrijdend gemiddelde: 1 per getriggerde grondstof | 0–10 |

**Worst case op een volatiele dag:**

| Provider | Monitoring | Deep-dives | Totaal |
|---|---|---|---|
| FRED | 16 | 5 | **21** |
| Alpha Vantage | 24 | 22 | **46** |

En let op de vorm van dat getal: het Alpha Vantage-volume **piekt precies
op de dagen dat er veel triggert**, dus op de marktbewegingen waar we het
meest over willen weten.

## GEMETEN op 28-09-2026: Alpha Vantage leverde 6 van de 24

De eerste live runs na de merge maakten van een vermoeden een meting. Twee
runs, hetzelfde beeld:

| Run | FRED | Alpha Vantage |
|---|---|---|
| 07:15 (cron) | 8 van 8 | **6 van 24** — currency 1/3, sector 2/11, commodity 3/10 |
| 16:37 (handmatig) | 15 van 15 | **5 van 24** — currency 1/3, sector 2/11, commodity 2/10 |

FRED leverde beide keren alles. Alpha Vantage kwam niet verder dan een
handvol calls per burst. De uitval lijkt eerder op een limiet per MINUUT
dan per dag, maar voor de conclusie maakt dat niet uit: 24 calls in één
burst komt er op de gratis tier niet doorheen.

**En alle vijf agents rapporteerden `success=True`.** `fetch_snapshot()`
geeft alleen een fout terug als GEEN ENKELE reeks lukt, dus een bron die
voor 80% wegvalt was niet te onderscheiden van een gezonde dag. Dat is
sinds diezelfde dag opgelost: de completeness-check (roadmap 1.3) is
gewired en zet een gedeeltelijke pull om in een zichtbare trigger. **Die
check is nu ook de controle op de betaalde tier hieronder** — komt er na
de upgrade nog een completeness-trigger voorbij voor currency, sector of
commodity, dan is het probleem niet opgelost.

## GEMETEN op 02-10-2026 (2): vijf sector-ETF's halveerden op 5 december 2025 door een splitsing

De pseudo-OOS-prompt (`pseudo_oos.py prompt`) toonde voor XLB, XLE, XLK, XLU en XLY een 52-weken-hoog van ongeveer het dubbele van de koers, en een spreiding over het
laatste jaar die twee keer zo groot was als over vijf jaar. DD draaide een alleen-lezen controle op de echte database: één sprong per ETF, allemaal op **2025-12-05**
(XLB 88,47 -> 44,09; XLE 92,22 -> 45,92; XLK 291,07 -> 146,60; XLU 87,42 -> 43,30; XLY 238,14 -> 119,73; verhoudingen 0,495 tot 0,504), geen enkele andere ETF en SPY niet. Het zijn
**2-voor-1-splitsingen** in een reeks die niet voor splitsingen is gecorrigeerd: de back-fill gebruikt `TIME_SERIES_DAILY`, niet de gecorrigeerde variant.

**Wat het besmette:** de spreiding in de evidence-sheet, de baselines (persistence, climatology, ridge), het afrekenen van een voorspelling die over de splitsingsdatum loopt, en het
kalibratierapport van de triggers (de sectordrempels zijn absolute prijsverschillen en zijn mede op de dubbel zo hoge koersen van vóór de splitsing gekalibreerd). Niet besmet: `predictions` en de
ruwe claims (die blijven onaangeroerd).

**Gewijzigd (DD akkoord):** `contract/corporate_actions.py` (een expliciete lijst `SPLITSINGEN`), toegepast in het ene leespad `scoring/resolver.py::observations_for`: waarden van vóór een splitsing worden gedeeld
door de verhouding, zodat de hele historie in huidige aandelen staat. `runtime/split_waakhond.py` meldt in het dagelijkse log (en in `freeze_status.py`) een sprong van meer dan ~35% die niet in de lijst staat, een
geregistreerde splitsing waarvan de verhouding niet bij de sprong past, en een geregistreerde splitsing die de data niet bevestigt (typefout in de datum). Alleen waarschuwen, nooit wijzigen. Een nieuwe splitsing wordt
alleen AAN HET EIND van de lijst toegevoegd. Baseline-versie v2 -> v3. De triggerdrempels zijn NIET gewijzigd; de vergelijking staat in `docs/deployment.md`.

## GEMETEN op 02-10-2026: één reeks miste, het log zei niet waarom — en wat er is veranderd

De eerste T₀ᵃ-dag (02-10, 07:15 UTC) leverde van de twaalf sectorreeksen er elf: `xlp_consumer_staples` ontbrak. Alle agents meldden `ok`;
de completeness-check zette er een trigger bij en de dag telde niet als schoon (teller op nul, T₀ᵃ op zijn vroegst 13-10 volgens
`t0a_status.py`). **De oorzaak is niet bekend en kon uit het log niet worden afgeleid**: de drie `_fetch_*`-helpers (sector, currency,
commodity) vingen elke fout op met `except Exception: return None`, ook een "Note"/"Information"-melding van Alpha Vantage, en
loggen deden ze niets. Een grep op `xlp|rate|limit|Note|Information` over het hele `daily.log` gaf niets.

**Gewijzigd op 02-10 (DD akkoord; checkpoint 3 via het plan in `docs/deployment.md`):** `src/sources/alpha_vantage.py`.
1. Elke mislukte reeks krijgt een gelogde reden: time-out, verbindingsfout, HTTP-status, de tekst van Alpha Vantage's eigen melding, of
   "lege respons". De API-sleutel komt nooit in het log (van een uitzondering loggen we alleen het type).
2. Wat in de eerste ronde ontbreekt, wordt na één gezamenlijke pauze van 30 seconden één keer opnieuw geprobeerd.
3. **Niet gewijzigd:** de completeness-check. Een gat dat ook na de herhaling blijft, blijft een volledigheidstrigger en de dag telt dan
   niet. Op een goede dag verandert er niets (geen pauze, geen extra aanroepen, geen logregel).

**Wat nog niet bekend is:** of de uitval een limiet per minuut is (de 12 sectoraanroepen staan in een snelle lus zonder pauze), een
tijdelijke fout aan Alpha Vantage's kant, of iets structureels voor XLP. De gelogde redenen van de komende ochtenden moeten dat uitwijzen.

## GEMETEN op 30-09-2026: het commodity-endpoint is niet live, ook niet met het betaalde plan

DD vroeg of de commodity agent met het betaalde plan (real-time of 15 minuten vertraagd) live data kan
ophalen. Dat real-time recht geldt voor koersen van aandelen, ETF's en valuta (`GLOBAL_QUOTE`, wat de
sector en currency agent al gebruiken), niet voor het commodity-endpoint. Gemeten op de VPS op 30-09-2026,
met `interval=daily` voor twee grondstoffen:

| Grondstof | Antwoord | Nieuwste waarneming | Achterstand |
|---|---|---|---|
| WTI | `interval: daily`, dollar per vat | 22-09-2026 | 8 dagen (6 handelsdagen) |
| Koper | vraagt daily, krijgt `interval: monthly`, dollar per metrische ton | juli 2026 (1-07-2026) | twee maanden |

**Wat dat betekent.** Olie heeft dagcijfers, maar ongeveer een week achter: een echte dagelijkse maar geen
verse bron. Koper (en volgens de documentatie ook aluminium, tarwe, maïs, katoen, suiker en koffie; alleen
koper is gemeten) heeft alleen maandcijfers met twee maanden achterstand. Voor een voorspelling over 5, 21 of
63 handelsdagen is dat geen bruikbare bron: de voorspelling zou op een waarde van een week of twee maanden
terug moeten aansluiten en pas veel later af te rekenen zijn. Dit bevestigt waarom de commodity agent in
cohort 0 alleen monitort. Aardgas is niet apart gemeten.

**Als commodity ooit verse dagdata moet krijgen** (roadmap 2.6 en fase 4, "commodity naar dagelijkse
bron"): de route via Alpha Vantage die wél real-time is, zijn ETF's op grondstoffen via `GLOBAL_QUOTE` en
`TIME_SERIES_DAILY`, hetzelfde pad als de sector agent. Dat volgt futures met roll- en contango-effecten en
is dus niet gelijk aan de spotprijs; de exacte symbolen zijn niet geverifieerd en moeten op de VPS worden
gecontroleerd voordat er een reeks bij komt (checkpoint 4). Het raakt de reeksenlijst en vraagt drempels
en een nieuwe trigger-versie.

## BESLIST op 28-09-2026: betaalde Alpha Vantage-tier

DD kiest voor een betaald plan in plaats van een bronmigratie. De
afweging: een migratie naar FRED kost engineeringtijd en introduceert
nieuwe, onzekere reeks-id's én andere eenheden (koper per ton in plaats
van per pond, met alle tolerances die daarmee opnieuw gegokt moeten
worden), terwijl T₀ᵃ vlakbij ligt en de klok geen kalendertijd
terugkrijgt. Geld in plaats van werktijd.

**Wat dit NIET oplost:** het Alpha Vantage commodity-endpoint blijft
maandelijks. Een 5/21/63-daagse voorspelling is daar niet tegen te
resolven, dus de commodity agent blijft in cohort 0 monitoring-only en
komt pas vanaf cohort v1 in de scoring (roadmap deel A). Dat was al de
planning; de upgrade verandert daar niets aan.

**Te doen na de upgrade:** één run draaien en controleren dat er geen
completeness-trigger meer komt. **[30-09 gedaan: de run van 07:15 was compleet, 0 triggers.]** De vier opties hieronder blijven staan als
verantwoording van de keuze, niet als openstaande actie.

## Het probleem

**FRED** is ruim. De API is gratis en de limieten liggen ver boven 20
calls per dag. Geen zorg.

**Alpha Vantage is het knelpunt.** De gratis tier is de afgelopen jaren
fors teruggeschroefd — naar de orde van **25 requests per dag**. Klopt
dat, dan zit de monitoring alléén (24) al tegen het plafond en is elke
deep-dive-dag gegarandeerd te veel.

> **NIET GEVERIFIEERD VANUIT DEZE OMGEVING.** De ontwikkelomgeving heeft
> geen netwerktoegang naar Alpha Vantage, dus het exacte quotum van de
> tier die bij DD's key hoort is hier niet op te vragen. DD moet dit
> controleren op zijn eigen accountpagina. Het kan zijn dat de key uit
> `analyst_agent.ai` een betaalde tier heeft — dan verandert de conclusie.
> Dit is expliciet gevlagd als het minst zekere deel van dit document
> (`CLAUDE.md`, checkpoint 4).

Wat wél zeker is, ongeacht het quotum: **24 calls per dag voor monitoring
en tot 46 op een drukke dag.** Die getallen komen uit de code.

## Wat de opties zijn, als het quotum inderdaad krap is

In volgorde van hoe goed ze bij het project passen:

**1. Sector en commodity naar FRED, waar dat kan.** FRED heeft dagelijkse
olie- en gasreeksen en maandelijkse metaalprijzen. Dat zou de commodity
agent van 10 Alpha Vantage-calls naar ~0 brengen, én — belangrijker — hem
van maandcadans naar dagcadans tillen, waardoor hij in cohort 0 kan
vóórspellen in plaats van pas in cohort v1 (roadmap deel A). Twee vliegen
in één klap. **Reeks-id's hier niet te verifiëren.**

**2. Een andere aanbieder voor de ETF-koersen.** De sector agent is met 11
calls de grootverbruiker. Er zijn gratis bronnen voor dagelijkse
slotkoersen met ruimere limieten. Kost een nieuwe fetch-implementatie,
maar de agent-structuur verandert niet — alleen `fetch_snapshot()`.

**3. Betaalde Alpha Vantage-tier.** Simpelste oplossing, kost geld per
maand. Voor een systeem dat zes maanden moet draaien is dat een reële
afweging tegen de tijd die optie 1 of 2 kost.

**4. Cadans verlagen** (bijv. commodity wekelijks). Werkt, maar kost
precies wat je niet wilt kwijtraken: waarnemingen. Bij een maandelijkse
bron is dagelijks pollen sowieso overkill, dus voor commodity is dit
verdedigbaar; voor sector niet.

**Wat je NIET moet doen:** het laten zoals het is en hopen dat het meevalt.
Als de calls stilvallen op de volatiele dagen, is dat het ene faalpatroon
dat de hele forward test ongeldig maakt, en je merkt het pas bij de
evaluatie in mei.

## Onderhoud

`tests/test_api_budget.py` telt deze aantallen uit de code en vergelijkt ze
met de getallen hierboven. Voeg je een reeks toe aan een agent, dan faalt
die test en moet dit document in dezelfde ronde bij — zodat het
callvolume niet ongemerkt kan groeien tot het een keer op de VPS omvalt.

## Per bron: wat we ophalen

| Bron | Agents | Reeksen | Kosten | Cadans |
|---|---|---|---|---|
| FRED | monetary_policy | FEDFUNDS, DGS10, DGS2, CPIAUCSL, UNRATE, T5YIE, T10YIE, WALCL | gratis | gemengd |
| FRED | financial | NFCI, BAMLH0A0HYM2, VIXCLS, T10Y2Y | gratis | dagelijks/wekelijks |
| FRED | economic | ICSA, UNRATE, PAYEMS | gratis | wekelijks/maandelijks |
| Alpha Vantage | currency | EUR/USD, USD/JPY, GBP/USD | tier-afhankelijk | continu |
| Alpha Vantage | sector | 11 SPDR Select Sector-ETF's (+ SPY bij deep-dive) | tier-afhankelijk | dagelijks |
| Alpha Vantage | commodity | WTI, Brent, aardgas, koper, aluminium, tarwe, maïs, katoen, suiker, koffie | tier-afhankelijk | maandelijks |

Elke bron is apart geregistreerd in de Source Registry (roadmap 1.4) met
een eigen `source_key` per (provider, domein), zodat de data-health van de
ene agent die van de andere niet kan maskeren.
