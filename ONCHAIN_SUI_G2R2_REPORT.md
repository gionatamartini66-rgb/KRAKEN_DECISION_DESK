# KDD — G2R2 | Remediation conclusiva D1–D3 del navigatore Sui

**Data:** 21 ottobre 2026 (UTC). **Classe:** G2 sperimentale isolata. **Verdetto:** PASS per il mandato circoscritto D1–D3, senza promozione operativa.

## 1. Provenienza e conservazione

Repository: `gionatamartini66-rgb/KRAKEN_DECISION_DESK`. Base esatta: `c4101e449d78a6c7bd511e4eeda4849e2e1bf19f` (G2R1, PR #10); ramo isolato `experiments/kdd-sui-onchain-g2r2-20261021`. Consultati per intero `onchain_nav_core.py`, `onchain_nav_sui.py`, `test_onchain_nav.py` e `ONCHAIN_SUI_G2R1_REPORT.md`. Conservato intatto il nucleo `onchain_nav_core.py`. Nessuna modifica ai file operativi, main, governance, dashboard, scanner, dossier, wallet o componenti Kraken.

## 2. Difetti originali riprodotti prima della correzione

Aggiunti nove test iniziali e avviati contro il codice G2R1 intatto: 11 fallimenti conteggiando i subtest, pertinenti a D1, D2, D3; i casi di deduplicazione identica e di eventi distinti già passavano. Il difetto D1 consentiva un `idDeleted='true'` o campo mancante anche quando l'oggetto era pubblicato. D2 conservava arbitrariamente 1 SUI anziché segnalare due record dello stesso evento/oggetto con principal rispettivamente 1 e 2 SUI (dentro la pagina, attraverso pagine o nei due filtri). D3 considerava interpretabile un intervallo con estremi assenti, tipi invalidi o ordine invertito.

## 3. Interventi

**D1 — forma GraphQL.** Ogni `objectChange` del batch è sottoposto a controllo esatto dei booleani `idCreated` e `idDeleted`, inclusi i record non pertinenti a StakedSui. Campi mancanti, stringhe, `None` o numeri non sono ammessi; `SourceProblem(RISPOSTA_INCOMPLETA)`, senza pubblicazione del batch malformato. Resta il rifiuto di `True/True` contraddittorio.

**D2 — quantità per identità.** Chiave `(digest, staked_sui_object, event)` nella raccolta globale, e `(staked_sui_object,event)` nel parser della singola transazione. Un duplicato con quantità identica viene conservato una sola volta; un duplicato con quantità discordante genera `RISPOSTA_INCOERENTE`. Attraverso i filtri la raccolta è differita fino alla fine e l'osservazione in conflitto viene eliminata, senza scegliere primo/ultimo record; anche le famiglie coinvolte vengono segnalate come incoerenti. Eventi realmente distinti sulla stessa identità oggetto sono preservati come eventi diversi. Nessuna operazione finanziaria è inferita.

**D3 — copertura disponibile.** `availableRange.first/last.sequenceNumber` deve essere presente e validabile come intero senza segno entro il contratto `uint`; rifiutati `bool`, `None`, negativi, valori non numerici, estremi invertiti. In tali casi `coverage=NON_DETERMINABILE` e `<family>_coverage=COPERTURA_INSUFFICIENTE`. Un oggetto individuale autentico conserva `verification=VERIFICATO` anche se la copertura generale non è dimostrabile. Estremi validi non provano l'assenza di lacune interne né la completezza del campione.

## 4. Test e regressioni

**Esecuzione indipendente in Python 3.11.2/Linux:** `python -m unittest -v test_onchain_nav` => **50/50 PASS**. I 39 test G2R1 restano per nome e obiettivo; **11 test avversariali G2R2 aggiunti** (2 D1 iniziali + un caso di modifica non pertinente; 5 D2, inclusi duplicati fra pagine e filtri; 2 D3). La fixture sintetica preesistente `test_identity_ambiguous` ometteva `idDeleted` ma rappresentava una risposta GraphQL coerente: aggiunto esplicitamente `idDeleted=False`; l'asserzione originale sulla diversità del tipo Move resta immutata. Sono stati conservati i test G2 e G2R1 e tutti i loro controlli, senza modifiche per nascondere fallimenti.

**Verifica pubblica reale addizionale:** un'unica esecuzione manuale di `run()` sulla Sui Mainnet GraphQL; **9 POST**, identità `VERIFICATA`, **6 oggetti osservati**, tre `STAKED_SUI_OGGETTO_CREATO` e tre `STAKED_SUI_OGGETTO_CONSUMATO`. Esempi: creazione di 3000 SUI nel digest `9YcGPibWLoCboGQtKknE2N5tfhFVHrFwv53o552dF1b6` al checkpoint `336592287`, consumo di 10 SUI nel digest `2k7NUmHJgkmgYHGCbfKLJP1rviHuhEfCqJskuuLEnCkP` al checkpoint `336581812`. Intervallo restituito `326227943..336596511`; timestamp acquisizione `2026-10-21T20:09:00.847895Z`. Lo stato del campione rimane `COPERTURA_INSUFFICIENTE` perché non è un censimento. I casi anomali D1–D3 sono verificati da fixture, non rivendicati come anomalie osservate sulla rete.

## 5. Sicurezza, limiti e seguito

Rimangono esecuzione manuale e sola lettura, adattatore Sui separato dal nucleo chain-neutral, nessun servizio permanente o archivio storico, nessun portafoglio né ordine e nessun segnale finanziario BUY/SELL. Il modello PTB non consente di attribuire causalmente al singolo comando un objectChange; `command_attribution=NON_DIMOSTRATA`. La presenza/consumo dell'oggetto StakedSui non equivale a compravendita, pressione di mercato o rendimento. Non è dimostrata alcuna utilità decisionale né compatibilità operativa spot/futures. Non è stato eseguito alcun deploy, test Android/Termux o accesso Kraken.

**Difetti D1–D3:** rimediati per il perimetro dimostrato. **Rischi ancora aperti:** schema futuro della fonte, paginazioni oltre il budget e comportamento del runtime Termux, non compresi in questa remediation. Il singolo collaudo Termux richiede GO separato, repository e commit esatti, esecuzione manuale limitata a 9 POST, nessuna persistenza e arresto dopo conservazione esiti. Nessuna promozione a main né runtime operativo.

**Verdetto: PASS limitato alla correzione verificata D1–D3.**
