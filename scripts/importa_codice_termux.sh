#!/data/data/com.termux/files/usr/bin/bash
# Importazione INIZIALE del solo codice KDD su GitHub PRIVATO.
# Non inizializzare git dentro KDD live. Non copiare dati, report, chiavi o README operativo.
set -euo pipefail

SRC="$HOME/kraken-decision-desk/KRAKEN_DECISION_DESK_V001"
MIRROR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="gionatamartini66-rgb/KRAKEN_DECISION_DESK"

echo "KDD: verifica origine e repository..."
test -d "$SRC" && test -f "$SRC/decision_desk.py" && test -f "$SRC/grafico_4h.py" || {
  echo "STOP: progetto KDD originale non trovato. Nessun file copiato."; exit 1;
}
test "$(git -C "$MIRROR" rev-parse --is-inside-work-tree)" = "true" || {
  echo "STOP: eseguire da clone GitHub separato."; exit 1;
}
REMOTE="$(git -C "$MIRROR" remote get-url origin)"
case "$REMOTE" in
  "https://github.com/$REPO"|"https://github.com/$REPO.git"|"git@github.com:$REPO"|"git@github.com:$REPO.git"|"ssh://git@github.com/$REPO"|"ssh://git@github.com/$REPO.git") ;;
  *) echo "STOP: origin non corrisponde al repository KDD autorizzato."; exit 1 ;;
esac

if [ -n "$(git -C "$MIRROR" status --porcelain)" ]; then
  echo "STOP: clone non pulito. Nessuna importazione avviata."; exit 1
fi

echo "KDD: test sul programma ORIGINALE, prima di copiare il codice..."
(cd "$SRC" && python -m unittest -q test_decision_desk)

# Lista APPROVATA: solamente sorgenti testati. Nessun *.json, README di Termux,
# screenshot, report, database, dato conto, chiave o archivio.
FILES=(
  analisi_v02.py
  binance_reference.py
  costi_spot.py
  decision_desk.py
  dossier_trade.py
  flusso_spot.py
  grafico_4h.py
  kdd_saldi.py
  kraken_readonly.py
  mercati_spot.py
  piano_gpt.py
  ricerca_setup.py
  serve.py
  studio_delta.py
  test_decision_desk.py
  verifica_piani.py
)
VENDOR=(
  lightweight-charts-5.2.1.js
  LIGHTWEIGHT_CHARTS_LICENSE.txt
  LIGHTWEIGHT_CHARTS_NOTICE.txt
)
for f in "${FILES[@]}"; do
  test -f "$SRC/$f" || { echo "STOP: sorgente mancante: $f"; exit 1; }
done
for f in "${VENDOR[@]}"; do
  test -f "$SRC/vendor/$f" || { echo "STOP: asset grafico mancante: $f"; exit 1; }
done

# Controllo supplementare: rifiuta secret/key letterali hardcoded ovvi.
# Una scansione non prova da sola che ogni file sia innocuo; ecco perche'
# sono comunque ammessi SOLO i nomi esplicitamente previsti.
python - "$SRC" "${FILES[@]}" <<'PY'
import pathlib,re,sys
base=pathlib.Path(sys.argv[1])
pattern=re.compile(
    r"(?im)\b(?:KRAKEN_API_KEY|KRAKEN_API_SECRET|API_SECRET|API_KEY|PRIVATE_KEY)"
    r"\s*(?::[^=]+)?=\s*['\"]([^'\"\n]{15,})['\"]"
)
for name in sys.argv[2:]:
    body=(base/name).read_text(encoding='utf-8')
    if pattern.search(body) or "-----BEGIN PRIVATE KEY-----" in body:
        print("STOP: possibile credenziale incorporata nel sorgente",name)
        raise SystemExit(1)
print("Controllo semplice contro credenziali hardcoded: PASS (non garanzia assoluta)")
PY

echo "KDD: trasferimento in clone SEPARATO, soltanto lista approvata..."
for f in "${FILES[@]}"; do
  cp -p "$SRC/$f" "$MIRROR/$f"
done
mkdir -p "$MIRROR/vendor"
for f in "${VENDOR[@]}"; do
  cp -p "$SRC/vendor/$f" "$MIRROR/vendor/$f"
done

(
  cd "$MIRROR"
  git add -- "${FILES[@]}"
  for f in "${VENDOR[@]}"; do git add -- "vendor/$f"; done
  # Non usare git add . o -f: il README patrimoniale e i file privati sono esclusi.
  git diff --cached --check
  python - <<'PY'
import subprocess
approved=set("""analisi_v02.py binance_reference.py costi_spot.py decision_desk.py
dossier_trade.py flusso_spot.py grafico_4h.py kdd_saldi.py
kraken_readonly.py mercati_spot.py piano_gpt.py ricerca_setup.py
serve.py studio_delta.py test_decision_desk.py verifica_piani.py
vendor/lightweight-charts-5.2.1.js
vendor/LIGHTWEIGHT_CHARTS_LICENSE.txt
vendor/LIGHTWEIGHT_CHARTS_NOTICE.txt""".split())
actual=set(subprocess.check_output(
    ["git","diff","--cached","--name-only"],text=True).splitlines())
bad=actual-approved
if bad or not actual:
    raise SystemExit("STOP: staged inattesi o vuoti: "+repr(sorted(bad)))
if any(x.endswith((".json",".env",".pem",".key",".log",".sqlite",".html"))
       or "README.md" in x for x in actual):
    raise SystemExit("STOP: formato di file riservato nello staging")
print("STAGING OK:",len(actual),"file codici/asset, NESSUN JSON/README privato.")
PY
  git diff --cached --stat
  git commit -m "Importazione iniziale KDD: solo sorgenti approvati, niente dati conto"
  git push origin HEAD:main
)
echo "IMPORTAZIONE COMPLETATA. Il KDD live sul Samsung e' rimasto intatto."
