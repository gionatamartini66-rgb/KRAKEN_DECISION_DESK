"""Synthetic G2 regression tests. No internet, no private data."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error

import onchain_nav_core as core
import onchain_nav_sui as sui

DIGEST='9jpePvm98WscMhGj4S9YGucWrcCT4RtuLrCdVsPkc6am'
STAMP='2026-10-21T12:00:00Z'
OBJ='0xabc123'


def change(*, kind='staking', principal='18208340000000', deleted=False):
    obj={'contents':{'type':{'repr':'0x0003::staking_pool::StakedSui'},
                     'json':{'principal':principal}}}
    return {'address':OBJ,'idCreated':not deleted,'idDeleted':deleted,
            'inputState': {'asMoveObject':obj} if deleted else None,
            'outputState': None if deleted else {'asMoveObject':obj}}


def tx(*, status='SUCCESS', changes=None, stamp=STAMP, cp='336510802'):
    return {'digest':DIGEST,'effects':{'status':status,'timestamp':stamp,
      'checkpoint':{'sequenceNumber':cp},'objectChanges':{'nodes':changes if changes is not None else [change()]}}}


class ContextTests(unittest.TestCase):
    def test_decimal(self):
        self.assertEqual(core.units('18208340000000'),'18208.34')
        self.assertEqual(core.units('1'),'0.000000001')

    def test_bad_integer(self):
        for value in (-1,0,True,'1.1',' 1',2**64,1.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                core.units(value)

    def test_utc(self):
        self.assertEqual(core.utc('2026-10-21T12:00:00+00:00'),STAMP)
        for value in ('2026-10-21T12:00:00','2026-10-21T14:00:00+02:00','2500-01-01T00:00:00Z'):
            with self.subTest(value=value),self.assertRaises(ValueError): core.utc(value)

    def test_common_interface_no_market_signal(self):
        obs,_=sui.parse_stake(tx(),'staking',STAMP,'3 esempi')
        d=obs[0].to_decision_context()
        self.assertEqual(d['chain'],'sui:mainnet')
        self.assertEqual(d['decision_status'],'CONTESTO_INFORMATIVO_NON_PREDITTIVO')
        self.assertNotIn('BUY',d)

    def test_other_chain_shape_possible(self):
        o=core.Observation(kind='NON_DISPONIBILE',asset='TEST',chain='other:network',asset_id='other-id',
           event='UNKNOWN',quantity=None,unit=None,transaction=None,block_reference=None,event_utc=None,
           acquired_utc=STAMP,reference_period=None,knowable_utc=None,source='public',coverage='unknown',
           verification='ASSENTE',limits=('missing',),compatible=(),prohibited=('inference',))
        self.assertEqual(o.to_decision_context()['chain'],'other:network')


class SuiTests(unittest.TestCase):
    def test_chain_identity(self):
        self.assertTrue(sui.mainnet('35834a8a'))
        self.assertFalse(sui.mainnet('4c78adac'))
        self.assertFalse(sui.mainnet(None))
        self.assertTrue(sui.mainnet('4btiuiMPvEENsttpZC7CZ53DruC3MAgfznDbASZ7DR6S'))

    def test_verified_stake(self):
        result,status=sui.parse_stake(tx(),'staking',STAMP,'3 esempi')
        self.assertEqual(status,'VERIFICATO')
        self.assertEqual(result[0].quantity,'18208.34')
        self.assertEqual(result[0].transaction,DIGEST)
        self.assertEqual(result[0].block_reference,'336510802')

    def test_unstake_principal_not_net_funds(self):
        t=tx(changes=[change(deleted=True)])
        observations,status=sui.parse_stake(t,'unstaking',STAMP,'3 esempi')
        self.assertEqual(status,'VERIFICATO')
        self.assertEqual(observations[0].event,'UNSTAKING_PRINCIPALE_CONSUMATO')
        self.assertNotIn('reward',observations[0].details)

    def test_failed_tx(self):
        self.assertEqual(sui.parse_stake(tx(status='FAILURE'),'staking',STAMP,'coverage'),([], 'TRANSAZIONE_FALLITA'))

    def test_event_missing_not_zero(self):
        o,s=sui.parse_stake(tx(changes=[]),'staking',STAMP,'coverage')
        self.assertEqual((o,s),([],'EVENTO_NON_VERIFICABILE'))

    def test_identity_ambiguous(self):
        t=tx(changes=[{'address':OBJ,'idCreated':True,'outputState':{
             'asMoveObject':{'contents':{'type':{'repr':'0x4::staking_pool::StakedSui'},'json':{'principal':'99'}}}}}])
        self.assertEqual(sui.parse_stake(t,'staking',STAMP,'coverage')[0],[])

    def test_dedup(self):
        t=tx(changes=[change(),change()])
        self.assertEqual(len(sui.parse_stake(t,'staking',STAMP,'coverage')[0]),1)

    def test_inconsistent_timestamp(self):
        with self.assertRaises(sui.SourceProblem):
            sui.parse_stake(tx(stamp='2026-10-21T14:00:00+02:00'),'staking',STAMP,'coverage')

    def test_missing_graphql_data(self):
        with self.assertRaises(sui.SourceProblem):
            sui.parse_stake({'digest':DIGEST,'effects':{'status':'SUCCESS'}},'staking',STAMP,'coverage')

    def test_programmed_not_actual(self):
        d=sui.parse_circulation({'year':2026,'month':10,'circulatingSupplyValue':4118270447.6403894},STAMP)
        self.assertEqual(d.kind,'DATO_PROGRAMMATO')
        self.assertIsNone(d.transaction)
        self.assertEqual(d.reference_period,'2026-10-fine-mese')
        self.assertNotIn('STAKING',d.event)

    def test_bad_program(self):
        with self.assertRaises(sui.SourceProblem):
            sui.parse_circulation({'year':2026,'month':13,'circulatingSupplyValue':4118},STAMP)

    def test_graphql_errors_even_http_200(self):
        class Stream:
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def read(self,n):return b'{"data":{"chainIdentifier":"35834a8a"},"errors":[{"message":"partial"}]}'
        with self.assertRaises(sui.SourceProblem) as raised:
            sui.post_graphql(sui.IDENTITY,transport=lambda req,timeout:Stream())
        self.assertEqual(raised.exception.state,'ERRORE_GRAPHQL')

    def test_rate_limit(self):
        def blocked(req,timeout):
            raise urllib.error.HTTPError(sui.ENDPOINT,429,'limited',{},None)
        with self.assertRaises(sui.SourceProblem) as raised:
            sui.post_graphql(sui.IDENTITY,transport=blocked)
        self.assertEqual(raised.exception.state,'RATE_LIMIT')

    def test_timeout(self):
        def blocked(req,timeout):raise TimeoutError()
        with self.assertRaises(sui.SourceProblem) as raised:
            sui.post_graphql(sui.IDENTITY,transport=blocked)
        self.assertEqual(raised.exception.state,'FONTE_NON_DISPONIBILE')

    def test_bounded_run(self):
        calls=[]
        def req(q, vars=None):
            calls.append((q,vars))
            if q==sui.IDENTITY:
                return {'chainIdentifier':'35834a8a','serviceConfig':{'availableRange':{'first':{'sequenceNumber':'336000000'},'last':{'sequenceNumber':'336510900'}}}}
            if q==sui.FILTER:
                return {'transactions':{'nodes':[{'digest':DIGEST}]}}
            if q==sui.LOOKUP:
                return {'transaction':tx(changes=[change(deleted=len(calls)==5)])}
            raise AssertionError('query inattesa')
        report=sui.run(request=req)
        self.assertEqual(report['requests_made'],5)
        self.assertEqual(report['statuses']['identity'],'VERIFICATA')
        self.assertEqual(report['statuses']['staking'],'VERIFICATO')
        self.assertEqual(report['statuses']['unstaking'],'VERIFICATO')
        self.assertEqual(len(report['observations']),2)
        self.assertEqual(report['decision_utility'],'NON_DIMOSTRATA')

    def test_no_network_on_wrong_chain(self):
        calls=[]
        def req(q, vars=None):
            calls.append(q)
            return {'chainIdentifier':'4c78adac'}
        report=sui.run(request=req)
        self.assertEqual(report['requests_made'],1)
        self.assertEqual(report['statuses']['staking'],'NON_ESEGUITO_IDENTITA_NON_VERIFICATA')

    def test_history_missing_not_zero(self):
        def req(q, vars=None):
            if q==sui.IDENTITY:return {'chainIdentifier':'35834a8a','serviceConfig':{}}
            return {'transactions':{'nodes':[]}}
        d=sui.run(request=req)
        self.assertEqual(d['coverage'],'NON_DETERMINABILE')
        self.assertEqual(d['statuses']['staking'],'EVENTO_NON_TROVATO')
        self.assertEqual(d['observations'],[])


if __name__=='__main__': unittest.main(verbosity=2)
