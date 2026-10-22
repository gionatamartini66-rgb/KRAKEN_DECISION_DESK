# KDD — Punto 4 | G2R2 — remediation di integrità e fedeltà informativa

**Data:** 22 ottobre 2026. **Classe:** G2 limitata, laboratorio isolato. **Giudizio tecnico:** **PARTIAL**; miglioramenti riprodotti su fixture, autenticazione del produttore e quattro canali sostanziali non dimostrate. Gate pubblico reale **CHIUSO**. Nessun trade/API privata/deploy/merge.

## 1. Identità source-bound

Repository: `gionatamartini66-rgb/KRAKEN_DECISION_DESK`. Baseline G2R1 esatta `be7e17776c31fc711aaed75cfc35a1c5632a5b4c`, ramo `experiments/kdd-point4-dossier-g2r1-20261022`, PR #13. Sono stati letti integralmente i file richiesti e il rapporto avversariale `KDD_P4_G2R1_RED_TEAM_G0_SOL_2026-10-22.md` con la sonda dei 17 controlli. Sono stati confrontati i contratti G2R2 Sui a 50 casi e le interfacce canoniche `dossier_trade.py`, `decision_desk.py`, `costi_spot.py`. Le fonti governative e la roadmap restano vincolanti. Nessuna sorgente originale è stata modificata sul Samsung.

Prima delle modifiche: eseguiti localmente 22 test G2, 27 G2R1, 50 G2R2 **99/99 PASS**. Eseguite le 17 sonde indipendenti SOL: **8 PASS, 9 FAIL** sulla baseline, riproducendo i nuovi punti P05–P15. Test G2R2 da 50 casi: blob originali di `onchain_nav_core.py` / `onchain_nav_sui.py` / `test_onchain_nav.py` verificati rispettivamente `9da6f827fbe9124ff5d450932e64029f6c9a0a01`, `085d04dcb63acae227f83a97e917fa4a9793429a`, `aac7649689f61a374635208f7f0b4ef167debe69`.

## 2. Interventi limitati (solo compositore e suite di regressione)

| Asse | Modifica / prova | Limite non eliminato |
| --- | --- | --- |
| **P15 — tempo** | Prezzo cronologicamente successivo alla costruzione segnato `TEMPO_INCOERENTE` prima di generare i dipendenti. `liquidita` e `costi` non ricevono evidenze ammissibili. Prezzo strutturato disponibile soltanto come audit non utilizzabile. Prova positiva: book e costo legittimi ancora presenti a snapshot coerente. | Book senza timestamp proprio, perciò nessuna freschezza inventata. |
| **P05 — indici** | Calcolo liste `structurally_*` *dopo* le mutazioni degli stati; `section_availability` esplicita presenza strutturale dell'evidenza, validità, freschezza, provenienza e utilizzabilità per ciascuno dei nove canali. | Etichette legacy `structurally_present_sections` mantenute per compatibilità, ora corrispondono alle sezioni strutturalmente ammissibili; nessuna source attested. |
| **P11 — on-chain** | Oggetto StakedSui e `filter_family` coerente con tipo evento, confronti per `(digest,object,event)`. Doppioni identici deduplicati; conflitti di payload scartati e diagnosticati (`conflicting_fact_keys`, `RISPOSTA_INCOERENTE`). Non modificato produttore G2R2. | Autenticità del digest non provabile dal solo formato. Eventi senza `details` ammessi solo per vecchie fixture, non nel ramo `PUBLIC_REPORTED`. |
| **P06/P07 — audit** | Conservati `reported_coverage` con estremi e scope tipizzati, `staking_coverage`,`unstaking_coverage`, `reported_source_url` su allowlist esatta di endpoint canonici e marcatori di fonte dichiarata non autenticata; casi malformed esplicitati. | Una URL testuale non è un'attestazione. La copertura dichiarata non prova storia completa; nessun uso di nuove fonti. |
| **P10 — OHLCV** | Separati `bar_close_validation` e `ohlcv_integrity`; verifica numerica OHLCV delle barre effettivamente disponibili, rifiuto tuple contraddittorie e 4H non contigue; marcatura come non verificata delle vecchie barre ridotte al solo close, senza falsi `missing_bars=0` storici. | Le barre minimaliste non attestano OHLCV; il produttore `dossier_trade` controlla a monte gli OHLCV completi. |
| **P12 — costi** | Esclusione di righe con `errore` dichiarato; conservazione di `importo_eur` e pochi parametri numerici soltanto se già effettivamente presenti nell'input; flag se l'importo è perso. | `dossier_trade.collect` perde importo/fee/condizioni originarie, non ricostruibili dal compositore senza cambiare interfaccia a monte. Nessuna commissione inventata. |
| **P09 — confine** | Qualifiche `reported_verification` e `producer_attestation` mantenute. Forma degli URL vincolata ai produttori G2R2 attuali; niente copia libera dei testi upstream. | Produttore non autenticato; il canary base58 dalla forma plausibile non è distinguibile da digest genuino qui. **BLOCKER**. |
| **P08 — contesti** | Dimostrazione limitata di conservazione di un sottoinsieme numerico del produttore KDD esistente CoinGecko, con identificatore/URL/UTC tipizzati e `source_authentication=NON_DIMOSTRATA`, canary aggiuntivi scartati. Contratto separato per i testi dei quattro canali. | Fatti liberi di notizie token, macro e geopolitica restano NON pubblicati. Non si finge produttore attestato. **BLOCKER**. |

## 3. Test e controprove eseguiti

| Momento | Suite | Esito |
| --- | --- | --- |
| Prima del cambiamento | 22 nominali G2 + 27 G2R1 + 50 G2R2 correnti | **99/99 PASS** |
| Prima del cambiamento | Sonde SOL, 17 condizioni | **8/17 PASS; 9/17 non soddisfatte** |
| Dopo la remediation | 22 G2 + 27 G2R1 + 50 G2R2 + 21 G2R2 nuove | **120/120 PASS** |
| Dopo la remediation | Sonde SOL (una sola riga adattata per gestire `evidence=None` nel ramo correttamente quarantinato) | **15/17 PASS; due FAIL attesi P08 e P09**, blocchi di provenienza non mascherati |
| Dopo | `py_compile` e test di controllo di dati validi, malformed, canary e origine riportata | **PASS** per le prove incluse |

La sonda SOL è stata conservata **senza mutarne le aspettative**. Solo il campo diagnostico `book_depth_retained` è stato reso tollerante a `None`, perché un output correttamente quarantinato non contiene più un dizionario in `liquidita.evidence`. P08 richiede autentica prova di fonte pubblica testuale che non esiste nel presente contratto; P09 rifiuta in blocco un digest formalmente valido ma prodotto da chiamante arbitrario: soddisfarla richiederebbe autenticazione della fonte, non un filtro pseudo-privacy.

## 4. Misura della funzione utile conservata

**Conservato:** nove sezioni come struttura; Kraken SUI/EUR numerico, spread/volume stimato/minimi; 15m/1H/4H chiusi con status temporali autonomi; book Depth10 e costo non eseguito su refresh coerenti; costi validi e conversioni corrette; on-chain StakedSui fatto/programmato distinti, quantità, unità, checkpoint, digest riportato, oggetto, principal MIST, PTB non attribuita, copertura e URL fonte dichiarati; stato epistemico esplicito; una proiezione numerica CoinGecko circoscritta da `dossier_trade.token_fundamentals` quando presente.

**Escluso per necessità:** campi operativi privati, liste di testo arbitrario nel report, notizie/analisi macro/geopolitica di origine non attestata e fonti alterate. **Perso a monte:** importo e condizioni delle simulazioni nel produttore `dossier_trade.collect`, in contrasto con l'output originale più ricco di `costi_spot.py`.

**Non dimostrato:** fonte effettivamente pubblica del lotto, autenticazione dei produttori, fonte primaria delle notizie/testi, idoneità ad analisi macro o geopolitica, integrazione live, Termux, utilità decisionale GPT o risultati finanziari. `public_sources_attested=[]`, `missing_sections` rimane lista dei nove canali, in quanto nessuno è attestato tecnicamente.

## 5. Compatibilità e gate

I test 50 G2R2 *correnti* passano, senza toccare `onchain_nav_core.py`, `onchain_nav_sui.py` o la loro suite. Le 99 prove nominali G2R1/G2R2 restano verdi; le 21 nuove includono ingressi leciti mantenuti e avversari respinti. L'attestazione source-bound viene mantenuta distinta da un'autenticazione assente. Le prove sono eseguite su fixture e in locale, senza rete e senza account privati.

**Verdetto PARTIAL.** Le anomalie software P05/P06/P07/P10/P11/P12/P15 sono corrette nel perimetro testato; P08 e P09 hanno BLOCKER di origine non risolvibili con una modifica cosmetica al compositore. Ne segue **NO-GO al completamento del Punto 4**, alla pubblicazione di contenuti testuali reali, all'avvio del Punto 5, al merge e al deploy Android. Un prossimo lotto pubblico congelato richiede prima valutazione indipendente delle modifiche e verifica del trust boundary a monte, su GO umano distinto. Le condizioni contrattuali sono riportate in `KDD_P4_G2R2_CONTRATTO_PROVENIENZA_V001.md`.

**STOP.**
