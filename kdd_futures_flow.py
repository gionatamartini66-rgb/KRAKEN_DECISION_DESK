"""KDD-16: bounded Kraken Futures public market flow; no keys or trade execution.

Only PF_XBTUSD. Samples are not a liquidation heatmap, market-wide flow,
historical volume profile or evidence of a particular trader's identity.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
import json
import math

BASE = "https://futures.kraken.com/derivatives/api/v3/"
SYMBOL = "PF_XBTUSD"
TYPES = frozenset(("fill", "liquidation", "assignment", "termination", "block"))
UTC = dt.timezone.utc


def _date(value):
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    instant = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("timestamp without timezone")
    return instant.astimezone(UTC)


def _number(value, *, positive=False):
    if type(value) not in (int, float, str):
        raise ValueError("invalid numeric type")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid numeric value") from None
    if not result.is_finite() or (result <= 0 if positive else result < 0):
        raise ValueError("nonfinite, negative or zero value")
    return result


def _read(endpoint, request):
    payload = json.loads(request(BASE + endpoint, timeout=13).decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("result") != "success" or payload.get("errors"):
        raise ValueError("Kraken Futures public source rejected")
    return payload


def _stamp(value):
    return value.isoformat(timespec="seconds")


def _fresh(source_time, now, minutes=15):
    delta = (now - source_time).total_seconds()
    return -120 <= delta <= minutes * 60


def _funding(data, now):
    observed = _date(data.get("serverTime"))
    tickers = data.get("tickers")
    if not isinstance(tickers, list):
        raise ValueError("ticker array absent")
    selected = [t for t in tickers if isinstance(t, dict) and t.get("symbol") == SYMBOL]
    if len(selected) != 1:
        raise ValueError("perpetual BTC ticker missing or duplicated")
    ticker = selected[0]
    if ticker.get("suspended") is not False:
        raise ValueError("suspended or unverified perpetual")
    def funding_value(value):
        if type(value) not in (int, float, str):
            raise ValueError("invalid funding type")
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise ValueError("invalid funding") from None
        if not number.is_finite():
            raise ValueError("nonfinite funding")
        return number
    current = funding_value(ticker["fundingRate"])
    predicted = funding_value(ticker["fundingRatePrediction"])
    return {
        "stato": "OSSERVATO" if _fresh(observed, now) else "SCADUTO",
        "osservato_utc": _stamp(observed),
        "ultimo_trade_utc": _stamp(_date(ticker["lastTime"])),
        "funding_rate_grezzo": str(current),
        "funding_rate_previsione_grezza": str(predicted),
        "unita": "Valore grezzo API Kraken; periodo/scaling percentuale non attestati",
        "limite": "Stima funding non equivale a pagamento realizzato o costo netto"
    }


def _history(data, now):
    observed = _date(data.get("serverTime"))
    trades = data.get("history")
    if not isinstance(trades, list) or not 0 < len(trades) <= 100:
        raise ValueError("invalid public history sample")
    validated = []
    prior = None
    for row in trades:
        if not isinstance(row, dict) or row.get("type") not in TYPES:
            raise ValueError("unverifiable trade type")
        timestamp = _date(row["time"])
        if timestamp > observed + dt.timedelta(minutes=2) or timestamp > now + dt.timedelta(minutes=2):
            raise ValueError("future trade timestamp")
        if prior is not None and timestamp > prior:
            raise ValueError("unordered trades")
        prior = timestamp
        validated.append({"t": timestamp, "price": _number(row["price"], positive=True),
                          "size": _number(row["size"], positive=True), "type": row["type"]})
    lo, hi = min(r["price"] for r in validated), max(r["price"] for r in validated)
    step = (hi - lo) / 10 if hi > lo else None
    bands = {}
    for item in validated:
        key = min(9, int((item["price"]-lo)/step)) if step else 0
        quantity, count = bands.get(key, (Decimal(0), 0))
        bands[key] = (quantity + item["size"], count + 1)
    # Show a bounded top-5 distribution; it is a sampled VAP proxy, never
    # a market-wide Volume Profile or a liquidity/liquidation heatmap.
    bins = []
    for key, (quantity, count) in bands.items():
        left = lo + step * key if step else lo
        right = lo + step * (key + 1) if step and key < 9 else hi
        bins.append({"prezzo_da": str(left), "prezzo_a": str(right),
                     "volume_size_grezzo": str(quantity), "n_esecuzioni": count})
    bins.sort(key=lambda b: Decimal(b["volume_size_grezzo"]), reverse=True)
    largest = sorted(validated, key=lambda x: x["size"], reverse=True)[:3]
    latest = validated[0]["t"]
    age_ok = _fresh(latest, now)
    return {
        "stato": "CAMPIONE_RECENTE" if age_ok and _fresh(observed, now) else "SCADUTO",
        "osservato_utc": _stamp(observed),
        "primo_trade_utc": _stamp(validated[-1]["t"]),
        "ultimo_trade_utc": _stamp(latest),
        "n_esecuzioni": len(validated),
        "durata_campione_secondi": round((latest-validated[-1]["t"]).total_seconds(), 3),
        "n_liquidazioni_nel_campione": sum(x["type"] == "liquidation" for x in validated),
        "n_block_nel_campione": sum(x["type"] == "block" for x in validated),
        "n_assignment_nel_campione": sum(x["type"] == "assignment" for x in validated),
        "profilo_volumi_campione": bins[:5],
        "tre_maggiori_esecuzioni": [{"prezzo": str(x["price"]), "size_grezza": str(x["size"]),
                                    "tipo": x["type"], "timestamp": _stamp(x["t"])}
                                   for x in largest],
        "unita": "size contratto da attestare; prezzi USD, non volumi in USD",
        "limite": ("Ultime <=100 esecuzioni in finestra variabile, fino a 7 giorni/riavvio motore; "
                   "zero liquidazioni nel campione non equivale a zero sul mercato; "
                   "trade grande non identifica whale; bins NON sono heatmap")
    }


def collect(now, *, request=None):
    """Exactly two public GETs; source failures are explicit and independent."""
    if request is None:
        import decision_desk as desk
        request = desk.request
    moment = dt.datetime.fromtimestamp(now, UTC) if type(now) in (int, float) else now
    if not isinstance(moment, dt.datetime) or moment.tzinfo is None:
        raise ValueError("now must be aware")
    moment = moment.astimezone(UTC)
    result = {
        "strumento": SYMBOL,
        "fonte_ticker": BASE + "tickers",
        "fonte_trades": BASE + "history?symbol=" + SYMBOL,
        "copertura": "Solo perpetual BTC Kraken Futures, NON cross-exchange",
        "richieste_pubbliche_massime": 2,
        "heatmap": {"stato": "NON_DISPONIBILE",
                    "motivo": "Nessuna posizione di liquidazione futura inferibile dal trade tape"}
    }
    for field, endpoint, parser in (
            ("funding", "tickers", _funding),
            ("esecuzioni", "history?symbol=" + SYMBOL, _history)):
        try:
            result[field] = parser(_read(endpoint, request), moment)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError,
                OverflowError, ArithmeticError, UnicodeError) as exc:
            result[field] = {"stato": "NON_VERIFICATO", "motivo": type(exc).__name__}
    return result


def at_read(source, now):
    """Recheck age and source identity; suppress stale numerical data."""
    if not isinstance(source, dict) or source.get("strumento") != SYMBOL or (
            source.get("fonte_ticker") != BASE + "tickers"
            or source.get("fonte_trades") != BASE + "history?symbol=" + SYMBOL):
        return {"strumento": SYMBOL, "stato": "NON_VERIFICATO", "motivo": "Fonte o contratto non attribuibile"}
    moment = now.astimezone(UTC)
    out = {"strumento": SYMBOL, "stato": "EVIDENZE_CON_LIMITI",
           "copertura": source.get("copertura"),
           "heatmap": {"stato": "NON_DISPONIBILE"}}
    for key, valid_state in (("funding", "OSSERVATO"), ("esecuzioni", "CAMPIONE_RECENTE")):
        row = source.get(key)
        if not isinstance(row, dict) or row.get("stato") != valid_state:
            out[key] = {"stato": "NON_VERIFICATO"}
            continue
        try:
            stamp = _date(row["osservato_utc"])
            if not _fresh(stamp, moment):
                out[key] = {"stato": "SCADUTO", "osservato_utc": row["osservato_utc"],
                            "limite": "Numeri storici soppressi: aggiornare la fonte"}
                continue
            if key == "esecuzioni" and not _fresh(_date(row["ultimo_trade_utc"]), moment):
                out[key] = {"stato": "SCADUTO", "limite": "Ultimo trade non recente"}
                continue
            out[key] = dict(row)
        except (TypeError, ValueError, KeyError, OverflowError):
            out[key] = {"stato": "NON_VERIFICATO"}
    return out
