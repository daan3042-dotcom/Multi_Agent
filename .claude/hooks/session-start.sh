#!/bin/bash
# SessionStart-hook voor Claude Code op het web.
#
# Twee taken, allebei bedoeld om tijd te besparen die anders verloren gaat:
#
# 1. Dependencies installeren, zodat `pytest` meteen werkt. Zonder dit moet
#    elke sessie eerst zelf ontdekken dat pytest ontbreekt en het
#    installeren.
#
# 2. WAARSCHUWEN VOOR PARALLEL WERK. Op 28-09-2026 hebben twee sessies
#    onafhankelijk dezelfde vier roadmap-items gebouwd (atomiciteit,
#    ouderdomsgrens, API-quota, economic agent), omdat geen van beide keek
#    of er al een branch bestond waar dat op stond. Beide branches waren
#    gewoon zichtbaar op GitHub -- er keek alleen niemand. Deze hook maakt
#    dat kijken onvermijdelijk in plaats van een goede gewoonte.
#
# Faalt nooit de sessie: elke netwerkstap mag mislukken (offline container,
# geen credentials) zonder dat de sessie daarop stukloopt.

set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

# --- 1. Dependencies ---------------------------------------------------
if [ -f requirements.txt ]; then
  python -m pip install --quiet --disable-pip-version-check -r requirements.txt 2>/dev/null \
    || echo "LET OP: 'pip install -r requirements.txt' is niet gelukt; draai 'm handmatig voordat je pytest gebruikt."
fi

# --- 2. Parallel werk opsporen -----------------------------------------
git fetch --all --prune --quiet 2>/dev/null || {
  echo "LET OP: 'git fetch' is niet gelukt. Controleer HANDMATIG of er andere branches openstaan voordat je aan een roadmap-item begint."
  exit 0
}

# Default branch bepalen. Deze repo heeft (nog) geen 'main'; de default is
# ingesteld op GitHub en staat niet per se lokaal als symbolic ref.
DEFAULT="$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null)"
if [ -z "$DEFAULT" ]; then
  DEFAULT="$(git remote show origin 2>/dev/null | awk '/HEAD branch/ {print "origin/"$NF}')"
fi
if [ -z "$DEFAULT" ] || ! git rev-parse --verify --quiet "$DEFAULT" >/dev/null; then
  echo "LET OP: de default branch is niet te bepalen. Controleer handmatig welke branches openstaan."
  exit 0
fi

HUIDIG="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
GEVONDEN=0
REGELS=""

while read -r BRANCH; do
  [ -z "$BRANCH" ] && continue
  [ "$BRANCH" = "$DEFAULT" ] && continue
  [ "$BRANCH" = "origin/$HUIDIG" ] && continue

  AANTAL="$(git rev-list --count "$DEFAULT..$BRANCH" 2>/dev/null || echo 0)"
  [ "$AANTAL" -eq 0 ] && continue

  LAATSTE="$(git log -1 --format='%ad | %s' --date=short "$BRANCH" 2>/dev/null)"
  REGELS="${REGELS}  - ${BRANCH}  (${AANTAL} commits niet in ${DEFAULT})
      laatste: ${LAATSTE}
"
  GEVONDEN=$((GEVONDEN + 1))
done < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin 2>/dev/null)

if [ "$GEVONDEN" -gt 0 ]; then
  cat <<BANNER

========================================================================
LET OP: ${GEVONDEN} branch(es) met werk dat NIET in ${DEFAULT} zit.
========================================================================
${REGELS}
Voordat je aan een roadmap-item begint: controleer of het daar al op
staat. Op 28-09-2026 is dit misgegaan -- twee sessies bouwden dezelfde
vier fase-0-items onafhankelijk, puur omdat niemand keek.

Nuttige commando's:
  git log --oneline ${DEFAULT}..<branch>
  git diff --name-only ${DEFAULT}...<branch>

En let op: docs/project-state.md en docs/roadmap.md op ${DEFAULT}
lopen achter op alles wat hierboven staat. Wat daar "nog te doen" heet,
kan elders al gebouwd zijn.
========================================================================

BANNER
fi

exit 0
