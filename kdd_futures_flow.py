"""KDD-16: bounded public Kraken Futures PF_XBTUSD observations.

The public tape is not a heatmap, historical market profile or whale ledger.
Read-time checks recompute summaries from bounded normalized executions.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
import json

BASE = "https://futures.kraken.com/derivatives/api/v3/"
SYMBOL = "PF_XBTUSD"
TYPES = frozenset(("fill", "liquidation", "assignment", "termination", "block"))
UTC = dt.timezone.utc
COVERAGE = "Solo perpetual BTC Kraken Futures, NON cross-exchange"
FUNDING_UNIT = "Valore grezzo API Kraken; periodo/scaling percentuale non attestati"
# Engineering quarantine, NOT an official Kraken contractual maximum:
# the published ticker example is around 1e-7 in raw API units; |x| > 1
# is orders of magnitude beyond it. Reject rather than re-scale/round.
MAX_ABS_FUNDING_RAW = Decimal("1")
MAX_TRADE_ID = 2147483647  # Kraken /history trade_id: integer<int32>
FUNDING_LIMIT = (
    "Stima funding non equivale a pagamento realizzato o costo netto; "
    "valori grezzi oltre +/-1 in quarantena (soglia ingegneristica, "
    "NON massimo contrattuale Kraken)")
TRADES_UNIT = "size contratto da attestare; prezzi USD, non volumi in USD"
TRADES_LIMIT = (
    "Ultime <=100 esecuzioni in finestra variabile, fino a 7 giorni/riavvio motore; "
    "zero liquidazioni nel campione non equivale a zero sul mercato; "
    "trade grande non identifica whale; bins NON sono heatmap")
HEATMAP = {"stato": "NON_DISPONIBILE",
           "motivo": "Nessuna posizione di liquidazione futura inferibile dal trade tape"}


def _date(value):
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    instant = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("timestamp without timezone")
    return instant.astimezone(UTC)


def _number(value, *, positive=False, signed=False):
    if type(value) not in (int, float, str):
        raise ValueError("invalid numeric type")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid numeric value") from None
    if not result.is_finite() or (not signed and (result <= 0 if positive else result < 0)):
        raise ValueError("nonfinite, negative or zero value")
    return result


class FundingAnomaly(ValueError):
    """Finite but implausibly large raw funding, distinct from missing data."""


def _funding_value(value):
    number = _number(value, signed=True)
    if abs(number) > MAX_ABS_FUNDING_RAW:
        raise FundingAnomaly("funding raw exceeds engineering quarantine threshold")
    return number


def _read(endpoint, request):
    payload = json.loads(request(BASE + endpoint, timeout=13).decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("result") != "success" or payload.get("errors"):
        raise ValueError("Kraken Futures public source rejected")
    return payload


def _stamp(value):
    return value.isoformat(timespec="seconds")


def _fresh(source_time, now, minutes=15):
    delta = (now - source_time).total_seconds()
    return 0 <= delta <= minutes * 60


def _moment(now):
    value = dt.datetime.fromtimestamp(now, UTC) if type(now) in (int, float) else now
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


def _server_time(data, now):
    observed = _date(data.get("serverTime"))
    if observed > now:
        raise ValueError("future serverTime")
    return observed


def _funding(data, now):
    observed = _server_time(data, now)
    tickers = data.get("tickers")
    if not isinstance(tickers, list):
        raise ValueError("ticker array absent")
    selected = [t for t in tickers if isinstance(t, dict) and t.get("symbol") == SYMBOL]
    if len(selected) != 1:
        raise ValueError("perpetual BTC ticker missing or duplicated")
    ticker = selected[0]
    if ticker.get("suspended") is not False:
        raise ValueError("suspended or unverified perpetual")
    last = _date(ticker["lastTime"])
    if last > observed or last > now:
        raise ValueError("future/incoherent lastTime")
    current = _funding_value(ticker["fundingRate"])
    predicted = _funding_value(ticker["fundingRatePrediction"])
    if not _fresh(observed, now):
        return {"stato": "SCADUTO", "osservato_utc": _stamp(observed),
                "limite": "Funding storico: numeri soppressi"}
    return {
        "stato": "OSSERVATO",
        "osservato_utc": _stamp(observed),
        "ultimo_trade_utc": _stamp(last),
        "funding_rate_grezzo": str(current),
        "funding_rate_previsione_grezza": str(predicted),
        "unita": FUNDING_UNIT, "limite": FUNDING_LIMIT
    }


def _normalize_trades(trades, observed, now):
    """Bounded public evidence; stable trade_id/uid, not timestamp/price dedupe."""
    if not isinstance(trades, list) or not 0 < len(trades) <= 100:
        raise ValueError("invalid public history sample")
    result, ids, uids = [], {}, {}
    for row in trades:
        if not isinstance(row, dict) or row.get("type") not in TYPES:
            raise ValueError("unverifiable trade type")
        timestamp = _date(row.get("time"))
        if timestamp > observed or timestamp > now:
            raise ValueError("future trade timestamp")
        trade_id = row.get("trade_id")
        uid = row.get("uid")
        if trade_id is not None and (type(trade_id) is not int or not 1 <= trade_id <= MAX_TRADE_ID):
            raise ValueError("invalid trade_id")
        if uid is not None and (not isinstance(uid, str) or not 1 <= len(uid) <= 128):
            raise ValueError("invalid uid")
        if trade_id is None and uid is None:
            raise ValueError("public trade lacks a stable identifier")
        price = _number(row.get("price"), positive=True)
        size = _number(row.get("size"), positive=True)
        normalized = {"trade_id": trade_id, "uid": uid, "time": timestamp.isoformat(),
                      "price": str(price), "size": str(size), "type": row["type"]}
        # A repeated identity may repeat the same observation, but conflicting
        # IDs or changed economic data cannot be safely counted.
        prior_id = ids.get(trade_id) if trade_id is not None else None
        prior_uid = uids.get(uid) if uid is not None else None
        if (prior_id is not None and prior_id != normalized
                or prior_uid is not None and prior_uid != normalized):
            raise ValueError("conflicting trade identifiers or contents")
        if prior_id is not None or prior_uid is not None:
            continue
        if trade_id is not None:
            ids[trade_id] = normalized
        if uid is not None:
            uids[uid] = normalized
        result.append(normalized)
    if not result:
        raise ValueError("no distinct executions")
    result.sort(key=lambda row: _date(row["time"]), reverse=True)
    return result


def _summary(normalized, observed, now):
    """One algorithm for acquisition and consumer; do not trust stored totals."""
    trades = [{"t": _date(x["time"]), "price": _number(x["price"], positive=True),
               "size": _number(x["size"], positive=True), "type": x["type"]}
              for x in normalized]
    lo, hi = min(r["price"] for r in trades), max(r["price"] for r in trades)
    step = (hi-lo)/10 if hi > lo else None
    bands = {}
    for item in trades:
        idx = min(9, int((item["price"]-lo)/step)) if step else 0
        quantity, count = bands.get(idx, (Decimal(0), 0))
        bands[idx] = (quantity+item["size"], count+1)
    bins = []
    for idx, (quantity, count) in bands.items():
        left = lo + step*idx if step else lo
        right = lo + step*(idx+1) if step and idx < 9 else hi
        bins.append({"prezzo_da": str(left), "prezzo_a": str(right),
                     "volume_size_grezzo": str(quantity), "n_esecuzioni": count})
    bins.sort(key=lambda b: Decimal(b["volume_size_grezzo"]), reverse=True)
    largest = sorted(trades, key=lambda x: x["size"], reverse=True)[:3]
    latest, earliest = trades[0]["t"], trades[-1]["t"]
    return {
        "stato": ("CAMPIONE_RECENTE" if _fresh(latest, now) and _fresh(observed, now)
                  else "SCADUTO"),
        "osservato_utc": _stamp(observed),
        "primo_trade_utc": _stamp(earliest),
        "ultimo_trade_utc": _stamp(latest),
        "n_esecuzioni": len(trades),
        "durata_campione_secondi": round((latest-earliest).total_seconds(), 3),
        "n_liquidazioni_nel_campione": sum(x["type"] == "liquidation" for x in trades),
        "n_block_nel_campione": sum(x["type"] == "block" for x in trades),
        "n_assignment_nel_campione": sum(x["type"] == "assignment" for x in trades),
        "profilo_volumi_campione": bins[:5],
        "tre_maggiori_esecuzioni": [
            {"prezzo": str(x["price"]), "size_grezza": str(x["size"]),
             "tipo": x["type"], "timestamp": _stamp(x["t"])} for x in largest],
        "trade_normalizzati": normalized,
        "unita": TRADES_UNIT, "limite": TRADES_LIMIT
    }


def _history(data, now):
    observed = _server_time(data, now)
    normalized = _normalize_trades(data.get("history"), observed, now)
    row = _summary(normalized, observed, now)
    if row["stato"] != "CAMPIONE_RECENTE":
        return {"stato": "SCADUTO", "osservato_utc": _stamp(observed),
                "limite": "Campione storico: numeri soppressi"}
    return row


def collect(now, *, request=None):
    """Exactly two public GETs; source failures are explicit and independent."""
    if request is None:
        import decision_desk as desk
        request = desk.request
    moment = _moment(now)
    result = {
        "strumento": SYMBOL,
        "fonte_ticker": BASE + "tickers",
        "fonte_trades": BASE + "history?symbol=" + SYMBOL,
        "copertura": COVERAGE,
        "richieste_pubbliche_massime": 2,
        "heatmap": dict(HEATMAP)
    }
    for field, endpoint, parser in (
            ("funding", "tickers", _funding),
            ("esecuzioni", "history?symbol=" + SYMBOL, _history)):
        try:
            result[field] = parser(_read(endpoint, request), moment)
        except FundingAnomaly:
            result[field] = {"stato": "NON_VERIFICATO",
                             "motivo": "FUNDING_FUORI_SOGLIA_INGEGNERISTICA"}
        except (OSError, ValueError, TypeError, KeyError, OverflowError,
                ArithmeticError, UnicodeError) as exc:
            result[field] = {"stato": "NON_VERIFICATO", "motivo": type(exc).__name__}
    return result


def _same(expected, observed):
    """Strict canonical comparison rejects bool-as-int, NaN, type changes and edits."""
    return (json.dumps(expected, sort_keys=True, allow_nan=False) ==
            json.dumps(observed, sort_keys=True, allow_nan=False))


def _read_funding(row, now):
    if not isinstance(row, dict) or row.get("stato") not in ("OSSERVATO", "SCADUTO"):
        return {"stato": "NON_VERIFICATO"}
    observed = _date(row.get("osservato_utc"))
    if observed > now:
        raise ValueError("future funding source time")
    if row["stato"] == "SCADUTO":
        if (set(row) != {"stato", "osservato_utc", "limite"}
                or row.get("limite") not in ("Funding storico: numeri soppressi",
                                             "Numeri storici soppressi: aggiornare la fonte")):
            raise ValueError("invalid stale funding")
        return {"stato": "SCADUTO", "osservato_utc": _stamp(observed),
                "limite": "Numeri storici soppressi: aggiornare la fonte"}
    last = _date(row.get("ultimo_trade_utc"))
    if last > observed or last > now:
        raise ValueError("funding lastTime future or incoherent")
    current = _funding_value(row.get("funding_rate_grezzo"))
    predicted = _funding_value(row.get("funding_rate_previsione_grezza"))
    expected = {"stato": "OSSERVATO", "osservato_utc": _stamp(observed),
                "ultimo_trade_utc": _stamp(last),
                "funding_rate_grezzo": str(current),
                "funding_rate_previsione_grezza": str(predicted),
                "unita": FUNDING_UNIT, "limite": FUNDING_LIMIT}
    if not _same(expected, row):
        raise ValueError("funding contents or descriptions altered")
    if not _fresh(observed, now):
        return {"stato": "SCADUTO", "osservato_utc": _stamp(observed),
                "limite": "Numeri storici soppressi: aggiornare la fonte"}
    return expected


def _read_history(row, now):
    if not isinstance(row, dict) or row.get("stato") not in ("CAMPIONE_RECENTE", "SCADUTO"):
        return {"stato": "NON_VERIFICATO"}
    observed = _date(row.get("osservato_utc"))
    if observed > now:
        raise ValueError("future execution source time")
    if row["stato"] == "SCADUTO":
        if (set(row) != {"stato", "osservato_utc", "limite"}
                or row.get("limite") not in ("Campione storico: numeri soppressi",
                                             "Numeri storici soppressi: aggiornare la fonte")):
            raise ValueError("invalid stale execution sample")
        return {"stato": "SCADUTO", "osservato_utc": _stamp(observed),
                "limite": "Numeri storici soppressi: aggiornare la fonte"}
    normalized = _normalize_trades(row.get("trade_normalizzati"), observed, now)
    recomputed = _summary(normalized, observed, now)
    # Recompute *every* public sample metric from the bounded tape, including
    # the 1 -> 99 mutation that fits a 100-trade cap.
    expected = dict(recomputed, stato="CAMPIONE_RECENTE")
    if not _same(expected, row):
        raise ValueError("execution tape and summary disagree")
    if recomputed["stato"] != "CAMPIONE_RECENTE":
        return {"stato": "SCADUTO", "osservato_utc": _stamp(observed),
                "limite": "Numeri storici soppressi: aggiornare la fonte"}
    return expected


def at_read(source, now):
    """Full read-time semantic revalidation after persistence and serialization."""
    try:
        moment = _moment(now)
        if (not isinstance(source, dict) or source.get("strumento") != SYMBOL
                or source.get("fonte_ticker") != BASE + "tickers"
                or source.get("fonte_trades") != BASE + "history?symbol=" + SYMBOL
                or source.get("copertura") != COVERAGE
                or source.get("richieste_pubbliche_massime") != 2
                or not _same(source.get("heatmap"), HEATMAP)):
            return {"strumento": SYMBOL, "stato": "NON_VERIFICATO",
                    "motivo": "Fonte, contratto o descrizioni non attribuibili"}
        # Preserve already verified source identity for the packet -> GPT bridge:
        # the second at_read must apply the same provenance checks, not lose them.
        out = {"strumento": SYMBOL, "stato": "EVIDENZE_CON_LIMITI",
               "fonte_ticker": BASE + "tickers",
               "fonte_trades": BASE + "history?symbol=" + SYMBOL,
               "richieste_pubbliche_massime": 2,
               "copertura": COVERAGE, "heatmap": dict(HEATMAP)}
        for name, verifier in (("funding", _read_funding), ("esecuzioni", _read_history)):
            try:
                out[name] = verifier(source.get(name), moment)
            except FundingAnomaly:
                out[name] = {"stato": "NON_VERIFICATO",
                             "motivo": "FUNDING_FUORI_SOGLIA_INGEGNERISTICA"}
            except (ValueError, KeyError, TypeError, OverflowError, ArithmeticError):
                out[name] = {"stato": "NON_VERIFICATO", "motivo": "CONTENUTO_NON_CONGRUENTE"}
        return out
    except (ValueError, KeyError, TypeError, OverflowError, ArithmeticError):
        return {"strumento": SYMBOL, "stato": "NON_VERIFICATO",
                "motivo": "Formato o provenienza non verificabile"}
