"""Aggressione buy/sell da ultime esecuzioni pubbliche Kraken Spot.

Misura una FINESTRA CONOSCIUTA di trade recenti, non CVD storico continuo,
derivati, tutti gli exchange, ordini a book, né previsione di direzione.
"""
import datetime as dt
import math
import decision_desk as desk

FULL_SECONDS=4*3600
SHORT_SECONDS=15*60
MAX_ROWS=1000
MAX_LAG_SECONDS=300


def iso(seconds):
    return dt.datetime.fromtimestamp(seconds,dt.timezone.utc).isoformat(timespec='seconds')


def subset(rows, lower):
    eligible=[x for x in rows if x['t']>=lower]
    buy=sum(x['qval'] for x in eligible if x['side']=='b')
    sell=sum(x['qval'] for x in eligible if x['side']=='s')
    return {'numero_trade':len(eligible),
            'acquisti_aggressivi_quote':round(buy,4),
            'vendite_aggressive_quote':round(sell,4),
            'delta_quote':round(buy-sell,4),
            'percentuale_netto_su_volume':round(100*(buy-sell)/(buy+sell),2)
               if buy+sell>0 else None}


def analyze(trades, now, pair, chiusura_15m_utc=None):
    """La finestra 4h e completa solo se il primo trade precede l'inizio."""
    if not trades:
        return {'stato':'NESSUNA_ESECUZIONE','coppia':pair,
                'motivo':'Nessun trade restituito dalla sorgente'}
    if len(trades)>MAX_ROWS:
        return {'stato':'SCHEMA_NON_VALIDO','coppia':pair,
                'motivo':'Numero esecuzioni oltre il limite richiesto'}
    clean=[]
    try:
        for x in trades:
            if len(x)<5 or x[3] not in ('b','s'):raise ValueError('Lato trade non riconosciuto')
            price=float(x[0]);quantity=float(x[1]);timestamp=float(x[2])
            if not all(math.isfinite(y) and y>0 for y in (price,quantity,timestamp)):
                raise ValueError('Esecuzione invalida')
            if timestamp>now+2:raise ValueError('Trade con timestamp futuro')
            clean.append({'t':timestamp,'qval':price*quantity,'side':x[3]})
        if any(clean[i]['t']<clean[i-1]['t'] for i in range(1,len(clean))):
            raise ValueError('Esecuzioni fuori ordine cronologico')
    except (IndexError,TypeError,ValueError,OverflowError) as exc:
        return {'stato':'SCHEMA_NON_VALIDO','coppia':pair,
                'motivo':type(exc).__name__+': '+str(exc)[:120]}
    oldest=clean[0]['t'];last=clean[-1]['t']
    lag=now-last
    if lag>MAX_LAG_SECONDS:
        return {'stato':'SCADUTO','coppia':pair,
                'primo_trade_utc':iso(oldest),'ultimo_trade_utc':iso(last),
                'ritardo_ultimo_trade_secondi':round(lag),
                'motivo':'Ultima esecuzione oltre 5 minuti fa: non idonea a conferme in tempo reale'}
    complete4=oldest<=now-FULL_SECONDS
    complete15=oldest<=now-SHORT_SECONDS
    outcome={'stato':('COMPLETO_4H' if complete4 else 'FINESTRA_4H_NON_COPERTA'),
            'coppia':pair,'fonte':'Kraken public Trades',
            'fonte_documentazione':'https://docs.kraken.com/api/docs/rest-api/get-recent-trades',
            'copertura':'UNA coppia Kraken SPOT, non derivati, non altri exchange',
            'unita':'valuta di quotazione '+pair.split('/')[-1],
            'numero_trade_ottenuti':len(clean),
            'primo_trade_utc':iso(oldest),'ultimo_trade_utc':iso(last),
            'ritardo_ultimo_trade_secondi':round(lag),
            'durata_campione_secondi':round(last-oldest),
            'finestra_4h_completa':complete4,
            'delta_4h':subset(clean,now-FULL_SECONDS) if complete4 else None,
            'finestra_15m_completa':complete15,
            'delta_15m':subset(clean,now-SHORT_SECONDS) if complete15 else None,
            'nota':'Delta firmato dei trade buy - sell (lato riportato da Kraken). '
                   'Le esecuzioni oltre il limite di 1000 possono troncare la finestra. '
                   'NON è un CVD cumulativo continuo e non dimostra acquisti futuri.'}
    # La finestra rolling 15m NON coincide in generale con l'ultima candela
    # OHLC 15m chiusa. Solo la seconda permette un confronto temporale
    # corretto fra delta eseguito e movimento della candela specifica.
    closed={'stato':'RIFERIMENTO_MANCANTE'}
    if chiusura_15m_utc is not None:
        try:
            end=dt.datetime.fromisoformat(chiusura_15m_utc.replace('Z','+00:00'))
            if end.tzinfo is None:
                raise ValueError('Timezone obbligatoria')
            end=end.timestamp()
            if not math.isfinite(end) or end>now or end<=0:
                raise ValueError('Fine candela non valida')
            start=end-SHORT_SECONDS
            covered=oldest<=start and last>=end
            closed={'stato':'COMPLETA' if covered else 'NON_COPERTA',
                    'inizio_utc':iso(start),'fine_utc':iso(end),
                    'misure':subset([t for t in clean if t['t']<end],start) if covered else None,
                    'nota':'Intervallo [inizio, fine) della candela chiusa, NON degli ultimi 15 minuti mobili.'}
        except (TypeError,ValueError,OverflowError,AttributeError) as exc:
            closed={'stato':'RIFERIMENTO_NON_VALIDO','motivo':type(exc).__name__}
    outcome['candela_15m_chiusa']=closed
    return outcome


def fetch(pair, pair_key, now=None, chiusura_15m_utc=None, *, fetcher=None):
    """Una chiamata pubblica. Timestamp acquisito DOPO la risposta HTTP.

    Il ciclo multifonte può impiegare diversi secondi: usare il timestamp
    dello snapshot iniziale qui farebbe apparire futuri trade autentici.
    """
    try:
        result=(fetcher or desk.kraken)('Trades',pair=pair_key,count=MAX_ROWS)
        observed=desk.NOW().timestamp() if now is None else now
        trades=next(v for k,v in result.items() if k!='last')
        outcome=analyze(trades,observed,pair,chiusura_15m_utc=chiusura_15m_utc)
        outcome['osservato_utc']=iso(observed)
        return outcome
    except Exception as exc:
        return {'stato':'NON_DISPONIBILE','coppia':pair,
                'errore':type(exc).__name__,'motivo':str(exc)[:130]}
