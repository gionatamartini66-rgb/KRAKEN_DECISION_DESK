"""Stima spot round-trip: book Kraken pubblico, nessun ordine / saldo account.

Il prezzo del token e il cambio sono tenuti fermi e si simulano due esecuzioni
taker contro gli stessi primi livelli del book. Fee standard LIVELLO 1
modificabili, non personalizzate. Non è un preventivo eseguibile.
"""
import math

FIAT = {"EUR", "USD", "USDC"}


def positive(v):
    try:
        n = float(v)
        return n if math.isfinite(n) and n > 0 else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def execute_book(book, side, input_amount, fee_rate):
    """Restituisce (output al netto fee, commissione nominale nell'asset ricevuto)."""
    if not (0 <= fee_rate < 1) or input_amount <= 0:
        raise ValueError("Importo o commissione non validi")
    entries = book.get("asks" if side == "buy" else "bids", [])
    remaining = input_amount
    gross_out = 0.0
    for row in entries:
        price, available_base = positive(row[0]), positive(row[1])
        if price <= 0 or available_base <= 0:
            continue
        # compra: input = valuta quote; vendi: input = quantità base
        capacity = price * available_base if side == "buy" else available_base
        used = min(capacity, remaining)
        gross_out += used / price if side == "buy" else used * price
        remaining -= used
        if remaining <= 1e-8 * input_amount:
            break
    if remaining > 1e-8 * input_amount:
        raise ValueError("Profondità book insufficiente per la dimensione ipotizzata")
    fee_out = gross_out * fee_rate
    return gross_out - fee_out, fee_out


def execute_passive_conditional(book, side, input_amount, maker_fee):
    """Maker teorico al miglior bid/ask osservato, solo SE tutto l'ordine viene eseguito.

    Il volume sul book è liquidità opposta, non domanda per l'ordine passivo:
    NON è una promessa di esecuzione e NON va comparato a taker come costo garantito.
    """
    if input_amount <= 0 or not (0 <= maker_fee < 1):
        raise ValueError("Importo o fee maker non validi")
    price = positive(book["bids"][0][0] if side == "buy" else book["asks"][0][0])
    if not price:
        raise ValueError("Prezzo maker non disponibile")
    gross_out = input_amount / price if side == "buy" else input_amount * price
    fee = gross_out * maker_fee
    return gross_out - fee, fee


def execute_crypto(book, side, amount, mode, taker_fee, maker_fee):
    if mode == "taker":
        return execute_book(book, side, amount, taker_fee)
    if mode == "maker":
        return execute_passive_conditional(book, side, amount, maker_fee)
    raise ValueError("Modalità ordine non riconosciuta")


def fx_edges(fx_books):
    """fx_books: {'EUR/USD': depth,...}; archi applicano bid/ask REALI."""
    edges = {}
    for pair, book in fx_books.items():
        base, quote = pair.split("/")
        if base not in FIAT or quote not in FIAT:
            continue
        if not book.get("bids") or not book.get("asks"):
            continue
        edges[(base, quote)] = (pair, book, "sell")
        edges[(quote, base)] = (pair, book, "buy")
    return edges


def fx_convert(amount, src, dest, fx_books, fx_fee):
    if src == dest:
        return amount, [], []
    edges = fx_edges(fx_books)
    # un salto diretto, altrimenti due; nessuna conversione presunta senza orderbook
    paths = [[src, dest]]
    for via in sorted(FIAT - {src, dest}):
        paths.append([src, via, dest])
    best = None
    for path in paths:
        value = amount
        steps = []
        fees = []
        try:
            for a, b in zip(path, path[1:]):
                pair, book, side = edges[(a, b)]
                value, fee = execute_book(book, side, value, fx_fee)
                fees.append((b, fee))
                steps.append(pair + " (" + a + "→" + b + ")")
        except (KeyError, ValueError):
            continue
        if best is None or value > best[0]:
            best = (value, steps, fees)
    if best is None:
        raise ValueError(f"Nessun percorso book {src}→{dest} disponibile")
    return best


def simulate(token_pair, book, starting_currency, amount_eur, eur_per_quote,
             fx_books, crypto_fee=0.008, fx_fee=0.002,
             buy_mode="taker", sell_mode="taker", maker_fee=0.004):
    """Round-trip costo piatto: wallet→token→wallet, spread+slippage+fee.
    Il valore iniziale viene espresso in EUR, anche se il saldo è in USDC.
    """
    token, quote = token_pair.split("/")
    if quote not in FIAT or starting_currency not in {"EUR", "USDC"}:
        raise ValueError("Valuta wallet o quote non prevista")
    if amount_eur <= 0 or not math.isfinite(amount_eur):
        raise ValueError("Importo EUR non valido")
    wallet_rate = eur_per_quote.get(starting_currency)
    quote_rate = eur_per_quote.get(quote)
    if not wallet_rate or not quote_rate:
        raise ValueError("Cambio EUR non rilevato per wallet o quote")
    source_balance = amount_eur / wallet_rate
    buy_budget, ingress_steps, ingress_fees = fx_convert(
        source_balance, starting_currency, quote, fx_books, fx_fee)
    qty_net, crypto_buy_fee = execute_crypto(book, "buy", buy_budget,
                                             buy_mode, crypto_fee, maker_fee)
    proceeds, crypto_sell_fee = execute_crypto(book, "sell", qty_net,
                                               sell_mode, crypto_fee, maker_fee)
    final_wallet, egress_steps, egress_fees = fx_convert(
        proceeds, quote, starting_currency, fx_books, fx_fee)
    final_eur = final_wallet * wallet_rate
    gross_cost = amount_eur - final_eur
    fees_in_eur = ((crypto_buy_fee * quote_rate * price_mid(book))
                   + crypto_sell_fee * quote_rate)
    fees_in_eur += sum(fee * eur_per_quote[cur] for cur, fee in
                       ingress_fees + egress_fees)
    # Il costo è una differenza contro un prezzo che non si muove, non un profitto.
    return {
        "coppia": token_pair, "valuta_partenza": starting_currency,
        "importo_eur": amount_eur, "ritorno_eur": final_eur,
        "costo_roundtrip_eur": gross_cost,
        "costo_roundtrip_pct": gross_cost / amount_eur * 100,
        "fee_stimate_eur": fees_in_eur,
        "spread_slippage_stimati_eur": gross_cost - fees_in_eur,
        "n_conversioni": len(ingress_steps) + len(egress_steps),
        "percorso": ingress_steps + [token_pair + " (compra/vendi)"] + egress_steps,
        "commissione_crypto_pct": crypto_fee * 100,
        "commissione_fx_pct": fx_fee * 100,
        "fee_maker_pct": maker_fee * 100,
        "modalita_ingresso": buy_mode, "modalita_uscita": sell_mode,
        "esecuzione_condizionale": buy_mode == "maker" or sell_mode == "maker",
        "ipotesi": ("Prezzo/quantità maker teorici; esecuzione totale NON garantita"
                    if buy_mode == "maker" or sell_mode == "maker"
                    else "Taker livello 1, book fotografato"),
    }


def price_mid(book):
    bid = positive(book["bids"][0][0])
    ask = positive(book["asks"][0][0])
    if not bid or not ask or bid > ask:
        raise ValueError("Book non coerente")
    return (bid + ask) / 2


def compare_for_token(alternatives, depths_by_pair, fx_books, rates, amount_eur=100,
                      crypto_fee=0.008, fx_fee=0.002):
    """Scenari per wallet EUR e USDC: nessuna classifica tra quote senza book."""
    results = []
    rates_eur = {key: value["eur"] for key, value in rates.items()}
    for origin in ("EUR", "USDC"):
        for alt in alternatives:
            pair = alt["pair"]
            book = depths_by_pair.get(pair)
            if not book:
                results.append({"coppia":pair,"valuta_partenza":origin,
                                "errore":"Book del mercato non acquisito"})
                continue
            try:
                result = simulate(pair,book,origin,amount_eur,rates_eur,fx_books,
                                  crypto_fee,fx_fee)
                results.append(result)
            except ValueError as ex:
                results.append({"coppia":pair,"valuta_partenza":origin,
                                "errore":str(ex)})
    return results


def compare_modes(token_pair, book, starting_currency, amount_eur, eur_per_quote,
                  fx_books, crypto_fee=0.008, maker_fee=0.004, fx_fee=0.002):
    """Confronto T/T, M/M, M/T, T/M sullo stesso itinerario valutario.

    Solo T/T è un'ipotesi di esecuzione immediata soggetta a mutamento del book.
    M/M e misti sono scenari CONDIZIONALI di pieno fill al miglior bid/ask di oggi.
    """
    plans = [
        ("taker/taker", "taker", "taker"),
        ("maker/maker", "maker", "maker"),
        ("maker/taker", "maker", "taker"),
        ("taker/maker", "taker", "maker"),
    ]
    outputs = []
    for name, inbound, outbound in plans:
        try:
            row = simulate(
                token_pair, book, starting_currency, amount_eur, eur_per_quote,
                fx_books, crypto_fee=crypto_fee, fx_fee=fx_fee,
                buy_mode=inbound, sell_mode=outbound, maker_fee=maker_fee)
            row["scenario"] = name
            outputs.append(row)
        except ValueError as exc:
            outputs.append({"coppia": token_pair, "valuta_partenza": starting_currency,
                            "scenario": name, "errore": str(exc),
                            "esecuzione_condizionale": inbound=="maker" or outbound=="maker"})
    return outputs


def stima_vendita_book_150(bids, disponibile_base, *, target_eur="150", fee_ipotesi="0.008"):
    """KDD-05/12: quantita minima teorica da vendere sui bid Kraken fotografati.

    Solo stima di liquidita, usando una fee ASSUNTA e non il livello reale del conto.
    Il book può cambiare prima del fill; non legge né crea ordini.
    """
    from decimal import Decimal, InvalidOperation, localcontext
    from fractions import Fraction
    def dec(value):
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise ValueError("Book: valore non numerico")
        try:
            v = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("Book: valore non numerico") from exc
        if not v.is_finite():
            raise ValueError("Book: numero non finito")
        return v
    def as_fraction(value):
        # Decimal context rounding at target/(1-fee) can produce 149.9999…
        # even when the mathematically required net is exactly 150.
        return Fraction(dec(value))
    def shown(value):
        with localcontext() as context:
            context.prec = 50
            return format(Decimal(value.numerator) / Decimal(value.denominator), "f")

    available = as_fraction(disponibile_base)
    target = as_fraction(target_eur)
    fee = as_fraction(fee_ipotesi)
    if available < 0 or target <= 0 or fee < 0 or fee >= 1:
        raise ValueError("Book: quantita, obiettivo o fee non validi")
    if not isinstance(bids, list) or not 1 <= len(bids) <= 500:
        raise ValueError("Book: profondita assente o fuori limite")
    remaining = available
    qty = Fraction(0)
    gross = Fraction(0)
    last_price = None
    levels_used = 0
    for row in bids:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise ValueError("Book: livello non valido")
        price, size = as_fraction(row[0]), as_fraction(row[1])
        if price <= 0 or size <= 0 or (last_price is not None and price >= last_price):
            raise ValueError("Book: bid non valido, duplicato o fuori ordine")
        last_price = price
        if remaining <= 0 or gross * (1 - fee) >= target:
            continue
        missing_gross = target / (1 - fee) - gross
        take = min(remaining, size, missing_gross / price)
        if take > 0:
            qty += take
            gross += take * price
            remaining -= take
            levels_used += 1
    net = gross * (1 - fee)
    reaches = net >= target
    if reaches:
        state = "150_NETTI_SOLO_CON_FEE_IPOTETICA_E_BOOK_FOTOGRAFATO"
    elif remaining <= 0:
        state = "SALDO_DISPONIBILE_INSUFFICIENTE"
    else:
        state = "PROFONDITA_BOOK_INSUFFICIENTE"
    return {
        "stato": state,
        "obiettivo_netto_eur": shown(target),
        "quantita_base_teorica": shown(qty),
        "proventi_lordi_stimati_eur": shown(gross),
        "fee_ipotetica_eur": shown(gross * fee),
        "proventi_netto_fee_ipotesi_eur": shown(net),
        "fee_ipotetica_pct": format(dec(fee_ipotesi) * Decimal(100), "f"),
        "livelli_bid_utilizzati": levels_used,
        "nessun_fill_attestato": True,
        "limite": ("Fee NON verificata per il conto; prezzo e profondita book mutano, "
                   "minimi e precisione ordine da controllare, nessuna negoziabilita "
                   "personale o risultato di vendita attestato."),
    }

def stima_vendita_book_disponibile(bids, disponibile_base, *, fee_ipotesi="0.008"):
    """Target-free depth capacity for ALL available units, not a sales goal.

    Uses public bid levels and a disclosed hypothetical fee; it cannot attest
    account-specific fees, trading permission, or execution. No order is sent.
    """
    from decimal import Decimal, InvalidOperation
    def decimal(value):
        if type(value) not in (str,int,float,Decimal):
            raise ValueError("Depth: malformed number")
        try: v=Decimal(str(value))
        except InvalidOperation as exc:raise ValueError("Depth: malformed number") from exc
        if not v.is_finite():raise ValueError("Depth: non-finite number")
        return v
    available=decimal(disponibile_base)
    fee=decimal(fee_ipotesi)
    if available<0 or not 0<=fee<1:
        raise ValueError("Depth: available amount or fee invalid")
    if not isinstance(bids,list) or not 1<=len(bids)<=500:
        raise ValueError("Depth: missing or oversized bids")
    remaining=available
    gross=Decimal(0)
    last=None
    used=0
    for level in bids:
        if not isinstance(level,(list,tuple)) or len(level)<2:
            raise ValueError("Depth: malformed bid")
        price,quantity=decimal(level[0]),decimal(level[1])
        if price<=0 or quantity<=0 or (last is not None and price>=last):
            raise ValueError("Depth: non-descending/invalid bids")
        last=price
        if remaining<=0: continue
        consume=min(remaining,quantity)
        remaining-=consume
        gross+=consume*price
        used+=1
    net=gross*(1-fee)
    return {
        "stato":"CAPACITA_TOTALE_BOOK_OSSERVATA" if remaining==0 else
                "CAPACITA_PARZIALE_BOOK_OSSERVATA",
        "quantita_base_teorica":format(available-remaining,"f"),
        "quantita_senza_profondita":format(remaining,"f"),
        "proventi_lordi_stimati_eur":format(gross,"f"),
        "fee_ipotetica_eur":format(gross*fee,"f"),
        "proventi_netto_fee_ipotesi_eur":format(net,"f"),
        "fee_ipotetica_pct":format(fee*100,"f"),
        "livelli_bid_utilizzati":used,
        "nessun_fill_attestato":True,
        "limite":"Analisi di capienza senza importo-obiettivo: profondita e bid mobili, "
                 "fee solo ipotetica, minimi, precisione e disponibilita a negoziare "
                 "non verificati; nessun importo netto effettivamente ottenuto."}
