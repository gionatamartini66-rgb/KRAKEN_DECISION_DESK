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


def sample(markets, scanner, size=MAX_SCREEN):
    """Stratificazione 5 contesti giornalieri × 3 fasce di liquidità.

    Il dato ticker è la prima fotografia, non la prova di una ripartenza.
    La fascia esplorativa amplia la COPERTURA, ma richiede un book verificato
    e non può diventare automaticamente una proposta operativa.
    """
    if not isinstance(size,int) or not (0 <= size <= MAX_SCREEN):
        raise ValueError('Budget massimo campione: '+str(MAX_SCREEN))
    min_volume=float(scanner.get('volume_24h_min_eur',500000))
    max_spread=float(scanner.get('spread_massimo_pct',0.8))
    # Il filtro operativo del book resta quello delle schede precedenti.
    # Per ricerca si consente una fascia più piccola, con spread più severo.
    lower_volume=min(150_000,min_volume)
    grouped={(b,t):[] for b in BUCKETS for t in LIQUIDITY_TIERS}
    for row in markets.values():
        try:
            vol=float(row['volume_24h_eur_stimato'])
            spread=float(row['spread_pct'])
            change=float(row['var_oggi_utc_pct'])
            price=float(row['prezzo_eur'])
        except (KeyError,TypeError,ValueError,OverflowError):continue
        if not all(math.isfinite(x) for x in (vol,spread,change,price)):continue
        if vol<lower_volume or not (0<=spread<=max_spread) or price<=0:
            continue
        if vol<350_000 and spread>min(max_spread,0.35):
            continue
        if row.get('token') in NON_NEGOZIABILI_SEE or row.get('token') in ('BTC','ETH'):
            continue
        r=dict(row,fascia_liquidita=tier(vol))
        grouped[(bucket(change),r['fascia_liquidita'])].append(r)
    for group in grouped.values():
        group.sort(key=lambda r:(-r['volume_24h_eur_stimato']/(1+r['spread_pct']*3),
                                 r['token']))
    chosen=[]
    count_tier={t:0 for t in LIQUIDITY_TIERS}
    # La fascia sperimentale non può occupare tutto il radar:
    # massimo sei mercati sotto 350k EUR/24h, e solo a spread stretto.
    exploratory_cap=6
    # Ogni giro da spazio ai movimenti piccoli, ai laterali e alle tre fasce.
    # Non si sceglie prima 24 high-cap e poi si dice che non c'è altro.
    while len(chosen)<size and any(grouped.values()):
        before=len(chosen)
        for b in BUCKETS:
            for t in LIQUIDITY_TIERS:
                if len(chosen)>=size:break
                if t=='esplorativa' and count_tier[t]>=exploratory_cap:
                    continue
                group=grouped[(b,t)]
                if group:
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
    return {'stato':'OSSERVATO','categoria':category,'motivo':reason,
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
    groups=('tentativo di ripartenza','consolidamento',
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
                         'perche':obs['motivo'],'preselezione':obs})
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


def scan(markets, scanner, kraken, now, max_requests=MAX_SCREEN):
    pool=sample(markets,scanner,size=max_requests)
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
    return chosen,{'campionati':len(pool),'analizzati':len(pool)-len(issues),
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
                   'ambito':'24 o meno token: 5 gruppi giornalieri × 3 fasce liquidità; opportunità non esaustive, non segnali di acquisto',
                   'restrizioni_see_note':NON_NEGOZIABILI_SEE,
                   'negoziabilita_personale':'NON VERIFICATA: controllo finale nella app Kraken Pro richiesto'},hourly_cache
