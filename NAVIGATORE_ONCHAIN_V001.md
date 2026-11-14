# KDD — NAVIGATORE ON-CHAIN E CONTESTO FONDAMENTALE
## Disegno V001 — priorità on-chain

**Data:** 21 ottobre 2026.  
**Classe originaria al 21/10:** disegno G0, conservato per le famiglie di dati e le domande economiche. **Stato attuale 14/11:** una prima acquisizione reti/contract è già in `main` e installata sul Samsung ([PR #59](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/59), [#61](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/61)); l'osservatorio trasferimenti/detentori è in costruzione sulla sola [PR #64 Draft](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/64), issue #63, **non merged né installata**. Stato e lavoro effettivo sono esclusivamente nella [Roadmap](ROADMAP_KDD.md).  
**Origine:** scelta strategica dell'autore successiva alla chiusura della prova del delta spot: dare precedenza alle **informazioni on-chain**, integrandole con fondamentali, macroeconomia, geopolitica e notizie sul singolo token.  
**Ambito:** strumento informativo a supporto GPT e autore. Il disegno iniziale era Spot; la destinazione complessiva Spot/Futures e il divieto di ordini automatici sono stabiliti dal [Governo](GOVERNO_KDD.md). Questo testo non è una seconda Roadmap.

### 1. Ragione della priorità on-chain

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

**Identità tecnica prima dell'attribuzione al progetto:** mappare l'asset Kraken a chain, natura dell'asset (nativo/ERC-20/SPL/ecc.), contratto/mint/denom, eventuali bridge o wrapped e fonte. Un ticker da solo NON identifica un contratto. Se la corrispondenza progetto↔contratto è ambigua, segnare `IDENTITA_NON_VERIFICATA`: **osservare comunque i fatti pubblici del contratto identificato, dichiarandoli fatti di quel contratto e senza attribuirli automaticamente al progetto Kraken**. Distinguere evento osservato, attribuzione facoltativa dell'operatore e interpretazione economica. Nessuna verifica di identità personale è prerequisito dell'osservazione.

**Osservazione e inferenza sono separate:** in ogni metrica registrare rete, indirizzo/contratto identificato (solo se pubblico e necessario), fonte primaria o derivata, UTC e blocco/altezza, copertura temporale, unità, metodologia, etichettatura e livello di confidenza. Correlazione con prezzi ≠ causalità né segnale BUY/SELL.

### 3. Fonti da provare e integrare per capacità

**Priorità di verifica:**
1. **Fonte primaria:** explorer/RPC pubblico e documentazione ufficiale della blockchain, progetti e smart contract ufficiali verificati. Servono prove del campo, della rete e del momento in cui il dato è stato registrato.
2. **Aggregatori comparativi:** servizi come DefiLlama per alcune metriche di protocolli, provider on-chain per dati indicizzati, CoinGecko per identificatori e mercati; eventuali Token Terminal, Dune, explorer o analitiche etichette exchange SOLO se copertura, licenze, API, limiti e qualità lo consentono. **Nessun servizio o campo dichiarato disponibile senza prova diretta su richiesta.**
3. **Notizie token-specifiche:** governance e release ufficiali, exploit verificati, listing/delisting da exchange, unlock da fonte primaria; notizie terze come segnali da verificare e contestualizzare.
4. **Macro/geopolitica:** fonti ufficiali Fed/BCE/dati macro e fonti verificabili sugli eventi. Separare *pubblicazione → sorpresa rispetto alle attese → possibile trasmissione → dato di mercato*; non attribuire cause senza evidenza.

Non creare API generative a pagamento né abbonamenti impliciti. Distinguere l'accesso pubblico senza chiave dai servizi che richiedono API key, quota, costo o elaborazione centralizzata. La connessione in chat a plugin esterni non equivale a disponibilità di quelle stesse API nel programma Termux.

### 4. Contratto minimo della possibile integrazione

La scheda di **contesto on-chain** deve restituire, per ogni asset posseduto o candidato pertinente e secondo la copertura effettiva delle fonti:

`token_kraken`, `chain`, `asset_id_verificato`, `periodo_utc`, `metriche_osservate`, `eventi_verificati`, `fonti`, `timestamp`, `copertura`, `lacune`, `possibili_spiegazioni_contrarie`, `rilevanza_per_la_decisione`.

**Output del motore decisionale:** fatto on-chain → interpretazioni compatibili (anche opposte) → conseguenza possibile per lo scenario spot → grado di incertezza e condizione per riesaminare. Un dato mancante non è neutro; **nessun punteggio sintetico inventato**, nessuna soglia scelta solo perché un numero è alto.

**Prova di efficacia e generalizzazione:** un primo asset/rete serve a validare il produttore, **non** ad accettare l'osservatorio. Verificare fonti vere, copertura e tempestività, assenza di etichette e controargomenti; poi sostituire **tutti** i token del wallet sintetico con token diversi, su più reti, mostrando dati Kraken Spot disponibili, fatti on-chain e lacune puntuali. Un asset che esce, entra o rientra non richiede codice per ticker. Confrontare la valutazione GPT senza e con contesto on-chain, senza usare un rialzo noto per selezionare il test. Un adapter nuovo è legittimo se serve a un **protocollo** non ancora supportato, non a una moneta particolare.

**Criterio di utilità:** cambiamento motivato della valutazione, qualità dei rischi identificati, falsi allarmi e confronto degli esiti con il tempo. Un grafico più ricco o una correlazione retrospettiva non bastano.

### 5. Confini operativi vigenti

- **Costruzione G2 già autorizzata nella stessa PR #64**, non un altro studio o nuovo ramo: integrare fonti pubbliche realmente interrogabili per capacità/rete, riutilizzando `kdd_network_defi.py`, il catalogo dinamico e dossier → packet → bridge. Alla data del 14/11 gli indici Ethplorer/Ethereum, Binplorer/BNB e Jupiter/Solana hanno risposte pubbliche concrete; la presenza di una API non dimostra da sola l'integrazione nel codice né la copertura di tutti i token Kraken. Routescan Ethereum è stato provato esternamente e il relativo adattatore Ethereum/Avalanche è stato integrato successivamente nel ramo #64; il suo risultato sul codice e sulla CI corrente deve essere verificato prima del merge. Le alternative 403/429 vanno cercate concretamente e le coperture limitate dichiarate senza falsi zeri.
- **Niente whitelist di ticker del wallet attuale.** Il catalogo Kraken Spot e i dati del patrimonio/scanner guidano gli asset da analizzare; dati di trading CEX e dati di trasferimento blockchain restano semanticamente distinti. Una rete non supportata richiede una strategia tecnica proporzionata, senza dichiarare copertura sulla sola base di un record `NON_COPERTO`.
- **Nessuna automazione finanziaria:** Kraken API private read-only, nessun ordine, nessuna spesa/API a pagamento o installazione senza GO separato; conservare credenziali e dati riservati fuori da GitHub. Non usare l'ignoto proprietario di wallet pubblici come blocco alla rilevazione dei trasferimenti.

**Gate sostanziale:** prova multirete su wallet completamente sostituito, fonti reali, confronto fra rilevazioni e passaggio al giudizio GPT; in seguito GO di merge, GO separato di deploy e prova sul Samsung. La sola CI o il pilota su un asset non chiudono KDD-17.
