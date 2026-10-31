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

## 3. Ponte KDD–GPT — stato verificabile al 31 ottobre 2026

**Scopo economico:** provare il ciclo unico «fotografia verificabile dell'intero patrimonio → dossier → GPT e autore → proposta motivata → scelta dell'autore → ritorno nel KDD → archivio e riesame». Approvare la pubblicazione non autorizza un ordine finanziario. Il client Kraken usa esclusivamente API private di lettura; ogni operazione Spot o Futures resta manuale.

**Versioni e prove distinte:**
- [PR #22](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/22) R5, HEAD `fc2306fd118024c9bdeb7908d85360c3fc578943`, **OPEN/DRAFT**, baseline applicativa `d6264145b7e49f5c2ca913bfe7dc928a0247d136`. Prove Linux; **non installata**. Sul Samsung un collaudo sintetico si è arrestato perché Python Termux 3.14.6 non espone `os.link`; 378 PASS / 2 SKIP in CI non provavano la compatibilità.
- **Misura Termux G0 31/10:** in arena separata, `O_EXCL`, `O_NOFOLLOW`, `flock` tra processi, `fsync` su file/directory, permessi privati e rename verso nome assente hanno superato la prova sintetica; `os.link` è assente e `os.rename` su un finale esistente lo **sovrascrive**. Verificate primitive, **non** il bridge #23 né la durabilità dopo perdita hardware.
- [PR #23](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/23), HEAD `af5f7f34a516a7aa48ebda8ce0d197a22e93d936`, **OPEN/DRAFT, ramo sperimentale derivato da R5**. Sostituisce gli hard link con staging, journal temporaneo, `flock`, rename e sincronizzazioni. [CI #41215897964](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/actions/runs/41215897964): **383 PASS, 2 SKIP** sul candidato Linux sintetico, **378 PASS, 2 SKIP** sul checkout R5 storico separato. I 20 focused sono già conteggiati nel totale. Nessun merge, deploy, trasferimento privato o test funzionale del nuovo bridge sul Samsung.

**Red Team G0 RT1 ricevuto il 31/10:** fonti e CI esaminate; controprove autonome di recupero eseguite su una **ricostruzione isolata** del flusso, non sul modulo autentico integrale. Dopo `SIGKILL` del recuperatore fra eliminazione dello staging e del journal può rimanere un journal senza finale/staging; prima del journal può rimanere uno staging orfano. Il codice rifiuta nuove pubblicazioni e conserva i residui: **nessuna falsa approvazione dimostrata**. **PR23-01:** manca una procedura assistita verificata per riaprire la pubblicazione in tali stati. Il Red Team ha espresso STOP al pilota completo; la Supervisione lo classifica come **rilievo operativo circoscritto**, senza autorizzare automaticamente una remediation. Restano da provare il modulo originale su Android e il recupero pratico.

**Rischio proporzionato allo scopo:** le chiavi read-only del KDD non impartiscono ordini né prelievi. I guasti del bridge riguardano continuità dell'archivio, integrità delle proposte e affidabilità del supporto decisionale. Sono prioritari correttezza, freschezza, identità dei dati, consenso, riservatezza pratica e non interferenza con il KDD operativo. Gli scenari same-UID fuori lock restano limiti dichiarati, non richieste automatiche di nuovo sviluppo.

**Stato del prodotto:** dashboard, Spot, 4TF e produttore packet risultano installati secondo la prova Samsung del 30/10; il packet è stato composto localmente senza pubblicazione privata. **Il percorso GPT → ritorno sul Samsung non è stato ancora collaudato integralmente.** #23 affronta un ostacolo tecnico, non certifica da sola il circuito.

**Prossimo passo G0, senza sviluppo:** ricostruire sui sorgenti la catena producer/consumer, le interfacce del programma installato con #23 e ciò che GPT deve effettivamente ricevere; definire la prova sintetica Android minima, con isolamento e criterio d'uso. Nessuna nuova remediation o GO al pilota prima di questa verifica. PR23-01 resta aperto e classificato. Pilota, merge, deploy e dati privati richiedono distinti GO dell'autore. A ogni avanzamento materiale, aggiornare questa Roadmap per sostituzione con prove e SHA.

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

**Fonti per chi subentra:** [README e mandato originale](README.md), [Governo](GOVERNO_KDD.md), [mandato di subentro fino a EOF](SUBENTRO_SUPERVISIONE_APICALE.md), [procedura di aggiornamento Termux](AGGIORNAMENTI_TERMUX.md), [PR #21](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/21), [PR #22 R5](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/22), [PR #23 Android](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/23). Le prove di altre PR e della Libreria vanno lette quando pertinenti, **non ricostruite da snippet**.
