# KDD-43 — CP5-bis | Primo collaudo interpretativo: rapporto e STOP

**Data:** 17 novembre 2026. **Regime:** G2, PR Draft #73. **Baseline applicativa:** `38ebf2bee30a3542b3220889f050482b22a63b13`. Nessuna modifica funzionale. **Verdetto della fase semantica: NON ESEGUITO.** Non è disponibile nello strumentario di questa sessione una funzione che avvii una **nuova, distinta sessione GPT**, registri il materiale realmente letto e restituisca il transcript completo. Non è stata eseguita né simulata una risposta del modello. Il successo dei controlli Python NON soddisfa il gate C1/M.

## 1. Evidenze congelate, prima delle risposte

- **Criteri C0–C4 e casi P1–P5, C1–C6 congelati PRIMA di qualsiasi output GPT** in `00_PROTOCOLLO_C0_C4_CONGELATO.md`, commit `e3754b0de4b387947e3e4bbef2ffc83951bfc94a`.
- Fonti pubbliche del 17/11/2026: 4 originali HTTP acquisiti nel clone isolato Samsung/Termux e identificati con SHA-256 nel `06_MANIFEST_FONTI_E_PROVENIENZE.json`. Originali byte-per-byte custoditi in `cp5bis_sources` nella cartella isolata del collaudo, **non incorporati integralmente in GitHub**. Pubblicazione UE ufficiale verificata via web, **ma GET diretto HTTP 403** e quindi nessun hash raw; caso P5 basato sul checkpoint CP4, **senza originali Kraken/CoinGecko** recuperati. Nessuna presunta fonte autenticata dove manca.
- Sono depositati **esattamente** i file necessari alla sessione indipendente: `01_BUNDLE_PATRIMONIALE_SOLO_SINTETICO.json`, `02_CONTESTO_RIVALIDATO_BRIDGE.json`, `04_STIMOLI_CASI_PER_GPT.json`, `05_PROMPT_INTEGRALE_SESSIONE_GPT.md`, `06_MANIFEST_FONTI_E_PROVENIENZE.json`, e, per C1/C3, i quattro file `08_C1_*` e `10_C3_*`. Protocollo e rapporto sono destinati al **revisore**, non al modello valutato.

## 2. Prove tecniche realmente osservate

**Ambiente:** esclusivamente un clone isolato Termux del ramo #73. I valori sono inventati, nessuna API privata Kraken e nessun accesso a saldi/credenziali, ordini o installazione operativa.

| Verifica | Risultato |
| --- | --- |
| Generazione con `scripts.kdd_wallet_packet_g0.build` e lettura con il vero `scripts.kdd_bridge_g2.read_context` | **PASS tecnico**: 3 posizioni fittizie BTC/ETH/STRK e 1 candidato fittizio SOL conservati; quattro famiglie economiche esposte su ciascuna riga |
| P1 — release Bitcoin Core v32.1 28/10 | **PASS di attribuzione tecnica** `evento.stato=VERIFICATO` per BTC; nessuna interpretazione GPT |
| P2 — release Agave v4.4.1 05/11 | **PASS di attribuzione tecnica** `evento.stato=VERIFICATO` per candidato SOL; nessuna interpretazione GPT |
| C1 — rimozione fonte supply BTC | **PASS tecnico:** `fondamentali.stato` passa da `VERIFICATO` a `NON_VERIFICATO` nel vero bridge; release BTC invariata `VERIFICATO` |
| C3 — release Solana attribuita a BTC | **PASS tecnico:** `release_event` rifiuta il documento come evento BTC, `evento.stato=NON_VERIFICATO` nel vero bridge |
| P3 | Fonte Starknet originale disponibile nel manifest ma **allegato esterno**, non inserita in `quadro_eventi` KDD del packet |
| P4 | I due documenti Fed/UE figurano nella sezione **macro legacy**; `contesto_macro_primario.fatti` del bridge nella fixture ha **zero fatti** |
| P5 | Mancano i corpi originali dei dati Kraken/CoinGecko usati nel checkpoint CP4: **NON VALUTABILE come caso pubblico primario** |
| C2/C4/C5/C6 | Stimoli sintetici completi nel file `04_*`, ma **non passati come varianti reali del produttore** e non valutati da GPT |

**Integrità degli output generati:** `01_BUNDLE` SHA-256 `dd3cf7d3f14facc4283e39e1e775ada07c61de2e171c2cd67ed9ac663d9db322` (91.539 byte); `02_CONTESTO` SHA-256 `bdd474bf9e275e5dd6c103ce6a0c8cf97944bdf5c89bb5ec7425238372b7aeec` (78.280 byte). Le varianti C1/C3 sono archiviate senza successivo editing dei dati-base. La suite globale CI sull'attuale commit **non è qui dichiarata eseguita/verde**.

## 3. Attribuzione di lacune, errori e insufficienze

| Punto | Osservazione e responsabilità |
| --- | --- |
| **Produttore economico** | La fixture ha fornito supply BTC **completamente inventata** in una struttura che imita CoinGecko; il produttore l'ha accettata come `VERIFICATO` dal punto di vista strutturale. Quello stato non dimostra l'HTTP originario. È una lacuna della **prova d'autenticità del produttore e del perimetro della fixture**, da non trasferire al modello. C3 respinge correttamente la release riferita al progetto sbagliato. |
| **Dossier / packet** | Patrimonio e candidato sintetici conservati; `quadro_economico_per_gpt` contiene tuttora un esempio di liberazione **150 EUR** (`alternative_liberazione_150_lordi`, `esempio_150_...`). Questo obiettivo prefissato è stato **revocato dall'autore il 13/11/2026**. Un modello non deve ripresentarlo come mandato operativo. Difetto di allineamento a Governo/README, pertinenza KDD-02/05. |
| **Bridge** | Le quattro famiglie sono leggibili e i casi C1/C3 sono declassati correttamente. Ma `read_context` **non è l'intero bundle**: quantità, quote patrimoniali e cash dettagliato restano in `bundle.packet.patrimonio`. Se non si inviano entrambi, un'assenza informativa appartiene alla consegna, non all'interpretazione. |
| **Copertura economica** | Per P3 manca l'assorbimento nel produttore della documentazione primaria specifica; per P4 il macro primario del campione è vuoto; per P5 gli originali API sono assenti. Queste lacune sono **a monte di GPT** (KDD-18/20/21/22). |
| **Consegna al modello** | Nessun transcript di sessione GPT separata e nessun record effettivo di allegati letti. **NON ESEGUITA**. |
| **Interpretazione GPT** | Nessuna risposta o conclusione osservata. **Non esistono per ora errori interpretativi GPT riproducibili, né casi superati.** Valutazione indipendente C0–C4 **NON VALUTABILE**. |

## 4. Interventi proposti, nessuno autorizzato/attuato

1. **KDD-23 / valutazione CP5-bis:** svolgere una nuova sessione realmente GPT allegando i file indicati nel prompt, conservare esattamente modello, data, input hash, prompt e risposta integrale; valutare con i criteri congelati **dopo**, senza fornire al modello la rubrica. Non servono API a pagamento.
2. **KDD-18/20:** distinguere inequivocabilmente `schema coerente` da `fonte HTTP autenticamente acquisita` nelle prove; dove manca una fonte primaria, preservare `NON_VERIFICATO`; continuare a richiedere identità e attribuzione puntuale delle notizie, senza nuova infrastruttura.
3. **KDD-21/22:** riprodurre il primo caso macro con `contesto_macro_primario` realmente acquisito e P5 con corpi sorgente originali datati; un vecchio resoconto non sostituisce il dato grezzo.
4. **KDD-02/05:** eliminare in un futuro GO la finalità monetaria fissa di 150 EUR dall'esposizione patrimoniale a GPT; il confronto delle alternative deve riflettere l'obiettivo revocato e restare condizionale a prezzi/costi.
5. **KDD-23, poi KDD-29:** distinguere qualità della giustificazione e utilità economica prospettica, non giudicare sulla sola performance del prezzo. Le sei alternative patrimoniali complessive non sono state collaudate in questa fase.

**STOP dopo la consegna.** KDD-18/20/21/22 **PARZIALI**. CP6 **NON AUTORIZZATO**. PR #73 **Draft**, nessun merge, deploy, nuova PR, implementazione funzionale, spesa o ordine.