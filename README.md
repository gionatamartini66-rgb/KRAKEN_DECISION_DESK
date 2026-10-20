# KRAKEN DECISION DESK (KDD) — repository tecnico privato

**Stato operativo (20 ottobre 2026):** repository privato collegato a ChatGPT e a Termux; importati **19 file tecnici** con commit `3fab216ac1c66cb03f6d57c5c42bd1fdbb7ac175`, dopo 109/109 test locali superati. Il programma vivo continua sul Samsung. L'aggiornatore GitHub → Termux è ora disponibile nel repository, con 4 test isolati PASS (dry run/applicazione simulata/nessun cambiamento/rollback). **Installazione dell'aggiornatore e collaudo su Samsung ancora in attesa di conferma dell'autore.**

## Scopo
KDD rileva dati di mercato pubblici Kraken e Binance, conserva fonti e orari, aiuta a esaminare strutture tecniche e condizioni di liquidità; GPT interpreta e formula proposte, l'autore discute e decide. Solo l'autore esegue eventuali ordini manualmente. Per ora spot, niente short/leva o ordini automatici. Il patrimonio strategico è **a gestione attiva**, non un vincolo a conservare ogni token.

## Regola di sicurezza fondamentale
**Non trasferire su GitHub dati personali/finanziari, credenziali o stato operativo**. Il repository conserva solo sorgenti selezionati e licenze di dipendenze pubbliche. Rimangono **esclusivamente sul Samsung**:
- `~/.config/kraken-decision-desk/readonly.json` e ogni altro segreto/chiave, anche nei backup;
- `portafoglio.json`, saldi, T0, movimenti e storici, piani GPT, dossier con snapshot, report, file HTML generati e log;
- il README operativo **completo** in Termux, che contiene dettagli patrimoniali e non viene copiato qui;
- `config.json` locale, finché non viene definita una configurazione pubblicabile priva di informazioni private.

Il file `.gitignore` usa una **allowlist** di nomi di file. Non aggirarla usando `git add -f`. È solo una precauzione: i contenuti dei sorgenti vanno comunque controllati prima di pubblicarli, e un file già tracciato non è protetto retroattivamente da .gitignore.

## Importazione e sviluppo
Per il primo trasferimento usare esclusivamente la procedura `IMPORTAZIONE_SICURA.md` e lo script `scripts/importa_codice_termux.sh` da un clone privato distinto dalla cartella KDD live; **non inizializzare Git direttamente nella cartella del programma corrente e non pubblicare tutta la cartella con `git add .`**.

Le modifiche future devono arrivare sul telefono solo tramite aggiornamento controllato dopo test. La nuova procedura documentata in **`AGGIORNAMENTI_TERMUX.md`** aggiorna il clone GitHub separato, collauda le modifiche in staging locale, richiede conferma `APPLICA`, crea backup locali privati e ripete 109 test sul programma, con rollback dei sorgenti in caso di errore. **Non ancora collaudata sul Samsung**: nessuna modifica al programma live viene dichiarata finché i risultati del dispositivo non sono verificati. Non eseguire `git pull` dentro la cartella runtime. La sostituzione dei file non riavvia il server Chrome già attivo.

## Lavoro grafico
POC grafico SUI/EUR 4H con candele e volumi reali, visualizzato su Chrome Android dall'utente il 20 ottobre. Prossime fasi: indicatori EMA20/50, pivot classico e suoi R1–R3/S1–S3, fino a tre supporti/resistenze strutturali per timeframe, 15m/1H/4H/1D, figure candlestick contestualizzate. Tutti i risultati devono provenire da dati chiusi con fonte e orario, senza segnali automatici BUY/SELL.

**Nota:** i test di continuità dei sorgenti dipendono dal README e dalla configurazione locali sul Samsung. Un clone soltanto tecnico può richiedere una fixture di test e una procedura di deploy specifica, da implementare prima di dichiararlo completamente portabile.
