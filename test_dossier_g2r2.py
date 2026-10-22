"""G2R2 bounded regression checks against G0 SOL probes (synthetic only).
No source authentication, no external requests, accounts or financial operations.
"""
import copy
import unittest
from navigatore_dossier import build, CHANNELS
from test_navigatore_dossier import market, existing, onchain, extra, P, T

DIGEST = '7AbcDefGhijkMnpQRSTuvWxyz' * 2
COINGECKO_URL=('https://api.coingecko.com/api/v3/coins/sui'
               '?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false')


def make(**changes):
    args=dict(snapshot=market(),existing_dossier=existing(),onchain_report=onchain(),
              public_context=extra(),acquired_utc=P)
    args.update(changes)
    return build(**args)


def staked_report():
    r=onchain()
    r['observations'][0].update(transaction=DIGEST,details={
        'staked_sui_object':'0xabc', 'principal_mist':'1500000000',
        'filter_family':'staking','command_attribution':'NON_DIMOSTRATA'})
    return r


class G2R2Remediation(unittest.TestCase):
    def test_p15_future_market_quarantines_book_costs(self):
        m=market();m['rilevazione_utc']='2026-10-21T20:20:00Z'
        e=existing();e['kraken_istantanea_utc']=m['rilevazione_utc']
        out=make(snapshot=m,existing_dossier=e,provenance='PUBLIC_REPORTED')
        for label in ('mercato','liquidita','costi'):
            self.assertEqual(out['sections'][label]['status'],'TEMPO_INCOERENTE')
        self.assertIsNone(out['sections']['costi']['evidence'])
        self.assertIsNone(out['sections']['liquidita']['evidence'])
        self.assertEqual(out['sections']['mercato']['evidence']['prezzo_eur'],'1.25')  # audit, not usable

    def test_p15_future_market_alignment_never_claims_synchrony(self):
        m=market();m['rilevazione_utc']='2026-10-21T20:20:00Z'
        e=existing();e['kraken_istantanea_utc']='2026-10-20T20:20:00Z'
        out=make(snapshot=m,existing_dossier=e)
        self.assertEqual(out['temporal_alignment']['status'],'TEMPO_INCOERENTE')
        self.assertEqual(out['sections']['costi']['status'],'TEMPO_INCOERENTE')
        self.assertEqual(out['sections']['liquidita']['status'],'TEMPO_INCOERENTE')
        self.assertIn('NON_ALLINEATO',' '.join(out['sections']['costi']['limits']))

    def test_p15_legitimate_book_and_costs_retained(self):
        e=existing();e['kraken_istantanea_utc']=T
        out=make(existing_dossier=e,provenance='PUBLIC_REPORTED')
        self.assertEqual(out['sections']['liquidita']['evidence']['profondita_bid10_eur'],'5000')
        self.assertEqual(out['sections']['costi']['evidence'][0]['costo_roundtrip_eur'],'2.5')
        self.assertIsNone(out['sections']['liquidita']['evidence']['book_acquired_utc'])

    def test_p05_postvalidation_indices_consistent(self):
        m=market();m['rilevazione_utc']='2026-10-21T20:20:00Z'
        out=make(snapshot=m)
        self.assertIn('mercato',out['structurally_missing_sections'])
        self.assertNotIn('mercato',out['structurally_present_sections'])
        self.assertEqual(out['section_availability']['mercato']['validita'],'NON_VALIDA')
        self.assertEqual(out['section_availability']['mercato']['struttura'],'PRESENTE')
        self.assertEqual(out['section_availability']['mercato']['utilizzabilita'],'NON_UTILIZZABILE')
        self.assertEqual(set(out['section_availability']),set(CHANNELS))

    def test_p06_coverage_source_g2r2_enums_retained(self):
        r=staked_report()
        r['coverage']={'first_checkpoint':336000000,'last_checkpoint':336500000,
                       'scope':'Query.transactions filter=function; campione limitato; contiguita interna non dimostrata'}
        r['statuses']['staking_coverage']='COPERTURA_INSUFFICIENTE'
        r['statuses']['unstaking_coverage']='CAMPIONE_LIMITATO_NON_GENERALE'
        ev=make(onchain_report=r)['sections']['onchain']['evidence']
        self.assertEqual(ev['reported_coverage']['first_checkpoint'],336000000)
        self.assertEqual(ev['reported_coverage']['last_checkpoint'],336500000)
        self.assertEqual(ev['source_statuses']['staking_coverage'],'COPERTURA_INSUFFICIENTE')
        self.assertEqual(ev['source_statuses']['unstaking_coverage'],'CAMPIONE_LIMITATO_NON_GENERALE')
        self.assertEqual(ev['producer_attestation'],'DICHIARAZIONE_NON_AUTENTICATA')

    def test_p06_malformed_reported_coverage_never_validated(self):
        for coverage in ({'first_checkpoint':9,'last_checkpoint':8,'scope':'BATCH_ONLY'},
                         {'first_checkpoint':True,'last_checkpoint':8,'scope':'BATCH_ONLY'},
                         {'first_checkpoint':1,'last_checkpoint':9,'scope':'PRIVATE_DATA'},
                         {'first_checkpoint':1,'last_checkpoint':9,'scope':{'canary':'PRIVATE'}}):
            with self.subTest(coverage=str(coverage)[:50]):
                r=staked_report();r['coverage']=coverage
                ev=make(onchain_report=r)['sections']['onchain']['evidence']
                self.assertEqual(ev['reported_coverage'],{'status':'COPERTURA_MALFORMATA'})
                self.assertNotIn('PRIVATE',str(ev))

    def test_p07_source_url_public_reported_separated_from_authentication(self):
        r=staked_report()
        entry=make(onchain_report=r)['sections']['onchain']['evidence']['observations'][0]
        self.assertEqual(entry['reported_source_url'],'https://graphql.mainnet.sui.io/graphql')
        self.assertEqual(entry['reported_source_authentication'],'NON_DIMOSTRATA')
        self.assertNotEqual(entry['integration_verification'],'VERIFICATO')

    def test_p07_arbitrary_https_path_and_query_not_echoed(self):
        r=staked_report();r['observations'][0]['source']='https://graphql.mainnet.sui.io/graphql?account=PRIVATE_CANARY'
        sec=make(onchain_report=r)['sections']['onchain']
        self.assertEqual(sec['evidence']['observations'],[])
        self.assertNotIn('PRIVATE_CANARY',str(sec))

    def test_p10_4h_incoherent_ohlcv_rejected(self):
        e=existing();bar=e['grafici_4h']['SUI']['serie_ohlcv_chiuse'][0]
        bar.update(open=1.25,high=.1,low=.09,close=1.25,volume_base=-10)
        tf=make(existing_dossier=e)['sections']['multitimeframe']['evidence']
        self.assertNotIn('4H',tf)

    def test_p10_15m_contradiction_rejected(self):
        e=existing();bar=e['candidati'][0]['livelli_15m']['ultime_candele'][-1]
        bar.update(apertura=1.25,massimo=0.5,minimo=0.4,volume_base=10)
        tf=make(existing_dossier=e)['sections']['multitimeframe']['evidence']
        self.assertNotIn('15m',tf)

    def test_p10_valid_producer_schema_and_legacy_marker_only(self):
        e=existing();bar=e['grafici_4h']['SUI']['serie_ohlcv_chiuse'][0]
        bar.update(open=1.2,high=1.35,low=1.15,volume_base=10)
        inner=make(existing_dossier=e)['sections']['multitimeframe']['evidence']
        self.assertEqual(inner['4H']['ohlcv_integrity'],'COERENZA_NUMERICA_OHLCV_CONTROLLATA')
        self.assertEqual(inner['15m']['ohlcv_integrity'],'NON_VERIFICATA_OHLCV_INCOMPLETO')
        self.assertEqual(inner['4H']['bar_close_validation'],'CHIUSURA_CONFERMATA')

    def test_p10_earlier_4h_bar_malformed_rejected(self):
        e=existing();bar=e['grafici_4h']['SUI']['serie_ohlcv_chiuse'][0]
        earlier=copy.deepcopy(bar);earlier['apertura_ts_utc']-=14400
        earlier.update(open=1.25,high=0.1,low=0.09,volume_base=10)
        e['grafici_4h']['SUI']['serie_ohlcv_chiuse'].insert(0,earlier)
        self.assertNotIn('4H',make(existing_dossier=e)['sections']['multitimeframe']['evidence'])

    def test_p11_conflicting_same_object_event_discards_both(self):
        r=staked_report()
        copy2=copy.deepcopy(r['observations'][0]);copy2['quantity']='2.5';copy2['details']['principal_mist']='2500000000'
        r['observations'].append(copy2)
        sec=make(onchain_report=r)['sections']['onchain']
        self.assertEqual(sec['status'],'RISPOSTA_INCOERENTE')
        self.assertEqual(sec['evidence']['observations'],[])
        self.assertEqual(sec['evidence']['conflicting_fact_keys'],1)

    def test_p11_identical_duplicates_deduplicated(self):
        r=staked_report();r['observations'].append(copy.deepcopy(r['observations'][0]))
        sec=make(onchain_report=r)['sections']['onchain']
        self.assertEqual(len(sec['evidence']['observations']),1)
        self.assertEqual(sec['evidence']['conflicting_fact_keys'],0)

    def test_p11_distinct_events_retained(self):
        r=staked_report();copy2=copy.deepcopy(r['observations'][0]);copy2['event']='STAKED_SUI_OGGETTO_CONSUMATO'
        copy2['details']['filter_family']='unstaking'
        r['observations'].append(copy2)
        self.assertEqual(len(make(onchain_report=r)['sections']['onchain']['evidence']['observations']),2)

    def test_p11_filter_event_mismatch_rejected(self):
        r=staked_report();r['observations'][0]['details']['filter_family']='unstaking'
        self.assertEqual(make(onchain_report=r)['sections']['onchain']['evidence']['observations'],[])

    def test_p12_error_cost_source_not_valid(self):
        e=existing();e['candidati'][0]['simulazione_costi_eur_wallet'][0]['errore']='FEE_SOURCE_NOT_AVAILABLE'
        self.assertEqual(make(existing_dossier=e)['sections']['costi']['status'],'NON_DISPONIBILE')

    def test_p12_valid_cost_keeps_available_original_assumptions(self):
        e=existing();r=e['candidati'][0]['simulazione_costi_eur_wallet'][0]
        r.update(importo_eur=100,costo_roundtrip_pct=2.5,fee_stimate_eur=1.2)
        result=make(existing_dossier=e)['sections']['costi']['evidence'][0]
        self.assertEqual(result['importo_eur'],'100')
        self.assertEqual(result['fee_stimate_eur'],'1.2')
        self.assertTrue(result['importo_originale_disponibile'])

    def test_p12_legacy_loss_audit_visible(self):
        x=make()['sections']['costi']
        self.assertFalse(x['evidence'][0]['importo_originale_disponibile'])
        self.assertIn('persi a monte',' '.join(x['limits']))

    def test_p08_existing_coingecko_numeric_subset_transported_unattested(self):
        e=existing();e['candidati'][0]['fondamentali_coingecko']={
            'id':'sui','fonte':COINGECKO_URL,'aggiornato_utc':'2026-10-21T19:55:00Z',
            'prezzo_usd':1.33,'capitalizzazione_usd':'1000000','offerta_circolante':123456,
            'offerta_totale':None, 'private':'PRIVATE_CANARY'}
        sec=make(existing_dossier=e)['sections']['fondamentali']
        self.assertEqual(sec['status'],'FONTE_NUMERICA_RIPORTATA_NON_ATTESTATA')
        self.assertEqual(sec['evidence']['coingecko_reported_numbers']['offerta_circolante'],'123456')
        self.assertNotIn('PRIVATE_CANARY',str(sec))
        self.assertNotIn('fondamentali',make(existing_dossier=e)['public_sources_attested'])

    def test_p08_forged_coingecko_identity_and_untrusted_free_text_blocked(self):
        e=existing();e['candidati'][0]['fondamentali_coingecko']={
            'id':'not-sui','fonte':COINGECKO_URL,'aggiornato_utc':T,'prezzo_usd':1.2}
        c=extra();c['notizie_token']['fact']='PRIVATE_CANARY leak'
        res=make(existing_dossier=e,public_context=c)
        self.assertNotIn('PRIVATE_CANARY',str(res))
        self.assertNotEqual(res['sections']['fondamentali']['status'],'FONTE_NUMERICA_RIPORTATA_NON_ATTESTATA')
        self.assertEqual(res['sections']['notizie_token']['evidence']['fact'],'CONTENUTO_NON_ATTESTATO_NON_ESPORTATO')

    def test_p09_digest_is_reported_not_authenticated(self):
        r=staked_report()
        sec=make(onchain_report=r,provenance='PUBLIC_REPORTED')['sections']['onchain']
        self.assertEqual(sec['evidence']['producer_attestation'],'DICHIARAZIONE_NON_AUTENTICATA')
        self.assertEqual(sec['evidence']['observations'][0]['transaction'],DIGEST)
        self.assertEqual(sec['evidence']['observations'][0]['reported_source_authentication'],'NON_DIMOSTRATA')
        self.assertEqual(make(onchain_report=r,provenance='PUBLIC_REPORTED')['public_sources_attested'],[])

if __name__=='__main__':unittest.main(verbosity=2)
