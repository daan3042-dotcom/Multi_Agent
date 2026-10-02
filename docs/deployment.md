# Deployment — de VPS inrichten (roadmap 1.11, fase 0a)

Runbook voor taak 0a-1/0a-2/0a-4 uit `docs/roadmap.md` (VPS bestellen,
keys inrichten, cron met `flock`). DD voert dit uit op de eigen VPS —
Claude Code heeft hier geen toegang (netwerk-egress in de sandbox is
geblokkeerd, en er is geen SSH-verbinding met de VPS vanuit deze sessie).

**Checkpoint 3 uit `CLAUDE.md` geldt hier expliciet: dit is een uitrol
naar de VPS.** Zie "Dry-run-plan" onderaan — geen `--deep-dives` en geen
"vertrouwd" totdat dat plan doorlopen is.

## 1. Machine klaarzetten

Op de DigitalOcean-droplet (SSH erin):

```bash
python3 --version   # 3.12+ nodig; als het lager is, zie DigitalOcean se
                     # eigen Python-repo/deadsnakes-instructies voor de
                     # gekozen distro
timedatectl          # controleer dat de tijdzone UTC is (of zet 'm:
                     # sudo timedatectl set-timezone UTC) -- run_daily.py
                     # en de cron-tijden in dit document gaan uit van UTC
```

## 2. Repo uitchecken en dependencies installeren

```bash
sudo mkdir -p /opt/multi_agent
sudo chown $USER:$USER /opt/multi_agent
# De machine hoort ALTIJD de default branch te volgen, niet een
# feature-branch. Zie sectie 6 hieronder voor waarom dat uitmaakt.
git clone --branch claude/beautiful-cori-f9p6h6 <repo-url> /opt/multi_agent
cd /opt/multi_agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. `.env` invullen

```bash
cp .env.example .env
chmod 600 .env       # bevat API-keys, alleen leesbaar voor deze user
nano .env            # FRED_API_KEY, ALPHAVANTAGE_API_KEY, MI_DB_PATH,
                      # MI_WEBHOOK_URL invullen (ANTHROPIC_API_KEY pas
                      # nodig zodra --deep-dives aan gaat, zie hieronder).
                      # MI_COHORT LEEG LATEN tot T₀ᵇ, zie "Het cohort" hieronder.
```

`run_daily.sh` (repo-root) laadt dit bestand automatisch vóór elke run —
zie dat script se eigen commentaar voor waarom (cron laadt geen
shell-profile, en run_daily.py zelf heeft geen dotenv-dependency).

## 4. Handmatige testrun (VÓÓR cron)

```bash
cd /opt/multi_agent
./run_daily.sh
echo "exit code: $?"
```

Verwacht: exit code 0, en een melding op je telefoon als `MI_WEBHOOK_URL`
klopt (zie `run_daily.py`'s eigen exit-code-tabel: 0 = niets mis, 1 =
minstens één agent mislukte, 2 = de cyclus zelf kon niet draaien). Faalt
dit, ga NIET door naar cron — debug hier eerst (vaak: verkeerde API-key,
`.env` niet gevonden omdat het script niet vanuit de eigen map gestart is).

**Let op de 0a-3-bevinding uit `docs/data-sources.md`:** de Alpha
Vantage-monitoring-bodem (24 calls/dag) zit al tegen de publieke
free-tier-limiet van 25/dag. Bevestig dat cijfer tegen je eigen key
(bijv. via het AV-dashboard) vóórdat je vertrouwt op een schone eerste
run — een falende sector/commodity-pull op dag 1 kan hierdoor komen.

## 5. Cron installeren

```bash
crontab -e
```

Voeg toe:

```
15 7 * * 1-5 /usr/bin/flock -n /tmp/mi-daily.lock /opt/multi_agent/run_daily.sh >> /var/log/mi/daily.log 2>&1
```

```bash
sudo mkdir -p /var/log/mi
sudo chown $USER:$USER /var/log/mi
```

Logrotatie (voorkomt een ongelimiteerd groeiend logbestand):

```bash
sudo tee /etc/logrotate.d/mi-daily <<'EOF'
/var/log/mi/daily.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
}
EOF
```

## 6. De VPS bijwerken na een merge

**De machine volgt de default branch (`claude/beautiful-cori-f9p6h6`), nooit
een feature-branch.** Een feature-branch kan gesloten, hernoemd of verwijderd
worden zonder dat iemand aan de VPS denkt; dan faalt de volgende `git pull`
stil en staat de ingestieklok stil op precies de dagen die je niet kunt
inhalen. De default branch verdwijnt niet.

### Standaardprocedure

```bash
cd /opt/multi_agent
git fetch origin
git status                       # werkboom moet schoon zijn; .env staat in .gitignore
git pull --ff-only origin claude/beautiful-cori-f9p6h6
.venv/bin/pip install -r requirements.txt   # alleen nodig als requirements.txt veranderde
.venv/bin/python -m pytest -q    # moet groen zijn VOORDAT de volgende cron vuurt
```

`--ff-only` is bewust: als dat weigert, is er lokaal iets gewijzigd op de VPS
en dat wil je weten in plaats van wegmergen.

### Eenmalig: overstappen van een feature-branch naar de default

Nodig op 28-09-2026, toen de machine nog `claude/ecstatic-fermat-3uunqw`
volgde terwijl al dat werk via PR #4 in de default branch terecht was
gekomen:

```bash
cd /opt/multi_agent
git fetch origin
git checkout claude/beautiful-cori-f9p6h6
git branch --set-upstream-to=origin/claude/beautiful-cori-f9p6h6
git pull --ff-only
git remote set-head origin -a    # lokale notie van de default bijwerken
.venv/bin/python -m pytest -q
```

### Wat je daarna in `daily.log` moet zien

Na deze specifieke overstap zijn er drie dingen veranderd die zichtbaar
horen te worden in de eerstvolgende run:

1. **De monetary agent haalt 8 FRED-reeksen op in plaats van 4.** Er komen
   claims bij voor `2y_treasury_yield`, `inflation_expectations_5y`,
   `inflation_expectations_10y` en `fed_balance_sheet`. Ontbreken die, dan
   is de pull mislukt of klopt de reeks-id niet.
2. **De Sahm Rule rekent met 15 waarnemingen in plaats van 14.** Bij een
   deep-dive op de economic agent hoort er een Sahm-claim te verschijnen.
   Blijft die weg, dan levert FRED te weinig UNRATE-historie -- dat is geen
   fout maar een weigering (het model rekent niet op een te korte reeks),
   en het hoort eenmalig gecontroleerd te worden.
3. **De economic agent draait mee.** `agent_runs` hoort een regel met
   `domain='economic'` te krijgen.

Controleren kan zonder de logs door te spitten:

```bash
sqlite3 "$MI_DB_PATH" "SELECT domain, mode, run_at, success, trigger_count
                       FROM agent_runs ORDER BY run_at DESC LIMIT 10;"
sqlite3 "$MI_DB_PATH" "SELECT metric_key, value_json FROM claims
                       WHERE domain='monetary_policy'
                       ORDER BY analysis_time DESC LIMIT 10;"
```

### De melding "Werkdagen zonder succesvolle run"

Elke run kijkt zeven dagen terug of er dagen waren zonder enkele succesvolle
monitoring-run. Dat is een **kritieke** melding: het is het enige signaal dat een
run nooit gebeurde (cron uit, venv stuk, VPS uit).

**Alleen werkdagen tellen mee** (`EXPECTED_RUN_WEEKDAYS` in `runtime/daily.py`),
omdat de cron `15 7 * * 1-5` alleen ma t/m vr draait. Tot 29-09 telde de code ook
zaterdag en zondag mee: elk weekend zou als storing zijn gemeld, bij elke run van
ma t/m vr, en een alarm dat dagelijks afgaat wordt genegeerd. Een test leest de
cron-regel in dit document en controleert dat de code hetzelfde aanneemt; verander
je de cron (bijvoorbeeld naar `1-7`), dan faalt die test totdat je de constante
meeneemt.

**Rond de start van het systeem** (eind september 2026) blijft de melding een
paar dagen komen voor werkdagen vóór de VPS bestond. Dat is verwacht en verdwijnt
vanzelf zodra die dagen uit het venster van zeven dagen vallen (op 3 oktober is het
schoon). Het maakt de exit code van die runs `1`; dat is geen agent-fout.

### Drie tolerances die op deze machine geverifieerd moeten worden

Niet vanuit de ontwikkelomgeving te controleren (geen netwerk naar FRED),
dus dit is de eerste plek waar het kan. Klopt een eenheid niet, dan staat de
drempel ordes van grootte naast de werkelijkheid en triggert hij nooit of
altijd:

| Metric | Aanname | Drempel |
|---|---|---|
| `fed_balance_sheet` (WALCL) | miljoenen USD, niveau ~6-7 miljoen | 100.000 |
| `initial_claims` (ICSA) | aantal aanvragen, niveau ~200.000-250.000 | 25.000 |
| `nonfarm_payrolls` (PAYEMS) | duizenden personen, niveau ~155.000-160.000 | 250 |

```bash
sqlite3 "$MI_DB_PATH" "SELECT metric_key, value_json FROM claims
                       WHERE metric_key IN ('fed_balance_sheet','initial_claims','nonfarm_payrolls')
                       ORDER BY analysis_time DESC LIMIT 6;"
```

## Dry-run-plan (checkpoint 3, verplicht vóór "vertrouwd")

**Duur: 3 dagen, monitoring-only (geen `--deep-dives` in de cron-regel
hierboven).** Dit is een KLEINERE, eerdere dry-run dan de volledige
dry-run-week uit fase 3b (27 okt – 9 nov, incl. forecast-ronde en
resolver, die pas relevant is zodra `predictions` bestaat) — dit hier is
puur "haalt de ingestieklok elke dag zonder tussenkomst echte data op".

**Wat je elke dag in de logs checkt (`/var/log/mi/daily.log`):**
1. Exit code 0 (of 1 met een begrijpelijke reden — een tijdelijke
   API-hapering is geen paniek, drie dagen op rij falen wel).
2. Kwam de webhook-melding daadwerkelijk aan op je telefoon (test dit
   ook door één keer bewust een foute API-key te zetten en te zien of de
   melding klopt)?
3. `sqlite3 market_intelligence.db "SELECT domain, mode, run_at, success FROM agent_runs ORDER BY run_at DESC LIMIT 10;"`
   — vijf agents, elke dag een nieuwe rij, `success=1`.
4. Geen dubbele rijen voor dezelfde dag (zou op een atomiciteits- of
   idempotency-bug wijzen — zie roadmap 1.7/1.11).

**Na 3 schone dagen:** zie het aparte plan hieronder ("Dry-run-plan voor
`--deep-dives`"). **T₀ᵃ is gehaald** na zeven werkdagen op rij ingestie zonder
handmatige actie (roadmap 1.11, herzien op 30-09 naar 7 oktober, op 01-10 naar 12 oktober en op 02-10 naar op zijn vroegst 13 oktober, met de strenge definitie van een schone dag: alle agents `ok` én geen volledigheidstrigger). Een eerdere
versie van deze zin koppelde T₀ᵃ aan zeven dagen mét `--deep-dives`; dat is de
voorspelmeting (T₀ᵇ), niet de ingestieklok, en is rechtgezet.

**Let op wat die vlag sinds 28-09 nog meer aanzet:** de wekelijkse
forecast-ronde (roadmap 2.0) draait mee op de maandagcyclus, mits er een
Anthropic-client is. Er is dus GEEN aparte cron-regel voor; de bestaande
`15 7 * * 1-5` dekt hem. Controleer op de eerste maandag na het aanzetten:

```bash
sqlite3 market_intelligence.db \
  "SELECT agent, COUNT(*) FROM predictions GROUP BY agent ORDER BY agent;"
```

Groepeer op `agent` en niet op `domain`: de baselines schrijven onder het
domein van de agent waarmee ze vergeleken worden, dus per domein tellen ze
mee en klopt het getal niet meer. Verwacht per week bij volledige historie
en een bevroren ridge: **de vijf agents samen 57 rijen** (sector 22,
financial 12, currency 9, monetary_policy 8, economic 6) en elk van de drie
`baseline:*` **55 rijen** (57 minus de twee FEDFUNDS-doelen, die geen
baseline krijgen). Staat er een agent op nul of op een te laag aantal, kijk
dan in het log naar regels die beginnen met `Forecast-probleem:` of
`Baseline-probleem:` — een deels mislukte ronde gooit de geldige
voorspellingen niet weg, dus een lager aantal is geen crash maar wel een
gat.

### De historische back-fill (roadmap 1.11, 0b-1)

Eenmalig, en sinds 29-09 **veilig om opnieuw te draaien**: elke reeks wordt
apart afgehandeld. Een reeks die al historie heeft (≥20 claims ouder dan 30
dagen) wordt overgeslagen, een mislukte reeks meldt de reden van de bron, en
er ontstaan nooit dubbele claims. Vóór 29-09 slikte het script elke fout stil
in (ook Alpha Vantage's "limiet bereikt", dat als HTTP 200 met alleen tekst
komt) en telde een domein als geslaagd zodra één reeks data gaf.

**Je hoeft `.env` niet zelf in te laden.** `backfill.py` en `fit_baselines.py`
lezen het `.env` naast het script zelf in (`runtime/env.py`); een variabele die je
expliciet zet wint altijd, en waarden worden nooit getoond. Vóór 29-09 moest je
eerst `set -a; source .env; set +a` doen, en vergeten gaf een "API-key niet
gevonden" (bij `fit_baselines.py` ergens anders: een stille terugval op een
database in de huidige map).

```bash
cd /opt/multi_agent

# Alles in één keer. Reeksen die er al staan worden overgeslagen; reeksen die
# er sinds de vorige back-fill bij zijn gekomen (DGS2, T5YIE, T10YIE, WALCL bij
# monetary_policy) worden alsnog gevuld.
.venv/bin/python backfill.py
```

**Wat je in de uitvoer leest**, per reeks:

- `OPGESLAGEN  N claims` — gelukt.
- `overgeslagen al historie aanwezig` — stond er al, niet aangeraakt.
- `MISLUKT  <reden van de bron>` — niet gevuld. Lees de reden:
  - *"reached the ... requests per day limit"* → quota. Wacht tot morgen of
    check je tier.
  - *"premium endpoint"* → dit endpoint zit niet in je plan.
  - *"api_key is invalid"* / *"invalid API call"* → verkeerde of niet-actieve key.
  - *"LEEG antwoord ({})"* → Alpha Vantage antwoordde met HTTP 200 en niets erin, ook
    voor endpoints die eerder werkten. Niet gedocumenteerd; gezien op 29-09 na ruim
    100 calls op één dag. Stop met testen, wacht, en test met één call; houdt het aan,
    mail hun support.
  - *"ReadTimeout"* / *"timed out"* → Alpha Vantage was te traag (gemeten: tot 30 s
    voor één call). Draai opnieuw; de timeout staat op 120 s.

**De uitvoer bevat nooit je API-key.** `requests` zet de volledige url, query
inclusief, in zijn foutmeldingen; het script vervangt `apikey=...` door
`apikey=<verborgen>` voordat het iets toont.

**Exit code 0** betekent: elke gevraagde reeks heeft nu historie. **Exit code 1**
betekent: minstens één reeks is niet gevuld, en de laatste regels noemen welke.
Draai gewoon opnieuw — alleen die reeksen worden dan opgehaald.

**Controleren dat alles erin zit:**

```bash
sqlite3 "$MI_DB_PATH" "SELECT domain, metric_key, COUNT(*) AS claims, MIN(source_time) AS vanaf
                       FROM claims WHERE metric_key IS NOT NULL
                       GROUP BY domain, metric_key ORDER BY domain, metric_key;"
```

Elke reeks hoort hier honderden tot duizenden claims te hebben (dagreeksen
~5.000 bij 20 jaar). Een reeks met een paar rijen is niet gebackfilld. Dat ziet
`fit_baselines.py` ook, dus draai deze controle vóór je de ridge fit.

### Het cohort: dry-run versus echte meting (`MI_COHORT`)

**Laat `MI_COHORT` leeg in `.env` tot T₀ᵇ.** Leeg betekent `dry_run`: alle
voorspellingen en baselines die de wekelijkse ronde schrijft, krijgen dat
label en tellen dus NIET mee in het track record. Dat is precies wat je in
de dry-run-week wilt: de hele keten (forecast, baselines, resolver, scores)
draait echt en wordt echt gescoord, maar er raakt niets het echte cohort
vervuild vóór de freeze.

Het label is definitief zodra een voorspelling is opgeslagen — de
`predictions`-tabel heeft geen update-pad. Daarom is de default de veilige
kant, en is het echte cohort iets dat je bewust aanzet.

**Controleren wat er staat:**

```bash
sqlite3 market_intelligence.db \
  "SELECT cohort, COUNT(*) FROM predictions GROUP BY cohort;"
```

Vóór T₀ᵇ verwacht je hier **alleen `dry_run`**. Staat er `cohort_0`, dan is
`MI_COHORT` te vroeg gezet: stop, en meld het voordat er nog een ronde draait.

**De overgang op T₀ᵇ (één handeling, na de freeze):**

1. Freeze bevestigd met versienummers (CLAUDE.md checkpoint 5).
1b. **Trigger-versie vastleggen.** Zet in `src/contract/trigger_version.py`
   `FROZEN_TRIGGER_VERSION = "v2"` (of welke versie de freeze bevestigde),
   laat de tests draaien, merge en werk de VPS bij. Zonder deze stap
   weigert `run_daily.py` onder `MI_COHORT=cohort_0` te starten (exit 2,
   met de reden in de log): een drempel die na de klokstart verschuift start
   een nieuw cohort, en dat hoort een bewuste stap te zijn.
2. In `.env` op de VPS: `MI_COHORT=cohort_0`. Geen aanhalingstekens, geen
   spatie rond het `=`.
3. Draai `./run_daily.sh` (of wacht op de cron) en lees de eerste regels van
   het log. Er hoort te staan:
   `Cohort voor nieuwe voorspellingen: cohort_0 (ECHT COHORT -- telt mee in het track record)`
   gevolgd door `Trigger-versie: v2`. Onder `dry_run` staat die laatste regel er
   ook: zo zie je met welke regels er gedraaid is.
4. Na de eerstvolgende wekelijkse ronde: dezelfde SQL als hierboven. Er
   hoort nu een `cohort_0`-groep te staan die groeit.

**Vergeten te schakelen** is de fout die overblijft, en die is te
herstellen: elke run logt het cohort, dus je ziet `telt NIET mee` in
`daily.log`. De eerste weken staan dan onder `dry_run`; de klok start
gewoon een ronde later. **Een typefout** (`cohort0`, `Cohort_0`) laat
`run_daily.py` met exit 2 stoppen voor er iets gebeurt, en meldt welke
waarden wel mogen.

### Het trigger-kalibratierapport (roadmap 1.5) — alleen lezen

Hoe vaak zou elke triggerdrempel de afgelopen tientallen jaren gevuurd hebben? De
huidige tolerances zijn illustratieve plaatshouders, en na T₀ᵇ mogen ze niet meer
verschuiven zonder een nieuw cohort te starten. Dit is het moment om ze met open ogen
te kiezen. Het rapport **wijzigt niets** (geen drempel, geen agent, niets in de
database) en doet geen calls naar Alpha Vantage.

```bash
cd /opt/multi_agent
.venv/bin/python calibrate_triggers.py                  # alle 40 reeksen
.venv/bin/python calibrate_triggers.py --domain sector  # één domein, korter om te plakken
```

Drie tabellen:

1. **Hoe vaak vuurt de huidige drempel** (per jaar, over alles / 10 jaar / 3 jaar / 1 jaar),
   plus een kolom `3j,rel` met dezelfde drempel uitgedrukt als percentage van het huidige
   niveau. Verschillen `3j` en `3j,rel` sterk, dan schuift een vaste, absolute drempel niet
   mee met het niveau. Dat is het geval bij koersen (een ETF stond in 1999 op ~$25, nu op
   ~$250). De gecorrigeerde kolom staat alleen bij reeksen die niet rond nul bewegen; bij een
   spread of index die door nul gaat (10Y-2Y, NFCI) zegt een percentage niets.
2. **Welke drempel hoort bij 2, 5 en 10 triggers per jaar** (laatste 3 jaar). Per jaar en niet als
   percentage van de dagen: 2% is ~5 triggers per jaar bij een dagreeks maar ~0,24 bij een maandreeks.
3. **Het verwachte aantal triggers per jaar** per domein bij de huidige drempels.

De kolom `oordeel` noemt wat opvalt: `vuurt nooit`, `vuurt vaak` (meer dan 25 per jaar),
`vuurt zelden` (minder dan 1 per jaar), `wisselt sterk per periode`, `niveau-afhankelijk`,
`korte historie`. Die drempels zijn leeshulpen, geen regels, en tellen per jaar zodat ze voor
dag-, week- en maandreeksen hetzelfde betekenen.

**Let op:** `high_yield_credit_spread` heeft maar ~3 jaar historie, dus daar zegt "alles"
niets meer dan "3j". De commodity-reeksen zijn maandelijks (sinds 29-09 met ~35 jaar historie): een reeks kan er hooguit twaalf keer per jaar vuren.

### De ridge-baseline fitten en bevriezen (roadmap 4.6) — eenmalig, na de back-fill

De derde baseline moet gefit worden op de historie, en daarna staat hij
vast. Dat is een **freeze-beslissing** (CLAUDE.md checkpoint 5): doe het
pas als de volledige back-fill erin zit, ook de Alpha Vantage-helft. Anders
hebben currency en sector te weinig historie en worden ze overgeslagen —
en een ridge die je later moet vervangen is een nieuwe specversie.

```bash
cd /opt/multi_agent

# 1. Droog: fit alles, toon de diagnostiek, schrijf NIETS.
.venv/bin/python fit_baselines.py

# 2. Pas als je tevreden bent: bevries. ONOMKEERBAAR.
.venv/bin/python fit_baselines.py --freeze
```

**Wat je in de uitvoer bekijkt:**

- **Geen regels met `MISLUKT`.** Staat er wel een, dan is de back-fill niet
  klaar voor dat doel (de reden staat erachter). Bevries pas als alles fit.
- **`weggelaten`** achter een doel: een input met minder dan 80% van de
  trainingsrijen is uit het model gelaten. Dat zijn ook reeksen die het LLM wél
  ziet (bijvoorbeeld de balans van de Fed bij de 10-jaars rente); zie de
  freeze-punten in `docs/project-state.md`.
- **`oos/rw`**: de uit-de-steekproef-fout gedeeld door die van "geen verandering".
  Het model kiest uit een raster dat "geen verandering" bevat, dus deze waarde kan
  **niet meer ruim boven 1,000 uitkomen**. Staat er toch iets als 1,01 of hoger, dan
  is dat een bug: meld het, bevries niet. **Waarden net onder 1 (0,97 tot 1,00) zijn
  geen bewijs van voorspelkracht**: de cross-validatie kiest de toevallig beste uit
  14 combinaties (winner's curse). Echte structuur zie je aan duidelijk lagere
  waarden, zoals VIX h=63 op 0,88.
- **`rijen`**: de trainingsrijen. Ze overlappen (vensters van 21 of 63
  dagen), dus de effectieve n ligt er ver onder; kijk alleen naar de orde
  van grootte.

Controle achteraf:

```bash
sqlite3 market_intelligence.db \
  "SELECT domain, COUNT(*) FROM baseline_models GROUP BY domain;"
```

Verwacht **55** in totaal (sector 22, financial 12, currency 9,
monetary_policy 6, economic 6). Tot dit gedaan is, meldt de wekelijkse
ronde elke maandag "nog geen enkel bevroren ridge-model" en draaien
persistence en climatology gewoon door.

**De resolver draait elke dag mee** en kost niets (geen API-calls, geen
LLM). Vanaf het moment dat de eerste voorspellingen aflopen — vijf
handelsdagen na de eerste ronde — hoort dit te groeien:

```bash
sqlite3 market_intelligence.db \
  "SELECT status, COUNT(*) FROM evaluations GROUP BY status;"
```

Alleen `resolved` is goed. Verschijnt er `unresolvable`, kijk dan naar de
reden (`SELECT reason FROM evaluations WHERE status = 'unresolvable'`):
dat is een voorspelling die nooit meer gescoord wordt en dus definitief uit
het cohort is. De melding zegt het ook, maar het patroon zie je hier.

De forecast-ronde probeert het de rest van de week elke ochtend opnieuw, maar
**alleen op de dagen dat de cron draait**. Met `15 7 * * 1-5` zijn dat
maandag t/m vrijdag: vier inhaalkansen na een mislukte maandag, en daarna
is die week definitief leeg. Zie je op vrijdagochtend nog steeds nul
voorspellingen voor die week, dan is dat het laatste moment om handmatig
in te grijpen (`./run_daily.sh --deep-dives`) — zaterdag is te laat.

**Stop en meld het hier** als er op enig moment een dag ONTBREEKT (geen
enkele rij in `agent_runs` voor die datum) — dat is precies het
faalscenario dat de externe heartbeat hieronder moet opvangen als niemand
kijkt, maar tijdens de dry-run kijk je zelf.

**Correctie t.o.v. een eerdere versie van dit document:** back-up en
heartbeat hoeven NIET te wachten tot na de dry-run — ze draaien los van
`run_daily.py` zelf en kunnen de dry-run niet verstoren. Sterker nog: elke
dag zonder back-up is een dag data die je kwijt bent bij een VPS-storing,
en de heartbeat is juist nuttig TIJDENS de dry-run (vangt op als jij een
dag vergeet te checken). Beide dus gewoon nu opzetten, parallel aan de
dry-run.

## De T₀ᵃ-teller (alleen lezen)

```bash
cd /opt/multi_agent && .venv/bin/python t0a_status.py
```

Toont per werkdag vanaf 2 oktober `schoon`, `NIET SCHOON` (met de reden, bijvoorbeeld de ontbrekende reeks), `GEEN RUN` of `nog niet`,
de lopende reeks van zeven en de vroegste datum voor T₀ᵃ. Schoon = alle zes agents ok én geen volledigheidstrigger. Gebruik `--vanaf <datum>`
als de telling na een nieuwe breuk opnieuw moet beginnen. Het script schrijft niets. "Mogelijk handmatig" betekent: een run buiten 07:00 tot 09:00 UTC; beoordeel zelf.

## Het freeze-overzicht (alleen lezen)

```bash
cd /opt/multi_agent && .venv/bin/python freeze_status.py
```

Toont elk freeze-punt (contract, kwantielen, graaf, doelenlijst, resolver, scorer, trigger-regels en pin, model, prompts, evidence-sheet,
baselines, ridge, cohort, prior, voorspellingen per cohort) met de huidige waarde uit code en database en een status: `BEVROREN`, `TE BEVESTIGEN`,
`OPEN BESLISSING`, `WIJZIGING ZONDER VERSIE` of `LET OP`. Het script schrijft niets, zet geen pin, fit geen ridge en raakt `MI_COHORT` niet aan:
**het is een overzicht, geen freeze.**

Onderaan staat een tweede blok, **"Voorwaarden vóór de klok"**: wat er vóór de freeze gedaan moet zijn (T₀ᵃ, 14 werkdagen op rij zonder
handmatige actie, begeleide deep-dive-testrun, forecast-rondes, resolver, pseudo-OOS-run, dry-run-week, reeksenlijst, back-up-herstel,
heartbeat-test, API-quota). Drie statussen, en het verschil telt: **AF** (uit de data af te leiden en voldaan; alleen T₀ᵃ en de 14 werkdagen kunnen dit
worden), **NOG NIET AF** (uit de data af te leiden en niet voldaan) en **ZELF CONTROLEREN** (de data toont dat iets gedaan is, niet of het
*goed* is, of het is niet uit de data af te leiden: een testrun, een herstelde back-up, een doorlopen dry-run-week). Zonder database (bijvoorbeeld
buiten de VPS) staat elke datagedreven regel op ZELF CONTROLEREN met "onbekend", nooit op NOG NIET AF. Forecast-rondes met meer dan 5% gemiste
voorspellingen krijgen LET OP (contract heroverwegen). De dry-run-week-data (27-10 t/m 09-11) staan als constante in `src/runtime/freeze_voorwaarden.py`. Wijzigt iemand de doelenlijst of de evidence-sheet zonder het versienummer in
`src/contract/freeze_versions.py` op te hogen, dan faalt `tests/test_freeze_guard.py` (en voor de evidence-sheet ook de prompt-test).

**`AKKOORD DD` (02-10-2026).** Een punt dat DD voorlopig heeft goedgekeurd staat als `AKKOORD DD` in plaats van `TE BEVESTIGEN`. Het akkoord hangt aan de waarde zoals het overzicht hem toont (`contract/freeze_versions.py::AKKOORDEN_DD`) en vervalt vanzelf, met een melding, zodra die waarde verandert. Het is geen freeze en telt niet als `BEVROREN`; bij de freeze bevestig je nog steeds met de versienummers erbij.

## Dry-run-plan voor `--deep-dives` (checkpoint 3) — **goedgekeurd door DD op 30-09-2026, nog niet gestart**

Nog niets hiervan is aangezet. `--deep-dives` staat niet in de cron-regel, en dat
blijft zo tot de voorwaarden hieronder gehaald zijn (T₀ᵃ op zijn vroegst 13 oktober). DD keurde het plan
goed met één aanpassing: de maandgrens voor LLM-kosten staat op **$200**, niet $20.

### Wat de vlag aanzet (uit de code, `runtime/daily.py`)

Eén vlag, drie dingen, alle achter één Anthropic-client:

1. **Deep-dives** voor elk domein waarvan minstens één trigger vuurde. Per domein
   twee LLM-aanroepen: de duiding (max. 800 tokens) en de kwaliteitscontrole
   (`qc.default_llm_review`). De manager bundelt gelijktijdige triggers per domein.
2. **De wekelijkse forecast-ronde:** één aanroep per agent (vijf agents, commodity
   voorspelt niet), alle doelen in één JSON (max. 2000 tokens). **Hij draait niet
   per se op maandag maar op elke werkdag zolang de ISO-week nog geen geslaagde
   ronde kent.** Wie de vlag op een woensdag aanzet, krijgt dus dezelfde dag al een
   ronde voor die week.
3. **De baseline-ronde** (deterministisch, kost niets): persistence en climatology.
   De ridge draait pas mee als hij is bevroren; tot dan meldt de ronde dat, en dat
   geeft **exit code 1 op de dag dat de ronde draait**. Dat is verwacht, geen storing.

Alles draait onder `MI_COHORT=dry_run` (de standaard): geen enkele voorspelling
telt mee. Een fout in de LLM-fase blokkeert de ingestie niet: monitoring is dan al
opgeslagen, en elke agent zit in zijn eigen foutisolatie.

### Wat het kost (ruwe schatting, niet gemeten)

Tokens zijn geschat uit de promptlengtes in de code (systeemprompts 1.400 tot 2.200
tekens, plus de claims van het domein): ongeveer 2.000 invoer- en 1.000 uitvoertokens
per forecast-aanroep, en 1.500 in en 800 uit per deep-dive plus een korte kwaliteitscontrole.
Tegen de prijs van het huidige model (**sinds 01-10 `claude-sonnet-5-5`**, $2 per miljoen invoer- en $10 per
miljoen uitvoertokens; was `claude-sonnet-4-6` met $3 en $15; prijzen van 25-09-2026), met denken uitgezet
(zie hieronder), dus dezelfde tokenaantallen als eerder:

| Onderdeel | Aanroepen per week | Kosten per week |
|---|---|---|
| Forecast-ronde | 5 | ~$0,07 |
| Deep-dives | 2 tot 3 domeinen | ~$0,03 |
| **Totaal** | ~10 tot 15 | **~$0,10 tot $0,17** |

Dat is ongeveer $5 tot $9 per jaar. **Zou denken aan komen te staan, dan komen er tokens bij die niet in deze
schatting zitten; meten in de begeleide testrun.** De slechtste dag (alle zes de domeinen triggeren)
is ongeveer $0,15. Zelfs met een factor vijf te laag geschat is het tientallen dollars per
jaar. **Kosten zijn dus niet de reden voor voorzichtigheid; de betrouwbaarheid van de keten is dat.**
Meten kan pas na de eerste run, in het Anthropic-console onder Usage.

### Wat er is gebouwd (30-09, na akkoord, met tests)

1. **Een time-out op de Anthropic-client** (`run_daily.py::build_client`): 90 seconden per
   aanroep en twee herhalingen. Voorheen gold de SDK-standaard van 10 minuten per poging, en
   één hangende aanroep kon de run een half uur vasthouden; `flock` liet de run van de
   volgende dag dan overslaan.
2. **Tokenverbruik per aanroep** (`runtime/llm_budget.py`, tabel `llm_usage`): elke
   LLM-aanroep legt zijn invoer- en uitvoertokens en de geschatte kosten vast, en de log
   toont ze per aanroep en per run.
3. **Een harde maandrem van $200** (`MI_MAX_MAANDBEDRAG_USD`, default 200). Zodra de
   geschatte kosten van de kalendermaand (UTC) de grens bereiken, stopt het systeem met
   aanroepen. **Niet stil:** de aanroep die de grens raakt faalt zoals elke mislukte
   LLM-aanroep (de deep-dive wordt `needs_review`, de forecast-ronde een mislukte
   `agent_run` met reden), dus exit code 1 en een melding. Vanaf 50% van de grens komt
   bij elke aanroep een WARNING. Monitoring blijft draaien. Een onleesbare
   `MI_MAX_MAANDBEDRAG_USD` stopt `run_daily.py --deep-dives` met exit 2.
   De prijzen staan hardcoded (peildatum 25-09-2026) en een onbekend model telt tegen de
   duurste bekende prijs. Het Anthropic-console blijft de autoriteit aan de factuurkant.

Het verbruik uitlezen:

```bash
sqlite3 market_intelligence.db "SELECT date(called_at) AS dag, COUNT(*) AS aanroepen, SUM(input_tokens) AS invoer, SUM(output_tokens) AS uitvoer, ROUND(SUM(cost_usd), 4) AS dollar FROM llm_usage GROUP BY dag ORDER BY dag DESC LIMIT 14;"
```

De log toont daarnaast per run een regel `LLM-verbruik: deze run ... deze maand ... van $200`.

### Voorwaarden om te beginnen

- [ ] T₀ᵃ gehaald: zeven schone werkdagen op rij zonder handmatige actie (schoon = alle agents
      `ok` én geen volledigheidstrigger). Op zijn vroegst **dinsdag 13 oktober**: de reeks begon op
      29-09, maar de run van 01-10 was niet schoon (sector 10 van 12 reeksen) en die van 02-10 ook niet (11 van 12), dus de telling
      herstartte op 05-10. **Een handmatige testrun
      vóór die datum telt als handmatige actie**, dus de smoke test hieronder wacht.
- [ ] Trigger-versie in de log en in `trigger_events`: `v3` t/m 05-10 en **`v4` vanaf de uitrol van PR "trigger-versie v4" (02-10-2026, de drempels van vijf sector-ETF's)**; de T₀ᵃ-teller meldt de wissel als LET OP en telt hem niet als niet-schone dag.
- [ ] `MI_COHORT` leeg of `dry_run` in `.env` (de log zegt `dry_run`).
- [ ] **Ook de reparatie van de forecast-prompt staat op de VPS** (volgende PR na #25): zonder die zou elke ronde falen op een prompt van ruim een miljoen tokens (zie project-state, 01-10).
- [ ] **De code van PR #25 staat op de VPS** (vijf kwantielen, `llm_calls`, Sonnet 5.5), `pytest` geeft `880 passed`, en de databasemigratie
      is gedraaid (`SELECT COUNT(*) FROM predictions;` geeft `0`, en `.schema predictions` bevat `q25` en `q75`).
- [ ] **`ANTHROPIC_API_KEY` staat in `.env` op de VPS** (tot nu toe was dat nergens nodig; `run_daily.sh` zonder `--deep-dives` gebruikt hem niet).
      Controleren zonder de sleutel te tonen: `grep -c '^ANTHROPIC_API_KEY=.\+' /opt/multi_agent/.env` moet `1` geven.
- [ ] **Voorcontrole van het model (kost een fractie van een cent, schrijft niets, raakt de cron niet):** één minimale aanroep met precies de
      instellingen die de testrun gebruikt, zodat een toegangs- of parameterfout nu zichtbaar wordt en niet midden in de testrun:

      ```bash
      cd /opt/multi_agent && set -a && . ./.env && set +a && .venv/bin/python -c "import anthropic; r = anthropic.Anthropic().messages.create(model='claude-sonnet-5-5', max_tokens=20, thinking={'type': 'between_tools'}, messages=[{'role': 'user', 'content': 'Zeg alleen: ok'}]); print(r.stop_reason, [b.type for b in r.content], r.usage.input_tokens, r.usage.output_tokens)"
      ```

      Verwacht: `end_turn ['text'] <getal> <getal>`. Een `404` betekent geen toegang tot het model, een `400` over `thinking` betekent dat de
      geïnstalleerde `anthropic`-versie of het model de instelling niet accepteert (`.venv/bin/pip show anthropic` toont de versie).
      Stop dan en meld het; draai de testrun niet.
- [x] Een uitgavenlimiet van $200 per maand in het Anthropic-console (ingesteld door DD op 30-09; de
      code-rem van hetzelfde bedrag is de tweede lijn).
- [x] Dit plan goedgekeurd door DD op 30-09, inclusief de codewijzigingen hierboven (gebouwd).

### Fase 1 — één begeleide testrun (voorstel: op zijn vroegst woensdag 14 oktober, middag; was 13 oktober vóór de verschuiving van T₀ᵃ op 02-10)

De cron van 07:15 heeft dan al gedraaid; monitoring wordt bij een tweede run
overgeslagen (idempotent). Draai met de hand:

```bash
cd /opt/multi_agent && ./run_daily.sh --deep-dives
```

Dat draait alleen de LLM-fasen: deep-dives voor triggers van vandaag (als die er zijn),
de forecast-ronde voor de lopende week, en de baselines. Controleer daarna:

1. **De log:** per agent een regel `forecast-ronde 2026-W41 -- N voorspellingen`, geen
   `Traceback`, geen `apikey=`. Verwacht: één waarschuwing over de ontbrekende ridge.
2. **Ronde compleet en onder het juiste cohort:**
   ```bash
   sqlite3 market_intelligence.db "SELECT agent, cohort, COUNT(*) FROM predictions GROUP BY agent, cohort ORDER BY agent;"
   ```
   Alleen `dry_run`. Rond 57 voorspellingen in totaal voor de vijf agents, plus baselines.
3. **Herkomst vastgelegd:**
   ```bash
   sqlite3 market_intelligence.db "SELECT DISTINCT agent, model_id, prompt_version, trigger_version FROM predictions;"
   ```
   Agents: `claude-sonnet-5-5`, prompt-versie `v3`, trigger-versie `v3` (dry-run tot de uitrol van v4, daarna `v4`). Baselines: `deterministic`.
4. **De runs zelf:**
   ```bash
   sqlite3 market_intelligence.db "SELECT domain, mode, success, error FROM agent_runs WHERE mode IN ('forecast','deep_dive') ORDER BY run_at DESC LIMIT 15;"
   ```
   `success=1` voor alle vijf de forecast-rijen; een `0` met een fout is precies wat je wilt zien.
5. **De kwaliteitscontrole van deep-dives (alleen als er triggers waren):**
   ```bash
   sqlite3 market_intelligence.db "SELECT domain, status, COUNT(*) FROM qc_cases GROUP BY domain, status;"
   ```
   `NEEDS_REVIEW` is een vlag en geen fout (CLAUDE.md, regel 3): lees de tekst voordat je oordeelt.
6. **Lees minstens twee voorspellingen met de hand** en kijk of de vijf kwantielen (q10 ≤ q25 ≤ q50 ≤ q75 ≤ q90)
   en de onderbouwing te volgen zijn. Dit is het enige punt dat geen test kan controleren.
   **Het ruwe antwoord van het model terugkijken** (nieuw sinds 01-10): elke aanroep staat in `llm_calls`, met het volledige verzoek (inclusief de
   denkinstelling) en het antwoord. Handig bij een afgewezen voorspelling of een kruisend kwantiel:

   ```bash
   cd /opt/multi_agent && sqlite3 -header -column market_intelligence.db "SELECT id, purpose, domain, model, stop_reason, input_tokens, output_tokens, substr(response_text, 1, 100) AS begin FROM llm_calls ORDER BY id DESC LIMIT 12;"
   ```

   **Precies zien wat een agent kreeg** (de cijfers plus de berekende context), bijvoorbeeld voor de monetary agent:

   ```bash
   cd /opt/multi_agent && sqlite3 market_intelligence.db "SELECT json_extract(request_json, '$.messages[0].content') FROM llm_calls WHERE purpose = 'forecast' AND domain = 'monetary_policy' ORDER BY id DESC LIMIT 1;"
   ```

   Controleer of de context klopt met wat je zelf weet: datum en ouderdom van de laatste waarden, het bereik van een jaar, de FOMC-besluitdagen (28-10 en 09-12).
   Zie je bij een reeks "geen opgeslagen waarnemingen" of "niet te berekenen", dan ontbrak er historie of was de reeks te oud: dat is dan een bevinding.

   Staat er bij een rij `stop_reason = max_tokens` of een lege `response_text`, dan was de limiet te krap (met denken uit zou dat niet moeten gebeuren).
7. **De kosten:** de log (`LLM-verbruik: ...`) en de query hierboven, en ter controle het Anthropic-console
   onder Usage. Ongeveer $0,10 tot $0,30 voor deze run. Wijkt het met een factor tien af, of wijken de
   tokens in de database sterk af van het console, stop dan en meld het.

**Stop en meld het** bij: voorspellingen onder een ander cohort dan `dry_run`; een agent zonder
enkele voorspelling; een run langer dan tien minuten; kosten een factor tien boven de schatting.

### Fase 2 — cron aanzetten, drie weken begeleid (voorstel: vanaf donderdag 15 oktober; was 14 oktober)

Alleen als fase 1 schoon was: `--deep-dives` toevoegen aan de cron-regel (`crontab -e`,
dezelfde regel als in dit document, plus de vlag). Ronden vallen dan op de maandagen
19 en 26 oktober en 2 november (plus een inhaalronde op donderdag 15 oktober voor de lopende week). **De drie weken lopen nu tot 5 november en overlappen de dry-run-week (27 oktober tot 9 november).** Dat is een voorstel dat DD moet bevestigen: of de begeleide periode op twee weken zetten, of de dry-run-week laten beginnen zodra de begeleide periode schoon is.

**Elke dag, twee minuten:** de laatste regels van `daily.log`. Exit 0, of exit 1 met een
begrijpelijke reden (de ridge-melding op de rondedag is verwacht).
**Elke maandag na de ronde:** queries 2, 3 en 4 hierboven, en het aantal voorspellingen per agent
in vergelijking met vorige week. Ontbreekt er een agent, dan probeert de ronde het de rest van
de week zelf opnieuw (vier kansen, ma t/m vr); zie je vrijdag nog een gat, dan is dat het laatste
moment om `./run_daily.sh --deep-dives` met de hand te draaien.

**Uitschakelen (de noodrem):** zet een `#` voor de cron-regel met `--deep-dives` en schrijf de
regel opnieuw zonder de vlag. Monitoring blijft draaien; er gaat geen data verloren. Doe dit bij:
een voorspelling onder een ander cohort dan `dry_run`; een monitoringdag die ontbreekt terwijl
deep-dives aan stonden; drie dagen op rij exit 1 om een andere reden dan de ridge-melding; kosten
boven $5 in één week. De maandrem van $200 is een ruime vangrail voor een echte ontsporing; deze
$5 per week is de grens waarbij je zelf ingrijpt, ver vóór de rem.

### Fase 3 — de dry-run-week (27 oktober tot 9 november, roadmap fase 3b)

Dat is de eigenlijke generale repetitie, met het model en de prompts zoals ze bij de freeze
bevroren worden. Drie weken begeleid draaien ervoor betekent dat de meeste fouten er dan al uit zijn.

### Beslissing die vóór fase 3 valt: welk model?

**[01-10 BESLOTEN door DD: `claude-sonnet-5-5`.]** Tot dan gebruikte de code overal `claude-sonnet-4-6`
(`qc.DEFAULT_LLM_REVIEW_MODEL`, hergebruikt voor de deep-dive en de forecast-ronde). De roadmap (4.4) gaat voor de
pseudo-OOS-run uit van een model met een kennisgrens in juni 2026, en `model_id` is een freeze-punt (checkpoint 5).
De kennisgrens van juni 2026 is **bevestigd in het Anthropic-modeloverzicht** (01-10-2026; uittreding niet eerder dan 28-09-2027). Prijs wel bevestigd: $2/$10, 1M context.

**Wat er voor de wissel is geregeld (`runtime/llm_budget.py`, `agents/base.py`):**
- **Denken staat op Sonnet 5.5 standaard AAN** (op 4.6 stond het uit). Onze aanroepen hebben een kleine `max_tokens` (500 QC-review,
  800 deep-dive, 2000 forecast), waar het denken in meetelt: zonder maatregel kunnen antwoorden leeg of afgekapt terugkomen en
  verzwakt de QC-review stil. `MeteredClient` zet daarom bij elke aanroep naar dit model `thinking={"type": "between_tools"}` mee
  (de manier om denken uit te zetten; `disabled` geeft een 400). Dit geldt centraal voor alle aanroepen, zonder `src/qc/` aan te raken.
  **Denken AAN voor de forecast-ronde is een experiment voor de begeleide testrun**, niet iets dat nu is beslist.
- De QC-review draait nu ook op Sonnet 5.5, via de bestaande `model`-parameter van `default_llm_review` (aangeroepen vanuit `base.py`);
  `qc.DEFAULT_LLM_REVIEW_MODEL` in `qc.py` staat ONGEWIJZIGD op `claude-sonnet-4-6` (checkpoint 2).
- Geen `temperature`, `tool_choice` of prefill in onze aanroepen, dus de overige breuken van Sonnet 5.5 raken ons niet.
- **Nog niet getest tegen de echte API:** of jouw account toegang heeft tot dit model en of `between_tools` door de geïnstalleerde `anthropic`-versie
  op de VPS wordt doorgegeven. Beide falen zichtbaar (fout in de log, exit 1), niet stil. De begeleide testrun is de eerste echte meting.
- Een refusal (`stop_reason: "refusal"`, veiligheidsclassifier) is op dit model mogelijk; onze code ziet dat als een lege respons en meldt het als
  fout. De naslag raadt server-side fallbacks aan; dat is bewust niet ingebouwd (extra model, extra kosten) en een optie als het in de testrun voorkomt.
- **Het logboek (`llm_calls`)** legt elk verzoek (inclusief de denkinstelling) en elk antwoord vast, zodat de instelling per voorspelling terug te vinden is.
  De denkinstelling staat dus NIET in `model_id`; het is een covariaat die alleen in dit logboek staat.

## Splitsingscorrectie en de triggerdrempels van de sector-ETF's (02-10-2026) — **beslissing voor DD, niets gewijzigd**

Op 5 december 2025 halveerden XLB, XLE, XLK, XLU en XLY door een 2-voor-1-splitsing (zie `docs/data-sources.md`). Alle leespaden corrigeren daar nu voor (`contract/corporate_actions.py`); de triggerdrempels zijn
absolute prijsverschillen die op de ongecorrigeerde historie zijn gekalibreerd en zijn daarom NIET aangepast. Bekijk eerst de vergelijking (alleen lezen, wijzigt niets):
```bash
cd /opt/multi_agent && git pull && .venv/bin/python calibrate_triggers.py --vergelijk-splitsingen
```
Per ETF met een splitsing staan er: de huidige drempel, hoe vaak hij per jaar vuurt op de ruwe en op de gecorrigeerde reeks (doel: ~5 per jaar), en welke drempel bij 5 per jaar hoort op de gecorrigeerde reeks, ook als percentage van het
niveau. Vuurt de huidige drempel op de gecorrigeerde reeks veel vaker dan 5 per jaar, dan was hij te grof (XLK 8,9 en XLY 6,2 zijn rond 5% van de koers, tegen ~2% bij XLF en XLI). Een andere drempel is een nieuwe trigger-versie
(`TRIGGER_VERSION`) en een beslissing van DD (checkpoint 2 en 5); de trigger-engine zelf blijft ongemoeid. Het volledige gecorrigeerde rapport: `calibrate_triggers.py --domain sector`; het ruwe: `--domain sector --ongecorrigeerd`.

**Elke ochtend in het log:** `grep -i "splitsing" /var/log/mi/daily.log | tail`. Geen regels = niets te doen. Een regel `Mogelijke splitsing NIET geregistreerd` betekent dat een ETF-koers meer dan ~35% sprong: controleer of het echt een splitsing is
(de ETF-aanbieder meldt ze vooraf) en laat de splitsing dan toevoegen aan `SPLITSINGEN`. Eén valse trigger voor die ETF op de dag zelf is verwacht (de live trigger-engine ziet de ruwe koers).

## Trigger-versie v4: de drempels van vijf sector-ETF's (02-10-2026) — dry-run-plan (checkpoint 2 en 3), **goedgekeurd door DD op 02-10-2026**

**Wat.** XLK 8,9 → 5,4, XLE 2,6 → 1,6, XLY 6,2 → 3,2, XLB 2,0 → 1,2, XLU 1,8 → 1,0. Alleen die vijf; de andere zes sector-ETF's, SPY en alle andere agents blijven gelijk. De trigger-engine (`src/triggers/`) en `src/qc/` zijn niet
aangeraakt: alleen de configuratie in `sector_agent.py`. `TRIGGER_VERSION` is v4 (vingerafdruk `26f1dcf7937e4f86`). Reden: op de gecorrigeerde reeks vuurden de oude drempels 0,3 tot 1,7 keer per jaar in plaats van ~5 (zie "Splitsingscorrectie en de
triggerdrempels" hierboven); de nieuwe zijn de 5-per-jaar-drempel op de gecorrigeerde laatste drie jaar, afgerond op één decimaal.

**Verwachting.** Samen ongeveer 20 extra triggers per jaar (~0,4 per week) uit sector. Deep-dives kosten alleen iets als `--deep-dives` aanstaat.

**Uitrollen.** Na een ochtendrun: `cd /opt/multi_agent && git pull` (niets te herstarten). Terugdraaien: `git revert` en weer `git pull`.

**Controleren (alleen lezen).**
```bash
cd /opt/multi_agent && .venv/bin/python calibrate_triggers.py --domain sector
```
De kolom `3j` van XLK, XLE, XLY, XLB en XLU moet nu rond de 5 staan (4 tot 6 is goed); de andere sectoren ongewijzigd (rond de 5). De eerste drie ochtenden: in het log `Trigger-versie: v4` en het aantal `triggers=` bij sector; een enkele extra trigger per week is verwacht.
**De T₀ᵃ-teller:** meldt de versiewissel (v3 → v4) als LET OP, maar het is geen niet-schone dag (schoon = alle agents ok én geen volledigheidstrigger).

## De pseudo-OOS-run (roadmap 4.4, fase 3b) — gebouwd op 02-10-2026, **nog niet gedraaid**

**Wat het is.** De agents doen de wekelijkse forecast-ronde over het verleden: de dertien maandagen van 6 juli t/m 28 september 2026 (na de kennisgrens
van het model), op data zoals die op dat moment bekend was. Doel: contract- en resolverfouten vinden vóór de klok loopt, en meten hoe vaak het model vijf
kwantielen betrouwbaar uitspreekt (**meer dan 5% niet opgeleverd = het contract heroverwegen**). Het is **geen bewijs van kalibratie**: het venster is kort, de lange
horizonnen lopen nog en de uitkomsten overlappen. Alles staat onder `cohort=pseudo_oos`.

**Draait nooit op de echte database.** `voorbereiden` maakt een KOPIE (`pseudo_oos.db`, naast de echte) waarin het publicatiemoment van de back-fill-claims is
verschoven met een aangenomen vertraging per reeks (`PUBLICATIE_VERTRAGING_DAGEN` in `src/scoring/pseudo_oos.py`: dagseries 1 dag, weekseries 2 tot 6, maandseries 38 tot 45).
Zonder die correctie zou de agent op 6 juli de payrolls van juli zien (die pas in augustus verschenen). Alle bestaande point-in-time-code werkt dan ongewijzigd.
De echte database wordt alleen gelezen. Elke andere stap weigert een database zonder die voorbereiding.

**Gevonden bij de eerste echte `audit` (02-10-2026) en hersteld:** `fed_funds_rate` bleek een MAANDgemiddelde (FEDFUNDS, 866 waarnemingen sinds 1954), terwijl ik hem als dagreeks
(1 dag vertraging) had aangenomen: op 6 juli was daardoor de julistand zichtbaar. Nu 35 dagen. **`voorbereiden` toetst voortaan elke vertraging aan de werkelijke afstand tussen de
waarnemingen in de data zelf** (maandreeks: minstens 30 dagen, weekreeks: minstens 2, dagreeks: minstens 1) en breekt af als een aanname daar niet bij past. Een kopie die vóór
deze correctie is gemaakt moet worden weggegooid: `rm pseudo_oos.db` en `voorbereiden` opnieuw.

**Aannames, niet te verifiëren (checkpoint 4):** de vertragingen zijn mijn inschatting van de publicatiekalenders en bewust conservatief (te veel vertraging toont
oudere data, nooit nieuwere). `audit` laat per reeks de laatste zichtbare waarneming zien, zodat je die naast de echte kalender kunt leggen. **Geen ridge** (die kent
het venster al); **geen herziene-versus-eerste-print-correctie** (de back-fill is gereviseerd); **geen tweede run over 2025** (geen passend ouder model gekozen).

**Voorwaarden vóór de echte run**
1. **[02-10 gedaan]** De FOMC-besluitdagen van juli en september 2026 (29 juli en 16 september) staan in `FOMC_MEETING_DATES` (`contract/resolution.py`); bron: de twee persberichten die DD aanleverde
   (29 juli: ongewijzigd op 3,50-3,75; 16 september: verhoogd naar 3,75-4,00). De run weigert te starten zolang de kalender een gat heeft rond een voorspeldatum.
2. Graaf v1 (of het besluit dat v0 blijft) staat in de code, zodat de doelen-vingerafdruk niet meer verandert na de run.
3. De begeleide testrun van 14-10 is geweest (echte tokencijfers, een echte prompt gezien).

**Stappen (op de VPS, in deze volgorde; de eerste vier kosten niets)**
```bash
cd /opt/multi_agent
.venv/bin/python pseudo_oos.py voorbereiden --bron market_intelligence.db --doel pseudo_oos.db
.venv/bin/python pseudo_oos.py audit --db pseudo_oos.db          # laatste zichtbare waarneming per reeks, begin en einde van het venster
.venv/bin/python pseudo_oos.py prompt --db pseudo_oos.db --agent sector --datum 2026-07-06   # de echte prompt van die dag lezen
.venv/bin/python pseudo_oos.py schatting --db pseudo_oos.db      # kostenschatting uit echte promptlengtes
.venv/bin/python pseudo_oos.py draaien --db pseudo_oos.db        # DROGE run: toont alleen het plan
.venv/bin/python pseudo_oos.py draaien --db pseudo_oos.db --ja   # KOST GELD (ruwe schatting: enkele dollars)
.venv/bin/python pseudo_oos.py afwikkelen --db pseudo_oos.db
.venv/bin/python pseudo_oos.py rapport --db pseudo_oos.db        # per agent: gevraagd, gekregen, % gemist, afgewikkeld
```
De standaardlocatie van `--bron` is `market_intelligence.db`; geef bij een andere plek het volledige pad op (zoals de dagelijkse run `MI_DB_PATH` gebruikt).
De run is hervatbaar (per ISO-week; een tweede aanroep slaat af wat er staat). Het LLM-verbruik wordt in de kopie vastgelegd (`llm_usage`), niet in de echte database;
de maandrem van de kopie kent het verbruik van vóór het kopiëren. `freeze_status.py` kijkt naast de echte database ook in `pseudo_oos.db`.
**Wat DD beoordeelt:** de `audit` en een `prompt` (klopt wat er zichtbaar is met de echte publicatiekalender?), het `rapport` (>5% gemist?), en of er geen resolverfouten zijn.

## Alpha Vantage: reden loggen en één herhaalpoging — dry-run-plan (checkpoint 3), **goedgekeurd door DD op 02-10-2026**

**Waarom.** De eerste T₀ᵃ-dag miste `xlp_consumer_staples` en het log gaf geen reden (zie `docs/data-sources.md`, "GEMETEN op 02-10-2026").
**Wat (`src/sources/alpha_vantage.py`, gebruikt door sector, currency en commodity):** elke mislukte reeks krijgt een gelogde reden; wat
ontbreekt wordt na één pauze van 30 seconden één keer opnieuw geprobeerd. De completeness-check blijft ongewijzigd, `src/triggers/`
en `src/qc/` zijn niet aangeraakt, en `TRIGGER_VERSION` blijft v3 (de vingerafdruk bevat geen fetch-gedrag; een test bewaakt dat).

**Wat het kost.** Op een goede dag niets. Bij gaten maximaal één pauze van 30 s per agent (sector, currency, commodity: ten hoogste 90 s extra);
de run duurt nu ongeveer 20 s en de heartbeat heeft 2 uur grace.

**Uitrollen:** na een ochtendrun, niet ervoor; `cd /opt/multi_agent && git pull`. Er is niets te herstarten: de cron start de volgende ochtend de nieuwe code.
Terugdraaien: `git revert` van de merge en weer `git pull`.

**Wat DD de eerste drie ochtenden controleert** (na de run van 07:15 UTC):
```bash
grep -n "Alpha Vantage" /var/log/mi/daily.log | tail -n 30
cd /opt/multi_agent && .venv/bin/python t0a_status.py
```
- Geen regels `Alpha Vantage ...` = alle reeksen kwamen in één keer binnen: goed.
- `hersteld bij herhaling` = de herhaling deed zijn werk; noteer de reden uit de eerste ronde.
- `blijft ontbreken na herhaling` = het gat bleef; de dag telt niet. Staat steeds dezelfde reden of dezelfde reeks erbij, dan is het structureel en
  beslissen we op die reden (andere pauze, een andere aanpak voor die reeks), niet op een gok.
- Komt er een melding van Alpha Vantage zelf (`meldt (Note)` of `(Information)`) over aanroepen per minuut of per dag, dan is dat het
  gezochte antwoord op de oorzaak.

## De dagelijkse controle (`dagcontrole.py`) — gebouwd op 02-10-2026, alleen lezen

Eén scherm in plaats van vijf losse commando's, voor de begeleide weken en de dry-run-week (roadmap fase 3b, checkpoint 3). De database gaat open met `mode=ro`; er wordt niets aangeroepen op het netwerk en niets gewijzigd.

```bash
cd /opt/multi_agent && git pull && .venv/bin/python dagcontrole.py                    # vandaag (UTC)
cd /opt/multi_agent && .venv/bin/python dagcontrole.py --dag 2026-10-05              # een eerdere dag
```

**Wat je ziet:** `run` (elke agent ok, geen volledigheidstrigger; dezelfde definitie als `t0a_status.py`), `triggers` (aantal per domein, en of de trigger-versie die van de code is), `claims` (elk domein minstens één), `bronnen` (mislukte bronchecks), `voorspellingen` (op maandag moet de forecast-ronde er zijn), `llm-verbruik` (de maandrem), `log` (WARNING/ERROR/CRITICAL-regels van die dag: Alpha Vantage-redenen, splitsing-waarschuwingen, forecast-/baseline-problemen, resolver-fouten; plus wat de run over cohort en trigger-versie zei), `back-up` (een foutregel in het log is LET OP; bewijs van een geslaagde back-up is een regel `back-up ok` van vandaag in het log of, met `--space`, het nieuwste bestand in de Space; zonder bewijs staat er ONBEKEND), `archief` (SPY-bestand van vandaag in het manifest) en `schijf` (LET OP vanaf 85%).

**Statussen:** `ok`, `LET OP` (vraagt aandacht), `ONBEKEND` (niet te controleren, bijvoorbeeld een ontbrekend logbestand; telt **niet** als ok), `nog niet` (het tijdstip van de cron is nog niet voorbij: 07:15 run, 08:00 back-up, 08:30 archief; geen probleem) en `info`. Exitcode 0 = niets dat aandacht vraagt, 1 = minstens één LET OP of ONBEKEND, 2 = database niet gevonden.

**Bevindingen van de eerste echte draai (02-10-2026) en wat ervan is aangepast:**
- *Back-up:* `rclone copy` en `sqlite3 .backup` melden niets bij succes, dus het back-uplog wordt bij een geslaagde back-up niet bijgewerkt. De eerste versie gaf daarop ten onrechte een LET OP (log van 28-09), terwijl de back-up van 02-10 in de Space stond. Nu geldt het log alleen als bewijs als er een `back-up ok`-regel in staat. Gebruik `--space` voor het bewijs uit de Space zelf (alleen een lijst):
  ```bash
  cd /opt/multi_agent && .venv/bin/python dagcontrole.py --space do-spaces:mi-backups-multi-agent/backups/
  ```
  Wil je het zonder `--space`, dan kan `backup.sh` na de `rclone copy`-regel één regel schrijven: `echo "$(date -u +%FT%TZ) back-up ok"` (door `set -e` alleen na een geslaagde back-up). Dat is een wijziging aan het onbeheerde proces (checkpoint 3); die doe ik niet zonder jouw akkoord.
- *Trigger-versie:* de run van 07:15 draaide met v3 en de code ging daarna naar v4. Dat is een update, geen afwijking. De controle vergelijkt nu met wat de run zelf in het log meldde ("Trigger-versie: v3"), en meldt het verschil met de huidige code alleen als `info`.
- *"Dagen zonder succesvolle run: 2026-09-25":* een bekende melding van de gatendetectie (`run_daily`, terugkijkvenster van zeven dagen) omdat de VPS pas op 28-09 begon. Het venster schuift op en de melding verdwijnt vanaf maandag 05-10. De dagcontrole toont hem zolang hij in het log staat.
- *Archief `as_of` 2026-09-30 op 02-10:* verwacht. De bron publiceert rond 10:15 UTC, de cron draait om 08:30, dus het archief loopt een dag achter (zie de SPY-meting).

**Wat het niet kan:** beoordelen of een analyse goed is, of er handmatig ingegrepen is (een run buiten 07-09 UTC wordt wel gemeld), of de back-up herstelbaar is (daarvoor is de hersteltest). De logregels van de dag worden gevonden op de datum aan het begin van de regel, dus de logklok moet op UTC staan (zoals de cron). Controleer na de eerste echte run of de bestandsnamen (`/var/log/mi/daily.log`, `/var/log/mi/backup.log`) kloppen; met `--log` en `--backup-log` kun je andere paden meegeven.

## Synthesizer, slanke v1: voorblik (roadmap 4.5) — gebouwd op 02-10-2026, **nog niet gekoppeld aan `run_daily`**

```bash
cd /opt/multi_agent && git pull && .venv/bin/python synthesizer_preview.py            # groottes, kostenschatting, begin van de prompt
cd /opt/multi_agent && .venv/bin/python synthesizer_preview.py --volledig | less     # de hele prompt
```

Alleen lezen (`mode=ro`), geen LLM-aanroep, niets opgeslagen. Controleer: (1) staan alle 24 doelen/57 voorspellingen erin, (2) is de promptgrootte aanvaardbaar, (3) staat er nergens een kwantiel of kans van een agent in (de synthesizer is blind), (4) de kostenschatting past naast de domain agents bij de maandrem. De schatting is ruw (3 tekens per token); de begeleide testrun geeft de echte cijfers. Pas na jouw akkoord koppel ik de synthesizer aan de wekelijkse ronde (checkpoint 1 en 3).

## ATR-proefrapport (roadmap 4.2, idee van DD) — gebouwd op 02-10-2026, alleen lezen

Beantwoordt: hoeveel triggers per jaar zou "beweging groter dan N keer de gemiddelde absolute beweging van de afgelopen 30 dagen" geven, per reeks, voor N van 2 tot 6, naast de huidige vaste drempel? Het rapport leest alleen de database (op de gesplitsingsgecorrigeerde reeksen) en wijzigt niets.

```bash
cd /opt/multi_agent && git pull && .venv/bin/python calibrate_triggers.py --atr-proef --domain sector
.venv/bin/python calibrate_triggers.py --atr-proef          # alle reeksen, langer
```

**Wat je ziet:** per reeks de kolom `nu` (vaste drempel, trigger-versie v4) en `N=2..6`; `dekking` (aandeel paren met een bruikbaar 30-daags gemiddelde) en `N~5` (de N die het dichtst bij 5 per jaar komt). Week-, maand- en stapreeksen krijgen "niet te beoordelen": die passen niet in een venster van 30 dagen. Onderaan staat het totaal over de vergelijkbare reeksen.

**Wat het niet doet:** de regel in de engine zetten (checkpoint 2, nieuwe trigger-versie, besluit van DD) en niet op het kritieke pad naar T₀.

## Jaarlijkse FOMC-kalenderstap (besluit DD 02-10-2026: niets bouwen)

De besluitdagen staan in `FOMC_MEETING_DATES` (`src/contract/resolution.py`). Er komt geen automatische kalender. Eens per jaar, zodra de Fed het schema voor het volgende jaar publiceert (federalreserve.gov, "FOMC Meeting Calendars"): geef de nieuwe besluitdagen door; ze worden **aan het eind** toegevoegd (nooit bestaande wijzigen of verwijderen). Een gat in de kalender merkt het systeem zelf op: de pseudo-OOS-run weigert te starten zonder dekking, en de resolver weigert een FOMC-doel af te wikkelen als er te weinig besluitdagen zijn en zegt dan "vul FOMC_MEETING_DATES aan". De huidige lijst loopt tot en met 2027; zie vóór oktober 2027 of het volgende jaar erbij moet.

## SPY-bron: wanneer ververst de `as_of`? — meting (02-10-2026), voorstel, **nog niet in de cron**

**Waarom.** Het archief bewaart per UTC-dag het EERSTE bestand. Op 02-10 stond de `as_of` om 08:30 UTC nog op 30-09, twee handelsdagen achter, en
`archive_daily.py` kan dat niet verder meten (een tweede aanroep op dezelfde dag doet bewust niets). Ververst de bron later op de dag, dan bewaart de
cron elke dag een verouderde versie. Dat weten we alleen met metingen over de dag heen.

**`meet_spy_asof.py` (alleen lezen).** Haalt het bestand op en print één regel: tijdstip, `as_of`, grootte, vingerafdruk en wat de bron zelf zegt
(`Last-Modified`, `ETag`, `Date`). Bewaart niets en raakt het archief, het manifest en de database niet aan. Eenmalig:
```bash
cd /opt/multi_agent && .venv/bin/python meet_spy_asof.py
```
**Eerste meting (02-10-2026, 12:13 UTC, DD):** `as_of=2026-10-01`, `last-modified=Fri, 02 Oct 2026 10:15:20 GMT`, ETag `0x8DF206E10C627F7`. De bron
plaatste het bestand met `as_of` 01-10 dus om **10:15 UTC op 02-10**, ná de archief-cron van 08:30 UTC (die `as_of` 30-09 bewaarde).
*Wat dat betekent (één meetpunt, nog te bevestigen):* het archief loopt één dag achter op wat er op dat moment beschikbaar is, maar er gaat niets
verloren zolang de bron één keer per werkdag rond 10:15 UTC ververst: elk bestand leeft van zijn publicatie tot de volgende, en de cron van 08:30 valt
elke werkdag in dat venster (het bestand van gisteren). **Het risico zit aan de vroege kant:** publiceert de bron ooit vóór 08:30 UTC, dan wordt het
bestand van de vorige dag nooit bewaard. De cron NIET later zetten dan 10:15 (dan sla je juist bestanden over); eerder zetten geeft marge.
Onbekend en te meten: of de tijd van dag tot dag schommelt en of er in het weekend of op feestdagen iets verschijnt.

**Voorstel, door DD te bevestigen (checkpoint 3):** elk uur laten meten, tot en met maandag 5 oktober 12:00 UTC (dan zitten het weekend en de publicatie van maandag erbij), zodat het niet van DD's aanwezigheid afhangt. Eén verzoek per uur aan
State Street, naar een eigen logbestand, los van de dagelijkse run en het archief (`crontab -e`, regel toevoegen):
```
5 * * * * cd /opt/multi_agent && .venv/bin/python meet_spy_asof.py >> /var/log/mi/spy_asof.log 2>&1
```
Veilig toevoegen (laat de rest van de crontab ongemoeid) en controleren:
```bash
(crontab -l; echo '5 * * * * cd /opt/multi_agent && .venv/bin/python meet_spy_asof.py >> /var/log/mi/spy_asof.log 2>&1') | crontab - && crontab -l
```
Op maandag 5 oktober na 12:00 UTC: `cat /var/log/mi/spy_asof.log` plakken, en de regel weer weghalen:
```bash
crontab -l | grep -v meet_spy_asof | crontab - && crontab -l
``` Wat we dan zien: het uur waarop `as_of` van dag
wisselt en wat `Last-Modified` zegt. Bij een verversing later dan 08:30 UTC stel ik een nieuw archiefmoment voor (nieuwe checkpoint-3-beslissing).

## Het ruwe archief (SPY-holdings) — dry-run-plan (checkpoint 3), **goedgekeurd door DD op 01-10-2026, nog NIET in de cron**

Wat het is en waarom: `docs/data-archive.md`, "Het ruwe archief draaien". Kort: de SPY-samenstelling van State
Street is de enige bron uit de probe die niet terug te halen is. `archive_daily.py` haalt het bestand één keer
per dag op, gzipt het onder `archive/spy_holdings/` en schrijft een regel in `manifest.jsonl`. Het is een
eigen proces zonder database, los van de dagelijkse run: het kan T₀ᵃ niet raken, en T₀ᵃ kan het niet raken.

**Stap 1 — één handmatige run (nu, kost niets, raakt niets anders).**

```bash
cd /opt/multi_agent && git pull origin claude/beautiful-cori-f9p6h6 && .venv/bin/python archive_daily.py
```

Wat je ziet bij succes: één regel `spy_holdings: gearchiveerd archive/spy_holdings/2026/... (… B -> … B gzip,
as_of=…, identiek aan gisteren=False)`. **Dit is de eerste echte test tegen State Street** (de bouw gebeurde in
een omgeving die dat domein niet kan bereiken), dus drie dingen zijn pas nu bekend:

- Werkt het zonder meer? Zo niet, dan staat er `NIET gearchiveerd:` met de reden (bijvoorbeeld `HTTP 403`: de bron
  eist iets wat we niet sturen). Er is dan niets weggeschreven.
- Staat er `as_of=2026-…` of `as_of=None`? Bij `None` komt er een waarschuwing "as_of niet te lezen". Dat is
  geen fout (het ruwe bestand is bewaard), maar stuur me dan het volgende, zodat ik de leesregel aanpas:

```bash
cd /opt/multi_agent && zcat "$(ls -t archive/spy_holdings/*/*.gz | head -1)" | .venv/bin/python -c "import sys,io,zipfile; print(zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).read('xl/sharedStrings.xml').decode()[:1500])"
```

- Hoe lang het duurt (moet seconden zijn).

**Stap 2 — de cron-regel (pas na een geslaagde stap 1).** Aparte regel, aparte lock, eigen log, **na** de
dagelijkse run (07:15) zodat ze elkaar nooit raken. 08:30 UTC is bewust: de bron ververst hoogstwaarschijnlijk
's avonds Amerikaanse tijd, dus 's ochtends staat de vorige handelsdag erin. Dat laatste is een aanname; stap 3 meet het.

```bash
crontab -e
```

```
30 8 * * 1-5 /usr/bin/flock -n /tmp/mi-archive.lock /opt/multi_agent/archive_daily.sh >> /var/log/mi/archive.log 2>&1
```

Geen healthchecks-ping eraan in het begin: een mislukte archiefdag is vervelend maar geen alarm (anders dan een
gemiste ingestiedag). Pas na twee weken stabiel draaien beslissen we of er een eigen check bij komt.

**Stap 3 — twee weken alleen kijken (dagelijks twee seconden).**

```bash
cd /opt/multi_agent && .venv/bin/python archive_daily.py --status
```

Wat je controleert, en wat het betekent:

| Je ziet | Betekenis | Actie |
|---|---|---|
| `ontbrekende werkdagen: geen` | elke werkdag is binnengekomen | niets |
| een datum bij ontbrekende werkdagen | die dag mislukte (kijk in `/var/log/mi/archive.log`) | die dag is voorgoed verloren; oorzaak zoeken |
| `byte-identiek aan de dag ervoor` op een dinsdag t/m vrijdag | de bron ververste niet tussen twee werkdagen | meld het: dan loopt de cron te vroeg |
| `as_of` is steeds 1 handelsdag oud | verwacht (de run van 08:30 pakt de vorige slotstand) | niets |
| `as_of` is 2+ handelsdagen oud | de bron loopt achter | meld het |
| `zonder leesbare as_of` > 0 | de leesregel past niet op het bestand | stuur me het stukje sharedStrings uit stap 1 |

**Opslag:** ~40 KB per dag, dus ongeveer 10 MB per jaar. Geen probleem op deze machine (11 % van 23 GB gebruikt).

**Back-up:** de map `/opt/multi_agent/archive/` zit **niet** in `backup.sh` (dat kopieert alleen de database).
Voeg dit toe aan `backup.sh` (na de bestaande `rclone copy`-regel), want een archief dat alleen op deze machine
staat is weg als de machine weg is, en dat is precies de data die niet terug te halen is:

```
rclone copy /opt/multi_agent/archive do-spaces:<jouw-space-naam>/archive/
```

**Wat dit bewust niet doet:** de bestanden niet parsen, niets naar de database schrijven, geen andere bronnen
archiveren (Kalshi/Polymarket wachten op een diepte-meting, betaalde bronnen op DD's budgetbeslissing), en niet
mee in `run_daily.py`.

## Externe heartbeat (0a-6): healthchecks.io — ✅ 27-09-2026

1. Account aanmaken op [healthchecks.io](https://healthchecks.io) (gratis
   tier is ruim genoeg voor één dagelijkse check).
2. Nieuwe check aanmaken, naam `mi-daily`. Kies **"Cron Schedule"** als
   schema-type (niet "Simple"/period) en vul exact dezelfde expressie in
   als de crontab-regel: `15 7 * * 1-5`, tijdzone **UTC**, grace-tijd
   bijv. 2 uur (marge voor een trage run of een tijdelijke netwerk-
   hapering). Cron-schema i.p.v. een vaste periode voorkomt een vals
   alarm in het weekend, wanneer er terecht geen run is.
3. Kopieer de ping-URL (`https://hc-ping.com/<uuid>`).
4. Pas de crontab-regel aan zodat de ping ALTIJD verstuurd wordt, ongeacht
   of `run_daily.sh` slaagde of faalde — de heartbeat moet specifiek
   detecteren of de cron/het script ÜBERHAUPT gedraaid heeft, dat is een
   ander signaal dan "lukte de datapull" (dat dekt de ntfy-melding via
   `runtime/notifications.py` al):

   ```bash
   crontab -e
   ```

   Vervang de bestaande regel door (`;` i.p.v. `&&` -- de ping moet ook bij
   een mislukte cyclus verstuurd worden):

   ```
   15 7 * * 1-5 /usr/bin/flock -n /tmp/mi-daily.lock /opt/multi_agent/run_daily.sh >> /var/log/mi/daily.log 2>&1; curl -fsS -m 10 --retry 3 https://hc-ping.com/<uuid> >> /var/log/mi/daily.log 2>&1
   ```

5. Test de ping-URL direct (bevestigt dat 'ie in het dashboard geregistreerd wordt):
   ```bash
   curl -fsS -m 10 https://hc-ping.com/<uuid>
   ```
   Zou in het healthchecks.io-dashboard meteen een groene "laatste ping"
   moeten laten zien.
6. **Nog te doen, apart, later:** de DoD ("getest door de machine bewust
   een dag uit te zetten") écht uitvoeren — bijv. de cron-regel één dag
   tijdelijk uitschakelen en checken dat er een e-mail van healthchecks.io
   komt. Niet nu meteen nodig, wel vóór T₀ᵃ als afgerond geldt.

**Status:** ping-URL werkt (getest met een losse `curl`, groen vinkje in
het dashboard), cron-regel staat (`crontab -l` bevestigd). **[30-09]** Het
dashboard toont de ping van de dagelijkse run van 07:15 UTC als groen, met
grace-tijd 2 uur en een e-mailmelding gekoppeld. Alleen punt 6 (de
daadwerkelijke "machine uitzetten"-test) staat nog open. **[30-09] Alarmkanaal
getest en geslaagd:** met een tijdelijke tweede check `mi-test` (kortste periode,
één ping vanaf de VPS, daarna geen ping meer) kwam de "down"-e-mail na twee
minuten aan; de check is daarna verwijderd. Zo is aangetoond dat een uitgebleven
ping een mail oplevert zonder dat er een dag ingestie verloren ging. Dit bewijst
het alarmkanaal, niet dat de echte cron-regel het alarm uitlokt als de machine
uitstaat. **De strikte versie (cron een dag uit) blijft staan voor na T₀ᵃ** en
is pas dan afgevinkt op de T₀ᵇ-checklist.
De ping-URL van `mi-daily` is een zwak geheim: niet in chats of screenshots
delen.

## Offsite back-up (0a-5): DigitalOcean Spaces + rclone — ✅ 27-09-2026, met een bekende beperking

1. In het DigitalOcean-dashboard: **Spaces & Object Storage → Create
   Space** — zelfde regio als de droplet (AMS3), een unieke naam (bijv.
   `mi-backups-<jouw-suffix>`).
2. **API → Spaces Keys → Generate New Key** — noteer de Access Key en
   Secret Key (de secret wordt maar ÉÉN keer getoond).
3. Op de VPS, rclone installeren en configureren (niet-interactief, geen
   losse config-stappen nodig):
   ```bash
   sudo apt install -y rclone
   rclone config create do-spaces s3 provider=DigitalOcean \
     access_key_id=<ACCESS_KEY> secret_access_key=<SECRET_KEY> \
     endpoint=ams3.digitaloceanspaces.com region=ams3
   ```
4. Testen dat de Space zichtbaar is:
   ```bash
   rclone lsd do-spaces:
   ```
5. Back-upscript aanmaken (`/opt/multi_agent/backup.sh`):
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   cd /opt/multi_agent
   DATE=$(date -u +%F)
   sqlite3 market_intelligence.db ".backup /tmp/mi-backup-$DATE.db"
   rclone copy "/tmp/mi-backup-$DATE.db" "do-spaces:<jouw-space-naam>/backups/"
   rm "/tmp/mi-backup-$DATE.db"
   # [02-10-2026, akkoord DD] Bewijs voor de dagcontrole: rclone en sqlite melden niets bij succes. Dankzij `set -e` komt deze
   # regel alleen na een geslaagde back-up; de cron-regel hieronder leidt de uitvoer naar het back-uplog.
   echo "$(date -u +%FT%TZ) back-up ok"
   ```
   ```bash
   chmod +x /opt/multi_agent/backup.sh
   ```
6. Cron-regel toevoegen (ná de dagelijkse cyclus, dus de back-up bevat de
   verse data van vandaag):
   ```
   0 8 * * * /opt/multi_agent/backup.sh >> /var/log/mi/backup.log 2>&1
   ```
7. **Restore-test (verplicht onderdeel van de DoD, "op een andere
   machine"):** vanaf je eigen laptop (met `rclone` of gewoon via het
   DigitalOcean-dashboard een bestand downloaden uit de Space):
   ```bash
   rclone copy do-spaces:<jouw-space-naam>/backups/mi-backup-<datum>.db ./restore-test.db
   sqlite3 restore-test.db "SELECT COUNT(*) FROM agent_runs;"
   ```
   Een niet-nul aantal rijen bevestigt dat de back-up een bruikbare,
   herstelbare database is — niet alleen "het bestand bestaat".

**Bevinding, expliciet gevlagd (checkpoint 4 uit `CLAUDE.md`):** een
Spaces-key die bij aanmaken beperkt wordt tot ÉÉN specifieke bucket
("Read/Write/Delete" op alleen `mi-backups-multi-agent`) kon in de
praktijk niet SCHRIJVEN (`rclone copy` gaf `AccessDenied`, ook na de key
te verwijderen en helemaal opnieuw aan te maken) — terwijl lezen
(`rclone lsd`) op diezelfde beperkte key wél werkte. Een key met
**"Full Access"** (alle Spaces-buckets in het account, niet beperkt tot
één) werkte META wél voor schrijven. Dit wijst op een beperking/bug in
DigitalOcean's relatief nieuwe "beperk tot één bucket"-functie, niet op
een fout in onze configuratie (rclone-config, regio en endpoint waren
identiek in beide pogingen). **Bewuste, geaccepteerde afwijking:** de
VPS gebruikt nu een Full-Access-Spaces-key i.p.v. de bedoelde, striktere
per-bucket-scoping — breder dan strikt nodig (kan bij alle Spaces-buckets
in het account, niet DigitalOcean's volledige account/droplets/billing),
geaccepteerd omdat er op dit moment maar één Space bestaat en "geen
back-up" een groter risico is. Kandidaat om later opnieuw te proberen als
DigitalOcean deze functie bijwerkt, of te vervangen door een aparte
sub-account-achtige oplossing als er meer Spaces bijkomen.

**Status:** Space aangemaakt (regio AMS3), rclone geconfigureerd en
werkend, `backup.sh` + cron-regel staan, restore-test geslaagd (bestand
gedownload naar DD's laptop, geopend met DB Browser for SQLite, `agent_runs`
toont de 5 verwachte rijen van de eerste succesvolle cyclus).
