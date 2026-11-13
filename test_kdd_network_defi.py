"""KDD-16/17/19 regressions: network/DeFi HTTP replies are SYNTHETIC."""
import copy
import datetime as dt
import json
import unittest
from unittest import mock

import kdd_network_defi as evidence

T=dt.datetime(2026,11,11,14,30,tzinfo=dt.timezone.utc)
ISO=T.isoformat(timespec="seconds")


def fake_fetch(url, payload=None):
    if url==evidence.SUI_URL:
        assert payload=={"query":evidence.SUI_QUERY}
        return {"data":{"checkpoint":{"sequenceNumber":"343931063",
                                        "networkTotalTransactions":"1000000000",
                                        "timestamp":(T-dt.timedelta(seconds=4)).isoformat()},
                        "epoch":{"epochId":"1308","referenceGasPrice":"100"}}}
    if url==evidence.SOL_URL:
        assert payload["method"]=="getSupply"
        return {"jsonrpc":"2.0","id":1,"result":{
            "context":{"slot":468128016},
            "value":{"total":600000000000000000,
                     "circulating":500000000000000000,
                     "nonCirculating":100000000000000000}}}
    if url==evidence.CHAIN_URL:
        return [{"name":"Sui","tvl":411351240.64},
                {"name":"Solana","tvl":5080652974.44}]
    if url==evidence.DEX_URL:
        return {"chain":"Sui","total24h":27216147,"total7d":165543653}
    raise AssertionError("unexpected URL")


class NetworkDefiTests(unittest.TestCase):
    def rows(self):
        return [{"token":"BTC"},{"token":"SUI"},{"token":"SOL"},
                {"token":"NEAR"}], [{"token":"SUI","coppia_analisi":"SUI/EUR"}]

    def test_public_collection_and_full_roster_to_read_with_limits(self):
        positions,candidates=self.rows()
        calls=[]
        def get(url,payload=None):
            calls.append((url,payload is not None))
            return fake_fetch(url,payload)
        raw=evidence.collect(T,positions,candidates,fetch=get)
        self.assertEqual(len(calls),4)
        self.assertEqual(raw["fonti"]["sui"]["stato"],"OSSERVATO")
        self.assertEqual(raw["fonti"]["chain_tvl"]["stato"],"OSSERVATO")
        self.assertNotIn("quantita",json.dumps(raw).lower())
        self.assertNotIn("credential",json.dumps(raw).lower())
        read=evidence.at_read(raw,positions,candidates,T)
        self.assertEqual(len(read["posizioni"]),4)
        self.assertEqual(len(read["candidati"]),1)
        self.assertEqual([x["token"] for x in read["posizioni"]],
                         ["BTC","SUI","SOL","NEAR"])
        sui=read["posizioni"][1]
        self.assertEqual(sui["onchain"]["valori"]["checkpoint"],343931063)
        self.assertEqual(sui["defi"]["valori"]["tvl_chain_usd"],"411351240.64")
        self.assertIsNone(sui["defi"]["timestamp_upstream_utc"])
        self.assertEqual(sui["defi"]["volume_dex24h_su_tvl_chain_pct"],"6.616")
        self.assertIn("controipotesi",sui["onchain"])
        self.assertIn("condizione_riesame",sui["defi"])
        self.assertEqual(read["posizioni"][2]["onchain"]["valori"]
                         ["circolante_sol"],"500000000")
        self.assertEqual(read["posizioni"][0]["onchain"]["stato"],"NON_COPERTO")
        self.assertEqual(read["candidati"][0]["onchain"]["valori"]
                         ["checkpoint"],343931063)
        self.assertEqual(evidence.at_read(read,positions,candidates,T)
                         ["posizioni"][1]["onchain"]["valori"]["checkpoint"],343931063)

    def test_missing_upstream_is_missing_not_a_zero_or_wallet_claim(self):
        positions,candidates=self.rows()
        def down(url,payload=None):
            if url in (evidence.SUI_URL,evidence.CHAIN_URL):
                raise OSError("offline")
            return fake_fetch(url,payload)
        raw=evidence.collect(T,positions,candidates,fetch=down)
        got=evidence.at_read(raw,positions,candidates,T)
        self.assertEqual(got["posizioni"][1]["onchain"]["stato"],"NON_DISPONIBILE")
        self.assertIsNone(got["posizioni"][1]["onchain"]["valori"])
        self.assertIsNone(got["posizioni"][1]["defi"]["valori"])
        self.assertEqual(len(got["posizioni"]),4)
        legacy=evidence.at_read(None,positions,candidates,T)
        self.assertEqual(len(legacy["posizioni"]),4)
        self.assertEqual(evidence.at_read(legacy,positions,candidates,T)["stato"],
                         "NON_ACQUISITO")

    def test_stale_wrong_chain_time_and_numeric_forgery_fail_closed(self):
        positions,candidates=self.rows()
        raw=evidence.collect(T,positions,candidates,fetch=fake_fetch)
        late=evidence.at_read(raw,positions,candidates,T+dt.timedelta(minutes=40))
        self.assertEqual(late["posizioni"][1]["onchain"]["stato"],"SCADUTO")
        self.assertIsNone(late["posizioni"][1]["onchain"]["valori"])
        self.assertIsNone(late["posizioni"][1]["defi"]["valori"])
        self.assertIsNone(late["posizioni"][2]["defi"]["valori"])
        for case in ("url","negative","future","roster","trust"):
            mutated=copy.deepcopy(raw)
            if case=="url": mutated["fonti"]["sui"]["fonte"]="https://evil.example/graphql"
            if case=="negative": mutated["fonti"]["chain_tvl"]["valori"]["Sui"]="-1"
            if case=="future": mutated["fonti"]["sui"]["osservato_utc"]=(T+dt.timedelta(days=1)).isoformat()
            if case=="roster": mutated["roster_posizioni"][1]["token"]="BTC"
            if case=="trust": mutated["limite_provenienza"]="UPSTREAM_AUTENTICATO"
            with self.subTest(case=case),self.assertRaises(ValueError):
                evidence.at_read(mutated,positions,candidates,T)
        self.assertEqual(evidence.at_read(raw,positions,candidates,T)
                         ["posizioni"][1]["onchain"]["limite"],
                         "Osservazione della rete; nessun address label, wallet o vendita attribuiti.")

    def test_actual_dossier_collect_persists_public_producer_without_wallet_data(self):
        """Exercise dossier_trade.collect, not just a manually injected packet."""
        import dossier_trade as producer
        import patrimonio_4tf
        wallet={"posizioni":[{"token":"SUI","quantita":"5"},
                              {"token":"SOL","quantita":"7"}],
                "credenziali":"PRIVATE_MUST_NOT_LEAK"}
        source={"rilevazione_utc":ISO,"schede_v02":[],"markets":{},
                "feed":[],"orari_fonti":{"composizione_kdd_utc":ISO}}
        four={"posizioni":[{"token":"SUI"},{"token":"SOL"}]}
        quality={"stato_saldo":{"portafoglio_aggiornato_da_api_private":False},
                 "saldo_recente_verificato":False,"portafoglio_noto":True,
                 "fotografia_portafoglio_sha256":"a"*64,
                 "portafoglio_letto_utc":ISO}
        economics={"schema":"fixture","posizioni":[{"token":"SUI"},{"token":"SOL"}],
                   "candidati":[]}
        saved={}
        original=evidence.collect
        def from_public(t,holdings,candidates):
            return original(t,holdings,candidates,fetch=fake_fetch)
        with mock.patch.object(producer.desk,"NOW",return_value=T), \
             mock.patch.object(producer.desk,"load",
                 side_effect=lambda name,default=None: wallet if name=="portafoglio.json" else {}), \
             mock.patch.object(producer.desk,"save",
                 side_effect=lambda name,value: saved.__setitem__(name,value)), \
             mock.patch.object(producer.desk,"qualita_portafoglio",return_value=quality), \
             mock.patch.object(producer,"recupera_4h",return_value={}), \
             mock.patch.object(producer,"global_context",return_value={"errore":"offline"}), \
             mock.patch.object(producer,"derivatives_context",
                               return_value={"strumento":"PF_XBTUSD"}), \
             mock.patch.object(patrimonio_4tf,"collect",return_value=four), \
             mock.patch.object(producer,"finanziamento_150_book",return_value={}), \
             mock.patch.object(producer,"economic_evidence",return_value=economics), \
             mock.patch.object(evidence,"collect",side_effect=from_public) as called, \
             mock.patch.object(producer.time,"sleep"):
            dossier=producer.collect(source=source,asset_pairs={})
        called.assert_called_once()
        self.assertEqual([x["token"] for x in dossier["evidenze_rete_defi"]
                          ["roster_posizioni"]],["SUI","SOL"])
        self.assertEqual(dossier["evidenze_rete_defi"]["fonti"]["sui"]["stato"],
                         "OSSERVATO")
        self.assertIn("dossier_multifonte.json",saved)
        self.assertNotIn("PRIVATE_MUST_NOT_LEAK",
                         json.dumps(saved["dossier_multifonte.json"]))

    def test_packet_and_bridge_recheck_public_evidence_without_writes(self):
        from scripts import kdd_wallet_packet_g0 as packet
        from scripts import kdd_bridge_g2 as bridge
        from scripts import test_kdd_wallet_packet_g0 as packet_fixture
        # Existing packet fixtures use top-level import root in Android:
        # pass a genuine self-contained source and the existing wallet fixture.
        with mock.patch.dict("sys.modules",{"kdd_wallet_packet_g0":packet}):
            import importlib
            test_source=importlib.import_module("scripts.test_kdd_wallet_packet_g0")
        fixture=test_source.WalletPacketG0Tests(
            "test_asset_weights_never_rebrand_partial_total_as_entire_wallet")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        # Make the first two owned positions SUI/SOL with synthetic coherent prices.
        fixture.portfolio["posizioni"][0]["token"]="SUI"
        fixture.portfolio["posizioni"][1]["token"]="SOL"
        fixture.snapshot["markets"]={
            "SUI":{"token":"SUI","pair":"SUI/EUR","pair_key":"SUIEUR","prezzo_eur":1},
            "SOL":{"token":"SOL","pair":"SOL/EUR","pair_key":"SOLEUR","prezzo_eur":2000}}
        fixture.report["posizioni"][0]["token"]="SUI"
        fixture.report["posizioni"][1]["token"]="SOL"
        fixture.snapshot["schede_v02"]=[{"token":"SUI","coppia_analisi":"SUI/EUR",
                                        "esito":"RIESAME","categoria":"confronto"}]
        fixture.dossier["candidati"]=[]
        rows=[{"token":"SUI"},{"token":"SOL"},{"token":"SXT"}]
        shortlist=[{"token":"SUI","coppia_analisi":"SUI/EUR"}]
        # Use a coherent synthetic observation time for all four source files.
        moment=T
        iso=moment.isoformat()
        fixture.portfolio["data_ora_saldo_privato_utc"]=iso
        fixture.portfolio["fonte_quantita"]="Kraken BalanceEx API privata SOLA LETTURA, "+iso
        fixture.snapshot["rilevazione_utc"]=iso
        fixture.report["rilevazione_utc"]=iso
        fixture.dossier["kraken_istantanea_utc"]=iso
        fixture.dossier["evidenze_rete_defi"]=evidence.collect(
            moment,rows,shortlist,fetch=fake_fetch)
        fixture.dump()
        p=packet.build(fixture.root,now=moment)
        self.assertEqual(len(p["patrimonio"]["posizioni"]),3)
        network=p["evidenze_multifonte"]["rete_defi"]
        self.assertEqual(len(network["posizioni"]),3)
        self.assertEqual(len(network["candidati"]),1)
        bundle={"schema":bridge.SCHEMA_BUNDLE,"packet":p,
                "packet_sha256":bridge.digest(p),"preparato_utc":iso}
        reading=bridge.read_context(json.loads(json.dumps(bundle)),now=moment)
        self.assertEqual(reading["rete_defi_alla_lettura"]["posizioni"][0]
                         ["onchain"]["stato"],"OSSERVATO_CON_LIMITI")
        late=bridge.read_context(bundle,now=moment+dt.timedelta(minutes=40))
        self.assertIsNone(late["rete_defi_alla_lettura"]["posizioni"][0]
                          ["defi"]["valori"])
        poison=copy.deepcopy(bundle)
        poison["packet"]["evidenze_multifonte"]["rete_defi"]["sorgente"]["fonti"]["chain_tvl"]["fonte"]="https://malicious.example/"
        poison["packet_sha256"]=bridge.digest(poison["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(poison,now=moment)



class IdentityBoundNetworkTests(unittest.TestCase):
    """All RPC payloads here are synthetic; no private balance or paid API."""

    def ident(self,token):
        import kdd_economics as econ
        entry=econ._CURATED[token]
        return {"stato":"IDENTITA_VERIFICATA_DA_CATALOGO",
                "token":token,"token_progetto":token,
                "metodo":"REGISTRO_CURATO","coingecko_id":entry["id"],
                "progetto":entry["name"],"coppia":token+"/EUR",
                "pair_key":token+"EUR","asset_base_kraken":token}

    def row(self,token):
        return {"token":token,"identita":self.ident(token)}

    def public(self,url,payload=None):
        t=int(T.timestamp())
        if url=="https://blockstream.info/api/blocks":
            return [{"id":"a"*64,"height":930120,"tx_count":1923,
                     "timestamp":t-80}]
        if url=="https://ethereum-rpc.publicnode.com":
            method=payload["method"]
            if method=="eth_chainId":
                return {"jsonrpc":"2.0","id":1,"result":"0x1"}
            self.assertEqual(method,"eth_getBlockByNumber")
            self.assertEqual(payload["params"],["finalized",False])
            return {"jsonrpc":"2.0","id":1,"result":{
                "number":"0x1a9c00","timestamp":hex(t-90),
                "hash":"0x"+"b"*64,"transactions":["0x01","0x02"]}}
        if url=="https://bsc-dataseed.bnbchain.org":
            if payload["method"]=="eth_chainId":
                return {"jsonrpc":"2.0","id":1,"result":"0x38"}
            self.assertEqual(payload["params"],["latest",False])
            return {"jsonrpc":"2.0","id":1,"result":{
                "number":"0x991a0","timestamp":hex(t-5),
                "hash":"0x"+"c"*64,"transactions":["0x01"]}}
        if url=="https://rpc.mainnet.near.org":
            self.assertEqual(payload["method"],"block")
            return {"jsonrpc":"2.0","id":1,"result":{
                "header":{"height":143002003,"timestamp":str((t-4)*10**9),
                          "hash":"5"*44}}}
        if url=="https://xrplcluster.com/":
            self.assertEqual(payload["method"],"ledger")
            return {"jsonrpc":"2.0","id":1,"result":{
                "status":"success","ledger_hash":"d"*64,"ledger_index":99012514,
                "validated":True,"ledger":{"close_time_iso":(T-dt.timedelta(seconds=5)).isoformat(),
                                           "total_coins":"99900000000000000"}}}
        if url==evidence.SOL_URL:
            self.assertEqual(payload["id"],1)
            if payload["method"]=="getTokenSupply":
                self.assertEqual(payload["params"][0],
                                 "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN")
                return {"jsonrpc":"2.0","id":1,"result":{
                    "context":{"slot":30000000},
                    "value":{"amount":"6861485685760334","decimals":6}}}
            self.assertEqual(payload["method"],"getAccountInfo")
            return {"jsonrpc":"2.0","id":1,"result":{
                "context":{"slot":30000001},
                "value":{"owner":evidence.TOKEN_PROGRAM,
                         "data":{"parsed":{"type":"mint","info":{"decimals":6}}}}}}
        raise AssertionError("unexpected source "+url)

    def test_native_contract_multichain_and_new_candidate_to_gpt_consumer(self):
        owned=[self.row(t) for t in ("BTC","ETH","BNB","NEAR","XRP","JUP","RENDER","FET")]
        candidates=[dict(self.row("JUP"),coppia_analisi="JUP/EUR"),
                    {"token":"ZEC","coppia_analisi":"ZEC/EUR"}]
        calls=[]
        def get(url,payload=None):
            calls.append(url)
            return self.public(url,payload)
        collected=evidence.collect(T,owned,candidates,fetch=get)
        self.assertEqual(len(calls),9)
        self.assertEqual(set(collected["fonti_rete"]),set(evidence.NETWORK_ADAPTERS))
        self.assertEqual(collected["fonti_rete"]["bitcoin"]["stato"],"OSSERVATO")
        self.assertEqual(collected["fonti_rete"]["near"]["stato"],"OSSERVATO")
        mint="JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
        self.assertEqual(collected["fonti_contratti"][mint]["stato"],"OSSERVATO")
        minimal=[{"token":x["token"]} for x in owned]
        minimal_c=[{"token":x["token"],"coppia_analisi":x["coppia_analisi"]}
                   for x in candidates]
        econ={"posizioni":owned,"candidati":candidates}
        context=evidence.at_read(collected,minimal,minimal_c,T,economia=econ)
        self.assertEqual([x["token"] for x in context["posizioni"]],
                         ["BTC","ETH","BNB","NEAR","XRP","JUP","RENDER","FET"])
        for i,network in enumerate(("bitcoin","ethereum","bsc","near","xrpl")):
            row=context["posizioni"][i]["onchain"]
            self.assertEqual(row["stato"],"OSSERVATO_CON_LIMITI")
            self.assertEqual(row["tipologia"],"ASSET_NATIVO")
            self.assertEqual(row["rete"],network)
            self.assertIsNotNone(row["valori"]["altezza"])
            self.assertIsNotNone(row["osservato_utc"])
            self.assertIn("controipotesi",row)
        self.assertEqual(context["posizioni"][5]["onchain"]["tipologia"],
                         "TOKEN_CON_MINT")
        self.assertEqual(context["posizioni"][5]["onchain"]["valori"]["supply_token"],
                         "6861485685.760334")
        self.assertEqual(context["posizioni"][6]["onchain"]["stato"],
                         "MULTICHAIN_DA_RISOLVERE")
        self.assertEqual(context["posizioni"][7]["onchain"]["stato"],
                         "MULTICHAIN_DA_RISOLVERE")
        self.assertEqual(context["candidati"][1]["onchain"]["stato"],
                         "NON_COPERTO")
        self.assertEqual(context["candidati"][0]["onchain"]["contratto"],mint)
        again=evidence.at_read(context,minimal,minimal_c,T,economia=econ)
        self.assertEqual(again["posizioni"][0]["onchain"]["valori"]["altezza"],930120)
        expired=evidence.at_read(collected,minimal,minimal_c,
                                   T+dt.timedelta(minutes=45),economia=econ)
        self.assertEqual(expired["posizioni"][0]["onchain"]["stato"],"SCADUTO")
        self.assertIsNone(expired["posizioni"][0]["onchain"]["valori"])
        self.assertIsNone(expired["posizioni"][5]["onchain"]["valori"])

    def test_ticker_collision_and_forged_mint_are_not_attested(self):
        actual=self.row("JUP")
        bad=copy.deepcopy(actual)
        bad["identita"]["coingecko_id"]="wrong-jupiter"
        raw=evidence.collect(T,[bad],[],fetch=self.public)
        self.assertEqual(raw["roster_posizioni"][0]["binding"]["stato"],
                         "NON_VERIFICATO")
        self.assertEqual(raw["fonti_contratti"],{})
        valid=evidence.collect(T,[actual],[],fetch=self.public)
        forged=copy.deepcopy(valid)
        forged["roster_posizioni"][0]["binding"]["contratto"]="fake-mint"
        with self.assertRaises(ValueError):
            evidence.at_read(forged,[{"token":"JUP"}],[],T,
                             economia={"posizioni":[actual],"candidati":[]})
        injected=copy.deepcopy(valid)
        injected["fonti_contratti"]["FAKE_MINT"]=injected["fonti_contratti"][
            "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"]
        with self.assertRaises(ValueError):
            evidence.at_read(injected,[{"token":"JUP"}],[],T,
                             economia={"posizioni":[actual],"candidati":[]})

    def test_source_unavailable_and_chainid_mismatch_fail_with_rows_preserved(self):
        items=[self.row("ETH"),self.row("BTC"),self.row("JUP")]
        def unavailable(url,payload=None):
            if url=="https://ethereum-rpc.publicnode.com":
                return {"jsonrpc":"2.0","id":1,"result":"0x38"}
            if url=="https://blockstream.info/api/blocks":
                raise OSError("offline")
            return self.public(url,payload)
        raw=evidence.collect(T,items,[],fetch=unavailable)
        read=evidence.at_read(raw,[{"token":x["token"]} for x in items],[],T,
                              economia={"posizioni":items,"candidati":[]})
        self.assertEqual(len(read["posizioni"]),3)
        self.assertEqual(read["posizioni"][0]["onchain"]["stato"],"NON_DISPONIBILE")
        self.assertEqual(read["posizioni"][1]["onchain"]["stato"],"NON_DISPONIBILE")
        self.assertIsNone(read["posizioni"][1]["onchain"]["valori"])
        self.assertEqual(read["posizioni"][2]["onchain"]["stato"],"OSSERVATO_CON_LIMITI")

    def test_new_asset_entry_exit_and_return_never_carries_old_chain_evidence(self):
        stages=[[self.row("BTC")],[self.row("BTC"),
                 {"token":"ZEC"}],[self.row("BTC"),self.row("JUP")]]
        for i,holdings in enumerate(stages):
            with self.subTest(stage=i):
                source=evidence.collect(T,holdings,[],fetch=self.public)
                rows=[{"token":x["token"]} for x in holdings]
                read=evidence.at_read(source,rows,[],T,
                                      economia={"posizioni":holdings,"candidati":[]})
                self.assertEqual(len(read["posizioni"]),len(holdings))
                if i==1:
                    self.assertEqual(read["posizioni"][1]["onchain"]["stato"],
                                     "NON_COPERTO")
                if i==2:
                    self.assertEqual(read["posizioni"][1]["onchain"]["tipologia"],
                                     "TOKEN_CON_MINT")
        with self.assertRaises(ValueError):
            evidence.at_read(source,[{"token":"BTC"},{"token":"ZEC"}],[],T,
                             economia={"posizioni":stages[1],"candidati":[]})

if __name__=="__main__":
    unittest.main()
