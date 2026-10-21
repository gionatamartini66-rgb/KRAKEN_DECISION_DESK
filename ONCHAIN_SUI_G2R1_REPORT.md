# KDD — G2R1, remediation isolata navigatore on-chain generale / pilota Sui Mainnet

**Data:** 21 ottobre 2026 (UTC). **Classe:** G2R1, sperimentazione isolata. **Verdetto:** **PARTIAL**. **Nessun deploy Android/Termux, nessuna operazione Kraken, nessun ordine o modifica del portafoglio.**

## 1. Provenienza e conservazione

Repository privato: `gionatamartini66-rgb/KRAKEN_DECISION_DESK`. Base verificata via GitHub: commit originale G2 `34c33b427d78f6e55908032bbf016792a7bf1d5f`, ramo `experiments/kdd-sui-onchain-g2-20261021`, PR originale **#9**, non unita. Letti integralmente a quel commit: `onchain_nav_core.py`, `onchain_nav_sui.py`, `test_onchain_nav.py`, `ONCHAIN_SUI_G2_REPORT.md`. Verificati inoltre i documenti di governo (`README.md`, `ROADMAP_KDD.md`, `GOVERNO_KDD.md`, `NAVIGATORE_ONCHAIN_V001.md`, `GIUDIZIO_DELTA_SPOT_G0_G2.md`) e il funzionamento della allowlist di `scripts/kdd_aggiorna.py`, senza modificarli. Il rapporto G0 avversariale è stato riferito dall'autore nei suoi rilievi R1–R5 e da sintesi precedenti; **il suo testo originale integrale non era disponibile fra i file del repository o nella Libreria consultata**: le conclusioni R1–R5 sono state ricontrollate direttamente sul codice G2.

Ramo remediation derivato *esattamente* da `34c33b4…`: `experiments/kdd-sui-onchain-g2r1-20261021`. Nessuna modifica al ramo G2 o a `main`. File modificati: `onchain_nav_core.py`, `onchain_nav_sui.py`, `test_onchain_nav.py`; presente questo rapporto nuovo. Non modificati: `.gitignore`, sistemi `kdd-aggiorna`, dashboard, dossier finanziari e governance.

## 2. Difetti riprodotti e rimedi circoscritti

**R1 — UTC e conoscibilità.** `utc()` G2 confrontava un timestamp potenzialmente frazionario con `datetime.now(...).replace(microsecond=0)`: un orario di pochi millisecondi prima dell'istante corrente veniva erroneamente scartato. Il confronto ora mantiene i microsecondi. La richiesta registra *inizio*, acquisizione delle singole risposte dopo che sono state lette e completamento; il fatto conserva `event_utc` letto da Sui. `knowable_utc` resta `None` e `knowability_status=NON_DETERMINABILE`: non viene inventato un istante di disponibilità pubblica né confuso il timestamp blockchain con la conoscibilità. L'oggetto `Observation` respinge event time > acquisizione e conoscibilità provata incongrua.

**R2 — paginazione objectChanges.** La query `LOOKUP` ora seleziona `objectChanges(first:50, after:$after) { pageInfo { hasNextPage endCursor } nodes {...} }`; l'acquisizione pagina fino al termine nel budget complessivo di **9 POST** e massimo **4 pagine per transazione**. Controlla la continuità di digest, status, timestamp e checkpoint, l'esistenza del cursore e i cicli. Se una pagina manca, l'API restituisce una forma inattesa o il budget finisce, assegna `RISPOSTA_INCOMPLETA` e **non pubblica il sottoinsieme come transazione completa**. Il comportamento è verificato con fixture; la query non è ancora validata contro lo schema live.

**R3 — PTB multicomando.** La semplice inclusione di una Move function in un filtro GraphQL non permette di collegare un determinato `objectChange` a quel comando in una PTB. Il parser pubblica soltanto `STAKED_SUI_OGGETTO_CREATO` o `STAKED_SUI_OGGETTO_CONSUMATO` (tipo, principal e oggetto verificati), con `command_attribution=NON_DIMOSTRATA`. Questo è un **declassamento epistemico intenzionale**, non prova di staking/unstaking attribuito. Se il medesimo digest/oggetto appare in entrambi i filtri, l'osservazione viene conservata una sola volta. Non attribuisce transfer, intenzioni o compravendite.

**R4 — assenze e copertura.** `NESSUN_EVENTO_NEL_CAMPIONE` descrive solo la lista filtrata vuota. Lo stato separato `<famiglia>_coverage=COPERTURA_INSUFFICIENTE` segnala pagine precedenti e/o copertura non determinata; `RISPOSTA_INCOMPLETA` indica payload/pagine mancanti, `EVENTO_NON_VERIFICABILE` assenza di riscontro sull'oggetto, `FONTE_NON_DISPONIBILE` la disfunzione di rete. Nessuna assenza viene sommata come quantità zero o dimostrazione di assenza generale di attività.

**R5 — forma e integrità.** I campi che dovrebbero essere oggetti o liste sono verificati prima di accedervi. I dati parziali GraphQL e i JSON inattesi vengono classificati come `SourceProblem` negli ingressi coperti. `Observation(frozen=True)` protegge ora anche le strutture annidate di `details` e le tuple interpretative: la serializzazione di `to_decision_context()` produce una copia indipendente, modificabile dal chiamante senza alterare l'osservazione.

## 3. Contratto informativo invariato

Resta la separazione di **fatto on-chain**, **programma ufficiale di circolazione**, **interpretazioni consentite**, **interpretazioni proibite** e **possibile rilevanza economica**, con `decision_status=CONTESTO_INFORMATIVO_NON_PREDITTIVO`. `asset_id=0x2::sui::SUI`, MIST convertiti con `Decimal` a rapporto `1e9`, checkpoint/digest/UTC conservati. Il nucleo è indipendente dalla blockchain e dal mercato spot/futures. Non implementati adattatori di altre chain, trading futures, prezzi o portafogli; nessuna soglia o segnale BUY/SELL.

## 4. Test ed evidenza eseguita

**Ambiente:** Linux Python 3.13, sola libreria standard. `python -m unittest -v test_onchain_nav` eseguito localmente: **39/39 PASS** (22 casi G2 mantenuti per nome e scopo, con aspettative adeguate soltanto dove R1–R4 modificano intenzionalmente la semantica; 17 nuovi casi avversariali). Durata circa 0,004 s. Tipi: **39 sintetici/unitari e integrativi simulati**, **0 test integrazione GraphQL reale riusciti**. Verificati millisecondi (orologio deterministico), incoerenza temporale, conoscibilità ignota, pagina successiva contenente l'oggetto, cursori assenti/ripetuti, metadati diversi, budget, dati malformati, doppia attribuzione tra filtri, risultati vuoti, payload parziali, immutabilità, assenza di segnale finanziario, identità, importi, fallimenti e programmi mensili distinti.

**Tentativo reale:** una POST diretta alla query `IDENTITY` su `https://graphql.mainnet.sui.io/graphql`: `SourceProblem(FONTE_NON_DISPONIBILE, URLError)` nell'ambiente Linux (DNS/rete non raggiungibile). Non è stato ottenuto HTTP 200 da Python, né verificato il digest G0 precedente. Il test reale **non è passato**; nessun dato autentico derivante dall'esecuzione del nuovo adattatore. Fonte API ufficiale consultata per struttura `ObjectChangeConnection.pageInfo`: https://docs.sui.io/references/sui-api/sui-graphql/beta/reference/types/objects/object-change-connection; semantica PTB: https://www.docs.sui.io/develop/transactions/ptbs/prog-txn-blocks. **La documentazione non sostituisce il collaudo dello schema del servizio attuale.**

**Staking:** oggetto `StakedSui` creato riconosciuto soltanto su fixture; attribuzione a comando staking **NON DIMOSTRATA**; evento reale non verificato.

**Unstaking:** oggetto `StakedSui` consumato riconosciuto soltanto su fixture; attribuzione a comando unstaking **NON DIMOSTRATA**; evento reale non verificato; `principal` non equivale a SUI netti liquidi o venduti.

## 5. Rischi aperti e condizioni prima della promozione

1. **Query reale e schema:** endpoint GraphQL, nomi dei campi, paginazione, formato di `status`, `type.repr`, flag `idCreated/idDeleted`, filtri per funzione e cronologia effettiva devono essere controllati mediante POST reali con dati autentici; validare su almeno un evento oggettivo di creazione e uno di consumo.
2. **Attribuzione per comando:** nessun riscontro del comando Move ha autorità sull'oggetto; per classificare propriamente staking e unstaking servono nuove evidenze che colleghino causazione PTB e objectChanges. Finché mancano, il downgrade resta permanente.
3. **Copertura:** filtro limitato a 3 transazioni recenti per famiglia e 9 POST totali; non ricostruisce flussi aggregati, rendimento o supply circolante effettiva. Un limite di paginazione può rendere la singola transazione non verificabile.
4. **Compatibilità ambiente:** Python stdlib e nessuna dipendenza extra; esecuzione su Linux verificata, **Termux/Android non collaudati**.
5. **Audit indipendente:** riprodurre 39 test dal commit, verificare la conservazione degli originari, eseguire query pubbliche reali, attaccare classificazioni errate di eventi e controllare scenari in cui JSON valido contiene dati semanticamente errati. Solo dopo eventuale nuovo GO valutare deploy via percorso esistente e un distinto confronto A/B.

**Limiti finanziari:** il prototipo rende più prudente la rappresentazione dell'evidenza. Non dimostra utilità decisionale, profitti, predizioni, direzione spot o riutilizzo futures operativo. **Nessuna promozione automatica.**

## 6. Condizione di arresto

La revisione si ferma con l'esito **PARTIAL**: remediation locale verificata; GraphQL non collaudato e semantica causale non dimostrata. Nessun merge, deploy su Samsung, modifica a `main`, nuova chiave, nuovo repository, operazione finanziaria o API generativa a pagamento.
