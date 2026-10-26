"""KDD: grafico locale SUI/EUR per timeframe 15m, 1H, 4H, 1D.
Solo Kraken Spot pubblico e dossier locale, candele chiuse reali, nessun ordine.
"""
from __future__ import annotations

# CANARY DEPLOY 2026-10-20: sola verifica aggiornamento GitHub → Termux.
# Nessun cambiamento al grafico, ai dati di mercato o al comportamento di KDD.

import datetime as dt
import html
import json
import math
import re
import urllib.parse
import statistics
from pathlib import Path

TOKEN = "SUI"
TF = "4H"
CANDLES_MAX = 200


def market_round(value):
    """Preserve sub-micro market levels; legacy 8dp for ordinary prices."""
    if value != 0 and abs(value) < 1e-6:
        return float(f"{value:.12g}")
    return round(value, 8)

TIMEFRAMES = {"15m": (15, "15m"), "1h": (60, "1H"),
              "4h": (240, "4H"), "1d": (1440, "1D")}

def data_from_dossier(path: Path):
    src = json.loads(path.read_text(encoding="utf-8"))
    market = src.get("grafici_4h", {}).get(TOKEN)
    if not market or market.get("stato") != "OK":
        raise ValueError("Serie SUI 4H non disponibile o con lacune")
    if market.get("coppia") != "SUI/EUR":
        raise ValueError("La coppia SUI/EUR non corrisponde ai dati richiesti")
    records = market.get("serie_ohlcv_chiuse")
    if not isinstance(records, list) or not 30 <= len(records) <= CANDLES_MAX:
        raise ValueError("Numero di candele chiuse 4H insufficiente o inatteso")

    now = dt.datetime.now(dt.timezone.utc).timestamp()
    ordered = []
    previous = None
    for record in records:
        ts = record.get("apertura_ts_utc")
        if type(ts) is not int or (previous is not None and ts-previous != 14400):
            raise ValueError("Timestamp delle candele non consecutivi")
        previous = ts
        if ts+14400 > now + 2:  # esclude la candela ancora in formazione
            raise ValueError("Candela 4H non conclusa")
        prices = {k: float(record[k]) for k in ("open", "high", "low", "close")}
        volume = float(record["volume_base"])
        o,h,l,c = (prices[k] for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(v) for v in (o,h,l,c,volume)) or not (
            0 < l <= min(o,c) <= max(o,c) <= h and volume >= 0
        ):
            raise ValueError("OHLCV non valido")
        ordered.append({"time":ts, **prices, "volume":volume})
    return {
        "observed_utc": src["creato_utc"],
        "pair":market["coppia"],
        "token":TOKEN,
        "timeframe":TF,
        "closed_at_utc": dt.datetime.fromtimestamp(
            ordered[-1]["time"]+14400, dt.timezone.utc
        ).isoformat(timespec="seconds"),
        "candles":ordered,
    }

def data_from_kraken_ohlc(result, timeframe, now=None, *, pair='SUI/EUR', token='SUI', pair_key=None):
    """Real consecutive Kraken Spot OHLC candles, discarding final uncommitted bar."""
    if timeframe not in TIMEFRAMES:
        raise ValueError("Timeframe non consentito")
    if (not isinstance(pair, str) or
            re.fullmatch(r"[A-Za-z0-9._-]{1,40}/[A-Za-z0-9._-]{1,40}", pair) is None or
            not isinstance(token, str) or token != pair.split("/", 1)[0]):
        raise ValueError("Identità coppia Kraken non valida")
    minutes, label = TIMEFRAMES[timeframe]
    seconds = minutes * 60
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Orario senza fuso orario")
    series = [v for k, v in result.items() if k != "last"]
    if len(series) != 1 or not isinstance(series[0], list) or len(series[0]) < 31:
        raise ValueError("Storico Kraken incompleto o inatteso")
    # Kraken documents the final OHLC row as the uncommitted interval.
    raw = series[0][:-1][-CANDLES_MAX:]
    closed, previous = [], None
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 7:
            raise ValueError("Candela Kraken malformata")
        ts = row[0]
        if type(ts) is not int or ts % seconds:
            raise ValueError("Timestamp non allineato al timeframe")
        if previous is not None and ts - previous != seconds:
            raise ValueError("Lacuna temporale: nessuna candela interpolata")
        if ts + seconds > now.timestamp() + 2:
            raise ValueError("Candela non conclusa")
        previous = ts
        o, h, l, c, volume = map(float, (row[1], row[2], row[3], row[4], row[6]))
        if not all(math.isfinite(v) for v in (o, h, l, c, volume)) or not (
                0 < l <= min(o, c) <= max(o, c) <= h and volume >= 0):
            raise ValueError("OHLCV Kraken non valido")
        closed.append({"time": ts, "open": o, "high": h, "low": l,
                       "close": c, "volume": volume})
    if len(closed) < 30:
        raise ValueError("Storico di candele chiuse insufficiente")
    return {"observed_utc": now.isoformat(timespec="seconds"),
            "pair": pair, "token": token, "pair_key": pair_key, "timeframe": label,
            "closed_at_utc": dt.datetime.fromtimestamp(
                closed[-1]["time"] + seconds, dt.timezone.utc
            ).isoformat(timespec="seconds"),
            "candles": closed, "interval_seconds": seconds,
            "source": "Kraken Spot pubblico /0/public/OHLC"}


def ema_points(candles, period):
    """EMA sull'ultimo campione di candele chiuse; SMA iniziale di 'period' chiusure.

    I primi period-1 punti sono assenti, mai riempiti artificialmente.
    """
    if not isinstance(period, int) or period < 2 or len(candles) < period:
        return []
    alpha = 2.0 / (period + 1)
    values = [row["close"] for row in candles]
    ema = sum(values[:period]) / period
    points = [{"time": candles[period - 1]["time"], "value": market_round(ema)}]
    for i in range(period, len(candles)):
        ema += alpha * (values[i] - ema)
        points.append({"time": candles[i]["time"], "value": market_round(ema)})
    return points


def daily_pivots(candles, interval_seconds=14400):
    """Pivot CLASSICI del giorno UTC precedente, con barre complete del timeframe.

    Il riferimento è il giorno UTC nel quale cade la chiusura più recente:
    non si usano candele in formazione né dati del giorno corrente.
    """
    if not candles:
        return None
    last_close = dt.datetime.fromtimestamp(
        candles[-1]["time"] + interval_seconds, dt.timezone.utc)
    prev_day = last_close.date() - dt.timedelta(days=1)
    start = int(dt.datetime.combine(prev_day, dt.time.min,
                                     dt.timezone.utc).timestamp())
    day = [row for row in candles if start <= row["time"] < start + 86400]
    expected = 86400 // interval_seconds
    if 86400 % interval_seconds or len(day) != expected or [row["time"] for row in day] != [
            start + interval_seconds * i for i in range(expected)]:
        return None
    high = max(row["high"] for row in day)
    low = min(row["low"] for row in day)
    close = day[-1]["close"]
    p = (high + low + close) / 3.0
    spread = high - low
    return {"reference_day_utc": prev_day.isoformat(),
            "P": market_round(p),
            "R1": market_round(2 * p - low),
            "S1": market_round(2 * p - high),
            "R2": market_round(p + spread),
            "S2": market_round(p - spread),
            "R3": market_round(high + 2 * (p - low)),
            "S3": market_round(low - 2 * (high - p))}


def structural_levels(candles, tolerance=0.009):
    """Livelli *descrittivi* da swing 4H confermati: almeno due test.

    Richiede due candele chiuse prima e dopo ciascuno swing (raggio 2).
    Raggruppa prezzi simili entro una tolleranza relativa dello 0,9%.
    Nessun livello quando mancano due estremi indipendenti. Non è un ordine.
    """
    if len(candles) < 7:
        return {"supports": [], "resistances": []}
    last = candles[-1]["close"]
    def pivots(side):
        col = "low" if side == "low" else "high"
        result = []
        for i in range(2, len(candles) - 2):
            here = candles[i][col]
            nearby = [candles[j][col] for j in range(i - 2, i + 3) if j != i]
            if ((here < min(nearby)) if side == "low" else
                    (here > max(nearby))):
                result.append((i, here))
        return result
    def group(items, support):
        clusters = []
        for index, price in sorted(items, key=lambda entry: entry[1]):
            found = next((
                cl for cl in clusters
                if abs(price - statistics.median(x[1] for x in cl)) /
                   statistics.median(x[1] for x in cl) <= tolerance
            ), None)
            if found is None:
                clusters.append([(index, price)])
            else:
                found.append((index, price))
        candidates = []
        for cl in clusters:
            if len(cl) < 2:
                continue
            level = statistics.median(x[1] for x in cl)
            if (support and level >= last) or (not support and level <= last):
                continue
            candidates.append((level, len(cl), max(x[0] for x in cl)))
        # Prossimità al prezzo corrente, a parità tocchi/recenza.
        candidates.sort(key=lambda z: (abs(z[0] - last), -z[1], -z[2]))
        return [{"price": market_round(p), "touches": n,
                 "last_swing_time": candles[i]["time"]}
                for p, n, i in candidates[:3]]
    return {"supports": group(pivots("low"), True),
            "resistances": group(pivots("high"), False)}


def technical_from_candles(candles, interval_seconds=14400):
    return {
        "ema20": ema_points(candles, 20),
        "ema50": ema_points(candles, 50),
        "pivots": daily_pivots(candles, interval_seconds=interval_seconds),
        "structure": structural_levels(candles),
    }


def temporal_consistency(data, *, now):
    """Validate reported observation, completed candle and timeframe together.

    Returns comparable timestamps in seconds; an inconsistent source is
    rejected even if its last candle happens to look recent.
    """
    if now.tzinfo is None:
        raise ValueError("Orario UTC di confronto non valido")
    intervals = {"15m": 900, "1H": 3600, "4H": 14400, "1D": 86400}
    seconds = intervals.get(data.get("timeframe"))
    if seconds is None or data.get("interval_seconds", seconds) != seconds:
        raise ValueError("Durata candele incoerente")
    candles = data["candles"]
    if not candles:
        raise ValueError("Candele mancanti")
    last_start = candles[-1]["time"]
    if type(last_start) is not int or last_start % seconds:
        raise ValueError("Orario ultima candela non allineato")
    close_end = last_start + seconds

    def parse_utc(name):
        value = data[name]
        if not isinstance(value, str):
            raise ValueError("Timestamp " + name + " non valido")
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timestamp " + name + " privo di fuso")
        return parsed.timestamp()

    observed = parse_utc("observed_utc")
    closed = parse_utc("closed_at_utc")
    t = now.timestamp()
    # Rounding/clock tolerance only (2s), not an extra candle of leeway.
    if (abs(closed - close_end) > 2
            or close_end > t + 2
            or closed > t + 2
            or observed > t + 2
            or observed < close_end - 2
            or closed > observed + 2):
        raise ValueError("Metadati temporali discordanti, futuri o non verificabili")
    expected_end = int((t - 120) // seconds) * seconds
    return {"observed": observed, "closed": closed, "seconds": seconds,
            "fresh": close_end >= expected_end}


def summarize_timeframe(data, now=None):
    """Describe price/EMA and completed-volume observations, never a trade signal.

    Freshness is assessed against the most recent fully closed time boundary,
    allowing 120 seconds for the upstream OHLC close to become available.
    Never replace a missing/stale frame with another timeframe.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    frame = data.get("timeframe")
    records = data.get("candles", [])
    if frame not in ("15m", "1H", "4H", "1D"):
        raise ValueError("Timeframe sconosciuto")
    if len(records) < 50:
        return {"timeframe": frame, "stato": "STORICO_INSUFFICIENTE",
                "motivo": "Servono almeno 50 candele chiuse per confrontare EMA20 ed EMA50"}
    timing = temporal_consistency(data, now=now)
    seconds = timing["seconds"]
    close_end = records[-1]["time"] + seconds
    last = records[-1]
    fresh = timing["fresh"]
    indicator20 = ema_points(records, 20)[-1]["value"]
    indicator50 = ema_points(records, 50)[-1]["value"]
    price = last["close"]
    prior = [r["volume"] for r in records[-21:-1]]
    volume_avg = statistics.mean(prior)
    volume_ratio = last["volume"] / volume_avg if volume_avg > 0 else None
    if price > indicator20 > indicator50:
        orientation = "PREZZO_SOPRA_EMA20_SOPRA_EMA50"
    elif price < indicator20 < indicator50:
        orientation = "PREZZO_SOTTO_EMA20_SOTTO_EMA50"
    else:
        orientation = "CONFIGURAZIONE_MISTA"
    structure = structural_levels(records)
    supports = structure.get("supports", [])
    resistances = structure.get("resistances", [])
    return {
        "timeframe": frame,
        "stato": "AGGIORNATO" if fresh else "SCADUTO",
        "orientamento": orientation if fresh else "NON_VALUTABILE",
        "chiusura_utc": dt.datetime.fromtimestamp(
            close_end, dt.timezone.utc).isoformat(timespec="seconds"),
        "rilevazione_utc": data["observed_utc"],
        "candele": len(records),
        "close": price,
        "ema20": indicator20,
        "ema50": indicator50,
        "volume": last["volume"],
        "volume_vs_media20": round(volume_ratio, 3) if volume_ratio is not None else None,
        "supporto_vicino": supports[0]["price"] if supports else None,
        "resistenza_vicina": resistances[0]["price"] if resistances else None,
        "fonte": data.get("source", "Dossier Kraken KDD"),
    }


def compare_timeframes(frames, now=None, *, pair='SUI/EUR'):
    """Compare four independently acquired frames without implying an order."""
    now = now or dt.datetime.now(dt.timezone.utc)
    labels = ("15m", "1H", "4H", "1D")
    details = []
    for name in labels:
        entry = frames.get(name)
        if isinstance(entry, dict) and "errore" in entry:
            details.append({"timeframe": name, "stato": "NON_DISPONIBILE",
                            "motivo": str(entry["errore"])[:160]})
        elif entry is None:
            details.append({"timeframe": name, "stato": "NON_DISPONIBILE",
                            "motivo": "Nessun dato disponibile"})
        else:
            try:
                details.append(summarize_timeframe(entry, now=now))
            except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError):
                details.append({"timeframe": name, "stato": "NON_VALIDO",
                                "motivo": "Serie OHLC o timestamp non verificabili"})
    complete = all(x["stato"] == "AGGIORNATO" for x in details)
    if not complete:
        picture = "CONFRONTO_INCOMPLETO"
    else:
        orientations = {x["orientamento"] for x in details}
        if orientations == {"PREZZO_SOPRA_EMA20_SOPRA_EMA50"}:
            picture = "ALLINEAMENTO_RIALZISTA_DESCRITTIVO"
        elif orientations == {"PREZZO_SOTTO_EMA20_SOTTO_EMA50"}:
            picture = "ALLINEAMENTO_RIBASSISTA_DESCRITTIVO"
        else:
            picture = "CONFIGURAZIONE_MISTA"
    return {"coppia": pair, "rilevazione_confronto_utc": now.isoformat(
                timespec="seconds"), "stato": "COMPLETO" if complete else "PARZIALE",
            "quadro": picture, "timeframe": details,
            "avvertenza": ("Ultime chiusure a orari differenti: confrontare la posizione "
                          "rispetto alle medie, non considerare i close simultanei. "
                          "Nessun segnale operativo, probabilita o istruzione di trading.")}


def page_from_dossier(path: Path):
    return page_from_data(data_from_dossier(path))


def page_from_data(x, *, now=None, home_url="/"):
    """Real 15m/1H/4H/1D candles; fail closed on unrepresentable price ticks."""
    frame = x.get("timeframe", "4H")
    interval = x.get("interval_seconds", 14400)
    if frame not in ("15m", "1H", "4H", "1D"):
        raise ValueError("Timeframe non valido")
    active = {"15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}[frame]
    key = x.get("pair_key")
    if key is not None and not re.fullmatch(r"[A-Za-z0-9_.-]{2,48}", key):
        raise ValueError("Chiave Kraken non valida")
    path = ("/grafico/spot?pair=" + urllib.parse.quote(key, safe="") + "&tf="
            if key else "/grafico/sui-4h?tf=")
    links = " ".join(
        '<a class="tf-link" href="' + html.escape(path + frame_key, quote=True) +
        '"' + (' aria-current="page"' if frame_key == active else "") +
        '>' + html.escape(label) + '</a>'
        for frame_key, (_, label) in TIMEFRAMES.items())
    candle_json = json.dumps(x["candles"], separators=(",",":"), allow_nan=False)
    technical = technical_from_candles(x["candles"], interval_seconds=interval)
    technical_json = json.dumps(technical, separators=(",",":"), allow_nan=False)
    # Friendly labels must never overwrite the exact pair identity from Kraken.
    pair = html.escape(x.get("display_pair", x["pair"]), quote=True)
    token = x.get("display_token", x.get("token"))
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", token):
        raise ValueError("Token grafico non valido")
    token_js = json.dumps(token, ensure_ascii=True)
    quote_js = json.dumps(x["pair"].split("/", 1)[1], ensure_ascii=True)
    positive_lows = [r["low"] for r in x["candles"]]
    if (not positive_lows or not all(isinstance(v, (int, float)) and
            math.isfinite(v) and v > 0 for v in positive_lows)):
        raise ValueError("Prezzo minimo OHLC non valido")
    smallest = min(positive_lows)
    if smallest < 1e-12:
        # Explicitly decline to misrepresent smaller quotes as zero
        # with the 12dp precision currently supported by this view.
        raise ValueError("Prezzo sotto la precisione supportata dal grafico")
    # Original OHLC must be injective at display precision. EMA, pivots and
    # structural levels retain their original numeric values, but legitimate
    # sub-tick variation in calculated series is normal and NOT a reason to
    # reject representable exchange candles.
    prices = [r[k] for r in x["candles"] for k in ("open", "high", "low", "close")]
    prices.extend(p["value"] for name in ("ema20", "ema50")
                  for p in technical[name])
    if technical["pivots"]:
        prices.extend(value for key, value in technical["pivots"].items()
                      if key != "reference_day_utc")
    for side in ("supports", "resistances"):
        prices.extend(item["price"] for item in technical["structure"][side])
    if not all(isinstance(v, (float, int)) and not isinstance(v, bool)
               and math.isfinite(v) for v in prices):
        raise ValueError("Prezzi e livelli non verificabili")
    # Distinct ORIGINAL prices, both through time and within each candle.
    # Do not enforce artificial sub-tick injectivity on calculated indicators.
    groups = [[r[k] for r in x["candles"]] for k in
              ("open", "high", "low", "close")]
    groups += [[r[k] for k in ("open", "high", "low", "close")]
               for r in x["candles"]]
    decimal_places = max(5, min(12, math.ceil(-math.log10(smallest)) + 3))
    for candidate in range(decimal_places, 13):
        collision = False
        for group in groups:
            represented = {}
            for value in group:
                key_text = f"{value:.{candidate}f}"
                if (value > 0 and float(key_text) == 0
                        or key_text in represented and represented[key_text] != value):
                    collision = True
                    break
                represented[key_text] = value
            if collision:
                break
        if not collision:
            decimal_places = candidate
            break
    else:
        raise ValueError("Prezzi distinti non rappresentabili entro 12 decimali")
    min_move = 10 ** (-decimal_places)
    now = now or dt.datetime.now(dt.timezone.utc)
    timing = None
    try:
        freshness = summarize_timeframe(x, now=now)
        fresh_state = freshness["stato"]
        if fresh_state in ("AGGIORNATO", "SCADUTO"):
            timing = temporal_consistency(x, now=now)
    except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError, OverflowError):
        fresh_state = "NON_VERIFICABILE"
    temporal_valid = timing is not None
    if fresh_state == "AGGIORNATO":
        freshness_text = "DATI RECENTI VERIFICATI: ultima candela chiusa disponibile."
    elif fresh_state == "SCADUTO":
        freshness_text = "GRAFICO STORICO / SCADUTO: non descrive il mercato corrente."
    else:
        freshness_text = "DATI INCOMPLETI O NON VERIFICABILI: nessuna lettura corrente."
    if not isinstance(home_url, str) or home_url not in ("/", "http://127.0.0.1:8765/"):
        raise ValueError("Destinazione navigazione non consentita")
    comparison_url = ("/analisi/spot?pair=" + urllib.parse.quote(key, safe="")
                      if key else "/analisi/sui-mtf")
    observed = html.escape(x["observed_utc"], quote=True)
    closed = html.escape(x["closed_at_utc"], quote=True)
    freshness_text = html.escape(freshness_text, quote=True)
    notice = ("TradingView Lightweight Charts™. "
              "Copyright (с) 2025 TradingView, Inc.")
    template = """<!doctype html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KDD | SUI/EUR __TF__</title>
<style>
:root{color-scheme:dark;font-family:system-ui,Arial,sans-serif;background:#0b1221;color:#eaf0fa}
*{box-sizing:border-box}body{margin:0;padding:12px;max-width:1120px;margin-inline:auto}
a{color:#8aceff}h1{font-size:1.25rem;margin:8px 0}small,.muted{color:#b3c1d8}
header{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.panel{background:#151f32;border:1px solid #34415d;border-radius:12px;padding:12px;margin-top:12px}
#price-shell{position:relative}
#price-plot{width:100%;height:420px}#volume-plot{width:100%;height:150px}
#plot-ema-legend{position:absolute;z-index:2;top:9px;left:10px;pointer-events:none;
  display:flex;gap:11px;flex-wrap:wrap;padding:5px 8px;
  border-radius:6px;background:rgba(16,26,44,.86);
  color:#eaf0fa;font-size:.78rem;font-weight:600}
#plot-ema-legend span{display:inline-flex;align-items:center;gap:5px}
#plot-ema-legend [hidden]{display:none}
.ema-swatch{display:inline-block;width:18px;border-top:2px solid}
.ema-swatch.ema20{border-color:#ffc85a}
.ema-swatch.ema50{border-color:#58c5ff}
.buttons{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
.legend{display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 12px}
.legend label{display:flex;gap:6px;align-items:center;padding:8px;border:1px solid #536481;
 background:#1a2941;border-radius:8px;font-size:.92rem}
.legend input{width:17px;height:17px;accent-color:#8aceff}
#tech-summary{font-size:.9rem;line-height:1.45;margin-bottom:6px}
#nearby-summary{font-size:.9rem;line-height:1.5;padding:8px 10px;
 background:#1a2941;border-left:3px solid #8aceff;border-radius:5px;margin:8px 0 12px}
.level-details{margin:8px 0 14px;padding:10px;border:1px solid #41506c;border-radius:8px}
.level-details summary{cursor:pointer;color:#c7e8ff;font-weight:600}
.level-details section{margin:12px 0 8px}
.level-details h3{font-size:.95rem;margin:8px 0}
.level-details table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:.9rem}
.level-details td,.level-details th{padding:7px 5px;border-bottom:1px solid #3a4b64;text-align:left}
.level-details td:nth-child(2){font-weight:600;text-align:right;white-space:nowrap}
.level-details td:last-child,.level-details th:last-child{font-size:.82rem;color:#b7c9dd;padding-left:8px}
.level-details .method{margin:9px 0;font-size:.85rem}
.tf-link{display:inline-flex;align-items:center;justify-content:center;min-width:60px;
min-height:42px;padding:8px 13px;border-radius:8px;border:1px solid #5e8cbb;
background:#253c5e;color:white;text-decoration:none;font-weight:650}
.tf-link[aria-current="page"]{background:#89cfff;color:#09172b;border-color:#89cfff}
button{font:inherit;min-height:40px;padding:8px 14px;border-radius:8px;
 background:#253c5e;border:1px solid #5e8cbb;color:white}
button:focus-visible,a:focus-visible{outline:3px solid #a2e2ff}
.stats{font-variant-numeric:tabular-nums;min-height:42px}
#graph-status{font-weight:600;color:#85e6bc;min-height:24px}
#graph-status.error{color:#ff969d}
#market-freshness{font-weight:700;line-height:1.45}
#market-freshness.current{color:#85e6bc}
#market-freshness.warning{color:#ffd48a}
footer{font-size:.83rem;color:#b3c1d8;line-height:1.5;margin:14px 0 26px}
</style>
</head>
<body>
<header>
<div><h1>📈 KDD · Grafico SUI/EUR · __TF__</h1>
<small>Kraken Spot · candele CHIUSE · orari UTC · nessun ordine</small></div>
<a href="__HOME_URL__">← Torna al cruscotto</a>
</header>
<section class="panel">
<div id="graph-status" role="status">Preparazione grafico…</div>
<p id="market-freshness" class="__FRESH_CLASS__" role="status">__FRESHNESS__</p>
<p class="muted">Ultima candela CHIUSA: __CLOSED__. Rilevazione: __OBSERVED__.
La freschezza si rivaluta nella scheda senza richiedere nuove candele.
La rilevazione originale non cambia; il grafico non fornisce quotazioni in tempo reale.</p>
<nav class="buttons" aria-label="Timeframe grafico">
__TIMEFRAME_BUTTONS__
</nav>
<p class="muted">Seleziona l'intervallo reale delle candele. Zoom e scorrimento col dito.</p>
<p><a href="__COMPARE_URL__" style="font-weight:700">🔎 Confronta 15m · 1H · 4H · 1D</a></p>
<div class="legend" aria-label="Livelli e indicatori">
<label><input type="checkbox" id="show-ema20" checked> EMA20 (oro)</label>
<label><input type="checkbox" id="show-ema50" checked> EMA50 (azzurro)</label>
<label><input type="checkbox" id="show-structure" checked> S/R principali</label>
<label><input type="checkbox" id="show-pivots"> Pivot (3 linee)</label>
</div>
<div id="tech-summary" class="muted" aria-live="polite">Elaborazione livelli tecnici…</div>
<div id="nearby-summary" aria-live="polite">Ricerca di eventuali vicinanze fra livelli…</div>
<details class="level-details">
<summary>Tutti i livelli e i prezzi esatti (apri)</summary>
<p class="method">Le linee sul grafico mostrano soltanto i due S/R più vicini per lato
e, se selezionati, P più un pivot sopra e uno sotto l'ultima chiusura.
Nella tabella trovi tutti i livelli calcolati, anche quelli nascosti.
Sull'asse destro, i S/R mostrano il prezzo a cinque decimali quando
c'è spazio. Le etichette che si sovrapporrebbero al prezzo corrente
o ad altri livelli vengono nascoste, lasciando le linee visibili.
Il motore grafico può spostare altre etichette: per prezzi esatti
e gli eventuali livelli senza targhetta consulta la tabella.
I pivot mantengono le etichette sull'asse disattivate.</p>
<div id="levels-list"></div>
</details>
<div class="stats" id="candle-stats" aria-live="polite">Seleziona una candela per i valori OHLCV.</div>
<p id="axis-note" class="muted" aria-live="polite">Prezzi S/R a cinque decimali; etichette troppo vicine nascoste senza rimuovere le linee.</p>
<div id="price-shell">
<div id="plot-ema-legend" role="note" aria-label="Legenda delle medie mobili">
<span data-ema="20"><i class="ema-swatch ema20" aria-hidden="true"></i>EMA20</span>
<span data-ema="50"><i class="ema-swatch ema50" aria-hidden="true"></i>EMA50</span>
</div>
<div id="price-plot" aria-label="Grafico candlestick SUI/EUR __TF__"></div>
</div>
<h2 style="font-size:1rem">Volumi scambiati (SUI)</h2>
<div id="volume-plot" aria-label="Istogramma volumi SUI/EUR __TF__"></div>
<p class="muted">Dati raccolti: __OBSERVED__. Ultima candela chiusa: __CLOSED__.
Il grafico usa fino a 200 candele __TF__ chiuse. Fonte: __SOURCE__.
L'ultimo prezzo mostrato è una chiusura, non una quotazione live.</p>
<p class="muted"><b>INDICATORI ESPLORATIVI __TF__.</b>
EMA20/50 calcolate esclusivamente sulle candele CHIUSE presenti (massimo 200,
seme SMA iniziale). Supporti e resistenze: estremi locali confermati con
almeno due swing vicini; se mancano non viene inventata una linea.
Pivot P/S1–S3/R1–R3: formule classiche sul giorno UTC precedente, solo se
è presente l'intera giornata UTC precedente di candele chiuse. Il grafico limita il
numero delle linee per leggibilità, mentre la tabella conserva i valori
completi. Le vicinanze fra indicatori non costituiscono conferme indipendenti:
sono una descrizione geometrica; nessun segnale BUY/SELL.
Prezzi OHLC originali rappresentabili senza collisioni; EMA e livelli
conservano il valore numerico di calcolo, ma possono sovrapporsi alla
risoluzione massima della scala (12 decimali).
Pattern e altri timeframe NON sono ancora implementati.</p>
</section>
<footer><a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">
__NOTICE__</a> · Libreria gratuita Lightweight Charts 5.2.1, servita localmente.
<a href="/asset/lightweight-notice">NOTICE</a> ·
<a href="/asset/lightweight-license">Licenza Apache 2.0</a>.
Dati Kraken Spot pubblici, non grafico ufficiale TradingView.</footer>
<script src="/asset/lightweight-charts.js"></script>
<script>
(function(){
"use strict";
const rows = __BARS__;
const timeframeLabel = '__TF__';
const tech = __TECHNICAL__;
const msg=document.getElementById('graph-status');
const stats=document.getElementById('candle-stats');
// Only the age indicator changes; the original Kraken candle array never does.
const freshnessValid=__FRESH_VALID__;
const lastClosedMs=__LAST_CLOSED_MS__;
const observedMs=__OBSERVED_MS__;
const intervalMs=__INTERVAL_MS__;
function freshnessAt(nowMs){
  if(!freshnessValid || !Number.isFinite(nowMs) ||
     nowMs < lastClosedMs-2000 || nowMs < observedMs-2000)
    return 'NON_VERIFICABILE';
  const expected=Math.floor((nowMs-120000)/intervalMs)*intervalMs;
  return lastClosedMs >= expected ? 'AGGIORNATO' : 'SCADUTO';
}
function updateFreshness(){
  const state=freshnessAt(Date.now());
  const el=document.getElementById('market-freshness');
  if(state==='AGGIORNATO'){
    el.textContent='DATI RECENTI VERIFICATI: ultima candela chiusa disponibile.';
    el.className='current';
  }else if(state==='SCADUTO'){
    el.textContent='GRAFICO STORICO / SCADUTO: non descrive il mercato corrente.';
    el.className='warning';
  }else{
    el.textContent='DATI INCOMPLETI O NON VERIFICABILI: nessuna lettura corrente.';
    el.className='warning';
  }
}
updateFreshness();
setInterval(updateFreshness,15000);
document.addEventListener('visibilitychange',updateFreshness);
window.addEventListener('focus',updateFreshness);
try {
  if (!window.LightweightCharts ||
      !LightweightCharts.createChart ||
      !LightweightCharts.CandlestickSeries ||
      !LightweightCharts.HistogramSeries ||
      !LightweightCharts.LineSeries) {
     throw new Error('Libreria grafica non caricata completamente');
  }
  const grid={vertLines:{color:'#27354c'},horzLines:{color:'#27354c'}};
  const layout={background:{type:'solid',color:'#101a2c'},textColor:'#dbe5f3',
                attributionLogo:true,fontFamily:'system-ui, sans-serif'};
  const common={width:document.getElementById('price-plot').clientWidth,
    rightPriceScale:{borderColor:'#50617b',alignLabels:true},timeScale:{borderColor:'#50617b',
    timeVisible:true,secondsVisible:false},layout:layout,grid:grid,
    localization:{locale:'it-IT'}};
  const chart=LightweightCharts.createChart(document.getElementById('price-plot'),
                {...common,height:420});
  const candleSeries=chart.addSeries(LightweightCharts.CandlestickSeries,{
    upColor:'#23bb91',downColor:'#ee6b77',borderVisible:false,
    wickUpColor:'#23bb91',wickDownColor:'#ee6b77',priceLineVisible:false,
    priceFormat:{type:'price',precision:__PRECISION__,minMove:__MIN_MOVE__},
    lastValueVisible:true});
  candleSeries.setData(rows.map(v=>({
    time:v.time,open:v.open,high:v.high,low:v.low,close:v.close})));
  // EMA calcolate in Python sul medesimo campione chiuso delle candele.
  // Non introdurre qui dati nuovi o stime che non siano tracciabili.
  function addEma(points,color,selector,legendSelector){
    const series=chart.addSeries(LightweightCharts.LineSeries,{
      color:color,lineWidth:2,priceLineVisible:false,lastValueVisible:false,
      priceFormat:{type:'price',precision:__PRECISION__,minMove:__MIN_MOVE__},
      crosshairMarkerVisible:false,title:''});
    series.setData(points);
    const control=document.querySelector(selector);
    const indicator=document.querySelector(legendSelector);
    function sync(){
      const visible=control.checked&&!control.disabled;
      series.applyOptions({visible:visible});
      indicator.hidden=!visible;
    }
    control.addEventListener('change',sync);
    sync();
    return series;
  }
  addEma(tech.ema20,'#ffc85a','#show-ema20','[data-ema="20"]');
  if(tech.ema50.length)
    addEma(tech.ema50,'#58c5ff','#show-ema50','[data-ema="50"]');
  else {
    const e=document.querySelector('#show-ema50');
    e.checked=false;e.disabled=true;e.parentElement.title='Meno di 50 barre chiuse';
    document.querySelector('[data-ema="50"]').hidden=true;
  }

  // Il numero mostrato su una linea S/R è a cinque decimali; la
  // tabella sottostante conserva il valore di calcolo a otto decimali.
  // Se i prezzi sono vicini, non spostiamo etichette fingendo una
  // corrispondenza verticale: ne mostriamo soltanto quelle distinguibili.
  const PRICE_LABEL_GAP_PX=30;
  const lastClose=rows[rows.length-1].close;
  const axisNote=document.getElementById('axis-note');
  let activeStructural=[];
  let labelUpdatePending=false;
  function refreshAxisLabels(){
    if(!activeStructural.length){
      axisNote.textContent='Livelli S/R nascosti: i prezzi esatti restano nella tabella.';
      return;
    }
    const occupied=[];
    const lastY=candleSeries.priceToCoordinate(lastClose);
    if(Number.isFinite(lastY))occupied.push(lastY);
    const ranked=activeStructural.map(e=>({
      ...e,y:candleSeries.priceToCoordinate(e.price)
    })).sort((a,b)=>Math.abs(a.price-lastClose)-Math.abs(b.price-lastClose));
    let hidden=0;
    for(const item of ranked){
      const visible=Number.isFinite(item.y) &&
        item.y>=0 && item.y<=document.getElementById('price-plot').clientHeight &&
        occupied.every(y=>Math.abs(y-item.y)>=PRICE_LABEL_GAP_PX);
      // Solo l'etichetta viene omessa; la linea resta a prezzo reale.
      item.line.applyOptions({axisLabelVisible:visible});
      if(visible)occupied.push(item.y);
      else hidden++;
    }
    axisNote.textContent="S/R sull'asse: prezzi a 5 decimali."+
      (hidden?' '+hidden+' etichett'+(hidden===1?'a omessa':'e omesse')+
       ' per vicinanza o fuori scala; le linee restano visibili.':' Tutte le etichette distinguibili.')+
      ' Prezzi completi nella tabella.';
  }
  function scheduleAxisLabels(){
    if(labelUpdatePending)return;
    labelUpdatePending=true;
    requestAnimationFrame(()=>{
      labelUpdatePending=false;
      refreshAxisLabels();
    });
  }
  function addLevel(price,color,group,showPrice){
    const line=candleSeries.createPriceLine({
      price:price,color:color,lineWidth:1,lineStyle:2,
      axisLabelVisible:showPrice,title:''});
    group.push({line:line,price:price});
  }
  function levelToggle(selector,entries,showPrice,updateStructure=false){
    const input=document.querySelector(selector);
    let active=[];
    function display(){
      for(const item of active)candleSeries.removePriceLine(item.line);
      active=[];
      if(input.checked)entries.forEach(e=>
        addLevel(e.price,e.color,active,showPrice));
      if(updateStructure){
        activeStructural=active;
        scheduleAxisLabels();
      }
    }
    input.addEventListener('change',display);
    display();
  }
  const structural=[];
  tech.structure.supports.slice(0,2).forEach((e,i)=>structural.push({
    price:e.price,color:'#32c7aa'}));
  tech.structure.resistances.slice(0,2).forEach((e,i)=>structural.push({
    price:e.price,color:'#f3a078'}));
  levelToggle('#show-structure',structural,true,true);
  const pivotEntries=[];
  const pivotNames=['P','S1','S2','S3','R1','R2','R3'];
  if(tech.pivots){
    // Una sola linea P e le due coordinate pivot più vicine, sopra e sotto.
    const byDistance=pivotNames.filter(n=>n!=='P')
      .sort((a,b)=>Math.abs(tech.pivots[a]-lastClose)-
                    Math.abs(tech.pivots[b]-lastClose));
    const above=byDistance.find(n=>tech.pivots[n]>lastClose);
    const below=byDistance.find(n=>tech.pivots[n]<lastClose);
    for(const name of ['P',above,below].filter((n,i,all)=>n && all.indexOf(n)===i)){
      pivotEntries.push({price:tech.pivots[name],
        color:name==='P'?'#e4d778':name.startsWith('S')?'#8bceaf':'#bd9fff'});
    }
  }
  levelToggle('#show-pivots',pivotEntries,false);
  const quote=__QUOTE_JS__;
  const priceText=new Intl.NumberFormat('it-IT',{maximumFractionDigits:__PRECISION__});
  const supports=tech.structure.supports.length;
  const resistances=tech.structure.resistances.length;
  document.querySelector('#tech-summary').textContent=
    'Ultima EMA20: '+priceText.format(tech.ema20[tech.ema20.length-1].value)+
    (tech.ema50.length?' · EMA50: '+priceText.format(tech.ema50[tech.ema50.length-1].value):
      ' · EMA50: storico insufficiente')+
    ' · S/R confermati: '+supports+' supporti, '+resistances+' resistenze'+
    ' (almeno due swing per livello).'+
    (tech.pivots?' Pivot del '+tech.pivots.reference_day_utc+
       ' UTC: P '+priceText.format(tech.pivots.P)+'.':
       ' Pivot giornalieri: dati completi giorno precedente insufficienti.');

  // All indicators, levels and OHLC use the selected quote precision.
  const categories=[
    {name:'Medie esponenziali (chiusure '+timeframeLabel+')',family:'EMA',items:[
      {label:'EMA20',price:tech.ema20[tech.ema20.length-1].value,note:'20 chiusure'},
      ...(tech.ema50.length ? [{label:'EMA50',
        price:tech.ema50[tech.ema50.length-1].value,note:'50 chiusure'}] : [])]},
    {name:'Supporti strutturali',family:'S/R',items:
      tech.structure.supports.map((v,i)=>({label:'S'+(i+1),
        price:v.price,note:v.touches+' swing '+timeframeLabel}))},
    {name:'Resistenze strutturali',family:'S/R',items:
      tech.structure.resistances.map((v,i)=>({label:'R'+(i+1),
        price:v.price,note:v.touches+' swing '+timeframeLabel}))},
    {name:'Pivot classici UTC',family:'Pivot',items:
      tech.pivots?pivotNames.map(n=>({label:n,price:tech.pivots[n],
        note:tech.pivots.reference_day_utc})) : []},
  ];
  const panel=document.getElementById('levels-list');
  for(const section of categories){
    const block=document.createElement('section');
    const title=document.createElement('h3');
    title.textContent=section.name;
    block.appendChild(title);
    if(!section.items.length){
      const empty=document.createElement('p');
      empty.textContent='Nessun livello disponibile con i dati chiusi.';
      block.appendChild(empty);
    }else{
      const table=document.createElement('table');
      const header=document.createElement('tr');
      ['Livello','Prezzo '+quote,'Origine'].forEach(name=>{
        const th=document.createElement('th');
        th.textContent=name;header.appendChild(th);
      });
      table.appendChild(header);
      for(const item of section.items){
        const tr=document.createElement('tr');
        [item.label,priceText.format(item.price),item.note].forEach(value=>{
          const td=document.createElement('td');
          td.textContent=value;tr.appendChild(td);
        });
        table.appendChild(tr);
      }
      block.appendChild(table);
    }
    panel.appendChild(block);
  }
  // Confluenza = vicinanza numerica, NON maggior probabilità di rimbalzo.
  // Il gruppo deve stare per intero entro 0,5% del valore mediano.
  const near=categories.flatMap(cat=>cat.items.map(item=>({
    ...item,family:cat.family
  }))).sort((a,b)=>a.price-b.price);
  const groups=[];
  let group=[];
  for(const item of near){
    if(group.length===0 || (item.price-group[0].price)/
        (0.5*(item.price+group[0].price))<=0.005){
      group.push(item);
    }else{
      groups.push(group);group=[item];
    }
  }
  if(group.length)groups.push(group);
  const confluences=groups.filter(items=>items.length>=2 &&
    new Set(items.map(x=>x.family)).size>=2);
  confluences.sort((a,b)=>Math.abs(a[0].price-lastClose)-
                         Math.abs(b[0].price-lastClose));
  const strip=document.getElementById('nearby-summary');
  if(confluences.length){
    const shown=confluences.slice(0,2).map(items=>
      priceText.format(Math.min(...items.map(x=>x.price)))+'–'+
      priceText.format(Math.max(...items.map(x=>x.price)))+' '+quote+' ('+
      items.map(x=>x.label+' '+x.family).join(', ')+')');
    strip.textContent='Vicinanze entro 0,5% (solo descrittive): '+
      shown.join(' · ')+'. Nessuna conferma di tenuta o breakout.';
  }else{
    strip.textContent='Nessuna vicinanza multi-fonte entro 0,5% '+
      'fra i livelli osservati. Non equivale a mancanza di opportunità.';
  }
  const volumeChart=LightweightCharts.createChart(
    document.getElementById('volume-plot'),{...common,height:150});
  const volumeSeries=volumeChart.addSeries(LightweightCharts.HistogramSeries,{
    priceFormat:{type:'volume'},priceLineVisible:false,lastValueVisible:false});
  volumeSeries.setData(rows.map(v=>({
    time:v.time,value:v.volume,
    color:v.close>=v.open?'rgba(35,187,145,0.75)':'rgba(238,107,119,0.75)'})));
  chart.timeScale().fitContent();
  volumeChart.timeScale().fitContent();
  // Ricalcola l'affollamento dopo zoom e scorrimento: l'autoscale
  // può modificare le distanze in pixel senza alterare i prezzi.
  chart.timeScale().subscribeVisibleLogicalRangeChange(scheduleAxisLabels);
  scheduleAxisLabels();
  let syncing=false;
  function sync(source,dest){
    source.timeScale().subscribeVisibleLogicalRangeChange(r=>{
      if(syncing || !r)return; syncing=true;
      try{dest.timeScale().setVisibleLogicalRange(r)}finally{syncing=false}
    });
  }
  sync(chart,volumeChart);sync(volumeChart,chart);
  // Timeframe buttons navigate to independent Kraken OHLC series.
  // Pan and zoom remain native gestures of the chart.
  function formatVolume(value){
    if(value === 0) return '0';
    const result=new Intl.NumberFormat('it-IT',{maximumSignificantDigits:12}).format(value);
    // Preserve a small positive value even on runtimes with coarse ICU output.
    return result === '0' && value > 0 ? value.toExponential(8) : result;
  }
  function show(row){
    const time=new Date(row.time*1000).toLocaleString('it-IT',{timeZone:'UTC'});
    stats.textContent=time+' UTC · O '+priceText.format(row.open)+' · H '+priceText.format(row.high)+
     ' · L '+priceText.format(row.low)+' · C '+priceText.format(row.close)+
     ' '+quote+' · Vol '+formatVolume(row.volume)+' '+__TOKEN_JS__;
  }
  show(rows[rows.length-1]);
  const byTime=new Map(rows.map(v=>[v.time,v]));
  chart.subscribeCrosshairMove(p=>{
    if(p.time && byTime.has(p.time))show(byTime.get(p.time));
  });
  const observer=new ResizeObserver(()=>{
    chart.applyOptions({width:document.getElementById('price-plot').clientWidth});
    volumeChart.applyOptions({width:document.getElementById('volume-plot').clientWidth});
    scheduleAxisLabels();
  });
  observer.observe(document.getElementById('price-plot'));
  msg.textContent='Grafico generato: '+rows.length+' candele '+timeframeLabel+' reali + volumi. Scorri e ingrandisci.';
}catch(e){
  msg.classList.add('error');
  msg.textContent='Errore di visualizzazione: '+e.message+
    '. Dati preservati, nessun ordine eseguito.';
}
})();
</script>
</body>
</html>"""
    template = (template.replace("SUI/EUR", "__PAIR__")
                .replace("(SUI)", "(__TOKEN__)")
                .replace("/analisi/sui-mtf", "__COMPARE_URL__")
                .replace("cinque decimali", "__DECIMALS__ decimali")
                .replace("5 decimali", "__DECIMALS__ decimali"))
    return (template.replace("__BARS__", candle_json)
             .replace("__FRESH_VALID__", "true" if temporal_valid else "false")
             .replace("__LAST_CLOSED_MS__",
                      str(x["candles"][-1]["time"] * 1000 + interval * 1000))
             .replace("__OBSERVED_MS__",
                      str(round(timing["observed"] * 1000)) if temporal_valid else "0")
             .replace("__INTERVAL_MS__", str(interval * 1000))
             .replace("__HOME_URL__", html.escape(home_url, quote=True))
             .replace("__FRESHNESS__", freshness_text)
             .replace("__FRESH_CLASS__", "current" if fresh_state == "AGGIORNATO" else "warning")
            .replace("__TECHNICAL__", technical_json)
            .replace("__OBSERVED__", observed).replace("__CLOSED__", closed)
            .replace("__NOTICE__", html.escape(notice))
            .replace("__TIMEFRAME_BUTTONS__", links)
            .replace("__TF__", html.escape(frame))
            .replace("__PAIR__", pair).replace("__TOKEN__", html.escape(token))
            .replace("__TOKEN_JS__", token_js)
            .replace("__QUOTE_JS__", quote_js)
            .replace("__COMPARE_URL__", html.escape(comparison_url, quote=True))
            .replace("__PRECISION__", str(decimal_places))
            .replace("__MIN_MOVE__", f"{min_move:.{decimal_places}f}")
            .replace("__DECIMALS__", str(decimal_places))
            .replace("__SOURCE__", html.escape(x.get("source", "Dossier Kraken KDD"))))
