"""Bridge: successful Kraken read-only BalanceEx -> KDD current holdings.
Never modifies the independent immutable T0 baseline.
"""
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import kraken_readonly as k

DIR = Path(__file__).resolve().parent

def positive_decimal(value):
    v = Decimal(str(value))
    if not v.is_finite() or v < 0:
        raise ValueError("Valore saldo non valido")
    return v

def apply(snapshot, path=None):
    if snapshot.get("source") != "Kraken Spot REST /0/private/BalanceEx (read-only)":
        raise ValueError("Fonte non riconosciuta")
    acquired = snapshot.get("acquired_utc")
    segments = snapshot.get("account_segments")
    if not acquired or not isinstance(segments, list):
        raise ValueError("Saldo non completo")
    path = Path(path) if path else DIR / "portafoglio.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    if not original.get("t0_id") or not original.get("t0_sha256"):
        raise ValueError("T0 assente: blocco sostituzione")
    earlier = {x["token"]: x for x in original.get("posizioni", [])}
    positions = []
    seen = set()
    liquidity = {}
    all_balances = {}
    for item in segments:
        if not isinstance(item, dict):
            raise ValueError("Segmento saldo non valido")
        token = item["token"].upper()
        segment = item["account_segment"]
        qty = positive_decimal(item["balance"])
        available = positive_decimal(item["available_balance"])
        if available > qty:
            raise ValueError("Disponibile maggiore del saldo: interrompo")
        all_balances.setdefault(token, []).append({
            "segment": segment, "saldo": str(qty), "disponibile": str(available)})
        if segment != "spot":
            continue
        if token in seen:
            raise ValueError("Token spot duplicato")
        seen.add(token)
        if token in ("EUR", "USDC", "USD", "EURC"):
            liquidity[token] = {"saldo": str(qty), "disponibile": str(available)}
            continue
        if qty == 0:
            continue
        positions.append({"token": token, "quantita": str(qty),
                          "costo_medio_eur": earlier.get(token, {}).get("costo_medio_eur"),
                          "disponibile_spot": str(available)})
    if not positions and not liquidity:
        raise ValueError("Nessun asset valido: non sostituisco il portafoglio")
    # Copy the T0 ID and digest unchanged; the T0 file itself is never opened for writing.
    original["posizioni"] = sorted(positions, key=lambda x: x["token"])
    original["fonte_quantita"] = "Kraken BalanceEx API privata SOLA LETTURA, " + acquired
    original["data_ora_saldo_privato_utc"] = acquired
    original["liquidita_spot_api"] = {
        token: liquidity.get(token, {"saldo":"0", "disponibile":"0"})
        for token in ("EUR", "USDC", "USD", "EURC")}
    original["segmenti_non_spot"] = {
        token: [x for x in values if x["segment"] != "spot"]
        for token, values in all_balances.items()
        if any(x["segment"] != "spot" for x in values)}
    original["nota_saldi_api"] = (
        "Quantità disponibili aggiornate da BalanceEx, non prezzo di carico. "
        "Assenza di EUR/USDC nel risultato spot significa nessun saldo positivo nel risultato; "
        "conti derivati e altre posizioni non sono inclusi. T0 conservato in storico_portafoglio.")
    k.save_private(path, original)
    return {"positions": len(positions), "source": acquired,
            "spot_USDC": original["liquidita_spot_api"]["USDC"]["disponibile"],
            "spot_EUR": original["liquidita_spot_api"]["EUR"]["disponibile"]}
