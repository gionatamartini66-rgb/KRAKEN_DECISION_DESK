# KDD — Governo del progetto

**Fonte di autorità:** mandato dell'autore conservato nel [README](README.md), comprese le precisazioni successive. **Stato operativo e prossimo incarico:** [ROADMAP](ROADMAP_KDD.md). Questo file stabilisce scopo, responsabilità e criteri di decisione; non è un diario delle sessioni.

## 1. Destinazione economica

Kraken Decision Desk è **un unico sistema di supporto alla gestione attiva dell'intero patrimonio crypto**.

- **Componente strategica prevalente:** il capitale è gestito in base a opportunità, rischi e condizioni di mercato. Mantenere, incrementare, alleggerire, liquidare e ruotare sono alternative da valutare, non comportamenti prestabiliti. «Strategica» **non significa immobilizzata**.
- **Componente operativa:** impiego flessibile di capitale per operazioni **Spot e Futures, long e short**. Ai derivati è destinabile una **quota minoritaria**; nessuna percentuale, durata, leva o ripartizione rigida è prescritta qui.
- Le componenti sono funzioni economiche del capitale, **non tre portafogli artificiali**. Eventuali passaggi di risorse sono decisioni dell'autore, da valutare per costo, rischio ed effetti sul patrimonio complessivo.
- KDD deve riconoscere regimi rialzisti, ribassisti, laterali e transizioni. Anche non intervenire è un'ipotesi da giustificare e riesaminare, mai una risposta automatica.

**I Futures appartengono alla destinazione del KDD. Non esiste un divieto generale di esaminarli o di considerarli nelle decisioni dell'autore.** Il programma attuale, tuttavia, **non dispone ancora delle funzioni necessarie a gestire posizioni Futures**: questa è una lacuna di implementazione, non un cambio di obiettivo.

## 2. Autorità e responsabilità

- **Autore:** sceglie obiettivi, esposizione, rischio e operazioni; approva i lavori che intervengono su codice, dispositivi, dati e permessi. Qualsiasi eventuale ordine viene deciso ed eseguito **manualmente dall'autore sulla piattaforma di negoziazione**, non da GPT o dal KDD.
- **GPT:** analizza il dossier, cerca fonti pertinenti, contesta ipotesi, confronta scenari e alternative, propone azioni e condizioni di riesame; **non è l'esecutore di un ordine**.
- **Supervisione apicale:** ricostruisce il progetto dai documenti e dal codice effettivi, coordina il lavoro, valuta conseguenze e prove, decide la raccomandazione tecnica e sottopone all'autore i passaggi che richiedono autorizzazione.
- **Costruttrice:** implementa nel perimetro assegnato, preserva i collegamenti esistenti e fornisce prove riproducibili. I propri test non sono una certificazione indipendente.
- **Red Team/revisore:** tenta di falsificare requisiti e comportamenti nel modello di minaccia dichiarato; separa difetto tecnico, rischio reale e scelta di accettazione.

**Le autorizzazioni non si trasferiscono per implicazione:** esaminare il codice non autorizza a modificarlo; sviluppare su un ramo non autorizza merge o installazione; installare non autorizza a movimentare fondi. Non trasformare una precedente limitazione dello sviluppo Spot in una proibizione permanente dei Futures.

## 3. Semantica dei dati e strumenti

- **Patrimonio:** distinguere asset, quantità posseduta, disponibilità, valore indicativo, costo storico ignoto e capitale allocato. Zero, dato mancante e dato non verificato non coincidono. Il saldo privato e le quotazioni hanno **fonti e timestamp indipendenti**, da ricontrollare al consumo.
- **Riferimento T0 convenzionale:** il T0 del 19/10/2026 è una fotografia immutabile di partenza, usata per misurare da quella data la variazione di valore del paniere effettivamente fotografato, come se l'osservazione fosse il momento iniziale dell'investimento. **Non è una registrazione di acquisti avvenuti il 19/10, non ricostruisce il prezzo medio storico né il P/L fiscale.** Il confronto del paniere T0 a quantità fisse è distinto dalla performance effettiva del patrimonio, che richiede di contabilizzare successivi scambi, depositi, prelievi e costi. Asset non visibili nella fotografia T0 non equivalgono a saldo zero. Conservare il file originale immutato; una successiva fotografia completa può costituire un secondo riferimento esplicitamente datato, senza riscrivere il T0.
- **Mercato Spot:** preservare identificità dell'asset e della coppia, valuta di quotazione, bid/ask, profondità, spread, liquidità, commissioni, conversioni, minimi e negoziabilità effettiva per account/territorio. Una coppia pubblicata nelle API non è necessariamente negoziabile dall'autore.
- **Futures:** non confondere il contratto derivato con il token Spot. Distinguere direzione long/short, nozionale, leva, margine, collaterale esposto, funding, prezzo mark/index, eventuale scadenza, costi, P&L, rischio di liquidazione e configurazione wallet/cross/isolated. Il capitale strategico non va esposto inconsapevolmente come collaterale. L'eventuale integrazione KDD/GPT dovrà impiegare contratti informativi **distinti e versionati**, senza reinterpretare schemi Spot esistenti.
- **Fonti esterne:** on-chain, tokenomics, unlock, Binance, CoinGecko, notizie, macro e geopolitica entrano nell'analisi quando pertinenti e verificabili. OI/CVD di un singolo contratto o exchange non equivalgono al mercato aggregato. Hash, URL e metadati non provano da soli autenticità dell'origine. Un deposito su exchange non prova una vendita.

## 4. Circuito decisionale KDD ↔ GPT ↔ autore

Il ciclo richiesto è: **fotografia datata KDD → dossier e fonti → GPT in chat → discussione e proposta motivata → scelta dell'autore → eventuale pubblicazione/archivio nel KDD → verifica successiva**.

Ogni proposta deve distinguere osservazione, ipotesi, decisione, eventuale esecuzione manuale **dichiarata dall'autore** e verifica successiva. Quando i dati lo permettono, deve mostrare ragioni favorevoli e contrarie, alternativa concreta, effetti sul patrimonio, dimensionamento, condizioni di ingresso/uscita/invalidazione, costi e rischio. Una soglia di prezzo attraversata non prova un fill; una proposta archiviata non prova un trade; un test verde non dimostra utilità economica.

Il circuito del programma deve poter evolvere per gli strumenti previsti, **senza rifare il KDD** e senza presentare come già esistente una funzione ancora da realizzare.

## 5. Sicurezza e cambiamenti

- Le credenziali e i dati finanziari privati restano sul Samsung o in un canale privato autorizzato; niente chiavi, T0, saldi, indirizzi privati o backup nel repository. Il client Kraken oggi presente usa permessi **di sola lettura**; non attribuirgli operazioni che non implementa.
- GitHub è la fonte del codice versionato, **non** prova dell'installazione sul Samsung. Un documento su Drive non dimostra freschezza o ritorno nel KDD. Nessuna sincronizzazione indiscriminata della home Termux.
- Per cambiare il software: ramo e perimetro definiti, confronto con la baseline, prove su sorgenti autentici, revisione indipendente proporzionata al rischio, decisione dell'autore per merge e deploy. Sul Samsung: [aggiornamento controllato](AGGIORNAMENTI_TERMUX.md), backup, preflight, postflight, rollback e verifica del servizio.
- Le prove sono classificate per ambiente: ispezione, fixture, modulo reale in laboratorio, Android isolato, runtime Samsung, ciclo informativo completo. **Non promuovere uno stato sulla base dei PASS scritti da chi ha costruito il codice**.

## 6. Gerarchia documentale

1. **README:** presentazione e architettura attuale; mandato originale e storia nella sezione archivistica, con date preservate.
2. **GOVERNO (questo file):** destinazione, responsabilità e criteri duraturi.
3. **ROADMAP:** unica fotografia corrente dei lavori, delle dipendenze e del prossimo passo.
4. **PR, commit, log e rapporti originali:** evidenze tecniche e decisioni storiche da verificare sui rispettivi SHA.
5. **Dispositivo e Drive:** stato e dati effettivi, da osservare separatamente.

Le decisioni storiche descrivono il **perimetro e lo stato della loro data**: non sostituiscono gli obiettivi complessivi dell'autore. Prima di cambiare un documento, riconciliare la sua affermazione con le fonti originali e con il software. **Non creare altra documentazione di governo parallela.**
