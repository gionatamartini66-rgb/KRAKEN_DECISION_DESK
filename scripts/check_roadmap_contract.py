#!/usr/bin/env python3
"""KDD 29-point roadmap integrity gate. Python stdlib only; no financial data/network.

A structural PR check is not an author's GO and does not protect main by itself.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

# Fixed *titles*, taken in order from the 02/11/2026 inventory in ROADMAP_KDD.
# Change requires an explicit new mandate from the author, not refactoring.
TITLES = ["Kraken BalanceEx read-only, 10 posizioni","Patrimonio strategico gestito asset per asset","T0 convenzionale e registrazione dei movimenti","Analisi concentrazione e allocazione patrimonio","Liquidità USDC e scenari per almeno 150 EUR equivalenti","Kraken Spot: catalogo e scelta coppie","Scanner opportunità in diversi regimi","Quattro timeframe per ogni posizione","Grafici reali 15m/1H/4H/1D","EMA20/50, pivot, swing S/R","Figure candlestick nel contesto","Book Kraken, spread, profondità, costi FX","Benchmark Binance Spot","Delta spot, esecuzioni Kraken Trades","OI e CVD derivati","Funding, liquidazioni, heatmap, whale trades, Volume Profile","Identità asset, contract, chain e dati on-chain","Tokenomics, supply, unlock, vesting, diluizione","Metriche DeFi (TVL, fees/revenue), DEX liquidity/bridge","Notizie specifiche ai token e fonti primarie","Macroeconomia, geopolitica e scenari","Riconoscimento dei regimi di mercato","GPT interpretazione in chat, intero portafoglio","Catena diretta GPT-chat → Samsung → browser","Proposta unica in cima, comprensibile su mobile","Approvazione, eventi storici e riesame","Aggiornamento ricorrente, sorveglianza, alert","Futures long/short, margine, funding e rischio collaterale","Effettiva utilità economica e qualità della proposta"]
ALLOWED = frozenset({
    "PRESENTE_DA_ACCETTARE", "PARZIALE", "DA_REALIZZARE",
    "SPERIMENTALE", "USO_LIMITATO", "NON_DIMOSTRATO", "COMPLETO"
})
TABLE_HEADER = ("| Casella / ID immutabile | Requisito dell'autore | "
                "Stato di completamento | Fatto verificato (fotografia 02/11) | "
                "Lavoro ancora da svolgere |")
ROW = re.compile(r"^\\|\\s*- \\[([ x])\\] (KDD-\\d{2})\\s*\\|\\s*(.*?)\\s*"
                 r"\\|\\s*([A-Z_]+)\\s*\\|\\s*(.*?)\\s*\\|\\s*(.*?)\\s*\\|$")
REFERENCE = re.compile(r"\\bKDD-\\d{2}\\b")
LEGACY_HEAD = "| Capacità richiesta dall'autore | Stato 02/11, fatto osservabile | Lacuna materiale |"
ARCHIVE_MARKER = "## README OPERATIVO ESTESO — TESTO ORIGINALE, 17–22 OTTOBRE 2026"


class GateError(ValueError):
    pass


def plain(text: str) -> str:
    return re.sub(r"[\x60*]", "", text).strip()


def parse(text: str) -> dict[str, tuple[str, str, str, str, str]]:
    """Return all and only 29 immutable slots; reject malformed/missing entries."""
    if text.count(TABLE_HEADER) != 1:
        raise GateError("Intestazione checklist assente, doppia o modificata")
    beginning = text.find(TABLE_HEADER)
    ending = text.find("\n\n**Fonti storiche/limiti:**", beginning)
    if ending < 0:
        raise GateError("Fine checklist e contesto storico non trovati")
    region = text[beginning:ending]
    lines = region.splitlines()
    if len(lines) != 31 or lines[1].strip() != "| --- | --- | --- | --- | --- |":
        raise GateError("Tabella deve avere intestazione, separatore e 29 righe")
    result: dict[str, tuple[str, str, str, str, str]] = {}
    for i, line in enumerate(lines[2:], 1):
        m = ROW.fullmatch(line.strip())
        if not m:
            raise GateError(f"Riga {i}: sintassi non valida o checkbox/ID assenti")
        checked, ident, label, state, evidence, gap = m.groups()
        expected = f"KDD-{i:02d}"
        if ident != expected:
            raise GateError(f"Identificativi fuori ordine o duplicati: {ident} atteso {expected}")
        if plain(label) != TITLES[i - 1]:
            raise GateError(f"{ident}: requisito originario riscritto o eliminato")
        if state not in ALLOWED:
            raise GateError(f"{ident}: stato non ammesso {state}")
        if len(evidence.strip()) < 18 or len(gap.strip()) < 15:
            raise GateError(f"{ident}: prova/fatto o lacuna non documentati")
        if (checked == "x") != (state == "COMPLETO"):
            raise GateError(f"{ident}: casella e stato COMPLETO in disaccordo")
        if state == "COMPLETO":
            if "PROVA:" not in evidence or "GO-AUTORE:" not in evidence:
                raise GateError(f"{ident}: chiusura senza prova e GO dell'autore")
            if not re.search(r"PROVA:\\s*\\S.{10,}", evidence):
                raise GateError(f"{ident}: PROVA priva di riferimento verificabile")
            if not re.search(r"GO-AUTORE:\\s*\\S.{8,}", evidence):
                raise GateError(f"{ident}: GO-AUTORE privo di riferimento verificabile")
        result[ident] = (checked, label.strip(), state, evidence.strip(), gap.strip())
    if len(result) != 29:
        raise GateError("La checklist deve preservare esattamente 29 identità")
    return result


def original_inventory(text: str) -> None:
    """Permit only the one-time exact migration from the archived 29-row inventory."""
    if text.count(LEGACY_HEAD) != 1 or TABLE_HEADER in text:
        raise GateError("Baseline non conforme: impossibile ricostruire 29 originali")
    first = text.find(LEGACY_HEAD)
    last = text.find("\n\n**Fonti storiche/limiti:**", first)
    if last < 0:
        raise GateError("Inventario originale non terminato")
    lines = text[first:last].splitlines()
    if len(lines) != 31 or lines[1] != "| --- | --- | --- |":
        raise GateError("Inventario originale non ha 29 requisiti")
    for n, line in enumerate(lines[2:]):
        cols = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cols) != 3 or plain(cols[0]) != TITLES[n]:
            raise GateError(f"Inventario originale alterato in riga {n + 1}")


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], text=True, capture_output=True)
    if proc.returncode:
        raise GateError(f"git {' '.join(args[:2])}: {proc.stderr.strip()[:250]}")
    return proc.stdout


def field(body: str, name: str) -> str:
    vals = re.findall(rf"(?m)^{re.escape(name)}:\\s*(.+)\\s*$", body)
    if len(vals) != 1 or len(vals[0].strip()) < 9:
        raise GateError(f"PR: campo obbligatorio {name} assente/ambiguo")
    return vals[0].strip()


def check_pr(base: str, head: str, body: str) -> dict:
    """Enforce 29 IDs AND a meaningful per-ID roadmap update on each G2 PR."""
    if not re.fullmatch(r"[a-f0-9]{40}", base) or not re.fullmatch(r"[a-f0-9]{40}", head):
        raise GateError("PR: riferimenti Git SHA esatti richiesti")
    current = git("show", f"{head}:ROADMAP_KDD.md")
    preceding = git("show", f"{base}:ROADMAP_KDD.md")
    now = parse(current)
    if TABLE_HEADER in preceding:
        before = parse(preceding)
        changed = {k for k in now if now[k] != before[k]}
    else:
        original_inventory(preceding)
        changed = set(now)
    files = set(git("diff", "--name-only", base, head).splitlines())
    if "ROADMAP_KDD.md" not in files or not changed:
        raise GateError("PR senza aggiornamento concreto di almeno una riga ROADMAP")
    ids_field = field(body, "ROADMAP-IDS")
    ids = [x.strip() for x in ids_field.split(",")]
    if len(set(ids)) != len(ids) or not ids or any(x not in now for x in ids):
        raise GateError("ROADMAP-IDS: identificativi duplicati, inesistenti o malformati")
    if set(ids) != changed:
        raise GateError("ROADMAP-IDS differenti dalle righe realmente modificate: "
                        f"dichiarate={sorted(ids)}, modificate={sorted(changed)}")
    field(body, "MANDATO-AUTORE")
    field(body, "PROVE")
    merge_status = field(body, "GO-MERGE")
    if merge_status not in ("PENDENTE - SERVE DECISIONE ESPLICITA DELL'AUTORE",
                            "RICHIESTO - NON EQUIVALE AD AUTORIZZAZIONE"):
        raise GateError("GO-MERGE deve restare pendente nella PR; il controllo non può dare GO")
    if "GOVERNO_KDD.md" in files:
        raise GateError("PR modifica il GOVERNO: STOP; richiede specifico mandato dell'autore")
    if "README.md" in files:
        old_readme = git("show", f"{base}:README.md")
        new_readme = git("show", f"{head}:README.md")
        if (ARCHIVE_MARKER not in old_readme or ARCHIVE_MARKER not in new_readme
                or old_readme.split(ARCHIVE_MARKER, 1)[1]
                != new_readme.split(ARCHIVE_MARKER, 1)[1]):
            raise GateError("Il mandato originale conservato nel README è stato modificato")
    return {"changed_ids": sorted(changed), "files": sorted(files)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roadmap", default="ROADMAP_KDD.md")
    parser.add_argument("--check-pr", action="store_true")
    args = parser.parse_args()
    try:
        entries = parse(Path(args.roadmap).read_text(encoding="utf-8"))
        print(f"KDD roadmap: {len(entries)}/29 identità integre, "
              f"{sum(x[2]=='COMPLETO' for x in entries.values())} chiuse")
        if args.check_pr:
            check = check_pr(
                os.environ.get("KDD_BASE_SHA", ""),
                os.environ.get("KDD_HEAD_SHA", ""),
                os.environ.get("KDD_PR_BODY", ""))
            print(f"PR tracciata a {', '.join(check['changed_ids'])}; "
                  f"{len(check['files'])} file modificati. GO-MERGE resta umano.")
    except (GateError, OSError, UnicodeError) as exc:
        print(f"STOP GOVERNO ROADMAP: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
