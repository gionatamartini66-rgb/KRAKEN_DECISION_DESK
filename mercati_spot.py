"""Osservazione multi-coppia spot Kraken: EUR, USD, USDC soltanto.

Raggruppa mercati dello stesso token, mantenendo distinti:
- volume aggregato su Kraken nelle quote incluse, solo per scoperta;
- volume/spread della coppia specifica per l'operatività;
- conversione indicativa di USD/USDC in EUR a prezzi mid pubblici.
Non verifica la negoziabilità sul conto dell'utente e non calcola fee reali.
"""
from collections import defaultdict

QUOTES = {"EUR", "USD", "USDC"}
EXCLUDE_BASE = {
    "EUR", "USD", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SGD",
    "USDC", "USDT", "EURC", "DAI", "RLUSD", "PYUSD", "ZCHF",
    "EUROP", "USDG", "EURQ", "USD1", "USDE",
    # L'area di ricerca e' il mercato crypto, non esposizione al prezzo dell'oro.
    # Prodotti tokenizzati gold/commodities restano fuori dal radar spot.
    "PAXG", "XAUT",
}
ALIASES = {"XBT": "BTC", "XXBT": "BTC", "XDG": "DOGE"}


def num(value):
    try:
        n = float(value)
        return n if n > 0 and n < float("inf") else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def ticker_mid(ticker):
    if not ticker:
        return None
    bid = num((ticker.get("b") or [0])[0])
    ask = num((ticker.get("a") or [0])[0])
    return (bid + ask) / 2 if 0 < bid <= ask else None


def eur_per_quote(pairs, tickers):
    """Richiediamo cambi diretti Kraken; niente ipotesi di parità per USDC."""
    rates = {"EUR": {"eur": 1.0, "source": "EUR"}}
    for key, meta in pairs.items():
        if meta.get("status") != "online":
            continue
        w = meta.get("wsname", "")
        ticker = tickers.get(key)
        mid = ticker_mid(ticker)
        if not mid:
            continue
        if w == "EUR/USD":
            rates["USD"] = {"eur": 1.0 / mid, "source": w}
        elif w == "USD/EUR":
            rates["USD"] = {"eur": mid, "source": w}
        elif w == "USDC/EUR":
            rates["USDC"] = {"eur": mid, "source": w}
        elif w == "EUR/USDC":
            rates["USDC"] = {"eur": 1.0 / mid, "source": w}
    return rates


def assemble(pairs, tickers, min_vol=500000, max_spread=0.8):
    """Ritorna token→riga osservata e tassi. Somma solo coppie spot distinte."""
    rates = eur_per_quote(pairs, tickers)
    groups = defaultdict(list)
    for key, meta in pairs.items():
        if meta.get("status") != "online" or ".d" in key.lower():
            continue
        name = meta.get("wsname", "")
        if name.count("/") != 1:
            continue
        base, quote = name.split("/")
        base = ALIASES.get(base.upper(), base.upper())
        if quote not in QUOTES or base in EXCLUDE_BASE or base == quote:
            continue
        rate = rates.get(quote)
        t = tickers.get(key)
        if not rate or not t:
            continue  # Se manca il cambio o ticker, mai utilizzare conversioni ipotetiche.
        price = num((t.get("c") or [0])[0])
        opening = num(t.get("o"))
        ask = num((t.get("a") or [0])[0])
        bid = num((t.get("b") or [0])[0])
        if not min(price, opening, ask, bid) or ask < bid:
            continue
        mid = (ask + bid) / 2
        spread = 100 * (ask - bid) / mid
        volume_base_24h = num((t.get("v") or [0, 0])[-1])
        volume_eur = price * volume_base_24h * rate["eur"]
        groups[base].append({
            "token": base, "pair": name, "pair_key": key,
            "quote": quote, "prezzo_quote": price,
            "prezzo_eur": price * rate["eur"],
            "eur_per_quote": rate["eur"], "conversione_fonte": rate["source"],
            "var_oggi_utc_pct": 100 * (price / opening - 1),
            "volume_24h_eur_stimato": volume_eur,
            "spread_pct": spread,
            "costo_min_quote": num(meta.get("costmin")),
            "quantita_min": num(meta.get("ordermin")),
        })
    result = {}
    for token, options in groups.items():
        # Scelta coppia di ANALISI: privilegia liquidità singola coppia e spread,
        # non una 'migliore esecuzione' (mancano saldi, fee e slippage per importo).
        good = [p for p in options if p["spread_pct"] <= max_spread]
        ranked = sorted(good or options,
                        key=lambda p: (-p["volume_24h_eur_stimato"], p["spread_pct"]))
        primary = ranked[0]
        eur_option = next((p for p in options if p["quote"] == "EUR"), None)
        if (eur_option is not None and primary["quote"] != "EUR"
                and eur_option["spread_pct"] <= max_spread
                and eur_option["spread_pct"] <= primary["spread_pct"] + 0.10
                and eur_option["volume_24h_eur_stimato"] >= 0.75 * primary["volume_24h_eur_stimato"]
                and eur_option["volume_24h_eur_stimato"] >= min_vol):
            primary = eur_option
        ordered = sorted(options, key=lambda p: -p["volume_24h_eur_stimato"])
        x = dict(primary)
        x["volume_token_kraken_eur_stimato"] = sum(p["volume_24h_eur_stimato"] for p in options)
        x["n_coppie"] = len(options)
        x["alternative"] = [
            {"pair": p["pair"], "quote": p["quote"],
             "volume_eur_stimato": p["volume_24h_eur_stimato"],
             "spread_pct": p["spread_pct"], "prezzo_quote": p["prezzo_quote"],
             "eur_per_quote": p["eur_per_quote"],
             "pair_key": p["pair_key"]}
            for p in ordered
        ]
        result[token] = x
    return result, rates
