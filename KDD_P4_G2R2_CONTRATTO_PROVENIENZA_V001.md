# KDD — Punto 4 — Contratto di ingresso pubblico: confine ancora aperto
Data: 22 ottobre 2026. Classe: G2R2, documentazione sperimentale. **NON è un nuovo sistema di autenticazione**.

## Requisito di origine prima di pubblicare testi liberi (P08/P09)

Un record `source='https://...'`, un `provenance='PUBLIC_REPORTED'`, un digest base58, `statuses.identity='VERIFICATA'`, un identificatore token o l'esito dichiarato `verification='VERIFICATO'` **non attestano il produttore**. Anche un file JSON ben formato può provenire da input manipolato oppure contenere testo privato. Gli schemi di tipo possono verificare forma e coerenza, non rendere pubblico un testo arbitrario.

Il produttore a monte, in una fase distinta e autorizzata, dovrà garantire una catena di origine verificabile dalla sua acquisizione alla consegna dell'oggetto: identità effettiva del componente e della versione, origine dei byte, metodo di acquisizione, URL originario, data/ora e finestra, hash e legame immutabile al payload pubblicabile, ispezione delle trasformazioni e separazione fisica dai saldi/portafogli privati. **Non si prescrive qui una particolare tecnologia, firma, servizio o token di autenticazione.** La decisione di collocazione del trust boundary compete alla Supervisione.

### Contratto d'ingresso proposto, NON soddisfatto

Per ciascuno di `fondamentali`, `notizie_token`, `macroeconomia`, `geopolitica`, servono: `asset_id` oppure ambito macro dichiarato, `kind` epistemico, `source_original_url`, `producer_id`, `producer_version`, `producer_evidence` attestabile, `acquired_utc`, `observed_utc` o pubblicazione, `coverage`, `fact` strettamente correlato alla fonte pubblica, `alternatives`, limiti ed eventuale politica di riproduzione/licenza. L'attestazione deve provenire **fuori** dall'oggetto arbitrario in ingresso. I quattro testi restano esclusi dal dossier condivisibile fino a una prova tecnica di provenienza pubblica.

### Produttori già presenti: ricognizione e dimostrazione delimitata

- `dossier_trade.token_fundamentals` interroga per SUI la API pubblica CoinGecko e restituisce identificatore, URL, prezzo, capitalizzazione, supply e `aggiornato_utc`. Nel nuovo compositore, quando il dossier appartiene allo stesso refresh e URL/id/timestamp/valori rispettano il contratto atteso, il sottoinsieme **numerico tipizzato** può attraversare in `coingecko_reported_numbers`, con `source_authentication=NON_DIMOSTRATA`, senza pubblicare campi aggiuntivi controllati dal chiamante. È una **dimostrazione di trasporto**, NON acquisizione reale e NON attestazione della fonte.
- `dossier_trade.global_context` restituisce aggregati CoinGecko; utili come dati dichiarati, ma la G2R2 non li promuove a valutazioni macro/geopolitiche né li distribuisce in nuovi canali.
- `decision_desk.fetch_feed` ricava titoli RSS; già il KDD esplicita che un titolo non è contestualizzazione verificata di cause o conseguenze. Non soddisfa `notizie_token` o `macroeconomia` attestate.
- Non è stato individuato nel perimetro autorizzato un produttore di testi pubblici attestabili di notizie token, analisi macro o geopolitica adatto al confine condivisibile. **BLOCKER P08**: contenuti fattuali liberi di questi canali non vengono esportati.

### Frontiera P09

Un digest di 32–64 caratteri base58 può contenere un canary artificiale e restare indistinguibile da un digest autentico senza riscontro sulla blockchain o produttore autenticato. Il compositore conserva la stringa per audit sotto `reported_*` o `transaction`, ma segnala che la fonte e il produttore **non sono autenticati**. Il test avversariale P09 resta deliberatamente non soddisfatto se inteso come capacità di distinguere un digest inventato, e **non** viene risolto con filtri lessicali.

## Gate non superato

Il codice G2R2 non acquisisce dati live, non verifica autenticità originaria, non abilita `public_sources_attested`, non abilita il Punto 5 né autorizza il merge/deploy. Per superare P08 serve in seguito una prova autonoma della preparazione a monte con lotto pubblico congelato e confronto payload per payload, su mandato distinto.
