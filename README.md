# KRAKEN DECISION DESK (KDD)

**Stato consolidato: 22 ottobre 2026.** Questo README sostituisce la precedente cronaca incrementale con uno stato unitario. È la **documentazione tecnica pubblicabile del repository privato GitHub**, non il README operativo completo né la fotografia patrimoniale custoditi sul Samsung. La fonte primaria dello stato installato rimane il dispositivo; un commit GitHub non prova un deploy.

## 1. Missione e autorità

**Obiettivo sovrano:** assistere l'autore nella gestione consapevole di un patrimonio crypto prevalentemente pluriennale **a gestione attiva**, e nella ricerca di opportunità tattiche **spot** in mercati rialzisti, laterali, ribassisti e di transizione. GPT confronta mantenimento, incremento, alleggerimento, uscita, rotazione, liquidità (anche USDC) e attesa motivata, valutando rischi, costi, alternative e invalidazioni. Nessun token è obbligatoriamente da mantenere; nessuna operazione è obbligatoria.

L'autore prende ogni decisione ed esegue personalmente ogni eventuale ordine. **Nessun trading automatico, short, futures, margin o leva autorizzato.** Gli short sono ammessi esclusivamente come oggetto di analisi ipotetica. Nessuna API generativa a pagamento. La liquidità in stablecoin espone a rischi di emittente, depeg ed exchange. Non confondere PASS software, esiti controfattuali o grafici con prova di redditività.

**Kraken Spot** è il riferimento di portafoglio ed eventuale esecuzione manuale. **Binance Spot pubblico** è soltanto una fonte comparativa; i suoi volumi e book non sono liquidità negoziabile su Kraken. I saldi Kraken sono acquisibili esclusivamente tramite API private **a sola lettura**, con credenziali locali al Samsung; nessuna facoltà di ordine/prelievo.

## 2. Architettura effettiva e stato delle evidenze

| Livello | Funzione | Stato accertabile al 22/10 |
| --- | --- | --- |
| **Samsung / Termux** | Programma KDD operativo, cruscotto locale `127.0.0.1:8765`, saldi Kraken read-only, prezzi, scanner, multitimeframe, dossier, piani e verifiche. | Esistente e precedentemente collaudato. Il 22/10 l'autore ha mostrato la riuscita di un refresh Termux: **saldo Kraken read-only alle 15:56:32 UTC (10 posizioni)** e report mercato successivo; non è ancora sincronizzato il saldo privato su Drive. Lo stato del codice installato non è identificato con quello di GitHub odierno. |
| **GitHub `main`** | Codice sorgente selezionato, documentazione di governo, test, aggiornamento controllato. | Base del lavoro canonico; prima di questa revisione, HEAD verificato `ed52ed666040c3faa20cd73bae15c77e54151df1`. Nessuno dei prototipi successivi del Punto 4 è stato unito. |
| **GitHub sperimentale** | Ricerca confinata, red team, test riproducibili. | Punto 4: G2 PR #12, remediation G2R1 PR #13, G2R2 PR #14; **tutte separate da `main`**. |
| **Google Drive** | Futuro archivio consultabile da GPT dell'intero patrimonio *informativo* KDD, esclusi segreti in chiaro. | Connettore ChatGPT verificato. Cartella privata `KDD_CANALE_PRIVATO_CHATGPT` non condivisa. **Canale Samsung→FolderSync→Drive→ChatGPT collaudato con due file NON patrimoniali**, `prova_kdd.txt` e `mercato_kdd.json`. Solo sincronizzazioni manuali; job automatici disattivati. |
| **ChatGPT / Supervisione** | Lettura e ragionamento su dati con fonte/orario; coordinamento dei mandati indipendenti. | Può leggere GitHub e Drive collegati. **Non può attualmente ottenere automaticamente il saldo corrente dal Samsung.** |

Il codice e la documentazione di GitHub **non** equivalgono allo stato installato sul telefono. Il README operativo locale è più completo e distinto; non è stato sovrascritto da questa revisione.

### Funzioni già disponibili nel KDD operativo

Il programma `decision_desk.py` include il comando `aggiorna`: tenta di aggiornare il saldo attraverso `kraken_readonly.py` se la chiave locale esiste, quindi raccoglie dati Kraken pubblici e aggiorna le evidenze locali. **Se la lettura privata fallisce, conserva il vecchio saldo datato e segnala il problema; non lo rende automaticamente corrente.** Il cruscotto e le routine raccolgono mercati Kraken, Binance pubblico, dossier e verifiche. Sono state sviluppate e verificate sul Samsung viste SUI/EUR 15m/1H/4H/1D e pannello multitimeframe; ogni timeframe richiede candele chiuse, orari e controlli di integrità.

I dossier operativi, `portafoglio.json`, `ultima_rilevazione.json`, `ultimo_report.json`, verifiche e storici appartengono alla **zona privata**. La fotografia nell'archivio già consegnato alla Supervisione documenta saldi al **21 ottobre 2026**. Il log Termux dell'autore del **22 ottobre ore 15:56:32 UTC** documenta 10 quantità spot aggiornate via BalanceEx, uguali alle precedenti, ma questo saldo **non è ancora accessibile via Drive**. Nessuna decisione operativa va ricavata dalle quotazioni precedenti senza dati negoziabili aggiornati.

### Delta spot: decisione conclusa nel campione

La prova A/B del 19–21 ottobre (QNT, SUI, PUMP, ONDO) ha prodotto **4 casi, 12/12 orizzonti osservati, 0/4 cambi d'azione**, hash A/B coerenti da verifica Termux. **Verdetto: USO LIMITATO** come descrizione di microstruttura con coppia, finestra, copertura e freschezza esplicite; non come segnale o ranking predittivo. Non è stata dimostrata redditività. Rapporto: [GIUDIZIO_DELTA_SPOT_G0_G2.md](GIUDIZIO_DELTA_SPOT_G0_G2.md).

## 3. Punto 4 — navigatore informativo integrato, pilota SUI/EUR

**Scopo:** un dossier a nove canali: mercato, multitimeframe, liquidità, costi, fondamentali, on-chain, notizie token, macroeconomia, geopolitica. I canali non sono nove fonti automaticamente disponibili o autentiche. L'adattatore non deve trasformare un unlock in una vendita, uno staking in un acquisto, un deposito exchange in un ordine, un identificatore blockchain in una persona, o un titolo RSS in analisi economica verificata.

**Progressione verificabile:**

| Fase | Commit / artefatto | Giudizio e confine |
| --- | --- | --- |
| G2 iniziale | `1cff221dd1f47463a9349c8ef3567b3c110f74bd`, PR #12 | Prototipo sintetico, 22 test nominali; primo G0 Red Team ha dichiarato **FAIL** il gate dati pubblici non fidati. |
| G2R1 | `be7e17776c31fc711aaed75cfc35a1c5632a5b4c`, PR #13 | Correzione D1–D8; 49 test propri PASS. Red Team Sol: **PARTIAL**, 50/50 suite on-chain corrente e 99/99 combinata PASS, con nuovi difetti contrattuali. |
| G2R2 | `d474bd6c614b6cbd7a06ba69bc4311ffa34a0f32`, PR #14 | Costruttrice riporta **121/121** test PASS e 15/17 controprove Sol soddisfatte. **Non ancora accettato come validazione indipendente finale.** Nessun merge o deploy. |

**Gate Punto 4: NON SUPERATO.** Restano **P08** (quattro contesti testuali pubblici non trasferiti con provenienza affidabile) e **P09** (autenticazione effettiva del produttore/input non dimostrata). Un URL HTTPS, un digest base58, il flag `PUBLIC_REPORTED` o `VERIFICATO` **non costituiscono attestazione**. Il contratto sperimentale è [KDD_P4_G2R2_CONTRATTO_PROVENIENZA_V001.md](KDD_P4_G2R2_CONTRATTO_PROVENIENZA_V001.md). La G2R2 conserva ulteriori metadati e dimostra un trasporto numerico limitato su fixture, **non** una pipeline live attestata.

**Punto da verificare nel G0 Sol G2R2:** la funzione canonica `dossier_trade.token_fundamentals` mappa attualmente CoinGecko solo per ICNT e KAS, non per SUI. La fixture numerica CoinGecko SUI in G2R2 non prova da sola la disponibilità di un produttore canonico SUI. Sol è stato incaricato di controllare il punto; non anticipare il risultato.

**STOP** a nuovi automatismi, Punto 5, merge o installazione dei rami sperimentali senza mandato esplicito e verifica indipendente. Il Punto 4 non deve però impedire la ricognizione G0 strategica sull'intero KDD.

## 4. Prossima priorità infrastrutturale: ponte Samsung → Drive → ChatGPT

**Decisione di indirizzo dell'autore, 22 ottobre 2026:** rendere accessibile a GPT **l'intero patrimonio informativo** del KDD tramite Google Drive collegato, per eliminare esportazioni manuali ripetute e consentire valutazioni su dati aggiornati. **Non** è un trasferimento del runtime Python su Drive, né un ordine di caricare indiscriminatamente la cartella Termux.

**Architettura prevista:** il Samsung resta esecutore e fonte primaria; Drive è archivio privato e consultabile; GitHub continua a gestire codice/test/versioni; ChatGPT legge i file autorizzati tramite connettore. Sincronizzazione desiderata **unidirezionale**, con pubblicazione atomica e verifica di provenienza, orari e integrità. Nessuna modifica da Drive verso Termux.

**Perimetro del futuro archivio leggibile:** snapshot di quantità e liquidità Kraken (dati personali, con accesso ristretto), prezzi e mercati, dossier e fonti, piani, decisioni, verifiche, storici, configurazioni non segrete e documentazione locale opportunamente verificata. Servono manifest, timestamp indipendenti per saldo/prezzi, versione, stato di errore, hash e indicazione esplicita della freschezza. File vecchi non devono essere presentati come attuali.

**Separazione obbligatoria dei segreti:** chiavi/API, password, token, seed, credenziali e backup non bonificati **non devono essere copiati in chiaro su Drive o inseriti nei documenti leggibili da GPT**. Eventuale backup integrale sensibile solo cifrato localmente, con chiave custodita fuori da Drive/ChatGPT. Una cartella privata Drive non offre di per sé cifratura end-to-end e potrebbe essere resa accessibile ad app collegate: minimizzazione e permessi verificati sono obbligatori.

**Stato al 22/10 — distinzione rigorosa delle prove:** il ponte **Samsung → FolderSync → Drive → GPT** è stato collaudato manualmente con `prova_kdd.txt` e `mercato_kdd.json`, letti in chat senza caricamento diretto. L'ultima rilevazione pubblica osservata è `2026-10-22T15:57:41+00:00` (1.090 coppie, 610 token); la sua età va ricalcolata al momento della lettura. L'autore ha mostrato il log di saldo privato Kraken delle `15:56:32 UTC` con 10 posizioni **non esportate**. Il job automatico FolderSync rimane **OFF**, e non esiste una pipeline automatica di saldi privati.

**GO G2 sperimentale conferito dall'autore:** su ramo `experiments/kdd-drive-public-export-g2-20261022`, PR #15 **bozza**, un nuovo modulo `kdd_export_public_v001.py` permette di estrarre **solo contatori e metadati pubblici** da `ultima_rilevazione.json` e pubblicare atomicamente `/storage/emulated/0/KDD_TEST_SAMSUNG/mercato_kdd.json`. L'hook nel `refresh()` di `decision_desk.py` avviene *dopo* il report ed è **disattivato per impostazione predefinita**: l'opt-in `KDD_DRIVE_PUBLIC_EXPORT=1` richiede altra autorizzazione per l'attivazione sul telefono. Errori di esportazione non bloccano KDD. Regressioni specifiche **24/24 PASS in ambiente locale isolato** (non è un collaudo integrale Termux/FolderSync); adeguate le allowlist Git e deploy del solo ramo.

**NON FATTO:** verifica indipendente Sol, merge su `main`, installazione sul Samsung, attivazione dell'opt-in, job pianificati e trasferimento di dati patrimoniali reali. L'estensione ai dati privati richiede inventario reale delle cartelle, minimizzazione, consenso e modifica esplicita dei vincoli in [GOVERNO_KDD.md](GOVERNO_KDD.md). **Mai** inviare chiavi, seed, token o backup in chiaro a Drive/GitHub/ChatGPT.

## 5. Regole di sicurezza e sviluppo

- L'autore autorizza ogni intervento; **GO G0 ≠ GO G2 ≠ GO al deploy ≠ GO finanziario**. Gli esperimenti isolati non modificano `main` o il Samsung salvo mandato distinto.
- In GitHub solo sorgenti e documenti esplicitamente consentiti dalla `.gitignore` in allowlist; **mai** dati personali, file `portafoglio.json`, report finanziari, snapshot, T0, piani privati, credenziali o README Termux completo. Non usare `git add -f` né sincronizzazioni cieche col repo.
- Sorgenti aggiornati sul telefono soltanto tramite procedura [AGGIORNAMENTI_TERMUX.md](AGGIORNAMENTI_TERMUX.md): staging, `kdd-aggiorna --check`, autorizzazione umana `--apply`, backup/rollback, test e, se cambia la UI, riavvio server e prova Chrome. Non usare `git pull` nel runtime vivo.
- Distinguere sempre dato osservato, interpretazione, ipotesi, ordine manuale confermato e scenario controfattuale. Non registrare un ordine non eseguito come profitto/perdita reale.

## 6. Priorità operative correnti

1. **G0 Sol:** verifica indipendente PR #14 e discrepanza CoinGecko SUI; Punto 4 resta separato da `main`.
2. **Ponte Drive:** acquisiti i percorsi del codice, realizzato e verificato il trasporto Android→FolderSync→Drive→GPT su dati innocui, preparato prototipo esportatore pubblico 20/20 PASS **offline**. Ora verifica G0 della directory Termux reale e della privacy, quindi GO G2 dedicato per installazione sperimentale (senza toccare altri rami).
3. **G0 patrimoniale in chat:** usare la fotografia del 21/10 solo come base storica e ottenere in seguito dati correnti con marcatori di freschezza. Rivedere alternativamente esposizioni strategiche, rotazioni, liquidità spot e opportunità; nessun ordine implicito.

La sequenza e i gate sono descritti in [ROADMAP_KDD.md](ROADMAP_KDD.md); i vincoli sovraordinati in [GOVERNO_KDD.md](GOVERNO_KDD.md) e nel mandato operativo locale. **Questo aggiornamento è solo documentale e non prova alcuna nuova funzione installata.**
