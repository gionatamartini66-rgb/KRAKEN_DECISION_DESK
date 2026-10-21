"""Bounded read-only Sui Mainnet pilot; manual use, stdlib-only, no state persistence."""
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
MAX_BYTES = 1_000_000
LOOKUP = '''query($digest: String!) { transaction(digest: $digest) {
 digest effects { status timestamp checkpoint { sequenceNumber }
 objectChanges { nodes { address idCreated idDeleted
 inputState { asMoveObject { contents { type { repr } json } } }
 outputState { asMoveObject { contents { type { repr } json } } } } }
 } } }'''
FILTER = '''query($function: String!) { transactions(last: 3, filter:{function:$function}) {
 pageInfo { hasPreviousPage startCursor } nodes { digest } } }'''
IDENTITY = 'query { chainIdentifier serviceConfig { availableRange(type:"Query",field:"transactions",filters:["function"]) { first {sequenceNumber} last {sequenceNumber} } } }'


class SourceProblem(Exception):
    def __init__(self, state, message):
        super().__init__(message)
        self.state = state


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


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
    """No retry. Reject GraphQL partial-success as failure, including HTTP 200."""
    payload = json.dumps({'query': query, 'variables': variables or {}}, separators=(',', ':')).encode()
    if len(payload) > 5000:
        raise SourceProblem('RICHIESTA_TROPPO_GRANDE', 'limite payload')
    req = urllib.request.Request(ENDPOINT, data=payload,
             headers={'Content-Type': 'application/json', 'User-Agent': 'KDD-Onchain-G2/0.1 read-only'}, method='POST')
    try:
        response = (transport or urllib.request.urlopen)(req, timeout=12)
        with response as conn:
            raw = conn.read(MAX_BYTES+1)
            if len(raw) > MAX_BYTES:
                raise SourceProblem('RISPOSTA_TROPPO_GRANDE', 'limite risposta')
    except urllib.error.HTTPError as exc:
        state = 'RATE_LIMIT' if exc.code == 429 else 'ERRORE_HTTP'
        raise SourceProblem(state, f'HTTP {exc.code}') from exc
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        raise SourceProblem('FONTE_NON_DISPONIBILE', type(exc).__name__) from exc
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceProblem('RISPOSTA_INCOMPLETA', 'JSON invalido') from exc
    if not isinstance(doc, dict) or doc.get('errors'):
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


def parse_stake(tx, kind, acquired, coverage):
    """Only record a verified changed StakedSui principal; no inferred net flow."""
    if not isinstance(tx, dict) or not re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{32,64}', str(tx.get('digest', ''))):
        raise SourceProblem('EVENTO_NON_VERIFICABILE', 'digest invalido')
    effects = tx.get('effects')
    if not isinstance(effects, dict):
        raise SourceProblem('EVENTO_NON_VERIFICABILE', 'effects assenti')
    if effects.get('status') != 'SUCCESS':
        return [], 'TRANSAZIONE_FALLITA' if effects.get('status') else 'EVENTO_NON_VERIFICABILE'
    timestamp = effects.get('timestamp')
    checkpoint = (effects.get('checkpoint') or {}).get('sequenceNumber')
    try:
        stamp = utc(timestamp)
        cp = uint(checkpoint, allow_zero=True)
    except (ValueError, AttributeError) as exc:
        raise SourceProblem('EVENTO_NON_VERIFICABILE', 'timestamp/checkpoint non validi') from exc
    changes = (effects.get('objectChanges') or {}).get('nodes')
    if not isinstance(changes, list):
        raise SourceProblem('EVENTO_NON_VERIFICABILE', 'objectChanges assenti')
    out = []
    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            continue
        side = 'outputState' if kind == 'staking' else 'inputState'
        state = ((change.get(side) or {}).get('asMoveObject') or {}).get('contents')
        if not isinstance(state, dict) or _normalized_type((state.get('type') or {}).get('repr')) != STAKED:
            continue
        if kind == 'staking' and change.get('idCreated') is not True:
            continue
        if kind == 'unstaking' and change.get('idDeleted') is not True:
            continue
        obj = change.get('address')
        if not isinstance(obj, str) or not re.fullmatch(r'0x[0-9a-fA-F]{1,64}', obj):
            continue
        if obj in seen:
            continue
        raw = (state.get('json') or {}).get('principal')
        try:
            amount = units(raw)
        except ValueError:
            continue
        seen.add(obj)
        out.append(Observation(
            kind='FATTO_OSSERVATO', asset='SUI', chain='sui:mainnet', asset_id=COIN,
            event='STAKING_PRINCIPALE' if kind == 'staking' else 'UNSTAKING_PRINCIPALE_CONSUMATO',
            quantity=amount, unit='SUI', transaction=tx['digest'], block_reference=str(cp),
            event_utc=stamp, acquired_utc=acquired, reference_period=stamp,
            knowable_utc=stamp, source=ENDPOINT, coverage=coverage, verification='VERIFICATO',
            limits=('Singola transazione, non flusso netto di rete.',
                    'Principal di StakedSui, non saldo exchange o vendita.'),
            compatible=('Delegazione di principal' if kind == 'staking' else 'Consumo di un oggetto StakedSui',),
            prohibited=('BUY/SELL', 'Intenzione del proprietario', 'Pressione immediata di mercato'),
            economic_relevance='Modifica individuale dei token impegnati nello staking.',
            details={'staked_sui_object': obj, 'principal_mist': str(raw), 'operation': kind}
        ))
    return out, 'VERIFICATO' if out else 'EVENTO_NON_VERIFICABILE'


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
        economic_relevance='Contesto programmatico di offerta, privo di implicazione direzionale automatica.')


def read_circulation(transport=None):
    req = urllib.request.Request(CIRCULATION, headers={'Accept':'application/json','User-Agent':'KDD-Onchain-G2/0.1 read-only'})
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
    """1 identity + 2 bounded filters + <=6 detail lookups; no background tasks."""
    start = now()
    report = {'acquired_utc':start, 'network':'sui:mainnet', 'statuses':{}, 'observations':[],
              'coverage':None, 'requests_max':MAX_CALLS, 'requests_made':0}
    def ask(query, vars=None):
        if report['requests_made'] >= MAX_CALLS:
            raise SourceProblem('LIMITE_RICHIESTE', 'budget esaurito')
        report['requests_made'] += 1
        return request(query, vars)
    try:
        ident = ask(IDENTITY)
        if not isinstance(ident, dict):
            raise SourceProblem('RISPOSTA_INCOMPLETA', 'identita non presente')
        if not mainnet(ident.get('chainIdentifier')):
            raise SourceProblem('IDENTITA_NON_VERIFICATA','chainIdentifier non mainnet')
        rng = ((ident.get('serviceConfig') or {}).get('availableRange') or {})
        if not isinstance(rng.get('first'), dict) or not isinstance(rng.get('last'), dict):
            report['coverage']='NON_DETERMINABILE'
        else:
            report['coverage']={'first_checkpoint':rng['first'].get('sequenceNumber'),
                                'last_checkpoint':rng['last'].get('sequenceNumber'),
                                'scope':'Query.transactions filter=function; non copertura totale'}
        report['statuses']['identity']='VERIFICATA'
        for label, func in (('staking',STAKING), ('unstaking',UNSTAKING)):
            try:
                d = ask(FILTER, {'function':func})
                txs = (d.get('transactions') or {}).get('nodes')
                if not isinstance(txs, list):
                    raise SourceProblem('RISPOSTA_INCOMPLETA','transactions.nodes assenti')
                status = 'EVENTO_NON_TROVATO'
                for tx in txs[:3]:
                    if not isinstance(tx,dict) or not isinstance(tx.get('digest'),str):
                        raise SourceProblem('RISPOSTA_INCOMPLETA','digest assente')
                    data = ask(LOOKUP, {'digest':tx['digest']})
                    if (data.get('transaction') or {}).get('digest') != tx['digest']:
                        raise SourceProblem('EVENTO_NON_VERIFICABILE','mismatch digest lookup')
                    obs, event_status = parse_stake(data['transaction'],label,start,str(report['coverage']))
                    if obs:
                        report['observations'].extend(o.to_decision_context() for o in obs)
                        status='VERIFICATO'
                    elif status != 'VERIFICATO':
                        status=event_status
                report['statuses'][label]=status
                report['statuses'][f'{label}_pagination']='CAMPIONE_PARZIALE_NON_AGGREGABILE'
            except SourceProblem as exc:
                report['statuses'][label]=exc.state
                report['statuses'][f'{label}_detail']=str(exc)
    except SourceProblem as exc:
        report['statuses']['identity']=exc.state
        report['statuses']['identity_detail']=str(exc)
        report['statuses']['staking']='NON_ESEGUITO_IDENTITA_NON_VERIFICATA'
        report['statuses']['unstaking']='NON_ESEGUITO_IDENTITA_NON_VERIFICATA'
    if include_circulation:
        try:
            report['observations'].append(circulation().to_decision_context())
            report['statuses']['circulation']='PROGRAMMA_ACQUISITO'
        except SourceProblem as exc:
            report['statuses']['circulation']=exc.state
    report['decision_utility']='NON_DIMOSTRATA'
    report['market_pair_context']='SUI/EUR Kraken spot: ASSOCIAZIONE FUTURA, NESSUN DATO MERCATO ACQUISITO'
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(description='KDD G2 Sui on-chain, solo consultazione manuale')
    p.add_argument('--live',action='store_true',help='autorizza richieste pubbliche; default non esegue rete')
    p.add_argument('--circulation',action='store_true',help='includi fonte programma circolazione')
    args=p.parse_args()
    if not args.live:
        p.error('nessuna richiesta eseguita senza --live')
    print(json.dumps(run(include_circulation=args.circulation),ensure_ascii=False,indent=2))
