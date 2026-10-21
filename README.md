# KRAKEN DECISION DESK (KDD) — repository tecnico privato

**Stato operativo (20 ottobre 2026):** repository privato collegato a ChatGPT e a Termux; importati **19 file tecnici** con commit `3fab216ac1c66cb03f6d57c5c42bd1fdbb7ac175`, dopo 109/109 test locali superati. Il programma vivo continua sul Samsung. L'aggiornatore GitHub → Termux è ora disponibile nel repository, con 4 test isolati PASS (dry run/applicazione simulata/nessun cambiamento/rollback). **Aggiornatore installato e collaudato sul Samsung il 20 ottobre 2026**: test 109/109 prima e dopo un deploy innocuo, backup locale creato, verifica senza alterare portafoglio e credenziali. L'indicazione precedente di collaudo ancora in attesa è superata.

## Scopo
KDD rileva dati di mercato pubblici Kraken e Binance, conserva fonti e orari, aiuta a esaminare strutture tecniche e condizioni di liquidità; GPT interpreta e formula proposte, l'autore discute e decide. Solo l'autore esegue eventuali ordini manualmente. **Operatività reale iniziale: spot, nessuno short, futures o leva e nessun ordine automatico. Analisi di scenari short consentita senza esecuzione.** Il patrimonio strategico è **a gestione attiva**, non un vincolo a conservare ogni token.

## Indirizzo strategico e roadmap — decisione dell'autore, 21 ottobre 2026

**KDD «cross-over»: la capacità decisionale deve valere in regimi rialzisti, laterali, ribassisti e di transizione.** Non dipendiamo da un mercato sempre rialzista: in spot il sistema deve saper distinguere rimbalzi, ripartenze, forza relativa, rotazioni fra token, alleggerimenti, uscita o liquidità in USDC, oltre all'eventuale attesa motivata. Un long spot non guadagna direttamente dalla semplice discesa e mantenere USDC comporta rischi propri.

L'autore in passato evitava gli short soprattutto perché gli riusciva più naturale riconoscere i movimenti rialzisti. **Analizzare short e regimi ribassisti è ammesso; eseguire short, futures, margin o leva non è autorizzato.** L'apertura analitica non sblocca di per sé nuove sperimentazioni o permessi. Le scelte restano token-specifiche, sensibili a regime, liquidità, costo reale, macro e geopolitica, senza quote o soglie rigide imposte automaticamente.

**Sequenza già concordata, da preservare:**

1. G0, verifica source-bound del delta spot — riportata come svolta.
2. G2, prova delimitata su INJ, QNT, AVA e PUMP — riportata come svolta; contributo informativo osservato, **nessuna redditività dimostrata**.
3. **Delta spot — uso LIMITATO (giudizio G0 preliminare), validazione scientifica INCOMPLETA:** conservare come dato contestuale con copertura verificata; verificare i file A/B e gli esiti prospettici prima di chiudere il giudizio.
4. Solo dopo, **una integrazione delimitata e motivata** dal giudizio.
5. Consolidamento delle valutazioni GPT su candidati reali, condizioni operative, alternative spot e costi netti.

**Fonti di governo della decisione:** [ROADMAP_KDD.md](ROADMAP_KDD.md), [GOVERNO_KDD.md](GOVERNO_KDD.md) e [GIUDIZIO_DELTA_SPOT_G0_G2.md](GIUDIZIO_DELTA_SPOT_G0_G2.md). Sono documenti del **repository tecnico GitHub**; non sostituiscono il mandato operativo completo conservato sul Samsung né modificano il README privato di Termux. Le fasi G0/G2 sono riportate nella cronologia di lavoro: il codice del delta è stato riletto e la sua funzione tecnica verificata, ma le prove A/B originali e i risultati +1h/+4h/+24h non sono stati acquisiti dal Samsung. Il giudizio d'uso LIMITATO non è una prova di efficacia né una convalida scientifica definitiva.

**Stato operativo dell'infrastruttura, 21/10:** multitimeframe SUI/EUR 15m/1H/4H/1D e confronto fra intervalli verificati visivamente sul Samsung; correzione del 4H live pubblicata e collaudata fino a **125 test** nel ciclo Termux riferito dall'autore. Le sezioni successive del README sono **cronologia dei singoli checkpoint**, perciò eventuali scritte storiche «non ancora installato» non descrivono lo stato attuale.

**Nessun nuovo cantiere viene aperto da questa cristallizzazione.** Si riprende la roadmap dal nodo del delta spot: funzionalità grafiche, volume anomalo, avvio server e analisi short restano capacità, osservazioni o possibili requisiti futuri, senza scavalcare le dipendenze autorizzate. La pubblicazione di questi documenti non installa software sul Samsung né abilita operazioni Kraken.

## Audit offline A/B del delta spot — 21 ottobre 2026

**Stato del codice:** implementazione proposta su ramo GitHub; collaudo Python Termux PENDENTE. Questo intervento è **limitato alla verifica G0/G2 già in roadmap**, non una nuova sperimentazione.

Il modulo già esistente `studio_delta.py` dispone della nuova modalità **sola lettura**, senza accessi Kraken, chiamate di rete o scrittura di file:

```sh
cd ~/kraken-decision-desk/KRAKEN_DECISION_DESK_V001
python studio_delta.py --audit-offline
```

Legge esclusivamente il percorso privato originale `esperimenti_delta/` accanto al modulo Python. Controlla le coppie A/B tramite checksum del file A, unicità/identità dei candidati, integrità SHA256 del file esiti rispetto alla fase B, e per ogni orizzonte +1h/+4h/+24h verifica timestamp e coerenza aritmetica **solo dove il dato è già stato registrato**. Non ricostruisce prezzi assenti; `ASSENTE` non significa fallimento della strategia. Se le fasi usano un campo testuale esplicito omonimo (es. `scelta`), ne dichiara soltanto l'uguaglianza o la differenza **testuale**, non inventa semantiche decisionali né mostra il contenuto.

L'output terminale include solo indicatori di integrità, nomi pubblici dei token e copertura per orizzonte; **mai prezzi, scelte testuali, importi, saldi, hash o contenuto dei file sorgente**. `python studio_delta.py` **senza il flag** mantiene invece la precedente verifica prospettica, che può interrogare Kraken e aggiornare file locali: sono due modalità diverse.

Per installare questa variazione seguire il solito ponte controllato `kdd-aggiorna --check`, poi `--apply` con conferma umana e backup soltanto dopo PASS. Suite attesa: **128 test** (125 precedenti + 3 regressioni specifiche). Il browser KDD non richiede riavvio per questo controllo da terminale. **Nessuno snapshot A/B né altri dati operativi vanno aggiunti a GitHub.** L'output di audit determina se la validazione prospettica è davvero completa; un report `INCOMPLETO` resta INCOMPLETO, senza inferenze.

## Regola di sicurezza fondamentale
**Non trasferire su GitHub dati personali/finanziari, credenziali o stato operativo**. Il repository conserva solo sorgenti selezionati e licenze di dipendenze pubbliche. Rimangono **esclusivamente sul Samsung**:
- `~/.config/kraken-decision-desk/readonly.json` e ogni altro segreto/chiave, anche nei backup;
- `portafoglio.json`, saldi, T0, movimenti e storici, piani GPT, dossier con snapshot, report, file HTML generati e log;
- il README operativo **completo** in Termux, che contiene dettagli patrimoniali e non viene copiato qui;
- `config.json` locale, finché non viene definita una configurazione pubblicabile priva di informazioni private.

Il file `.gitignore` usa una **allowlist** di nomi di file. Non aggirarla usando `git add -f`. È solo una precauzione: i contenuti dei sorgenti vanno comunque controllati prima di pubblicarli, e un file già tracciato non è protetto retroattivamente da .gitignore.

## Importazione e sviluppo
Per il primo trasferimento usare esclusivamente la procedura `IMPORTAZIONE_SICURA.md` e lo script `scripts/importa_codice_termux.sh` da un clone privato distinto dalla cartella KDD live; **non inizializzare Git direttamente nella cartella del programma corrente e non pubblicare tutta la cartella con `git add .`**.

Le modifiche future devono arrivare sul telefono solo tramite aggiornamento controllato dopo test. La nuova procedura documentata in **`AGGIORNAMENTI_TERMUX.md`** aggiorna il clone GitHub separato, collauda le modifiche in staging locale, richiede conferma `APPLICA`, crea backup locali privati e ripete la suite vigente (113 test a questo commit) sul programma, con rollback dei sorgenti in caso di errore. **Collaudata sul Samsung** con commit `3385c9e44a62feb08fd0fd70b23ec20c917eb4fa` (un solo commento in `grafico_4h.py`), test 109/109 ante e post, backup locale verificato dall'output di Termux. Non eseguire `git pull` dentro la cartella runtime. La sostituzione dei file non riavvia il server Chrome già attivo.

## Lavoro grafico
POC grafico SUI/EUR 4H con candele e volumi reali **visualizzato su Chrome Android il 20 ottobre**; non conteneva EMA o livelli perché l'aggiornamento precedente era soltanto il collaudo dell'infrastruttura. **Grafico fase 2 INSTALLATO sul Samsung il 20 ottobre 2026: commit `99cc469f574d3a4111c2dfd17c4ffe8ec0692fa9`, 113/113 test superati sia nel preflight sia dopo la sostituzione, backup locale `20261020T182448-99cc469f57` riportato dall'autore. Riavvio controllato del server Chrome e verifica VISIVA ancora da svolgere**: EMA20/EMA50 seed SMA, strutture di supporto/resistenza 4H con almeno due swing confermati, pivot classici P/S1–S3/R1–R3 basati esclusivamente su un intero giorno UTC precedente (sei candele 4H chiuse), caselle di selezione sul grafico. Modifiche ai soli `grafico_4h.py` e `test_decision_desk.py`, +4 test di regressione. **Non dichiarare la pagina browser aggiornata prima del riavvio del server `serve.py` e della verifica visiva su Android**. Prossimi passi: 15m/1H/1D, figure candlestick contestualizzate, rilettura per decisioni. Tutti i dati devono avere fonte e orario, nessun segnale automatico BUY/SELL.

**Nota:** i test di continuità dei sorgenti dipendono dal README e dalla configurazione locali sul Samsung. Un clone soltanto tecnico può richiedere una fixture di test e una procedura di deploy specifica, da implementare prima di dichiararlo completamente portabile.

## Collaudo visivo Chrome Android — 20/10/2026, ore 20:34 Italia
L'autore ha fornito screenshot del grafico SUI/EUR 4H servito da KDD su Samsung dopo il riavvio del server. **VERIFICA VISIVA POSITIVA** della fase 2: entrambe le EMA20 (oro) ed EMA50 (azzurro) tracciate; tre supporti e tre resistenze strutturali visualizzati; interruttori operativi presenti (toggle pivot mostrato non selezionato); istogramma volumi visibile più in basso. Riferimenti osservati nello screenshot: EMA20 0,888452; EMA50 0,909399; pivot del 19/10 UTC P 0,890233; ultima candela mostrata, apertura 20/10 alle 12 UTC, chiusura prezzo 0,901. **Questo non dimostra che i toggle accendano/spegnano correttamente dopo tap né valida scientificamente l'affidabilità dei livelli di swing; tali prove restano da completare.**
Da migliorare: densità delle etichette sull'asse destro (S/R/EMA sovrapposte), distinguere livelli euristici e confluenze dall'affidabilità provata, estendere in modo verificabile 15m/1H/1D dopo controllo dati chiusi e freschezza. L'ultimo prezzo del grafico è l'ultima chiusura, NON una quotazione live. Non eseguire ordini automaticamente.

## Verifica interruttore pivot — 20/10/2026, ore 20:40 Italia
Secondo screenshot dell'autore su Chrome Android: casella **Pivot giornalieri UTC selezionata** e sette livelli del 19/10 (P, S1-S3, R1-R3) effettivamente visibili in aggiunta a EMA e S/R. Il confronto fra screenshot delle 20:34 e 20:40 conferma che l'interruttore può visualizzare i livelli. Da provare eventualmente disattivazione se necessario. **Problema UI confermato**: numerose etichette prezzo sul bordo destro si accavallano/sfalsano e alcune cifre visualizzate sull'asse paiono incoerenti con i numeri di riepilogo; non usare le etichette come valori precisi finché il rendering non sarà corretto. Prossimo intervento tecnico: decluttering etichette, priorità ai livelli vicini e liste numeriche separate, preservando tracciabilità/formule e distinzione fra valori al tempo corrente e livelli storici.

## FASE 2B — Leggibilità grafico mobile, 20/10/2026
Dopo la prova visuale del pulsante pivot, la revisione 2B è stata **sviluppata su GitHub, ancora NON installata né verificata sul Samsung**. Oggetto: disattivazione delle etichette dei price line sull'asse prezzi (i numeri venivano traslati per evitare collisioni), massimo due supporti e due resistenze strutturali visualizzati sul grafico, solo P + il pivot più vicino sopra e sotto l'ultima chiusura quando l'interruttore è attivo. La sezione espandibile «Tutti i livelli e i prezzi esatti» conserva comunque i **tre supporti, le tre resistenze** e gli **sette pivot** eventualmente calcolabili, con valori precisi e conteggio swing; nessun livello è scartato dai dati originali. In evidenza le vicinanze numeriche entro lo 0,5% tra fonti diverse, espressamente descrittive (non segnali di tenuta). Interruttori EMA e S/R rimangono disponibili. File modificati `grafico_4h.py` e `test_decision_desk.py`; **2 test di regressione aggiunti (suite attesa 115)**. Validazione sintattica JavaScript dell'HTML `PASS` nell'ambiente di sviluppo; **test Python/Chrome sul Samsung ancora da eseguire** con `kdd-aggiorna --check`, poi `--apply` solo dopo PASS. Il riavvio controllato del server locale sarà necessario. 
Prossima fase dopo la prova visuale: dati OHLCV realmente chiusi per 15m/1H/1D, senza interpolazioni e con confronto strutturale multitimeframe; non inventare feed o indicatori.

## FASE 2C — Etichette numeriche e legenda EMA sul grafico, 20/10/2026
**Sviluppata su GitHub ma NON installata né verificata visivamente sul Samsung.**
Commits di codice `f0b8778d65200c5ecec0d0d22963fb710bd7bd0c` e regressione
`2708a9cb13948dcb8deaa6648c60cf9feb13691a`.
La nuova rappresentazione inserisce una piccola legenda EMA20 (oro) / EMA50
(azzurro) dentro l'angolo alto sinistro del grafico prezzi, con visibilità
sincronizzata agli interruttori. Le linee EMA rimangono senza targhe sul
lato destro. I S/R visibili, sempre al massimo due per lato, tornano a mostrare
sull'asse dei prezzi solo il valore numerico, senza il testo `Str S1/R1`.
I pivot restano con etichette sull'asse disabilitate per evitare nuove
collisioni e con valori esatti nella tabella espandibile; le formule, le
candele, gli orari, i toggle e il contenuto dei dati restano invariati.
Regressione preesistente aggiornata per controllare la legenda e la
separazione dei nomi dal prezzo. **Verifica statica dei sorgenti e parsing
JavaScript con V8: PASS**; test Python nell'ambiente Termux e collaudo
visuale su Chrome Android: **DA ESEGUIRE**, tramite procedura controllata
`kdd-aggiorna --check`, eventuale `--apply` solo con preflight positivo,
poi riavvio consapevole del server. La sovrapposizione effettiva dei valori
numerici sul display mobile resta da verificare: se il motore sposta etichette
molto ravvicinate, il dato esatto resta in tabella. Nessun ordine su Kraken.

## Verifica Android fase 2C — 20/10/2026, ore 22:18 Italia
L'autore ha eseguito `kdd-aggiorna --check` e poi `kdd-aggiorna --apply` per
il commit `66ed493c0c6bc425d4da14240be563b37c6d2cca`:
**115/115 test PASS prima e dopo l'applicazione**, con backup locale
`20261020T194800-66ed493c0c`. Il server KDD era già avviato su
`127.0.0.1:8765` (un secondo avvio ha prodotto il normale errore
`Address already in use`), quindi è stato riavviato il processo esistente.
Screenshot di Chrome Android conferma: legenda EMA interna, S/R numerici,
candele e volumi visibili. Dopo "Aggiorna dati ora", la candela 4H con
apertura 20/10 ore 16:00 UTC risulta disponibile, chiusura 0,9061 EUR:
refresh grafico verificato. Persistono tag S/R affollati e arrotondati
a due decimali: **fase 2C completata, limite visivo documentato**.

## FASE 2D — Prezzi S/R più precisi e riduzione collisioni, 20/10/2026
**Codice sviluppato nel repository; NON ancora installato o collaudato in
Chrome Android.** Gli indicatori e i dati OHLCV non cambiano.
La formattazione grafica dei prezzi (candele ed EMA) passa a **5 decimali**
soltanto come rappresentazione, indipendente dal tick negoziabile di Kraken.
Le targhette S/R sono rese quando c'è spazio sufficiente in pixel; quelle
vicine al prezzo di chiusura o ad altre targhette vengono nascoste, ma
**le linee restano alla loro quota reale** e la tabella continua a mostrare
i prezzi calcolati fino a otto decimali. Regola conservativa
`PRICE_LABEL_GAP_PX=30`; recalcolo su zoom, pan e ridimensionamento,
e controllo esplicito del prezzo corrente. I pivot conservano l'asse
senza etichette.
Verifica sintattica del JS `PASS`; simulazione isolata V8 di tre diverse
scale grafiche `PASS` per collisioni fra S/R e close. La suite Python
è stata aggiornata con un nuovo test di rendering, esecuzione Termux
**PENDENTE** (attesi almeno 116 test). Confronto visivo e possibili
aggiustamenti del margine pixel restano necessari dopo l'installazione
controllata. Il prossimo incremento funzionale sarà il multitimeframe
15m/1H/4H/1D, subordinato alla verifica dei dati chiusi disponibili e
delle fonti; nessun segnale BUY/SELL automatico.

## FASE 2D — Hotfix JavaScript del grafico vuoto, 21/10/2026
**Difetto osservato su Chrome Android:** il server e l'aggiornamento saldi
funzionano, ma la pagina SUI/EUR 4H resta a "Preparazione grafico…":
senza candele, volumi o sintesi. Non è un problema di dati Kraken.
**Causa identificata nel codice:** dentro la tripla stringa Python del
template HTML, il frammento JavaScript `sull\\'asse` viene interpretato
da Python come `sull'asse`. Il JavaScript effettivamente inviato al browser
contiene quindi una stringa con apostrofo non protetto, che produce
`SyntaxError: Unexpected identifier 'asse'` prima che il `try/catch`
dello script possa funzionare. I precedenti controlli analizzavano
il testo sorgente prima della trasformazione del template Python: perciò
**116 test PASS non garantivano JavaScript eseguibile nel browser**.

**Rimedio su GitHub:** stringa JavaScript riscritta usando doppi apici,
così l'apostrofo resta parte del testo; nuovo test di regressione che
genera la pagina dal template Python e verifica la stringa effettivamente
emessa. Se Node.js è disponibile, il test prova anche `node --check`
sullo script HTML estratto. Diagnosi del bug riprodotta con parser V8
sulla trasformazione della stringa Python; nuova versione PASS per la
sintassi. I 116 test preesistenti non sono stati eliminati.
**STATO: fix sviluppato, installazione Termux e verifica Chrome PENDENTI.**
L'esito di `kdd-aggiorna --check` deve confermare almeno **117 test**,
prima di ogni installazione. Nessuna modifica ai dati reali, ordini o segreti.

## FASE 3A — Selettore timeframe reale SUI/EUR
**Sviluppo su ramo `feature/sui-real-timeframes-20261021`.**
Sostituiti i pulsanti `Ultime 40 / Ultime 100 / Tutte`, che cambiavano
soltanto lo zoom, con quattro pulsanti per intervalli **reali**:
`15m`, `1H`, `4H`, `1D`. Zoom e scorrimento restano gestuali sul grafico.
La coppia è SUI/EUR Spot Kraken per tutti e quattro gli intervalli.
Il grafico 4H esistente continua a utilizzare le candele CHIUSE già
verificate nel dossier locale KDD, aggiornate da «Aggiorna dati ora».
Per 15m/1H/1D il server effettua, solo alla richiesta della relativa
pagina, una lettura **Kraken Spot REST pubblica** `OHLC` della medesima
coppia con `interval=15/60/1440`, e usa soltanto le ultime 200 barre
effettivamente chiuse. L'ultima riga in formazione restituita da Kraken
è sempre esclusa, anche se erroneamente etichettata come chiusa.
Il parser richiede timestamp UTC allineati e consecutivi, OHLC e volumi
numerici coerenti, e almeno 30 barre: se la fonte non supera tali gate,
KDD segnala errore con HTTP 503, senza interpolare candele o nascondere
lacune. Il server non accede a saldi o chiavi private durante il cambio
timeframe. EMA, S/R e pivot vengono ricalcolati per l'intervallo selezionato;
i pivot richiedono una giornata UTC precedente completa del medesimo
timeframe (96 barre 15m, 24 barre 1H, 6 barre 4H, 1 barra 1D).
I dati 4H in dossier e gli altri intervalli via lettura pubblica possono
avere orari di rilevazione diversi, sempre indicati.

Sorgenti cambiati: `grafico_4h.py`, `serve.py` e regressioni in
`test_decision_desk.py` (+3 test previsti, suite attesa 120).
Nessun dato patrimoniale trasferito a GitHub, nessun ordine inviato.
**Stato: sola implementazione e verifiche statiche, ancora da sottoporre
a `kdd-aggiorna --check` sul Samsung. Non dichiarare installato.**
Dopo il precheck e l'applicazione autorizzata, serve un riavvio controllato
del server `serve.py`, cambiato in questa fase, e una verifica browser
di tutti i quattro pulsanti.

## FASE 3B — Confronto SUI/EUR multitimeframe (21 ottobre 2026)

**Implementazione su ramo `feature/sui-multiframe-desk-20261021`;
non ancora verificata sul Samsung.** Le acquisizioni 15m, 1H e 1D
provengono esclusivamente da `/0/public/OHLC` Kraken Spot, senza chiavi
private né scraping. Il 4H proviene dal dossier locale già verificato.
La pagina di confronto `/analisi/sui-mtf` è raggiungibile dal cruscotto
e da ciascuno dei quattro grafici. Non contiene ordini o pulsanti trading.

Per ciascun intervallo indica: data/ora della propria ultima candela chiusa,
data/ora rilevazione, close, EMA20, EMA50, posizione relativa fra queste
tre grandezze, volume dell'ultima barra rispetto alla media delle **venti
barre precedenti del medesimo timeframe**, e S/R euristici più vicini,
con collegamento al grafico originale. Mostra il riferimento originario
dei dati e impedisce che una rilevazione venga considerata simultanea alle
altre.

Il controllo freschezza confronta la chiusura dell'ultima barra con
il limite UTC completo del suo intervallo (margine tecnico 120 secondi).
Una serie troppo vecchia, incompleta, incongruente o la risposta Kraken
non disponibile producono uno stato separato per quell'intervallo e
**bloccano qualunque conclusione complessiva**. Nessuna interpolazione,
nessuna candela in formazione, nessun dato patrimoniale pubblicato.

Soltanto con tutti i quattro intervalli verificabili, KDD descrive
l'eventuale allineamento o disallineamento di `close > EMA20 > EMA50`
o `close < EMA20 < EMA50`. L'etichetta è una classificazione geometrica,
senza previsione dei rendimenti, senza segnale BUY/SELL e senza autorizzazione
a operare. L'analisi GPT resta autonoma e deve considerare anche liquidità,
spread, book, contesto macro e rischi di esecuzione.

File toccati `grafico_4h.py`, `serve.py`, `test_decision_desk.py`;
+4 nuovi test di regressione (suite attesa almeno **124**), compresi
dati assenti/scaduti, simulazione di indisponibilità Kraken, orientamenti
opposti e rendering HTML mobile. Da eseguire `kdd-aggiorna --check` e
`--apply` solo dopo esito PASS. Serve un riavvio controllato del processo
`serve.py` e una verifica visiva della pagina mobile. Fino a quel momento
lo stato dell'implementazione resta **DA COLLAUDARE SU ANDROID**.

## FASE 3B — Correzione freschezza 4H nel confronto (21 ottobre 2026)

**Difetto osservato sul Samsung:** nel nuovo pannello MTF i dati pubblici 15m,
1H e 1D erano aggiornati, ma 4H risultava `SCADUTO` alle 08:04 UTC
perché il confronto attingeva al dossier locale fermo alla chiusura delle
04:00 UTC anziché interrogare Kraken per quella vista. La regola di
freschezza ha reagito correttamente e ha impedito conclusioni generali;
la causa era una dipendenza di acquisizione, non la formula degli indicatori.

**Correzione proposta nel codice:** `load_sui_comparison` consulta
`/0/public/OHLC` con `pair=SUIEUR` per **tutti e quattro** gli
intervalli (15, 60, 240 e 1440 minuti). Il confronto non consulta più
`dossier_multifonte.json` e non richiede `Aggiorna dati ora`.
Il **grafico 4H separato** mantiene invece deliberatamente il suo dossier:
questa distinzione è dichiarata nella pagina, che mostra sempre la fonte
di ogni riga. Se anche Kraken 4H non fornisce l'ultima candela conclusa,
il risultato resta `SCADUTO`; se manca la risposta, `NON_DISPONIBILE`.
Nessun fallback silenzioso e nessuna interpolazione. Nessuna API privata.

Modificati soltanto `serve.py`, regressioni `test_decision_desk.py`
e questo checkpoint: il test di integrazione precedente simula ora le
quattro richieste pubbliche e vieta la consultazione del dossier; aggiunto
un test avversariale dove Kraken stesso ritarda la chiusura 4H e il
confronto deve restare parziale. **Suite prevista 125 test.**
Stato: **codice su ramo sperimentale, non ancora collaudato su Android**.
Obbligatori precheck, applicazione controllata e riavvio del server prima
di dichiarare la funzione riuscita.
