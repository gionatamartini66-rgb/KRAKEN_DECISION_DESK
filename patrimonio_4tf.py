"""KDD portfolio-specific four-timeframe evidence, public Kraken Spot only.

The scanner sample is independent. Every registered wallet row receives a result,
including malformed rows, unknown pairs and deferred/failed observations.
No private API, trading, finance conversion, Drive or file writes.
"""
from __future__ import annotations

import datetime as dt
import math
import time

import decision_desk as desk
import grafico_4h as charts

LABELS = (("15m", "15m"), ("1H", "1h"), ("4H", "4h"), ("1D", "1d"))
QUOTES = ("EUR", "USD", "USDC")
MAX_OHLC_PER_REFRESH = 80  # request budget; NEVER a wallet-position limit
SOURCE = "Kraken Spot pubblico /0/public/OHLC"


def canonical_base(raw):
    if raw in ("XBT", "XXBT", "BTC"):
        return "BTC"
    if raw in ("XDG", "XXDG", "DOGE"):
        return "DOGE"
    return raw


def select_pair(token, catalog):
    """Choose an actual online Kraken pair, rejecting alias collisions."""
    matches = {}
    for key, meta in catalog.items():
        if canonical_base(meta["base"]) != token or meta["quote"] not in QUOTES:
            continue
        matches.setdefault(meta["quote"], []).append(meta)
    for quote in QUOTES:
        candidates = matches.get(quote, [])
        if len(candidates) > 1:
            return None, "COPPIA_AMBIGUA", "Più identificativi Kraken per " + quote
        if len(candidates) == 1:
            return candidates[0], None, None
    return None, "COPPIA_NON_DISPONIBILE", "Nessuna coppia Kraken Spot EUR/USD/USDC online verificata"


def from_old_4h(observation, meta, now):
    """Only reuse validated, same-pair 4H close bars from this refresh."""
    if not isinstance(observation, dict) or (observation.get("stato") != "OK"
            or observation.get("coppia") != meta["pair"]
            or canonical_base(observation.get("token")) != canonical_base(meta["base"])):
        return None
    raw = observation.get("serie_ohlcv_chiuse")
    if not isinstance(raw, list) or len(raw) < 50:
        return None
    records = []
    for v in raw:
        if not isinstance(v, dict):
            return None
        records.append({"time": v["apertura_ts_utc"], "open": v["open"],
                        "high": v["high"], "low": v["low"], "close": v["close"],
                        "volume": v["volume_base"]})
    result = {"observed_utc": now.isoformat(timespec="seconds"),
              "closed_at_utc": dt.datetime.fromtimestamp(
                  records[-1]["time"]+14400, dt.timezone.utc).isoformat(timespec="seconds"),
              "pair": meta["pair"], "pair_key": meta["pair_key"],
              "token": meta["base"], "timeframe": "4H",
              "interval_seconds": 14400, "candles": records,
              "source": "Kraken Spot 4H già verificato nel dossier corrente"}
    charts.temporal_consistency(result, now=now)
    # Validate all OHLC, continuity and completeness, not just the last bar.
    prior = None
    for v in records:
        if (type(v["time"]) is not int or v["time"] % 14400
                or (prior is not None and v["time"] - prior != 14400)
                or not all(type(v[k]) in (int, float) and math.isfinite(v[k])
                           for k in ("open", "high", "low", "close", "volume"))
                or not (0 < v["low"] <= min(v["open"], v["close"]) <=
                        max(v["open"], v["close"]) <= v["high"] and v["volume"] >= 0)):
            return None
        prior = v["time"]
    return result


def analyze_frame(data, now):
    """Original chart calculations plus actual closed OHLC evidence."""
    description = charts.summarize_timeframe(data, now=now)
    if description["stato"] not in ("AGGIORNATO", "SCADUTO"):
        return description
    calculations = charts.technical_from_candles(
        data["candles"], interval_seconds=data["interval_seconds"])
    return dict(description,
                pair_key=data["pair_key"], coppia=data["pair"],
                asset_base=data["token"],
                valuta_quotazione=data["pair"].split("/", 1)[1],
                ultima_candela_ohlcv_chiusa=dict(data["candles"][-1]),
                serie_ohlcv_chiuse=data["candles"],
                pivot_giornaliero=calculations["pivots"],
                livelli_strutturali=calculations["structure"],
                intervallo_secondi=data["interval_seconds"],
                fonte=data["source"], limiti=[
                    "Solo candele chiuse, non quotazione eseguibile",
                    "EMA e livelli descrittivi, nessun ordine o segnale automatico",
                    "Freschezza da ricalcolare al momento di utilizzare il pacchetto"])


def collect(portfolio, source, *, asset_pairs=None, fetch=None, now=None,
            old_4h=None, max_queries=MAX_OHLC_PER_REFRESH, pause=None):
    """One entry PER original wallet row, independent of scanner sample size.

    Requests are bounded; if budget is exhausted all rows remain visible with
    RINVIATO_BUDGET. A catalog failure does not delete registered positions.
    """
    import serve  # existing authoritative Kraken alias and OHLC identity checks
    now = now or desk.NOW()
    fetch = fetch or desk.kraken
    pause = pause if pause is not None else time.sleep
    positions = portfolio.get("posizioni") if isinstance(portfolio, dict) else None
    snapshot = source.get("rilevazione_utc")
    result = {"schema": 1, "rilevazione_kraken_utc": snapshot,
              "portafoglio_sha256": desk.fotografia_portafoglio_sha256(portfolio),
              "creato_utc": now.isoformat(timespec="seconds"),
              "fonte_catalogo": "Kraken /0/public/AssetPairs (status online)",
              "fonte_candele": SOURCE,
              "richieste_ohlc": 0, "riusi_4h": 0,
              "budget_ohlc": max_queries,
              "limite": "Il budget limita le richieste per ciclo, mai le posizioni rappresentate.",
              "posizioni": []}
    if not isinstance(positions, list):
        result["errore"] = "SCHEMA_POSIZIONI_NON_VALIDO"
        return result
    try:
        raw_pairs = asset_pairs if asset_pairs is not None else fetch("AssetPairs")
        catalog = serve.spot_catalog(lambda name: raw_pairs)
        catalog_error = None
    except (OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
        catalog = {}
        catalog_error = type(exc).__name__ + ": catalogo non verificabile"
    seen = set()
    duplicates = set()
    for row in positions:
        if isinstance(row, dict):
            sym, ok = desk.wallet_symbol(row.get("token"))
            if ok and sym in seen:
                duplicates.add(sym)
            seen.add(sym)
    # Interleave requests fairly: first timeframe for ALL positions, then the
    # next. A late wallet row must not be denied analysis by scanner rank.
    entries = []
    for index, row in enumerate(positions):
        raw = row.get("token") if isinstance(row, dict) else None
        sym, valid = desk.wallet_symbol(raw)
        entry = {"indice": index, "token": sym, "identita_valida": valid,
                 "rilevazione_kraken_utc": snapshot,
                 "timeframe": {label: {"timeframe": label, "stato": "NON_DISPONIBILE",
                                       "motivo": "Non acquisito"} for label, _ in LABELS}}
        if not valid or not isinstance(row, dict):
            entry["stato"] = "IDENTITA_NON_VALIDA"
        elif sym in duplicates:
            entry["stato"] = "IDENTITA_DUPLICATA"
        elif catalog_error:
            entry.update(stato="CATALOGO_NON_DISPONIBILE", motivo=catalog_error)
        else:
            meta, state, reason = select_pair(sym, catalog)
            if state:
                entry.update(stato=state, motivo=reason)
            else:
                entry.update(stato="IN_ANALISI", coppia=meta["pair"],
                             pair_key=meta["pair_key"], asset_base=meta["base"],
                             valuta_quotazione=meta["quote"],
                             eleggibilita_conto="NON_VERIFICATA",
                             metodo_scelta="EUR preferita; altrimenti USD, USDC; solo coppie Kraken online")
                entry["_meta"] = meta
        if entry["stato"] != "IN_ANALISI":
            for label, _ in LABELS:
                entry["timeframe"][label]["motivo"] = entry["stato"]
        entries.append(entry)
    cache = {}
    for label, tf in LABELS:
        for entry in entries:
            meta = entry.get("_meta")
            if meta is None:
                continue
            cache_key = (meta["pair_key"], label)
            if cache_key not in cache:
                frame = None
                if label == "4H" and isinstance(old_4h, dict):
                    try:
                        frame = from_old_4h(old_4h.get(entry["token"]), meta, now)
                    except (KeyError, ValueError, TypeError, OverflowError):
                        frame = None
                    if frame is not None:
                        result["riusi_4h"] += 1
                if frame is None:
                    if result["richieste_ohlc"] >= max_queries:
                        cache[cache_key] = {"timeframe": label, "stato": "RINVIATO_BUDGET",
                                            "motivo": "Budget chiamate OHLC esaurito"}
                    else:
                        result["richieste_ohlc"] += 1
                        try:
                            raw = fetch("OHLC", pair=meta["pair_key"],
                                        interval=charts.TIMEFRAMES[tf][0])
                            checked = serve.checked_spot_ohlc(raw, meta)
                            frame = charts.data_from_kraken_ohlc(
                                checked, tf, now=now, pair=meta["pair"],
                                token=meta["base"], pair_key=meta["pair_key"])
                        except (OSError, RuntimeError, ValueError, KeyError,
                                TypeError, IndexError, OverflowError) as exc:
                            cache[cache_key] = {"timeframe": label, "stato": "NON_DISPONIBILE",
                                                "motivo": type(exc).__name__ + ": " + str(exc)[:105]}
                        if pause is not None:
                            pause(0.25)
                if cache_key not in cache:
                    try:
                        cache[cache_key] = analyze_frame(frame, now)
                    except (KeyError, ValueError, TypeError, IndexError, OverflowError,
                            ZeroDivisionError) as exc:
                        cache[cache_key] = {"timeframe": label, "stato": "NON_VALIDO",
                                            "motivo": type(exc).__name__ + ": dati tecnici non verificabili"}
            entry["timeframe"][label] = cache[cache_key]
    for entry in entries:
        entry.pop("_meta", None)
        if entry["stato"] == "IN_ANALISI":
            vals = list(entry["timeframe"].values())
            entry["stato"] = ("COMPLETO" if all(v["stato"] == "AGGIORNATO" for v in vals)
                              else "PARZIALE")
        result["posizioni"].append(entry)
    return result
