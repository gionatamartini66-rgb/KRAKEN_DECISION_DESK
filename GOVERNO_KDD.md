# KDD — GOVERNO OPERATIVO DELLE DECISIONI

**Data di cristallizzazione:** 21 ottobre 2026.  
**Natura:** sintesi documentale dei vincoli confermati dall'autore per KDD; **non è un nuovo mandato autonomo**.

## 1. Autorità, integrità e precedenza

L'autore decide obiettivi, tolleranza al rischio, priorità della roadmap, operazioni e ampliamenti dei permessi. ChatGPT può proporre autonomamente analisi e scelte con motivazioni, ma **non esegue operazioni finanziarie senza autorizzazione esplicita**, non attiva strumenti negoziali e non modifica il conto.

Il presente documento governa l'interpretazione delle indicazioni presenti nel repository tecnico privato. È **subordinato al mandato KDD originale e ai vincoli di sicurezza già vigenti nel runtime Termux**; non pretende di sostituire il file operativo locale di subentro, non acquisito direttamente in questa ricognizione. In caso di contrasto, **STOP** e confronto con la fonte originale prima di adeguare il repository o il Samsung.

Distingui sempre: **idea strategica ≠ GO tecnico; test PASS ≠ prova di redditività; analisi short ≠ permesso short; commit GitHub ≠ deploy sul telefono; simulazione ≠ trade realmente eseguito**.

## 2. Perimetro di investimento e di azione

- **Destinazione:** gestione attiva dell'intero patrimonio: **componente strategica prevalente** e **componente operativa** su Spot e Futures long/short, con quota minoritaria destinabile ai derivati. Non sono imposte percentuali o durate fisse. Mantenere una posizione è una scelta da motivare, non un obbligo.
- **Regimi:** KDD deve interpretare mercati rialzisti, laterali, ribassisti e transizioni; nei ribassi riconoscere sia opportunità di gestione del rischio sia eventuali rimbalzi/rotazioni spot selettivi.
- **Azioni da confrontare:** mantenere, incrementare, alleggerire, vendere, ruotare, ribilanciare, operare Spot o Futures long/short quando pertinenti, restare liquidi o attendere con motivazione. Per ogni ipotesi distinguere strumento, rischi, alternative e disponibilità effettiva: nessuna risposta predefinita.
- **Contesto obbligatorio quando pertinente:** singolo token, struttura di mercato, volumi, book, liquidità, spread, costi netti, orizzonte, macro (tassi/liquidità/dollaro) e geopolitica verificabili. Non imporre parametri numerici rigidi senza motivazione economica.
- **Limite finanziario:** lo spot long non genera profitto automaticamente durante una discesa; lo studio dei ribassi serve anche a riconoscere condizioni in cui alleggerire, ruotare o restare liquidi. Stablecoin e exchange conservano rischi propri.

## 3. Short, leva e futures

**Spot e Futures sono strumenti previsti dal progetto**, con analisi sia long sia short. KDD e GPT valutano condizioni, scenari contrari, dimensionamento e rischio; **l'autore decide e compie personalmente qualsiasi operazione**. KDD e GPT non trasmettono ordini, non movimentano fondi e non aumentano autonomamente i permessi API. Le credenziali software attuali consentono soltanto lettura.

**Distinzione tecnica indispensabile:** posizioni Spot, contratti Futures, nozionale, margine, collaterale, funding, costi e rischio di liquidazione non sono intercambiabili. L'eventuale quota Futures va valutata senza esporre inconsapevolmente il patrimonio strategico, anche nel caso di wallet unificato o margine cross. Prima di usare dati o funzioni operative si verificano idoneità dell'account, condizioni Kraken e configurazione reale. Le future funzioni KDD/GPT dovranno essere introdotte con schema esplicito e controlli appropriati.


## 4. Sequenza, responsabilità e divieto di cantieri paralleli

La roadmap `ROADMAP_KDD.md` registra la dipendenza principale già concordata:

**G0 delta spot → G2 esperimento delimitato (INJ, QNT, AVA, PUMP) → decisione motivata sul delta → una sola integrazione giustificata → motore GPT su opportunità reali.**

**Aggiornamento 21/10 — prova A/B completata entro il campione:** decisione di uso del delta spot = **LIMITARE** a osservazione secondaria, soltanto con coppia, finestra, copertura e freschezza verificabili. Da output di Termux: fasi A/B integre, **4 token**, **12/12 orizzonti** a +1h/+4h/+24h presenti, **0/4 azioni cambiate**; delta della candela negativo e prezzi successivi positivi per tutti e quattro. **Nessuna prova di miglioramento decisionale, rendimento o validità predittiva generale**. Vedi [GIUDIZIO_DELTA_SPOT_G0_G2.md](GIUDIZIO_DELTA_SPOT_G0_G2.md). La fonte primaria locale resta sul Samsung; il rapporto conserva solo sintesi priva di snapshot privati. **Nessuna nuova sperimentazione o implementazione nasce implicitamente dal giudizio**, da uno screenshot, da una notizia o da un indicatore.

La capacità multitimeframe già costruita resta preservata come strumento disponibile. Correzioni urgenti motivate da difetti riproducibili possono essere considerate nel rispetto del perimetro già autorizzato, senza trasformarsi in espansioni funzionali incontrollate.

### 4A. Priorità informativa successiva — on-chain (21/10)

L'autore ha indicato che il prossimo navigatore deve mettere **soprattutto dati on-chain** al servizio delle decisioni, assieme a fondamentali, notizie specifiche del token, macro e geopolitica. I canali informativi compongono una **unica futura integrazione**, non quattro progetti autonomi. Design controllato: [NAVIGATORE_ONCHAIN_V001.md](NAVIGATORE_ONCHAIN_V001.md).

**Primo limite interpretativo:** transazioni on-chain ≠ operazioni Kraken; deposito a un exchange ≠ vendita; indirizzo ≠ persona; unlock ≠ cessione; crescita di indirizzi ≠ crescita di utenti; notizia ≠ causalità. Identità token, chain/contract, finestra temporale e fonti hanno precedenza su qualsiasi conclusione.

**Stato di governo: REQUISITO DOCUMENTATO; IMPLEMENTAZIONE NON AUTORIZZATA.** Iniziare solo con un mandato tecnico esplicito, verifiche G0 delle fonti e un pilota delimitato; nessuna chiave Kraken aggiuntiva, API commerciali implicite, sorveglianza personale o trading automatico.

## 5. Procedura per una decisione proposta da GPT

Una proposta utile presenta, nei limiti della copertura dati verificata:

1. **Che cosa**: token/coppia/mercato Kraken, timeframe e condizioni attuali con orari delle fonti.
2. **Perché**: regime, liquidità, motivi pro e contro, alternative spot compreso USDC/attesa motivata.
3. **Come cambierebbe il portafoglio**: effetto sulla componente strategica e su quella operativa, dimensione ipotetica, minimi e commissioni, prezzo negoziabile e possibile slippage.
4. **Quando l'ipotesi decade**: condizione di invalidazione, scenari avversi e limite di rischio.
5. **Qual è lo stato della proposta**: osservazione, idea condizionata, piano presentato, decisione umana, ordine manuale dichiarato; **mai simulare in rendicontazione un ordine non eseguito**.

La mancata esecuzione è una decisione da spiegare quando pertinente, non una scorciatoia per evitare la valutazione del rischio. Non promettere rendimenti né confondere capacità di previsione con abilità tecnica del software.

## 6. Sicurezza dei dati, codice e installazione

Le API Kraken eventualmente usate per leggere saldo e cronologia sono **solo lettura**, con segreti custoditi localmente sul Samsung; nessuna chiave, estratto di conto, portafoglio, T0, dossier privato, log finanziario o backup viene copiato nel repository.

Il programma attivo sul Samsung e la sua documentazione operativa privata restano distinti dal repository GitHub. Solo sorgenti e documentazione **esplicitamente approvati e inseriti nella allowlist** possono essere versionati. Niente `git add -f`, nessun push indiscriminato, nessuna API generativa a pagamento.

Gli aggiornamenti di codice attraversano verifiche isolate, applicazione volontaria, backup/rollback e test successivi; per il server serve anche riavvio controllato e prova browser. L'aggiornamento **solo documentale** di questi file GitHub non autorizza e non richiede deploy del runtime, né riscrittura del README privato su Termux.

## 7. Registro della decisione 21/10/2026

**Acquisito dall'autore:** KDD deve leggere mercati ribassisti e lavorare opportunisticamente in **spot** anche durante le discese, quando esistano rimbalzi, rotazioni o strategie di gestione del rischio sensate. Gli short erano stati evitati in passato perché l'autore individuava più naturalmente movimenti rialzisti, **non per un divieto teorico universale**.

**Nota archivistica:** la decisione del 21/10 descriveva il perimetro operativo di quella data. Non prevale sulla destinazione stabilita in §2–3; i riferimenti storici restano nel README e nella cronologia Git.

Il presente documento cristallizza l'indirizzo e i limiti. Qualsiasi mutamento di diritti operativi esige un nuovo intervento esplicito dell'autore.
