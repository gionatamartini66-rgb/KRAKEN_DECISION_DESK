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


def collect(source=None):
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
    dossier={
        "schema":1,"creato_utc":desk.NOW().isoformat(timespec="seconds"),
        "kraken_istantanea_utc":source["rilevazione_utc"],"eta_kraken_minuti_al_dossier":round(age,2),
        "regime":{"trend_eur":source.get("trends",{}),"btc_spot_eur":source.get("markets",{}).get("BTC")},
        "candidati":candidates,"grafici_4h":quattro_ore,
        "ricerca_setup":source.get("ricerca_setup",{}),
        "fonti_esterne":external,
        "contesto_derivati_btc":derivatives,
        "contesto_macro_news":"Ricerca GPT separata: non inferire macro dai soli RSS",
        "portafoglio_quantita_fonte":desk.load("portafoglio.json",{}).get("fonte_quantita"),
        "portafoglio_aggiornato_da_api_private":False,
        "portafoglio_noto":all(x.get("quantita") is not None
                                for x in desk.load("portafoglio.json",{"posizioni":[]}).get("posizioni",[]))
                             and bool(desk.load("portafoglio.json",{"posizioni":[]}).get("posizioni",[])),
        "limiti":["Campione dello scanner, non ricerca esaustiva di tutti i token.",
                  "Candele chiuse; supporti/resistenze solo estremi storici, non segnali validati.",
                  "OI/CVD Futures Kraken BTC non disponibili per ogni token e non aggregati globali.",
                  "Flusso buy/sell spot recente da Kraken Trades: al piu 1000 esecuzioni per coppia; NON CVD storico, heatmap o mercato aggregato. Copertura e lacune per token indicate.",
                  "Quantità manuali trascritte da screenshot Kraken Pro, non lette automaticamente; saldo EUR liberamente utilizzabile, precisione dei saldi e costi di carico non verificati; nessun sizing del patrimonio disponibile.",
                  "Nessun ordine o controllo privato della negoziabilità SEE."]
    }
    desk.save("dossier_multifonte.json",dossier)
    return dossier


if __name__=="__main__":
    x=collect()
    print("DOSSIER_SAVED",x["creato_utc"],"CANDIDATES",
          [(y["token"],y["coppia_analisi"],y.get("ultimo_prezzo_in_quote")) for y in x["candidati"]])
    print("EXTERNAL",x["fonti_esterne"])
    print("BTC_FUTURES",x["contesto_derivati_btc"])
