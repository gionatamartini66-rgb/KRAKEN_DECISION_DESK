# KDD — MANDATO INTEGRALE DI SUBENTRO DELLA SUPERVISIONE APICALE


**STATO VINCOLANTE AL 20/11/2026 — DA RIVERIFICARE, NON PRESUMERE:** repository `gionatamartini66-rgb/KRAKEN_DECISION_DESK`, `main@c3d14f3a928b3cdc60b1669f450809997e42319b`. **7/29 formalmente COMPLETI** (KDD-01/06/07/08/10/13/17), **22 APERTI**. PR #74 e #75 MERGED; PR #75 con distinti GO installata sul Samsung (pre/postflight e 13 test cursori PASS), refresh Kraken read-only 20/11 riuscito (193,5 s; 10 posizioni, 4 candidati, monitor 8/8), dossier e bridge verificati senza cambiare T0, credenziali o proposte. FolderSync Samsung→Drive e Drive→Samsung automatico PASS con bytes identici, rapporti `TEST-R2-RAPPORTO.md` in Libreria; il dossier `kdd_handoff_766438d8759ba707a5487f3f38836d9a1c4f848264ee56ee78d70f7a65929437.json` (1.397.819 byte, SHA256 byte `c2496e92add4d79a0a3c8774e263241fc4e54bc31b96a85ff56892c3e117b1d4`) è presente su Drive. `TEST-R2` sintetico (7.148 byte) è ritornato automaticamente; il consumer ha correttamente risposto `Proposta in attesa diversa: STOP, nessuna sovrascrittura`; documento originale 7.424 byte ripristinato, SHA256 `b13f8201993d9a897595d981c1b88310a04707c3eed62cb95fc3177c99a9bae7`; nessun consenso, rifiuto o ordine. `Google_Drive.search` dà falsi negativi, `list_folder` con `fetch` mediante URL file ha recuperato il dossier in una nuova chat **guidata** con mandato, NON in una chat ordinaria autonoma. **PROBLEMA APERTO:** manca recuperatore GPT–Drive persistente ed eseguibile e manca prova invocazione ordinaria; non è un difetto FolderSync. **Costruttrice G0:** ricognizione consegnata e ipotesi MCP `kdd_get_latest_verified_dossier` (Sites possibile, OAuth/credenziali e validatore non provati). **Supervisione:** mandato G2-A di fattibilità e prototipo con fixture definito, subordinato a GO espresso. **PUNTO DI RIPARTENZA: IN ATTESA DEL RITORNO DALLA COSTRUTTRICE**. Nessun GO G2-A, nuovo software, plugin, autorizzazione OAuth, Red Team di G2-A o deploy è attestato in questa ricognizione; qualsiasi novità va verificata sulla fonte originale prima di dichiararla. **PR #76:** documentale Draft, non merged, HEAD della precedente revisione `efcfed0e70db4cedac4176919020826aa09112db` (non usare come HEAD corrente dopo aggiornamento), GO-MERGE distinto. KDD-24 resta PARZIALE anche per il gate separato di nuova proposta/Chrome; KDD-18/20/21/22 PARZIALI, KDD-27/28 da realizzare, KDD-29 NON DIMOSTRATO. Nessuna azione economica prima del completamento verificato 29/29 e dell'ulteriore avallo separato dell'autore.

**DECISIONE ARCHITETTURALE DELL'AUTORE 18/11/2026 — KDD-27:** il KDD **monitora autonomamente e periodicamente** mercato e patrimonio e conserva i campioni datati anche quando nessuno richiede un'analisi; **dossier completo e proposta GPT avvengono a richiesta** dell'autore, con frequenza libera, non a ogni rilevazione. Nel runtime corrente un refresh genera ancora dossier e handoff: il disaccoppiamento è un **nuovo lavoro**, non una funzione già attiva. Nessun valore di frequenza numerica è stato deliberato: 15m/1h/4h/24h sono solo ipotesi; le cadenze, i limiti, le soglie d'intensificazione, il ritorno alla normalità, le sospensioni Android, la storia, FolderSync/Drive, gli alert e il confine Futures devono essere **progettati quantitativamente e misurati prima dello sviluppo G2**. Una chat apposita progetta, la Costruttrice collabora alle prove di fattibilità, la Supervisione valuta, **l'autore approva le scelte**, e solo dopo la Costruttrice implementa con prove reali sul Samsung. Questo lavoro alimenta KDD-03/24/28/29, non introduce nuove caselle né una seconda roadmap.


## PROTOCOLLO DI SUBENTRO VINCOLANTE — 20 NOVEMBRE 2026

**Destinatario:** ogni nuova Supervisione apicale. Il mandato è un ordine di acquisizione, comprensione e ricostruzione, non un'autorizzazione a progettare o codificare. I capitoli storici sottostanti restano da leggere integralmente, non competono con il checkpoint in testa. **Nessuna dichiarazione di subentro completato, nessuna nuova delega, valutazione conclusiva, GO o stato PASS prima di aver superato i gate che seguono.**

**Gate A — Fonti e letture integrali, senza scelta discrezionale.** Recuperare dal repository vivo e leggere dal primo all'ultimo byte `README.md`, incluso interamente il mandato originale e le rettifiche; `GOVERNO_KDD.md` senza estratti; `ROADMAP_KDD.md` integralmente, con ognuno dei 29 requisiti e ogni nota; questo `SUBENTRO_SUPERVISIONE_APICALE.md` integralmente fino alla sentinella finale `KDD-SUP-SUBENTRO-INTEGRALE-EOF-20261028-FINE`, incluse TUTTE le attualizzazioni storiche; `AGGIORNAMENTI_TERMUX.md`, `IMPORTAZIONE_SICURA.md`, `NAVIGATORE_ONCHAIN_V001.md`, `GIUDIZIO_DELTA_SPOT_G0_G2.md` e gli originali correlati. Nessun operatore può decidere che un documento intero, un archivio, una sezione lontana dall'incarico o una parte della storia sia superflua: stabilire la rilevanza soltanto DOPO averla letta. Vietate letture sostitutive attraverso snippet, ricerca testuale, memorie, riassunti precedenti o elenco dei titoli. Su ogni troncamento ricominciare dall'ultima riga acquisita e continuare in intervalli contigui fino a EOF. Registrare fonte, ref, SHA, intervalli e conferma EOF; file non raggiungibile = `NON_ACQUISITO`, senza inventare l'esito.

**Gate B — Inventario e lettura reale di GitHub.** Ottenere HEAD di `main` e albero ricorsivo, verificare che non sia troncato e contabilizzare ogni file e cartella; il riferimento al 20/11 conta 85 voci, ma il numero VA RICALCOLATO. Leggere fino a EOF tutti i sorgenti di prima parte, i test, gli script, workflow, cataloghi, file di contratto e rapporti originali necessari a ricostruire l'intero prodotto, non soltanto i file che contengono una parola cercata. Include, senza eccezioni arbitrarie, acquisizione delle catene Spot, wallet, on-chain/DeFi, fondamentali, macro, Futures, scheduler, dashboard e ponte GPT; l'inventario dei file test e `collaudi/` va riconciliato con gli esiti dichiarati. Asset vendor: identificare versione, licenza, API realmente usate e collegamento alla UI, esaminando nel dettaglio i punti impiegati; non attribuire proprietà al JS minificato senza prova. Per ogni originale registrare percorso, commit/blob SHA, dimensione/righe ove note, intervalli letti ed EOF; distinguere `LOCALIZZATO`, `LETTO_EOF`, `INTERCONNESSO`, `PROVATO_IN_CODICE`, `PROVATO_SAMSUNG` e `ACCETTATO`. Un elenco `def` o un numero di test verdi NON è lettura del codice. Se il limite di contesto impedisce l'acquisizione, continuare in sessioni con manifest persistente verificabile: non attribuirsi ciò che un altro ha letto e non proseguire con una conclusione su fonti mancanti.

**Gate C — Storia e autorità.** Elencare tutte le PR aperte e storiche pertinenti; acquisire per ognuna base/head, stato, patch e prove originali quando rilevanti, Red Team indipendenti, GO, merge e deploy. Numerose PR sperimentali vecchie risultano ancora `open`: ciò non le rende automaticamente candidate attive. Ricostruire `baseline → sviluppo → test Costruttrice → Red Team G0 → GO merge → main → GO deploy → versione runtime Samsung → prova consumer`. Verificare le date e le autorità; non promuovere un Draft a main, una CI a prova Android, un rapporto della Costruttrice a verifica indipendente, una presenza su Drive a freschezza economica. L'autore dà GO distinti; non presumerli dalla presenza di un mandato.

**Gate D — Drive, Samsung e provenienza.** Confrontare gli ambienti senza appiattirli: repository GitHub, clone sicuro sul Samsung, sorgenti del runtime Termux, processo HTTP `127.0.0.1:8765`, cartella Android `/storage/emulated/0/KDD_TEST_SAMSUNG/`, flussi FolderSync, Drive privato e ChatGPT. Acquisire i documenti Drive progettuali secondo i link dei master, seguendo cartelle, pagine e riferimenti; elencare esplicitamente i file/ID non raggiunti. Poiché `Google_Drive.search` ha restituito falsi negativi, usare `list_folder` sull'ID cartella verificato e `fetch` tramite URL del file dall'elenco, con dimensione, SHA byte e provenienza. La mancata paginazione o l'elenco parziale impediscono conclusioni di assenza. Non pubblicare dati patrimoniali o credenziali in GitHub, non aprire permessi, non attivare refresh privati né toccare FolderSync senza GO. Se dispositivo e Drive non sono direttamente verificabili, registrare `NON_VERIFICATO_ORA` e riferire distintamente le prove storiche.

**Gate E — Comprensione dimostrata dei 29 requisiti.** Per **ciascuno** degli ID `KDD-01`…`KDD-29`, senza salti, descrivere dato grezzo/fonte e tempi, produttore, trasformazione, contratto e identità, persistenza, consumer locale/dashboard, consumer GPT, condizioni di errore, prove nel codice, eventuale prova live e relativa data, stato formale, requisito dipendente e carenza concreta. Se un anello manca: `NON_VERIFICATO` o `NON_REALIZZATO`, mai una funzione riempitiva inventata. Ricostruire il circuito in entrambe le direzioni: Kraken BalanceEx read-only → fotografia e T0 convenzionale → ricerca Spot/on-chain/fondamentali/macro → dossier → packet e bridge → FolderSync → Drive → recupero GPT con ricalcolo della freschezza → confronto ragionato patrimonio/alternative → proposta di sola prova fino a 29/29 → decisione espressa → Drive/FolderSync ritorno → consumer KDD/Chrome → evento, archivio e riesame. Collegare KDD-06–22 a KDD-02–05 e KDD-23/24/25/26, e KDD-27 (monitoraggio periodico indipendente dai dossier a richiesta), KDD-28 (Futures distinto Spot), KDD-29 (utilità economica da dimostrare). KDD-30 è evoluzione futura, non prerequisito aggiunto. Distinguere SHA logico nel nome da SHA256 dei byte, fonte da inferenza, saldi da mercato, storico da attuale, evento da ordine, presenza di asset da negoziabilità. Una narrazione eloquente senza questa matrice e queste dipendenze non dimostra comprensione.

**Gate F — Punto locale e ruoli non fungibili.** Il lavoro attuale NON è riparare FolderSync né inventare una seconda roadmap. Il collo di bottiglia attivo è l'assenza di un recuperatore ChatGPT→Drive persistente e autonomo. La Costruttrice ha consegnato ricognizione G0, proposto MCP privato, ricevuto mandato G2-A come testo di Supervisione subordinato a GO, e se ne ATTENDE il ritorno. La nuova Supervisione deve verificare l'effettivo GO e l'originale della nuova consegna, con ramo, commit, codice, prove, errori, alternative, permessi e limiti; non può trasformarsi in Costruttrice né svolgere Red Team del proprio codice. Valutare la fattibilità concreta di Google OAuth e del runtime/plugin, e in una fase separata la selezione dello strumento da nuova chat senza istruzioni tecniche. La #76 documentale non è una riparazione funzionale e resta senza GO-MERGE attestato. La proposta sintetica storica pendente è un altro gate KDD-24: nessuna decisione o sovrascrittura implicita.

**Gate G — Soglia di ammissione e prova della comprensione.** Prima di assumere il ruolo consegnare: (A) manifest dei file e letture intere con EOF e sentinella; (B) inventario ricorsivo Git, PR, allegati e originali Drive; (C) matrice completa 29/29 che connette produttori, trasformazioni, consumer, prove e carenze; (D) mappa dei due cicli, differenza fra codice, deploy e prova live, fra validatore ed errore; (E) genealogia dei commit e GO materialmente accertati; (F) situazione concreta della Costruttrice e dei lavori ancora in attesa; (G) limitazioni/documenti `NON_ACQUISITI` per i quali non è consentita un'affermazione conclusiva. Ogni informazione deve essere qualificata per data, versione e prova originale. Se manca un originale indispensabile, bloccare SOLO la conclusione dipendente, completando il resto senza scaricare sull'autore un lavoro di recupero accessibile agli strumenti. Non usare l'esaurimento del contesto per saltare file: preparare manifest/riferimenti persistenti e riprendere senza attestazioni false. Nessuna delega prematura, nessun test ridondante per evitare sviluppo, nessun dashboard o cantiere sostitutivo.

**Divieto di chiusura anticipata.** Progettare, costruire, certificare e approvare il medesimo risultato nella stessa chat è contrario alla governance. Un G0 guidato con URL/strumenti dimostra soltanto che il percorso manuale è possibile; non prova il recuperatore persistente. Una PR Draft non prova un merge; un file ricevuto non prova saldo/mercato aggiornati; un dossier accettato non prova giudizio economico GPT; una proposta pubblicata non prova un ordine. Senza dimostrazione documentale, funzionamento verificabile e atti autorizzativi pertinenti nessun KDD da PARZIALE può diventare COMPLETO. Ogni operazione patrimoniale resta vietata prima del completamento e collaudo di tutti i 29 requisiti e di successivo avallo espresso dell'autore; gli ordini non sono automatici.

---

**CONSEGNA OBBLIGATORIA PER OGNI SUBENTRANTE:** leggere integralmente i quattro master (fino a EOF e sentinella del presente file), gli originali progettuali e il codice/test effettivamente pertinenti; fissare SHAs e distinguere `main`, PR, clone Samsung, runtime vivo e Drive; spiegare **29 requisiti ↔ fonte → produttore → trasformazione → persistenza → consumer GPT e Chrome → evidenze → carenze → dipendenze**. Prima di incaricare la Costruttrice proporre **un solo avanzamento funzionale misurabile** che rimuova un collo di bottiglia reale del KDD, non quello più semplice da testare. Una prova sintetica è valida nel proprio perimetro, non sostituisce un passaggio sul telefono né giustifica infiniti nuovi audit. Completare tutti i 29 (inclusi KDD-27 e 28) prima del collaudo economico finale KDD-29; 29/29 e ulteriore avallo finanziario espresso restano due gate distinti. Nessun lavoro di codice, dati riservati, merge, deploy, spesa o trading per implicazione.

**Rettifica permanente dell'autore 13/11/2026:** è revocato qualsiasi importo obiettivo di liquidità operativa; KDD-05 conserva disponibilità, costi e alternative senza soglia prefissata. La PR #56 resta annullata e chiusa senza merge. Nessuna operazione finanziaria prima del gate completo 29/29 e del successivo avallo separato dell'autore; API Kraken di sola lettura, nessun trading automatizzato.

## Mandato di subentro del 13 novembre 2026 — disposizioni generali (stato operativo aggiornato sopra)

**Incarico:** KDD-SUP-SUBENTRO-INTEGRALE-20261113  
**Autorità:** autore e titolare del Kraken Decision Desk  
**Destinatario:** nuova Supervisione apicale, distinta dalla Costruttrice e dal Red Team  
**Regime di ingresso:** G0 — acquisizione, lettura, riconciliazione, valutazione e direzione tecnica. Nessun GO automatico a sviluppo, merge, deploy, operazioni, spese o accesso ai segreti.  
**Oggetto inderogabile:** completare, installare, verificare sul dispositivo ove pertinente e far accettare **tutti e 29** i requisiti del KDD, senza modificarne il significato.

**PRECEDENZA.** Le disposizioni generali espresse dall'autore il 13/11/2026 prevalgono su quelle storiche incompatibili; **stato, PR corrente e prossimo intervento sono quelli della Roadmap e della nota operativa corrente del 15/11 in testa a questo file**, sempre da verificare su GitHub. Le successive sezioni datate sono conservate come storia, non mandati concorrenti. La fonte vigente dei requisiti resta la ROADMAP; responsabilità e limiti nel GOVERNO e nel README.

## I. Divieto di reinterpretazione

I ventinove requisiti derivano da un progetto ingegneristico e **non** da suggerimenti della Supervisione. Il KDD richiesto è un solo sistema locale Samsung/Termux che osserva patrimonio e mercati, ricerca rischi/opportunità Spot e, nella componente prevista, Futures; integra analisi tecnica, fondamentali, tokenomics, on-chain, DeFi, flussi derivati, macro, geopolitica e notizie; rende possibile il giudizio proattivo GPT, la discussione con l'autore, la registrazione delle decisioni e il riesame degli esiti.

La Supervisione non è autorizzata a riprogettare il prodotto, sostituirne le priorità con proprie ipotesi o ridurlo a una dashboard, a una simulazione finanziaria, a uno scanner o a un calcolatore patrimoniale. Non utilizzare prove patrimoniali anticipate per stabilire **quali** dei 29 requisiti siano necessari: sono tutti da completare. Sono invece necessarie le prove tecniche e funzionali di **ciascun** requisito, senza le quali non si può chiuderlo.

Non basta scrivere «test PASS» o «codice su main»: servono integrazione, installazione quando richiesta, funzionamento effettivo, verifica dei consumer e accettazione esplicita secondo la ROADMAP.

**Rettifica 13/11/2026:** qualsiasi importo di liquidità operativa prestabilito è revocato, incluso il vecchio obiettivo di 150 USDC. KDD-05 mantiene il senso generale di analisi delle disponibilità, costi, cambi, impiego del capitale e alternative, **senza soglia-obiettivo**. Le funzioni storiche nate per importi fissi non costituiscono nuovo mandato. La **PR #56 è ANNULLATA e CLOSED, NON MERGED**: vietato riaprirla, usarla come base, integrarla o riproporne lo scopo come prossimo cantiere. La sua presenza nello storico non autorizza alcuna ripresa.

Nessuna operazione finanziaria reale prima del gate **29/29** e di una successiva autorizzazione finanziaria distinta dell'autore. Kraken resta con API di sola lettura; nessun ordine automatico. I GO di sviluppo, merge, installazione, accesso a dati privati, pubblicazione di una proposta e operazioni finanziarie sono indipendenti.

## II. Gerarchia e acquisizione obbligatoria

1. Decisioni espresse dell'autore, rettifiche e divieti successivi.
2. **README.md**, compreso il mandato congelato e tutte le rettifiche e appendici storiche.
3. **GOVERNO_KDD.md**, letto integralmente fino a EOF.
4. **ROADMAP_KDD.md**, unica checklist corrente KDD-01…KDD-29 e dipendenze, letta fino a EOF.
5. **SUBENTRO_SUPERVISIONE_APICALE.md**, dal primo byte alla sentinella di EOF storica, comprese questa e tutte le attualizzazioni.
6. **AGGIORNAMENTI_TERMUX.md**, **IMPORTAZIONE_SICURA.md**, **NAVIGATORE_ONCHAIN_V001.md**, **GIUDIZIO_DELTA_SPOT_G0_G2.md** e altri originali progettuali pertinenti individuati ricorsivamente.
7. Repository, codice, test, PR e revisioni originali, non le loro sintesi.
8. Progettazione e archivi pertinenti su Drive privato, quindi prova distinta dello stato Samsung.

**Lettura EOF significa lettura effettiva dell'originale intero.** Ogni risultato troncato richiede ripresa con finestre contigue, senza saltare righe, fino a EOF. Titolo, snippet, indice, riassunto di altra chat, memoria, ricerca o dichiarazione altrui NON sono prova di acquisizione. Verificare la sentinella terminale di questo file: \`KDD-SUP-SUBENTRO-INTEGRALE-EOF-20261028-FINE\`.

Per ciascuna fonte necessaria registrare nel checkpoint di ricognizione: URL/percorso, commit/ramo/blob SHA o ID/revisione Drive, byte/righe se noti, intervalli letti, EOF verificato, ruolo nel progetto, lacune e controversie riconciliate. Le qualifiche **INDICATO**, **LOCALIZZATO**, **LETTO_EOF**, **INTERCONNESSO**, **PROVATO IN CODICE**, **PROVATO SUL SAMSUNG**, **ACCETTATO** non sono intercambiabili.

**Persistenza ricorsiva:** prima di ogni nuova decisione di costruzione la Supervisione ricontrolla HEAD, versioni correnti dei quattro master, stato delle dipendenze e modifiche pertinenti. Per file invariati basta un'acquisizione EOF **propria e verificabile** già registrata nella stessa catena di lavoro; per file mutati, rileggere le parti mutate con il contesto necessario e riconciliare l'intero documento. In una nuova chat, se la precedente acquisizione non è dimostrabile con manifest e riferimenti, la lettura va rifatta. Non moltiplicare letture inutili di byte immutati, ma non lavorare mai su documenti non acquisiti o versioni scadute.

## III. Ricognizione ricorsiva completa di GitHub

Repository canonico: https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK

**Baseline documentale storica del mandato 13/11, NON corrente:** \`main@51937f9114cc30c510928d9ceefb49e7cd812699\`. Non utilizzarla per sviluppare né inferirne la versione Samsung: recuperare `main` e PR #64 all'istante del subentro.

- Inventariare ricorsivamente **tutto l'albero di main fino a EOF**, comprese sottocartelle, test, vendor, configurazioni e script di distribuzione; indicare eventuali limiti del servizio.
- Leggere integralmente fino a EOF i sorgenti e i test necessari a capire gli assi patrimoniale, Spot, on-chain/DeFi, derivati/Futures, macro/notizie, scheduler/alert, dashboard e ciclo GPT.
- Per ogni KDD-01…29 ricostruire **requisito → dati originari → acquisizione → identificazione/provenienza → trasformazioni → persistenza → consumer KDD → consumer GPT → UI → regressioni → prove live → lacuna per accettazione**. Se un collegamento non è verificato, indicarlo.
- Seguire ricorsivamente riferimenti e dipendenze reali dei sorgenti, senza usare un elenco di \`def\` come surrogato della lettura.
- Esaminare le PR storiche o aperte **solo** nella misura necessaria a ricostruire lo stato di main, difetti riparati, scelte progettuali e controprove indipendenti. Non assumere che un ramo storico prevalga sul prodotto canonico.
- Distinguere proposta, PR aperta, merge, main, clone locale, file realmente installato, processo in esecuzione, HTTP, comportamento effettivo, accettazione dell'autore.
- Individuare codici obsoleti, residui di importi revocati, duplicazioni, percorsi senza consumer e incompletezze sostanziali; non aprire un cantiere preventivo di bonifica non giustificato da una capacità mancante.

## IV. Ricognizione ricorsiva completa della documentazione Drive

**Canale privato KDD:** https://drive.google.com/drive/folders/1q0zcu0srqp9gRHwIHo6trCXLI0KCaH20  
**Dossier Samsung:** https://drive.google.com/drive/folders/1Fjh1gXhV6s2o8kKafVDZPBjjaTSYbNIr  
**Laboratorio SAF storico:** https://drive.google.com/drive/folders/1u7_AN8u1yKDEAZa6EYgaBOx0EGP2neOG  
**Documento ponte storico:** https://docs.google.com/document/d/1rmEhQ27PXk0nr2gJj4XBBesMwiWnCjAWVs_ZhLEjs70/edit

- Partire dalle cartelle verificate, **ma non limitarsi a esse o alle ricerche per il solo nome KDD**. Cercare mandati, specifiche, versioni, allegati, ZIP, relazioni, prove, fascicoli di progettazione, titoli alternativi e collegamenti indicati dagli originali.
- Visitare ricorsivamente i sottofolder, seguire la paginazione e distinguere liste complete da liste parziali; non affermare che Drive sia stato inventariato completamente se l'indice è incompleto.
- **Leggere integralmente fino a EOF i documenti progettuali pertinenti**, registrando ID, titolo, dimensione, versione/revisione quando disponibile, copertura e stato dell'originale.
- Confrontare ogni documento progettuale con README/GOVERNO/ROADMAP e con il codice. Riportare conflitti, decisione cronologicamente prevalente e fonti; non cancellare arbitrariamente il materiale storico.
- Distingere **specifiche**, **rapporti storici**, **fixture**, **packet operativi**, **proposte** e **dati privati**: il loro apparire sul Drive non dimostra funzione eseguita, freschezza né consenso.
- Dossier reale di riferimento documentale, da rivalutare come storico: \`kdd_handoff_93fb754432c49908326980abcc1b40c688b2ec9974405dca7e9f94fd2c7f90dc.json\`, https://drive.google.com/file/d/1C0cV8drhzZmIB2c1ElsiyC4T8nHzByx0/view (ricezione 12/11/2026). Non interpretarlo come fotografia attuale per una proposta eseguibile.
- Mai esportare credenziali, segreti, backup indiscriminati o dati finanziari privati su repository. Non mutare la configurazione FolderSync senza GO.

Ogni riferimento a un file non trovato va mantenuto come **NON ACQUISITO**, con la via di recupero e il limite tecnico preciso, senza inventare il contenuto.

## V. Stato iniziale, non certificazione universale

ROADMAP attuale alla consegna: **5/29 formalmente COMPLETO** — KDD-01, KDD-06, KDD-08, KDD-10, KDD-13 — e **24/29 da completare**. Le definizioni, gli stati intermedi e le lacune specifiche sono esclusivamente nelle 29 righe canoniche della Roadmap. Non riaprire requisiti già accettati senza prova materiale contraria; non chiuderne altri senza evidenza e GO pertinenti.

La ricezione automatica dell'handoff Android→Drive è un fatto documentato, non il collaudo dell'intero circuito. Il ritorno di nuove proposte GPT, la registrazione e il riesame, l'attività ricorrente KDD-27, la componente Futures KDD-28 e la qualità economica KDD-29 devono essere accertati secondo i rispettivi requisiti. **KDD-30** resta una futura evoluzione documentata, senza trasformarsi in un trentesimo veto al gate 29/29.

## VI. Responsabilità e direzione effettiva

**Supervisione:** legge e comprende il sistema intero; sceglie il prossimo lavoro *in base alle dipendenze già deliberate*; formula mandato alla Costruttrice; verifica integrazioni e prove; richiede controprove avversarie quando c'è rischio concreto; sottopone GO necessari all'autore; aggiorna lo stato canonico. Non assume stabilmente il ruolo della Costruttrice né cambia il prodotto in funzione della propria facilità di programmazione.

**Costruttrice:** sviluppa su ramo G2 circoscritto, riusa infrastrutture presenti, produce codice, test e prove verificabili. Non integra o installa senza GO separato.

**Red Team:** tenta di falsificare difetti tecnici pertinenti in G0, indipendentemente dalla Costruttrice, senza alterare main.

**Autore:** decide destinazione, modifiche del mandato, accettazione, merge/installazione quando richiesti e — esclusivamente dopo il gate completo — eventuali scelte finanziarie reali.

Non usare Desktop Commander come infrastruttura ordinaria o consumer necessario di KDD; nessun lavoro oneroso API o cambio credenziali implicito.

Non aprire nuovi documenti di governo, checklist alternative, micro-PR scollegate o studi ripetitivi. **Se esiste una PR G2 autorizzata e aperta, riprendere quel ramo e far progredire il codice**, senza sostituire l'esecuzione con commenti, nuovi mandati o piani. Una lettura completata è condizione per costruire, non un pretesto per rinviare. Ogni lavoro deve rispettare il requisito, il comportamento mancante, le prove concrete e le dipendenze della Roadmap. Il successo è una funzione reale aggiunta e dimostrata, non un numero di commit.

## VII. Prima consegna indispensabile per il subentro

Prima di autorizzare o dirigere un'altra tranche G2, produrre nella chat:

**A. Inventario fonti EOF:** master GitHub, documenti di progettazione Drive, riferimenti, SHA/ID, estensione e intervalli acquisiti, file non raggiunti e limiti reali.

**B. Inventario ricorsivo Git:** tree e file pertinenti, dipendenze effettive dei consumer, test e versioni.

**C. Architettura unica verificata:** flusso dal saldo e dal mercato all'osservazione KDD, alla ricerca e proposta GPT, alla discussione dell'autore, al ritorno controllato su Samsung, archivio, alert e riesame.

**D. Stato 29/29:** per ciascun requisito distinguere specifica, codice, collegamenti, installazione, test, osservazioni Samsung e formale accettazione; non creare una seconda roadmap.

**E. Difetti reali e piano di completamento:** ciò che manca funzionalmente, in ordine di dipendenze già approvato, e **UN incarico sostanziale alla Costruttrice** che avanzi verso 29/29. Escludere la PR #56 e la soglia monetaria revocata.

Non presentare come attestato quanto non è stato direttamente verificato. Non chiedere all'autore di riscrivere o rispiegare decisioni presenti negli originali. Se un documento originale non è accessibile, dichiarare precisamente lo STOP locale e completare tutte le altre letture possibili.

**Soglia di accettazione del subentro:** letture EOF documentate, ricognizione ricorsiva verificabile di GitHub e Drive, interconnessione dei moduli e restituzione di un concreto incarico costruttivo fedele ai requisiti. Un rapporto eloquente, senza acquisizione e direzione concreta, non soddisfa il mandato.

**SENTINELLA DELLA PRESENTE ATTUALIZZAZIONE: KDD-SUP-SUBENTRO-INTEGRALE-20261113-EOF**

---

## ATTUALIZZAZIONE OPERATIVA VINCOLANTE — 10 NOVEMBRE 2026

**Incarico:** KDD-SUP-SUBENTRO-20261110-G0-EOF. **Autorità:** autore/titolare. **Destinataria:** nuova chat di Supervisione apicale, distinta da Costruttrice e Red Team. **Regime di ingresso: G0**, senza nuovo GO a codificare, integrare, distribuire, modificare dati privati o movimentare fondi. Questa sezione prevale **per lo stato corrente e il primo compito** sulle fotografie del 28 ottobre, 3, 6 e 7 novembre qui conservate; non abroga il mandato originale o il Governo.

**Scopo concreto:** assicurare continuità della direzione dell'unico KDD e portare alla realizzazione **tutti i 29 requisiti canonici**, anziché usare audit, microcorrezioni, approfondimenti sulla governance o l'accesso al telefono come surrogato della costruzione. La nuova Supervisione deve applicare i controlli necessari e proporzionati, far riparare il solo guasto materiale documentato, sbloccare l'installazione e tornare immediatamente alle capacità decisionali mancanti.

### A. Gerarchia, letture integrali e divieto di inferenza sostitutiva

**PRIMA di impartire un nuovo mandato o raccomandare un GO**, acquisire personalmente le seguenti fonti GitHub nelle versioni effettive: (1) l'intero messaggio dell'autore che conferisce il subentro, fino al suo eventuale EOF; (2) **questo stesso file, compreso tutto lo storico e la sentinella terminale del 28 ottobre**; (3) [README.md](README.md) fino a EOF, incluse le rettifiche dell'autore, il mandato originale del 17–22 ottobre e l'archivio; (4) [GOVERNO_KDD.md](GOVERNO_KDD.md) fino a EOF; (5) [ROADMAP_KDD.md](ROADMAP_KDD.md) fino a EOF, con **esattamente 29 ID KDD-01…KDD-29**; (6) [AGGIORNAMENTI_TERMUX.md](AGGIORNAMENTI_TERMUX.md) fino a EOF; (7) la diagnosi reale del deploy [PR #49, commento 6763033357](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/issues/49#issuecomment-6763033357), il rapporto di chiusura dei difetti RT2, la cronologia della PR #49 e le prove/il codice pertinenti al solo problema attuale.

**Metodo non eludibile:** leggere il testo completo **anche quando il collegamento mostra solo un estratto**. Per ogni risposta troncata, recuperare esattamente i segmenti successivi senza saltare intervalli; controllare la sentinella finale quando prevista. Documentare percorso, ref/commit/blob e intervallo o dimensione acquisita. Per il codice direttamente interessato leggere l'intero diff pertinente, le funzioni invocate e i test reali, senza confondere la descrizione del rapporto con la sorgente. Non è richiesto rileggere indiscriminatamente ogni storico di tutte le PR già chiuse per fingere un'acquisizione universale: seguire invece le dipendenze concrete e approfondire gli originali rilevanti.

**Quattro stati obbligatori e distinti:**
- **LETTO EOF** = originale realmente acquisito fino all'ultima riga.
- **COMPRESO E INTERCONNESSO** = ricostruiti scopo, producer, trasformazione, persistenza, consumer, fallimento e conseguenza.
- **VERIFICATO CON** = prova propria identificabile, su sorgente/HEAD e ambiente indicati, con esito e limiti.
- **NON ACQUISITO / NON VERIFICATO** = non ricostruibile dai materiali direttamente ottenuti.

È vietato affermare o insinuare «verificato» sulla base di snippet, riepiloghi, memoria, nome di funzione, CI dichiarata da terzi o prova effettuata da un'altra chat. Le letture della Supervisione uscente possono orientare, **non si ereditano come LETTO EOF**. Se una fonte manca, dichiararlo e circoscrivere ciò che resta verificabile, senza inventare contenuti e senza bloccare attività indipendenti.

**Gerarchia:** mandato vigente dell'autore e rettifiche espresse; GOVERNO per scopi/autorità/vincoli duraturi; README per architettura e mandato originale, distinguendo le sezioni storiche; ROADMAP come **unica fotografia corrente, priorità e prossima dipendenza**; PR/commit/test per evidenze tecniche; Samsung e Drive per stato effettivo separato. Non generare documenti di governo o roadmap paralleli. Solo la Supervisione modifica README/ROADMAP attuali, sostituendo affermazioni superate e preservando la storia.

### B. Visione generale immutabile da tenere davanti a ogni microattività

**Un solo KDD autonomo sul Samsung/Termux, un solo patrimonio crypto intero, gestione strategica attiva e operatività flessibile Spot/Futures.** Il patrimonio strategico prevalente è gestibile e rivedibile: mantenere, aumentare, alleggerire, uscire, ruotare o restare fermi sono alternative da confrontare, mai prescrizioni automatiche. Nessun token è intoccabile e non esistono soglie arbitrarie generali di detenzione, allocazione o leva. I Futures long/short fanno parte del mandato complessivo, con **quota minoritaria**, rischio del collaterale e possibili effetti del wallet cross/unified da distinguere esplicitamente; non sono già funzionalità operative disponibili.

**Catena di successo:** KDD osserva saldi Kraken in sola lettura e mercati → qualifica tecnica, fondamentale, on-chain, macro e rischi di **tutte** le posizioni e dei candidati → dossier datato → GPT in chat ricerca criticamente, interpreta e propone alternative motivate → autore discute e decide → proposta autorizzata alla sola pubblicazione torna da Drive/FolderSync al KDD → dashboard Samsung, archivio e riesame su dati successivi. Il trasporto deve funzionare senza premere manualmente «Sincronizza» nel singolo ciclo avviato in chat. **Nessun ordine automatico né API private di trading.** Un test, un grafico, un hash, una CI, un handoff o una proposta non sono da soli una decisione utile.

**Regola finanziaria inderogabile, GOVERNO §0-bis (09/11):** fino alla dimostrazione del funzionamento di **29/29 requisiti**, tutte le proposte e le simulazioni di ricomposizione sono **SOLO COLLAUDO**. Nessun GO a conversioni EUR/USDC, vendite/acquisti, operazioni o avalli finanziari anticipati. Quando i 29 requisiti saranno provati, l'eventuale avallo finanziario richiederà comunque **nuovo consenso espresso**. Autorizzazioni a lettura, G2 codice, merge, deploy, dati privati, pubblicazione di una proposta e operazione finanziaria sono **distinte e non trasferibili per implicazione**.

**Ordine delle dipendenze approvato 07/11:** KDD-06…22, cioè capacità di mercato, indicatori, flussi, fondamentali, on-chain e contesto, prima del giudizio economico completo KDD-02…05; poi KDD-23 GPT, KDD-25/26 proposta/decisione/storico, KDD-29 utilità. KDD-01 (Kraken read-only) e KDD-24 (trasporto bidirezionale) sono basi con prove reali limitate, non scorciatoie per la qualità economica. KDD-27 sorveglianza e KDD-28 Futures restano obbligatori. Nessun KDD-01…29 risulta formalmente chiuso: **0/29** è lo stato amministrativo, non un'affermazione che il codice precedente sia inutilizzabile. Non cambiare ID, cancellare requisiti o ripartire da una nuova architettura.

### C. Fotografia probatoria alla consegna — verificata su GitHub il 10/11/2026

Repository: [gionatamartini66-rgb/KRAKEN_DECISION_DESK](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK). **main HEAD al controllo:** \`8ecd5d24385f3d1058f0e17e2f4216cea3b1c735\` (ultimo aggiornamento documentale Roadmap, **non** nuova installazione). Il GOVERNO è stato ricondotto al testo canonico precedente: blob \`eba5b25a7c7e4917e1da073bf65620e3b280f8b7\`; non riaggiungere la disposizione ridondante su Desktop Commander. La ROADMAP descrive il tentativo di deploy e il guasto attuale.

**[PR #49](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/49):** **MERGED/CLOSED**, HEAD candidata \`9d469fac89a01bbcd607037d5f66d5e5a83a66d7\`, commit di merge \`ee828c3e49b1bfc442729c9b3f0e307241363be7\`, [CI #42781142769](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/actions/runs/42781142769) **4/4 SUCCESS**. RT1 su \`d8819ae…\` STOP e RT2 su \`9e2d45c…\` STOP furono riparati prima del merge. Non ripetere questi rapporti come verdetti sulla HEAD finale. La PR #49 introduce soltanto una **prima tranche KDD-16**: funding pubblico PF_XBTUSD, campione massimo 100 esecuzioni/liquidazioni/block e distribuzione per prezzo limitata al campione. **Non** heatmap globale, whale identificati, volume globale o gestione operativa Futures.

**[PR #48](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/48):** al controllo **OPEN/DRAFT, NON MERGED**, HEAD \`560367b505f931dbf4c84386e5f1dcae9f55b13f\`. Oggetto distinto: qualità del giudizio patrimoniale e rapporto fra lacune shortlist/idoneità. Non confonderla con la riparazione #49; nessun GO merge implicito.

**Samsung/Termux al tentativo del 10/11:** precedente baseline applicativa nel runtime, risultante da commit \`382a1a120c6ca17f9fc5eb042834964f9d01d693\` prima dei successivi commit documentali/merge. Directory operativa \`~/kraken-decision-desk/KRAKEN_DECISION_DESK_V001/\`; clone sicuro \`~/kraken-decision-desk/KDD_GITHUB_SAFE/\`; browser locale \`http://127.0.0.1:8765/\`. Con GO **deploy PR #49** esplicito, la Supervisione uscente ha aggiornato **solo il clone** alla HEAD di merge \`ee828c3e49b1bfc442729c9b3f0e307241363be7\` con fast-forward e stato Git pulito. Il comando ufficiale \`python -B scripts/kdd_aggiorna.py --check\` ha restituito **STOP SICUREZZA**: **299 test, 2 FAIL, 1 ERROR**. **Non è mai stato eseguito \`--apply\`**. I cinque file che l'updater avrebbe sostituito sono \`dossier_trade.py\`, \`kdd_futures_flow.py\`, \`test_kdd_futures_flow.py\`, \`scripts/kdd_wallet_packet_g0.py\`, \`scripts/kdd_bridge_g2.py\`; i file live non sono stati modificati. Verifica successiva: moduli live preesistenti e \`kdd_futures_flow.py\` ancora assente dal runtime; rotte \`/\`, \`/gpt\`, \`/stato\` HTTP 200. **HTTP 200 non equivale a installazione della #49.** Nessun dato finanziario, T0, credenziale o saldo alterato.

**Cause del precheck documentate con prove sul clone originale:**
1. \`test_decision_desk.DeskTests.test_local_t0_original_integrity_and_balances_are_separate\`: test richiede un'attestazione **storica indipendente T0**, assente dall'ambiente del comando; il file T0 originale locale e la sua impronta nel portafoglio erano coerenti. Il confronto con una prova storica indipendente precedente è stato positivo. **Non** derivare una presunta attestazione indipendente dal T0 corrente; non pubblicare valori o prova privata su GitHub.
2. \`test_kdd_futures_flow.FuturesFlowTests.test_read_time_summary_counts_bins_and_raw_tape_cannot_disagree\`: il test assegna \`type="liquidation"\` al primo trade, che ha **già** quel tipo nella fixture, per poi pretendere erroneamente \`NON_VERIFICATO\`. La mancata modifica preserva correttamente \`CAMPIONE_RECENTE\`. Il test va corretto affinché la mutazione sia reale, senza ridurre la copertura.
3. \`test_kdd_futures_flow.FuturesFlowTests.test_real_producer_serialized_packet_and_bridge_revalidate\`: import legacy di \`kdd_wallet_packet_g0\` non risolto nel runner normale Termux. Con import risolto emerge anche **un guasto funzionale vero**: \`kdd_futures_flow.at_read(raw)\` conserva funding/trade validati ma elimina i campi verificati \`fonte_ticker\`, \`fonte_trades\` e \`richieste_pubbliche_massime\`. Quindi \`at_read(at_read(raw))\`, percorso realmente sollecitato dal packet seguito da \`bridge.read_context()\`, declassa **dati validi** a \`NON_VERIFICATO\`. Una controprova isolata ha riprodotto il guasto; ricostituendo **solo i tre campi di provenienza** in memoria la doppia lettura recupera correttamente \`OSSERVATO\` e \`CAMPIONE_RECENTE\`. Ciò delimita la riparazione, non autorizza ad allentare la rivalidazione.
**Diagnosi integrale autentica:** [commento GitHub #6763033357](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/issues/49#issuecomment-6763033357). Le prove sono state eseguite sulla copia del clone Samsung; la nuova chat **non deve attribuirsele come esecuzioni proprie**.

### D. Prossimo e UNICO incarico operativo — riparazione puntuale G2, poi ripresa dei requisiti

La Supervisione uscente ha preparato **in chat** il mandato alla Costruttrice per il ripristino del passaggio Futures→GPT e del precheck Android. **Un mandato consegnato in chat non dimostra che la Costruttrice lo abbia letto, avviato o consegnato; al momento di questa verifica NON è stata acquisita una nuova PR correttiva.** La nuova Supervisione deve cercare la sua eventuale consegna **prima** di aprire un incarico duplicato.

**Ambito NON ampliabile della nuova PR correttiva:** (i) rendere idempotente \`at_read\` per l'evidenza valida e sanificata, mantenendo provenienza e budget **da costanti fidate**, senza accettare falsificazioni; (ii) far passare un dossier valido attraverso \`dossier_trade\` → packet → serializzazione → \`bridge.read_context\` con dato positivo, e far decadere campioni realmente falsificati/scaduti; (iii) correggere la mutazione-test del campo \`type\`; (iv) correggere import/runner della prova end-to-end su Termux; (v) usare l'attestazione T0 **precedente e indipendente** solo nell'ambiente locale protetto del test, preservandone il vincolo. Non riscrivere Spot, wallet, macro, sicurezza, UI o strategia; non introdurre framework per evitare tre errori concreti.

**Prova d'uscita:** suite mirata sui due bug di test e doppia lettura positiva/negativa; CI della nuova HEAD esatta; \`kdd_aggiorna --check\` sul Samsung soltanto **quando il codice corretto è pronto e l'uso del dispositivo è giustificato/autorizzato**, senza applicare o riavviare in G0. Se i gate sono superati e il rischio residuale è circoscritto, la Supervisione formula un giudizio proporzionato e sottopone **GO merge della nuova PR** all'autore, poi **GO deploy distinto**; non aprire automaticamente un nuovo RT generalista. Il GO deploy concesso per il tentativo fallito della #49 **non è un'autorizzazione illimitata a distribuire codice successivo**.

**Immediatamente dopo la riparazione:** la Supervisione riporta l'attività alle capacità più difficili ed economicamente utili dei 29 requisiti, secondo la ROADMAP. I primi obiettivi da non eludere riguardano copertura Futures/liquidazioni reale oltre il campione, metriche on-chain e DeFi pertinenti, tokenomics/unlock e notizie affidabili, scenario macro/regime, sintesi asset per asset, alternative, proposta GPT, continuità e qualità economica. Ogni modulo va misurato per (a) dato/risultato concreto, (b) fonte/copertura/freschezza, (c) consumer effettivo e uso nella decisione, (d) lacuna residua e sua conseguenza; **non** per numero di nuovi test o pannelli. Evitare sprint indefiniti di «sola diagnosi» quando una riparazione puntuale basta.

### E. Desktop Commander — risorsa limitata, nessuna dipendenza del KDD

L'autore ha precisato espressamente che **Desktop Commander serve, quando indispensabile, soltanto alla costruzione e alle prove reali di installazione/collaudo, non all'uso del KDD**. Il prodotto deve rimanere autonomo sul Samsung con Desktop Commander scollegato o senza crediti. DC non fa parte del runtime, non è una fonte dati, non trasporta ordinariamente file fra GPT e KDD e non può essere richiesto per dashboard, raccolta, FolderSync, gestione dossier o decisioni.

La Supervisione, la Costruttrice e i revisori devono **minimizzare le chiamate DC**: consultare codice e documenti con GitHub, usare CI e fixture isolate, non aprire la connessione per monitoraggi, letture già disponibili, curiosità diagnostiche o controlli rituali. Usare eventualmente il dispositivo solo per una necessità costruttiva concreta non riproducibile altrove, con obiettivo, GO e chiamate raggruppate; fermarsi quando la prova è sufficiente. I crediti DC appartengono all'autore e non vanno dissipati. Non riaprire la governance per reiterare questa regola: è una decisione d'uso esplicita dell'autore coerente con proporzionalità e autonomia del progetto.

### F. Responsabilità e decisioni — disciplina rigorosa senza rituali

**Autore:** unico titolare degli obiettivi, dei GO per interventi e delle eventuali operazioni manuali di mercato. **Supervisione:** legge, comprende, dirige, valuta e aggiorna il quadro documentale; non si sostituisce stabilmente alla Costruttrice. **Costruttrice:** una PR G2 circoscritta, codice/test reali e consegna HEAD/CI/limiti; non sceglie GO e non distribuisce autonomamente. **Red Team:** revisione indipendente proporzionata su copie isolate, solo quando un rischio specifico lo richiede, senza modifiche al repository o allo smartphone.

Prima di un controllo o di una richiesta aggiuntiva esplicitare in poche righe: **guasto credibile, impatto economico/funzionale, test minimo che lo falsifica, decisione che ne consegue**. Un rischio remoto non dimostrato non diventa STOP infinito; una catena verso GPT realmente rotta sì. Non usare l'esistenza di 29 requisiti per ampliare il piccolo mandato di riparazione. Non chiedere all'autore di ricopiare documenti presenti in GitHub. Non pretendere che una chat diversa abbia eseguito il lavoro per il semplice fatto di averne ricevuto un incarico.

### G. Consegna obbligatoria della nuova Supervisione al termine dell'acquisizione

Produrre **un rapporto breve ma controllabile**, senza nascondersi dietro il conteggio delle letture:
1. **Inventario EOF** delle fonti canoniche e dei pertinenti sorgenti/test; indicare versioni e lacune reali.
2. **Scopo unitario** e sequenza dei 29 requisiti, con stato di chiusura amministrativa **0/29** finché non deliberato diversamente.
3. **Stati separati e aggiornati**: HEAD main, PR #49 merged, PR #48 open/draft, clone Samsung, runtime Samsung, Drive/GPT; nessuna equivalenza implicita.
4. **Difetto bloccante attuale** spiegato con percorso e controesempio: doppia lettura Futures→GPT; separare i due guasti dei test e l'attestazione storica T0.
5. **Unica azione successiva**, con incaricato e criteri verificabili: ricevere/consegnare la piccola PR correttiva, test mirati, CI e precheck, GO autore separati.
6. **Nessun nuovo cantiere** di audit o di documentazione prima di rimettere in funzione il percorso; successiva priorità sostanziale fra i 29 punti. Se un dato non è acquisito, etichettarlo espressamente e non inferirlo.

L'acquisizione non è un fine: terminata la ricostruzione pertinente, assumere la direzione della riparazione e procedere alla verifica funzionale. Nessun cronoprogramma inventato, nessuna promessa di lavoro autonomo fra chat.

**FINE DELL'ATTUALIZZAZIONE DEL 10/11/2026. SEGUE, INALTERATO, IL MANDATO STORICO. LEGGERE COMUNQUE FINO ALL'ULTIMA SENTINELLA TERMINALE DEL FILE.**
**SENTINELLA DI QUESTA ATTUALIZZAZIONE: KDD-SUP-SUBENTRO-20261110-G0-EOF**

---


## Attualizzazione operativa — 7 novembre 2026 (senza alterare il mandato del 6 novembre)

**L'autore ha corretto espressamente l'ordine delle dipendenze:** «non si può fare una casa senza muri». Il collaudo tecnico che costituisce il *primo incarico* del mandato del 06/11 **è stato eseguito**: proposta sintetica JSON attraverso GPT → Drive → FolderSync automatico → Android → importazione KDD → home HTTP `/` e `/gpt`, risposta **NON APPROVATA**; dossier JSON completo trasferito in direzione inversa con stessa impronta. Su autorizzazione dell'autore la proposta del 31/10 è stata **RIFIUTATA** e registrata (1 evento, 0 approvazioni). Saldo e mercato Kraken rinnovati il 06/11, dieci posizioni, nessun ordine. La proposta usata per la prova è **solo sintetica**, non una scelta economica.

**Prossimo incarico vigente:** come stabilito nella [ROADMAP canonica](ROADMAP_KDD.md), prima verificare e completare i **produttori di evidenze KDD-06–22**, in modo che i dati dei mercati, flussi, fondamentali e contesto confluiscano davvero, con fonti/tempi/limiti, nel dossier. Solo dopo un gate di adeguatezza analitica affrontare la sintesi patrimoniale KDD-02–05 e il giudizio GPT KDD-23, seguiti da proposta KDD-25, deliberazione/archivio KDD-26 e prova d'utilità KDD-29. KDD-01 e il trasporto tecnico KDD-24 sono fondazioni acquisite nei limiti provati. **Nessuna chiusura formale automatica dei 29 requisiti.** KDD-27 e 28 conservano la propria destinazione futura.

Le istruzioni e le prove del mandato del 6 novembre, integralmente conservate sotto, sono **riferite al suo primo incarico e alla fotografia di allora**: non riaprire quel gate né usarle per invertire la precedenza ora decisa dall'autore. I vincoli di lettura EOF, ruoli, GO distinti, natura personale e privata e Kraken solo lettura rimangono validi.

---

## MANDATO ATTUALE DI PASSAGGIO DI CONSEGNE — 6 NOVEMBRE 2026
**Identificativo:** KDD-SUP-HANDOFF-20261106-G0
**Autorità:** autore del KDD. **Destinataria:** nuova chat di Supervisione apicale.
**Ambito del primo subentro:** G0, lettura, verifica, direzione e preparazione del prossimo collaudo. L'autorizzazione dell'autore a **aggiornare la documentazione del repository** non equivale a GO futuri per modifiche applicative, merge, deploy, dati privati, cambio di configurazione FolderSync, API Kraken o operazioni finanziarie.

### 1. Gerarchia e regola di lettura
Questa sezione è l'**istruzione attuale di subentro**, inserita nel file canonico esistente. Le sezioni successive del 28 ottobre e le note del 3 novembre devono essere **lette integralmente come documenti storici**, ma non prevalgono sullo stato verificato successivamente. Il [GOVERNO](GOVERNO_KDD.md) stabilisce i vincoli duraturi; la [ROADMAP](ROADMAP_KDD.md) è l'**unica fonte dello stato corrente e del prossimo lavoro**; il [README](README.md) contiene architettura e mandato originale integrale. Non creare una seconda Roadmap o nuovi documenti di metagoverno.

Prima di operare, la nuova Supervisione acquisisce **direttamente fino a EOF**, senza sostituzione mediante memoria, riassunti o risultati di ricerca: **(a)** il testo integrale del messaggio dell'autore che conferisce l'incarico nella nuova chat, compreso l'eventuale marcatore finale; **(b)** questo file fino alla sentinella finale storica; **(c)** README fino a EOF compreso il mandato originale; **(d)** GOVERNO, ROADMAP, AGGIORNAMENTI_TERMUX e istruzioni operative pertinenti fino a EOF; **(e)** PR, rapporti, diff, sorgenti, test e interfacce coinvolte dal primo lavoro, per i quali deve leggere integralmente quanto è necessario a ricostruire il percorso. Se una fonte è troncata, riprendere dall'esatto punto successivo, senza buchi e fino alla fine; se inaccessibile, registrare **NON ACQUISITO** e non supporne il contenuto. La nuova chat non eredita attestazioni di lettura da chat precedenti.

Per ciascuna fonte distinguere esplicitamente **LETTO EOF** (lettura realmente completa), **COMPRESO E INTERCONNESSO** (rapporti produttore → trasformazioni → file/Drive → consumer → UI), **VERIFICATO CON** (prova concreta, ambiente, risultato, versione) e **NON ACQUISITO / NON VERIFICATO**. Non chiamare «verifica» la semplice lettura o il PASS dichiarato da altri.

### 2. Stato di consegna acquisito, non da presumere eternamente
Riferimento documentale al **06/11/2026**, da riverificare sul repository e sul dispositivo prima di agire:

- **GitHub:** [PR #33](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/33) e [PR #34](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/34) **MERGED** con GO distinti dell'autore. Versione applicativa distribuita dal commit di main `e45ecaaa1814b281c6108bc2566f931a27132c92`; successiva riconciliazione **solo documentale** nella ROADMAP al commit `a6801da894b2e1b5e9b9bef6cdef4a8b0a3d6a43`. Un nuovo SHA documentale non dimostra un nuovo deploy.
- **Samsung/Termux:** il 06/11 il deploy #33/#34 è stato completato dopo un precedente tentativo della #33 fermato con rollback. Preflight e postflight riportano 227 test Desk più suite GPT/Android/R5 PASS, backup privato, cinque sorgenti identici al clone, riavvio di `serve.py` e HTTP 200 su `/` e `/gpt`. Il consumer GPT era inizialmente in STOP per continuità dello storico; dopo **autorizzazione distinta dell'autore**, riconciliazione privata di **zero eventi e zero approvazioni** con backup, nuova verifica di continuità PASS e pagine senza STOP. La proposta storica resta **NON APPROVATA**.
- **FolderSync/Drive:** il 05–06/11 è stato osservato un trasporto **automatico bidirezionale di file sintetici .txt**, senza pressione manuale di «Sincronizza». Non equivale all'importazione di una nuova proposta JSON. Un filtro `.txt` temporaneo della prova di ritorno va rimosso **solo con controllo/autorizzazione pertinenti**, preservando i filtri di produzione e senza sincronizzazione indiscriminata di Termux.
- **Economia:** l'ultima fotografia privata citata è del **02/11**, con dieci posizioni e 4TF acquisiti; **non è una fotografia corrente del 06/11**. La proposta del 31/10 è storica. Nessun ciclo economico nuovo su dati freschi con discussione, pubblicazione, scelta, archivio e riesame è stato collaudato. I **29 requisiti della Roadmap restano formalmente aperti**.

### 3. Primo incarico concreto, in ordine di dipendenza
1. Verificare l'ultima HEAD di `main`, il contenuto effettivo dei documenti canonici, le prove delle PR #33/#34, la versione applicativa **installata** e il suo servizio, senza confondere GitHub con Samsung o Drive.
2. Preparare **una nuova proposta JSON valida e interamente sintetica**, chiaramente distinta da quella storica. Identificare nei sorgenti veri di `scripts/kdd_drive_exchange.py`, `scripts/kdd_bridge_g2.py` e `serve.py` i requisiti di schema, i percorsi e le condizioni di importazione. Prima di scrivere nel canale Drive/FolderSync operativo chiedere il GO pertinente dell'autore; non sovrascrivere storico né simulare un'approvazione.
3. Con il GO necessario, collaudare **chat → Drive privato → FolderSync automatico → Samsung → importazione KDD → home Chrome** sulla proposta sintetica: stessa identità/versione e stato NON APPROVATA, senza intervento manuale di sincronizzazione. Verificare anche il fallimento sicuro e gli eventuali residui. Se si rompe, isolare **un difetto concreto** e delegare la minima riparazione G2 alla Costruttrice, con verifica indipendente proporzionata.
4. Solo dopo questo gate, e con nuova autorizzazione per dati privati ove richiesta, acquisire **fotografia e mercato freschi**, discutere in chat il patrimonio **intero** e le alternative, considerando le disponibilità quando pertinenti e senza obiettivi monetari predefiniti, formulare una proposta motivata, sottoporla all'autore, pubblicarla senza approvarla implicitamente, registrare l'eventuale decisione esplicita e riesaminarla successivamente. **Nessun ordine automatico**.

### 4. Disciplina, prova d'uscita e consegna successiva
La Supervisione dirige; la Costruttrice implementa su ramo e mandato circoscritti; il Red Team prova a falsificare senza scrivere il repository. Servono GO **distinti** dell'autore per merge, installazione, scrittura in dati privati e qualsiasi negoziazione; il consenso a **pubblicare una proposta** non è consenso a **comprare o vendere**. KDD è personale, non commerciale, e usa credenziali Kraken in sola lettura. Proteggere segreti e dati privati, senza proliferare difese forensi o cicli Red Team senza rischio concreto.

Nella prima risposta utile la subentrante deve produrre: **(i)** inventario delle fonti con letture EOF effettive e lacune; **(ii)** versione main, versione Samsung e prove distinte; **(iii)** percorso produttore/consumer del prossimo test; **(iv)** stato aperto dei 29 requisiti senza chiusure arbitrarie; **(v)** il singolo gate da eseguire, prova falsificabile, eventuale autorizzazione mancante e prossima azione. Aggiornare la sola ROADMAP quando cambia uno stato materiale, **sostituendo** la fotografia superata con data, SHA, evidenza e prossimo passo. Se la chat finisce, consegnare questi fatti e le lacune con link/commit; non pretendere che il successore ricostruisca la storia dalla memoria della chat.

**Fine della sezione operativa 06/11/2026. Segue il mandato storico integrale del 28/10 e note successive, da leggere comunque fino alla sentinella terminale EOF.**

---

> **PRECISAZIONE VINCOLANTE DELL'AUTORE — 05/11/2026.** **Prima regola della Supervisione:** KDD è un progetto personale e privato, **non commerciale né destinato alla commercializzazione**. Le API Kraken sono di **sola lettura**; il software non invia ordini e **non prevede trading automatico**; qualsiasi eventuale operazione è scelta ed eseguita manualmente dall'autore. Le transazioni on-chain sono in larga parte pubbliche, ma chiavi e dati locali non pubblici non vanno divulgati. **Sicurezza proporzionata ai rischi reali:** verificare ciò che serve davvero a evitare errori su dati, proposte e decisioni, senza moltiplicare meccanismi forensi o Red Team senza controesempi concreti. **Tutti i passi necessari e utili, senza scorciatoie e senza attività superflue.** Il criterio di riuscita è il circuito operativo reale Samsung/Termux ↔ FolderSync ↔ Drive privato ↔ ChatGPT/autore ↔ KDD, senza pressione manuale di «Sincronizza» nel ciclo avviato in chat, con proposta discutibile, decisione esplicita, archivio e riesame. Distinguere sempre PASS sintetici da verifica Android reale. Leggere [README](README.md), [GOVERNO](GOVERNO_KDD.md) e [ROADMAP](ROADMAP_KDD.md); questa precisazione non riscrive lo storico del mandato di subentro del 28/10 né autorizza merge/deploy.
>
> **NOTA DI ATTUALIZZAZIONE — 03/11/2026, senza modificare il mandato del 28 ottobre.** Le sezioni storiche che indicano la PR #21 e i suoi SHA come prima attività descrivono lo stato **del 28/10**, non quello corrente. Per chi subentra oggi: leggere fino a EOF il presente mandato, [README](README.md) con mandato originale, [GOVERNO](GOVERNO_KDD.md) e soprattutto la [ROADMAP](ROADMAP_KDD.md), ora con tutti i 29 requisiti e le loro dipendenze. Non chiedere all'autore di ricostruire la storia già conservata nel repo.
>
> **Stato di riferimento aggiornato al 03/11 dopo RT2, RT3 incaricato (nessun rapporto ancora acquisito):** Samsung applicativo documentato al 02/11 su `ba17ced6d51aedcb9ee19900f906f0127c912d57` (PR #30); PR #31 HEAD `8d8319073cf9b5edf9bb0f679e0f249dfd7882db`, DRAFT/non integrata, GitHub segnala `mergeable=false` su `main` documentale aggiornato: riconciliare prima di un eventuale merge con GO autore. PR #32 HEAD **`e89c7c187063a02ae25af630bc22055ba452dce8`**, DRAFT/non integrata, base PR #31: riparazione RT2-F2-DUP-WSNAME aggiunta dopo la precedente falsificazione RT2 sul commit `09bed987b22d2af6835de36682f47a473a36eed1`; [Actions #41642305461](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/actions/runs/41642305461) **4 job SUCCESS**. La Supervisione ha verificato codice, diff e test nuovi, non eseguito una controprova indipendente. **RT3 G0 mirato sullo SHA e89c7c... affidato all'altro revisore; verdict ancora assente in questa sessione.** Le riparazioni F1/F3/F4/F7 sono risultate favorevoli nel RT2; nessun nuovo cantiere oltre F2. Priorità dopo eventuale GO RT3 e autorizzazioni separate: integrare coerentemente PR #31 e #32, poi realizzare il ciclo GPT-chat → Samsung senza trasferimenti manuali (KDD-23/24/25), scelta/archivio/riesame (KDD-26/29), senza confondere merge, deploy e prova economica.
>
> **Ruoli per incarico dell'autore 03/11:** esclusivamente la **Supervisione** aggiorna README e ROADMAP; la **Costruttrice** sviluppa software su rami G2 nel perimetro affidato; il **Red Team G0** legge e falsifica su copie isolate, senza scrivere il repository. Solo l'autore dà GO distinti per merge, deploy e ordini. Un testo consegnato a un'altra chat non dimostra che quella chat abbia operato. Questa nota non conferisce automaticamente a una futura chat le letture e le verifiche già fatte da un'altra.

**Incarico:** KDD-SUP-SUBENTRO-INTEGRALE-EOF-20261028
**Data:** 28 ottobre 2026
**Autorità:** autore e titolare del Kraken Decision Desk
**Destinataria:** una NUOVA chat di Supervisione apicale, indipendente dalla Costruttrice e dai Red Team.
**Tipo di atto:** consegna dell'incarico nella PR già esistente; non crea un altro documento canonico o una nuova ROADMAP.
**Autorizzazione iniziale:** G0, acquisizione, ricostruzione, valutazione indipendente e direzione tecnica. Nessun GO a merge, deploy, accesso alle credenziali o operazioni finanziarie.

## 0. L'EOF DI QUESTO STESSO MANDATO È OBBLIGATORIO
Prima di qualsiasi altra attività, **leggere integralmente QUESTO commento**, dalle prime righe fino alla stringa terminale univoca **KDD-SUP-SUBENTRO-INTEGRALE-EOF-20261028-FINE**. Non basta visualizzare il primo blocco restituito da GitHub, un risultato di ricerca o un riassunto. Se GitHub tronca il commento, recuperare i segmenti mancanti mediante letture ripetute, fino alla conclusione. Accertarsi che la sezione finale non corregga o limiti quelle iniziali. L'EOF del presente mandato deve essere verificato prima di dichiararlo acquisito.

Una nuova chat non può considerare letto questo mandato perché un'altra chat lo ha scritto, riassunto o ricordato. Deve acquisirlo direttamente. Se un connettore rifiuta una lettura lunga, cambiare metodo autorizzato o interrogare un intervallo successivo; registrare l'eventuale ostacolo preciso. **L'impossibilità tecnica di acquisire un file non autorizza a inventarne il contenuto o dichiarare completato il subentro.**

## 1. RESPONSABILITÀ DELLA SUPERVISIONE
Il KDD riguarda un patrimonio finanziario reale, guadagnato dall'autore. La tutela dell'informazione patrimoniale, la precisione delle relazioni fra i dati e la qualità delle proposte decisionali sono requisiti sostanziali.

La Supervisione deve comprendere il progetto **dal macro al micro**, dirigere la Costruttrice, controllare la consegna, incaricare un Red Team indipendente e valutare i suoi controesempi. L'autore decide scopi, limiti e autorizzazioni. La Costruttrice realizza il software; il Red Team tenta di falsificarlo; la Supervisione decide come procedere tecnicamente, sottoponendo i GO necessari all'autore.

La Supervisione non può sostituire la direzione con programmazione continuativa svolta da sé, né una verifica con il semplice conteggio dei PASS della Costruttrice. Deve comprendere abbastanza il codice da scoprire errori di collegamento e semantica finanziaria. Non produrre mandati, matrici o registri aggiuntivi per rinviare il prodotto.

## 2. DESTINAZIONE: UN SOLO KDD
L'applicazione finale è un solo Kraken Decision Desk locale sul Samsung, via Termux, con interfaccia su 127.0.0.1:8765.

Deve integrare:
- gestione attiva del **patrimonio intero**, partendo dalle posizioni realmente detenute, con prospettive di mantenere, incrementare, alleggerire, uscire o ruotare, alternative e rischi;
- lettura Kraken privata **esclusivamente in sola lettura**, conti e disponibilità distinti da quotazioni e prezzi indicativi;
- universo Kraken Spot navigabile, screening economico ampio, approfondimenti sulle opportunità selezionate e quattro timeframe (15m, 1H, 4H, 1D) per ogni posizione o candidato sottoposto ad analisi approfondita;
- analisi tecnica, liquidità, order book, costi, valute, benchmark e flussi, senza confondere misure di mercati diversi;
- analisi fondamentale, tokenomics, sblocchi e diluizione, on-chain, macroeconomia, geopolitica e notizie con identificazione e provenienza attendibili;
- **contributo vivo di GPT:** ricerca propositiva di fonti, discussione con l'autore, alternative, ipotesi, rivalutazione dei dati e dei risultati;
- circuito controllato KDD Samsung → Drive → GPT ↔ autore → piano approvato → Drive/FolderSync → KDD, archivio e successive verifiche. La semplice presenza dei programmi, dei file o di un trasferimento manuale NON costituisce collaudo del circuito.

Nessun ordine finanziario automatico. Nessuna promessa di prezzo eseguibile. Nessun segreto o saldo reale in GitHub. Quattro timeframe "sulla pagina" e quattro timeframe "nel dossier GPT" sono consumer diversi: verificarne entrambi.

## 3. FONTI CANONICHE: RECUPERARE GLI ORIGINALI
Repository: https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK
ROADMAP unica: https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/blob/main/ROADMAP_KDD.md
README e mandato dell'autore: https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/blob/main/README.md
Governo: https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/blob/main/GOVERNO_KDD.md
PR candidata: https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/21
PR storica Spot: https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/20
PR navigatore/on-chain: https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/14
PR bridge e prove negative: #15–#17
Drive privato KDD: https://drive.google.com/drive/folders/1q0zcu0srqp9gRHwIHo6trCXLI0KCaH20

In Libreria ChatGPT cercare per nome e LEGGERE integralmente, ove pertinenti:
KDD_MANDATO_SUBENTRO_SUPERVISIONE_20261024.md;
KDD_HANDOFF_RIPARTENZA_2026-10-26.md;
KDD_RAPPORTO_FORENSE_G0_26_OTTOBRE_2026_RICONCILIATO.md;
KDD_SUPERVISIONE_APICALE_G0_SUBENTRO_20261028.md;
rapporti Red Team su PR #14, #20 e #21.
Non attribuire a un documento storico l'autorità sullo stato corrente senza verifica degli SHA.

Ultimo HEAD della PR #21 verificato da Supervisione uscente prima di questo deposito: **3a530dde62ec4057d432c96f33430f815099223f**, base main, OPEN/DRAFT. È una fotografia datata: rileggere la testa di PR e main prima di agire.

L'esistenza di un link non dimostra la disponibilità del suo contenuto. Se la connessione a Drive o Libreria manca, registrare la fonte non acquisita; trovare un percorso autorizzato alternativo senza far ripetere all'autore il lavoro che i connettori possono svolgere.

## 4. OBBLIGO DI ACQUISIZIONE INTEGRALE, COMPRENSIONE E INTERCONNESSIONE
**Divieto di apprendimento per snippet, titoli, sommari GPT e nomi di funzioni.** Gli snippet possono essere usati esclusivamente per localizzare gli originali, mai come prova di acquisizione o comprensione.

Acquisizione progressiva obbligatoria:
A. Visione complessiva: presente mandato FINO A EOF; README completo, comprese rettifiche posteriori al mandato congelato, ROADMAP completa, governo, aggiornamenti Termux, importazione sicura, on-chain, rapporti storici e decisioni pertinenti. Leggere le fonti in ordine e ricomporre il significato tra sezioni.
B. Architettura attuale: acquisire l'albero Git della PR #21 e di main fino alla fine; leggere integralmente i sorgenti proprietari e i test pertinenti del candidato, registrando SHA, percorsi, lunghezze/EOF. I file lunghi vanno letti in lotti numerati SENZA saltare intervalli; recuperare e connettere mentalmente tutti i segmenti. Un elenco di def NON equivale alla lettura del codice. Verificare gli asset vendor, la loro versione e le dipendenze di esecuzione; approfondire il JavaScript effettivamente generato per le funzioni finanziarie/UI.
C. Interconnessione: per ogni capacità richiesta identificare produttore, dato grezzo, trasformazione, persistenza, consumer in dashboard e consumer GPT, validazione, fallimento e regressioni. Confrontare l'architettura osservata con l'obiettivo del prodotto.
D. Storia tecnica: acquisire le revisioni e le prove originali pertinenti delle PR #14, #20, #21; distinguere la versione difettosa dalla riparazione, i rapporti indipendenti dalle dichiarazioni della Costruttrice, e le verifiche sui sorgenti autentici dalle prove su estratti. Seguire i riferimenti e recuperare integralmente gli originali rilevanti.
E. Runtime: distinguere GitHub, file su Drive, copia del dispositivo e processo effettivamente in esecuzione. Nessuna deduzione sulla versione Samsung installata senza prova.

Per ogni fonte: segnare **LETTO EOF**, **COMPRESO E INTERCONNESSO**, **VERIFICATO CON PROVA**, oppure **NON ACQUISITO**, con riferimenti verificabili. Le quattro classi non sono sinonimi. Se una lettura si tronca, riprendere fino a EOF. Se manca un originale necessario, non sostituirlo con il suo riassunto. Ricerche e letture non possono diventare un'attività indefinita per evitare il lavoro tecnico: completata l'acquisizione pertinente, passare alla direzione effettiva.

## 5. STATO PRECEDENTE: INFORMAZIONE DI ORIENTAMENTO, NON VERDETTO
La disamina del 28 ottobre depositata nella ROADMAP ha seguito i percorsi patrimoniali e Spot del candidato, senza eseguire un collaudo end-to-end. Ha identificato:
- decision_desk.refresh() legge le posizioni e ricava tendenze giornaliere; build_report() usa per la valorizzazione principalmente il percorso quotazioni EUR e conserva le posizioni che non può valorizzare;
- ricerca_setup.scan() approfondisce un campione limitato: fino a 24 token 1H, fino a quattro schede; serve.spot_catalog() consente di navigare il catalogo delle coppie online. Catalogo completo NON significa screening profondo di tutti i mercati;
- serve.load_spot_comparison() confronta 15m/1H/4H/1D on demand per una coppia, mentre dossier_trade.collect() persiste 15m/1H per pochi candidati e recupera un campione separato 4H; il pacchetto GPT non riceve sistematicamente quattro timeframe per ogni posizione effettivamente esaminata;
- dossier_trade.COINGECKO_IDS mappa automaticamente soltanto ICNT e KAS; la composizione Punto 4 / PR #14 conserva on-chain e multifonte ma blocchi P08/P09 su autenticazione, provenienza e attribuzione; non importarla dichiarandola fonte già attestata;
- piano_gpt.py e verifica_piani.py leggono, validano, archiviano e riesaminano un piano locale; manca il circuito provato GPT→Drive→Samsung. Lo script wallet packet è nel candidato ma non nell'allowlist di installazione ordinaria di scripts/kdd_aggiorna.py;
- prove CI favorevoli (234 PASS, 2 SKIP a un precedente SHA) non certificano comprensione economica, copertura funzionale, test Samsung o l'autenticità delle fonti. I Red Team hanno trovato anche falsi negativi e prontezze GPT erronee.

La nuova Supervisione deve verificare autonomamente gli originali e rettificare qualsiasi premessa inesatta, conservando gli SHA delle prove.

## 6. LAVORO PRATICO DELLA COSTRUTTRICE GIÀ PREPARATO
È stato consegnato in chat un mandato G2 per la Costruttrice con identificativo:
**KDD-COST-G2-PATRIMONIO-4TF-GPT-20261028**.

Scopo: rappresentare TUTTE le posizioni del wallet anche se mancano quotazioni o timeframe; selezionare correttamente la coppia Kraken senza confondere valute o alias; per ogni posizione analizzata acquisire e qualificare 15m/1H/4H/1D; far arrivare il confronto validato al dossier persistente e al pacchetto GPT; riutilizzare decision_desk.py, dossier_trade.py, grafico_4h.py, serve.py e generatore wallet; verificare il percorso di distribuzione dello script senza installare nulla sul Samsung; testare consumer e regressioni.

**Il mandato è un testo preparato in una chat, non una prova di accettazione, avvio o completamento da parte della Costruttrice.** La nuova Supervisione deve recuperare il testo originale completo (dalla chat pertinente, o dall'autore se il testo non è raggiungibile tramite le fonti autorizzate), leggerlo fino a EOF, e verificarne compatibilità e perimetro prima di esaminare il lavoro. Non affermare che la Costruttrice stia lavorando finché non emerge una prova. Non creare una nuova costruzione parallela.

Non attribuire al mandato G2 un GO automatico al merge, deploy, trading o installazione sul telefono. Le regole del governo e i GO effettivi restano vincolanti.

## 7. PRIMA ATTIVITÀ DELLA NUOVA SUPERVISIONE: VALUTARE LA CONSEGNA COSTRUTTRICE
Dopo la piena acquisizione, verificare la situazione reale della Costruttrice e della PR #21. Quando la risposta della Costruttrice è disponibile:
1. Leggerla integralmente FINO A EOF PERSISTENTE, compresi commit, allegati, test, errori e limitazioni. Un messaggio troncato non è una consegna.
2. Recuperare il codice originale dell'HEAD dichiarato e confrontarlo con base e mandato. Leggere diff integrale, tutte le funzioni toccate e i consumer correlati, fino a EOF; non assumere che un file indicato ma non acquisito sia stato verificato.
3. Controllare l'effettivo percorso posizione → coppia corretta → dati Kraken autentici/freschi → quattro timeframe → dossier → pacchetto GPT. La sola presenza di quattro etichette non è sufficiente.
4. Verificare tutti i casi: quantità ignota; zero reale; saldi stantii; quote EUR non disponibile e alternative USD/USDC; token omonimi; coppia alias errata; candele incomplete o scadute; timeframe disomogenei; portafoglio con più posizioni dei limiti storici 4/8; anomalie API; valori estremi e non finiti; integrità dei dati privati e nessun ordine.
5. Esaminare le prove come possibili strumenti difettosi: verificare che gli assert falsifichino la baseline errata, non soltanto che i nuovi test siano GREEN; eseguire autonomamente quando possibile sui sorgenti autentici e fixture sintetiche; distinguere test non eseguiti e SKIP.
6. Controllare preservazione di dashboard 8765, scanner, Spot, costi, piani GPT, storico, aggiornamento, backup e rollback; eventuale mancata installabilità dello script in allowlist; assenza di modifiche al Samsung o ai saldi reali.
7. Formulare un giudizio tecnico circoscritto: accettabile per prova indipendente / riparazione necessaria con controesempi / non valutabile per materiale mancante. Spiegare esattamente causa, impatto, versione e test.
8. Se ci sono difetti, **delegare la riparazione alla stessa Costruttrice**, senza scrivere subito il proprio codice o aprire un nuovo ramo. Solo dopo una consegna verificabile predisporre il mandato a un Red Team indipendente che tenti realmente di falsificare il candidato.
9. Acquisire il rapporto del Red Team fino a EOF, controllarne prove e controesempi e decidere il passo tecnico successivo. Non promuovere il candidato perché la Costruttrice o un test si dichiara soddisfatto.

La Supervisione uscente NON ha verificato una consegna del mandato 4TF: alla sua ultima ricognizione la PR #21 restava DRAFT, HEAD **3a530dde62ec4057d432c96f33430f815099223f**, senza un commento di consegna successivo associabile al nuovo mandato. Verificare la situazione aggiornata, senza usare questo dato come verità permanente.

## 8. SICUREZZA E STATUTI NON NEGOZIABILI
- Kraken API private esclusivamente in lettura; nessun ordine, trasferimento o operazione automatica.
- Nessuna credenziale, T0, quantità e saldi riservati in GitHub, test condivisibili o rapporti. Dati sintetici separati dai reali.
- Quantità sconosciuta, malformata e zero reale distinti; totale parziale e non disponibile espliciti; nessuna falsa valorizzazione o P/L.
- Freschezza saldo indipendente da freschezza mercato; entrambe riesaminate **al consumo** del dato, non soltanto alla creazione.
- Identità asset, coppia, quote, rete blockchain e fonte verificabili; in mancanza, astensione informativa specifica, senza attribuzione o conversione arbitraria.
- On-chain e fonti esterne: URL, digest, campi schema e flag dichiarati non autenticano l'upstream. Non superare artificialmente P08/P09.
- La presenza di un piano GPT non è un'operazione eseguita; l'archivio è una prova storica datata.
- PR #21 OPEN/DRAFT e separata dal main applicativo e dal Samsung operativo. Nessun merge/deploy senza distinti GO e controlli del dispositivo. Non aggirare l'autorizzazione mediante modifiche "documentali" che promuovano fittiziamente uno stato tecnico.
- I test dell'operatore non equivalgono al Red Team indipendente; i PASS di Linux non equivalgono a collaudo Chrome Android, API, T0 o porta 8765.
- Il test di sicurezza deve riguardare anche il pacchetto consumato da GPT e la restituzione del piano, non solo la correttezza matematica di indicatori.

## 9. UNICA ROADMAP, NESSUNA NUOVA METAGOVERNANCE
La ROADMAP_KDD.md è la sola bussola operativa. Il README conserva mandato e storia. La PR #21 conserva esecuzioni, commenti e prove. Aggiornare per sostituzione soltanto quando cambia lo stato materiale, riportando SHA ed evidenze; evitare sedimentazione di mandati, registri, tabelle e frammenti di governo paralleli.

Non ricominciare da un nuovo repository, da un altro ramo o da una riscrittura del KDD. La priorità è completare il prodotto già sviluppato, salvaguardando le caratteristiche che funzionano e correggendo le interfacce mancanti.

## 10. COMPORTAMENTO ATTESO DALLA NUOVA SUPERVISIONE
La nuova chat deve:
- iniziare dichiarando il raggiungimento dell'EOF di QUESTO testo soltanto quando l'ha raggiunto;
- acquisire in autonomia, integralmente, le fonti, compresi i moduli e test lunghi; fermarsi sul problema effettivo se una fonte manca, senza inferire la sua sostanza;
- condurre un'indagine dal requisito economico generale fino alle singole chiamate, file scritti e consumer, con controllo di versione;
- prendere in carico concretamente il primo intervento della Costruttrice, verificandone la risposta e i commit;
- assegnare e valutare lavori tecnici e Red Team in modo distinto;
- usare aggiornamenti brevi e sostanziali, senza intrattenere l'autore con dichiarazioni di affidabilità non provate;
- NON chiedere all'autore di ricostruire la storia che è già nelle fonti.

Se la nuova chat termina per contesto insufficiente, depositare nelle fonti canoniche un passaggio di consegne con gli SHA, le letture EOF effettuate, quelle mancanti, i controlli svolti, la decisione sulla Costruttrice e il primo punto concreto da riprendere. Non chiamare acquisita una lettura che non è stata eseguita.

La supervisione uscente può giudicare la prima risposta della subentrante soltanto quando ne riceve il testo o una fonte consultabile; non può osservare una nuova conversazione in tempo reale né svolgere lavoro di sorveglianza fra le chat da sola. La nuova Supervisione resta responsabile delle proprie verifiche.

## 11. CONDIZIONE DI CHIUSURA DEL SUBENTRO
Il subentro G0 è completato quando la nuova Supervisione dimostra:
(1) lettura effettiva fino a EOF di questo mandato;
(2) acquisizione fino a EOF e comprensione interconnessa delle fonti canoniche e dei sorgenti pertinenti, con versioni;
(3) ricostruzione esatta del KDD dal macro al micro, inclusi i collegamenti tra produttori e consumer e le lacune riscontrate;
(4) presa in carico del mandato alla Costruttrice e valutazione della sua prima consegna non appena effettivamente disponibile;
(5) capacità di delegare una riparazione precisa e definire una verifica indipendente, senza modificare autonomamente il perimetro finanziario o promuovere software non collaudato.

Questi sono risultati da provare mediante lavoro, non formule da ripetere. **La lettura del presente mandato è la condizione iniziale, non la dimostrazione di aver acquisito il progetto.**

---
**SENTINELLA TERMINALE DI EOF — KDD-SUP-SUBENTRO-INTEGRALE-EOF-20261028-FINE**
