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
                     "candidati":[econ_row("SUI",0,candidate=True)],
                     "regime":{"stato":"INDETERMINATO","qualita":"PARZIALE"},
                     "fonti_economiche":econ.sources_matrix(),
                     "macro":econ.macro([],moment)}
        fixture.dossier["evidenze_economiche"] = economics
        fixture.dossier["evidenze_rete_defi"]=evidence.collect(
            moment,rows,shortlist,fetch=fake_fetch,economics=economics)
        fixture.dump()
        p=packet.build(fixture.root,now=moment)
        self.assertEqual(len(p["patrimonio"]["posizioni"]),3)
        network=p["evidenze_multifonte"]["rete_defi"]
        self.assertEqual(len(network["posizioni"]),3)
        self.assertEqual(len(network["candidati"]),1)
        self.assertEqual(network["asset_reti"]["posizioni"][0]["tipo"],"NATIVO")
        self.assertEqual(network["asset_reti"]["posizioni"][2]["tipo"],"NON_VERIFICATO")
        bundle={"schema":bridge.SCHEMA_BUNDLE,"packet":p,
                "packet_sha256":bridge.digest(p),"preparato_utc":iso}
        reading=bridge.read_context(json.loads(json.dumps(bundle)),now=moment)
        self.assertEqual(reading["rete_defi_alla_lettura"]["posizioni"][0]
                         ["onchain"]["stato"],"OSSERVATO_CON_LIMITI")
        self.assertEqual(reading["rete_defi_alla_lettura"]["asset_reti"]["posizioni"][1]
                         ["tipo"],"NATIVO")
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
            return {"jsonrpc": "2.0", "id": 1, "result": {
                "status": "success", "ledger_index": 100000000,
                "ledger": {"close_time_iso": T.isoformat(),
                           "ledger_hash": "C" * 64}}}
        raise AssertionError("unexpected public request: " + url)

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
        self.assertIn("NON chain del saldo", details["limite"].replace("Contratti da aggregatore e RPC pubblici, non prova che Kraken custodisca sulla stessa rete", "NON chain del saldo"))
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


if __name__=="__main__":
    unittest.main()
