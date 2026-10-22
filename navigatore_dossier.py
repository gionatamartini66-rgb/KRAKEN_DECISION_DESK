"""KDD Point 4, bounded evidence-only SUI/EUR dossier.

Pure function over *supplied public-source snapshots*. Never opens files, network,
Kraken credentials, portfolio or orders. Designed as an adapter to the existing
KDD refresh/dossier and G2R2 on-chain report, without modifying either.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
from collections.abc import Mapping

from onchain_nav_core import utc, KINDS  # reuse the G2R2 chain-neutral contract

ASSET = 'SUI'
PAIR = 'SUI/EUR'
CHAIN = 'sui:mainnet'
ASSET_ID = '0x2::sui::SUI'
CHANNELS = ('mercato', 'multitimeframe', 'liquidita', 'costi', 'fondamentali',
            'onchain', 'notizie_token', 'macroeconomia', 'geopolitica')
REPORTED = 'RIPORTATO_DA_SNAPSHOT_PUBBLICO_NON_RIVERIFICATO'
FIXTURE = 'FIXTURE_SINTETICA'
UNAVAILABLE = 'NON_DISPONIBILE'
PROHIBITED = ('BUY/SELL automatico', 'Previsioni o probabilita arbitrarie',
              'Staking = acquisto', 'Unstaking = vendita',
              'Unlock = vendita', 'RSS = analisi macroeconomica',
              'Volumi Binance = liquidita eseguibile su Kraken')


def _time(value):
    try:
        s = utc(value)
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError('timestamp UTC esplicito non valido') from exc


def _number(x, name, *, strictly_positive=False):
    if isinstance(x, bool):
        raise ValueError(f'{name}: booleano non ammesso')
    try:
        val = Decimal(str(x))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f'{name}: numero non valido') from exc
    if not val.is_finite() or val < 0 or (strictly_positive and not val):
        raise ValueError(f'{name}: numero non valido')
    return str(val)


def _section(status=UNAVAILABLE, *, source=None, observed_utc=None, coverage=None,
             evidence=None, compatible=(), alternative=(), limits=()):
    return {'status': status, 'source': source, 'observed_utc': observed_utc,
            'coverage': coverage, 'evidence': evidence, 'compatible': list(compatible),
            'alternative': list(alternative), 'limits': list(limits)}


def _market(snapshot, provenance):
    if not isinstance(snapshot, Mapping):
        return _section(limits=('Snapshot pubblico Kraken non fornito.',))
    rows = snapshot.get('markets')
    if not isinstance(rows, Mapping):
        return _section(limits=('markets assente o malformato.',))
    row = rows.get(ASSET)
    if not isinstance(row, Mapping) or row.get('token') != ASSET or row.get('pair') != PAIR:
        return _section(status='IDENTITA_NON_VERIFICATA',
                        limits=('La coppia SUI/EUR deve essere esplicita; il solo ticker non basta.',))
    try:
        when = _time(snapshot['rilevazione_utc'])
        fields = {'prezzo_eur': _number(row['prezzo_eur'], 'prezzo', strictly_positive=True),
                  'spread_pct': _number(row['spread_pct'], 'spread'),
                  'volume_24h_eur_stimato': _number(row['volume_24h_eur_stimato'], 'volume')}
        if 'costo_min_eur' in row:
            fields['costo_min_eur'] = _number(row['costo_min_eur'], 'costo minimo')
        if 'quantita_min' in row:
            fields['quantita_min'] = _number(row['quantita_min'], 'quantita minima')
    except (ValueError, KeyError) as exc:
        return _section(status='RISPOSTA_INCOMPLETA', limits=(str(exc),))
    return _section(provenance, source='Kraken Spot REST pubblico, snapshot esistente KDD',
        observed_utc=when.isoformat().replace('+00:00', 'Z'),
        coverage='Sola coppia spot SUI/EUR; prezzo indicativo e stima volume 24h.',
        evidence={'asset':ASSET,'pair':PAIR,**fields},
        compatible=('Prezzo e spread descrivono il mercato al momento della rilevazione.',),
        alternative=('Il volume 24h stimato non e profondita eseguibile.',),
        limits=('Non certifica tradabilita in Italia, fee, slippage o prezzo di ordine.',
                'Variazione giornaliera e volume rolling 24h sono finestre diverse.'))


def _card(dossier):
    if not isinstance(dossier, Mapping):
        return None
    cards = dossier.get('candidati')
    if not isinstance(cards, list):
        return None
    for row in cards:
        if isinstance(row, Mapping) and row.get('token') == ASSET and row.get('coppia_analisi') == PAIR:
            return row
    return None


def _timeframes(dossier, provenance):
    card = _card(dossier)
    graph = dossier.get('grafici_4h', {}) if isinstance(dossier, Mapping) else {}
    four = graph.get(ASSET) if isinstance(graph, Mapping) else None
    periods = {}
    if isinstance(card, Mapping):
        for key, label in (('livelli_15m', '15m'), ('livelli_1h', '1H')):
            part = card.get(key)
            if not isinstance(part, Mapping):
                continue
            try:
                t = _time(part['ultima_chiusura_utc'])
                last = (part.get('ultime_candele') or [])[-1]
                close = _number(last['chiusura'], label+' close', strictly_positive=True)
            except (ValueError, KeyError, IndexError, TypeError):
                continue
            periods[label] = {'last_closed_utc':t.isoformat().replace('+00:00', 'Z'),
                              'close_eur':close,'source':'Kraken OHLC, dossier_trade'}
    if isinstance(four, Mapping) and four.get('stato') == 'OK' and four.get('coppia') == PAIR:
        indicative = four.get('lettura_indicativa')
        series = four.get('serie_ohlcv_chiuse')
        try:
            if not isinstance(indicative, Mapping) or not isinstance(series,list) or not series:
                raise ValueError('4H incomplete')
            close_t = _time(indicative['ultima_chiusura_utc'])
            close = _number(series[-1]['close'], '4H close', strictly_positive=True)
            # Reject an unproven linkage between chart extract and close marker.
            start = series[-1].get('apertura_ts_utc')
            if not isinstance(start, int) or start+14400 != int(close_t.timestamp()):
                raise ValueError('4H closing marker differs from last bar')
            periods['4H'] = {'last_closed_utc':close_t.isoformat().replace('+00:00', 'Z'),
                             'close_eur':close, 'closed_bars':len(series),
                             'source':'Kraken Spot OHLC 240, dossier_trade'}
        except (KeyError, TypeError, ValueError):
            pass
    if not periods:
        return _section(limits=('Nessuna serie OHLC chiusa SUI/EUR validabile da dossier esistente.',))
    missing = tuple(x for x in ('15m','1H','4H','1D') if x not in periods)
    return _section(provenance, source='dossier_trade.py + analisi_v02.py, da Kraken pubblico',
        observed_utc=max(v['last_closed_utc'] for v in periods.values()),
        coverage='Candele chiuse per '+','.join(periods), evidence=periods,
        alternative=('Confluenze tecniche non equivalgono a probabilita di rendimento.',),
        limits=tuple('Timeframe assente: '+x for x in missing)+
               ('Le chiusure di timeframe differenti non sono istanti identici.',))


def _liquidity(market, card, provenance):
    if market['evidence'] is None:
        return _section(limits=('Manca una coppia SUI/EUR verificabile.',))
    values={k:market['evidence'][k] for k in ('spread_pct', 'volume_24h_eur_stimato')}
    src='mercati_spot.py / decision_desk.py: Kraken ticker pubblico'
    if isinstance(card, Mapping) and isinstance(card.get('book'), Mapping):
        try:
            book = card['book']
            values.update({key:_number(book[key],key) for key in
                           ('spread_book_pct','profondita_bid10_eur','profondita_ask10_eur')})
            src+='; analisi_v02.book_metrics (Depth 10)'
            # No acquisition timestamp for depth in the existing dossier.
            values['book_acquired_utc']=None
        except (KeyError,ValueError):
            pass
    return _section(provenance, source=src,observed_utc=market['observed_utc'],
        coverage='Timestamp riferito al ticker; ora del book top-10 non dimostrata.',evidence=values,
        alternative=('Book modificabile; volume 24h non e profondita corrente.',),
        limits=('Non misura slippage eseguibile senza importo e libro fresco.',
                'Kraken resta mercato di esecuzione, non Binance.',
                'Book non allineabile temporalmente senza il suo timestamp autonomo.'))


def _costs(card, market, provenance):
    if market['evidence'] is None:
        return _section(limits=('Coppia spot non verificata.',))
    if not isinstance(card, Mapping):
        return _section(limits=('SUI non compare tra le schede candidate del dossier preesistente.',))
    rows=card.get('simulazione_costi_eur_wallet')
    if not isinstance(rows,list):
        return _section(limits=('Nessuna simulazione di costo gia disponibile.',))
    clean=[]
    for row in rows:
        if isinstance(row,Mapping) and row.get('coppia') == PAIR:
            try:
                clean.append({'pair':PAIR,'costo_roundtrip_eur':_number(
                     row['costo_roundtrip_eur'],'costo'),
                     'n_conversioni':int(row['n_conversioni'])})
            except (ValueError,KeyError,TypeError):
                continue
    if not clean:
        return _section(limits=('Simulazione costo SUI/EUR non presente o non validabile.',))
    return _section(provenance, source='costi_spot.py su dati pubblici; scenario non eseguibile',
        observed_utc=None,coverage='Solo simulazione per importo ipotetico; istante calcolo ignoto',
        evidence=clean[:3],limits=('Non si conoscono fee del conto e slippage effettivo.',
             'Tempo dell acquisizione del book per il calcolo costi non tracciato.'))


def _public_context(extra, key, provenance):
    record = extra.get(key) if isinstance(extra, Mapping) else None
    if not isinstance(record,Mapping):
        return _section(limits=(f'{key}: dati pubblici verificati non forniti.',))
    # Explicit evidence contract: no arbitrary text disguised as real-world truth.
    try:
        source = record['source']
        checked = _time(record['observed_utc'])
        coverage = record['coverage']
        summary = record['fact']
        if not all(isinstance(v,str) and v.strip() for v in (source, coverage, summary)):
            raise ValueError('attributi vuoti')
        if key in ('fondamentali','notizie_token') and record.get('asset_id') != ASSET_ID:
            raise ValueError('asset_id della notizia non verificato')
        if key in ('macroeconomia','geopolitica') and record.get('kind') != 'VERIFICA_CONTESTUALE':
            raise ValueError('RSS o titolo senza analisi contestuale verificata')
        alternative=record.get('alternative',[])
        if not isinstance(alternative,list) or not all(isinstance(v,str) for v in alternative):
            raise ValueError('alternative non valide')
    except (KeyError,ValueError,TypeError) as exc:
        return _section(status='NON_VERIFICABILE',limits=(str(exc),))
    return _section(provenance,source=source,
       observed_utc=checked.isoformat().replace('+00:00','Z'),coverage=coverage,
       evidence={'fact':summary},alternative=tuple(alternative),
       limits=('Informazione riportata nel payload; acquisizione diretta non effettuata da questo componente.',))


def _onchain(report, provenance):
    if not isinstance(report,Mapping):
        return _section(limits=('Output G2R2 on-chain non fornito; nessuna chiamata automatica.',))
    statuses=report.get('statuses')
    obs=report.get('observations')
    if not isinstance(statuses,Mapping) or not isinstance(obs,list):
        return _section(status='RISPOSTA_INCOMPLETA',limits=('Struttura report on-chain non valida.',))
    if statuses.get('identity') != 'VERIFICATA' or report.get('network') != CHAIN:
        return _section(status='IDENTITA_NON_VERIFICATA',limits=('Sui Mainnet non verificata dal report G2R2.',))
    cleaned=[]
    for o in obs:
        if not isinstance(o,Mapping) or o.get('asset') != ASSET or o.get('chain') != CHAIN or o.get('asset_id') != ASSET_ID:
            continue
        if o.get('kind') not in KINDS or o.get('verification') not in ('VERIFICATO','FONTE_UFFICIALE_DATI_PROGRAMMATI'):
            continue
        try:
            acquire = _time(o['acquired_utc'])
            event=_time(o['event_utc']) if o.get('event_utc') else None
            if event and event>acquire:
                continue
            quantity=_number(o['quantity'],'onchain quantity',strictly_positive=True) if o.get('quantity') is not None else None
            if o['kind']=='FATTO_OSSERVATO' and not (event and o.get('transaction') and o.get('block_reference')):
                continue
        except (ValueError,KeyError):
            continue
        cleaned.append({k:o.get(k) for k in ('kind','event','quantity','unit',
                         'transaction','block_reference','event_utc','acquired_utc',
                         'knowable_utc','coverage','verification','source',
                         'compatible','prohibited','limits','reference_period')})
    status=provenance if cleaned else 'NESSUNA_OSSERVAZIONE_UTILIZZABILE'
    try:
        moment=_time(report['acquired_utc']).isoformat().replace('+00:00','Z')
    except (KeyError, ValueError):
        moment=None
    return _section(status,source='Sui Mainnet GraphQL / programma Foundation (G2R2 report)',
       observed_utc=moment,coverage=str(report.get('coverage','NON_DETERMINABILE')),
       evidence={'observations':cleaned,'source_statuses':{k:v for k,v in statuses.items() if isinstance(v,str)}},
       compatible=('Creazione o consumo verificato di oggetto StakedSui; rilevanza economica ipotetica.',),
       alternative=('Non prova acquisti, vendite, intenzioni o flusso netto.',),
       limits=('Fonte ed estrazione da validare indipendentemente; campione non censuario.',
               'Attribution Move PTB non dimostrata; non aggregare staking/unstaking.',
               'Circolazione programmata e oggetti on-chain hanno semantiche differenti.'))


def build(*, snapshot=None, existing_dossier=None, onchain_report=None,
          public_context=None, acquired_utc=None, provenance='FIXTURE'):
    """Merge ONLY explicit public data. Never accesses files or network.

    `FIXTURE` and `PUBLIC_REPORTED` govern evidence wording; *no mode* can
    mark indirect input as independently verified by this integration.
    """
    if provenance not in ('FIXTURE','PUBLIC_REPORTED'):
        raise ValueError('provenienza esplicita richiesta')
    observed=FIXTURE if provenance=='FIXTURE' else REPORTED
    captured=_time(acquired_utc or datetime.now(timezone.utc).isoformat())
    sections={}
    sections['mercato']=_market(snapshot,observed)
    card=_card(existing_dossier)
    sections['multitimeframe']=_timeframes(existing_dossier,observed)
    sections['liquidita']=_liquidity(sections['mercato'],card,observed)
    sections['costi']=_costs(card,sections['mercato'],observed)
    sections['onchain']=_onchain(onchain_report,observed)
    for key in ('fondamentali','notizie_token','macroeconomia','geopolitica'):
        sections[key]=_public_context(public_context,key,observed)
    missing=[key for key in CHANNELS if sections[key]['status'] in
             (UNAVAILABLE,'RISPOSTA_INCOMPLETA','NON_VERIFICABILE',
              'IDENTITA_NON_VERIFICATA','NESSUNA_OSSERVAZIONE_UTILIZZABILE')]
    time_info={}
    market_t=sections['mercato']['observed_utc']
    chain_t=sections['onchain']['observed_utc']
    if market_t and chain_t:
        delta=abs((_time(market_t)-_time(chain_t)).total_seconds())
        time_info={'market_utc':market_t,'onchain_acquired_utc':chain_t,
                   'difference_seconds':int(delta),
                   'status':'ALLINEAMENTO_ACQUISIZIONE_ENTRO_60_MIN' if delta<=3600 else 'NON_ALLINEATI',
                   'warning':'Tempi di acquisizione comparabili NON rendono contemporanei gli eventi on-chain.'}
    else:
        time_info={'status':'NON_DETERMINABILE','warning':'Manca almeno un timestamp di fonte.'}
    channel_times={}
    for k,s in sections.items():
        t=s['observed_utc']
        if t is None:
            channel_times[k]={'status':'NON_DETERMINABILE','source_utc':None}
            continue
        dt=_time(t)
        lag=int((captured-dt).total_seconds())
        if lag<0:
            s['status']='TEMPO_INCOERENTE'
            s['limits'].append('Fonte temporalmente successiva alla data del dossier.')
            if k not in missing: missing.append(k)
            state='FUTURO_RISPETTO_AL_DOSSIER'
        elif k in ('mercato','liquidita','costi','onchain'):
            state='ACQUISIZIONE_ENTRO_60_MIN' if lag<=3600 else 'ACQUISIZIONE_PIU_VECCHIA_DI_60_MIN'
        elif k=='multitimeframe':
            state='ULTIMA_CANDELA_CHIUSA_NON_QUOTAZIONE_LIVE'
        else:
            state='CONTESTO_DATATO_NON_QUOTAZIONE_LIVE'
        channel_times[k]={'status':state,'source_utc':t,
                          'age_at_dossier_seconds':lag}
    time_info['per_channel']=channel_times
    return {'schema':'KDD_NAVIGATORE_P4_V001','asset':ASSET,'market_pair':PAIR,
            'market_type':'KRAKEN_SPOT', 'asset_identity':{'chain':CHAIN,'asset_id':ASSET_ID},
            'built_utc':captured.isoformat().replace('+00:00','Z'),
            'input_provenance':provenance,
            'sections':sections, 'temporal_alignment':time_info,
            'missing_sections':missing,'decision_status':'CONTESTO_INFORMATIVO_NON_PREDITTIVO',
            'possible_interpretations':['Valutare se un fatto cambia le ipotesi, solo dopo verifica delle fonti e del tempo.'],
            'alternative_interpretations':['L evento osservato potrebbe non riguardare domanda o offerta negoziabile.'],
            'prohibited_interpretations':list(PROHIBITED),
            'private_data_access':False,'execution_permissions':False,
            'decision_utility':'NON_DIMOSTRATA'}