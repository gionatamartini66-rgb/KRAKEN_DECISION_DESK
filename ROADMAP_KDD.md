# KDD — Roadmap canonica

**Stato ricostruito al 31 ottobre 2026.** Questa è l'unica vista operativa del **lavoro corrente**. La [destinazione e l'architettura](README.md) e il [governo](GOVERNO_KDD.md) non si riscrivono a ogni riparazione. Un commit GitHub non prova ciò che gira sul Samsung.

## 1. Destinazione e criterio di successo

**Un solo KDD**, accessibile dal Samsung, per la **gestione attiva dell'intero patrimonio**: componente strategica prevalente e componente operativa in **Spot e Futures long/short**, con eventuale quota minoritaria dedicata ai derivati. Le funzioni non fissano una durata di detenzione né impongono compartimenti rigidi. GPT deve esaminare l'intero patrimonio, proporre e discutere alternative fondate, confrontare rischio/costo/beneficio e permettere di archiviare e riesaminare le decisioni.

**Criterio pratico:** l'autore riceve una fotografia verificabile, comprende opzioni e rischi e può ritrovare nel KDD le proposte discusse, le proprie decisioni e gli esiti osservati. Nessun ordine automatico. Un sistema più complesso, un nuovo cruscotto o una CI verde non costituiscono da soli un risultato.

## 2. Stato del prodotto: codice, Samsung e prove distinti

| Capacità | Stato verificabile al 31/10 | Limite principale |
| --- | --- | --- |
| Unico runtime KDD / dashboard `127.0.0.1:8765` | **Installato sul Samsung** con GO distinto il 30/10; prova tramite output Termux e screenshot dell'autore | Non è accesso remoto diretto o attestazione continua |
| Portafoglio e lettura privata Kraken `BalanceEx` | **Integrati**, chiavi read-only; sul Samsung risultavano dieci posizioni all'ultimo controllo | Saldo e mercato diventano obsoleti; nessun costo fiscale o P&L originario attestato |
| Spot, catalogo coppie, 4TF e grafici | **Integrati** dopo PR #21; Chrome del 30/10 ha mostrato PEPE/EUR su 15m/1H/4H/1D | Qualità delle scelte e negoziabilità per ogni account non provate; confronto mobile migliorabile |
| Dossier patrimoniale e pacchetto GPT | **Produttore integrato**; eseguita sul Samsung composizione **10/10** senza scrivere un nuovo file privato | Dossier globale **PARZIALE**; mercato/saldo già vecchi alla successiva lettura; nessun packet 30/10 consumato da GPT |
| GPT in chat, ricerca e piani | Esistono `piano_gpt.py` e `verifica_piani.py`, con piani storici e riesami osservativi | Il piano esistente non viene rivalutato da GPT automaticamente; il ritorno remoto non è collaudato |
| Trasporto Android/SAF/FolderSync/Drive | Test manuali in direzione Samsung→Drive→GPT il 22–23/10 con file di prova | Non certificano trasferimenti privati correnti o il ritorno GPT→KDD |
| Futures | **Obiettivo del sistema**, non funzione operativa attuale del KDD; OI/CVD pubblici BTC già presenti nel dossier come contesto circoscritto | Mancano lettura posizioni Futures, collaterale, rischio e contratto GPT dedicato |
| On-chain / fondamentali / news | Componenti e prove sperimentali, incluse PR #14 e fonti esterne, da qualificare | Provenienza, attribuzione e P08/P09 restano limiti reali; non importare componenti non attestati |

**Riferimenti di versione:** PR [#21](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/21) **MERGED** il 30/10; PIN applicativo riferito come installato sul Samsung `da908139ffd51872f2829fb3b305ff7e6a0e0fea`. Il deploy ha utilizzato preflight, backup privato, postflight e riavvio; prove locali registrate nella cronologia Git e nella PR, **non** nuovo accesso al dispositivo in questa ricognizione. La baseline applicativa prima del lavoro PR #22 è `d6264145b7e49f5c2ca913bfe7dc928a0247d136`. I successivi commit di riallineamento dei documenti in `main` **non modificano il software**.

## 3. Ponte GPT PR #22 — audit concluso, decisione di prova sintetica da autorizzare

**Obiettivo:** completare il circuito **KDD → dossier privato autorizzato → GPT e autore → proposta → consenso → ritorno nel KDD → archivio e riesame**, riusando quanto già esiste, senza costruire un secondo KDD.

**Candidato:** [PR #22](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/22), **OPEN/DRAFT, non integrata e non installata**, HEAD R5 `fc2306fd118024c9bdeb7908d85360c3fc578943`, baseline software `d6264145b7e49f5c2ca913bfe7dc928a0247d136`. La PR aggiunge un ponte con contratto patrimoniale chiuso e protocolli locali di pubblicazione, consenso, archivio e riconciliazione, oggi provati **solo in laboratorio sintetico**.

**Evidenze e problema aperto:**
- [CI R5](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/actions/runs/41183794535): **378 PASS / 2 SKIP**; sono test della Costruttrice, non garanzia indipendente.
- I Red Team hanno individuato problemi progressivi nel recupero dopo interruzione. Nel quarto rapporto, RT3-A (tentativi ripetuti) e RT3-B (symlink journal) risultano corretti nelle controprove eseguite su un **estratto del modulo autentico**, non sull'intero programma.
- **RT4-C1:** `os.rename()` può sovrascrivere una marcatura creata da un altro processo tra controllo di assenza e rinomina. La controprova Linux è fondata, ma usa un concorrente capace di scrivere nella directory senza rispettare il lock: occorre giudicarne l'effettiva rilevanza nel modello di minaccia e l'effetto di un'ulteriore riparazione.
- Restano non verificati il recupero dopo perdita di alimentazione Android, il filesystem effettivo Termux, i passaggi SAF/FolderSync/Drive e il ciclo patrimoniale completo.

**Audit metaarchitetturale Astra concluso (31/10/2026, G0):** `KDD_PR22_META_AUDIT_20261031.md` e `KDD_PR22_META_AUDIT_PROVE_20261031.zip`, presenti nella Libreria dell'autore. **Verdetto del revisore: ARCHITETTURA ADEGUATA — PROSEGUIRE CON RISERVE DOCUMENTATE**; proposta di conservare R5 per un **eventuale collaudo Android in arena isolata e interamente sintetica**, soltanto con GO distinto dell'autore. La Supervisione ha letto il rapporto integrale, confrontato i blob R5 con GitHub e replicato in ambiente Linux 15 scenari del primo harness con esiti attesi; la seconda suite supplementare non è stata completata autonomamente entro il limite di esecuzione, e rimane evidenza del revisore. **RT4-C1 è riprodotto ma richiede uno scrittore non cooperativo sulle directory private**, che non risulta nel flusso previsto. **META-01:** journal incompleto può bloccare il recupero automatico; **META-02:** errore nell'ultimo fsync può lasciare finale leggibile e diagnosi incerta; **META-03:** test negativo del consenso non discriminante, mentre il controllo è provato separatamente. Il revisore non ha acquisito integralmente quattro rapporti RT precedenti e non ha collaudato Android/Drive. **Compatibilità futura Futures non analizzata nel rapporto**, da non qualificare come certificata; gli schemi R5 restano patrimoniali/Spot e versionabili soltanto tramite futura progettazione esplicita.

**Decisione tecnica provvisoria della Supervisione:** concordare con l'opzione A del revisore per il solo pilota sintetico; mantenere R5 immutata, nessuna R6 e nessun nuovo Red Team microsettoriale ora. **GO NON CONCESSO**: l'autore deve decidere se autorizzare il test isolato su Android/Termux. Il futuro test deve provare isolamento da portafoglio, credenziali, percorsi e Drive reali, e classificare gli STOP ordinari senza pulizia indiscriminata. Il risultato del pilota non autorizzerà automaticamente merge/deploy, trasporto privato o trading.

**Gate successivi soltanto se decisi dall'autore:** test Android isolato con dati sintetici, poi — con consensi e verifiche distinti — prove del canale informativo con dati privati autorizzati. Nessuna di queste fasi è già passata.

## 4. Valore decisionale dopo il collegamento centrale

1. **Patrimonio completo:** per ogni asset valutare mantenere, incrementare, alleggerire, uscire, ruotare e confrontare alternative, distinguendo dati confermati e lacune; quattro timeframe per le posizioni realmente analizzate, non un solo pilota.
2. **Opportunità Spot:** universo Kraken navigabile, approfondimento mirato, segnali tecnici qualificati, liquidità, order book, fee e percorso di conversione; Binance e altre fonti sono confronti, non volumi sommabili senza base comune.
3. **Futures:** integrare in modo coerente la componente operativa long/short e i dati di rischio su strumenti derivati. È una parte del prodotto da progettare quando si apre il relativo lavoro; **non** un divieto permanente né una funzione da dichiarare già installata.
4. **Contesto esterno:** completare on-chain, tokenomics, unlock, fondamentali, macro e news solo quando cambiano materialmente il giudizio e la loro provenienza è controllabile. [PR #14](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/14) non è pronta da fondere automaticamente.
5. **Caso economico iniziale, non ordine:** esaminare l'eventuale costituzione di liquidità operativa per circa **150 EUR equivalenti in USDC**, verificando costi, saldo attuale, cambio e alternativa di non convertire.

La qualità si misura sulla **decisione contestabile e riesaminabile**, non sul numero di filtri, indicatori, test o rapporti.

## 5. Regola di aggiornamento della Roadmap

Quando cambia lo stato materiale, **sostituire** l'affermazione superata e indicare prova, data, commit, autorizzazione e prossimo passo. La storia completa resta nei commit, nelle PR e nell'archivio datato del [README](README.md); non appendere nuovi resoconti a questa pagina.

Ogni passaggio è distinto: **proposto → sviluppato su ramo → provato indipendentemente → integrato → installato → osservato sul Samsung → utilizzato nel circuito decisionale**. Se una prova manca, indicarlo; se uno schema o una fonte non sono disponibili, non inventarli.

**Fonti per chi subentra:** [README e mandato originale](README.md), [Governo](GOVERNO_KDD.md), [mandato di subentro fino a EOF](SUBENTRO_SUPERVISIONE_APICALE.md), [procedura di aggiornamento Termux](AGGIORNAMENTI_TERMUX.md), [PR #21](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/21), [PR #22](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/22). Le prove di altre PR e della Libreria vanno lette quando pertinenti, **non ricostruite da snippet**.
