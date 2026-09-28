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
                      # nodig zodra --deep-dives aan gaat, zie hieronder)
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

**Na 3 schone dagen:** `--deep-dives` toevoegen aan de cron-regel (en
`ANTHROPIC_API_KEY` in `.env`), en **T₀ᵃ is gehaald** zodra dat ook 7 dagen
op rij zonder handmatige actie draait (roadmap 1.11's eigen DoD).

**Let op wat die vlag sinds 28-09 nog meer aanzet:** de wekelijkse
forecast-ronde (roadmap 2.0) draait mee op de maandagcyclus, mits er een
Anthropic-client is. Er is dus GEEN aparte cron-regel voor; de bestaande
`15 7 * * 1-5` dekt hem. Controleer op de eerste maandag na het aanzetten:

```bash
sqlite3 market_intelligence.db \
  "SELECT domain, COUNT(*) FROM predictions GROUP BY domain;"
```

Verwacht: vijf domeinen, samen 57 rijen (sector 22, financial 12,
currency 9, monetary_policy 8, economic 6). Staat er een domein op nul of
op een te laag aantal, kijk dan in het log naar regels die beginnen met
`Forecast-probleem:` — een deels mislukte ronde gooit de geldige
voorspellingen niet weg, dus een lager aantal is geen crash maar wel een
gat. De ronde probeert het de rest van de week elke ochtend opnieuw.

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
het dashboard), cron-regel staat (`crontab -l` bevestigd). Alleen punt 6
(de daadwerkelijke "machine uitzetten"-test) staat nog open.

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
