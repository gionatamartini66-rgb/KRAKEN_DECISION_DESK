# KRAKEN DECISION DESK (KDD) — repository tecnico privato

**Stato iniziale (20 ottobre 2026):** repository privato usato come ponte fra ChatGPT/GitHub e il programma installato su Samsung/Termux. **Non contiene ancora il codice operativo finché l'importazione sicura non viene eseguita e verificata.**

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

Le modifiche future devono arrivare sul telefono solo tramite aggiornamento/merge controllato dopo test. Il mirror GitHub **non** sostituisce automaticamente i dati o il codice live; non usare `git pull` direttamente sul runtime finché il flusso di distribuzione non sarà validato.

## Lavoro grafico
POC grafico SUI/EUR 4H con candele e volumi reali, visualizzato su Chrome Android dall'utente il 20 ottobre. Prossime fasi: indicatori EMA20/50, pivot classico e suoi R1–R3/S1–S3, fino a tre supporti/resistenze strutturali per timeframe, 15m/1H/4H/1D, figure candlestick contestualizzate. Tutti i risultati devono provenire da dati chiusi con fonte e orario, senza segnali automatici BUY/SELL.

**Nota:** i test di continuità dei sorgenti dipendono dal README e dalla configurazione locali sul Samsung. Un clone soltanto tecnico può richiedere una fixture di test e una procedura di deploy specifica, da implementare prima di dichiararlo completamente portabile.
