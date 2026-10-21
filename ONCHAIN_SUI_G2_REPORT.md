# KDD — G2 primo navigatore on-chain generale, pilota SUI

**Data:** 21 ottobre 2026. **Esito:** PARTIAL (software locale collaudato su fixture sintetiche, GraphQL vivo non raggiungibile da questo ambiente). **Stato:** ramo sperimentale, nessuna integrazione operativa.

## Fonti del progetto e limite di autorità

Repository privato `gionatamartini66-rgb/KRAKEN_DECISION_DESK`, commit di partenza `ed52ed666040c3faa20cd73bae15c77e54151df1`, controllato tramite connessione GitHub. Letti README, ROADMAP, GOVERNO, NAVIGATORE_ONCHAIN_V001, GIUDIZIO_DELTA_SPOT_G0_G2; inoltre `decision_desk.py`, `dossier_trade.py`, `mercati_spot.py`, `kraken_readonly.py`, `studio_delta.py`, `test_decision_desk.py`, `scripts/kdd_aggiorna.py`, `.gitignore`, `AGGIORNAMENTI_TERMUX.md` e `IMPORTAZIONE_SICURA.md`. Il mandato originale conservato sul Samsung non è stato acquisito; precede le fonti derivate, per cui il lavoro non modifica in alcun modo il runtime.

La raccolta KDD esistente usa snapshot Kraken pubblici, documenta fonti e freschezza, crea dossier con `dossier_trade.collect()`, e conserva sul dispositivo dati di conto e rapporti privati. `scripts/kdd_aggiorna.py` distribuisce soltanto una allowlist di sorgenti Python e vendor da **main** con preflight locale; una prova isolata non costituisce compatibilità Android. Il navigatore non interagisce con questi moduli né con il conto Kraken.

## Moduli, contratto dati e interfaccia

- `onchain_nav_core.py`: `Observation` indipendente dalla blockchain, immutabile, tipi epistemici distinti (`FATTO_OSSERVATO`, `DATO_PROGRAMMATO`, `DATO_DERIVATO`, `INTERPRETAZIONE`, `IPOTESI_ECONOMICA`, `NON_DISPONIBILE`). Comprende chain/asset ID, transaction/block opzionali, timestamp UTC dell'evento, acquisizione e conoscibilità, periodo, fonte, copertura, verifica, limiti e interpretazioni compatibili o proibite. `to_decision_context()` offre solo evidenza e cautele senza segnali trading. Può rappresentare asset non Sui e riferimenti non numerici.
- `onchain_nav_sui.py`: adattatore Sui Mainnet GraphQL e separato parser del programma mensile di circolazione SUI. Il filtro per funzione precede un lookup puntuale del digest; il parser convalida oggetto `0x3::staking_pool::StakedSui` creato (stake) o consumato (unstake), `principal` in MIST, riuscita, checkpoint, UTC, digest e deduplica; restituisce osservazioni di **principal**, non importi netti trasferiti o vendite.
- CLI manuale: `python onchain_nav_sui.py --live --circulation`, massimo **nove POST GraphQL** (una identità/copertura, due filtri, fino a sei lookup di dettaglio), facoltativamente una GET per circolazione. `python ...` senza `--live` non esegue rete. Niente scritture su disco, polling, server, credenziali o modifiche al sistema operativo.

Query GraphQL (codice versione esatta in costanti `IDENTITY`, `FILTER`, `LOOKUP`):

1. `chainIdentifier` e `serviceConfig.availableRange(type:"Query",field:"transactions",filters:["function"])` per rete e copertura del filtro.
2. `transactions(last:3,filter:{function:$function}) {pageInfo {hasPreviousPage startCursor} nodes {digest}}` per `0x3::sui_system::request_add_stake` e `0x3::sui_system::request_withdraw_stake`.
3. `transaction(digest:$digest) {digest effects {status timestamp checkpoint {sequenceNumber} objectChanges { nodes {address idCreated idDeleted inputState {asMoveObject {contents {type {repr} json}}} outputState {...}}}}}`.

Riferimenti ufficiali: https://www.docs.sui.io/develop/accessing-data/graphql/query-with-graphql ; https://www.docs.sui.io/operators/exchange-integration ; https://www.docs.sui.io/references/framework/sui_sui_system/sui_system ; https://www.sui.io/token-schedule ; https://sui-circulation.suiexplorer.com/api/current_month_sui_circulation . Sui GraphQL `chainIdentifier` può essere digest genesis Base58 di 32 byte, accettato solo se il suo prefisso hex decodificato corrisponde a Mainnet `35834a8a`. L'identificatore native coin è `0x2::sui::SUI`, `1 SUI = 1e9 MIST`.

## Collaudo e riscontri effettivi

**Test offline locali:** `python -m unittest -v test_onchain_nav`: **22/22 PASS** (eseguiti in ambiente Linux/Python durante questa implementazione, con dati sintetici; non su Termux). Si verificano conversione, identità errata/corretta, normalizzazione rete Base58, staking, unstaking come principal consumato, tx fallita, assenze, ambiguità token, duplicati, timestamp, GraphQL `errors` con HTTP 200, 429, timeout, copertura insufficiente, separazione del programma di circolazione, blocco su chain errata e contratto comune multichain. La transazione usata nelle fixture utilizza soltanto il digest **riportato** nella G0 precedente, NON costituisce una sua verifica live.

**Rete reale:** tentativo HTTPS POST verso `https://graphql.mainnet.sui.io/graphql` dall'ambiente di lavoro → `URLError: [Errno -3] Temporary failure in name resolution`. Non ottenuti in questa esecuzione HTTP 200, timestamp on-chain, eventi nuovi, verifica del digest `9jpePvm98WscMhGj4S9YGucWrcCT4RtuLrCdVsPkc6am` o copertura Mainnet reale. Gli stati reali di **staking e unstaking sono entrambi NON VERIFICATI da questa esecuzione**. La disponibilità della fonte descritta dalla precedente ricercatrice rimane un'evidenza esterna da convalidare.

**Fonte complementare verificata sul web nella fase di ricerca:** l'endpoint REST JSON di circolazione pubblica per ottobre 2026 riporta `{ "month":10, "year":2026, "circulatingSupplyValue":4118270447.6403894 }`; è un **dato programmato a fine mese**, NON la quantità realmente circolante il 21 ottobre. La lettura proviene da accesso web della fonte pubblica durante questo mandato, non dall'esecuzione del codice `read_circulation()`; anche questa funzione è stata testata solo tramite parsing simulato. Le revisioni della fonte non possono essere dedotte da un solo snapshot.

**Non dimostrati:** campionamento end-to-end della fonte GraphQL, schema vivo di `effects.objectChanges`, correttezza dei campi `idCreated/idDeleted` nel runtime attuale, individuazione regolare degli unstake, copertura storica effettiva, comparabilità statistica di staking/unstaking, utilità finanziaria e compatibilità Samsung/Termux. I filtri richiamano due sole entry functions; le forme `non_entry`, `mul_coin` e fungible stake NON sono coperte. Una PTB contenente più chiamate Move può rendere ambigua l'attribuzione di un oggetto, anche quando la funzione filtrata compare nella transazione. Il parser privilegia **nessuna osservazione** quando non è presente un `StakedSui` verificato; non calcola flussi netti.

## Criticità e gate successivi

1. **Revisione tecnica indipendente** dello schema GraphQL reale, delle query eseguite e dei marker `idCreated`/`idDeleted` prima di attribuire capacità di acquisizione live: tentare il digest della precedente G0 e nuovi esempi di staking e unstaking con due query separate, conservando checkpoint/time e limiti temporali.
2. Verificare che la copertura `availableRange` sia effettivamente disponibile per i filtri per funzione; assenza di risultati non equivale a zero eventi su tutta la rete. Pagina al massimo 3 transazioni per famiglia, campione parziale e non rappresentativo. Il budget massimo è 9 POST, non polling.
3. Il numero `principal` per uno unstake è il valore del precedente `StakedSui` consumato, **non** la quantità liquida ricevuta comprensiva di rewards/gas, né una vendita.
4. Per altre chain basta un adattatore che produca `Observation`; **nessun** adattatore alternativo è stato implementato, e non è dimostrata una reale portabilità multichain.
5. Prima di eventuale distribuzione autorizzata serviranno modifica espressa della allowlist `.gitignore` canonica per ammettere i moduli, modifica della lista `PY_FILES` di `scripts/kdd_aggiorna.py`, controlli su staged clone, suite pre/post, approvazione umana, installazione e prova esplicita sul Samsung. **Nessuna di queste operazioni è stata eseguita.** L'allowlist del ramo sperimentale riguarda esclusivamente la conservazione in Git, non il deploy.
6. Successivo A/B sulle valutazioni finanziarie indipendente, con raccomandazioni precongelate e controllo di validità; nessuna promozione automatica del prototipo.

**Dichiarazione:** nessun componente installato sul Samsung operativo; nessun ordine Kraken, futures, leverage, short, modifica portafoglio, nuovo repository o nuovo servizio residente. Nessuna API generativa o commerciale a pagamento.