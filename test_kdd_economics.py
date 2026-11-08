"""Synthetic economic evidence tests: no private wallet, no network."""
import copy
import datetime as dt
import unittest
import kdd_economics as e

T=dt.datetime(2026,11,8,13,30,tzinfo=dt.timezone.utc)


class EconomicEvidenceTests(unittest.TestCase):
    def catalog(self, token="BTC", pair=None, key=None):
        pair = pair or token+"/EUR"
        key = key or token+"EUR"
        base, quote = pair.split("/")
        return {key: {"pair_key": key, "pair": pair,
                      "base": base, "quote": quote}}

    def ident(self, token="BTC"):
        return e.identify(token,token+"/EUR",token+"EUR",
                          catalog=self.catalog(token))

    def market(self, ident=None, max_supply=21000000):
        ident=ident or self.ident()
        return {"id":ident["coingecko_id"],"symbol":ident["token"].lower(),
                "name":ident["progetto"],"market_data":{
                    "last_updated":T.isoformat(),"market_cap":{"usd":100},
                    "fully_diluted_valuation":{"usd":200},
                    "circulating_supply":10,"total_supply":20,
                    "max_supply":max_supply}}

    def test_real_wallet_and_shortlist_project_registry_is_curated(self):
        # Identity pairs reproduced from a 10-position/4-candidate schema.
        expected = {
            "BNB": ("binancecoin", "BNB"),
            "FET": ("fetch-ai", "Artificial Superintelligence Alliance"),
            "JUP": ("jupiter-exchange-solana", "Jupiter"),
            "RENDER": ("render-token", "Render"),
            "PEPE": ("pepe", "Pepe"),
            "PUMP": ("pump-fun", "Pump.fun"),
        }
        for token, (coin_id, name) in expected.items():
            with self.subTest(token=token):
                identity = self.ident(token)
                self.assertEqual(identity["stato"], "IDENTITA_VERIFICATA_DA_CATALOGO")
                self.assertEqual((identity["coingecko_id"], identity["progetto"]),
                                 (coin_id, name))
                self.assertEqual(e.fundamentals(identity, self.market(identity), T, T)
                                 ["stato"], "VERIFICATO")
                forged = self.market(identity)
                forged["name"] = "Wrapped " + name
                self.assertEqual(e.fundamentals(identity, forged, T, T)
                                 ["stato"], "NON_VERIFICATO")
                self.assertEqual(e.identify(token, token+"/EUR", "BOGUS",
                                            catalog=self.catalog(token))["stato"],
                                 "NON_VERIFICATO")
        self.assertIn("ASI", self.ident("FET")["limite"])
        self.assertIn("RNDR", self.ident("RENDER")["limite"])
        self.assertEqual(self.ident("USELESS")["stato"], "NON_VERIFICATO")
        self.assertEqual(e.identify("RENDER", "RNDR/EUR", "RENDEREUR",
                                    catalog=self.catalog("RENDER"))["stato"],
                         "NON_VERIFICATO")

    def test_real_roster_three_bounded_refreshes_recover_external_failures(self):
        import json
        import dossier_trade as producer
        from unittest import mock
        tokens = ["BNB", "FET", "JUP", "NEAR", "RENDER", "SOL", "SUI",
                  "ETH", "BTC", "XRP"]
        shortlist = ["USELESS", "PEPE", "PUMP", "BNB"]
        pairs = {t+"EUR": {"wsname": t+"/EUR", "status": "online"}
                 for t in tokens}
        pairs.update({t+"USD": {"wsname": t+"/USD", "status": "online"}
                      for t in shortlist})
        wallet = {"posizioni": [{"token": t} for t in tokens]}
        four = {"posizioni": [{"token": t, "coppia": t+"/EUR",
                               "pair_key": t+"EUR"}
                              for t in tokens]}
        candidates = [{"token": t, "coppia_analisi": t+"/USD",
                       "kraken_pair_key": t+"USD"} for t in shortlist]
        phase = [0]

        def public_source(url, timeout=12):
            if "/releases/latest" in url:
                repo = url.split("/repos/")[1].split("/releases/")[0]
                return json.dumps({"html_url": "https://github.com/" + repo +
                                   "/releases/tag/v1", "name": "Release v1",
                                   "published_at": T.isoformat()}).encode()
            coin_id = url.split("/coins/")[1].split("?")[0]
            if phase[0] == 0 and coin_id in ("bitcoin", "fetch-ai"):
                raise OSError("Simulated public source outage")
            token = next(t for t, v in e.PROJECTS.items() if v[0] == coin_id)
            return json.dumps(self.market(self.ident(token))).encode()

        outputs = []
        with mock.patch.object(producer.desk, "request", side_effect=public_source), \\
             mock.patch.object(producer.time, "sleep"):
            previous = None
            for iteration in range(3):
                phase[0] = iteration
                result = producer.economic_evidence(
                    {"feed": []}, wallet, four, candidates,
                    T + dt.timedelta(minutes=iteration), asset_pairs=pairs,
                    previous=previous)
                outputs.append(result)
                previous = result
        for output in outputs:
            self.assertEqual(len(output["posizioni"]), 10)
            self.assertEqual(len(output["candidati"]), 4)
            self.assertEqual(sum(x["identita"]["stato"] ==
                                 "IDENTITA_VERIFICATA_DA_CATALOGO"
                                 for x in output["posizioni"]), 10)
            self.assertLessEqual(output["richieste_effettuate"], 9)
        first, second, third = outputs
        self.assertEqual(sum(x["fondamentali"]["stato"] == "VERIFICATO"
                             for x in first["posizioni"]), 4)
        self.assertEqual(sum(x["fondamentali"]["stato"] == "VERIFICATO"
                             for x in second["posizioni"]), 8)
        self.assertEqual(sum(x["fondamentali"]["stato"] == "VERIFICATO"
                             for x in third["posizioni"]), 10)
        self.assertEqual([x["fondamentali"]["stato"]
                          for x in third["candidati"]],
                         ["NON_VERIFICATO_IDENTITA", "VERIFICATO",
                          "VERIFICATO", "VERIFICATO"])
        self.assertEqual(
            next(x for x in first["posizioni"] if x["token"] == "FET")
            ["fondamentali"]["motivo"], "ERRORE_OSError")

    def test_coin_gecko_429_stops_bounded_requests_without_faking_data(self):
        import urllib.error
        import dossier_trade as producer
        from unittest import mock
        tokens = ["BNB", "BTC"]
        wallet = {"posizioni": [{"token": t} for t in tokens]}
        four = {"posizioni": [{"token": t, "coppia": t+"/EUR",
                               "pair_key": t+"EUR"} for t in tokens]}
        pairs = {t+"EUR": {"status": "online", "wsname": t+"/EUR"}
                 for t in tokens}
        called = []

        def denied(url, timeout=12):
            if "/releases/latest" in url:
                raise OSError("release unavailable")
            called.append(url)
            raise urllib.error.HTTPError(url, 429, "rate limited", {}, None)

        with mock.patch.object(producer.desk, "request", side_effect=denied), \\
             mock.patch.object(producer.time, "sleep"):
            result = producer.economic_evidence(
                {"feed": []}, wallet, four, [], T, asset_pairs=pairs)
        self.assertEqual(len(called), 1)
        self.assertEqual(result["richieste_coingecko"], 1)
        self.assertEqual([r["fondamentali"]["stato"]
                          for r in result["posizioni"]],
                         ["NON_DISPONIBILE_FONTE"] * 2)
        self.assertEqual([r["fondamentali"]["motivo"]
                          for r in result["posizioni"]],
                         ["HTTP_429", "RINVIATO_RATE_LIMIT_HTTP_429"])

    def test_identity_requires_verified_catalog_pair_and_curated_mapping(self):
        self.assertEqual(self.ident()["stato"],"IDENTITA_VERIFICATA_DA_CATALOGO")
        self.assertEqual(e.identify("BTC","XBT/EUR","XXBTZEUR",
                                    catalog=self.catalog("BTC","XBT/EUR","XXBTZEUR"))["coingecko_id"],"bitcoin")
        for ident in (
            e.identify("BTC","BTC/EUR","BTCEUR",catalog={}),
            e.identify("BTC","ETH/EUR","BTCEUR",catalog=self.catalog("BTC")),
            e.identify("BTC","BTC/EUR",None,catalog=self.catalog("BTC")),
            e.identify("FAKE","FAKE/EUR","FAKEEUR",catalog=self.catalog("FAKE")),
            e.identify("BTC","BTC/EUR","NONEXISTENT-KRAKEN-PAIR",catalog=self.catalog("BTC")),
            e.identify("ADA","ADA/EUR","ANOTHER_PROJECT",catalog=self.catalog("ADA")),
            e.identify("BTC","BTC/EUR","BTCEUR",catalog=self.catalog("ETH")),
        ):
            self.assertEqual(ident["stato"],"NON_VERIFICATO")
            self.assertNotIn("coingecko_id",ident)

    def test_migrated_or_collision_source_cannot_inherit_fundamentals(self):
        ident=self.ident()
        forged=self.market()
        forged["id"]="bitcoin-old"
        self.assertEqual(e.fundamentals(ident,forged,T,T)["stato"],"NON_VERIFICATO")
        forged=self.market()
        forged["name"]="Bitcoin Wrapped"
        self.assertEqual(e.fundamentals(ident,forged,T,T)["stato"],"NON_VERIFICATO")

    def test_supply_without_max_never_invents_unlock(self):
        result=e.fundamentals(self.ident(),self.market(max_supply=None),T,T)
        self.assertEqual(result["stato"],"VERIFICATO")
        self.assertEqual(result["diluizione"],"MAX_NON_DICHIARATO_NON_EQUIVALE_A_ILLIMITATO")
        self.assertEqual(result["unlock"],"NON_VERIFICATO")
        self.assertEqual(result["rapporto_fdv_cap"],2)

    def test_zero_max_is_not_unlimited(self):
        result=e.fundamentals(self.ident(),self.market(max_supply=0),T,T)
        self.assertEqual(result["diluizione"],"MAX_ZERO_DATO_ANOMALO")

    def test_old_fundamentals_stale(self):
        data=self.market()
        data["market_data"]["last_updated"]=(T-dt.timedelta(days=2)).isoformat()
        self.assertEqual(e.fundamentals(self.ident(),data,T,T)["stato"],"SCADUTO")

    def test_release_requires_official_repository_and_time(self):
        release={"html_url":"https://github.com/bitcoin/bitcoin/releases/tag/v30.0",
                 "name":"Bitcoin Core v30.0","published_at":T.isoformat()}
        self.assertEqual(e.release_event(self.ident(),release,T,T)["stato"],"VERIFICATO")
        release["html_url"]="https://github.com/random/bitcoin/releases/tag/v30.0"
        self.assertEqual(e.release_event(self.ident(),release,T,T)["stato"],"NON_VERIFICATO")

    def test_rss_ticker_collision_is_not_token_event(self):
        feed=[{"fonte":"Fed — politica monetaria",
               "link":"https://www.federalreserve.gov/newsevents/pressreleases/monetary20261108a.htm",
               "titolo":"SOL outlook", "data":T.isoformat()}]
        macro=e.macro(feed,T)
        self.assertEqual(macro["fonti_ufficiali"][0]["impatto_asset"],"NON_VALUTABILE")
        self.assertEqual(e.release_event(self.ident("SOL"),feed[0],T,T)["stato"],"NON_VERIFICATO")

    def test_regime_contradiction_and_stale_4tf(self):
        frames={label:{"stato":"AGGIORNATO","figure_candlestick":{
            "stato":"AGGIORNATO","trend_precedente":"SALITA"}}
            for label in ("4H","1D")}
        glob={"aggiornato_sorgente_utc":T.timestamp(),"var_capitalizzazione_24h_pct":-1}
        self.assertEqual(e.regime({"timeframe":frames},glob,T)["stato"],"TRANSIZIONE")
        glob["var_capitalizzazione_24h_pct"]=2
        self.assertEqual(e.regime({"timeframe":frames},glob,T)["stato"],"RIALZISTA")
        frames["4H"]["stato"]="SCADUTO"
        self.assertEqual(e.regime({"timeframe":frames},glob,T)["stato"],"INDETERMINATO")

    def sample(self):
        positions=[{"token":"BTC"},{"token":"SOL"}]
        shortlist=[{"token":"ADA","coppia_analisi":"ADA/EUR"}]
        rows=[]
        for i,token in enumerate(("BTC","SOL")):
            ident=self.ident(token)
            rows.append({"indice":i,"token":token,"identita":ident,
                         "fondamentali":e.fundamentals(ident,self.market(ident),T,T),
                         "evento":e.release_event(ident,None,T,T)})
        ident=self.ident("ADA")
        candidate={"indice":0,"token":"ADA","coppia_analisi":"ADA/EUR",
                   "identita":ident,"fondamentali":e.fundamentals(ident,self.market(ident),T,T),
                   "evento":e.release_event(ident,None,T,T)}
        source={"schema":e.VERSION,"acquisito_utc":T.isoformat(),
                "posizioni":rows,"candidati":[candidate],
                "regime":{"stato":"RIALZISTA","qualita":"PARZIALE"},
                "macro":e.macro([],T)}
        return source,positions,shortlist

    def test_all_assets_remain_even_when_missing(self):
        source,positions,shortlist=self.sample()
        source["posizioni"][1]["fondamentali"]=e.fundamentals({},None,T,T)
        result=e.at_read(source,positions,shortlist,T)
        self.assertEqual(len(result["posizioni"]),2)
        self.assertEqual(len(result["candidati"]),1)
        self.assertEqual(result["posizioni"][1]["fondamentali"]["stato"],"NON_VERIFICATO")

    def test_later_read_degrades_economic_evidence(self):
        source,positions,shortlist=self.sample()
        result=e.at_read(source,positions,shortlist,T+dt.timedelta(days=3))
        self.assertEqual(result["posizioni"][0]["fondamentali"]["stato"],"SCADUTO")
        self.assertEqual(result["regime"]["stato"],"INDETERMINATO")
        self.assertEqual(result["regime"]["qualita"],"SCADUTO")

    def test_packet_identity_tamper_stops(self):
        source,positions,shortlist=self.sample()
        source["candidati"][0]["token"]="BTC"
        with self.assertRaises(ValueError):
            e.at_read(source,positions,shortlist,T)

    def test_coingecko_identity_tamper_stops(self):
        source,positions,shortlist=self.sample()
        source["posizioni"][0]["identita"]["coingecko_id"]="cardano"
        with self.assertRaises(ValueError):
            e.at_read(source,positions,shortlist,T)

    def test_real_producer_synthetic_ten_holdings_and_candidate(self):
        import json
        import dossier_trade as producer
        from unittest import mock
        tokens=["BTC","SOL","ETH","NEAR","SUI","XRP","ONDO","ADA","KAS","SXT"]
        portfolio={"posizioni":[{"token":t} for t in tokens]}
        four={"posizioni":[{"token":t,"coppia":t+"/EUR",
                             "pair_key":t+"EUR","asset_base":t}
                            for t in tokens]}
        candidate=[{"token":"ADA","coppia_analisi":"ADA/EUR",
                    "kraken_pair_key":"ADAEUR"}]
        def fake(url, timeout=12):
            if "/releases/latest" in url:
                repo=url.split("/repos/")[1].split("/releases/")[0]
                return json.dumps({"html_url":"https://github.com/"+repo+"/releases/tag/v1",
                                   "published_at":T.isoformat(),"name":"Release v1"}).encode()
            cg=url.split("/coins/")[1].split("?")[0]
            token=next((t for t,x in e.PROJECTS.items() if x[0]==cg),None)
            if token is None:
                raise ValueError("unknown project")
            return json.dumps(self.market(self.ident(token))).encode()
        asset_pairs={t+"EUR": {"wsname":t+"/EUR","status":"online"}
                     for t in tokens}
        with mock.patch.object(producer.desk,"request",side_effect=fake), \
             mock.patch.object(producer.time,"sleep"):
            result=producer.economic_evidence(
                {"feed":[]}, portfolio, four, candidate, T, asset_pairs=asset_pairs)
        self.assertEqual(len(result["posizioni"]),10)
        self.assertEqual(len(result["candidati"]),1)
        self.assertEqual(result["candidati"][0]["fondamentali"]["stato"],"VERIFICATO")
        self.assertEqual(result["posizioni"][0]["fondamentali"]["stato"],"VERIFICATO")
        self.assertEqual(result["posizioni"][9]["identita"]["stato"],"NON_VERIFICATO")
        self.assertLessEqual(result["richieste_effettuate"],9)


    def test_budget_rotation_cache_and_source_states_across_two_acquisitions(self):
        import json
        import dossier_trade as producer
        from unittest import mock
        tokens=["BTC","SOL","ETH","NEAR","SUI","XRP","ONDO","ADA","KAS","ICNT"]
        portfolio={"posizioni":[{"token":t} for t in tokens]}
        pairs={t+"EUR":{"status":"online","wsname":t+"/EUR"} for t in tokens}
        four={"posizioni":[{"token":t,"coppia":t+"/EUR",
                             "pair_key":t+"EUR","asset_base":t}
                            for t in tokens]}
        candidate=[{"token":"ADA","coppia_analisi":"ADA/EUR",
                    "kraken_pair_key":"ADAEUR"}]

        def response(url, timeout=12):
            if "/releases/latest" in url:
                repo=url.split("/repos/")[1].split("/releases/")[0]
                return json.dumps({"html_url":"https://github.com/"+repo+"/releases/tag/v1",
                                   "name":"Release v1","published_at":T.isoformat()}).encode()
            cg=url.split("/coins/")[1].split("?")[0]
            tok=next(t for t,v in e.PROJECTS.items() if v[0]==cg)
            return json.dumps(self.market(self.ident(tok))).encode()

        with mock.patch.object(producer.desk,"request",side_effect=response), \
             mock.patch.object(producer.time,"sleep"):
            first=producer.economic_evidence({"feed":[]},portfolio,four,candidate,T,
                                             asset_pairs=pairs)
            second=producer.economic_evidence(
                {"feed":[]},portfolio,four,candidate,T+dt.timedelta(minutes=1),
                asset_pairs=pairs,previous=first)
        self.assertEqual(len(first["posizioni"]),10)
        self.assertEqual(len(second["posizioni"]),10)
        self.assertEqual(sum(r["fondamentali"]["stato"]=="VERIFICATO"
                             for r in first["posizioni"]),6)
        self.assertEqual(sum(r["fondamentali"]["stato"]=="NON_ACQUISITO_PER_BUDGET"
                             for r in first["posizioni"]),4)
        self.assertEqual(sum(r["fondamentali"]["stato"]=="VERIFICATO"
                             for r in second["posizioni"]),10)
        self.assertEqual(sum(r["fondamentali"].get("origine")=="CACHE_LOCALE_FONTE_PUBBLICA"
                             for r in second["posizioni"]),4)
        self.assertLessEqual(first["richieste_effettuate"],9)
        self.assertLessEqual(second["richieste_effettuate"],9)
        self.assertEqual(first["richieste_coingecko"],6)
        self.assertEqual(second["richieste_coingecko"],6)
        self.assertEqual(second["candidati"][0]["fondamentali"]["stato"],"VERIFICATO")

    def test_producer_forged_candidate_pair_does_not_attribute_project(self):
        import dossier_trade as producer
        from unittest import mock
        pairs={"XXBTZEUR":{"wsname":"XBT/EUR","status":"online"},
               "ADAEUR":{"wsname":"ADA/EUR","status":"online"}}
        four={"posizioni":[{"token":"BTC","coppia":"XBT/EUR",
                            "pair_key":"XXBTZEUR","asset_base":"XBT"}]}
        wallet={"posizioni":[{"token":"BTC"}]}
        candidates=[{"token":"ADA","coppia_analisi":"ADA/EUR",
                     "kraken_pair_key":"ANOTHER_PROJECT"},
                    {"token":"BTC","coppia_analisi":"XBT/EUR",
                     "kraken_pair_key":"ADAEUR"}]
        with mock.patch.object(producer.desk,"request",side_effect=AssertionError(
                    "Nessun CoinGecko per candidati non identificati")), \
             mock.patch.object(producer.time,"sleep"):
            # Owned BTC may validly query; remove it to test only forged candidates.
            result=producer.economic_evidence({"feed":[]},{"posizioni":[]},
                      {"posizioni":[]},candidates,T,asset_pairs=pairs)
        self.assertEqual([r["identita"]["stato"] for r in result["candidati"]],
                         ["NON_VERIFICATO","NON_VERIFICATO"])
        self.assertTrue(all(r["fondamentali"]["stato"]=="NON_VERIFICATO_IDENTITA"
                            for r in result["candidati"]))

    def test_source_matrix_is_non_acquisition_and_tamper_is_rejected(self):
        source,positions,shortlist=self.sample()
        source["fonti_economiche"]=e.sources_matrix()
        read=e.at_read(source,positions,shortlist,T)
        self.assertIn("cftc_cme",[r["id"] for r in read["fonti_economiche"]])
        self.assertEqual(next(r["stato"] for r in read["fonti_economiche"]
                              if r["id"]=="farside"),
                         "CONSULTABILE_DA_GPT_NON_ACQUISITO")
        source["fonti_economiche"][0]["stato"]="INTEGRATO_MISURA_DI_AFFLUSSO"
        with self.assertRaises(ValueError):
            e.at_read(source,positions,shortlist,T)

    def test_missing_legacy_economics_does_not_create_facts(self):
        source,positions,shortlist=self.sample()
        source["posizioni"][0]["fondamentali"]["stato"]="NON_VERIFICATO"
        self.assertEqual(e.at_read(source,positions,shortlist,T)["posizioni"][0]
                         ["fondamentali"]["stato"],"NON_VERIFICATO")


if __name__=="__main__":
    unittest.main()
