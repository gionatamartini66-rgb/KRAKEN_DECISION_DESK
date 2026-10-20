#!/data/data/com.termux/files/usr/bin/bash
# Installer una volta sola: pubblica il comando locale kdd-aggiorna.
set -euo pipefail
MIRROR="$HOME/kraken-decision-desk/KDD_GITHUB_SAFE"
test -f "$MIRROR/scripts/kdd_aggiorna.sh" || {
  echo 'STOP: clone KDD aggiornato non trovato'; exit 2;
}
test -n "${PREFIX:-}" && test -d "$PREFIX/bin" || {
  echo 'STOP: PREFIX di Termux non disponibile'; exit 2;
}
printf 'Test interni della procedura aggiornamento...\n'
python "$MIRROR/scripts/test_kdd_aggiorna.py"
TARGET="$PREFIX/bin/kdd-aggiorna"
TMP="$PREFIX/bin/.kdd-aggiorna-temp-$$"
trap 'rm -f "$TMP"' EXIT
cat > "$TMP" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
exec bash "$HOME/kraken-decision-desk/KDD_GITHUB_SAFE/scripts/kdd_aggiorna.sh" "$@"
EOF
chmod 700 "$TMP"
mv -f "$TMP" "$TARGET"
echo 'Comando kdd-aggiorna installato (non contiene credenziali).'
echo 'Prima verifica non invasiva...'
"$TARGET" --check
