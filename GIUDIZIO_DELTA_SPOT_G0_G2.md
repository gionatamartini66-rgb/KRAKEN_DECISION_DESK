# KDD — GIUDIZIO G0/G2 SUL DELTA SPOT

**Data:** 21 ottobre 2026.  
**Classe:** revisione G0 dei sorgenti e della cronologia sperimentale; **nessuna sperimentazione o modifica del runtime**.  
**Stato:** **ESPERIMENTO STORICO A/B COMPLETATO E GIUDICATO NEL SUO PERIMETRO: LIMITARE**. I resoconti verificati da Termux il 21 ottobre riportano **4 casi, 12/12 orizzonti osservati, hash A/B coerenti, 0/4 cambi di decisione**. La conclusione non è generalizzabile a tutte le condizioni di mercato e non dimostra alcuna redditività.  
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

## 2. Evidenze sperimentali e provenienza della verifica locale

**G2 contestuale, 19/10:** prova riferita su INJ, QNT, AVA, PUMP: descrizione di coincidenze e divergenze prezzo/delta. Non costituisce prova prospettica di rendimento.

**A/B prospettico, 19/10, verificato da output Termux il 21/10:** quattro candidati QNT, SUI, PUMP, ONDO; fasi congelate A senza delta / B con delta. L'utente ha eseguito localmente `studio_delta.py`: `ORIZZONTI_COMPLETI`, **1 esperimento**, **4 casi**, **12/12 chiusure osservate** a +1h/+4h/+24h, **0 nuove chiamate Kraken** in quel passaggio, **0 errori**.

Nel successivo controllo locale, `studio_delta.paired()` ha validato gli abbinamenti e l'hash della fase A; il checksum dell'archivio esiti ha corrisposto alla fase B (**VERIFICA A/B: OK**). Tutti e quattro i token mostravano **delta della candela chiusa negativo** e **variazione di prezzo positiva a tutti e tre gli orizzonti successivi**. L'output delle fasi A/B ha mostrato esattamente **zero cambiamenti di azione su quattro**; le motivazioni B confermano perlopiù informazioni già disponibili su prezzo, forza relativa, volumi e book. Per SUI il delta della finestra mobile risultava di segno opposto a quello della candela chiusa: **le due finestre temporali non sono intercambiabili**.

**Interpretazione delimitata:** delta negativo in una candela e rialzo successivo non sono logicamente incompatibili; i casi mostrano però che **il segno del delta non va interpretato come previsione direzionale**, e che **nel campione osservato l'informazione non ha cambiato nessuna decisione**. Non è provata una relazione contrarian, né è possibile classificare le scelte prudenziali come errori ex post senza regole di ingresso, uscita, invalidazione, commissioni e rischio. **Quattro token non equivalgono a dodici esperimenti indipendenti.**

**Provenienza e limiti:** i risultati sono stati letti sul dispositivo tramite comandi Python e **trascritti dall'output Termux in chat**. Gli snapshot A/B e gli esiti completi restano privati sul Samsung, non copiati in GitHub. La verifica locale degli hash e dei 12 orizzonti è documentata nell'output; questo documento non attesta un'acquisizione diretta integrale dei tre file da parte del revisore né una validazione esterna delle quotazioni storiche. Il valore predittivo generale resta **NON DIMOSTRATO**.

## 3. Giudizio per l'uso decisionale attuale

**LIMITARE**: conservare il delta spot **come osservazione di microstruttura, subordinata a copertura, freschezza e medesima finestra del prezzo**; non eliminarlo, perché misura un fenomeno reale distinto dall'OHLCV, ma non promuoverlo a fattore direzionale affidabile.

Regole di uso **da applicare nel ragionamento**, senza sostenere che il software le faccia già rispettare tutte:
1. **Mostrare** fonte, coppia, unità, finestra precisa, copertura, istante ultimo trade e stato; separare la rolling 15m dalla candela 15m chiusa.
2. **Non classificare** il solo segno/valore del delta come BUY, SELL, breakout confermato, probabilità di continuazione, previsione del rendimento o ranking privilegiato.
3. **Non sommare** delta di coppie/valute/fonti diverse o confrontare variazioni di prezzo misurate in intervalli differenti.
4. **Sospendere l'inferenza** quando il campione non copre la candela, è scaduto, l'identità della coppia è ambigua o mancano dati confrontabili.
5. **Cercare discordanza utile** col prezzo, col volume e col book; trattarla come quesito di approfondimento e non come segnale predittivo.

**Zero cambiamenti A→B nel campione verificato tramite Termux** impedisce di sostenere che il delta abbia già migliorato le decisioni. Non assegniamo pesi o soglie decisionali nuove.

## 4. Adjudication chiusa per il campione; lavoro successivo distinto

**Decisione metodologica per l'esperimento disponibile: LIMITARE.** Con dati A/B e osservazioni prospettiche disponibili, il punto sperimentale storico è giudicato: il delta è una descrizione utile della microstruttura, ma il suo **valore decisionale incrementale non è dimostrato**. L'assenza di variazioni delle decisioni non permette di misurare miglioramenti di accuratezza, PnL o opportunità perse imputabili causalmente al delta.

**NON** occorre ripetere lo stesso esperimento, introdurre filtri numerici arbitrari o richiedere altre chiamate API per dichiarare questo esito. La limitazione non impone eliminare la raccolta tecnica del dato; non promuoverlo a segnale operativo o fattore di ranking.

Un'eventuale valutazione futura su campione maggiore, con esiti operativi netti predefiniti, sarebbe **un altro esperimento**, autorizzabile separatamente in roadmap; non rientra in questa adjudication.

La sequenza resta: **G0/G2 → giudizio delta (CHIUSO PER IL CAMPIONE: USO LIMITATO) → scelta umana di una sola integrazione motivata → consolidamento motore decisionale GPT**. La scelta del prossimo componente non è automaticamente autorizzata da questo rapporto.

**Nessuna modifica al software runtime, nessun trade, nessun documento privato del Samsung pubblicato.**
