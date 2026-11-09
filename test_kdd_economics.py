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
            if "/search?query=" in url:
                return json.dumps({"coins": []}).encode()
            coin_id = url.split("/coins/")[1].split("?")[0]
            if phase[0] == 0 and coin_id in ("bitcoin", "fetch-ai"):
                raise OSError("Simulated public source outage")
            token = next(t for t, v in e.PROJECTS.items() if v[0] == coin_id)
            return json.dumps(self.market(self.ident(token))).encode()

        outputs = []
        with mock.patch.object(producer.desk, "request", side_effect=public_source), \
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

        with mock.patch.object(producer.desk, "request", side_effect=denied), \
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
            if "/search?query=" in url:
                return json.dumps({"coins":[]}).encode()
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



class AdaptivePortfolioTests(unittest.TestCase):
    """New projects are resolved with a second market source, not registered in Python."""
    def setUp(self):
        self.now = T
        self.assertNotIn("ZEC", e.PROJECTS)
        self.catalog = {"ZECEUR": {"pair_key": "ZECEUR", "pair": "ZEC/EUR",
                                    "base": "ZEC", "quote": "EUR"}}
        self.search = {"coins": [
            {"id": "zcash", "symbol": "zec", "name": "Zcash"},
            {"id": "zcash-lookalike", "symbol": "zec", "name": "Zcash Imitation"}]}
        self.markets = {
            "zcash": {"tickers": [{"market": {"identifier": "kraken"}, "base": "ZEC",
                                   "target": "EUR", "is_anomaly": False, "is_stale": False}]},
            "zcash-lookalike": {"tickers": [{"market": {"identifier": "elsewhere"},
                                              "base": "ZEC", "target": "EUR"}]}}

    def proof(self):
        p = e.resolve_public("ZEC", "ZEC/EUR", self.search, self.markets, self.now)
        self.assertEqual(p["stato"], "RISOLTO")
        p["pair"] = "ZEC/EUR"
        return p

    def test_dynamic_identity_without_registration_is_bound_to_real_kraken_pair(self):
        evidence = self.proof()
        identity = e.identify("ZEC", "ZEC/EUR", "ZECEUR", catalog=self.catalog,
                              discovered=evidence)
        self.assertEqual(identity["coingecko_id"], "zcash")
        self.assertEqual(identity["metodo"], "KRAKEN_COINGECKO_MARKET")
        self.assertEqual(e.identify("ZEC", "ZEC/EUR", "FORGED", catalog=self.catalog,
                                    discovered=evidence)["stato"], "NON_VERIFICATO")
        self.assertEqual(e.identify("ZEC", "ZEC/USD", "ZECEUR", catalog=self.catalog,
                                    discovered=evidence)["stato"], "NON_VERIFICATO")
        fake = {"id": "zcash", "symbol": "zec", "name": "Zcash",
                "market_data": {"last_updated": T.isoformat(),
                                "market_cap": {"usd": 1000},
                                "fully_diluted_valuation": {"usd": 2000},
                                "circulating_supply": 10, "total_supply": 20,
                                "max_supply": None}}
        self.assertEqual(e.fundamentals(identity, fake, T, T)["stato"], "VERIFICATO")

    def test_unknown_ticker_ambiguity_and_nonexhaustive_search_fail_closed(self):
        ambiguous = copy.deepcopy(self.markets)
        ambiguous["zcash-lookalike"]["tickers"][0]["market"]["identifier"] = "kraken"
        self.assertEqual(e.resolve_public("ZEC", "ZEC/EUR", self.search, ambiguous,
                                           T)["motivo"], "TICKER_AMBIGUO_SU_KRAKEN")
        for result in ({"coins": self.search["coins"] * 2},
                       {"coins": self.search["coins"]}):
            market = self.markets if len(result["coins"]) > 3 else {"zcash": self.markets["zcash"]}
            self.assertEqual(e.resolve_public("ZEC", "ZEC/EUR", result, market,
                                               T)["stato"], "NON_VERIFICATO")
        self.assertEqual(e.identify("RNDR", "RNDR/EUR", "RNDREUR",
                                    catalog={"RNDREUR": {"pair_key": "RNDREUR",
                                             "pair": "RNDR/EUR", "base": "RNDR", "quote": "EUR"}})
                         ["stato"], "NON_VERIFICATO")

    def test_real_producer_new_asset_and_gpt_consumer_with_dated_reuse(self):
        import json
        import dossier_trade
        from scripts import kdd_wallet_packet_g0 as packet
        from unittest import mock
        roster = ["BNB", "FET", "JUP", "NEAR", "RENDER", "SOL", "SUI",
                  "ETH", "BTC", "XRP", "ZEC"]
        pairs = {x + "EUR": {"wsname": x + "/EUR", "status": "online"} for x in roster}
        pairs["ZECUSD"] = {"wsname": "ZEC/USD", "status": "online"}
        self.markets["zcash"]["tickers"].append({
            "market": {"identifier": "kraken"}, "base": "ZEC",
            "target": "USD", "is_anomaly": False, "is_stale": False})
        wallet = {"posizioni": [{"token": x} for x in roster]}
        four = {"posizioni": [{"token": x, "coppia": x + "/EUR",
                              "pair_key": x + "EUR"} for x in roster]}
        seen = []
        def response(url, timeout=12):
            seen.append(url)
            if "/search?query=ZEC" in url:
                return json.dumps(self.search).encode()
            if "/tickers?exchange_ids=kraken" in url:
                coin_id = url.split("/coins/")[1].split("/")[0]
                return json.dumps(self.markets[coin_id]).encode()
            if "/releases/latest" in url:
                raise OSError("no release")
            coin_id = url.split("/coins/")[1].split("?")[0]
            if coin_id == "zcash":
                name, symbol = "Zcash", "zec"
            else:
                token = next(t for t, v in e.PROJECTS.items() if v[0] == coin_id)
                name, symbol = e.PROJECTS[token][1], token.lower()
            return json.dumps({"id": coin_id, "name": name, "symbol": symbol,
                "market_data": {"last_updated": T.isoformat(),
                                "market_cap": {"usd": 100},
                                "fully_diluted_valuation": {"usd": 200},
                                "circulating_supply": 10, "total_supply": 20,
                                "max_supply": 100}}).encode()
        with mock.patch.object(dossier_trade.desk, "request", side_effect=response), \
             mock.patch.object(dossier_trade.time, "sleep"):
            first = dossier_trade.economic_evidence({"feed": []}, wallet, four,
                        [{"token": "ZEC", "coppia_analisi": "ZEC/USD",
                          "kraken_pair_key": "ZECUSD"}], T, asset_pairs=pairs)
            second = dossier_trade.economic_evidence({"feed": []}, wallet, four,
                        [{"token": "ZEC", "coppia_analisi": "ZEC/USD",
                          "kraken_pair_key": "ZECUSD"}],
                        T + dt.timedelta(minutes=1), asset_pairs=pairs, previous=first)
            third = dossier_trade.economic_evidence({"feed": []}, wallet, four,
                        [{"token": "ZEC", "coppia_analisi": "ZEC/USD",
                          "kraken_pair_key": "ZECUSD"}],
                        T + dt.timedelta(minutes=2), asset_pairs=pairs, previous=second)
        self.assertEqual(len(first["posizioni"]), 11)
        self.assertEqual(first["posizioni"][-1]["identita"]["coingecko_id"], "zcash")
        self.assertEqual(first["candidati"][0]["identita"]["stato"], "NON_VERIFICATO")
        self.assertEqual(second["candidati"][0]["identita"]["coingecko_id"], "zcash")
        self.assertEqual(second["posizioni"][-1]["identita"]["coingecko_id"], "zcash")
        self.assertEqual(third["richieste_identificazione"], 0)
        self.assertLessEqual(first["richieste_effettuate"], 9)
        self.assertLessEqual(second["richieste_effettuate"], 9)
        self.assertLessEqual(third["richieste_effettuate"], 9)
        self.assertEqual(len([url for url in seen if "/search?" in url]), 2)
        positions = [{"token": x, "stato_identita": "VALIDA"} for x in roster]
        shortlist = [{"token": "ZEC", "coppia_analisi": "ZEC/USD"}]
        snap = {"rilevazione_utc": T.isoformat()}
        dossier = {"kraken_istantanea_utc": T.isoformat(),
                   "evidenze_economiche": third, "candidati": []}
        got = packet.analytic_evidence(snap, dossier, positions, shortlist,
                                      T + dt.timedelta(minutes=2))
        self.assertEqual(got["economia"]["posizioni"][-1]["identita"]["coingecko_id"], "zcash")
        self.assertEqual(len(got["economia"]["posizioni"]), 11)
        tampered = copy.deepcopy(third)
        tampered["posizioni"][-1]["identita"]["coingecko_id"] = "bitcoin"
        with self.assertRaises(ValueError):
            e.at_read(tampered, positions, shortlist, T + dt.timedelta(minutes=2))


    def test_five_real_zec_homonyms_are_checked_before_attribution(self):
        """Five exact ZEC symbols reflect CoinGecko's 09/11 public response."""
        search = {"coins": [
            {"id": "zcash", "symbol": "zec", "name": "Zcash"},
            {"id": "binance-peg-zcash-token", "symbol": "zec", "name": "Binance-Peg Zcash Token"},
            {"id": "near-intents-bridged-zec", "symbol": "zec", "name": "NEAR Intents Bridged ZEC"},
            {"id": "omnibridge-bridged-zcash-solana", "symbol": "zec", "name": "Omnibridge Bridged Zcash"},
            {"id": "hyperlane-bridged-shield-swap-wrapped-zec-aleo",
             "symbol": "zec", "name": "Hyperlane Bridged Shield Swap Wrapped ZEC"}]}
        markets = {coin["id"]: {"tickers": []} for coin in search["coins"]}
        markets["zcash"] = {"tickers": [
            {"market": {"identifier": "kraken"}, "base": "ZEC",
             "target": "EUR", "is_stale": False, "is_anomaly": False}]}
        result = e.resolve_public("ZEC", "ZEC/EUR", search, markets, T)
        self.assertEqual(result["stato"], "RISOLTO")
        self.assertEqual(result["coingecko_id"], "zcash")
        real_catalog = {"XZECZEUR": {
            "pair_key": "XZECZEUR", "pair": "ZEC/EUR",
            "base": "ZEC", "quote": "EUR"}}
        self.assertEqual(
            e.identify("ZEC", "ZEC/EUR", "XZECZEUR",
                       catalog=real_catalog, discovered=result)["coingecko_id"], "zcash")
        # Two Kraken matches are ambiguous even if the first is the expected token.
        altered = copy.deepcopy(markets)
        altered["near-intents-bridged-zec"]["tickers"] = [
            {"market": {"identifier": "kraken"}, "base": "ZEC", "target": "EUR"}]
        self.assertEqual(e.resolve_public("ZEC", "ZEC/EUR", search, altered, T)
                         ["motivo"], "TICKER_AMBIGUO_SU_KRAKEN")
        missing = copy.deepcopy(markets)
        del missing["binance-peg-zcash-token"]
        self.assertEqual(e.resolve_public("ZEC", "ZEC/EUR", search, missing, T)
                         ["motivo"], "MERCATI_COINGECKO_NON_COMPLETI")
        nine = {"coins": search["coins"] + [
            {"id": f"extra-zec-{i}", "symbol": "zec", "name": f"Extra ZEC {i}"}
            for i in range(4)]}
        self.assertEqual(e.resolve_public("ZEC", "ZEC/EUR", nine, {}, T)
                         ["motivo"], "TICKER_OMONIMI_SUPERANO_BUDGET")

    def test_five_homonyms_pass_real_producer_and_gpt_packet(self):
        import dossier_trade
        from scripts import kdd_wallet_packet_g0 as packet
        from unittest import mock
        import json
        search = {"coins": [
            {"id": "zcash", "symbol": "zec", "name": "Zcash"},
            {"id": "binance-peg-zcash-token", "symbol": "zec", "name": "Binance-Peg"},
            {"id": "near-intents-bridged-zec", "symbol": "zec", "name": "NEAR Bridged"},
            {"id": "omnibridge-bridged-zcash-solana", "symbol": "zec", "name": "Omnibridge"},
            {"id": "hyperlane-bridged-shield-swap-wrapped-zec-aleo",
             "symbol": "zec", "name": "Hyperlane"}]}
        seen = []
        def public_response(url, timeout=12):
            seen.append(url)
            if url.endswith("/search?query=ZEC"):
                return json.dumps(search).encode()
            if "/tickers?exchange_ids=kraken" in url:
                coin_id = url.split("/coins/")[1].split("/")[0]
                rows = ([{"market": {"identifier": "kraken"}, "base": "ZEC",
                          "target": "EUR", "is_stale": False, "is_anomaly": False}]
                        if coin_id == "zcash" else [])
                return json.dumps({"tickers": rows}).encode()
            if "/coins/zcash?" in url:
                return json.dumps({"id": "zcash", "name": "Zcash", "symbol": "zec",
                  "market_data": {"last_updated": T.isoformat(),
                  "market_cap": {"usd": 100}, "fully_diluted_valuation": {"usd": 200},
                  "circulating_supply": 10, "total_supply": 20, "max_supply": 100}}).encode()
            raise OSError("unexpected public request")
        with mock.patch.object(dossier_trade.desk, "request", side_effect=public_response), \
             mock.patch.object(dossier_trade.time, "sleep"):
            ev = dossier_trade.economic_evidence(
                {"feed": []}, {"posizioni": [{"token": "ZEC"}]},
                {"posizioni": [{"token": "ZEC", "coppia": "ZEC/EUR",
                                "pair_key": "XZECZEUR"}]}, [], T,
                asset_pairs={"XZECZEUR": {"wsname": "ZEC/EUR", "status": "online"}})
        self.assertEqual(ev["richieste_identificazione"], 6)
        self.assertLessEqual(ev["richieste_effettuate"], 9)
        self.assertEqual(sum("tickers?exchange_ids=kraken" in x for x in seen), 5)
        self.assertEqual(ev["posizioni"][0]["identita"]["coingecko_id"], "zcash")
        self.assertEqual(ev["posizioni"][0]["fondamentali"]["stato"], "VERIFICATO")
        result = packet.analytic_evidence(
            {"rilevazione_utc": T.isoformat()},
            {"kraken_istantanea_utc": T.isoformat(),
             "evidenze_economiche": ev, "candidati": []},
            [{"token": "ZEC", "stato_identita": "VALIDA"}], [], T)
        self.assertEqual(result["economia"]["posizioni"][0]["identita"]
                         ["coingecko_id"], "zcash")
        self.assertEqual(result["economia"]["posizioni"][0]["fondamentali"]
                         ["stato"], "VERIFICATO")

    def test_doge_xdg_kraken_aliases_and_coin_gecko_flags_fail_closed(self):
        """Exercise actual identity functions; REST key XDGEUR is public-market attested."""
        import kraken_readonly
        import patrimonio_4tf
        import serve

        self.assertNotIn("DOGE", e.PROJECTS)
        for alias in ("DOGE", "XDG", "XXDG"):
            with self.subTest(alias=alias):
                self.assertEqual(kraken_readonly.normalize(alias)[0], "DOGE")
                self.assertEqual(patrimonio_4tf.canonical_base(alias), "DOGE")
                self.assertEqual(e.canonical_token(alias), "DOGE")
        for alias in ("BTC", "XBT", "XXBT"):
            with self.subTest(alias=alias):
                self.assertEqual(e.canonical_token(alias), "BTC")
                self.assertEqual(patrimonio_4tf.canonical_base(alias), "BTC")

        # Shape of Kraken AssetPairs; uses the independently documented
        # XDGEUR REST market rather than an invented DOGEEUR key.
        pairs = {"XDGEUR": {"wsname": "XDG/EUR", "altname": "XDGEUR",
                             "status": "online"}}
        catalog = serve.spot_catalog(lambda endpoint: pairs)
        self.assertEqual(catalog["XDGEUR"]["base"], "XDG")
        search = {"coins": [
            {"id": "dogecoin", "symbol": "doge", "name": "Dogecoin"},
            {"id": "wrapped-dogecoin-fixture", "symbol": "doge",
             "name": "Wrapped Dogecoin (fixture)"}]}
        good = {"market": {"identifier": "kraken"}, "base": "DOGE",
                "target": "EUR", "is_stale": False, "is_anomaly": False}
        markets = {"dogecoin": {"tickers": [good]},
                   "wrapped-dogecoin-fixture": {"tickers": []}}
        payload = {"id": "dogecoin", "symbol": "doge", "name": "Dogecoin",
                   "market_data": {"last_updated": T.isoformat(),
                                   "market_cap": {"usd": 100},
                                   "fully_diluted_valuation": {"usd": 200},
                                   "circulating_supply": 10, "total_supply": 20,
                                   "max_supply": None}}
        for alias in ("DOGE", "XDG", "XXDG"):
            with self.subTest(alias=alias):
                resolution = e.resolve_public(alias, "XDG/EUR", search, markets, T)
                self.assertEqual(resolution["coingecko_id"], "dogecoin")
                identity = e.identify(alias, "XDG/EUR", "XDGEUR",
                                      catalog=catalog, discovered=resolution)
                self.assertEqual(identity["stato"], "IDENTITA_VERIFICATA_DA_CATALOGO")
                self.assertEqual(identity["asset_base_kraken"], "XDG")
                self.assertEqual(identity["token_progetto"], "DOGE")
                self.assertTrue(e._dynamic_valid(alias, "XDG/EUR", identity))
                self.assertEqual(e.fundamentals(identity, payload, T, T)["stato"],
                                 "VERIFICATO")
                self.assertEqual(e.identify(alias, "XDG/EUR", "DOGEEUR",
                                 catalog=catalog, discovered=resolution)["stato"],
                                 "NON_VERIFICATO")
        for flag in ("is_stale", "is_anomaly"):
            for label, value in (("missing", None), ("null", None),
                                 ("true", True), ("integer_zero", 0),
                                 ("string_false", "false"), ("integer_one", 1)):
                with self.subTest(flag=flag, value=label):
                    altered = copy.deepcopy(markets)
                    ticker = altered["dogecoin"]["tickers"][0]
                    if label == "missing":
                        del ticker[flag]
                    else:
                        ticker[flag] = value
                    result = e.resolve_public("DOGE", "XDG/EUR", search, altered, T)
                    self.assertEqual(result["stato"], "NON_VERIFICATO")
                    self.assertEqual(result["motivo"], "NESSUN_MERCATO_KRAKEN_CONFERMATO")
        # A second verified competitor forbids positive attribution.
        ambiguous = copy.deepcopy(markets)
        ambiguous["wrapped-dogecoin-fixture"]["tickers"] = [good]
        self.assertEqual(e.resolve_public("DOGE", "XDG/EUR", search, ambiguous, T)
                         ["motivo"], "TICKER_AMBIGUO_SU_KRAKEN")

    def test_doge_normalized_wallet_to_real_dossier_at_read_and_gpt_packet(self):
        """Synthetic BalanceEx → Kraken AssetPairs → CoinGecko → GPT packet."""
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock
        import dossier_trade
        import kdd_saldi
        import kraken_readonly
        import patrimonio_4tf
        import serve
        from scripts import kdd_wallet_packet_g0 as packet

        old_tokens = ["BNB", "FET", "JUP", "NEAR", "RENDER",
                      "SOL", "SUI", "ETH", "BTC", "XRP"]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "wallet.json"
            path.write_text(json.dumps({
                "t0_id": "T0_IMMUTABILE", "t0_sha256": "HASH_IMMUTABILE",
                "posizioni": [{"token": token, "quantita": "1"}
                              for token in old_tokens]}), encoding="utf-8")
            segments = [{"token": token, "account_segment": "spot",
                         "balance": "1", "available_balance": "1"}
                        for token in old_tokens]
            segments.append({
                "token": kraken_readonly.normalize("XXDG")[0],
                "account_segment": "spot", "balance": "100",
                "available_balance": "100"})
            segments.append({"token": "EUR", "account_segment": "spot",
                             "balance": "1", "available_balance": "1"})
            kdd_saldi.apply({
                "source": "Kraken Spot REST /0/private/BalanceEx (read-only)",
                "acquired_utc": T.isoformat(),
                "account_segments": segments}, path=path)
            wallet = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(wallet["t0_sha256"], "HASH_IMMUTABILE")
        self.assertEqual(wallet["t0_id"], "T0_IMMUTABILE")
        self.assertEqual(len(wallet["posizioni"]), 11)
        self.assertIn("DOGE", [row["token"] for row in wallet["posizioni"]])
        self.assertIn({"acquisito_utc": T.isoformat(), "token": "DOGE",
                       "evento": "INGRESSO"},
                      wallet["storico_transizioni_posizioni"])
        pairs = {token + "EUR": {"wsname": token + "/EUR", "status": "online"}
                 for token in old_tokens}
        pairs["XDGEUR"] = {"wsname": "XDG/EUR", "altname": "XDGEUR",
                           "status": "online"}
        catalog = serve.spot_catalog(lambda endpoint: pairs)
        doge_meta, status, _ = patrimonio_4tf.select_pair("DOGE", catalog)
        self.assertIsNone(status)
        self.assertEqual((doge_meta["pair_key"], doge_meta["pair"]),
                         ("XDGEUR", "XDG/EUR"))
        four = {"posizioni": [
            {"token": row["token"],
             "coppia": ("XDG/EUR" if row["token"] == "DOGE"
                        else row["token"] + "/EUR"),
             "pair_key": ("XDGEUR" if row["token"] == "DOGE"
                          else row["token"] + "EUR")}
            for row in wallet["posizioni"]]}
        seen = []
        def source(url, timeout=12):
            seen.append(url)
            if url.endswith("/search?query=DOGE"):
                return json.dumps({"coins": [
                    {"id": "dogecoin", "symbol": "doge", "name": "Dogecoin"},
                    {"id": "doge-test-copy", "symbol": "doge",
                     "name": "DOGE copy (fixture)"}]}).encode()
            if "/tickers?exchange_ids=kraken" in url:
                coin_id = url.split("/coins/")[1].split("/")[0]
                tickers = ([{"market": {"identifier": "kraken"},
                             "base": "DOGE", "target": "EUR",
                             "is_stale": False, "is_anomaly": False}]
                           if coin_id == "dogecoin" else [])
                return json.dumps({"tickers": tickers}).encode()
            if "/releases/latest" in url:
                raise OSError("No synthetic releases")
            coin_id = url.split("/coins/")[1].split("?")[0]
            if coin_id == "dogecoin":
                token, name = "DOGE", "Dogecoin"
            else:
                token, name = next((token, details[1])
                                   for token, details in e.PROJECTS.items()
                                   if details[0] == coin_id)
            return json.dumps({
                "id": coin_id, "symbol": token.lower(), "name": name,
                "market_data": {"last_updated": T.isoformat(),
                                "market_cap": {"usd": 100},
                                "fully_diluted_valuation": {"usd": 200},
                                "circulating_supply": 10, "total_supply": 20,
                                "max_supply": 100}}).encode()

        with mock.patch.object(dossier_trade.desk, "request", side_effect=source), \
             mock.patch.object(dossier_trade.time, "sleep"):
            first = dossier_trade.economic_evidence(
                {"feed": []}, wallet, four, [], T, asset_pairs=pairs)
            second = dossier_trade.economic_evidence(
                {"feed": []}, wallet, four, [], T + dt.timedelta(minutes=1),
                asset_pairs=pairs, previous=first)
        for evidence in (first, second):
            self.assertEqual(len(evidence["posizioni"]), 11)
            self.assertEqual(sum(row["token"] in old_tokens
                                 for row in evidence["posizioni"]), 10)
            self.assertLessEqual(evidence["richieste_effettuate"], 9)
            doge = next(row for row in evidence["posizioni"]
                        if row["token"] == "DOGE")
            self.assertEqual(doge["identita"]["coingecko_id"], "dogecoin")
            self.assertEqual(doge["identita"]["asset_base_kraken"], "XDG")
            self.assertEqual(doge["fondamentali"]["stato"], "VERIFICATO")
        self.assertEqual(first["richieste_identificazione"], 3)
        self.assertEqual(second["richieste_identificazione"], 0)
        self.assertEqual(sum(url.endswith("/search?query=DOGE") for url in seen), 1)
        positions = [{"token": row["token"], "stato_identita": "VALIDA"}
                     for row in wallet["posizioni"]]
        got = packet.analytic_evidence(
            {"rilevazione_utc": T.isoformat()},
            {"kraken_istantanea_utc": T.isoformat(),
             "evidenze_economiche": second, "candidati": []},
            positions, [], T + dt.timedelta(minutes=1))
        self.assertEqual(len(got["economia"]["posizioni"]), 11)
        doge_packet = next(row for row in got["economia"]["posizioni"]
                           if row["token"] == "DOGE")
        self.assertEqual(doge_packet["identita"]["coingecko_id"], "dogecoin")
        self.assertEqual(doge_packet["fondamentali"]["stato"], "VERIFICATO")
        altered = copy.deepcopy(second)
        next(row for row in altered["posizioni"]
             if row["token"] == "DOGE")["identita"]["coingecko_id"] = "bitcoin"
        with self.assertRaises(ValueError):
            e.at_read(altered, positions, [], T + dt.timedelta(minutes=1))

    def test_wallet_entry_zero_absent_and_return_preserve_t0(self):
        import json
        import tempfile
        from pathlib import Path
        import kdd_saldi
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "portafoglio.json"
            original = {"t0_id": "T0_19_OTTOBRE", "t0_sha256": "ORIGINALE",
                        "posizioni": [{"token": "BTC", "quantita": "2"}]}
            path.write_text(json.dumps(original))
            def apply(ts, holdings):
                return kdd_saldi.apply({
                  "source": "Kraken Spot REST /0/private/BalanceEx (read-only)",
                  "acquired_utc": ts, "account_segments": [
                      {"token": k, "account_segment": "spot",
                       "balance": str(q), "available_balance": str(q)}
                      for k, q in holdings.items()] + [
                      {"token": "EUR", "account_segment": "spot",
                       "balance": "1", "available_balance": "1"}]
                }, path=path)
            apply("2026-11-09T08:00:00+00:00", {"BTC": 2})
            apply("2026-11-09T08:10:00+00:00", {"BTC": 2, "ZEC": 1})
            apply("2026-11-09T08:20:00+00:00", {"BTC": 0, "ZEC": 1})
            interim = json.loads(path.read_text())
            self.assertEqual(interim["riconciliazione_posizioni"]["zero_esplicito"], ["BTC"])
            self.assertEqual([x["token"] for x in interim["posizioni"]], ["ZEC"])
            apply("2026-11-09T08:30:00+00:00", {"BTC": 1, "ZEC": 1})
            result = json.loads(path.read_text())
            history = result["storico_transizioni_posizioni"]
            self.assertEqual([(x["token"], x["evento"]) for x in history],
                             [("ZEC", "INGRESSO"), ("BTC", "USCITA"),
                              ("BTC", "RIENTRO")])
            self.assertEqual(history[1]["evidenza"], "ZERO_ESPLICITO_BALANCEEX")
            self.assertEqual(result["t0_id"], "T0_19_OTTOBRE")
            self.assertEqual(result["t0_sha256"], "ORIGINALE")
            snap = json.loads(path.read_text())
            with self.assertRaises(ValueError):
                kdd_saldi.apply({"source": "invalid"}, path=path)
            self.assertEqual(json.loads(path.read_text()), snap)
            # A missing BTC entry is not equivalent to a reported zero.
            apply("2026-11-09T08:40:00+00:00", {"ZEC": 1})
            absent = json.loads(path.read_text())
            self.assertEqual(absent["riconciliazione_posizioni"]
                             ["assenti_rispetto_alla_precedente"], ["BTC"])
            self.assertEqual(absent["storico_transizioni_posizioni"][-1]["evidenza"],
                             "ASSENTE_DALLA_FOTOGRAFIA_BALANCEEX")
            self.assertEqual(absent["storico_transizioni_posizioni"][1]
                             ["acquisito_utc"], "2026-11-09T08:20:00+00:00")

if __name__=="__main__":
    unittest.main()
