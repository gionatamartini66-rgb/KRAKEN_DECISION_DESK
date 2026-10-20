"""Kraken Decision Desk V0.2: schede tecniche limitate, dati pubblici.
Nessun ordine; filtri di ricerca, non previsione di rendimento.
"""
import datetime as dt


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _change(current, reference):
    return 100 * (current / reference - 1) if reference > 0 else None


def choose(markets, scanner, max_items=3):
    """Campione intenzionalmente vario: gainer liquido, primo movimento, caso fragile."""
    lo = _number(scanner.get("min_var_oggi_utc_pct", 8))
    hi = _number(scanner.get("max_var_oggi_utc_pct", 20))
    min_eur = _number(scanner.get("volume_24h_min_eur", 500000))
    max_spread = _number(scanner.get("spread_massimo_pct", 0.8))
    out = []
    used = set()

    def acceptable(row):
        return (row["volume_24h_eur_stimato"] >= min_eur and
                row["spread_pct"] <= max_spread)

    def append_first(options, label):
        for row in options:
            if row["token"] not in used:
                out.append({"token": row["token"], "categoria": label,
                            "pair_key": row["pair_key"]})
                used.add(row["token"])
                return

    allrows = [r for r in markets.values()
               if r.get("var_oggi_utc_pct") is not None
               and r.get("prezzo_eur", 0) > 0]
    gainers = [r for r in allrows if lo <= r["var_oggi_utc_pct"] <= hi]
    early = [r for r in allrows if 2 <= r["var_oggi_utc_pct"] < lo]
    append_first(sorted((r for r in gainers if acceptable(r)),
                        key=lambda r: -r["volume_24h_eur_stimato"]), "Gainer liquido")
    append_first(sorted((r for r in early if acceptable(r)),
                        key=lambda r: (-r["var_oggi_utc_pct"], -r["volume_24h_eur_stimato"])),
                 "Primo movimento (2–8%, non previsione)")
    append_first(sorted((r for r in gainers if not acceptable(r)),
                        key=lambda r: -r["volume_24h_eur_stimato"]),
                 "Gainer fragile · confronto")
    if len(out) < max_items:
        append_first(sorted((r for r in early if not acceptable(r)),
                            key=lambda r: -r["volume_24h_eur_stimato"]),
                     "Primo movimento fragile · confronto")
    if len(out) < max_items:
        append_first(sorted((r for r in early if acceptable(r)),
                            key=lambda r: -r["volume_24h_eur_stimato"]),
                     "Altro primo movimento")
    return out[:max_items]


def closed_bars(raw, now=None, interval_sec=3600):
    """Kraken comprende la candela in formazione; controllare timestamp."""
    now = now or dt.datetime.now(dt.timezone.utc).timestamp()
    rows = [r for r in raw if len(r) >= 7 and _number(r[4]) > 0]
    # Non fidarsi della posizione: esclude tutte le candele non ancora chiuse.
    return [r for r in rows if _number(r[0]) + interval_sec <= now]


def momentum(hourly, fifteen, btc_hourly, now=None):
    hour = closed_bars(hourly, now, 3600)
    quarter = closed_bars(fifteen, now, 900)
    btc = closed_bars(btc_hourly, now, 3600)
    if min(len(hour), len(btc)) < 9 or len(quarter) < 5:
        raise ValueError("Candele chiuse insufficienti")
    close = lambda row: _number(row[4])
    hour_1 = _change(close(hour[-1]), close(hour[-2]))
    hour_4 = _change(close(hour[-1]), close(hour[-5]))
    btc_4 = _change(close(btc[-1]), close(btc[-5]))
    quarter_1h = _change(close(quarter[-1]), close(quarter[-5]))
    last4 = sum(_number(r[6]) for r in hour[-4:])
    before4 = sum(_number(r[6]) for r in hour[-8:-4])
    return {
        "chiusura_oraria_utc": dt.datetime.fromtimestamp(_number(hour[-1][0]) + 3600,
                                                          tz=dt.timezone.utc).isoformat(),
        "var_1h_pct": hour_1,
        "var_4h_pct": hour_4,
        "var_1h_su_15m_pct": quarter_1h,
        "btc_4h_pct": btc_4,
        "forza_relativa_4h_punti": hour_4 - btc_4,
        "rapporto_volumi_4h": last4 / before4 if before4 > 0 else None,
    }


def book_metrics(depth, eur_per_quote=1.0):
    bids = depth.get("bids", [])[:10]
    asks = depth.get("asks", [])[:10]
    if not bids or not asks:
        raise ValueError("Book privo di bid o ask")
    bid, ask = _number(bids[0][0]), _number(asks[0][0])
    if not (0 < bid <= ask):
        raise ValueError("Book incoerente")
    if eur_per_quote <= 0:
        raise ValueError("Cambio EUR della coppia assente")
    bv = sum(_number(p) * _number(q) for p, q, *_ in bids) * eur_per_quote
    av = sum(_number(p) * _number(q) for p, q, *_ in asks) * eur_per_quote
    return {
        "spread_book_pct": _change(ask, (ask + bid) / 2) * 2,
        "profondita_bid10_eur": bv, "profondita_ask10_eur": av,
        "imbalance10": (bv - av) / (bv + av) if bv + av else None
    }


def evaluate(row, cat, features=None, book=None, error=None, config=None):
    """Esito informativo condizionale. Non è un ordine né una probabilità."""
    cfg = config or {}
    min_eur = _number(cfg.get("volume_24h_min_eur", 500000))
    max_spread = _number(cfg.get("spread_massimo_pct", 0.8))
    issues = []
    evidence = []
    if row["volume_24h_eur_stimato"] < min_eur:
        issues.append("Volume 24h stimato della coppia selezionata sotto il filtro di ricerca")
    if row["spread_pct"] > max_spread:
        issues.append("Spread del ticker elevato")
    if error or features is None or book is None:
        issues.append("Analisi multi-timeframe/book incompleta: " + (error or "dati assenti"))
        return dict(token=row["token"], categoria=cat, esito="DATI INSUFFICIENTI",
                    sintesi="Ripetere la rilevazione prima di una valutazione operativa.",
                    criticita=issues, evidenze=evidence, indicatori=features, book=book,
                    prezzo_eur=row["prezzo_eur"], variazione_oggi=row["var_oggi_utc_pct"],
                    coppia_analisi=row.get("pair"), valuta_quotazione=row.get("quote", "EUR"),
                    alternative=row.get("alternative", []),
                    volume_token_kraken_eur_stimato=row.get("volume_token_kraken_eur_stimato"),
                    volume_coppia_eur_stimato=row["volume_24h_eur_stimato"])
    if book["spread_book_pct"] > max_spread:
        issues.append("Spread istantaneo del book elevato")
    if min(book["profondita_bid10_eur"], book["profondita_ask10_eur"]) < 3000:
        issues.append("Profondità ai primi 10 livelli limitata")
    if features["var_4h_pct"] > 0 and features["forza_relativa_4h_punti"] > 0:
        evidence.append("Nelle ultime quattro ore chiuse è più forte di BTC")
    else:
        issues.append("Nelle ultime quattro ore non mostra forza relativa positiva su BTC")
    ratio = features["rapporto_volumi_4h"]
    if ratio is None:
        issues.append("Confronto volumi 4h non disponibile")
    elif ratio >= 1.2:
        evidence.append("Volumi delle ultime 4h superiori alle 4h precedenti")
    else:
        issues.append("Volumi 4h senza accelerazione marcata rispetto alle precedenti")
    if features["var_1h_pct"] > 0 and features["var_1h_su_15m_pct"] > 0:
        evidence.append("Impulso positivo su candele orarie e da 15 minuti chiuse")
    else:
        issues.append("Impulso breve non concorde fra scale temporali")
    bad_liquidity = (row["volume_24h_eur_stimato"] < min_eur or
                     max(row["spread_pct"], book["spread_book_pct"]) > max_spread or
                     min(book["profondita_bid10_eur"], book["profondita_ask10_eur"]) < 3000)
    if bad_liquidity:
        status = "MOVIMENTO FRAGILE"
        summary = "Possibili costi/slippage rilevanti: prima di considerare un ordine verificare book e disponibilità spot."
    elif len(evidence) == 3:
        status = "SETUP DA ESAMINARE ORA"
        summary = "Convergenza tecnica da verificare sul grafico e nelle notizie del token; valutare un piano di ingresso/uscita, senza ordine automatico."
    else:
        status = "RIESAME MIRATO"
        summary = "Controllare se volume, forza relativa e impulso migliorano nelle prossime candele chiuse."
    return dict(token=row["token"], categoria=cat, esito=status, sintesi=summary,
                criticita=issues, evidenze=evidence, indicatori=features, book=book,
                prezzo_eur=row["prezzo_eur"], variazione_oggi=row["var_oggi_utc_pct"],
                coppia_analisi=row.get("pair"), valuta_quotazione=row.get("quote", "EUR"),
                alternative=row.get("alternative", []),
                volume_token_kraken_eur_stimato=row.get("volume_token_kraken_eur_stimato"),
                volume_coppia_eur_stimato=row["volume_24h_eur_stimato"])
