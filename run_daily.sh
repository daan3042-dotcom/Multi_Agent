#!/usr/bin/env bash
# run_daily.sh
# Roadmap 1.11 -- cron-wrapper. Cron laadt geen shell-profile en run_daily.py
# heeft zelf geen dotenv-afhankelijkheid (CLAUDE.md-regel 2: geen nieuwe
# dependency waar vermijdbaar) -- dit script laadt .env in de environment
# en start dan run_daily.py, in plaats van elke API-key als losse
# VAR=waarde-regel in de crontab te zetten (foutgevoelig, en crontab-syntax
# verdraagt geen quotes/newlines in een waarde).
#
# Verwacht: dit script staat in dezelfde map als de repo-checkout, met
# .env en .venv ernaast (bijv. /opt/multi_agent/run_daily.sh,
# /opt/multi_agent/.env, /opt/multi_agent/.venv/). Zie docs/deployment.md
# voor de volledige VPS-inrichting en .env.example voor de verwachte
# variabelen.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

exec .venv/bin/python run_daily.py "$@"
