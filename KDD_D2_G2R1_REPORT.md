# KRAKEN DECISION DESK — KDD
## D2 / G2R1 — Remediation del ponte pubblico KDD → FolderSync → Google Drive → ChatGPT

**Data:** 22 ottobre 2026. **Mandato:** G2R1 isolato, autorizzazione circoscritta. **Giudizio costruttrice:** **REMEDIATION PARZIALE**, non autorizzato collaudo Samsung, merge, attivazione, FolderSync o dati privati. Il presente documento non supera il gate del Red Team Sol.

## 1. Fonti e catena di custodia

Repository privato `gionatamartini66-rgb/KRAKEN_DECISION_DESK`, PR **#15** (draft, non merged), ramo originale `experiments/kdd-drive-public-export-g2-20261022`, commit originale immutato `a62ac221491494754577dca7e8fd19e1b39f8955`. Acquisiti dal connettore GitHub: `README.md`, `ROADMAP_KDD.md`, `GOVERNO_KDD.md`, `decision_desk.py`, `kdd_export_public_v001.py`, `test_kdd_export_public_v001.py`, `scripts/kdd_aggiorna.py`, `scripts/test_kdd_aggiorna.py`, `.gitignore`, PR e commit. Rapporto Red Team disponibile integralmente dalla Libreria ChatGPT: `KDD_D2_G0_SOL_VERIFICA_AVVERSARIALE_2026-10-22.md`. Log originale dei 40 test trovato: `KDD_D2_G0_SOL_40_TEST_LOG.txt`, che attesta soltanto `Ran 40 tests ... OK`. **I byte di `test_redteam_additional.py` (16 controprove Sol) e le fixture originali Sol non sono stati reperiti**: i nuovi test sono riproduzioni indipendenti, non una riesecuzione dei 16 test identici. La copia dell'esportatore G2 usata per le riproduzioni preliminari ha hash `git hash-object` **`eb6914c2d9f7efc912ea49d5ab9ecc0a24687787`**, identico a GitHub al commit originale.

## 2. Dimostrazione dei difetti PRIMA della correzione

Laboratorio isolato Python 3.13.5/Linux, fixture sintetiche, nessun Samsung, nessuna rete o dati privati. Script `reproduce_baseline.py` contro il blob originale Git verificato:

| ID | Evidenza G2 originale ricostruita | Esito |
|---|---|---|
| D2-S01 | Directory differente, ma stesso basename `KDD_TEST_SAMSUNG`, accettata e scritta | DIFETTO RIPRODOTTO |
| D2-S02 | Sostituzione della directory con symlink **dopo** il controllo ma **prima** della scrittura: output fuori destinazione | DIFETTO RIPRODOTTO |
| D2-O01 | Invocazione autonoma `main()` pubblica con opt-in `0` | DIFETTO RIPRODOTTO |
| D2-F01 | Documento etichettato `CORRENTE` rimane così dopo tre giorni | DIFETTO RIPRODOTTO |
| D2-C01 | `verified_clone()` nell'updater sorgente rifiuta ogni ramo diverso da `main` | DIFETTO CONFERMATO STATICAMENTE; non è stata eseguita la CLI updater sul branch sperimentale |

Risultati della riproduzione conservati in `baseline_reproduction.json` nel laboratorio; non contengono informazioni di mercato reali.

## 3. Correzione puntuale → nuovo controllo

### D2-S01 — indirizzo di output
`publish()` richiede ora il percorso completo **esatto** `DEFAULT_DEST = /storage/emulated/0/KDD_TEST_SAMSUNG`; sono eliminati il controllo basato solo sul basename e il parametro CLI `--dest-dir`. La visita parte dal descriptor della radice `/`, apre ogni componente con `O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC`, e rifiuta symlink negli antenati. Le operazioni di scrittura sono relative esclusivamente al descriptor aperto. Destinazioni diverse sono respinte senza scrivere file. Per i test Linux la costante viene **sostituita soltanto con mock nel processo di prova**, non esiste una variabile ambientale che configuri un percorso alternativo in produzione.

### D2-S02 — swap ostile e concorrenza
La directory finale viene fissata tramite descriptor; inode/dispositivo vengono ricontrollati rispetto alla visita dal percorso originale *prima* di creare il temporaneo e *prima* del rename. Temporaneo `O_CREAT | O_EXCL | O_NOFOLLOW` e `os.rename(... src_dir_fd=... dst_dir_fd=...)`; lock `fcntl.flock` esclusivo non bloccante, `fsync` di directory verificato **prima** della pubblicazione. Vietata pubblicazione quando descriptor/locking/fsync non sono supportati. Il file precedente resta disponibile in caso di errore di preparazione o scrittura prima del rename. Sono testati: directory rimpiazzata con symlink durante `prepare`, file finale symlink, errori `fsync`, errore rename, scritture concorrenti.

**RISCHIO RESIDUO IMPORTANTE:** i descriptor impediscono il follow di symlink e l'uso di pathname sostituiti, ma non costituiscono una prova matematica contro un avversario che può *rinominare la stessa directory* dopo l'ultimo controllo dell'inode e prima/durante il rename, specialmente se condivide UID o permessi di scrittura. Si rifiuta il genitore di destinazione se scrivibile da gruppo/altri secondo i permessi POSIX; la sicurezza reale dei permessi FUSE Android, delle directory antenate e degli eventuali accessi equivalenti resta **NON VERIFICATA**. Se il modello Android permette un rename concorrente ostile, l'implementazione non va attivata: **NO-GO alla pubblicazione Android senza nuova verifica e meccanismo di confinamento dimostrato**. L'`fsync` post-rename può fallire dopo la pubblicazione, determinando uno stato di esito operativo ambiguo: non dichiarare rollback completato.

### D2-C01 — gate sperimentale separato
Nuovo `scripts/kdd_export_preflight.py` **solo per test, senza possibilità di applicazione**. Verifica repository e `origin`, SHA esplicitamente passato, HEAD, ramo esatto, clone pulito, ancestry del commit G2, file modificati nella allowlist, `scripts/kdd_aggiorna.py` ancora main-only e presenza dei test storici. Copia soltanto i tre moduli di test/servizio in `TemporaryDirectory(0700)`, crea un **checkpoint sintetico di staging**, esegue unittest e poi elimina il temporaneo. Non importa `kdd_aggiorna.apply` né accede al Samsung. Backup e rollback restano quelli previsti dal deployment esistente, **non eseguiti né collaudati come parte del G2R1**. Cinque test del preflight PASS con Git simulato; **preflight end-to-end sul clone Git reale PENDENTE**. Regola `main` del deploy normale NON modificata.

### D2-O01 — opt-in globale
Anche `publish()` verifica l'opt-in esatto `KDD_DRIVE_PUBLIC_EXPORT=1` prima di aprire file; `export_if_enabled()` rimane OFF senza stringa esatta e `main()` passa esclusivamente attraverso la medesima funzione. Import del modulo senza effetti. Variabili `true/yes/0/" 1 "` non autorizzano. Servizio già in esecuzione mantiene le variabili d'ambiente del proprio processo: modificare l'ambiente in una shell separata NON attiva il server. Nessuna schedulazione FolderSync o deploy autorizzati.

### D2-F01 — freschezza al consumo
Contratto dati aggiornato a **`kdd_public_market_v002`**: output persistente `freschezza = DA_RICALCOLARE_ALLA_LETTURA`, niente etichetta `CORRENTE` permanente. Il record distingue `rilevazione_utc` (composizione KDD, non risposta Kraken nativa), `esportazione_utc`, `sincronizzazione_utc=null`, `lettura_gpt_utc=null`, e lo stato temporale **soltanto all'export**. `freshness_at_read(doc, tempo_lettura)` ricalcola età e riporta `CORRENTE_ALLA_LETTURA`, `SCADUTO_ALLA_LETTURA`, `OROLOGIO_INCOERENTE`. Un futuro entro tolleranza non è marchiato corrente. La sorgente resta di autenticità non attestata: non inventati hash di autenticazione o timestamps del provider. In caso di nuova esportazione fallita si conserva il precedente file, che però non dichiara freschezza attuale; **il consumer GPT esterno non è ancora automaticamente vincolato alla funzione, e va verificato separatamente**.

**Ulteriore difetto source-bound D2-I01:** eliminata la race `stat→open` del sorgente: apertura con `O_NOFOLLOW` su directory sicura, lettura con limite effettivo `MAX_SOURCE_BYTES+1`, controllo `fstat` prima/dopo. Nessuna nuova categoria di dati di mercato.

## 4. Test e limiti

**In ambiente Linux/Python 3.13.5, senza rete, Samsung o dati privati:**
- **24/24 PASS** test G2 originali *conservati per nome e intento*, ma **adattati** alle nuove invarianti di sicurezza: destinazione mockata nel sandbox, opt-in esplicito, schema v002 e freschezza al consumo. Non sono i byte originali, e non si pretende che lo siano.
- **22/22 PASS** nuovi test G2R1, incluse 16 riproduzioni *autonome* degli scenari descritti da Sol, più sei controlli di invarianti. **Non sono i 16 file/test originali di Sol**.
- **5/5 PASS** test specifici del preflight C01, con comandi Git mockati.
- **TOTALE 51/51 PASS locale**.
- Riprodotti in modo separato i quattro difetti dinamici G2 sul blob SHA verificato; il difetto C01 è statico.
- **0 esecuzioni** della suite completa `test_decision_desk.py` (necessita copia sicura dell'intero runtime/test fixture, non disponibile qui).
- **0 esecuzioni** della suite originale `scripts/test_kdd_aggiorna.py` (codice acquisito integralmente, ma non ricostruito eseguibile nel laboratorio isolato).
- **0 esecuzioni** dei 16 test *originali* Sol (solo rapporto, log e scenari disponibili).
- **0 collaudi** di preflight su un clone Git completo; 0 test sul filesystem emulato Android; 0 FolderSync/Drive/GPT end-to-end. Questi non sono PASS.

Il G2R1 non prova che il file `.json` arrivato a GPT sia autentico, fresco o coerente con lo stato corrente del telefono. Il consumer deve calcolare l'età all'istante effettivo di lettura, non utilizzare l'etichetta archiviata.

## 5. File e governance

Sostituiti su ramo G2R1 soltanto: `kdd_export_public_v001.py`, `test_kdd_export_public_v001.py`. Aggiunti `test_kdd_export_public_g2r1.py`, `scripts/kdd_export_preflight.py`, `scripts/test_kdd_export_preflight.py`, `KDD_D2_G2R1_REPORT.md`. Modificata `.gitignore` con allowlist ristretta di questi nuovi file. Originale PR #15 preservata, `main` non modificato, `scripts/kdd_aggiorna.py` non alterato, `decision_desk.py` non alterato, FolderSync non alterato. Report e codice non includono credenziali, saldo, T0, portafoglio, piani o wallet. Nessun deploy o conto Kraken interrogato.

## 6. Accettazione e prossima decisione indipendente

**Verdetto costruttrice: REMEDIATION PARZIALE.** Le vulnerabilità originali sono state affrontate e sono disponibili prove offline riproducibili. **S01, S02 e C01 NON sono considerati chiusi su Android**, per mancata verifica effettiva della semantica FUSE/dirfd e del clone/preflight. **F01 è mitigato nel produttore, non certificato nel consumer GPT**. Non va presentato un risultato 51/51 PASS come prova di sicurezza del ponte.

**Nuovo gate necessario:** Sol G0 indipendente sul nuovo commit, attacco con swap directory al limite del rename, verifica inode/permessi Android e fallimento chiuso; test della suite KDD/updater con fixture sintetiche in ambiente autorizzato, test CLI/hook/staging senza deploy e consumer ricalcolo di freschezza. **Non autorizzati:** merge, installazione Samsung, attivazione opt-in, FolderSync, ordini, saldi privati o altra infrastruttura.

**STOP al termine della consegna.**