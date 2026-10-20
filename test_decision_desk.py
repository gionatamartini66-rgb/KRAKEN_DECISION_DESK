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
        self.assertTrue(d.checkpoint_allineato(), 'README non allineato al codice: descrivere nel README modifiche, test e prossimo step, poi aggiornare impronta')

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
        import copy
        current=pg.load()
        self.assertIsNotNone(current)
        self.assertNotIn('errore',current)
        injected=fixture_trade_plan()
        injected['tesi']='<script>alert("x")</script>'
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
        self.assertIn('href=\'/grafico/sui-4h\'',html)
        self.assertIn("Prova grafico reale SUI 4H",html)
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
        plan=pg.load()
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
        report['piano_gpt']=pg.load()
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
            self.assertEqual(d.stato_dossier_per_report(report)['stato'],'PRONTO_PER_ESAME_GPT')
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
            with unittest.mock.patch.object(vp,'PLANS',root/'plans'), \
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
        import tempfile
        from pathlib import Path
        current=pg.load()
        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch.object(vp,'PLANS',Path(tmp)):
                digest=vp.archivia_piano(current)
                vp.archivia_piano(current)
                self.assertEqual(len(list(Path(tmp).glob('*.json'))),1)
                (Path(tmp)/(digest+'.json')).write_text('{"token":"BAD"}')
                with self.assertRaises(ValueError):vp.archivia_piano(current)

    def test_archive_render_hides_current_and_never_claims_returns(self):
        import verifica_piani as vp
        current=__import__('piano_gpt').load()
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
        import ricerca_setup as rs
        import piano_gpt as pg
        import verifica_piani as vp
        import copy,tempfile
        from pathlib import Path
        plan=copy.deepcopy(pg.load())
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
        import json,pathlib
        copy=json.loads(pathlib.Path('migrazione_attesa.json').read_text())
        self.assertEqual(copy['stato'],'DA_RICONCILIARE')
        self.assertFalse(copy['migrazione_completata'])
        self.assertEqual(set(x['token'] for x in copy['asset_visibili']),
                         {'NEAR','XRP','JUP','RENDER','FET','ONDO'})
        self.assertTrue(all(x['accreditato_kraken'] is None for x in copy['asset_visibili']))
        from decimal import Decimal
        import hashlib
        live=d.load('portafoglio.json')
        self.assertEqual(live['t0_id'], 'T0_2026-10-19_2301_KRAKEN_PRO')
        self.assertIn('BalanceEx', live['fonte_quantita'])
        p=pathlib.Path('storico_portafoglio/T0_2026-10-19_2301_KRAKEN_PRO.json')
        base=json.loads(p.read_text())
        self.assertEqual(base['valore_totale_fotografia_eur'],'1009.69')
        self.assertEqual(live['t0_sha256'],hashlib.sha256(p.read_bytes()).hexdigest())
        self.assertEqual(len(base['quantita_e_valori_schermata']),10)
        self.assertEqual(sum(Decimal(x['valore_eur_visualizzato'])
                             for x in base['quantita_e_valori_schermata']),Decimal('1009.68'))
        self.assertTrue(all(x['costo_medio_eur'] is None for x in live['posizioni']))
        self.assertIn('USDC',live['liquidita_spot_api'])
        self.assertEqual(copy['riscontro_portafoglio_kraken_2026_10_19']['non_visibile_nella_schermata'],['ONDO'])
        self.assertEqual(copy['riscontro_portafoglio_kraken_2026_10_19']['visibili_anche_su_kraken']['FET'],'20.15068')

    def test_migration_shown_only_as_pending_not_tradeable_portfolio(self):
        import copy,json
        report=d.build_report(
            {'rilevazione_utc':self.now.isoformat(), 'markets':{},'trends':{},
             'feed':[], 'problemi_feed':[]},
            {'posizioni':[]},{},{},[])
        report['migrazione_attesa']=json.loads(pathlib.Path('migrazione_attesa.json').read_text())
        rendered=d.render(report)
        self.assertIn('Le vecchie quantità Binance sono archiviate separatamente dal portafoglio Kraken',rendered)
        self.assertIn('5 asset ora visibili su Kraken, 1 da verificare',rendered)
        self.assertIn('6.34614039',rendered)
        self.assertNotIn('6.678999',rendered)
        self.assertNotIn('Valore posizioni inserite: 59',rendered)
        self.assertNotIn('€30,07',rendered)

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
        self.assertEqual(report['posizioni'],[])
        self.assertEqual(report['totale_stimato_eur'],0)

if __name__=='__main__': unittest.main(verbosity=2)
