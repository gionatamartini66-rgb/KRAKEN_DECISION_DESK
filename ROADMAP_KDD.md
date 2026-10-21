# KDD — ROADMAP DI IMPLEMENTAZIONE E STRATEGIA MULTIREGIME

**Ricognizione documentale:** 21 ottobre 2026.  
**Classe:** registrazione di indirizzo e sequenza già discussi; **nessuna nuova autorizzazione tecnica o di trading**.  
**Ambito:** Kraken Decision Desk (KDD), repository tecnico privato.  
**Precedenza:** resta valido il mandato operativo originario custodito sul Samsung; il presente file non sostituisce né modifica documenti locali che non siano stati direttamente confrontati.

## 1. Destinazione: KDD «cross-over»

KDD deve aiutare l'autore a **prendere decisioni spot ragionate in qualunque regime di mercato**, senza presumere che ogni criptovaluta debba salire per essere interessante o che una posizione debba essere mantenuta indefinitamente.

L'analisi del regime comprende il mercato generale e quello del singolo token, su orizzonti distinti; non suppone una suddivisione fissa dell'anno in mesi rialzisti o ribassisti. La preferenza storica dell'autore per riconoscere accelerazioni rialziste è un punto di partenza operativo, **non** un filtro che impedisca di leggere ribassi.

**Regimi da interpretare e strumenti spot da confrontare:**

| Regime osservato | Opportunità/decisioni spot da esaminare | Limite |
| --- | --- | --- |
| Rialzista | Formazione del movimento, consolidamento, ripartenza, rotazione verso forza relativa | Evitare acquisti tardivi su pump senza supporto di dati |
| Ribassista | Riduzione delle esposizioni vulnerabili, uscita parziale, USDC come liquidità operativa, ricerca di rimbalzi e ripartenze selettive | Uno spot long non guadagna direttamente dalla sola discesa |
| Laterale | Escursioni di prezzo negoziabili, rotture confermate, falsi breakout, rapporto fra range e costi | Non forzare operazioni in range troppo stretti |
| Transizione / divergenza fra timeframe | Divergenze di forza relativa, mutamento della struttura, posizioni da rivedere | Distinguere ipotesi da conferma |

La liquidità in USDC è una **possibile posizione tattica**, soggetta a rischio di emittente, depeg e piattaforma, non una garanzia di preservazione del capitale. La quota patrimoniale prevalente resta destinata all'investimento pluriennale, ma è **a gestione attiva**; una quota inferiore alimenta trading spot e rotazioni senza leva. Le percentuali non sono paletti automatici: variano solo per decisione dell'autore sulla base di rischio, token, liquidità e opportunità.

**Scelte che il motore deve saper confrontare:** aprire uno spot long, attendere un ingresso diverso, alleggerire, chiudere, ruotare, aumentare liquidità, conservare la posizione. «Non intervenire» è un esito legittimo **motivato**, non il risultato predefinito dell'eccesso di cautela.

## 2. Sequenza vincolante già concordata

Questa sequenza **rimane invariata**; la scoperta di nuove funzioni o un grafico convincente non la scavalcano.

| Ordine | Passaggio | Stato tracciato al 21/10 | Condizione per proseguire |
| --- | --- | --- | --- |
| 1 | **G0 — Verifica source-bound del delta spot** | Riportata come eseguita nella cronologia KDD | Evidenze originarie recuperabili e verificabili |
| 2 | **G2 — Esperimento delimitato su candidati reali** (INJ, QNT, AVA, PUMP) | Riportato come eseguito; segnalato contributo informativo, **non prova di redditività** | Separare riscontri da ipotesi e limiti sperimentali |
| 3 | **Decisione/adjudication sul delta spot**: mantenere, limitare oppure scartare | **CHIUSA per il campione A/B del 19/10: USO LIMITATO** | Il 21/10 Termux ha verificato hash A/B, 12/12 orizzonti e 0/4 cambi d'azione; generalizzabilità e redditività non dimostrate |
| 4 | **Una sola integrazione successiva**, delimitata dal giudizio | **NON APERTA** | Scelta umana, perimetro, dati, regressioni e criterio di successo |
| 5 | **Motore decisionale GPT per casi reali** | **DA CONSOLIDARE dopo i gate precedenti** | Confronto di candidati reali, condizioni d'ingresso/uscita, invalidazione, spread, book, volumi, fee, alternative e opportunità non eseguite; nessuna delega di ordini |

I passi G0/G2 e i nomi dei quattro candidati sono ricostruiti **dalla cronologia del lavoro in chat**, non elevati in questo file a prova indipendente: la revisione delle evidenze originali resta necessaria per chiudere il punto 3.

Il grafico SUI/EUR 15m–1H–4H–1D e il pannello multitimeframe già realizzati costituiscono **capacità preservate**; non modificano l'ordine di adjudication né aprono una nuova fase sperimentale. Migliorie estetiche, autostart del server, anomalie volume, altri timeframe, indicatori e fonti sono osservazioni da accodare **soltanto se** richieste dal passo autorizzato e supportate da evidenza.

## 3. Capacità analitiche che accompagneranno il motore, senza anticiparne la costruzione

Al raggiungimento del passo 5, le proposte dovranno tenere conto congiuntamente di:

- **Regime generale e locale:** BTC, dominio e forza relativa, struttura multitimeframe, rotazione settoriale, segnali di transizione.
- **Qualità del movimento:** prezzo, volumi e confronto con il passato, liquidità effettiva, profondità e spread, rischio di wick/manipolazione, condizioni di conferma e invalidazione.
- **Contesto esterno verificato:** macroeconomia (tassi, liquidità, dollaro), notizie e geopolitica con fonti/tempi espliciti; distinguere fatti, interpretazioni e vuoti di copertura.
- **Decisione eseguibile manualmente:** coppia Kraken realmente disponibile, importo/quantità e minimi, commissioni, slippage stimato e scenario netto; compatibilità con investimento pluriennale e quota tattica.
- **Alternative reali:** long tattico, riduzione, uscita in stablecoin, rotazione, attesa motivata e scenari in cui l'ipotesi diventa falsa.

Non fissare come unico scanner i token già saliti dell'8–20%: ricercare anche **movimenti iniziali, consolidamenti e ripartenze**. Nessuna statistica descrittiva deve essere presentata come probabilità predittiva senza verifica indipendente.

## 4. Posizione sugli short — acquisizione del 21/10/2026

**ANALISI SHORT: AMMESSA COME OGGETTO DI STUDIO**, per valutare regimi ribassisti, perdite di struttura, failed breakout, funding/OI e costo/rischio teorico, anche quando la decisione spot più adatta è uscire o restare liquidi.

**SHORT REALI: NON AUTORIZZATI.** Restano sospesi: aperture short, futures, margin, leva, ordini automatici, prestiti o attivazioni di permessi API. L'eventuale studio di opportunità short non implica alcuna autorizzazione alla loro esecuzione. Solo una **nuova scelta esplicita dell'autore**, preceduta da verifica di modalità, rischio massimo, liquidazione, funding, costi e permessi, potrebbe modificarlo.

Non anticipare un nuovo laboratorio sugli short prima della chiusura del nodo delta spot; l'apertura analitica è una **specifica futura**, non un GO sperimentale.

## 5. Criteri di successo e anticorpi contro la deriva

L'obiettivo è migliorare la **qualità verificabile delle decisioni**, non sommare grafici o test. Conservare risultati e non-risultati, trade ipotetici distinti da ordini reali, timestamp, costi, campioni comparabili e ragioni di ingresso, uscita e mancato intervento. Non dedurre redditività da test software PASS.

Ogni modifica tecnica passa per ramo/commit revisionabile, test preventivo `kdd-aggiorna --check`, eventuale applicazione volontaria `--apply` con backup e test, e prova sul Samsung se cambia il comportamento visivo. **La pubblicazione su GitHub non installa software né modifica il conto Kraken.**

**Giudizio del 21/10 — delta spot:** **USO LIMITATO**, osservazione di microstruttura con fonte, coppia, finestra, copertura e freschezza verificabili; non segnale di trading né ranking predittivo. La prova A/B (SUI, QNT, PUMP, ONDO) è stata controllata in Termux: **hash A/B coerenti, 12/12 chiusure a +1h/+4h/+24h osservate, zero cambiamenti di azione su quattro**. Tutti i delta della candela erano negativi mentre le chiusure successive dei quattro token risultavano positive. **Conclusione chiusa per il campione storico, non validità generale, non prova di PnL.** Fonte: [GIUDIZIO_DELTA_SPOT_G0_G2.md](GIUDIZIO_DELTA_SPOT_G0_G2.md).

**Prossimo passo:** scelta umana della **singola integrazione successiva**, valutando l'utilità marginale rispetto al motore GPT; il navigatore (fondamentali, macroeconomia, geopolitica) è candidato, **non approvato automaticamente**. L'eventuale ulteriore audit software dei dati locali resta distinto dalla decisione d'uso, già formulata per il campione. **Nessun cantiere avviato automaticamente.**
