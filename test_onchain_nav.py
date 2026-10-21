"""G2 original cases retained, plus G2R1 adverse regressions. Pure synthetic fixtures."""
import json
import unittest
import urllib.error
from datetime import datetime, timezone
from unittest.mock import patch
from dataclasses import FrozenInstanceError

import onchain_nav_core as core
import onchain_nav_sui as sui

DIGEST='9jpePvm98WscMhGj4S9YGucWrcCT4RtuLrCdVsPkc6am'  # fixture only
STAMP='2026-10-21T12:00:00Z'
OBJ='0xabc123'


def change(*, principal='18208340000000', deleted=False, obj=OBJ):
    state={'contents':{'type':{'repr':'0x0003::staking_pool::StakedSui'}, 'json':{'principal':principal}}}
    return {'address':obj,'idCreated':not deleted,'idDeleted':deleted,
            'inputState':{'asMoveObject':state} if deleted else None,
            'outputState':None if deleted else {'asMoveObject':state}}


def tx(*, status='SUCCESS', changes=None, stamp=STAMP, cp='336510802', more=False, cursor=None):
    return {'digest':DIGEST,'effects':{'status':status,'timestamp':stamp,
      'checkpoint':{'sequenceNumber':cp}, 'objectChanges':{
      'nodes':changes if changes is not None else [change()],
      'pageInfo':{'hasNextPage':more,'endCursor':cursor}}}}


def identity(covered=True):
    return {'chainIdentifier':'35834a8a','serviceConfig':{'availableRange':
        {'first':{'sequenceNumber':'336000000'},'last':{'sequenceNumber':'336510900'}} if covered else None}}


def filter_nodes(nodes=None, previous=False):
    return {'transactions':{'nodes':nodes if nodes is not None else [{'digest':DIGEST}],
        'pageInfo':{'hasPreviousPage':previous, 'startCursor':'back' if previous else None}}}


class ContextTests(unittest.TestCase):
    # G2 original 5
    def test_decimal(self):
        self.assertEqual(core.units('18208340000000'),'18208.34')
        self.assertEqual(core.units('1'),'0.000000001')

    def test_bad_integer(self):
        for value in (-1,0,True,'1.1',' 1',2**64,1.0):
            with self.subTest(value=value),self.assertRaises(ValueError): core.units(value)

    def test_utc(self):
        self.assertEqual(core.utc('2026-10-21T12:00:00+00:00'),STAMP)
        for value in ('2026-10-21T12:00:00','2026-10-21T14:00:00+02:00','2500-01-01T00:00:00Z'):
            with self.subTest(value=value), self.assertRaises(ValueError): core.utc(value)

    def test_common_interface_no_market_signal(self):
        obs,_=sui.parse_stake(tx(),'staking','2026-10-21T12:00:01Z','3 examples')
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
    # G2 original 17 (updated expected classification where G2R1 intentionally corrects it)
    def test_chain_identity(self):
        self.assertTrue(sui.mainnet('35834a8a'))
        self.assertFalse(sui.mainnet('4c78adac'))
        self.assertFalse(sui.mainnet(None))
        self.assertTrue(sui.mainnet('4btiuiMPvEENsttpZC7CZ53DruC3MAgfznDbASZ7DR6S'))

    def test_verified_stake(self):
        result,status=sui.parse_stake(tx(),'staking','2026-10-21T12:00:01Z','3 examples')
        self.assertEqual(status,'OGGETTO_VERIFICATO_ATTRIBUZIONE_NON_DIMOSTRATA')
        self.assertEqual(result[0].quantity,'18208.34')
        self.assertEqual(result[0].transaction,DIGEST)
        self.assertEqual(result[0].block_reference,'336510802')
        self.assertEqual(result[0].event,'STAKED_SUI_OGGETTO_CREATO')

    def test_unstake_principal_not_net_funds(self):
        obs,status=sui.parse_stake(tx(changes=[change(deleted=True)]),'unstaking','2026-10-21T12:00:01Z','3 examples')
        self.assertEqual(status,'OGGETTO_VERIFICATO_ATTRIBUZIONE_NON_DIMOSTRATA')
        self.assertEqual(obs[0].event,'STAKED_SUI_OGGETTO_CONSUMATO')
        self.assertNotIn('reward',obs[0].details)

    def test_failed_tx(self):
        self.assertEqual(sui.parse_stake(tx(status='FAILURE'),'staking','2026-10-21T12:00:01Z','coverage'),([], 'TRANSAZIONE_FALLITA'))

    def test_event_missing_not_zero(self):
        o,s=sui.parse_stake(tx(changes=[]),'staking','2026-10-21T12:00:01Z','coverage')
        self.assertEqual((o,s),([],'EVENTO_NON_VERIFICABILE'))

    def test_identity_ambiguous(self):
        t=tx(changes=[{'address':OBJ,'idCreated':True, 'outputState':{
          'asMoveObject':{'contents':{'type':{'repr':'0x4::staking_pool::StakedSui'},'json':{'principal':'99'}}}}}])
        self.assertEqual(sui.parse_stake(t,'staking','2026-10-21T12:00:01Z','coverage')[0],[])

    def test_dedup(self):
        self.assertEqual(len(sui.parse_stake(tx(changes=[change(),change()]),'staking','2026-10-21T12:00:01Z','coverage')[0]),1)

    def test_inconsistent_timestamp(self):
        with self.assertRaises(sui.SourceProblem):
            sui.parse_stake(tx(stamp='2026-10-21T14:00:00+02:00'),'staking','2026-10-21T12:00:01Z','coverage')

    def test_missing_graphql_data(self):
        with self.assertRaises(sui.SourceProblem):
            sui.parse_stake({'digest':DIGEST,'effects':{'status':'SUCCESS'}},'staking','2026-10-21T12:00:01Z','coverage')

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
        def blocked(req,timeout):raise urllib.error.HTTPError(sui.ENDPOINT,429,'limited',{},None)
        with self.assertRaises(sui.SourceProblem) as raised:sui.post_graphql(sui.IDENTITY,transport=blocked)
        self.assertEqual(raised.exception.state,'RATE_LIMIT')

    def test_timeout(self):
        def blocked(req,timeout):raise TimeoutError()
        with self.assertRaises(sui.SourceProblem) as raised:sui.post_graphql(sui.IDENTITY,transport=blocked)
        self.assertEqual(raised.exception.state,'FONTE_NON_DISPONIBILE')

    def test_bounded_run(self):
        calls=[]
        def req(q,vars=None):
            calls.append((q,vars))
            if q==sui.IDENTITY:return identity()
            if q==sui.FILTER:return filter_nodes()
            if q==sui.LOOKUP:return {'transaction':tx(changes=[change(deleted=len(calls)==5)])}
            raise AssertionError('query inattesa')
        report=sui.run(request=req)
        self.assertEqual(report['requests_made'],5)
        self.assertEqual(report['statuses']['identity'],'VERIFICATA')
        self.assertEqual(report['statuses']['staking'],'OGGETTO_VERIFICATO_ATTRIBUZIONE_NON_DIMOSTRATA')
        self.assertEqual(report['statuses']['unstaking'],'OGGETTO_VERIFICATO_ATTRIBUZIONE_NON_DIMOSTRATA')
        self.assertEqual(len(report['observations']),2)
        self.assertEqual(report['decision_utility'],'NON_DIMOSTRATA')

    def test_no_network_on_wrong_chain(self):
        calls=[]
        def req(q,vars=None):
            calls.append(q)
            return {'chainIdentifier':'4c78adac'}
        report=sui.run(request=req)
        self.assertEqual(report['requests_made'],1)
        self.assertEqual(report['statuses']['staking'],'NON_ESEGUITO_IDENTITA_NON_VERIFICATA')

    def test_history_missing_not_zero(self):
        def req(q,vars=None):
            if q==sui.IDENTITY:return identity(covered=False)
            return filter_nodes(nodes=[])
        d=sui.run(request=req)
        self.assertEqual(d['coverage'],'NON_DETERMINABILE')
        self.assertEqual(d['statuses']['staking'],'NESSUN_EVENTO_NEL_CAMPIONE')
        self.assertEqual(d['statuses']['staking_coverage'],'COPERTURA_INSUFFICIENTE')
        self.assertEqual(d['observations'],[])


class RemediationTests(unittest.TestCase):
    def test_milliseconds_full_precision(self):
        class FrozenTime(datetime):
            @classmethod
            def now(cls,tz=None): return datetime(2026,10,21,12,0,0,500000,tzinfo=timezone.utc)
        with patch.object(core,'datetime',FrozenTime):
            self.assertEqual(core.utc('2026-10-21T12:00:00.100000Z'),'2026-10-21T12:00:00.100000Z')
            with self.assertRaises(ValueError):core.utc('2026-10-21T12:00:00.600000Z')

    def test_knowability_not_assumed(self):
        obs,_=sui.parse_stake(tx(),'staking','2026-10-21T12:00:01.123Z','bounded')
        self.assertIsNone(obs[0].knowable_utc)
        d=obs[0].to_decision_context()
        self.assertEqual(d['knowability_status'],'NON_DETERMINABILE')
        self.assertNotEqual(d['event_utc'],d['acquired_utc'])

    def test_temporal_order_invalid(self):
        with self.assertRaises(sui.SourceProblem):
            sui.parse_stake(tx(stamp='2026-10-21T12:00:02Z'),'staking','2026-10-21T12:00:01Z','partial')
        valid,_=sui.parse_stake(tx(),'staking','2026-10-21T12:00:01Z','partial')
        vals={f.name:getattr(valid[0],f.name) for f in __import__('dataclasses').fields(valid[0])}
        vals['knowable_utc']='2026-10-21T11:59:59Z'
        with self.assertRaises(ValueError):core.Observation(**vals)

    def test_pagination_later_object(self):
        first=tx(changes=[],more=True,cursor='p2')
        def later(d,c):
            self.assertEqual((d,c),(DIGEST,'p2'))
            return tx(changes=[change()],more=False)
        merged=sui.collect_pages(first,later)
        obs,_=sui.parse_stake(merged,'staking','2026-10-21T12:00:01Z','partial')
        self.assertEqual(len(obs),1)

    def test_pagination_incomplete_no_claim(self):
        first=tx(changes=[change()],more=True,cursor='p2')
        with self.assertRaises(sui.SourceProblem) as cm:
            sui.collect_pages(first,lambda d,c:tx(changes=[],more=True,cursor='p2'))
        self.assertEqual(cm.exception.state,'RISPOSTA_INCOMPLETA')
        with self.assertRaises(sui.SourceProblem):
            sui.parse_stake(first,'staking','2026-10-21T12:00:01Z','partial')

    def test_pagination_missing_cursor(self):
        with self.assertRaises(sui.SourceProblem) as cm:
            sui.collect_pages(tx(more=True,cursor=None),lambda d,c:None)
        self.assertEqual(cm.exception.state,'RISPOSTA_INCOMPLETA')

    def test_pagination_different_checkpoint(self):
        with self.assertRaises(sui.SourceProblem) as cm:
            sui.collect_pages(tx(more=True,cursor='p2'),lambda d,c:tx(cp='336510803'))
        self.assertEqual(cm.exception.state,'EVENTO_NON_VERIFICABILE')

    def test_multicommand_no_attribution(self):
        obs,_=sui.parse_stake(tx(changes=[change(),change(deleted=True,obj='0x456')]),'staking','2026-10-21T12:00:01Z','partial')
        self.assertEqual({o.event for o in obs},{'STAKED_SUI_OGGETTO_CREATO','STAKED_SUI_OGGETTO_CONSUMATO'})
        self.assertTrue(all(o.details['command_attribution']=='NON_DIMOSTRATA' for o in obs))
        self.assertTrue(all('STAKING_PRINCIPALE'!=o.event for o in obs))

    def test_cross_filter_no_double_attribution(self):
        def req(q,vars=None):
            if q==sui.IDENTITY:return identity()
            if q==sui.FILTER:return filter_nodes()
            return {'transaction':tx()}
        d=sui.run(request=req)
        self.assertEqual(len(d['observations']),1)
        self.assertEqual(d['statuses']['cross_filter_duplicate'],'SCARTATO')

    def test_invalid_json_shapes(self):
        for malformed in ('not a dict',None,{'transaction':'invalid'}):
            with self.subTest(malformed=malformed),self.assertRaises(sui.SourceProblem):
                if isinstance(malformed,dict):sui.collect_pages(malformed['transaction'],lambda d,c:None)
                else:sui.parse_stake(malformed,'staking','2026-10-21T12:00:01Z','partial')

    def test_type_shape_in_staked_object(self):
        bad=change()
        bad['outputState']['asMoveObject']['contents']['type']='INVALID'
        with self.assertRaises(sui.SourceProblem):
            sui.parse_stake(tx(changes=[bad]),'staking','2026-10-21T12:00:01Z','partial')

    def test_missing_graphql_connection(self):
        bad=tx();del bad['effects']['objectChanges']['pageInfo']
        with self.assertRaises(sui.SourceProblem) as cm:sui.parse_stake(bad,'staking','2026-10-21T12:00:01Z','partial')
        self.assertEqual(cm.exception.state,'RISPOSTA_INCOMPLETA')

    def test_no_events_in_sample_distinguished(self):
        def req(q,vars=None):
            if q==sui.IDENTITY:return identity()
            return filter_nodes(nodes=[],previous=True)
        out=sui.run(request=req)
        self.assertEqual(out['statuses']['staking'],'NESSUN_EVENTO_NEL_CAMPIONE')
        self.assertEqual(out['statuses']['staking_coverage'],'COPERTURA_INSUFFICIENTE')

    def test_filter_partial_json(self):
        def req(q,vars=None):
            if q==sui.IDENTITY:return identity()
            return {'transactions':{'nodes':[]}}
        out=sui.run(request=req)
        self.assertEqual(out['statuses']['staking'],'RISPOSTA_INCOMPLETA')

    def test_immutable_nested_details_and_detached_output(self):
        obs,_=sui.parse_stake(tx(),'staking','2026-10-21T12:00:01Z','partial')
        with self.assertRaises(TypeError):obs[0].details['abc']='x'
        with self.assertRaises(FrozenInstanceError):obs[0].event='BUY'
        out=obs[0].to_decision_context();out['details']['principal_mist']='0'
        self.assertNotEqual(out['details']['principal_mist'],obs[0].details['principal_mist'])

    def test_no_economic_signal(self):
        obs,_=sui.parse_stake(tx(),'staking','2026-10-21T12:00:01Z','partial')
        d=obs[0].to_decision_context()
        self.assertEqual(d['decision_status'],'CONTESTO_INFORMATIVO_NON_PREDITTIVO')
        self.assertFalse(any(k in d for k in ('buy','sell','signal','prediction','probability')))
        self.assertEqual(d['verification'],'VERIFICATO')
        self.assertNotIn('VERIFICATA', d['details']['command_attribution'])

    def test_run_page_budget_not_partial_as_verified(self):
        def req(q,vars=None):
            if q==sui.IDENTITY:return identity()
            if q==sui.FILTER:return filter_nodes()
            return {'transaction':tx(changes=[change()],more=True,cursor='continua')}
        report=sui.run(request=req)
        self.assertLessEqual(report['requests_made'],sui.MAX_CALLS)
        self.assertEqual(report['statuses']['staking'],'RISPOSTA_INCOMPLETA')
        self.assertFalse(report['observations'])


if __name__=='__main__':unittest.main(verbosity=2)
