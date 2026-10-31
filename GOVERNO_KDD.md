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

**Requisito di destinazione dell'autore — 31/10/2026, predisposizione futura e NON GO operativo:** oltre alla componente prevalente strategica e alla componente tattica spot, il KDD dovrà poter supportare in una futura fase autorizzata una **quota minoritaria di capitale per trading futures, long e short**. Non è stata stabilita una percentuale, una leva, un contratto o una data di attivazione. Prima di programmare la funzione, il disegno dei dati e dell'interazione GPT deve mantenere distinti: patrimonio spot, capitale deliberatamente allocato ai futures, wallet/collaterale effettivamente impegnato, nozionale ed esposizione reale; contratto/mercato e direzione, margine cross/isolato, leva, maintenance margin, prezzi mark/index, funding, scadenza/settlement, commissioni, P&L realizzato/non realizzato e rischio di liquidazione. **Una proposta futures deve avere identità, validazione, provenienza, rischi e consenso autonomi rispetto a una proposta spot**; mai inserire un derivato dentro una posizione spot soltanto perché condivide il simbolo del token. Il protocollo GPT attuale, chiuso e solo patrimoniale/spot, resta invariato finché non sia autorizzata una futura versione esplicita e compatibile; la predisposizione è un vincolo per le prossime scelte architetturali, non un mandato G2 a implementare ora.

**Separazione del rischio e requisiti prima del futuro GO:** non assumere che l'account usi wallet separati, wallet unificato, cross o isolated; verificare configurazione reale e idoneità SEE. Un wallet unificato può esporre come collaterale anche asset strategici. KDD/GPT devono rendere visibile l'effettivo capitale a rischio e non attribuire all'etichetta "isolato" una garanzia di perdita massima assoluta. Le API restano solo lettura e nessun trasferimento, aumento dei permessi, ordine, posizione futures o leva è autorizzato. Fonti ufficiali da ricontrollare alla futura implementazione: https://support.kraken.com/it/articles/introduction-unified-wallet ; https://support.kraken.com/it/articles/multi-collateral-derivatives-contracts-eea ; https://support.kraken.com/articles/derivatives-eligibility-requirements-eea .

Questa regola preserva la preferenza iniziale per lo spot **senza limitare la capacità analitica** di KDD alle sole tendenze rialziste.

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

**Disposizione:** ANALISI SHORT AMMESSA; SHORT REALI NON AUTORIZZATI; REGIMI DI MERCATO TUTTI IN SCOPE; ROADMAP INVARIATA; NESSUN GO A NUOVI MODULI. La fase di adjudication del delta spot è chiusa per il campione A/B esaminato: uso LIMITATO. La successiva integrazione richiede scelta e perimetro espliciti dell'autore; nessuna abilitazione automatica.

Il presente documento cristallizza l'indirizzo e i limiti. Qualsiasi mutamento di diritti operativi esige un nuovo intervento esplicito dell'autore.
