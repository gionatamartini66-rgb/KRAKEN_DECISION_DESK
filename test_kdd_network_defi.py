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

    def proven(self, token, pair=None):
        import kdd_economics as econ
        key=econ.canonical_token(token)
        obj=econ._CURATED[key]
        return {"token":token,"identita":{
            "token":token,"stato":"IDENTITA_VERIFICATA_DA_CATALOGO",
            "metodo":"REGISTRO_CURATO","coingecko_id":obj["id"],
            "token_progetto":key,"coppia":pair or token+"/EUR"}}

    def many_network_fetch(self, url, payload=None):
        if url==evidence.NETWORK_ENDPOINTS["bitcoin"]:
            return [{"id":"00"*32,"height":900001,"timestamp":int(T.timestamp())-120,
                     "tx_count":3702}]
        if url in (evidence.NETWORK_ENDPOINTS["ethereum"],
                   evidence.NETWORK_ENDPOINTS["bsc"]):
            method=payload["method"]
            chain="0x1" if url==evidence.NETWORK_ENDPOINTS["ethereum"] else "0x38"
            if method=="eth_chainId":
                return {"jsonrpc":"2.0","id":1,"result":chain}
            if method=="eth_getBlockByNumber":
                return {"jsonrpc":"2.0","id":2,"result":{
                    "number":"0x100","hash":"0x"+"ab"*32,
                    "timestamp":hex(int(T.timestamp())-4),
                    "gasLimit":"0x1c9c380"}}
            raise AssertionError("unexpected EVM method")
        if url==evidence.NETWORK_ENDPOINTS["near"]:
            return {"jsonrpc":"2.0","id":1,"result":{"header":{
                "height":145000000,"timestamp_nanosec":str((int(T.timestamp())-3)*10**9),
                "hash":"7Ct7Zjn5AFk2vP9sHSQyR8kA9prE1cYkQvF6S14pT1R"}}}
        if url==evidence.NETWORK_ENDPOINTS["xrpl"]:
            return {"result":{"validated":True,"ledger":{
                "ledger_index":101001001,"ledger_hash":"cd"*32,
                "close_time":int(T.timestamp())-946684800-4}}}
        if url==evidence.NETWORK_ENDPOINTS["cardano"]:
            return [{"block_no":12344566,"abs_slot":166789112,"epoch_no":620,
                     "hash":"ef"*32,"block_time":int(T.timestamp())-3}]
        if url==evidence.SOL_URL and payload and payload.get("method")=="getTokenSupply":
            self.assertEqual(payload["params"][0],
                "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN")
            return {"jsonrpc":"2.0","id":1,"result":{
                "context":{"slot":451230000},
                "value":{"amount":"10000000000000000","decimals":6}}}
        return fake_fetch(url,payload)

    def test_curated_natives_evm_blockchains_and_spl_mint_are_source_bound(self):
        owned=[self.proven(x) for x in
               ("BTC","ETH","BNB","NEAR","XRP","ADA","SUI","SOL","JUP")]
        candidates=[self.proven("JUP","JUP/USD")]
        raw=evidence.collect(T,owned,candidates,fetch=self.many_network_fetch)
        self.assertEqual(set(raw["fonti_reti"]),{
            "bitcoin","ethereum","bsc","near","xrpl","cardano","jup_spl"})
        self.assertTrue(all(row["stato"]=="OSSERVATO" for row in raw["fonti_reti"].values()))
        read=evidence.at_read(raw,owned,candidates,T,
                             economia={"posizioni":owned,"candidati":candidates})
        self.assertEqual(len(read["posizioni"]),9)
        self.assertEqual(len(read["candidati"]),1)
        by_token={x["token"]:x for x in read["posizioni"]}
        self.assertEqual(by_token["BTC"]["osservazione_rete"]["valori"]["altezza"],900001)
        self.assertEqual(by_token["ETH"]["osservazione_rete"]["valori"]["chain_id"],1)
        self.assertEqual(by_token["BNB"]["osservazione_rete"]["valori"]["chain_id"],56)
        self.assertEqual(by_token["ADA"]["osservazione_rete"]["valori"]["epoca"],620)
        self.assertEqual(by_token["XRP"]["osservazione_rete"]["valori"]["ledger_index"],101001001)
        self.assertEqual(by_token["NEAR"]["osservazione_rete"]["valori"]["altezza"],145000000)
        self.assertEqual(by_token["JUP"]["identita_rete"]["tipo"],"TOKEN_CONTRATTO")
        self.assertEqual(by_token["JUP"]["osservazione_rete"]["valori"]["supply_token"],
                         "10000000000")
        self.assertEqual(read["candidati"][0]["osservazione_rete"]["valori"]
                         ["mint"],"JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN")
        self.assertEqual(by_token["SUI"]["osservazione_rete"]["stato"],
                         "OSSERVATO_CON_LIMITI")
        self.assertEqual(by_token["SOL"]["osservazione_rete"]["stato"],
                         "OSSERVATO_CON_LIMITI")
        self.assertIn("P08/P09",by_token["JUP"]["osservazione_rete"]["limite"])
        later=evidence.at_read(raw,owned,candidates,T+dt.timedelta(minutes=40),
                               economia={"posizioni":owned,"candidati":candidates})
        self.assertIsNone(later["posizioni"][1]["osservazione_rete"]["valori"])
        self.assertEqual(later["posizioni"][1]["osservazione_rete"]["stato"],"SCADUTO")

    def test_multichain_ambiguous_contract_and_reentry_never_infer_by_ticker(self):
        original=[self.proven("SUI"),self.proven("JUP")]
        unknown={"token":"ZEC","identita":{"token":"ZEC",
            "stato":"IDENTITA_VERIFICATA_DA_CATALOGO",
            "metodo":"KRAKEN_COINGECKO_MARKET","coingecko_id":"zcash",
            "token_progetto":"ZEC","coppia":"ZEC/EUR"}}
        risky=[self.proven("FET"),self.proven("RENDER"),self.proven("PEPE")]
        initial=evidence.collect(T,original+risky+[unknown],[],
                                 fetch=self.many_network_fetch)
        got=evidence.at_read(initial,original+risky+[unknown],[],T,
                             economia={"posizioni":original+risky+[unknown],"candidati":[]})
        self.assertEqual([x["token"] for x in got["posizioni"]],
                         ["SUI","JUP","FET","RENDER","PEPE","ZEC"])
        self.assertEqual(got["posizioni"][2]["identita_rete"]["stato"],
                         "MULTICHAIN_NON_DISAMBIGUATO")
        self.assertEqual(got["posizioni"][3]["identita_rete"]["stato"],
                         "MULTICHAIN_NON_DISAMBIGUATO")
        self.assertEqual(got["posizioni"][4]["identita_rete"]["stato"],
                         "TOKEN_CONTRATTO_NON_ATTESTATO")
        self.assertEqual(got["posizioni"][5]["osservazione_rete"]["stato"],
                         "NON_ATTRIBUIBILE")
        self.assertEqual(set(initial["fonti_reti"]),{"jup_spl"})
        # Wallet rotation: exiting JUP removes its contract read; coming back
        # restores the same curated mint only after project identity proof.
        second=evidence.collect(T,[unknown,self.proven("SUI")],[],
                                fetch=self.many_network_fetch)
        self.assertEqual(second["fonti_reti"],{})
        returned=evidence.collect(T,[self.proven("JUP"),unknown],[],
                                  fetch=self.many_network_fetch)
        self.assertEqual(set(returned["fonti_reti"]),{"jup_spl"})
        forged=self.proven("JUP")
        forged["identita"]["coingecko_id"]="wrong-project"
        blocked=evidence.collect(T,[forged],[],fetch=self.many_network_fetch)
        self.assertEqual(blocked["fonti_reti"],{})

    def test_network_absence_wrong_chain_tampered_proof_and_freshness(self):
        owned=[self.proven("BNB"),self.proven("JUP")]
        def unavailable(url,payload=None):
            if url==evidence.NETWORK_ENDPOINTS["bsc"]:
                raise OSError("public RPC offline")
            return self.many_network_fetch(url,payload)
        raw=evidence.collect(T,owned,[],fetch=unavailable)
        read=evidence.at_read(raw,owned,[],T,economia={"posizioni":owned,"candidati":[]})
        self.assertEqual(read["posizioni"][0]["osservazione_rete"]["stato"],
                         "NON_DISPONIBILE")
        self.assertIsNone(read["posizioni"][0]["osservazione_rete"]["valori"])
        def wrong_chain(url,payload=None):
            if url==evidence.NETWORK_ENDPOINTS["bsc"] and payload["method"]=="eth_chainId":
                return {"jsonrpc":"2.0","id":1,"result":"0x1"}
            return self.many_network_fetch(url,payload)
        wrong=evidence.collect(T,owned,[],fetch=wrong_chain)
        self.assertEqual(wrong["fonti_reti"]["bsc"]["stato"],"NON_DISPONIBILE")
        altered=copy.deepcopy(raw)
        altered["associazioni"]["posizioni"][1]["contratto"]="fake_contract"
        with self.assertRaises(ValueError):
            evidence.at_read(altered,owned,[],T,
                             economia={"posizioni":owned,"candidati":[]})
        minted=copy.deepcopy(raw)
        minted["fonti_reti"]["jup_spl"]["valori"]["mint"]="AnotherMint"
        with self.assertRaises(ValueError):
            evidence.at_read(minted,owned,[],T,
                             economia={"posizioni":owned,"candidati":[]})
        with self.assertRaises(ValueError):
            evidence.at_read(raw,owned,[],T,economia=None)

    def test_bound_jup_and_eth_through_actual_dossier_packet_and_gpt_bridge(self):
        import kdd_economics as econ
        import dossier_trade as producer
        import patrimonio_4tf
        from scripts import kdd_wallet_packet_g0 as packet
        from scripts import kdd_bridge_g2 as bridge
        from scripts import test_kdd_wallet_packet_g0 as fixture_module
        fx=fixture_module.WalletPacketG0Tests(
            "test_asset_weights_never_rebrand_partial_total_as_entire_wallet")
        fx.setUp()
        self.addCleanup(fx.doCleanups)
        fx.portfolio["posizioni"][0]["token"]="JUP"
        fx.portfolio["posizioni"][1]["token"]="ETH"
        fx.report["posizioni"][0]["token"]="JUP"
        fx.report["posizioni"][1]["token"]="ETH"
        fx.snapshot["markets"]={
            "JUP":{"token":"JUP","pair":"JUP/EUR","pair_key":"JUPEUR","prezzo_eur":1.0},
            "ETH":{"token":"ETH","pair":"ETH/EUR","pair_key":"ETHEUR","prezzo_eur":2000.0}}
        fx.snapshot["schede_v02"]=[]
        fx.portfolio["data_ora_saldo_privato_utc"]=ISO
        fx.portfolio["fonte_quantita"]="Kraken BalanceEx API privata SOLA LETTURA, "+ISO
        fx.snapshot["rilevazione_utc"]=ISO
        fx.report["rilevazione_utc"]=ISO
        fx.dossier["kraken_istantanea_utc"]=ISO
        selected=[]
        for i,token in enumerate(("JUP","ETH","SXT")):
            if token=="SXT":
                ident={"stato":"NON_VERIFICATO","token":"SXT","coppia":None}
            else:
                ident=econ.identify(token,token+"/EUR",token+"EUR",
                    catalog={token+"EUR":{"pair_key":token+"EUR",
                         "pair":token+"/EUR","base":token,"quote":"EUR"}})
            selected.append({"indice":i,"token":token,"identita":ident,
                "fondamentali":econ.fundamentals(ident,None,T,T),
                "evento":econ.release_event(ident,None,T,T)})
        economic={"schema":econ.VERSION,"acquisito_utc":ISO,
                  "posizioni":selected,"candidati":[],
                  "regime":{"stato":"INDETERMINATO","qualita":"INSUFFICIENTE"},
                  "macro":econ.macro([],T)}
        mock_source={"rilevazione_utc":ISO,"schede_v02":[],
                     "markets":fx.snapshot["markets"],
                     "feed":[],"orari_fonti":{"composizione_kdd_utc":ISO}}
        wallet=fx.portfolio
        wallet["credenziali"]="PRIVATE_MUST_NOT_LEAK"
        quality={"stato_saldo":{"portafoglio_aggiornato_da_api_private":False},
                 "saldo_recente_verificato":False,"portafoglio_noto":True,
                 "fotografia_portafoglio_sha256":"a"*64,
                 "portafoglio_letto_utc":ISO}
        four={"posizioni":[{"token":"JUP"},{"token":"ETH"},{"token":"SXT"}]}
        saved={}
        current_collect=evidence.collect
        def public_only(now,positions,candidates):
            return current_collect(now,positions,candidates,fetch=self.many_network_fetch)
        with mock.patch.object(producer.desk,"NOW",return_value=T), \
             mock.patch.object(producer.desk,"load",
                 side_effect=lambda name,default=None: wallet if name=="portafoglio.json" else {}), \
             mock.patch.object(producer.desk,"save",
                 side_effect=lambda name,obj: saved.__setitem__(name,obj)), \
             mock.patch.object(producer.desk,"qualita_portafoglio",return_value=quality), \
             mock.patch.object(producer,"recupera_4h",return_value={}), \
             mock.patch.object(producer,"global_context",return_value={"errore":"offline"}), \
             mock.patch.object(producer,"derivatives_context",return_value={"strumento":"PF_XBTUSD"}), \
             mock.patch.object(patrimonio_4tf,"collect",return_value=four), \
             mock.patch.object(producer,"finanziamento_150_book",return_value={}), \
             mock.patch.object(producer,"economic_evidence",return_value=economic), \
             mock.patch.object(evidence,"collect",side_effect=public_only):
            dossier=producer.collect(source=mock_source,asset_pairs={})
        self.assertIn("dossier_multifonte.json",saved)
        self.assertEqual(set(dossier["evidenze_rete_defi"]["fonti_reti"]),
                         {"ethereum","jup_spl"})
        self.assertNotIn("PRIVATE_MUST_NOT_LEAK",json.dumps(dossier))
        fx.dossier.update({
            "evidenze_economiche":dossier["evidenze_economiche"],
            "evidenze_rete_defi":dossier["evidenze_rete_defi"]})
        fx.dump()
        pkt=packet.build(fx.root,now=T)
        self.assertEqual(len(pkt["patrimonio"]["posizioni"]),3)
        self.assertEqual(pkt["evidenze_multifonte"]["rete_defi"]["posizioni"][0]
                         ["identita_rete"]["tipo"],"TOKEN_CONTRATTO")
        bundle={"schema":bridge.SCHEMA_BUNDLE,"packet":pkt,
                "packet_sha256":bridge.digest(pkt),"preparato_utc":ISO}
        reading=bridge.read_context(json.loads(json.dumps(bundle)),now=T)
        rows=reading["rete_defi_alla_lettura"]["posizioni"]
        self.assertEqual([x["token"] for x in rows],["JUP","ETH","SXT"])
        self.assertEqual(rows[0]["osservazione_rete"]["valori"]["supply_token"],
                         "10000000000")
        self.assertEqual(rows[1]["osservazione_rete"]["valori"]["chain_id"],1)
        self.assertEqual(rows[2]["osservazione_rete"]["stato"],"NON_ATTRIBUIBILE")
        tampered=copy.deepcopy(bundle)
        tampered["packet"]["evidenze_multifonte"]["rete_defi"]["sorgente"][
            "associazioni"]["posizioni"][0]["contratto"]="WrongMint"
        tampered["packet_sha256"]=bridge.digest(tampered["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(tampered,now=T)

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


if __name__=="__main__":
    unittest.main()
