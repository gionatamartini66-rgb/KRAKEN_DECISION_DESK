"""Kraken KDD: read-only private balance client, without trading endpoints."""
import argparse
import base64
import datetime as dt
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path.home()
AUTH = ROOT / ".config" / "kraken-decision-desk" / "readonly.json"
STATE = ROOT / ".local" / "state" / "kraken-decision-desk" / "balances_latest.json"
BASE_URL = "https://api.kraken.com"
ALLOWED = frozenset({"BalanceEx"})
SUFFIXES = (".F", ".S", ".M", ".B", ".T")
NAMES = {
    "XXBT": "BTC", "XBT": "BTC", "BTC": "BTC",
    "XETH": "ETH", "ETH": "ETH",
    "XXRP": "XRP", "XRP": "XRP",
    "ZEUR": "EUR", "EUR": "EUR",
    "ZUSD": "USD", "USD": "USD",
    "XDG": "DOGE", "XXDG": "DOGE",
}

def save_private(path, obj):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        if temp.exists():
            temp.unlink()

def setup():
    if AUTH.exists():
        raise SystemExit("Credenziali già presenti: non sovrascrivo. Usa la gestione chiave prima.")
    print("Inserisci le credenziali SOLO nel terminale Termux del Samsung.")
    print("Nessun dato sarà inviato alla chat. Permessi API: sola lettura.")
    print("ATTENZIONE: le chiavi saranno salvate non cifrate nella cartella PRIVATA di Termux,")
    print("con accesso al solo utente Android (0600), fuori dai backup condivisi.")
    agree = input("Confermi l’archiviazione locale in questo modo? [SI/no]: ").strip().upper()
    if agree != "SI":
        raise SystemExit("Nessuna credenziale acquisita.")
    key = getpass.getpass("API Key Kraken: ").strip()
    secret = getpass.getpass("Private Key / Secret Kraken: ").strip()
    if len(key) < 16 or not secret:
        raise SystemExit("Chiavi incomplete: nessun file creato.")
    try:
        if len(base64.b64decode(secret, validate=True)) < 32:
            raise ValueError("short")
    except Exception:
        raise SystemExit("Secret non riconosciuto in formato base64.")
    save_private(AUTH, {"api_key": key, "api_secret": secret})
    print("Credenziali memorizzate solo in Termux, file accessibile all'utente Android.")
    print("NOTA SICUREZZA: protetto da permessi 0600, ma NON crittografato a riposo.")
    print("Verifico ora la connessione: una sola lettura dei saldi.")
    refresh()

def sign(path, params, secret):
    postdata = urllib.parse.urlencode(params)
    seed = str(params["nonce"]) + postdata
    message = path.encode("utf-8") + hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.b64encode(hmac.new(base64.b64decode(secret), message, hashlib.sha512).digest()).decode()

def query_only(name, creds):
    if name not in ALLOWED:
        raise ValueError("Endpoint NON autorizzato")
    path = "/0/private/" + name
    params = {"nonce": str(time.time_ns())}
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        BASE_URL + path, data=data, method="POST",
        headers={"API-Key": creds["api_key"],
                 "API-Sign": sign(path, params, creds["api_secret"]),
                 "Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "KDD-readonly/1.0"})
    with urllib.request.urlopen(req, timeout=15) as response:
        result = json.load(response)
    if result.get("error"):
        # Never print responses or headers containing credential material.
        raise RuntimeError("Kraken ha rifiutato la richiesta: " + "; ".join(result["error"]))
    if not isinstance(result.get("result"), dict):
        raise RuntimeError("Risposta saldo non valida: conservato l'ultimo snapshot.")
    return result["result"]

def normalize(asset):
    for suffix in SUFFIXES:
        if asset.endswith(suffix):
            return NAMES.get(asset[:-2], asset[:-2]), suffix
    return NAMES.get(asset, asset), ""

def refresh():
    if not AUTH.is_file():
        raise SystemExit("Chiavi non configurate: esegui python kraken_readonly.py setup su Termux")
    if AUTH.stat().st_mode & 0o077:
        raise SystemExit("Permessi file credenziali non sicuri: interrompo.")
    creds = json.loads(AUTH.read_text(encoding="utf-8"))
    result = query_only("BalanceEx", creds)
    rows = []
    for raw, entry in sorted(result.items()):
        if not isinstance(entry, dict):
            raise ValueError("Risposta saldo con formato inatteso: nessun aggiornamento.")
        token, group = normalize(raw)
        from decimal import Decimal
        balance = Decimal(str(entry.get("balance", "0")))
        credit = Decimal(str(entry.get("credit", "0")))
        credit_used = Decimal(str(entry.get("credit_used", "0")))
        reserved = Decimal(str(entry.get("hold_trade", "0")))
        available = balance + credit - credit_used - reserved
        if min(balance, available, reserved) < 0:
            raise ValueError("Saldo incoerente: nessun aggiornamento.")
        rows.append({"raw_asset": raw, "token": token, "account_segment": group or "spot",
                     "balance": str(balance), "hold_trade": str(reserved),
                     "available_balance": str(available),
                     "tradable_spot": not bool(group)})
    snapshot = {"source": "Kraken Spot REST /0/private/BalanceEx (read-only)",
                "acquired_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "account_segments": rows,
                "trading_allowed": False,
                "notes": "Spot available = balance + credit - credit_used - hold_trade. Asset suffixes are not automatically considered tradable. Values are not cost basis."}
    save_private(STATE, snapshot)
    import kdd_saldi
    result_sync = kdd_saldi.apply(snapshot)
    print("SALDI AGGIORNATI E SINCRONIZZATI IN KDD:", result_sync["positions"], "posizioni")
    print("Rilevazione", snapshot["acquired_utc"], "| asset/segmenti", len(rows))
    for row in rows:
        print(row["token"], row["account_segment"],
              "totale", row["balance"], "disponibile", row["available_balance"])
    print("Il T0 è invariato. Nessun ordine è stato inviato.")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("setup", "refresh", "status"))
    args = p.parse_args()
    if args.command == "setup":
        setup()
    elif args.command == "refresh":
        refresh()
    else:
        print("Chiave locale configurata:", AUTH.is_file())
        print("Saldo locale disponibile:", STATE.is_file())
