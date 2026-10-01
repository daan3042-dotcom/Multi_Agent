# Data die niet terug te halen is: beoordeling en plan

Hoort bij roadmap 1.2 (`expectations`, `events`), 1.4 (bronnen) en de T₀ᵇ-checklist,
"reeksenlijst per agent definitief". Opgesteld op 30-09-2026 uit DD's onderzoek met een
ander model (Fable 5.1, twee ronden), dat hier is getoetst aan wat dit systeem kan. **Alles
wat hieronder als "onbekend" staat, is niet geverifieerd** (checkpoint 4): dat moet met
een testaanroep op de VPS, niet uit het hoofd.

## Het kernprincipe (en het staat al in de roadmap)

Niet alle data is even kwetsbaar. Wat later met terugwerkende kracht te halen is, kost bij
vergeten niets. De klok begint alleen opnieuw bij data die je **niet** kunt terughalen. De roadmap
zegt dit al voor verwachtingen en nieuws (1.2: "niet retroactief te reconstrueren, dus nu
opslaan, later pas gebruiken"); het onderzoek breidt de lijst uit.

**Twee lagen** (het beste idee uit het onderzoek):

1. **Een breed ruw archief.** Opslag is goedkoop, dus alles wat niet terug te halen is, gaat erin,
   zonder dat een agent het ziet of erop triggert.
2. **Een smalle set per agent** die triggert en voorspelt. Elke extra reeks met een trigger geeft
   extra valse alarmen, en dan meet de forward test ruis.

Een reeks uit het archief kan later aan een agent worden gegeven zonder dat de klok opnieuw begint.
Wat een agent wél ziet en waarop hij voorspelt, is een keuze met een prompt-versie (een covariaat),
geen nieuw cohort.

## Wat we al hebben

- **Vier tijdstempels per claim** (`event_time`, `source_time`, `ingestion_time`, `analysis_time`) en de
  eerste print afgeleid uit onze eigen claims-historie: dat bewijst dat een voorspelling alleen gebruikte
  wat toen bekend was. Revisies worden gedetecteerd.
- **Wat ontbreekt:** het exacte **releasetijdstip**. We pollen één keer per dag om 07:15, dus we weten
  alleen "gezien op" en niet "gepubliceerd om". Voor voorspellingen op de maandagochtend is dat genoeg;
  voor het meten van de reactie op een release niet.
- **Van prijzen slaan we alleen de slotkoers op**, geen open, hoog, laag en volume.

## Beoordeling per categorie

| Categorie | Terug te halen? | Haalbaar met onze stack? |
|---|---|---|
| FRED-reeksen, ook eerste prints (ALFRED) | **ja**, geen haast | ja; ID's uit het hoofd, eerst testen |
| CFTC COT, Fed-teksten (statements, notulen), Beige Book | **ja**, gearchiveerd | ja, later |
| Consensus vóór macro-releases | nee | **nee, betaald** (geen gratis betrouwbare bron bekend) |
| Fed funds futures, FedWatch-kansen | nee (CME-data betaald) | onbekend: gratis voorkant (alleen eerste contract) of scraping |
| Nowcasts (GDPNow, NY Fed, Cleveland Fed) | deels (Atlanta Fed publiceert historie) | onbekend |
| VIX-familie als indexreeks (VIX3M, VVIX, SKEW) | **ja**, Cboe publiceert volledige historie | ja, geen haast |
| Optieketens, open interest per strike | onbekend: mogelijk **wel** via Alpha Vantage (`HISTORICAL_OPTIONS`) | onbekend, eerst testen |
| Intraday-bars | onbekend: mogelijk **wel** via Alpha Vantage (`TIME_SERIES_INTRADAY` met maandparameter) | onbekend, eerst testen |
| Indexsamenstelling en gewichten per datum (S&P 500, Nasdaq 100) | moeilijk | onbekend; SPY-holdings worden dagelijks gepubliceerd |
| Nieuwskoppen met tijdstempel | deels (`NEWS_SENTIMENT` van Alpha Vantage kent een periode) | onbekend |
| ISM, flash-PMI's, regionale Fed-surveys | nee | deels betaald, deels niet te scrapen |
| Voorspellingsmarkten (Kalshi, Polymarket) | grotendeels wel (handelshistorie) | onbekend |
| Ongecorrigeerde koersen, dividenden en splits apart | deels | ja voor onze ETF's |
| De eigen output van het systeem | n.v.t. | **ja, doen we al** (agent-runs, triggers, voorspellingen, model_id, prompt_version) |

De tweede en derde ronde van het onderzoek gaven zelf al toe dat de eerste lijst te veel als
"niet terug te halen" noemde (ALFRED, CFTC en de Fed archiveren). **Mijn aanvullende kanttekening:** de
aanname "gratis bronnen gaan maar 30 tot 60 dagen terug" geldt niet voor ons betaalde Alpha Vantage-plan;
een deel van de opties en intraday-data is daarmee mogelijk wél recoverable. Dat moet gemeten worden voordat
we er een archief voor bouwen.

## Randvoorwaarden die het onderzoek niet kende

- **Geen gecompileerde afhankelijkheden** (CLAUDE.md, regel 2). De veelgenoemde Yahoo-tickers zijn alleen via
  de onofficiële `yfinance`-bibliotheek makkelijk te halen, en die haalt pandas en numpy binnen. Yahoo zelf is
  onofficieel en kan zonder waarschuwing veranderen: een slechte basis voor een onbeheerd systeem.
- **Het Alpha Vantage-incident van 29-09** (lege `{}` na ruim 100 aanroepen, oorzaak onbekend). Een archief van
  ~520 aandelen dagelijks is ruim 500 aanroepen per dag en moet dus buiten de dagelijkse run, met eigen
  foutafhandeling.
- **Opslag.** Optieketens van acht onderliggende waarden per dag zijn vele megabytes; in SQLite loopt dat op.
  Voorstel: gecomprimeerde bestanden (gzip'd CSV of JSON, geen Parquet want dat vraagt een gecompileerde
  bibliotheek) in de bestaande DigitalOcean Space, met alleen een index in SQLite.
- **Eigen job, niet de dagelijkse run.** T₀ᵃ hangt van de ingestie-run af; het archief mag die nooit kunnen
  laten falen of vertragen.
- **Licenties.** Bewaren voor eigen gebruik is meestal toegestaan, doorgeven niet. Per bron nagaan.

## Voorstel in fases

**Fase A, eerst weten wat kan (alleen lezen, klein). GEBOUWD op 30-09: `probe_sources.py`.** Een probe-script dat per kandidaatbron één aanroep doet
en meldt: bereikbaar, gratis of betaald, hoe ver historie, of het een archief heeft. Dat vervangt het
gokken: Alpha Vantage (`HISTORICAL_OPTIONS`, `REALTIME_OPTIONS`, `TIME_SERIES_INTRADAY` met maand,
`NEWS_SENTIMENT`), de FRED-ID's uit het onderzoek, Cboe-CSV's, SPY-holdings, Atlanta Fed Market Probability
Tracker.

### Het probe-script gebruiken

```bash
cd /opt/multi_agent
.venv/bin/python probe_sources.py --json probe.json
```

Ongeveer 2 tot 8 minuten (een seconde pauze per Alpha Vantage-aanroep, en die aanroepen zijn soms traag). Het toont een tabel met per bron:
status, kosten, of het terug te halen is, de nieuwste waarneming en de achterstand, en het **advies**; daaronder de
details (wat de bron zelf zei, en de **eenheid** bij FRED-reeksen) en een telling per advies. Opties: `--zonder-av` (geen
Alpha Vantage), `--alleen opties intraday` (filter op categorie), `--json PAD` (kopie van het rapport).

**Wat het rapport wel en niet is.** Het meet en adviseert; het slaat niets op. Het is de invoer voor laag 1, niet laag 1
zelf. De adviesregel is klein en staat in `sources/probe.py::bepaal_advies`: niet gemeten of niet te krijgen wordt een
beslissing voor DD; bereikbaar en niet terug te halen wordt archief nu; bereikbaar en terug te halen wordt archief later;
onbekend wordt eerst de diepte meten. De herstelbaarheid van een "nu"-meting (bijvoorbeeld optieketens van vandaag)
volgt uit de bijbehorende historische meting: lukt die niet, dan is elke dag zonder archief verloren.

**Wat een `fout` of `niet bereikbaar` bij een openbare bron betekent.** Een aantal url's en dataset-ID's (Cboe, State
Street, CFTC, Kalshi, Polymarket, de FRED-ID's) komt uit het onderzoek en uit het hoofd. Een 404 is dan geen storing
maar een bevinding: de bron heet anders of bestaat niet meer. De rij zegt dat, en we corrigeren de url.

**Veiligheid.** Sleutels staan nooit in de uitvoer (elke tekst gaat door `redact_secrets`), en het script schrijft niets
weg behalve de JSON op verzoek. Niet met `-v` of een debug-vlag draaien: urllib3 logt dan volledige url's. Niet op
dezelfde minuut als de cron van 07:15 draaien.

**Fase B, goedkoop en meteen nuttig (FRED, geen nieuwe bron).**
- `DFEDTARU` en `DFEDTARL` (target range) en `DFF` (dagelijks) naast `FEDFUNDS`. Dit is meer dan een
  archiefpunt, zie hieronder.
- Vooral ook: releasedatum vastleggen waar de bron het geeft.

**Fase C, wat geld of werk kost en écht niet terug te halen is.** Consensus en fed funds futures. Beslissen
met een budget erbij; geen bouw zonder verkende bron.

**Niet nu:** de volledige lijst van tientallen tickers, intraday voor alle futures, en alles wat betaald is.

## Eén concrete verbetering die uit dit onderzoek volgt

`FEDFUNDS` is een **maandgemiddelde**. Onze twee FOMC-doelen ("hoger na de volgende vergadering") worden nu
afgewikkeld op de eerste FEDFUNDS-waarneming ná de vergadering, en die verschijnt pas ongeveer vijf tot zes weken
later en mengt de dagen vóór en ná het besluit. `DFEDTARU` (bovengrens van de doelrange, dagelijks) verandert
precies op de besluitdag met een stap van 0,25: geen afrondingsruis, geen wachttijd, en het is meteen een betere
trigger dan de huidige FEDFUNDS-drempel. Dat is een wijziging van de resolutieregel, dus **vóór de freeze**
doen, niet erna (CLAUDE.md). Verifiëren op de VPS dat `DFEDTARU` beschikbaar en actueel is.

## Twee beslissingen die dit onderzoek aanscherpt

1. **Wie is eigenaar van inflatie en werkloosheid?** `unemployment_rate` staat nu in twee agents met dezelfde
   drempel, dus één cijfer geeft twee triggers. Dat is destijds bewust gekozen (`docs/agents.md`), maar is een
   open vraag in `docs/project-state.md`.
2. **Loongroei en core CPI** (de twee lege knopen) zijn FRED-reeksen en dus herstelbaar met back-fill: uitstellen
   kost geen testperiode. Wat een agent er niet van gezien heeft, is wel een verschil in wat hij wist, maar dat is
   een prompt-versie en geen nieuw cohort.
