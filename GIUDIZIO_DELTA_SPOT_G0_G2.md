# KDD — GIUDIZIO G0/G2 SUL DELTA SPOT

**Data:** 21 ottobre 2026.  
**Classe:** revisione G0 dei sorgenti e della cronologia sperimentale; **nessuna sperimentazione o modifica del runtime**.  
**Stato:** **DECISIONE D'USO ATTUALE: LIMITARE**. La **validazione scientifica incrementale rimane INCOMPLETA** finché non si rileggono integralmente i congelamenti A/B e gli esiti prospettici sul Samsung.  
**Autorità:** proposta tecnico-analitica. Eventuali ampliamenti e trade richiedono decisione dell'autore.

## 1. Oggetto misurato — verificato direttamente nel codice

Il componente `flusso_spot.py` utilizza i **trade SPOT pubblici di una singola coppia Kraken**, al massimo gli ultimi **1.000**. Il valore di ciascuna esecuzione nella valuta di quotazione è `prezzo × quantità`. Il **delta firmato** è `volume_buy − volume_sell`, e la percentuale netta è `100 × (volume_buy − volume_sell)/(volume_buy + volume_sell)` quando il denominatore è positivo. Il campo di lato `b/s` viene letto dai trade Kraken; la documentazione Kraken del canale trade WebSocket v2 qualifica esplicitamente il lato come **lato dell'ordine aggressore/taker**.

**Fonte REST:** https://docs.kraken.com/api/docs/rest-api/get-recent-trades (l'endpoint dichiara massimo 1.000 trade).  
**Fonte semantica WebSocket spot:** https://docs.kraken.com/api/docs/websocket-v2/trade (il campo `side` è il lato del `taker order`).

Il codice distingue correttamente:
- finestra **mobile 15 minuti** rispetto all'istante di acquisizione;
- **candela 15m CHIUSA** `[inizio, fine)`, confrontabile con il prezzo soltanto se il campione copre effettivamente tutta quella candela;
- finestra **4 ore**, calcolata solo quando risultano coperte tutte le quattro ore; non stimata quando i 1.000 trade non bastano;
- ultima esecuzione scaduta (>5 minuti), campione mancante o incoerente.

Le regressioni `test_decision_desk.py` verificano formule, campioni tronchi, finestre disallineate, latenze e gestione di risposte API fallite. Questi test verificano la **correttezza software e le limitazioni della copertura**, non efficacia economica.

**Il delta spot non è** un CVD storico continuo, il book, un indice multi-exchange, un indicatore dei futures o una previsione della direzione futura.

## 2. Due livelli di osservazione — cronologia da verificare sui congelamenti originali

**G2 contestuale, 19/10 ~17:17 Italia:** la cronologia di chat riferisce una prova su **INJ, QNT, AVA e PUMP** che ha mostrato alcune convergenze fra delta e variazione di prezzo, oltre alla divergenza QNT (buy delta positivo con prezzo in lieve ribasso). Questa è una **correlazione contestuale sulla finestra osservata**, non un test prospettico di redditività. Non sono ripubblicati qui gli snapshot e i numeri per rispettare il confine fra repository tecnico e dossier operativi privati.

**Esperimento prospettico A/B, 19/10 ~22:05 Italia:** la cronologia di chat riferisce fasi A senza delta / B con delta, congelate per **SUI, QNT, PUMP, ONDO**. Tutti e quattro i delta erano negativi e **nessuna delle quattro decisioni operative riferite cambiò** dopo aver mostrato il dato. Si tratta di evidenza preliminare di **nessun valore decisionale incrementale osservato in quel campione**, non di dimostrazione che il delta sia sempre inutile.

Il codice `studio_delta.py` implementa una coppia A/B immutabile con checksum della fase A e verifica le **variazioni di chiusura** a **+1h, +4h e +24h**, quando le candele sono disponibili. Le variazioni di prezzo **non** sono PnL, fill, segnali operativi o causalità; il modulo si aggiorna su richiesta, non in background.

**Lacuna probatoria esplicita:** in questa ricognizione non sono stati accessibili direttamente i file originali `esperimenti_delta/*_fase_A.json`, `*_fase_B.json`, `*_esiti.json`, relativi hash e timestamp interni. Sono custoditi nel runtime privato Samsung e non nel repository GitHub, correttamente per politica di riservatezza. Non è quindi accertata qui la completezza degli orizzonti +1/+4/+24h né verificato direttamente il verbatim delle due fasi. **Non proclamare validazione scientifica definitiva o guadagno dimostrato.**

## 3. Giudizio per l'uso decisionale attuale

**LIMITARE**: conservare il delta spot **come osservazione di microstruttura, subordinata a copertura, freschezza e medesima finestra del prezzo**; non eliminarlo, perché misura un fenomeno reale distinto dall'OHLCV, ma non promuoverlo a fattore direzionale affidabile.

Regole di uso **da applicare nel ragionamento**, senza sostenere che il software le faccia già rispettare tutte:
1. **Mostrare** fonte, coppia, unità, finestra precisa, copertura, istante ultimo trade e stato; separare la rolling 15m dalla candela 15m chiusa.
2. **Non classificare** il solo segno/valore del delta come BUY, SELL, breakout confermato, probabilità di continuazione, previsione del rendimento o ranking privilegiato.
3. **Non sommare** delta di coppie/valute/fonti diverse o confrontare variazioni di prezzo misurate in intervalli differenti.
4. **Sospendere l'inferenza** quando il campione non copre la candela, è scaduto, l'identità della coppia è ambigua o mancano dati confrontabili.
5. **Cercare discordanza utile** col prezzo, col volume e col book; trattarla come quesito di approfondimento e non come segnale predittivo.

**Zero cambiamenti A→B nel campione riferito** impedisce di sostenere che il delta abbia già migliorato le decisioni. Non assegniamo pesi o soglie decisionali nuove.

## 4. Residuo verificabile e sequenza preservata

Per trasformare il giudizio d'uso in **adjudication scientifica chiusa**, occorre la lettura locale source-bound delle coppie congelate A/B e degli eventuali file esiti: controllo checksum, riferimenti temporali, confronto ragioni **A vs B per candidato**, stato +1h/+4h/+24h, copertura, eventuali risultati mancanti. Questa verifica **non necessita nuovi indicatori, nuovi trade, API private o nuovi esperimenti**.

L'accesso al Samsung da Remote Desktop Commander era **esaurito per il mese** al momento della ricognizione. Non chiedere di mettere snapshot privati su GitHub, aggirare la quota o ripetere chiamate remote bloccate. Se non è possibile leggere gli originali, conservare l'esito **LIMITATO — VALIDAZIONE INCOMPLETA** senza inventare risultati.

La roadmap resta nell'ordine: **G0/G2 → adjudication delta (uso LIMITATO, conferma prospettica pendente) → una sola integrazione motivata → motore decisionale GPT**. Nessuna fase successiva è autorizzata automaticamente da questo giudizio.

**Nessun dato patrimoniale, segreto o snapshot operativo copiato nel repository.**
