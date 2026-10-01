#!/usr/bin/env bash
# archive_daily.sh
# Cron-wrapper voor archive_daily.py, zelfde patroon als run_daily.sh: laadt
# .env (cron kent geen shell-profile) en start dan het script. Bewust een
# eigen wrapper en een eigen lock-bestand: dit proces deelt niets met de
# dagelijkse run. Zie docs/deployment.md, "Het ruwe archief".
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

exec .venv/bin/python archive_daily.py "$@"
