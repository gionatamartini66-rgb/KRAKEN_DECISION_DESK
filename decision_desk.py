#!/usr/bin/env python3
"""Kraken Decision Desk V0.1: tool locale senza chiavi API e senza trading automatico.
Solo libreria standard Python. Richieste HTTPS alle API pubbliche Kraken e ai feed ufficiali.
"""
from __future__ import annotations
import argparse
import datetime as dt
import html
import hashlib
import re
import json
import math
from decimal import Decimal, InvalidOperation
import pathlib
import statistics
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import analisi_v02 as tactical
import mercati_spot as multi
import costi_spot as costs
import piano_gpt

DIR = pathlib.Path(__file__).resolve().parent
BASE = 'https://api.kraken.com/0/public/'
NOW = lambda: dt.datetime.now(dt.timezone.utc)


# Controllo minimo di continuità: il README deve descrivere il codice che eseguiamo.
# Un checksum non prova che il testo sia buono: prova soltanto che non sia rimasto
# il checkpoint della versione precedente dopo una modifica ai file sorgente.
CHECKPOINT_PATTERN = r"^<!-- CHECKPOINT_SORGENTI_SHA256: ([a-f0-9]{64}) -->$"


def fingerprint_sorgenti():
    h = hashlib.sha256()
    files = sorted(DIR.glob('*.py'), key=lambda p: p.name) + [DIR / 'config.json']
    for path in files:
        if not path.exists():
            continue
        h.update(path.name.encode('utf-8') + b'\0' + path.read_bytes() + b'\0')
    return h.hexdigest()


def checkpoint_allineato():
    p = DIR / 'README.md'
    if not p.exists():
        return False
    m = re.search(CHECKPOINT_PATTERN, p.read_text(encoding='utf-8'), re.MULTILINE)
    return bool(m and m.group(1) == fingerprint_sorgenti())
FEEDS = [
    ('Fed — politica monetaria', 'https://www.federalreserve.gov/feeds/press_monetary.xml', 'macro'),
    ('BCE — comunicati e discorsi', 'https://www.ecb.europa.eu/rss/press.html', 'macro'),
    ('BCE — operazioni di mercato', 'https://mid.ecb.europa.eu/rss/mid.xml', 'macro'),
    ('Consiglio UE — comunicati', 'https://www.consilium.europa.eu/en/rss/pressreleases.ashx', 'geopolitica'),
]
STABLES = {'USDT','USDC','EURC','DAI','RLUSD','PYUSD','EUROP','USDG','EURQ'}
SKIP_BASE = {'EUR','USD','GBP','CAD','CHF','JPY'} | STABLES

def load(name, default=None):
    p = DIR / name
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default

def save(name, obj):
    (DIR / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def request(url, timeout=18):
    req = urllib.request.Request(url, headers={'User-Agent': 'KrakenDecisionDesk/0.1 (manual, read-only)', 'Accept': 'application/json,application/xml,text/xml,application/rss+xml'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(7_000_000)

def kraken(endpoint, **params):
    q = urllib.parse.urlencode(params)
    url = BASE + endpoint + (('?' + q) if q else '')
    j = json.loads(request(url).decode('utf-8'))
    if j.get('error'):
        raise RuntimeError('Kraken ' + ', '.join(j['error']))
    return j['result']

def num(x):
    try: return float(x)
    except (ValueError, TypeError, OverflowError): return 0.0

def canonical(s):
    return {'XBT': 'BTC', 'XXBT': 'BTC', 'XDG': 'DOGE', 'XXDG': 'DOGE'}.get(s.upper(), s.upper())


# Boundary for manually entered holdings only. Do not change num() because
# scanner, market data, fees and other subsystems share its old contract.
_WALLET_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_WALLET_SYMBOL_RE = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,31}\Z")


def wallet_symbol(raw):
    """Return (displayed identity, valid). Never guess an invalid asset."""
    if not isinstance(raw, str):
        return ('identificativo assente' if raw is None else str(raw)[:120], False)
    symbol = raw.strip().upper()
    if not (_WALLET_SYMBOL_RE.fullmatch(symbol) and
            any('A' <= c <= 'Z' for c in symbol)):
        return (raw[:120] or 'identificativo assente', False)
    return symbol, True


def wallet_number(raw):
    """Finite nonnegative monetary/quantity number; reason on every failure.

    Decimal first prevents positive subnormal input from silently becoming zero
    in the float representation used by the existing JSON schema.
    """
    if raw is None:
        return None, 'NON_NOTO'
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None, 'NON_NUMERICO'
    if isinstance(raw, str):
        # These are valid spellings for Decimal/float non-finite numbers,
        # but they are never valid holding quantities or cost bases.
        if raw.strip().lower() in ('nan', '+nan', '-nan', 'inf', '+inf',
                                   '-inf', 'infinity', '+infinity', '-infinity'):
            return None, 'NON_FINITO'
        if not _WALLET_NUMBER_RE.fullmatch(raw.strip()):
            return None, 'NON_NUMERICO'
    try:
        number = Decimal(str(raw).strip())
        if not number.is_finite():
            return None, 'NON_FINITO'
        if number < 0:
            return None, 'NEGATIVO'
        value = float(number)
        if not math.isfinite(value) or (number > 0 and value == 0):
            return None, 'FUORI_SCALA'
        return value, 'VALIDO'
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None, 'NON_NUMERICO'


def wallet_quantity_display(raw):
    """JSON-safe representation of invalid input, without invented zeros."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw[:120]
    if isinstance(raw, bool):
        return str(raw)
    if isinstance(raw, float) and not math.isfinite(raw):
        return str(raw)
    if isinstance(raw, (int, float)):
        return raw
    return str(raw)[:120]


def pct(current, old):
    return (current / old - 1) * 100 if old > 0 else None

def market_pairs_and_ticker(pairs, tickers):
    """Solo coppie spot EUR online, una riga per token, segnalando copertura incompleta."""
    out = {}
    for key, meta in pairs.items():
        name = meta.get('wsname', '')
        if '/' not in name or meta.get('status') != 'online': continue
        base, quote = name.split('/', 1)
        base = canonical(base)
        if quote != 'EUR' or base in SKIP_BASE or '.d' in key.lower(): continue
        t = tickers.get(key)
        if not t: continue
        last = num(t.get('c', [0])[0]); op = num(t.get('o'))
        ask = num(t.get('a', [0])[0]); bid = num(t.get('b', [0])[0])
        if not (last > 0 and op > 0 and ask > 0 and bid > 0 and ask >= bid): continue
        spread = ((ask-bid)/((ask+bid)/2))*100
        day = pct(last, op)
        v = num((t.get('v') or [0,0])[-1]); volume_eur_est = v * last
        row = {'token': base, 'pair_key': key, 'pair': name, 'prezzo_eur': last,
               'var_oggi_utc_pct': day, 'volume_24h_eur_stimato': volume_eur_est,
               'spread_pct': spread, 'costo_min_eur': num(meta.get('costmin')),
               'quantita_min': num(meta.get('ordermin'))}
        prev = out.get(base)
        if not prev or row['volume_24h_eur_stimato'] > prev['volume_24h_eur_stimato']:
            out[base] = row
    return out

def wallet_spot_markets(legacy_eur, assembled, portfolio):
    """Reuse the public Kraken multi-quote catalog for held USD/USDC-only assets.

    Existing EUR market rows remain unchanged; no direct FX rate -> no row
    from mercati_spot.assemble -> no fabricated EUR valuation.
    """
    result = dict(legacy_eur)
    rows = portfolio.get('posizioni') if isinstance(portfolio,dict) else []
    for row in rows if isinstance(rows,list) else []:
        if not isinstance(row,dict):
            continue
        symbol, valid = wallet_symbol(row.get('token'))
        if not valid:
            continue
        token = canonical(symbol)
        multi = assembled.get(token) if isinstance(assembled,dict) else None
        if token not in result and isinstance(multi,dict):
            result[token] = dict(multi,
                                 fonte_quotazione='Kraken Spot Ticker + cambio diretto Kraken')
    return result


def calc_trend(candles, spot):
    # L'ultima candela OHLC Kraken è in formazione. Non trattarla come chiusura ufficiale.
    closed = [num(r[4]) for r in candles[:-1] if len(r) > 4 and num(r[4]) > 0]
    if len(closed) < 31: return {'errore': 'Storico giornaliero insufficiente'}
    d7, d30 = pct(spot, closed[-7]), pct(spot, closed[-30])
    ma20 = statistics.mean(closed[-20:])
    highs = max(closed[-30:]); dd30 = pct(spot, highs)
    return {'var_7g_pct': d7, 'var_30g_pct': d30, 'media_20g_eur': ma20,
            'sopra_media20': spot >= ma20, 'distanza_massimo_chiusure30_pct': dd30}

def trend_spot_quotato(candles, market):
    """Compare OHLC and spot in the *same* Kraken quote currency."""
    quote = market.get("quote", "EUR")
    if quote not in ("EUR", "USD", "USDC"):
        return {"errore": "Valuta mercato non riconosciuta"}
    base = (market.get("prezzo_quote") if quote!="EUR"
            else market.get("prezzo_eur"))
    price = num(base)
    if price <= 0:
        return {"errore": "Prezzo spot nella valuta della candela non disponibile"}
    result = calc_trend(candles, price)
    if quote!="EUR" and "media_20g_eur" in result:
        result["media_20g_quote"] = result.pop("media_20g_eur")
        result["valuta_quotazione"] = quote
    return result


def fetch_feed(name, url, kind):
    items = []
    try:
        root = ET.fromstring(request(url, timeout=12))
        # RSS 2.0 o Atom, valori soltanto; nessuna interpretazione automatica.
        candidates = list(root.findall('.//item'))
        if not candidates: candidates = list(root.findall('.//{http://www.w3.org/2005/Atom}entry'))
        for item in candidates[:5]:
            def element_text(tag1, tag2):
                e = item.find(tag1)
                if e is None: e = item.find(tag2)
                return (e.text or '').strip() if e is not None else ''
            title = element_text('title', '{http://www.w3.org/2005/Atom}title')
            link = element_text('link', '{http://www.w3.org/2005/Atom}link')
            if not link:
                a = item.find('{http://www.w3.org/2005/Atom}link')
                link = a.get('href', '') if a is not None else ''
            date = element_text('pubDate', '{http://www.w3.org/2005/Atom}updated')
            if title: items.append({'fonte': name, 'titolo': title, 'link': link, 'data': date, 'classe': kind})
        return items, None
    except Exception as exc:
        return [], f'{name}: {exc.__class__.__name__}'

def stato_saldo(portfolio, tentativo=None, now=None):
    """Distingue fonte dell'ultima acquisizione, età e tentativo di refresh.

    Il fatto che un saldo derivi da BalanceEx NON significa che sia corrente.
    Il limite di 30 minuti è un indicatore prudenziale, non una regola di trading.
    """
    now = now or NOW()
    source = portfolio.get('fonte_quantita') if isinstance(portfolio, dict) else None
    raw_time = portfolio.get('data_ora_saldo_privato_utc') if isinstance(portfolio, dict) else None
    known_source = isinstance(source, str) and source.startswith(
        'Kraken BalanceEx API privata SOLA LETTURA, ')
    acquired = None
    age = None
    state = 'ASSENTE_O_IGNOTO'
    if known_source and isinstance(raw_time, str):
        try:
            acquired = dt.datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
            if acquired.tzinfo is None:
                raise ValueError('fuso orario assente')
            acquired = acquired.astimezone(dt.timezone.utc)
            age = (now - acquired).total_seconds() / 60
            if age < -2:
                state = 'ORARIO_FUTURO_NON_ATTENDIBILE'
            elif age < 0:
                state = 'OROLOGI_NON_ALLINEATI'
            else:
                state = 'RECENTE' if age <= 30 else 'NON_RECENTE'
        except (TypeError, ValueError, OverflowError):
            acquired = None
            age = None
            state = 'ORARIO_NON_VALIDO'
    elif known_source:
        state = 'ORARIO_ASSENTE'
    attempt = tentativo if isinstance(tentativo, dict) else {}
    coerenza_tentativo = 'NON_DOCUMENTATA'
    checked_raw = attempt.get('controllato_utc')
    if attempt and checked_raw is None:
        coerenza_tentativo = 'ORARIO_TENTATIVO_NON_FORNITO'
    elif checked_raw is not None:
        try:
            checked = dt.datetime.fromisoformat(checked_raw.replace('Z', '+00:00'))
            if checked.tzinfo is None:
                raise ValueError('fuso orario tentativo assente')
            checked = checked.astimezone(dt.timezone.utc)
            if checked > now + dt.timedelta(minutes=2):
                coerenza_tentativo = 'ORARIO_TENTATIVO_FUTURO'
                attempt = {}
            elif acquired is not None and checked < acquired - dt.timedelta(seconds=2):
                # rigenera puo' combinare un vecchio snapshot con un saldo aggiornato in seguito.
                coerenza_tentativo = 'NON_CORRELATO_AL_SALDO'
                attempt = {}
            else:
                coerenza_tentativo = 'ORDINE_TEMPORALE_COMPATIBILE'
        except (AttributeError, TypeError, ValueError, OverflowError):
            coerenza_tentativo = 'ORARIO_TENTATIVO_NON_VALIDO'
            attempt = {}
    return {
        'coerenza_tentativo_con_saldo': coerenza_tentativo,
        'origine': 'KRAKEN_BALANCEEX' if known_source else 'IGNOTA_O_ALTRA',
        'portafoglio_aggiornato_da_api_private': bool(known_source and acquired is not None
                                                     and age is not None and age >= 0),
        'acquisizione_saldo_utc': acquired.isoformat(timespec='seconds') if acquired else None,
        'eta_saldo_minuti': round(age, 2) if age is not None and age >= 0 else None,
        'freschezza_saldo': state,
        'ultimo_tentativo': attempt.get('stato', 'NON_DOCUMENTATO'),
        'ultimo_tentativo_utc': attempt.get('controllato_utc'),
        'ultimo_errore_tipo': attempt.get('errore_tipo'),
    }


def aggiorna_saldo_sola_lettura():
    """Se la lettura privata fallisce, non blocca il refresh pubblico né cancella saldi."""
    state = 'NON_CONFIGURATO'
    errore = None
    try:
        import kraken_readonly as account
        if account.AUTH.is_file():
            account.refresh()
            state = 'RIUSCITO'
    except (Exception, SystemExit) as exc:
        state = 'FALLITO'
        errore = type(exc).__name__
        print('ATTENZIONE: saldo privato non aggiornato:', errore)
    return {'stato': state, 'controllato_utc': NOW().isoformat(timespec='seconds'),
            'errore_tipo': errore}


def load_decisions():
    p = DIR / 'decisioni.jsonl'
    if not p.exists(): return []
    out = []
    for line in p.read_text(encoding='utf-8').splitlines():
        try: out.append(json.loads(line))
        except json.JSONDecodeError: continue
    return out

def decision_state(token, decisions, now):
    options = [x for x in decisions
               if isinstance(x, dict) and isinstance(x.get('token'), str)
               and x['token'].strip().upper() in (token, 'PORTAFOGLIO')]
    if not options:
        return 'NESSUNA DECISIONE REGISTRATA: formulare una scelta; non equivale a HOLD.'
    last = max(options, key=lambda x: x.get('creata_utc', ''))
    try: expiry = dt.datetime.fromisoformat(last['scade_utc'])
    except (ValueError, KeyError): return 'DECISIONE senza scadenza valida: correggere il registro.'
    if now >= expiry:
        return f"REVISIONE SCADUTA: {last['scelta']} — riesaminare oggi."
    return f"{last['scelta']} fino al {expiry.strftime('%d/%m %H:%M UTC')} — {last['motivo']}"

def signals(row, trend):
    """Inneschi di ESAME, non segnali di compra/vendi né previsioni."""
    notes = []
    if not trend or 'errore' in trend:
        return ['ANALISI DEL TOKEN INCOMPLETA: storico insufficiente; verifica manuale richiesta.']
    if (trend['var_7g_pct'] or 0) >= 12:
        notes.append('RIALZO SETTIMANALE: valutare se alleggerire una posizione in guadagno; controllare costo fiscale e contesto.')
    if (trend['var_7g_pct'] or 0) <= -12:
        notes.append('RIBASSO SETTIMANALE: riesaminare la tesi del token e concentrazione; evitare mediazioni automatiche.')
    if not trend['sopra_media20'] and (trend['var_30g_pct'] or 0) < 0:
        notes.append('DEBOLEZZA DI TENDENZA: approfondire rischio e alternative; nessuna vendita automatica.')
    if not notes: notes.append('NESSUN ALLARME QUANTITATIVO: revisione programmata comunque obbligatoria.')
    return notes

def context_status(c, now):
    info = {}
    for area in ('macroeconomia','geopolitica'):
        x = c.get(area, {})
        updated = x.get('aggiornato_utc', '')
        try:
            when = dt.datetime.fromisoformat(updated.replace('Z','+00:00'))
            age = (now - when).total_seconds()/86400
        except (ValueError, TypeError): age = 9999
        valid = bool(x.get('valutazione') and x.get('fonte') and age <= x.get('validita_giorni', 7))
        info[area] = {'stato': 'VALUTATO' if valid else 'DA_VERIFICARE',
                      'testo': x.get('valutazione','') if valid else 'Nessuna valutazione documentata e aggiornata.',
                      'fonte': x.get('fonte','') if valid else '', 'eta_giorni': round(age, 1)}
    return info

def build_report(data, portfolio, conf, ctx, decisions):
    rilevazione = dt.datetime.fromisoformat(data['rilevazione_utc'])
    now = NOW()
    pairs = data['markets']; trends = data['trends']
    holdings = []
    positions = portfolio.get('posizioni') or []
    if not isinstance(positions, list):
        raise ValueError('Posizioni non in forma di lista: non creare un totale fittizio.')
    # Duplicate identities cannot safely be counted as distinct holdings.
    symbols = [wallet_symbol(h.get('token')) if isinstance(h, dict)
               else ('identificativo assente', False) for h in positions]
    # Duplicate alias identities invalidate BOTH row valuations and decisions.
    # Never merge wallet quantities or change their recorded representation.
    identities = [canonical(sym) if valid else None for sym, valid in symbols]
    duplicates = {key for key in identities if key is not None
                  and identities.count(key) > 1}
    for h, (symbol, identity_ok) in zip(positions, symbols):
        if not isinstance(h, dict):
            holdings.append({'token': symbol, 'quantita': None,
                             'identita_valida': False, 'quantita_stato': 'NON_NOTO',
                             'identificativo_duplicato': False,
                             'errore': 'Posizione non strutturata: verifica manuale.',
                             'decisione': 'DECISIONE NON ASSOCIABILE: identità non valida.'})
            continue
        raw_quantity = h.get('quantita')
        quantity, qty_state = wallet_number(raw_quantity)
        visible_quantity = wallet_quantity_display(raw_quantity)
        decision = (decision_state(symbol, decisions, now)
                    if identity_ok and canonical(symbol) not in duplicates else
                    'DECISIONE NON ASSOCIABILE: identificativo invalido o duplicato.')
        base = {'token': symbol, 'quantita': visible_quantity, 'decisione': decision,
                'identita_valida': bool(identity_ok), 'quantita_stato': qty_state,
                'identificativo_duplicato': canonical(symbol) in duplicates}
        if not identity_ok:
            base['errore'] = 'Identificativo token assente o malformato: verificare la posizione.'
        elif canonical(symbol) in duplicates:
            base['errore'] = 'Token duplicato: verificare le registrazioni prima del totale.'
        elif qty_state == 'NON_NOTO':
            base['errore'] = 'Quantità non nota: nessun saldo o valore stimato.'
        elif qty_state != 'VALIDO':
            base['errore'] = ('Quantità non valida (' + qty_state +
                              '): verificare; nessun zero o valore stimato.')
        else:
            row = pairs.get(symbol)
            if not isinstance(row, dict):
                base['errore'] = 'Nessuna quotazione spot EUR disponibile: nessuna stima inventata.'
            else:
                price, price_state = wallet_number(row.get('prezzo_eur'))
                if price_state != 'VALIDO' or price <= 0:
                    base['errore'] = 'Prezzo EUR non valido: nessuna stima patrimoniale.'
                else:
                    value = quantity * price
                    if not math.isfinite(value) or (quantity > 0 and value == 0):
                        base['errore'] = 'Controvalore non rappresentabile: nessuno zero inventato.'
                    else:
                        basis = h.get('costo_medio_eur')
                        pl = None
                        if basis is not None:
                            basis_value, cost_state = wallet_number(basis)
                            if cost_state == 'VALIDO':
                                pl_candidate = (price - basis_value) * quantity
                                if math.isfinite(pl_candidate):
                                    pl = pl_candidate
                                else:
                                    base['avviso_costo_medio'] = 'P/L non rappresentabile: verificare.'
                            else:
                                base['avviso_costo_medio'] = ('Costo medio non valido (' +
                                                             cost_state + '): verificare il P/L.')
                        base.update({'valore_eur': value, 'prezzo_eur': price,
                                     'pl_non_realizzato_eur': pl,
                                     'tendenza': trends.get(symbol),
                                     'note': signals(row, trends.get(symbol))})
        holdings.append(base)
    lo = num(conf.get('scanner',{}).get('min_var_oggi_utc_pct',8))
    hi = num(conf.get('scanner',{}).get('max_var_oggi_utc_pct',20))
    min_vol = num(conf.get('scanner',{}).get('volume_24h_min_eur', 500000))
    max_spread = num(conf.get('scanner',{}).get('spread_massimo_pct',0.8))
    gainers = []
    for r in pairs.values():
        change = r['var_oggi_utc_pct']
        if change is None or not (lo <= change <= hi): continue
        rr = dict(r)
        flags = []
        if r['volume_24h_eur_stimato'] < min_vol: flags.append('Liquidità ridotta')
        if r['spread_pct'] > max_spread: flags.append('Spread elevato')
        rr['criticita'] = flags
        gainers.append(rr)
    gainers.sort(key=lambda x: (len(x['criticita']), -x['volume_24h_eur_stimato']))
    schede = data.get('schede_v02', [])
    btc = trends.get('BTC')
    market = 'REGIME NON DETERMINATO — verifica BTC e contesto'
    if btc and 'errore' not in btc:
        if btc['sopra_media20'] and btc['var_30g_pct'] > 0: market = 'BTC: struttura tecnica favorevole (non previsione)'
        elif not btc['sopra_media20'] and btc['var_30g_pct'] < 0: market = 'BTC: struttura tecnica debole (non previsione)'
        else: market = 'BTC: quadro tecnico misto'
    age_minutes = max(0, (now - rilevazione).total_seconds()/60)
    freshness = 'Freschezza da ricalcolare alla consultazione; timestamp originale sempre disponibile.'
    saldo = stato_saldo(portfolio, data.get('saldo_refresh'), now=now)
    posizioni_non_aggiornate = sum(1 for h in positions
                                  if isinstance(h, dict) and h.get('quantita') is None)
    valued = [h['valore_eur'] for h in holdings if 'valore_eur' in h]
    n_valued = len(valued)
    n_incomplete = len(holdings) - n_valued
    total_error = None
    if not holdings:
        state, total = 'NESSUNA_POSIZIONE_REGISTRATA', None
    elif not valued:
        state, total = 'NON_DISPONIBILE', None
    else:
        # Finite individual values can still overflow their floating sum.
        try:
            total = math.fsum(valued)
        except OverflowError:
            total = math.inf
        if not math.isfinite(total):
            state, total = 'NON_RAPPRESENTABILE', None
            total_error = 'Somma dei controvalori fuori scala; non usare un totale.'
        else:
            state = 'PARZIALE' if n_incomplete else 'COMPLETO'
    return {'rilevazione_utc': data['rilevazione_utc'], 'mercato': market,
            'freschezza': freshness, 'saldo_stato': saldo,
            'orari_fonti': data.get('orari_fonti', {}),
            'revisione_portafoglio': decision_state('PORTAFOGLIO', decisions, now),
            'contesto': context_status(ctx, now), 'posizioni': holdings, 'candidati': gainers[:18], 'schede_v02': schede,
            # D1 contract: null means no reliable numeric total; never a fake 0.
            'totale_stimato_eur': total, 'stato_totale': state,
            'posizioni_registrate': len(holdings), 'posizioni_valorizzate': n_valued,
            'posizioni_incomplete': n_incomplete, 'zero_reale': state == 'COMPLETO' and total == 0,
            'errore_totale': total_error,
            'totale_parziale': state in ('PARZIALE','NON_DISPONIBILE','NON_RAPPRESENTABILE'),
            'posizioni_non_aggiornate': posizioni_non_aggiornate,
            'n_mercati_eur': len(pairs), 'n_coppie_multi':data.get('n_coppie_multi'),
            'n_token_multi':data.get('n_token_multi'), 'fx_rilevati':data.get('fx_rilevati',{}),
            'feed': data.get('feed',[]),
            'problemi_feed': data.get('problemi_feed', []),
            'avvertenze': [
               'Prezzi indicativi, non eseguibili; lo spread è indicativo e il costo effettivo dipende dal book e dalle commissioni.',
               'Variazione giornaliera: da mezzanotte UTC (Kraken), NON rendimento rolling 24h.',
               'Il volume 24h in EUR è stimato: volume token * ultimo prezzo.',
               'Radar gainer = selezione da approfondire, mai segnale automatico di acquisto.',
               'Fonti macro sono titoli ufficiali; il software NON deduce automaticamente implicazioni geopolitiche o monetarie.',
               ('Saldo spot: fonte '+saldo['origine']+', acquisizione '+str(saldo['acquisizione_saldo_utc'])+
                ', eta minuti '+str(saldo['eta_saldo_minuti'])+', freschezza '+saldo['freschezza_saldo']+
                ', ultimo tentativo '+saldo['ultimo_tentativo']+'. Dato precedente non equivale a saldo attuale.'),
               'Kraken BalanceEx solo lettura se configurato; nessun ordine, nessuna tassazione calcolata.'
            ]}


def fotografia_portafoglio_sha256(portfolio):
    """Digest of parsed local JSON content, NOT proof of authentic Kraken balance.

    Stable across key order, but deliberately absent for unrepresentable JSON.
    Raw wallet bytes, credentials and T0 never enter reports or GitHub.
    """
    try:
        canonical_json = json.dumps(portfolio, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, OverflowError):
        return None
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()


def qualita_portafoglio(data, portfolio):
    """One valuation engine for dashboard and GPT dossier: build_report D1/D2.

    Quantities and EUR valuation are distinct. Even a complete quoted wallet
    is not evidence of a current private balance unless stato_saldo says so.
    """
    read_at = NOW().isoformat(timespec='seconds')
    digest = fotografia_portafoglio_sha256(portfolio)
    saldo = stato_saldo(portfolio, data.get('saldo_refresh'), now=NOW())
    recent = (saldo['origine'] == 'KRAKEN_BALANCEEX'
              and saldo['freschezza_saldo'] == 'RECENTE'
              and saldo['portafoglio_aggiornato_da_api_private'])
    fields = {'stato_quantita': 'SCHEMA_NON_VALIDO', 'posizioni_registrate': None,
              'posizioni_quantita_valide': 0, 'posizioni_valorizzate': 0,
              'posizioni_incomplete': None, 'stato_totale': 'NON_DISPONIBILE',
              'totale_stimato_eur': None, 'zero_reale': False,
              'portafoglio_noto': False, 'saldo_recente_verificato': recent,
              'stato_saldo': saldo, 'anomalie_posizioni': [],
              'portafoglio_letto_utc': read_at,
              'fotografia_portafoglio_sha256': digest,
              'significato_fotografia': 'Hash del contenuto JSON locale, non autenticazione o prova di freschezza.'}
    if not isinstance(portfolio, dict):
        fields['anomalie_posizioni'] = [{'motivo': 'Portafoglio non strutturato'}]
        return fields
    positions = portfolio.get('posizioni')
    if not isinstance(positions, list):
        fields['anomalie_posizioni'] = [{'motivo': 'posizioni non in forma di lista'}]
        return fields
    # A dossier can be built from a source that contains no EUR market
    # rows. That means valuation unavailable, never zero or invented prices.
    valuation_source = dict(data)
    valuation_source.setdefault('rilevazione_utc', read_at)
    valuation_source.setdefault('markets', {})
    valuation_source.setdefault('trends', {})
    valuation_source.setdefault('feed', [])
    valuation_source.setdefault('problemi_feed', [])
    report = build_report(valuation_source, portfolio, {}, {}, [])
    holdings = report['posizioni']
    valid = sum(1 for h in holdings
                if h.get('identita_valida')
                and h.get('quantita_stato') == 'VALIDO'
                and not h.get('identificativo_duplicato'))
    complete = bool(holdings) and valid == len(holdings)
    fields.update({
        'stato_quantita': ('ASSENTI' if not holdings else
                           'COMPLETE' if complete else 'INCOMPLETE'),
        'posizioni_registrate': report['posizioni_registrate'],
        'posizioni_quantita_valide': valid,
        'posizioni_valorizzate': report['posizioni_valorizzate'],
        'posizioni_incomplete': report['posizioni_incomplete'],
        'stato_totale': report['stato_totale'],
        'totale_stimato_eur': report['totale_stimato_eur'],
        'zero_reale': report['zero_reale'],
        'portafoglio_noto': complete,
        'anomalie_posizioni': [
            {'indice': index, 'token': h['token'], 'motivo': h['errore']}
            for index, h in enumerate(holdings) if 'errore' in h]})
    return fields


def fmt(x, places=2):
    if x is None: return 'n.d.'
    return f'{x:,.{places}f}'.replace(',', ' ').replace('.', ',')

def badge(s):
    if 'SCADUTA' in s or 'NESSUNA' in s: return 'urgente'
    return 'neutro'

def render(report):
    esc = lambda s: html.escape(str(s), quote=True)
    holdings = ''
    for h in report['posizioni']:
        if 'errore' in h:
            quantity_info = 'non nota' if h.get('quantita') is None else esc(h['quantita'])
            holdings += (f"<article><h3>{esc(h['token'])}</h3><p>Quantità: {quantity_info}</p>"
                         f"<p>{esc(h['errore'])}</p><p>{esc(h['decisione'])}</p></article>")
        else:
            trend = h.get('tendenza') or {}
            delta7 = fmt(trend.get('var_7g_pct')) + '%' if 'errore' not in trend else 'n.d.'
            unrealized = 'senza costo fiscale' if h['pl_non_realizzato_eur'] is None else f"P/L indicativo: {fmt(h['pl_non_realizzato_eur'])} €"
            notes = ''.join(f'<li>{esc(note)}</li>' for note in h['note'])
            warning = (f"<p class='urgente'>{esc(h['avviso_costo_medio'])}</p>"
                       if h.get('avviso_costo_medio') else '')
            holdings += (f"<article><h3>{esc(h['token'])} <span>{fmt(h['valore_eur'])} €</span></h3>"
                         f"<p>Quantità {esc(h['quantita'])} · Prezzo {fmt(h['prezzo_eur'], 5)} € · 7g {delta7} · {unrealized}</p>"
                         f"{warning}<ul>{notes}</ul><p class='{badge(h['decisione'])}'>{esc(h['decisione'])}</p></article>")
    if not holdings:
        if report.get('stato_totale') == 'SCHEMA_NON_VALIDO':
            holdings = ("<article class='urgente'>Formato posizioni non valido: "
                        "impossibile ricostruire le righe patrimoniali. "
                        "Verificare il file originale; nessuna posizione o valore inventato.</article>")
        else:
            holdings = "<article>Nessuna quantità inserita. Compila <code>portafoglio.json</code>; finché i trasferimenti sono in corso non stimiamo il saldo.</article>"
    funds=report.get('liquidita_spot_api',{})
    available_html=''
    if funds:
        u=esc(funds.get('USDC',{}).get('disponibile','non noto'))
        e=esc(funds.get('EUR',{}).get('disponibile','non noto'))
        available_html=f"<p class='muted'>Disponibile spot da API privata: USDC {u} · EUR {e}. Fonte e ora nei saldi; non indica margine futures.</p>"
    pending=report.get('migrazione_attesa',{})
    transfer_html=''
    if pending.get('stato')=='DA_RICONCILIARE':
        items=pending.get('asset_visibili',[])
        riscontro=pending.get('riscontro_portafoglio_kraken_2026_10_19',{})
        confermati=riscontro.get('visibili_anche_su_kraken',{})
        # Non ripetere nella diagnostica gli asset gia presenti nel portafoglio.
        irrisolti=[item for item in items if item.get('token') not in confermati]
        lines=''.join(
            f"<li><b>{esc(item.get('token','?'))}</b>: saldo precedente Binance "
            f"{esc(item.get('quantita_binance_visualizzata','?'))}; "
            "non visibile nella fotografia Kraken, NON significa zero.</li>"
            for item in irrisolti)
        transfer_html=(
            "<details><summary>Migrazione storica: "
            +str(len(confermati))+" asset ora visibili su Kraken, "
            +str(len(irrisolti))+" da verificare</summary>"
            "<p>Le vecchie quantità Binance sono archiviate separatamente dal "
            "portafoglio Kraken. Essere visibili su Kraken non documenta da solo "
            "il singolo accredito o le commissioni di trasferimento.</p>"
            "<ul>"+lines+"</ul></details>")

    bn=report.get('binance_reference',{}) or {}
    bn_rows=''
    if bn.get('status') == 'OK':
        for item in bn.get('tokens',[]):
            tok=esc(item.get('token','?'))
            if item.get('status') != 'OK':
                bn_rows += f"<tr><td>{tok}</td><td colspan='5'>Non quotato nelle coppie Binance USDC/USDT controllate</td></tr>"
                continue
            pairs_bn=item.get('binance_pairs') or []
            main=max(pairs_bn,key=lambda z:z['base_qty_24h'])
            ratio=item.get('volume_ratio_subsets')
            ratio_s='n.d.' if ratio is None else f"{ratio:.1f}×"
            book=item.get('binance_top10_book') or {}
            bsign=book.get('imbalance_10levels')
            btxt='n.d.' if bsign is None else f"{bsign:+.2f}"
            bn_rows += (f"<tr><td>{tok}</td><td>{fmt(item['binance_base_volume_24h_subset'],1)}</td>"
                        f"<td>{fmt(item['kraken_base_volume_24h_subset'],1)}</td>"
                        f"<td>{ratio_s}</td><td>{esc(main['pair'])}: {fmt(main['change_24h_pct'])}%</td>"
                        f"<td>{btxt}</td></tr>")
    bn_html=(f"<details open><summary>Confronto Binance / Kraken SPOT — "
             f"{esc(bn.get('status','NON DISPONIBILE'))} · "
             f"{esc(bn.get('observed_utc','senza orario'))}</summary>"
             "<p class='muted'>Volume rolling 24h IN UNITÀ DEL TOKEN, Binance solo USDT+USDC"
             " contro Kraken solo EUR+USD+USDC: rapporto delle coppie esaminate,"
             " NON quota di mercato delle piattaforme. Ogni token mantiene il proprio"
             " mercato. Le variazioni 24h sono della coppia Binance più trattata."
             " Bilancio book sui primi 10 livelli, indicativo e manipolabile:"
             " non è un segnale di acquisto né ordine eseguito. "
             "Operazioni e prezzi realizzabili: SOLTANTO Kraken.</p>"
             "<div class='scroll'><table><thead><tr><th>Token</th><th>Volume Binance (token)</th>"
             "<th>Volume Kraken (token)</th><th>Rapporto</th><th>Trend Binance 24h</th>"
             "<th>Book ±</th></tr></thead><tbody>"
             + (bn_rows or "<tr><td colspan='6'>Dati Binance non disponibili</td></tr>")
             + "</tbody></table></div></details>")

    gainers = ''
    for x in report['candidati']:
        flags = ', '.join(x['criticita']) if x['criticita'] else 'Filtro liquidità/spread superato — NON è un segnale d’acquisto'
        gainers += (f"<tr><td>{esc(x['token'])}</td><td>{fmt(x['var_oggi_utc_pct'])}%</td>"
                    f"<td>{fmt(x['volume_24h_eur_stimato'], 0)} €</td><td>{fmt(x['spread_pct'])}%</td><td>{esc(flags)}</td></tr>")
    if not gainers: gainers = '<tr><td colspan="5">Nessun candidato nel filtro attuale. Non equivale a divieto di operare.</td></tr>'
    # Pochi candidati approfonditi. Il flusso esecutivo, quando presente,
    # resta nascosto sotto dettagli: non sostituisce decisione GPT o setup.
    schede_html = ''
    flows=report.get('flussi_spot',{})
    for c in report.get('schede_v02', []):
        tech = c.get('indicatori') or {}
        book = c.get('book') or {}
        metrics = []
        for label, key, unit in (
            ('1h (chiuse)', 'var_1h_pct', '%'), ('4h (chiuse)', 'var_4h_pct', '%'),
            ('Forza su BTC 4h', 'forza_relativa_4h_punti', ' p.p.'),
            ('Volume 4h / 4h precedenti', 'rapporto_volumi_4h', '×')):
            value=tech.get(key)
            if value is not None: metrics.append(f'<span class="tag">{esc(label)}: {fmt(value)}{esc(unit)}</span>')
        if book:
            metrics.append(f'<span class="tag">Spread book: {fmt(book.get("spread_book_pct"))}%</span>')
        observations=' '.join(metrics)
        yes=''.join(f'<li>{esc(t)}</li>' for t in c.get('evidenze',[]))
        no=''.join(f'<li>{esc(t)}</li>' for t in c.get('criticita',[]))
        why=f'<p><strong>{esc(c["esito"])}</strong> · {esc(c["sintesi"])}</p>'
        why+=f'<p><b>Perché è stato esaminato:</b> {esc(c.get("perche_selezionato") or "Campione di confronto")}</p>'
        choice = esc(c.get('coppia_analisi') or 'n.d.')
        vpair=c.get('volume_coppia_eur_stimato')
        vall=c.get('volume_token_kraken_eur_stimato')
        quote_info=f'<p><b>Coppia analizzata: {choice}</b>'
        if vpair is not None:
            quote_info+=f' · Vol. coppia stimato: {fmt(vpair,0)} €'
        if vall is not None:
            quote_info+=f' · Somma EUR/USD/USDC su Kraken: {fmt(vall,0)} €'
        quote_info+='</p>'
        alternatives = ''.join(
            f'<li>{esc(p["pair"])} · Vol. {fmt(p["volume_eur_stimato"],0)} € · Spread {fmt(p["spread_pct"])}%</li>'
            for p in c.get("alternative", []))
        alternatives_html=(
            f'<details><summary>Confronta coppie spot Kraken</summary><ul>{alternatives}</ul>'
            '<p>Volumi convertiti indicativamente in EUR al mid di Kraken. '
            'Nessuna verifica della negoziabilità sul conto o dei costi di conversione.</p></details>'
            if alternatives else '')

        # CVD su singola finestra Kraken Spot, *NON* futuro né 4h completo
        # quando 1000 trade coprono soltanto la coda recente del flusso.
        flow=flows.get(c['token'],{})
        flow_html=''
        if flow:
            status=flow.get('stato','NON_DISPONIBILE')
            def delta_text(key,complete):
                dlt=flow.get(key) if complete else None
                if not dlt:return 'Dati insufficienti per coprire tutta la finestra'
                return ('Netto buy−sell: '+fmt(dlt.get('delta_quote'))+' '
                        +esc(c.get('valuta_quotazione') or 'quote')
                        +' ('+fmt(dlt.get('percentuale_netto_su_volume'))+
                        '% sul volume della finestra)')
            closed=flow.get('candela_15m_chiusa') or {}
            measures=closed.get('misure') or {}
            if closed.get('stato')=='COMPLETA' and measures:
                closed_line=(
                    esc(closed.get('inizio_utc','?'))+' → '+esc(closed.get('fine_utc','?'))+
                    ' · netto buy−sell: '+fmt(measures.get('delta_quote'))+' '+
                    esc(c.get('valuta_quotazione') or 'quote')+
                    ' ('+fmt(measures.get('percentuale_netto_su_volume'))+
                    '% del volume della candela)')
            else:
                closed_line='Confronto non valido: '+esc(closed.get('stato','NON_DISPONIBILE'))
            flow_html=(
                '<details><summary>Flusso spot recente Kraken · '+esc(status)+'</summary>'
                '<p>Solo questa coppia Kraken spot, fino a 1000 trade;'
                ' NON derivati e NON CVD storico continuo. '
                'Il book è una fotografia presa a un altro momento; '
                'questo indicatore non conferma da solo alcun ingresso.</p>'
                '<p><b>Candela 15m chiusa, stessa finestra del prezzo:</b> '+
                closed_line+'</p>'
                '<p><b>Ultimi 15 minuti mobili (finestra differente):</b> '+
                delta_text('delta_15m',flow.get('finestra_15m_completa'))+'</p>'
                '<p><b>Ultime quattro ore:</b> '+
                delta_text('delta_4h',flow.get('finestra_4h_completa'))+'</p>'
                '<p>Ultima esecuzione: '+esc(flow.get('ultimo_trade_utc','non disponibile'))+
                ' · dati osservati: '+esc(flow.get('osservato_utc','non disponibile'))+'</p>'
                '</details>')
        # La candela 15m CHIUSA termina generalmente prima del fetch Trades.
        # Il rolling 15m e' una finestra diversa: non usarlo per spiegare
        # retroattivamente l'ultima candela chiusa.
        # Confronto costo ipotetico senza variazioni prezzo, separato dai segnali.
        roundtrips = c.get('costi_roundtrip', [])
        costs_html = ''
        if roundtrips:
            example_eur = next((x['importo_eur'] for x in roundtrips if 'importo_eur' in x), 100)
            by_wallet = []
            table_rows = []
            for wallet in ('EUR','USDC'):
                feasible = [x for x in roundtrips if x.get('valuta_partenza') == wallet
                            and 'costo_roundtrip_eur' in x]
                if feasible:
                    best = min(feasible, key=lambda x: x['costo_roundtrip_eur'])
                    by_wallet.append(f'<p><b>Partendo da {wallet}:</b> minore costo simulato su '
                                     f'{esc(best["coppia"])} · {fmt(best["costo_roundtrip_eur"])} € '
                                     f'({fmt(best["costo_roundtrip_pct"])}%). '
                                     f'{best["n_conversioni"]} conversioni.</p>')
                else:
                    by_wallet.append(f'<p>Da {wallet}: simulazione incompleta, mancano book sufficienti.</p>')
                for x in roundtrips:
                    if x.get('valuta_partenza') != wallet: continue
                    status = (f'{fmt(x["costo_roundtrip_eur"])} € · {fmt(x["costo_roundtrip_pct"])}%'
                              if 'costo_roundtrip_eur' in x else esc(x.get('errore','n.d.')))
                    path = ' → '.join(x.get('percorso', []))
                    table_rows.append(f'<tr><td>{esc(wallet)}</td><td>{esc(x["coppia"])}</td>'
                                      f'<td>{status}</td><td>{esc(path)}</td></tr>')
            # Esiti maker visibili ma mai usati per classificare il 'miglior'
            # percorso: al bid/ask passivo il fill è sconosciuto.
            conditional = []
            for x in c.get('costi_modalita', []):
                value = (f'{fmt(x["costo_roundtrip_eur"])} € '
                         f'({fmt(x["costo_roundtrip_pct"])}%)'
                         if 'costo_roundtrip_eur' in x else
                         esc(x.get('errore', 'n.d.')))
                conditional.append(
                    f'<tr><td>{esc(x["valuta_partenza"])}</td>'
                    f'<td>{esc(x["coppia"])}</td>'
                    f'<td>{esc(x["scenario"])}</td><td>{value}</td></tr>')
            scenarios_html = (
                '<details><summary>Maker, taker e misto: prezzi condizionali</summary>'
                '<p><b>Il maker NON è un risparmio garantito.</b> Prezzi teorici: '
                'acquisto maker al miglior bid, vendita maker al miglior ask osservati. '
                'L’ordine post-only potrebbe non essere eseguito, riempirsi solo '
                'parzialmente o incontrare prezzi cambiati. '
                'Le conversioni valutarie sono sempre simulate taker.</p>'
                '<div class="scroll"><table><thead><tr><th>Saldo</th>'
                '<th>Coppia</th><th>Entrata/uscita</th><th>Costo teorico</th>'
                '</tr></thead><tbody>' + ''.join(conditional) +
                '</tbody></table></div></details>'
                if conditional else '')
            costs_html = (
                f'<details><summary>Confronto costi spot: simulazione da {fmt(example_eur,0)} € '
                '(EUR o USDC)</summary>'
                + ''.join(by_wallet)
                + '<div class="scroll"><table><thead><tr><th>Saldo</th><th>Coppia</th>'
                '<th>Costo round-trip</th><th>Percorso</th></tr></thead><tbody>'
                + ''.join(table_rows) + '</tbody></table></div>' + scenarios_html +
                '<small>Scenario orientativo: acquisto e vendita taker allo stesso prezzo '
                'di mercato, 0,80% per lato crypto e 0,20% per conversione FX/stablecoin '
                '(livello 1 Kraken Pro: taker crypto verificato nel conto; '
                'FX/stablecoin al livello iniziale del tariffario pubblico). '
                'Maker spot verificato 0,40%, ma con esecuzione incerta. '
                'Include book/spread/slippage '
                'del momento, non il movimento futuro, tassazione, disponibilità conto o '
                'commissioni personali. Nessuna conversione imposta e nessun ordine.</small>'
                '</details>')
        schede_html+=f'<article><h3>{esc(c["token"])} <small>{esc(c["categoria"])}</small></h3>' + why + quote_info + alternatives_html + f'<p>{observations}</p>'
        schede_html += flow_html + costs_html
        if yes: schede_html += f'<p>Elementi favorevoli:</p><ul>{yes}</ul>'
        if no: schede_html += f'<p>Questioni da verificare:</p><ul>{no}</ul>'
        schede_html += '<small>Foto di mercato: servono verifica notizie, costi e disponibilità della coppia sul conto. Nessuna indicazione di acquisto.</small></article>'
    if not schede_html:
        schede_html = '<article>Nessuna scheda acquisita: premi Aggiorna dati ora per una nuova valutazione.</article>'
    exp = report.get('esperimento_delta') or {}
    studio_html = ''
    if exp.get('esperimenti'):
        studio_html = (
            "<p><small>Confronto sperimentale GPT senza/con flusso spot: "
            +str(exp.get('casi',0))+" candidati, "
            +str(exp.get('orizzonti_maturi_con_esito',0))+"/"
            +str(exp.get('orizzonti_totali',0))+
            " chiusure future osservate (+1h, +4h, +24h). "
            "Non sono operazioni né rendimenti. "
            "Stato: "+esc(exp.get('stato','?'))+".</small></p>")
    context = ''.join(f"<article><h3>{esc(k.capitalize())}: {esc(v['stato'])}</h3><p>{esc(v['testo'])}</p><small>{esc(v['fonte'])}</small></article>" for k,v in report['contesto'].items())
    feed = ''.join(f"<li><strong>{esc(x['fonte'])}:</strong> <a href='{esc(x['link'])}' target='_blank' rel='noopener'>{esc(x['titolo'])}</a> <small>{esc(x['data'])}</small></li>" for x in report['feed'])
    feed += ''.join(f'<li class="urgente">Fonte non disponibile: {esc(x)}</li>' for x in report['problemi_feed'])
    warnings = ''.join(f'<li>{esc(x)}</li>' for x in report['avvertenze'])
    dossier_status = report.get('dossier_stato') or {}
    dossier_notice = ''
    if dossier_status:
        message = ('Dossier GPT: mercato ' +
                   str(dossier_status.get('stato_fonti_mercato', 'NON_VERIFICATO')) +
                   '; patrimonio ' +
                   str(dossier_status.get('idoneita_analisi_patrimoniale', 'NON_IDONEA')) +
                   '; stato ' + str(dossier_status.get('stato', 'NON_VERIFICATO')))
        if dossier_status.get('stato') == 'NON_ALLINEATO_PATRIMONIO':
            message += ' — fotografia del patrimonio diversa da quella del dossier.'
        dossier_notice = "<p class='urgente' role='status'>" + esc(message) + "</p>"
    # Legacy JSON reports have no stato_totale: derive availability from
    # actual finite valued rows, never trust an unqualified legacy numeric 0.
    actual_values = [h['valore_eur'] for h in report['posizioni']
                     if isinstance(h.get('valore_eur'), (int, float))
                     and not isinstance(h['valore_eur'], bool)
                     and math.isfinite(h['valore_eur'])]
    state = report.get('stato_totale')
    if state is None:
        state = ('NESSUNA_POSIZIONE_REGISTRATA' if not report['posizioni']
                 else 'NON_DISPONIBILE' if not actual_values
                 else 'PARZIALE' if report.get('totale_parziale') else 'COMPLETO')
    numeric_total = report.get('totale_stimato_eur')
    can_show = (state in ('COMPLETO', 'PARZIALE')
                and isinstance(numeric_total, (int, float))
                and not isinstance(numeric_total, bool)
                and math.isfinite(numeric_total) and bool(actual_values))
    total = f"{fmt(numeric_total)} €" if can_show else 'non disponibile'
    if state in ('PARZIALE', 'NON_DISPONIBILE', 'NON_RAPPRESENTABILE'):
        total += ' (incompleto)' if state != 'NON_RAPPRESENTABILE' else ' (somma fuori scala)'
    elif state == 'NESSUNA_POSIZIONE_REGISTRATA':
        total += ' (nessuna posizione registrata; conto non verificato)'
    elif state == 'SCHEMA_NON_VALIDO':
        total += ' (formato del portafoglio non valido)'
    # La data in un file statico resta identica; l'età deve essere calcolata
    # dal browser a ogni apertura, ritorno in primo piano e durante la lettura.
    freschezza_live = '''<p id="data-freschezza" data-rilevazione="__RILEVAZIONE__" role="status">Verifica dell'età dei dati in corso; in assenza di JavaScript considerali da aggiornare.</p>
<script>
(function () {
  const target = document.getElementById('data-freschezza');
  const raw = target.getAttribute('data-rilevazione');
  const rilevazione = new Date(raw);
  function mostraEta() {
    const min = Math.floor((Date.now() - rilevazione.getTime()) / 60000);
    if (!Number.isFinite(min) || min < -2) {
      target.textContent = 'Ora della rilevazione non verificabile: controllare orologio e connessione.';
      target.className = 'urgente';
      return;
    }
    const locale = rilevazione.toLocaleString('it-IT', {dateStyle:'short',timeStyle:'short'});
    if (min > 30) {
      target.textContent = 'DATI DA AGGIORNARE: rilevazione ' + locale + ' (' + min + ' minuti fa).';
      target.className = 'urgente';
    } else {
      target.textContent = 'Rilevazione ' + locale + ' (' + Math.max(0,min) + ' minuti fa).';
      target.className = 'neutro';
    }
  }
  mostraEta();
  window.addEventListener('pageshow', mostraEta);
  document.addEventListener('visibilitychange', mostraEta);
  setInterval(mostraEta, 15000);
})();
</script>'''.replace('__RILEVAZIONE__', esc(report['rilevazione_utc']))
    return f'''<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Kraken Decision Desk — v0.2</title>
<style>:root{{color-scheme:dark}}body{{background:#0b1120;color:#e5edf9;font:16px/1.5 system-ui,Arial;margin:0;padding:16px;max-width:930px;margin:auto}}header{{padding:13px 0 20px;border-bottom:1px solid #334155}}h1{{font-size:1.7rem;margin:0}}h2{{margin-top:34px;color:#93c5fd}}.lead{{font-size:1.15rem;color:#fcd34d}}small,.muted{{color:#9ca3af}}article{{background:#15223a;border:1px solid #334155;border-radius:12px;padding:14px;margin:12px 0}}article h3{{margin:0 0 6px}}article h3 span{{float:right;color:#86efac}}table{{border-collapse:collapse;width:100%;font-size:.83rem}}th,td{{border-bottom:1px solid #334155;padding:9px 6px;text-align:left}}.scroll{{overflow-x:auto}}.urgente{{color:#fbbf24;font-weight:700}}.neutro{{color:#93c5fd}}a{{color:#7dd3fc}}code{{color:#eab308}}.tag{{border:1px solid #315389;border-radius:8px;padding:5px 9px;display:inline-block}}</style></head><body>
<header><h1>Kraken Decision Desk <small>v0.2</small></h1><p class="muted">Rilevazione UTC: {esc(report['rilevazione_utc'])}. Dati pubblici, nessuna operazione automatica.</p><p class="lead">{esc(report['mercato'])}</p><span class="tag">Valore posizioni inserite: {esc(total)}</span> <span class="tag">Token con coppia EUR: {report['n_mercati_eur']}</span></header>
{piano_gpt.render_box(report.get('piano_gpt'),report['rilevazione_utc'])}
{__import__('verifica_piani').render_summary(report.get('verifica_piano'),report.get('piano_gpt'))}
{__import__('verifica_piani').render_archivio(report.get('verifica_storico'), __import__('verifica_piani').plan_hash(report['piano_gpt']) if report.get('piano_gpt') and 'errore' not in report['piano_gpt'] else None)}
<h2>1 · Decisioni e posizioni</h2>{dossier_notice}{freschezza_live}<p class='muted'>Questa copia HTML è una fotografia: per ricevere nuovi prezzi apri il <a href='http://127.0.0.1:8765/'>cruscotto locale aggiornabile</a> (richiede Termux attivo).</p><article><h3>Decisione di portafoglio</h3><p class='{badge(report['revisione_portafoglio'])}'>{esc(report['revisione_portafoglio'])}</p></article><p>Ogni attesa richiede un motivo e una scadenza. Se scade, la revisione è dovuta; il sistema non decide di vendere.</p><p class='muted'>Quantità: {esc(report.get('portafoglio_fonte') or 'non documentate')} · non si aggiornano con i prezzi.</p>{available_html}{holdings}{transfer_html}
<h2>2 · Candidati da valutare</h2><p>Ricerca spot multi-coppia EUR/USD/USDC su Kraken: {report.get('n_token_multi') or 'n.d.'} token in {report.get('n_coppie_multi') or 'n.d.'} coppie. La somma dei volumi serve a scoprire token; per operare conta invece il book della singola coppia. Non sono ordini né stime di profitto.</p>{bn_html}{schede_html}{studio_html}<details><summary>Apri radar precedente solo EUR (dati grezzi)</summary><div class="scroll"><table><thead><tr><th>Token</th><th>Oggi</th><th>Vol. 24h stim.</th><th>Spread</th><th>Nota</th></tr></thead><tbody>{gainers}</tbody></table></div></details>
<h2>3 · Macroeconomia e geopolitica</h2><p>Un contesto non verificato è un'informazione mancante, non equivale a uno scenario neutrale o ribassista.</p>{context}
<h2>4 · Fonti e limiti</h2><details><summary>Apri titoli di Fed, BCE e Consiglio UE</summary><p>Raccolta automatica di titoli, nessuna interpretazione causale.</p><ul>{feed or '<li>Nessun feed acquisito.</li>'}</ul></details><details><summary>Apri limiti tecnici e avvertenze</summary><ul>{warnings}</ul></details><p class="muted">Strumento sperimentale per supporto alle decisioni. Nessuna previsione o consulenza personalizzata automatica.</p></body></html>'''

def prepara_dossier_aggiornamento(data, *, asset_pairs=None, wallet_override=None):
    """Produce un dossier sullo stesso snapshot Kraken. API pubbliche soltanto.

    Se una fonte secondaria fallisce non scambia dati vecchi per aggiornati:
    salva esplicitamente la mancanza. Non chiama GPT e non tocca i piani.
    """
    status={'rilevazione_kraken_utc':data['rilevazione_utc'],
            'preparato_utc':NOW().isoformat(timespec='seconds'),
            'stato':'NON_DISPONIBILE',
            'motivi_incompletezza':[]}
    try:
        import dossier_trade
        with dossier_trade.primary_refresh_context():
            dossier=dossier_trade.collect(
                source=data, portfolio_override=wallet_override,
                **({'asset_pairs': asset_pairs} if asset_pairs is not None else {}))
        if dossier['kraken_istantanea_utc']!=data['rilevazione_utc']:
            raise ValueError("Dossier riferito ad altro snapshot")
        rows=dossier.get('candidati',[])
        status['token_analizzati']=[x['token'] for x in rows]
        # Economic coverage and the external shortlist are different questions.
        # This is descriptive evidence at dossier time, not a GPT decision.
        economic = dossier.get('evidenze_economiche')
        economic = economic if isinstance(economic, dict) else {}
        econ_positions = economic.get('posizioni')
        econ_candidates = economic.get('candidati')
        econ_positions = econ_positions if isinstance(econ_positions, list) else None
        econ_candidates = econ_candidates if isinstance(econ_candidates, list) else None
        four_positions = (dossier.get('patrimonio_4tf') or {}).get('posizioni') or []
        aligned = bool(isinstance(four_positions, list) and four_positions
                       and isinstance(econ_positions, list)
                       and len(econ_positions) == len(four_positions)
                       and all(isinstance(row, dict)
                               and row.get('indice') == i
                               and row.get('token') == four_positions[i].get('token')
                               for i, row in enumerate(econ_positions)))
        verified_positions = sum(
            isinstance(row.get('identita'), dict)
            and row['identita'].get('stato') == 'IDENTITA_VERIFICATA_DA_CATALOGO'
            and isinstance(row.get('fondamentali'), dict)
            and row['fondamentali'].get('stato') == 'VERIFICATO'
            for row in (econ_positions or []) if isinstance(row, dict)) if aligned else 0
        status['copertura_economica_patrimonio'] = {
            'stato': ('VERIFICATA_ALLA_RILEVAZIONE'
                      if aligned and verified_positions == len(four_positions)
                      else 'PARZIALE' if aligned else 'NON_ATTESTATA'),
            'posizioni': len(four_positions),
            'fondamentali_verificati': verified_positions,
            'limite': ('Prove economiche locali datate; rivalutare identità, fonti '
                       'e freschezza nel pacchetto GPT alla lettura')}
        status['lacune_shortlist_economica'] = []
        if not rows:
            status['motivi_incompletezza'].append('Nessun candidato in questo campione di scanner')
        for index, item in enumerate(rows):
            token = item['token']
            if not item.get('livelli_15m') or not item.get('livelli_1h'):
                status['motivi_incompletezza'].append('Candele incomplete: '+token)
            erow = (econ_candidates[index] if isinstance(econ_candidates, list)
                    and index < len(econ_candidates) else None)
            same_candidate = (isinstance(erow, dict)
                              and erow.get('indice') == index
                              and erow.get('token') == token
                              and erow.get('coppia_analisi') == item.get('coppia_analisi'))
            identity = erow.get('identita') if same_candidate else None
            econ_fund = erow.get('fondamentali') if same_candidate else None
            new_verified = (isinstance(identity, dict)
                            and identity.get('stato') == 'IDENTITA_VERIFICATA_DA_CATALOGO'
                            and isinstance(econ_fund, dict)
                            and econ_fund.get('stato') == 'VERIFICATO')
            if erow is not None:
                if not same_candidate:
                    status['lacune_shortlist_economica'].append(
                        'Candidato economico non allineato: '+token)
                elif not new_verified:
                    status['lacune_shortlist_economica'].append(
                        'Evidenza economica incompleta: '+token+' ('+
                        (str(identity.get('motivo') or identity.get('stato'))
                         if isinstance(identity, dict) and
                            identity.get('stato') != 'IDENTITA_VERIFICATA_DA_CATALOGO'
                         else str(econ_fund.get('stato') if isinstance(econ_fund, dict)
                                  else 'FONTE_ASSENTE'))+')')
            else:
                status['lacune_shortlist_economica'].append(
                    'Evidenza economica assente: '+token)
            legacy_fund = item.get('fondamentali_coingecko')
            if not new_verified and (not legacy_fund or legacy_fund.get('errore')
                                     or not legacy_fund.get('id')):
                status['motivi_incompletezza'].append('Fondamentali non verificati: '+token)
            flow=item.get('flusso_spot_kraken',{})
            if flow.get('stato') not in ('COMPLETO_4H','FINESTRA_4H_NON_COPERTA'):
                status['motivi_incompletezza'].append('Trades spot non disponibili: '+token)
        for origin,details in dossier.get('fonti_esterne',{}).items():
            if isinstance(details,dict) and details.get('errore'):
                status['motivi_incompletezza'].append('Fonte esterna assente: '+origin)
        deriv=dossier.get('contesto_derivati_btc',{})
        for metric in ('open-interest','cvd'):
            if deriv.get(metric,{}).get('errore'):
                status['motivi_incompletezza'].append('Derivati BTC assenti: '+metric)
        market_complete = not status['motivi_incompletezza']
        quality = dossier.get('qualita_patrimonio') or {}
        four = dossier.get('patrimonio_4tf') or {}
        four_rows = four.get('posizioni') or []
        status['copertura_patrimonio_4tf'] = {
            'posizioni': len(four_rows),
            'completate': sum(x.get('stato') == 'COMPLETO' for x in four_rows
                             if isinstance(x, dict)),
            'richieste_ohlc': four.get('richieste_ohlc'),
            'budget_ohlc': four.get('budget_ohlc'),
            'stato': ('COMPLETO' if four_rows and all(
                isinstance(x, dict) and x.get('stato') == 'COMPLETO'
                for x in four_rows) else 'PARZIALE')}

        status['stato_fonti_mercato'] = 'COMPLETO' if market_complete else 'PARZIALE'
        status['stato_patrimonio'] = quality.get('stato_totale', 'NON_VERIFICABILE')
        status['stato_quantita'] = quality.get('stato_quantita', 'NON_VERIFICABILE')
        status['fotografia_portafoglio_sha256'] = dossier.get('fotografia_portafoglio_sha256')
        status['portafoglio_letto_utc'] = quality.get('portafoglio_letto_utc')
        status['acquisizione_saldo_utc'] = (quality.get('stato_saldo') or {}).get('acquisizione_saldo_utc')
        status['posizioni_registrate'] = quality.get('posizioni_registrate')
        status['posizioni_valorizzate'] = quality.get('posizioni_valorizzate')
        status['posizioni_incomplete'] = quality.get('posizioni_incomplete')
        status['zero_reale'] = quality.get('zero_reale', False)
        status['motivi_patrimoniali'] = []
        if not quality.get('portafoglio_noto') or quality.get('stato_quantita') != 'COMPLETE':
            status['motivi_patrimoniali'].append('Identità o quantità non tutte valide')
        if quality.get('stato_totale') != 'COMPLETO':
            status['motivi_patrimoniali'].append('Controvalore EUR non completo')
        # Full EUR valuation must cover the same nonempty set of positions.
        # Candidate completeness never substitutes for these wallet invariants.
        n = quality.get('posizioni_registrate')
        if (type(n) is not int or n < 1
                or type(quality.get('posizioni_valorizzate')) is not int
                or quality['posizioni_valorizzate'] != n
                or type(quality.get('posizioni_incomplete')) is not int
                or quality['posizioni_incomplete'] != 0):
            status['motivi_patrimoniali'].append('Copertura patrimoniale incompleta o incongruente')
        if not quality.get('saldo_recente_verificato'):
            status['motivi_patrimoniali'].append('Saldo Kraken attuale non attestato')
        if (not isinstance(status['fotografia_portafoglio_sha256'], str)
                or re.fullmatch(r'[a-f0-9]{64}', status['fotografia_portafoglio_sha256']) is None):
            status['motivi_patrimoniali'].append('Fotografia patrimoniale non identificabile')
        # A deficient external opportunity or derivative feed cannot invalidate
        # otherwise verified holdings. A full economic recommendation still
        # requires the GPT reader's independent source/time checks.
        suitable = not status['motivi_patrimoniali']
        status['idoneita_analisi_patrimoniale'] = 'IDONEA' if suitable else 'NON_IDONEA'
        status['stato'] = ('PRONTO_PER_ESAME_GPT' if suitable and market_complete else
                           'PRONTO_PER_ESAME_GPT_CON_LIMITI' if suitable else
                           'PARZIALE' if not market_complete else
                           'PRONTO_PER_ESAME_MERCATO')
        status['preparato_utc']=dossier['creato_utc']
    except Exception as exc:
        status['motivi_incompletezza']=[type(exc).__name__+': '+str(exc)[:180]]
        # A malformed, mismatched or stale input must explicitly remain
        # ineligible even when candidate collection aborted before quality
        # fields could be evaluated.
        status['idoneita_analisi_patrimoniale'] = 'NON_IDONEA'
        status['stato_fonti_mercato'] = 'NON_VERIFICABILE'
        status['motivi_patrimoniali'] = ['Dossier patrimoniale non verificabile']
    save('dossier_stato.json', status)
    return status


def stato_dossier_per_report(data, portfolio=None):
    """Reject dossier/wallet drift even when public market timestamps match."""
    status = load('dossier_stato.json', {}) or {}
    dossier = load('dossier_multifonte.json', {}) or {}
    snap = data['rilevazione_utc']
    if (not isinstance(status, dict) or not isinstance(dossier, dict)
            or status.get('rilevazione_kraken_utc') != snap
            or dossier.get('kraken_istantanea_utc') != snap):
        return {'stato': 'NON_ALLINEATO', 'rilevazione_kraken_utc': snap,
                'idoneita_analisi_patrimoniale': 'NON_IDONEA',
                'stato_fonti_mercato': 'NON_VERIFICABILE',
                'motivi_incompletezza': ['Il dossier GPT non corrisponde alla rilevazione Kraken']}
    current = fotografia_portafoglio_sha256(portfolio) if portfolio is not None else None
    recorded = dossier.get('fotografia_portafoglio_sha256')
    status_id = status.get('fotografia_portafoglio_sha256')
    if recorded and status_id and current and recorded == status_id == current:
        # A matching wallet hash does not extend the life of the market snapshot.
        # Use the same 60-minute limit as dossier_trade.collect, at report time.
        now = NOW()
        try:
            observed = dt.datetime.fromisoformat(snap.replace('Z', '+00:00'))
            if observed.tzinfo is None:
                raise ValueError('Market timestamp without timezone')
            age = (now - observed.astimezone(dt.timezone.utc)).total_seconds()
            market_recent = -120 <= age <= 3600
        except (TypeError, ValueError, AttributeError, OverflowError):
            market_recent = False
        if status.get('idoneita_analisi_patrimoniale') == 'IDONEA' and not market_recent:
            downgraded = dict(status)
            downgraded['stato'] = 'PARZIALE'
            downgraded['stato_fonti_mercato'] = 'SCADUTO'
            downgraded['idoneita_analisi_patrimoniale'] = 'NON_IDONEA'
            downgraded['motivi_incompletezza'] = (
                list(status.get('motivi_incompletezza') or []) +
                ['Rilevazione mercato scaduta o temporalmente incoerente alla composizione del report'])
            return downgraded
        # Freshness is time-dependent: a matched SHA never freezes balance age.
        if status.get('idoneita_analisi_patrimoniale') == 'IDONEA':
            fresh_now = stato_saldo(portfolio, data.get('saldo_refresh'), now=now)
            if fresh_now['freschezza_saldo'] != 'RECENTE':
                downgraded = dict(status)
                downgraded['stato'] = ('PRONTO_PER_ESAME_MERCATO'
                                       if status.get('stato_fonti_mercato') == 'COMPLETO'
                                       else 'PARZIALE')
                downgraded['idoneita_analisi_patrimoniale'] = 'NON_IDONEA'
                downgraded['motivi_patrimoniali'] = (
                    list(status.get('motivi_patrimoniali') or []) +
                    ['Saldo non più recente alla composizione del report'])
                return downgraded
        return status
    if recorded and status_id and current and (recorded != current or status_id != recorded):
        problem = 'Fotografia del patrimonio diversa fra dossier e report'
        state = 'NON_ALLINEATO_PATRIMONIO'
    else:
        problem = 'Identità della fotografia patrimoniale non verificabile; dossier legacy o snapshot assente'
        state = 'PATRIMONIO_NON_VERIFICABILE'
    safe = dict(status)
    safe['stato'] = state
    safe['idoneita_analisi_patrimoniale'] = 'NON_IDONEA'
    safe['motivi_patrimoniali'] = list(status.get('motivi_patrimoniali') or []) + [problem]
    return safe


def refresh(*, prepare_dossier=True):
    """Existing full market producers; optional deep dossier is now explicit.

    prepare_dossier=True preserves legacy library compatibility. The KDD-27
    monitor and the CLI/dashboard use False; only an explicit dossier request
    uses prepara_dossier_aggiornamento().
    """
    # Lettura privata indipendente dalla raccolta pubblica, senza cancellare il saldo vecchio.
    saldo_refresh = aggiorna_saldo_sola_lettura()
    portfolio = load('portafoglio.json', {'posizioni':[]})
    conf = load('config.json', {})
    ctx = load('contesto.json', {})
    print('Recupero coppie Kraken (lettura pubblica)...')
    pairs_started = NOW().isoformat(timespec='seconds')
    pairs = kraken('AssetPairs')
    pairs_received = NOW().isoformat(timespec='seconds')
    time.sleep(1.1)
    ticker_started = NOW().isoformat(timespec='seconds')
    tickers = kraken('Ticker')
    ticker_received = NOW().isoformat(timespec='seconds')
    markets = market_pairs_and_ticker(pairs, tickers)  # prezzo EUR portafoglio e radar storico
    markets_multi, rates = multi.assemble(
        pairs, tickers, min_vol=num(conf.get('scanner',{}).get('volume_24h_min_eur',500000)),
        max_spread=num(conf.get('scanner',{}).get('spread_massimo_pct',0.8)))
    # Reuse the existing verified multi-quote Kraken Spot/FX catalog for
    # positions with no EUR market. Keep original EUR quotes unchanged.
    # A missing direct FX observation cannot create an invented EUR price:
    # mercati_spot.assemble omits such a market.
    markets = wallet_spot_markets(markets, markets_multi, portfolio)
    tokens = sorted({'BTC','ETH','SOL'} |
                    {wallet_symbol(h.get('token'))[0]
                     for h in (portfolio.get('posizioni') or [])
                     if isinstance(h, dict) and wallet_symbol(h.get('token'))[1]})
    trends = {}
    for tok in tokens:
        row = markets.get(tok)
        if not row:
            trends[tok] = {'errore':'Token senza coppia EUR disponibile'}
            continue
        try:
            time.sleep(1.1)
            c = kraken('OHLC', pair=row['pair_key'], interval=1440)
            bars = [v for k,v in c.items() if k != 'last'][0]
            trends[tok] = trend_spot_quotato(bars, row)
        except Exception as exc:
            trends[tok] = {'errore': f'OHLC non disponibile ({type(exc).__name__})'}
    # Campione stratificato per movimento E liquidità: 24 OHLC 1h MAX;
    # fino a quattro approfondimenti 15m/book, privilegiando setup osservati.
    import ricerca_setup as explorer
    ora_candele=NOW().timestamp()
    prior_snapshot=load('ultima_rilevazione.json',{})
    prior_search=(prior_snapshot.get('ricerca_setup')
                  if isinstance(prior_snapshot,dict) else None)
    shortlist,ricerca,ore_cache=explorer.scan(
        markets_multi,conf.get('scanner',{}),kraken,ora_candele,
        previous=prior_search)
    ricerca['catalogo_kraken']=multi.coverage(pairs,tickers,markets_multi)
    ricerca['riferimento_candele_utc']=dt.datetime.fromtimestamp(
        ora_candele,dt.timezone.utc).isoformat(timespec='seconds')
    if not shortlist:
        ricerca['ripiego']='NESSUNO: movimento percentuale positivo da solo non costituisce un setup verificato'
    schede = []
    depth_by_pair = {}  # sola memoria del refresh, non persistito
    # Il confronto BTC va fatto con lo STESSO quote del token (USD vs USD, ecc.).
    btc_hours_by_quote = {}
    btc_pair_by_quote = {p['quote']: p['pair_key']
                         for p in markets_multi.get('BTC', {}).get('alternative', [])}
    for item in shortlist:
        row = markets_multi[item['token']]
        metrics = book = None
        error = None
        quote = row['quote']
        btc_pair = btc_pair_by_quote.get(quote)
        if not btc_pair:
            error = f'BTC/{quote} non disponibile: confronto omogeneo impossibile'
        else:
            try:
                if quote not in btc_hours_by_quote:
                    btc_raw = kraken('OHLC', pair=btc_pair, interval=60)
                    btc_hours_by_quote[quote] = next(v for k, v in btc_raw.items() if k != 'last')
                time.sleep(0.65)
                hours = ore_cache.get(item['pair_key'])
                if hours is None:
                    hourly = kraken('OHLC', pair=item['pair_key'], interval=60)
                    hours = next(v for k,v in hourly.items() if k!='last')
                time.sleep(0.65)
                quarters = kraken('OHLC', pair=item['pair_key'], interval=15)
                time.sleep(0.65)
                depth = kraken('Depth', pair=item['pair_key'], count=10)
                mins = next(v for k, v in quarters.items() if k != 'last')
                levels = next(v for k, v in depth.items() if k != 'last')
                depth_by_pair[row['pair']] = levels
                # Le stesse ore CHIUSE della preselezione, anche attraversando un'ora.
                metrics = tactical.momentum(hours, mins, btc_hours_by_quote[quote],
                                            now=ora_candele)
                book = tactical.book_metrics(levels, eur_per_quote=row['eur_per_quote'])
            except Exception as exc:
                error = f"Kraken / metriche ({type(exc).__name__})"
        card=tactical.evaluate(row, item['categoria'], metrics, book,error=error,
                               config=conf.get('scanner',{}))
        card['perche_selezionato']=item.get('perche','Solo controllo senza setup')
        card['preselezione']=item.get('preselezione')
        card['origine_scanner']={
            'fonte':'Kraken Spot pubblico OHLC 1h + AssetPairs/Ticker',
            'ciclo':ricerca['ciclo'], 'osservato_utc':item.get('osservato_utc'),
            'pair_key':item.get('pair_key'),
            'regime_osservato':item.get('regime_osservato'),
            'invalidazione':item.get('invalidazione'),
            'segnali_contrari':item.get('segnali_contrari',[]),
            'qualita_dati':item.get('qualita_dati'),
            'limite':'Preselezione descrittiva; un cambio percentuale non determina ordine o previsione'}
        card['copertura_scanner']={
            k:ricerca.get(k) for k in (
                'mercati_osservati_ticker','universo_ammissibile',
                'campionati','analizzati','ammissibili_non_campionati',
                'universo_esaminato_almeno_una_volta','universo_mai_esaminato',
                'copertura_progressiva_pct')}
        if item['categoria']=='nessun setup confermato':
            card['esito']='NESSUN SETUP INDIVIDUATO'
            card['sintesi']='Solo caso di confronto: non è emerso un ingresso spot da proporre.'
        schede.append(card)
    # Stima costi solo per i pochi token approfonditi: nessun saldo privato.
    cost_conf = conf.get('costi_spot_esempio', {})
    notional = num(cost_conf.get('importo_eur', 100))
    crypto_taker = num(cost_conf.get('taker_crypto_pct', 0.8)) / 100
    crypto_maker = num(cost_conf.get('maker_crypto_pct', 0.4)) / 100
    fx_taker = num(cost_conf.get('taker_fx_pct', 0.2)) / 100
    cost_errors = []
    fx_books = {}
    fx_names = {'EUR/USD', 'USDC/EUR', 'USDC/USD', 'USD/EUR', 'EUR/USDC', 'USD/USDC'}
    for key, meta in pairs.items():
        w = meta.get('wsname', '')
        if w not in fx_names or meta.get('status') != 'online':
            continue
        try:
            time.sleep(0.55)
            raw = kraken('Depth', pair=key, count=10)
            fx_books[w] = next(v for k,v in raw.items() if k != 'last')
        except Exception as ex:
            cost_errors.append(f"FX book {w}: {type(ex).__name__}")
    # Deduplica gli order book, incluse le coppie già viste dal radar.
    for card in schede:
        for alt in card.get('alternative', []):
            if alt['pair'] in depth_by_pair:
                continue
            try:
                time.sleep(0.55)
                data_depth = kraken('Depth', pair=alt['pair_key'], count=10)
                depth_by_pair[alt['pair']] = next(v for k,v in data_depth.items() if k != 'last')
            except Exception as ex:
                cost_errors.append(f"{alt['pair']}: {type(ex).__name__}")
        card['costi_roundtrip'] = costs.compare_for_token(
            card.get('alternative', []), depth_by_pair, fx_books, rates,
            amount_eur=notional, crypto_fee=crypto_taker, fx_fee=fx_taker)
        # Scenari maker SOLO per la coppia col minore costo taker per saldo:
        # evita tabelle di 16 righe e promesse di fill non verificabili.
        card['costi_modalita'] = []
        available = card['costi_roundtrip']
        rate_map = {k: v['eur'] for k, v in rates.items()}
        for start_currency in ('EUR', 'USDC'):
            executable = [x for x in available
                          if x.get('valuta_partenza') == start_currency
                          and 'costo_roundtrip_eur' in x]
            if not executable:
                continue
            baseline = min(executable, key=lambda x: x['costo_roundtrip_eur'])
            pair = baseline['coppia']
            card['costi_modalita'].extend(costs.compare_modes(
                pair, depth_by_pair[pair], start_currency, notional,
                rate_map, fx_books,
                crypto_fee=crypto_taker, maker_fee=crypto_maker, fx_fee=fx_taker))
    news = []; failures=[]
    for name,url,kind in FEEDS:
        items,error = fetch_feed(name,url,kind)
        news.extend(items)
        if error: failures.append(error)
    # Secondo mercato di riferimento: Binance spot PUBBLICO, senza chiavi.
    # Il book Kraken rimane quello di esecuzione; i volumi Binance sono contesto.
    try:
        import binance_reference as b_ref
        observed = sorted(set(tokens) | {x['token'] for x in schede})
        binance_ref = b_ref.collect(
            observed, pairs, tickers,
            shortlist=[x['token'] for x in schede])
    except Exception as exc:
        binance_ref = {'status':'NON_DISPONIBILE',
                       'observed_utc':NOW().isoformat(timespec='seconds'),
                       'reason':type(exc).__name__, 'tokens':[]}
    print('Binance spot pubblico:', binance_ref['status'], '|',
          len(binance_ref.get('tokens',[])), 'token')
    # Questi sono orari misurati dal telefono, NON timestamp nativi dell'exchange.
    composed_utc = NOW().isoformat(timespec='seconds')
    data = {'saldo_refresh': saldo_refresh,
            'orari_fonti': {
                'kraken_asset_pairs_richiesta_utc': pairs_started,
                'kraken_asset_pairs_risposta_utc': pairs_received,
                'kraken_ticker_richiesta_utc': ticker_started,
                'kraken_ticker_risposta_utc': ticker_received,
                'binance_risposta_utc': binance_ref.get('observed_utc'),
                'composizione_kdd_utc': composed_utc,
                'nota': 'Orari locali di osservazione, non timestamp Kraken nativi'},
            'binance_reference':binance_ref,
            'rilevazione_utc': composed_utc, 'markets': markets,
            'n_coppie_multi': sum(x['n_coppie'] for x in markets_multi.values()),
            'n_token_multi': len(markets_multi), 'fx_rilevati': rates,
            'trends': trends, 'schede_v02': schede, 'ricerca_setup': ricerca,
            'costi_errori':cost_errors, 'feed': news, 'problemi_feed': failures}
    save('ultima_rilevazione.json', data)
    # La verifica osservativa e' indipendente dal dossier e non inserisce ordini.
    # Anche in caso di errore esplicita la mancanza senza cancellare il piano.
    import verifica_piani
    check_out=verifica_piani.safe_check()
    print('Verifica vecchio piano:',check_out.get('stato'),
          '| nessun trade simulato come eseguito')
    status_dossier=(prepara_dossier_aggiornamento(data, asset_pairs=pairs)
                    if prepare_dossier else None)
    # Solo dopo che entrambe le valutazioni GPT sono state congelate:
    # verifica le chiusure future se i relativi orizzonti sono maturi.
    # Al massimo 4 richieste OHLC per refresh, zero prima della scadenza.
    import studio_delta
    delta_status=studio_delta.safe_verify()
    print('Studio delta:',delta_status.get('stato'),
          '| chiusure osservate',delta_status.get('orizzonti_maturi_con_esito',0),
          '| chiamate pubbliche',delta_status.get('chiamate_kraken',0))
    if status_dossier is not None:
        print('Dossier per GPT:',status_dossier['stato'],
              '|', len(status_dossier.get('token_analizzati',[])), 'candidati',
              '| analisi GPT non ricalcolata')
    else:
        print('KDD-27: raccolta completata senza generare dossier o handoff')
    output(data)
    return data

def output(data):
    # One actual in-memory wallet for report valuation and dossier provenance.
    account_portfolio = load('portafoglio.json', {'posizioni': []})
    schema_ok = (isinstance(account_portfolio, dict)
                 and isinstance(account_portfolio.get('posizioni'), list))
    # The direct build_report contract still rejects malformed schema; output
    # alone can publish an explicit error without replacing the real wallet.
    valuation_portfolio = account_portfolio if schema_ok else {'posizioni': []}
    report = build_report(data, valuation_portfolio, load('config.json',{}),
                          load('contesto.json',{}), load_decisions())
    if not schema_ok:
        report.update({'stato_totale': 'SCHEMA_NON_VALIDO',
                       'totale_stimato_eur': None, 'zero_reale': False,
                       'totale_parziale': True, 'posizioni_registrate': None,
                       'posizioni_incomplete': None, 'posizioni_non_aggiornate': None,
                       'errore_struttura_portafoglio':
                       'Formato posizioni non valido: nessuna attribuzione patrimoniale.'})
    report['fotografia_portafoglio_sha256'] = fotografia_portafoglio_sha256(account_portfolio)
    report['portafoglio_letto_utc'] = NOW().isoformat(timespec='seconds')
    report['portafoglio_fonte'] = (account_portfolio.get('fonte_quantita')
                                   if isinstance(account_portfolio, dict) else None)
    report['binance_reference'] = data.get('binance_reference',{})
    report['liquidita_spot_api'] = (account_portfolio.get('liquidita_spot_api',{})
                                   if isinstance(account_portfolio, dict) else {})
    report['migrazione_attesa'] = load('migrazione_attesa.json',{})
    report['esperimento_delta'] = load('esperimenti_delta/stato_verifiche.json',{})
    linked_dossier=load('dossier_multifonte.json',{})
    report['flussi_spot'] = (
        {x['token']:x.get('flusso_spot_kraken',{})
         for x in linked_dossier.get('candidati',[])}
        if linked_dossier.get('kraken_istantanea_utc')==data['rilevazione_utc'] else {})
    report['piano_gpt'] = piano_gpt.load()
    # Archivia il piano al PRIMO salvataggio in dashboard, anche senza refresh.
    # Se verra' sostituito, l'originale resta osservabile nel tempo.
    import verifica_piani
    verifica_piani.archivia_piano(report['piano_gpt'])
    report['dossier_stato'] = stato_dossier_per_report(data, portfolio=account_portfolio)
    report['verifica_piano'] = load('verifica_piano_corrente.json',{})
    report['verifica_storico'] = load('verifica_storico_stato.json',{})
    # Validate whole payload before saving: Python's default JSON would emit
    # non-standard NaN/Infinity constants, which a GPT consumer might accept.
    json.dumps(report, ensure_ascii=False, allow_nan=False)
    save('ultimo_report.json', report)
    (DIR/'cruscotto.html').write_text(render(report),encoding='utf-8')
    print('Aggiornato: cruscotto.html | ultimo_report.json')
    print('Regime:', report['mercato'])
    print('Posizioni:',len(report['posizioni']),'| gainer:',len(report['candidati']), '| schede V0.2:',len(report['schede_v02']))
    print('IMPORTANTE: senza contesto macro/geo verificato e prezzi recenti, nessuna operazione automatica.')

def annotate(args):
    if args.giorni <= 0 or args.giorni > 90: raise ValueError('La decisione deve scadere fra 1 e 90 giorni.')
    now = NOW()
    record = {'token': args.token.upper(), 'scelta': args.scelta.upper().replace('_',' '),
              'motivo': args.motivo, 'creata_utc': now.isoformat(timespec='seconds'),
              'scade_utc': (now+dt.timedelta(days=args.giorni)).isoformat(timespec='seconds')}
    with (DIR/'decisioni.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(record,ensure_ascii=False)+'\n')
    print('Decisione registrata, con scadenza:',record['scade_utc'])
    latest = load('ultima_rilevazione.json')
    if latest: output(latest)

def context_update(args):
    context = load('contesto.json', {})
    context[args.area] = {'valutazione': args.valutazione, 'fonte': args.fonte,
                          'aggiornato_utc': NOW().isoformat(timespec='seconds'),
                          'validita_giorni': args.giorni}
    save('contesto.json', context)
    print('Contesto aggiornato:',args.area)
    latest = load('ultima_rilevazione.json')
    if latest: output(latest)

def request_public_asset(args):
    """Record at most three explicit research requests; no Kraken call or order."""
    import re
    token,valid=wallet_symbol(args.token)
    if not valid or not re.fullmatch(r"[A-Z0-9]{2,20}",token):
        raise ValueError("Asset da esaminare: simbolo non valido")
    conf=load("config.json",{})
    if not isinstance(conf,dict):
        raise ValueError("Configurazione locale non valida")
    old=conf.get("analisi_asset_richiesti",[])
    old=old if isinstance(old,list) else []
    current=[]
    for record in old:
        if isinstance(record,dict) and record.get("token")!=token:
            current.append(record)
    current=current[-2:]
    canale=getattr(args,"canale","CLI")
    if canale not in ("CLI","WEB_LOCALE"):
        raise ValueError("Canale richiesta non valido")
    current.append({"token":token,"richiesto_utc":NOW().isoformat(timespec="seconds"),
                    "origine":("UI_ESPLICITA_LOCALE" if canale=="WEB_LOCALE"
                               else "CLI_ESPLICITO_LOCALE")})
    conf["analisi_asset_richiesti"]=current
    save("config.json",conf)
    print("Richiesta pubblica registrata:",token,
          "| sara verificata al prossimo aggiorna contro AssetPairs",
          "| nessun acquisto, nessun dato privato")


def main():
    if not checkpoint_allineato():
        print('ATTENZIONE CHECKPOINT: codice/config/test diversi dall’ultimo stato descritto nel README. Aggiornare stato e impronta prima del subentro.', file=sys.stderr)
    ap = argparse.ArgumentParser(description='Decision desk Kraken: lettura pubblica, niente ordini')
    sub = ap.add_subparsers(dest='cmd',required=True)
    sub.add_parser('aggiorna', help='Scarica prezzi e feed, genera cruscotto.html')
    sub.add_parser('rigenera', help='Rigenera HTML dall’ultima rilevazione, senza rete')
    req=sub.add_parser('richiedi-asset', help='Richiedi analisi economica di un asset pubblico fuori wallet/scanner, nessun ordine')
    req.add_argument('token')
    d = sub.add_parser('decisione', help='Registra una decisione temporanea, con ragione e scadenza')
    d.add_argument('token'); d.add_argument('scelta'); d.add_argument('motivo'); d.add_argument('--giorni',type=int,default=7)
    c = sub.add_parser('contesto', help='Registra una lettura documentata di macroeconomia/geopolitica')
    c.add_argument('area',choices=['macroeconomia','geopolitica']); c.add_argument('valutazione'); c.add_argument('fonte'); c.add_argument('--giorni',type=int,default=7)
    args = ap.parse_args()
    try:
        if args.cmd == 'aggiorna': refresh(prepare_dossier=False)
        elif args.cmd == 'richiedi-asset': request_public_asset(args)
        elif args.cmd == 'rigenera':
            last = load('ultima_rilevazione.json')
            if not last: raise RuntimeError('Manca una rilevazione: esegui prima aggiorna.')
            output(last)
        elif args.cmd == 'decisione': annotate(args)
        elif args.cmd == 'contesto': context_update(args)
    except Exception as exc:
        print(f'ERRORE: {exc}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__': sys.exit(main())
