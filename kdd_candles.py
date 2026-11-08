"""Deterministic, closed-bar KDD-11 observations; no trading instructions."""
from __future__ import annotations
import datetime as dt
import math
import statistics

VERSION = "kdd11-candle-v002"
FRAMES = {"15m": 900, "1H": 3600, "4H": 14400, "1D": 86400}


def recognize(data, *, now=None, _history=False):
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
    def add(kind, condition, invalidation, *, event_time=None, event_index=None,
            level=None, phases=None):
        # Shape is independent from interpretation. Context can contradict a
        # geometric figure, and a closed future candle is required to resolve it.
        direction = ("RIALZISTA" if kind in ("HAMMER_PIN_BAR", "POSSIBILE_MORNING_STAR",
                      "FALSA_ROTTURA_INFERIORE", "RETEST_DOPO_BREAKOUT", "DOPPIO_TEST_LIVELLO")
                     else "RIBASSISTA" if kind in ("SHOOTING_STAR", "FALSA_ROTTURA_SUPERIORE")
                     else "NEUTRA")
        near = (support is not None and abs(c-support)/support <= .01
                if direction == "RIALZISTA" else
                resistance is not None and abs(c-resistance)/resistance <= .01
                if direction == "RIBASSISTA" else None)
        aligned = (trend == "DISCESA" if direction == "RIALZISTA"
                   else trend == "SALITA" if direction == "RIBASSISTA" else None)
        conflicts = []
        if direction != "NEUTRA" and not near:
            conflicts.append("NESSUN_LIVELLO_STRUTTURALE_VICINO_ENTRO_1_PERCENTO")
        if direction != "NEUTRA" and not aligned:
            conflicts.append("TREND_ANTECEDENTE_NON_COERENTE_CON_IPOTESI_INVERSIONE")
        if ratio is None:
            conflicts.append("VOLUME_RELATIVO_NON_VALUTABILE")
        elif ratio < 1:
            conflicts.append("VOLUME_INFERIORE_ALLA_MEDIA20")
        index = len(bars)-1 if event_index is None else event_index
        event = {"figura": kind, "forma_osservata": condition,
                 "stato": "IN_ATTESA_CONFERMA",
                 "evento_chiusura_utc": event_time or closed,
                 "criterio": condition, "invalidazione": invalidation,
                 "contesto": {"trend_antecedente": trend,
                             "direzione_ipotesi": direction,
                             "presso_livello_strutturale_1pct": near,
                             "volume_vs_media20": ratio,
                             "ema20": ema20, "ema50": ema50,
                             "supporto": support, "resistenza": resistance},
                 "conflitti": conflicts,
                 "conferme_mancanti": ["CHIUSURA_SUCCESSIVA_COERENTE"],
                 "fasi_utc": phases or [event_time or closed]}
        if level is not None:
            event["livello_testato"] = level
        # Follow only CLOSED candles strictly after the event. No future input
        # enters detection at the event's own timestamp.
        for later in bars[index+1:]:
            if kind in ("HAMMER_PIN_BAR", "DOPPIO_TEST_LIVELLO", "RETEST_DOPO_BREAKOUT",
                        "FALSA_ROTTURA_INFERIORE", "POSSIBILE_MORNING_STAR"):
                invalid = later["close"] < (level if level is not None else bars[index]["low"])
                reaction = later["close"] > bars[index]["high"]
            elif kind in ("SHOOTING_STAR", "FALSA_ROTTURA_SUPERIORE"):
                invalid = later["close"] > (level if level is not None else bars[index]["high"])
                reaction = later["close"] < bars[index]["low"]
            else:
                invalid = False
                reaction = False
            if invalid or reaction:
                event["stato"] = "INVALIDATA" if invalid else "REAZIONE_CHIUSA_OSSERVATA"
                event["risoluzione_utc"] = dt.datetime.fromtimestamp(
                    later["time"]+seconds, dt.timezone.utc).isoformat(timespec="seconds")
                event["conferme_mancanti"] = [] if reaction else ["IPOTESI_INVALIDATA"]
                break
        figures.append(event)
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
        if (level*.997 <= l <= level*1.003 and c >= level
                and all(x["close"] >= level for x in bars[j+1:])):
            add("RETEST_DOPO_BREAKOUT", "breakout precedente e test entro 0.3% su candela distinta",
                "Chiusura sotto livello del breakout", level=level,
                phases=[dt.datetime.fromtimestamp(breakout["time"]+seconds, dt.timezone.utc).isoformat(timespec="seconds"),
                        closed])
            break
    # A double test is two separate closed lows near a PRIOR level, without a close below it.
    if len(bars)>=27:
        level=min(x["low"] for x in bars[-27:-7])
        touches=[(i,x) for i,x in enumerate(bars[-7:], start=len(bars)-7)
                 if abs(x["low"]-level)/level <= .003 and x["close"] >= level]
        found = None
        for first_idx, first in touches:
            for second_idx, second in touches:
                if second_idx-first_idx < 2:
                    continue
                between = bars[first_idx+1:second_idx]
                # Require a CLOSED rebound >= 0.6%, not repeated sideways wicks.
                if (between and max(x["close"] for x in between) >= level*1.006
                        and all(x["close"] >= level for x in bars[first_idx:second_idx+1])):
                    found = (first_idx, second_idx)
                    break
            if found:
                break
        if found:
            a,b=found
            utc=lambda i: dt.datetime.fromtimestamp(
                bars[i]["time"]+seconds, dt.timezone.utc).isoformat(timespec="seconds")
            add("DOPPIO_TEST_LIVELLO", "due test entro 0.3%, reazione chiusa >= 0.6% tra i test",
                "Chiusura sotto livello", event_time=utc(b), event_index=b,
                level=level, phases=[utc(a),utc(b)])
    if not _history:
        # Historical shapes are detected at their own close, then resolved
        # using only subsequent closed bars, never the other way around.
        for index in range(max(50, len(bars)-5), len(bars)-1):
            prefix = bars[:index+1]
            event_end = dt.datetime.fromtimestamp(
                prefix[-1]["time"]+seconds, dt.timezone.utc).isoformat(timespec="seconds")
            earlier = recognize(dict(data, candles=prefix,
                closed_at_utc=event_end, observed_utc=event_end),
                now=dt.datetime.fromisoformat(event_end), _history=True)
            for old in earlier["figure"]:
                if old["figura"] not in ("HAMMER_PIN_BAR", "SHOOTING_STAR",
                                        "POSSIBILE_MORNING_STAR", "FALSA_ROTTURA_INFERIORE",
                                        "FALSA_ROTTURA_SUPERIORE"):
                    continue
                event = dict(old)
                for later in bars[index+1:]:
                    bullish = old["figura"] in ("HAMMER_PIN_BAR", "POSSIBILE_MORNING_STAR",
                                                 "FALSA_ROTTURA_INFERIORE")
                    invalid = (later["close"] < prefix[-1]["low"] if bullish
                               else later["close"] > prefix[-1]["high"])
                    reaction = (later["close"] > prefix[-1]["high"] if bullish
                                else later["close"] < prefix[-1]["low"])
                    if invalid or reaction:
                        event["stato"] = "INVALIDATA" if invalid else "REAZIONE_CHIUSA_OSSERVATA"
                        event["risoluzione_utc"] = dt.datetime.fromtimestamp(
                            later["time"]+seconds, dt.timezone.utc).isoformat(timespec="seconds")
                        event["conferme_mancanti"] = [] if reaction else ["IPOTESI_INVALIDATA"]
                        break
                figures.append(event)
    return {"schema": VERSION, "stato": "AGGIORNATO" if timing["fresh"] else "SCADUTO",
            "timeframe": label, "coppia": data.get("pair"), "pair_key": data.get("pair_key"),
            "chiusura_utc": closed, "rilevazione_utc": data["observed_utc"],
            "fonte": data.get("source", "Kraken Spot OHLC"),
            "barre": len(bars), "trend_precedente": trend,
            "volume_vs_media20": ratio, "ema20": ema20, "ema50": ema50,
            "supporto_precedente": support, "resistenza_precedente": resistance,
            "figure": figures[-8:], "limite": "Configurazioni descrittive; conferma successiva non presunta"}


def compare_context(frames):
    """Describe disagreements across closed frames; never a trading verdict."""
    directions = {}
    for label in FRAMES:
        frame = frames.get(label, {})
        evidence = frame.get("figure_candlestick") or {}
        if evidence.get("stato") not in ("AGGIORNATO", "SCADUTO"):
            directions[label] = "NON_DISPONIBILE"
            continue
        directions[label] = evidence.get("trend_precedente", "NON_DISPONIBILE")
    higher = [directions[k] for k in ("4H", "1D") if directions[k] in ("SALITA", "DISCESA")]
    lower = [directions[k] for k in ("15m", "1H") if directions[k] in ("SALITA", "DISCESA")]
    conflict = bool(higher and lower and any(a != b for a in higher for b in lower))
    return {"schema": VERSION, "trend_per_timeframe": directions,
            "contraddizione_alto_basso": conflict,
            "limite": "Chiusure a orari diversi; confronto descrittivo"}
