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
        import kdd_economics as econ
        def catalog_identity(token):
            return econ.identify(token, token + "/EUR", token + "EUR",
                                 catalog={token+"EUR": {
                                     "pair": token+"/EUR", "pair_key": token+"EUR",
                                     "base": token, "quote": "EUR"}})
        economics={"schema":"fixture","posizioni":[
                      {"indice":i,"token":token,"identita":catalog_identity(token)}
                      for i,token in enumerate(("SUI","SOL"))],"candidati":[]}
        saved={}
        original=evidence.collect
        def from_public(t,holdings,candidates,**kwargs):
            return original(t,holdings,candidates,fetch=fake_fetch,**kwargs)
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
        self.assertEqual(dossier["evidenze_rete_defi"]["asset_reti"]["posizioni"][0]["tipo"],
                         "NATIVO")
        self.assertEqual(dossier["evidenze_rete_defi"]["asset_reti"]["posizioni"][1]["tipo"],
                         "NATIVO")
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
        fixture.snapshot["schede_v02"]=[
            {"token":"SUI","coppia_analisi":"SUI/EUR","esito":"RIESAME","categoria":"confronto"},
            {"token":"PEPE","coppia_analisi":"PEPE/EUR","esito":"RIESAME","categoria":"confronto"}]
        fixture.dossier["candidati"]=[]
        rows=[{"token":"SUI"},{"token":"SOL"},{"token":"SXT"}]
        shortlist=[{"token":"SUI","coppia_analisi":"SUI/EUR"},
                   {"token":"PEPE","coppia_analisi":"PEPE/EUR"}]
        # Use a coherent synthetic observation time for all four source files.
        moment=T
        iso=moment.isoformat()
        fixture.portfolio["data_ora_saldo_privato_utc"]=iso
        fixture.portfolio["fonte_quantita"]="Kraken BalanceEx API privata SOLA LETTURA, "+iso
        fixture.snapshot["rilevazione_utc"]=iso
        fixture.report["rilevazione_utc"]=iso
        fixture.dossier["kraken_istantanea_utc"]=iso
        import kdd_economics as econ
        def identity(token):
            if token == "SXT":
                return {"token": token, "stato": "NON_VERIFICATO"}
            return econ.identify(token, token+"/EUR", token+"EUR",
                                 catalog={token+"EUR":{
                                     "pair":token+"/EUR","pair_key":token+"EUR",
                                     "base":token,"quote":"EUR"}})
        def econ_row(token, idx, *, candidate=False):
            ident = identity(token)
            record = {"indice":idx, "token":token, "identita":ident,
                      "fondamentali":econ.fundamentals(ident,None,moment,moment),
                      "evento":econ.release_event(ident,None,moment,moment)}
            if candidate:
                record["coppia_analisi"] = token+"/EUR"
            return record
        economics = {"schema":econ.VERSION,"acquisito_utc":iso,
                     "posizioni":[econ_row(token,i) for i,token in enumerate(("SUI","SOL","SXT"))],
                     "candidati":[econ_row("SUI",0,candidate=True),
                                  econ_row("PEPE",1,candidate=True)],
                     "regime":{"stato":"INDETERMINATO","qualita":"PARZIALE"},
                     "fonti_economiche":econ.sources_matrix(),
                     "macro":econ.macro([],moment)}
        pepe = economics["candidati"][1]
        pepe["network_metadata"] = evidence.coin_network_metadata(
            pepe["identita"], {"id":"pepe","symbol":"pepe","name":"Pepe",
                               "platforms":{"ethereum":Kdd17AssetIdentityG2Tests.ETH}},moment)
        fixture.dossier["evidenze_economiche"] = economics
        standard_fetch=Kdd17AssetIdentityG2Tests().fetch
        def sample_capital_fetch(url, payload=None):
            # Keep the original Sui/Solana supply source, but also exercise
            # real-shaped capital events through dossier -> packet -> bridge.
            if url==evidence.SUI_URL and payload and "transactions(" in payload.get("query",""):
                return {"data":{"transactions":{"nodes":[{
                    "digest":"A"*40,"effects":{"status":"SUCCESS","timestamp":iso,
                    "checkpoint":{"sequenceNumber":"450"},
                    "balanceChanges":{"nodes":[{
                        "owner":{"address":"0x123"},"amount":"-1000000000",
                        "coinType":{"repr":"0x2::sui::SUI"}}]}}}]}}}
            if url==evidence.SOL_URL and payload and payload.get("method")=="getLargestAccounts":
                return {"id":1,"result":{"context":{"slot":500},
                    "value":[{"address":"B"*32,"lamports":2000000000}]}}
            return standard_fetch(url,payload)
        fixture.dossier["evidenze_rete_defi"]=evidence.collect(
            moment,rows,shortlist,fetch=sample_capital_fetch,
            economics=economics)
        fixture.dump()
        p=packet.build(fixture.root,now=moment)
        self.assertEqual(len(p["patrimonio"]["posizioni"]),3)
        network=p["evidenze_multifonte"]["rete_defi"]
        self.assertEqual(len(network["posizioni"]),3)
        self.assertEqual(len(network["candidati"]),2)
        self.assertEqual(network["asset_reti"]["posizioni"][0]["tipo"],"NATIVO")
        self.assertEqual(network["asset_reti"]["candidati"][1]["tipo"],"TOKEN_CON_CONTRATTO")
        self.assertEqual(network["asset_reti"]["candidati"][1]["osservazioni_contratti"][0]
                         ["osservazione"]["stato"],"OSSERVATO_CON_LIMITI")
        self.assertEqual(network["asset_reti"]["candidati"][1]["ufficialita_contratto"],
                         "NON_ATTESTATA")
        self.assertEqual(network["asset_reti"]["posizioni"][2]["tipo"],"NON_VERIFICATO")
        self.assertIn("flussi_capitale", network["asset_reti"])
        self.assertEqual(len(network["asset_reti"]["flussi_capitale"]["posizioni"]),3)
        self.assertEqual(len(network["asset_reti"]["flussi_capitale"]["candidati"]),2)
        bundle={"schema":bridge.SCHEMA_BUNDLE,"packet":p,
                "packet_sha256":bridge.digest(p),"preparato_utc":iso}
        reading=bridge.read_context(json.loads(json.dumps(bundle)),now=moment)
        self.assertEqual(reading["rete_defi_alla_lettura"]["posizioni"][0]
                         ["onchain"]["stato"],"OSSERVATO_CON_LIMITI")
        self.assertEqual(reading["rete_defi_alla_lettura"]["asset_reti"]["posizioni"][1]
                         ["tipo"],"NATIVO")
        self.assertEqual(reading["rete_defi_alla_lettura"]["asset_reti"]["candidati"][1]
                         ["osservazioni_contratti"][0]["osservazione"]["valori"]
                         ["supply_unita_minima"],"420690000000000000000000000000000000000")
        self.assertEqual(len(reading["rete_defi_alla_lettura"]["asset_reti"]["flussi_capitale"]["posizioni"]),3)
        self.assertEqual(len(reading["rete_defi_alla_lettura"]["asset_reti"]["flussi_capitale"]["candidati"]),2)
        capital=reading["rete_defi_alla_lettura"]["asset_reti"]["flussi_capitale"]
        sui=capital["posizioni"][0]["osservazioni"][0]
        sol=capital["posizioni"][1]["osservazioni"][0]
        self.assertEqual(sui["eventi"][0]["quantita"],"1")
        self.assertEqual(sui["eventi"][0]["tipo"],"VARIAZIONE_NETTA_SALDO_NON_TRASFERIMENTO")
        self.assertEqual(sui["eventi"][0]["stato_alla_lettura"],"CAMPIONE_RECENTE")
        self.assertEqual(sol["detentori"][0]["unita_minima"],"2000000000")
        self.assertEqual(sol["periodo"]["tipo"],"TOP20_ACCOUNT_SOL_FINALIZZATI")
        late=bridge.read_context(bundle,now=moment+dt.timedelta(minutes=40))
        self.assertIsNone(late["rete_defi_alla_lettura"]["posizioni"][0]
                          ["defi"]["valori"])
        poison=copy.deepcopy(bundle)
        poison["packet"]["evidenze_multifonte"]["rete_defi"]["sorgente"]["fonti"]["chain_tvl"]["fonte"]="https://malicious.example/"
        poison["packet_sha256"]=bridge.digest(poison["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(poison,now=moment)


class Kdd17AssetIdentityG2Tests(unittest.TestCase):
    """Independent synthetic counterexamples for project, chain and contract evidence."""
    ETH = "0x" + "1" * 40
    BSC = "0x" + "2" * 40
    MINT = "A" * 32

    @staticmethod
    def ident(token):
        import kdd_economics as econ
        return econ.identify(token, token + "/EUR", token + "EUR",
                             catalog={token + "EUR": {
                                 "pair_key": token + "EUR", "pair": token + "/EUR",
                                 "base": token, "quote": "EUR"}})

    def economic(self, positions, candidates, platforms=None):
        import kdd_economics as econ
        positions_out, candidates_out = [], []
        for group, tokens, dest in (("posizioni", positions, positions_out),
                                    ("candidati", candidates, candidates_out)):
            for i, token in enumerate(tokens):
                identity = self.ident(token)
                payload = {"id": identity.get("coingecko_id"), "symbol": token.lower(),
                           "name": identity.get("progetto"),
                           "platforms": (platforms or {}).get(token, {})}
                entry = {"indice": i, "token": token, "identita": identity,
                         "network_metadata": evidence.coin_network_metadata(identity, payload, T)}
                if group == "candidati":
                    entry["coppia_analisi"] = token + "/EUR"
                dest.append(entry)
        return {"posizioni": positions_out, "candidati": candidates_out}

    def fetch(self, url, payload=None):
        if url == evidence.CONTRACT_ENDPOINTS["solana"] and payload and payload.get("method") == "getTokenSupply":
            return {"jsonrpc": "2.0", "id": 1, "result": {
                "context": {"slot": 400000000},
                "value": {"amount": "1000000000000", "decimals": 6}}}
        if url in evidence.SOURCES.values():
            return fake_fetch(url, payload)
        if url == evidence.NATIVE_ENDPOINTS["bitcoin"]:
            return [{"height": 900000, "tx_count": 2378,
                     "timestamp": int(T.timestamp()), "id": "a" * 64}]
        if url in (evidence.NATIVE_ENDPOINTS["ethereum"],
                   evidence.NATIVE_ENDPOINTS["bsc"]):
            method = payload["method"]
            if method == "eth_getBlockByNumber":
                return {"jsonrpc": "2.0", "id": 1, "result": {
                    "number": hex(21000000), "timestamp": hex(int(T.timestamp())),
                    "hash": "0x" + "b" * 64}}
            if method == "eth_getCode":
                return {"jsonrpc": "2.0", "id": 1, "result": "0x60806040"}
            if method == "eth_call":
                return {"jsonrpc": "2.0", "id": 1,
                        "result": hex(420690000000000000000000000000000000000)}
        if url == evidence.CONTRACT_ENDPOINTS["solana"]:
            if payload["method"] == "getTokenSupply":
                return {"jsonrpc": "2.0", "id": 1, "result": {
                    "context": {"slot": 400000000},
                    "value": {"amount": "1000000000000", "decimals": 6}}}
            return fake_fetch(url, payload)
        if url == evidence.NATIVE_ENDPOINTS["near"]:
            return {"jsonrpc": "2.0", "id": 1, "result": {"header": {
                "height": 198000000, "timestamp_nanosec": str(int(T.timestamp()) * 10**9),
                "hash": "b" * 44}}}
        if url == evidence.NATIVE_ENDPOINTS["xrpl"]:
            return {"jsonrpc": "2.0", "status": "success", "result": {
                "validated": True, "ledger_index": 100000000,
                "ledger_hash": "C" * 64,
                "ledger": {"close_time_iso": T.isoformat(),
                           "ledger_index": "100000000", "closed": True,
                           "ledger_hash": "C" * 64}}}
        raise AssertionError("unexpected public request: " + url)

    def test_ethereum_verified_public_rpc_endpoint_and_ip_rate_limit(self):
        """Samsung-selected provider: shared 1rps/IP must include ERC-20 probes."""
        endpoint = "https://public-ethereum-mainnet.rpcnode.dev"
        self.assertEqual(evidence.NATIVE_ENDPOINTS["ethereum"], endpoint)
        self.assertEqual(evidence.CONTRACT_ENDPOINTS["ethereum"], endpoint)
        self.assertNotIn("ethereum-rpc.publicnode.com", evidence.NATIVE_ENDPOINTS.values())
        clock = [100.0]
        waits, requests = [], []

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def geturl(self):
                return endpoint
            def read(self, limit):
                return b'{"jsonrpc":"2.0","id":1,"result":"0x60806040"}'

        def sleep(seconds):
            waits.append(seconds)
            clock[0] += seconds

        def urlopen(req, timeout):
            requests.append((req.full_url, req.get_method(), timeout))
            return Response()

        payloads = [
            {"jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber",
             "params": ["latest", False]},
            {"jsonrpc": "2.0", "id": 1, "method": "eth_getCode",
             "params": [self.ETH, "latest"]},
            {"jsonrpc": "2.0", "id": 1, "method": "eth_call",
             "params": [{"to": self.ETH, "data": "0x18160ddd"}, "latest"]},
        ]
        with (mock.patch.object(evidence, "_ETH_RPC_NEXT_AT", 0.0),
              mock.patch.object(evidence.time, "monotonic", side_effect=lambda: clock[0]),
              mock.patch.object(evidence.time, "sleep", side_effect=sleep),
              mock.patch.object(evidence.urllib.request, "urlopen", side_effect=urlopen)):
            for payload in payloads:
                result = evidence._http(endpoint, payload)
                self.assertEqual(result["id"], 1)
        self.assertEqual(requests, [(endpoint, "POST", 9)] * 3)
        self.assertEqual(len(waits), 2)
        self.assertTrue(all(seconds >= 1.0 for seconds in waits))

    def test_xrpl_validated_response_without_id_and_fail_closed_variants(self):
        """Actual HTTP shape lacks id: finality still requires validated=true."""
        response = {
            "status": "success", "type": "response",
            "result": {
                "ledger_index": 100000000, "ledger_hash": "C" * 64,
                "validated": True,
                "ledger": {"ledger_index": "100000000", "ledger_hash": "C" * 64,
                           "close_time_iso": T.isoformat(), "closed": True},
            },
        }
        def observe(value):
            return evidence._native_observe("xrpl", lambda url, payload: copy.deepcopy(value), T)
        success = observe(response)
        self.assertEqual(success["stato"], "OSSERVATO")
        self.assertEqual(success["valori"]["indice_ledger"], 100000000)
        self.assertEqual(success["valori"]["ledger_hash"], "C" * 64)
        self.assertEqual(success["osservato_utc"], T.isoformat())
        # A correctly echoed id still works; a mismatched id must fail closed.
        with_id = copy.deepcopy(response)
        with_id["id"] = 1
        self.assertEqual(observe(with_id)["stato"], "OSSERVATO")
        # Preserve the older id+result.status dialect as well.
        old_style = copy.deepcopy(with_id)
        old_style.pop("status")
        old_style["result"]["status"] = "success"
        self.assertEqual(observe(old_style)["stato"], "OSSERVATO")
        cases = []
        for mutation in ("missing_validated", "not_validated", "numeric_validated",
                         "wrong_id", "bad_status", "index_mismatch", "hash_mismatch",
                         "bad_hash", "bad_timestamp", "open_ledger", "future_ledger"):
            damaged = copy.deepcopy(response)
            if mutation == "missing_validated":
                del damaged["result"]["validated"]
            elif mutation == "not_validated":
                damaged["result"]["validated"] = False
            elif mutation == "numeric_validated":
                damaged["result"]["validated"] = 1
            elif mutation == "wrong_id":
                damaged["id"] = 5
            elif mutation == "bad_status":
                damaged["status"] = "error"
            elif mutation == "index_mismatch":
                damaged["result"]["ledger"]["ledger_index"] = "99999999"
            elif mutation == "hash_mismatch":
                damaged["result"]["ledger_hash"] = "D" * 64
            elif mutation == "bad_hash":
                damaged["result"]["ledger"]["ledger_hash"] = "fake"
            elif mutation == "bad_timestamp":
                damaged["result"]["ledger"]["close_time_iso"] = "invalid"
            elif mutation == "open_ledger":
                damaged["result"]["ledger"]["closed"] = False
            elif mutation == "future_ledger":
                damaged["result"]["ledger"]["close_time_iso"] = (T + dt.timedelta(minutes=3)).isoformat()
            cases.append((mutation, observe(damaged)))
        for label, outcome in cases:
            with self.subTest(label=label):
                self.assertEqual(outcome["stato"], "NON_DISPONIBILE")
                self.assertIsNone(outcome["valori"])
                self.assertIsNone(outcome["osservato_utc"])

    def test_ethereum_http_error_stays_unavailable_without_contract_claims(self):
        from urllib.error import HTTPError
        def forbidden(url, payload=None):
            raise HTTPError(url, 429, "rate limited", {"Retry-After": "1"}, None)
        native = evidence._native_observe("ethereum", forbidden, T)
        contract = evidence._probe_contract("ethereum", self.ETH, forbidden, T)
        self.assertEqual(native["stato"], "NON_DISPONIBILE")
        self.assertIsNone(native["valori"])
        self.assertEqual(contract["stato"], "NON_DISPONIBILE")
        self.assertIsNone(contract["valori"])
        self.assertEqual(contract["ufficialita_contratto"], "NON_ATTESTATA")

    def test_native_contract_multichain_ambiguous_new_asset_and_rotation(self):
        positions = ["BTC", "ETH", "PEPE", "JUP", "NEAR", "XRP"]
        candidates = ["NEW", "JUP"]
        platforms = {"PEPE": {"ethereum": self.ETH, "binance-smart-chain": self.BSC},
                     "JUP": {"solana": self.MINT}}
        econ = self.economic(positions, candidates, platforms)
        owned = [{"token": t} for t in positions]
        shortlist = [{"token": t, "coppia_analisi": t + "/EUR"} for t in candidates]
        raw = evidence.collect(T, owned, shortlist, fetch=self.fetch, economics=econ)
        details = raw["asset_reti"]
        self.assertEqual(len(details["posizioni"]), 6)
        self.assertEqual(len(details["candidati"]), 2)
        self.assertEqual([row["tipo"] for row in details["posizioni"]],
                         ["NATIVO", "NATIVO", "MULTICHAIN",
                          "TOKEN_CON_CONTRATTO", "NATIVO", "NATIVO"])
        self.assertEqual(details["candidati"][0]["tipo"], "NON_VERIFICATO")
        self.assertEqual(details["candidati"][0]["contratti_indicizzati"], [])
        self.assertEqual(details["contratti_indicizzati_totali"], 3)
        self.assertEqual(details["contratti_esaminati"], 2)
        self.assertEqual(details["posizioni"][2]["ufficialita_contratto"], "NON_ATTESTATA")
        self.assertEqual(details["posizioni"][2]["verifica_contratto_fonte_primaria"], "NON_ESEGUITA")
        self.assertEqual(details["posizioni"][2]["rete_deposito_kraken"], "NON_ATTESTATA")
        self.assertEqual(details["posizioni"][3]["ufficialita_contratto"], "NON_ATTESTATA")
        read = evidence.at_read(raw, owned, shortlist, T, economics=econ)["asset_reti"]
        self.assertEqual(read["posizioni"][0]["osservazione_nativa"]["stato"],
                         "OSSERVATO_CON_LIMITI")
        self.assertEqual(read["posizioni"][0]["osservazione_nativa"]["valori"]["altezza_blocco"],
                         900000)
        self.assertEqual(read["posizioni"][2]["osservazioni_contratti"][0]["osservazione"]["stato"],
                         "OSSERVATO_CON_LIMITI")
        self.assertEqual(read["posizioni"][2]["osservazioni_contratti"][0]["osservazione"]["valori"]["supply_unita_minima"],
                         "420690000000000000000000000000000000000")
        self.assertNotIn("quantita", json.dumps(details).lower())
        self.assertIn("nessuna attestazione primaria", details["limite"])
        self.assertEqual(read["posizioni"][2]["osservazioni_contratti"][0]
                         ["osservazione"]["ufficialita_contratto"], "NON_ATTESTATA")
        forged = copy.deepcopy(raw)
        forged["asset_reti"]["posizioni"][2]["ufficialita_contratto"] = "ATTESTATA"
        with self.assertRaises(ValueError):
            evidence.at_read(forged, owned, shortlist, T, economics=econ)
        late = evidence.at_read(raw, owned, shortlist, T + dt.timedelta(minutes=40),
                                economics=econ)["asset_reti"]
        self.assertIsNone(late["posizioni"][0]["osservazione_nativa"]["valori"])
        self.assertIsNone(late["posizioni"][2]["osservazioni_contratti"][0]["osservazione"]["valori"])
        # The third mint is not silently forgotten; it appears on the next run.
        second = evidence.collect(T, owned, shortlist, fetch=self.fetch,
                                  economics=econ, previous=raw)
        self.assertIn(("solana", self.MINT),
                      {(x["rete"], x["contratto"]) for x in second["asset_reti"]["sonde_contratto"]})
        # Candidate leaves and re-enters: current roster, never a false balance.
        shorter = evidence.collect(T, owned, [], fetch=self.fetch, economics={
            "posizioni": econ["posizioni"], "candidati": []}, previous=second)
        self.assertEqual(shorter["asset_reti"]["candidati"], [])
        self.assertEqual(len(raw["asset_reti"]["candidati"]), 2)

    def test_mismatched_coin_id_ticker_only_and_rpc_failure_fail_closed(self):
        owned = [{"token": "PEPE"}, {"token": "BTC"}]
        econ = self.economic(["PEPE", "BTC"], [], {"PEPE": {"ethereum": self.ETH}})
        fake = {"id": "not-pepe", "symbol": "pepe", "name": "Pepe",
                "platforms": {"ethereum": self.ETH}}
        self.assertIsNone(evidence.coin_network_metadata(econ["posizioni"][0]["identita"],
                                                         fake, T))
        tamper = copy.deepcopy(econ)
        tamper["posizioni"][0]["identita"]["stato"] = "NON_VERIFICATO"
        with self.assertRaises(ValueError):
            evidence.collect(T, owned, [], fetch=self.fetch, economics=tamper)
        def down(url, payload=None):
            if url in (evidence.NATIVE_ENDPOINTS["bitcoin"],
                       evidence.CONTRACT_ENDPOINTS["ethereum"]):
                raise OSError("offline")
            return self.fetch(url, payload)
        raw = evidence.collect(T, owned, [], fetch=down, economics=econ)
        read = evidence.at_read(raw, owned, [], T, economics=econ)["asset_reti"]
        self.assertEqual(read["posizioni"][1]["osservazione_nativa"]["stato"],
                         "NON_DISPONIBILE")
        self.assertEqual(read["posizioni"][0]["osservazioni_contratti"][0]["osservazione"]["stato"],
                         "NON_DISPONIBILE")
        self.assertIsNone(read["posizioni"][0]["osservazioni_contratti"][0]["osservazione"]["valori"])
        mutated = copy.deepcopy(raw)
        mutated["asset_reti"]["posizioni"][0]["contratti_indicizzati"][0]["contratto"] = self.BSC
        with self.assertRaises(ValueError):
            evidence.at_read(mutated, owned, [], T, economics=econ)
        missing = copy.deepcopy(raw)
        missing["asset_reti"]["sonde_contratto"][0]["stato"] = "OSSERVATO"
        with self.assertRaises(ValueError):
            evidence.at_read(missing, owned, [], T, economics=econ)
        with self.assertRaises(ValueError):
            evidence.at_read(raw, owned, [], T)



class Kdd17CapitalMovementTests(unittest.TestCase):
    """Synthetic protocol replies; no external calls or private account IDs."""

    EVM_ADDR = "0x" + "1" * 40
    EVM_FROM = "0x" + "2" * 40
    EVM_TO = "0x" + "3" * 40
    MINT = "A" * 32
    HOLDER = "B" * 32

    def _assets(self, chain="ethereum", contract=None):
        return {"posizioni": [{"token": "PEPE" if contract else "BTC",
                                "progetto_id": "pepe" if contract else "bitcoin",
                                "coppia_analisi": None,
                                "contratti_indicizzati":
                                    [{"rete": chain, "contratto": contract}] if contract else []}],
                "candidati": [],
                "fonti_native": {
                    "bitcoin": {"valori": {"blocco_hash": "a" * 64,
                                           "transazioni_blocco": 300}},
                    "ethereum": {"valori": {"altezza_blocco": 1000}},
                    "bsc": {"valori": {"altezza_blocco": 1000}}}}

    def _econ(self):
        return {"posizioni": [{"fondamentali": {
                    "stato": "VERIFICATO", "capitalizzazione_usd": 100000000,
                    "offerta_circolante": 1000000, "fonte": "https://api.coingecko.com/api/v3/coins/pepe"}}],
                "candidati": []}

    def test_erc20_real_transfer_logs_dedup_largest_and_supply_context(self):
        import kdd_capital_flow as cap
        topic = lambda addr: "0x" + "0" * 24 + addr[2:]
        log = {"address": self.EVM_ADDR, "transactionHash": "0x" + "f" * 64,
               "blockNumber": hex(983), "logIndex": "0x0",
               "removed": False, "topics": [cap.TOPIC_TRANSFER,
                topic(self.EVM_FROM), topic(self.EVM_TO)],
               "data": "0x" + format(200000000, "064x")}
        seen = []
        def fetch(url, payload=None):
            seen.append((url, payload))
            if payload:
                method = payload["method"]
                if method == "eth_call":
                    return {"jsonrpc": "2.0", "id": 1, "result": "0x12"}
                if method == "eth_getLogs":
                    self.assertEqual(payload["params"][0]["address"], self.EVM_ADDR)
                    return {"jsonrpc": "2.0", "id": 1, "result": [log, dict(log)]}
            if url.endswith("/transfers"):
                return {"items": [{"tx_hash":log["transactionHash"],
                        "from":{"hash":self.EVM_FROM,"public_tags":[{"label":"Coinbase 1"}]},
                        "to":{"hash":self.EVM_TO,"public_tags":[]},
                        "total":{"value":"200000000"}}]}
            if url.endswith("/holders"):
                return {"items": [{"address": {"hash": self.EVM_FROM,
                                                "public_tags": [{"label": "Exchange"}]},
                                   "value": "500000000"}]}
            raise OSError("not used")
        assets = self._assets(contract=self.EVM_ADDR)
        raw = cap.collect(T, assets, self._econ(), None, fetch)
        self.assertEqual(raw["target_totali"], 1)
        probe = raw["sonde"][0]
        self.assertEqual(probe["stato"], "OSSERVATO")
        self.assertEqual(len(probe["eventi"]), 1)
        self.assertEqual(probe["eventi"][0]["quantita"], "0.0000000002")
        self.assertEqual(probe["eventi"][0]["da"], self.EVM_FROM)
        self.assertEqual(probe["detentori"][0]["entita"]["classe"], "EXCHANGE")
        self.assertEqual(probe["eventi"][0]["attribuzione"]["da"]["classe"],"EXCHANGE")
        self.assertEqual(probe["eventi"][0]["fonte_attribuzione"], cap.ETH_EXPLORER+"/api/v2/tokens/"+self.EVM_ADDR+"/transfers")
        second=cap.collect(T, assets, self._econ(), raw, fetch)
        self.assertEqual(second["sonde"][0]["detentori"][0]["variazione_unita_minima"],"0")
        assets["posizioni"][0]["osservazioni_contratti"]=[{
            "rete":"ethereum","contratto":self.EVM_ADDR,
            "osservazione":{"stato":"OSSERVATO_CON_LIMITI",
                           "valori":{"supply_unita_minima":"1000000000"}}}]
        read = cap.at_read(raw, assets, self._econ(), T)
        record = read["posizioni"][0]["osservazioni"][0]
        self.assertEqual(record["stato"], "OSSERVATO_CON_LIMITI")
        self.assertEqual(record["detentori"][0]["quota_supply_pct"],"50.0000")
        self.assertEqual(record["flussi_exchange_campione"]["uscita_unita_minima"],200000000)
        self.assertEqual(record["eventi"][0]["stato_alla_lettura"], "CAMPIONE_RECENTE")
        self.assertIsNotNone(record["eventi"][0]["valore_usd_indicativo"])
        late = cap.at_read(raw, assets, self._econ(), T + dt.timedelta(minutes=40))
        self.assertIsNone(late["posizioni"][0]["osservazioni"][0]["eventi"][0]["valore_usd_indicativo"])
        self.assertEqual(late["posizioni"][0]["osservazioni"][0]["stato"], "STORICO")
        poison = copy.deepcopy(raw)
        poison["sonde"][0]["eventi"][0]["quantita"] = "1"
        with self.assertRaises(ValueError):
            cap.at_read(poison, assets, self._econ(), T)
        poison = copy.deepcopy(raw)
        poison["sonde"][0]["asset_tecnico"] = self.EVM_TO
        with self.assertRaises(ValueError):
            cap.at_read(poison, assets, self._econ(), T)

    def test_bitcoin_utxo_output_is_not_investor_and_sample_limited(self):
        import kdd_capital_flow as cap
        assets = self._assets()
        def fetch(url, payload=None):
            self.assertTrue(url.endswith("/" + "a" * 64 + "/txs"))
            return [{"txid": "b" * 64, "status": {"confirmed": True,
                      "block_hash": "a" * 64, "block_height": 800},
                     "vin": [{"prevout": {"scriptpubkey_address": "bc1qtest"}}],
                     "vout": [{"value": 100000000, "scriptpubkey_address": "bc1qdest"},
                              {"value": 200000000, "scriptpubkey_address": "bc1qchange"}]},
                    {"txid": "c" * 64, "status": {"confirmed": False},
                     "vin": [], "vout": [{"value": 900000000,
                                           "scriptpubkey_address": "bc1qpending"}]}]
        raw = cap.collect(T, assets, self._econ(), None, fetch)
        block = raw["sonde"][0]
        self.assertEqual(block["stato"], "OSSERVATO")
        self.assertEqual(len(block["eventi"]), 2)
        self.assertEqual(block["eventi"][0]["quantita"], "2")
        self.assertEqual(block["eventi"][0]["tipo"], "OUTPUT_UTXO")
        self.assertIn("resto", block["copertura"])
        self.assertEqual(block["periodo"]["transazioni_totali_blocco"], 300)

    def test_explorer_transfer_tags_inbound_not_sale_and_historical_nonzero_unknown(self):
        import kdd_capital_flow as cap
        assets=self._assets(contract=self.EVM_ADDR)
        tx="0x"+"d"*64
        transfer={"tx_hash":tx,"timestamp":T.isoformat(),
                  "from":{"hash":self.EVM_FROM,"public_tags":[]},
                  "to":{"hash":self.EVM_TO,"public_tags":[{"label":"Example Exchange"}]},
                  "total":{"value":"1000000000000000000"}}
        def fetch(url,payload=None):
            if payload:
                if payload["method"]=="eth_call":
                    return {"jsonrpc":"2.0","id":1,"result":"0x12"}
                if payload["method"]=="eth_getLogs":
                    raise OSError("RPC method denied")
            if url.endswith("/transfers"):
                return {"items":[transfer,dict(transfer)]}
            if url.endswith("/holders"):
                return {"items":[]}
            raise AssertionError(url)
        raw=cap.collect(T,assets,self._econ(),None,fetch)
        self.assertEqual(raw["sonde"][0]["stato"],"OSSERVATO")
        self.assertEqual(len(raw["sonde"][0]["eventi"]),1)
        read=cap.at_read(raw,assets,self._econ(),T)["posizioni"][0]["osservazioni"][0]
        self.assertEqual(read["flussi_exchange_campione"]["stato"],"CAMPIONE_ETICHETTATO_PARZIALE")
        self.assertEqual(read["flussi_exchange_campione"]["ingresso_unita_minima"],10**18)
        self.assertEqual(read["flussi_exchange_campione"]["uscita_unita_minima"],0)
        self.assertIn("deposito non significa vendita",read["flussi_exchange_campione"]["limite"])
        late=cap.at_read(raw,assets,self._econ(),T+dt.timedelta(minutes=45))["posizioni"][0]["osservazioni"][0]
        self.assertEqual(late["eventi"][0]["stato_alla_lettura"],"STORICO")
        self.assertIsNone(late["flussi_exchange_campione"]["flusso_netto_unita_minima"])
        transfer["timestamp"]=(T-dt.timedelta(days=1)).isoformat()
        old=cap.collect(T,assets,self._econ(),None,fetch)
        historical=cap.at_read(old,assets,self._econ(),T)["posizioni"][0]["osservazioni"][0]
        self.assertEqual(historical["eventi"][0]["stato_alla_lettura"],"STORICO")
        self.assertIsNone(historical["flussi_exchange_campione"]["ingresso_unita_minima"])

    def test_ethplorer_public_fallback_real_response_shape_and_exact_units(self):
        """Verified free-index schema: operations/holders/rawBalance, no invented labels."""
        from urllib.error import HTTPError
        import kdd_capital_flow as cap
        assets=self._assets(contract=self.EVM_ADDR)
        observed=[]
        def fetch(url,payload=None):
            observed.append((url,payload["method"] if payload else "GET"))
            if payload:
                if payload["method"]=="eth_call":
                    return {"jsonrpc":"2.0","id":1,"result":"0x12"}
                if payload["method"]=="eth_getLogs":
                    raise HTTPError(url,403,"forbidden",None,None)
            if url.startswith(cap.ETH_EXPLORER):
                raise HTTPError(url,403,"forbidden",None,None)
            if url.startswith(cap.ETHPLORER+"/getTokenHistory/"):
                return {"operations":[
                    {"timestamp":int(T.timestamp()),"transactionHash":"0x"+"e"*64,
                     "tokenInfo":{"address":self.EVM_ADDR,"decimals":"18"},
                     "type":"transfer","value":"3000000000000000000",
                     "from":self.EVM_FROM,"to":self.EVM_TO},
                    {"timestamp":int(T.timestamp()),"transactionHash":"0x"+"e"*64,
                     "tokenInfo":{"address":self.EVM_ADDR,"decimals":"18"},
                     "type":"transfer","value":"3000000000000000000",
                     "from":self.EVM_FROM,"to":self.EVM_TO},
                    {"timestamp":int(T.timestamp()),"transactionHash":"0x"+"f"*64,
                     "tokenInfo":{"address":self.EVM_TO,"decimals":"18"},
                     "type":"transfer","value":"900000000000000000000",
                     "from":self.EVM_FROM,"to":self.EVM_TO}]}
            if url.startswith(cap.ETHPLORER+"/getTopTokenHolders/"):
                return {"holders":[
                    {"address":self.EVM_FROM, "balance":50.0,
                     "rawBalance":"50000000000000000000","share":50.0},
                    {"address":self.EVM_TO,"balance":5.0,"share":5.0}]}
            raise AssertionError(url)
        raw=cap.collect(T,assets,self._econ(),None,fetch)
        self.assertEqual(raw["sonde"][0]["stato"],"OSSERVATO")
        self.assertEqual(raw["sonde"][0]["periodo"]["tipo"],"PAGINA_ETHPLORER")
        self.assertEqual(len(raw["sonde"][0]["eventi"]),1)
        self.assertEqual(raw["sonde"][0]["eventi"][0]["quantita"],"3")
        self.assertEqual(raw["sonde"][0]["detentori"][0]["unita_minima"],
                         "50000000000000000000")
        self.assertEqual(len(raw["sonde"][0]["detentori"]),1)  # rounded UI only skipped
        self.assertEqual(raw["sonde"][0]["richieste_effettuate"],6)
        reading=cap.at_read(raw,assets,self._econ(),T)["posizioni"][0]["osservazioni"][0]
        self.assertEqual(reading["eventi"][0]["fonte"],cap.ETHPLORER+
                         "/getTokenHistory/"+self.EVM_ADDR+"?apiKey=freekey&limit=20")
        self.assertEqual(reading["flussi_exchange_campione"]["stato"],
                         "NON_ATTRIBUIBILE_O_STORICO")
        self.assertIsNone(reading["flussi_exchange_campione"]["ingresso_unita_minima"])
        self.assertEqual(reading["operatori_etichettati_nel_campione"],0)
        bad=copy.deepcopy(raw)
        bad["sonde"][0]["eventi"][0]["fonte"]="https://api.ethplorer.io/getTokenHistory/"+self.EVM_TO+"?apiKey=freekey&limit=20"
        with self.assertRaises(ValueError):
            cap.at_read(bad,assets,self._econ(),T)

    def test_custodian_fund_protocol_labels_are_not_exchange_flows(self):
        """An identified institution is not automatically a known exchange."""
        import kdd_capital_flow as cap
        assets = self._assets(contract=self.EVM_ADDR)
        for name, expected in (("Example Custodian", "CUSTODE"),
                               ("Example Fund", "FONDO"),
                               ("Example Protocol", "PROTOCOLLO")):
            with self.subTest(name=name):
                def fetch(url, payload=None):
                    if payload:
                        method = payload["method"]
                        if method == "eth_call":
                            return {"jsonrpc": "2.0", "id": 1, "result": "0x12"}
                        if method == "eth_getLogs":
                            raise OSError("RPC logs unavailable")
                    if url.endswith("/transfers"):
                        return {"items": [{"tx_hash": "0x" + "e" * 64,
                            "timestamp": T.isoformat(),
                            "from": {"hash": self.EVM_FROM, "public_tags": []},
                            "to": {"hash": self.EVM_TO,
                                   "public_tags": [{"label": name}]},
                            "total": {"value": "1000000000000000000"}}]}
                    if url.endswith("/holders"):
                        return {"items": []}
                    raise AssertionError(url)
                raw = cap.collect(T, assets, self._econ(), None, fetch)
                reading = cap.at_read(raw, assets, self._econ(), T)
                observation = reading["posizioni"][0]["osservazioni"][0]
                self.assertEqual(observation["eventi"][0]["attribuzione"]["a"]["classe"],
                                 expected)
                self.assertEqual(observation["operatori_etichettati_nel_campione"], 1)
                flow = observation["flussi_exchange_campione"]
                self.assertEqual(flow["stato"], "NON_ATTRIBUIBILE_O_STORICO")
                for field in ("ingresso_unita_minima", "uscita_unita_minima",
                              "flusso_netto_unita_minima"):
                    self.assertIsNone(flow[field])
                self.assertIn("NON zero", flow["limite"])

    def test_solana_spl_holders_and_transfer_checked(self):
        import kdd_capital_flow as cap
        assets = {"posizioni": [{"token": "JUP", "progetto_id": "jupiter",
                 "coppia_analisi": None,
                 "contratti_indicizzati": [{"rete":"solana","contratto":self.MINT}]}],
                 "candidati": [], "fonti_native": {}}
        def fetch(url, payload=None):
            method=payload["method"]
            if method=="getTokenLargestAccounts":
                return {"id":1,"result":{"context":{"slot":500},
                     "value":[{"address":self.HOLDER,"amount":"5000000","decimals":6}]}}
            if method=="getTokenSupply":
                return {"id":1,"result":{"value":{"amount":"10000000","decimals":6}}}
            if method=="getSignaturesForAddress":
                return {"id":1,"result":[{"signature":"C"*64,"err":None}]}
            if method=="getTransaction":
                return {"id":1,"result":{"slot":500,"blockTime":int(T.timestamp()),
                     "meta":{"err":None,"innerInstructions":[]},
                     "transaction":{"message":{"instructions":[{"parsed":{
                       "type":"transferChecked","info":{"mint":self.MINT,
                       "source":self.HOLDER,"destination":"D"*32,
                       "tokenAmount":{"amount":"250000","decimals":6}}}}]}}}}
            raise AssertionError(method)
        raw = cap.collect(T, assets, self._econ(), None, fetch)
        p = raw["sonde"][0]
        self.assertEqual(p["stato"],"OSSERVATO")
        self.assertEqual(p["detentori"][0]["quota_supply_pct"],"50.0000")
        self.assertEqual(p["eventi"][0]["quantita"],"0.25")
        second=cap.collect(T,assets,self._econ(),raw,fetch)
        self.assertEqual(second["sonde"][0]["detentori"][0]["variazione_unita_minima"],"0")

    def test_xrp_sui_near_samples_and_source_outage_independent(self):
        import kdd_capital_flow as cap
        btc = self._assets()
        assets = {"posizioni": [
            {"token":"XRP","progetto_id":"ripple","contratti_indicizzati":[]},
            {"token":"SUI","progetto_id":"sui","contratti_indicizzati":[]},
            {"token":"NEAR","progetto_id":"near","contratti_indicizzati":[]},
            btc["posizioni"][0]],"candidati":[],"fonti_native":btc["fonti_native"]}
        def fetch(url,payload=None):
            if "ripple.com" in url:
                return {"status":"success","result":{"status":"success","validated":True,
                    "ledger_index":100,"ledger":{"ledger_hash":"A"*64,
                    "close_time_iso":T.isoformat(),"transactions":[{
                      "tx":{"hash":"B"*64,"TransactionType":"Payment",
                      "Account":"rSRC","Destination":"rDST","Amount":"999"},
                      "meta":{"TransactionResult":"tesSUCCESS",
                              "delivered_amount":"5000000"}}]}}}
            if "sui.io" in url:
                return {"data":{"transactions":{"nodes":[{
                    "digest":"A"*40,"effects":{"status":"SUCCESS",
                      "timestamp":T.isoformat(),"checkpoint":{"sequenceNumber":"450"},
                      "balanceChanges":{"nodes":[{"owner":{"address":"0x123"},
                      "amount":"-1000000000","coinType":{"repr":"0x2::sui::SUI"}}]}}}]}}}
            if "near.org" in url:
                if payload["method"]=="block":
                    return {"id":1,"result":{"chunks":[{"chunk_hash":"A"*44}],
                            "header":{"height":200}}}
                if payload["method"]=="chunk":
                    return {"id":1,"result":{"transactions":[{"hash":"D"*42,
                           "signer_id":"sender.near","receiver_id":"receiver.near",
                           "actions":[{"Transfer":{"deposit":"5000000000000000000000000"}}]}]}}
            raise OSError("Bitcoin not available")
        raw=cap.collect(T,assets,{"posizioni":[{}]*4,"candidati":[]},None,fetch)
        statuses={(s["rete"],s["stato"]) for s in raw["sonde"]}
        self.assertIn(("xrpl","OSSERVATO"),statuses)
        self.assertIn(("sui","OSSERVATO"),statuses)
        self.assertIn(("near","OSSERVATO"),statuses)
        self.assertIn(("bitcoin","NON_DISPONIBILE"),statuses)
        self.assertEqual(next(s for s in raw["sonde"] if s["rete"]=="xrpl")
                         ["eventi"][0]["quantita"],"5")
        self.assertEqual(next(s for s in raw["sonde"] if s["rete"]=="sui")
                         ["eventi"][0]["tipo"],"VARIAZIONE_NETTA_SALDO_NON_TRASFERIMENTO")

    def test_holders_comparison_survives_bounded_target_rotation(self):
        import kdd_capital_flow as cap
        contracts=["0x"+format(i+1, "040x") for i in range(6)]
        assets={"posizioni":[],"candidati":[
            {"token":"T"+str(i),"progetto_id":"project-"+str(i),
             "coppia_analisi":"T"+str(i)+"/EUR",
             "contratti_indicizzati":[{"rete":"ethereum","contratto":address}]}
            for i,address in enumerate(contracts)],
            "fonti_native":{"ethereum":{"valori":{"altezza_blocco":1000}}}}
        economic={"posizioni":[],"candidati":[{} for _ in contracts]}
        calls=[]
        def fake_probe(key, assets, fetch, previous):
            previous_rows=previous.get("detentori") or []
            old=previous_rows[0]["unita_minima"] if previous_rows else None
            calls.append((key[1],old))
            qty=int(old)+1 if old is not None else 100
            return {"eventi":[],"detentori":[{
                "account":"0x"+"a"*40,"unita_minima":str(qty),"decimali":18,
                "variazione_unita_minima":str(qty-int(old)) if old else None,
                "entita":{"stato":"ENTITA_NON_IDENTIFICATA"}}],
                "elementi_esaminati":1,"eventi_distinti":0,
                "periodo":{"tipo":"TEST"},"copertura":"Synthetic holder snapshot"}
        with mock.patch.object(cap,"_probe",side_effect=fake_probe):
            first=cap.collect(T,assets,economic,None,lambda *args: None)
            second=cap.collect(T+dt.timedelta(minutes=1),assets,economic,first,lambda *args: None)
            third=cap.collect(T+dt.timedelta(minutes=2),assets,economic,second,lambda *args: None)
        self.assertEqual([x["asset_tecnico"] for x in first["sonde"]],contracts[:5])
        self.assertEqual(len(first["storico_detentori"]),5)
        self.assertEqual(len(second["storico_detentori"]),6)
        self.assertEqual(len(third["storico_detentori"]),6)
        self.assertEqual(calls[6],(contracts[0],"100"))
        self.assertTrue(any(key==contracts[4] and prior=="100" for key,prior in calls[10:]))
        interpreted=cap.at_read(third,assets,economic,T+dt.timedelta(minutes=2))
        self.assertEqual(len(interpreted["candidati"]),6)
        self.assertTrue(any(x["osservazioni"][0]["stato"]=="RINVIATO_BUDGET"
                            for x in interpreted["candidati"]))

    def test_public_request_budget_stops_rotation_without_zero_metrics(self):
        import kdd_capital_flow as cap
        contracts=["0x"+format(i+1,"040x") for i in range(6)]
        assets={"posizioni":[], "candidati":[
            {"token":"X"+str(i), "progetto_id":"other-"+str(i),
             "coppia_analisi":"X"+str(i)+"/EUR",
             "contratti_indicizzati":[{"rete":"ethereum","contratto":addr}]}
            for i,addr in enumerate(contracts)],"fonti_native":{}}
        calls=[]
        def fetch(url,payload=None):
            calls.append(url)
            return {}
        def expensive_probe(key,assets,fetch,previous):
            for i in range(7):
                fetch("https://test.example/public")
            raise AssertionError("over-budget probe should not finish")
        with mock.patch.object(cap,"_probe",side_effect=expensive_probe):
            result=cap.collect(T,assets,{"posizioni":[],"candidati":[{}]*6},
                               None,fetch)
        self.assertEqual(result["richieste_effettuate"],15)
        self.assertEqual(len(calls),15)
        self.assertEqual(result["target_totali"],6)
        self.assertEqual(result["target_interrogati"],3)
        self.assertEqual([r["motivo"] for r in result["sonde"]],
                         ["BUDGET_RICHIESTE"]*3)
        self.assertEqual(result["prossimo_target"],"ethereum|"+contracts[3])
        read=cap.at_read(result,assets,{"posizioni":[],"candidati":[{}]*6},T)
        self.assertEqual(len(read["candidati"]),6)
        self.assertEqual(read["candidati"][3]["osservazioni"][0]["stato"],
                         "RINVIATO_BUDGET")
        self.assertEqual(read["candidati"][0]["osservazioni"][0]["stato"],
                         "NON_DISPONIBILE")
        self.assertIsNone(read["candidati"][3]["osservazioni"][0].get("valori"))

    def test_routescan_ethereum_and_avalanche_without_native_wallet_assets(self):
        """Live-verified Routescan schemas; both tokens have dynamic contracts."""
        import kdd_capital_flow as cap
        chains={"ethereum":("0x"+"1"*40,"1"),
                "avalanche":("0x"+"2"*40,"43114")}
        assets={"posizioni":[
            {"token":"AAVE","progetto_id":"aave","coppia_analisi":None,
             "contratti_indicizzati":[{"rete":"ethereum","contratto":chains["ethereum"][0]}]},
            {"token":"AVAXUSDC","progetto_id":"usd-coin","coppia_analisi":None,
             "contratti_indicizzati":[{"rete":"avalanche","contratto":chains["avalanche"][0]}]}],
            "candidati":[],"fonti_native":{}} # No ETH or AVAX wallet position
        def fetch(url,payload=None):
            chain=next((ch for ch,(contract,number) in chains.items()
                        if url.startswith(cap.ROUTESCAN+number+"/")),None)
            if not chain:
                raise AssertionError("unexpected source: "+url)
            contract,chain_id=chains[chain]
            if "erc20-transfers?" in url:
                self.assertIn("tokenAddress="+contract,url)
                return {"items":[{"chainId":chain_id,"blockNumber":25800000,
                    "txHash":"0x"+("a" if chain=="ethereum" else "b")*64,
                    "logIndex":0,"from":self.EVM_FROM,"to":self.EVM_TO,
                    "timestamp":T.isoformat(),"amount":"123000000",
                    "tokenAddress":contract,"tokenDecimals":6,
                    "tokenSymbol":"USDC"}],"link":{"next":"opaque"}}
            if url.endswith("/holders?limit=10"):
                return {"items":[{"chainId":chain_id,"address":self.EVM_FROM,
                                  "balance":"500000000"}],"link":{}}
            raise AssertionError(url)
        econ={"posizioni":[{},{}],"candidati":[]}
        raw=cap.collect(T,assets,econ,None,fetch)
        self.assertEqual(raw["target_totali"],2)
        self.assertEqual(raw["richieste_effettuate"],4)
        self.assertEqual([r["stato"] for r in raw["sonde"]],["OSSERVATO"]*2)
        read=cap.at_read(raw,assets,econ,T)
        for row,chain in zip(read["posizioni"],("ethereum","avalanche")):
            record=row["osservazioni"][0]
            self.assertEqual(record["rete"],chain)
            self.assertEqual(record["eventi"][0]["quantita"],"123")
            self.assertEqual(record["detentori"][0]["unita_minima"],"500000000")
            self.assertEqual(record["eventi"][0]["fonte"],
                cap._routescan_urls(chain,chains[chain][0])[0])
            self.assertIsNone(record["flussi_exchange_campione"]["flusso_netto_unita_minima"])
        self.assertEqual(read["posizioni"][1]["osservazioni"][0]["periodo"]["tipo"],
                         "PAGINA_ROUTESCAN")

    def test_routescan_wrong_contract_chain_and_unit_fail_closed(self):
        import kdd_capital_flow as cap
        contract="0x"+"5"*40
        for bad_field in ("tokenAddress","chainId","tokenDecimals","amount"):
            with self.subTest(bad_field=bad_field):
                row={"chainId":"1","blockNumber":123,
                     "txHash":"0x"+"a"*64,"logIndex":1,
                     "from":self.EVM_FROM,"to":self.EVM_TO,
                     "timestamp":T.isoformat(),"amount":"1000000",
                     "tokenAddress":contract,"tokenDecimals":6}
                row[bad_field]={"tokenAddress":"0x"+"9"*40,
                                "chainId":"43114","tokenDecimals":18,
                                "amount":"1.250"}[bad_field]
                def fetch(url,payload=None):
                    return {"items":[row],"link":{}}
                events,precision,source=cap._routescan_transfers(
                    "ethereum",contract,6,fetch)
                self.assertEqual(events,[])

    def test_bsc_new_candidate_binplorer_without_native_bnb_position(self):
        import kdd_capital_flow as cap
        contract=self.EVM_ADDR
        asset={"posizioni":[],"candidati":[{"token":"NEWBSC",
            "progetto_id":"unlisted-new-project","coppia_analisi":"NEWBSC/EUR",
            "contratti_indicizzati":[{"rete":"bsc","contratto":contract}]}],
            "fonti_native":{}}  # No BNB held; token still gets public evidence.
        seen=[]
        def fetch(url,payload=None):
            seen.append(url)
            if "/getTokenInfo/" in url:
                return {"address":contract,"decimals":"18","symbol":"NEWBSC"}
            if "/getTokenHistory/" in url:
                return {"operations":[{"timestamp":int(T.timestamp()),
                    "transactionHash":"0x"+"d"*64,
                    "tokenInfo":{"address":contract,"decimals":"18"},
                    "type":"transfer","value":"4000000000000000000",
                    "from":self.EVM_FROM,"to":self.EVM_TO}]}
            if "/getTopTokenHolders/" in url:
                return {"holders":[{"address":self.EVM_FROM,
                    "rawBalance":"8000000000000000000"}]}
            raise OSError("unexpected source")
        economics={"posizioni":[],"candidati":[{}]}
        raw=cap.collect(T,asset,economics,None,fetch)
        self.assertEqual(raw["target_totali"],1)
        self.assertEqual(raw["sonde"][0]["stato"],"OSSERVATO")
        self.assertEqual(raw["sonde"][0]["periodo"]["tipo"],"PAGINA_BINPLORER")
        self.assertEqual(raw["sonde"][0]["eventi"][0]["quantita"],"4")
        self.assertEqual(raw["sonde"][0]["detentori"][0]["unita_minima"],
                         "8000000000000000000")
        self.assertEqual(len(seen),3)
        read=cap.at_read(raw,asset,economics,T)
        obs=read["candidati"][0]["osservazioni"][0]
        self.assertEqual(obs["stato"],"OSSERVATO_CON_LIMITI")
        self.assertIsNone(obs["flussi_exchange_campione"]["ingresso_unita_minima"])
        self.assertEqual(obs["eventi"][0]["quantita"],"4")

    def test_sol_jupiter_index_when_largest_accounts_rpc_throttled(self):
        import kdd_capital_flow as cap
        mint=self.MINT
        asset={"posizioni":[],"candidati":[{"token":"FUTURE",
            "progetto_id":"future-sol-token","coppia_analisi":"FUTURE/EUR",
            "contratti_indicizzati":[{"rete":"solana","contratto":mint}]}],
            "fonti_native":{}}
        def fetch(url,payload=None):
            if url==evidence.CONTRACT_ENDPOINTS["solana"] and payload:
                self.assertEqual(payload["method"],"getTokenLargestAccounts")
                raise OSError("public RPC HTTP 429")
            if url==cap.JUPITER_TOKENS+mint:
                return [{"id":mint,"decimals":6,"holderCount":5000,
                         "audit":{"topHoldersPercentage":12.4}}]
            raise OSError("unexpected source")
        econ={"posizioni":[],"candidati":[{}]}
        raw=cap.collect(T,asset,econ,None,fetch)
        self.assertEqual(raw["sonde"][0]["stato"],"OSSERVATO")
        self.assertEqual(raw["sonde"][0]["eventi"],[])
        self.assertEqual(raw["sonde"][0]["detentori"],[])
        recent=cap.at_read(raw,asset,econ,T)["candidati"][0]["osservazioni"][0]
        agg=recent["aggregato_detentori"]
        self.assertEqual(agg["numero_account"],5000)
        self.assertEqual(agg["quota_top_pct_indice"],"12.4")
        self.assertEqual(agg["stato_alla_lettura"],"RECENTE")
        self.assertEqual(recent["periodo"]["tipo"],"RIEPILOGO_JUPITER_TOKEN")
        late=cap.at_read(raw,asset,econ,T+dt.timedelta(minutes=40))
        self.assertEqual(late["candidati"][0]["osservazioni"][0]
                         ["aggregato_detentori"]["stato_alla_lettura"],"STORICO")
        def wrong_mint(url,payload=None):
            if url==evidence.CONTRACT_ENDPOINTS["solana"]:
                raise OSError("HTTP 429")
            return [{"id":"WRONG","decimals":6,"holderCount":5000}]
        bad=cap.collect(T,asset,econ,None,wrong_mint)
        self.assertEqual(bad["sonde"][0]["stato"],"NON_DISPONIBILE")

    def test_entirely_replaced_ten_asset_kraken_wallet_multichain_packet_gpt(self):
        """No original holding: dynamic Kraken pairs, four index networks, fallbacks.
        Kraken prices below are fixtures; all chain responses are invented.
        """
        import kdd_economics as econ
        import kdd_capital_flow as cap
        import mercati_spot as spot
        import decision_desk as desk
        from scripts import kdd_wallet_packet_g0 as packet
        from scripts import kdd_bridge_g2 as bridge
        from scripts import test_kdd_wallet_packet_g0 as packet_fixture
        tokens=["LIGHTER","AAVE","AVAX","BONK","LINK","UNI","USDC","PEPE","ONDO","PUMP"]
        original={"BTC","ETH","SOL","SUI","NEAR","JUP","RENDER","FET","BNB","XRP"}
        self.assertFalse(original.intersection(tokens))
        evm=lambda n:"0x"+format(n,"040x")
        platforms={
            "AAVE":{"ethereum":evm(11)},
            "BONK":{"solana":"B"*32},
            "LINK":{"ethereum":evm(12)},
            "UNI":{"ethereum":evm(13)},
            "USDC":{"ethereum":evm(14),"binance-smart-chain":evm(15),
                    "avalanche":evm(16)},
            "PEPE":{"ethereum":evm(17)},
            "ONDO":{"ethereum":evm(18)},
            "PUMP":{"solana":"C"*32},
            "CAKE":{"binance-smart-chain":evm(19)}}
        catalog={}
        for token in tokens+["CAKE"]:
            q="USD" if token=="LIGHTER" else "EUR"
            catalog[token+q]={"pair_key":token+q,"pair":token+"/"+q,
                                   "base":token,"quote":q}
        def identity(token):
            coin_id=token.lower()+"-synthetic-project"
            quote="USD" if token=="LIGHTER" else "EUR"
            discovered={"metodo":"KRAKEN_COINGECKO_MARKET",
                        "coingecko_id":coin_id,"progetto":token+" Synthetic",
                        "prova_mercato":{"exchange":"kraken","symbol":token,
                           "base":token,"target":quote,"is_stale":False,
                           "is_anomaly":False,
                           "ricerca_url":econ.CG_SEARCH+token,
                           "ticker_url":econ.CG+coin_id+"/tickers?exchange_ids=kraken",
                           "verificato_utc":T.isoformat()}}
            return econ.identify(token,token+"/"+quote,token+quote,
                                 catalog=catalog,discovered=discovered)
        def row(token,i,candidate=False):
            ident=identity(token)
            self.assertEqual(ident["stato"],"IDENTITA_VERIFICATA_DA_CATALOGO")
            payload={"id":ident["coingecko_id"],"symbol":token.lower(),
                     "name":ident["progetto"],"platforms":platforms.get(token,{})}
            result={"indice":i,"token":token,"identita":ident,
                    "network_metadata":evidence.coin_network_metadata(ident,payload,T),
                    "fondamentali":econ.fundamentals(ident,None,T,T),
                    "evento":econ.release_event(ident,None,T,T)}
            if candidate:
                result["coppia_analisi"]=token+"/EUR"
            return result
        economic={"schema":econ.VERSION,"acquisito_utc":T.isoformat(),
                  "posizioni":[row(t,i) for i,t in enumerate(tokens)],
                  "candidati":[row("CAKE",0,True)],
                  "regime":{"stato":"INDETERMINATO","qualita":"PARZIALE"},
                  "fonti_economiche":econ.sources_matrix(),
                  "macro":econ.macro([],T)}
        positions=[{"token":t} for t in tokens]
        candidates=[{"token":"CAKE","coppia_analisi":"CAKE/EUR"}]
        def fetch(url,payload=None):
            if url in evidence.SOURCES.values():
                if url==evidence.SOL_URL and payload and payload.get("method")!="getSupply":
                    raise OSError("public Solana RPC 429")
                return fake_fetch(url,payload)
            if url==evidence.CONTRACT_ENDPOINTS["solana"]:
                raise OSError("public Solana RPC 429")
            if url in (evidence.CONTRACT_ENDPOINTS["bsc"],evidence.CONTRACT_ENDPOINTS["ethereum"]):
                if payload["method"]=="eth_getCode":
                    return {"id":1,"result":"0x608060"}
                if payload["method"]=="eth_call":
                    return {"id":1,"result":"0x18"}
                raise OSError("block head deliberately not acquired")
            if url.startswith(cap.ROUTESCAN):
                number=url[len(cap.ROUTESCAN):].split("/")[0]
                if "erc20-transfers?" in url:
                    contract=url.split("tokenAddress=",1)[1].split("&",1)[0]
                    return {"items":[{"chainId":number,"tokenAddress":contract,
                          "txHash":"0x"+"d"*64,"logIndex":0,"blockNumber":999,
                          "from":self.EVM_FROM,"to":self.EVM_TO,
                          "amount":"7000000","tokenDecimals":6,
                          "timestamp":T.isoformat()}]}
                if "/holders?" in url:
                    return {"items":[{"chainId":number,"address":self.EVM_FROM,
                                      "balance":"28000000"}]}
                raise AssertionError(url)
            if url.startswith(cap.BINPLORER):
                contract=url.split("?",1)[0].split("/")[-1]
                if "/getTokenInfo/" in url:
                    return {"address":contract,"decimals":"18"}
                if "/getTokenHistory/" in url:
                    return {"operations":[{"tokenInfo":{"address":contract,"decimals":"18"},
                         "timestamp":int(T.timestamp()),"transactionHash":"0x"+"b"*64,
                         "from":self.EVM_FROM,"to":self.EVM_TO,
                         "type":"transfer","value":"3000000000000000000"}]}
                if "/getTopTokenHolders/" in url:
                    return {"holders":[{"address":self.EVM_FROM,
                                        "rawBalance":"4000000000000000000"}]}
            if url.startswith(cap.JUPITER_TOKENS):
                mint=url[len(cap.JUPITER_TOKENS):]
                return [{"id":mint,"decimals":6,"holderCount":2345,
                        "audit":{"topHoldersPercentage":18.5}}]
            raise OSError("unsupported public source")
        previous=None
        observed=set()
        final=None
        for minute in range(4):
            instant=T+dt.timedelta(minutes=minute)
            # Economic metadata is still valid; no new wallet quantities are
            # ever sent to a public provider by these calls.
            current=evidence.collect(instant,positions,candidates,fetch=fetch,
                                      economics=economic,previous=previous)
            self.assertLessEqual(current["asset_reti"]["flussi_capitale"]["richieste_effettuate"],15)
            reader=evidence.at_read(current,positions,candidates,instant,economics=economic)
            for source in current["asset_reti"]["flussi_capitale"]["sonde"]:
                if source["stato"]=="OSSERVATO":
                    observed.add((source["rete"],source["asset_tecnico"]))
            previous=current
            final=(current,reader)
        self.assertGreaterEqual(len(observed),8)
        self.assertTrue(any(chain=="avalanche" for chain,_ in observed))
        self.assertTrue(any(chain=="bsc" for chain,_ in observed))
        self.assertTrue(any(chain=="solana" for chain,_ in observed))
        self.assertTrue(any(chain=="ethereum" for chain,_ in observed))
        self.assertEqual(len(final[1]["asset_reti"]["flussi_capitale"]["posizioni"]),10)
        self.assertEqual(len(final[1]["asset_reti"]["flussi_capitale"]["candidati"]),1)
        # Exit and re-entry: obsolete contracts disappear from target selection,
        # without erasing the possibility of later public re-observation.
        all_rows=final[1]["asset_reti"]
        without_aave={"posizioni":[r for r in all_rows["posizioni"] if r["token"]!="AAVE"],
                      "candidati":all_rows["candidati"],"fonti_native":{}}
        departed=cap.collect(T+dt.timedelta(minutes=4),without_aave,
                             {"posizioni":[{}]*9,"candidati":[{}]},
                             final[0]["asset_reti"]["flussi_capitale"],fetch)
        self.assertNotIn(("ethereum",platforms["AAVE"]["ethereum"]),
                         cap._targets(without_aave))
        self.assertEqual(departed["target_totali"],
                         final[0]["asset_reti"]["flussi_capitale"]["target_totali"]-1)
        returned=cap.collect(T+dt.timedelta(minutes=5),all_rows,
                             {"posizioni":[{}]*10,"candidati":[{}]},
                             departed,fetch)
        self.assertIn(("ethereum",platforms["AAVE"]["ethereum"]),
                      cap._targets(all_rows))
        self.assertEqual(returned["target_totali"],
                         final[0]["asset_reti"]["flussi_capitale"]["target_totali"])
        for r in final[1]["asset_reti"]["flussi_capitale"]["posizioni"]:
            self.assertEqual(r["contratto_ufficiale"],"NON_ATTESTATO")

        fixture=packet_fixture.WalletPacketG0Tests("test_asset_weights_never_rebrand_partial_total_as_entire_wallet")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.portfolio["posizioni"]=[
            {"token":token,"quantita":"1","disponibile_spot":"1",
             "costo_medio_eur":None} for token in tokens]
        fixture.snapshot["rilevazione_utc"]=(T+dt.timedelta(minutes=3)).isoformat()
        # LIGHTER/USD was confirmed in real public Kraken AssetPairs+Ticker
        # on 14 Nov 2026 (Actions #43622245482); no LIGHTER/EUR was listed.
        # Test the actual reusable assemble + FX path, not a made-up EUR pair.
        fx_pairs={"ZEURZUSD":{"wsname":"EUR/USD","status":"online"}}
        fx_ticks={"ZEURZUSD":{"a":["1.1"],"b":["1.1"],"c":["1.1"],
                             "o":"1.1","v":["100","100"]}}
        fx_pairs["LIGHTERUSD"]={"wsname":"LIGHTER/USD","status":"online"}
        fx_ticks["LIGHTERUSD"]={"a":["11.0"],"b":["11.0"],"c":["11.0"],
                               "o":"11.0","v":["100000","100000"]}
        multi,rates=spot.assemble(fx_pairs,fx_ticks)
        self.assertEqual(multi["LIGHTER"]["quote"],"USD")
        self.assertEqual(multi["LIGHTER"]["conversione_fonte"],"EUR/USD")
        self.assertEqual(multi["LIGHTER"]["prezzo_eur"],10.0)
        fixture.snapshot["fx_rilevati"]=rates
        old_eur={token:{"token":token,"pair":token+"/EUR",
             "pair_key":token+"EUR","prezzo_eur":10.0,"volume_24h_eur_stimato":1000000.0,
             "spread_pct":0.4} for token in tokens if token!="LIGHTER"}
        fixture.snapshot["markets"]=desk.wallet_spot_markets(old_eur,multi,fixture.portfolio)
        self.assertEqual(fixture.snapshot["markets"]["LIGHTER"]["pair"],"LIGHTER/USD")
        fixture.snapshot["schede_v02"]=[{"token":"CAKE","coppia_analisi":"CAKE/EUR",
                                        "esito":"RIESAME","categoria":"confronto"}]
        fixture.report["rilevazione_utc"]=fixture.snapshot["rilevazione_utc"]
        fixture.report["posizioni"]=[{"token":token,"quantita":"1",
            "prezzo_eur":fixture.snapshot["markets"][token]["prezzo_eur"],
            "valore_eur":fixture.snapshot["markets"][token]["prezzo_eur"],
            "pl_non_realizzato_eur":None,"decisione":"ESAME"}
            for token in tokens]
        fixture.report["totale_stimato_eur"]=100
        fixture.report["totale_parziale"]=False
        fixture.report["stato_totale"]="COMPLETO"
        instant=T+dt.timedelta(minutes=3)
        iso=instant.isoformat()
        fixture.portfolio["data_ora_saldo_privato_utc"]=iso
        fixture.portfolio["fonte_quantita"]="Kraken BalanceEx API privata SOLA LETTURA, "+iso
        fixture.dossier["kraken_istantanea_utc"]=iso
        fixture.dossier["candidati"]=[{"token":"CAKE","coppia_analisi":"CAKE/EUR"}]
        fixture.dossier["evidenze_economiche"]=economic
        fixture.dossier["evidenze_rete_defi"]=final[0]
        fixture.dump()
        prepared=packet.build(fixture.root,now=instant)
        self.assertEqual([r["token"] for r in prepared["patrimonio"]["posizioni"]],tokens)
        for position in prepared["patrimonio"]["posizioni"]:
            spot=position["mercato_spot_kraken"]
            expected="LIGHTER/USD" if position["token"]=="LIGHTER" else position["token"]+"/EUR"
            self.assertEqual(spot["coppia"],expected)
            if position["token"]=="LIGHTER":
                self.assertEqual(spot["valuta_quotazione"],"USD")
                self.assertEqual(spot["conversione_fonte"],"EUR/USD")
                self.assertEqual(position["fonte_prezzo_eur"]["prezzo_quote"],"11.0")
            else:
                self.assertEqual(spot["volume_24h_eur_stimato"],"1000000.0")
            self.assertEqual(spot["spread_pct"],"0.0" if position["token"]=="LIGHTER" else "0.4")
            self.assertEqual(spot["book"],"NON_ACQUISITO_PER_QUESTA_COPPIA")
        self.assertEqual(len(prepared["evidenze_multifonte"]["rete_defi"]
                             ["asset_reti"]["flussi_capitale"]["posizioni"]),10)
        bundle={"schema":bridge.SCHEMA_BUNDLE,"packet":prepared,
                "packet_sha256":bridge.digest(prepared),"preparato_utc":iso}
        result=bridge.read_context(json.loads(json.dumps(bundle)),now=instant)
        flow=result["rete_defi_alla_lettura"]["asset_reti"]["flussi_capitale"]
        self.assertEqual([r["token"] for r in flow["posizioni"]],tokens)
        self.assertEqual(flow["candidati"][0]["token"],"CAKE")
        self.assertTrue(all(r["mercato_spot_kraken_alla_lettura"]["stato"] ==
                            "DISPONIBILE"
                            for r in result["copertura"]))
        lighter=next(x for x in result["copertura"] if x["token"]=="LIGHTER")
        self.assertEqual(lighter["mercato_spot_kraken_alla_lettura"]["coppia"],"LIGHTER/USD")
        self.assertEqual(lighter["mercato_spot_kraken_alla_lettura"]["valuta_quotazione"],"USD")
        self.assertEqual(lighter["mercato_spot_kraken_alla_lettura"]["conversione_fonte"],"EUR/USD")
        self.assertTrue(all(r["mercato_spot_kraken_alla_lettura"]["volume_24h_eur_stimato"]
                            == "1000000.0" for r in result["copertura"]
                            if r["token"]!="LIGHTER"))
        tampered=copy.deepcopy(bundle)
        tampered["packet"]["patrimonio"]["posizioni"][0]["mercato_spot_kraken"]["pair_key"]="FAKEPAIR"
        tampered["packet_sha256"]=bridge.digest(tampered["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(tampered,now=instant)
        badfx=copy.deepcopy(bundle)
        lighter_row=badfx["packet"]["patrimonio"]["posizioni"][0]
        lighter_row["mercato_spot_kraken"]["eur_per_quote"]="1"
        badfx["packet_sha256"]=bridge.digest(badfx["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(badfx,now=instant)
        missing_fx=copy.deepcopy(fixture.snapshot)
        missing_fx["fx_rilevati"].pop("USD")
        # A price already derived from an absent FX rate cannot be endorsed.
        with self.assertRaises(packet.PacketError):
            packet.brief_positions(fixture.portfolio,fixture.report,missing_fx,
                                   fixture.dossier,True,
                                   four_rows=packet.four_tf_evidence(
                                      fixture.portfolio,fixture.report,fixture.dossier,
                                      fixture.snapshot["rilevazione_utc"]),now=instant)
        self.assertTrue(any(s["stato"]=="OSSERVATO_CON_LIMITI"
                            for r in flow["posizioni"] for s in r["osservazioni"]))
        self.assertTrue(all(r["token"] in fixture.snapshot["markets"]
                            for r in flow["posizioni"]))

    def test_dynamic_candidate_rotation_and_missing_attribution(self):
        import kdd_capital_flow as cap
        assets = {"posizioni": [],"candidati":[
          {"token":"NEW","progetto_id":"new_project","coppia_analisi":"NEW/EUR",
           "contratti_indicizzati":[{"rete":"ethereum","contratto":self.EVM_ADDR}]},
          {"token":"OTH","progetto_id":"other_project","coppia_analisi":"OTH/EUR",
           "contratti_indicizzati":[{"rete":"solana","contratto":self.MINT}]}],
          "fonti_native":{"ethereum":{"valori":{"altezza_blocco":1000}}}}
        def down(url,payload=None):
            raise OSError("offline")
        raw=cap.collect(T,assets,{"posizioni":[],"candidati":[{},{}]},None,down)
        self.assertEqual(len(raw["sonde"]),2)
        read=cap.at_read(raw,assets,{"posizioni":[],"candidati":[{},{}]},T)
        self.assertEqual([x["token"] for x in read["candidati"]],["NEW","OTH"])
        self.assertTrue(all(x["osservazioni"][0]["stato"]=="NON_DISPONIBILE"
                            for x in read["candidati"]))


if __name__=="__main__":
    unittest.main()
