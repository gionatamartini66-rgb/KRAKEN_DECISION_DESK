import datetime as dt
import json
import pathlib
import tempfile
import unittest
import unittest.mock
import decision_desk as d
import serve
import analisi_v02 as a
import mercati_spot as m
import costi_spot as cs

def fixture_trade_plan():
    """Esempio isolato per i test: NON leggere mai il piano pubblicato."""
    return {
        'autore':'GPT-6 test','creato_utc':'2026-10-18T08:20:00+00:00',
        'snapshot_kraken_utc':'2026-10-18T08:15:00+00:00',
        'scade_utc':'2026-10-18T09:30:00+00:00',
        'token':'ICNT','coppia':'ICNT/USD','mercato':'SPOT',
        'stato':'CONDIZIONALE','azione':'Solo prova',
        'tesi':'Test separato dalle scelte dell’utente',
        'condizione_ingresso':'Conferma 15m',
        'condizione_invalidazione':'Sotto minimo',
        'condizione_uscita':'Presa parziale',
        'revisione':'Entro 90 minuti',
        'capitale':'50 EUR ipotetici',
        'alternativa':'Q solo in confronto',
        'contesto_portafoglio':'Sconosciuto',
        'motivi':['Test'], 'rischi':['Test'], 'dati_mancanti':['Saldo'],
        'fonti':[{'nome':'Kraken','url':'https://docs.kraken.com/'}],
        'livelli':{'ingresso':.1985,'stop':.1910,'obiettivo1':.2153}
    }


def fixture_migration():
    """Migrazione interamente sintetica: nessun importo né identità patrimoniale."""
    return {
        'stato': 'DA_RICONCILIARE',
        'migrazione_completata': False,
        'asset_visibili': [
            {'token': 'SIM_PRESENTE', 'quantita_binance_visualizzata': '0.125',
             'accreditato_kraken': None},
            {'token': 'SIM_ATTESA', 'quantita_binance_visualizzata': '2.5',
             'accreditato_kraken': None},
        ],
        'riscontro_portafoglio_kraken_2026_10_19': {
            'visibili_anche_su_kraken': {'SIM_PRESENTE': '0.125'},
            'non_visibile_nella_schermata': ['SIM_ATTESA'],
        },
    }


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.pairs = {
            'XXBTZEUR': {'wsname':'XBT/EUR','status':'online','costmin':'0.5','ordermin':'0.0001'},
            'XSOLEUR': {'wsname':'SOL/EUR','status':'online','costmin':'1','ordermin':'0.01'},
            'DUP': {'wsname':'SOL/USD','status':'online'},
            'OUT': {'wsname':'SUI/EUR','status':'cancel_only'},
        }
        self.t = {
            'XXBTZEUR': {'c':['45000'], 'o':'44000', 'a':['45001'], 'b':['44999'], 'v':['20','100']},
            'XSOLEUR': {'c':['100'], 'o':'90', 'a':['100.05'], 'b':['99.95'], 'v':['50','12000']},
            'DUP': {'c':['130'],'o':'120','a':['130'],'b':['129'],'v':['4','40']},
            'OUT': {'c':['3'],'o':'3','a':['3'],'b':['2.99'],'v':['8','90']}
        }
        self.now=dt.datetime(2026,10,16,12,tzinfo=dt.timezone.utc)
    def test_checkpoint_documentato(self):
        # Sul checkout pubblico manca la configurazione privata. Qui NON
        # inventiamo il checkpoint locale: il test deve eseguirsi sul Samsung.
        if not (d.DIR / 'config.json').is_file():
            self.skipTest('CHECKPOINT LOCALE NON ESEGUITO: config privata assente; prova obbligatoria nello staging Samsung')
        self.assertTrue(d.checkpoint_allineato(),
                        'Checkpoint dei sorgenti/README/config locale incoerente')

    def test_checkpoint_detects_source_tampering_on_isolated_synthetic_files(self):
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'config.json').write_text('{"test":true}',encoding='utf-8')
            source=root/'sintetico.py'
            source.write_text('SIMULATO = True\n',encoding='utf-8')
            with mock.patch.object(d,'DIR',root):
                sig=d.fingerprint_sorgenti()
                (root/'README.md').write_text(
                    '<!-- CHECKPOINT_SORGENTI_SHA256: '+sig+' -->\n',
                    encoding='utf-8')
                self.assertTrue(d.checkpoint_allineato())
                source.write_text('SIMULATO = False\n',encoding='utf-8')
                self.assertFalse(d.checkpoint_allineato())
                source.write_text('SIMULATO = True\n',encoding='utf-8')
                self.assertTrue(d.checkpoint_allineato())
                (root/'config.json').write_text('{"test":false}',encoding='utf-8')
                self.assertFalse(d.checkpoint_allineato())

    def test_widget_age_computed_in_browser(self):
        data={'rilevazione_utc':d.NOW().isoformat(), 'markets':{}, 'trends':{}, 'feed':[], 'problemi_feed':[]}
        report=d.build_report(data, {'posizioni':[]}, {}, {}, [])
        page=d.render(report)
        self.assertIn('id="data-freschezza"', page)
        self.assertIn('Date.now()', page)
        self.assertIn('visibilitychange', page)
        self.assertIn('DATI DA AGGIORNARE', page)
        self.assertNotIn('Dati rilevati da meno di 30 minuti.', page)
        self.assertNotIn("method='post'",page)

    def test_local_refresh_only_in_server_page(self):
        page="<html><h2>1 · Decisioni e posizioni</h2></html>"
        served=serve.with_controls(page)
        self.assertIn("method='post' action='/aggiorna'", served)
        self.assertIn("name='token'", served)
        self.assertIn("↻ Aggiorna dati ora", served)
        self.assertEqual(serve.HOST, '127.0.0.1')
        self.assertNotIn("method='post'",page)

    def test_local_host_only(self):
        self.assertTrue(serve.host_valido('127.0.0.1:8765'))
        self.assertFalse(serve.host_valido('attacker.test:8765'))
        self.assertFalse(serve.host_valido('localhost:8765'))

    def test_served_page_drops_static_copy_notice(self):
        sample = ("<html><p class='muted'>Questa copia HTML è una fotografia: per ricevere nuovi prezzi apri il "
                  "<a href='http://127.0.0.1:8765/'>cruscotto locale aggiornabile</a> "
                  "(richiede Termux attivo).</p><h2>1 · Decisioni e posizioni</h2></html>")
        result=serve.with_controls(sample)
        self.assertNotIn('Questa copia HTML è una fotografia',result)
        self.assertIn('Aggiorna dati ora',result)

    def test_v02_selection_variety(self):
        def row(token,change,vol,spread):
            return {'token':token,'var_oggi_utc_pct':change,
                    'volume_24h_eur_stimato':vol,'spread_pct':spread,
                    'pair_key':token+'EUR','prezzo_eur':1}
        rows={r['token']:r for r in (
            row('GAIN',11,900000,0.2),row('EARLY',4,1100000,0.1),
            row('FRAGILE',13,25000,3),row('MORE',3,550000,0.1))}
        result=a.choose(rows,{'min_var_oggi_utc_pct':8,'max_var_oggi_utc_pct':20,
                              'volume_24h_min_eur':500000,'spread_massimo_pct':0.8})
        self.assertEqual([v['token'] for v in result],['GAIN','EARLY','FRAGILE'])

    def test_v02_no_liquid_candidates_keeps_contrast(self):
        def row(token,change,vol,spread):
            return {'token':token,'var_oggi_utc_pct':change,
                    'volume_24h_eur_stimato':vol,'spread_pct':spread,
                    'pair_key':token+'EUR','prezzo_eur':1}
        rows={x['token']:x for x in (
            row('GAIN_BAD',11,110000,1.1),row('EARLY_BAD',4,80000,0.3))}
        chosen=a.choose(rows,{},max_items=3)
        self.assertEqual([x['token'] for x in chosen],['GAIN_BAD','EARLY_BAD'])
        self.assertIn('fragile',chosen[1]['categoria'])

    def test_v02_choice_without_liquid_gainer(self):
        def row(token,change,vol,spread):
            return {'token':token,'var_oggi_utc_pct':change,
                    'volume_24h_eur_stimato':vol,'spread_pct':spread,
                    'pair_key':token+'EUR','prezzo_eur':1}
        rows={x['token']:x for x in (row('EARLY',4,800000,0.1),row('FRAG',11,300,6))}
        names=[x['token'] for x in a.choose(rows,{})]
        self.assertEqual(names,['EARLY','FRAG'])

    def test_v02_closed_candle_excludes_ongoing(self):
        now=1_800_000_000
        candles=[[now-3600,1,2,1,'100',1,20],[now,1,2,1,'999',1,20]]
        self.assertEqual(len(a.closed_bars(candles,now,3600)),1)

    def test_v02_momentum_synthetic(self):
        t0=1792000000
        bars=lambda n,sec,ret: [[t0+i*sec,0,0,0,str(100+ret*i),0,'10',1] for i in range(n)]
        # 40 timestamped candles; 'now' well after last
        hour=bars(40,3600,1)
        btc=bars(40,3600,0.1)
        quarter=bars(50,900,0.3)
        m=a.momentum(hour,quarter,btc,now=t0+42*3600)
        self.assertGreater(m['var_4h_pct'], m['btc_4h_pct'])
        self.assertAlmostEqual(m['rapporto_volumi_4h'],1)
        self.assertGreater(m['var_1h_su_15m_pct'],0)

    def test_v02_depth_and_liquidity_flags(self):
        dep={'bids':[['100','100',1]],'asks':[['101','100',1]]}
        m=a.book_metrics(dep)
        self.assertGreater(m['spread_book_pct'],0.8)
        r={'token':'EX','volume_24h_eur_stimato':30000,'spread_pct':2,
           'prezzo_eur':100,'var_oggi_utc_pct':12}
        feats={'var_4h_pct':2,'forza_relativa_4h_punti':1,'var_1h_pct':1,
               'var_1h_su_15m_pct':1,'rapporto_volumi_4h':1.5}
        out=a.evaluate(r,'Gainer',feats,m)
        self.assertEqual(out['esito'],'MOVIMENTO FRAGILE')

    def test_v02_setup_is_not_buy_order(self):
        dep={'spread_book_pct':0.05,'profondita_bid10_eur':20000,
             'profondita_ask10_eur':15000,'imbalance10':0.1}
        r={'token':'GOOD','volume_24h_eur_stimato':800000,'spread_pct':0.1,
           'prezzo_eur':5,'var_oggi_utc_pct':6}
        feats={'var_4h_pct':2,'forza_relativa_4h_punti':0.9,'var_1h_pct':1,
               'var_1h_su_15m_pct':1,'rapporto_volumi_4h':1.6}
        out=a.evaluate(r,'Primo movimento',feats,dep)
        self.assertEqual(out['esito'],'SETUP DA ESAMINARE ORA')
        self.assertIn('senza ordine automatico',out['sintesi'])

    def test_multiquote_real_fx_not_usdc_peg(self):
        pairs={
            'fxeurusd':{'wsname':'EUR/USD','status':'online'},
            'fxusdc':{'wsname':'USDC/EUR','status':'online'},
            'aae':{'wsname':'AAA/EUR','status':'online','costmin':'0.45'},
            'aau':{'wsname':'AAA/USD','status':'online','costmin':'0.5'},
            'aac':{'wsname':'AAA/USDC','status':'online','costmin':'0.5'},
            'usdt':{'wsname':'AAA/USDT','status':'online'},
            'bad':{'wsname':'BBB/USD','status':'cancel_only'},
        }
        def ticker(price, open_, vol, bid=None, ask=None):
            return {'c':[str(price)],'o':str(open_), 'v':['1',str(vol)],
                    'b':[str(bid or price*0.999)],'a':[str(ask or price*1.001)]}
        data={'fxeurusd':ticker(1.25,1.25,1000000),
              'fxusdc':ticker(0.77,0.77,1000000),
              'aae':ticker(8,7.5,20000),
              'aau':ticker(10,9,100000),
              'aac':ticker(10,9,50000),
              'usdt':ticker(10,9,100000000),
              'bad':ticker(10,9,90000)}
        result,fx=m.assemble(pairs,data)
        self.assertAlmostEqual(fx['USD']['eur'],0.8)
        self.assertAlmostEqual(fx['USDC']['eur'],0.77)
        self.assertEqual(result['AAA']['n_coppie'],3)
        self.assertEqual(result['AAA']['pair'],'AAA/USD')
        self.assertAlmostEqual(result['AAA']['volume_token_kraken_eur_stimato'],
                               160000+800000+385000)
        self.assertNotIn('BBB',result)
        self.assertEqual(set(a['quote'] for a in result['AAA']['alternative']),
                         {'EUR','USD','USDC'})

    def test_multiquote_missing_fx_excludes_quote(self):
        pairs={'px':{'wsname':'ZED/USD','status':'online'},
               'pe':{'wsname':'ZED/EUR','status':'online'}}
        tickers={'px':{'c':['10'],'o':'9','v':['1','100'],
                       'b':['9.9'],'a':['10.1']},
                 'pe':{'c':['8'],'o':'7','v':['1','100'],
                       'b':['7.9'],'a':['8.1']}}
        result,fx=m.assemble(pairs,tickers)
        self.assertNotIn('USD',fx)
        self.assertEqual(result['ZED']['n_coppie'],1)
        self.assertEqual(result['ZED']['quote'],'EUR')

    def test_multiquote_kraken_btc_alias(self):
        pairs={'btc':{'wsname':'XBT/USD','status':'online'},
               'fx':{'wsname':'EUR/USD','status':'online'}}
        t={'btc':{'c':['50000'],'o':'48000','a':['50005'],'b':['49995'],'v':['1','15']},
           'fx':{'c':['1.1'],'o':'1.1','a':['1.11'],'b':['1.09'],'v':['1','30']}}
        result,fx=m.assemble(pairs,t)
        self.assertIn('BTC',result)
        self.assertEqual(result['BTC']['pair'],'XBT/USD')

    def test_multiquote_book_depth_eur_conversion(self):
        dep={'bids':[['10','30',1]],'asks':[['10.1','40',1]]}
        out=a.book_metrics(dep,eur_per_quote=0.8)
        self.assertAlmostEqual(out['profondita_bid10_eur'],240.0)
        self.assertAlmostEqual(out['profondita_ask10_eur'],323.2)
        self.assertGreater(out['spread_book_pct'],0)

    def test_multiquote_report_display(self):
        data={'rilevazione_utc':d.NOW().isoformat(), 'markets':{},'trends':{},
              'feed':[],'problemi_feed':[],
              'n_coppie_multi':450, 'n_token_multi':300,
              'schede_v02':[{'token':'AAA','categoria':'Gainer liquido',
                             'esito':'RIESAME MIRATO','sintesi':'Segnale',
                             'evidenze':[],'criticita':[],
                             'coppia_analisi':'AAA/USD',
                             'volume_coppia_eur_stimato':750000,
                             'volume_token_kraken_eur_stimato':1500000,
                             'alternative':[{'pair':'AAA/EUR','volume_eur_stimato':700000,'spread_pct':0.1}],
                             'indicatori':{},'book':{}}]}
        page=d.render(d.build_report(data,{'posizioni':[]},{},{},[]))
        self.assertIn('Ricerca spot multi-coppia EUR/USD/USDC',page)
        self.assertIn('Coppia analizzata: AAA/USD',page)
        self.assertIn('AAA/EUR',page)
        self.assertIn('Confronta coppie spot Kraken',page)

    def test_single_refresh_and_busy_status(self):
        from threading import Event
        import time
        started, release = Event(), Event()
        def fake_refresh():
            started.set()
            release.wait(2.0)
        try:
            with unittest.mock.patch.object(serve.desk,'refresh', side_effect=fake_refresh):
                self.assertTrue(serve.start_refresh())
                self.assertTrue(started.wait(1.0))
                self.assertEqual(serve.job_snapshot()['stato'],'in_corso')
                self.assertFalse(serve.start_refresh())
                release.set()
                for _ in range(100):
                    if serve.job_snapshot()['stato'] != 'in_corso':
                        break
                    time.sleep(0.01)
                self.assertEqual(serve.job_snapshot()['stato'],'riuscito')
        finally:
            release.set()

    def test_error_status_and_retry(self):
        import time
        def fake_failure():
            raise ConnectionError('simulazione offline')
        with unittest.mock.patch.object(serve.desk,'refresh',side_effect=fake_failure):
            self.assertTrue(serve.start_refresh())
            for _ in range(100):
                if serve.job_snapshot()['stato'] != 'in_corso':
                    break
                time.sleep(0.01)
            self.assertEqual(serve.job_snapshot()['stato'],'errore')
        # La richiesta successiva può essere avviata dopo un errore.
        with unittest.mock.patch.object(serve.desk,'refresh',return_value=None):
            self.assertTrue(serve.start_refresh())
            for _ in range(100):
                if serve.job_snapshot()['stato'] != 'in_corso':
                    break
                time.sleep(0.01)
            self.assertEqual(serve.job_snapshot()['stato'],'riuscito')

    def test_browser_status_poll_and_refresh(self):
        page="<html><h2>1 · Decisioni e posizioni</h2></html>"
        old=serve.job_snapshot()['stato']
        try:
            with serve.STATE_LOCK:
                serve.JOB_STATE['stato']='in_corso'
            served=serve.with_controls(page,'occupato')
            self.assertIn("fetch('/stato'",served)
            self.assertIn("window.location.replace('/?esito=ok')",served)
            self.assertIn('non occorre ripremere',served)
            self.assertIn('disabled',served)
        finally:
            with serve.STATE_LOCK:
                serve.JOB_STATE['stato']=old

    def test_costs_book_buy_sell_and_exhaustion(self):
        book={'bids':[['9.9','100',1]],'asks':[['10.1','100',1]]}
        amount,fee=cs.execute_book(book,'buy',101,0.008)
        self.assertAlmostEqual(amount,9.92)
        self.assertAlmostEqual(fee,0.08)
        quote,fee2=cs.execute_book(book,'sell',amount,0.008)
        self.assertLess(quote,101)
        with self.assertRaises(ValueError):
            cs.execute_book(book,'buy',999999,0.008)

    def test_costs_conversion_bid_ask_direction_and_fees(self):
        book={'bids':[['1.1','10000',1]],'asks':[['1.2','10000',1]]}
        forward=cs.fx_convert(100,'EUR','USD',{'EUR/USD':book},0.002)
        backward=cs.fx_convert(forward[0],'USD','EUR',{'EUR/USD':book},0.002)
        self.assertLess(backward[0],100)
        self.assertEqual(len(forward[1]),1)
        self.assertEqual(len(backward[1]),1)

    def test_costs_full_eur_roundtrip_no_conversion(self):
        book={'bids':[['9.9','10000',1]],'asks':[['10.1','10000',1]]}
        res=cs.simulate('TOK/EUR',book,'EUR',100,
                        {'EUR':1.0,'USD':0.9,'USDC':0.9},{})
        self.assertEqual(res['n_conversioni'],0)
        self.assertGreater(res['costo_roundtrip_eur'],1.6)
        self.assertLess(res['ritorno_eur'],100)
        self.assertGreater(res['fee_stimate_eur'],0)

    def test_costs_compares_wallet_eur_usdc_routes(self):
        fx={'EUR/USD':{'bids':[['1.10','10000',1]],
                       'asks':[['1.11','10000',1]]},
            'USDC/EUR':{'bids':[['0.895','10000',1]],
                        'asks':[['0.898','10000',1]]},
            'USDC/USD':{'bids':[['0.995','10000',1]],
                        'asks':[['0.999','10000',1]]}}
        depth={'TOK/EUR':{'bids':[['9.9','10000',1]],
                          'asks':[['10.1','10000',1]]},
               'TOK/USD':{'bids':[['11','10000',1]],
                          'asks':[['11.12','10000',1]]}}
        rates={'EUR':{'eur':1.0},'USD':{'eur':0.9},'USDC':{'eur':0.896}}
        out=cs.compare_for_token([{'pair':'TOK/EUR'},{'pair':'TOK/USD'}],
                                 depth,fx,rates,100)
        self.assertEqual(len(out),4)
        self.assertTrue(all('costo_roundtrip_eur' in x for x in out))
        self.assertEqual(next(x for x in out if x['valuta_partenza']=='EUR'
                              and x['coppia']=='TOK/EUR')['n_conversioni'],0)
        self.assertEqual(next(x for x in out if x['valuta_partenza']=='USDC'
                              and x['coppia']=='TOK/EUR')['n_conversioni'],2)

    def test_costs_missing_fx_is_missing_not_zero(self):
        tok={'bids':[['9.9','100',1]],'asks':[['10.1','100',1]]}
        result=cs.compare_for_token([{'pair':'TOK/USD'}],{'TOK/USD':tok},{},
                                     {'EUR':{'eur':1},'USD':{'eur':0.9},
                                      'USDC':{'eur':0.9}},100)
        self.assertEqual(len(result),2)
        self.assertTrue(all('errore' in x for x in result))

    def test_costs_html_details_and_fee_source(self):
        data={'rilevazione_utc':d.NOW().isoformat(),'markets':{},'trends':{},
              'schede_v02':[{
                  'token':'EX','categoria':'test','esito':'RIESAME MIRATO',
                  'sintesi':'scenario','criticita':[],'evidenze':[],
                  'coppia_analisi':'EX/EUR','indicatori':{},'book':{},
                  'alternative':[], 'costi_roundtrip':[
                      {'valuta_partenza':'EUR','coppia':'EX/EUR',
                       'importo_eur':100,'costo_roundtrip_eur':2.1,
                       'costo_roundtrip_pct':2.1,'n_conversioni':0,
                       'percorso':['EX/EUR (compra/vendi)']},
                      {'valuta_partenza':'USDC','coppia':'EX/EUR','errore':'Dati assenti'}
                  ]}], 'feed':[], 'problemi_feed':[]}
        page=d.render(d.build_report(data,{'posizioni':[]},{},{},[]))
        self.assertIn('Confronto costi spot',page)
        self.assertIn('Da USDC: simulazione incompleta',page)
        self.assertIn('nessun ordine',page.lower())

    def test_maker_conditional_bid_ask_and_fee(self):
        book={'bids':[['99','100',1]],'asks':[['101','100',1]]}
        qty,fee=cs.execute_passive_conditional(book,'buy',99,0.004)
        self.assertAlmostEqual(qty,0.996)
        self.assertAlmostEqual(fee,0.004)
        proceeds,_=cs.execute_passive_conditional(book,'sell',1,0.004)
        self.assertAlmostEqual(proceeds,101*0.996)

    def test_maker_bad_quote_or_mode_rejected(self):
        with self.assertRaises(ValueError):
            cs.execute_passive_conditional({'bids':[['0','1',0]]},'buy',100,0.004)
        with self.assertRaises(ValueError):
            cs.execute_crypto({},'buy',100,'market-maker',0.008,0.004)

    def test_four_execution_combinations_without_fx(self):
        book={'bids':[['99','500',1]],'asks':[['101','500',1]]}
        result=cs.compare_modes('ABC/EUR',book,'EUR',100,
                                {'EUR':1,'USD':0.9,'USDC':0.9}, {},
                                crypto_fee=0.008,maker_fee=0.004,fx_fee=0.002)
        self.assertEqual([r['scenario'] for r in result],
                         ['taker/taker','maker/maker','maker/taker','taker/maker'])
        self.assertTrue(all('costo_roundtrip_eur' in r for r in result))
        self.assertFalse(result[0]['esecuzione_condizionale'])
        self.assertTrue(all(r['esecuzione_condizionale'] for r in result[1:]))
        # T/T paga spread e fee; il miglior prezzo passivo richiede fill incerto.
        self.assertGreater(result[0]['costo_roundtrip_eur'],result[1]['costo_roundtrip_eur'])

    def test_maker_does_not_invent_fx_path(self):
        book={'bids':[['99','500',1]],'asks':[['101','500',1]]}
        result=cs.compare_modes('ABC/USD',book,'EUR',100,
                                {'EUR':1,'USD':0.9,'USDC':0.9}, {},
                                crypto_fee=0.008,maker_fee=0.004,fx_fee=0.002)
        self.assertTrue(all('errore' in r for r in result))

    def test_maker_render_conditional_not_execution_promise(self):
        data={'rilevazione_utc':d.NOW().isoformat(),'markets':{},'trends':{},
              'schede_v02':[{
                  'token':'EX','categoria':'test','esito':'RIESAME MIRATO',
                  'sintesi':'scenario','criticita':[],'evidenze':[],
                  'coppia_analisi':'EX/EUR','indicatori':{},'book':{},
                  'alternative':[],
                  'costi_roundtrip':[{
                      'valuta_partenza':'EUR','coppia':'EX/EUR',
                      'importo_eur':100,'costo_roundtrip_eur':2,
                      'costo_roundtrip_pct':2,'n_conversioni':0,
                      'percorso':['EX/EUR (compra/vendi)']}],
                  'costi_modalita':[{
                      'valuta_partenza':'EUR','coppia':'EX/EUR',
                      'scenario':'maker/taker','costo_roundtrip_eur':1.2,
                      'costo_roundtrip_pct':1.2,'esecuzione_condizionale':True}]
              }], 'feed':[], 'problemi_feed':[]}
        page=d.render(d.build_report(data,{'posizioni':[]},{},{},[]))
        self.assertIn('Maker, taker e misto: prezzi condizionali',page)
        self.assertIn('Il maker NON è un risparmio garantito',page)
        self.assertIn('maker/taker',page)
        self.assertIn('post-only',page)

    def test_gpt_plan_validation_and_levels(self):
        import piano_gpt as pg
        from copy import deepcopy
        t0="2026-10-18T08:20:00+00:00"
        base=dict(autore="GPT-6",creato_utc=t0,
                  snapshot_kraken_utc="2026-10-18T08:15:00+00:00",
                  scade_utc="2026-10-18T09:30:00+00:00",token="ICNT",
                  coppia="ICNT/USD",mercato="SPOT",stato="CONDIZIONALE",
                  azione="Valutare solo se...",tesi="Prova",
                  condizione_ingresso="Conferma 15m",
                  condizione_invalidazione="Sotto minimo",
                  condizione_uscita="Presa parziale",
                  revisione="Entro 90 minuti",
                  capitale="50 EUR illustrativi",
                  alternativa="Q scartato",
                  contesto_portafoglio="Sconosciuto",
                  motivi=["Test"],rischi=["Stop"],dati_mancanti=["Saldo"],
                  fonti=[{"nome":"Kraken","url":"https://docs.kraken.com/"}],
                  livelli={"ingresso":0.1985,"stop":0.1910,"obiettivo1":0.2153})
        self.assertEqual(pg.validate(base),base)
        result=pg.render_box(base,"2026-10-18T08:15:00+00:00")
        self.assertIn("PRIMA LETTURA · PIANO GPT",result)
        self.assertIn("PIANO SCADUTO",result)
        self.assertIn("stop 0.191",result)
        self.assertIn("Date.now()",result)
        bad=deepcopy(base); bad['livelli']['stop']=.21
        with self.assertRaises(ValueError):pg.validate(bad)
        bad=deepcopy(base); bad['mercato']='FUTURES'
        with self.assertRaises(ValueError):pg.validate(bad)
        bad=deepcopy(base);bad['fonti'][0]['url']='javascript:alert(1)'
        with self.assertRaises(ValueError):pg.validate(bad)
        bad=deepcopy(base);bad['snapshot_kraken_utc']='2026-10-01T08:00:00+00:00'
        with self.assertRaises(ValueError):pg.validate(bad)

    def test_gpt_plan_escapes_html_and_marks_new_snapshot(self):
        import piano_gpt as pg
        injected=fixture_trade_plan()
        injected['tesi']='<script>alert("x")</script>'
        pg.validate(injected)
        view=pg.render_box(injected,"2026-10-18T08:30:00+00:00")
        self.assertNotIn('<script>alert("x")</script>',view)
        self.assertIn('&lt;script&gt;',view)
        self.assertIn('questa analisi GPT NON è stata ricalcolata',view)

    def test_trade_dossier_candle_extremes_closed_only(self):
        import dossier_trade as dtc
        start=1_800_000_000
        samples=[[start+i*900, 10, 11+i*.01, 9-i*.01,
                  10, 10, 100] for i in range(50)]
        samples.append([start+50*900, 10, 999, .001, 10, 10, 100])
        out=dtc.summarize_candles(samples,900,start+50*900+5)
        self.assertEqual(out['ultime_24']['minimo'],9-49*.01)
        self.assertLess(out['ultime_24']['massimo'],20)

    def test_grafico_4h_uses_true_closed_candles_no_indicators_claimed(self):
        import grafico_4h as g
        from unittest import mock
        fake={"creato_utc":"2026-10-20T12:00:00+00:00",
              "grafici_4h":{"SUI":{"stato":"OK","coppia":"SUI/EUR",
                   "serie_ohlcv_chiuse":[
                     {"apertura_ts_utc":1_800_000_000+14400*k,
                      "open":10.0,"high":11.0,"low":9.0,"close":10.2,
                      "volume_base":123.0} for k in range(35)]}}}
        with tempfile.TemporaryDirectory() as folder:
            file=pathlib.Path(folder)/"dossier.json"
            file.write_text(json.dumps(fake))
            with mock.patch.object(g.dt,"datetime",wraps=dt.datetime) as time_cls:
                time_cls.now.return_value=dt.datetime.fromtimestamp(
                    1_800_000_000+14400*40,dt.timezone.utc)
                values=g.data_from_dossier(file)
                self.assertEqual(len(values["candles"]),35)
                self.assertEqual(values["candles"][3]["volume"],123)
                page=g.page_from_dossier(file)
        self.assertIn("lightweight-charts.js",page)
        self.assertIn("CandlestickSeries",page)
        self.assertIn("HistogramSeries",page)
        self.assertIn('"time":1800000000',page)
        self.assertIn("nessun ordine",page)
        self.assertIn("NON sono ancora",page)
        self.assertNotIn("readonly.json",page)
        self.assertIn("TradingView",page)

    def test_graph_real_ema_seed_no_lookahead(self):
        import grafico_4h as g
        candles=[{"time":i*14400,"close":float(i+1)} for i in range(80)]
        e20=g.ema_points(candles,20)
        e50=g.ema_points(candles,50)
        self.assertEqual(len(e20),61)
        self.assertEqual(len(e50),31)
        self.assertEqual(e20[0],{"time":19*14400,"value":10.5})
        self.assertEqual(e50[0],{"time":49*14400,"value":25.5})
        self.assertAlmostEqual(e20[1]["value"],10.5+2/(20+1)*(21-10.5),places=7)
        self.assertEqual(g.ema_points(candles[:25],50),[])
        self.assertEqual(len(g.ema_points(candles[:25],20)),6)

    def test_graph_daily_pivots_complete_previous_utc_day_only(self):
        import grafico_4h as g
        start=int(dt.datetime(2026,10,19,tzinfo=dt.timezone.utc).timestamp())
        prior=[dict(time=start+i*14400,open=10,close=10+i*.1,
                    low=8+i*.1,high=12+i*.1,volume=1) for i in range(6)]
        current=[dict(time=start+86400+i*14400,open=100,close=100,
                      low=1,high=1000,volume=1) for i in range(2)]
        levels=g.daily_pivots(prior+current)
        self.assertEqual(levels["reference_day_utc"],"2026-10-19")
        hi=12.5; lo=8; close=10.5
        pivot=(hi+lo+close)/3
        self.assertAlmostEqual(levels["P"],pivot)
        self.assertAlmostEqual(levels["R1"],2*pivot-lo)
        self.assertAlmostEqual(levels["S1"],2*pivot-hi)
        self.assertAlmostEqual(levels["R2"],pivot+(hi-lo))
        self.assertAlmostEqual(levels["S2"],pivot-(hi-lo))
        self.assertAlmostEqual(levels["R3"],hi+2*(pivot-lo))
        self.assertAlmostEqual(levels["S3"],lo-2*(hi-pivot))
        self.assertIsNone(g.daily_pivots(prior[:-1]+current))
        self.assertIsNone(g.daily_pivots(current))

    def test_graph_structural_levels_need_confirmed_twice(self):
        import grafico_4h as g
        candles=[dict(time=i*14400,open=10.5,close=10.5,
                      high=10.9,low=10.1,volume=1) for i in range(33)]
        for i in (7,17):
            candles[i]["low"]=9.2
        for i in (10,20):
            candles[i]["high"]=11.8
        levels=g.structural_levels(candles)
        self.assertEqual(len(levels["supports"]),1)
        self.assertEqual(len(levels["resistances"]),1)
        self.assertAlmostEqual(levels["supports"][0]["price"],9.2)
        self.assertAlmostEqual(levels["resistances"][0]["price"],11.8)
        self.assertEqual(levels["supports"][0]["touches"],2)
        self.assertEqual(g.structural_levels(candles[:7]),
                         {"supports":[],"resistances":[]})

    def test_graph_indicator_controls_and_no_unjustified_claims(self):
        import grafico_4h as g
        from unittest import mock
        start=1_800_000_000
        sample={"creato_utc":"2026-10-20T12:00:00+00:00",
            "grafici_4h":{"SUI":{"stato":"OK","coppia":"SUI/EUR",
                "serie_ohlcv_chiuse":[
                    {"apertura_ts_utc":start+i*14400,"open":10.0,
                     "high":10.5,"low":9.5,"close":10.0,
                     "volume_base":1.0} for i in range(60)]}}}
        with tempfile.TemporaryDirectory() as folder:
            fp=pathlib.Path(folder)/"dossier.json"
            fp.write_text(json.dumps(sample))
            with mock.patch.object(g.dt,"datetime",wraps=dt.datetime) as time_cls:
                time_cls.now.return_value=dt.datetime.fromtimestamp(
                    start+14400*65,dt.timezone.utc)
                page=g.page_from_dossier(fp)
        self.assertIn("EMA20",page)
        self.assertIn("EMA50",page)
        self.assertIn('id="show-structure"',page)
        self.assertIn('id="show-pivots"',page)
        self.assertIn("createPriceLine",page)
        self.assertIn('"ema20"',page)
        self.assertIn('"ema50"',page)
        self.assertNotIn("readonly.json",page)
        self.assertIn("nessun segnale BUY/SELL",page)

    def test_graph_level_decluttering_preserves_exact_level_data(self):
        import grafico_4h as g
        from unittest import mock
        start=1_800_000_000
        fake={"creato_utc":"2026-10-20T12:00:00+00:00",
              "grafici_4h":{"SUI":{"stato":"OK","coppia":"SUI/EUR",
              "serie_ohlcv_chiuse":[{
                  "apertura_ts_utc":start+i*14400,
                  "open":10.0, "high":11.0, "low":9.0,
                  "close":10.0, "volume_base":123.0} for i in range(60)]}}}
        with tempfile.TemporaryDirectory() as folder:
            file=pathlib.Path(folder)/"dossier.json"
            file.write_text(json.dumps(fake))
            with mock.patch.object(g.dt,"datetime",wraps=dt.datetime) as cls:
                cls.now.return_value=dt.datetime.fromtimestamp(
                    start+14400*70,dt.timezone.utc)
                page=g.page_from_dossier(file)
        self.assertIn("Tutti i livelli e i prezzi esatti",page)
        self.assertIn('id="nearby-summary"',page)
        self.assertIn('id="levels-list"',page)
        # Legenda EMA interna al grafico e sincronizzata coi checkbox.
        self.assertIn('id="price-shell"',page)
        self.assertIn('id="plot-ema-legend"',page)
        self.assertIn('data-ema="20"',page)
        self.assertIn('data-ema="50"',page)
        self.assertIn("indicator.hidden=!visible",page)
        self.assertIn("lastValueVisible:false",page)
        # I livelli S/R espongono solo prezzi numerici, senza nomi nell'asse.
        self.assertIn("axisLabelVisible:showPrice,title:''",page)
        self.assertIn("levelToggle('#show-structure',structural,true,true)",page)
        self.assertIn("priceFormat:{type:'price',precision:5,minMove:0.00001}",page)
        self.assertIn("candleSeries.priceToCoordinate(lastClose)",page)
        self.assertIn("PRICE_LABEL_GAP_PX=30",page)
        self.assertIn("axisLabelVisible:visible",page)
        self.assertIn("subscribeVisibleLogicalRangeChange(scheduleAxisLabels)",page)
        self.assertIn('id="axis-note"',page)
        self.assertIn("levelToggle('#show-pivots',pivotEntries,false)",page)
        self.assertNotIn("title:'Str S",page)
        self.assertNotIn("title:'Str R",page)
        self.assertNotIn("title:'Pivot ",page)
        self.assertIn("tech.structure.supports.slice(0,2)",page)
        self.assertIn("tech.structure.resistances.slice(0,2)",page)
        self.assertIn("pivotNames.map(",page)
        self.assertIn("function withinHalfPercent(lo,hi)",page)
        self.assertIn("399n*(right.mantissa",page)
        self.assertIn("401n*(left.mantissa",page)
        self.assertIn("Nessuna conferma di tenuta o breakout",page)
        self.assertNotIn("readonly.json",page)

    def test_graph_precise_axis_labels_preserve_exact_source_and_no_stale_descriptions(self):
        import grafico_4h as g
        import datetime as dt
        import json, tempfile, pathlib
        from unittest import mock
        start=1_800_000_000
        candles=[{'apertura_ts_utc':start+i*14400,
                  'open':.905,'high':.910,'low':.89,'close':.9061,
                  'volume_base':100+i} for i in range(60)]
        sample={'creato_utc':'2026-10-20T16:30:00+00:00',
                'grafici_4h':{'SUI':{'stato':'OK','coppia':'SUI/EUR',
                    'serie_ohlcv_chiuse':candles}}}
        with tempfile.TemporaryDirectory() as folder:
            f=pathlib.Path(folder)/'dossier.json'
            f.write_text(json.dumps(sample))
            with mock.patch.object(g.dt,'datetime',wraps=dt.datetime) as cls:
                cls.now.return_value=dt.datetime.fromtimestamp(
                    start+70*14400,dt.timezone.utc)
                page=g.page_from_dossier(f)
        self.assertIn("precision:5,minMove:0.00001",page)
        self.assertIn("show-structure",page)
        self.assertIn("priceToCoordinate",page)
        self.assertIn("requestAnimationFrame",page)
        self.assertIn("Tutti i livelli e i prezzi esatti",page)
        self.assertIn('"close":0.9061',page)
        self.assertNotIn("title:'Str S",page)
        self.assertNotIn("title:'Str R",page)
        self.assertNotIn("readonly.json",page)

    def test_chart_inline_javascript_survives_python_html_escaping(self):
        """The Python HTML template must not break embedded JavaScript quotes."""
        import grafico_4h as g
        import datetime as dt
        import json, pathlib, tempfile, re, shutil, subprocess
        from unittest import mock
        start=1_800_000_000
        sample={'creato_utc':'2026-10-20T16:30:00+00:00',
                'grafici_4h':{'SUI':{'stato':'OK','coppia':'SUI/EUR',
                    'serie_ohlcv_chiuse':[
                      {'apertura_ts_utc':start+i*14400,'open':.9,
                       'high':.91,'low':.89,'close':.9,'volume_base':1}
                      for i in range(60)]}}}
        with tempfile.TemporaryDirectory() as folder:
            path=pathlib.Path(folder)/'dossier.json'
            path.write_text(json.dumps(sample))
            with mock.patch.object(g.dt,'datetime',wraps=dt.datetime) as cls:
                cls.now.return_value=dt.datetime.fromtimestamp(
                    start+70*14400,dt.timezone.utc)
                page=g.page_from_dossier(path)
        match=re.search('<script>(.*?)</script>',page,re.S)
        self.assertIsNotNone(match)
        script=match.group(1)
        self.assertIn('axisNote.textContent="S/R sull' + chr(39) + 'asse: prezzi a 5 decimali."',script)
        self.assertNotIn("axisNote.textContent='S/R sull'asse",script)
        # Optional stronger syntax check where a JS parser is installed.
        node=shutil.which('node')
        if node:
            outcome=subprocess.run([node,'--check'],input=script,
                text=True,capture_output=True,timeout=10)
            self.assertEqual(outcome.returncode,0,outcome.stderr)

    def test_timeframes_public_ohlc_are_real_closed_candles(self):
        import grafico_4h as g
        import datetime as dt
        for name, (minutes, label) in g.TIMEFRAMES.items():
            with self.subTest(timeframe=name):
                duration=minutes*60
                beginning=86400*21000
                current=beginning+80*duration
                start=beginning
                raws=[[start+duration*i,"1.0000","1.1000","0.9000",
                       "1.0100","1.0000","123.45",100]
                      for i in range(81)]
                payload={'PAIR':raws, 'last':current}
                now=dt.datetime.fromtimestamp(current+duration//2,dt.timezone.utc)
                result=g.data_from_kraken_ohlc(payload,name,now=now)
                self.assertEqual(result['timeframe'],label)
                self.assertEqual(result['interval_seconds'],duration)
                self.assertEqual(len(result['candles']),80)
                self.assertEqual(result['candles'][-1]['time'],current-duration)
                self.assertTrue(result['closed_at_utc'])
                self.assertEqual(result['candles'][-1]['volume'],123.45)
                self.assertNotIn(current,[row['time'] for row in result['candles']])
                # Missing intervals must fail, never silently interpolate.
                with self.assertRaises(ValueError):
                    g.data_from_kraken_ohlc({'PAIR':raws[:15]+raws[16:],
                                             'last':current},name,now=now)
                broken=[list(r) for r in raws]
                broken[20][2]="0.10"
                with self.assertRaises(ValueError):
                    g.data_from_kraken_ohlc({'PAIR':broken,
                                             'last':current},name,now=now)
        with self.assertRaises(ValueError):
            g.data_from_kraken_ohlc({},'1n')

    def test_timeframe_tabs_fetch_correct_public_intervals(self):
        import grafico_4h as g
        import serve
        import datetime as dt
        from unittest import mock
        # A single public pair in EUR, with a different real period in each case.
        for name, (minutes, label) in g.TIMEFRAMES.items():
            if name == '4h':
                continue
            with self.subTest(frame=name):
                duration=minutes*60
                beginning=86400*21000
                current=beginning+80*duration
                candles=[[beginning+i*duration,'1','1.1','0.9','1','1','5',1]
                         for i in range(81)]
                now=dt.datetime.fromtimestamp(current+duration//2,dt.timezone.utc)
                def fake(endpoint,**kwargs):
                    self.assertEqual(endpoint,'OHLC')
                    self.assertEqual(kwargs,{'pair':'SUIEUR','interval':minutes})
                    return {'SUIEUR':candles,'last':current}
                with mock.patch.object(g.dt,'datetime',wraps=dt.datetime) as clock:
                    clock.now.return_value=now
                    page=serve.load_sui_chart(name,public_kraken=fake)
                self.assertIn('aria-current="page"',' '.join(
                    line for line in page.splitlines() if 'tf='+name in line))
                self.assertIn('Grafico SUI/EUR · '+label,page)
                self.assertIn('Kraken Spot pubblico',page)
                self.assertIn('Tutti i livelli e i prezzi esatti',page)
                self.assertNotIn('Ultime 40',page)
        with self.assertRaises(ValueError):
            serve.load_sui_chart('1n')
        with mock.patch.object(g,'page_from_dossier',return_value='legacy 4h') as existing:
            self.assertEqual(serve.load_sui_chart('4h'),'legacy 4h')
            existing.assert_called_once()

    def test_timeframe_pivots_require_complete_previous_utc_day(self):
        import grafico_4h as g
        import datetime as dt
        start=int(dt.datetime(2026,10,19,tzinfo=dt.timezone.utc).timestamp())
        for sec in (900,3600,14400,86400):
            with self.subTest(seconds=sec):
                n=86400//sec
                bars=[dict(time=start+i*sec,open=10.0,high=11.0,
                           low=9.0,close=10.0,volume=1) for i in range(n)]
                bars.append(dict(time=start+86400,open=12.0,
                                 high=13.0,low=11.0,close=12.0,volume=1))
                result=g.daily_pivots(bars,interval_seconds=sec)
                self.assertIsNotNone(result)
                # With 1D, the last bar at midnight covers the full new day;
                # with intraday data the last bar covers only part of that day.
                expected_day='2026-10-20' if sec == 86400 else '2026-10-19'
                self.assertEqual(result['reference_day_utc'],expected_day)
                if sec < 86400:
                    self.assertIsNone(g.daily_pivots(bars[1:],interval_seconds=sec))
                else:
                    self.assertEqual(
                        g.daily_pivots(bars[1:],interval_seconds=sec)['reference_day_utc'],
                        '2026-10-20')

    def _mtf_fixture(self, now, direction="up"):
        import grafico_4h as g
        frames = {}
        by_label = {"15m": 900, "1H": 3600, "4H": 14400, "1D": 86400}
        for label, seconds in by_label.items():
            expected_end = int((now.timestamp()-120)//seconds)*seconds
            start = expected_end - seconds*65
            bars = []
            for k in range(65):
                close = (0.75 + k*.003 if direction=="up" else 1.15-k*.003)
                bars.append({"time":start+k*seconds,"open":close,
                    "high":close+.012,"low":close-.012,"close":close,
                    "volume":500.0 if k==64 else 250.0})
            frames[label] = {"timeframe":label,"interval_seconds":seconds,
                "observed_utc":now.isoformat(timespec="seconds"),
                "closed_at_utc":dt.datetime.fromtimestamp(
                    expected_end,dt.timezone.utc).isoformat(timespec="seconds"),
                "source":"Kraken Spot test fixture",
                "candles":bars}
        return frames

    def test_mtf_four_real_freshness_bullish_and_bearish(self):
        import grafico_4h as g
        import datetime as dt
        now=dt.datetime(2026,10,21,7,42,tzinfo=dt.timezone.utc)
        rising=g.compare_timeframes(self._mtf_fixture(now),now=now)
        self.assertEqual(rising["stato"],"COMPLETO")
        self.assertEqual(rising["quadro"],"ALLINEAMENTO_RIALZISTA_DESCRITTIVO")
        self.assertEqual([x["timeframe"] for x in rising["timeframe"]],
                         ["15m","1H","4H","1D"])
        self.assertTrue(all(x["stato"]=="AGGIORNATO" for x in rising["timeframe"]))
        self.assertTrue(all(x["volume_vs_media20"]==2 for x in rising["timeframe"]))
        falling=g.compare_timeframes(self._mtf_fixture(now,"down"),now=now)
        self.assertEqual(falling["quadro"],"ALLINEAMENTO_RIBASSISTA_DESCRITTIVO")
        self.assertTrue(all(x["orientamento"]=="PREZZO_SOTTO_EMA20_SOTTO_EMA50"
                            for x in falling["timeframe"]))

    def test_mtf_stale_or_missing_frame_blocks_market_conclusion(self):
        import grafico_4h as g
        import datetime as dt
        now=dt.datetime(2026,10,21,7,42,tzinfo=dt.timezone.utc)
        data=self._mtf_fixture(now)
        data["4H"]["candles"]=data["4H"]["candles"][:-1]
        # The missing last bar is a coherent old dataset, not contradictory metadata.
        data["4H"]["closed_at_utc"]=dt.datetime.fromtimestamp(
            data["4H"]["candles"][-1]["time"]+14400,
            dt.timezone.utc).isoformat(timespec="seconds")
        stale=g.compare_timeframes(data,now=now)
        self.assertEqual(stale["stato"],"PARZIALE")
        self.assertEqual(stale["quadro"],"CONFRONTO_INCOMPLETO")
        self.assertEqual(stale["timeframe"][2]["stato"],"SCADUTO")
        data["1H"]={"errore":"HTTP 503"}
        incomplete=g.compare_timeframes(data,now=now)
        self.assertEqual(incomplete["timeframe"][1]["stato"],"NON_DISPONIBILE")
        self.assertEqual(incomplete["quadro"],"CONFRONTO_INCOMPLETO")
        self.assertNotIn("ALLINEAMENTO_RIALZISTA",str(incomplete))

    def test_mtf_transitions_and_invalid_temporal_data(self):
        import grafico_4h as g
        import datetime as dt
        now=dt.datetime(2026,10,21,7,42,tzinfo=dt.timezone.utc)
        data=self._mtf_fixture(now)
        last=data["15m"]["candles"][-1]
        last.update(open=0.90,high=0.91,low=0.86,close=0.88)
        self.assertEqual(g.compare_timeframes(data,now=now)["quadro"],
                         "CONFIGURAZIONE_MISTA")
        data=self._mtf_fixture(now)
        data["1D"]["observed_utc"]="2026-10-23T00:00:00+00:00"
        invalid=g.compare_timeframes(data,now=now)
        self.assertEqual(invalid["timeframe"][-1]["stato"],"NON_VALIDO")
        self.assertEqual(invalid["stato"],"PARZIALE")
        short=self._mtf_fixture(now)
        short["15m"]["candles"]=short["15m"]["candles"][:30]
        self.assertEqual(g.compare_timeframes(short,now=now)["timeframe"][0]["stato"],
                         "STORICO_INSUFFICIENTE")

    def test_mtf_read_only_sources_partial_failures_and_mobile_render(self):
        import grafico_4h as g
        import serve
        import datetime as dt
        from unittest import mock
        now=dt.datetime(2026,10,21,7,42,tzinfo=dt.timezone.utc)
        frames=self._mtf_fixture(now)
        called=[]
        def fake(endpoint,**kwargs):
            self.assertEqual(endpoint,"OHLC")
            self.assertEqual(kwargs["pair"],"SUIEUR")
            called.append(kwargs["interval"])
            if kwargs["interval"]==60:
                raise OSError("mock offline")
            seconds=kwargs["interval"]*60
            frame_label={15:"15m",240:"4H",1440:"1D"}[kwargs["interval"]]
            bars=frames[frame_label]["candles"]
            records=[[c["time"],str(c["open"]),str(c["high"]),str(c["low"]),
                str(c["close"]),"1",str(c["volume"]),"1"] for c in bars]
            last=records[-1][:]
            last[0]+=seconds
            return {"PAIR":records+[last],"last":last[0]}
        # A stale/missing local dossier cannot influence MTF: all 4
        # timeframes are sourced from public Kraken on demand.
        with mock.patch.object(g,"data_from_dossier",
                               side_effect=AssertionError("No local dossier")):
            summary=serve.load_sui_comparison(public_kraken=fake,now=now)
        self.assertEqual(called,[15,60,240,1440])
        self.assertEqual(summary["stato"],"PARZIALE")
        self.assertEqual(summary["timeframe"][1]["stato"],"NON_DISPONIBILE")
        self.assertEqual(summary["timeframe"][2]["stato"],"AGGIORNATO")
        self.assertEqual(summary["timeframe"][2]["fonte"],
                         "Kraken Spot pubblico /0/public/OHLC")
        page=serve.render_sui_comparison(summary)
        self.assertIn("Confronto SUI/EUR",page)
        self.assertIn("tf=15m",page)
        self.assertIn("tf=1h",page)
        self.assertIn("tf=4h",page)
        self.assertIn("tf=1d",page)
        self.assertIn("CONFRONTO",page.upper())
        self.assertNotIn("readonly.json",page)
        self.assertNotIn("necessario per il 4H",page)
        dashboard=serve.with_controls("<html><h2>1 · Decisioni e posizioni</h2></html>")
        self.assertIn("href='/mercati/spot'",dashboard)
        self.assertNotIn("href='/analisi/sui-mtf'",dashboard)

    def test_mtf_live_4h_missing_close_marks_stale_without_fallback(self):
        import serve
        import datetime as dt
        now=dt.datetime(2026,10,21,8,5,tzinfo=dt.timezone.utc)
        frames=self._mtf_fixture(now)
        def fake(endpoint,**kwargs):
            self.assertEqual(endpoint,"OHLC")
            seconds=kwargs["interval"]*60
            label={15:"15m",60:"1H",240:"4H",1440:"1D"}[kwargs["interval"]]
            bars=frames[label]["candles"]
            if label=="4H":
                bars=bars[:-1]  # Kraken has not supplied the latest 4H close yet
            records=[[c["time"],str(c["open"]),str(c["high"]),str(c["low"]),
                str(c["close"]),"1",str(c["volume"]),"1"] for c in bars]
            # Last row is always uncommitted and will be discarded by parser.
            last=records[-1][:]
            last[0]=int(now.timestamp()//seconds)*seconds
            return {"PAIR":records+[last],"last":last[0]}
        report=serve.load_sui_comparison(public_kraken=fake,now=now)
        self.assertEqual([row["stato"] for row in report["timeframe"]],
                         ["AGGIORNATO","AGGIORNATO","SCADUTO","AGGIORNATO"])
        self.assertEqual(report["quadro"],"CONFRONTO_INCOMPLETO")
        self.assertEqual(report["stato"],"PARZIALE")

    def test_graph_full_pivots_stay_in_payload_when_plot_filters_lines(self):
        import grafico_4h as g
        start=int(dt.datetime(2026,10,19,tzinfo=dt.timezone.utc).timestamp())
        candles=[
            dict(time=start+i*14400,open=10.0,high=11.0,
                 low=9.0,close=10.0,volume=1.0) for i in range(6)
        ]
        candles.append(dict(time=start+6*14400,open=10.0,
                            high=12.0,low=8.0,close=11.0,volume=1.0))
        pivots=g.daily_pivots(candles)
        self.assertEqual(set(pivots),
                         {"reference_day_utc","P","R1","S1","R2","S2","R3","S3"})
        self.assertEqual(g.technical_from_candles(candles)["pivots"],pivots)

    def test_grafico_4h_refuses_partial_and_gapped(self):
        import grafico_4h as g
        from unittest import mock
        raw={"creato_utc":"2026-10-20T12:00:00+00:00",
             "grafici_4h":{"SUI":{"stato":"OK","coppia":"SUI/EUR",
                "serie_ohlcv_chiuse":[
                 {"apertura_ts_utc":1_800_000_000+14400*k,
                  "open":10.0,"high":11.0,"low":9.0,"close":10.2,
                  "volume_base":123.0} for k in range(35)]}}}
        with tempfile.TemporaryDirectory() as folder:
            file=pathlib.Path(folder)/"dossier.json"
            with mock.patch.object(g.dt,"datetime",wraps=dt.datetime) as time_cls:
                time_cls.now.return_value=dt.datetime.fromtimestamp(
                    1_800_000_000+14400*40,dt.timezone.utc)
                raw["grafici_4h"]["SUI"]["serie_ohlcv_chiuse"][9]["apertura_ts_utc"] += 1
                file.write_text(json.dumps(raw))
                with self.assertRaisesRegex(ValueError,"non consecutivi"):
                    g.data_from_dossier(file)
                raw["grafici_4h"]["SUI"]["serie_ohlcv_chiuse"][9]["apertura_ts_utc"] -= 1
                time_cls.now.return_value=dt.datetime.fromtimestamp(
                    1_800_000_000+14400*34+5,dt.timezone.utc)
                file.write_text(json.dumps(raw))
                with self.assertRaisesRegex(ValueError,"non conclusa"):
                    g.data_from_dossier(file)

    def test_graph_is_linked_from_live_mobile_dashboard_not_promised_full(self):
        html=serve.with_controls("<html><h2>1 · Decisioni e posizioni</h2></html>")
        self.assertIn('href=\'/mercati/spot\'',html)
        self.assertNotIn('href=\'/grafico/sui-4h\'',html)
        self.assertIn("Seleziona coppia Kraken Spot · grafici 15m / 1H / 4H / 1D",html)
        self.assertNotIn("EMA 20",html)

    def test_4h_closed_candles_without_last_in_progress(self):
        import dossier_trade as dtc
        start=1_800_000_000
        raw=[[start+k*14400,100,105,95,100+k*.01,100,10]
             for k in range(205)]
        raw[-1]=[start+204*14400,100,999,1,999,999,100000]
        obs=dtc.documenta_4h(raw,start+204*14400+10)
        self.assertEqual(obs["stato"],"OK")
        self.assertEqual(obs["timeframe"],"4H")
        self.assertEqual(obs["n_candele_chiuse_totali"],204)
        self.assertEqual(obs["n_candele_conservate"],200)
        self.assertLess(max(x["high"] for x in obs["serie_ohlcv_chiuse"]),999)
        self.assertTrue(obs["campione_ema50_sufficiente"])
        self.assertEqual(obs["lettura_indicativa"]["ultime_4"]["massimo"],105)

    def test_4h_gap_is_not_interpolated(self):
        import dossier_trade as dtc
        start=1_800_000_000
        raw=[[start+k*14400,100,105,95,100,100,10]
             for k in range(160) if k!=90]
        obs=dtc.documenta_4h(raw,start+160*14400)
        self.assertEqual(obs["stato"],"LACUNE_TEMPORALI")
        self.assertEqual(obs["gap_nell_estratto"],1)
        self.assertFalse(obs["campione_ema50_sufficiente"])

    def test_4h_priority_core_even_when_scanner_has_no_candidates(self):
        import dossier_trade as dtc
        from unittest import mock
        start=1_800_000_000
        raw=[[start+k*14400,100,105,95,100,100,10]
             for k in range(40)]
        source={"markets":{x:{"pair_key":x+"EUR","pair":x+"/EUR"}
                           for x in ("BTC","ETH","SUI","BNB")}}
        with mock.patch.object(dtc.desk,"kraken",return_value={"X":raw}) as api, \
             mock.patch.object(dtc.time,"sleep"):
            out=dtc.recupera_4h(source,[],start+40*14400)
        self.assertEqual(list(out),["BTC","ETH","SUI","BNB"])
        self.assertTrue(all(out[k]["stato"]=="OK" for k in out))
        self.assertEqual(api.call_count,4)
        self.assertTrue(all(x.kwargs["interval"]==240 for x in api.call_args_list))

    def test_gpt_mobile_first_summary_before_details(self):
        import piano_gpt as pg
        plan=fixture_trade_plan()
        pg.validate(plan)
        markup=pg.render_box(plan,plan['snapshot_kraken_utc'])
        self.assertIn('PRIMA LETTURA · PIANO GPT',markup)
        self.assertIn('Condizione:</b>',markup)
        self.assertIn('Convenienza:</b>',markup)
        self.assertIn('Importo:</b>',markup)
        self.assertIn('Riesame:</b>',markup)
        self.assertIn('Apri motivazione e piano completo',markup)
        self.assertLess(markup.index('Convenienza:</b>'),
                        markup.index('Apri motivazione e piano completo'))
        self.assertLess(markup.index('Apri motivazione e piano completo'),
                        markup.index('<b>Tesi:</b>'))
        self.assertEqual(markup.count("id='piano-freschezza'"),1)

    def test_gpt_plan_is_top_of_report(self):
        import piano_gpt as pg
        data={'rilevazione_utc':d.NOW().isoformat(), 'markets':{}, 'trends':{},
              'feed':[],'problemi_feed':[]}
        report=d.build_report(data, {'posizioni':[]}, {}, {}, [])
        report['piano_gpt']=pg.validate(fixture_trade_plan())
        page=d.render(report)
        self.assertIn('PRIMA LETTURA · PIANO GPT',page)
        self.assertLess(page.index('PRIMA LETTURA · PIANO GPT'),
                        page.index('1 · Decisioni e posizioni'))
        self.assertNotIn('name="api_key"',page)

    def test_auto_dossier_links_exact_kraken_snapshot_and_keeps_gpt_plan(self):
        import dossier_trade
        from copy import deepcopy
        data={'rilevazione_utc':'2026-10-18T11:00:00+00:00'}
        dossier={'kraken_istantanea_utc':data['rilevazione_utc'],
                 'creato_utc':'2026-10-18T11:00:20+00:00',
                 'candidati':[{'token':'Q','livelli_15m':{'ultime_4':{}},
                               'livelli_1h':{'ultime_4':{}},
                               'fondamentali_coingecko':{'stato':'non verificati'}}],
                 'fonti_esterne':{'coingecko_global':{'dominanza_btc_pct':60}},
                 'contesto_derivati_btc':{'open-interest':{'ultimo_close':1000},
                                         'cvd':{'ultimo_cvd':100}}}
        saved=[]
        with unittest.mock.patch.object(dossier_trade,'collect',return_value=dossier) as collect, \
             unittest.mock.patch.object(d,'save',side_effect=lambda name,obj:saved.append((name,deepcopy(obj)))):
            status=d.prepara_dossier_aggiornamento(data)
        collect.assert_called_once_with(source=data)
        self.assertEqual(status['stato'],'PARZIALE')
        self.assertIn('Fondamentali non verificati: Q',status['motivi_incompletezza'])
        self.assertEqual(status['rilevazione_kraken_utc'],data['rilevazione_utc'])
        self.assertEqual([x[0] for x in saved],['dossier_stato.json'])
        self.assertFalse(any('piano_gpt' in name for name,_ in saved))

    def test_auto_dossier_failure_never_claims_fresh_data(self):
        import dossier_trade
        data={'rilevazione_utc':'2026-10-18T11:00:00+00:00'}
        with unittest.mock.patch.object(dossier_trade,'collect',side_effect=ConnectionError('offline')), \
             unittest.mock.patch.object(d,'save') as saver:
            state=d.prepara_dossier_aggiornamento(data)
        self.assertEqual(state['stato'],'NON_DISPONIBILE')
        self.assertIn('ConnectionError',state['motivi_incompletezza'][0])
        saver.assert_called_once()

    def test_auto_dossier_status_matches_source_no_false_freshness(self):
        snap='2026-10-18T11:00:00+00:00'
        s0={'stato':'PRONTO_PER_ESAME_GPT','rilevazione_kraken_utc':snap}
        report={'rilevazione_utc':snap}
        with unittest.mock.patch.object(d,'load', side_effect=lambda n,default=None:
                 s0 if n=='dossier_stato.json' else {'kraken_istantanea_utc':snap}):
            # Legacy dossier matches market UTC but has no wallet provenance.
            self.assertEqual(d.stato_dossier_per_report(report)['stato'],
                             'PATRIMONIO_NON_VERIFICABILE')
        with unittest.mock.patch.object(d,'load', side_effect=lambda n,default=None:
                 s0 if n=='dossier_stato.json' else {'kraken_istantanea_utc':'2026-10-18T10:00:00+00:00'}):
            self.assertEqual(d.stato_dossier_per_report(report)['stato'],'NON_ALLINEATO')
        with unittest.mock.patch.object(d,'load', return_value={}):
            self.assertEqual(d.stato_dossier_per_report(report)['stato'],'NON_ALLINEATO')

    def test_btc_futures_excludes_live_hour_and_discloses_coverage(self):
        import dossier_trade as dd
        import time as tm
        from unittest.mock import patch
        start=1800000000
        stamps=[start+3600*i for i in range(7)]
        now=stamps[-1]+1800  # ultima barra IN CORSO
        def fake_fetch(url,timeout=13):
            if 'open-interest' in url:
                info={'result':{'timestamp':stamps,
                      'data':[[str(100+i)]*4 for i in range(7)]},'errors':[]}
            else:
                info={'result':{'timestamp':stamps,'data':{
                      'cvd':[str(i*10) for i in range(7)],
                      'buy_volume':[str(i*2) for i in range(7)],
                      'sell_volume':[str(i) for i in range(7)]}},'errors':[]}
            return json.dumps(info).encode()
        with patch.object(dd.desk,'request',side_effect=fake_fetch),\
             patch.object(dd.time,'sleep'):
            out=dd.derivatives_context(now)
        self.assertFalse(out['open-interest']['ultimo_punto_provvisorio'])
        self.assertEqual(out['open-interest']['ultimo_close'],105.0)
        self.assertFalse(out['cvd']['ultimo_punto_provvisorio'])
        self.assertEqual(out['cvd']['ultimo_cvd'],50.0)
        self.assertEqual(out['cvd']['cvd_4h_fa'],10.0)
        self.assertIn('NON aggregato',out['copertura'])

    def test_history_stop_before_target_not_profit(self):
        import verifica_piani as vp
        import copy
        plan=copy.deepcopy(fixture_trade_plan())
        start=1800000000
        from datetime import datetime,timezone,timedelta
        plan['creato_utc']=datetime.fromtimestamp(start+45,timezone.utc).isoformat()
        plan['snapshot_kraken_utc']=datetime.fromtimestamp(start,timezone.utc).isoformat()
        plan['scade_utc']=datetime.fromtimestamp(start+3600,timezone.utc).isoformat()
        bars=[]
        # Stop and entry level crossed in SAME 15m candle.
        bars.append([start+900,0.202,0.204,0.189,0.190,0,100])
        bars.append([start+1800,0.190,0.220,0.190,0.218,0,120])
        bars.append([start+2700,0.218,0.224,0.216,0.220,0,90])
        out=vp.analyze(plan,bars,start+7200)
        self.assertEqual(out['ordine_eventi'],'INVALIDAZIONE_PRIMA_DEL_TARGET')
        self.assertTrue(out['copertura_completa'])
        self.assertEqual(out['stato'],'COMPLETO')
        self.assertEqual(out['primo_contatto_livelli_utc']['ingresso'],
                         out['primo_contatto_livelli_utc']['stop'])
        self.assertNotIn('profitto',out['ordine_eventi'].lower())
        self.assertIn('NON',out['giudizio'])

    def test_history_incomplete_candles_never_claim_full_outcome(self):
        import verifica_piani as vp
        import copy
        plan=copy.deepcopy(fixture_trade_plan())
        from datetime import datetime,timezone
        start=1800000000
        plan['creato_utc']=datetime.fromtimestamp(start+45,timezone.utc).isoformat()
        plan['snapshot_kraken_utc']=datetime.fromtimestamp(start,timezone.utc).isoformat()
        plan['scade_utc']=datetime.fromtimestamp(start+3600,timezone.utc).isoformat()
        bars=[[start+900,0.2,0.201,0.199,0.2,0,100],
              [start+2700,0.2,0.202,0.198,0.2,0,100]]
        res=vp.analyze(plan,bars,start+7200)
        self.assertFalse(res['copertura_completa'])
        self.assertEqual(res['stato'],'PROVVISORIO')
        self.assertEqual((res['ottenute'],res['attese']),(2,3))

    def test_history_excludes_partial_candle_and_prepublication(self):
        import verifica_piani as vp
        import copy
        from datetime import datetime,timezone
        plan=copy.deepcopy(fixture_trade_plan())
        start=1800000000
        plan['creato_utc']=datetime.fromtimestamp(start+899,timezone.utc).isoformat()
        plan['snapshot_kraken_utc']=datetime.fromtimestamp(start,timezone.utc).isoformat()
        plan['scade_utc']=datetime.fromtimestamp(start+3600,timezone.utc).isoformat()
        bars=[[start,0.2,0.22,0.18,0.2,0,100],
              [start+900,0.2,0.204,0.2,0.202,0,100],
              [start+1800,0.2,0.24,0.17,0.2,0,100],
              [start+2700,0.2,0.2,0.2,0.2,0,100]]
        res=vp.analyze(plan,bars,start+2500)
        self.assertEqual(res['ottenute'],1)
        self.assertIsNone(res['primo_contatto_livelli_utc']['stop'])
        self.assertIsNone(res['primo_contatto_livelli_utc']['obiettivo1'])
        self.assertTrue(res['copertura_completa']) # all eligible closed bars present

    def test_history_archives_only_verified_public_observation(self):
        import verifica_piani as vp
        import tempfile,copy,unittest.mock
        from pathlib import Path
        from datetime import datetime,timezone
        plan=copy.deepcopy(fixture_trade_plan())
        start=1800000000
        plan['creato_utc']=datetime.fromtimestamp(start+45,timezone.utc).isoformat()
        plan['snapshot_kraken_utc']=datetime.fromtimestamp(start,timezone.utc).isoformat()
        plan['scade_utc']=datetime.fromtimestamp(start+2700,timezone.utc).isoformat()
        bars=[[start+900,0.2,0.2,0.2,0.2,0,10],
              [start+1800,0.2,0.2,0.2,0.2,0,10]]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with unittest.mock.patch.object(vp,'PLANS',root/'plans'), \
                 unittest.mock.patch.object(vp,'LOG',root/'record.jsonl'), \
                 unittest.mock.patch.object(vp.desk,'kraken',return_value={'ICNTUSD':bars}) as rest:
                first=vp.check(plan,now=start+3600)
                second=vp.check(plan,now=start+3700)
                self.assertEqual(first['stato'],'COMPLETO')
                self.assertEqual(second['hash_piano'],first['hash_piano'])
                self.assertEqual(len((root/'record.jsonl').read_text().splitlines()),1)
                self.assertEqual(len(list((root/'plans').glob('*.json'))),1)
                rest.assert_called_once()
        self.assertNotIn('quantita',first)

    def test_history_html_is_nontrading_and_escaped(self):
        import verifica_piani as vp
        plan=fixture_trade_plan()
        row={'hash_piano':vp.plan_hash(plan),
             'ordine_eventi':'INVALIDAZIONE_PRIMA_DEL_TARGET',
             'stato':'COMPLETO','copertura_completa':True,'ottenute':11,'attese':11,
             'primo_contatto_livelli_utc':{'stop':'2026-10-18T09:45:00+00:00',
                                             'obiettivo1':'2026-10-18T10:30:00+00:00'},
             'minimo_osservato':0.1814,'massimo_osservato':0.2262}
        out=vp.render_summary(row,plan)
        self.assertIn('INVALIDAZIONE',out.upper())
        self.assertIn('NON rende riuscito',out)
        self.assertIn('Nessun ordine eseguito',out)
        self.assertEqual(vp.render_summary(dict(row,hash_piano='wrong'),plan),'')
        row['minimo_osservato']='<script>bad</script>'
        self.assertNotIn('<script>bad</script>',vp.render_summary(row,plan))

    def test_multiple_plans_preserve_old_even_if_current_is_replaced(self):
        import verifica_piani as vp
        import piano_gpt as pg
        import copy, tempfile
        from pathlib import Path
        old=copy.deepcopy(fixture_trade_plan())
        new=copy.deepcopy(old)
        new['token']='HBAR';new['coppia']='HBAR/USD';new['azione']='Monitoraggio HBAR'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            # Synthetic 18/10 plans must not age out of Kraken's 720-bar window
            # as real calendar days pass. Keep the production expiry logic intact.
            with unittest.mock.patch.object(vp.desk,'NOW',
                    return_value=dt.datetime(2026,10,18,8,40,tzinfo=dt.timezone.utc)), \
                 unittest.mock.patch.object(vp,'PLANS',root/'plans'), \
                 unittest.mock.patch.object(vp,'LOG',root/'observations.jsonl'), \
                 unittest.mock.patch.object(pg,'load',return_value=new), \
                 unittest.mock.patch.object(vp.desk,'save') as store, \
                 unittest.mock.patch.object(vp,'check',return_value={
                      'stato':'PROVVISORIO','copertura_completa':True}) as observe:
                oldhash=vp.archivia_piano(old)
                result=vp.check_all(max_queries=2)
                newhash=vp.plan_hash(new)
                self.assertNotEqual(oldhash,newhash)
                self.assertEqual(len(list((root/'plans').glob('*.json'))),2)
                self.assertEqual(result['storico']['piani_totali'],2)
                self.assertEqual(observe.call_count,2)
                self.assertEqual({x['token'] for x in result['storico']['piani']},{'ICNT','HBAR'})
                self.assertEqual(vp.plan_hash(json.loads((root/'plans'/(oldhash+'.json')).read_text())),oldhash)
                self.assertEqual(result['corrente']['stato'],'PROVVISORIO')
                self.assertEqual(store.call_count,2)

    def test_multiple_plans_budget_does_not_discard_unchecked_history(self):
        import verifica_piani as vp
        import piano_gpt as pg
        import copy,tempfile
        from pathlib import Path
        previous=copy.deepcopy(fixture_trade_plan())
        current=copy.deepcopy(previous)
        current['token']='HBAR';current['coppia']='HBAR/USD';current['azione']='Nuovo piano'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with unittest.mock.patch.object(vp,'PLANS',root/'plans'), \
                 unittest.mock.patch.object(vp,'LOG',root/'log'), \
                 unittest.mock.patch.object(pg,'load',return_value=current), \
                 unittest.mock.patch.object(vp.desk,'save'), \
                 unittest.mock.patch.object(vp,'check') as check:
                vp.archivia_piano(previous)
                result=vp.check_all(max_queries=0)
                check.assert_not_called()
                self.assertEqual(result['storico']['piani_totali'],2)
                self.assertEqual(result['storico']['da_riprendere'],2)
                self.assertTrue((root/'plans'/(vp.plan_hash(current)+'.json')).exists())

    def test_archive_detects_corruption_and_rejects_overwrite(self):
        import verifica_piani as vp
        import piano_gpt as pg
        from pathlib import Path
        current=pg.validate(fixture_trade_plan())
        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch.object(vp,'PLANS',Path(tmp)):
                digest=vp.archivia_piano(current)
                vp.archivia_piano(current)
                self.assertEqual(len(list(Path(tmp).glob('*.json'))),1)
                (Path(tmp)/(digest+'.json')).write_text('{"token":"BAD"}')
                with self.assertRaises(ValueError):
                    vp.archivia_piano(current)

    def test_archive_render_hides_current_and_never_claims_returns(self):
        import verifica_piani as vp
        current=fixture_trade_plan()
        digest=vp.plan_hash(current)
        data={'piani':[
            {'hash_piano':digest,'coppia':'ICNT/USD','tracking':'CONCLUSO',
             'ordine_eventi':'INVALIDAZIONE_PRIMA_DEL_TARGET'},
            {'hash_piano':'old','coppia':'HBAR/USD<script>',
             'tracking':'CONCLUSO','ordine_eventi':'TARGET_PRIMA_DELL_INVALIDAZIONE',
             'creato_utc':'2026-10-18T10:00:00+00:00'}
        ]}
        page=vp.render_archivio(data,digest)
        self.assertIn('Archivio: 1 piani precedenti',page)
        self.assertIn('nessun fill provato',page)
        self.assertIn('&lt;script&gt;',page)
        self.assertNotIn('ICNT/USD',page)
        self.assertNotIn('trade redditizi',page)
        self.assertEqual(vp.render_archivio({'piani':[data['piani'][0]]},digest),'')

    def test_setup_sampler_sees_flat_and_declining_not_only_gainers(self):
        import ricerca_setup as rs
        def market(name,change,volume=1_000_000,spread=.1):
            return dict(token=name, var_oggi_utc_pct=change,
                        volume_24h_eur_stimato=volume,spread_pct=spread,
                        pair_key=name+'USD',prezzo_eur=1)
        pool={x['token']:x for x in (market('DOWN',-3), market('FLAT',.2),
             market('EARLY',4),market('GAINER',13),
             market('OVERHEATED',27),market('TOO_SMALL',0,9000),
             market('TOO_WIDE',0,1_000_000,2))}
        chosen=rs.sample(pool,{},size=10)
        names={x['token'] for x in chosen}
        self.assertTrue({'DOWN','FLAT','EARLY','GAINER','OVERHEATED'}<=names)
        self.assertNotIn('TOO_SMALL',names)
        self.assertNotIn('TOO_WIDE',names)

    def test_setup_excludes_officially_delisted_monero_eea(self):
        import ricerca_setup as rs
        p={'token':'XMR','var_oggi_utc_pct':4.5,'volume_24h_eur_stimato':20000000,
           'spread_pct':.01,'pair_key':'XMRUSD','prezzo_eur':500}
        q=dict(p,token='NEAR',pair_key='NEARUSD')
        sample=rs.sample({'XMR':p,'NEAR':q},{})
        self.assertEqual([v['token'] for v in sample],['NEAR'])
        self.assertIn('support.kraken.com',rs.NON_NEGOZIABILI_SEE['XMR'])

    def test_setup_geometry_closed_hour_breakout_with_volume(self):
        import ricerca_setup as rs
        t0=1800000000
        bars=[]
        for i in range(33):
            final=i==32
            op=100 if not final else 101
            bars.append([t0+i*3600,op,105 if final else 101,
                         99,104 if final else 100,op,60 if final else 10,1])
        bars.append([t0+33*3600,104,400,1,300,300,900,1])
        result=rs.geometry(bars,t0+33*3600+180)
        self.assertEqual(result['categoria'],'tentativo di ripartenza')
        self.assertLess(result['prezzo_ultimo_close_quote'],105)
        self.assertGreater(result['volumi_4h_su_4h_precedenti'],1.15)

    def test_setup_consolidation_uses_two_distinct_windows(self):
        import ricerca_setup as rs
        t0=1800000000
        bars=[]
        for i in range(33):
            hi,lo=(108,92) if 17<=i<25 else (101,99) if i>=25 else (110,90)
            bars.append([t0+i*3600,100,hi,lo,100,100,10,1])
        res=rs.geometry(bars,t0+33*3600+100)
        self.assertEqual(res['categoria'],'consolidamento')
        self.assertLess(res['rapporto_ristrettezza'],.68)

    def test_setup_rejects_missing_hours_or_partial_evidence(self):
        import ricerca_setup as rs
        t0=1800000000
        bars=[[t0+i*3600,100,101,99,100,100,10,1] for i in range(33)]
        self.assertEqual(rs.geometry(bars,t0+20*3600)['stato'],'DATI_INSUFFICIENTI')
        bars[12][0]+=120
        self.assertEqual(rs.geometry(bars,t0+35*3600)['stato'],'DATI_INSUFFICIENTI')

    def test_setup_selection_keeps_categories_not_only_top_volume(self):
        import ricerca_setup as rs
        def row(token,volume):
            return {'token':token,'pair_key':token+'USD','volume_24h_eur_stimato':volume,
                    'spread_pct':0.1}
        rows=[row('BRK',800000),row('COMP',750000),row('START',900000),row('NONE',90_000_000)]
        obs={'BRK':{'stato':'OSSERVATO','categoria':'tentativo di ripartenza','motivo':'A'},
             'COMP':{'stato':'OSSERVATO','categoria':'consolidamento','motivo':'B'},
             'START':{'stato':'OSSERVATO','categoria':'movimento iniziale','motivo':'C'},
             'NONE':{'stato':'OSSERVATO','categoria':'nessun setup confermato','motivo':'D'}}
        chosen=rs.select(rows,obs)
        self.assertEqual([x['token'] for x in chosen],['BRK','COMP','START'])
        self.assertTrue(all(x['perche'] in ('A','B','C') for x in chosen))

    def test_no_trade_plan_preserved_without_fake_prices_or_api(self):
        import piano_gpt as pg
        import verifica_piani as vp
        import copy
        from pathlib import Path
        plan=copy.deepcopy(fixture_trade_plan())
        plan['token']='MERCATO_SPOT'
        plan['coppia']='NESSUNA COPPIA OPERATIVA'
        plan['livelli']=None
        pg.validate(plan)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with unittest.mock.patch.object(vp,'PLANS',root/'plans'), \
                 unittest.mock.patch.object(vp,'LOG',root/'log.jsonl'), \
                 unittest.mock.patch.object(pg,'load',return_value=plan), \
                 unittest.mock.patch.object(vp.desk,'save'), \
                 unittest.mock.patch.object(vp.desk,'kraken') as k:
                out=vp.check_all(max_queries=4)
                self.assertEqual(out['corrente']['stato'],'SENZA_LIVELLI')
                self.assertEqual(out['storico']['non_operativi'],1)
                self.assertEqual(out['storico']['stato'],'VERIFICATO')
                k.assert_not_called()
                self.assertEqual(len(list((root/'plans').glob('*.json'))),1)
                self.assertIn('nessuna entrata',vp.render_summary(out['corrente'],plan))
                self.assertFalse((root/'log.jsonl').exists())

    def test_same_cutoff_for_preselection_and_final_closed_hour(self):
        import analisi_v02 as tv
        import ricerca_setup as rs
        t0=1800000000
        bars=[]
        for i in range(40):
            close=100+i*.2
            bars.append([t0+i*3600,close,close+.1,close-.1,close,close,10+i,1])
        # Chiusa la barra 39, ma la scan ha iniziato a fine barra 38.
        now=t0+39*3600-1
        pre=rs.geometry(bars,now)
        final=tv.momentum(bars,[[t0+i*900,100,101,99,100,100,10,1] for i in range(156)],
                           bars,now=now)
        self.assertEqual(pre['chiusura_1h_utc'],final['chiusura_oraria_utc'])
        self.assertNotEqual(pre['chiusura_1h_utc'],
                            tv.momentum(bars,[[t0+i*900,100,101,99,100,100,10,1] for i in range(156)],
                                       bars,now=t0+40*3600)['chiusura_oraria_utc'])

    def test_search_strata_include_mid_and_exploratory_not_only_large(self):
        import ricerca_setup as rs
        change=(-4,.4,4,12,28)
        rows={}
        for b,pct in enumerate(change):
            for suffix,vol in (('H',2_000_000),('M',650_000),('E',210_000)):
                name='T'+str(b)+suffix
                rows[name]=dict(token=name,pair=name+'/USD',pair_key=name,
                    var_oggi_utc_pct=pct,volume_24h_eur_stimato=vol,
                    spread_pct=.12,prezzo_eur=1.2)
        selected=rs.sample(rows,{},size=15)
        self.assertEqual(len(selected),15)
        self.assertEqual({x['fascia_liquidita'] for x in selected},
                         {'alta','media','esplorativa'})
        self.assertEqual(set(x['token'] for x in selected),set(rows))
        self.assertLess(selected.index(next(x for x in selected if x['token']=='T0E')),
                        selected.index(next(x for x in selected if x['token']=='T1H')))

    def test_exploratory_volume_requires_strict_spread_and_minimum(self):
        import ricerca_setup as rs
        def market(tok,vol,spread):
            return dict(token=tok,pair=tok+'/USD',pair_key=tok,
                var_oggi_utc_pct=0.1,volume_24h_eur_stimato=vol,
                spread_pct=spread,prezzo_eur=1)
        markets={r['token']:r for r in (
            market('GOOD',170000,.14),market('ILLQ',175000,.75),
            market('TINY',110000,.12),market('MID',400000,.6))}
        chosen=rs.sample(markets,{},size=12)
        names={r['token'] for r in chosen}
        self.assertEqual(names,{'GOOD','MID'})
        self.assertEqual(next(r['fascia_liquidita'] for r in chosen
                              if r['token']=='GOOD'),'esplorativa')

    def test_setup_hard_budget_max_24_even_if_many_eligible(self):
        import ricerca_setup as rs
        rows={}
        for i in range(100):
            name='TOKEN'+str(i)
            rows[name]=dict(token=name,pair=name+'/USD',pair_key=name,
                            var_oggi_utc_pct=(i%5)*5-3,
                            volume_24h_eur_stimato=1_000_000+i*1000,
                            prezzo_eur=3,spread_pct=.1)
        self.assertEqual(len(rs.sample(rows,{},size=24)),24)
        with self.assertRaises(ValueError):rs.sample(rows,{},size=25)
        with self.assertRaises(ValueError):rs.sample(rows,{},size=-1)

    def test_setup_scan_provenance_and_no_fabricated_confirmations(self):
        import ricerca_setup as rs
        t0=1800000000
        rows={}
        for i in range(6):
            name='S'+str(i)
            rows[name]=dict(token=name,pair=name+'/USD',pair_key=name,
                            var_oggi_utc_pct=i*5-3,
                            volume_24h_eur_stimato=(180000 if i%3==0 else
                                                       500000 if i%3==1 else 1200000),
                            prezzo_eur=1,spread_pct=.1)
        raw=[[t0+i*3600,100,101,99,100,100,10,1] for i in range(33)]
        calls=[]
        def kraken(endpoint,**kw):
            calls.append((endpoint,kw))
            return {kw['pair']:raw}
        with unittest.mock.patch.object(rs.time,'sleep'):
            selected,info,cache=rs.scan(rows,{},kraken,t0+33*3600+200)
        self.assertEqual(info['campionati'],6)
        self.assertEqual(info['analizzati'],6)
        self.assertEqual(len(info['confronto_1h']),6)
        self.assertEqual(len(calls),6)
        self.assertTrue(all(x['stato']=='OSSERVATO' for x in
                            (y['geometria'] for y in info['confronto_1h'])))
        self.assertTrue(all(x['categoria']=='nessun setup confermato'
                            for x in selected))
        self.assertEqual(len(cache),6)
        self.assertEqual(sum(info['fasce_esaminate'].values()),6)

    def test_radar_excludes_fx_stablecoin_gold_token_pairs(self):
        import mercati_spot as mm
        bases=('AUD','ZCHF','PAXG','XAUT','SOL')
        pairs={'EURUSD':{'wsname':'EUR/USD','status':'online'}}
        tickers={'EURUSD':{'a':['1.2'],'b':['1.19'],'c':['1.195'],
                              'o':'1.195','v':['100','1000']}}
        for token in bases:
            pairs[token]={'wsname':token+'/USD','status':'online'}
            tickers[token]={'a':['1.01'],'b':['.99'],'c':['1'],
                            'o':'1','v':['100000','1000000']}
        found,_=mm.assemble(pairs,tickers)
        self.assertEqual(set(found),{'SOL'})

    def test_exploratory_limit_cannot_overrun_with_cheap_pairs(self):
        import ricerca_setup as rs
        rows={}
        for i in range(30):
            name='EX'+str(i)
            rows[name]=dict(token=name,pair=name+'/USD',pair_key=name,
                            var_oggi_utc_pct=1+0.2*i,
                            volume_24h_eur_stimato=180000+i*1000,
                            spread_pct=.06,prezzo_eur=1)
        pool=rs.sample(rows,{},size=24)
        self.assertEqual(len(pool),6)
        self.assertTrue(all(x['fascia_liquidita']=='esplorativa' for x in pool))

    def test_priority_does_not_discard_second_consolidation_for_no_setup(self):
        import ricerca_setup as rs
        def row(token,vol):
            return {'token':token,'pair_key':token+'USD',
                    'volume_24h_eur_stimato':vol,'spread_pct':.1}
        candidates=[row('VSN',245318),row('SENT',202733),
                    row('XCN',396551),row('AIOZ',219012),row('XRP',17818219)]
        kinds={'VSN':'consolidamento','SENT':'consolidamento',
               'XCN':'movimento iniziale','AIOZ':'movimento iniziale',
               'XRP':'nessun setup confermato'}
        observations={name:{'stato':'OSSERVATO','categoria':kind,
                            'motivo':'Synthetic pattern for regression'}
                      for name,kind in kinds.items()}
        chosen=rs.select(candidates,observations)
        self.assertEqual({x['token'] for x in chosen},
                         {'VSN','SENT','XCN','AIOZ'})
        self.assertEqual(len(chosen),4)
        self.assertNotIn('XRP',{x['token'] for x in chosen})

    def test_priority_one_each_then_more_real_setups_before_neutral(self):
        import ricerca_setup as rs
        rows=[]
        obs={}
        kinds=['consolidamento','consolidamento','consolidamento',
               'movimento iniziale','nessun setup confermato']
        for i,kind in enumerate(kinds):
            token='TOK'+str(i)
            rows.append({'token':token,'pair_key':token+'USD',
                         'volume_24h_eur_stimato':900000-i*80000,
                         'spread_pct':.05})
            obs[token]={'stato':'OSSERVATO','categoria':kind,'motivo':'Test'}
        chosen=rs.select(rows,obs,max_items=4)
        self.assertEqual([x['token'] for x in chosen],
                         ['TOK0','TOK3','TOK1','TOK2'])
        self.assertTrue(all(x['categoria']!='nessun setup confermato' for x in chosen))

    def test_priority_neutral_only_uses_two_contrasts(self):
        import ricerca_setup as rs
        pool=[{'token':str(i),'pair_key':str(i)+'USD',
               'volume_24h_eur_stimato':1_000_000-i*1000,
               'spread_pct':.05} for i in range(8)]
        obs={r['token']:{'stato':'OSSERVATO',
             'categoria':'nessun setup confermato','motivo':'No pattern'}
             for r in pool}
        self.assertEqual(len(rs.select(pool,obs)),2)
        with self.assertRaises(ValueError):rs.select(pool,obs,max_items=5)
        self.assertEqual(rs.select(pool,obs,max_items=0),[])

    def test_dossier_does_not_drop_fourth_full_candidate(self):
        import dossier_trade as dd
        now=d.NOW()
        source={'rilevazione_utc':now.isoformat(),
                'schede_v02':[{'token':'SIM'+str(i),'coppia_analisi':'SIM'+str(i)+'/USD',
                                'alternative':[],'categoria':'test'}
                               for i in range(4)],'markets':{},'trends':{}}
        with unittest.mock.patch.object(dd,'global_context',return_value={}), \
             unittest.mock.patch.object(dd,'derivatives_context',return_value={}), \
             unittest.mock.patch.object(dd.desk,'save') as saver, \
             unittest.mock.patch.object(dd.time,'sleep'), \
             unittest.mock.patch.object(dd.desk,'load',return_value={'posizioni':[]}):
            result=dd.collect(source)
        self.assertEqual([x['token'] for x in result['candidati']],
                         ['SIM0','SIM1','SIM2','SIM3'])
        self.assertEqual(result['kraken_istantanea_utc'],source['rilevazione_utc'])
        saver.assert_called_once()

    def test_fast_20_percent_rebound_not_called_early_breakout(self):
        import ricerca_setup as rs
        first=1800000000
        rows=[]
        for i in range(33):
            close=120.0 if i==8 else 121.0 if i==32 else 100.0
            rows.append([first+i*3600,100.0,max(close,101.0),
                         99.0,close,0,100 if i==32 else 10,1])
        res=rs.geometry(rows,first+33*3600+10)
        self.assertEqual(res['stato'],'OSSERVATO')
        self.assertGreater(res['var_4h_pct'],12)
        self.assertEqual(res['categoria'],'rialzo rapido già esteso')
        self.assertIn('4h',res['motivo'])

    def test_rapid_extension_not_selected_as_setup_or_neutral_control(self):
        import ricerca_setup as rs
        def row(token,vol):
            return {'token':token,'pair_key':token+'USD',
                    'volume_24h_eur_stimato':vol,'spread_pct':.05}
        rows=[row('RALLY',8_000_000),row('STABLE',600_000),row('BREAKOUT',500_000)]
        observations={
            'RALLY':{'stato':'OSSERVATO','categoria':'rialzo rapido già esteso','motivo':'Too far'},
            'STABLE':{'stato':'OSSERVATO','categoria':'consolidamento','motivo':'Tight'},
            'BREAKOUT':{'stato':'OSSERVATO','categoria':'movimento iniziale','motivo':'Early'}}
        chosen=rs.select(rows,observations,max_items=4)
        self.assertEqual({x['token'] for x in chosen},{'STABLE','BREAKOUT'})

    def test_kaspa_identity_verified_before_fundamentals(self):
        import dossier_trade as dd
        import json
        self.assertEqual(dd.COINGECKO_IDS['KAS'],'kaspa')
        market={'current_price':{'usd':0.036},
                'market_cap':{'usd':1_000_000_000},
                'circulating_supply':27_000_000_000,
                'total_supply':27_500_000_000,
                'last_updated':'2026-10-19T05:35:00Z'}
        good={'id':'kaspa','symbol':'kas','name':'Kaspa','market_data':market}
        with unittest.mock.patch.object(dd.desk,'request',return_value=json.dumps(good).encode()):
            found=dd.token_fundamentals('KAS')
            self.assertEqual(found['id'],'kaspa')
            self.assertEqual(found['nome'],'Kaspa')
        wrong=dict(good,symbol='kasx')
        with unittest.mock.patch.object(dd.desk,'request',return_value=json.dumps(wrong).encode()):
            with self.assertRaises(ValueError):dd.token_fundamentals('KAS')

    def test_delta_study_outcome_observes_exact_closed_candle(self):
        import studio_delta as sd
        base=1_800_000_000
        raw=[[base+2700,100,104,98,102,0,11],
             [base+3600,102,109,100,108,0,12]]
        out=sd.outcome(raw,base,100,1,base+3601)
        self.assertEqual(out['stato'],'CHIUSURA_OSSERVATA')
        self.assertAlmostEqual(out['variazione_prezzo_pct'],2.0)
        self.assertNotIn('profitto',str(out).lower())
        pending=sd.outcome(raw,base,100,1,base+3599)
        self.assertEqual(pending['stato'],'NON_MATURO')

    def test_delta_study_rejects_missing_final_candle(self):
        import studio_delta as sd
        base=1_800_000_000
        raw=[[base+3600,102,109,100,108,0,12]]
        res=sd.outcome(raw,base,100,1,base+5400)
        self.assertEqual(res['stato'],'DATI_NON_COPERTI')

    def test_delta_study_blind_frozen_pair_and_no_calls_before_maturity(self):
        import studio_delta as sd
        import hashlib
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch,Mock
        base=1_800_000_000
        stamp=dt.datetime.fromtimestamp(base,dt.timezone.utc).isoformat()
        ref={'fase':'A_SENZA_DELTA_CONGELATA','snapshot_kraken_utc':stamp,
             'candidati':[{'token':'AAA','coppia':'AAA/USD',
                           'riferimento_chiusura_15m_utc':stamp,
                           'prezzo_riferimento_quote':100}]}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            path=root/'example_fase_A.json'
            path.write_text(json.dumps(ref))
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            other={'fase':'B_CON_DELTA_CONGELATA','snapshot_kraken_utc':stamp,
                   'fase_A_nome':path.name,'fase_A_sha256':digest,
                   'candidati':[{'token':'AAA','coppia':'AAA/USD','pair_key_kraken':'AAAUSD',
                                 'finestra_a_utc':stamp,'delta_candela_stato':'COMPLETA'}]}
            (root/'example_fase_B.json').write_text(json.dumps(other))
            api=Mock()
            with patch.object(sd,'ROOT',root),patch.object(sd.time,'sleep'):
                prior=sd.verify(max_calls=4,now=base+3500,api=api)
                self.assertEqual(prior['chiamate_kraken'],0)
                api.assert_not_called()
                api.return_value={'AAAUSD':[[base+2700,100,104,98,102,0,11]]}
                later=sd.verify(max_calls=4,now=base+3601,api=api)
                self.assertEqual(later['orizzonti_maturi_con_esito'],1)
                self.assertEqual(later['chiamate_kraken'],1)
                again=sd.verify(max_calls=4,now=base+3610,api=api)
                self.assertEqual(again['chiamate_kraken'],0)
                path.write_text('manomesso')
                corrupted=sd.verify(max_calls=4,now=base+3611,api=api)
                self.assertEqual(corrupted['stato'],'PARZIALE')
                self.assertEqual(corrupted['esperimenti'],0)
                self.assertEqual(corrupted['chiamate_kraken'],0)

    def test_delta_offline_audit_is_readonly_with_three_closed_horizons(self):
        import studio_delta as sd
        import hashlib, json, tempfile, pathlib
        from unittest.mock import patch
        base=1_800_000_000
        stamp=dt.datetime.fromtimestamp(base,dt.timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder)
            a={'fase':'A_SENZA_DELTA_CONGELATA','snapshot_kraken_utc':stamp,
               'candidati':[{'token':'SUI','coppia':'SUI/EUR',
                   'riferimento_chiusura_15m_utc':stamp,
                   'prezzo_riferimento_quote':100.0,
                   'scelta':'ATTESA','prezzo_privato_TEST':1234567}]}
            aa=root/'mock_fase_A.json'
            aa.write_text(json.dumps(a))
            b={'fase':'B_CON_DELTA_CONGELATA','snapshot_kraken_utc':stamp,
               'fase_A_nome':aa.name,
               'fase_A_sha256':hashlib.sha256(aa.read_bytes()).hexdigest(),
               'candidati':[{'token':'SUI','coppia':'SUI/EUR',
                   'pair_key_kraken':'SUIEUR','finestra_a_utc':stamp,
                   'delta_candela_stato':'COMPLETA','scelta':'ATTESA'}]}
            bb=root/'mock_fase_B.json'
            bb.write_text(json.dumps(b))
            observations={}
            for hours in (1,4,24):
                end=100+hours
                observations[str(hours)]={
                    'stato':'CHIUSURA_OSSERVATA','orizzonte_ore':hours,
                    'chiusura_finale_utc':dt.datetime.fromtimestamp(
                        base+hours*3600,dt.timezone.utc).isoformat(),
                    'prezzo_finale_quote':end,
                    'variazione_prezzo_pct':float(hours)}
            ep=root/'mock_esiti.json'
            ep.write_text(json.dumps({'fase_B_nome':bb.name,
                'fase_B_sha256':hashlib.sha256(bb.read_bytes()).hexdigest(),
                'esiti':{'SUI':observations}}))
            before={p.name:p.read_bytes() for p in root.iterdir()}
            with patch.object(sd.desk,'kraken',
                              side_effect=AssertionError('OFFLINE means no API')):
                audit=sd.audit_offline(root)
            after={p.name:p.read_bytes() for p in root.iterdir()}
            self.assertEqual(before,after)
            self.assertEqual(audit['stato'],'DOCUMENTAZIONE_AB_ED_ESITI_COMPLETI')
            case=audit['esperimenti'][0]['candidati'][0]
            self.assertEqual(case['confronto_testuale_A_B']['stato'],
                             'CAMPO_TESTUALE_UGUALE')
            self.assertEqual(set(case['orizzonti'].values()),{'OSSERVATO'})
            # This output can be copied from Termux without private values.
            public=json.dumps(audit)
            self.assertNotIn('1234567',public)
            self.assertNotIn('prezzo_finale_quote',public)
            self.assertNotIn('fase_A_sha256',public)
            self.assertEqual(audit['rete'],'NESSUNA_CHIAMATA')
            self.assertEqual(audit['scritture'],'NESSUNA')

    def test_delta_offline_audit_tampering_and_absent_results_fail_closed(self):
        import studio_delta as sd
        import hashlib, json, tempfile, pathlib
        base=1_800_000_000
        stamp=dt.datetime.fromtimestamp(base,dt.timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder)
            self.assertEqual(sd.audit_offline(root)['stato'],'NESSUNA_FASE_B')
            aa=root/'x_fase_A.json'
            aa.write_text(json.dumps({'fase':'A_SENZA_DELTA_CONGELATA',
                'snapshot_kraken_utc':stamp,
                'candidati':[{'token':'QNT','coppia':'QNT/USD',
                'riferimento_chiusura_15m_utc':stamp,
                'prezzo_riferimento_quote':100.0}]}))
            bb=root/'x_fase_B.json'
            bb.write_text(json.dumps({'fase':'B_CON_DELTA_CONGELATA',
                'snapshot_kraken_utc':stamp,'fase_A_nome':aa.name,
                'fase_A_sha256':hashlib.sha256(aa.read_bytes()).hexdigest(),
                'candidati':[{'token':'QNT','coppia':'QNT/USD',
                  'pair_key_kraken':'QNTUSD','finestra_a_utc':stamp,
                  'delta_candela_stato':'COMPLETA'}]}))
            audit=sd.audit_offline(root)
            self.assertEqual(audit['stato'],'INCOMPLETO')
            self.assertEqual(audit['esperimenti'][0]['esiti'],'FILE_ASSENTE')
            self.assertEqual(audit['esperimenti'][0]['candidati'][0]
                             ['confronto_testuale_A_B']['stato'],'NON_CONFRONTABILE')
            self.assertEqual(set(audit['esperimenti'][0]['candidati'][0]
                                 ['orizzonti'].values()),{'ASSENTE'})
            aa.write_text('manomesso')
            tampered=sd.audit_offline(root)
            self.assertEqual(tampered['stato'],'INCOMPLETO')
            self.assertEqual(tampered['esperimenti'][0]['fasi'],'NON_VERIFICABILI')
            self.assertNotIn('manomesso',json.dumps(tampered))

    def test_delta_offline_audit_rejects_wrong_outcome_hash_or_close(self):
        import studio_delta as sd
        import hashlib, json, tempfile, pathlib
        base=1_800_000_000
        stamp=dt.datetime.fromtimestamp(base,dt.timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder)
            a={'fase':'A_SENZA_DELTA_CONGELATA',
               'snapshot_kraken_utc':stamp,
               'candidati':[{'token':'PUMP','coppia':'PUMP/USD',
                   'riferimento_chiusura_15m_utc':stamp,
                   'prezzo_riferimento_quote':100,'scelta':'LONG'}]}
            aa=root/'a_fase_A.json';aa.write_text(json.dumps(a))
            b={'fase':'B_CON_DELTA_CONGELATA',
               'snapshot_kraken_utc':stamp,'fase_A_nome':aa.name,
               'fase_A_sha256':hashlib.sha256(aa.read_bytes()).hexdigest(),
               'candidati':[{'token':'PUMP','coppia':'PUMP/USD',
                   'pair_key_kraken':'PUMPUSD','finestra_a_utc':stamp,
                   'delta_candela_stato':'COMPLETA','scelta':'ATTESA'}]}
            bb=root/'a_fase_B.json';bb.write_text(json.dumps(b))
            ep=root/'a_esiti.json'
            row={'stato':'CHIUSURA_OSSERVATA','orizzonte_ore':1,
                 'chiusura_finale_utc':dt.datetime.fromtimestamp(
                      base+2*3600,dt.timezone.utc).isoformat(),
                 'prezzo_finale_quote':103,'variazione_prezzo_pct':3}
            ep.write_text(json.dumps({'fase_B_nome':bb.name,
                'fase_B_sha256':'0'*64,'esiti':{'PUMP':{'1':row}}}))
            wrong_hash=sd.audit_offline(root)['esperimenti'][0]
            self.assertEqual(wrong_hash['esiti'],'METADATI_INCOERENTI')
            ep.write_text(json.dumps({'fase_B_nome':bb.name,
                'fase_B_sha256':hashlib.sha256(bb.read_bytes()).hexdigest(),
                'esiti':{'PUMP':{'1':row}}}))
            wrong_end=sd.audit_offline(root)['esperimenti'][0]
            self.assertEqual(wrong_end['esiti'],'FILE_INTEGRO')
            self.assertEqual(wrong_end['candidati'][0]['orizzonti']['1h'],
                             'INCOERENTE')
            self.assertEqual(wrong_end['candidati'][0]
                             ['confronto_testuale_A_B']['stato'],
                             'CAMPO_TESTUALE_DIVERSO')

    def test_spot_flow_full_4h_window_and_15m_signed_volume(self):
        import flusso_spot as f
        now=1_800_000_000
        trades=[['2','10',now-4*3600-10,'b','l'],
                ['3','4',now-3600,'s','m'],
                ['4','2',now-600,'b','l'],
                ['5','3',now-50,'s','m']]
        data=f.analyze(trades,now,'ABC/USD')
        self.assertEqual(data['stato'],'COMPLETO_4H')
        self.assertTrue(data['finestra_4h_completa'])
        self.assertEqual(data['delta_4h']['delta_quote'],-19.0)
        self.assertEqual(data['delta_15m']['delta_quote'],-7.0)
        self.assertEqual(data['numero_trade_ottenuti'],4)
        self.assertIn('SPOT',data['copertura'])

    def test_spot_flow_partial_4h_does_not_invent_4h_cvd(self):
        import flusso_spot as f
        now=1_800_000_000
        tr=[['2','10',now-1800,'b','l'],['2','8',now-10,'s','l']]
        out=f.analyze(tr,now,'ABC/USD')
        self.assertEqual(out['stato'],'FINESTRA_4H_NON_COPERTA')
        self.assertIsNone(out['delta_4h'])
        self.assertTrue(out['finestra_15m_completa'])
        self.assertEqual(out['delta_15m']['delta_quote'],-16.0)

    def test_spot_flow_15m_also_incomplete_without_coverage(self):
        import flusso_spot as f
        now=1_800_000_000
        out=f.analyze([['2','10',now-200,'b','l']],now,'ABC/USD')
        self.assertIsNone(out['delta_15m'])
        self.assertFalse(out['finestra_15m_completa'])

    def test_spot_flow_closed_candle_is_not_rolling_window(self):
        import flusso_spot as f
        import datetime as dt
        now=1_800_000_000
        end=now-300
        end_iso=dt.datetime.fromtimestamp(end,dt.timezone.utc).isoformat()
        trades=[['1','1',now-1300,'s','l'],
                ['2','10',now-800,'b','l'],
                ['3','4',now-400,'s','m'],
                ['4','20',now-100,'b','m']]
        out=f.analyze(trades,now,'ABC/USD',chiusura_15m_utc=end_iso)
        aligned=out['candela_15m_chiusa']
        self.assertEqual(aligned['stato'],'COMPLETA')
        self.assertEqual(aligned['misure']['delta_quote'],8.0)
        self.assertEqual(aligned['misure']['numero_trade'],2)
        self.assertNotEqual(aligned['misure']['delta_quote'],out['delta_15m']['delta_quote'])

    def test_spot_flow_does_not_guess_truncated_closed_candle(self):
        import flusso_spot as f
        import datetime as dt
        now=1_800_000_000
        end=now-300
        end_iso=dt.datetime.fromtimestamp(end,dt.timezone.utc).isoformat()
        out=f.analyze([['2','2',now-500,'b','l'],['2','2',now-5,'s','l']],
                      now,'ABC/USD',chiusura_15m_utc=end_iso)
        self.assertEqual(out['candela_15m_chiusa']['stato'],'NON_COPERTA')
        self.assertIsNone(out['candela_15m_chiusa']['misure'])
        wrong=f.analyze([['2','2',now-1000,'b','l'],['2','2',now-5,'s','l']],
                        now,'ABC/USD',chiusura_15m_utc='not-a-date')
        self.assertEqual(wrong['candela_15m_chiusa']['stato'],'RIFERIMENTO_NON_VALIDO')

    def test_spot_flow_ui_separates_closed_and_rolling_intervals(self):
        import copy
        report=d.build_report({'rilevazione_utc':self.now.isoformat(),'markets':{},
                                'trends':{},'feed':[],'problemi_feed':[]},
                                {'posizioni':[]},{},{},[])
        report['schede_v02']=[dict(token='ABC',categoria='esame',esito='RIESAME MIRATO',
            sintesi='In prova',coppia_analisi='ABC/USD',valuta_quotazione='USD',
            alternative=[],indicatori={},book={},evidenze=[],criticita=[],
            costi_roundtrip=[])]
        report['flussi_spot']={'ABC':{'stato':'FINESTRA_4H_NON_COPERTA',
            'candela_15m_chiusa':{'stato':'COMPLETA',
                'inizio_utc':'2026-10-19T14:45:00+00:00',
                'fine_utc':'2026-10-19T15:00:00+00:00',
                'misure':{'delta_quote':300,'percentuale_netto_su_volume':30}},
            'finestra_15m_completa':True,
            'delta_15m':{'delta_quote':-100,'percentuale_netto_su_volume':-10},
            'finestra_4h_completa':False,'delta_4h':None}}
        html=d.render(report)
        self.assertIn('Candela 15m chiusa, stessa finestra del prezzo',html)
        self.assertIn('Ultimi 15 minuti mobili (finestra differente)',html)
        self.assertIn('300,00',html)
        self.assertIn('-100,00',html)
        self.assertIn('NON CVD storico continuo',html)

    def test_spot_flow_old_last_trade_is_not_live_signal(self):
        import flusso_spot as f
        now=1_800_000_000
        tr=[['2','10',now-6000,'b','l'],['2','3',now-500,'s','l']]
        out=f.analyze(tr,now,'ABC/USD')
        self.assertEqual(out['stato'],'SCADUTO')
        self.assertNotIn('delta_4h',out)

    def test_spot_flow_malformed_side_or_future_timestamp(self):
        import flusso_spot as f
        now=1_800_000_000
        for tr in ([[['1','1',now-5,'x','l']],
                    [['1','1',now+60,'b','l']],
                    [['1','0',now-5,'b','l']],
                    [['1','1',now-5,'b','l'],['1','1',now-20,'s','l']]]):
            with self.subTest(data=tr):
                self.assertEqual(f.analyze(tr,now,'ABC/USD')['stato'],'SCHEMA_NON_VALIDO')

    def test_spot_flow_api_failure_reported_not_hidden(self):
        import flusso_spot as f
        with unittest.mock.patch.object(f.desk,'kraken',side_effect=ConnectionError('offline')):
            out=f.fetch('ABC/USD','ABCUSD',1_800_000_000)
        self.assertEqual(out['stato'],'NON_DISPONIBILE')
        self.assertEqual(out['errore'],'ConnectionError')

    def test_binance_reference_volume_in_token_units_and_source_separation(self):
        import binance_reference as b
        import unittest.mock
        from copy import deepcopy
        kr_pairs={
            "BTC_EUR":{"wsname":"XBT/EUR","status":"online"},
            "BTC_USDC":{"wsname":"XBT/USDC","status":"online"},
            "BTC_USDT":{"wsname":"XBT/USDT","status":"online"}}
        kr_tickers={
            "BTC_EUR":{"v":["8","10"]},
            "BTC_USDC":{"v":["8","20"]},
            "BTC_USDT":{"v":["8","9999"]}}
        fake={
            "symbol":"BTCUSDT","bidPrice":"100","askPrice":"100.02",
            "lastPrice":"100.01","volume":"60","quoteVolume":"6000.6",
            "priceChangePercent":"3.0"}
        def getter(endpoint,**kwargs):
            if endpoint=="exchangeInfo":
                return {"symbols":[{"symbol":"BTCUSDT","status":"TRADING"}]}
            if endpoint=="ticker/24hr":
                self.assertIn('BTCUSDT',kwargs['symbols'])
                return [deepcopy(fake)]
            if endpoint=="depth":
                return {"bids":[["100","1"]],"asks":[["100.02","2"]]}
            raise AssertionError("Unexpected API")
        with unittest.mock.patch.object(b,"api",side_effect=getter):
            out=b.collect(["BTC"],kr_pairs,kr_tickers,shortlist=["BTC"])
        self.assertEqual(out["status"],"OK")
        row=out["tokens"][0]
        self.assertEqual(row["binance_base_volume_24h_subset"],60.0)
        self.assertEqual(row["kraken_base_volume_24h_subset"],30.0)
        self.assertEqual(row["volume_ratio_subsets"],2.0)
        self.assertEqual(row["binance_pairs"][0]["quote"],"USDT")
        self.assertAlmostEqual(row["binance_top10_book"]["imbalance_10levels"],-0.333,places=3)
        self.assertIn("NON sono volumi totali",row["coverage_warning"])
        self.assertNotIn('BTC/USDT', str(row["kraken_pairs"]))

    def test_binance_reference_rejects_malformed_tickers_and_auth_endpoints(self):
        import binance_reference as b
        import unittest.mock
        with self.assertRaises(ValueError):
            b.api("order",symbol="BTCUSDT")
        with self.assertRaises(ValueError):
            b.parse_ticker({"symbol":"BTCUSDT","bidPrice":"105",
                            "askPrice":"100","lastPrice":"102",
                            "volume":"100","quoteVolume":"10200",
                            "priceChangePercent":"2"})
        with unittest.mock.patch.object(b,"api",side_effect=[
                {"symbols":[]}
             ]):
            out=b.collect(["MISSING"],{}, {},shortlist=[])
        self.assertEqual(out["status"],"NO_PAIR")

    def test_c1_fonte_storica_distinta_da_freschezza_e_fallimento(self):
        import datetime as dt
        now=dt.datetime(2026,10,24,8,tzinfo=dt.timezone.utc)
        p={'fonte_quantita':'Kraken BalanceEx API privata SOLA LETTURA, 2026-10-24T06:00:00+00:00',
           'data_ora_saldo_privato_utc':'2026-10-24T06:00:00+00:00',
           'posizioni':[{'token':'BTC','quantita':'1'}]}
        state=d.stato_saldo(p, {'stato':'FALLITO','errore_tipo':'ConnectionError'}, now=now)
        self.assertTrue(state['portafoglio_aggiornato_da_api_private'])
        self.assertEqual(state['freschezza_saldo'],'NON_RECENTE')
        self.assertEqual(state['eta_saldo_minuti'],120.0)
        self.assertEqual(state['ultimo_tentativo'],'FALLITO')
        self.assertEqual(state['ultimo_errore_tipo'],'ConnectionError')
        self.assertFalse(d.stato_saldo({},now=now)['portafoglio_aggiornato_da_api_private'])
        self.assertEqual(d.stato_saldo({},now=now)['freschezza_saldo'],'ASSENTE_O_IGNOTO')
        self.assertEqual(d.stato_saldo({'fonte_quantita':'manuale'},now=now)['origine'],
                         'IGNOTA_O_ALTRA')
        p['data_ora_saldo_privato_utc']='non valido'
        self.assertEqual(d.stato_saldo(p,now=now)['freschezza_saldo'],'ORARIO_NON_VALIDO')
        p['data_ora_saldo_privato_utc']=(now+dt.timedelta(minutes=10)).isoformat()
        future=d.stato_saldo(p,now=now)
        self.assertEqual(future['freschezza_saldo'],'ORARIO_FUTURO_NON_ATTENDIBILE')
        self.assertFalse(future['portafoglio_aggiornato_da_api_private'])

    def test_c1_privato_non_blocca_aggiornamento_pubblico(self):
        import kraken_readonly as account
        from unittest import mock
        with mock.patch.object(account,'AUTH') as auth, mock.patch.object(account,'refresh') as get:
            auth.is_file.return_value=False
            self.assertEqual(d.aggiorna_saldo_sola_lettura()['stato'],'NON_CONFIGURATO')
            get.assert_not_called()
            auth.is_file.return_value=True
            get.side_effect=SystemExit('permessi non corretti')
            result=d.aggiorna_saldo_sola_lettura()
            self.assertEqual(result['stato'],'FALLITO')
            self.assertEqual(result['errore_tipo'],'SystemExit')
            get.side_effect=ConnectionError('offline')
            self.assertEqual(d.aggiorna_saldo_sola_lettura()['errore_tipo'],'ConnectionError')
            get.side_effect=None
            self.assertEqual(d.aggiorna_saldo_sola_lettura()['stato'],'RIUSCITO')

    def test_c1_dossier_dichiara_fonte_e_ultimo_tentativo(self):
        import dossier_trade as dd
        from unittest import mock
        now=d.NOW().isoformat(timespec='seconds')
        p={'fonte_quantita':'Kraken BalanceEx API privata SOLA LETTURA, '+now,
           'data_ora_saldo_privato_utc':now,'posizioni':[{'token':'BTC','quantita':'1'}]}
        source={'rilevazione_utc':now,'schede_v02':[],
                'saldo_refresh':{'stato':'FALLITO','errore_tipo':'ConnectionError'},
                'orari_fonti':{'composizione_kdd_utc':now}}
        with mock.patch.object(dd.desk,'load',return_value=p), \
             mock.patch.object(dd.desk,'save'), \
             mock.patch.object(dd,'recupera_4h',return_value={}), \
             mock.patch.object(dd,'global_context',return_value={}), \
             mock.patch.object(dd,'derivatives_context',return_value={}):
            result=dd.collect(source=source)
        self.assertTrue(result['portafoglio_aggiornato_da_api_private'])
        self.assertEqual(result['stato_saldo']['ultimo_tentativo'],'FALLITO')
        self.assertEqual(result['orari_fonti']['composizione_kdd_utc'],now)
        self.assertTrue(result['portafoglio_noto'])
        self.assertNotIn('Quantità manuali trascritte',' '.join(result['limiti']))

    def test_c1_report_conserva_timestamp_e_separa_saldo(self):
        now=d.NOW().isoformat(timespec='seconds')
        p={'posizioni':[],'fonte_quantita':'Kraken BalanceEx API privata SOLA LETTURA, '+now,
           'data_ora_saldo_privato_utc':now}
        data={'rilevazione_utc':now,'markets':{},'trends':{},'feed':[],
              'problemi_feed':[], 'saldo_refresh':{'stato':'RIUSCITO'},
              'orari_fonti':{'kraken_ticker_richiesta_utc':now,
                             'kraken_ticker_risposta_utc':now,'composizione_kdd_utc':now}}
        result=d.build_report(data,p,{},{},[])
        self.assertEqual(result['orari_fonti'],data['orari_fonti'])
        self.assertEqual(result['saldo_stato']['ultimo_tentativo'],'RIUSCITO')
        self.assertEqual(result['saldo_stato']['origine'],'KRAKEN_BALANCEEX')
        self.assertNotIn('Nessun accesso al conto, nessuna API privata',
                         ' '.join(result['avvertenze']))

    def test_c1_rigenera_non_attribuisce_vecchio_tentativo_a_saldo_nuovo(self):
        import datetime as dt
        now=dt.datetime(2026,10,24,10,tzinfo=dt.timezone.utc)
        portfolio={
            'fonte_quantita':'Kraken BalanceEx API privata SOLA LETTURA, 2026-10-24T09:58:00+00:00',
            'data_ora_saldo_privato_utc':'2026-10-24T09:58:00+00:00'}
        vecchio={'stato':'FALLITO',
                 'controllato_utc':'2026-10-24T08:00:00+00:00',
                 'errore_tipo':'ConnectionError'}
        result=d.stato_saldo(portfolio,vecchio,now=now)
        self.assertEqual(result['freschezza_saldo'],'RECENTE')
        self.assertEqual(result['coerenza_tentativo_con_saldo'],'NON_CORRELATO_AL_SALDO')
        self.assertEqual(result['ultimo_tentativo'],'NON_DOCUMENTATO')
        self.assertIsNone(result['ultimo_errore_tipo'])
        corrente={'stato':'RIUSCITO','controllato_utc':'2026-10-24T09:58:01+00:00'}
        result=d.stato_saldo(portfolio,corrente,now=now)
        self.assertEqual(result['coerenza_tentativo_con_saldo'],'ORDINE_TEMPORALE_COMPATIBILE')
        self.assertEqual(result['ultimo_tentativo'],'RIUSCITO')
        futuro={'stato':'RIUSCITO','controllato_utc':'2026-10-24T11:00:00+00:00'}
        result=d.stato_saldo(portfolio,futuro,now=now)
        self.assertEqual(result['coerenza_tentativo_con_saldo'],'ORARIO_TENTATIVO_FUTURO')
        self.assertEqual(result['ultimo_tentativo'],'NON_DOCUMENTATO')

    def test_private_balance_sync_preserves_t0_and_excludes_cash_from_positions(self):
        import kdd_saldi
        import tempfile, json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"portafoglio.json"
            p.write_text(json.dumps({
                "t0_id":"T0_EXAMPLE", "t0_sha256":"fixed-digest",
                "posizioni":[{"token":"BTC","quantita":"2","costo_medio_eur":None}]
            }))
            snapshot={
                "source":"Kraken Spot REST /0/private/BalanceEx (read-only)",
                "acquired_utc":"2026-10-20T08:00:00+00:00",
                "account_segments":[
                    {"token":"BTC","account_segment":"spot",
                     "balance":"1.25","available_balance":"1.00"},
                    {"token":"USDC","account_segment":"spot",
                     "balance":"150.00","available_balance":"140.00"},
                    {"token":"ETH","account_segment":".F",
                     "balance":"0.25","available_balance":"0.25"}
                ]}
            result=kdd_saldi.apply(snapshot,path=p)
            saved=json.loads(p.read_text())
            self.assertEqual(result['spot_USDC'],'140.00')
            self.assertEqual(saved['t0_id'],'T0_EXAMPLE')
            self.assertEqual(saved['t0_sha256'],'fixed-digest')
            self.assertEqual(saved['posizioni'][0]['quantita'],'1.25')
            self.assertEqual(saved['posizioni'][0]['disponibile_spot'],'1.00')
            self.assertEqual(len(saved['posizioni']),1)
            self.assertNotIn('USDC',[x['token'] for x in saved['posizioni']])
            self.assertEqual(saved['segmenti_non_spot']['ETH'][0]['segment'],'.F')
            with self.assertRaises(ValueError):
                kdd_saldi.apply({**snapshot,'source':'other'},path=p)
            self.assertEqual(json.loads(p.read_text()),saved)

    def test_migration_screenshot_is_not_kraken_balance(self):
        sample=fixture_migration()
        self.assertEqual(sample['stato'],'DA_RICONCILIARE')
        self.assertFalse(sample['migrazione_completata'])
        self.assertTrue(all(row['accreditato_kraken'] is None
                            for row in sample['asset_visibili']))
        report=d.build_report(
            {'rilevazione_utc':self.now.isoformat(),'markets':{},'trends':{},
             'feed':[],'problemi_feed':[]},
            {'posizioni':[]},{},{},[])
        report['migrazione_attesa']=sample
        self.assertFalse(report['posizioni'])
        self.assertFalse(report.get('liquidita_spot_api'))
        page=d.render(report)
        self.assertIn('Migrazione storica:',page)
        self.assertIn('NON significa zero',page)
        self.assertNotIn('Disponibile spot da API privata:',page)

    def test_migration_shown_only_as_pending_not_tradeable_portfolio(self):
        report=d.build_report(
            {'rilevazione_utc':self.now.isoformat(), 'markets':{},'trends':{},
             'feed':[], 'problemi_feed':[]},
            {'posizioni':[]},{},{},[])
        report['migrazione_attesa']=fixture_migration()
        rendered=d.render(report)
        self.assertIn('Le vecchie quantità Binance sono archiviate separatamente dal portafoglio Kraken',rendered)
        self.assertIn('1 asset ora visibili su Kraken, 1 da verificare',rendered)
        self.assertIn('SIM_ATTESA',rendered)
        self.assertNotIn('SIM_PRESENTE',rendered)
        self.assertIn('Nessuna quantità inserita',rendered)
        self.assertNotIn('Disponibile spot da API privata:',rendered)

    def test_local_t0_original_integrity_and_balances_are_separate(self):
        """Gate locale vero: mai inviare T0 o dati personali nel repository."""
        from pathlib import Path
        from decimal import Decimal, InvalidOperation
        import hashlib
        import re
        import os
        root=d.DIR
        if not (root/'config.json').is_file():
            self.skipTest('T0 LOCALE NON ESEGUITO: checkout senza config privata; prova obbligatoria nello staging Samsung')
        port=root/'portafoglio.json'
        self.assertTrue(port.is_file() and not port.is_symlink(),
                        'Portafoglio privato necessario per gate T0 locale')
        local=json.loads(port.read_text(encoding='utf-8'))
        identifier=local.get('t0_id')
        self.assertTrue(isinstance(identifier,str) and
                        re.fullmatch(r'T0_\d{4}-\d{2}-\d{2}_\d{4}_KRAKEN_PRO',
                                     identifier) is not None,
                        'Identificatore T0 locale non valido')
        original=root/'storico_portafoglio'/(identifier+'.json')
        self.assertTrue(original.is_file() and not original.is_symlink(),
                        'Fotografia T0 originale non trovata')
        self.assertTrue(isinstance(local.get('t0_sha256'),str) and
                        hashlib.sha256(original.read_bytes()).hexdigest()==local['t0_sha256'],
                        'Impronta T0 differente dalla copia originaria')
        # Il solo hash in portafoglio.json non autentica T0: i due file
        # potrebbero essere modificati insieme. Richiediamo un'impronta
        # precedentemente attestata, recuperata da prova PRIVATA INDIPENDENTE.
        # Non ricavarla di nuovo dal T0 corrente: sarebbe una verifica circolare.
        trusted=os.environ.get('KDD_T0_TRUSTED_SHA256','')
        proof=os.environ.get('KDD_T0_TRUSTED_PROOF','')
        # Due rappresentazioni alternative della prova storica:
        # hash originale privato, oppure prova SHA-256 ridotta a 96 bit
        # derivata in modo deterministico dal medesimo hash. Entrambe devono
        # provenire da una copia INDIPENDENTE, mai dal file corrente.
        digest=hashlib.sha256(original.read_bytes()).hexdigest()
        expected_proof=hashlib.sha256(
            ('KDD-T0-20261024-VERIFICA-RETROSPETTIVA:'+digest).encode()
        ).hexdigest()[:24]
        valid_hash=re.fullmatch(r'[a-f0-9]{64}',trusted) is not None
        valid_proof=re.fullmatch(r'[a-f0-9]{24}',proof) is not None
        self.assertTrue(valid_hash or valid_proof,
                        'ATTESTAZIONE T0 LOCALE ASSENTE: occorre riferimento storico indipendente; gate NON SUPERATO')
        if valid_hash:
            self.assertEqual(digest,trusted,
                             'T0 locale diverso dall\'impronta storica indipendente')
        if valid_proof:
            self.assertEqual(expected_proof,proof,
                             'T0 locale diverso dalla prova storica indipendente')
        snapshot=json.loads(original.read_text(encoding='utf-8'))
        entries=snapshot.get('quantita_e_valori_schermata')
        self.assertTrue(isinstance(entries,list) and len(entries)>0,
                        'Fotografia T0 priva delle voci originarie')
        try:
            values=[Decimal(str(entry['valore_eur_visualizzato']))
                    for entry in entries]
            recorded=Decimal(str(snapshot['valore_totale_fotografia_eur']))
        except (KeyError,TypeError,InvalidOperation) as exc:
            self.fail('Fotografia T0 non interpretabile: '+type(exc).__name__)
        # La fotografia originale mostra valori arrotondati ai centesimi:
        # il totale dell'interfaccia può discostarsi di un centesimo dalla
        # somma delle righe. Non dichiararlo corruzione: l'autenticità
        # resta vincolata all'impronta storica indipendente sopra.
        self.assertTrue(recorded.is_finite() and recorded>0 and
                        all(v.is_finite() and v>=0 for v in values) and
                        abs(sum(values,Decimal('0'))-recorded)<=Decimal('0.01'),
                        'Totale T0 incoerente oltre lo scarto di arrotondamento documentato')
        self.assertIn('BalanceEx',local.get('fonte_quantita',''),
                      'Fonte dei saldi locali non riconosciuta')
        self.assertIsInstance(local.get('posizioni'),list)
        self.assertIsInstance(local.get('liquidita_spot_api',{}),dict)
        self.assertTrue(all(item.get('costo_medio_eur') is None or
                            isinstance(item.get('costo_medio_eur'),(int,float,str))
                            for item in local['posizioni']),
                        'Schema dei costi medi incoerente')

    def test_trade_flow_timestamp_is_after_api_response_not_snapshot_start(self):
        import flusso_spot as f
        import datetime
        now=1_800_000_000
        def later_now():
            return datetime.datetime.fromtimestamp(now+30,datetime.timezone.utc)
        api={'PAIR':[['2','3',now+10,'b','l'],['2','2',now+25,'s','l']],
             'last':'x'}
        with unittest.mock.patch.object(f.desk,'kraken',return_value=api), \
             unittest.mock.patch.object(f.desk,'NOW',side_effect=later_now):
            out=f.fetch('PAIR/USD','PAIR')
        self.assertNotEqual(out['stato'],'SCHEMA_NON_VALIDO')
        self.assertIn('osservato_utc',out)
        self.assertEqual(out['ritardo_ultimo_trade_secondi'],5)

    def test_spot_flow_panel_keeps_uncovered_four_hours_explicit(self):
        report=d.build_report(
            {'rilevazione_utc':self.now.isoformat(), 'markets':{},
             'trends':{},'feed':[],'problemi_feed':[]}, {'posizioni':[]},{},{},[])
        # La stessa coppia ha 15m validi e un campione 4h troncato.
        report['schede_v02']=[dict(
            token='SIM', categoria='movimento iniziale',esito='DA ESAMINARE',
            sintesi='Osservazione',coppia_analisi='SIM/USD',valuta_quotazione='USD',
            prezzo_eur=1,indicatori={},book={},evidenze=[],criticita=[],
            alternative=[],costi_roundtrip=[])]
        report['flussi_spot']={'SIM':dict(stato='FINESTRA_4H_NON_COPERTA',
            finestra_15m_completa=True,
            delta_15m={'delta_quote':-125.0,'percentuale_netto_su_volume':-25.0},
            finestra_4h_completa=False,delta_4h=None,
            ultimo_trade_utc='2026-10-19T09:01:00+00:00',
            osservato_utc='2026-10-19T09:01:01+00:00')}
        html=d.render(report)
        self.assertIn('Flusso spot recente Kraken',html)
        self.assertIn('Netto buy',html)
        self.assertIn('Dati insufficienti per coprire tutta la finestra',html)
        self.assertIn('NON CVD storico continuo',html)
        self.assertNotIn('Netto buy−sell: None',html)

    def test_canonical(self):
        self.assertEqual(d.canonical('XBT'),'BTC')
    def test_paired_correctly(self):
        rows=d.market_pairs_and_ticker(self.pairs,self.t)
        self.assertEqual(set(rows),{'BTC','SOL'})
        self.assertEqual(rows['BTC']['pair_key'],'XXBTZEUR')
    def test_open_utc_change(self):
        self.assertAlmostEqual(d.market_pairs_and_ticker(self.pairs,self.t)['SOL']['var_oggi_utc_pct'],11.111111,places=4)
    def test_spread(self):
        self.assertAlmostEqual(d.market_pairs_and_ticker(self.pairs,self.t)['SOL']['spread_pct'],0.1,places=4)
    def test_insufficient_candles(self):
        self.assertIn('errore',d.calc_trend([[1,0,0,0,100]]*4,100))
    def test_complete_candles_excludes_partial(self):
        bars=[[i,0,0,0,str(100+i)] for i in range(40)]
        result=d.calc_trend(bars,140)
        self.assertAlmostEqual(result['media_20g_eur'], 128.5)
    def test_missing_context_is_not_neutral(self):
        c=d.context_status({},self.now)
        self.assertEqual(c['macroeconomia']['stato'],'DA_VERIFICARE')
    def test_context_with_source(self):
        c=d.context_status({'geopolitica': {'valutazione':'documentata','fonte':'https://example.org','aggiornato_utc':self.now.isoformat(), 'validita_giorni':5}},self.now)
        self.assertEqual(c['geopolitica']['stato'],'VALUTATO')
    def test_invalid_expiry(self):
        text=d.decision_state('BTC',[{'token':'BTC','scelta':'ATTESA','motivo':'x','scade_utc':'bad','creata_utc':'2026'}],self.now)
        self.assertIn('scadenza',text)
    def test_overdue(self):
        text=d.decision_state('BTC',[{'token':'BTC','scelta':'ATTESA','motivo':'x','scade_utc':'2026-10-15T00:00:00+00:00','creata_utc':'2026-10-14'}],self.now)
        self.assertIn('SCADUTA',text)
    def test_default_not_hold(self):
        self.assertIn('non equivale a HOLD',d.decision_state('BTC',[],self.now))
    def test_rising_token_is_review_not_order(self):
        sig=d.signals({}, {'var_7g_pct':25,'var_30g_pct':20,'sopra_media20':True})
        self.assertIn('valutare',sig[0])
    def test_screening_and_html(self):
        rows=d.market_pairs_and_ticker(self.pairs,self.t)
        bars=[[i,0,0,0,str(100+i)] for i in range(40)]
        data={'rilevazione_utc':d.NOW().isoformat(),'markets':rows,'trends':{'BTC':d.calc_trend(bars,45000),'SOL':d.calc_trend(bars,100)},'feed':[],'problemi_feed':[]}
        report=d.build_report(data,{'posizioni':[{'token':'SOL','quantita':1,'costo_medio_eur':None}]},{'scanner': {'min_var_oggi_utc_pct':8,'max_var_oggi_utc_pct':20}}, {}, [])
        self.assertEqual(len(report['candidati']),1)
        self.assertIn('SOL',d.render(report))
        self.assertAlmostEqual(report['totale_stimato_eur'],100)
    def test_no_invented_balances(self):
        rows=d.market_pairs_and_ticker(self.pairs,self.t)
        report=d.build_report({'rilevazione_utc':d.NOW().isoformat(),'markets':rows,'trends':{},'feed':[], 'problemi_feed':[]},
                              {'posizioni':[{'token':'BTC','quantita':None,'costo_medio_eur':None}]},{},{},[])
        self.assertEqual(len(report['posizioni']),1)
        self.assertEqual(report['posizioni'][0]['token'],'BTC')
        self.assertIsNone(report['posizioni'][0]['quantita'])
        # D1: previously this assertion expected a fake numeric zero.
        # Unknown quantity requires null, explicit state and counted gap.
        self.assertIsNone(report['totale_stimato_eur'])
        self.assertEqual(report['stato_totale'],'NON_DISPONIBILE')
        self.assertEqual(report['posizioni_valorizzate'],0)
        self.assertEqual(report['posizioni_incomplete'],1)
        self.assertTrue(report['totale_parziale'])
        self.assertEqual(report['posizioni_non_aggiornate'],1)
        page=d.render(report)
        self.assertIn('Quantità: non nota',page)
        self.assertIn('Valore posizioni inserite: non disponibile (incompleto)',page)
        self.assertNotIn('Valore posizioni inserite: 0,00 €',page)

    def test_rt_i01_mixed_incomplete_positions_visible_without_fictitious_value(self):
        rows=d.market_pairs_and_ticker(self.pairs,self.t)
        data={'rilevazione_utc':d.NOW().isoformat(),'markets':rows,'trends':{},
              'feed':[],'problemi_feed':[]}
        portfolio={'posizioni':[
            {'token':'BTC','quantita':2,'costo_medio_eur':None},
            {'token':'SOL','quantita':None,'costo_medio_eur':None},
            {'token':'ETH','quantita':3,'costo_medio_eur':None}]}
        report=d.build_report(data,portfolio,{}, {}, [])
        self.assertEqual([x['token'] for x in report['posizioni']],['BTC','SOL','ETH'])
        self.assertEqual(report['posizioni'][0]['valore_eur'],90000)
        self.assertEqual(report['totale_stimato_eur'],90000)
        self.assertTrue(report['totale_parziale'])
        self.assertEqual(report['posizioni_non_aggiornate'],1)
        self.assertNotIn('valore_eur',report['posizioni'][1])
        self.assertNotIn('valore_eur',report['posizioni'][2])
        self.assertEqual(report['posizioni'][2]['quantita'],3)
        page=d.render(report)
        self.assertIn('<h3>SOL</h3><p>Quantità: non nota</p>',page)
        self.assertIn('<h3>ETH</h3><p>Quantità: 3</p>',page)
        self.assertIn('Valore posizioni inserite: 90 000,00 € (incompleto)',page)
        self.assertNotIn('P/L indicativo:',page)

    def test_rt_i01_only_unquoted_quantity_is_not_zero_total(self):
        data={'rilevazione_utc':d.NOW().isoformat(),'markets':{},'trends':{},
              'feed':[],'problemi_feed':[]}
        report=d.build_report(data,{'posizioni':[{'token':'ETH','quantita':3}]},{},{},[])
        page=d.render(report)
        self.assertIn('<h3>ETH</h3><p>Quantità: 3</p>',page)
        self.assertIn('Valore posizioni inserite: non disponibile (incompleto)',page)

    def test_rt_i01_known_zero_is_different_from_missing_quantity(self):
        rows=d.market_pairs_and_ticker(self.pairs,self.t)
        data={'rilevazione_utc':d.NOW().isoformat(),'markets':rows,'trends':{},
              'feed':[],'problemi_feed':[]}
        report=d.build_report(data,{'posizioni':[{'token':'BTC','quantita':0}]},{},{},[])
        self.assertFalse(report['totale_parziale'])
        self.assertEqual(report['posizioni'][0]['valore_eur'],0)
        self.assertIn('Valore posizioni inserite: 0,00 €',d.render(report))

# Copertura G2: coppie arbitrarie senza preferenza SUI/EUR.
import grafico_4h as g
from unittest import mock

class AnyKrakenSpotTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 10, 24, 20, 42, tzinfo=dt.timezone.utc)
        self.pairs = {
            "ADAUSDT": {"wsname": "ADA/USDT", "status": "online"},
            "XXBTZEUR": {"wsname": "XBT/EUR", "status": "online"},
            "SUIPERP": {"wsname": "SUI/EUR", "status": "cancel_only"},
            "ETHUSD.d": {"wsname": "ETH/USD", "status": "online"},
            "BAD": {"wsname": "<svg/onload=alert(1)>/EUR", "status": "online"},
            "DOTGBP": {"wsname": "DOT/GBP", "status": "online"},
        }
        self.calls = []

    def fake(self, endpoint, **params):
        self.calls.append((endpoint, dict(params)))
        if endpoint == "AssetPairs":
            self.assertFalse(params)
            return self.pairs
        self.assertEqual(endpoint, "OHLC")
        self.assertIn(params["pair"], ("ADAUSDT", "DOTGBP", "XXBTZEUR"))
        interval = params["interval"] * 60
        current = (int(self.now.timestamp()) // interval) * interval
        raw = []
        for i in range(81):
            close = 1 + .005*i
            raw.append([current - (80-i)*interval, str(close),
                        str(close+.015), str(close-.015), str(close),
                        "0", "125", 1])
        return {params["pair"]: raw, "last": current}

    def test_market_catalog_includes_non_eur_and_does_not_force_sui(self):
        catalog = serve.spot_catalog(self.fake)
        self.assertEqual(set(catalog), {"ADAUSDT", "XXBTZEUR", "DOTGBP"})
        self.assertEqual(catalog["ADAUSDT"]["quote"], "USDT")
        self.assertEqual(catalog["DOTGBP"]["quote"], "GBP")
        self.assertEqual(catalog["ADAUSDT"]["eligibilita_conto"], "NON_VERIFICATA")
        page = serve.spot_selector(catalog)
        self.assertIn("ADA/USDT", page)
        self.assertIn("DOT/GBP", page)
        self.assertIn('value=""', page)
        self.assertNotIn('value="SUIEUR"', page)
        self.assertNotIn("<svg", page)
        self.assertNotIn("portafoglio", page.lower())

    def test_invalid_nononline_and_injection_pair_are_refused_before_ohlc(self):
        for key in ("SUIEUR", "SUIPERP", "BAD", "../api", "", "<svg>"):
            with self.subTest(key=key):
                self.calls.clear()
                with self.assertRaises(ValueError):
                    serve.load_spot_chart(key, "4h", public_kraken=self.fake,
                                          now=self.now)
                self.assertEqual([ep for ep,_ in self.calls], ["AssetPairs"])

    def test_chart_for_ada_usdt_not_eur_or_sui(self):
        html = serve.load_spot_chart("ADAUSDT", "4h", public_kraken=self.fake,
                                     now=self.now)
        self.assertIn("Grafico ADA/USDT · 4H", html)
        self.assertIn("Volumi scambiati (ADA)", html)
        self.assertIn("pair=ADAUSDT&amp;tf=15m", html)
        self.assertIn("pair=ADAUSDT&amp;tf=1d", html)
        self.assertNotIn("Grafico SUI/EUR", html)
        self.assertNotIn(" SUI';", html)
        self.assertEqual(self.calls[1], ("OHLC", {"pair":"ADAUSDT","interval":240}))

    def test_chart_comparison_link_uses_selected_market_not_sui(self):
        page = serve.load_spot_chart("ADAUSDT", "4h",
                                     public_kraken=self.fake, now=self.now)
        self.assertIn('href="/analisi/spot?pair=ADAUSDT"', page)
        self.assertNotIn('href="/analisi/sui-mtf"', page)
        self.assertNotIn("__COMPARE_URL__", page)
        self.assertIn("precision:5,minMove:0.00001", page)

    def test_graph_quotes_apply_to_levels_confluence_and_ohlcv_not_only_title(self):
        page = serve.load_spot_chart("ADAUSDT", "4h",
                                     public_kraken=self.fake, now=self.now)
        self.assertIn('const quote="USDT";', page)
        self.assertIn("['Livello','Prezzo '+quote,'Origine']", page)
        self.assertNotIn("Prezzo EUR", page)
        self.assertIn("stats.textContent=time+' UTC · O '+priceText.format(row.open)",page)
        self.assertIn("'+quote+' · Vol '",page)
        self.assertIn("priceText.format(Math.min(",page)
        self.assertNotIn("maximumFractionDigits:8",page)
        self.assertNotIn("maximumFractionDigits:6});\n  const supports",page)

    def test_tiny_chart_prices_keep_nonzero_axis_and_ema_values(self):
        seconds = 14400
        start = int(self.now.timestamp() // seconds) * seconds - 81*seconds
        bars=[]
        for i in range(80):
            p=1.1e-9 * (1+i/1000)
            bars.append({"time":start+i*seconds,"open":p,
                "high":p*1.01,"low":p*0.99,"close":p,"volume":10.0})
        frame={"pair":"SHIB/USD","token":"SHIB","pair_key":"SHIBUSD",
            "timeframe":"4H","interval_seconds":seconds,
            "observed_utc":self.now.isoformat(),
            "closed_at_utc":self.now.isoformat(),"candles":bars}
        self.assertGreater(g.ema_points(bars,20)[-1]["value"],0)
        self.assertGreater(g.ema_points(bars,50)[-1]["value"],0)
        page=g.page_from_data(frame)
        self.assertIn("precision:12,minMove:0.000000000001",page)
        self.assertIn('href="/analisi/spot?pair=SHIBUSD"',page)
        self.assertNotIn("precision:5,minMove:0.00001",page)
        self.assertNotIn('"value":0.0}',page)
        self.assertIn("12 decimali",page)

    def test_unrepresentable_chart_price_fails_explicitly(self):
        seconds=14400
        frame={"pair":"MICRO/USD","token":"MICRO","pair_key":"MICROUSD",
            "timeframe":"4H","interval_seconds":seconds,
            "observed_utc":self.now.isoformat(),
            "closed_at_utc":self.now.isoformat(),
            "candles":[{"time":i*seconds,"open":1e-14,"high":1.1e-14,
                       "low":0.9e-14,"close":1e-14,"volume":10}
                       for i in range(80)]}
        with self.assertRaisesRegex(ValueError,"precisione supportata"):
            g.page_from_data(frame)

    def test_four_independent_closed_public_frames_keep_pair_and_quote(self):
        report = serve.load_spot_comparison("ADAUSDT", public_kraken=self.fake,
                                            now=self.now)
        self.assertEqual(report["coppia"], "ADA/USDT")
        self.assertEqual(report["stato"], "COMPLETO")
        self.assertEqual([ep for ep,_ in self.calls],
                         ["AssetPairs","OHLC","OHLC","OHLC","OHLC"])
        self.assertEqual([args["interval"] for ep,args in self.calls[1:]],
                         [15,60,240,1440])
        self.assertTrue(all(args["pair"]=="ADAUSDT" for _,args in self.calls[1:]))
        page = serve.render_sui_comparison(report, pair_key="ADAUSDT")
        self.assertIn("Confronto ADA/USDT",page)
        self.assertIn(" USDT",page)
        self.assertIn(" ADA",page)
        self.assertIn("pair=ADAUSDT&amp;tf=4h",page)
        self.assertNotIn("Confronto SUI/EUR",page)

    def test_incomplete_ohlc_is_not_silently_filled(self):
        def missing(endpoint, **kwargs):
            if endpoint=="OHLC" and kwargs["interval"]==60:
                raise ConnectionError("public OHLC unavailable")
            return self.fake(endpoint,**kwargs)
        report=serve.load_spot_comparison("ADAUSDT",public_kraken=missing,
                                          now=self.now)
        self.assertEqual(report["stato"],"PARZIALE")
        self.assertEqual(report["quadro"],"CONFRONTO_INCOMPLETO")
        self.assertEqual(report["timeframe"][1]["stato"],"NON_DISPONIBILE")

    def test_missing_blank_or_repeated_pair_id_is_rejected(self):
        for path in ("/grafico/spot", "/analisi/spot"):
            for query in ("", "pair=", "pair=A&pair=B", "pair=../../", "pair=bad%00"):
                with self.subTest(path=path, query=query):
                    with self.assertRaises(ValueError):
                        serve.spot_request_pair(path, query)
            self.assertEqual(serve.spot_request_pair(path, "pair=XXBTZEUR"),
                             "XXBTZEUR")
        self.assertIsNone(serve.spot_request_pair("/mercati/spot", ""))

    def test_mobile_search_operates_on_full_catalog_without_default_selection(self):
        page = serve.spot_selector(serve.spot_catalog(self.fake))
        self.assertIn('type="search" id="filtro"', page)
        self.assertIn('name="pair" id="pair" required', page)
        self.assertIn("all.filter(", page)
        self.assertIn("search.addEventListener('input',rebuild)", page)
        self.assertIn("select.value = ''", page)
        self.assertIn("replaceAll('BTC','XBT')", page)
        self.assertIn("replaceAll('DOGE','XDG')", page)
        self.assertIn("Visualizzate le prime 90; affina la ricerca.", page)
        self.assertIn("ADA/USDT",page)
        self.assertIn("DOT/GBP",page)
        self.assertIn("BTC/EUR (Kraken XBT/EUR)",page)
        self.assertIn("il cruscotto KDD e il pulsante Aggiorna",page)

    def test_existing_kdd_shortlist_leads_spot_exploration(self):
        catalog = serve.spot_catalog(self.fake)
        snapshot = {
            "rilevazione_utc": self.now.isoformat(),
            "schede_v02": [
                {"token": "ADA", "coppia_analisi": "ADA/USDT",
                 "categoria": "consolidamento", "esito": "RIESAME MIRATO",
                 "perche_selezionato": "Controllare la chiusura oraria",
                 "sintesi": "Le chiusure sono ancora senza conferma.",
                 "evidenze": ["Volumi in aumento"], "criticita": ["Spread da verificare"],
                 "alternative": [{"pair": "ADA/USDT", "pair_key": "ADAUSDT"}]},
                {"token": "DOT", "coppia_analisi": "DOT/GBP",
                 "categoria": "tentativo di ripartenza", "esito": "DA VERIFICARE",
                 "alternative": [{"pair": "DOT/GBP", "pair_key": "DOTGBP"}]},
            ],
        }
        page = serve.spot_selector(catalog, snapshot=snapshot, now=self.now)
        self.assertLess(page.index("Da esaminare: selezione KDD"),
                        page.index("Esplora qualsiasi altra coppia"))
        self.assertIn('href="/grafico/spot?pair=ADAUSDT&amp;tf=4h"', page)
        self.assertIn('href="/analisi/spot?pair=DOTGBP"', page)
        self.assertIn("Motivo della selezione:", page)
        self.assertIn("Controllare la chiusura oraria", page)
        self.assertIn("Le chiusure sono ancora senza conferma.", page)
        self.assertIn("Elementi osservati:"," ".join(page.split("<")))
        self.assertIn("Volumi in aumento", page)
        self.assertIn("Criticità:", page)
        self.assertIn("Spread da verificare", page)
        self.assertIn("Rilevazione recente", page)
        self.assertIn('const found = needle ? all.filter(', page)
        self.assertIn('}) : [];', page)
        self.assertNotIn("Visualizzate le prime 90; affina la ricerca.' : all", page)

    def test_stale_kdd_shortlist_is_visible_but_identified_as_stale(self):
        catalog = serve.spot_catalog(self.fake)
        snapshot = {
            "rilevazione_utc": (self.now - dt.timedelta(hours=4)).isoformat(),
            "schede_v02": [{"token": "ADA", "coppia_analisi": "ADA/USDT",
                            "esito": "RIESAME MIRATO",
                            "alternative": [{"pair": "ADA/USDT", "pair_key": "ADAUSDT"}]}],
        }
        page = serve.spot_selector(catalog, snapshot=snapshot, now=self.now)
        self.assertIn("RILEVAZIONE DA AGGIORNARE", page)
        self.assertIn("Segnalazioni precedenti: dati da aggiornare", page)
        self.assertIn("Apri KDD completo e aggiorna", page)
        self.assertIn('href="/analisi/spot?pair=ADAUSDT"', page)

    def test_kdd_shortlist_rejects_forged_pair_token_and_escapes_text(self):
        catalog = serve.spot_catalog(self.fake)
        snapshot = {
            "rilevazione_utc": self.now.isoformat(),
            "schede_v02": [
                {"token": "BTC", "coppia_analisi": "ADA/USDT",
                 "alternative": [{"pair": "ADA/USDT", "pair_key": "ADAUSDT"}]},
                {"token": "ADA", "coppia_analisi": "ADA/USDT",
                 "esito": "<svg onload=alert(1)>",
                 "perche_selezionato": "<script>bad()</script>",
                 "alternative": [{"pair": "ADA/USDT", "pair_key": "ADAUSDT"}]},
                {"token": "ADA", "coppia_analisi": "DOT/GBP",
                 "alternative": [{"pair": "DOT/GBP", "pair_key": "DOTGBP"}]},
            ],
        }
        rows = serve.spot_observed_candidates(catalog, snapshot)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pair_key"], "ADAUSDT")
        page = serve.spot_selector(catalog, snapshot=snapshot, now=self.now)
        self.assertIn("&lt;svg", page)
        self.assertNotIn("<svg", page)
        self.assertNotIn("<script>bad()", page)
        self.assertIn("&lt;script&gt;", page)

    def test_no_candidate_scan_does_not_invent_cryptocurrencies(self):
        catalog = serve.spot_catalog(self.fake)
        page = serve.spot_selector(catalog, snapshot={}, now=self.now)
        self.assertIn("Nessun caso", page)
        self.assertIn("Catalogo:", page)
        self.assertNotIn("Da esaminare: selezione KDD", page)

    def test_exchange_pair_alias_retains_original_rest_identity(self):
        catalog = serve.spot_catalog(self.fake)
        self.assertEqual(serve.spot_friendly_label(catalog["XXBTZEUR"]["pair"]),
                         "BTC/EUR (Kraken XBT/EUR)")
        self.assertIn("BTC/EUR (Kraken XBT/EUR)",
                      serve.spot_selector(catalog, snapshot={}, now=self.now))
        self.assertEqual(serve.spot_lookup("XXBTZEUR", catalog)["pair_key"], "XXBTZEUR")

    def test_invalid_frame_prevents_even_catalog_call(self):
        with self.assertRaises(ValueError):
            serve.load_spot_chart("ADAUSDT","invalid",public_kraken=self.fake)
        self.assertEqual(self.calls,[])

    def test_ohlc_mismatched_response_symbol_is_rejected_before_render(self):
        """A valid candle array from ANOTHER token may not inherit selected label."""
        calls = []
        def swapped(endpoint, **params):
            if endpoint == "AssetPairs":
                return self.pairs
            calls.append(params["interval"])
            raw = self.fake(endpoint, **params)
            return {"UNRELATEDBTCUSD": raw[params["pair"]],
                    "last": raw["last"]}
        with self.assertRaises(serve.KrakenPairMismatch):
            serve.load_spot_chart("ADAUSDT", "4h",
                                  public_kraken=swapped, now=self.now)
        self.assertEqual(calls, [240])
        calls.clear()
        result = serve.load_spot_comparison(
            "ADAUSDT", public_kraken=swapped, now=self.now)
        self.assertEqual(calls, [15, 60, 240, 1440])
        self.assertEqual(result["stato"], "PARZIALE")
        self.assertEqual(result["quadro"], "CONFRONTO_INCOMPLETO")
        self.assertTrue(all(f["stato"] == "NON_DISPONIBILE"
                            for f in result["timeframe"]))

    def test_ohlc_alias_return_name_allowed_only_if_declared_by_kraken(self):
        pairs = dict(self.pairs)
        pairs["XXBTZEUR"] = dict(pairs["XXBTZEUR"], altname="XBTEUR")
        def alias(endpoint, **params):
            if endpoint == "AssetPairs":
                return pairs
            raw = self.fake(endpoint, **params)
            assert params["pair"] == "XXBTZEUR"
            return {"XBTEUR": raw["XXBTZEUR"], "last": raw["last"]}
        graph = serve.load_spot_chart(
            "XXBTZEUR", "4h", public_kraken=alias, now=self.now)
        self.assertIn("Grafico BTC/EUR", graph)
        self.assertIn("Volumi scambiati (BTC)", graph)
        self.assertIn("Kraken usa XBT per BTC", graph)
        self.assertNotIn("Grafico SUI/EUR", graph)
        compare = serve.load_spot_comparison("XXBTZEUR",
                                             public_kraken=alias, now=self.now)
        self.assertEqual(compare["coppia"], "XBT/EUR")  # original Kraken identity
        view = serve.render_sui_comparison(compare, pair_key="XXBTZEUR")
        self.assertIn("Confronto BTC/EUR (Kraken XBT/EUR)", view)
        self.assertIn("Volume ultima candela:", view)
        self.assertIn(" BTC;", view)

    def test_micro_volume_remains_nonzero_in_quote_aware_comparison(self):
        report = serve.load_spot_comparison(
            "ADAUSDT", public_kraken=self.fake, now=self.now)
        self.assertEqual(report["stato"], "COMPLETO")
        report["timeframe"][0]["volume"] = 1e-9
        report["timeframe"][1]["volume"] = 0.0
        report["timeframe"][2]["volume"] = 1.234567891
        page = serve.render_sui_comparison(report, pair_key="ADAUSDT")
        self.assertIn("Volume ultima candela: 1e-09 ADA", page)
        self.assertIn("Volume ultima candela: 0 ADA", page)
        self.assertIn("Volume ultima candela: 1.234567891 ADA", page)
        self.assertNotIn("Volume ultima candela: 0.0000 ADA", page)
        self.assertIn("controlla", page)
        self.assertNotIn("4H separato conserva il", page)

    def test_tiny_crypto_quote_displays_significant_price_not_fake_zero(self):
        report = serve.load_spot_comparison(
            "ADAUSDT", public_kraken=self.fake, now=self.now)
        self.assertEqual(report["stato"], "COMPLETO")
        first = report["timeframe"][0]
        first["close"] = 0.000000001234567
        first["ema20"] = 0.000000000987654
        first["ema50"] = 0.000000000876543
        page = serve.render_sui_comparison(report, pair_key="ADAUSDT")
        self.assertIn("1.234567e-09 USDT", page)
        self.assertIn("9.87654e-10 USDT", page)
        self.assertNotIn("0.00000 USDT", page)

    def test_ohlc_response_two_symbols_fail_closed_even_if_one_matches(self):
        def double(endpoint, **params):
            if endpoint == "AssetPairs":
                return self.pairs
            raw = self.fake(endpoint, **params)
            raw["EXTRAUSD"] = raw[params["pair"]]
            return raw
        with self.assertRaises(serve.KrakenPairMismatch):
            serve.load_spot_chart("ADAUSDT", "4h",
                                  public_kraken=double, now=self.now)

    def test_none_catalog_is_fail_closed(self):
        with self.assertRaises(serve.KrakenMarketDataUnavailable):
            serve.spot_catalog(lambda endpoint: {})
        with self.assertRaises(serve.KrakenMarketDataUnavailable):
            serve.spot_catalog(lambda endpoint: [])

    def test_invalid_ohlc_is_source_error_not_invalid_selection(self):
        def corrupted(endpoint, **params):
            if endpoint == "AssetPairs":
                return self.pairs
            return {"ADAUSDT": [], "last": 0}
        with self.assertRaises(serve.KrakenMarketDataUnavailable):
            serve.load_spot_chart("ADAUSDT", "4h",
                                  public_kraken=corrupted, now=self.now)
        with self.assertRaises(ValueError):
            serve.load_spot_chart("NOT_A_PAIR", "4h",
                                  public_kraken=corrupted, now=self.now)

    def test_local_http_routes_distinguish_400_invalid_pair_from_503_upstream(self):
        """Real KDD HTTP Handler with synthetic exchange only; no phone/files."""
        import threading
        import urllib.request
        import urllib.error
        from http.server import ThreadingHTTPServer
        def fake_provider(endpoint, **params):
            if endpoint == "AssetPairs":
                return self.pairs
            if endpoint == "OHLC":
                # Upstream data failure after valid catalog lookup.
                return {"ADAUSDT": [], "last": 0}
            raise AssertionError("Private or unexpected API call")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        server.daemon_threads = True
        with (mock.patch.object(serve, "PORT", server.server_address[1]),
              mock.patch.object(serve.desk, "kraken", side_effect=fake_provider)):
            worker = threading.Thread(target=server.serve_forever,
                                      daemon=True)
            worker.start()
            try:
                base = "http://127.0.0.1:" + str(server.server_address[1])
                for route, status in (
                    ("/mercati/spot", 200),
                    ("/grafico/spot", 400),
                    ("/grafico/spot?pair=BADPAIR", 400),
                    ("/grafico/spot?pair=ADAUSDT&tf=4h", 503),
                    ("/analisi/spot?pair=ADAUSDT", 200)):
                    with self.subTest(route=route):
                        try:
                            with opener.open(base + route, timeout=5) as response:
                                actual = response.status
                                page = response.read().decode("utf-8")
                        except urllib.error.HTTPError as error:
                            actual = error.code
                            page = error.read().decode("utf-8")
                        self.assertEqual(actual, status)
                        if route.startswith("/analisi/spot"):
                            self.assertIn("PARZIALE", page)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=3)

    def test_catalog_provider_outage_is_unavailable_not_bad_user_query(self):
        def unavailable(endpoint, **params):
            if endpoint == "AssetPairs":
                return {}
            raise AssertionError("Should not call OHLC")
        with self.assertRaises(serve.KrakenMarketDataUnavailable):
            serve.load_spot_chart("ADAUSDT", "4h", public_kraken=unavailable,
                                  now=self.now)

    def test_legacy_sui_url_retained_but_no_longer_on_home(self):
        page=serve.with_controls("<h2>1 · Decisioni e posizioni</h2>")
        self.assertIn('href=\'/mercati/spot\'',page)
        self.assertNotIn('href=\'/grafico/sui-4h\'',page)
        self.assertNotIn('href=\'/analisi/sui-mtf\'',page)
        self.assertTrue(callable(serve.load_sui_chart))
        self.assertTrue(callable(serve.load_sui_comparison))

    def test_home_with_present_report_never_links_fixed_sui_mtf(self):
        # Unlike report-free preflight, exercise the real report-loaded home.
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report = {
                'rilevazione_utc': self.now.isoformat(),
                'stato_totale': 'PARZIALE',
                'totale_stimato_eur': 0,
                'posizioni': [{'token': 'BTC', 'decisione': 'NESSUNA DECISIONE',
                               'valore_eur': 0, 'note': []}],
                'schede_v02': [],
            }
            (root / 'ultimo_report.json').write_text(
                json.dumps(report), encoding='utf-8')
            with mock.patch.object(serve.desk, 'DIR', root), \
                 mock.patch('scripts.kdd_drive_exchange.receive_synced',
                            side_effect=RuntimeError('bridge isolated for this test')):
                page = serve.with_controls("<h2>1 · Decisioni e posizioni</h2>")
        self.assertIn('Patrimonio: PARZIALE', page)
        self.assertIn('<b>BTC</b>', page)
        self.assertIn("href='/mercati/spot'", page)
        self.assertNotIn("href='/analisi/sui-mtf'", page)
        self.assertNotIn("href='/grafico/sui-4h'", page)
        self.assertIn('Aggiorna dati ora', page)

    def test_user_selected_pair_not_derived_from_portfolio(self):
        with mock.patch.object(serve.desk, "load",
                               side_effect=AssertionError("no private local files")):
            catalog=serve.spot_catalog(self.fake)
            report=serve.load_spot_comparison("DOTGBP",public_kraken=self.fake,
                                              now=self.now)
        self.assertIn("DOTGBP",catalog)
        self.assertEqual(report["coppia"],"DOT/GBP")


    def test_rt02_actual_javascript_volume_formatter_preserves_small_positive(self):
        """Execute the function extracted from the generated chart, not source grep."""
        import re, shutil, subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("Node JS runtime missing; formatter execution not verified")
        sec = 14400
        start = int(self.now.timestamp() // sec) * sec - 80*sec
        frame = {"pair":"ADA/USDT", "token":"ADA", "pair_key":"ADAUSDT",
                 "timeframe":"4H", "interval_seconds":sec,
                 "observed_utc":self.now.isoformat(),
                 "closed_at_utc":self.now.isoformat(),
                 "candles":[{"time":start+i*sec,"open":1., "high":1.1,
                            "low":.9,"close":1., "volume":1e-9} for i in range(80)]}
        page = g.page_from_data(frame, now=self.now)
        fn = re.search(r'  function formatVolume\(value\)\{.*?\n  \}', page, re.S)
        self.assertIsNotNone(fn)
        run = subprocess.run([node, "-e", fn.group(0)+
            "\nconsole.log(JSON.stringify([0,1e-9,1e-15,1.23456789,123456].map(formatVolume)))"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        shown = json.loads(run.stdout)
        self.assertEqual(shown[0], "0")
        self.assertTrue(all(v not in ("0","0,0","-0") for v in shown[1:3]))
        self.assertIn("1", shown[3])
        self.assertIn("123", shown[4])
        self.assertIn("Vol '+formatVolume(row.volume)+' '+\"ADA\"", page)
        self.assertIn('"volume":1e-09', page)

    def test_rt03_rejects_prices_colliding_at_12dp_inside_same_candle(self):
        sec=14400
        start=int(self.now.timestamp() // sec)*sec-80*sec
        frame={"pair":"MICRO/USD","token":"MICRO","pair_key":"MICROUSD",
               "timeframe":"4H","interval_seconds":sec,
               "observed_utc":self.now.isoformat(),
               "closed_at_utc":self.now.isoformat(),
               "candles":[{"time":start+i*sec,"open":1.49e-12,
                           "high":2e-12,"low":1e-12,"close":1.49e-12,
                           "volume":1} for i in range(80)]}
        self.assertEqual(f"{1.0e-12:.12f}", f"{1.49e-12:.12f}")
        with self.assertRaisesRegex(ValueError, "distinti non rappresentabili"):
            g.page_from_data(frame, now=self.now)
        # One actual twelfth-decimal tick DOES remain representable.
        for row in frame["candles"]:
            row.update(open=2e-12, high=3e-12, low=1e-12, close=2e-12)
        self.assertIn("precision:12,minMove:0.000000000001",
                      g.page_from_data(frame,now=self.now))

    def test_rt04_alias_rest_collision_fails_closed_before_ohlc(self):
        pairs={"AAAUSD":{"wsname":"AAA/USD","status":"online","altname":"BBBUSD"},
               "BBBUSD":{"wsname":"BBB/USD","status":"online"}}
        calls=[]
        def fake(endpoint, **kwargs):
            calls.append(endpoint)
            if endpoint=="AssetPairs": return pairs
            raise AssertionError("Ambiguous market must not request OHLC")
        with self.assertRaisesRegex(serve.KrakenMarketDataUnavailable, "ambigua"):
            serve.load_spot_chart("AAAUSD","4h",public_kraken=fake,now=self.now)
        self.assertEqual(calls, ["AssetPairs"])
        # Even a non-online key must not borrow an online pair's alias.
        pairs["BBBUSD"]["status"]="cancel_only"
        with self.assertRaisesRegex(serve.KrakenMarketDataUnavailable, "ambigua"):
            serve.spot_catalog(fake)
        # Two unique names with a valid declared alias remain supported.
        pairs["AAAUSD"]["altname"]="AAAALT"
        self.assertEqual(serve.spot_catalog(fake)["AAAUSD"]["altname"],"AAAALT")

    def test_rt05_single_chart_marks_fresh_stale_and_nonverifiable(self):
        sec=14400
        start=int(self.now.timestamp() // sec)*sec-80*sec
        frame={"pair":"ADA/USDT","token":"ADA","pair_key":"ADAUSDT",
               "timeframe":"4H","interval_seconds":sec,
               "observed_utc":self.now.isoformat(),
               "closed_at_utc":dt.datetime.fromtimestamp(
                   start+80*sec,dt.timezone.utc).isoformat(),
               "candles":[{"time":start+i*sec,"open":1.,"high":1.1,
                           "low":.9,"close":1.,"volume":1.} for i in range(80)]}
        current=g.page_from_data(frame,now=self.now)
        self.assertIn("DATI RECENTI VERIFICATI",current)
        self.assertIn("Ultima candela CHIUSA:",current)
        old=g.page_from_data(frame,now=self.now+dt.timedelta(days=5))
        self.assertIn("GRAFICO STORICO / SCADUTO",old)
        self.assertIn('class="warning" role="status">GRAFICO STORICO / SCADUTO',old)
        bad=dict(frame,observed_utc="bad")
        self.assertIn("DATI INCOMPLETI O NON VERIFICABILI",
                      g.page_from_data(bad,now=self.now))
        limited=dict(frame,candles=frame["candles"][:35])
        self.assertIn("DATI INCOMPLETI O NON VERIFICABILI",
                      g.page_from_data(limited,now=self.now))

    def test_rt_ui_integrated_links_and_preview_remain_separate(self):
        catalog=serve.spot_catalog(self.fake)
        for preview in (False,True):
            view=serve.spot_selector(catalog, snapshot={}, now=self.now,preview=preview)
            if preview:
                self.assertIn("preview pubblica isolata",view)
                self.assertIn('href="http://127.0.0.1:8765/"',view)
            else:
                self.assertIn("KDD patrimoniale originale",view)
                self.assertIn('href="/"',view)
                self.assertNotIn("porta 8765",view)
                self.assertNotIn("non il KDD completo",view)
        self.assertIn("negoziabilità per il conto italiano",view)


    def _r2_frame(self, *, frame="4H", candles=80):
        seconds={"15m":900,"1H":3600,"4H":14400,"1D":86400}[frame]
        close_end=int(self.now.timestamp()//seconds)*seconds
        start=close_end-candles*seconds
        series=[{"time":start+i*seconds, "open":1e-8, "high":1e-8+2e-12,
                 "low":1e-8-2e-12,
                 "close":1e-8+(i%2)*1e-12, "volume":1e-9}
                for i in range(candles)]
        return {"pair":"ADA/USDT","pair_key":"ADAUSDT","token":"ADA",
                "timeframe":frame,"interval_seconds":seconds,
                "observed_utc":self.now.isoformat(),
                "closed_at_utc":dt.datetime.fromtimestamp(
                    close_end,dt.timezone.utc).isoformat(),
                "candles":series}

    def test_r2_rt03_ema20_50_subtick_does_not_reject_ohlc(self):
        frame=self._r2_frame()
        points20=g.ema_points(frame["candles"],20)
        points50=g.ema_points(frame["candles"],50)
        self.assertTrue(points20 and points50)
        # Red Team R1 counterexample: distinct EMA20 values at <12th decimal.
        # Collisions may occur on alternate EMA samples, not necessarily
        # on adjacent points of an oscillating sequence.
        buckets={}
        for point in points20:
            buckets.setdefault(f'{point["value"]:.12f}',set()).add(point["value"])
        self.assertTrue(any(len(values)>1 for values in buckets.values()))
        snapshot=json.dumps(frame["candles"],sort_keys=True)
        page=g.page_from_data(frame,now=self.now)
        self.assertIn('precision:12,minMove:0.000000000001',page)
        self.assertIn('"ema20":',page)
        self.assertIn('"ema50":',page)
        self.assertEqual(json.dumps(frame["candles"],sort_keys=True),snapshot)

    def test_r2_rt03_derived_levels_subtick_not_a_rejection(self):
        frame=self._r2_frame()
        real=g.technical_from_candles(frame["candles"],interval_seconds=14400)
        self.assertTrue(real["ema50"])
        # Deliberately inject valid tiny calculated variations in all families:
        # they are derived values, not original exchange prices.
        derived=dict(real)
        derived["pivots"]={
            "reference_day_utc":"2026-10-23","P":1e-8,
            "S1":1.0000500e-8,"S2":1.0000504e-8,"S3":1.0000510e-8,
            "R1":1.0000500e-8,"R2":1.0000504e-8,"R3":1.0000510e-8}
        derived["structure"]={
            "supports":[{"price":1.0000500e-8,"touches":2,"last_swing_time":0},
                        {"price":1.0000504e-8,"touches":2,"last_swing_time":0}],
            "resistances":[{"price":1.0000510e-8,"touches":2,"last_swing_time":0},
                           {"price":1.0000514e-8,"touches":2,"last_swing_time":0}]}
        with mock.patch.object(g,"technical_from_candles",return_value=derived):
            page=g.page_from_data(frame,now=self.now)
        self.assertIn('"pivots":',page)
        self.assertIn('"supports":',page)
        self.assertIn('"resistances":',page)
        self.assertIn('"price":1.0000504e-08',page)
        self.assertIn("12 decimali",page)

    def test_r2_rt03_true_ohlc_collision_rejected_cross_candle_and_intra(self):
        frame=self._r2_frame()
        frame["candles"][1]["close"]=1.000049e-8
        # Original alternating series should remain distinguishable at 12dp;
        # the new close has a distinct source value but collides after rounding.
        with self.assertRaisesRegex(ValueError,"distinti non rappresentabili"):
            g.page_from_data(frame,now=self.now)
        frame=self._r2_frame()
        frame["candles"][0].update(open=1e-12,low=1e-12,
                                    close=1.49e-12,high=2e-12)
        with self.assertRaisesRegex(ValueError,"distinti non rappresentabili"):
            g.page_from_data(frame,now=self.now)

    def test_r2_rt05_temporal_integrity_all_frames(self):
        for frame in ("15m","1H","4H","1D"):
            with self.subTest(frame=frame):
                data=self._r2_frame(frame=frame)
                self.assertEqual(g.summarize_timeframe(data,now=self.now)["stato"],
                                 "AGGIORNATO")
                self.assertIn("DATI RECENTI VERIFICATI",g.page_from_data(
                    data,now=self.now))
                wrongs=[]
                wrongs.append(dict(data,observed_utc="2020-01-01T00:00:00+00:00"))
                wrongs.append(dict(data,observed_utc="not-a-date"))
                wrongs.append(dict(data,observed_utc="2026-10-30T00:00:00+00:00"))
                wrongs.append(dict(data,closed_at_utc="not-a-date"))
                wrongs.append(dict(data,closed_at_utc=data["observed_utc"]))
                wrongs.append(dict(data,closed_at_utc="2026-10-30T00:00:00+00:00"))
                wrongs.append(dict(data,closed_at_utc="2020-01-01T00:00:00+00:00"))
                wrongs.append(dict(data,observed_utc="2026-10-24T20:00:00"))
                wrongs.append(dict(data,interval_seconds=5))
                wrongs.append(dict(data,candles=data["candles"][:-1]))
                future=dict(data)
                future["candles"]=list(data["candles"])
                future["candles"][-1]=dict(data["candles"][-1],
                                          time=data["candles"][-1]["time"]+
                                               data["interval_seconds"])
                wrongs.append(future)
                for bad in wrongs:
                    with self.assertRaises((ValueError,TypeError,KeyError)):
                        g.summarize_timeframe(bad,now=self.now)
                    page=g.page_from_data(bad,now=self.now)
                    self.assertIn(
                        'class="warning" role="status">DATI INCOMPLETI O NON VERIFICABILI',
                        page)
                stale=g.page_from_data(
                    data,now=self.now+dt.timedelta(days=5))
                self.assertIn("GRAFICO STORICO / SCADUTO",stale)

    def test_r2_rt05_actual_browser_clock_and_visibility_transition(self):
        import re, shutil, subprocess
        node=shutil.which("node")
        if not node:
            self.skipTest("Node unavailable: browser freshness JavaScript not executed")
        frame=self._r2_frame()
        page=g.page_from_data(frame,now=self.now)
        snippet=re.search(
            r'const freshnessValid=.*?(?=\ntry \{)',page,re.S)
        self.assertIsNotNone(snippet)
        clock_ms=int(self.now.timestamp()*1000)
        # Execute the REAL generated JS with a simulated DOM, time jump and
        # visibility/focus hooks. No network, no reload or candle alteration.
        script="""
const vm=require('node:vm');
let clock=__CLOCK__;
const indicator={textContent:'',className:''};
const events={};const intervals=[];
const context={
  document:{getElementById:()=>indicator,addEventListener:(n,fn)=>{events[n]=fn}},
  window:{addEventListener:(n,fn)=>{events[n]=fn}},
  setInterval:(fn,ms)=>intervals.push([fn,ms]),
  Date:{now:()=>clock},Math,Number,
};
vm.runInNewContext(__SNIPPET__,context);
if(!indicator.textContent.includes('DATI RECENTI VERIFICATI'))
  throw Error('initial not fresh: '+indicator.textContent);
if(intervals.length!==1||intervals[0][1]>15000)throw Error('no timed clock');
if(!events.visibilitychange||!events.focus)throw Error('no focus events');
clock += 6*86400000;
events.visibilitychange();
if(!indicator.textContent.includes('GRAFICO STORICO / SCADUTO'))
  throw Error('not stale on visibility: '+indicator.textContent);
clock += 86400000;
events.focus();
if(!indicator.textContent.includes('SCADUTO')) throw Error('focus lost');
console.log('BROWSER_CLOCK_PASS');
""".replace("__CLOCK__",str(clock_ms)).replace(
            "__SNIPPET__",json.dumps(snippet.group(0)))
        run=subprocess.run([node,"-e",script],capture_output=True,
                           text=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn("BROWSER_CLOCK_PASS",run.stdout)
        self.assertNotIn("fetch(",snippet.group(0))
        self.assertNotIn("location.reload",snippet.group(0))


    def _r3_pivot_frame(self, timeframe, pair):
        """Actual complete UTC previous day; no synthetic pivot formula."""
        seconds={"15m":900,"1H":3600,"4H":14400,"1D":86400}[timeframe]
        count=200 if timeframe=="15m" else 80
        end=int(self.now.timestamp()//seconds)*seconds
        start=end-count*seconds
        token=pair.split("/")[0]
        return {"pair":pair,"pair_key":pair.replace("/",""),"token":token,
                "timeframe":timeframe,"interval_seconds":seconds,
                "observed_utc":self.now.isoformat(),
                "closed_at_utc":dt.datetime.fromtimestamp(
                    end,dt.timezone.utc).isoformat(),
                "candles":[{"time":start+i*seconds,
                            "open":1e-8,"high":2.49997e-8,
                            "low":1e-8,"close":1e-8,"volume":1e-9}
                           for i in range(count)]}

    def _r3_render_actual_javascript(self, page):
        """Run the exact generated browser script with a minimal DOM stub."""
        import subprocess,shutil
        node=shutil.which("node")
        if not node:
            self.skipTest("Node missing: R3 JavaScript not executed")
        script_src=page.split('<script>\n(function(){',1)[1].split('</script>',1)[0]
        harness=r"""
const elements={};
function el(tag){
  return {tag:tag||'',textContent:'',children:[],checked:true,disabled:false,
    hidden:false,parentElement:{title:''},clientWidth:700,clientHeight:420,
    style:{},className:'',classList:{add(){}},
    addEventListener(){},appendChild(c){this.children.push(c);return c;}};
}
const node=id=>elements[id]??(elements[id]=el(id));
global.document={
  getElementById:node, querySelector:node, createElement:el,
  addEventListener(){}
};
global.window={addEventListener(){}};
global.requestAnimationFrame=fn=>fn();
global.setInterval=()=>0;
global.ResizeObserver=class{observe(){}};
const chartSeries=()=>({
  setData(){},applyOptions(){},
  createPriceLine(){return {applyOptions(){}};},
  removePriceLine(){},priceToCoordinate(){return 100;}
});
const makeChart=()=>({
  addSeries:()=>chartSeries(),
  timeScale:()=>({
    fitContent(){},subscribeVisibleLogicalRangeChange(){},
    setVisibleLogicalRange(){}
  }),
  applyOptions(){},subscribeCrosshairMove(){}
});
global.LightweightCharts={createChart:()=>makeChart(),
  CandlestickSeries:{},HistogramSeries:{},LineSeries:{}};
window.LightweightCharts=global.LightweightCharts;
"""
        final=r"""
function walk(root,out=[]){
  for(const c of root.children){
    if(c.tag==='tr')out.push(c.children.map(x=>x.textContent));
    walk(c,out);
  }
  return out;
}
const report={
  graph:node('graph-status').textContent,
  summary:node('#tech-summary').textContent,
  near:node('nearby-summary').textContent,
  stats:node('candle-stats').textContent,
  table:walk(node('levels-list'))
};
if(!report.graph.includes('Grafico generato'))
  throw Error('Full generated JS failed: '+report.graph);
console.log(JSON.stringify(report));
"""
        run=subprocess.run([node,"-e",harness+"\n(function(){"+script_src+
                                    "\n"+final],
                           capture_output=True,text=True,timeout=12)
        self.assertEqual(run.returncode,0,run.stderr[:2500])
        return json.loads(run.stdout.strip().splitlines()[-1])

    def test_r3_rt03_real_pivot_positive_subtick_all_timeframes_quotes(self):
        """Real formulas, generated JS and rendered pivot tables for 4 timeframes."""
        import re,subprocess,shutil
        node=shutil.which("node")
        if not node: self.skipTest("Node missing")
        targets=(("15m","ADA/USDT"),("1H","DOT/GBP"),
                 ("4H","ETH/USD"),("1D","SUI/EUR"))
        for tf,pair in targets:
            with self.subTest(timeframe=tf,pair=pair):
                frame=self._r3_pivot_frame(tf,pair)
                original=json.dumps(frame["candles"],sort_keys=True)
                pivot=g.daily_pivots(frame["candles"],frame["interval_seconds"])
                self.assertIsNotNone(pivot,"Fixture must contain full previous UTC day")
                s2=pivot["S2"]
                self.assertGreater(s2,0)
                self.assertLess(s2,1e-11)
                html=g.page_from_data(frame,now=self.now)
                self.assertEqual(json.dumps(frame["candles"],sort_keys=True),original)
                self.assertIn('precision:11,minMove:0.00000000001',html)
                self.assertIn('const quote='+json.dumps(pair.split("/")[1])+';',html)
                self.assertIn('"S2":',html)
                report=self._r3_render_actual_javascript(html)
                table={row[0]:row[1] for row in report["table"]
                       if len(row)==3 and row[0] in ("S2","P","EMA20","EMA50")}
                self.assertIn("S2",table)
                self.assertRegex(table["S2"],r'[1-9]')
                self.assertIn("e-",table["S2"])
                self.assertNotIn(table["S2"],("0","-0","−0"))
                self.assertIn("EMA20",report["summary"])
                self.assertIn("Pivot del",report["summary"])
                self.assertIn(" C ",report["stats"])
                self.assertNotIn("NaN",report["stats"])
                self.assertIn(pair.split("/")[1],report["stats"])
                # Compare direct locale baseline to actual sub-tick fallback.
                js=re.search(
                    r'  const basePriceText=.*?(?=\n  const supports=)',html,re.S)
                self.assertIsNotNone(js)
                values=[0,s2,-s2,1.23456789,2.5e-8,1e-15,-1e-15]
                program=js.group(0)+"\nconsole.log(JSON.stringify(" + (
                    json.dumps(values)+".map(v=>priceText.format(v))));")
                out=subprocess.run([node,"-e",program],
                                   capture_output=True,text=True,timeout=10)
                self.assertEqual(out.returncode,0,out.stderr)
                rendered=json.loads(out.stdout)
                self.assertEqual(rendered[0],"0")
                self.assertNotIn(rendered[1],("0","-0","−0"))
                self.assertNotIn(rendered[2],("0","-0","−0"))
                self.assertTrue(rendered[2].startswith("-"))
                self.assertIn("1,",rendered[3])
                self.assertNotEqual(rendered[4],"0")
                self.assertNotEqual(rendered[5],"0")
                self.assertTrue(rendered[6].startswith("-"))

    def test_r3_rt03_actual_html_derivative_zero_negative_and_confluence(self):
        """Run every text path: EMA summary, S/R, pivot table and confluence."""
        frame=self._r3_pivot_frame("4H","DOT/GBP")
        technical=g.technical_from_candles(frame["candles"],
                                            interval_seconds=14400)
        positive=technical["pivots"]["S2"]
        self.assertGreater(positive,0)
        negative=-positive
        modified={
            "ema20":[{"time":frame["candles"][-1]["time"],"value":positive}],
            "ema50":[{"time":frame["candles"][-1]["time"],"value":negative}],
            "pivots":dict(technical["pivots"],S2=positive,S3=negative),
            "structure":{
                "supports":[{"price":positive,"touches":2,"last_swing_time":0}],
                "resistances":[{"price":negative,"touches":2,"last_swing_time":0}]
            }
        }
        with mock.patch.object(g,"technical_from_candles",return_value=modified):
            html=g.page_from_data(frame,now=self.now)
        self.assertIn('"value":',html)
        self.assertIn('"S2":',html)
        self.assertIn('"S3":',html)
        report=self._r3_render_actual_javascript(html)
        self.assertNotIn("EMA20: 0",report["summary"])
        self.assertNotIn("EMA50: -0",report["summary"])
        self.assertIn("e-",report["summary"])
        self.assertIn("e-",report["near"])
        self.assertIn("GBP",report["near"])
        tab={row[0]:row[1] for row in report["table"]
             if len(row)==3}
        for key in ("EMA20","EMA50","S2","S3"):
            self.assertIn(key,tab)
            self.assertNotIn(tab[key],("0","-0","−0"))
            self.assertIn("e-",tab[key])
        self.assertTrue(any(row[1].startswith("-") and "e-" in row[1]
                            for row in report["table"] if len(row)==3))
        # The fallback must not turn genuine exact zero into scientific text.
        # Normal OHLC candles continue using the same shared formatter.
        self.assertIn(" O 0,00000001",report["stats"])

    def test_r3_rt03_regression_ema_and_true_original_ohlc_guard(self):
        frame=self._r2_frame()
        self.assertIn('"ema20":',g.page_from_data(frame,now=self.now))
        self.assertIn('"ema50":',g.page_from_data(frame,now=self.now))
        wrong=self._r2_frame()
        wrong["candles"][0].update(open=1e-12,high=2e-12,low=1e-12,close=1.49e-12)
        with self.assertRaisesRegex(ValueError,"distinti non rappresentabili"):
            g.page_from_data(wrong,now=self.now)
        old=self._r2_frame()
        old["observed_utc"]="2020-01-01T00:00:00+00:00"
        self.assertIn("DATI INCOMPLETI O NON VERIFICABILI",
                      g.page_from_data(old,now=self.now))


    def test_r4_confluence_real_dom_negative_and_opposite_signs(self):
        """Counterexample must run actual generated HTML/JS, not a copied formula."""
        from unittest import mock
        frame=self._r3_pivot_frame("4H","DOT/GBP")
        stamp=frame["candles"][-1]["time"]
        technical={
            "ema20":[{"time":stamp,"value":1e-8}],
            "ema50":[{"time":stamp,"value":-1.5e-8}],
            "structure":{
                "supports":[{"price":-4e-8,"touches":2,"last_swing_time":0}],
                "resistances":[]},
            "pivots":{
                "reference_day_utc":"2026-10-26","P":2.25e-8,
                "S1":-3e-8,"S2":-5e-8,"S3":-7e-8,
                "R1":6e-8,"R2":8e-8,"R3":1e-7}
        }
        with mock.patch.object(g,"technical_from_candles",return_value=technical):
            page=g.page_from_data(frame,now=self.now)
        report=self._r3_render_actual_javascript(page)
        self.assertIn("Nessuna vicinanza multi-fonte entro 0,5%",report["near"],
                      "False grouping of negative or cross-sign levels")
        # The rejected levels remain visible with their exact signed values
        # in the independent levels table; only confluence grouping changes.
        rows={row[0]:row[1] for row in report["table"] if len(row)==3}
        for name in ("EMA50","S1","S2","S3"):
            self.assertIn(name,rows)
            self.assertTrue(rows[name].startswith("-"),(name,rows[name]))
        self.assertIn("EMA20",rows)

    def test_r4_confluence_real_dom_positive_threshold_and_overflow(self):
        """Positive near/far and huge values must use the full browser DOM path."""
        from unittest import mock
        frame=self._r3_pivot_frame("4H","ADA/USDT")
        stamp=frame["candles"][-1]["time"]

        def check(pivot_price,ema_price):
            technical={
                "ema20":[{"time":stamp,"value":ema_price}],
                "ema50":[],
                "structure":{"supports":[],"resistances":[]},
                "pivots":{
                    "reference_day_utc":"2026-10-26","P":pivot_price,
                    "S1":-10.0,"S2":-20.0,"S3":-30.0,
                    "R1":40.0,"R2":80.0,"R3":160.0}
            }
            with mock.patch.object(g,"technical_from_candles",return_value=technical):
                page=g.page_from_data(frame,now=self.now)
            return self._r3_render_actual_javascript(page)

        close=check(1.0049e-8,1e-8)
        self.assertIn("Vicinanze entro 0,5% (solo descrittive):",close["near"])
        self.assertIn("EMA20",close["near"])
        self.assertIn("P Pivot",close["near"])
        far=check(1.0051e-8,1e-8)
        self.assertIn("Nessuna vicinanza multi-fonte",far["near"],
                      "A spread above 0.5% must be rejected")
        # Old code computes 0.5*(1e308+1.25e308)==Infinity and reports a
        # false 0% difference. A ratio avoids the overflowing sum.
        huge_far=check(1.25e308,1e308)
        self.assertIn("Nessuna vicinanza multi-fonte",huge_far["near"])



    def _r5_confluence_full_dom(self, ema20, ema50, pivot_p):
        """Full generated graph JavaScript with independent selected technical levels."""
        from unittest import mock
        frame=self._r3_pivot_frame("4H","ADA/USDT")
        stamp=frame["candles"][-1]["time"]
        technical={
            "ema20":([] if ema20 is None else [{"time":stamp,"value":ema20}]),
            "ema50":([] if ema50 is None else [{"time":stamp,"value":ema50}]),
            "structure":{"supports":[],"resistances":[]},
            "pivots":{
                "reference_day_utc":"2026-10-26",
                "P":pivot_p,"S1":10.0,"S2":20.0,"S3":30.0,
                "R1":110.0,"R2":120.0,"R3":130.0}
        }
        with mock.patch.object(g,"technical_from_candles",return_value=technical):
            html=g.page_from_data(frame,now=self.now)
        return self._r3_render_actual_javascript(html)

    def test_r5_redteam_bridged_cross_family_survives_same_family(self):
        """Red Team 6447216348: 100/100.4/100.8 must expose EMA50/P."""
        extended=self._r5_confluence_full_dom(100.0,100.4,100.8)
        text=extended["near"]
        self.assertIn("Vicinanze entro 0,5% (solo descrittive):",text)
        self.assertIn("EMA50 EMA",text)
        self.assertIn("P Pivot",text)
        self.assertNotIn("Nessuna vicinanza multi-fonte",text)
        rows={row[0]:row[1] for row in extended["table"] if len(row)==3}
        for level in ("EMA20","EMA50","P"):
            self.assertIn(level,rows)

    def test_r5_overlapping_cross_family_windows_do_not_merge_extrema(self):
        """The distinct admissible windows 100-100.3 and 100.3-100.6 must survive."""
        reported=self._r5_confluence_full_dom(100.0,100.6,100.3)["near"]
        self.assertIn("EMA20 EMA",reported)
        self.assertIn("EMA50 EMA",reported)
        # The Pivot must be used in both valid descriptions; 100->100.6
        # is outside 0.5% and must never be shown as a single group.
        self.assertEqual(reported.count("P Pivot"),2,reported)
        for chunk in reported.split(" · "):
            if "EMA20 EMA" in chunk:
                self.assertNotIn("EMA50 EMA",chunk)


    def test_r6_rt2_inclusive_exact_point_five_percent_in_generated_dom(self):
        """RT2: inclusive 0.5% must admit 99.75/100.25 and 399/401."""
        import math
        for low,high in ((99.75,100.25),(399.0,401.0)):
            with self.subTest(low=low,high=high):
                shown=self._r5_confluence_full_dom(low,None,high)["near"]
                self.assertIn("Vicinanze entro 0,5% (solo descrittive):",shown)
                self.assertIn("EMA20 EMA",shown)
                self.assertIn("P Pivot",shown)
                beyond=self._r5_confluence_full_dom(
                    low,None,math.nextafter(high,math.inf))["near"]
                self.assertIn("Nessuna vicinanza multi-fonte entro 0,5%",beyond)

    def test_r6_rt2_inclusive_subnormal_point_five_percent_in_generated_dom(self):
        """No overflow/underflow tolerance: preserve exact subnormal 399/401 ratio."""
        import math
        ulp=math.ulp(0.0)
        low=399*ulp
        high=401*ulp
        self.assertGreater(low,0)
        at=self._r5_confluence_full_dom(low,None,high)["near"]
        self.assertIn("Vicinanze entro 0,5%",at)
        beyond=self._r5_confluence_full_dom(low,None,high+ulp)["near"]
        self.assertIn("Nessuna vicinanza multi-fonte",beyond)

    def test_r6_rt2_more_than_two_confluences_are_explicitly_disclosed(self):
        """Two displayed windows cannot imply only two valid windows exist."""
        from unittest import mock
        frame=self._r3_pivot_frame("4H","ADA/USDT")
        stamp=frame["candles"][-1]["time"]
        technical={
            "ema20":[{"time":stamp,"value":100.0}],
            "ema50":[{"time":stamp,"value":200.0}],
            "structure":{
                "supports":[{"price":300.0,"touches":2,"last_swing_time":0}],
                "resistances":[]},
            "pivots":{
                "reference_day_utc":"2026-10-26",
                "P":100.2,"S1":200.2,"S2":10.0,"S3":20.0,
                "R1":300.2,"R2":400.0,"R3":500.0}
        }
        with mock.patch.object(g,"technical_from_candles",return_value=technical):
            page=g.page_from_data(frame,now=self.now)
        near=self._r3_render_actual_javascript(page)["near"]
        self.assertIn("Vicinanze entro 0,5% (solo descrittive):",near)
        self.assertIn("Mostrate 2 di 3",near)
        self.assertNotIn("300–300,2",near)



class PatrimonioD1D2Tests(unittest.TestCase):
    """KDD-PR21 D1/D2: only synthetic holdings/prices; never read real wallet."""
    def setUp(self):
        self.now=dt.datetime(2026,10,28,11,0,tzinfo=dt.timezone.utc)
        self.market={"prezzo_eur":100.0,"var_oggi_utc_pct":None,
                     "volume_24h_eur_stimato":1000,"spread_pct":0.1}
        self.source={"rilevazione_utc":self.now.isoformat(),
                     "markets":{"BTC":dict(self.market),"SOL":dict(self.market,prezzo_eur=25)},
                     "trends":{},"feed":[],"problemi_feed":[]}

    def report(self,positions,markets=None,decisions=None):
        data=dict(self.source)
        if markets is not None: data["markets"]=markets
        return d.build_report(data,{"posizioni":positions},{},{},decisions or [])

    def test_d1_five_contract_states_and_html(self):
        samples=[
          ([{"token":"BTC","quantita":"2"},{"token":"SOL","quantita":"4"}],
           "COMPLETO",300.0,2,0,"300,00 €"),
          ([{"token":"BTC","quantita":"2"},{"token":"ETH","quantita":"3"}],
           "PARZIALE",200.0,1,1,"200,00 € (incompleto)"),
          ([{"token":"ETH","quantita":"3"}],
           "NON_DISPONIBILE",None,0,1,"non disponibile (incompleto)"),
          ([{"token":"BTC","quantita":"0"}],
           "COMPLETO",0.0,1,0,"0,00 €"),
          ([], "NESSUNA_POSIZIONE_REGISTRATA",None,0,0,
           "non disponibile")]
        for positions,state,expected,ok,bad,caption in samples:
            with self.subTest(state=state):
                report=self.report(positions)
                self.assertEqual(report["stato_totale"],state)
                self.assertEqual(report["totale_stimato_eur"],expected)
                self.assertEqual(report["posizioni_valorizzate"],ok)
                self.assertEqual(report["posizioni_incomplete"],bad)
                self.assertEqual(report["posizioni_registrate"],len(positions))
                self.assertEqual(report["totale_parziale"],state in
                                 ("PARZIALE","NON_DISPONIBILE"))
                self.assertIn("Valore posizioni inserite: "+caption,d.render(report))
                self.assertNotIn("Valore posizioni inserite: nan",d.render(report))
                json.dumps(report,allow_nan=False)
        self.assertTrue(self.report([{"token":"BTC","quantita":"0"}])["zero_reale"])
        self.assertFalse(self.report([])["zero_reale"])

    def test_d1_old_report_render_preserves_unavailable_semantics(self):
        case=self.report([{"token":"BTC","quantita":"2"}])
        old=dict(case,totale_stimato_eur=0,totale_parziale=True)
        for key in ("stato_totale","posizioni_valorizzate","posizioni_incomplete",
                    "posizioni_registrate","zero_reale"):
            old.pop(key,None)
        old["posizioni"]=[{"token":"BTC","quantita":None,
                           "errore":"Quantità non nota",
                           "decisione":"NESSUNA DECISIONE REGISTRATA"}]
        self.assertIn("non disponibile (incompleto)",d.render(old))
        self.assertNotIn("Valore posizioni inserite: 0,00 €",d.render(old))

    def test_d2_malformed_quantities_keep_identity_and_do_not_fake_zero(self):
        for raw in (None,"MISSING","","NaN","Infinity","-Infinity",
                    -2,True,False,float("nan"),float("inf"),
                    1e308,"1e400","1e-400",[],{}):
            with self.subTest(value=str(raw)):
                case=self.report([{"token":"BTC","quantita":raw,
                                   "costo_medio_eur":10}])
                p=case["posizioni"][0]
                self.assertEqual(p["token"],"BTC")
                self.assertIn("errore",p)
                self.assertNotIn("valore_eur",p)
                self.assertNotIn("pl_non_realizzato_eur",p)
                self.assertIsNone(case["totale_stimato_eur"])
                self.assertEqual(case["stato_totale"],"NON_DISPONIBILE")
                json.dumps(case,allow_nan=False)
                shown=d.render(case)
                self.assertIn("BTC",shown)
                self.assertIn("Valore posizioni inserite: non disponibile",shown)
                self.assertNotIn("P/L indicativo: ",shown)

    def test_d2_nonfinite_distinct_from_not_numeric(self):
        for raw, expected in (("MISSING","NON_NUMERICO"),("","NON_NUMERICO"),
                              ("NaN","NON_FINITO"),("Infinity","NON_FINITO"),
                              ("-Infinity","NON_FINITO"),(float("nan"),"NON_FINITO"),
                              (float("inf"),"NON_FINITO"),(-1,"NEGATIVO"),
                              ("1e400","FUORI_SCALA")):
            with self.subTest(raw=repr(raw)):
                report=self.report([{"token":"BTC","quantita":raw}])
                self.assertEqual(report["posizioni_valorizzate"],0)
                self.assertIn(expected,report["posizioni"][0]["errore"])
                self.assertIsNone(report["totale_stimato_eur"])
                json.dumps(report,allow_nan=False)

    def test_d2_zero_and_valid_quantity_yield_genuine_zero_and_pl(self):
        z=self.report([{"token":"BTC","quantita":0,"costo_medio_eur":12}])
        self.assertEqual(z["posizioni"][0]["valore_eur"],0)
        self.assertEqual(z["posizioni"][0]["pl_non_realizzato_eur"],0)
        self.assertTrue(z["zero_reale"])
        p=self.report([{"token":"BTC","quantita":"2.5","costo_medio_eur":"75"}])
        self.assertEqual(p["posizioni"][0]["valore_eur"],250)
        self.assertEqual(p["posizioni"][0]["pl_non_realizzato_eur"],62.5)
        self.assertFalse(p["zero_reale"])

    def test_d2_invalid_token_and_duplicate_do_not_get_wrong_decision(self):
        now=self.now.isoformat()
        decisions=[{"token":"BTC","scelta":"TENERE","motivo":"BTC TEST",
                    "creata_utc":now,
                    "scade_utc":"2030-10-29T11:00:00+00:00"}]
        for bad in (None,27,"","   ","<script>alert(1)</script>",
                    "A/B","BTC EVIL",True):
            with self.subTest(token=repr(bad)):
                report=self.report([{"token":bad,"quantita":1}],decisions=decisions)
                self.assertEqual(len(report["posizioni"]),1)
                self.assertIn("errore",report["posizioni"][0])
                self.assertNotIn("valore_eur",report["posizioni"][0])
                self.assertNotIn("BTC TEST",report["posizioni"][0]["decisione"])
                self.assertEqual(report["posizioni_incomplete"],1)
                page=d.render(report)
                self.assertNotIn("<script>alert(1)</script>",page)
                json.dumps(report,allow_nan=False)
        duplicated=self.report([{"token":"BTC","quantita":2},
                                {"token":"btc","quantita":3}],decisions=decisions)
        self.assertEqual(len(duplicated["posizioni"]),2)
        self.assertEqual(duplicated["posizioni_valorizzate"],0)
        self.assertEqual(duplicated["posizioni_incomplete"],2)
        self.assertIsNone(duplicated["totale_stimato_eur"])
        self.assertTrue(all("errore" in h and "valore_eur" not in h
                            and "BTC TEST" not in h["decisione"]
                            for h in duplicated["posizioni"]))
        self.assertIn("duplic",d.render(duplicated).lower())

    def test_d2_invalid_cost_basis_keeps_value_but_no_pl(self):
        for basis in ("MISSING","","NaN","Infinity",-1,True,1e309,{}):
            with self.subTest(basis=repr(basis)):
                report=self.report([{"token":"BTC","quantita":2,
                                     "costo_medio_eur":basis}])
                p=report["posizioni"][0]
                self.assertEqual(p["valore_eur"],200)
                self.assertIsNone(p["pl_non_realizzato_eur"])
                self.assertIn("costo",d.render(report).lower())
                self.assertIn("verific",d.render(report).lower())
                json.dumps(report,allow_nan=False)

    def test_d2_bad_market_prices_and_overflow_not_a_value(self):
        for price in (0,-1,float("nan"),float("inf"),"NaN","oops",1e308):
            with self.subTest(price=repr(price)):
                markets={"BTC":dict(self.market,prezzo_eur=price)}
                report=self.report([{"token":"BTC","quantita":"2"}],markets=markets)
                self.assertIsNone(report["totale_stimato_eur"])
                self.assertIn("errore",report["posizioni"][0])
                json.dumps(report,allow_nan=False)
        tiny=self.report([{"token":"BTC","quantita":"1e-200"}],
                         markets={"BTC":dict(self.market,prezzo_eur=1e-200)})
        self.assertIsNone(tiny["totale_stimato_eur"])
        json.dumps(tiny,allow_nan=False)

    def test_d2_duplicate_unknown_token_keeps_all_rows(self):
        case=self.report([{"token":None,"quantita":None},
                          {"token":None,"quantita":"MISSING"},
                          {"token":"SOL","quantita":"3"}])
        self.assertEqual(len(case["posizioni"]),3)
        self.assertEqual(case["posizioni_valorizzate"],1)
        self.assertEqual(case["posizioni_incomplete"],2)
        self.assertEqual(case["totale_stimato_eur"],75)
        json.dumps(case,allow_nan=False)

    def test_d2_malformed_decision_records_do_not_bind_wrong_asset(self):
        now=self.now.isoformat()
        entries=[{"token":None,"creata_utc":now},
                 {"token":27,"creata_utc":now},
                 {"token":"BTC","creata_utc":now,
                  "scelta":"ATTESA","motivo":"BTC_ONLY",
                  "scade_utc":"2030-10-29T11:00:00+00:00"}]
        good=self.report([{"token":"BTC","quantita":"1"}],decisions=entries)
        self.assertIn("BTC_ONLY",good["posizioni"][0]["decisione"])
        bad=self.report([{"token":"ETH","quantita":"1"}],decisions=entries)
        self.assertNotIn("BTC_ONLY",bad["posizioni"][0]["decisione"])

    def test_d2_strict_report_file_and_html_consumers(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            original_load=d.load
            def local_load(name,default=None):
                if name=="portafoglio.json":
                    return {"posizioni":[{"token":"BTC","quantita":"MISSING"}]}
                return default
            with unittest.mock.patch.object(d,"DIR",root),\
                 unittest.mock.patch.object(d,"load",side_effect=local_load),\
                 unittest.mock.patch.object(d,"load_decisions",return_value=[]),\
                 unittest.mock.patch.object(d.piano_gpt,"load",return_value=None),\
                 unittest.mock.patch("verifica_piani.archivia_piano",return_value=None):
                d.output(self.source)
            raw=(root/"ultimo_report.json").read_text()
            obj=json.loads(raw,parse_constant=lambda x:(_ for _ in ()).throw(
                ValueError("Nonfinite JSON constant: "+x)))
            self.assertIsNone(obj["totale_stimato_eur"])
            self.assertEqual(obj["stato_totale"],"NON_DISPONIBILE")
            html=(root/"cruscotto.html").read_text()
            self.assertIn("Valore posizioni inserite: non disponibile",html)
            self.assertNotIn("Valore posizioni inserite: 0,00 €",html)



class DossierPatrimonialeG2Tests(unittest.TestCase):
    """KDD PR21 dossier: original collect/status/output on isolated synthetic files."""
    def setUp(self):
        self.now=dt.datetime(2026,10,28,16,0,tzinfo=dt.timezone.utc)
        self.market={"BTC":{"prezzo_eur":100.0,"var_oggi_utc_pct":None,
                             "volume_24h_eur_stimato":1000,"spread_pct":0.2}}
        self.source={"rilevazione_utc":self.now.isoformat(timespec="seconds"),
            "markets":self.market,"trends":{},"feed":[],"problemi_feed":[],
            "schede_v02":[{"token":"ICNT","categoria":"test","esito":"RIESAME",
                           "sintesi":"Fixture sintetica","coppia_analisi":"ICNT/EUR",
                           "alternative":[{"pair":"ICNT/EUR","pair_key":"ICNTEUR",
                                           "prezzo_quote":1.0,
                                           "volume_eur_stimato":5000,
                                           "spread_pct":0.2}],
                           "evidenze":[],"criticita":[],"costi_roundtrip":[]}]}

    def exercise(self, positions, *, source_label=None, acquired=None,
                 after_collect=None, do_output=True):
        import dossier_trade as mod
        import verifica_piani as vp
        with tempfile.TemporaryDirectory() as folder:
            path=pathlib.Path(folder)
            portfolio={"posizioni":positions}
            if source_label is not None:
                portfolio["fonte_quantita"]=source_label
            if acquired is not None:
                portfolio["data_ora_saldo_privato_utc"]=acquired
            (path/"portafoglio.json").write_text(json.dumps(portfolio,allow_nan=True))
            with unittest.mock.patch.object(d,"DIR",path),\
                 unittest.mock.patch.object(d,"NOW",return_value=self.now),\
                 unittest.mock.patch.object(mod,"recupera_4h",return_value={}),\
                 unittest.mock.patch.object(mod,"global_context",return_value={}),\
                 unittest.mock.patch.object(mod,"derivatives_context",return_value={
                     "open-interest":{},"cvd":{}}),\
                 unittest.mock.patch.object(mod,"summarize_candles",return_value={
                     "ultima_chiusura_utc":self.now.isoformat()}),\
                 unittest.mock.patch.object(mod,"token_fundamentals",return_value={
                     "id":"impossible-cloud-network-token"}),\
                 unittest.mock.patch.object(mod.flusso_spot,"fetch",return_value={
                     "stato":"COMPLETO_4H"}),\
                 unittest.mock.patch.object(d,"kraken",return_value={"ICNTEUR":[[1]]}),\
                 unittest.mock.patch.object(mod.time,"sleep"),\
                 unittest.mock.patch.object(d.piano_gpt,"load",return_value=None),\
                 unittest.mock.patch.object(vp,"archivia_piano",return_value=None):
                dossier=mod.collect(source=self.source)
                status=d.prepara_dossier_aggiornamento(self.source)
                if after_collect is not None:
                    portfolio=after_collect
                    (path/"portafoglio.json").write_text(json.dumps(portfolio,allow_nan=True))
                if do_output:
                    d.output(self.source)
                    report=d.load("ultimo_report.json")
                    page=(path/"cruscotto.html").read_text()
                else:
                    report=None;page=""
                # Verify actual JSON from disk, not merely Python return values.
                stored_dossier=d.load("dossier_multifonte.json")
                stored_status=d.load("dossier_stato.json")
                return stored_dossier,stored_status,report,page

    def test_g2_red_original_counterexample_three_saved_files(self):
        dossier,status,report,page=self.exercise(
            [{"token":"BTC","quantita":"MISSING"}])
        self.assertFalse(dossier["portafoglio_noto"])
        self.assertEqual(dossier["qualita_patrimonio"]["stato_totale"],"NON_DISPONIBILE")
        self.assertEqual(dossier["qualita_patrimonio"]["posizioni_valorizzate"],0)
        self.assertEqual(dossier["qualita_patrimonio"]["posizioni_incomplete"],1)
        self.assertEqual(status["stato_fonti_mercato"],"COMPLETO")
        self.assertEqual(status["stato"],"PRONTO_PER_ESAME_MERCATO")
        self.assertEqual(status["idoneita_analisi_patrimoniale"],"NON_IDONEA")
        self.assertEqual(report["stato_totale"],"NON_DISPONIBILE")
        self.assertIsNone(report["totale_stimato_eur"])
        self.assertEqual(report["dossier_stato"]["idoneita_analisi_patrimoniale"],"NON_IDONEA")
        self.assertIn("patrimonio",page.lower())

    def test_g2_market_fully_usable_while_holdings_invalid(self):
        for entries in ([{"token":"BTC","quantita":None}],
                        [{"token":"BTC","quantita":"NaN"}],
                        [{"token":"BTC","quantita":"Infinity"}],
                        [{"token":"BTC","quantita":-1}],
                        [{"token":"BTC","quantita":True}],
                        [{"token":"BTC","quantita":""}],
                        [{"token":"BTC","quantita":2},{"token":"btc","quantita":3}],
                        [{"token":None,"quantita":2}],
                        [{"token":37,"quantita":2}],
                        [{"token":"<script>","quantita":2}],
                        [{"token":"BTC","quantita":"MISSING"},{"token":"SOL","quantita":2}]):
            with self.subTest(entries=repr(entries)):
                dossier,status,report,page=self.exercise(entries)
                self.assertEqual(status["stato"],"PRONTO_PER_ESAME_MERCATO")
                self.assertEqual(status["stato_fonti_mercato"],"COMPLETO")
                self.assertEqual(status["idoneita_analisi_patrimoniale"],"NON_IDONEA")
                self.assertFalse(dossier["portafoglio_noto"])
                self.assertEqual(report["dossier_stato"]["idoneita_analisi_patrimoniale"],
                                 "NON_IDONEA")
                self.assertNotIn("<h3><script>",page)
                if entries == [{"token":"<script>","quantita":2}]:
                    self.assertIn("&lt;script&gt;",page)
                json.dumps(dossier,allow_nan=False)

    def test_g2_positive_quantity_not_enough_for_eur_value_or_freshness(self):
        for entries in ([{"token":"BTC","quantita":"2"}],
                        [{"token":"BTC","quantita":"0"}],
                        [{"token":"BTC","quantita":"2"},{"token":"SOL","quantita":"3"}],
                        []):
            with self.subTest(entries=repr(entries)):
                dossier,status,report,page=self.exercise(entries)
                self.assertEqual(status["stato"],"PRONTO_PER_ESAME_MERCATO")
                self.assertEqual(status["idoneita_analisi_patrimoniale"],"NON_IDONEA")
                self.assertEqual(dossier["portafoglio_noto"],bool(entries))
                self.assertFalse(dossier["qualita_patrimonio"]["saldo_recente_verificato"])
                if entries==[{"token":"BTC","quantita":"0"}]:
                    self.assertTrue(dossier["qualita_patrimonio"]["zero_reale"])
                if not entries:
                    self.assertEqual(dossier["qualita_patrimonio"]["stato_totale"],
                                     "NESSUNA_POSIZIONE_REGISTRATA")

    def test_g2_valid_recent_balanceex_is_eligible_but_not_order(self):
        stamp=self.now.isoformat(timespec="seconds")
        dossier,status,report,page=self.exercise(
            [{"token":"BTC","quantita":"2"}],
            source_label="Kraken BalanceEx API privata SOLA LETTURA, "+stamp,
            acquired=stamp)
        self.assertTrue(dossier["portafoglio_noto"])
        self.assertTrue(dossier["qualita_patrimonio"]["saldo_recente_verificato"])
        self.assertEqual(status["stato"],"PRONTO_PER_ESAME_GPT")
        self.assertEqual(status["idoneita_analisi_patrimoniale"],"IDONEA")
        self.assertEqual(report["totale_stimato_eur"],200)
        self.assertIn("fotografia_portafoglio_sha256",report["dossier_stato"])
        self.assertIn("nessuna operazione automatica",page.lower())

    def test_g2_different_portfolio_between_collect_and_output_blocks_readiness(self):
        original=[{"token":"BTC","quantita":"2"}]
        updated={"posizioni":[{"token":"BTC","quantita":"3"}]}
        stamp=self.now.isoformat(timespec="seconds")
        dossier,status,report,page=self.exercise(
            original,source_label="Kraken BalanceEx API privata SOLA LETTURA, "+stamp,
            acquired=stamp,after_collect=updated)
        self.assertEqual(status["stato"],"PRONTO_PER_ESAME_GPT")
        self.assertNotEqual(dossier["fotografia_portafoglio_sha256"],
                            report["fotografia_portafoglio_sha256"])
        self.assertEqual(report["dossier_stato"]["stato"],"NON_ALLINEATO_PATRIMONIO")
        self.assertEqual(report["dossier_stato"]["idoneita_analisi_patrimoniale"],"NON_IDONEA")
        self.assertIn("diversa",page.lower())

    def test_g2_invalid_schema_dossier_reports_instead_of_exception(self):
        for positions in ([None],["MISSING"],{"BTC":"2"},"BTC",5):
            with self.subTest(type=repr(positions)):
                dossier,status,_,_=self.exercise(positions,do_output=False)
                self.assertFalse(dossier["portafoglio_noto"])
                self.assertIn(dossier["qualita_patrimonio"]["stato_quantita"],
                              ("SCHEMA_NON_VALIDO","INCOMPLETE"))
                self.assertEqual(status["stato"],"PRONTO_PER_ESAME_MERCATO")
                self.assertEqual(status["idoneita_analisi_patrimoniale"],"NON_IDONEA")
                json.dumps(dossier,allow_nan=False)

    def test_g2_old_dossier_cannot_claim_patrimony_from_timestamp_alone(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"dossier_stato.json").write_text(json.dumps({
                "stato":"PRONTO_PER_ESAME_GPT",
                "rilevazione_kraken_utc":self.source["rilevazione_utc"]}))
            (root/"dossier_multifonte.json").write_text(json.dumps({
                "schema":1,"kraken_istantanea_utc":self.source["rilevazione_utc"],
                "portafoglio_noto":True}))
            with unittest.mock.patch.object(d,"DIR",root):
                status=d.stato_dossier_per_report(self.source,
                   portfolio={"posizioni":[{"token":"BTC","quantita":"2"}]})
            self.assertEqual(status["idoneita_analisi_patrimoniale"],"NON_IDONEA")
            self.assertNotEqual(status["stato"],"PRONTO_PER_ESAME_GPT")

    def test_g2_invalid_nonlist_wallet_produces_explicit_report_without_fake_rows(self):
        for positions in ({"BTC":"2"}, "BTC", 5):
            with self.subTest(positions=repr(positions)):
                dossier,status,report,page=self.exercise(positions,do_output=True)
                self.assertFalse(dossier["portafoglio_noto"])
                self.assertEqual(dossier["qualita_patrimonio"]["stato_quantita"],
                                 "SCHEMA_NON_VALIDO")
                self.assertEqual(status["idoneita_analisi_patrimoniale"],"NON_IDONEA")
                self.assertEqual(report["stato_totale"],"SCHEMA_NON_VALIDO")
                self.assertIsNone(report["totale_stimato_eur"])
                self.assertIsNone(report["posizioni_registrate"])
                self.assertEqual(report["posizioni"],[])
                self.assertIn("Formato posizioni non valido",page)
                self.assertIn("nessuna posizione o valore inventato",page)
                json.dumps(report,allow_nan=False)

    def test_g2_matching_wallet_digest_does_not_freeze_balance_freshness(self):
        stamp=self.now.isoformat(timespec="seconds")
        wallet={"posizioni":[{"token":"BTC","quantita":"2"}],
                "fonte_quantita":"Kraken BalanceEx API privata SOLA LETTURA, "+stamp,
                "data_ora_saldo_privato_utc":stamp}
        digest=d.fotografia_portafoglio_sha256(wallet)
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder)
            (root/"dossier_multifonte.json").write_text(json.dumps({
                "schema":2,"kraken_istantanea_utc":stamp,
                "fotografia_portafoglio_sha256":digest}))
            (root/"dossier_stato.json").write_text(json.dumps({
                "stato":"PRONTO_PER_ESAME_GPT",
                "stato_fonti_mercato":"COMPLETO",
                "idoneita_analisi_patrimoniale":"IDONEA",
                "rilevazione_kraken_utc":stamp,
                "fotografia_portafoglio_sha256":digest}))
            with unittest.mock.patch.object(d,"DIR",root):
                with unittest.mock.patch.object(d,"NOW",return_value=self.now):
                    ready=d.stato_dossier_per_report(self.source,portfolio=wallet)
                with unittest.mock.patch.object(d,"NOW",
                      return_value=self.now+dt.timedelta(minutes=35)):
                    late=d.stato_dossier_per_report(self.source,portfolio=wallet)
            self.assertEqual(ready["stato"],"PRONTO_PER_ESAME_GPT")
            self.assertEqual(late["stato"],"PRONTO_PER_ESAME_MERCATO")
            self.assertEqual(late["idoneita_analisi_patrimoniale"],"NON_IDONEA")
            self.assertIn("non più recente"," ".join(late["motivi_patrimoniali"]))

    def test_g2_missing_price_keeps_quantities_known_but_value_partial(self):
        dossier,status,report,_=self.exercise([
            {"token":"BTC","quantita":"2"},{"token":"SOL","quantita":"4"}])
        self.assertTrue(dossier["portafoglio_noto"])
        self.assertEqual(dossier["qualita_patrimonio"]["stato_totale"],"PARZIALE")
        self.assertEqual(dossier["qualita_patrimonio"]["posizioni_valorizzate"],1)
        self.assertEqual(report["stato_totale"],"PARZIALE")
        self.assertEqual(status["idoneita_analisi_patrimoniale"],"NON_IDONEA")




class IntegratedDecisionHomeTests(unittest.TestCase):
    """Falsifiable home composition: local report and original rendering, no private data."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        patcher = unittest.mock.patch.object(d, "DIR", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.now = d.NOW()
        self.tokens = ["BTC", "ETH", "SOL", "SUI", "BNB", "ADA", "DOT",
                       "LINK", "AVAX", "NEAR"]
        data = {"rilevazione_utc": self.now.isoformat(timespec="seconds"),
                "markets": {"BTC": {"prezzo_eur": 1, "var_oggi_utc_pct": None,
                                     "volume_24h_eur_stimato": 0, "spread_pct": 0}}, "trends": {},
                "feed": [], "problemi_feed": []}
        wallet = {"posizioni": [{"token": t, "quantita": None if t == "ETH" else "1"}
                                for t in self.tokens]}
        self.report = d.build_report(data, wallet, {}, {}, [])
        self.report["piano_gpt"] = None
        self.report["schede_v02"] = [{
            "token": "ADA", "categoria": "setup in verifica",
            "esito": "CONFIGURAZIONE_MISTA", "sintesi": "Volume da verificare",
            "perche_selezionato": "Osservazione 1H",
            "evidenze": ["OHLC 1H"], "criticita": ["Spread da aggiornare"],
            "coppia_analisi": "ADA/USD",
            "alternative": [{"pair": "ADA/USD", "pair_key": "ADAUSD"}],
            "costi_roundtrip": []}]
        self.report["saldo_stato"] = {
            "origine": "KRAKEN_BALANCEEX",
            "acquisizione_saldo_utc": (self.now - dt.timedelta(hours=4)).isoformat(),
            "freschezza_saldo": "RECENTE"}
        self.report["dossier_stato"] = {"stato": "PARZIALE",
                                         "fotografia_portafoglio_sha256": "abc"}
        (self.root / "ultimo_report.json").write_text(
            json.dumps(self.report), encoding="utf-8")
        dossier = {
            "kraken_istantanea_utc": self.report["rilevazione_utc"],
            "fotografia_portafoglio_sha256": "abc",
            "patrimonio_4tf": {
                "posizioni": [{
                    "indice": i, "token": token, "coppia": "XBT/EUR" if i == 0 else None,
                    "pair_key": "XXBTZEUR" if i == 0 else None,
                    "asset_base": "XBT" if i == 0 else None,
                    "valuta_quotazione": "EUR" if i == 0 else None,
                    "stato": "PARZIALE",
                    "timeframe": {label: {"stato": "NON_DISPONIBILE" if label == "1D" else "AGGIORNATO"}
                                  for label in ("15m", "1H", "4H", "1D")}
                } for i, token in enumerate(self.tokens)]
            }}
        (self.root / "dossier_multifonte.json").write_text(
            json.dumps(dossier), encoding="utf-8")
        self.proposal = {
            "proposta_id": "fixture-001",
            "snapshot_utc": (self.now - dt.timedelta(days=2)).isoformat(),
            "scenario": "Valutazione storica su dieci asset",
            "scenario_alternativo": "Ruotare solo dopo confronto",
            "rischi_comuni": "Liquidità incerta",
            "liquidita": "Disponibilità non verificata",
            "revisione": "Riesame al nuovo snapshot",
            "posizioni": [{
                "indice": i, "token": token, "azione": "RINVIARE" if i == 1 else "MANTENERE",
                "tesi": "Ipotesi storica " + token, "alternativa": "Alleggerire",
                "rischi": "Rischio " + token, "invalidazione": "Nuovo contesto",
                "riesame": "Prossima fotografia", "costi": "Non calcolati",
                "evidenze": "Dossier storico",
            } for i, token in enumerate(self.tokens)]}
        from scripts import kdd_drive_exchange as exchange
        self.mocks = [
            unittest.mock.patch.object(exchange, "receive_synced", return_value=None),
            unittest.mock.patch.object(exchange, "pending", return_value=(self.proposal, {})),
            unittest.mock.patch.object(exchange.bridge, "load_archive", return_value={}),
            unittest.mock.patch.object(exchange, "decision_history", return_value=[]),
        ]
        for patch in self.mocks:
            patch.start()
            self.addCleanup(patch.stop)

    def render_home(self):
        return serve.with_controls(d.render(self.report))

    def test_decision_first_real_render_and_complete_wallet(self):
        page = self.render_home()
        self.assertLess(page.index("id='kdd-decisioni'"), page.index("id='piano-gpt'"))
        self.assertIn("NON APPROVATA", page)
        self.assertIn("Valutazione storica su dieci asset", page)
        self.assertIn("Riesame al nuovo snapshot", page)
        self.assertIn("10 posizioni", page)
        self.assertIn("saldo", page.lower())
        self.assertIn("mercato", page.lower())
        self.assertIn("ETH", page)
        self.assertIn("Quantità non nota", page)
        self.assertIn("PARZIALE", page)
        self.assertIn("Visualizza tutte le posizioni", page)
        self.assertIn("id='kdd-legacy-spot'", page)

    def test_direct_catalogued_pair_links_and_missing_frame(self):
        page = self.render_home()
        self.assertIn("href='/grafico/spot?pair=XXBTZEUR&amp;tf=4h'", page)
        self.assertIn("href='/analisi/spot?pair=XXBTZEUR'", page)
        self.assertIn("href='/grafico/spot?pair=ADAUSD&amp;tf=15m'", page)
        self.assertIn("href='/analisi/spot?pair=ADAUSD'", page)
        self.assertIn("1D NON DISPONIBILE", page)
        self.assertNotIn("href='/analisi/sui-mtf'", page)
        self.assertNotIn("href='/grafico/spot?pair=ETH", page)

    def test_unverified_pair_and_old_market_fail_closed(self):
        report = dict(self.report)
        report["rilevazione_utc"] = (self.now - dt.timedelta(days=3)).isoformat()
        (self.root / "ultimo_report.json").write_text(json.dumps(report), encoding="utf-8")
        page = self.render_home()
        self.assertIn("DA AGGIORNARE", page)
        self.assertIn("fotografia GPT", page.lower())
        self.assertNotIn("href='/grafico/spot?pair=XXBTZEUR", page)
        self.assertNotIn("href='/grafico/spot?pair=ADAUSD", page)

if __name__=='__main__': unittest.main(verbosity=2)
