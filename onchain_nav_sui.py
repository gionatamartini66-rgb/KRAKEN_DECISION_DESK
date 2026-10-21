"""Bounded manual read-only Sui on-chain pilot, stdlib-only; no persistence."""
import argparse
from datetime import datetime, timezone
import json
import re
import urllib.error
import urllib.request

from onchain_nav_core import Observation, uint, units, utc

ENDPOINT = 'https://graphql.mainnet.sui.io/graphql'
CIRCULATION = 'https://sui-circulation.suiexplorer.com/api/current_month_sui_circulation'
COIN = '0x2::sui::SUI'
STAKED = '0x3::staking_pool::StakedSui'
MAINNET_PREFIX = '35834a8a'
STAKING = '0x3::sui_system::request_add_stake'
UNSTAKING = '0x3::sui_system::request_withdraw_stake'
MAX_CALLS = 9
MAX_PAGES_PER_TRANSACTION = 4
MAX_BYTES = 1_000_000
# Pagination explicitly requested. Query syntax is provisional until validated live.
LOOKUP = '''query($digest: String!, $after: String) { transaction(digest: $digest) {
 digest effects { status timestamp checkpoint { sequenceNumber }
 objectChanges(first: 50, after: $after) { pageInfo { hasNextPage endCursor }
 nodes { address idCreated idDeleted
 inputState { asMoveObject { contents { type { repr } json } } }
 outputState { asMoveObject { contents { type { repr } json } } } } } }
 } }'''
FILTER = '''query($function: String!) { transactions(last: 3, filter:{function:$function}) {
 pageInfo { hasPreviousPage startCursor } nodes { digest } } }'''
IDENTITY = 'query { chainIdentifier serviceConfig { availableRange(type:"Query",field:"transactions",filters:["function"]) { first {sequenceNumber} last {sequenceNumber} } } }'


class SourceProblem(Exception):
    def __init__(self, state, message):
        super().__init__(message)
        self.state = state


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _dict(value, field):
    if not isinstance(value, dict):
        raise SourceProblem('RISPOSTA_INCOMPLETA', f'oggetto {field} assente o malformato')
    return value


def _base58_decode(s):
    abc = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    x = 0
    for ch in s:
        if ch not in abc:
            raise ValueError('invalid base58')
        x = x * 58 + abc.index(ch)
    b = x.to_bytes((x.bit_length() + 7) // 8, 'big')
    return bytes([0]) * (len(s) - len(s.lstrip('1'))) + b


def mainnet(chain_identifier):
    if not isinstance(chain_identifier, str):
        return False
    if chain_identifier.lower() == MAINNET_PREFIX:
        return True
    try:
        decoded = _base58_decode(chain_identifier)
        return len(decoded) == 32 and decoded[:4].hex() == MAINNET_PREFIX
    except ValueError:
        return False


def post_graphql(query, variables=None, *, transport=None):
    payload = json.dumps({'query': query, 'variables': variables or {}}, separators=(',', ':')).encode()
    if len(payload) > 5000:
        raise SourceProblem('RICHIESTA_TROPPO_GRANDE', 'limite payload')
    req = urllib.request.Request(ENDPOINT, data=payload,
             headers={'Content-Type': 'application/json', 'User-Agent': 'KDD-Onchain-G2R1/0.1 read-only'}, method='POST')
    try:
        response = (transport or urllib.request.urlopen)(req, timeout=12)
        with response as conn:
            raw = conn.read(MAX_BYTES+1)
            if len(raw) > MAX_BYTES:
                raise SourceProblem('RISPOSTA_TROPPO_GRANDE', 'limite risposta')
    except urllib.error.HTTPError as exc:
        raise SourceProblem('RATE_LIMIT' if exc.code == 429 else 'ERRORE_HTTP', f'HTTP {exc.code}') from exc
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        raise SourceProblem('FONTE_NON_DISPONIBILE', type(exc).__name__) from exc
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceProblem('RISPOSTA_INCOMPLETA', 'JSON invalido') from exc
    if not isinstance(doc, dict):
        raise SourceProblem('RISPOSTA_INCOMPLETA', 'GraphQL documento non oggetto')
    if doc.get('errors'):
        raise SourceProblem('ERRORE_GRAPHQL', 'GraphQL errors presenti')
    if not isinstance(doc.get('data'), dict):
        raise SourceProblem('RISPOSTA_INCOMPLETA', 'campo data assente')
    return doc['data']


def _normalized_type(t):
    if not isinstance(t, str):
        return None
    parts = t.split('::')
    if len(parts) != 3 or not parts[0].startswith('0x'):
        return None
    try:
        return '0x' + format(int(parts[0], 16), 'x') + '::' + '::'.join(parts[1:])
    except ValueError:
        return None


def _object_changes(tx):
    fx = _dict(_dict(tx, 'transaction').get('effects'), 'effects')
    conn = _dict(fx.get('objectChanges'), 'effects.objectChanges')
    nodes = conn.get('nodes')
    page = _dict(conn.get('pageInfo'), 'effects.objectChanges.pageInfo')
    if not isinstance(nodes, list) or type(page.get('hasNextPage')) is not bool:
        raise SourceProblem('RISPOSTA_INCOMPLETA', 'nodes o hasNextPage mancanti')
    cursor = page.get('endCursor')
    if page['hasNextPage'] and (not isinstance(cursor, str) or not cursor):
        raise SourceProblem('RISPOSTA_INCOMPLETA', 'cursor di continuazione non valido')
    return nodes, page['hasNextPage'], cursor


def _transaction_identity(tx):
    _dict(tx, 'transaction')
    if not re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{32,64}', str(tx.get('digest', ''))):
        raise SourceProblem('EVENTO_NON_VERIFICABILE', 'digest invalido')
    fx = _dict(tx.get('effects'), 'effects')
    status = fx.get('status')
    if status not in ('SUCCESS', 'FAILURE'):
        raise SourceProblem('EVENTO_NON_VERIFICABILE', 'status transazione assente o inatteso')
    checkpoint = _dict(fx.get('checkpoint'), 'checkpoint').get('sequenceNumber')
    try:
        stamp, cp = utc(fx.get('timestamp')), uint(checkpoint, allow_zero=True)
    except ValueError as exc:
        raise SourceProblem('EVENTO_NON_VERIFICABILE', 'timestamp/checkpoint invalidi') from exc
    return tx['digest'], status, stamp, cp


def collect_pages(first_tx, fetch_page):
    """Atomic collection. On incomplete pages emit no verified transaction."""
    ident = _transaction_identity(first_tx)
    tx = first_tx
    collected = []
    used = set()
    for count in range(MAX_PAGES_PER_TRANSACTION):
        if _transaction_identity(tx) != ident:
            raise SourceProblem('EVENTO_NON_VERIFICABILE', 'metadati transazione differiscono fra pagine')
        nodes, has_more, cursor = _object_changes(tx)
        collected.extend(nodes)
        if not has_more:
            merged = {'digest':first_tx['digest'], 'effects':dict(first_tx['effects'])}
            merged['effects']['objectChanges'] = {'nodes':collected, 'pageInfo':{'hasNextPage':False, 'endCursor':cursor}}
            return merged
        if count + 1 >= MAX_PAGES_PER_TRANSACTION:
            raise SourceProblem('RISPOSTA_INCOMPLETA', 'limite pagine raggiunto')
        if cursor in used:
            raise SourceProblem('RISPOSTA_INCOMPLETA', 'cursore ripetuto')
        used.add(cursor)
        tx = _dict(fetch_page(first_tx['digest'], cursor), 'transaction')
    raise SourceProblem('RISPOSTA_INCOMPLETA', 'paginazione interrotta')


def _contents(change, side):
    outer = change.get(side)
    if outer is None:
        return None
    outer = _dict(outer, side)
    obj = outer.get('asMoveObject')
    if obj is None:
        return None
    return _dict(_dict(obj, 'asMoveObject').get('contents'), 'contents')


def parse_stake(tx, kind, acquired, coverage):
    """Only changed StakedSui objects are facts; filter != command attribution."""
    if kind not in ('staking','unstaking'):
        raise SourceProblem('EVENTO_NON_VERIFICABILE', 'famiglia filtro sconosciuta')
    digest, status, stamp, cp = _transaction_identity(tx)
    if status == 'FAILURE':
        return [], 'TRANSAZIONE_FALLITA'
    try:
        acquired = utc(acquired)
    except ValueError as exc:
        raise SourceProblem('EVENTO_NON_VERIFICABILE', 'orario acquisizione invalido') from exc
    if datetime.fromisoformat(stamp.replace('Z','+00:00')) > datetime.fromisoformat(acquired.replace('Z','+00:00')):
        raise SourceProblem('EVENTO_NON_VERIFICABILE', 'evento successivo ad acquisizione')
    changes, more, _ = _object_changes(tx)
    if more:
        raise SourceProblem('RISPOSTA_INCOMPLETA', 'objectChanges con pagine ulteriori')
    out = []
    seen = {}
    for change in changes:
        if not isinstance(change, dict):
            raise SourceProblem('RISPOSTA_INCOMPLETA', 'objectChange malformato')
        obj = change.get('address')
        if type(change.get('idCreated')) is not bool or type(change.get('idDeleted')) is not bool:
            raise SourceProblem('RISPOSTA_INCOMPLETA', 'idCreated/idDeleted non booleani')
        created = change['idCreated']
        deleted = change['idDeleted']
        if created and deleted:
            raise SourceProblem('EVENTO_NON_VERIFICABILE', 'cambiamento contraddittorio')
        for side, marked, event in (
            ('outputState',created,'STAKED_SUI_OGGETTO_CREATO'),
            ('inputState',deleted,'STAKED_SUI_OGGETTO_CONSUMATO')):
            if not marked:
                continue
            state = _contents(change,side)
            if state is None:
                continue
            typed = state.get('type')
            if _normalized_type(_dict(typed, 'contents.type').get('repr')) != STAKED:
                continue
            if not isinstance(obj, str) or not re.fullmatch(r'0x[0-9a-fA-F]{1,64}',obj):
                raise SourceProblem('EVENTO_NON_VERIFICABILE','id oggetto StakedSui non valido')
            key = (obj.lower(),event)
            raw = _dict(state.get('json'), 'contents.json').get('principal')
            try:
                amount = units(raw)
            except ValueError as exc:
                raise SourceProblem('EVENTO_NON_VERIFICABILE','principal non valido') from exc
            if key in seen:
                if seen[key] != amount:
                    raise SourceProblem('RISPOSTA_INCOERENTE', 'principal discordante per stesso digest/oggetto/evento')
                continue
            seen[key] = amount
            out.append(Observation(
                kind='FATTO_OSSERVATO', asset='SUI',chain='sui:mainnet',asset_id=COIN,
                event=event,quantity=amount,unit='SUI',transaction=digest,
                block_reference=str(cp),event_utc=stamp,acquired_utc=acquired,
                reference_period=stamp,knowable_utc=None,source=ENDPOINT,
                coverage=coverage,verification='VERIFICATO',
                limits=('Singola transazione: nessun flusso netto di rete.',
                        'Filtro per funzione non prova attribuzione al singolo comando PTB.',
                        'StakedSui principal non e ordine exchange, vendita o ricompensa.'),
                compatible=('Creazione o consumo oggetto StakedSui',),
                prohibited=('BUY/SELL','Intenzione indirizzo','Pressione di mercato',
                            'Attribuzione causale di comando Move non provata'),
                economic_relevance='Cambiamento oggetto StakedSui, significato direzionale indeterminato.',
                details={'staked_sui_object':obj.lower(),'principal_mist':str(raw),
                         'filter_family':kind,'command_attribution':'NON_DIMOSTRATA'}))
    return out, ('OGGETTO_VERIFICATO_ATTRIBUZIONE_NON_DIMOSTRATA' if out else 'EVENTO_NON_VERIFICABILE')


def parse_circulation(data, acquired):
    if not isinstance(data, dict) or not all(k in data for k in ('year','month','circulatingSupplyValue')):
        raise SourceProblem('RISPOSTA_INCOMPLETA', 'programmazione senza periodo/valore')
    from decimal import Decimal, InvalidOperation
    try:
        y, m = int(data['year']), int(data['month'])
        v = Decimal(str(data['circulatingSupplyValue']))
        if not 1 <= m <= 12 or not 2023 <= y <= 2100 or not v.is_finite() or v <= 0 or v > 10_000_000_000:
            raise ValueError()
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise SourceProblem('RISPOSTA_INCOMPLETA', 'valore programmato non valido') from exc
    return Observation(kind='DATO_PROGRAMMATO',asset='SUI',chain='sui:mainnet',asset_id=COIN,
        event='CIRCOLAZIONE_PROGRAMMATA_FINE_MESE',quantity=format(v,'f'),unit='SUI',
        transaction=None,block_reference=None,event_utc=None,acquired_utc=acquired,
        reference_period=f'{y:04d}-{m:02d}-fine-mese',knowable_utc=None,source=CIRCULATION,
        coverage='Un punto del programma mensile ufficiale; non un saldo osservato in tempo reale.',
        verification='FONTE_UFFICIALE_DATI_PROGRAMMATI',
        limits=('Stima per fine mese soggetta a revisioni.','Non aggiungere ai flussi blockchain.'),
        compatible=('Programma di circolazione della Foundation',),
        prohibited=('Offerta circolante in tempo reale', 'Vendite attese', 'Flussi exchange'),
        economic_relevance='Contesto programmatico, non direzione prezzo.')


def read_circulation(transport=None):
    req = urllib.request.Request(CIRCULATION, headers={'Accept':'application/json','User-Agent':'KDD-Onchain-G2R1/0.1 read-only'})
    try:
        with (transport or urllib.request.urlopen)(req, timeout=12) as resp:
            raw = resp.read(MAX_BYTES+1)
    except urllib.error.HTTPError as exc:
        raise SourceProblem('RATE_LIMIT' if exc.code==429 else 'ERRORE_HTTP',f'HTTP {exc.code}') from exc
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        raise SourceProblem('FONTE_NON_DISPONIBILE', type(exc).__name__) from exc
    if len(raw) > MAX_BYTES:
        raise SourceProblem('RISPOSTA_TROPPO_GRANDE','limite risposta')
    try:
        from decimal import Decimal
        return parse_circulation(json.loads(raw, parse_float=Decimal), now())
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceProblem('RISPOSTA_INCOMPLETA', 'JSON invalido') from exc


def run(*, request=post_graphql, include_circulation=False, circulation=read_circulation):
    """1 identity + 2 bounded filters + remaining details/pages; never aggregates."""
    report={'request_started_utc':now(),'network':'sui:mainnet','statuses':{},
            'observations':[],'coverage':None,'requests_max':MAX_CALLS,'requests_made':0}
    def ask(query, vars=None):
        if report['requests_made'] >= MAX_CALLS:
            raise SourceProblem('RISPOSTA_INCOMPLETA', 'budget richieste esaurito')
        report['requests_made'] += 1
        result = request(query,vars)
        return _dict(result,'GraphQL.data'),now()
    try:
        ident,_ = ask(IDENTITY)
        if not mainnet(ident.get('chainIdentifier')):
            raise SourceProblem('IDENTITA_NON_VERIFICATA','chainIdentifier non mainnet')
        service = _dict(ident.get('serviceConfig'),'serviceConfig')
        rng = service.get('availableRange')
        try:
            if not isinstance(rng, dict) or not isinstance(rng.get('first'), dict) or not isinstance(rng.get('last'), dict):
                raise ValueError('estremi intervallo assenti')
            first_cp = uint(rng['first'].get('sequenceNumber'), allow_zero=True)
            last_cp = uint(rng['last'].get('sequenceNumber'), allow_zero=True)
            if first_cp > last_cp:
                raise ValueError('estremi intervallo invertiti')
        except ValueError:
            report['coverage']='NON_DETERMINABILE'
        else:
            report['coverage']={'first_checkpoint':first_cp,
                  'last_checkpoint':last_cp,
                  'scope':'Query.transactions filter=function; campione limitato; contiguita interna non dimostrata'}
        report['statuses']['identity']='VERIFICATA'
        global_seen={}
        seen_sources={}
        conflicted_keys=set()
        conflict_families=set()
        for label,func in (('staking',STAKING),('unstaking',UNSTAKING)):
            try:
                d,_=ask(FILTER,{'function':func})
                conn=_dict(d.get('transactions'),'transactions')
                nodes=conn.get('nodes')
                page=_dict(conn.get('pageInfo'),'transactions.pageInfo')
                if not isinstance(nodes,list) or type(page.get('hasPreviousPage')) is not bool:
                    raise SourceProblem('RISPOSTA_INCOMPLETA','filtro nodes/pageInfo malformato')
                incomplete = page['hasPreviousPage'] or report['coverage']=='NON_DETERMINABILE'
                report['statuses'][f'{label}_coverage']=('COPERTURA_INSUFFICIENTE' if incomplete else 'CAMPIONE_LIMITATO_NON_GENERALE')
                status='NESSUN_EVENTO_NEL_CAMPIONE' if not nodes else 'EVENTO_NON_VERIFICABILE'
                for node in nodes[:3]:
                    node=_dict(node,'transactions.nodes entry')
                    digest=node.get('digest')
                    if not isinstance(digest,str):
                        raise SourceProblem('RISPOSTA_INCOMPLETA','digest filtro malformato')
                    first, acquired = ask(LOOKUP,{'digest':digest,'after':None})
                    tx=_dict(first.get('transaction'),'transaction')
                    if tx.get('digest') != digest:
                        raise SourceProblem('EVENTO_NON_VERIFICABILE','digest mismatch')
                    def next_page(digest_,cursor):
                        nonlocal acquired
                        response, acquired = ask(LOOKUP,{'digest':digest_, 'after':cursor})
                        return _dict(response.get('transaction'),'transaction')
                    full=collect_pages(tx,next_page)
                    found,event_status=parse_stake(full,label,acquired,str(report['coverage']))
                    if found:
                        for o in found:
                            key=(o.transaction,o.details['staked_sui_object'],o.event)
                            if key in conflicted_keys:
                                conflict_families.add(label)
                                continue
                            prior=global_seen.get(key)
                            if prior is not None:
                                if prior.quantity != o.quantity:
                                    del global_seen[key]
                                    conflicted_keys.add(key)
                                    conflict_families.update(seen_sources[key])
                                    conflict_families.add(label)
                                    report['statuses']['cross_filter_conflict']='RISPOSTA_INCOERENTE'
                                    continue
                                report['statuses']['cross_filter_duplicate']='SCARTATO'
                                seen_sources[key].add(label)
                                continue
                            global_seen[key]=o
                            seen_sources[key]={label}
                        status='OGGETTO_VERIFICATO_ATTRIBUZIONE_NON_DIMOSTRATA'
                    elif status != 'OGGETTO_VERIFICATO_ATTRIBUZIONE_NON_DIMOSTRATA':
                        status=event_status
                report['statuses'][label]=status
            except SourceProblem as exc:
                report['statuses'][label]=exc.state
                report['statuses'][f'{label}_detail']=str(exc)
    except SourceProblem as exc:
        report['statuses']['identity']=exc.state
        report['statuses']['identity_detail']=str(exc)
        report['statuses']['staking']='NON_ESEGUITO_IDENTITA_NON_VERIFICATA'
        report['statuses']['unstaking']='NON_ESEGUITO_IDENTITA_NON_VERIFICATA'
    if report['statuses'].get('identity') == 'VERIFICATA':
        for family in conflict_families:
            report['statuses'][family]='RISPOSTA_INCOERENTE'
        report['observations'].extend(o.to_decision_context() for o in global_seen.values())
    if include_circulation:
        try:
            report['observations'].append(circulation().to_decision_context())
            report['statuses']['circulation']='PROGRAMMA_ACQUISITO'
        except SourceProblem as exc:
            report['statuses']['circulation']=exc.state
    report['acquired_utc']=now()
    report['decision_utility']='NON_DIMOSTRATA'
    report['market_pair_context']='SUI/EUR Kraken spot: ASSOCIAZIONE FUTURA, NESSUN DATO MERCATO ACQUISITO'
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description='KDD G2R1 Sui on-chain, consultazione manuale')
    p.add_argument('--live',action='store_true',help='richieste pubbliche; default nessuna rete')
    p.add_argument('--circulation',action='store_true',help='includi programma circolazione')
    args=p.parse_args()
    if not args.live:
        p.error('nessuna richiesta eseguita senza --live')
    print(json.dumps(run(include_circulation=args.circulation),ensure_ascii=False,indent=2))
