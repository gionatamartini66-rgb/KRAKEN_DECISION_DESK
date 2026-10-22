# KDD — Punto 4 | Remediation G2R1 del dossier integrato

**Data:** 22 ottobre 2026  
**Classe:** G2, intervento isolato sui contratti del compositore SUI/EUR  
**Giudizio della costruttrice:** **PARTIAL — correzioni implementate e controllate su fixture; gate di pubblicazione reale NON superato.**  
**Base GitHub obbligatoria:** `gionatamartini66-rgb/KRAKEN_DECISION_DESK`, `1cff221dd1f47463a9349c8ef3567b3c110f74bd`; PR preesistente #12.

## 1. Integrità della baseline e provenienza

File originali `navigatore_dossier.py`, `test_navigatore_dossier.py`, `onchain_nav_core.py` acquisiti dalla Libreria e confrontati come Git blob **prima delle modifiche** con i valori pubblicati dal connettore GitHub al commit esatto:

| File | Git blob originale confrontato |
| --- | --- |
| `navigatore_dossier.py` | `877144618d662e8431938d8e9e0d173c85084b3e` |
| `test_navigatore_dossier.py` | `f65804d93e4f5311101f5b3e228b55b2d6ae6dfe` |
| `onchain_nav_core.py` | `9da6f827fbe9124ff5d450932e64029f6c9a0a01` |

Il nucleo on-chain e il produttore G2R2 **non sono stati modificati**. La suite esatta di 50 casi `test_onchain_nav.py` al commit remoto era consultabile sul connettore, ma **non trasferita né eseguita in questo runtime**. È stata eseguita soltanto la **versione storica della Libreria con 39 casi**, che non costituisce verifica equivalente dei 50 casi attuali. Il report Red Team è stato acquisito nella sua interezza; la suite avversariale originale non era disponibile come file autonomo in Libreria, per cui le 17 controprove sono state **ricostruite dalla descrizione riproducibile** e lanciate sulla baseline originale.

**Baseline eseguita in Python locale, senza rete:** 22/22 casi G2 PASS; 17/17 riproduzioni avversariali confermate (PASS = presenza originaria del difetto, non sicurezza). Le riproduzioni sono conservate fuori dal ramo GitHub in `baseline17_reproduced_original.py`, poiché codificano aspettative di comportamento sbagliato.

## 2. Modifiche D1–D8: problema / causa / rimedio / controprova / comportamento / residuo

### D1 — Disallineamento dello snapshot e falsa freschezza del book

- **Problema:** book e simulazione di un altro refresh accostati al prezzo corrente; età del ticker trasferita alla liquidità.
- **Causa originale:** `build()` ignorava `kraken_istantanea_utc`; `_liquidity()` attribuiva `observed_utc` del ticker all'intera sezione.
- **Correzione:** se i due istanti dichiarati differiscono, il dossier candidato viene segregato da multitimeframe e costi e il book escluso; in modalità `PUBLIC_REPORTED` è richiesto l'istante esplicito del dossier. `liquidita.observed_utc=None` finché il book non ha un proprio orario, e `ticker_acquired_utc` resta separato nell'evidenza.
- **Controprove:** `test_D1_mismatched_refresh_book_and_costs_quarantined`, `test_D1_unknown_book_time_never_fresh`, `test_D1_legitimate_matching_refresh`, `test_D1_public_missing_refresh_rejected`.
- **Osservato:** book e simulazioni incompatibili non confluiscono; un refresh uguale conserva i dati; nessun book sconosciuto è certificato fresco.
- **Residuo:** per le fixture storiche senza marker è preservata la prova sintetica, dichiaratamente **non attestata**. Il produttore non esporta ancora un timestamp autonomo del book.

### D2 — Marker 15m/1H, età individuale e lacune

- **Problema:** chiusura barra diversa dal marker e timeframe vecchio senza età propria.
- **Causa:** uso del solo `ultima_chiusura_utc` per 15m/1H e del massimo globale.
- **Correzione:** controllo di `chiusura_utc` o `apertura_ts_utc + durata`, rifiuto di discordanza, età e stato di freschezza per timeframe; se tutte le chiusure individuali esistono, conteggio delle lacune oppure `NON_DETERMINABILE`. Preservato il controllo 4H.
- **Controprove:** `test_D2_reject_marker_conflict`, `test_D2_age_per_period_and_no_missing_bar_claim`, `test_D2_valid_bar_markers`, `test_D2_real_gap_count_if_bar_times_complete`.
- **Osservato:** il 15m discordante viene scartato; il 1H vecchio è dichiarato storico; i casi coerenti sono conservati.
- **Residuo:** le barre storiche senza chiusura per barra restano esplicitamente marker non attestati nelle sole fixture; nell'ingresso pubblico sono scartate.

### D3 — Attestazioni on-chain e validazione del contratto

- **Problema:** `verification='VERIFICATO'` accettato su evento inventato, unità errata, fonte mancante o digest arbitrario.
- **Causa:** controllo nominale dei campi senza contratto per evento/asset/unità/provenienza e attestazione separata.
- **Correzione:** ammettere soltanto eventi Sui del pilota, quantità positive in SUI, source HTTPS non sintetica, checkpoint numerico, digest base58 strutturato (marker speciale confinato alla fixture), campi tipizzati e `reported_verification` distinto da `integration_verification`. Il compositore registra `producer_attestation=DICHIARAZIONE_NON_AUTENTICATA`; non dichiara verifica diretta blockchain.
- **Controprove:** `test_D3_fake_sale_discarded`, `test_D3_source_missing_rejected`, `test_D3_wrong_unit_rejected`, `test_D3_declared_vs_checked`, `test_D3_legitimate_programmed_circulation_not_transaction`.
- **Osservato:** eventi falsi non vengono pubblicati; il dato programmatico è conservato in categoria distinta.
- **Residuo:** un URL o un digest strutturalmente valido **non ne prova l'autenticità**. Serve ancora una catena producer→fonte tecnicamente attestabile, non inclusa in questa G2R1.

### D4 — Cronologia impossibile

- **Problema:** report acquisito prima dell'evento/osservazione.
- **Causa:** assente vincolo di ordinamento evento→acquisizione osservazione→acquisizione report→costruzione.
- **Correzione:** verifiche degli ordini e di `knowable_utc`; record temporali impossibili scartati e se presenti anomalie etichetta `TEMPO_INCOERENTE`.
- **Controprove:** `test_D4_knowable_before_event_rejected`, `test_D4_event_later_than_report_rejected`, `test_D4_valid_order_admitted`.
- **Osservato:** eventi impossibili esclusi, eventi coerenti conservati.
- **Residuo:** orari dichiarati dalla fonte non significano orari verificati indipendentemente.

### D5 — Metadati di audit economico del G2R2

- **Problema:** scomparivano oggetto StakedSui, principal MIST, famiglia filtro, attribuzione e rilevanza.
- **Causa:** allowlist piatta che ometteva i campi annidati.
- **Correzione:** mappa tipizzata `details` solo per oggetti StakedSui, quantità principal compatibile con SUI, attribuzione `NON_DIMOSTRATA`; rilevanza economica conservata come formula canonica legata alla classe evento, senza ricopiare testo arbitrario.
- **Controprove:** `test_D5_valid_public_metadata_retained`, `test_D5_inconsistent_principal_rejected`.
- **Osservato:** metadati pubblici validi presenti; principal incongruo escluso.
- **Residuo:** il testo originario libero di `economic_relevance` non è ripubblicato; è usata la dichiarazione canonica del contratto G2R2, da verificare caso per caso prima dell'uso di fonti reali.

### D6 — Confine pubblico/privato

- **Problema:** canary passavano da `fact`, `statuses`, `limits`, sequenze annidate e digests arbitrari.
- **Causa:** allowlist per nomi di chiavi senza schema rigoroso sui valori.
- **Correzione:** liste piatte di stringhe tipizzate, rifiuto di strutture annidate non valide, copie di `statuses` limitate a nomi **e valori** del contratto, convalida del digest, esclusione dalla pubblicazione di testi liberi di terzi e dei `fact` non attestati. Le sezioni mantengono la struttura ma riportano contenuto non attestato.
- **Controprove:** `test_D6_context_canary_not_leaked`, `test_D6_statuses_and_limits_not_leaked`, `test_D6_nested_canary_quarantined`, `test_D6_digest_free_text_not_exported`.
- **Osservato:** nessuna delle canary artificiali previste attraversa l'output.
- **Residuo cruciale:** non si può provare pubblica una stringa arbitraria controllata da un chiamante; l'unico confine sicuro per testi liberi è a monte, mediante produttore attestato e preparazione esclusivamente pubblica. Il compositore **non fornisce** questa attestazione. Non dichiarare sicurezza generale contro ogni contenuto riservato.

### D7 — Fixture ≠ fonte pubblica

- **Problema:** nove sezioni di fixture popolavano `missing_sections=[]` e il selettore `PUBLIC_REPORTED` mutava status senza prova.
- **Causa:** un solo elenco confondeva presenza del modello con prova di disponibilità delle fonti.
- **Correzione:** aggiunti `structurally_present_sections`, `structurally_missing_sections`, `public_sources_attested` (vuoto in questo adapter), `source_provenance_gate`; `missing_sections` descrive assenza di sorgenti pubbliche **attestate**, non mera presenza di campi. `PUBLIC_REPORTED` diventa `FONTE_NON_ATTESTATA` e non pubblica contesto sintetico `.invalid`.
- **Controprove:** `test_D7_fixture_not_public_source`, `test_D7_label_does_not_promote_fixture`.
- **Osservato:** 9 sezioni strutturali e zero fonti attestate convivono senza ambiguo conteggio di fonti reali.
- **Residuo:** serve un produttore reale con provenienza verificabile prima di dichiarare disponibile qualunque sorgente pubblica.

### D8 — `n_conversioni`

- **Problema:** valori negativi o `2.9` accettati e convertiti a `2`.
- **Causa:** `int(...)` senza validazione del tipo e della non negatività.
- **Correzione:** intero Python non negativo oppure stringa canonica di cifre; rifiuto di float, booleani, stringhe non canoniche, negativi.
- **Controprove:** `test_D8_negative_conversion_excluded`, `test_D8_fraction_conversion_excluded`, `test_D8_integer_zero_and_positive_remain`.
- **Osservato:** rigetto dei casi impossibili e conservazione di 0, 2, "3".
- **Residuo:** invariato il limite economico dei costi simulati; nessuna commissione privata è stata calcolata.

## 3. Test e risultati eseguiti qui

| Suite effettiva | Eseguiti | Esito |
| --- | ---: | --- |
| Baseline `test_navigatore_dossier` **prima della correzione** | 22 | **22 PASS** |
| 17 controprove G0 **ricostruite** sulla baseline originale | 17 | **17 PASS nel senso di difetti riprodotti** |
| `test_navigatore_dossier` **dopo correzione** | 22 | **22 PASS** (una aspettativa modificata intenzionalmente: fixture non equivale a 9 fonti pubbliche) |
| Nuovi casi `test_dossier_g2r1` | 27 | **27 PASS** |
| Insieme dei 22+27 | **49** | **49 PASS** |
| Suite storica Libreria `test_onchain_nav` | **39** | **39 PASS**, versione precedente al G2R2, **non sostitutiva** |
| Suite esatta on-chain G2R2 corrente | 50 previsti | **NON ESEGUITA** in questo runtime |
| `compileall` sui tre file candidati | 3 file | PASS |

Sono stati usati unicamente dati sintetici; nessuna rete, conto, API, ordine o Samsung. In fase di verifica finale il codice dell'on-chain G2R2 non è stato modificato, ma **assenza di modifica non equivale al PASS della suite attuale**.

## 4. Compatibilità, trade-off e limiti

- Contratto `KDD_NAVIGATORE_P4_V001` conservato, stessi 9 canali. Nuovi metadati espliciti. Una sola aspettativa originale modificata e tracciata: `missing_sections` include ora le nove sezioni di fixture perché non attestate come fonti pubbliche.
- `PUBLIC_REPORTED` non equivale a report autenticato: il compositore **non può** pubblicare liberamente i quattro canali contestuali sulla base di un flag del chiamante. Ciò è una riduzione deliberata dell'output finché manca il contratto fidato del produttore; non è una soluzione definitiva alla verifica delle fonti.
- Non è stato verificato comportamento con acquisizione pubblica live, Termux, interoperabilità integrata, sicurezza generale di input ostili, utilità per GPT o successo degli investimenti.
- L'esempio `ESEMPIO_SUI_EUR_SINTETICO.json` della G2 originale resta evidenza **storica del vecchio contratto**, non nuovo output generato dopo la remediation.
- Non è stato modificato `onchain_nav_core.py`, `onchain_nav_sui.py`, codice di ordini, finanze, dashboard, allowlist, main né governance.

## 5. Conclusione e STOP

**PARTIAL**: gli 8 gruppi di difetti hanno correzioni e verifiche riproducibili nel perimetro synthetic-only, ma mancano la suite G2R2 attuale eseguita in questo runtime e, soprattutto, una catena di provenienza/autenticazione dei produttori di dati pubblici. Non è autorizzato usare l'output come dossier pubblico live affidabile, né proseguire al Punto 5. La valutazione indipendente e la promozione sono di competenza della Supervisione apicale dopo nuovo Red Team. **STOP.**
