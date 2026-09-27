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
git clone <repo-url> /opt/multi_agent
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

## Externe heartbeat (0a-6): healthchecks.io

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

## Offsite back-up (0a-5): DigitalOcean Spaces + rclone

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
