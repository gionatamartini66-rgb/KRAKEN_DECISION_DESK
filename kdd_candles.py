"""Deterministic, closed-bar KDD-11 observations; no trading instructions."""
from __future__ import annotations
import datetime as dt
import math
import statistics

VERSION = "kdd11-candle-v001"
FRAMES = {"15m": 900, "1H": 3600, "4H": 14400, "1D": 86400}


def recognize(data, *, now=None):
    """Recompute from OHLCV; every event uses only bars available at its close."""
    import grafico_4h as charts
    now = now or dt.datetime.now(dt.timezone.utc)
    label = data["timeframe"]
    seconds = FRAMES[label]
    bars = data["candles"]
    if len(bars) < 50 or len(bars) > 200:
        return {"schema": VERSION, "stato": "STORICO_INSUFFICIENTE",
                "timeframe": label, "figure": [], "barre": len(bars)}
    timing = charts.temporal_consistency(data, now=now)
    previous = None
    for b in bars:
        t = b.get("time")
        vals = [b.get(k) for k in ("open", "high", "low", "close", "volume")]
        if (type(t) is not int or t % seconds
                or (previous is not None and t-previous != seconds)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in vals)
                or not (0 < vals[2] <= min(vals[0], vals[3]) <=
                        max(vals[0], vals[3]) <= vals[1] and vals[4] >= 0)):
            raise ValueError("Serie OHLCV discontinua o non verificabile")
        previous = t
    last = bars[-1]
    prev = bars[-2]
    o, h, l, c = (last[k] for k in ("open", "high", "low", "close"))
    spread = h-l
    body = abs(c-o)
    upper = h-max(o,c)
    lower = min(o,c)-l
    prior_volumes = [x["volume"] for x in bars[-21:-1]]
    avg = statistics.mean(prior_volumes)
    ratio = round(last["volume"]/avg, 4) if avg > 0 else None
    closes = [x["close"] for x in bars]
    prior_move = (closes[-2]-closes[-7])/closes[-7]
    trend = "SALITA" if prior_move > .008 else "DISCESA" if prior_move < -.008 else "LATERALE"
    levels = charts.structural_levels(bars[:-1])
    support = (levels.get("supports") or [{}])[0].get("price")
    resistance = (levels.get("resistances") or [{}])[0].get("price")
    ema20 = charts.ema_points(bars, 20)[-1]["value"]
    ema50 = charts.ema_points(bars, 50)[-1]["value"]
    figures = []
    closed = dt.datetime.fromtimestamp(last["time"]+seconds, dt.timezone.utc).isoformat(timespec="seconds")
    def add(kind, condition, invalidation, *, event_time=None):
        figures.append({"figura": kind, "stato": "IN_ATTESA_CONFERMA",
                        "evento_chiusura_utc": event_time or closed,
                        "criterio": condition, "invalidazione": invalidation})
    if spread > 0:
        if body/spread <= .1:
            add("DOJI", "corpo/range <= 0.10", "Chiusura successiva oltre l'estremo opposto")
        if lower/spread >= .55 and upper/spread <= .18 and body/spread <= .35:
            add("HAMMER_PIN_BAR", "ombra inferiore/range >= 0.55", "Chiusura successiva sotto minimo")
        if upper/spread >= .55 and lower/spread <= .18 and body/spread <= .35:
            add("SHOOTING_STAR", "ombra superiore/range >= 0.55", "Chiusura successiva sopra massimo")
        if ((c-o)*(prev["close"]-prev["open"]) < 0 and
                min(o,c) <= min(prev["open"],prev["close"]) and
                max(o,c) >= max(prev["open"],prev["close"])):
            add("ENGULFING", "corpo attuale include corpo precedente, verso opposto",
                "Chiusura successiva oltre estremo opposto")
        ranges = [x["high"]-x["low"] for x in bars[-21:-1]]
        median = statistics.median(ranges)
        if median > 0 and spread >= 1.8*median:
            add("ESPANSIONE", "range >= 1.8 volte mediana precedente", "Rientro nel range precedente")
        if median > 0 and spread <= .5*median:
            add("COMPRESSIONE", "range <= 0.5 volte mediana precedente", "Espansione successiva")
        a,b=bars[-3],bars[-2]
        if (a["close"]<a["open"] and abs(b["close"]-b["open"])<=.35*(b["high"]-b["low"])
                and c>o and c>(a["open"]+a["close"])/2):
            add("POSSIBILE_MORNING_STAR", "ribasso, corpo piccolo, recupero sopra meta prima candela",
                "Chiusura sotto minimo della sequenza")
    # Level events use the PREVIOUS 20 bars, never the current bar to define the level.
    prior20=bars[-21:-1]
    hi=max(x["high"] for x in prior20)
    lo=min(x["low"] for x in prior20)
    if c > hi and prev["close"] <= hi:
        add("BREAKOUT_DA_VERIFICARE", "chiusura oltre massimo 20 barre precedenti",
            "Chiusura sotto livello superato")
    if c < lo and prev["close"] >= lo:
        add("ROTTURA_RIBASSISTA_DA_VERIFICARE", "chiusura sotto minimo 20 barre precedenti",
            "Chiusura sopra livello violato")
    if h > hi and c <= hi:
        add("FALSA_ROTTURA_SUPERIORE", "massimo oltre livello e chiusura rientrata",
            "Nuova chiusura sopra livello")
    if l < lo and c >= lo:
        add("FALSA_ROTTURA_INFERIORE", "minimo sotto livello e chiusura rientrata",
            "Nuova chiusura sotto livello")
    # A retest needs an earlier closed breakout, followed by a distinct closed bar.
    for j in range(max(21,len(bars)-6),len(bars)-1):
        prior=bars[j-20:j]
        level=max(x["high"] for x in prior)
        breakout=bars[j]
        if breakout["close"] <= level:
            continue
        if l <= level*1.003 and c >= level and last["time"] > breakout["time"]:
            add("RETEST_DOPO_BREAKOUT", "breakout precedente e test del livello su candela distinta",
                "Chiusura sotto livello del breakout")
            break
    # A double test is two separate closed lows near a PRIOR level, without a close below it.
    if len(bars)>=27:
        level=min(x["low"] for x in bars[-27:-7])
        touches=[x for x in bars[-7:] if abs(x["low"]-level)/level <= .003
                 and x["close"] >= level]
        if len(touches)>=2 and touches[-1]["time"]-touches[0]["time"]>=seconds*2:
            add("DOPPIO_TEST_LIVELLO", "due minimi separati presso livello precedente, senza rottura chiusa",
                "Chiusura sotto livello")
    return {"schema": VERSION, "stato": "AGGIORNATO" if timing["fresh"] else "SCADUTO",
            "timeframe": label, "coppia": data.get("pair"), "pair_key": data.get("pair_key"),
            "chiusura_utc": closed, "rilevazione_utc": data["observed_utc"],
            "fonte": data.get("source", "Kraken Spot OHLC"),
            "barre": len(bars), "trend_precedente": trend,
            "volume_vs_media20": ratio, "ema20": ema20, "ema50": ema50,
            "supporto_precedente": support, "resistenza_precedente": resistance,
            "figure": figures[-8:], "limite": "Configurazioni descrittive; conferma successiva non presunta"}
