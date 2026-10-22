# KDD — ROADMAP CANONICA (22 OTTOBRE 2026)

**Versione consolidata per sostituzione, non diario incrementale.** Fonte di governo: [GOVERNO_KDD.md](GOVERNO_KDD.md) e mandato operativo originario sul Samsung, non alterati da questa revisione. Stato tecnico source-bound da GitHub; stato del telefono verificato solo fino alle evidenze disponibili del 21/10. **Nessuna autorizzazione implicita a codice, trasferimenti dati, trade, merge o deploy.**

## 1. Destinazione

**Kraken Decision Desk** supporta GPT nel confronto di scelte patrimoniali e tattiche spot per un patrimonio prevalentemente pluriennale ma **a gestione attiva**. Deve riconoscere regimi rialzisti, laterali, ribassisti e transizioni, senza presumere un mercato sempre in rialzo e senza imporre quote fisse. Confrontare mantenere, incrementare, alleggerire, uscire, ruotare, liquidità in USDC e attesa motivata, sotto rischio di token, mercato, liquidità e controparte.

Kraken Spot è la sede di riferimento per prezzi negoziabili e ordini **eseguiti soltanto dall'autore**. Binance Spot pubblico integra il confronto di mercato e non rappresenta liquidità eseguibile su Kraken. Contesto on-chain, tokenomics, news, macro e geopolitica sono rilevanti solo se fonte, identità, tempo e limiti sono espliciti. **Analisi short ammessa; operazioni short/futures/leva/margin non autorizzate.** Nessun ordine automatico o API generativa a pagamento.

## 2. Sequenza di sviluppo e gate — stato attuale

| Passaggio | Esito accertato | Prossimo gate |
| --- | --- | --- |
| **1 — G0 delta spot** | Ricognizione condotta. Il delta misura la microstruttura della coppia/finestra campionata, non direzione futura. | Chiuso per la domanda storica. |
| **2 — G2 casi spot** | Prove delimitate su INJ, QNT, AVA, PUMP; nessuna redditività dimostrata. | Evidenze circoscritte ai casi trattati. |
| **3 — Adjudication delta A/B** | **CHIUSO: USO LIMITATO**; QNT/SUI/PUMP/ONDO, 4 casi, 12/12 orizzonti +1h/+4h/+24h, 0/4 cambi di azione; hash A/B verificati in Termux. | Non promuovere a segnale o ranking; non ripetere il medesimo campione per cambiare il verdetto. |
| **4 — Navigatore integrato on-chain-first SUI/EUR** | **G2 prototipo, G2R1 e G2R2 implementati in rami isolati; gate live NO-GO.** Correzioni tecniche sostanziali, P08/P09 aperti. | G0 Red Team indipendente sulla PR #14, poi decisione di Supervisione su provenienza upstream e possibilità di collaudo con lotto pubblico congelato. |
| **5 — Motore decisionale GPT su casi reali** | **NON AUTORIZZATO COME NUOVO SVILUPPO.** Analisi patrimoniali G0 in chat sempre possibili con dati correttamente datati. | Dopo superamento/giudizio esplicito sui gate precedenti e GO umano distinto. |

La distinzione fra le fasi non impedisce di **ragionare ora sul portafoglio**: impedisce soltanto di attribuire a moduli non convalidati una capacità già operativa o di iniziare sviluppo non autorizzato.

### Dettaglio Punto 4 e lavori in corso

- **PR #12 / G2**: `1cff221dd1f47463a9349c8ef3567b3c110f74bd`, 22 nominali PASS, primo Red Team FAIL sul gate non fidato.
- **PR #13 / G2R1**: `be7e17776c31fc711aaed75cfc35a1c5632a5b4c`, 49 nominali PASS; Sol 99/99 combinati con 50 correnti on-chain, nuove criticità di integrità/fedeltà.
- **PR #14 / G2R2**: `d474bd6c614b6cbd7a06ba69bc4311ffa34a0f32`; la Costruttrice dichiara 121/121 PASS e miglioramento da 8/17 a 15/17 controprove indipendenti. **Resta da verificare autonomamente da Sol; PR in bozza e non unita.**
- **Blocker P08**: i contenuti pubblici di fondamentali/notizie/macro/geopolitica non hanno un trasporto testuale affidabile completo.
- **Blocker P09**: identità del produttore e origine dei payload non autenticati. HTTPS, etichette e digest ben formati non bastano.
- **Controllo source-bound supplementare**: `dossier_trade.COINGECKO_IDS` include ICNT e KAS, non SUI, mentre il prototipo G2R2 mostra un caso numerico CoinGecko SUI. Sol deve distinguere fixture ammissibile da produttore canonico realmente disponibile.
- **Regola:** nessun nuovo ciclo correttivo, fonte live, Punto 5, merge o deploy sulla base dei soli test dichiarati. Le correzioni del Punto 4 restano un cantiere unico, senza proliferazione di moduli.

## 3. Nuova priorità infrastrutturale parallela — patrimonio informativo su Drive

**Scelta di architettura dell'autore, 22/10:** consentire a ChatGPT di consultare autonomamente **tutto il patrimonio informativo utile di KDD** tramite Google Drive privato, senza che l'autore debba esportare foto, ZIP e file ogni volta.

**Modello prescelto:** **Samsung/Termux = origine ed esecuzione; Google Drive = archivio privato sincronizzato e leggibile da GPT; GitHub = codice/versionamento; ChatGPT = analisi e supervisione.** Il runtime non migra su Drive. Il ponte deve essere **solo in uscita** dal Samsung, senza sincronizzazione inversa né permessi di scrittura sul conto.

**Stato effettivo:** connettore Google Drive disponibile e letto in chat; creata la cartella privata `KDD_CANALE_PRIVATO_CHATGPT`, non condivisa e ancora **vuota**. **Nessun job, esportatore, sync del telefono o nuova foto del wallet è stato installato.** Desktop Commander risulta collegato ma le letture remote sono bloccate dalla quota mensile.

### Sequenza del ponte, autonoma dalle sperimentazioni del Punto 4

| Gate | Lavoro | Stato / condizione |
| --- | --- | --- |
| **D0 — Ricognizione G0** | Distinguere la cartella condivisa `/storage/emulated/0/Kraken` dalla directory effettiva `~/kraken-decision-desk/KRAKEN_DECISION_DESK_V001`, inventariare file, campi privati, segreti e aggiornamenti reali, senza copiarli. | **DA ESEGUIRE** con accesso appropriato al dispositivo o fonte privata autorizzata. |
| **D1 — Contratto dei dati e sicurezza** | Definire area *leggibile da GPT* (saldi, prezzi, dossier, storici, decisioni, documenti pertinenti) e area *backup cifrato non leggibile da GPT*. Prevedere minimi permessi, esclusioni esplicite, hash, metadati di acquisizione, versione, marcatori stale, errori e separazione saldi/mercato. | **DA APPROVARE**; la governance attuale mantiene dati operativi sul Samsung. Non si caricano segreti in chiaro. |
| **D2 — Pilota G2 delimitato** | Sincronizzare in sola uscita un **lotto minimo sanificato** e verificare lettura da ChatGPT, permessi, corrispondenza contenuti, timestamp, fallimenti, ripetizioni, conflitti e comportamento offline. | **NESSUN GO G2 ANCORA CONFERITO**; serve mandato dedicato prima di intervenire sul Samsung. |
| **D3 — Archivio informativo completo** | Solo dopo prova positiva, estendere progressivamente a dossier, storico, piani e documentazione; eventuale backup cifrato separato. Evitare copie ridondanti del repository GitHub. | **NON INIZIATO**. |
| **D4 — Regime di esercizio** | Lettura dell'ultima fotografia effettivamente disponibile, monitoraggio di età/versione/errori e recovery, senza pretendere aggiornamento live se il Samsung è offline. | **NON INIZIATO**. |

**Vincolo di priorità:** questo ponte è **infrastruttura di accesso ai dati**, non il Punto 5 e non una scorciatoia per aggirare P08/P09 del dossier pubblico. I report privati del wallet, pur leggibili da ChatGPT con permesso, **non sono dati pubblici**. Non caricare file privati su GitHub. Prima di trasferire quelli reali, armonizzare con specifico GO [GOVERNO_KDD.md](GOVERNO_KDD.md) e il mandato locale, che oggi li assegnano solo al Samsung.

## 4. Primo caso patrimoniale e misura dell'utilità

**Caso iniziale:** riesaminare se e come costituire una liquidità operativa indicativa di circa **150 EUR equivalenti in USDC**, soltanto se economicamente giustificato. La vecchia ipotesi di vendere ETH/SUI è **scaduta e non costituisce ordine**. La fotografia storica del 21/10 è una base di confronto, non il saldo corrente del 22/10. Prima di una decisione di esecuzione servono saldo aggiornato, quotazioni, spread/book, minimi, costi e conferma umana.

Ogni proposta GPT dovrà mostrare: scenario e regime; fonte e ora; ragioni favorevoli e contrarie; effetti sul patrimonio strategico e tattico; alternative praticabili (inclusi non intervenire e liquidità); condizioni di ingresso/uscita/invalidazione; rischio, fee e netto; stato dell'azione (**osservazione / proposta / decisione umana / esecuzione manuale dichiarata / verifica successiva**). Conservare le opportunità non eseguite senza trattarle come PnL reale. **Successo** significa migliori decisioni auditabili e minore lavoro manuale, non più indicatori o test nominali.

## 5. Regole sempre vincolanti

- Non dedurre causalità da news, trasferimenti on-chain, unlock, etichette exchange o delta spot; distinguere fatto, scenario, ipotesi, assenza dati.
- Non inventare probabilità, fee, slippage, cost basis, esecuzioni o timestamp.
- Dati privati e chiavi restano separati: l'eventuale accesso GPT ai dati del patrimonio richiede sicurezza, minimizzazione e mandato. Un Google Drive privato **non** è backup end-to-end cifrato per definizione.
- Nessuna operazione trading automatica o permessi API di esecuzione; short e futures solo analisi astratta.
- GitHub→Termux soltanto tramite [AGGIORNAMENTI_TERMUX.md](AGGIORNAMENTI_TERMUX.md): `kdd-aggiorna --check`, backup, `--apply` con GO, test, rollback e riavvio/prova visiva quando necessario. Una PR aperta o un commit non sono installazione.
- La Supervisione mantiene il governo dell'architettura completa; Sol valuta indipendentemente il Punto 4. **GO tecnico per un ramo ≠ GO a main ≠ GO al deploy ≠ GO finanziario**.

**Prossima decisione della Supervisione:** ricevere il nuovo rapporto G0 di Sol per il Punto 4 e aprire separatamente una ricognizione G0 del ponte Drive, senza attendere altre funzionalità di mercato.
