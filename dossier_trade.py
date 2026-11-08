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


def economic_evidence(source, wallet, four, candidates, now):
    """One bounded, read-only source chain; every asset retains a row."""
    import kdd_economics as econ
    items = {"posizioni": [], "candidati": []}
    wallet_rows = wallet.get("posizioni") if isinstance(wallet, dict) else None
    wallet_rows = wallet_rows if isinstance(wallet_rows, list) else []
    for index, row in enumerate(wallet_rows):
        tf = (four.get("posizioni") or [])[index] if index < len(four.get("posizioni") or []) else {}
        token, valid = desk.wallet_symbol(row.get("token") if isinstance(row, dict) else None)
        identity = econ.identify(token, tf.get("coppia"), tf.get("pair_key"),
                                 catalog_verified=bool(valid and tf.get("asset_base") in (
                                     token, "XBT" if token == "BTC" else token)))
        items["posizioni"].append({"indice": index, "token": token, "identita": identity})
    for index, row in enumerate(candidates):
        token = row.get("token")
        pair = row.get("coppia_analisi")
        key = row.get("kraken_pair_key")
        identity = econ.identify(token, pair, key,
                                 catalog_verified=bool(key and pair == row.get("coppia_analisi")))
        items["candidati"].append({"indice": index, "token": token,
                                   "coppia_analisi": pair, "identita": identity})
    # Candidate and owned asset coverage share one cache and one request budget.
    # No unverified ticker can consume the budget or inherit another project's data.
    cache, calls = {}, 0
    priority = items["candidati"][:1] + items["posizioni"] + items["candidati"][1:]
    for row in priority:
        identity = row["identita"]
        cg = identity.get("coingecko_id")
        if not cg:
            row["fondamentali"] = econ.fundamentals(identity, None, now, now)
            row["evento"] = econ.release_event(identity, None, now, now)
            row["lettura_economica"] = econ.decision_context(
                identity, row["fondamentali"], row["evento"])
            continue
        if cg not in cache:
            if calls < 6:
                calls += 1
                try:
                    url = (econ.CG + cg +
                           "?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false")
                    cache[cg] = json.loads(desk.request(url, timeout=12).decode("utf-8"))
                except (ValueError, OSError, RuntimeError, KeyError, TypeError):
                    cache[cg] = None
                time.sleep(.35)
            else:
                cache[cg] = None
        row["fondamentali"] = econ.fundamentals(identity, cache[cg], now, now)
        repo = identity.get("repository_primario")
        release = None
        if repo and calls < 9:
            calls += 1
            try:
                url = "https://api.github.com/repos/" + repo + "/releases/latest"
                release = json.loads(desk.request(url, timeout=10).decode("utf-8"))
            except (ValueError, OSError, RuntimeError, KeyError, TypeError):
                pass
        row["evento"] = econ.release_event(identity, release, now, now)
        row["lettura_economica"] = econ.decision_context(
            identity, row["fondamentali"], row["evento"])
    btc = next((r for r in (four.get("posizioni") or []) if r.get("token") == "BTC"), {})
    return {"schema": econ.VERSION, "acquisito_utc": now.isoformat(timespec="seconds"),
            "posizioni": items["posizioni"], "candidati": items["candidati"],
            "macro": econ.macro(source.get("feed"), now),
            "regime": econ.regime(btc, (source.get("coingecko_global") or {}), now),
            "richieste_esterne_massime": 9, "richieste_effettuate": calls,
            "limite": "Nessun consiglio, prezzo futuro, unlock o impatto macro dedotto"}


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
    analisi_patrimonio = patrimonio_4tf.collect(
        portafoglio, source, asset_pairs=asset_pairs,
        now=now, old_4h=quattro_ore)
    finanziamento_book = finanziamento_150_book(
        dict(source, _verified_asset_pairs=asset_pairs), portafoglio,
        saldo_recente=qualita.get("saldo_recente_verificato", False))
    economic = economic_evidence(source, portafoglio, analisi_patrimonio, candidates, now)
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
