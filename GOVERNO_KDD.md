# KDD — GOVERNO OPERATIVO DELLE DECISIONI

**Data di cristallizzazione:** 21 ottobre 2026.  
**Natura:** sintesi documentale dei vincoli confermati dall'autore per KDD; **non è un nuovo mandato autonomo**.

## 1. Autorità, integrità e precedenza

L'autore decide obiettivi, tolleranza al rischio, priorità della roadmap, operazioni e ampliamenti dei permessi. ChatGPT può proporre autonomamente analisi e scelte con motivazioni, ma **non esegue operazioni finanziarie senza autorizzazione esplicita**, non attiva strumenti negoziali e non modifica il conto.

Il presente documento governa l'interpretazione delle indicazioni presenti nel repository tecnico privato. È **subordinato al mandato KDD originale e ai vincoli di sicurezza già vigenti nel runtime Termux**; non pretende di sostituire il file operativo locale di subentro, non acquisito direttamente in questa ricognizione. In caso di contrasto, **STOP** e confronto con la fonte originale prima di adeguare il repository o il Samsung.

Distingui sempre: **idea strategica ≠ GO tecnico; test PASS ≠ prova di redditività; analisi short ≠ permesso short; commit GitHub ≠ deploy sul telefono; simulazione ≠ trade realmente eseguito**.

## 2. Perimetro di investimento e di azione

- **Obiettivo:** valorizzare una componente prevalente di investimento pluriennale a gestione attiva e una componente tattica spot, senza trasformare il mantenimento del portafoglio in un obbligo indiscriminato.
- **Regimi:** KDD deve interpretare mercati rialzisti, laterali, ribassisti e transizioni; nei ribassi riconoscere sia opportunità di gestione del rischio sia eventuali rimbalzi/rotazioni spot selettivi.
- **Azioni da confrontare:** ingresso long spot, uscita totale/parziale, rotazione, ribilanciamento, mantenimento, liquidità in USDC e attesa motivata. Nessuna scelta è obbligatoria: neppure «non intervenire» è la risposta predefinita.
- **Contesto obbligatorio quando pertinente:** singolo token, struttura di mercato, volumi, book, liquidità, spread, costi netti, orizzonte, macro (tassi/liquidità/dollaro) e geopolitica verificabili. Non imporre parametri numerici rigidi senza motivazione economica.
- **Limite finanziario:** lo spot long non genera profitto automaticamente durante una discesa; lo studio dei ribassi serve anche a riconoscere condizioni in cui alleggerire, ruotare o restare liquidi. Stablecoin e exchange conservano rischi propri.

## 3. Short, leva e futures

**Consentito per ragionare:** individuare ed esaminare pattern ribassisti, scenari short ipotetici, invalidazioni, costi, funding, rischi di liquidazione e differenze rispetto alle alternative spot. Eventuali simulazioni future richiedono il relativo posto in roadmap e uno specifico perimetro autorizzato.

**Non consentito adesso:** eseguire short, operazioni a margine, prestiti di titoli/token, futures, leva, trading automatico, modifiche ai permessi API per inviare ordini, trasferimenti o prelievi. Lo studio di uno scenario short **non costituisce autorizzazione a tradarlo**. Un eventuale ampliamento richiede decisione umana esplicita con gestione quantitativa del rischio e verifica della disponibilità/regolamentazione dello strumento.

Questa regola preserva la preferenza iniziale per lo spot **senza limitare la capacità analitica** di KDD alle sole tendenze rialziste.

## 4. Sequenza, responsabilità e divieto di cantieri paralleli

La roadmap `ROADMAP_KDD.md` registra la dipendenza principale già concordata:

**G0 delta spot → G2 esperimento delimitato (INJ, QNT, AVA, PUMP) → decisione motivata sul delta → una sola integrazione giustificata → motore GPT su opportunità reali.**

**Aggiornamento 21/10:** la decisione d'uso preliminare è **LIMITARE** il delta spot a osservazione secondaria, solo con coppia, finestra, copertura e freschezza verificabili; non autorizza segnali BUY/SELL, ranking privilegiati né previsioni. La **validazione scientifica G0/G2 rimane INCOMPLETA**: le fasi A/B congelate e gli esiti +1h/+4h/+24h sono dati locali privati non acquisiti direttamente nella ricognizione. Vedi [GIUDIZIO_DELTA_SPOT_G0_G2.md](GIUDIZIO_DELTA_SPOT_G0_G2.md). Nessuna nuova sperimentazione o implementazione nasce implicitamente da uno screenshot, da una notizia, dalla scoperta di un indicatore o da questo documento.

La capacità multitimeframe già costruita resta preservata come strumento disponibile. Correzioni urgenti motivate da difetti riproducibili possono essere considerate nel rispetto del perimetro già autorizzato, senza trasformarsi in espansioni funzionali incontrollate.

## 5. Procedura per una decisione proposta da GPT

Una proposta utile presenta, nei limiti della copertura dati verificata:

1. **Che cosa**: token/coppia/mercato Kraken, timeframe e condizioni attuali con orari delle fonti.
2. **Perché**: regime, liquidità, motivi pro e contro, alternative spot compreso USDC/attesa motivata.
3. **Come cambierebbe il portafoglio**: compatibilità con quota pluriennale e tattica, dimensione ipotetica, minimi e commissioni, prezzo realmente negoziabile e possibile slippage.
4. **Quando l'ipotesi decade**: condizione di invalidazione, scenari avversi e limite di rischio.
5. **Qual è lo stato della proposta**: osservazione, idea condizionata, piano presentato, decisione umana, ordine manuale dichiarato; **mai simulare in rendicontazione un ordine non eseguito**.

La mancata esecuzione è una decisione da spiegare quando pertinente, non una scorciatoia per evitare la valutazione del rischio. Non promettere rendimenti né confondere capacità di previsione con abilità tecnica del software.

## 6. Sicurezza dei dati, codice e installazione

Le API Kraken eventualmente usate per leggere saldo e cronologia sono **solo lettura**, con segreti custoditi localmente sul Samsung; nessuna chiave, estratto di conto, portafoglio, T0, dossier privato, log finanziario o backup viene copiato nel repository.

Il programma attivo sul Samsung e la sua documentazione operativa privata restano distinti dal repository GitHub. Solo sorgenti e documentazione **esplicitamente approvati e inseriti nella allowlist** possono essere versionati. Niente `git add -f`, nessun push indiscriminato, nessuna API generativa a pagamento.

Gli aggiornamenti di codice attraversano verifiche isolate, applicazione volontaria, backup/rollback e test successivi; per il server serve anche riavvio controllato e prova browser. L'aggiornamento **solo documentale** di questi file GitHub non autorizza e non richiede deploy del runtime, né riscrittura del README privato su Termux.

## 7. Registro della decisione 21/10/2026

**Acquisito dall'autore:** KDD deve leggere mercati ribassisti e lavorare opportunisticamente in **spot** anche durante le discese, quando esistano rimbalzi, rotazioni o strategie di gestione del rischio sensate. Gli short erano stati evitati in passato perché l'autore individuava più naturalmente movimenti rialzisti, **non per un divieto teorico universale**.

**Disposizione:** ANALISI SHORT AMMESSA; SHORT REALI NON AUTORIZZATI; REGIMI DI MERCATO TUTTI IN SCOPE; ROADMAP INVARIATA; NESSUN GO A NUOVI MODULI. La priorità esecutiva rimane la decisione sul delta spot a valle delle prove G0/G2.

Il presente documento cristallizza l'indirizzo e i limiti. Qualsiasi mutamento di diritti operativi esige un nuovo intervento esplicito dell'autore.
