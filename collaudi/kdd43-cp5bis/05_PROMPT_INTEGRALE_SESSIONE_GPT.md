# KDD-43 / CP5-bis — Prompt integrale per sessione GPT separata

**Stato attuale: PREPARATO, NON INVIATO AL MODELLO.** Questo testo è lo stimolo congelato per una nuova sessione GPT distinta dalla Costruttrice. Nella prima tornata non effettuare nuove ricerche web.

## Allegati esatti obbligatori
1. `01_BUNDLE_PATRIMONIALE_SOLO_SINTETICO.json`: il bundle intero del KDD, incluse quantità, pesi, liquidità e candidati INVENTATI.
2. `02_CONTESTO_RIVALIDATO_BRIDGE.json`: contesto della stessa fotografia prodotto da `kdd_bridge_g2.read_context`.
3. `04_STIMOLI_CASI_PER_GPT.json`: casi P1–P5 e C1–C6, con documenti pubblici e scenari di test.
4. `06_MANIFEST_FONTI_E_PROVENIENZE.json`: URL di origine, dati di pubblicazione, hash delle acquisizioni, limiti e confini fra fonte pubblica e fixture.
5. Per **C1** anche `08_C1_BUNDLE_SINTETICO.json` e `08_C1_CONTEXTO_BRIDGE.json`.
6. Per **C3** anche `10_C3_BUNDLE_SINTETICO.json` e `10_C3_CONTEXTO_BRIDGE.json`.

**Non allegare** il documento `00_PROTOCOLLO_C0_C4_CONGELATO.md` o il rapporto del revisore: espongono i criteri di giudizio e contaminerebbero la verifica indipendente. Per uno o più allegati non realmente disponibili in chat, dichiara il caso NON VALUTABILE per mancata consegna anziché fingere di averli letti.

## Compito

Interpreta le evidenze economiche del KDD come informazioni falsificabili. Le **tre posizioni BTC/ETH/STRK, il candidato SOL, quantità, valori, liquidità e numeri della supply BTC sono interamente INVENTATI**. Una URL CoinGecko nella fixture NON costituisce una risposta reale CoinGecko; l'etichetta tecnica VERIFICATO non la rende autentica. Le release Bitcoin Core v32.1 e Agave v4.4.1 sono invece fatti pubblici acquisiti e verificabili. La documentazione STRK è un allegato pubblico non acquisito dal produttore del packet. Fed/UE sono nel macro legacy; il `contesto_macro_primario` dell'esempio non contiene notizie attuali. Il checkpoint CP4 per P5 non contiene gli originali HTTP ed è una fonte secondaria.

Per **ciascun** caso P1, P2, P3, P4, P5, C1, C2, C3, C4, C5, C6 restituisci integralmente:

- `case_id` e `evidence_ids` effettivamente letti, con posizione posseduta/candidata o fonte esterna;
- fatti attestati nelle quattro aree **fondamentali, eventi, macro, regime**, separando quanto proviene da packet/bridge/allegato, tempo di pubblicazione, acquisizione ed efficacia;
- fatti soltanto sintetici, fonti assenti, scadute, discordanti e inferenze vietate dalla mancanza di prove;
- ragionamento economico condizionale con pro e contro e **alternative concretamente distinguibili**;
- considerazioni sul patrimonio soltanto con valori, disponibilità, rischi comuni e costi effettivamente presenti, senza inventare fee del conto;
- giudizio provvisorio con `evidence_id → fatto → inferenza → controipotesi → condizione di riesame`;
- motivo preciso dell'eventuale conclusione indeterminata.

Per C1 confronta i due bundle effettivamente rigenerati, per C3 verifica la diversa attribuzione dell'evento, per C2/C4/C5/C6 segnala che le evidenze aggiuntive sono **stimoli esterni di test**, non acquisizioni KDD. Confronta in C6 almeno A, B e l'eventuale rinvio. Non fabbricare l'andamento del prezzo successivo; non raccomandare né eseguire operazioni. Considera mantenimento, incremento, alleggerimento, uscita, rotazione e inattività solo come alternative, alcune non valutabili con questi dati.

In apertura dichiara modello (nome e versione se visibili), data UTC, eventuale ID di sessione, nomi degli allegati realmente letti. **Restituisci l'output integrale**, non una sintesi.
