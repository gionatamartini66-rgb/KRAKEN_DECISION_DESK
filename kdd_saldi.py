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
    # Every successful BalanceEx snapshot can show a zero explicitly or omit
    # an asset entirely. Neither is a failed acquisition; errors above do not
    # write anything. Preserve earlier observations without rewriting T0.
    previous_active = set(earlier)
    current_active = {x["token"] for x in positions}
    historic = set(original.get("token_visti_in_precedenza", []))
    historic |= previous_active
    zeros = sorted(token for token, parts in all_balances.items()
                   if token not in ("EUR", "USD", "USDC", "EURC")
                   and any(x["segment"] == "spot" and Decimal(x["saldo"]) == 0
                           for x in parts))
    entering = sorted(current_active - previous_active)
    events = list(original.get("storico_transizioni_posizioni", []))
    if not all(isinstance(x, dict) for x in events):
        raise ValueError("Storico delle transizioni non verificabile")
    for token in entering:
        events.append({"acquisito_utc": acquired, "token": token,
                       "evento": "RIENTRO" if token in historic else "INGRESSO"})
    for token in sorted(previous_active - current_active):
        events.append({"acquisito_utc": acquired, "token": token,
                       "evento": "USCITA",
                       "evidenza": ("ZERO_ESPLICITO_BALANCEEX" if token in zeros
                                    else "ASSENTE_DALLA_FOTOGRAFIA_BALANCEEX")})
    original["token_visti_in_precedenza"] = sorted(historic | current_active)
    original["storico_transizioni_posizioni"] = events
    original["riconciliazione_posizioni"] = {
        "acquisito_utc": acquired, "stato": "ACQUISIZIONE_COMPLETA",
        "attive": sorted(current_active),
        "zero_esplicito": zeros,
        "assenti_rispetto_alla_precedente": sorted(
            token for token in previous_active-current_active if token not in zeros),
        "entrate": sorted(token for token in entering if token not in historic),
        "rientrate": sorted(token for token in entering if token in historic),
        "uscite": sorted(previous_active-current_active),
        "limite": "Assenza dalla nuova lettura non equivale a saldo zero. Errori di lettura non aggiornano il wallet."
    }
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
