# KDD — Punto 4 della roadmap: prima integrazione informativa SUI/EUR

**Data:** 22 ottobre 2026. **Classe:** G2 sperimentale, ramo isolato. **Verdetto:** **PARTIAL**: un dossier unificato è costruito e testato con fixture, ma non è stata eseguita acquisizione live dell'intera catena informativa né una valutazione indipendente dell'utilità decisionale. **Nessun deploy, merge o modifica a main.**

## 1. Base canonica acquisita

Repository GitHub privato `gionatamartini66-rgb/KRAKEN_DECISION_DESK`, commit G2R2 verificato `c38e7a74e4ac25f538b1758f178264f7fbf76070` del ramo `experiments/kdd-sui-onchain-g2r2-20261021`. Sono stati letti `README.md`, `ROADMAP_KDD.md`, `GOVERNO_KDD.md`, `NAVIGATORE_ONCHAIN_V001.md`, `decision_desk.py`, `dossier_trade.py`, `mercati_spot.py`, `ricerca_setup.py`, `binance_reference.py`, i moduli on-chain `onchain_nav_core.py`, `onchain_nav_sui.py` e il rapporto `ONCHAIN_SUI_G2R2_REPORT.md`; inoltre controllata la allowlist `.gitignore` e la configurazione della distribuzione `scripts/kdd_aggiorna.py`. Nessun accesso al mandato privato custodito sul Samsung.

**Fonti ufficiali consultate per lo schema, non come campioni live del prototipo:** documentazione Sui GraphQL per endpoint Mainnet, paginazione, `effects.objectChanges`, `StakedSui` e relativi limiti; documentazione Kraken Spot per prezzi e candele, in aggiunta al contratto dei sorgenti KDD. Consultazione della documentazione ≠ interrogazione delle API di mercato o blockchain. Riferimenti: `https://www.docs.sui.io/develop/accessing-data/graphql/query-with-graphql`, `https://www.docs.sui.io/develop/accessing-data/graphql/graphql-rpc`, `https://docs.kraken.com/api/docs/rest-api/get-ohlc-data`.

## 2. Architettura effettiva

È stato aggiunto **un solo adattatore puro** `navigatore_dossier.py` con funzione `build(...)` e un contratto JSON. La funzione riceve come input espliciti, senza acquisire autonomamente altri dati:

- `snapshot`: solo i campi pubblici `markets[SUI]` e `rilevazione_utc` prodotti da `decision_desk.py`/`mercati_spot.py`, per la coppia esplicita `SUI/EUR`;
- `existing_dossier`: sole sezioni pubbliche di `dossier_trade.py` riferite al candidato SUI/EUR (indicatori pubblici, book elaborato, costi simulati, eventuali OHLC chiuse);
- `onchain_report`: output informativo del `run()` G2R2, già prodotto altrove, **senza chiamare `run()` durante la composizione**; le osservazioni sono ammesse solo con asset, chain, ID, tipo epistemico, esiti e metadati tracciabili; conserva la distinzione tra fatto e dato programmato;
- `public_context`: record espliciti di fondamentali, notizie token-specifiche, macro e geopolitica, con fonte, orario, copertura e interpretazione alternativa; il modulo non trasforma RSS o titoli isolati in un giudizio macro;
- `acquired_utc`: orario dichiarato della composizione; `provenance`: obbligatoriamente `FIXTURE` oppure `PUBLIC_REPORTED` (nessuna modalità fittizia `LIVE_VERIFIED`).

Il nucleo generale G2R2 è **riutilizzato** tramite `from onchain_nav_core import utc, KINDS`. Copia locale acquisita dalla Libreria con blob Git corrispondente a `9da6f827fbe9124ff5d450932e64029f6c9a0a01`, come nel ramo G2R2. Il nuovo modulo **non modifica** `onchain_nav_core`, `onchain_nav_sui`, le funzioni originali di KDD, il cruscotto o l'aggiornatore. I dati on-chain rimangono separati dal contesto `KRAKEN_SPOT`: futuri mercati non ne mutano l'identità.

## 3. Contratto verso GPT

Il dossier `KDD_NAVIGATORE_P4_V001` contiene `asset`, `market_pair`, `market_type`, `asset_identity`, `built_utc`, `input_provenance`, nove sezioni, allineamento temporale, lista esplicita dei canali mancanti, interpretazioni compatibili e alternative, proibizioni e stato decisionale non predittivo. Ogni sezione conserva: `status`, `source`, `observed_utc`, `coverage`, `evidence`, `compatible`, `alternative`, `limits`. Non vi sono segnali BUY/SELL, punteggi di trading, accesso a conti o suggerimenti di sizing.

L'allineamento temporale separa tempo **dell'evento on-chain**, tempo **dell'acquisizione on-chain**, momento di **acquisizione del prezzo**, chiusure delle barre OHLC, data di un fatto macro/notizia e momento di composizione. Espone differenze e convenzioni per canale; la regola descrittiva dei 60 minuti confronta due istanti di acquisizione, **non** è una soglia di trading e non dimostra contemporaneità causale. Un canale successivo alla composizione viene segnalato `TEMPO_INCOERENTE`. Candele OHLC 4H non vengono attribuite al dossier se la chiusura non coincide con l'apertura dell'ultima candela più quattro ore.

## 4. Riutilizzo dei componenti e lacune

- **Mercato:** `decision_desk.market_pairs_and_ticker` conserva prezzo, spread, volume EUR stimato per singola coppia; non equivalgono a trade eseguibili né fee reali.
- **Liquidità:** `analisi_v02.book_metrics` tramite `dossier_trade` può fornire profondità dei primi 10 livelli; in mancanza rimane solo spread/volume ticker, esplicitando i limiti.
- **Multitimeframe:** `dossier_trade.summarize_candles`, `documenta_4h` e caratteristiche già prodotte; non modifica la produzione, non raccoglie candele. Un timeframe non presente resta esplicitamente assente.
- **Costi:** importa esclusivamente simulazioni già presenti per SUI/EUR, mai fee conto, dimensionamenti o saldi.
- **Fondamentali:** `dossier_trade.COINGECKO_IDS` contiene ICNT e KAS, **non** mappatura SUI sufficiente a un'acquisizione automatica; quindi SUI richiede un dato con identificatore e fonte verificati, senza inferire da ticker.
- **Notizie/macro/geopolitica:** nessuna classificazione fondata sul solo titolo RSS; mancano feed token-specifici validati e una valutazione contestuale scientificamente verificata. I record eventuali sono segnati come **riportati**, non autenticati dal compositore.
- **On-chain:** G2R2 preservato, staking/unstaking con attribuzione del comando Move non dimostrata e campione non censuario; non calcola flussi netti né previsioni.
- **Binance:** `binance_reference.py` offre contesto pubblico separato sulle coppie spot e non dimostra liquidità di esecuzione Kraken. Il modulo non fonde automaticamente metriche Binance con SUI/EUR.

**Lacune materiali:** verifica delle fonti live dentro il dossier, allineamento a un ciclo reale di aggiornamento (no deploy), eventuali costi effettivi personali, serie multitimeframe complete, fondamentale SUI verificato, notizie pertinenti, contesto macro/geopolitico con interpretazione fondata, comparabilità economica fra orizzonti, red-team scientifico su interpretazioni.

## 5. Scheda prodotta e natura delle evidenze

`ESEMPIO_SUI_EUR_SINTETICO.json`: nove sezioni presenti, identità nominale SUI / Sui Mainnet / `0x2::sui::SUI` / Kraken SUI/EUR; prezzo **fittizio** 1,25 EUR, spread **fittizio** 0,2%, volume 24h **fittizio** 250.000 EUR, importi e transazione on-chain **fittizi**. Gli orari delle fixture sono storici (`2026-10-21`) e volutamente dichiarati come prova; non rappresentano il mercato reale del 22 ottobre. Le fonti `example.invalid` identificano esclusivamente contenuti sintetici. Ogni sezione ha `status=FIXTURE_SINTETICA` e il dossier ha `input_provenance=FIXTURE`, `decision_utility=NON_DIMOSTRATA`.

Nel caso senza fonti, il compositore produce nove sezioni `NON_DISPONIBILE` e non inventa zero o valori sostitutivi. Nel caso senza on-chain, gli altri canali presenti restano leggibili, con `temporal_alignment.status=NON_DETERMINABILE`. Gli elementi privati artificialmente inseriti nei dati di test non compaiono nell'output grazie ad allowlist stretta.

**Acquisizione reale in questa G2:** lettura integrale dei sorgenti sul repository e della documentazione ufficiale, **nessuna chiamata live** a Kraken, Binance, CoinGecko o Sui per popolare il dossier. Il report originale G2R2 del 21/10 riporta un collaudo live separato di 9 POST e sei oggetti StakedSui; questo G2 non lo ha riprodotto e non usa quei numeri nella fixture. Nessuna capacità reale di acquisizione spot/on-chain congiunta è dunque dimostrata da questa prova.

## 6. Test

Eseguiti localmente, in ambiente Linux/Python 3.13.5:

`python -m unittest -v test_navigatore_dossier` → **22 test, 22 PASS, 0 FAIL, 0 ERROR**.

Copertura verificata: contratto e nove canali, assenza totale/parziale, identità pair SUI/EUR e chain/asset ID, timestamp, confronto fra acquisizioni, timestamp fonte successivo al dossier, validità OHLC 4H, NaN nei prezzi, dati fonte malformati, fonte macro non contestualizzata, verifica identità delle notizie/fondamentali, esclusione campi privati, divieto dei segnali finanziari, provenienza obbligatoria, test di determinismo, gestione report on-chain privo di checkpoint. Compilazione Python (`compileall`) PASS. Non è stata eseguita l'intera suite operativa KDD né la suite 50/50 G2R2 su questo runtime: l'integrazione usa il nucleo comune senza modificarlo.

## 7. Governance e gate

Nuovo ramo sperimentale dal commit esatto `c38e7a74e4ac25f538b1758f178264f7fbf76070` (G2R2); aggiunti `navigatore_dossier.py`, `test_navigatore_dossier.py`, `ESEMPIO_SUI_EUR_SINTETICO.json`, questo rapporto e la minima allowlist `.gitignore`. Nessun commit su main né altre modifiche. Il `.gitignore` aggiornato permette **esclusivamente la conservazione dei quattro nuovi file sul ramo**: `scripts/kdd_aggiorna.PY_FILES` **non viene ampliato**. Non eseguire `kdd-aggiorna --apply`, non distribuire sul Samsung né aggiornare il cruscotto.

**Condizioni per una valutazione indipendente successiva:** verificare le mappe campi e l'esclusione di contenuti privati; eseguire con dati **pubblici autentici e congelati** raccolti nello stesso periodo, controllare coppia, timestamps e finestre OHLC; recuperare separatamente on-chain G2R2 con tracciabilità di query, range, digest e limiti; verificare che la disponibilità di una nuova fonte non produca automaticamente una previsione; far giudicare a revisori indipendenti la pertinenza dei fatti senza usare GPT autore come revisore; confrontare eventuali decisioni A/B solo con mandato separato. **Non promuovere il software solo perché la fixture PASS.**

**Verdetto conclusivo: PARTIAL (prototipo integrato su fixture verificato; dati live e valore decisionale non dimostrati).** Nessuna API privata, ordine, future, leva, database storico, servizio residente, file privato Samsung, deploy o merge.