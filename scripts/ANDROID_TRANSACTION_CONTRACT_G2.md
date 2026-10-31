# KDD Android Transaction G2 — contratto tecnico congelato PRE-CODICE
Mandato: KDD-PR22-ANDROID-TRANSACTION-G2-UNICO-20261031.
Fonte R5: fc2306fd118024c9bdeb7908d85360c3fc578943; baseline applicativa d6264145b7e49f5c2ca913bfe7dc928a0247d136. Solo laboratorio sintetico. Non è un documento di governo, non autorizza deploy.
## Invarianti immutabili nel G2
I01: finale incompleto mai accettato (falsificatore: consumer lo legge).
I02: digest esatto (falsificatore: byte alterati accettati).
I03: privacy 0600/0700, inode verificato, symlink vietato (falsificatore: input estraneo ammesso).
I04: originale outbox persisted (falsificatore: incoming auto-attestante).
I05: packet/envelope/byte/proposal SHA distinti (falsificatore: alias fra identità).
I06: consenso umano testuale e SHA esatto (falsificatore: diverso SHA accettato).
I07: idempotenza (falsificatore: sovrascrittura o doppia versione).
I08: approvazioni concorrenti dello stesso genitore serializzate (falsificatore: fork).
I09: versioni confermate preservate (falsificatore: perdita).
I10: nessun successo prima del file fsync, rename e directory fsync (falsificatore: successo prima).
I11: nessun cleanup estraneo; journal sospetto STOP (falsificatore: eliminazione generica).
I12: home KDD disponibile con archivio guasto (falsificatore: home indisponibile).
I13: no esecuzione finanziaria (falsificatore: ordine chiamato).
I14: persistence generica, validatori Spot separati da Futures (falsificatore: Futuro richiede nuovo commit backend).
I15: capability preflight prima dei test Android (falsificatore: ignora primitiva assente).
I16: rollback codice non elimina stato privato (falsificatore: perdita).
I17: modello writer cooperativi, esclusività sotto flock, NO garanzia contro writer non cooperativi (falsificatore: claim universale).
## Macchina a stati candidata (da verificare, non implementazione)
Un solo journal .pending-<versione>.json; staging completo e fsync prima di crearne il nome. Journal proprietario 0600, O_EXCL, fsync file e directory. Marker .resolved/.cancelled v3 NON creati dai nuovi tentativi; storici solo letti, eventuali pending v1-v3 = STOP assistito. Ogni interruzione prima del journal crea residuo NON attribuibile da non cancellare; blocco dei nuovi writer quando esiste staging sconosciuto. Journal vuoto o symlink: STOP assistito.
| Confine | Path visibili | Esito e recupero |
|---|---|---|
| Prima dello staging | nessuno | NON_PUBBLICATO; retry consentito |
| Durante staging / dopo fsync | stage senza pending | NON_PUBBLICATO; residuo sconosciuto STOP assistito |
| Dopo lock e verifica | stato precedente verificato | nessuna accettazione del nuovo |
| Journal v004 persistito, prima di rename | stage + pending | NON_PUBBLICATO; riconciliazione esplicita verifica stage, rimuove SOLO quello, cancella pending |
| Dopo rename, prima di fsync directory | finale + pending | PUBBLICAZIONE_INCERTA; reader STOP, recovery fsync directory e verifica finale |
| Dopo fsync directory, prima di unlink pending | finale + pending | fisicamente final synced; reader STOP fino a recovery esplicita |
| Dopo unlink pending, prima di return | finale senza pending | PUBBLICATO_CONFERMATO: unlink raggiungibile soltanto dopo fsync finale riuscito. Nessun fsync della rimozione richiesto per integrità; riapparizione pendente dopo power loss => STOP |
| Retry stesso SHA | finale byte-identico | GIA_PRESENTE; mai overwrite |
| Retry revisione diversa | validare testa sotto medesimo lock | uno solo accettato |
| Riconciliazione altro processo | final e pending o stage e pending | digest/inode/dev/uid/modo verificati; sincronizza; pulizia circoscritta; idempotente |
| File anomalie | symlink, più link, mismatch, marker corrotto | STOP assistito, no promozione |
## Perimetro e modello di fiducia
Writer autorizzati passano dal livello persistente e da flock, nello stesso filesystem per stage/finale, mai via SAF. Rename POSIX sovrascrive un path già apparso tra il check e il rename se writer non cooperativo: rischio NON coperto. Nessun nuovo binario, ctypes o ABI. Non attestare power loss Android. R3/R4/R5 legacy pending incompatibili con il nuovo protocollo: quarantena di fatto mediante rifiuto, NESSUNA migrazione automatica; R5 non distribuita.
## Matrice di impatto congelata
Sorgenti -> wallet.build -> prepare: unchanged semantics, source identity before/after; outbox: new transaction; manual SAF/GPT: byte contract unchanged; proposal/validate: unchanged; origin/consent/approval: gate and locks preserved; archive: recognizes residual, old confirmed docs; dashboard: fail closed, UI still serves Spot; updater: capability preflight, stage, rollback of CODE only; Futures: independent schema, same byte persistence.
## Rilievi
RT4-C1: rename no-replace impossibile da promettere contro noncooperanti. META-01: journal zero-length STOP; META-02: dir fsync del finale PRIMA dell'unlink pending, errore mantiene pending; META-03: consent negative test with valid persisted original + mutant defective.
