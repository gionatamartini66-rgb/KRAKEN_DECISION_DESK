#!/data/data/com.termux/files/usr/bin/bash
# Ponte: GitHub privato -> mirror locale -> verifica -> KDD live, SOLO dopo consenso.
set -euo pipefail
MIRROR="$HOME/kraken-decision-desk/KDD_GITHUB_SAFE"
REPO='gionatamartini66-rgb/KRAKEN_DECISION_DESK'
test -d "$MIRROR/.git" || { echo 'STOP: clone GitHub non presente'; exit 2; }
cd "$MIRROR"
origin="$(git remote get-url origin)"
case "$origin" in
  "git@github.com:$REPO.git"|"git@github.com:$REPO"|"https://github.com/$REPO.git"|"https://github.com/$REPO"|"ssh://git@github.com/$REPO"|"ssh://git@github.com/$REPO.git") ;;
  *) echo 'STOP: indirizzo origin diverso dal repository KDD autorizzato'; exit 2 ;;
esac
if [ "$(git branch --show-current)" != main ] || [ -n "$(git status --porcelain)" ]; then
  echo 'STOP: ramo Git non main o modifiche locali. Nessun pull.'; exit 2
fi
if [ "$#" -gt 1 ]; then
  echo 'Uso: kdd-aggiorna [--check|--apply]'; exit 2
fi
mode="${1:---apply}"
case "$mode" in --check|--apply) ;; *) echo 'Solo --check o --apply'; exit 2 ;; esac
printf 'KDD: recupero codice GitHub, senza caricare dati...\n'
git pull --ff-only origin main
python scripts/kdd_aggiorna.py "$mode"
