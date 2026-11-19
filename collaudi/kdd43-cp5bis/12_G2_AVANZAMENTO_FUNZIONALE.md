# KDD-43 — G2 | Avanzamento funzionale dei produttori economici

**18 novembre 2026.** Stessa PR Draft #73, ramo `g2/kdd43-economic-cp1-20261117`. Baseline prima delle modifiche `b95dc72f7a06d82ab402810cca89fee16d4a38ba`. Solo sviluppo in clone Termux isolato; nessun saldo privato, ordine, costo, merge o deploy. Non si modifica il protocollo C0–C4 congelato nel CP5-bis.

## Ricognizione: funzioni esistenti, nessuna duplicazione

Erano già disponibili `dossier_trade.economic_evidence` (identità Kraken/CoinGecko), `kdd_economic_sources.collect` (calendari STRK, SUI, ARB, RPC Solana, RSS Fed/Consiglio, BCE/CFTC), `kdd_economics.tokenomics_view/project_events_view/macro_primary_context/regime_integrato`, `wallet_packet.build` e `kdd_bridge_g2.read_context`. Le assenze nella vecchia fixture CP5-bis non dimostravano assenze equivalenti nel software: la fixture non invocava tutto il ciclo del produttore. Gli interventi sotto correggono provenienza e comunicazione economica, non introducono un altro produttore.

## KDD-18 — Fondamentali/tokenomics

**Capacità corretta:** il produttore pubblico CoinGecko registra richiesta HTTP esatta, ora, SHA-256 **dei byte realmente ricevuti** e identificativo `E-FUND-<progetto>-<hash>`. `fundamentals`, `verify_supply_at_read`, `tokenomics_view` e il quadro integrato distinguono `validita_strutturale` da `provenienza_acquisizione`. Un JSON con numeri plausibili passato direttamente alla funzione può ancora essere strutturalmente `VERIFICATO` per compatibilità, ma dichiara `NON_ATTESTATA_DAL_PRODUTTORE`, senza E-FUND. L'acquisizione passata nel vero percorso produttore espone `RISPOSTA_HTTP_PASSATA_AL_PRODUTTORE` e hash. Provenienza alterata respinta dal bridge anche se si ricalcola il checksum del packet. Supply, FDV, massimi, unlock e vesting restano distinti: i dati di un aggregatore non sono calendario primario né vendita.

**Limiti:** ricevere byte con una richiesta non è attestazione crittografica dell'emittente; le fixture possono imitare un HTTP. Non sono state acquisite e validate risposte originali recenti CoinGecko per l'intero portafoglio. Nessuna operazione con conto reale.

## KDD-20 — Eventi specifici

**Capacità corretta:** ogni documento attribuito produce `E-EVENTO` collegato a progetto, tipo, URL e data; il calendario espone `E-SCHEDULE`, data programmata, massimo quantitativo, e `realizzazione=NON_ATTESTATA` / `vendita=NON_ATTESTATA`. Si riutilizzano i parser ufficiali STRK/SUI/ARB e le release software già presenti. Regressione attraverso produttore → dossier → packet → bridge su **BTC/ETH/STRK (posseduti FINTI) + SOL (candidato FINTO)**; Starknet non è l'unico asset rappresentato.

**Fonte originale pubblica:** [Starknet STRK MDX](https://raw.githubusercontent.com/starknet-io/starknet-docs/main/learn/protocol/strk.mdx), SHA-256 `ea0eb3fda7a088a1d858a082d0c054f4492391c57e88108020b634491cd2c189`; parser sul contenuto originale: prossimo evento 15/12/2026 **fino a 127 milioni STRK**, non avvenuto e non venduto. E-SCHEDULE `E-SCHEDULE-8ed158f20d014ec44ca3`. Sono documentate anche le distinzioni evento software vs adozione reale.

**Limiti:** data nativa di pubblicazione MDX assente; molte fonti primaria token-specifiche non coprono ogni asset/periodo, nessuna vendita effettiva accertata.

## KDD-21 — Macroeconomia

**Capacità corretta:** `contesto_macro_primario` espone `E-MACRO`, URL ufficiale, pubblicazione e precisione temporale, ora raccolta, SHA-256 della **risposta originale prima di rimozione BOM XML**, ipotesi/controipotesi, limiti d'efficacia e causalità. Evidenze BCE/ETF/CFTC continuano a essere un tipo distinto di serie o flusso. Un RSS prova la **pubblicazione del comunicato**, non che la misura sia stata letta o abbia causato un rialzo/ribasso crypto.

**Fonti realmente recuperate il 18/11 alle 08:18 UTC:** Fed Monetary RSS (9.765 byte), SHA `c11f5680803548e827867f643ee584b9503a3b285ffad5bf85fecfd02459d747`; Consiglio UE RSS (13.697 byte), SHA `e8d112753e27e57aef0a8fa5d779621bdd90bbe65f5e59c791d67c9a67af30d4`. I byte originari sono conservati nella directory isolata fuori repository, identificati nel verbale (non ripubblicati). Sette refresh **del vero produttore** tramite replay degli originali entro il limite **6 richieste/ciclo, massimo 8**: **3 comunicati Fed e 4 Consiglio UE**, sette fatti nel contesto. E-MACRO `E-MACRO-d203954708accc28469a` (Fed 28/10) ed `E-MACRO-2de1e40ac363999c1168` (UE 16/11). Digest della lettura coincidente coi byte originali, anche con BOM.

**Limiti:** feed e titoli non sostituiscono esame integrale degli atti, consenso preannuncio, efficacia né misurazione di impatto sui token. Campione macro non copre il mondo.

## KDD-22 — Regime

**Capacità corretta:** si conserva il classificatore CP4 che distingue BTC Kraken 4H/1D e quadro globale CoinGecko (cap + turnover sono **una sola famiglia aggregata**). Ora la famiglia attività include fonte, verificata anche contro la fonte della capitalizzazione; ogni evidenza indipendente ha riferimento `E-REGIME`. Una fonte diversa o stantia rende l'insieme `INDETERMINATO`; un disaccordo tra timeframe BTC con aggregato sufficientemente presente dà `TRANSIZIONE`. I titoli macro non votano una direzione.

**Prove:** trend BTC 4H salita/1D discesa con aggregato valido: `TRANSIZIONE`; sostituzione della fonte turnover con dominio estraneo: `INDETERMINATO`; dopo tre ore: `INDETERMINATO`. Lettura bridge rivalida. **Limite:** mancano ancora i corpi Kraken/CoinGecko originali del checkpoint storico CP4 per riprodurre quel campione dal vivo; regime solo descrittivo, senza previsione economica.

## Rimozione dell'obiettivo revocato 150 EUR dal packet operativo

**Capacità corretta:** percorso attivo `dossier_trade.collect` usa `finanziamento_150_book(target_eur=None)` e produce `profondita_book_pubblica`, che il packet convalida ricostruendo la profondità dai bid e il bridge ricalcola in `book_alla_lettura`. Il nuovo `disponibilita_lorda_spot` valuta **tutte le posizioni** e la capacità lorda indicativa senza soglia di vendita; permane la liquidità *per valuta*, quote/concentrazione, e lo stato `costi_di_negoziazione=NON_VERIFICATI_PER_IL_CONTO`. Non si inferiscono spread, fee personali, conversioni o fill. Le vecchie funzioni col nome `*_150` sono mantenute solo per compatibilità e test storici: **il nuovo packet e bridge non espongono la finalità 150**.

**Prova:** nel bundle sintetico effettivamente prodotto, **0 occorrenze di «150»** nel contenuto patrimoniale e nel contesto bridge, mantenendo **3 posizioni di disponibilità** e i limiti sui costi. Nessun mandato monetario automatico.

## Prove eseguite

- **4 nuovi controlli discriminanti** in `test_kdd_g2_economic_functional.py`: vero codice produttore `economic_evidence` con sorgenti *mock esplicitamente sintetiche*, otto cicli, dossier, `wallet_packet.build`, bundle e `bridge.read_context`; fonte HTTP assente distinta da fonte validata; manipolazione SHA respinta; regime discordante o scaduto; hash XML original bytes anche con BOM
- **84 test economici**, **73 test packet/book**, **4 nuovi controlli G2**: PASS nelle esecuzioni mirate
- **Replay originali pubblici** STRK/Fed/UE su `kdd_economic_sources.collect/at_read` reale, sette cicli, hash originali coincidenti, calendario STRK e sette pubblicazioni macro con identificativi
- **Regressione globale finale dopo correzione BOM:** 411 test, **OK (2 skipped)**, 18/11/2026, esito processo 0; **409 passati + 2 saltati**. Confermata inoltre la suite mirata packet/book **73/73 OK** dopo tutte le modifiche. Il log integrale rimane fuori repository nell'ambiente isolato; nessun accesso al patrimonio privato. Le prove sono tecniche, **non collaudo interpretativo GPT**

## Lacune, verifica indipendente e STOP

KDD-18/20/21/22 restano **PARZIALI** finché la Supervisione non valuta il codice e decide il Red Team. Controlli Red Team proposti: autenticità originale vs struttura JSON, cache e data scaduta, manomissione progetto, ciclo STRK su diversi asset, RSS Fed/UE originale con BOM e doppie letture, conflitto fonte regime, compatibilità vecchi bundle e revoca 150 nell'output attivo. Nessuna roadmap riscritta, nuovo servizio, nuovo ramo o richiesta GPT complessiva.

**STOP dopo la consegna alla Supervisione. PR #73 Draft, nessun merge/deploy, ordine, spesa, uso del patrimonio privato o CP6.**
