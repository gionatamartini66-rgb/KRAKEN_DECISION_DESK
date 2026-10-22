"""D1-D8 correction tests: negative and legitimate cases; synthetic only."""
import unittest
from test_navigatore_dossier import market, existing, onchain, extra, P, T
from navigatore_dossier import build, CHANNELS

class Remediation(unittest.TestCase):
    def dossier(self, **kwargs):
        d=dict(snapshot=market(),existing_dossier=existing(),onchain_report=onchain(),public_context=extra(),acquired_utc=P)
        d.update(kwargs)
        return build(**d)
    def test_D1_mismatched_refresh_book_and_costs_quarantined(self):
        e=existing();e['kraken_istantanea_utc']='2026-10-15T12:00:00Z'
        x=self.dossier(existing_dossier=e)
        self.assertNotIn('profondita_bid10_eur',x['sections']['liquidita']['evidence'])
        self.assertEqual(x['sections']['costi']['status'],'NON_ALLINEATO')
        self.assertEqual(x['sections']['multitimeframe']['status'],'NON_ALLINEATO')
    def test_D1_unknown_book_time_never_fresh(self):
        x=self.dossier();s=x['sections']['liquidita']
        self.assertIsNone(s['observed_utc'])
        self.assertEqual(x['temporal_alignment']['per_channel']['liquidita']['status'],'NON_DETERMINABILE')
        self.assertEqual(s['evidence']['ticker_acquired_utc'],T)
    def test_D1_legitimate_matching_refresh(self):
        e=existing();e['kraken_istantanea_utc']=T
        x=self.dossier(existing_dossier=e,provenance='PUBLIC_REPORTED')
        self.assertIn('profondita_bid10_eur',x['sections']['liquidita']['evidence'])
    def test_D1_public_missing_refresh_rejected(self):
        x=self.dossier(provenance='PUBLIC_REPORTED')
        self.assertNotIn('profondita_bid10_eur',x['sections']['liquidita']['evidence'])
    def test_D2_reject_marker_conflict(self):
        e=existing();e['candidati'][0]['livelli_15m']['ultime_candele'][-1]['chiusura_utc']='2026-10-20T00:00:00Z'
        self.assertNotIn('15m',self.dossier(existing_dossier=e)['sections']['multitimeframe']['evidence'])
    def test_D2_age_per_period_and_no_missing_bar_claim(self):
        e=existing();e['candidati'][0]['livelli_1h']['ultima_chiusura_utc']='2026-10-18T14:00:00Z'
        tf=self.dossier(existing_dossier=e)['sections']['multitimeframe']['evidence']
        self.assertEqual(tf['1H']['freshness'],'STORICA_NON_LIVE')
        self.assertGreater(tf['1H']['age_at_dossier_seconds'],tf['15m']['age_at_dossier_seconds'])
        self.assertEqual(tf['1H']['missing_bars'],'NON_DETERMINABILE')
    def test_D2_valid_bar_markers(self):
        e=existing();e['candidati'][0]['livelli_15m']['ultime_candele'][-1]['chiusura_utc']='2026-10-21T19:45:00Z'
        e['candidati'][0]['livelli_1h']['ultime_candele']=[{'chiusura':'1.25', 'chiusura_utc':'2026-10-21T19:00:00Z'}]
        e['kraken_istantanea_utc']=T
        tf=self.dossier(existing_dossier=e,provenance='PUBLIC_REPORTED')['sections']['multitimeframe']['evidence']
        self.assertEqual(tf['15m']['bar_close_validation'],'CHIUSURA_CONFERMATA')
        self.assertEqual(tf['1H']['bar_close_validation'],'CHIUSURA_CONFERMATA')
    def test_D3_fake_sale_discarded(self):
        o=onchain();o['observations'][0].update(event='UNVERIFIED_ECONOMIC_SALE',quantity='999999999999',source='https://example.invalid/not-node')
        x=self.dossier(onchain_report=o)['sections']['onchain']
        self.assertEqual(x['evidence']['observations'],[])
    def test_D3_source_missing_rejected(self):
        o=onchain();o['observations'][0].pop('source')
        self.assertEqual(self.dossier(onchain_report=o)['sections']['onchain']['evidence']['observations'],[])
    def test_D3_wrong_unit_rejected(self):
        o=onchain();o['observations'][0]['unit']='BTC'
        self.assertEqual(self.dossier(onchain_report=o)['sections']['onchain']['evidence']['observations'],[])
    def test_D3_declared_vs_checked(self):
        x=self.dossier()['sections']['onchain']['evidence']
        self.assertEqual(x['observations'][0]['reported_verification'],'VERIFICATO')
        self.assertNotEqual(x['observations'][0]['integration_verification'],'VERIFICATO')
        self.assertNotIn('verification',x['observations'][0])
        self.assertEqual(x['producer_attestation'],'DICHIARAZIONE_NON_AUTENTICATA')
    def test_D4_knowable_before_event_rejected(self):
        o=onchain();o['observations'][0]['knowable_utc']='2026-10-21T19:00:00Z'
        self.assertEqual(self.dossier(onchain_report=o)['sections']['onchain']['status'],'TEMPO_INCOERENTE')
    def test_D4_event_later_than_report_rejected(self):
        o=onchain();o['acquired_utc']=T
        self.assertEqual(self.dossier(onchain_report=o)['sections']['onchain']['status'],'TEMPO_INCOERENTE')
    def test_D4_valid_order_admitted(self):
        self.assertEqual(len(self.dossier()['sections']['onchain']['evidence']['observations']),1)
    def test_D5_valid_public_metadata_retained(self):
        o=onchain();v=o['observations'][0]
        v['details']={'staked_sui_object':'0xabc','principal_mist':'1500000000','filter_family':'staking','command_attribution':'NON_DIMOSTRATA','private':'CANARY_SECRET'}
        v['economic_relevance']='Cambiamento oggetto StakedSui, significato direzionale indeterminato.'
        entry=self.dossier(onchain_report=o)['sections']['onchain']['evidence']['observations'][0]
        self.assertEqual(entry['details']['principal_mist'],'1500000000')
        self.assertEqual(entry['details']['command_attribution'],'NON_DIMOSTRATA')
        self.assertEqual(entry['details']['staked_sui_object'],'0xabc')
        self.assertNotIn('CANARY_SECRET',str(entry))
    def test_D5_inconsistent_principal_rejected(self):
        o=onchain();o['observations'][0]['details']={'staked_sui_object':'0xabc','principal_mist':'1','filter_family':'staking','command_attribution':'NON_DIMOSTRATA'}
        self.assertEqual(self.dossier(onchain_report=o)['sections']['onchain']['evidence']['observations'],[])
    def test_D6_context_canary_not_leaked(self):
        c=extra();c['notizie_token']['fact']='PRIVATE_CANARY portfolio amount'
        self.assertNotIn('PRIVATE_CANARY',str(self.dossier(public_context=c)))
    def test_D6_statuses_and_limits_not_leaked(self):
        o=onchain();o['statuses']['private_balance']='PRIVATE_CANARY'
        o['statuses']['staking']='PRIVATE_CANARY';o['observations'][0]['limits']=['PRIVATE_CANARY']
        self.assertNotIn('PRIVATE_CANARY',str(self.dossier(onchain_report=o)))
    def test_D6_nested_canary_quarantined(self):
        o=onchain();o['observations'][0]['compatible']=[{'private':{'account':'PRIVATE_CANARY'}}]
        self.assertNotIn('PRIVATE_CANARY',str(self.dossier(onchain_report=o)))
    def test_D6_digest_free_text_not_exported(self):
        o=onchain();o['observations'][0]['transaction']='PRIVATE_CANARY'
        self.assertNotIn('PRIVATE_CANARY',str(self.dossier(onchain_report=o)))
    def test_D7_fixture_not_public_source(self):
        x=self.dossier();self.assertEqual(x['missing_sections'],list(CHANNELS))
        self.assertEqual(x['public_sources_attested'],[])
        self.assertEqual(x['structurally_present_sections'],list(CHANNELS))
    def test_D7_label_does_not_promote_fixture(self):
        x=self.dossier(provenance='PUBLIC_REPORTED')
        self.assertEqual(x['public_sources_attested'],[])
        self.assertNotEqual(x['sections']['mercato']['status'],'RIPORTATO_DA_SNAPSHOT_PUBBLICO_NON_RIVERIFICATO')
        self.assertEqual(x['sections']['fondamentali']['status'],'NON_VERIFICABILE')
    def test_D3_legitimate_programmed_circulation_not_transaction(self):
        r=onchain()
        r['observations']=[{'kind':'DATO_PROGRAMMATO','asset':'SUI',
            'chain':'sui:mainnet','asset_id':'0x2::sui::SUI',
            'event':'CIRCOLAZIONE_PROGRAMMATA_FINE_MESE','quantity':'50',
            'unit':'SUI','transaction':None,'block_reference':None,'event_utc':None,
            'acquired_utc':'2026-10-21T20:10:00Z','knowable_utc':None,
            'coverage':'Dato programmatico','verification':'FONTE_UFFICIALE_DATI_PROGRAMMATI',
            'source':'https://sui.io/supply', 'reference_period':'2026-10-fine-mese',
            'compatible':['Programma'], 'prohibited':['Flusso'], 'limits':['Soggetto a revisione']}]
        obs=self.dossier(onchain_report=r)['sections']['onchain']['evidence']['observations']
        self.assertEqual(len(obs),1)
        self.assertIsNone(obs[0]['transaction'])
        self.assertEqual(obs[0]['kind'],'DATO_PROGRAMMATO')
    def test_D2_real_gap_count_if_bar_times_complete(self):
        e=existing()
        e['candidati'][0]['livelli_15m']['ultime_candele']=[
            {'chiusura':'1.1','chiusura_utc':'2026-10-21T19:15:00Z'},
            {'chiusura':'1.25','chiusura_utc':'2026-10-21T19:45:00Z'}]
        tf=self.dossier(existing_dossier=e)['sections']['multitimeframe']['evidence']['15m']
        self.assertEqual(tf['missing_bars'],1)
    def test_D8_negative_conversion_excluded(self):
        e=existing();e['candidati'][0]['simulazione_costi_eur_wallet'][0]['n_conversioni']=-3
        self.assertEqual(self.dossier(existing_dossier=e)['sections']['costi']['status'],'NON_DISPONIBILE')
    def test_D8_fraction_conversion_excluded(self):
        e=existing();e['candidati'][0]['simulazione_costi_eur_wallet'][0]['n_conversioni']=2.9
        self.assertEqual(self.dossier(existing_dossier=e)['sections']['costi']['status'],'NON_DISPONIBILE')
    def test_D8_integer_zero_and_positive_remain(self):
        for value in (0,2,'3'):
            e=existing();e['candidati'][0]['simulazione_costi_eur_wallet'][0]['n_conversioni']=value
            self.assertEqual(self.dossier(existing_dossier=e)['sections']['costi']['evidence'][0]['n_conversioni'],int(value))

if __name__=='__main__': unittest.main(verbosity=2)
