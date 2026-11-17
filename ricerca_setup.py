"""Ricerca spot a due fasi: ticker liquidi -> campione 1h -> pochi setup per esame.
Non predice rendimenti, non verifica ordini/account né produce suggerimenti GPT.
"""
import datetime as dt
import math
import statistics
import time
import analisi_v02 as technical

BUCKETS=('correzione','laterale','inizio','rialzo','esteso')
MAX_SCREEN=24
MAX_FINAL=4
LIQUIDITY_TIERS=('alta','media','esplorativa')
# Kraken conferma il delisting XMR per tutti i clienti SEE (31/10/2024).
# AssetPairs globale non assicura negoziabilita in Italia.
NON_NEGOZIABILI_SEE={
    'XMR': 'https://support.kraken.com/it/articles/support-for-monero-xmr-in-europe'
}


def bucket(pct):
    if pct < -0.75:return 'correzione'
    if pct < 1.5:return 'laterale'
    if pct < 8:return 'inizio'
    if pct < 20:return 'rialzo'
    return 'esteso'


def tier(volume):
    if volume >= 1_000_000:return 'alta'
    if volume >= 350_000:return 'media'
    return 'esplorativa'


def eligible_markets(markets, scanner):
    """Observe the complete ticker-based universe; OHLC is a separate, bounded phase.

    The effective search thresholds are the existing user configuration and
    legacy exploratory-spread policy. No fixed volume target is introduced.
    """
    min_volume=float(scanner.get('volume_24h_min_eur',500000))
    max_spread=float(scanner.get('spread_massimo_pct',0.8))
    lower_volume=min(150_000,min_volume)
    groups={(b,t):[] for b in BUCKETS for t in LIQUIDITY_TIERS}
    exclusions={}
    excluded_examples={}
    for token,row in markets.items():
        reason=None
        if not isinstance(row,dict) or row.get('token')!=token or not row.get('pair_key'):
            reason='IDENTITA_NON_VERIFICABILE'
        elif token in NON_NEGOZIABILI_SEE:
            reason='RESTRIZIONE_SEE_DOCUMENTATA'
        elif token in ('BTC','ETH'):
            reason='BENCHMARK_NON_CANDIDATO'
        else:
            try:
                vol=float(row['volume_24h_eur_stimato'])
                spread=float(row['spread_pct'])
                change=float(row['var_oggi_utc_pct'])
                price=float(row['prezzo_eur'])
                if not all(math.isfinite(x) for x in (vol,spread,change,price)) or price<=0:
                    reason='DATI_TICKER_NON_VERIFICABILI'
                elif vol<lower_volume:
                    reason='VOLUME_SOTTO_FILTRO_RICERCA'
                elif not 0<=spread<=max_spread:
                    reason='SPREAD_OLTRE_FILTRO'
                elif vol<350_000 and spread>min(max_spread,0.35):
                    reason='FASCIA_ESPLORATIVA_SPREAD'
                else:
                    r=dict(row,fascia_liquidita=tier(vol))
                    groups[(bucket(change),r['fascia_liquidita'])].append(r)
            except (KeyError,TypeError,ValueError,OverflowError):
                reason='DATI_TICKER_NON_VERIFICABILI'
        if reason:
            exclusions[reason]=exclusions.get(reason,0)+1
            if len(excluded_examples.setdefault(reason,[]))<6:
                excluded_examples[reason].append(str(token))
    return groups,exclusions,excluded_examples


def sample(markets, scanner, size=MAX_SCREEN, *, previous=None):
    """Fair bounded rotation across all eligible Spot assets in successive cycles.

    Never-seen eligible pairs precede recently scanned pairs within each
    daily-context/liquidity bucket. A changed pair identity resets the visit.
    Visible ticker anomalies affect priority only *among equally old* visits;
    they cannot indefinitely displace a market never yet examined.
    """
    if not isinstance(size,int) or not (0<=size<=MAX_SCREEN):
        raise ValueError('Budget massimo campione: '+str(MAX_SCREEN))
    groups,_,_=eligible_markets(markets,scanner)
    previous=previous if isinstance(previous,dict) else {}
    visits=previous.get('ultime_analisi') if isinstance(previous.get('ultime_analisi'),dict) else {}
    prior_ticker=previous.get('ticker_precedente') if isinstance(previous.get('ticker_precedente'),dict) else {}
    def priority(row):
        token=row['token']
        previous_visit=visits.get(token)
        seen=(previous_visit.get('ciclo') if isinstance(previous_visit,dict)
              and previous_visit.get('pair_key')==row['pair_key']
              and type(previous_visit.get('ciclo')) is int else -1)
        old=prior_ticker.get(token) or {}
        anomaly=0
        try:
            if old.get('pair_key')==row['pair_key']:
                change=abs(row['var_oggi_utc_pct']-old['variazione_pct'])
                volume_ratio=(row['volume_24h_eur_stimato']/old['volume_eur']
                              if old.get('volume_eur',0)>0 else 1)
                anomaly=int(change>=4)+int(volume_ratio>=2)
        except (KeyError,TypeError,ValueError,ZeroDivisionError,OverflowError):
            anomaly=0
        return (seen,-anomaly,
                -row['volume_24h_eur_stimato']/(1+row['spread_pct']*3),token)
    for group in groups.values():
        group.sort(key=priority)
    chosen=[]
    count_tier={t:0 for t in LIQUIDITY_TIERS}
    # First use all available never-scanned markets across EVERY stratum.
    # Otherwise a rare bucket with one frequently observed asset consumes a
    # request each refresh while other buckets still contain unseen markets.
    # Only when new identities are exhausted for the chosen per-cycle budget
    # may the scanner revisit older rows, least recently visited first.
    for allow_repeat in (False,True):
        while len(chosen)<size and any(groups.values()):
            before=len(chosen)
            for b in BUCKETS:
                for t in LIQUIDITY_TIERS:
                    if len(chosen)>=size:break
                    if t=='esplorativa' and count_tier[t]>=6:continue
                    group=groups[(b,t)]
                    if not group:continue
                    if not allow_repeat and priority(group[0])[0]>=0:
                        continue
                    chosen.append(group.pop(0))
                    count_tier[t]+=1
                if len(chosen)>=size:break
            if len(chosen)==before:break
    return chosen


def geometry(raw, now):
    """Geometria delle ultime 24 ore CHIUSE, 1h; niente candela in corso."""
    bars=technical.closed_bars(raw,now=now,interval_sec=3600)
    if len(bars)<33:return {'stato':'DATI_INSUFFICIENTI',
                            'motivo':'Servono almeno 33 candele orarie chiuse'}
    recent=bars[-33:]
    try:
        candles=[{'t':int(x[0]), 'high':float(x[2]),'low':float(x[3]),
                  'close':float(x[4]),'volume':float(x[6])} for x in recent]
        for c in candles:
            if (not all(math.isfinite(c[k]) and c[k]>0 for k in ('high','low','close'))
                or not (c['low']<=c['close']<=c['high']) or c['volume']<0 or
                not math.isfinite(c['volume'])):
                raise ValueError('Candela incoerente')
        if any(candles[i]['t']-candles[i-1]['t']!=3600 for i in range(1,len(candles))):
            return {'stato':'DATI_INSUFFICIENTI','motivo':'Intervalli orari con lacune'}
    except (TypeError,KeyError,ValueError,OverflowError,IndexError):
        return {'stato':'DATI_INSUFFICIENTI','motivo':'OHLC non valido'}
    last=candles[-1]
    window=candles[-25:]
    def change(a,b):return 100*(a/b-1) if b>0 else None
    def width(part):return 100*(max(x['high'] for x in part)-min(x['low'] for x in part))/last['close']
    volnow=sum(x['volume'] for x in candles[-4:])
    volpast=sum(x['volume'] for x in candles[-8:-4])
    volume_ratio=volnow/volpast if volpast>0 else None
    now8=width(candles[-8:])
    prev8=width(candles[-16:-8])
    high24=max(x['high'] for x in window)
    low24=min(x['low'] for x in window)
    priorhigh=max(x['high'] for x in candles[-13:-1])
    priorlow=min(x['low'] for x in candles[-13:-1])
    ret24=change(last['close'],candles[-25]['close'])
    ret4=change(last['close'],candles[-5]['close'])
    drawdown=100*(last['close']/high24-1)
    narrowing=now8/prev8 if prev8>0 else None
    # Non chiamare il pattern confermato: serve verifica 15m+book e costi.
    category='nessun setup confermato'
    reason='Nessuna geometria 1h sufficiente per una configurazione preferita.'
    if ret4>=12:
        # Etichetta descrittiva, non previsione di inversione: dopo un +12%
        # in quattro ore non presentare il movimento come ancora iniziale.
        category='rialzo rapido già esteso'
        reason='Movimento >12% su 4h chiuse: non confondere un recupero veloce con un ingresso precoce.'
    elif (last['close']>priorhigh and ret4>0.75 and
          volume_ratio is not None and volume_ratio>=1.15 and ret24<18):
        category='tentativo di ripartenza'
        reason='Chiusura 1h oltre i massimi delle 12 ore precedenti, con volumi 4h in aumento.'
    elif (last['close']<priorlow and ret4< -0.75 and ret24< -2
          and volume_ratio is not None and volume_ratio>=1.12):
        category='pressione ribassista'
        reason='Chiusura 1h sotto i minimi precedenti e volumi in crescita: rischio di prosecuzione del calo, nessun invito allo short.'
    elif (ret24< -3 and 0.75<ret4<8 and
          volume_ratio is not None and volume_ratio>=1.08):
        category='transizione in recupero'
        reason='Recupero 4h dopo una discesa 24h, con volumi relativi: cambio di fase da verificare, non inversione confermata.'
    elif (narrowing is not None and narrowing<=0.68 and now8<=7.5
          and abs(ret4)<3.5 and -12<ret24<15):
        category='consolidamento'
        reason='Intervallo 8h più stretto del precedente; manca ancora una conferma di uscita.'
    elif (ret24>=3 and -7<ret4<-0.5 and drawdown>-12
          and (volume_ratio is None or volume_ratio<=1.2)):
        category='ritracciamento'
        reason='Trend positivo su 24h e correzione nelle ultime 4h senza accelerazione evidente dei volumi.'
    elif (0.75<ret4<8 and -6<ret24<12 and
          volume_ratio is not None and volume_ratio>=1.08):
        category='movimento iniziale'
        reason='Prime 4h positive su candele chiuse con volume superiore alle 4h precedenti.'
    regime=('RIBASSISTA' if ret24<=-3 and ret4<0 else
            'RIALZISTA' if ret24>=3 and ret4>0 else
            'LATERALE' if abs(ret24)<3 and abs(ret4)<1.5 else 'TRANSIZIONE')
    contra=[]
    if volume_ratio is None:contra.append('VOLUMI_RELATIVI_NON_VALUTABILI')
    elif volume_ratio<1:contra.append('VOLUMI_4H_INFERIORI_AL_PERIODO_PRECEDENTE')
    if ret4*ret24<0:contra.append('DIREZIONI_4H_E_24H_CONTRARIE')
    if category in ('tentativo di ripartenza','movimento iniziale','transizione in recupero'):
        invalidazione='Nuova chiusura sotto il minimo delle ultime 8h chiuse'
    elif category=='pressione ribassista':
        invalidazione='Nuova chiusura sopra il massimo delle ultime 8h chiuse'
    elif category=='consolidamento':
        invalidazione='Espansione del range 8h senza successiva conferma direzionale'
    elif category=='ritracciamento':
        invalidazione='Perdita del minimo delle ultime 8h con volumi in aumento'
    else:
        invalidazione='Nessuna configurazione confermata da invalidare'
    return {'stato':'OSSERVATO','categoria':category,'motivo':reason,
            'regime_osservato':regime,'segnali_contrari':contra,
            'invalidazione':invalidazione,
            'qualita_dati':'33_OHLC_1H_CHIUSE_CONTIGUE',
            'base_regime':'Variazioni 24h/4h da OHLC Kraken, non regime macro',
            'chiusura_1h_utc':dt.datetime.fromtimestamp(last['t']+3600,dt.timezone.utc).isoformat(),
            'var_24h_pct':round(ret24,3),'var_4h_pct':round(ret4,3),
            'range_8h_pct':round(now8,3),'range_8h_precedente_pct':round(prev8,3),
            'rapporto_ristrettezza':round(narrowing,3) if narrowing is not None else None,
            'volumi_4h_su_4h_precedenti':round(volume_ratio,3) if volume_ratio is not None else None,
            'distanza_massimo_24h_pct':round(drawdown,3),
            'prezzo_ultimo_close_quote':last['close'],
            'massimo_precedenti_12h_quote':priorhigh}


def select(rows, observations, max_items=MAX_FINAL):
    """Approfondire PRIMA tutte le configurazioni emerse (fino a quattro).

    Un caso senza configurazione può servire come controllo, ma non deve
    occupare il posto di una ripartenza/consolidamento da verificare.
    Ranking a parità di categoria = liquidità/spread, NON probabilità di profitto.
    """
    if not isinstance(max_items,int) or not (0<=max_items<=MAX_FINAL):
        raise ValueError('Massimo quattro approfondimenti')
    evaluated=[]
    for row in rows:
        observation=observations.get(row['token'],{})
        if observation.get('stato')!='OSSERVATO':continue
        score=math.log1p(row['volume_24h_eur_stimato'])-3*row['spread_pct']
        evaluated.append((score,row,observation))
    # Tie deterministico; classi a rischio falsi segnali restano ipotesi.
    evaluated.sort(key=lambda item:(-item[0],item[1]['token']))
    groups=('tentativo di ripartenza','pressione ribassista',
            'consolidamento','transizione in recupero',
            'ritracciamento','movimento iniziale')
    actual=[x for x in evaluated if x[2]['categoria'] in groups]
    neutral=[x for x in evaluated if x[2]['categoria']=='nessun setup confermato']
    selected=[]
    seen=set()
    def take(entry):
        _,r,obs=entry
        if r['token'] in seen or len(selected)>=max_items:return
        selected.append({'token':r['token'],'pair_key':r['pair_key'],
                         'categoria':obs['categoria'],
                         'perche':obs['motivo'],'preselezione':obs,
                         'regime_osservato':obs.get('regime_osservato'),
                         'segnali_contrari':obs.get('segnali_contrari',[]),
                         'invalidazione':obs.get('invalidazione'),
                         'qualita_dati':obs.get('qualita_dati')})
        seen.add(r['token'])
    # Uno per tipologia quando possibile.
    for category in groups:
        for item in actual:
            if item[2]['categoria']==category:
                take(item)
                break
    # Riempire con altri casi REALI della stessa classe prima di casi neutrali.
    for item in actual:
        take(item)
    # Quando ci sono almeno due candidati reali, non consumare book e costi
    # per casi senza configurazione. Con un solo candidato, un confronto;
    # se non emerge nulla, massimo due controlli negativi.
    max_neutral=0 if len(actual)>=2 else (1 if actual else 2)
    for item in neutral[:min(max_neutral,max_items-len(selected))]:
        take(item)
    return selected


def scan(markets, scanner, kraken, now, max_requests=MAX_SCREEN, *, previous=None):
    previous=previous if isinstance(previous,dict) else {}
    cycle=previous.get('ciclo',0)
    cycle=cycle+1 if type(cycle) is int and 0<=cycle<2**31 else 1
    grouped,excluded,examples=eligible_markets(markets,scanner)
    eligible={r['token']:r for members in grouped.values() for r in members}
    pool=sample(markets,scanner,size=max_requests,previous=previous)
    observations={}
    issues=[]
    hourly_cache={}
    for row in pool:
        try:
            result=kraken('OHLC',pair=row['pair_key'],interval=60)
            candles=next(v for k,v in result.items() if k!='last')
            hourly_cache[row['pair_key']]=candles
            observations[row['token']]=geometry(candles,now)
            if observations[row['token']]['stato']!='OSSERVATO':
                issues.append(row['token']+': '+observations[row['token']]['motivo'])
        except Exception as exc:
            observations[row['token']]={'stato':'DATI_INSUFFICIENTI','motivo':type(exc).__name__}
            issues.append(row['token']+': '+type(exc).__name__)
        time.sleep(0.85)
    chosen=select(pool,observations)
    now_iso=dt.datetime.fromtimestamp(now,dt.timezone.utc).isoformat(timespec='seconds')
    past=previous.get('ultime_analisi') if isinstance(previous.get('ultime_analisi'),dict) else {}
    visits={tok:v for tok,v in past.items() if tok in eligible
            and isinstance(v,dict) and v.get('pair_key')==eligible[tok]['pair_key']
            and type(v.get('ciclo')) is int}
    for row in pool:
        visits[row['token']]={'ciclo':cycle,'pair_key':row['pair_key'],
                              'esito':observations[row['token']]['stato']}
    ticker_base={tok:{'pair_key':row['pair_key'],
                        'volume_eur':row['volume_24h_eur_stimato'],
                        'variazione_pct':row['var_oggi_utc_pct']}
                 for tok,row in eligible.items()}
    seen=len(visits)
    total=len(eligible)
    for item in chosen:
        item['origine']='SCANNER_KRAKEN_1H'
        item['osservato_utc']=now_iso
        item['ciclo_scanner']=cycle
    return chosen,{'ciclo':cycle,'ultime_analisi':visits,
                   'ticker_precedente':ticker_base,
                   'mercati_osservati_ticker':len(markets),
                   'universo_ammissibile':total,
                   'universo_escluso':sum(excluded.values()),
                   'esclusioni_per_motivo':excluded,
                   'esclusioni_esempi':examples,
                   'ammissibili_non_campionati':total-len(pool),
                   'universo_esaminato_almeno_una_volta':seen,
                   'universo_mai_esaminato':total-seen,
                   'copertura_progressiva_pct':round(100*seen/total,2) if total else None,
                   'budget_ohlc_1h':max_requests,
                   'richieste_ohlc_1h':len(pool),
                   'campionati':len(pool),'analizzati':len(pool)-len(issues),
                   'scelti':len(chosen),
                   'fasce_esaminate':{t:sum(x['fascia_liquidita']==t for x in pool)
                                      for t in LIQUIDITY_TIERS},
                   'confronto_1h':[{'token':x['token'],'coppia':x['pair'],
                                    'fascia_liquidita':x['fascia_liquidita'],
                                    'variazione_oggi_pct':x['var_oggi_utc_pct'],
                                    'volume_coppia_24h_eur_stimato':round(x['volume_24h_eur_stimato']),
                                    'spread_ticker_pct':round(x['spread_pct'],4),
                                    'geometria':observations.get(x['token'],{})}
                                    for x in pool],
                   'categorie':[{'token':x['token'],'categoria':x['categoria']} for x in chosen],
                   'limiti':issues,
                   'ambito':'Massimo 24 OHLC 1h per ciclo, rotazione tra tutte le fasce; copertura progressiva solo dell universo ticker ammissibile, non dell intera lista Kraken senza filtro',
                   'restrizioni_see_note':NON_NEGOZIABILI_SEE,
                   'negoziabilita_personale':'NON VERIFICATA: controllo finale nella app Kraken Pro richiesto'},hourly_cache
