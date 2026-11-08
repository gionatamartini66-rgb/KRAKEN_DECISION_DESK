"""Dossier verificabile per ragionamento GPT in chat, senza API private né ordini."""
import datetime as dt
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
                             max_calls=4):
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
            estimate = costi_spot.stima_vendita_book_150(
                depth.get("bids"), available, target_eur="150", fee_ipotesi="0.008")
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
                      asset_pairs=None, previous=None):
    """All rows, bounded public requests and fair multi-refresh fundamental coverage."""
    import kdd_economics as econ
    import serve

    # Existing Kraken parser enforces ONLINE, exact REST key/wsname, aliases,
    # and unique ownership. A candidate's own key is never a certificate.
    try:
        catalog = serve.spot_catalog(lambda endpoint: asset_pairs)
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        catalog = {}
    items = {"posizioni": [], "candidati": []}
    wallet_rows = wallet.get("posizioni") if isinstance(wallet, dict) else None
    wallet_rows = wallet_rows if isinstance(wallet_rows, list) else []
    four_rows = four.get("posizioni") if isinstance(four, dict) else None
    four_rows = four_rows if isinstance(four_rows, list) else []
    for index, row in enumerate(wallet_rows):
        tf = four_rows[index] if index < len(four_rows) and isinstance(four_rows[index], dict) else {}
        token, valid = desk.wallet_symbol(row.get("token") if isinstance(row, dict) else None)
        identity = econ.identify(token, tf.get("coppia"), tf.get("pair_key"),
                                 catalog=catalog if valid and tf.get("token") == token else {})
        items["posizioni"].append({"indice": index, "token": token, "identita": identity})
    for index, row in enumerate(candidates):
        row = row if isinstance(row, dict) else {}
        token, valid = desk.wallet_symbol(row.get("token"))
        pair = row.get("coppia_analisi")
        key = row.get("kraken_pair_key")
        identity = econ.identify(token, pair, key, catalog=catalog if valid else {})
        items["candidati"].append({"indice": index, "token": token,
                                   "coppia_analisi": pair, "identita": identity})

    # Stable ID rotation: every verifiable project is acquired within
    # ceil(unique_ids / 6) refreshes, independently of release requests and
    # scanner rank. Persist only the next public project ID in the dossier.
    unique_ids = sorted({row["identita"]["coingecko_id"]
                         for group in items.values() for row in group
                         if row["identita"].get("coingecko_id")})
    prior = previous if isinstance(previous, dict) and previous.get("schema") == econ.VERSION else {}
    previous_next = prior.get("prossimo_id_fondamentali")
    start_at = next((i for i, cg in enumerate(unique_ids)
                     if isinstance(previous_next, str) and cg >= previous_next), 0)
    selected = [unique_ids[(start_at+i) % len(unique_ids)]
                for i in range(min(6, len(unique_ids)))]
    selected_ids = set(selected)
    next_id = (unique_ids[(start_at+len(selected)) % len(unique_ids)]
               if unique_ids else None)

    # Reuse only facts already acquired and validated locally, bound to this
    # token, exact Kraken pair and CoinGecko ID, with unchanged upstream time.
    # A cache hit is labelled and never refreshed merely by re-reading it.
    previous_cache = {}
    prior_time = econ.stamp(prior.get("acquisito_utc"))
    if prior_time and dt.timedelta(0) <= now-prior_time <= dt.timedelta(days=1):
        for group in ("posizioni", "candidati"):
            for old in prior.get(group, []):
                if not isinstance(old, dict):
                    continue
                ident = old.get("identita") or {}
                data = old.get("fondamentali") or {}
                if not isinstance(ident, dict) or not isinstance(data, dict):
                    continue
                when = econ.stamp(data.get("rilevato_utc"))
                acquired = econ.stamp(data.get("acquisito_utc"))
                if (data.get("stato") == "VERIFICATO"
                        and when and acquired and acquired <= now
                        and dt.timedelta(0) <= now-when <= dt.timedelta(days=1)
                        and data.get("fonte") == econ.CG + str(ident.get("coingecko_id"))
                        and ident.get("stato") == "IDENTITA_VERIFICATA_DA_CATALOGO"):
                    key = (ident.get("token"), ident.get("coppia"),
                           ident.get("pair_key"), ident.get("coingecko_id"))
                    previous_cache[key] = data

    cache, release_cache = {}, {}
    cg_calls, release_calls = 0, 0
    for cg in selected:
        cg_calls += 1
        try:
            url = (econ.CG + cg +
                   "?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false")
            cache[cg] = json.loads(desk.request(url, timeout=12).decode("utf-8"))
        except (ValueError, OSError, RuntimeError, KeyError, TypeError):
            cache[cg] = None
        time.sleep(.35)
    projects = sorted({row["identita"]["repository_primario"]
                       for group in items.values() for row in group
                       if row["identita"].get("repository_primario")})
    for repo in projects[:3]:
        release_calls += 1
        try:
            url = "https://api.github.com/repos/" + repo + "/releases/latest"
            release_cache[repo] = json.loads(desk.request(url, timeout=10).decode("utf-8"))
        except (ValueError, OSError, RuntimeError, KeyError, TypeError):
            release_cache[repo] = None

    for group in ("posizioni", "candidati"):
        for row in items[group]:
            identity = row["identita"]
            cg = identity.get("coingecko_id")
            if cg is None:
                fundamental = dict(econ.fundamentals(identity, None, now, now),
                                   stato="NON_VERIFICATO_IDENTITA")
            else:
                fresh = econ.fundamentals(identity, cache.get(cg), now, now)
                old_key = (identity.get("token"), identity.get("coppia"),
                           identity.get("pair_key"), cg)
                if fresh["stato"] == "VERIFICATO":
                    fundamental = dict(fresh, origine="ACQUISIZIONE_PUBBLICA")
                elif old_key in previous_cache:
                    fundamental = dict(previous_cache[old_key],
                                       origine="CACHE_LOCALE_FONTE_PUBBLICA",
                                       riutilizzato_utc=now.isoformat(timespec="seconds"))
                elif cg not in selected_ids:
                    fundamental = dict(fresh, stato="NON_ACQUISITO_PER_BUDGET")
                elif cache.get(cg) is None:
                    fundamental = dict(fresh, stato="NON_DISPONIBILE_FONTE")
                else:
                    fundamental = fresh
            row["fondamentali"] = fundamental
            repo = identity.get("repository_primario")
            row["evento"] = econ.release_event(identity, release_cache.get(repo), now, now)
            row["lettura_economica"] = econ.decision_context(
                identity, row["fondamentali"], row["evento"])

    btc = next((r for r in four_rows if isinstance(r, dict) and r.get("token") == "BTC"), {})
    return {"schema": econ.VERSION, "acquisito_utc": now.isoformat(timespec="seconds"),
            "posizioni": items["posizioni"], "candidati": items["candidati"],
            "macro": econ.macro(source.get("feed"), now),
            "regime": econ.regime(btc, (source.get("coingecko_global") or {}), now),
            "fonti_economiche": econ.sources_matrix(),
            "prossimo_id_fondamentali": next_id,
            "richieste_coingecko": cg_calls, "richieste_release": release_calls,
            "richieste_esterne_massime": 9,
            "richieste_effettuate": cg_calls+release_calls,
            "limite": "Nessun afflusso istituzionale, ordine, unlock o effetto macro dedotto"}


def collect(source=None, *, asset_pairs=None):
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
            row["kraken_pair_key"] = matching.get("pair_key")
            row["ultimo_prezzo_in_quote"]=matching.get("prezzo_quote")
            try:
                result=desk.kraken('OHLC',pair=matching["pair_key"],interval=15)
                candles=next(v for k,v in result.items() if k!='last')
                row["livelli_15m"]=summarize_candles(candles,900,now.timestamp())
                time.sleep(.6)
                result=desk.kraken('OHLC',pair=matching["pair_key"],interval=60)
                candles=next(v for k,v in result.items() if k!='last')
                row["livelli_1h"]=summarize_candles(candles,3600,now.timestamp())
            except Exception as exc:
                row["limite_livelli"]=type(exc).__name__+": "+str(exc)[:120]
        if matching:
            row["flusso_spot_kraken"]=flusso_spot.fetch(
                base_pair,matching["pair_key"],
                chiusura_15m_utc=(row.get("livelli_15m") or {}).get("ultima_chiusura_utc"))
            time.sleep(.8)
        else:
            row["flusso_spot_kraken"]={
                "stato":"NON_DISPONIBILE","motivo":"Coppia di riferimento non valida"}
        if row["token"] in COINGECKO_IDS:
            try: row["fondamentali_coingecko"]=token_fundamentals(row["token"])
            except Exception as exc: row["fondamentali_coingecko"]={"errore":type(exc).__name__}
        else:
            row["fondamentali_coingecko"]={
                "stato":"ID token non validato su CoinGecko: nessun dato fondamentale attribuito"}
        # KDD-11: candidate shortlist does not carry the verified four-frame
        # closed OHLCV series. Never promote 15m/1H level summaries to patterns.
        row["figure_candlestick"] = {
            "stato": "NON_DISPONIBILE",
            "motivo": "Serie OHLCV chiuse 4TF non attestata per candidato nel dossier",
            "coppia": row.get("coppia_analisi"),
            "fonte": "Nessuna serie verificata per riconoscimento KDD-11"}
        candidates.append(row)
        time.sleep(.5)
    # Campione 4H anche dei quattro asset strategici (non solo gainer).
    # Kraken restituisce la candela 4H corrente: esclusa esplicitamente.
    quattro_ore=recupera_4h(source,candidates,now.timestamp())
    for row in candidates:
        obs=quattro_ore.get(row["token"],{})
        if obs.get("coppia") == row.get("coppia_analisi"):
            row["livelli_4h"]=dict(obs.get("lettura_indicativa") or {},
                                   stato=obs.get("stato","NON_DISPONIBILE"),
                                   coppia=obs.get("coppia"),
                                   serie_numerica="grafici_4h["+row["token"]+"]")
        else:
            row["livelli_4h"]={"stato":"COPPIA_DIVERSA_O_ASSENTE",
                               "coppia_analisi":row.get("coppia_analisi"),
                               "coppia_4h_osservata":obs.get("coppia"),
                               "nota":"Non associare livelli 4H di coppie differenti "
                                      "alla coppia operativa senza esplicitarlo."}
    external={}
    try: external["coingecko_global"]=global_context()
    except Exception as exc: external["coingecko_global"]={"errore":type(exc).__name__+": "+str(exc)[:80]}
    derivatives=derivatives_context(now.timestamp())
    # Same D1/D2 validation as dashboard, applied to this actual wallet read.
    # A market snapshot time is not proof of wallet identity or freshness.
    portafoglio = desk.load('portafoglio.json', {})
    qualita = desk.qualita_portafoglio(source, portafoglio)
    saldo = qualita["stato_saldo"]
    fonte = portafoglio.get("fonte_quantita") if isinstance(portafoglio, dict) else None
    import patrimonio_4tf
    # One actual public AssetPairs snapshot shared by 4TF and economics.
    if asset_pairs is None:
        try:
            asset_pairs = desk.kraken("AssetPairs")
        except (OSError, RuntimeError, TypeError, ValueError, KeyError):
            asset_pairs = {}
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
        saldo_recente=qualita.get("saldo_recente_verificato", False))
    economic = economic_evidence(source, portafoglio, analisi_patrimonio, candidates, now,
                                 asset_pairs=asset_pairs, previous=previous_economic)
    # Global market data is obtained independently and may be unavailable.
    import kdd_economics as econ
    btc = next((r for r in (analisi_patrimonio.get("posizioni") or [])
                if r.get("token") == "BTC"), {})
    economic["regime"] = econ.regime(btc, external.get("coingecko_global"), now)
    dossier={
        "schema":3,"creato_utc":desk.NOW().isoformat(timespec="seconds"),
        "kraken_istantanea_utc":source["rilevazione_utc"],"eta_kraken_minuti_al_dossier":round(age,2),
        "regime":{"trend_eur":source.get("trends",{}),"btc_spot_eur":source.get("markets",{}).get("BTC")},
        "candidati":candidates,"grafici_4h":quattro_ore,
        "evidenze_economiche":economic,
        "patrimonio_4tf":analisi_patrimonio,
        "finanziamento_150_book_pubblico":finanziamento_book,
        "ricerca_setup":source.get("ricerca_setup",{}),
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
