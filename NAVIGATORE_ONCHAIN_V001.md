# KDD — NAVIGATORE ON-CHAIN E CONTESTO FONDAMENTALE
## Disegno V001 — priorità on-chain

**Data:** 21 ottobre 2026.  
**Classe:** G0 — orientamento, inventario sorgenti e disegno di una sola futura integrazione; **NON IMPLEMENTATO / NON AUTORIZZATO A OPERARE**.  
**Origine:** scelta strategica dell'autore successiva alla chiusura della prova del delta spot: dare precedenza alle **informazioni on-chain**, integrandole con fondamentali, macroeconomia, geopolitica e notizie sul singolo token.  
**Ambito:** strumento di supporto a GPT, operatività iniziale esclusivamente spot e manuale. Non sostituisce `GOVERNO_KDD.md`, il mandato privato Termux o il dossier tecnico già esistente.

### 1. Perché questa è la prossima direzione

Il delta buy/sell spot osservato su Kraken non ha modificato le quattro decisioni della prova A/B, pur essendo stato misurato correttamente. La nuova priorità non è sommare indicatori: è ricostruire **fattori di offerta, domanda e rischio** che la sola struttura dei prezzi non cattura.

**Navigatore KDD = analisi on-chain in primo piano**, con fondamentali del token e notizie specifiche; macro e geopolitica come contesto e possibili fattori di regime. Questi sono **canali informativi di una sola integrazione decisionale**, non autorizzazioni a tre o quattro moduli separati.

Il contesto non deve apparire accanto ai grafici come elenco descrittivo, ma permettere una domanda operativa: **«Questa nuova informazione cambia la valutazione, e perché?»** Nessuna certezza predittiva implicita.

### 2. On-chain: dati candidati, rilevanza e limiti

| Famiglia | Domanda cui risponde | Limiti e precauzioni |
| --- | --- | --- |
| **Offerta e vesting** | Quando e quanti token diventano negoziabili, cambiano supply e pressione potenziale? | Verificare calendari ufficiali, eventuali contratti e reale circolazione. Unlock ≠ vendita; supply aggregata può divergere da custodia ed emissioni. |
| **Flussi verso/da exchange** | Crescono depositi o prelievi presso indirizzi **verificati** di exchange? | Etichette di wallet spesso incerte/incomplete. Trasferimento ≠ ordine/sell; movimenti interni, custodia e bridge alterano i conteggi. |
| **Grandi detentori e concentrazione** | Si modificano concentrazione, quantità vincolate, disponibilità presso wallet conosciuti? | Un indirizzo può essere custodian, contratto o exchange di migliaia di utenti. Whale transfer ≠ accumulo/distribuzione. Evitare profilazioni personali. |
| **Uso effettivo rete/protocollo** | Attività verificabile: utenti/indirizzi attivi, operazioni, fees, revenue protocollo, TVL quando pertinente? | Un indirizzo non equivale a un utente; transazioni bot/spam non valgono adozione; TVL, fees e ricavi hanno definizioni e contabilità diverse. Non tutte le metriche esistono per ogni asset. |
| **Liquidità on-chain** | Cambiano profondità, pool DEX, concentrazione LP, slippage e flussi di bridge? | DEX ≠ liquidità di esecuzione Kraken. Bridge e rappresentazioni wrapped possono causare doppio conteggio. |
| **Eventi di rete/contratto** | Upgrade, exploit, pause, governance, variazioni di tokenomics? | Distinguere dato direttamente osservabile, annuncio ufficiale, interpretazione e rumor; tempi di validazione finality e chain-specific. |

**L'identità viene prima dei numeri:** mappare l'asset Kraken a **chain, natura dell'asset (nativo/ERC-20/SPL/etc.), identificatore di contratto o denom verificato, eventuali bridge/wrapped**, e fonte della verifica. Un ticker da solo NON identifica un contratto. Se la corrispondenza è ambigua → `IDENTITA_NON_VERIFICATA`, nessuna metrica attribuita.

**Osservazione e inferenza sono separate:** in ogni metrica registrare rete, indirizzo/contratto identificato (solo se pubblico e necessario), fonte primaria o derivata, UTC e blocco/altezza, copertura temporale, unità, metodologia, etichettatura e livello di confidenza. Correlazione con prezzi ≠ causalità né segnale BUY/SELL.

### 3. Fonti da qualificare prima dell'implementazione

**Priorità di verifica:**
1. **Fonte primaria:** explorer/RPC pubblico e documentazione ufficiale della blockchain, progetti e smart contract ufficiali verificati. Servono prove del campo, della rete e del momento in cui il dato è stato registrato.
2. **Aggregatori comparativi:** servizi come DefiLlama per alcune metriche di protocolli, provider on-chain per dati indicizzati, CoinGecko per identificatori e mercati; eventuali Token Terminal, Dune, explorer o analitiche etichette exchange SOLO se copertura, licenze, API, limiti e qualità lo consentono. **Nessun servizio o campo dichiarato disponibile senza prova diretta su richiesta.**
3. **Notizie token-specifiche:** governance e release ufficiali, exploit verificati, listing/delisting da exchange, unlock da fonte primaria; notizie terze come segnali da verificare e contestualizzare.
4. **Macro/geopolitica:** fonti ufficiali Fed/BCE/dati macro e fonti verificabili sugli eventi. Separare *pubblicazione → sorpresa rispetto alle attese → possibile trasmissione → dato di mercato*; non attribuire cause senza evidenza.

Non creare API generative a pagamento né abbonamenti impliciti. Distinguere l'accesso pubblico senza chiave dai servizi che richiedono API key, quota, costo o elaborazione centralizzata. La connessione in chat a plugin esterni non equivale a disponibilità di quelle stesse API nel programma Termux.

### 4. Contratto minimo della possibile integrazione

Una singola scheda di **contesto on-chain verificabile** deve restituire, per un asset pilota con identità certa:

`token_kraken`, `chain`, `asset_id_verificato`, `periodo_utc`, `metriche_osservate`, `eventi_verificati`, `fonti`, `timestamp`, `copertura`, `lacune`, `possibili_spiegazioni_contrarie`, `rilevanza_per_la_decisione`.

**Output del motore decisionale:** fatto on-chain → interpretazioni compatibili (anche opposte) → conseguenza possibile per lo scenario spot → grado di incertezza e condizione per riesaminare. Un dato mancante non è neutro; **nessun punteggio sintetico inventato**, nessuna soglia scelta solo perché un numero è alto.

**Pilotaggio verificabile:** iniziare con **un solo asset e una sola rete, identità controllata**; misurare copertura e tempestività, controllare casi di dato assente/etichetta ambigua, verificare la capacità di esprimere un controargomento; confrontare la **decisione GPT senza e con contesto on-chain**, congelando le valutazioni prima di mostrare l'informazione. Non scegliere l'asset o le soglie in base a un rialzo già noto; qualunque prova prospettica richiede GO dedicato.

**Criterio di utilità:** cambiamento motivato della valutazione, qualità dei rischi identificati, falsi allarmi e confronto degli esiti con il tempo. Un grafico più ricco o una correlazione retrospettiva non bastano.

### 5. Confini operativi

- **Adesso: SOLO DOCUMENTAZIONE DEL DISEGNO E DELLA PRIORITÀ.** Niente nuovo file Python, scraping, pipeline, API, raccolta dati in background o modifica dashboard.
- Dopo scelta umana espressa in un **mandato di implementazione limitato**, si effettua G0 sulle fonti concrete, poi G2 confinato su ramo GitHub con test e installazione volontaria tramite `kdd-aggiorna`.
- Conservare dossier tecnici e dati potenzialmente sensibili **solo sul Samsung**. Non riversare nel repository privato portafogli, indirizzi personali, wallet di terzi associati a persone o credenziali; utilizzare solo dati pubblici, leciti e pertinenti.
- Il navigatore non autorizza short, leva, futures, ordini automatici o accesso Kraken oltre la sola lettura.

**Prossimo gate:** scelta formale del **perimetro minimo on-chain** e verifica reale delle fonti, prima di programmare. Macro, geopolitica e news saranno contestualizzazioni dello stesso motore decisionale, senza far partire tre cantieri paralleli.
