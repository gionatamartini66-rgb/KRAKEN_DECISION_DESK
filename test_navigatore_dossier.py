"""Independent bounded synthetic checks; no Kraken keys or network."""
import copy
import unittest
from navigatore_dossier import build, PAIR, ASSET_ID

T='2026-10-21T20:00:00Z'
P='2026-10-21T20:15:00Z'


def market():
    return {'rilevazione_utc':T, 'markets':{'SUI':{
      'token':'SUI','pair':'SUI/EUR','pair_key':'SU I EUR EXAMPLE',
      'prezzo_eur': '1.25', 'spread_pct':'0.2',
      'volume_24h_eur_stimato':'250000', 'costo_min_eur':5,'quantita_min':'1'}}}


def existing():
    rows=[{'chiusura':'1.25'}]
    return {'candidati':[{'token':'SUI','coppia_analisi':PAIR,
      'book':{'spread_book_pct':0.21, 'profondita_bid10_eur':5000,
              'profondita_ask10_eur':4500,'ignored_private':'secret'},
      'simulazione_costi_eur_wallet':[{'coppia':PAIR,'costo_roundtrip_eur':2.5,
                                    'n_conversioni':0,'secret':'do-not-emit'}],
      'livelli_15m':{'ultima_chiusura_utc':'2026-10-21T19:45:00Z',
                   'ultime_candele':rows},
      'livelli_1h':{'ultima_chiusura_utc':'2026-10-21T19:00:00Z',
                    'ultime_candele':rows},'wallet':'PRIVATE'}],
      'grafici_4h':{'SUI':{'stato':'OK','coppia':PAIR,
          'serie_ohlcv_chiuse':[{'close':1.25, 'apertura_ts_utc':1792584000}],
          'lettura_indicativa':{'ultima_chiusura_utc':'2026-10-21T16:00:00Z'}}},
      'portafoglio_noto':True,'private_balances':{'SUI':112}}


def onchain():
    return {'network':'sui:mainnet','acquired_utc':'2026-10-21T20:10:00Z',
     'statuses':{'identity':'VERIFICATA','staking':'OGGETTO_VERIFICATO_ATTRIBUZIONE_NON_DIMOSTRATA'},
     'coverage':'336500000..336600000 (campione)',
     'observations':[{'kind':'FATTO_OSSERVATO','asset':'SUI',
       'chain':'sui:mainnet','asset_id':ASSET_ID,
       'event':'STAKED_SUI_OGGETTO_CREATO','quantity':'1.5',
       'unit':'SUI','transaction':'DIGEST_FIXTURE','block_reference':'336592287',
       'event_utc':'2026-10-21T20:02:00Z','acquired_utc':'2026-10-21T20:10:00Z',
       'knowable_utc':None,'coverage':'un evento','verification':'VERIFICATO',
       'source':'https://graphql.mainnet.sui.io/graphql',
       'compatible':['Object created'],'prohibited':['BUY/SELL'],
       'limits':['Non e vendita'],'reference_period':None,
       'wallet_private':'UNAUTHORIZED'}]}


def extra():
    general={'source':'https://example.invalid/fixture',
      'observed_utc':T,'coverage':'Un episodio sintetico','fact':'Fatto esclusivamente sintetico',
      'alternative':['Un altro meccanismo potrebbe contribuire.']}
    return {'fondamentali':{**general,'asset_id':ASSET_ID},
            'notizie_token':{**general,'asset_id':ASSET_ID},
            'macroeconomia':{**general,'kind':'VERIFICA_CONTESTUALE'},
            'geopolitica':{**general,'kind':'VERIFICA_CONTESTUALE'}}


class DossierTests(unittest.TestCase):
    def mk(self,**kw):
        return build(snapshot=kw.pop('snapshot',market()),
                     existing_dossier=kw.pop('existing_dossier',existing()),
                     onchain_report=kw.pop('onchain_report',onchain()),
                     public_context=kw.pop('public_context',extra()),
                     acquired_utc=kw.pop('acquired_utc',P),**kw)

    def test_full_fixture_all_channels(self):
        x=self.mk()
        self.assertEqual(x['market_pair'],PAIR)
        self.assertEqual(len(x['sections']),9)
        self.assertEqual(set(x['sections']['multitimeframe']['evidence']), {'15m','1H','4H'})
        self.assertEqual(len(x['missing_sections']),9)
        self.assertEqual(x['public_sources_attested'],[])
        self.assertEqual(x['temporal_alignment']['status'],'ALLINEAMENTO_ACQUISIZIONE_ENTRO_60_MIN')
        self.assertEqual(x['decision_utility'],'NON_DIMOSTRATA')

    def test_missing_all_sources_graceful(self):
        x=build(acquired_utc=P)
        self.assertEqual(len(x['missing_sections']),9)
        self.assertEqual(x['sections']['onchain']['status'],'NON_DISPONIBILE')
        self.assertIsNone(x['sections']['mercato']['evidence'])

    def test_partial_without_onchain_and_macro(self):
        x=self.mk(onchain_report=None,public_context={})
        self.assertEqual(x['sections']['mercato']['evidence']['prezzo_eur'],'1.25')
        self.assertIn('onchain',x['missing_sections'])
        self.assertEqual(x['temporal_alignment']['status'],'NON_DETERMINABILE')

    def test_market_pair_not_only_ticker(self):
        v=market();v['markets']['SUI']['pair']='SUI/USD'
        self.assertEqual(self.mk(snapshot=v)['sections']['mercato']['status'],'IDENTITA_NON_VERIFICATA')

    def test_bad_number_rejected(self):
        v=market();v['markets']['SUI']['volume_24h_eur_stimato']='NaN'
        self.assertEqual(self.mk(snapshot=v)['sections']['mercato']['status'],'RISPOSTA_INCOMPLETA')

    def test_timestamp_mismatch_detected(self):
        v=market();v['rilevazione_utc']='2026-10-20T18:00:00Z'
        self.assertEqual(self.mk(snapshot=v)['temporal_alignment']['status'],'NON_ALLINEATI')

    def test_future_source_rejected(self):
        v=market();v['rilevazione_utc']='2026-10-21T20:20:00Z'
        x=self.mk(snapshot=v)
        self.assertEqual(x['sections']['mercato']['status'],'TEMPO_INCOERENTE')
        self.assertIn('mercato',x['missing_sections'])

    def test_wrong_chain_identity_blocks(self):
        v=onchain();v['network']='sui:testnet'
        self.assertEqual(self.mk(onchain_report=v)['sections']['onchain']['status'],'IDENTITA_NON_VERIFICATA')

    def test_wrong_asset_dropped(self):
        v=onchain();v['observations'][0]['asset_id']='0x2::fake::SUI'
        x=self.mk(onchain_report=v)
        self.assertEqual(x['sections']['onchain']['status'],'NESSUNA_OSSERVAZIONE_UTILIZZABILE')

    def test_observation_missing_checkpoint_dropped(self):
        v=onchain();v['observations'][0]['block_reference']=None
        x=self.mk(onchain_report=v)
        self.assertEqual(x['sections']['onchain']['evidence']['observations'],[])

    def test_unchecked_headline_rejected(self):
        v=extra();del v['macroeconomia']['kind']
        x=self.mk(public_context=v)
        self.assertEqual(x['sections']['macroeconomia']['status'],'NON_VERIFICABILE')

    def test_token_specific_news_identity(self):
        v=extra();v['notizie_token']['asset_id']='fake'
        x=self.mk(public_context=v)
        self.assertIn('notizie_token',x['missing_sections'])

    def test_copies_only_allowlisted_public_fields(self):
        x=str(self.mk())
        for token in ('PRIVATE','do-not-emit','secret','UNAUTHORIZED'):
            self.assertNotIn(token,x)

    def test_readonly_no_signals(self):
        x=self.mk()
        self.assertFalse(x['execution_permissions'])
        self.assertFalse(x['private_data_access'])
        self.assertNotIn('BUY',x['sections']['mercato'])
        self.assertIn('BUY/SELL automatico',x['prohibited_interpretations'])

    def test_provenance_must_be_explicit(self):
        with self.assertRaises(ValueError):self.mk(provenance='VERIFIED_LIVE')

    def test_snapshot_malformed(self):
        x=self.mk(snapshot={'markets':['wrong']})
        self.assertIn('mercato',x['missing_sections'])

    def test_multitimeframe_no_chart(self):
        x=self.mk(existing_dossier=None)
        self.assertEqual(x['sections']['multitimeframe']['status'],'NON_DISPONIBILE')

    def test_spot_and_onchain_semantics_independent(self):
        x=self.mk()
        self.assertNotIn('order',x['sections']['onchain'])
        self.assertEqual(x['sections']['onchain']['evidence']['observations'][0]['kind'],'FATTO_OSSERVATO')
        self.assertEqual(x['sections']['mercato']['evidence']['pair'],PAIR)

    def test_context_age_disclosed(self):
        x=self.mk()
        self.assertEqual(x['temporal_alignment']['per_channel']['multitimeframe']['status'],
                         'ULTIMA_CANDELA_CHIUSA_NON_QUOTAZIONE_LIVE')
        self.assertEqual(x['temporal_alignment']['per_channel']['onchain']['age_at_dossier_seconds'],300)
        self.assertEqual(x['temporal_alignment']['per_channel']['costi']['status'], 'NON_DETERMINABILE')
        self.assertIsNone(x['sections']['liquidita']['evidence']['book_acquired_utc'])

    def test_wrong_fundamentals_asset_rejected(self):
        v=extra();v['fondamentali']['asset_id']='NOT_SUI'
        self.assertEqual(self.mk(public_context=v)['sections']['fondamentali']['status'],'NON_VERIFICABILE')

    def test_incoherent_four_hour_marker_rejected(self):
        v=existing();v['grafici_4h']['SUI']['serie_ohlcv_chiuse'][0]['apertura_ts_utc']+=3600
        x=self.mk(existing_dossier=v)
        self.assertNotIn('4H',x['sections']['multitimeframe']['evidence'])

    def test_repeatable(self):
        a=self.mk();b=self.mk();self.assertEqual(a,b)


if __name__ == '__main__':unittest.main(verbosity=2)