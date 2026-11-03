#!/usr/bin/env python3
"""KDD G0: prepare ONE private wallet-first GPT analysis packet from current KDD files.

Read-only for KDD originals. No network, Kraken orders, Drive or FolderSync.
An explicit --write-private writes only under Termux's app-private state directory.
This is an opt-in, app-private packet generator; it never publishes or synchronizes.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import datetime as dt
from decimal import Decimal, InvalidOperation
import grafico_4h as charts
import json
import os
from pathlib import Path
import re
import stat
import tempfile

SCHEMA = "kdd_wallet_analysis_packet_v001"
UTC = dt.timezone.utc
DEFAULT_SOURCE = Path.home() / "kraken-decision-desk" / "KRAKEN_DECISION_DESK_V001"
PRIVATE_OUTPUT = Path.home() / ".local" / "state" / "kraken-decision-desk" / "wallet_packet_gpt_v001.json"
SRC_MAX = {"portafoglio.json": 2_000_000, "ultimo_report.json": 9_000_000,
           "ultima_rilevazione.json": 15_000_000, "dossier_multifonte.json": 15_000_000}
SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,19}$")


class PacketError(ValueError):
    """Failure message contains no portfolio values."""


def read_json(root: Path, name: str) -> dict:
    """Read only a known, regular JSON, never a symlink or unrelated credentials."""
    path = root / name
    try:
        if path.is_symlink():
            raise PacketError("Input non regolare: " + name)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or not 2 <= info.st_size <= SRC_MAX[name]:
            raise PacketError("Input assente o fuori misura: " + name)
        with path.open("rb") as stream:
            raw = stream.read(SRC_MAX[name] + 1)
        if len(raw) > SRC_MAX[name]:
            raise PacketError("Input fuori misura: " + name)
        result = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PacketError("Input non leggibile: " + name) from exc
    if not isinstance(result, dict):
        raise PacketError("Input non oggetto: " + name)
    return result


def when(value, label: str) -> dt.datetime:
    if not isinstance(value, str):
        raise PacketError("Orario assente: " + label)
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("naive")
        return result.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise PacketError("Orario non valido: " + label) from exc


def amount(value, label: str, *, nonnegative=True):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise PacketError("Numero non valido: " + label)
    try:
        v = Decimal(str(value))
    except InvalidOperation as exc:
        raise PacketError("Numero non valido: " + label) from exc
    if not v.is_finite() or (nonnegative and v < 0):
        raise PacketError("Numero non valido: " + label)
    return format(v, "f")


def d1_float(value, label):
    """Finite IEEE-754 arithmetic exactly matching decision_desk.build_report."""
    try:
        result = float(Decimal(value))
    except (ValueError, TypeError, OverflowError, InvalidOperation) as exc:
        raise PacketError("Numero fuori scala: " + label) from exc
    if not math.isfinite(result):
        raise PacketError("Numero fuori scala: " + label)
    return result


def safe_symbol(value, label="token"):
    if not isinstance(value, str) or not SYMBOL.fullmatch(value):
        raise PacketError("Identificativo non valido: " + label)
    return value


def safe_notes(items, max_items=6):
    if not isinstance(items, list):
        return []
    return [x[:240] for x in items[:max_items] if isinstance(x, str)]


def source_status(timestamp: dt.datetime, current: dt.datetime, *, max_age_min=30):
    age = (current - timestamp).total_seconds() / 60
    if age < -2:
        return {"stato": "OROLOGIO_INCOERENTE", "eta_minuti": None}
    if age < 0:
        return {"stato": "OROLOGI_DISALLINEATI", "eta_minuti": None}
    return {"stato": "RECENTE" if age <= max_age_min else "DA_AGGIORNARE",
            "eta_minuti": round(age, 2)}


def portfolio_identity(portfolio: dict) -> str | None:
    """Canonical local JSON content hash, not origin authentication."""
    try:
        b=json.dumps(portfolio,sort_keys=True,separators=(',', ':'),
                     ensure_ascii=False,allow_nan=False).encode('utf-8')
    except (TypeError,ValueError,OverflowError):
        return None
    return hashlib.sha256(b).hexdigest()


def canonical_wallet_alias(token):
    """Only documented legacy Kraken identifiers: no generic prefix stripping."""
    return {'XBT':'BTC','XXBT':'BTC','XDG':'DOGE','XXDG':'DOGE'}.get(token,token)


# Syntax only: a Kraken AssetPairs key is opaque, never decoded as an asset.
KRAKEN_PAIR_KEY = re.compile(r"[A-Za-z0-9_.-]{2,48}$")


def verify_eur_market_identity(snapshot, token, market, four_row=None):
    """Reject contradicted EUR provenance; do not infer assets from opaque keys."""
    identity = canonical_wallet_alias(token)
    if not isinstance(market, dict):
        raise PacketError("Identita mercato EUR assente per posizione valorizzata")
    pair = market.get("pair")
    if not isinstance(pair, str) or pair.count("/") != 1:
        raise PacketError("Coppia mercato EUR assente o non valida")
    base, quote = pair.split("/")
    if (not SYMBOL.fullmatch(base) or quote != "EUR"
            or canonical_wallet_alias(base) != identity):
        raise PacketError("Coppia mercato EUR incoerente con posizione")
    declared = market.get("token")
    if (not isinstance(declared, str) or not SYMBOL.fullmatch(declared)
            or canonical_wallet_alias(declared) != identity):
        raise PacketError("Identita token mercato EUR assente o discordante")
    key = market.get("pair_key")
    if not isinstance(key, str) or not KRAKEN_PAIR_KEY.fullmatch(key):
        raise PacketError("Identita Kraken della coppia EUR non verificabile")
    # Extra metadata, if present, must agree; it cannot override pair/token.
    for field in ("base", "asset_base"):
        if field in market:
            other = market[field]
            if (not isinstance(other, str) or not SYMBOL.fullmatch(other)
                    or canonical_wallet_alias(other) != identity):
                raise PacketError("Identita base mercato EUR discordante")
    for field in ("quote", "valuta_quotazione"):
        if field in market and market[field] != "EUR":
            raise PacketError("Coppia mercato EUR con valuta incoerente")
    markets = snapshot.get("markets")
    # The exact same opaque Kraken identifier cannot name two different assets
    # in the SAME observation; this is an observable conflict, not key parsing.
    if isinstance(markets, dict):
        for other_token, other in markets.items():
            if (other_token != token and isinstance(other, dict)
                    and other.get("pair_key") == key
                    and canonical_wallet_alias(other_token) != identity):
                raise PacketError("Identita Kraken riutilizzata fra asset diversi")
    # The separately built, same-wallet/snapshot 4TF dossier is corroboration
    # only when it identifies a EUR pair. USD/USDC 4TF never imply EUR prices.
    if (isinstance(four_row, dict) and four_row.get("valuta_quotazione") == "EUR"
            and isinstance(four_row.get("coppia"), str)):
        if (four_row.get("coppia") != pair or four_row.get("pair_key") != key):
            raise PacketError("Identita Kraken EUR contraddetta dal dossier 4TF")


def four_tf_evidence(portfolio, report, dossier, expected_market):
    """Verify exact D1/D2 wallet/snapshot identity before using 4TF evidence.

    Legacy dossiers remain readable but explicitly lack four-TF evidence.
    """
    four=dossier.get('patrimonio_4tf')
    if not isinstance(four,dict):
        return None
    identifier=portfolio_identity(portfolio)
    if (not identifier or four.get('portafoglio_sha256')!=identifier
            or dossier.get('fotografia_portafoglio_sha256')!=identifier
            or report.get('fotografia_portafoglio_sha256')!=identifier):
        raise PacketError('Fotografia patrimoniale 4TF discordante')
    if (four.get('rilevazione_kraken_utc')!=expected_market
            or dossier.get('kraken_istantanea_utc')!=expected_market):
        raise PacketError('Rilevazione delle serie 4TF discordante')
    rows=four.get('posizioni')
    if not isinstance(rows,list) or len(rows)!=len(portfolio.get('posizioni',[])):
        raise PacketError('Copertura delle posizioni 4TF incompleta o manomessa')
    for index,entry in enumerate(rows):
        if not isinstance(entry,dict) or entry.get('indice')!=index:
            raise PacketError('Indice della posizione 4TF incoerente')
        actual=portfolio['posizioni'][index]
        symbol=actual.get('token') if isinstance(actual,dict) else None
        if isinstance(symbol,str):
            symbol=symbol.strip().upper()
        if entry.get('identita_valida') and entry.get('token')!=symbol:
            raise PacketError('Identita della posizione 4TF incoerente')
    return rows


def technical_in_packet(row, now):
    """Evidence belongs to the declared Kraken pair, with closed OHLC rows."""
    if not isinstance(row,dict):
        raise PacketError('Posizione tecnica non strutturata')
    pair=row.get('coppia');pair_key=row.get('pair_key')
    entries=row.get('timeframe')
    if not isinstance(entries,dict):
        raise PacketError('Timeframe patrimoniali non strutturati')
    result={'stato':'PARZIALE', 'coppia':pair,
            'pair_key':pair_key, 'asset_base':row.get('asset_base'),
            'valuta_quotazione':row.get('valuta_quotazione'),
            'eleggibilita_conto':'NON_VERIFICATA', 'timeframe':{}}
    for label,seconds in (('15m',900),('1H',3600),('4H',14400),('1D',86400)):
        frame=entries.get(label)
        if not isinstance(frame,dict) or frame.get('timeframe')!=label:
            raise PacketError('Timeframe non corrispondente: '+label)
        status=frame.get('stato')
        if status not in ('AGGIORNATO','SCADUTO','STORICO_INSUFFICIENTE',
                          'NON_DISPONIBILE','NON_VALIDO','RINVIATO_BUDGET'):
            raise PacketError('Stato tecnico sconosciuto: '+label)
        if status not in ('AGGIORNATO','SCADUTO'):
            result['timeframe'][label]={'stato':status,'motivo':str(frame.get('motivo') or '')[:180]}
            continue
        if (frame.get('coppia')!=pair or frame.get('pair_key')!=pair_key
                or frame.get('valuta_quotazione')!=row.get('valuta_quotazione')
                or frame.get('asset_base')!=row.get('asset_base')
                or not pair or not pair_key):
            raise PacketError('Coppia 4TF discordante: '+label)
        raw=frame.get('serie_ohlcv_chiuse')
        if not isinstance(raw,list) or not 50<=len(raw)<=200:
            raise PacketError('Campione tecnico non valido: '+label)
        last_time=None
        for c in raw:
            if not isinstance(c,dict) or type(c.get('time')) is not int:
                raise PacketError('Timestamp OHLC non valido: '+label)
            ts=c['time']
            if ts%seconds or (last_time is not None and ts-last_time!=seconds):
                raise PacketError('Lacuna o sovrapposizione OHLC: '+label)
            last_time=ts
            vals=[c.get(n) for n in ('open','high','low','close','volume')]
            if (any(type(v) not in (float,int) or not math.isfinite(v) for v in vals)
                    or not (0<vals[2]<=min(vals[0],vals[3])<=max(vals[0],vals[3])<=vals[1]
                            and vals[4]>=0)):
                raise PacketError('Candela non valida: '+label)
        closed=when(frame.get('chiusura_utc'),'ultimo close '+label)
        observation=when(frame.get('rilevazione_utc'),'osservazione '+label)
        if (closed.timestamp()!=last_time+seconds or observation<closed
                or frame.get('ultima_candela_ohlcv_chiusa')!=raw[-1]
                or observation>now+dt.timedelta(seconds=2)
                or closed>now+dt.timedelta(seconds=2)):

            raise PacketError('Candele o timestamp incoerenti: '+label)
        # Source verdict was written at dossier generation. Re-evaluate when
        # composing the GPT packet, including a previously "AGGIORNATO" candle.
        expected_end=int((now.timestamp()-120)//seconds)*seconds
        # Canonical recomputation, not trust in persisted indicator fields.
        # Use source observation time; recompute freshness at packet time below.
        try:
            source_data={'timeframe':label,'interval_seconds':seconds,'candles':raw,
                         'observed_utc':frame['rilevazione_utc'],
                         'closed_at_utc':frame['chiusura_utc']}
            recalculated=charts.summarize_timeframe(source_data,now=observation)
            extra=charts.technical_from_candles(raw,interval_seconds=seconds)
            authoritative={name:recalculated[name] for name in (
                'stato','orientamento','chiusura_utc','rilevazione_utc',
                'candele','close','ema20','ema50','volume','volume_vs_media20',
                'supporto_vicino','resistenza_vicina')}
            authoritative.update(pivot_giornaliero=extra['pivots'],
                                 livelli_strutturali=extra['structure'],
                                 intervallo_secondi=seconds)
            for name,expected in authoritative.items():
                if name not in frame or (
                    json.dumps(frame[name],allow_nan=False,sort_keys=True)
                    != json.dumps(expected,allow_nan=False,sort_keys=True)):
                    raise PacketError('Indicatore non coerente con OHLCV: '+label+'/'+name)
        except PacketError:
            raise
        except (ValueError,TypeError,KeyError,OverflowError,ZeroDivisionError,
                ArithmeticError) as exc:
            raise PacketError('Indicatori tecnici non verificabili: '+label) from exc
        status='AGGIORNATO' if last_time+seconds>=expected_end else 'SCADUTO'
        result['timeframe'][label]={
            'stato':status, 'chiusura_utc':frame['chiusura_utc'],
            'rilevazione_utc':frame['rilevazione_utc'],
            'candele_chiuse':len(raw), 'serie_ohlcv_chiuse':raw,
            'close':amount(frame.get('close'),'close'),
            'ema20':amount(frame.get('ema20'),'EMA20'),
            'ema50':amount(frame.get('ema50'),'EMA50'),
            'volume':amount(frame.get('volume'),'volume'),
            'pivot_giornaliero':frame.get('pivot_giornaliero'),
            'livelli_strutturali':frame.get('livelli_strutturali'),
            'fonte':str(frame.get('fonte') or '')[:130],
            'limite':'Solo candele chiuse Kraken Spot; non prezzo eseguibile'}
    # A previously complete set is partial when ANY frame has aged.
    source_state=row.get('stato')
    if source_state=='COMPLETO' and all(
            x['stato']=='AGGIORNATO' for x in result['timeframe'].values()):
        result['stato']='COMPLETO'
    elif source_state not in ('COMPLETO','PARZIALE','IN_ANALISI'):
        result['stato']=source_state or 'PARZIALE'
    else:
        result['stato']='PARZIALE'
    return result


def brief_positions(portfolio: dict, report: dict, snapshot: dict, dossier: dict,
                    dossier_fresh: bool, four_rows=None, now=None) -> list[dict]:
    all_positions = portfolio.get("posizioni")
    reported = report.get("posizioni")
    if not isinstance(all_positions, list) or not isinstance(reported, list):
        raise PacketError("Posizioni non leggibili")
    if len(reported) != len(all_positions):
        raise PacketError("Numero posizioni tra report e portafoglio diverso")
    names=[]
    for row in all_positions:
        raw=row.get('token') if isinstance(row,dict) else None
        try:
            names.append(safe_symbol(raw))
        except PacketError:
            names.append(None)
    keys=[canonical_wallet_alias(token) if token is not None else None for token in names]
    duplicates={key for key in keys if key is not None and keys.count(key)>1}
    selected = []
    for index, row in enumerate(all_positions):
        token=names[index]
        matched=reported[index]
        if not isinstance(matched,dict):
            raise PacketError("Riga report non valida")
        # Invalid, duplicate or unstructured identities remain visible by row
        # index, with no attribution of assets, valuation or a decision.
        if token is None or canonical_wallet_alias(token) in duplicates:
            state=('IDENTITA_AMBIGUA' if token is not None and canonical_wallet_alias(token) in duplicates else
                   'IDENTITA_NON_VALIDA')
            if four_rows is not None:
                technical4=technical_in_packet(four_rows[index], now)
            else:
                technical4={'stato':'NON_DISPONIBILE',
                            'motivo':'Dossier senza 4TF verificati'}
            selected.append({'indice':index,'token':token,
                             'stato_identita':state,'stato_quantita':'NON_ATTRIBUIBILE','quantita_spot':None,
                             'prezzo_eur':None,'valore_eur':None,
                             'pl_indicativo_eur':None,'decisione_precedente':'',
                             'analisi_4tf':technical4,
                             'limite':'Identita non attribuibile: nessun valore o decisione riferiti alla riga'})
            continue
        if matched.get('token')!=token:
            raise PacketError("Posizioni report/portafoglio non allineate")
        try:
            qty = amount(row.get("quantita"), "quantita")
            qty_state = 'VALIDA' if qty is not None else 'NON_NOTA'
        except PacketError:
            # Keep the wallet row. The D1/D2 report must NOT ascribe
            # a numerical valuation to an invalid quantity.
            qty, qty_state = None, 'INVALIDA'
        if qty is None and (matched.get('valore_eur') is not None or
                            matched.get('prezzo_eur') is not None):
            raise PacketError('Quantita ignota/invalida ma report valorizzato')
        if qty is not None and "quantita" in matched:
            reported_qty = amount(matched["quantita"], "quantita report")
            if reported_qty is None or Decimal(qty) != Decimal(reported_qty):
                raise PacketError("Quantita report/portafoglio diversa")
        if matched and "errore" not in matched and qty is not None:
            price = amount(matched.get("prezzo_eur"), "prezzo_eur")
            val = amount(matched.get("valore_eur"), "valore_eur")
            pnl = amount(matched.get("pl_non_realizzato_eur"), "pl_indicativo", nonnegative=False)
            if (price is None) != (val is None):
                raise PacketError("Prezzo/valore incompleto")
        else:
            price, val, pnl = None, None, None
        if val is not None:
            # Reconcile each reported valuation, not just the forged global sum.
            # D1 builds float products: compare their roundtripped binary value,
            # with NO invented cent tolerance and no suppressed small amounts.
            q, unit = d1_float(qty, "quantita"), d1_float(price, "prezzo_eur")
            computed = q * unit
            if (unit <= 0 or not math.isfinite(computed)
                    or (q > 0 and computed == 0)
                    or d1_float(val, "valore_eur") != computed):
                raise PacketError("Valore incoerente con quantita e prezzo EUR")
            # FIN-RT-01: a valued report row requires a same-snapshot EUR
            # source. Missing/legacy rows can still be represented UNVALUED.
            markets = snapshot.get("markets")
            market = markets.get(token) if isinstance(markets, dict) else None
            if not isinstance(market, dict) or "prezzo_eur" not in market:
                raise PacketError("Quotazione EUR di mercato assente per posizione valorizzata")
            try:
                snap_price = amount(market["prezzo_eur"], "prezzo mercato")
                snap_unit = d1_float(snap_price, "prezzo mercato") if snap_price is not None else None
            except PacketError:
                raise PacketError("Quotazione EUR di mercato non valida per posizione valorizzata") from None
            if snap_unit is None or snap_unit <= 0:
                raise PacketError("Quotazione EUR di mercato non valida per posizione valorizzata")
            if snap_unit != unit:
                raise PacketError("Prezzo incoerente con rilevazione mercato")
            verify_eur_market_identity(
                snapshot, token, market, four_rows[index] if four_rows is not None else None)
            basis = row.get("costo_medio_eur")
            declared_cost = None
            if basis is not None:
                try:
                    declared_cost = d1_float(amount(basis, "costo medio"), "costo medio")
                except PacketError:
                    declared_cost = None
            # A declared cost is not independently authenticated trade history.
            # Missing/invalid costs MUST NOT produce a numerical P/L.
            if declared_cost is None:
                if pnl is not None:
                    raise PacketError("P/L privo di costo storico attendibile")
            else:
                expected_pl = (unit - declared_cost) * q
                if not math.isfinite(expected_pl):
                    if pnl is not None:
                        raise PacketError("P/L non rappresentabile: costo/quantita")
                elif pnl is None or d1_float(pnl, "P/L") != expected_pl:
                    raise PacketError("P/L incoerente con costo medio dichiarato")
        elif pnl is not None:
            raise PacketError("P/L senza prezzo o valore verificati")
        tr = snapshot.get("trends", {}).get(token) if isinstance(snapshot.get("trends"), dict) else None
        if not isinstance(tr, dict):
            tr = {}
        technical = {}
        for field in ("var_7g_pct", "var_30g_pct"):
            if tr.get(field) is not None:
                technical[field] = amount(tr[field], field, nonnegative=False)
        if type(tr.get("sopra_media20")) is bool:
            technical["sopra_media20"] = tr["sopra_media20"]
        chart = dossier.get("grafici_4h", {}).get(token) if dossier_fresh and isinstance(dossier.get("grafici_4h"), dict) else None
        chart_info = {"stato": "NON_DISPONIBILE"}
        if isinstance(chart, dict):
            status = str(chart.get("stato", "NON_DISPONIBILE"))
            # KDD's real 4H contract uses OK / LACUNE_TEMPORALI, not COMPLETO.
            # Never attribute a chart without checking both token and exact EUR pair.
            markets = snapshot.get("markets")
            market = markets.get(token) if isinstance(markets, dict) else None
            expected_pair = market.get("pair") if isinstance(market, dict) else None
            if (chart.get("token") == token and isinstance(expected_pair, str)
                    and chart.get("coppia") == expected_pair and status in ("OK", "LACUNE_TEMPORALI")):
                chart_info = {"stato": status, "coppia": expected_pair,
                              "fonte": "dossier_multifonte.json",
                              "limiti": "4H descrittivo, solo candele chiuse, non segnali di acquisto"}
                if status == "OK" and isinstance(chart.get("lettura_indicativa"), dict):
                    levels = chart["lettura_indicativa"]
                    summary = {}
                    if isinstance(levels.get("ultima_chiusura_utc"), str):
                        when(levels["ultima_chiusura_utc"], "ultima chiusura 4H")
                        summary["ultima_chiusura_utc"] = levels["ultima_chiusura_utc"][:40]
                    for frame in ("ultime_4", "ultime_12", "ultime_24", "ultime_48"):
                        info = levels.get(frame)
                        if isinstance(info, dict):
                            low = amount(info.get("minimo"), frame + " minimo")
                            high = amount(info.get("massimo"), frame + " massimo")
                            if low is not None and high is not None and Decimal(low) <= Decimal(high):
                                summary[frame] = {"minimo": low, "massimo": high}
                    for volume in ("volume_ultime_4", "volume_4_precedenti"):
                        if levels.get(volume) is not None:
                            summary[volume] = amount(levels[volume], volume)
                    chart_info["lettura_4h"] = summary
        technical4 = ({'stato':'NON_DISPONIBILE','motivo':'Dossier senza 4TF verificati'}
                      if four_rows is None else technical_in_packet(four_rows[index], now))
        market_eur = snapshot.get("markets", {}).get(token) if price is not None else None
        price_source = ({"token":market_eur["token"], "pair":market_eur["pair"],
                         "pair_key":market_eur["pair_key"], "valuta":"EUR",
                         "rilevazione_utc":snapshot["rilevazione_utc"]}
                        if isinstance(market_eur, dict) else None)
        selected.append({"indice":index, "token": token, "stato_identita":"VALIDA", "stato_quantita":qty_state, "quantita_spot": qty,
                         "analisi_4tf": technical4, "fonte_prezzo_eur": price_source,
                         "disponibile_spot": amount(row.get("disponibile_spot"), "disponibile_spot"),
                         "prezzo_eur": price, "valore_eur": val,
                         "pl_indicativo_eur": pnl, "variazione": technical,
                         "annotazioni_kdd": safe_notes(matched.get("note")) if isinstance(matched, dict) else [],
                         "decisione_precedente": str(matched.get("decisione", ""))[:240] if isinstance(matched, dict) else "",
                         "grafico_4h": chart_info,
                         "limite": "Nessun prezzo EUR provato" if price is None else "Prezzo indicativo non eseguibile"})
    return selected


def public_shortlist(snapshot: dict) -> list[dict]:
    out = []
    src = snapshot.get("schede_v02")
    if not isinstance(src, list):
        return out
    for x in src[:4]:
        if not isinstance(x, dict):
            continue
        token = x.get("token")
        if not isinstance(token, str) or not SYMBOL.fullmatch(token):
            continue
        out.append({"token": token,
                    "categoria": str(x.get("categoria") or "")[:100],
                    "esito_kdd": str(x.get("esito") or "")[:100],
                    "coppia_analisi": str(x.get("coppia_analisi") or "")[:70],
                    "motivazione": str(x.get("perche_selezionato") or "")[:350],
                    "sintesi": str(x.get("sintesi") or "")[:350],
                    "evidenze": safe_notes(x.get("evidenze")),
                    "criticita": safe_notes(x.get("criticita"))})
    return out


def cash_balances(portfolio: dict, report: dict) -> dict:
    raw = portfolio.get("liquidita_spot_api")
    report_cash = report.get("liquidita_spot_api")
    if raw is None and report_cash in (None, {}):
        return {}
    if not isinstance(raw, dict) or not isinstance(report_cash, dict):
        raise PacketError("Liquidita incoerente")
    result = {}
    for key in ("EUR", "USD", "USDC", "EURC"):
        v = raw.get(key, {})
        r = report_cash.get(key, {})
        if not isinstance(v, dict) or not isinstance(r, dict):
            raise PacketError("Liquidita incoerente")
        for field in ("saldo", "disponibile"):
            if amount(v.get(field), "saldo") != amount(r.get(field), "saldo report"):
                raise PacketError("Liquidita report/portafoglio diversa")
        result[key] = {"saldo": amount(v.get("saldo"), "saldo"),
                       "disponibile": amount(v.get("disponibile"), "disponibile")}
    return result


def alternative_liquidazione_150_lorda(positions: list, total, *,
                                    mercato_stato=None, saldo_stato=None) -> dict:
    """KDD-05: confronta TUTTE le posizioni come possibili fonti di 150 EUR lordi.

    Non usa il prezzo bid, il book, le fee del conto o la precisione di ordine:
    nessun risultato attesta un netto di 150 EUR o un'esecuzione possibile.
    """
    target = Decimal("150")
    total_text = amount(total, "patrimonio in EUR")
    base = Decimal(total_text) if total_text is not None else None
    current = mercato_stato == "RECENTE" and saldo_stato == "RECENTE"
    scenarios = []
    for i, row in enumerate(positions):
        if not isinstance(row, dict) or row.get("indice", i) != i:
            raise PacketError("Alternativa 150: posizione o ordine incoerenti")
        token = row.get("token")
        item = {"indice": i, "token": token,
                "esito": "NON_VERIFICABILE", "capienza_lorda_fotografia": None,
                "massimo_lordo_indicativo_eur": None,
                "quantita_teorica_150_lordi": None,
                "peso_asset_post_alleggerimento_pct": None}
        if row.get("stato_identita") != "VALIDA":
            item["esito"] = "IDENTITA_NON_VERIFICATA"
            scenarios.append(item)
            continue
        price_text = amount(row.get("prezzo_eur"), "prezzo EUR")
        held_text = amount(row.get("quantita_spot"), "quantita posseduta")
        free_text = amount(row.get("disponibile_spot"), "quantita disponibile")
        valued_text = amount(row.get("valore_eur"), "valore posizione")
        source = row.get("fonte_prezzo_eur")
        if (price_text is None or held_text is None or free_text is None
                or valued_text is None or not isinstance(source, dict)
                or source.get("valuta") != "EUR"
                or source.get("token") != token
                or not isinstance(source.get("pair"), str)
                or source["pair"].split("/")[-1] != "EUR"
                or canonical_wallet_alias(source["pair"].split("/")[0])
                   != canonical_wallet_alias(token)):
            scenarios.append(item)
            continue
        price, held, free = Decimal(price_text), Decimal(held_text), Decimal(free_text)
        valued = Decimal(valued_text)
        if price <= 0 or free > held:
            scenarios.append(item)
            continue
        maximum = free * price
        item["massimo_lordo_indicativo_eur"] = format(maximum, "f")
        item["capienza_lorda_fotografia"] = maximum >= target
        item["esito"] = ("SOGLIA_LORDA_POTENZIALE" if maximum >= target
                         else "SOTTO_SOGLIA_LORDA")
        if maximum >= target:
            # The source price is indicative, NOT a live executable bid.
            item["quantita_teorica_150_lordi"] = format(target / price, "f")
            if base is not None and base > target and valued >= target:
                remaining = valued - target
                denominator = base - target
                share = (remaining * 100 / denominator).quantize(Decimal("0.01"))
                item["peso_asset_post_alleggerimento_pct"] = format(share, "f")
        scenarios.append(item)
    return {
        "obiettivo_lordo_eur": "150",
        "freschezza_fotografia": ("RECENTE_ALLA_COMPOSIZIONE" if current
                                 else "NON_RECENTE_O_NON_ATTESTATA"),
        "n_posizioni_esaminate": len(scenarios),
        "n_fonti_potenziali_lorde": sum(
            row["capienza_lorda_fotografia"] is True for row in scenarios),
        "alternative": scenarios,
        "alternativa_senza_operazione": {
            "azione": "NON_CONVERTIRE_ORA",
            "effetto": "Nessuna vendita né nuovo capitale creato; valutare un versamento o attendere"},
        "limite": ("Il prezzo EUR è indicativo e non è un bid. Mancano book, "
                   "fee reali, spread, minimi, precisione quantità e verifica della "
                   "negoziabilità del conto. Anche SOGLIA_LORDA_POTENZIALE "
                   "non certifica che arrivino 150 EUR netti."),
    }



def book_150_per_gpt(dossier, positions, wallet_sha, snapshot_utc, now):
    """Valida origine, righe, coppia e ora della stima book prima di esporla a GPT."""
    fallback = {"stato": "NON_ATTESTATO", "righe": [],
                "limite": "Nessun confronto book verificato per la fotografia corrente."}
    raw = dossier.get("finanziamento_150_book_pubblico")
    if (not isinstance(raw, dict) or dossier.get("fotografia_portafoglio_sha256") != wallet_sha
            or raw.get("rilevazione_mercato_utc") != snapshot_utc):
        return fallback
    items = raw.get("righe")
    if not isinstance(items, list) or len(items) != len(positions):
        return fallback
    output = []
    for i, (item, position) in enumerate(zip(items, positions)):
        if (not isinstance(item, dict) or item.get("indice") != i
                or item.get("token") != position.get("token")):
            return fallback
        row = {"indice": i, "token": position.get("token"), "stato": item.get("stato")}
        if item.get("stato") == "BOOK_PUBBLICO_OSSERVATO":
            origin = position.get("fonte_prezzo_eur")
            if (not isinstance(origin, dict) or origin.get("pair") != item.get("pair")
                    or origin.get("pair_key") != item.get("pair_key")
                    or position.get("stato_identita") != "VALIDA"):
                return fallback
            try:
                observed = when(item.get("osservato_utc"), "osservazione book")
                snap = when(snapshot_utc, "fotografia book")
            except PacketError:
                return fallback
            if observed < snap - dt.timedelta(minutes=2) or observed > now + dt.timedelta(minutes=2):
                return fallback
            estimate = item.get("stima")
            if not isinstance(estimate, dict) or estimate.get("nessun_fill_attestato") is not True:
                return fallback
            if estimate.get("fee_ipotetica_pct") != "0.800":
                return fallback
            try:
                qty = amount(estimate.get("quantita_base_teorica"), "book: quantità")
                gross = amount(estimate.get("proventi_lordi_stimati_eur"), "book: lordo")
                net = amount(estimate.get("proventi_netto_fee_ipotesi_eur"), "book: netto")
                free = amount(position.get("disponibile_spot"), "book: saldo disponibile")
            except PacketError:
                return fallback
            if None in (qty, gross, net, free) or Decimal(qty) > Decimal(free):
                return fallback
            row.update({"stima": {"stato": str(estimate.get("stato"))[:80],
                                  "quantita_base_teorica": qty,
                                  "lordo_eur": gross, "netto_fee_ipotetica_eur": net,
                                  "fee_taker_ipotizzata_pct": "0.8"},
                        "osservato_utc": item.get("osservato_utc"),
                        "freschezza": ("RECENTE_ALLA_COMPOSIZIONE"
                                       if (now-observed).total_seconds() <= 300 else "SCADUTO")})
        output.append(row)
    return {"stato": "STIMA_BOOK_CON_FEE_IPOTETICA", "righe": output,
            "limite": "Non è un preventivo: fee reale, minimi, bid eseguibile e account non verificati; rivalutare freschezza alla lettura."}


def quadro_economico_per_gpt(positions: list, cash: dict, total, *, mercato_stato=None, saldo_stato=None) -> dict:
    """Pure, non-prescriptive arithmetic for KDD-02/04/05/23.

    No trading recommendation, no fee assumptions and no cross-currency sum.
    Values remain private inside the same opt-in packet as the original wallet.
    """
    if not isinstance(positions, list) or not isinstance(cash, dict):
        raise PacketError("Quadro economico: input non strutturato")
    total_value = amount(total, "totale patrimonio")
    denom = Decimal(total_value) if total_value is not None else None
    entries = []
    tokens_seen = set()
    identities_valid = True
    for pos in positions:
        if not isinstance(pos, dict):
            raise PacketError("Quadro economico: posizione non strutturata")
        token = pos.get("token")
        # Producer intentionally preserves unknown and duplicate wallet identities
        # by row index. Never remove them or fabricate a portfolio distribution.
        if (not isinstance(token, str) or not SYMBOL.fullmatch(token)
                or pos.get("stato_identita", "VALIDA") != "VALIDA"
                or token in tokens_seen):
            identities_valid = False
        else:
            tokens_seen.add(token)
        value = amount(pos.get("valore_eur"), "valore posizione")
        entries.append((token, Decimal(value) if value is not None else None))

    complete = bool(denom is not None and denom > 0 and identities_valid
                    and entries and all(value is not None for _, value in entries))
    quote = []
    if complete:
        observed = sum((v for _, v in entries), Decimal(0))
        if abs(observed - denom) > Decimal("0.01"):
            raise PacketError("Quadro economico: totale discordante")
    for token, value in entries:
        pct = ((value * Decimal(100) / denom).quantize(Decimal("0.01"))
               if complete else None)
        quote.append({"token": token, "quota_pct": format(pct, "f") if pct is not None else None})
    top = sorted((v for _, v in entries if v is not None), reverse=True) if complete else []
    pct_top2 = (sum(top[:2], Decimal(0)) * 100 / denom).quantize(Decimal("0.01")) if top else None
    pct_top3 = (sum(top[:3], Decimal(0)) * 100 / denom).quantize(Decimal("0.01")) if top else None
    scenario_150 = (Decimal(150) * 100 / denom).quantize(Decimal("0.01")) if complete else None

    currencies = ("EUR", "EURC", "USD", "USDC")
    available = []
    for symbol in currencies:
        block = cash.get(symbol)
        if not isinstance(block, dict):
            available = []
            break
        value = amount(block.get("disponibile"), "liquidita disponibile")
        if value is None:
            available = []
            break
        available.append(Decimal(value))
    if len(available) != len(currencies):
        cash_status = "NON_VERIFICATA"
    elif not any(available):
        cash_status = "ZERO_RILEVATO_NELLE_QUATTRO_VALUTE"
    else:
        cash_status = "PRESENTE_PER_VALUTA_EQUIVALENZA_EUR_NON_ATTESTATA"

    return {
        "stato": "INDICATIVO" if complete else "NON_CALCOLABILE_INTEGRALMENTE",
        "base": "valore_eur_posizioni_senza_liquidita",
        "alternative_liberazione_150_lordi": alternative_liquidazione_150_lorda(
            positions, total, mercato_stato=mercato_stato, saldo_stato=saldo_stato),
        "quote_posizioni": quote,
        "concentrazione_top2_pct": format(pct_top2, "f") if pct_top2 is not None else None,
        "concentrazione_top3_pct": format(pct_top3, "f") if pct_top3 is not None else None,
        "liquidita_stato": cash_status,
        "esempio_150_eur_sul_patrimonio_pct": (format(scenario_150, "f")
                                               if scenario_150 is not None else None),
        "esempio_150_finanziamento_stato": (
            "NESSUNA_LIQUIDITA_SULLE_QUATTRO_VALUTE_VERIFICARE_FONTI"
            if cash_status == "ZERO_RILEVATO_NELLE_QUATTRO_VALUTE" else
            "NON_DETERMINABILE_SENZA_CAMBIO_SPREAD_E_COSTI"
            if cash_status == "PRESENTE_PER_VALUTA_EQUIVALENZA_EUR_NON_ATTESTATA" else
            "NON_VERIFICATO"),
        "vincoli": [
            "Calcolo descrittivo: non è proposta di vendita, acquisto o conversione.",
            "Valori indicativi della fotografia, non prezzi eseguibili.",
            "Nessun P/L reale senza movimenti e costo storico verificati.",
            "USD, EUR, EURC e USDC non sommati senza quotazioni e costi attuali.",
            "Ogni alternativa deve considerare fee, spread, liquidità e scelta dell'autore."
        ]
    }



def build(root: Path, now: dt.datetime | None = None) -> dict:
    """Compose with explicit stale flags. No external calls, writes or auto-approval."""
    now = now or dt.datetime.now(UTC)
    if now.tzinfo is None:
        raise PacketError("Ora senza timezone")
    now = now.astimezone(UTC)
    portfolio = read_json(root, "portafoglio.json")
    report = read_json(root, "ultimo_report.json")
    snapshot = read_json(root, "ultima_rilevazione.json")
    dossier = read_json(root, "dossier_multifonte.json")
    r_time = when(report.get("rilevazione_utc"), "report")
    s_time = when(snapshot.get("rilevazione_utc"), "mercato")
    if r_time != s_time:
        raise PacketError("Report e mercato da acquisizioni differenti")
    d_time = when(dossier.get("kraken_istantanea_utc"), "dossier")
    dossier_fresh = d_time == s_time
    balance_date = portfolio.get("data_ora_saldo_privato_utc")
    balance = when(balance_date, "saldo") if balance_date else None
    status_market = source_status(s_time, now)
    status_saldo = source_status(balance, now) if balance else {"stato": "ORIGINE_SCONOSCIUTA", "eta_minuti": None}
    if not str(portfolio.get("fonte_quantita") or "").startswith("Kraken BalanceEx API privata SOLA LETTURA, "):
        status_saldo = {"stato": "ORIGINE_SCONOSCIUTA", "eta_minuti": None}
    if balance and balance > now + dt.timedelta(minutes=2):
        status_saldo = {"stato": "OROLOGIO_INCOERENTE", "eta_minuti": None}
    four_rows = four_tf_evidence(portfolio, report, dossier, snapshot['rilevazione_utc'])
    positions = brief_positions(portfolio, report, snapshot, dossier,
                                dossier_fresh, four_rows=four_rows, now=now)
    cash = cash_balances(portfolio, report)
    # Full original JSON identity (cost basis, available balances, metadata):
    # same canonical SHA256 domain used by decision_desk.output(). Legacy
    # packets without this optional field remain readable, but unattributable.
    wallet_sha = portfolio_identity(portfolio)
    if wallet_sha is None:
        raise PacketError("Identità completa del portafoglio non verificabile")
    reported_sha = report.get("fotografia_portafoglio_sha256")
    if reported_sha is not None and reported_sha != wallet_sha:
        raise PacketError("Portafoglio originario e report discordanti")
    incomplete = any(x["prezzo_eur"] is None for x in positions) or any(x["quantita_spot"] is None for x in positions)
    total = amount(report.get("totale_stimato_eur"), "totale_stimato_eur")
    valued_sum = sum((Decimal(x["valore_eur"]) for x in positions if x["valore_eur"] is not None), Decimal(0))
    has_valuation = any(x["valore_eur"] is not None for x in positions)
    state = report.get("stato_totale")
    if state == "COMPLETO" and (incomplete or not has_valuation or
                                bool(report.get("totale_parziale"))):
        raise PacketError("COMPLETO dichiarato con posizioni incomplete")
    # D1/D2: no valued positions means no total (null), not a fictional zero.
    if total is None:
        if has_valuation or state == "COMPLETO":
            raise PacketError("Totale stimato mancante con posizioni valorizzate")
    elif not has_valuation and positions:
        raise PacketError("Totale numerico senza posizioni valorizzate")
    elif abs(valued_sum - Decimal(total)) > Decimal("0.01"):
        raise PacketError("Totale stimato non coincide con posizioni")
    book_for_gpt = book_150_per_gpt(
        dossier, positions, wallet_sha, snapshot["rilevazione_utc"], now)
    return {"schema": SCHEMA, "tipo": "PACCHETTO_PATRIMONIALE_PRIVATO",
            "generato_utc": now.isoformat(timespec="seconds"),
            "rilevazione_kdd_utc": s_time.isoformat(timespec="seconds"),
            "timestamp_mercato_semantica": "ora di composizione KDD, non ora nativa Kraken",
            "mercato": status_market,
            "saldo": {"ultima_acquisizione_utc": balance.isoformat(timespec="seconds") if balance else None,
                      "stato": status_saldo,
                      "tentativo": str(report.get("saldo_stato", {}).get("ultimo_tentativo", "NON_DOCUMENTATO"))[:60]
                      if isinstance(report.get("saldo_stato"), dict) else "NON_DOCUMENTATO"},
            "dossier": {"coerente_con_mercato": dossier_fresh,
                        "stato": "UTILIZZABILE_CON_LIMITI" if dossier_fresh else "RILEVAZIONE_DIFFERENTE_NON_ATTRIBUIRE_LIVELLI"},
            "patrimonio": {"posizioni": positions, "liquidita_spot": cash,
                           "book_pubblico_150": book_for_gpt,
                           "quadro_economico_per_gpt": quadro_economico_per_gpt(
                               positions, cash, total,
                               mercato_stato=status_market["stato"],
                               saldo_stato=status_saldo["stato"]),
                           "fotografia_portafoglio_sha256": wallet_sha,
                           "totale_stimato_eur_senza_cash": total,
                           "totale_parziale": bool(report.get("totale_parziale")) or incomplete,
                           "stato_totale": report.get("stato_totale", "NON_VERIFICATO"),
                           "n_posizioni": len(positions)},
            "scenario_mercato_kdd": str(report.get("mercato", "NON_DETERMINATO"))[:300],
            "opportunita_esterne_scanner": public_shortlist(snapshot),
            "nessun_ordine": True,
            "richiesta_gpt": "Valuta prima TUTTE le posizioni possedute; per ognuna mantenere/incrementare/alleggerire/uscire/ruotare e alternative, con dati e limiti. Solo poi confronta opportunita esterne. Non inventare prezzi, notizie, commissioni, performance o esecuzioni; ricerca fonti attuali indipendenti e proponi opzioni all'autore, mai ordini automatici.",
            "limiti": ["Prototipo G0 locale: nessun trasferimento a Drive o chat senza consenso dell'autore.",
                      "Prezzi indicativi; saldi e mercato hanno orari indipendenti.",
                      "P/L nullo non significa pareggio: costo storico non attestato.",
                      "Dati vecchi non sono dati attuali alla lettura GPT: rivaluta freschezza.",
                      "La copertura 4TF e la disponibilita reale sono indicate per posizione; non attribuire dati ad altre coppie."]}


def write_private(packet: dict, target: Path | None = None) -> None:
    """Explicit opt-in; target must be the sole app-private canonical location."""
    if target is None:
        target = PRIVATE_OUTPUT
    if target != PRIVATE_OUTPUT:
        raise PacketError("Destinazione privata non autorizzata")
    folder = target.parent
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if folder.is_symlink() or target.is_symlink():
        raise PacketError("Percorso non regolare")
    if target.exists() and not target.is_file():
        raise PacketError("Destinazione non regolare")
    fd, tmp = tempfile.mkstemp(prefix=".wallet_gpt_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(packet, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None):
    parser = argparse.ArgumentParser(description="KDD: ispezione patrimoniale G0 in staging privato; nessuna pubblicazione")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--write-private", action="store_true", help="crea solo un file privato 0600, non esporta")
    args = parser.parse_args(argv)
    try:
        packet = build(args.source_dir)
        if args.write_private:
            write_private(packet)
    except PacketError as exc:
        print("STOP G0:", str(exc))
        return 1
    print("KDD WALLET G0: OK | posizioni valutate:", packet["patrimonio"]["n_posizioni"],
          "| mercato:", packet["mercato"]["stato"],
          "| saldo:", packet["saldo"]["stato"]["stato"],
          "| dossier:", packet["dossier"]["stato"],
          "| output:", "PRIVATO, NON SINCRONIZZATO" if args.write_private else "NESSUNO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
