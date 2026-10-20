"""Verifica PROSPETTICA del confronto GPT senza/con flusso spot.

Fasi A e B sono congelate in file JSON immutabili: il modulo misura solo
l'evoluzione successiva delle chiusure spot Kraken. Non ricostruisce
esecuzioni, fill, PnL, successo di strategia o causalità.
Si aggiorna quando viene richiamato il programma, NON in background.
"""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import time
import decision_desk as desk

ROOT = Path(__file__).resolve().parent / 'esperimenti_delta'
HORIZONS = (1, 4, 24)
INTERVAL = 900
MAX_API_CALLS = 4


def parsed(iso):
    x = dt.datetime.fromisoformat(iso.replace('Z', '+00:00'))
    if x.tzinfo is None:
        raise ValueError('Timezone mancante')
    return x.astimezone(dt.timezone.utc).timestamp()


def paired(b_path):
    b = json.loads(b_path.read_text(encoding='utf-8'))
    a_path = ROOT / b['fase_A_nome']
    if not a_path.name.endswith('_fase_A.json') or a_path.parent != ROOT:
        raise ValueError('Percorso fase A non valido')
    digest = hashlib.sha256(a_path.read_bytes()).hexdigest()
    if digest != b['fase_A_sha256']:
        raise ValueError('Fase A manomessa: hash non corrisponde')
    a = json.loads(a_path.read_text(encoding='utf-8'))
    if (a['fase'] != 'A_SENZA_DELTA_CONGELATA'
        or b['fase'] != 'B_CON_DELTA_CONGELATA'
        or a['snapshot_kraken_utc'] != b['snapshot_kraken_utc']):
        raise ValueError('Fasi sperimentali incompatibili')
    ca = {x['token']: x for x in a['candidati']}
    cb = {x['token']: x for x in b['candidati']}
    if set(ca) != set(cb):
        raise ValueError('Candidati differenti nelle due fasi')
    for token, row in cb.items():
        if (row['coppia'] != ca[token]['coppia']
                or row['finestra_a_utc'] != ca[token]['riferimento_chiusura_15m_utc']
                or row['delta_candela_stato'] != 'COMPLETA'):
            raise ValueError('Intervalli temporali non allineati')
    return a, b


def outcome(raw, base_time, ref_price, hour, now):
    """Prezzo dell'esatta candela 15m CHIUSA all'orizzonte previsto."""
    if not 0 < ref_price < float('inf'):
        raise ValueError('Prezzo di riferimento invalido')
    target = base_time + hour * 3600
    if target > now:
        return {'stato': 'NON_MATURO'}
    matches = []
    for row in raw:
        if len(row) < 7:
            continue
        end = float(row[0]) + INTERVAL
        if end == target and end <= now:
            last, hi, low = map(float, (row[4], row[2], row[3]))
            if all(math.isfinite(x) and x > 0 for x in (last, hi, low)) and low <= last <= hi:
                matches.append(last)
    if len(matches) != 1:
        return {'stato': 'DATI_NON_COPERTI', 'motivo': 'Candela finale chiusa assente o incoerente'}
    return {'stato': 'CHIUSURA_OSSERVATA',
            'orizzonte_ore': hour,
            'chiusura_finale_utc': dt.datetime.fromtimestamp(target, dt.timezone.utc).isoformat(),
            'prezzo_finale_quote': matches[0],
            'variazione_prezzo_pct': round(100 * (matches[0] / ref_price - 1), 4),
            'nota': 'Variazione fra chiusure, NON rendimento di un ordine.'}


def verify(max_calls=MAX_API_CALLS, now=None, api=None):
    if not isinstance(max_calls, int) or not 0 <= max_calls <= MAX_API_CALLS:
        raise ValueError('Budget massimo quattro API per aggiornamento')
    now = desk.NOW().timestamp() if now is None else now
    api = desk.kraken if api is None else api
    checked = 0
    stats = {'stato': 'NESSUNA_PROVA', 'aggiornato_utc': dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
             'esperimenti': 0, 'casi': 0, 'orizzonti_maturi_con_esito': 0,
             'orizzonti_totali': 0, 'chiamate_kraken': 0, 'errori': []}
    if not ROOT.exists():
        return stats
    for b_path in sorted(ROOT.glob('*_fase_B.json')):
        try:
            a, b = paired(b_path)
        except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
            stats['errori'].append(b_path.name + ': ' + type(exc).__name__)
            continue
        stats['esperimenti'] += 1
        cases = {x['token']: x for x in a['candidati']}
        stats['casi'] += len(cases)
        results_path = ROOT / b_path.name.replace('_fase_B.json', '_esiti.json')
        existing = json.loads(results_path.read_text()) if results_path.exists() else {}
        stored = existing.get('esiti', {})
        updated = False
        for token, row in cases.items():
            saved = stored.setdefault(token, {})
            base_time = parsed(row['riferimento_chiusura_15m_utc'])
            ref = float(row['prezzo_riferimento_quote'])
            due = [h for h in HORIZONS if base_time + h * 3600 <= now
                   and str(h) not in saved]
            stats['orizzonti_totali'] += len(HORIZONS)
            if due and checked < max_calls:
                key = next(x['pair_key_kraken'] for x in b['candidati'] if x['token'] == token)
                try:
                    response = api('OHLC', pair=key, interval=15)
                    raw = next(v for k,v in response.items() if k != 'last')
                    checked += 1
                    for hour in due:
                        value = outcome(raw, base_time, ref, hour, now)
                        if value['stato'] == 'CHIUSURA_OSSERVATA':
                            saved[str(hour)] = value
                            updated = True
                        # Dati temporaneamente assenti NON si archiviano come esito.
                    time.sleep(.2)
                except Exception as exc:
                    checked += 1
                    stats['errori'].append(token + ': ' + type(exc).__name__)
            stats['orizzonti_maturi_con_esito'] += sum(
                (str(h) in saved and saved[str(h)].get('stato') == 'CHIUSURA_OSSERVATA')
                for h in HORIZONS)
        if updated:
            # A/B restano immutati: solo le nuove osservazioni entrano nel file esiti.
            payload = {'fase_B_nome': b_path.name,
                       'fase_B_sha256': hashlib.sha256(b_path.read_bytes()).hexdigest(),
                       'aggiornato_utc': dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
                       'esiti': stored,
                       'nota': 'Chiusure a +1h/+4h/+24h dalla candela di riferimento, non trading.'}
            results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    stats['chiamate_kraken'] = checked
    stats['stato'] = ('PARZIALE' if stats['errori']
                      else 'NESSUNA_PROVA' if not stats['esperimenti']
                      else 'IN_OSSERVAZIONE' if stats['orizzonti_maturi_con_esito'] < stats['orizzonti_totali']
                      else 'ORIZZONTI_COMPLETI')
    return stats


def safe_verify():
    try:
        status = verify()
    except Exception as exc:
        status = {'stato': 'ERRORE', 'errori': [type(exc).__name__ + ': ' + str(exc)[:100]]}
    desk.save('esperimenti_delta/stato_verifiche.json', status) if ROOT.exists() else None
    return status


if __name__ == '__main__':
    print(json.dumps(safe_verify(), ensure_ascii=False, indent=2))
