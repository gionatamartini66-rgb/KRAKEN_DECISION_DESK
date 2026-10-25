#!/usr/bin/env python3
"""KDD G0: prepare ONE private wallet-first GPT analysis packet from current KDD files.

Read-only for KDD originals. No network, Kraken orders, Drive or FolderSync.
An explicit --write-private writes only under Termux's app-private state directory.
This is a prototype on an isolated branch, not a live KDD component.
"""
from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import stat
import tempfile

SCHEMA = "kdd_wallet_analysis_packet_v001"
UTC = dt.timezone.utc
DEFAULT_SOURCE = Path.home() / "kraken-decision-desk" / "KRAKEN_DECISION_DESK_V001"
PRIVATE_OUTPUT = Path.home() / ".local" / "state" / "kraken-decision-desk" / "wallet_packet_gpt_v001.json"
SRC_MAX = {"portafoglio.json": 2_000_000, "ultimo_report.json": 9_000_000,
           "ultima_rilevazione.json": 15_000_000, "dossier_multifonte.json": 15_000_000}
SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,19}$")


class PacketError(ValueError):
    """Failure message contains no portfolio values."""


def read_json(root: Path, name: str) -> dict:
    """Read only a known, regular JSON, never a symlink or unrelated credentials."""
    path = root / name
    try:
        if path.is_symlink():
            raise PacketError("Input non regolare: " + name)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or not 2 <= info.st_size <= SRC_MAX[name]:
            raise PacketError("Input assente o fuori misura: " + name)
        with path.open("rb") as stream:
            raw = stream.read(SRC_MAX[name] + 1)
        if len(raw) > SRC_MAX[name]:
            raise PacketError("Input fuori misura: " + name)
        result = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PacketError("Input non leggibile: " + name) from exc
    if not isinstance(result, dict):
        raise PacketError("Input non oggetto: " + name)
    return result


def when(value, label: str) -> dt.datetime:
    if not isinstance(value, str):
        raise PacketError("Orario assente: " + label)
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("naive")
        return result.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise PacketError("Orario non valido: " + label) from exc


def amount(value, label: str, *, nonnegative=True):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise PacketError("Numero non valido: " + label)
    try:
        v = Decimal(str(value))
    except InvalidOperation as exc:
        raise PacketError("Numero non valido: " + label) from exc
    if not v.is_finite() or (nonnegative and v < 0):
        raise PacketError("Numero non valido: " + label)
    return format(v, "f")


def safe_symbol(value, label="token"):
    if not isinstance(value, str) or not SYMBOL.fullmatch(value):
        raise PacketError("Identificativo non valido: " + label)
    return value


def safe_notes(items, max_items=6):
    if not isinstance(items, list):
        return []
    return [x[:240] for x in items[:max_items] if isinstance(x, str)]


def source_status(timestamp: dt.datetime, current: dt.datetime, *, max_age_min=30):
    age = round((current - timestamp).total_seconds() / 60, 2)
    if age < -2:
        return {"stato": "OROLOGIO_INCOERENTE", "eta_minuti": None}
    if age < 0:
        return {"stato": "OROLOGI_DISALLINEATI", "eta_minuti": None}
    return {"stato": "RECENTE" if age <= max_age_min else "DA_AGGIORNARE",
            "eta_minuti": age}


def brief_positions(portfolio: dict, report: dict, snapshot: dict, dossier: dict,
                    dossier_fresh: bool) -> list[dict]:
    all_positions = portfolio.get("posizioni")
    reported = report.get("posizioni")
    if not isinstance(all_positions, list) or not isinstance(reported, list):
        raise PacketError("Posizioni non leggibili")
    by_report = {}
    for row in reported:
        if not isinstance(row, dict):
            raise PacketError("Riga report non valida")
        token = safe_symbol(row.get("token"))
        if token in by_report:
            raise PacketError("Posizione duplicata nel report")
        by_report[token] = row
    selected = []
    seen = set()
    for row in all_positions:
        if not isinstance(row, dict):
            raise PacketError("Riga portafoglio non valida")
        token = safe_symbol(row.get("token"))
        if token in seen:
            raise PacketError("Posizione duplicata nel portafoglio")
        seen.add(token)
        qty = amount(row.get("quantita"), "quantita")
        matched = by_report.get(token)
        if qty is not None and matched is None:
            raise PacketError("Posizione mancante dal report")
        # An original report with an unavailable EUR pair omits qty: keep token
        # and original qty, but never invent a price or substitute another quote.
        if qty is not None and matched and "quantita" in matched:
            if Decimal(qty) != Decimal(amount(matched["quantita"], "quantita report")):
                raise PacketError("Quantita report/portafoglio diversa")
        if matched and "errore" not in matched:
            price = amount(matched.get("prezzo_eur"), "prezzo_eur")
            val = amount(matched.get("valore_eur"), "valore_eur")
            pnl = amount(matched.get("pl_non_realizzato_eur"), "pl_indicativo", nonnegative=False)
            if (price is None) != (val is None):
                raise PacketError("Prezzo/valore incompleto")
        else:
            price, val, pnl = None, None, None
        tr = snapshot.get("trends", {}).get(token) if isinstance(snapshot.get("trends"), dict) else None
        if not isinstance(tr, dict):
            tr = {}
        technical = {}
        for field in ("var_7g_pct", "var_30g_pct"):
            if tr.get(field) is not None:
                technical[field] = amount(tr[field], field, nonnegative=False)
        if type(tr.get("sopra_media20")) is bool:
            technical["sopra_media20"] = tr["sopra_media20"]
        chart = dossier.get("grafici_4h", {}).get(token) if dossier_fresh and isinstance(dossier.get("grafici_4h"), dict) else None
        chart_info = {"stato": "NON_DISPONIBILE"}
        if isinstance(chart, dict):
            status = str(chart.get("stato", "NON_DISPONIBILE"))
            # KDD's real 4H contract uses OK / LACUNE_TEMPORALI, not COMPLETO.
            # Never attribute a chart without checking both token and exact EUR pair.
            markets = snapshot.get("markets")
            market = markets.get(token) if isinstance(markets, dict) else None
            expected_pair = market.get("pair") if isinstance(market, dict) else None
            if (chart.get("token") == token and isinstance(expected_pair, str)
                    and chart.get("coppia") == expected_pair and status in ("OK", "LACUNE_TEMPORALI")):
                chart_info = {"stato": status, "coppia": expected_pair,
                              "fonte": "dossier_multifonte.json",
                              "limiti": "4H descrittivo, solo candele chiuse, non segnali di acquisto"}
                if status == "OK" and isinstance(chart.get("lettura_indicativa"), dict):
                    levels = chart["lettura_indicativa"]
                    summary = {}
                    if isinstance(levels.get("ultima_chiusura_utc"), str):
                        when(levels["ultima_chiusura_utc"], "ultima chiusura 4H")
                        summary["ultima_chiusura_utc"] = levels["ultima_chiusura_utc"][:40]
                    for frame in ("ultime_4", "ultime_12", "ultime_24", "ultime_48"):
                        info = levels.get(frame)
                        if isinstance(info, dict):
                            low = amount(info.get("minimo"), frame + " minimo")
                            high = amount(info.get("massimo"), frame + " massimo")
                            if low is not None and high is not None and Decimal(low) <= Decimal(high):
                                summary[frame] = {"minimo": low, "massimo": high}
                    for volume in ("volume_ultime_4", "volume_4_precedenti"):
                        if levels.get(volume) is not None:
                            summary[volume] = amount(levels[volume], volume)
                    chart_info["lettura_4h"] = summary
        selected.append({"token": token, "quantita_spot": qty,
                         "disponibile_spot": amount(row.get("disponibile_spot"), "disponibile_spot"),
                         "prezzo_eur": price, "valore_eur": val,
                         "pl_indicativo_eur": pnl, "variazione": technical,
                         "annotazioni_kdd": safe_notes(matched.get("note")) if isinstance(matched, dict) else [],
                         "decisione_precedente": str(matched.get("decisione", ""))[:240] if isinstance(matched, dict) else "",
                         "grafico_4h": chart_info,
                         "limite": "Nessun prezzo EUR provato" if price is None else "Prezzo indicativo non eseguibile"})
    if set(by_report) - seen:
        raise PacketError("Posizioni nel report ma non nel portafoglio")
    return selected


def public_shortlist(snapshot: dict) -> list[dict]:
    out = []
    src = snapshot.get("schede_v02")
    if not isinstance(src, list):
        return out
    for x in src[:4]:
        if not isinstance(x, dict):
            continue
        token = x.get("token")
        if not isinstance(token, str) or not SYMBOL.fullmatch(token):
            continue
        out.append({"token": token,
                    "categoria": str(x.get("categoria") or "")[:100],
                    "esito_kdd": str(x.get("esito") or "")[:100],
                    "coppia_analisi": str(x.get("coppia_analisi") or "")[:70],
                    "motivazione": str(x.get("perche_selezionato") or "")[:350],
                    "sintesi": str(x.get("sintesi") or "")[:350],
                    "evidenze": safe_notes(x.get("evidenze")),
                    "criticita": safe_notes(x.get("criticita"))})
    return out


def cash_balances(portfolio: dict, report: dict) -> dict:
    raw = portfolio.get("liquidita_spot_api")
    report_cash = report.get("liquidita_spot_api")
    if raw is None and report_cash is None:
        return {}
    if not isinstance(raw, dict) or not isinstance(report_cash, dict):
        raise PacketError("Liquidita incoerente")
    result = {}
    for key in ("EUR", "USD", "USDC", "EURC"):
        v = raw.get(key, {})
        r = report_cash.get(key, {})
        if not isinstance(v, dict) or not isinstance(r, dict):
            raise PacketError("Liquidita incoerente")
        for field in ("saldo", "disponibile"):
            if amount(v.get(field), "saldo") != amount(r.get(field), "saldo report"):
                raise PacketError("Liquidita report/portafoglio diversa")
        result[key] = {"saldo": amount(v.get("saldo"), "saldo"),
                       "disponibile": amount(v.get("disponibile"), "disponibile")}
    return result


def build(root: Path, now: dt.datetime | None = None) -> dict:
    """Compose with explicit stale flags. No external calls, writes or auto-approval."""
    now = now or dt.datetime.now(UTC)
    if now.tzinfo is None:
        raise PacketError("Ora senza timezone")
    now = now.astimezone(UTC)
    portfolio = read_json(root, "portafoglio.json")
    report = read_json(root, "ultimo_report.json")
    snapshot = read_json(root, "ultima_rilevazione.json")
    dossier = read_json(root, "dossier_multifonte.json")
    r_time = when(report.get("rilevazione_utc"), "report")
    s_time = when(snapshot.get("rilevazione_utc"), "mercato")
    if r_time != s_time:
        raise PacketError("Report e mercato da acquisizioni differenti")
    d_time = when(dossier.get("kraken_istantanea_utc"), "dossier")
    dossier_fresh = d_time == s_time
    balance_date = portfolio.get("data_ora_saldo_privato_utc")
    balance = when(balance_date, "saldo") if balance_date else None
    status_market = source_status(s_time, now)
    status_saldo = source_status(balance, now) if balance else {"stato": "ORIGINE_SCONOSCIUTA", "eta_minuti": None}
    if not str(portfolio.get("fonte_quantita") or "").startswith("Kraken BalanceEx API privata SOLA LETTURA, "):
        status_saldo = {"stato": "ORIGINE_SCONOSCIUTA", "eta_minuti": None}
    if balance and balance > now + dt.timedelta(minutes=2):
        status_saldo = {"stato": "OROLOGIO_INCOERENTE", "eta_minuti": None}
    positions = brief_positions(portfolio, report, snapshot, dossier, dossier_fresh)
    cash = cash_balances(portfolio, report)
    incomplete = any(x["prezzo_eur"] is None for x in positions) or any(x["quantita_spot"] is None for x in positions)
    total = amount(report.get("totale_stimato_eur"), "totale_stimato_eur")
    if total is None:
        raise PacketError("Totale stimato mancante")
    valued_sum = sum((Decimal(x["valore_eur"]) for x in positions if x["valore_eur"] is not None), Decimal(0))
    # KDD computes total as float; tolerate at most one cent rounding, not fake complete values.
    if abs(valued_sum - Decimal(total)) > Decimal("0.01"):
        raise PacketError("Totale stimato non coincide con posizioni")
    return {"schema": SCHEMA, "tipo": "DATI_PERSONALI_PATRIMONIALI_NON_PUBBLICATI",
            "generato_utc": now.isoformat(timespec="seconds"),
            "rilevazione_kdd_utc": s_time.isoformat(timespec="seconds"),
            "timestamp_mercato_semantica": "ora di composizione KDD, non ora nativa Kraken",
            "mercato": status_market,
            "saldo": {"ultima_acquisizione_utc": balance.isoformat(timespec="seconds") if balance else None,
                      "stato": status_saldo,
                      "tentativo": str(report.get("saldo_stato", {}).get("ultimo_tentativo", "NON_DOCUMENTATO"))[:60]
                      if isinstance(report.get("saldo_stato"), dict) else "NON_DOCUMENTATO"},
            "dossier": {"coerente_con_mercato": dossier_fresh,
                        "stato": "UTILIZZABILE_CON_LIMITI" if dossier_fresh else "RILEVAZIONE_DIFFERENTE_NON_ATTRIBUIRE_LIVELLI"},
            "patrimonio": {"posizioni": positions, "liquidita_spot": cash,
                           "totale_stimato_eur_senza_cash": total,
                           "totale_parziale": bool(report.get("totale_parziale")) or incomplete,
                           "n_posizioni": len(positions)},
            "scenario_mercato_kdd": str(report.get("mercato", "NON_DETERMINATO"))[:300],
            "opportunita_esterne_scanner": public_shortlist(snapshot),
            "nessun_ordine": True,
            "richiesta_gpt": "Valuta prima TUTTE le posizioni possedute; per ognuna mantenere/incrementare/alleggerire/uscire/ruotare e alternative, con dati e limiti. Solo poi confronta opportunita esterne. Non inventare prezzi, notizie, commissioni, performance o esecuzioni; ricerca fonti attuali indipendenti e proponi opzioni all'autore, mai ordini automatici.",
            "limiti": ["Prototipo G0 locale: nessun trasferimento a Drive o chat senza consenso dell'autore.",
                      "Prezzi indicativi; saldi e mercato hanno orari indipendenti.",
                      "P/L nullo non significa pareggio: costo storico non attestato.",
                      "Dati vecchi non sono dati attuali alla lettura GPT: rivaluta freschezza.",
                      "Dossier 4H non disponibile per tutti gli asset; non attribuire una coppia ad altra."]}


def write_private(packet: dict, target: Path | None = None) -> None:
    """Explicit opt-in; target must be the sole app-private canonical location."""
    if target is None:
        target = PRIVATE_OUTPUT
    if target != PRIVATE_OUTPUT:
        raise PacketError("Destinazione privata non autorizzata")
    folder = target.parent
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if folder.is_symlink() or target.is_symlink():
        raise PacketError("Percorso non regolare")
    if target.exists() and not target.is_file():
        raise PacketError("Destinazione non regolare")
    fd, tmp = tempfile.mkstemp(prefix=".wallet_gpt_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(packet, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None):
    parser = argparse.ArgumentParser(description="KDD: ispezione patrimoniale G0 in staging privato; nessuna pubblicazione")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--write-private", action="store_true", help="crea solo un file privato 0600, non esporta")
    args = parser.parse_args(argv)
    try:
        packet = build(args.source_dir)
        if args.write_private:
            write_private(packet)
    except PacketError as exc:
        print("STOP G0:", str(exc))
        return 1
    print("KDD WALLET G0: OK | posizioni valutate:", packet["patrimonio"]["n_posizioni"],
          "| mercato:", packet["mercato"]["stato"],
          "| saldo:", packet["saldo"]["stato"]["stato"],
          "| dossier:", packet["dossier"]["stato"],
          "| output:", "PRIVATO, NON SINCRONIZZATO" if args.write_private else "NESSUNO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
