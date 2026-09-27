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
faalscenario dat de externe heartbeat (0a-6, hieronder) moet opvangen als
niemand kijkt, maar tijdens de dry-run kijk je zelf.

## Nog niet hier: back-up en heartbeat

Taken 0a-5 (offsite back-up) en 0a-6 (externe heartbeat) staan los van
deze inrichting — zie `docs/roadmap.md` fase 0 voor de DoD per taak. Pak
die na deze dry-run op, niet ervoor: een back-up van een database die nog
geen enkele echte dag heeft gedraaid is niet zinvol te testen.
