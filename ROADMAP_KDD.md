# KDD — Roadmap canonica

**Stato verificabile al 2 novembre 2026.** Unica fotografia operativa. Il [README](README.md) conserva il mandato e la storia; [GOVERNO](GOVERNO_KDD.md) fissa i vincoli. Fonti: commit/CI GitHub, output preflight e postflight Termux, confronto byte dei file live, HTTP locale, schermate Chrome e metadati Drive. Installazione, visualizzazione, dati freschi e decisione economica sono prove distinte.

## 1. Destinazione e criterio di successo

**Un solo KDD** sul Samsung per la **gestione attiva dell'intero patrimonio**: componente strategica prevalente, attività Spot e futura componente Futures long/short, con eventuale quota minoritaria sui derivati. GPT discute il patrimonio, opportunità, alternative, rischio e costi; l'autore decide e opera manualmente. Nessun ordine automatico, nessuna quota o durata rigida imposta dal software.

**Criterio reale:** fotografia datata → dossier → GPT e autore in chat → proposta motivata → ritorno nel KDD → scelta esplicita dell'autore → archivio → riesame su dati aggiornati. Ogni passaggio va provato separatamente.

## 2. Stato del prodotto: codice, Samsung e prove distinti

| Capacità | Stato verificato al 02/11/2026 | Limite / prossimo controllo |
| --- | --- | --- |
| KDD Samsung, home e `/gpt` | **PR #29 e #30 integrate e installate** al commit `ba17ced6d51aedcb9ee19900f906f0127c912d57`. Backup privato; 5 file installati identici al clone sicuro; **227 test KDD e suite GPT/Android/R5 PASS** prima e dopo; server riavviato, HTTP 200 e schermate Chrome della home decision-first. | Distribuzione e prima osservazione visiva CHIUSE. Valore economico su fotografia fresca e interazione completa ancora non dimostrati. Leggibilità mobile migliorabile ma non un nuovo cantiere prioritario. |
| Patrimonio e API Kraken `BalanceEx` | Sola lettura già utilizzata, 10 posizioni rappresentate, pacchetto patrimoniale e 4TF sulla fotografia storica. Ultimo saldo mostrato: **30/10/2026, 15:56:58 UTC**. | Ricontrollare separatamente saldo, disponibilità, mercato e loro timestamp; nessuna nuova interrogazione privata verificata il 02/11. |
| Spot, grafici, quattro timeframe | Catalogo Kraken, scanner, grafici 15m/1H/4H/1D e diagnostica conservati. Home visiva: XRP, LSK, HYPE segnalati per riesame, non per ordini. | Negoziazione per account/SEE, costi eseguibili, analisi comparativa e fondatezza delle segnalazioni ancora da provare su dati freschi. |
| Dossier KDD → Android → Drive → GPT | Handoff 10 posizioni prodotto e trasferito il 31/10; esportazione presente nel codice installato. | File locali dati/report 30/10, pacchetto locale 31/10; in Drive principale il vecchio wallet packet è del 26/10. Nessuna nuova esportazione 02/11 verificata. |
| GPT → Drive → FolderSync → Samsung | **Primo ritorno informativo reale PASS il 01/11** con `proposta_portafoglio.json` del 31/10; la home lo presenta come **NON APPROVATA · IN ATTESA DI DECISIONE**. | Scambio manuale e unidirezionale; proposta storica, non automaticamente attuale o approvata. |
| Archivio e deliberazioni autore | PR #30 conserva gli eventi storici in home anche con report presente; CI differenziale, Red Team e prove Android isolate favorevoli. | Nessuna deliberazione reale su una proposta fresca né riesame successivo collaudati. |
| Futures, on-chain, macro e fonti esterne | Futures destinazione esplicita, non funzione installata; on-chain e contesto esterno parziali. | Non confondere Spot/Futures o fonte pubblicata con provenienza attestata. Integrare soltanto quando cambia il giudizio economico e con mandato specifico. |

**Versioni e prove:** [PR #25](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/25) ponte; [PR #26](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/26) e [PR #28](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/28) baseline Samsung precedente `c92e2cdd14c16d7447e891125e88a4a6bfb1c3f6`; [PR #29](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/29) home decision-first, merge `a4153244f3ea484b7e9e08835e85230ede9c0e8c`, primo postflight STOP e rollback corretto; [PR #30](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/30) riparazione storico eventi, HEAD `c9a86709a0a597f2489a78f29f6f8f66f32ab339`, CI 3/3 PASS, Red Team G0 favorevole con limite probatorio dichiarato, merge `ba17ced6d51aedcb9ee19900f906f0127c912d57`. GO distinti dell'autore per merge e deploy; 02/11 installazione controllata PASS con backup, riavvio e schermate Chrome. Nessun ordine/trasferimento Kraken; le prove storiche rimangono nelle PR e nei commit.

## 3. Ponte KDD–GPT: collegamenti verificati e passaggi aperti

**Percorso esistente da preservare:** Kraken `BalanceEx` sola lettura → portafoglio e dati pubblici con tempi separati → `decision_desk.py`, `dossier_trade.py`, `patrimonio_4tf.py` → `scripts/kdd_wallet_packet_g0.py` / `scripts/kdd_bridge_g2.py` → cartella Android `/storage/emulated/0/KDD_TEST_SAMSUNG/` → FolderSync → [Drive privato](https://drive.google.com/drive/folders/1q0zcu0srqp9gRHwIHo6trCXLI0KCaH20) → GPT/autore → `proposta_portafoglio.json` → FolderSync di ritorno → `scripts/kdd_drive_exchange.py` → KDD. La coppia di ritorno è manuale, senza cancellazioni o pianificazione. Importare non significa approvare. La cronologia del primo handoff rimane nei commit e nelle PR precedenti.

**Stato al 02/11:** la home nuova è integrata, installata e visibile; non occorre riprogettarla. Sono datati 30/10 gli ultimi dati di conto/mercato osservati sul Samsung, 31/10 il file di proposta sul Drive e il packet nella cartella condivisa; nessun nuovo dossier 02/11 nella cartella Drive principale al momento della verifica. Non presumere che un file in trasferimento sia già disponibile.

**Prossimo gate unico: una decisione contestabile sul patrimonio intero fondata su una nuova fotografia.**

1. Con autorizzazione dell'autore alla nuova consultazione privata, aggiornare saldo Kraken **solo in lettura**, mercato e dossier attraverso il comando KDD esistente, verificando timestamp distinti, copertura 4TF e lacune.
2. Preparare il packet privato aggiornato con il percorso installato; trasferirlo solo nella cartella Drive autorizzata e verificarne versione/snapshot al consumo GPT. Escludere chiavi, T0, backup e home Termux.
3. GPT in chat studia patrimonio strategico a gestione attiva e candidati Spot, cerca almeno una fonte esterna pertinente e confronta proposte e alternative concrete: costi, disponibilità, rischi, invalidazione, condizioni di ingresso/uscita e riesame, oppure non-intervento motivato. Non inventare prezzi eseguibili o riattualizzare automaticamente la proposta del 31/10.
4. Solo dopo discussione e scelta esplicita dell'autore, pubblicare la proposta e verificarne il ritorno nel KDD. Deliberazione, archivio e riesame sono un secondo gate da provare su una scelta reale **senza ordini** e senza approvare per test una proposta vecchia.
5. Aprire nuovi lavori G2 soltanto per difetti concreti emersi nel ciclo economico; la scheda GPT lunga su Chrome è un limite d'uso osservato, non un motivo sufficiente per altra dashboard.

**Successo richiesto:** fotografia → dossier → analisi/discussione GPT-autore → proposta motivata e pubblicata → scelta esplicita dell'autore → archivio → riesame successivo. Test verdi e schermate, da soli, non equivalgono al risultato economico.

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

**Fonti per chi subentra:** [README e mandato originale](README.md), [Governo](GOVERNO_KDD.md), [mandato di subentro fino a EOF](SUBENTRO_SUPERVISIONE_APICALE.md), [procedura Termux](AGGIORNAMENTI_TERMUX.md), [PR #26](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/26), [PR #28](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/28), [PR #29](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/29), [PR #30](https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK/pull/30), sorgenti `serve.py`, `scripts/kdd_drive_exchange.py`, `scripts/kdd_bridge_g2.py`, `scripts/kdd_aggiorna.py`, `decision_desk.py`, `piano_gpt.py` e `verifica_piani.py`. La ROADMAP è la fonte dello stato **attuale**; le prove di novembre sostituiscono le diagnosi del 31/10 sul mancato ritorno automatico. Le letture EOF e le controprove storiche restano documentate nel versionamento precedente, senza attribuire loro nuovi collaudi.
