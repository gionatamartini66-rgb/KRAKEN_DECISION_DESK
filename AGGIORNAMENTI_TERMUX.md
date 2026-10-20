# KDD: aggiornamento GitHub → Samsung/Termux

**Stato 20 ottobre 2026:** codice KDD importato in GitHub privato, 19 file. L'aggiornatore è stato costruito nel repository e collaudato **in ambiente isolato** con 4 test (check, installazione simulata, nessuna modifica, rollback). Non è ancora stato eseguito/validato sul Samsung finché l'autore non installa il comando locale e riporta l'esito.

## Attivazione una volta sola dal Samsung

Il programma vivo resta invariato; si agisce solo sul clone separato `KDD_GITHUB_SAFE`.

```sh
cd ~/kraken-decision-desk/KDD_GITHUB_SAFE &&
git pull --ff-only origin main &&
bash scripts/installa_comando_kdd.sh
```

L'installer verifica la routine con 4 test sintetici locali, prepara il comando `kdd-aggiorna` in `$PREFIX/bin` e fa un primo controllo non invasivo. Non chiede chiavi Kraken, non scrive in GitHub e non tocca il codice live durante il solo `--check`.

## Uso successivo (una riga)

- `kdd-aggiorna --check`: scarica i nuovi commit **solo in modalità fast-forward**, verifica la lista file, verifica eventuali cambiamenti di codice in una cartella temporanea privata con tutti i test del KDD e **non modifica il programma in funzione**.
- `kdd-aggiorna` oppure `kdd-aggiorna --apply`: stessi controlli, poi chiede di digitare **APPLICA** se ci sono file cambiati; crea il backup **locale privato**, sostituisce esclusivamente file consentiti, riallinea il checkpoint nel README **locale** preservandone il testo, ripete i test sul runtime e, se falliscono, ripristina i file originali.

Lo script **non** manda comandi a Kraken, **non** esegue ordini, **non** trasferisce il contenuto del telefono verso GitHub, **non** elimina dati, **non** modifica `config.json`, portafogli, T0 o altri file JSON.

La procedura conserva la selezione di 16 sorgenti Python e 3 file pubblici sotto `vendor/` (biblioteca Lightweight Charts, licenza e avviso), più il README **locale** aggiornato esclusivamente nel checkpoint e nello storico deploy. L'elenco è scritto nel codice; nessun `git add .`, nessun push di archivi o dati conto.

**Importante:** la sostituzione di sorgenti Python **non riavvia il server Chrome già in esecuzione**: finché il server non viene riavviato in modo controllato potrebbe mostrare la versione precedente. Il riavvio automatico e il test visivo browser rimangono da implementare/verificare separatamente, senza interrompere forzatamente un processo sconosciuto.

I backup sono conservati solo sul Samsung in `~/.local/share/kdd-deploy-backups/`; non copiarli nel repository GitHub. Un backup di codice/README ripristina i file, **non può annullare effetti esterni** di eventuale codice già avviato; perciò aggiornamento soltanto volontario, con review e test.

## Vincoli e limiti

- Il KDD live è `~/kraken-decision-desk/KRAKEN_DECISION_DESK_V001/`.
- Mirror GitHub è `~/kraken-decision-desk/KDD_GITHUB_SAFE/`, non modificarlo manualmente.
- La protezione primaria è la **allowlist** dei file; `.gitignore` da solo non protegge i file già tracciati.
- Non memorizzare mai token di accesso, chiavi, estratti patrimoniali, API segrete o README originale nel repository.
- La fase 1 in GitHub non ha mai sincronizzato la cartella dati; la configurazione e l'operatività restano sul Samsung.
- Test preventivi sul clone sono di sicurezza regressiva, non una garanzia di correttezza strategica delle analisi.
- Rischio significativo: aggiornare un modulo server mentre il vecchio processo serve Chrome richiede riavvio prima di considerare attive le modifiche.
- In caso di `STOP SICUREZZA`, nessun intervento manuale sui file live: comunicare le righe d'errore in chat, senza credenziali.

## Obiettivo successivo

Dopo il primo controllo `kdd-aggiorna --check` positivo sul Samsung, creare un cambiamento benigno con commit e verificare il percorso completo `--apply` con test reali prima di utilizzarlo per le EMA20/50 e i livelli tecnici del grafico.

## Diagnosi e correzione del primo collaudo (20 ottobre 2026)

Il primo `kdd-aggiorna --check` dopo la canary `c833d569` ha confermato che il
clone si aggiorna correttamente e rileva il solo `grafico_4h.py`; lo staging
ha però prodotto `FAILED (failures=3, errors=3)`. **Nessun sorgente live è stato
modificato:** stop precauzionale corretto.

**Causa nel deploy iniziale:** il suite di test originale include verifiche
dell'effettivo stato patrimoniale/migrazione e di un piano GPT presente sul
Samsung; lo staging copiava `migrazione_attesa.json` e la fotografia T0, ma
**ometteva** `portafoglio.json` e `piano_gpt.json`. In assenza dei file
originali locali le prove producevano errori di fixture, anziché segnalare una
regressione delle tre righe di commento.

Correzione: lo staging temporaneo privato (directory 0700 sullo stesso Samsung)
copia anche questi due file **solo localmente**, prima di eseguire i 109 test.
Lo script rifiuta link simbolici per tali fixture e stampa soltanto i nomi dei
test falliti, senza diff HTML che potrebbero esporre dati. Sono state aggiunte
due regressioni dedicate all'assenza dei file privati nel clone GitHub e al
rifiuto dei symlink (suite di updater ora 6 test, una volta eseguita sul Samsung).

**Fatto osservato:** diagnosi ricavata dai sorgenti, correzione pubblicata su
GitHub. **Ancora da confermare:** l'esecuzione corretta sul Samsung di
`kdd-aggiorna --check` e `kdd-aggiorna --apply`. Nessuna installazione nel
runtime ancora dichiarata.
