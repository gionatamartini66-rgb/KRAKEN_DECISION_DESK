"""KDD Point 4, bounded evidence-only SUI/EUR dossier.

Pure function over *supplied public-source snapshots*. Never opens files, network,
Kraken credentials, portfolio or orders. Designed as an adapter to the existing
KDD refresh/dossier and G2R2 on-chain report, without modifying either.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping

from onchain_nav_core import utc, uint  # reuse the G2R2 chain-neutral contract

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


def _string(value, *, max_len=500):
    """Strict scalar contract; no arbitrary nested values or unbounded strings."""
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        raise ValueError('testo non conforme al contratto pubblico')
    return value


def _texts(seq):
    if not isinstance(seq, (list, tuple)) or len(seq) > 12:
        raise ValueError('sequenza non conforme')
    return [_string(x, max_len=500) for x in seq]


def _int_nonnegative(x):
    # Never silently convert floats, bools, scientific notation or negative inputs.
    if type(x) is int and x >= 0:
        return x
    if isinstance(x, str) and x.isascii() and x.isdecimal() and x == str(int(x)):
        return int(x)
    raise ValueError('n_conversioni deve essere intero non negativo')


def _iso(x):
    return _time(x).isoformat().replace('+00:00', 'Z')


def _ohlcv_consistency(bar, label, *, four_hour=False):
    """OHLCV consistency is different from verification of a candle close marker.

    A legacy minimal synthetic example or a close-only producer can keep its
    timestamp evidence but never acquire a claim of complete OHLCV integrity.
    """
    if not isinstance(bar, Mapping):
        raise ValueError(label + ': barra non strutturata')
    names = (('open', 'high', 'low', 'close', 'volume_base') if four_hour else
             ('apertura', 'massimo', 'minimo', 'chiusura', 'volume_base'))
    extra = names[:3] + names[4:]
    if not any(k in bar for k in extra):
        return 'NON_VERIFICATA_OHLCV_INCOMPLETO'
    if not all(k in bar for k in names):
        raise ValueError(label + ': tuple OHLCV parziali')
    op, high, low, close, volume = (Decimal(_number(bar[k], label+' '+k)) for k in names)
    if not (low > 0 and low <= min(op, close) <= max(op, close) <= high and volume >= 0):
        raise ValueError(label + ': OHLCV incoerenti')
    return 'COERENZA_NUMERICA_OHLCV_CONTROLLATA'


def _timeframes(dossier, provenance, built):
    card = _card(dossier)
    graph = dossier.get('grafici_4h', {}) if isinstance(dossier, Mapping) else {}
    four = graph.get(ASSET) if isinstance(graph, Mapping) else None
    periods, invalid = {}, []
    for key, label, seconds in (('livelli_15m', '15m', 900), ('livelli_1h', '1H', 3600)):
        part = card.get(key) if isinstance(card, Mapping) else None
        if not isinstance(part, Mapping):
            continue
        try:
            t = _time(part['ultima_chiusura_utc'])
            bars = part['ultime_candele']
            if not isinstance(bars, list) or not bars or not isinstance(bars[-1], Mapping):
                raise ValueError('ultime_candele non disponibili')
            last = bars[-1]
            close = _number(last['chiusura'], label+' close', strictly_positive=True)
            integrity_flags = [_ohlcv_consistency(b, label) for b in bars]
            ohlcv_integrity = ('COERENZA_NUMERICA_OHLCV_CONTROLLATA' if
                  all(x=='COERENZA_NUMERICA_OHLCV_CONTROLLATA' for x in integrity_flags)
                  else 'NON_VERIFICATA_OHLCV_INCOMPLETO')
            proof = 'MARKER_NON_ATTESTATO'
            # Some legacy exports do not carry per-bar closure timestamps. They
            # can remain visible as unverified synthetic context, not certified OHLC.
            if 'chiusura_utc' in last:
                if _time(last['chiusura_utc']) != t:
                    raise ValueError('marker e chiusura candela non corrispondono')
                proof = 'CHIUSURA_CONFERMATA'
            elif 'apertura_ts_utc' in last:
                opening = last['apertura_ts_utc']
                if type(opening) is not int or opening + seconds != int(t.timestamp()):
                    raise ValueError('marker e apertura candela non corrispondono')
                proof = 'CHIUSURA_CONFERMATA'
            if t > built:
                raise ValueError('chiusura futura rispetto al dossier')
            if provenance != FIXTURE and proof != 'CHIUSURA_CONFERMATA':
                raise ValueError('timestamp barra non attestato per fonte pubblica')
            # Gaps only when every bar has a provable close; unknown != zero.
            gaps='NON_DETERMINABILE'
            if all(isinstance(b, Mapping) and 'chiusura_utc' in b for b in bars):
                closes=[_time(b['chiusura_utc']) for b in bars]
                if closes[-1] != t or any(b<=a for a,b in zip(closes,closes[1:])):
                    raise ValueError('sequenza OHLC non crescente o marker discordante')
                gaps=sum(max(0,int((b-a).total_seconds())//seconds-1) for a,b in zip(closes,closes[1:]))
                if any((b-a).total_seconds()%seconds for a,b in zip(closes,closes[1:])):
                    raise ValueError('sequenza OHLC non aderente al timeframe')
            age = int((built-t).total_seconds())
            periods[label] = {'last_closed_utc':_iso(part['ultima_chiusura_utc']),
                              'close_eur':close, 'source':'Kraken OHLC, dossier_trade',
                              'bar_close_validation':proof,
                              'ohlcv_integrity':ohlcv_integrity,
                              'age_at_dossier_seconds':age,
                              'freshness':'STORICA_NON_LIVE' if age > seconds*3 else 'CANDELA_CHIUSA_RECENTE',
                              'missing_bars':gaps}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            invalid.append(label + ': ' + str(exc))
    if isinstance(four, Mapping) and four.get('stato') == 'OK' and four.get('coppia') == PAIR:
        indicative, series = four.get('lettura_indicativa'), four.get('serie_ohlcv_chiuse')
        try:
            if not isinstance(indicative, Mapping) or not isinstance(series,list) or not series:
                raise ValueError('4H incomplete')
            close_t = _time(indicative['ultima_chiusura_utc'])
            close = _number(series[-1]['close'], '4H close', strictly_positive=True)
            integrity_flags = [_ohlcv_consistency(b, '4H', four_hour=True) for b in series]
            ohlcv_integrity = ('COERENZA_NUMERICA_OHLCV_CONTROLLATA' if
                  all(x=='COERENZA_NUMERICA_OHLCV_CONTROLLATA' for x in integrity_flags)
                  else 'NON_VERIFICATA_OHLCV_INCOMPLETO')
            starts=[b.get('apertura_ts_utc') for b in series]
            if any(type(t) is not int for t in starts):
                raise ValueError('aperture 4H incomplete')
            if any(b-a!=14400 for a,b in zip(starts,starts[1:])):
                raise ValueError('serie 4H non contigua o non ordinata')
            start = series[-1].get('apertura_ts_utc')
            if type(start) is not int or start+14400 != int(close_t.timestamp()) or close_t > built:
                raise ValueError('4H closing marker differs from last bar or built time')
            age=int((built-close_t).total_seconds())
            periods['4H'] = {'last_closed_utc':_iso(indicative['ultima_chiusura_utc']),
                             'close_eur':close, 'closed_bars':len(series),
                             'source':'Kraken Spot OHLC 240, dossier_trade',
                             'bar_close_validation':'CHIUSURA_CONFERMATA',
                             'ohlcv_integrity':ohlcv_integrity,
                             'age_at_dossier_seconds':age,
                             'freshness':'STORICA_NON_LIVE' if age>43200 else 'CANDELA_CHIUSA_RECENTE',
                             'missing_bars':'NON_DETERMINABILE',
                             'missing_bars_in_sample':0 if len(series)>1 else 'NON_DETERMINABILE'}
        except (KeyError, TypeError, ValueError) as exc:
            invalid.append('4H: '+str(exc))
    if not periods:
        return _section(limits=('Nessuna serie OHLC chiusa SUI/EUR validabile.',)+tuple(invalid))
    missing = tuple(x for x in ('15m','1H','4H','1D') if x not in periods)
    return _section(provenance, source='dossier_trade.py + analisi_v02.py, da Kraken pubblico',
        observed_utc=max(v['last_closed_utc'] for v in periods.values()),
        coverage='Candele chiuse per '+','.join(periods), evidence=periods,
        alternative=('Confluenze tecniche non equivalgono a probabilita di rendimento.',),
        limits=tuple('Timeframe assente: '+x for x in missing)+tuple(invalid)+
               ('Le chiusure di timeframe differenti non sono istanti identici.',))


def _liquidity(market, card, provenance):
    if market['evidence'] is None:
        return _section(limits=('Manca una coppia SUI/EUR verificabile.',))
    values={k:market['evidence'][k] for k in ('spread_pct', 'volume_24h_eur_stimato')}
    values['ticker_acquired_utc']=market['observed_utc']
    src='mercati_spot.py / decision_desk.py: Kraken ticker pubblico'
    if isinstance(card, Mapping) and isinstance(card.get('book'), Mapping):
        try:
            book = card['book']
            values.update({key:_number(book[key],key) for key in
                           ('spread_book_pct','profondita_bid10_eur','profondita_ask10_eur')})
            src+='; analisi_v02.book_metrics (Depth 10)'
            values['book_acquired_utc']=None
        except (KeyError,ValueError):
            pass
    return _section(provenance, source=src, observed_utc=None,
        coverage='Spread/volume del ticker datato separatamente; book Depth 10 senza timestamp autonomo.',
        evidence=values,
        alternative=('Book modificabile; volume 24h non e profondita corrente.',),
        limits=('NON_DETERMINABILE: freschezza autonoma del book e della sezione.',
                'Non misura slippage eseguibile senza importo e libro fresco.',
                'Kraken resta mercato di esecuzione, non Binance.'))


def _costs(card, market, provenance):
    if market['evidence'] is None:
        return _section(limits=('Coppia spot non verificata.',))
    if not isinstance(card, Mapping):
        return _section(limits=('SUI non compare tra le schede candidate.',))
    rows=card.get('simulazione_costi_eur_wallet')
    if not isinstance(rows,list):
        return _section(limits=('Nessuna simulazione di costo gia disponibile.',))
    clean=[]
    for row in rows:
        if isinstance(row,Mapping) and row.get('coppia') == PAIR:
            if row.get('errore') is not None:  # explicit failure, never a cost quote
                continue
            try:
                entry={'pair':PAIR,'costo_roundtrip_eur':_number(
                      row['costo_roundtrip_eur'],'costo'),
                      'n_conversioni':_int_nonnegative(row['n_conversioni'])}
                # Normally absent: dossier_trade.collect discards these upstream.
                for name in ('importo_eur','costo_roundtrip_pct','fee_stimate_eur',
                             'spread_slippage_stimati_eur','commissione_crypto_pct',
                             'commissione_fx_pct','fee_maker_pct'):
                    if name in row and row[name] is not None:
                        entry[name]=_number(row[name],name)
                entry['importo_originale_disponibile']='importo_eur' in entry
                clean.append(entry)
            except (ValueError,KeyError,TypeError):
                continue
    if not clean:
        return _section(limits=('Simulazione costo SUI/EUR non presente o non validabile.',))
    return _section(provenance, source='costi_spot.py su dati pubblici; scenario non eseguibile',
        observed_utc=None,coverage='Solo simulazione per importo ipotetico; istante calcolo ignoto',
        evidence=clean[:3],limits=('Non si conoscono fee del conto e slippage effettivo.',
              'Importo e parametri di costo completi persi a monte in dossier_trade.collect se assenti nella riga.',
              'Tempo dell acquisizione del book per il calcolo costi non tracciato.'))


def _public_context(extra, key, provenance):
    record = extra.get(key) if isinstance(extra, Mapping) else None
    if not isinstance(record,Mapping):
        return _section(limits=(f'{key}: fonte non fornita.',))
    try:
        source = _string(record['source'], max_len=255)
        checked = _iso(record['observed_utc'])
        coverage = _string(record['coverage'])
        _string(record['fact'], max_len=1200)
        _texts(record.get('alternative',[]))
        if key in ('fondamentali','notizie_token') and record.get('asset_id') != ASSET_ID:
            raise ValueError('asset_id della notizia non verificato')
        if key in ('macroeconomia','geopolitica') and record.get('kind') != 'VERIFICA_CONTESTUALE':
            raise ValueError('RSS o titolo senza analisi contestuale verificata')
        if not source.startswith('https://') or '.invalid' in source:
            if provenance != FIXTURE:
                raise ValueError('fonte sintetica o URL non attendibile')
        # A caller-provided fact and alternatives are NOT authenticated public
        # content. Exclude them rather than relying on a lexical secret filter.
    except (KeyError,ValueError,TypeError) as exc:
        return _section(status='NON_VERIFICABILE',limits=(str(exc),))
    return _section(provenance,source='FONTE_NON_ATTESTATA_DAL_COMPOSITORE',
       observed_utc=checked,coverage='Record nominale valido; contenuto non pubblicato.',
       evidence={'fact':'CONTENUTO_NON_ATTESTATO_NON_ESPORTATO'},
       limits=('Il testo sorgente e le alternative del chiamante non attraversano il confine pubblico.',
               'Per pubblicare contenuti reali serve un produttore attestato e un contratto pubblico di origine.'))

def _declared_sui_source(url, kind, provenance):
    # In the current G2R2 producer these are constant source URLs, not arbitrary
    # URLs provided by a caller. Matching them does NOT authenticate the caller.
    expected = ('https://graphql.mainnet.sui.io/graphql' if kind=='FATTO_OSSERVATO'
                else 'https://sui-circulation.suiexplorer.com/api/current_month_sui_circulation')
    if url == expected or (provenance == FIXTURE and kind=='DATO_PROGRAMMATO' and url=='https://sui.io/supply'):
        return url
    raise ValueError('URL fonte diverso dal contratto G2R2 corrente')


def _reported_coverage(report, provenance):
    """Preserve typed G2R2 reported bounds, never imply a complete history."""
    cov=report.get('coverage')
    if cov=='NON_DETERMINABILE' or cov is None:
        return {'status':'NON_DETERMINABILE'}
    if not isinstance(cov,Mapping):
        return {'status':'COPERTURA_MALFORMATA'}
    try:
        first=uint(cov['first_checkpoint'],allow_zero=True)
        last=uint(cov['last_checkpoint'],allow_zero=True)
        if first>last:
            raise ValueError('intervallo invertito')
        # Source's fixed scope string; legacy synthetic BATCH_ONLY is a declared
        # test marker, not arbitrary producer text or a complete-history claim.
        scope=cov.get('scope')
        canonical='Query.transactions filter=function; campione limitato; contiguita interna non dimostrata'
        if scope!=canonical and not (provenance==FIXTURE and scope=='BATCH_ONLY'):
            raise ValueError('scope non canonico')
        return {'status':'RIPORTATA_NON_RIVERIFICATA',
                'first_checkpoint':first,'last_checkpoint':last,'scope':scope}
    except (ValueError,KeyError,TypeError,OverflowError):
        return {'status':'COPERTURA_MALFORMATA'}


def _existing_coingecko_fundamentals(card, built):
    """Bounded numeric projection from dossier_trade.token_fundamentals (not auth)."""
    raw=card.get('fondamentali_coingecko') if isinstance(card,Mapping) else None
    if not isinstance(raw,Mapping) or raw.get('errore') or raw.get('id')!='sui':
        return None
    # Constant KDD producer endpoint/asset, no arbitrary URL echo.
    expected=('https://api.coingecko.com/api/v3/coins/sui'
              '?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false')
    if raw.get('fonte')!=expected:
        return None
    try:
        observed=_iso(raw['aggiornato_utc'])
        if _time(observed)>built:
            return None
        values={'coin_id':'sui', 'source_reported_url':expected,
                'source_authentication':'NON_DIMOSTRATA', 'source_observed_utc':observed}
        for field in ('prezzo_usd','capitalizzazione_usd','offerta_circolante','offerta_totale'):
            if raw.get(field) is not None:
                values[field]=_number(raw[field],field)
        if len(values)==4:
            return None
        return values
    except (KeyError, ValueError, TypeError):
        return None


# Contractual statuses allowed by the actual Sui G2R2 report.
_ONCHAIN_STATUSES = ('identity','staking','unstaking','circulation',
                     'staking_coverage','unstaking_coverage')
_ONCHAIN_EVENTS = {'STAKED_SUI_OGGETTO_CREATO':'staking',
                   'STAKED_SUI_OGGETTO_CONSUMATO':'unstaking',
                   'CIRCOLAZIONE_PROGRAMMATA_FINE_MESE':'circulation'}


def _onchain(report, provenance, built):
    if not isinstance(report,Mapping):
        return _section(limits=('Output G2R2 on-chain non fornito; nessuna chiamata automatica.',))
    statuses, obs = report.get('statuses'), report.get('observations')
    if not isinstance(statuses,Mapping) or not isinstance(obs,list) or len(obs)>100:
        return _section(status='RISPOSTA_INCOMPLETA',limits=('Struttura report on-chain non valida.',))
    if statuses.get('identity') != 'VERIFICATA' or report.get('network') != CHAIN:
        return _section(status='IDENTITA_NON_VERIFICATA',limits=('Sui Mainnet non verificata dal report G2R2.',))
    try:
        report_time=_time(report['acquired_utc'])
    except (ValueError,KeyError):
        return _section(status='RISPOSTA_INCOMPLETA',limits=('Acquisizione report assente o invalida.',))
    if report_time > built:
        return _section(status='TEMPO_INCOERENTE',limits=('Report successivo alla costruzione del dossier.',))
    clean, invalid, chronological=[],0,0
    seen_facts, conflicting_facts = {}, set()
    for o in obs:
        try:
            if not isinstance(o, Mapping) or (o.get('asset'),o.get('chain'),o.get('asset_id')) != (ASSET,CHAIN,ASSET_ID):
                raise ValueError('identita osservazione non valida')
            kind, event = o.get('kind'),o.get('event')
            if kind not in ('FATTO_OSSERVATO','DATO_PROGRAMMATO') or event not in _ONCHAIN_EVENTS:
                raise ValueError('tipo evento non supportato dal pilota')
            if kind != ('DATO_PROGRAMMATO' if event=='CIRCOLAZIONE_PROGRAMMATA_FINE_MESE' else 'FATTO_OSSERVATO'):
                raise ValueError('categoria evento incompatibile')
            reported = o.get('verification')
            expected='FONTE_UFFICIALE_DATI_PROGRAMMATI' if kind=='DATO_PROGRAMMATO' else 'VERIFICATO'
            if reported != expected:
                raise ValueError('stato di verifica del producer non conforme')
            if o.get('unit') != 'SUI':
                raise ValueError('unita non SUI')
            qty = _number(o['quantity'],'onchain quantity', strictly_positive=True)
            source = _string(o['source'],max_len=255)
            source=_declared_sui_source(source, kind, provenance)
            coverage = _string(o['coverage'])
            acquire=_time(o['acquired_utc'])
            event_t=_time(o['event_utc']) if o.get('event_utc') else None
            knowable=_time(o['knowable_utc']) if o.get('knowable_utc') else None
            if ((event_t and event_t>acquire) or (knowable and
                (knowable>acquire or (event_t and knowable<event_t))) or
                acquire>report_time or acquire>built):
                chronological+=1
                raise ValueError('cronologia impossibile')
            transaction=o.get('transaction')
            checkpoint=o.get('block_reference')
            transaction_output=None
            if kind=='FATTO_OSSERVATO':
                if not event_t or not _string(transaction,max_len=128) or not isinstance(checkpoint,(str,int)):
                    raise ValueError('digest/checkpoint assenti')
                if isinstance(checkpoint,bool) or not str(checkpoint).isascii() or not str(checkpoint).isdecimal():
                    raise ValueError('checkpoint non numerico')
                uint(str(checkpoint),allow_zero=True)
                # Sui digest base58; a special nominal marker is allowed only
                # in a synthetic fixture, and never exported as a real digest.
                alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
                if 32 <= len(transaction) <= 64 and all(c in alphabet for c in transaction):
                    transaction_output=transaction
                elif provenance==FIXTURE and transaction=='DIGEST_FIXTURE':
                    transaction_output='DIGEST_SINTETICO_NON_VERIFICATO'
                else:
                    raise ValueError('digest senza struttura Sui ammissibile')
            else:
                period = _string(o.get('reference_period'), max_len=80)
                if len(period)!=17 or not period.endswith('-fine-mese') or not (
                    period[:4].isdigit() and period[4]=='-' and period[5:7].isdigit() and
                    period[7:]=='-fine-mese' and 1<=int(period[5:7])<=12):
                    raise ValueError('periodo programmatico non conforme')
            # Validate even discarded prose; do not copy any caller-provided lists.
            for key in ('compatible','prohibited','limits'):
                _texts(o.get(key,[]))
            details=o.get('details')
            accepted_details=None
            if details is not None:
                if not isinstance(details,Mapping) or kind!='FATTO_OSSERVATO':
                    raise ValueError('details non coerenti')
                obj = _string(details['staked_sui_object'],max_len=66)
                principal = _int_nonnegative(details['principal_mist'])
                fam = details['filter_family']
                attrib = details['command_attribution']
                if not (obj.startswith('0x') and 1<=len(obj[2:])<=64 and
                        all(c in '0123456789abcdefABCDEF' for c in obj[2:]) and
                        fam in ('staking','unstaking') and attrib=='NON_DIMOSTRATA'):
                    raise ValueError('metadati oggetto non validi')
                if fam!=_ONCHAIN_EVENTS[event]:
                    raise ValueError('famiglia filtro incompatibile con evento')
                if Decimal(principal)/Decimal(10**9)!=Decimal(qty):
                    raise ValueError('principal MIST diverso da quantita SUI')
                accepted_details={'staked_sui_object':obj.lower(),
                                  'principal_mist':str(principal),'filter_family':fam,
                                  'command_attribution':'NON_DIMOSTRATA'}
            raw_econ=o.get('economic_relevance')
            if raw_econ is not None:
                _string(raw_econ)
            entry={'kind':kind,'event':event,'quantity':qty,'unit':'SUI',
               'transaction':transaction_output if kind=='FATTO_OSSERVATO' else None,
               'block_reference':str(checkpoint) if kind=='FATTO_OSSERVATO' else None,
               'event_utc':_iso(o['event_utc']) if event_t else None,
               'acquired_utc':_iso(o['acquired_utc']),
               'knowable_utc':_iso(o['knowable_utc']) if knowable else None,
               'coverage':'EVENTO_CON_COPERTURA_DICHIARATA_DAL_PRODUTTORE',
               'reported_verification':reported,
               'integration_verification':'CONTRATTO_FORMALE_VALIDATO_FONTE_NON_RIVERIFICATA',
               'source':'FONTE_DICHIARATA_DAL_PRODUTTORE_NON_AUTENTICATA',
               'reported_source_url':source,
               'reported_source_authentication':'NON_DIMOSTRATA',
               'reference_period':o.get('reference_period') if kind=='DATO_PROGRAMMATO' else None,
               'details':accepted_details,
               'economic_relevance': ('Cambiamento oggetto StakedSui, significato direzionale indeterminato.'
                 if kind=='FATTO_OSSERVATO' else 'Contesto programmatico, non direzione prezzo.')}
            if kind=='FATTO_OSSERVATO' and accepted_details is not None:
                key=(transaction_output, accepted_details['staked_sui_object'],event)
                if key in conflicting_facts:
                    invalid+=1
                    continue
                if key in seen_facts:
                    if seen_facts[key]!=entry:
                        clean.remove(seen_facts[key])
                        del seen_facts[key]
                        conflicting_facts.add(key)
                        invalid+=2
                    # Identical duplicates are not separate facts.
                    continue
                seen_facts[key]=entry
            clean.append(entry)
        except (ValueError,TypeError,KeyError):
            invalid+=1
    state=('TEMPO_INCOERENTE' if chronological else
           ('RISPOSTA_INCOERENTE' if conflicting_facts else
           (provenance if clean else 'NESSUNA_OSSERVAZIONE_UTILIZZABILE')))
    return _section(state,
       source='G2R2 report fornito dal chiamante, autenticita tecnica non attestata',
       observed_utc=_iso(report['acquired_utc']),
       coverage='Campione G2R2: descrizione originale non riverificata dal compositore.',
       evidence={'observations':clean,
                 'source_statuses':{k:statuses[k] for k in _ONCHAIN_STATUSES
                    if (k=='identity' and statuses.get(k)=='VERIFICATA') or
                       (k in ('staking','unstaking') and statuses.get(k) in
                        ('OGGETTO_VERIFICATO_ATTRIBUZIONE_NON_DIMOSTRATA',
                         'EVENTO_NON_VERIFICABILE','RISPOSTA_INCOMPLETA',
                         'TRANSAZIONE_FALLITA','NON_ESEGUITO_IDENTITA_NON_VERIFICATA')) or
                       (k in ('staking_coverage','unstaking_coverage') and statuses.get(k) in
                        ('COPERTURA_INSUFFICIENTE','CAMPIONE_LIMITATO_NON_GENERALE')) or
                       (k=='circulation' and statuses.get(k) in
                        ('PROGRAMMA_ACQUISITO','FONTE_NON_DISPONIBILE','RISPOSTA_INCOMPLETA'))},
                 'rejected_observations':invalid,
                 'conflicting_fact_keys':len(conflicting_facts),
                 'reported_coverage':_reported_coverage(report,provenance),
                 'producer_attestation':'DICHIARAZIONE_NON_AUTENTICATA',
                 'independently_checked':'IDENTITA_CONTRATTO_E_CRONOLOGIA_SOLTANTO'},
       alternative=('Non prova acquisti, vendite, intenzioni o flusso netto.',),
       limits=('Nessun controllo indipendente della blockchain o delle firme di provenienza.',
               'Non si pubblicano liste testuali arbitrarie dagli input.',
               'Attribuzione Move PTB non dimostrata.'))


def build(*, snapshot=None, existing_dossier=None, onchain_report=None,
          public_context=None, acquired_utc=None, provenance='FIXTURE'):
    """Evidence-only composition; data supplied by caller is not public attestation.

    No identity of upstream public producers is authenticated here. Therefore a
    PUBLIC_REPORTED label never upgrades caller-provided records to verified
    or publishes free-form content. A future trusted producer needs separate GO.
    """
    if provenance not in ('FIXTURE','PUBLIC_REPORTED'):
        raise ValueError('provenienza esplicita richiesta')
    observed=FIXTURE if provenance=='FIXTURE' else 'FONTE_NON_ATTESTATA'
    captured=_time(acquired_utc or datetime.now(timezone.utc).isoformat())
    sections={}
    sections['mercato']=_market(snapshot,observed)
    market_t=sections['mercato']['observed_utc']
    if market_t and _time(market_t)>captured:
        sections['mercato']['status']='TEMPO_INCOERENTE'
        sections['mercato']['limits'].append('Prezzo futuro rispetto alla costruzione; quarantena dei dipendenti.')
    card=_card(existing_dossier)
    snapshot_mismatch=False
    if isinstance(existing_dossier, Mapping) and card is not None:
        ds=existing_dossier.get('kraken_istantanea_utc')
        st=snapshot.get('rilevazione_utc') if isinstance(snapshot, Mapping) else None
        try:
            snapshot_mismatch=bool(ds is not None and _time(ds)!=_time(st))
            if provenance=='PUBLIC_REPORTED' and ds is None:
                snapshot_mismatch=True  # fail closed if no shared refresh identity
        except ValueError:
            snapshot_mismatch=True
    if snapshot_mismatch:
        card=None
        safe_dossier=None
    else:
        safe_dossier=existing_dossier
    sections['multitimeframe']=_timeframes(safe_dossier,observed,captured)
    if sections['mercato']['status']=='TEMPO_INCOERENTE':
        sections['liquidita']=_section(status='TEMPO_INCOERENTE',
            limits=('Market ticker temporalmente impossibile; book non pubblicabile.',))
        sections['costi']=_section(status='TEMPO_INCOERENTE',
            limits=('Market ticker temporalmente impossibile; simulazioni sospese.',))
    else:
        sections['liquidita']=_liquidity(sections['mercato'],card,observed)
        sections['costi']=_costs(card,sections['mercato'],observed)
    if snapshot_mismatch:
        for k in ('multitimeframe','liquidita','costi'):
            if k=='liquidita':
                # Ticker metrics remain, but no book can be borrowed from a
                # different snapshot; ticker time never becomes book time.
                sections[k]['limits'].append('Dossier Kraken NON_ALLINEATO: book escluso.')
            else:
                sections[k]=_section(status='NON_ALLINEATO',
                    limits=('kraken_istantanea_utc e rilevazione_utc non corrispondono.',))
    sections['onchain']=_onchain(onchain_report,observed,captured)
    for key in ('fondamentali','notizie_token','macroeconomia','geopolitica'):
        sections[key]=_public_context(public_context,key,observed)
    # Existing KDD CoinGecko producer already supplies bounded public numeric
    # fields. Preserve a typed demonstration without advertising authentication.
    cg=_existing_coingecko_fundamentals(card if not snapshot_mismatch and
        sections['mercato']['status']!='TEMPO_INCOERENTE' else None, captured)
    if cg is not None:
        sections['fondamentali']['evidence']={'coingecko_reported_numbers':cg}
        sections['fondamentali']['status']='FONTE_NUMERICA_RIPORTATA_NON_ATTESTATA'
        sections['fondamentali']['source']='dossier_trade.token_fundamentals, provenienza non autenticata'
        sections['fondamentali']['observed_utc']=cg['source_observed_utc']
        sections['fondamentali']['coverage']='Soli valori numerici CoinGecko dichiarati, identita SUI; nessun testo terzo.'
        sections['fondamentali']['limits'].append('Sorgente HTTPS riportata ma produttore non autenticato; senza gate pubblico.')
    # Structural presence is not availability of an authenticated public source.
    unavailable_statuses={UNAVAILABLE,'RISPOSTA_INCOMPLETA','NON_VERIFICABILE',
                           'IDENTITA_NON_VERIFICATA','NESSUNA_OSSERVAZIONE_UTILIZZABILE',
                           'TEMPO_INCOERENTE','NON_ALLINEATO','RISPOSTA_INCOERENTE'}
    public_attested=[]  # no authenticated producer here
    missing=list(CHANNELS)
    market_t=sections['mercato']['observed_utc']
    chain_t=sections['onchain']['observed_utc']
    if market_t and chain_t:
        delta=abs((_time(market_t)-_time(chain_t)).total_seconds())
        time_info={'market_utc':market_t,'onchain_acquired_utc':chain_t,
                   'difference_seconds':int(delta),
                   'status':'ALLINEAMENTO_ACQUISIZIONE_ENTRO_60_MIN' if delta<=3600 else 'NON_ALLINEATI',
                   'warning':'Tempi di acquisizione NON rendono contemporanei gli eventi on-chain.'}
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
            state='FUTURO_RISPETTO_AL_DOSSIER'
        elif k in ('mercato','costi','onchain'):
            state='ACQUISIZIONE_ENTRO_60_MIN' if lag<=3600 else 'ACQUISIZIONE_PIU_VECCHIA_DI_60_MIN'
        elif k=='multitimeframe':
            state='ULTIMA_CANDELA_CHIUSA_NON_QUOTAZIONE_LIVE'
        else:
            state='CONTESTO_DATATO_NON_QUOTAZIONE_LIVE'
        channel_times[k]={'status':state,'source_utc':t,'age_at_dossier_seconds':lag}
    time_info['per_channel']=channel_times
    # Availability indices MUST reflect final statuses, including future-source
    # invalidation in the temporal pass, never the preliminary draft.
    structural_missing=[k for k in CHANNELS if sections[k]['status'] in unavailable_statuses]
    structural_present=[k for k in CHANNELS if k not in structural_missing]
    availability={}
    for k in CHANNELS:
        sec=sections[k]
        validity='NON_VALIDA' if k in structural_missing else 'FORMA_AMMESSA_NON_AUTENTICATA'
        availability[k]={'struttura':'PRESENTE' if sec['evidence'] is not None else 'ASSENTE',
                         'validita':validity,
                         'freschezza':channel_times[k]['status'],
                         'provenienza':'NON_ATTESTATA',
                         'utilizzabilita':'LIMITATA_CON_VERIFICA_ESTERNA' if k in structural_present else 'NON_UTILIZZABILE'}
    return {'schema':'KDD_NAVIGATORE_P4_V001','asset':ASSET,'market_pair':PAIR,
            'market_type':'KRAKEN_SPOT','asset_identity':{'chain':CHAIN,'asset_id':ASSET_ID},
            'built_utc':_iso(captured.isoformat()), 'input_provenance':provenance,
            'sections':sections,'temporal_alignment':time_info,
            'missing_sections':missing,'structurally_missing_sections':structural_missing,
            'structurally_present_sections':structural_present,
            'public_sources_attested':public_attested,
             'section_availability':availability,
            'source_provenance_gate':'Nessuna fonte attestata direttamente dal compositore',
            'decision_status':'CONTESTO_INFORMATIVO_NON_PREDITTIVO',
            'possible_interpretations':['Valutare fatti solo dopo verifica di fonti e tempo.'],
            'alternative_interpretations':['L evento osservato potrebbe non riguardare domanda o offerta negoziabile.'],
            'prohibited_interpretations':list(PROHIBITED),
            'private_data_access':False,'execution_permissions':False,
            'decision_utility':'NON_DIMOSTRATA'}
