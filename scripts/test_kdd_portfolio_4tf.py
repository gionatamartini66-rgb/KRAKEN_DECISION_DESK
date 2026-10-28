"""PR21 four timeframe financial invariants; no real private data/network."""
import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import decision_desk as desk
import dossier_trade as dossier
import patrimonio_4tf as wallet_tf
import grafico_4h as charts
import kdd_wallet_packet_g0 as packet

UTC=dt.timezone.utc
NOW=dt.datetime(2026,10,28,17,31,tzinfo=UTC)


def candles(frame, *, now=NOW, older=0):
    seconds=charts.TIMEFRAMES[frame][0]*60
    last=(int(now.timestamp())//seconds-1)*seconds-older*seconds
    rows=[]
    for i in range(71):
        timestamp=last-(70-i)*seconds
        base=100.0+(i%5)*0.01
        rows.append([timestamp,str(base),str(base+.1),str(base-.1),str(base+.03),str(base+.02),'19',0])
    # Last is always uncommitted in Kraken OHLC contract; original parser discards it.
    rows.append([last+seconds,'100','100.2','99.8','100.1','100.0','12',0])
    return rows


def catalogue(tokens, alt_btc=True):
    raw={}
    for token in tokens:
        base='XBT' if token=='BTC' else token
        key='PAIR'+token
        quote='USD' if token=='ALT' else 'EUR'
        raw[key]={'status':'online','wsname':base+'/'+quote,
                  'altname':'ALT'+token}
    return raw


def positions(tokens):
    return [{'token':t,'quantita':'2','costo_medio_eur':None} for t in tokens]


class PortfolioFourTFTests(unittest.TestCase):
    def setUp(self):
        self.now=NOW
        self.rootctx=tempfile.TemporaryDirectory()
        self.addCleanup(self.rootctx.cleanup)
        self.root=pathlib.Path(self.rootctx.name)

    def source(self,tokens):
        return {'rilevazione_utc':self.now.isoformat(timespec='seconds'),
                'markets':{t:{'pair':('XBT/EUR' if t=='BTC' else t+'/EUR'),
                              'pair_key':'PAIR'+t,'prezzo_eur':100,
                              'var_oggi_utc_pct':0,'volume_24h_eur_stimato':1e6,
                              'spread_pct':0.1} for t in tokens if t!='ALT'},
                'trends':{},'schede_v02':[],'feed':[], 'problemi_feed':[]}

    def net(self, *args, mismatch=None, stale_frame=None, missing=None, **kwargs):
        endpoint=args[0]
        if endpoint!='OHLC':
            raise AssertionError('Unexpected public API '+endpoint)
        key=kwargs['pair']
        frame={15:'15m',60:'1h',240:'4h',1440:'1d'}[kwargs['interval']]
        if missing == (key,frame):
            raise ConnectionError('synthetic Kraken offline')
        return {(mismatch if mismatch else key):candles(frame,older=2 if stale_frame==(key,frame) else 0),'last':0}

    def test_01_all_wallet_rows_and_four_real_timeframes(self):
        names=['BTC','ETH','ADA','SOL','LINK','DOT','UNI','ATOM','AVAX','NEAR','AAVE']
        data=wallet_tf.collect({'posizioni':positions(names)},self.source(names),
              asset_pairs=catalogue(names), fetch=self.net, now=self.now,
              pause=lambda _:None)
        self.assertEqual(len(data['posizioni']),11)
        self.assertEqual(data['richieste_ohlc'],44)
        for row in data['posizioni']:
            self.assertEqual(row['stato'],'COMPLETO')
            self.assertEqual(len(row['timeframe']),4)
            for tf,seconds in [('15m',900),('1H',3600),('4H',14400),('1D',86400)]:
                frame=row['timeframe'][tf]
                self.assertEqual(frame['stato'],'AGGIORNATO')
                self.assertEqual(frame['pair_key'],row['pair_key'])
                self.assertEqual(frame['candele'],71)
                self.assertEqual(frame['ultima_candela_ohlcv_chiusa']['time']+seconds,
                                 int(dt.datetime.fromisoformat(frame['chiusura_utc']).timestamp()))
                self.assertTrue(frame['ema20'] and frame['ema50'])
                self.assertEqual(len(frame['serie_ohlcv_chiuse']),71)
        self.assertEqual(data['posizioni'][0]['asset_base'],'XBT')
        self.assertEqual(data['posizioni'][0]['token'],'BTC')

    def test_02_verified_usd_alternative_no_fake_eur(self):
        result=wallet_tf.collect({'posizioni':positions(['ALT'])}, self.source(['ALT']),
              asset_pairs=catalogue(['ALT']),fetch=self.net,now=self.now,pause=lambda _:None)
        row=result['posizioni'][0]
        self.assertEqual(row['coppia'],'ALT/USD')
        self.assertEqual(row['valuta_quotazione'],'USD')
        self.assertEqual(row['stato'],'COMPLETO')
        self.assertNotIn('prezzo_eur',row)

    def test_03_mismatched_rest_response_does_not_reassign_candles(self):
        result=wallet_tf.collect({'posizioni':positions(['BTC'])},self.source(['BTC']),
            asset_pairs=catalogue(['BTC']),fetch=lambda *a,**k:self.net(*a,mismatch='NOT_BTC',**k),
            now=self.now,pause=lambda _:None)
        self.assertEqual(result['posizioni'][0]['stato'],'PARZIALE')
        self.assertEqual({f['stato'] for f in result['posizioni'][0]['timeframe'].values()},
                         {'NON_DISPONIBILE'})

    def test_04_partial_stale_and_failed_timeframes(self):
        def partial(*a,**kw):
            if kw['interval']==15:
                return self.net(*a,stale_frame=(kw['pair'],'15m'),**kw)
            if kw['interval']==60:
                raise ConnectionError('offline')
            return self.net(*a,**kw)
        result=wallet_tf.collect({'posizioni':positions(['BTC'])},self.source(['BTC']),
                                 asset_pairs=catalogue(['BTC']),fetch=partial,now=self.now,
                                 pause=lambda _:None)
        rows=result['posizioni'][0]['timeframe']
        self.assertEqual(rows['15m']['stato'],'SCADUTO')
        self.assertEqual(rows['1H']['stato'],'NON_DISPONIBILE')
        self.assertEqual(rows['4H']['stato'],'AGGIORNATO')
        self.assertEqual(rows['1D']['stato'],'AGGIORNATO')

    def test_05_budget_deferred_never_drops_wallet_rows(self):
        names=['BTC','ETH','ADA','SOL','LINK','DOT','UNI','ATOM','AVAX','NEAR','AAVE']
        result=wallet_tf.collect({'posizioni':positions(names)},self.source(names),
             asset_pairs=catalogue(names),fetch=self.net,now=self.now,
             max_queries=10,pause=lambda _:None)
        self.assertEqual(len(result['posizioni']),len(names))
        self.assertEqual(result['richieste_ohlc'],10)
        self.assertTrue(any(f['stato']=='RINVIATO_BUDGET'
                            for row in result['posizioni'] for f in row['timeframe'].values()))

    def test_06_ambiguous_or_invalid_token_cannot_claim_ohlc(self):
        pairs=catalogue(['BTC'])
        pairs['OTHER']={'status':'online','wsname':'XBT/EUR','altname':'OTHERALT'}
        result=wallet_tf.collect({'posizioni':[{'token':'BTC','quantita':'2'},
                                                {'token':'BTC','quantita':'3'},
                                                {'token':None,'quantita':'2'},
                                                'malformed']},
                                 self.source(['BTC']),asset_pairs=pairs,fetch=self.net,
                                 now=self.now,pause=lambda _:None)
        self.assertEqual(len(result['posizioni']),4)
        self.assertEqual(result['richieste_ohlc'],0)
        self.assertEqual(result['posizioni'][0]['stato'],'IDENTITA_DUPLICATA')
        self.assertEqual(result['posizioni'][2]['stato'],'IDENTITA_NON_VALIDA')
        self.assertEqual(result['posizioni'][3]['stato'],'IDENTITA_NON_VALIDA')

    def test_07_full_original_dossier_to_private_gpt_packet(self):
        tokens=['BTC','ETH','SOL']
        source=self.source(tokens)
        wallet={'posizioni':positions(tokens)}
        (self.root/'portafoglio.json').write_text(json.dumps(wallet))
        (self.root/'ultima_rilevazione.json').write_text(json.dumps(source))
        with mock.patch.object(desk,'DIR',self.root),\
             mock.patch.object(desk,'NOW',return_value=self.now),\
             mock.patch.object(dossier,'recupera_4h',return_value={}),\
             mock.patch.object(dossier,'global_context',return_value={}),\
             mock.patch.object(dossier,'derivatives_context',return_value={}),\
             mock.patch.object(dossier.time,'sleep'),\
             mock.patch.object(desk,'kraken',side_effect=self.net),\
             mock.patch.object(desk.piano_gpt,'load',return_value=None),\
             mock.patch('verifica_piani.archivia_piano',return_value=None):
            status=desk.prepara_dossier_aggiornamento(source,asset_pairs=catalogue(tokens))
            desk.output(source)
            self.assertEqual(status['copertura_patrimonio_4tf']['completate'],len(tokens))
        dossier_raw=json.loads((self.root/'dossier_multifonte.json').read_text())
        report=json.loads((self.root/'ultimo_report.json').read_text())
        self.assertEqual(dossier_raw['schema'],3)
        self.assertEqual(len(dossier_raw['patrimonio_4tf']['posizioni']),len(tokens))
        self.assertEqual(report['fotografia_portafoglio_sha256'],
                         dossier_raw['fotografia_portafoglio_sha256'])
        result=packet.build(self.root,now=self.now)
        self.assertEqual(len(result['patrimonio']['posizioni']),len(tokens))
        for position in result['patrimonio']['posizioni']:
            self.assertEqual(position['analisi_4tf']['stato'],'COMPLETO')
            self.assertEqual(len(position['analisi_4tf']['timeframe']),4)
            self.assertEqual(position['analisi_4tf']['timeframe']['15m']['stato'],'AGGIORNATO')
        self.assertIsNone(result['patrimonio']['posizioni'][0]['pl_indicativo_eur'])
        raw=json.dumps(result,allow_nan=False)
        for forbidden in ('t0_id','t0_sha256','costo_medio_eur','readonly.json'):
            self.assertNotIn(forbidden,raw)
        dossier_raw['patrimonio_4tf']['rilevazione_kraken_utc']='2001-01-01T00:00:00Z'
        (self.root/'dossier_multifonte.json').write_text(json.dumps(dossier_raw))
        with self.assertRaises(packet.PacketError):
            packet.build(self.root,now=self.now)

    def test_09_invalid_and_duplicate_wallet_rows_remain_packet_visible(self):
        tokens=['BTC','BTC',None]
        wallet={'posizioni':[{'token':'BTC','quantita':'2'},
                              {'token':'BTC','quantita':'3'},
                              {'token':None,'quantita':'2'}]}
        source=self.source(['BTC'])
        four=wallet_tf.collect(wallet,source,asset_pairs=catalogue(['BTC']),
                               fetch=self.net,now=self.now,pause=lambda _:None)
        report=desk.build_report(source,wallet,{}, {},[])
        report.update(rilevazione_utc=source['rilevazione_utc'],
                      fotografia_portafoglio_sha256=four['portafoglio_sha256'])
        dossier_raw={'schema':3,'kraken_istantanea_utc':source['rilevazione_utc'],
                     'fotografia_portafoglio_sha256':four['portafoglio_sha256'],
                     'patrimonio_4tf':four}
        for name,obj in [('portafoglio.json',wallet),('ultimo_report.json',report),
                         ('dossier_multifonte.json',dossier_raw),
                         ('ultima_rilevazione.json',source)]:
            (self.root/name).write_text(json.dumps(obj))
        pkt=packet.build(self.root,now=self.now)
        rows=pkt['patrimonio']['posizioni']
        self.assertEqual(len(rows),3)
        self.assertTrue(all(x['stato_identita']!='VALIDA' for x in rows))
        self.assertTrue(all(x['valore_eur'] is None for x in rows))
        self.assertTrue(all(x['analisi_4tf']['stato']!='COMPLETO' for x in rows))

    def test_10_packet_rechecks_aged_technical_frames_at_creation(self):
        tokens=['BTC']
        source=self.source(tokens)
        wallet={'posizioni':positions(tokens)}
        (self.root/'portafoglio.json').write_text(json.dumps(wallet))
        (self.root/'ultima_rilevazione.json').write_text(json.dumps(source))
        with mock.patch.object(desk,'DIR',self.root),\
             mock.patch.object(desk,'NOW',return_value=self.now),\
             mock.patch.object(dossier,'recupera_4h',return_value={}),\
             mock.patch.object(dossier,'global_context',return_value={}),\
             mock.patch.object(dossier,'derivatives_context',return_value={}),\
             mock.patch.object(dossier.time,'sleep'),\
             mock.patch.object(desk,'kraken',side_effect=self.net),\
             mock.patch.object(desk.piano_gpt,'load',return_value=None),\
             mock.patch('verifica_piani.archivia_piano',return_value=None):
            desk.prepara_dossier_aggiornamento(source,asset_pairs=catalogue(tokens))
            desk.output(source)
        old=packet.build(self.root,now=self.now)
        late=packet.build(self.root,now=self.now+dt.timedelta(hours=3))
        self.assertEqual(old['patrimonio']['posizioni'][0]['analisi_4tf']['timeframe']['15m']['stato'],
                         'AGGIORNATO')
        self.assertEqual(late['patrimonio']['posizioni'][0]['analisi_4tf']['timeframe']['15m']['stato'],
                         'SCADUTO')
        self.assertEqual(late['mercato']['stato'],'DA_AGGIORNARE')

    def test_11_usd_only_position_reaches_packet_without_eur_total(self):
        source=self.source(['ALT']); wallet={'posizioni':positions(['ALT'])}
        (self.root/'portafoglio.json').write_text(json.dumps(wallet))
        (self.root/'ultima_rilevazione.json').write_text(json.dumps(source))
        with mock.patch.object(desk,'DIR',self.root),\
             mock.patch.object(desk,'NOW',return_value=self.now),\
             mock.patch.object(dossier,'recupera_4h',return_value={}),\
             mock.patch.object(dossier,'global_context',return_value={}),\
             mock.patch.object(dossier,'derivatives_context',return_value={}),\
             mock.patch.object(dossier.time,'sleep'),\
             mock.patch.object(desk,'kraken',side_effect=self.net),\
             mock.patch.object(desk.piano_gpt,'load',return_value=None),\
             mock.patch('verifica_piani.archivia_piano',return_value=None):
            desk.prepara_dossier_aggiornamento(source,asset_pairs=catalogue(['ALT']))
            desk.output(source)
        pkt=packet.build(self.root,now=self.now)
        self.assertIsNone(pkt['patrimonio']['totale_stimato_eur_senza_cash'])
        self.assertEqual(pkt['patrimonio']['stato_totale'],'NON_DISPONIBILE')
        row=pkt['patrimonio']['posizioni'][0]
        self.assertEqual(row['analisi_4tf']['coppia'],'ALT/USD')
        self.assertEqual(row['analisi_4tf']['timeframe']['1H']['stato'],'AGGIORNATO')
        self.assertIsNone(row['prezzo_eur'])

    def test_12_tampered_ohlc_and_snapshot_rejected_by_packet(self):
        source=self.source(['BTC']);wallet={'posizioni':positions(['BTC'])}
        four=wallet_tf.collect(wallet,source,asset_pairs=catalogue(['BTC']),
                               fetch=self.net,now=self.now,pause=lambda _:None)
        report=desk.build_report(source,wallet,{}, {},[])
        report['fotografia_portafoglio_sha256']=four['portafoglio_sha256']
        dossier_doc={'schema':3,'kraken_istantanea_utc':source['rilevazione_utc'],
                     'fotografia_portafoglio_sha256':four['portafoglio_sha256'],
                     'patrimonio_4tf':four}
        for name,obj in [('portafoglio.json',wallet),('ultimo_report.json',report),
                         ('dossier_multifonte.json',dossier_doc),
                         ('ultima_rilevazione.json',source)]:
            (self.root/name).write_text(json.dumps(obj))
        packet.build(self.root,now=self.now)
        frame=four['posizioni'][0]['timeframe']['1H']
        frame['serie_ohlcv_chiuse'][10]['time']+=1
        (self.root/'dossier_multifonte.json').write_text(json.dumps(dossier_doc))
        with self.assertRaisesRegex(packet.PacketError,'Lacuna|sovrapposizione'):
            packet.build(self.root,now=self.now)

    def test_13_invalid_quantity_remains_visible_with_no_fictitious_value(self):
        source=self.source(['BTC'])
        wallet={'posizioni':[{'token':'BTC','quantita':'NaN','costo_medio_eur':None}]}
        four=wallet_tf.collect(wallet,source,asset_pairs=catalogue(['BTC']),
                               fetch=self.net,now=self.now,pause=lambda _:None)
        report=desk.build_report(source,wallet,{}, {},[])
        report['fotografia_portafoglio_sha256']=four['portafoglio_sha256']
        dossier_doc={'schema':3,'kraken_istantanea_utc':source['rilevazione_utc'],
                     'fotografia_portafoglio_sha256':four['portafoglio_sha256'],
                     'patrimonio_4tf':four}
        for name,obj in [('portafoglio.json',wallet),('ultimo_report.json',report),
                         ('dossier_multifonte.json',dossier_doc),
                         ('ultima_rilevazione.json',source)]:
            (self.root/name).write_text(json.dumps(obj))
        result=packet.build(self.root,now=self.now)
        self.assertEqual(len(result['patrimonio']['posizioni']),1)
        row=result['patrimonio']['posizioni'][0]
        self.assertEqual(row['stato_quantita'],'INVALIDA')
        self.assertIsNone(row['quantita_spot'])
        self.assertIsNone(row['valore_eur'])
        self.assertEqual(row['analisi_4tf']['timeframe']['15m']['stato'],'AGGIORNATO')
        self.assertIsNone(result['patrimonio']['totale_stimato_eur_senza_cash'])

    def test_08_real_zero_total_not_guessed_when_eur_missing(self):
        source=self.source(['ALT'])
        portfolio={'posizioni':positions(['ALT'])}
        result=wallet_tf.collect(portfolio,source,asset_pairs=catalogue(['ALT']),
                                 fetch=self.net,now=self.now,pause=lambda _:None)
        self.assertEqual(result['posizioni'][0]['stato'],'COMPLETO')
        # Price conversion deliberately absent in 4TF; D1/D2 report stays null.
        report=desk.build_report(source,portfolio,{}, {},[])
        self.assertIsNone(report['totale_stimato_eur'])
        self.assertEqual(report['stato_totale'],'NON_DISPONIBILE')

if __name__=='__main__':
    unittest.main()
