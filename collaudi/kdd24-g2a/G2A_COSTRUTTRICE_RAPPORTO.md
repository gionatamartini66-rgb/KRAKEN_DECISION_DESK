# KDD-24 — G2-A | Recuperatore GPT–Google Drive

Costruttrice. Data: 20 novembre 2026. Regime: GO G2-A, solo sviluppo isolato e dati sintetici. Nessuna modifica ai documenti canonici, main, PR #76 o patrimonio. Nessun merge, deploy, plugin, OAuth, connessione Google o ordine.

Baseline: main@c3d14f3a928b3cdc60b1669f450809997e42319b. PR #76 Draft separata (HEAD del mandato efcfed0e70db4cedac4176919020826aa09112db; la lettura successiva la vedeva già a 153e7eb549bd4e7916c57f88801e598b6478aa1c). Il ramo G2-A deriva direttamente dalla baseline main.

## Materiali e contratto

- scripts/kdd_gpt_drive_retriever.py: funzione kdd_get_latest_verified_dossier(reader, folder_id, validator=None, now=None); adattatore DriveV3ReadOnlyAdapter per trasporti HTTP JSON e byte **iniettati**, senza implementare OAuth o rete.
- scripts/test_kdd_gpt_drive_retriever.py: 19 prove sintetiche locali superate in Python 3.13 e una controprova differenziale col bridge originale, progettata per essere eseguita nel checkout completo.
- .github/workflows/kdd-g2a-retriever-synthetic.yml: CI dedicata, attivabile esclusivamente da push su questo ramo; una sola suite di fixture sintetiche, senza suite live e senza credenziali Google.

Lettura: doppia enumerazione completa della cartella con nextPageToken e incompleteSearch=false; rifiuto di cursori ciclici, risposte parziali e identificativi duplicati; lettura dei file binari compatibili con kdd_handoff_<sha>.json; confronto dimensione, SHA-256 dei byte, SHA-256 e MD5 eventualmente forniti dal provider; verifica che i byte siano esattamente la serializzazione canonica bridge.canonical(bundle) più newline e che il digest JSON del filename corrisponda; parsing JSON rigoroso; controllo dei timestamp; chiamata obbligatoria al vero scripts.kdd_bridge_g2.read_context(bundle, now=..., expected_sha256=...); scelta del massimo preparato_utc; confronto dei metadati tra le due scansioni; stati finali.

I due SHA-256 sono diversi per contratto: l'identificativo nel nome deriva dal JSON canonico **senza** newline; i byte trasportati comprendono una newline. Nessuna di queste prove autentica l'origine del produttore. La risposta espone sempre integrita_origine=NON_AUTENTICATA, e segnala separatamente se il SHA-256 restituito da Google Drive è stato confrontato.

Non viene praticato il fallback silenzioso. Una qualsiasi evidenza KDD malformata, anche storica, blocca l'intera selezione; regola più severa di “scegli il più recente valido”, soggetta a futura valutazione di politica di quarantena e continuità. I file del dossier devono risultare univoci o semanticamente identici a parità del massimo timestamp. Drive non offre uno snapshot transazionale cross-page: la seconda scansione riduce i rischi di race ma non conferisce atomicità assoluta.

Stati: DOSSIER_RECUPERATO quando market e saldo sono RECENTE alla lettura; DOSSIER_SCADUTO in presenza di evidenza valida ma non recente; DOSSIER_NON_VERIFICABILE se inventario, byte, identità, schema o validatore falliscono; ACCESSO_NON_DISPONIBILE per accesso revocato o fonte indisponibile. Nessun esito positivo è emesso quando il modulo KDD originale è assente; NON esiste validatore parziale di fallback. L'intero contesto validato è restituito senza omettere sezioni, ma l'eventuale MCP reale dovrà prevedere output/sezioni paginati senza alterare il significato.

## Prove: distinzioni obbligatorie

Nel contenitore isolato locale è stato eseguito:
PYTHONPATH=.:scripts python -B -m unittest -v scripts.test_kdd_gpt_drive_retriever

Esito: 20 test scoperti; 19 superati con FakeDrive e SyntheticBridge; 1 test differenziale con il vero read_context NON eseguito (skip: sorgente originale non presente nel runtime locale e rete GitHub non disponibile). I 19 casi coprono multipagina, ordinamento corretto, recente alterato, duplicati incompatibili, storico alterato, scadenza, revoche, incompleteSearch mancante/true, token ciclico, ID ripetuti, race inventario, hash provider discordanti, assenza dichiarata dell'hash provider, byte non canonici, chiavi JSON duplicate, assenza bridge e parametri dell'adattatore Drive.

La prova di confronto esatto usa le fixture ORIGINALI KDD, bridge.prepare(..., _fixture=True) e bridge.read_context(..., expected_sha256=...), allo snapshot e quattro ore dopo. È predisposta, non già superata localmente; la CI di questo ramo è il mezzo consentito per eseguirla in checkout completo. Il suo risultato va accertato e distinto dalle prove simulate prima di consegnare la parità alla Supervisione. Le prove della Costruttrice non sono collaudo indipendente Red Team.

## ChatGPT Sites, Google Drive e ambiente

La documentazione OpenAI conferma l'hosting MCP su Sites, ma per l'avvio iniziale occorre pubblicazione di un Site e creazione/connessione del plugin: attività vietate in G2-A. Gli strumenti attivi consentono di creare plugin privati ma non danno un sandbox di esecuzione Sites senza pubblicazione; nessuna operazione di installazione o pubblicazione è stata effettuata. Il supporto del runtime Sites per Python e per tutte le dipendenze KDD rimane NON DIMOSTRATO, non dichiarato impossibile.

Il connettore ChatGPT Google_Drive.list_folder ha una cardinalità limitata e non espone nextPageToken; Google_Drive.search non è una base affidabile secondo la prova R2. Perciò il progetto prevede l'interfaccia Drive REST v3 con credenziali esterne, non configurate, e query cartella esplicita. Il recuperatore non eredita né presume le credenziali Google del connettore ChatGPT.

OAuth non autorizzato. drive.file non garantisce visibilità di dossier FolderSync preesistenti; drive.readonly concede accesso a tutti i file leggibili dall'utente (non solo KDD) ed è scope sensibile/ristretto secondo la classificazione di Google. Prima di usarlo occorrono GO separato, verifiche del consenso, storage protetto dei refresh token, revoca, scope minimo praticabile e limite applicativo alla cartella, oltre a prova effettiva in runtime MCP. Nessun accesso a Google è stato eseguito in G2-A.

## Gate successivo

1. Verificare la CI e il differenziale col read_context originale; non certificare ciò che non si è riusciti a eseguire.
2. Valutare con un GO specifico runtime Sites senza dati privati, incluso eseguire il Python KDD originale o un servizio con dipendenze originali; nessuna architettura Sites definitiva assunta ora.
3. Progettare il layer auth Google con privilegi e custodia credenziali, richiedere distinto GO OAuth prima dell'uso.
4. Collaudo indipendente Red Team, poi decisione della Supervisione; KDD-24 NON chiuso e nessun merge/deploy consentito.

STOP alla consegna G2-A.


## Esito CI sintetica sul checkout originale — prova eseguita

GitHub Actions: https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/actions/runs/44774244735
Run ID: 44774244735; job: synthetic-only, ID 136419670344; commit di prova 3c8e59c9a77b9ff3feb4a9ec2a3fff06689f16c4; conclusione: SUCCESS.

Log letti direttamente: 20 test scoperti, 19 passati, 1 skipped. Il confronto **sul vero codice KDD** OriginalBridgeDifferentialTests.test_original_read_context_matches_retriever_fresh_and_stale risulta **ok**: contesto recuperato identico al bridge.read_context() originale, alle due date della fixture. Lo skip riguarda soltanto test_missing_real_bridge_fails_closed_no_partial_validation, previsto per l'ambiente privo di bridge; nel checkout CI il bridge originale è presente ed è esercitato dalla prova differenziale.

Questo sostituisce il precedente stato di prova differenziale non eseguita localmente, senza riqualificare le prove come Red Team o come test live Drive. Tutta la CI rimane solo sintetica. Sites, OAuth, collegamento GPT automatico e Drive reale NON verificati, non autorizzati né attivati.
