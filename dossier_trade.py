"""Dossier verificabile per ragionamento GPT in chat, senza API private né ordini."""
import datetime as dt
import contextlib
import contextvars

_PRIMARY_REAL_REFRESH=contextvars.ContextVar("kdd_primary_real_refresh",default=False)


@contextlib.contextmanager
def primary_refresh_context():
    """Permit new external economic sources only during genuine KDD refresh."""
    marker=_PRIMARY_REAL_REFRESH.set(True)
    try:
        yield
    finally:
        _PRIMARY_REAL_REFRESH.reset(marker)


import json
import math
import time
import urllib.parse
import decision_desk as desk
import analisi_v02 as technical
import flusso_spot

URL_GLOBAL = "https://api.coingecko.com/api/v3/global"
FUTURES = "https://futures.kraken.com/api/charts/v1/analytics/PF_XBTUSD/"


def summarize_candles(raw, seconds, now):
    bars = technical.closed_bars(raw, now=now, interval_sec=seconds)
    if len(bars) < 30:
        raise ValueError("Meno di 30 candele chiuse: livelli tecnici non disponibili")
    def lo(items):
        return min(float(v[3]) for v in items)
    def hi(items):
        return max(float(v[2]) for v in items)
    def fl(v): return round(float(v), 9)
    candle = lambda x: dict(
        chiusura_utc=dt.datetime.fromtimestamp(int(x[0])+seconds,dt.timezone.utc).isoformat(),
        apertura=fl(x[1]), massimo=fl(x[2]), minimo=fl(x[3]),
        chiusura=fl(x[4]), volume_base=fl(x[6]))
    return dict(
        ultima_chiusura_utc=dt.datetime.fromtimestamp(int(bars[-1][0])+seconds,dt.timezone.utc).isoformat(),
        ultime_candele=[candle(x) for x in bars[-8:]],
        ultime_4=dict(minimo=lo(bars[-4:]), massimo=hi(bars[-4:])),
        ultime_12=dict(minimo=lo(bars[-12:]), massimo=hi(bars[-12:])),
        ultime_24=dict(minimo=lo(bars[-24:]), massimo=hi(bars[-24:])),
        ultime_48=dict(minimo=lo(bars[-48:]), massimo=hi(bars[-48:])) if len(bars)>=48 else None,
        volume_ultime_4=sum(float(x[6]) for x in bars[-4:]),
        volume_4_precedenti=sum(float(x[6]) for x in bars[-8:-4]),
    )


def livelli_da_frame_4tf(frame, now):
    """Legacy levels from the *same already checked* closed series, no extra GET."""
    if not isinstance(frame,dict) or frame.get('stato')!='AGGIORNATO':
        return {'stato':(frame.get('stato','NON_DISPONIBILE')
                         if isinstance(frame,dict) else 'NON_DISPONIBILE'),
                'motivo':(frame.get('motivo','Non aggiornato')
                          if isinstance(frame,dict) else 'Frame mancante')}
    records=frame.get('serie_ohlcv_chiuse')
    seconds=frame.get('intervallo_secondi')
    if not isinstance(records,list) or seconds not in (900,3600,14400,86400):
        return {'stato':'NON_DISPONIBILE','motivo':'Serie 4TF non verificata'}
    raw=[[x['time'],x['open'],x['high'],x['low'],x['close'],
          x['close'],x['volume'],0] for x in records]
    try:
        return dict(summarize_candles(raw,seconds,now.timestamp()),
                    stato='AGGIORNATO',coppia=frame['coppia'],
                    pair_key=frame['pair_key'],fonte=frame['fonte'])
    except (ValueError,TypeError,KeyError,IndexError,ZeroDivisionError,OverflowError):
        return {'stato':'NON_DISPONIBILE','motivo':'Riepilogo serie OHLCV non valido'}


def documenta_4h(raw, now):
    """Dataset 4H verificabile, non grafico ne' pattern certificato.
    Una candela 4H in corso non puo' essere usata come chiusura.
    """
    rows=technical.closed_bars(raw, now=now, interval_sec=14400)
    if len(rows)<30:
        raise ValueError("4H: meno di 30 candele chiuse")
    stamps=[int(x[0]) for x in rows]
    if any(stamps[k]<=stamps[k-1] for k in range(1,len(stamps))):
        raise ValueError("4H: timestamp non ordinati o duplicati")
    recent=rows[-200:]
    gaps=[k for k in range(1,len(recent))
          if int(recent[k][0])-int(recent[k-1][0])!=14400]
    serie=[]
    for c in recent:
        o,h,l,cl,vol=(float(c[j]) for j in (1,2,3,4,6))
        if not (0<l<=min(o,cl)<=max(o,cl)<=h and vol>=0
                and all(math.isfinite(v) for v in (o,h,l,cl,vol))):
            raise ValueError("4H: OHLCV incoerente")
        serie.append({"apertura_ts_utc":int(c[0]), "open":o,"high":h,
                      "low":l,"close":cl,"volume_base":vol})
    return {"stato":"OK" if not gaps else "LACUNE_TEMPORALI",
            "timeframe":"4H","intervallo_secondi":14400,
            "n_candele_chiuse_totali":len(rows),
            "n_candele_conservate":len(serie),"serie_ohlcv_chiuse":serie,
            "gap_nell_estratto":len(gaps),
            "campione_ema50_sufficiente":len(serie)>=150 and not gaps,
            "lettura_indicativa":summarize_candles(raw,14400,now),
            "nota":"Solo candele CHIUSE; EMA, pivot e livelli strutturali "
                   "NON ancora calcolati da questa funzione. "
                   "Se mancano barre, non interpolarle."}


def recupera_4h(source, candidates, now):
    """Dati 4H sia per BTC/ETH/SUI/BNB, sia per le schede dello scanner.
    Budget massimo otto coppie e solo Kraken spot pubblico, senza ordini.
    """
    request_pairs={}
    markets=source.get("markets",{})
    for token in ("BTC","ETH","SUI","BNB"):
        meta=markets.get(token)
        if meta and meta.get("pair_key"):
            request_pairs[token]=(meta["pair_key"],meta.get("pair",""))
        else:
            request_pairs[token]=(None,None)
    for c in candidates:
        token=c.get("token")
        if token in request_pairs and request_pairs[token][0]:
            continue
        pair=c.get("coppia_analisi")
        match=next((x for x in c.get("alternative",[])
                    if x.get("pair")==pair),None)
        if match and match.get("pair_key"):
            request_pairs[token]=(match["pair_key"],pair)
    results={}
    count=0
    for token,(pair_key,pair) in list(request_pairs.items())[:8]:
        if not pair_key:
            results[token]={"stato":"NON_DISPONIBILE","motivo":"Coppia Kraken non individuata"}
            continue
        try:
            response=desk.kraken("OHLC",pair=pair_key,interval=240)
            candles=next(v for k,v in response.items() if k!="last")
            observation=documenta_4h(candles,now)
            results[token]=dict(observation,token=token,coppia=pair,
                                fonte="Kraken Spot OHLC interval=240")
        except Exception as exc:
            results[token]={"stato":"NON_DISPONIBILE","coppia":pair,
                            "motivo":type(exc).__name__+": "+str(exc)[:110]}
        count+=1
        if count<8: time.sleep(.65)
    return results


def derivatives_context(now):
    outputs={"strumento":"PF_XBTUSD", "copertura":"Solo derivato Kraken Futures BTC, NON aggregato cross-exchange",
             "fonte":"https://futures.kraken.com/api/charts/v1/analytics/"}
    for metric in ("open-interest", "cvd"):
        q=urllib.parse.urlencode({"since":int(now)-86400,"interval":3600})
        url=FUTURES+metric+"?"+q
        try:
            data=json.loads(desk.request(url,timeout=13).decode("utf-8"))
            if data.get("errors"): raise ValueError("API error")
            result=data["result"]; stamps=result["timestamp"]
            if not stamps: raise ValueError("Serie vuota")
            # Le timestamps sono gli inizi delle barre 1h. Escludere la barra
            # corrente e verificare la stessa lunghezza per tutte le serie.
            closed_idx=[i for i,t in enumerate(stamps) if int(t)+3600<=now]
            if len(closed_idx)<5:raise ValueError("Meno di 5 barre orarie chiuse")
            last=closed_idx[-1]; previous=closed_idx[-5]
            ended=dt.datetime.fromtimestamp(int(stamps[last])+3600,dt.timezone.utc).isoformat()
            if metric=="open-interest":
                values=[float(x[-1]) for x in result["data"]]
                if len(values)!=len(stamps):raise ValueError("Lunghezze open interest incoerenti")
                outputs[metric]={"ultimo_close":values[last],"close_4h_fa":values[previous],
                                 "ultimo_punto_utc":ended, "ultimo_punto_provvisorio":False,
                                 "unita":"Verificare specifica contrattuale PF_XBTUSD prima di interpretare le unità"}
            else:
                rows=result["data"]
                if any(len(rows[k])!=len(stamps) for k in ("cvd","buy_volume","sell_volume")):
                    raise ValueError("Lunghezze CVD incoerenti")
                outputs[metric]={"ultimo_cvd":float(rows["cvd"][last]),
                                 "cvd_4h_fa":float(rows["cvd"][previous]),
                                 "ultimo_buy_volume":float(rows["buy_volume"][last]),
                                 "ultimo_sell_volume":float(rows["sell_volume"][last]),
                                 "ultimo_punto_utc":ended, "ultimo_punto_provvisorio":False,
                                 "copertura_cvd":"Serie del derivato Kraken PF_XBTUSD, dipende dalla finestra richiesta"}
        except Exception as exc:
            outputs[metric]={"errore":type(exc).__name__}
        time.sleep(.35)
    # KDD-16: bounded public futures tape + funding; no keys, margin or orders.
    # Keep the pre-existing OI/CVD measurements if this extra feed is missing.
    try:
        import kdd_futures_flow
        outputs["flusso_futures"] = kdd_futures_flow.collect(now)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        outputs["flusso_futures"] = {"strumento": "PF_XBTUSD",
                                   "stato": "NON_VERIFICATO",
                                   "motivo": type(exc).__name__}
    return outputs


# Mappatura verificata del NOME completo, non dedotta da ticker ambigui.
COINGECKO_IDS = {"ICNT": "impossible-cloud-network-token", "KAS": "kaspa"}


def token_fundamentals(token):
    if token not in COINGECKO_IDS:
        return {"stato": "Non verificato: manca ID univoco fonte"}
    ref = COINGECKO_IDS[token]
    url=("https://api.coingecko.com/api/v3/coins/"+ref+
         "?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false")
    data=json.loads(desk.request(url,timeout=13).decode("utf-8"))
    if data.get("id") != ref or data.get("symbol","").upper() != token:
        raise ValueError("Identità token non verificata")
    market=data["market_data"]
    return {"fonte":url,"id":ref,"nome":data.get("name"),
            "prezzo_usd":market["current_price"].get("usd"),
            "capitalizzazione_usd":market["market_cap"].get("usd"),
            "offerta_circolante":market.get("circulating_supply"),
            "offerta_totale":market.get("total_supply"),
            "aggiornato_utc":market.get("last_updated")}


def global_context():
    d=json.loads(desk.request(URL_GLOBAL,timeout=14).decode("utf-8"))["data"]
    cap=d["total_market_cap"]["usd"]
    volume=d["total_volume"]["usd"]
    invalid_volume=(volume>cap*10 or volume<=0)
    return {"fonte":URL_GLOBAL, "capitalizzazione_totale_usd":cap,
            "volume_24h_usd":None if invalid_volume else volume,
            "anomalia_volume_24h":"Dato API incoerente, ESCLUSO dall'analisi" if invalid_volume else None,
            "dominanza_btc_pct":d["market_cap_percentage"].get("btc"),
            "var_capitalizzazione_24h_pct":d.get("market_cap_change_percentage_24h_usd"),
            "aggiornato_sorgente_utc":d.get("updated_at"), "copertura":"Mercato crypto aggregato CoinGecko, non liquidità Kraken."}


def finanziamento_150_book(source, portfolio, *, saldo_recente, kraken_client=None,
                             max_calls=4, target_eur="150"):
    """KDD-05/12: pubblica profondita bid su asset posseduti, fee solo ipotetica.

    Usa la fotografia Kraken; non controlla negoziabilita/fee del conto e non ordina.
    """
    from decimal import Decimal, InvalidOperation
    import costi_spot
    if kraken_client is None:
        kraken_client = desk.kraken
    rows = portfolio.get("posizioni") if isinstance(portfolio, dict) else None
    markets = source.get("markets") if isinstance(source, dict) else None
    if not isinstance(rows, list) or not isinstance(markets, dict):
        return {"stato": "NON_VERIFICABILE", "righe": [], "richieste_depth": 0}
    result = [{"indice": i, "token": x.get("token") if isinstance(x, dict) else None,
               "stato": "NON_VERIFICABILE"} for i, x in enumerate(rows)]
    if not saldo_recente:
        return {"stato": "SALDO_NON_RECENTE", "righe": result, "richieste_depth": 0}
    # AssetPairs was already downloaded during this refresh. Never infer a REST
    # identifier from the printed wsname or the Depth response's own key.
    # Missing/colliding metadata fails closed; no extra network request.
    try:
        import serve
        raw_pairs = source.get("_verified_asset_pairs")
        catalog = serve.spot_catalog(lambda _: raw_pairs)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError, AttributeError):
        catalog = {}
    eligible = []
    for i, x in enumerate(rows):
        if not isinstance(x, dict) or not isinstance(x.get("token"), str):
            continue
        token = x["token"]
        market = markets.get(token)
        if (not isinstance(market, dict) or market.get("token") != token
                or not isinstance(market.get("pair"), str)
                or not market["pair"].endswith("/EUR")
                or desk.canonical(market["pair"].split("/")[0]) != desk.canonical(token)
                or not isinstance(market.get("pair_key"), str)
                or not market["pair_key"].isalnum()):
            continue
        try:
            import patrimonio_4tf
            metadata = catalog.get(market["pair_key"])
            if (not isinstance(metadata, dict)
                    or metadata.get("pair") != market["pair"]
                    or metadata.get("quote") != "EUR"
                    or patrimonio_4tf.canonical_base(metadata.get("base"))
                       != patrimonio_4tf.canonical_base(token)):
                result[i]["stato"] = "IDENTITA_BOOK_NON_VERIFICABILE"
                continue
        except (TypeError, AttributeError, ValueError, KeyError):
            result[i]["stato"] = "IDENTITA_BOOK_NON_VERIFICABILE"
            continue
        try:
            amount = Decimal(str(x.get("disponibile_spot")))
            held = Decimal(str(x.get("quantita")))
            price = Decimal(str(market.get("prezzo_eur")))
            if (not amount.is_finite() or not held.is_finite() or not price.is_finite()
                    or amount < 0 or held < 0 or amount > held or price <= 0):
                continue
        except (TypeError, ValueError, InvalidOperation):
            continue
        # About 150 USDC is a flexible aim, NOT a 150-EUR cutoff.
        # Every positive available EUR-value may provide an alternative;
        # examine the largest capacities first within the existing call cap.
        maximum = price * amount
        result[i]["massimo_lordo_indicativo_eur"] = format(maximum, "f")
        if maximum > 0:
            eligible.append((maximum, i, token, market["pair"], market["pair_key"], str(amount)))
            result[i]["stato"] = "IN_ATTESA_BOOK"
        else:
            result[i]["stato"] = "NESSUNA_DISPONIBILITA_SPOT"
    eligible.sort(key=lambda row: row[0], reverse=True)
    called = 0
    for _, i, token, pair, pair_key, available in eligible:
        if called >= max_calls:
            result[i]["stato"] = "RINVIATO_LIMITE_RICHIESTE"
            continue
        called += 1
        try:
            raw = kraken_client("Depth", pair=pair_key, count=25)
            if not isinstance(raw, dict) or set(raw) != {pair_key}:
                raise ValueError("Identita book Kraken diversa dalla coppia richiesta")
            depth = raw[pair_key]
            if not isinstance(depth, dict):
                raise ValueError("Book Kraken non strutturato")
            estimate = (costi_spot.stima_vendita_book_disponibile(
                depth.get("bids"), available, fee_ipotesi="0.008")
                if target_eur is None else costi_spot.stima_vendita_book_150(
                    depth.get("bids"), available, target_eur=target_eur, fee_ipotesi="0.008"))
            result[i] = {"indice": i, "token": token, "stato": "BOOK_PUBBLICO_OSSERVATO",
                         "pair": pair, "pair_key": pair_key,
                         "osservato_utc": desk.NOW().isoformat(timespec="seconds"),
                         "bids_osservati": depth.get("bids"),
                         "stima": estimate}
        except Exception as exc:
            result[i]["stato"] = "BOOK_NON_VERIFICATO"
            result[i]["motivo"] = type(exc).__name__
        if called < min(len(eligible), max_calls):
            time.sleep(1)
    return {"stato": "OSSERVAZIONE_PARZIALE_SENZA_FEE_REALI",
            "rilevazione_mercato_utc": source.get("rilevazione_utc"),
            "righe": result, "richieste_depth": called,
            "limite": "Fee 0,8% ipotizzata; book mobile e minimi/negoziabilita del conto ignoti."}


def economic_evidence(source, wallet, four, candidates, now, *,
                      asset_pairs=None, previous=None, requested=None):
    """Patrimonio dinamico: catalogo Kraken reale, progetti curati o ricerca incrociata.

    The previous dossier is a dated, local public-evidence cache, never a
    substitute for the current Kraken AssetPairs binding or wallet snapshot.
    """
    import json
    import urllib.error
    import kdd_economics as econ
    import kdd_network_defi as onchain
    import serve

    try:
        catalog = serve.spot_catalog(lambda endpoint: asset_pairs)
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        catalog = {}
    prior = previous if isinstance(previous, dict) and previous.get("schema") == econ.VERSION else {}
    prior_time = econ.stamp(prior.get("acquisito_utc"))
    allowed_history = bool(prior_time and dt.timedelta(0) <= now-prior_time <= dt.timedelta(days=7))
    # Only locally recorded public identities are retained; every new snapshot
    # rechecks their exact REST key and pair against Kraken ONLINE AssetPairs.
    previous_dynamic = {}
    if allowed_history:
        for old in prior.get("identita_dinamiche", [])[:100]:
            if not isinstance(old, dict):
                continue
            token = old.get("token")
            pair = old.get("coppia")
            record = old.get("risoluzione")
            proof = record.get("prova_mercato") if isinstance(record, dict) else None
            verified = econ.stamp(proof.get("verificato_utc")) if isinstance(proof, dict) else None
            if (isinstance(token, str) and verified
                    and dt.timedelta(0) <= now-verified <= dt.timedelta(days=7)
                    and econ._dynamic_valid(token, pair, record)):
                previous_dynamic[(token, pair)] = record

    wallet_rows = wallet.get("posizioni") if isinstance(wallet, dict) else None
    wallet_rows = wallet_rows if isinstance(wallet_rows, list) else []
    four_rows = four.get("posizioni") if isinstance(four, dict) else None
    four_rows = four_rows if isinstance(four_rows, list) else []
    def _prior_pair_for_public_status(index, token):
        """Recover only a *pair reference*, never an old project verification.

        The live AssetPairs REST key and wsname must still match. The standard
        online-only spot catalogue remains unchanged, so a restricted pair
        cannot regain eligibility for trading or priced 4TF inference.
        """
        if not allowed_history or not isinstance(asset_pairs,dict):
            return None
        prior_positions=prior.get("posizioni")
        if not isinstance(prior_positions,list) or index>=len(prior_positions):
            return None
        previous_row=prior_positions[index]
        if (not isinstance(previous_row,dict) or previous_row.get("indice")!=index
                or previous_row.get("token")!=token):
            return None
        identity=previous_row.get("identita")
        if not isinstance(identity,dict) or identity.get("stato")!="IDENTITA_VERIFICATA_DA_CATALOGO":
            return None
        key,pair=identity.get("pair_key"),identity.get("coppia")
        if not isinstance(key,str) or not isinstance(pair,str) or pair.count("/")!=1:
            return None
        base,quote=pair.split("/")
        if (econ.canonical_token(base)!=econ.canonical_token(token)
                or quote not in ("EUR","USD","USDC")):
            return None
        current=asset_pairs.get(key)
        if not isinstance(current,dict) or current.get("wsname")!=pair:
            return None
        return (pair,key)

    items = {"posizioni": [], "candidati": [], "richiesti": []}
    for index, row in enumerate(wallet_rows):
        tf = four_rows[index] if index < len(four_rows) and isinstance(four_rows[index], dict) else {}
        token, valid = desk.wallet_symbol(row.get("token") if isinstance(row, dict) else None)
        pair, key = tf.get("coppia"), tf.get("pair_key")
        if valid and (not isinstance(pair,str) or not isinstance(key,str)):
            old_pair=_prior_pair_for_public_status(index,token)
            if old_pair is not None:
                pair,key=old_pair
        identity = econ.identify(token, pair, key,
                                 catalog=catalog if valid and tf.get("token") == token else {},
                                 discovered=previous_dynamic.get((token, pair)))
        items["posizioni"].append({"indice": index, "token": token, "identita": identity})
    for index, row in enumerate(candidates):
        row = row if isinstance(row, dict) else {}
        token, valid = desk.wallet_symbol(row.get("token"))
        pair, key = row.get("coppia_analisi"), row.get("kraken_pair_key")
        identity = econ.identify(token, pair, key,
                                 catalog=catalog if valid else {},
                                 discovered=previous_dynamic.get((token, pair)))
        items["candidati"].append({"indice": index, "token": token,
                                   "coppia_analisi": pair, "identita": identity})

    # Third public-only universe. It exists only following an explicit local
    # CLI author request; it is neither a wallet holding nor a scanner tip.
    # The request token is not sufficient proof of a Kraken market identity.
    accepted=set()
    for record in (requested if isinstance(requested,list) else [])[:3]:
        if not isinstance(record,dict) or record.get("origine") not in (
                "CLI_ESPLICITO_LOCALE","UI_ESPLICITA_LOCALE"):
            continue
        token,valid=desk.wallet_symbol(record.get("token"))
        since=econ.stamp(record.get("richiesto_utc"))
        if (not valid or not since
                or not dt.timedelta(0)<=now-since<=dt.timedelta(days=7)
                or token in accepted):
            continue
        accepted.add(token)
        match=sorted(
            ((("EUR","USD","USDC").index(meta["quote"]),key,meta)
             for key,meta in catalog.items()
             if isinstance(meta,dict)
             and econ.canonical_token(meta.get("base"))==econ.canonical_token(token)
             and meta.get("quote") in ("EUR","USD","USDC")),
            key=lambda a:(a[0],a[1]))
        if match:
            _,key,meta=match[0]
            pair=meta["pair"]
        else:
            pair,key=None,None
        identity=econ.identify(token,pair,key,catalog=catalog,
                               discovered=previous_dynamic.get((token,pair)))
        items["richiesti"].append({
            "indice":len(items["richiesti"]),"token":token,"coppia_analisi":pair,
            "richiesto_utc":record["richiesto_utc"],
            "origine":record["origine"],"identita":identity})

    # One unresolved unique token per cycle, deterministic rotation. Limit
    # discovery to 1 search + up to 8 market checks (9 total). If more
    # candidates appear, leave identity unresolved; never pick the first hit.
    unresolved = {}
    for group in ("posizioni", "candidati", "richiesti"):
        for row in items[group]:
            identity = row["identita"]
            token = row["token"]
            if (identity.get("motivo") == "PROGETTO_NON_NEL_CATALOGO_CURATO"
                    and isinstance(token, str)):
                key = (token, identity["coppia"])
                unresolved.setdefault(key, identity["pair_key"])
    # A completely replaced wallet must not queue newly owned assets
    # behind scanner-only ideas. Keep deterministic rotation *within* each
    # group and retain the existing nine-call CoinGecko budget.
    held_pending = {(row["token"], row["identita"].get("coppia"))
                    for row in items["posizioni"]
                    if row["identita"].get("motivo") == "PROGETTO_NON_NEL_CATALOGO_CURATO"}
    pending_pairs = sorted(unresolved, key=lambda item: (item not in held_pending, item))
    next_token = prior.get("prossimo_token_identita")
    next_idx = next((i for i, item in enumerate(pending_pairs)
                     if isinstance(next_token, str)
                     and "|".join(item) == next_token), 0)
    chosen = pending_pairs[next_idx] if pending_pairs else None
    next_token = ("|".join(pending_pairs[(next_idx+1) % len(pending_pairs)])
                  if pending_pairs else None)
    discovery_calls = 0
    rate_limited = False
    discovery_problem = None
    resolved = None

    acquired_http = {}
    def public_json(url, *, timeout=12):
        nonlocal rate_limited
        try:
            # Capture the actual bytes obtained in this request path; do not
            # interpret a plausible JSON document as proof of HTTP origin.
            raw = desk.request(url, timeout=timeout)
            decoded = json.loads(raw.decode("utf-8"))
            import hashlib
            acquired_http[url] = {"url_richiesto": url,
                "sha256_corpo_risposta": hashlib.sha256(raw).hexdigest(),
                "acquisito_utc": now.isoformat(timespec="seconds"),
                "canale": "REQUEST_PUBBLICA_DEL_PRODUTTORE",
                "limite": "Hash e URL documentano il percorso di acquisizione locale; "
                          "non attestano da soli autenticita esterna o veridicita dei dati."}
            return decoded, None
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                rate_limited = True
            return None, "HTTP_" + str(exc.code)
        except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
            return None, "ERRORE_" + type(exc).__name__

    if chosen:
        token, pair = chosen
        key = unresolved[chosen]
        discovery_calls += 1
        search, error = public_json(econ.CG_SEARCH + econ.canonical_token(token))
        if error:
            discovery_problem = error
        elif not isinstance(search, dict) or not isinstance(search.get("coins"), list):
            discovery_problem = "RICERCA_NON_DISPONIBILE"
        else:
            exact = [c for c in search["coins"] if isinstance(c, dict)
                     and isinstance(c.get("symbol"), str)
                     and c["symbol"].upper() == econ.canonical_token(token)]
            if len(search["coins"]) >= 100:
                discovery_problem = "RISULTATI_RICERCA_PAGINATI_NON_ESAUSTIVI"
            elif len(exact) > econ.MAX_MARKET_CANDIDATES:
                discovery_problem = "TICKER_OMONIMI_SUPERANO_BUDGET"
            else:
                markets = {}
                for coin in exact:
                    coin_id = coin.get("id")
                    if not isinstance(coin_id, str) or not __import__("re").fullmatch(
                            r"[a-z0-9-]{2,120}", coin_id):
                        discovery_problem = "ID_PROGETTO_NON_VALIDO"
                        break
                    if rate_limited:
                        discovery_problem = "RINVIATO_RATE_LIMIT_HTTP_429"
                        break
                    discovery_calls += 1
                    markets[coin_id], error = public_json(
                        econ.CG + coin_id + "/tickers?exchange_ids=kraken")
                    if error:
                        discovery_problem = error
                        break
                    time.sleep(.35)
                if discovery_problem is None:
                    resolved = econ.resolve_public(token, pair, search, markets, now)
                    if resolved.get("stato") != "RISOLTO":
                        discovery_problem = resolved.get("motivo", "IDENTITA_NON_VERIFICATA")
        if resolved and resolved.get("stato") == "RISOLTO":
            # Preserve the exact market used as proof. The same token may be
            # present in the owned wallet and scanner under different pairs:
            # only the proved pair gets this resolution.
            resolved["pair"] = pair
            previous_dynamic[chosen] = resolved
        for group in ("posizioni", "candidati", "richiesti"):
            for row in items[group]:
                if (row["token"], row["identita"].get("coppia")) != chosen:
                    continue
                prior_id = row["identita"]
                identity = econ.identify(token, prior_id.get("coppia"),
                                         prior_id.get("pair_key"), catalog=catalog,
                                         discovered=resolved if resolved and
                                         resolved.get("stato") == "RISOLTO" else None)
                if identity["stato"] != "IDENTITA_VERIFICATA_DA_CATALOGO":
                    identity["motivo"] = discovery_problem or "IDENTITA_NON_VERIFICATA"
                row["identita"] = identity
        time.sleep(.35)

    # Carry forward previously authenticated public fundamentals for a
    # disappearing/re-entering asset; never carry its quantity or valuation.
    previous_cache = {}
    if allowed_history:
        old_rows = list(prior.get("cache_fondamentali", [])[:100])
        for group in ("posizioni", "candidati", "richiesti"):
            old_rows.extend(r for r in prior.get(group, []) if isinstance(r, dict))
        for old in old_rows:
            if not isinstance(old, dict):
                continue
            ident, data = old.get("identita"), old.get("fondamentali")
            if not isinstance(ident, dict) or not isinstance(data, dict):
                continue
            observed = econ.stamp(data.get("rilevato_utc"))
            acquired = econ.stamp(data.get("acquisito_utc"))
            if (data.get("stato") != "VERIFICATO" or not observed or not acquired
                    or acquired > now or not dt.timedelta(0) <= now-observed <= dt.timedelta(days=1)
                    or ident.get("stato") != "IDENTITA_VERIFICATA_DA_CATALOGO"
                    or not econ.fundamental_source_valid(
                        data.get("fonte"),ident.get("coingecko_id"))):
                continue
            try: econ.verify_supply_at_read(data)
            except ValueError: continue
            cache_key = (ident.get("token"), ident.get("coppia"),
                         ident.get("pair_key"), ident.get("coingecko_id"))
            previous_cache[cache_key] = {"identita": ident, "fondamentali": data,
                                         "network_metadata": old.get("network_metadata")}

    unique_ids = sorted({row["identita"]["coingecko_id"] for group in items.values()
                         for row in group if row["identita"].get("coingecko_id")})
    # KDD-18: one public batch of verified CoinGecko project IDs can cover
    # the entire current portfolio/shortlist without one /coins GET per asset.
    # Individual /coins responses still run, separately, for KDD-17 contract
    # and network metadata: the markets endpoint cannot replace those facts.
    batch_requested=[]
    batch_rows={}
    batch_url=None
    batch_calls=0
    batch_error=None
    batch_returned=0
    batch_cursor=prior.get("prossimo_id_batch_fondamentali")
    batch_start=next((i for i,c in enumerate(unique_ids)
        if isinstance(batch_cursor,str) and c>=batch_cursor),0)
    if len(unique_ids)>=7 and not rate_limited and discovery_calls<9:
        batch_requested=[unique_ids[(batch_start+i)%len(unique_ids)]
            for i in range(min(len(unique_ids),econ.MAX_CG_BATCH_IDS))]
        batch_url=econ.market_batch_url(batch_requested)
        batch_calls=1
        batch_payload,batch_error=public_json(batch_url)
        if isinstance(batch_payload,list) and len(batch_payload)<=len(batch_requested):
            ids=[r.get("id") if isinstance(r,dict) else None for r in batch_payload]
            if (len(set(ids))==len(ids) and
                    all(isinstance(cid,str) and cid in batch_requested for cid in ids)):
                batch_rows={item["id"]:item for item in batch_payload}
                batch_returned=len(batch_rows)
            else:
                batch_error="BATCH_IDENTITA_AMBIGUA_O_NON_RICHIESTA"
        elif batch_error is None:
            batch_error="BATCH_FORMATO_NON_VERIFICATO"
    next_batch=(unique_ids[(batch_start+len(batch_requested))%len(unique_ids)]
                if unique_ids else None)
    previous_next = prior.get("prossimo_id_fondamentali")
    start_at = next((i for i, cg in enumerate(unique_ids)
                     if isinstance(previous_next, str) and cg >= previous_next), 0)
    # Max 6 acquisitions of fundamentals, reduced when discovery used API calls.
    capacity = min(6, max(0, 9-discovery_calls-batch_calls))
    selected = [unique_ids[(start_at+i) % len(unique_ids)]
                for i in range(min(capacity, len(unique_ids)))]
    selected_ids = set(selected)
    next_id = (unique_ids[(start_at+len(selected)) % len(unique_ids)]
               if unique_ids else None)
    cache, failures, cg_calls = {}, {}, 0
    for cg in selected:
        if rate_limited:
            cache[cg] = None
            failures[cg] = "RINVIATO_RATE_LIMIT_HTTP_429"
            continue
        cg_calls += 1
        url = (econ.CG + cg
               + "?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false")
        cache[cg], failures[cg] = public_json(url)
        time.sleep(.35)

    # KDD-20: rotate official project releases over ALL eligible repositories.
    # Previously projects[:3] permanently excluded the fourth repository.
    # Keep the existing shared 9-request ceiling (including CoinGecko).
    release_cache, release_calls = {}, 0
    projects = sorted({row["identita"]["repository_primario"]
                       for group in items.values() for row in group
                       if row["identita"].get("stato")=="IDENTITA_VERIFICATA_DA_CATALOGO"
                       and row["identita"].get("repository_primario")})
    release_cursor=prior.get("prossimo_repository_release") if allowed_history else None
    release_start=next((i for i,repo in enumerate(projects)
                        if isinstance(release_cursor,str) and repo>=release_cursor),0)
    release_capacity=min(3,max(0,9-discovery_calls-batch_calls-cg_calls))
    release_selected=[projects[(release_start+i)%len(projects)]
                      for i in range(min(release_capacity,len(projects)))]
    next_release=(projects[(release_start+len(release_selected))%len(projects)]
                  if projects else None)
    release_failures={}
    for project_repo in release_selected:
        release_calls+=1
        try:
            url="https://api.github.com/repos/"+project_repo+"/releases/latest"
            release_cache[project_repo]=json.loads(desk.request(url,timeout=10).decode("utf-8"))
        except (ValueError,OSError,RuntimeError,KeyError,TypeError) as exc:
            release_cache[project_repo]=None
            release_failures[project_repo]=(
                "HTTP_"+str(exc.code) if getattr(exc,"code",None)
                in (403,404,429,500,502,503) else "ERRORE_"+type(exc).__name__)
    # A released version is observable through its official repo even after
    # it rotates out of the request budget. Preserve it ONLY as historical,
    # with its original acquisition date, project and exact Kraken pair.
    previous_releases={}
    if allowed_history:
        for group in ("posizioni","candidati","richiesti"):
            for old in prior.get(group,[]):
                if not isinstance(old,dict):
                    continue
                ident,event=old.get("identita"),old.get("evento")
                if (not isinstance(ident,dict) or
                        ident.get("stato")!="IDENTITA_VERIFICATA_DA_CATALOGO" or
                        not isinstance(event,dict) or
                        event.get("stato") not in ("VERIFICATO","STORICO_NON_AGGIORNATO")):
                    continue
                acquired=econ.stamp(event.get("acquisito_utc"))
                if not acquired or not dt.timedelta(0)<=now-acquired<=dt.timedelta(days=7):
                    continue
                reconstructed=econ.release_event(ident,{
                    "html_url":event.get("fonte"),"tag_name":event.get("tag"),
                    "published_at":event.get("pubblicato_utc"),
                    "name":event.get("sintesi"),
                    "draft":False,"prerelease":event.get("pre_release") is True},
                    now,acquired)
                if reconstructed.get("stato")!="VERIFICATO":
                    continue
                keys=("fonte","emittente","tag","pubblicato_utc","evento_utc",
                      "sintesi","pre_release","adozione_rete","impatto_economico")
                if any(reconstructed.get(key)!=event.get(key) for key in keys):
                    continue
                key=(ident.get("token"),ident.get("coppia"),
                     ident.get("pair_key"),ident.get("coingecko_id"))
                previous_releases[key]=event

    for group in ("posizioni", "candidati", "richiesti"):
        for row in items[group]:
            identity = row["identita"]
            cg = identity.get("coingecko_id")
            if cg is None:
                fund = dict(econ.fundamentals(identity, None, now, now),
                            stato="NON_VERIFICATO_IDENTITA",
                            motivo=identity.get("motivo"))
            else:
                individual_url=(econ.CG + cg
                    + "?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false")
                individual = econ.fundamentals(identity, cache.get(cg), now, now,
                    acquisition=acquired_http.get(individual_url))
                batched=(econ.market_batch_fundamentals(
                    identity,batch_rows[cg],now,now,batch_url,
                    acquisition=acquired_http.get(batch_url))
                    if cg in batch_rows and batch_url else None)
                fresh=(batched if batched and batched["stato"] in
                    ("VERIFICATO","ANOMALIA_SUPPLY","SCADUTO") else individual)
                cache_key = (identity.get("token"), identity.get("coppia"),
                             identity.get("pair_key"), cg)
                if fresh["stato"] == "VERIFICATO":
                    fund = dict(fresh, origine="ACQUISIZIONE_PUBBLICA")
                elif cache_key in previous_cache:
                    # The same Kraken pair and CoinGecko project must still
                    # be verified; values keep their upstream observation time.
                    fund = dict(previous_cache[cache_key]["fondamentali"],
                                origine="CACHE_LOCALE_FONTE_PUBBLICA",
                                riutilizzato_utc=now.isoformat(timespec="seconds"))
                elif fresh["stato"]=="ANOMALIA_SUPPLY":
                    fund=fresh
                elif cg in batch_requested and batch_returned and cg not in batch_rows and cg not in selected_ids:
                    fund=dict(fresh,stato="NON_DISPONIBILE_FONTE",
                              motivo="COINGECKO_ID_NON_RESTITUITO_BATCH")
                elif cg in batch_rows and batched and batched["stato"]=="NON_VERIFICATO" and cg not in selected_ids:
                    fund=dict(fresh,stato="NON_VERIFICATO_IDENTITA",
                              motivo="RISPOSTA_BATCH_PROGETTO_DISCORDANTE")
                elif cg not in selected_ids:
                    fund = dict(fresh, stato="NON_ACQUISITO_PER_BUDGET")
                elif cache.get(cg) is None:
                    fund = dict(fresh, stato="NON_DISPONIBILE_FONTE",
                                motivo=failures.get(cg, "RISPOSTA_NON_DISPONIBILE"))
                else:
                    fund = fresh
            # Reuse the exact /coins response already acquired by economics.
            # Metadata is an index; neither chain custody nor contract authority.
            previous_meta = previous_cache.get(cache_key, {}).get("network_metadata") if cg else None
            metadata = onchain.coin_network_metadata(identity, cache.get(cg), now)
            if metadata is None and onchain._metadata_valid(previous_meta, identity, now):
                metadata = previous_meta
            row["network_metadata"] = metadata
            row["fondamentali"] = fund
            repo_name = identity.get("repository_primario")
            release=econ.release_event(identity,release_cache.get(repo_name),now,now)
            if release["stato"]=="VERIFICATO":
                release["origine"]="ACQUISIZIONE_REPOSITORY_PUBBLICO"
            else:
                previous_key=(identity.get("token"),identity.get("coppia"),
                              identity.get("pair_key"),identity.get("coingecko_id"))
                old_release=previous_releases.get(previous_key)
                if old_release and repo_name==old_release.get("emittente"):
                    release=dict(old_release,stato="STORICO_NON_AGGIORNATO",
                        origine="CACHE_LOCALE_RELEASE_PUBBLICA",
                        motivo_rinvio=("RINVIATO_BUDGET" if repo_name not in release_selected
                                      else release_failures.get(repo_name,"FONTE_NON_CONFORME")))
                elif repo_name and identity.get("stato")=="IDENTITA_VERIFICATA_DA_CATALOGO":
                    release["stato"]=("RINVIATO_BUDGET" if repo_name not in release_selected
                                     else "FONTE_NON_DISPONIBILE")
                    release["motivo"]=release_failures.get(repo_name,
                                                         "RELEASE_NON_ATTESTATA")
            row["evento"]=release
            # A curated primary monetary-policy URL is a research reference,
            # NOT a newly acquired unlock/vesting schedule.
            row["politica_monetaria_primaria"] = econ.monetary_reference(identity)
            row["lettura_economica"] = econ.decision_context(
                identity, row["fondamentali"], row["evento"])

    # Bounded PUBLIC-only persistence: identity and source cache, no balances,
    # wallet quantities, T0 or private account data.
    public_cache = dict(previous_cache)
    for group in ("posizioni", "candidati", "richiesti"):
        for row in items[group]:
            identity, data = row["identita"], row["fondamentali"]
            if data.get("stato") == "VERIFICATO":
                key = (identity.get("token"), identity.get("coppia"),
                       identity.get("pair_key"), identity.get("coingecko_id"))
                public_cache[key] = {"identita": identity, "fondamentali": data,
                                     "network_metadata": row.get("network_metadata")}
    dynamic_cache = [{"token": token, "coppia": pair, "risoluzione": record}
                     for (token, pair), record in sorted(previous_dynamic.items())][:100]
    # The primary-source follow-up belongs to the same economic dossier and
    # uses the same verified identity roster, prior public cache and refresh.
    import kdd_economic_sources as primary
    monitoring = primary.collect(
        now, items, prior.get("monitor_fonti"),
        lambda url: desk.request(url, timeout=10),
        # CoinGecko HTTP 429 stops only requests to CoinGecko. Official
        # schedules, repository documents and the Solana RPC have their own
        # independent bounded budget: suppressing them would turn a single
        # aggregator outage into loss of ALL primary tokenomics evidence.
        network_allowed=_PRIMARY_REAL_REFRESH.get(),
        skipped_reason="FUORI_REFRESH",
        asset_pairs=asset_pairs,
        rpc_fetch=onchain._http,collect_project_issues=True,
        collect_kraken_status=_PRIMARY_REAL_REFRESH.get())
    btc = next((r for r in four_rows if isinstance(r, dict) and r.get("token") == "BTC"), {})
    return {"schema": econ.VERSION, "acquisito_utc": now.isoformat(timespec="seconds"),
            "posizioni": items["posizioni"], "candidati": items["candidati"],
            "richiesti": items["richiesti"],
            "macro": econ.macro(source.get("feed"), now),
            "monitor_fonti": monitoring,
            "regime": econ.regime(btc, (source.get("coingecko_global") or {}), now),
            "fonti_economiche": econ.sources_matrix(),
            "identita_dinamiche": dynamic_cache,
            "prossimo_token_identita": next_token,
            "cache_fondamentali": list(public_cache.values())[:100],
            "prossimo_id_fondamentali": next_id,
            "prossimo_id_batch_fondamentali":next_batch,
            "copertura_batch_fondamentali":{
                "stato":("OSSERVATO" if batch_returned else
                         batch_error or "NON_RICHIESTO"),
                "id_richiesti":len(batch_requested),"id_restituiti":batch_returned,
                "fonte":batch_url if batch_calls else None,
                "limite":"Aggregatore CoinGecko, non source schedule primario; dati assenti restano assenti"},
            "richieste_identificazione": discovery_calls,
            "richieste_coingecko": cg_calls,
            "richieste_batch_coingecko":batch_calls,
            "richieste_release": release_calls,
            "prossimo_repository_release":next_release,
            "copertura_release":{
                "repository_associati":len(projects),
                "repository_richiesti":len(release_selected),
                "repository_con_release_confermata":len({
                    row["evento"]["emittente"]
                    for group in items.values() for row in group
                    if row["evento"].get("stato")=="VERIFICATO"
                    and row["evento"].get("origine")=="ACQUISIZIONE_REPOSITORY_PUBBLICO"
                    and row["evento"].get("emittente") in release_selected}),
                "limite":"Release software ufficiale non equivale a attivazione del protocollo"},
            "richieste_esterne_massime": 9,
            "richieste_effettuate": discovery_calls+batch_calls+cg_calls+release_calls,
            "limite": "Risoluzione pubblica incrociata, non prova chain/contract, unlock, acquisti o ordini"}

def collect(source=None, *, asset_pairs=None, portfolio_override=None,
            previous_dossier_override=None):
    """Prepara il dossier sullo snapshot appena acquisito, senza iniziare un'analisi GPT."""
    now=desk.NOW()
    if source is None:
        source=desk.load("ultima_rilevazione.json")
    if not source: raise ValueError("Rilevazione Kraken mancante")
    age=(now-dt.datetime.fromisoformat(source["rilevazione_utc"])).total_seconds()/60
    if age < -2 or age > 60:
        raise ValueError(f"Timestamp Kraken non valido o scaduto ({age:.0f} min)")
    candidates=[]
    shortlisted=list(source.get("schede_v02",[]))[:4]
    for card in shortlisted:
        row={k:card.get(k) for k in ('token','categoria','esito','sintesi','coppia_analisi','valuta_quotazione',
                                     'prezzo_eur','variazione_oggi','volume_coppia_eur_stimato',
                                     'indicatori','book','evidenze','criticita','alternative',
                                     'perche_selezionato','preselezione')}
        base_pair=card["coppia_analisi"]
        row["simulazione_costi_eur_wallet"]=[
            {k:x.get(k) for k in ('coppia','costo_roundtrip_eur','n_conversioni','errore')}
            for x in card.get('costi_roundtrip',[]) if x.get('valuta_partenza')=='EUR']
        matching=next((x for x in card.get('alternative',[]) if x['pair']==base_pair),None)
        if matching:
            row["kraken_pair_key"]=matching.get("pair_key")
            row["ultimo_prezzo_in_quote"]=matching.get("prezzo_quote")
        else:
            row["limite_livelli"]="Coppia della scheda non presente nelle alternative Kraken"
        if row["token"] in COINGECKO_IDS:
            try: row["fondamentali_coingecko"]=token_fundamentals(row["token"])
            except Exception as exc: row["fondamentali_coingecko"]={"errore":type(exc).__name__}
        else:
            row["fondamentali_coingecko"]={
                "stato":"ID token non validato su CoinGecko: nessun dato fondamentale attribuito"}
        row["origine_scanner"]=card.get("origine_scanner")
        row["copertura_scanner"]=card.get("copertura_scanner")
        row["figure_candlestick"]={
            "stato":"NON_DISPONIBILE","motivo":"Acquisizione 4TF non eseguita",
            "coppia":row.get("coppia_analisi")}
        candidates.append(row)
        time.sleep(.5)
    # Campione 4H anche dei quattro asset strategici (non solo gainer).
    # Kraken restituisce la candela 4H corrente: esclusa esplicitamente.
    quattro_ore=recupera_4h(source,candidates,now.timestamp())
    import patrimonio_4tf
    # KDD-07 candidates reuse the existing verified chart/candle engines,
    # never a second indicator implementation. Same-pair cached 4H may be reused.
    if asset_pairs is None:
        try:
            asset_pairs=desk.kraken("AssetPairs")
        except (OSError,RuntimeError,TypeError,ValueError,KeyError):
            asset_pairs={}
    cand_4tf=patrimonio_4tf.collect_candidates(
        candidates,asset_pairs=asset_pairs,now=now,old_4h=quattro_ore)
    for index,row in enumerate(candidates):
        tf=cand_4tf["candidati"][index]
        row["tecnica_4tf"]=tf
        row["livelli_15m"]=livelli_da_frame_4tf(tf["timeframe"]["15m"],now)
        row["livelli_1h"]=livelli_da_frame_4tf(tf["timeframe"]["1H"],now)
        same=(tf.get("token")==row.get("token") and
              tf.get("coppia")==row.get("coppia_analisi") and
              tf.get("pair_key")==row.get("kraken_pair_key"))
        if not same:
            row["tecnica_4tf"]["stato"]="COPPIA_DIVERSA_O_ASSENTE"
            row["livelli_15m"]={"stato":"COPPIA_DIVERSA_O_ASSENTE"}
            row["livelli_1h"]={"stato":"COPPIA_DIVERSA_O_ASSENTE"}
        row["figure_candlestick"]={
            "stato":("AGGIORNATO" if same and tf["stato"]=="COMPLETO"
                     else "NON_DISPONIBILE"),
            "coppia":row.get("coppia_analisi"),
            "pair_key":row.get("kraken_pair_key"),
            "confronto_4tf":tf.get("confronto_figure_4tf"),
            "per_timeframe":{label:{
                "stato":frame.get("stato"),
                "fonte":frame.get("fonte"),
                "chiusura_utc":frame.get("chiusura_utc"),
                "figure":frame.get("figure_candlestick")}
                for label,frame in tf["timeframe"].items()},
            "motivo":("Serie 4TF verificata, nessun segnale operativo"
                       if same and tf["stato"]=="COMPLETO"
                       else "Coppia o timeframe incompleti/non aggiornati")}
        row["livelli_4h"]=livelli_da_frame_4tf(tf["timeframe"]["4H"],now)
        obs=quattro_ore.get(row["token"],{})
        if obs.get("coppia")==row.get("coppia_analisi"):
            row["grafico_4h_riferimento"]=row["token"]
        match=row.get("kraken_pair_key")
        if same and match:
            try:
                row["flusso_spot_kraken"]=flusso_spot.fetch(
                    row["coppia_analisi"],match,
                    chiusura_15m_utc=(row.get("livelli_15m") or {}).get("ultima_chiusura_utc"))
                time.sleep(.8)
            except (OSError,RuntimeError,TypeError,ValueError,KeyError) as exc:
                row["flusso_spot_kraken"]={"stato":"NON_DISPONIBILE",
                                          "motivo":type(exc).__name__}
        else:
            row["flusso_spot_kraken"]={
                "stato":"NON_DISPONIBILE",
                "motivo":"Coppia candidata non riconciliata con AssetPairs"}
    external={}
    try: external["coingecko_global"]=global_context()
    except Exception as exc: external["coingecko_global"]={"errore":type(exc).__name__+": "+str(exc)[:80]}
    derivatives=derivatives_context(now.timestamp())
    # Same D1/D2 validation as dashboard, applied to this actual wallet read.
    # A market snapshot time is not proof of wallet identity or freshness.
    portafoglio = (portfolio_override if portfolio_override is not None
                   else desk.load('portafoglio.json', {}))
    qualita = desk.qualita_portafoglio(source, portafoglio)
    saldo = qualita["stato_saldo"]
    fonte = portafoglio.get("fonte_quantita") if isinstance(portafoglio, dict) else None
    # One actual public AssetPairs snapshot shared by 4TF and economics.
    if asset_pairs is None:
        try:
            asset_pairs = desk.kraken("AssetPairs")
        except (OSError, RuntimeError, TypeError, ValueError, KeyError):
            asset_pairs = {}
    previous_dossier = {}
    if previous_dossier_override is not None:
        if not isinstance(previous_dossier_override, dict):
            raise ValueError("Dossier historical input must be a private JSON object")
        previous_dossier = previous_dossier_override
        previous_economic = previous_dossier.get("evidenze_economiche")
    else:
        try:
            previous_dossier = desk.load("dossier_multifonte.json", {})
            previous_economic = (previous_dossier or {}).get("evidenze_economiche")
        except (OSError, ValueError, TypeError, AttributeError):
            previous_economic = None
    analisi_patrimonio = patrimonio_4tf.collect(
        portafoglio, source, asset_pairs=asset_pairs,
        now=now, old_4h=quattro_ore)
    finanziamento_book = finanziamento_150_book(
        dict(source, _verified_asset_pairs=asset_pairs), portafoglio,
        saldo_recente=qualita.get("saldo_recente_verificato", False), target_eur=None)
    config=desk.load("config.json",{})
    requested=(config.get("analisi_asset_richiesti") if isinstance(config,dict) else None)
    economic = economic_evidence(source, portafoglio, analisi_patrimonio, candidates, now,
                                 asset_pairs=asset_pairs, previous=previous_economic,
                                 requested=requested)
    # Global market data is obtained independently and may be unavailable.
    import kdd_economics as econ
    btc = next((r for r in (analisi_patrimonio.get("posizioni") or [])
                if r.get("token") == "BTC"), {})
    economic["regime"] = econ.regime_participation(
        econ.regime(btc, external.get("coingecko_global"), now),
        derivatives, economic.get("monitor_fonti"), now,
        previous=(previous_economic or {}).get("regime")
                 if isinstance(previous_economic,dict) else None)
    # Expose the motivated regime in the EXISTING dossier; the packet/bridge
    # separately recomputes it from time-validated sources at the moment of
    # consumption. No duplicate data fetch or second regime detector.
    context_for_regime=econ.macro_primary_context(
        economic.get("monitor_fonti") or {},economic.get("macro") or {},now)
    economic["regime_motivato"]=econ.regime_integrato(
        economic["regime"],context_for_regime,now)
    # One additional public-only evidence family. No private balances, amounts,
    # addresses or the on-chain prototypes #9-14 ever enter these requests.
    # Manual/legacy dossier creation without a real refresh has no new-source
    # claim; the packet/bridge will preserve explicit NOT_ACQUIRED rows.
    import kdd_network_defi
    network_defi = None
    if isinstance(source.get("orari_fonti"), dict) and source["orari_fonti"].get("composizione_kdd_utc"):
        holdings_for_sources = [
            {"token": row.get("token")}
            for row in economic.get("posizioni", []) if isinstance(row, dict)]
        candidates_for_sources = [
            {"token": row.get("token"), "coppia_analisi": row.get("coppia_analisi")}
            for row in candidates if isinstance(row, dict)]
        network_defi = kdd_network_defi.collect(
            now, holdings_for_sources, candidates_for_sources,
            economics=economic,
            previous=(previous_dossier or {}).get("evidenze_rete_defi")
            if isinstance(previous_dossier, dict) else None)
    dossier={
        "schema":3,"creato_utc":desk.NOW().isoformat(timespec="seconds"),
        "kraken_istantanea_utc":source["rilevazione_utc"],"eta_kraken_minuti_al_dossier":round(age,2),
        "regime":{"trend_eur":source.get("trends",{}),"btc_spot_eur":source.get("markets",{}).get("BTC")},
        "candidati":candidates,"grafici_4h":quattro_ore,
        "evidenze_economiche":economic,
        "asset_richiesti_espliciti":[{
            "token":r["token"],"coppia_analisi":r["coppia_analisi"],
            "richiesto_utc":r["richiesto_utc"],"origine":r["origine"]}
            for r in economic.get("richiesti",[])],
        "evidenze_rete_defi": network_defi,
        "patrimonio_4tf":analisi_patrimonio,
        "profondita_book_pubblica":finanziamento_book,
        "ricerca_setup":source.get("ricerca_setup",{}),
        "approfondimento_candidati_4tf":{
            "fonte":cand_4tf["fonte"],"richieste_ohlc":cand_4tf["richieste_ohlc"],
            "riusi_4h":cand_4tf["riusi_4h"],"budget_ohlc":cand_4tf["budget_ohlc"],
            "n_candidati":len(cand_4tf["candidati"]),
            "completi":sum(x["stato"]=="COMPLETO" for x in cand_4tf["candidati"]),
            "parziali":sum(x["stato"]!="COMPLETO" for x in cand_4tf["candidati"])},
        "fonti_esterne":external,
        "contesto_derivati_btc":derivatives,
        "contesto_macro_news":"Ricerca GPT separata: non inferire macro dai soli RSS",
        "portafoglio_quantita_fonte":fonte,
        "portafoglio_aggiornato_da_api_private":saldo['portafoglio_aggiornato_da_api_private'],
        "stato_saldo":saldo,
        "orari_fonti":source.get('orari_fonti', {}),
        # Legacy: means all recorded identities and quantities valid, NOT
        # complete EUR valuation, current Kraken balance, or a verified wallet.
        "portafoglio_noto":qualita['portafoglio_noto'],
        "qualita_patrimonio":qualita,
        "fotografia_portafoglio_sha256":qualita['fotografia_portafoglio_sha256'],
        "portafoglio_letto_utc":qualita['portafoglio_letto_utc'],
        "limite_fotografia":"Hash del JSON locale, non garanzia di provenienza o attualità.",
        "limiti":["Scanner limitato ai candidati; patrimonio_4tf copre tutte le righe con stati espliciti.",
                  "Candele chiuse; supporti/resistenze solo estremi storici, non segnali validati.",
                  "OI/CVD Futures Kraken BTC non disponibili per ogni token e non aggregati globali.",
                  "Flusso buy/sell spot recente da Kraken Trades: al piu 1000 esecuzioni per coppia; NON CVD storico, heatmap o mercato aggregato. Copertura e lacune per token indicate.",
                  "Origine, acquisizione e tentativo di aggiornamento saldo in stato_saldo; un dato precedente o fallito non vale come saldo attuale. Disponibilità spot, prezzo di carico e costi da verificare prima di dimensionare operazioni.",
                  "Nessun ordine o controllo privato della negoziabilità SEE."]
    }
    # JSON interoperability: no NaN/Infinity, even when an upstream source is
    # malformed. Do not silently turn impossible values into financial zeros.
    json.dumps(dossier, allow_nan=False)
    desk.save("dossier_multifonte.json",dossier)
    return dossier


if __name__=="__main__":
    x=collect()
    print("DOSSIER_SAVED",x["creato_utc"],"CANDIDATES",
          [(y["token"],y["coppia_analisi"],y.get("ultimo_prezzo_in_quote")) for y in x["candidati"]])
    print("EXTERNAL",x["fonti_esterne"])
    print("BTC_FUTURES",x["contesto_derivati_btc"])
