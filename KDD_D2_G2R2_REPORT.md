# KRAKEN DECISION DESK — D2/G2R2
## Remediation architetturale del confinamento e controllo semantico del preflight

**Data:** 22 ottobre 2026. **Classe:** G2 su ramo sperimentale isolato, sola elaborazione di fixture pubbliche sintetiche. **Verdetto costruttrice: NO-GO ARCHITETTURALE per la pubblicazione diretta sul percorso condiviso.** Correzione C02 predisposta per valutazione indipendente, **non** certificata su clone completo del progetto. Nessun merge, deploy, FolderSync, cloud, API finanziaria o operazione.

## 1. Identità e provenienza

Repository privato `gionatamartini66-rgb/KRAKEN_DECISION_DESK`. Base esatta G2R1 `5c891a073eb4d2360a2e7d3a6740a7c44b6e43d4` (PR #16 draft), con G2 originale `a62ac221491494754577dca7e8fd19e1b39f8955` (PR #15 draft). I 14 file richiesti nel mandato sono stati letti integralmente mediante connettore GitHub al commit G2R1. Acquisito integralmente dalla Libreria il rapporto Sol `KDD_D2_G0R1_SOL_REDTEAM_2026-10-22.md` (194 righe). La relazione cita gli artefatti `test_sol_adversarial.py`, `sol_g0r1_70_tests.log`, `test_preflight_git_real_synthetic.py` ma **non ne sono stati trovati i byte sorgente nella Libreria**: non pretendiamo di averli riprodotti identicamente.

Le copie G2R1 nell'archivio `KDD_D2_G2R1_REMEDIATION_2026-10-22.zip` presentavano **un newline finale aggiuntivo** rispetto ai blob GitHub. Rimosso questo byte extra nelle copie locali del laboratorio: i cinque hash `git hash-object` coincidono esattamente con quelli verificati da Sol:

| File | Git blob SHA-1 G2R1 verificato |
|---|---|
| `kdd_export_public_v001.py` | `b9443c4cf8a766033a4f448ae1fbb0072e721625` |
| `test_kdd_export_public_v001.py` | `fd282f26bee218cd7246934cc8058f02caad5b64` |
| `test_kdd_export_public_g2r1.py` | `432d6fbdfc49e27ef29d7c8b6bd889beac8f36f8` |
| `scripts/kdd_export_preflight.py` | `aa20036a36ea5f0b8ed1943bc4f9d9e1982dd983` |
| `scripts/test_kdd_export_preflight.py` | `a8889342458613b3493b4e00ce7754c7f2c651f9` |

L'updater ordinario resta il blob `408e8f0328d35129021333df0fa9b99e8e8a4bc6`; non è stato modificato. Questa identità riguarda codice e prove, non l'autenticità dell'origin remoto o lo stato del dispositivo.

## 2. Modello di minaccia non ridotto implicitamente

1. **Errore umano:** destinazioni sbagliate e file incoerenti. Blocco della pubblicazione condivisa; parsing a allowlist.
2. **Processi concorrenti legittimi:** lettori, FolderSync e scrittori che rispettano lock; perimetro non validato su Android. Il lock POSIX è advisory.
3. **Altre applicazioni autorizzate allo storage condiviso:** diritti dipendenti da scoped storage, grant, media provider e FUSE reali; possibilità di rinomina **non accertata** sul Samsung.
4. **Processo ostile che può rinominare la directory:** incluso. S02 **dimostrato** in Linux. I descriptor restano legati all'inode spostato. Nessuna ulteriore verifica `stat`, inode, `flock` o confronto di pathname può chiudere l'ultima finestra atomica.
5. **Processo ostile con privilegi Termux-equivalenti/stesso UID:** incluso come avversario forte; permessi `0700` di una directory dell'app **non isolano da un processo dello stesso UID**. Serve un separato dominio di fiducia o rinuncia alla garanzia.
6. **Dispositivo integralmente compromesso:** nessuna garanzia di confidenzialità/integrità locale è sostenibile. Esclusione motivata dalla capacità di alterare codice, storage, runtime e attestazioni, non dal ritenere improbabile tale compromissione.

In nessun punto si suppone che il Samsung garantisca permessi Linux normali su `/storage/emulated/0`.

## 3. Causa D2-S02 e riproduzione autonoma antecedente la correzione

Nel codice G2R1 `_assert_anchored(dirfd)` controlla che l'inode sia ancora al percorso consentito. L'attore ostile può spostare **quella stessa directory** fra l'ultimo controllo e `os.rename(temp, final, src_dir_fd=dirfd, dst_dir_fd=dirfd)`. Il rename mantiene l'inode, scrive il documento nel contenitore ormai trasferito, poi il controllo finale segnala errore. Un errore non revoca il documento già pubblicato.

Il riproduttore autonomo su G2R1 byte-identico `reproduce_g2r1_s02.py`, solo Linux e file sintetici, registra:

- `D2_S02_G2R1_directory_moved=true`;
- `D2_S02_G2R1_published_outside_original_path=true`;
- `G2R1_move_during_file_write_detected=true` e `...did_not_publish=true`: il movimento più precoce durante fsync file viene rilevato prima del rename;
- `G2R1_fsync_calls=3`, `G2R1_post_rename_failure_document_exists=true`: fsync directory successivo al rename fallisce quando il file è già presente.

Per la variante della rinomina immediatamente prima della syscall, il riproduttore intercetta la funzione nel solo processo di test, include esplicitamente il mock in `os.supports_dir_fd` e poi richiama il vero `os.rename`; evita così il falso positivo di test D2-T01. Niente scrittura su `/storage` reale.

## 4. Alternative esaminate

| Scelta | Garanzia realistica | Prerequisiti e rischio residuo | Android / FolderSync / impatto KDD |
|---|---|---|---|
| **A. Cartella condivisa protetta da permessi** | Può bloccare rinominazioni solo se il kernel nega effettivamente il diritto a **tutti gli attori non fidati**, inclusi accessi equivalenti allo stesso UID | ACL/UID/mount verificati sul dispositivo, niente attore ostile con permesso di rinomina; permessi POSIX su FUSE non sufficienti di per sé | Compatibilità e controllo delle autorizzazioni non provati; FolderSync deve avere accesso; non autorizzata la modifica dei permessi |
| **B. Generazione nell'area privata app + trasferimento autorizzato** | Staging locale isolato da altri UID secondo sandbox Android; niente pubblicazione nel percorso condiviso effettuata dal KDD | Canale di passaggio con confine di fiducia distinto (SAF/ContentResolver o meccanismo autorizzato). Attore stesso UID o compromissione completa non contenuti dalla sola directory privata | Android offre storage interno app-specific, ma FolderSync potrebbe non accedervi. Serve autorizzazione e collaudo del passaggio; nessun nuovo servizio implementato |
| **C. Pubblicazione tramite API/mediatori Android autorizzati** | Potenziale controllo attraverso autorizzazioni SAF/ContentProvider, non prova automatica di atomicità/durabilità o autenticità | Contratto URI/document provider, verifica dei permessi, semantica di replace/stream, FolderSync e assenza di bypass | Richiederebbe integrazione Android/permessi e GO separato; il semplice Python/Termux stdlib non implementa tali proprietà |
| **D. Mantenere il percorso attuale senza separare il trust boundary** | **Nessuna garanzia assoluta** nel modello che include rinomina ostile autorizzata | Qualsiasi ultimo controllo può essere seguito da uno spostamento; lock advisory inefficace contro l'attore ostile | Non approvabile; aumenta il rischio di pubblicazione fuori destinazione se il rename è consentito |

**Scelta:** NO-GO per la scrittura diretta nella cartella condivisa. Preferenza architetturale futura per **B**, con **C** come possibile trasporto autorizzato dopo prova dei diritti effettivi. Non è lecito presentarla oggi come soluzione completata: nessun bridge privato→condiviso verificato su Android è disponibile nel mandato.

## 5. Modifiche G2R2 — disabilitazione controllata e laboratorio

`kdd_export_public_v001.py`: conserva `prepare`, validazione, allowlist e consumer `freshness_at_read`, **schema `kdd_public_market_v002` invariato**; sostituisce la pubblicazione diretta su shared storage con **fail-closed incondizionato**, anche con opt-in `1`. `publish()` solleva `ExportError('NON_PUBBLICATO: ...')` senza aprire la destinazione, creare un temporaneo o eseguire `os.rename`. `export_if_enabled` resta OFF senza opt-in esatto; il codice esistente di `decision_desk.refresh` intercetta la sua eccezione nell'hook. La CLI non può forzare output. Il processo KDD non è modificato; su un eventuale deploy non autorizzato l'opt-in ON produrrebbe un avviso, **non un file**.

`scripts/kdd_publication_lab.py`: **solo laboratorio**. La simulazione alloca da sé cartelle in `TemporaryDirectory`, scrive esclusivamente un JSON marcato `FIXTURE_TEST_ONLY`, modella quattro esiti `NON_PUBBLICATO`, `PUBBLICATO_CONFERMATO`, `PUBBLICAZIONE_INCERTA`, `ERRORE_PRIMA_DELLA_PUBBLICAZIONE`. Non è importata dall'esportatore, non fa parte della allowlist `scripts/kdd_aggiorna.py`, non può trasferire dati sul telefono. Il test del `fsync` post-rename dà `PUBBLICAZIONE_INCERTA` e registra un file finale già esistente; non viene dichiarato rollback. Anche un errore `rename` senza attestazione di commit è classificato prudentemente incerto. La conferma nel laboratorio non certifica durabilità contro crash Android.

**Protocollo di recupero per un eventuale futuro publisher:** dopo stato incerto, **non** annunciare assenza di file e **non** sovrascrivere automaticamente. Ricontrollare in una destinazione protetta l'identità/versione dell'output, confrontarne contenuto e origine con il record preparato, distinguere presenza da durabilità e ottenere una nuova autorizzazione al retry. Senza boundary di fiducia verificato, restare NO-GO.

## 6. D2-C02 — verifica semantica effettiva e limiti

`scripts/kdd_export_preflight.py`: eliminata la ricerca di sottostringhe nel sorgente updater. Adesso:

1. richiede commit SHA esatto proposto, HEAD, ramo G2R2, clone pulito, base G2R1 antenata, diff soltanto in allowlist; controlla le entrate pertinenti in `.gitignore`;
2. confronta **byte effettivi** dell'updater con il blob Git attestato `408e8f...` prima di eseguirne qualsiasi codice;
3. carica il **solo updater così riconosciuto**, senza entrare nel suo `__main__`, ed esercita `verified_clone()` su un ramo sperimentale reale del clone verificato: è richiesta esattamente la motivazione di rifiuto `solo ramo main controllato`;
4. effettua un clone **locale in temporanea**, seleziona un ramo `main` Git reale (da `origin/main` del clone locale), imposta *solo nel clone sintetico* l'URL origin canonico e verifica che la stessa funzione accetti `main` pulito restituendo l'HEAD. Un controllore che rifiuti sempre non supera la prova;
5. esegue nello staging 0700 soltanto test isolati del nuovo export non pubblicante e della simulazione, con checkpoint **sintetico** e senza chiamare `apply`.

I sette test G2R2 specifici del preflight creano un repository Git locale reale, con commit `main` e ramo sperimentale. Un updater fittizio con le stringhe originali **nei soli commenti** viene respinto dal controllo blob. Anche un updater che accetti il ramo sperimentale, oppure rifiuti per un motivo estraneo, viene respinto nelle prove di comportamento. Per la prova positiva i test iniettano una **fixture comportamentale** della funzione `verified_clone`, NON l'intero updater canonico; dunque il preflight end-to-end con il blob updater completo, GitHub clone e ramo G2R2 resta **NON ESEGUITO** in questo laboratorio. Il controllo `origin` testuale da solo NON autentica la provenienza remota; lo SHA fornito dal chiamante da solo NON è approvazione umana.

Non sono stati modificati `scripts/kdd_aggiorna.py`, `scripts/test_kdd_aggiorna.py`, `decision_desk.py`, `GOVERNO_KDD.md`, Termux o qualunque PR preesistente. Il preflight non ha modalità `--apply` né call-path all'installer ordinario.

## 7. Test — separazione dei significati

| Contesto eseguito localmente | PASS | FAIL / incompatibilità | Evidenza |
|---|---:|---:|---|
| **Baseline G2R1 byte-identica**, 24 vecchi + 22 G2R1 + 5 preflight | **51/51** | 0 | `tests_legacy_against_original.log`; sono test **della vecchia implementazione insicura**, non un PASS G2R2 |
| **Nuova suite G2R2** (20 exporter non pubblicante + 7 simulazione fsync/rename + 7 Git/preflight) | **34/34** | 0 | `tests_g2r2_acceptance.log` |
| Vecchie suite G2R1 eseguite **contro il nuovo exporter non pubblicante** | 32 | **14 incompatibilità**: 1 FAIL + 13 ERROR | `tests_legacy_against_new.log`; i casi si aspettano ancora la pubblicazione condivisa. **Non sono stati modificati per simulare PASS** |
| Riproduttore autonomo G2R1 race/fsync | prove booleane come in §3 | N/D | `g2r1_reproduction.json` |
| Suite integrale `test_decision_desk.py` | **non eseguita** | ambiente/runtime locale completo assente | Solo codice remoto letto |
| Suite legacy `scripts/test_kdd_aggiorna.py` | **non eseguita** | modulo completo updater non disponibile nel laboratorio | Codice remoto letto |
| Test originali Sol D2/G0R1 | **non eseguiti** | byte originali non ritrovati | Rapporto Sol letto |
| Test su Android/Termux/FUSE, FolderSync, Drive, GPT consumer | **0** | **NON DIMOSTRATI** | Nessun accesso al telefono |

I 34 PASS non significano che esista un nuovo publisher operativo: dimostrano precisamente che **non è possibile pubblicare attraverso l'exporter G2R2** e che le prove sintetiche distinguono gli esiti. Gli 14 fallimenti storici sono **regressioni di contratto intenzionali**: impongono un blocco ulteriore contro l'eventuale merge inconsapevole senza riprogettazione autorizzata. Il preflight del clone completo resta un gate distinto.

## 8. Freschezza e riservatezza

Preservato `kdd_public_market_v002`. Il documento non contiene un'etichetta permanente `CORRENTE`: `freshness_at_read` ricalcola sull'istante di lettura, segnala incoerenze, non attribuisce timestamp nativi Kraken. Sincronizzazione e lettura GPT sono `null` se non comprovate. Il consumer esterno resta **NON VINCOLATO** a questa funzione e la catena cronologica reale **NON TESTATA**.

La sola struttura positiva prodotta in `prepare()` estrae due contatori e metadati fissi. Il test con sentinelle sintetiche per portafoglio, saldo, T0, piano, backup/log verifica che siano assenti. Nessun file privato sul Samsung, nessuna chiave, account, API privata, ordine o trasferimento di dati è stato usato.

## 9. Gate residui

1. Non pubblicare direttamente su `/storage/emulated/0/KDD_TEST_SAMSUNG` finché S02 non sia chiusa con un confine di fiducia dimostrato nel modello di minaccia autorizzato.
2. Un nuovo GO **G0 diagnostico non pubblicante** potrà misurare autorizzazioni reali, FUSE, capacità di rename da altre app, differenza di UID, permessi SAF/ContentProvider, e accessibilità a FolderSync, senza modificare KDD.
3. Un futuro GO distinto potrà prototipare **B/C** con una interfaccia di trasferimento controllata, usando esclusivamente fixture, e dimostrare atomicità, provenienza, opzioni crash/retry e consumer freshness sul dispositivo.
4. Nuovo Red Team Sol indipendente sul commit finale, controprova di byte SHA updater e clone reale completo, suite KDD/updater pertinenti, verifica dell'impossibilità di ogni pubblicazione su shared path.
5. Niente promozione/merge/deploy, attivazione `KDD_DRIVE_PUBLIC_EXPORT=1`, FolderSync, dati patrimoniali o aumento del perimetro informativo.

## 10. Decisione

**NO-GO ARCHITETTURALE** per il **publisher diretto su memoria condivisa sotto attore ostile con permesso di rinomina**. **G2R2 CONSEGNATA come remediation di fail-closed e riprogettazione documentata, non come ponte operativo riuscito.** L'alternativa B/C resta da costruire e verificare con altra autorizzazione. L'esito C02 è migliorato, ma il collaudo positivo dell'updater pin attraverso l'intero clone KDD è ancora da eseguire. La Costruttrice non può certificare il gate Sol.