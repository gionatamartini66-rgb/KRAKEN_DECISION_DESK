"""Public Binance SPOT market reference for KDD. NO account, API key, private trades or futures.
Compare token base-volume over explicit pair subsets, never confuse venue liquidity
with Kraken execution price, and never claim a cross-exchange arbitrage.
"""
from __future__ import annotations
import datetime as dt
import json
import math
import urllib.parse
import urllib.request

BASE = "https://data-api.binance.vision/api/v3/"
QUOTES = ("USDC", "USDT")
KRAKEN_QUOTES = {"EUR", "USD", "USDC"}
ALIAS = {"XBT": "BTC", "XXBT": "BTC"}

def positive(value):
    v = float(value)
    if not math.isfinite(v) or v < 0:
        raise ValueError("Numerical market-data value not valid")
    return v

def api(endpoint, **params):
    if endpoint not in {"exchangeInfo", "ticker/24hr", "depth"}:
        raise ValueError("Only approved public Binance SPOT data endpoints")
    url = BASE + endpoint
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent":"KrakenDecisionDesk-public-Binance-reference/1.0",
        "Accept":"application/json"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.load(r)

def kraken_24h_base_volumes(pairs, tickers, tokens):
    result = {tok:{} for tok in tokens}
    for key,meta in pairs.items():
        if meta.get("status") != "online":
            continue
        name = meta.get("wsname","")
        if name.count("/") != 1:
            continue
        base,quote = name.split("/")
        base = ALIAS.get(base,base)
        if base not in result or quote not in KRAKEN_QUOTES or ".d" in key.lower():
            continue
        ticker = tickers.get(key) or {}
        vol = ticker.get("v") or []
        if len(vol) < 2:
            continue
        try:
            qty = positive(vol[1])
        except (ValueError,TypeError):
            continue
        result[base][quote] = {"pair":name, "base_qty_24h":qty}
    return result

def parse_ticker(x):
    bid = positive(x["bidPrice"])
    ask = positive(x["askPrice"])
    last = positive(x["lastPrice"])
    volbase = positive(x["volume"])
    volquote = positive(x["quoteVolume"])
    move = float(x["priceChangePercent"])
    if not math.isfinite(move) or not 0 < bid <= ask or last <= 0:
        raise ValueError("Ticker malformed")
    return {"pair": x["symbol"], "base_qty_24h":volbase,
            "quote_qty_24h":volquote,"last":last,"bid":bid,"ask":ask,
            "spread_pct":100*(ask-bid)/((ask+bid)/2),
            "change_24h_pct":move}

def collect(tokens, pairs_kraken, ticker_kraken, *, shortlist=()):
    """Market data 24h rolling; Binance USDC + USDT vs Kraken EUR + USD + USDC.
    The different quote-currency coverage is explicitly disclosed in each result.
    """
    tokens = list(dict.fromkeys(t.upper() for t in tokens if t and t.isalnum()))[:20]
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    info = api("exchangeInfo")
    permitted = {x["symbol"] for x in info.get("symbols",[])
                 if x.get("status") == "TRADING" and x.get("isSpotTradingAllowed",True)}
    symbols = [t + q for t in tokens for q in QUOTES if t+q in permitted]
    if not symbols:
        return {"status":"NO_PAIR", "observed_utc":now, "tokens":[],
                "note":"Nessuna coppia Binance nei due quote indicati"}
    tick = api("ticker/24hr", symbols=json.dumps(symbols,separators=(",",":")))
    if not isinstance(tick,list):
        raise ValueError("Binance bulk ticker unexpected schema")
    ticker_by_symbol = {x["symbol"]:parse_ticker(x) for x in tick
                        if isinstance(x,dict) and x.get("symbol") in symbols}
    kraken = kraken_24h_base_volumes(pairs_kraken, ticker_kraken, tokens)
    result = []
    for tok in tokens:
        rows = [dict(ticker_by_symbol[tok+q],quote=q)
                for q in QUOTES if tok+q in ticker_by_symbol]
        if not rows:
            result.append({"token":tok,"status":"NOT_LISTED_FOR_QUOTE","binance_pairs":[]})
            continue
        bk_base = sum(row["base_qty_24h"] for row in rows)
        kr_base = sum(row["base_qty_24h"] for row in kraken.get(tok,{}).values())
        # Volume in TOKEN units is quote-independent; still compare only stated
        # subsets (USDC/USDT versus EUR/USD/USDC), not global venue totals.
        ratio = bk_base / kr_base if kr_base > 0 else None
        result.append({"token":tok,"status":"OK",
                       "binance_pairs":rows,
                       "binance_base_volume_24h_subset":bk_base,
                       "kraken_pairs":kraken.get(tok,{}),
                       "kraken_base_volume_24h_subset":kr_base,
                       "volume_ratio_subsets":round(ratio,2) if ratio is not None else None,
                       "coverage_warning":(
                          "Solo Binance spot USDC+USDT contro Kraken spot EUR+USD+USDC;"
                          " volume su asset base, non quota USD; NON sono volumi totali"
                          " dell'exchange e NON implicano equivalenza di liquidità/fee/mercato.")})
    shortlisted = {t.upper() for t in shortlist}
    # Price-book views for top 4 meaningful candidates; choose MOST TRADED
    # Binance market, never assume USDT equals USDC for Kraken execution.
    done = 0
    for record in result:
        if record["token"] not in shortlisted or not record.get("binance_pairs") or done >= 4:
            continue
        choice = max(record["binance_pairs"],key=lambda x:x["base_qty_24h"])
        done += 1
        try:
            book = api("depth",symbol=choice["pair"],limit=10)
            bids = book.get("bids",[])
            asks = book.get("asks",[])
            bsum = sum(positive(q) for _,q in bids[:10])
            asum = sum(positive(q) for _,q in asks[:10])
            record["binance_top10_book"] = {
                "pair":choice["pair"],"bid_qty_base":bsum,
                "ask_qty_base":asum,
                "imbalance_10levels":round((bsum-asum)/(bsum+asum),3)
                      if bsum+asum>0 else None,
                "warning":"Book istantaneo soggetto a cancellazioni/spoofing;"
                          " non è delta ordini eseguiti né segnale direzionale."}
        except Exception as exc:
            record["book_error"] = type(exc).__name__
    return {"status":"OK","source":"Binance SPOT market-data-only, NO authentication",
            "observed_utc":dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "tokens":result, "scope":"USDC+USDT Binance SPOT vs EUR+USD+USDC Kraken SPOT",
            "coverage_warning":("Volume 24h di sole coppie esaminate, non market share."
                                " Quote USDT, USDC, USD, EUR non sono equivalenti"
                                " ai fini del prezzo. Kraken resta mercato di esecuzione;"
                                " Binance è indicatore di volume/price discovery.")}

if __name__=="__main__":
    print("Importare questo modulo tramite decision_desk.py aggiorna: API pubbliche Binance Spot.")
