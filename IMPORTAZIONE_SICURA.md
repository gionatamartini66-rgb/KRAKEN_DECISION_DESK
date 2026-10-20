# Primo collegamento Termux ↔ GitHub privato (una sola volta)

**Non creare un nuovo progetto al posto del KDD esistente.** Il programma attuale resta in
`~/kraken-decision-desk/KRAKEN_DECISION_DESK_V001/` e continua a funzionare.

La cartella del repository **sarà distinta**:
`~/kraken-decision-desk/KDD_GITHUB_SAFE/`.

## Procedura (solo dal proprio Samsung/Termux)
La prima verifica serve ad accertare che anche Termux — non solo ChatGPT — sia autorizzato a leggere il repository **privato**:

```sh
git ls-remote git@github.com:gionatamartini66-rgb/KRAKEN_DECISION_DESK.git HEAD
```

Se restituisce un hash/una riga, il collegamento SSH a GitHub funziona. Se restituisce
`Permission denied (publickey)`, **fermarsi**: il collegamento GitHub di ChatGPT è separato dalle credenziali SSH di Termux. Non inviare mai token o chiavi in chat e non rendere nuovamente pubblico il repository.

Quando l'accesso è verificato, clonare in una cartella SEPARATA:

```sh
cd ~/kraken-decision-desk &&
git clone git@github.com:gionatamartini66-rgb/KRAKEN_DECISION_DESK.git KDD_GITHUB_SAFE
```

Quindi eseguire il solo importatore verificabile:

```sh
bash ~/kraken-decision-desk/KDD_GITHUB_SAFE/scripts/importa_codice_termux.sh
```

Lo script verifica l'URL del repository, la pulizia del clone, l'esistenza dei sorgenti,
fa i test nella cartella del programma originario e trasferisce **solo** 16 sorgenti Python
esplicitamente ammessi più 3 file pubblici della libreria grafica (script JS + LICENSE + NOTICE).

Non copia `README.md` originale, `config.json`, `portafoglio.json`, T0, report,
ledger, snapshot JSON, risultati dei test, HTML generati, cartelle di backup o
**nessun file di chiavi**. Fa ulteriori controlli sullo staging prima del primo push.

**Limiti:** l'importatore non può garantire matematicamente l'assenza di ogni segreto
incorporato nel testo del codice; resta necessaria la revisione dei sorgenti che si
deciderà di pubblicare. Il repo è privato ma non è un deposito di credenziali.

## Stato
- Repository GitHub creato privato e abilitato al connettore ChatGPT.
- Preparati soltanto i file di sicurezza e la procedura, NON il programma vivo.
- Nessun file del Samsung trasferito finché la procedura non viene eseguita.
- Il sistema di distribuzione degli aggiornamenti **GitHub → Samsung** richiede
ancora progettazione e collaudo: il primo passo è acquisire codice senza dati privati.
