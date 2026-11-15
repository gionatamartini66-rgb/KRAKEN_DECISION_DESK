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

    def test_g2_primary_release_cases_and_supply_no_invented_unlock(self):
        """Real primary-release metadata checked 11 Nov 2026; synthetic CoinGecko amounts."""
        moment=dt.datetime(2026,11,11,8,tzinfo=dt.timezone.utc)
        cases=[
            ("BTC","bitcoin/bitcoin","v32.1","Bitcoin Core 32.1",
             "2026-10-28T14:23:53Z"),
            ("SOL","anza-xyz/agave","v4.4.1","Release v4.4.1",
             "2026-11-05T18:33:50Z")]
        for token,repo,tag,title,published in cases:
            with self.subTest(token=token):
                identity=self.ident(token)
                event=e.release_event(identity,{"html_url":
                    f"https://github.com/{repo}/releases/tag/{tag}",
                    "tag_name":tag,"published_at":published,
                    "name":title,"draft":False,"prerelease":False},moment,moment)
                self.assertEqual(event["stato"],"VERIFICATO")
                self.assertEqual(event["emittente"],repo)
                self.assertEqual(event["tag"],tag)
                self.assertEqual(event["adozione_rete"],"NON_VERIFICATA")
                self.assertEqual(event["impatto_economico"],"NON_DIMOSTRATO")
                self.assertTrue(event["condizione_riesame"])
                ref=e.monetary_reference(identity)
                self.assertEqual(ref["stato"],"CONSULTABILE_NON_ACQUISITO")
                self.assertTrue(ref["fonte"].startswith("https://"))
                self.assertFalse(ref["calendario_unlock_verificato"])
                self.assertIsNone(ref["ultimo_controllo_documentale_utc"])
                forbidden={"html_url":"https://github.com/fake/bitcoin/releases/tag/"+tag,
                           "tag_name":tag,"published_at":published,"name":title}
                self.assertEqual(e.release_event(identity,forbidden,moment,moment)
                                 ["stato"],"NON_VERIFICATO")
        ident=self.ident("BTC")
        stats=e.fundamentals(ident,self.market(ident,max_supply=100),T,T)
        self.assertEqual(stats["quota_circolante_su_totale_pct"],50)
        self.assertEqual(stats["emissione_residua_massima_su_circolante_pct"],900)
        self.assertIsNone(stats["prossimo_unlock_utc"])
        self.assertIsNone(stats["fonte_calendario_unlock"])
        self.assertEqual(stats["vesting"],"NON_VERIFICATO")
        no_max=e.fundamentals(self.ident("SOL"),
                             self.market(self.ident("SOL"),max_supply=None),T,T)
        self.assertIsNone(no_max["emissione_residua_massima_su_circolante_pct"])
        self.assertEqual(no_max["unlock"],"NON_VERIFICATO")
        impossible=e.fundamentals(ident,self.market(ident,max_supply=5),T,T)
        self.assertEqual(impossible["diluizione"],
                         "SUPPLY_MAX_INFERIORE_AL_CIRCOLANTE_ANOMALIA")
        self.assertIsNone(impossible["emissione_residua_massima_su_circolante_pct"])

    def test_g2_macro_and_geopolitical_hypotheses_revoke_when_expired(self):
        feed=[
            {"fonte":"Fed — politica monetaria",
             "link":"https://www.federalreserve.gov/newsevents/pressreleases/example.htm",
             "data":T.isoformat(),"titolo":"Synthetic official policy topic"},
            {"fonte":"Consiglio UE — comunicati",
             "link":"https://www.consilium.europa.eu/en/press/example/",
             "data":T.isoformat(),"titolo":"Synthetic council topic"}]
        observed=e.macro(feed,T)
        self.assertEqual(len(observed["scenari_condizionali"]),2)
        self.assertTrue(all(row["stato"]=="IPOTESI_DA_VERIFICARE"
                            for row in observed["scenari_condizionali"]))
        self.assertTrue(all(row["controipotesi"] and row["condizione_di_riesame"]
                            for row in observed["scenari_condizionali"]))
        self.assertEqual(observed["sorpresa_vs_consenso"],"NON_VALUTABILE")
        self.assertTrue(all(row["impatto_asset"]=="NON_VALUTABILE"
                            for row in observed["fonti_ufficiali"]))
        old=e.macro(feed,T+dt.timedelta(days=15))
        self.assertTrue(all(row["stato"]=="NON_VALUTABILE"
                            for row in old["scenari_condizionali"]))
        forged=e.macro([{**feed[0],"link":"https://www.federalreserve.gov.evil.example/"}],T)
        self.assertEqual(forged["scenari_condizionali"][0]["stato"],"NON_VALUTABILE")
        # Re-validation is at GPT time, regardless of a stored optimistic label.
        source,positions,shortlist=self.sample()
        source["macro"]=observed
        read=e.at_read(source,positions,shortlist,T+dt.timedelta(days=15))
        self.assertTrue(all(row["stato"]=="NON_VALUTABILE"
                            for row in read["macro"]["scenari_condizionali"]))

    def test_g2_multifactor_regime_conflicts_and_observation_families(self):
        frames={label:{"stato":"AGGIORNATO","figure_candlestick":{
            "stato":"AGGIORNATO","trend_precedente":"SALITA"}}
            for label in ("4H","1D")}
        global_row={"fonte":"https://api.coingecko.com/api/v3/global",
                    "aggiornato_sorgente_utc":T.timestamp(),
                    "var_capitalizzazione_24h_pct":1.25,
                    "capitalizzazione_totale_usd":200000,
                    "volume_24h_usd":12000}
        bullish=e.regime({"timeframe":frames},global_row,T)
        self.assertEqual(bullish["stato"],"RIALZISTA")
        self.assertEqual([x["famiglia"] for x in bullish["famiglie_osservate"]],
                         ["TREND_BTC","CAPITALIZZAZIONE_CRYPTO_AGGREGATA",
                          "ATTIVITA_AGGREGATA"])
        self.assertTrue(bullish["mancanti"])
        global_row["var_capitalizzazione_24h_pct"]=-2
        self.assertEqual(e.regime({"timeframe":frames},global_row,T)["stato"],
                         "TRANSIZIONE")
        frames["1D"]["figure_candlestick"]["trend_precedente"]="DISCESA"
        self.assertEqual(e.regime({"timeframe":frames},global_row,T)["stato"],
                         "TRANSIZIONE")
        frames["1D"]["stato"]="SCADUTO"
        self.assertEqual(e.regime({"timeframe":frames},global_row,T)["stato"],
                         "INDETERMINATO")
        frames["1D"]["stato"]="AGGIORNATO"
        frames["1D"]["figure_candlestick"]["trend_precedente"]="SALITA"
        global_row["aggiornato_sorgente_utc"]=(T-dt.timedelta(hours=3)).timestamp()
        self.assertEqual(e.regime({"timeframe":frames},global_row,T)["stato"],
                         "INDETERMINATO")

    def test_g2_source_dossier_packet_bridge_historical_roster_and_zec(self):
        """Ten token identities from the 08/11 roster; all amounts are invented."""
        import json
        from unittest import mock
        import dossier_trade as producer
        from scripts import kdd_wallet_packet_g0 as wallet_packet
        from scripts import kdd_bridge_g2 as bridge
        with mock.patch.dict("sys.modules", {"kdd_wallet_packet_g0": wallet_packet}):
            from scripts import test_kdd_wallet_packet_g0 as fixture_mod
        fixture=fixture_mod.WalletPacketG0Tests(
            "test_asset_weights_never_rebrand_partial_total_as_entire_wallet")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        tokens=["BNB","FET","JUP","NEAR","RENDER","SOL","SUI","ETH","BTC","XRP"]
        pairs={token+"EUR":{"wsname":token+"/EUR","status":"online"}
               for token in tokens+["ZEC"]}
        iso=T.isoformat()
        fixture.portfolio["posizioni"]=[
            {"token":token,"quantita":"1","disponibile_spot":"1","costo_medio_eur":None}
            for token in tokens]
        fixture.snapshot["markets"]={
            token:{"token":token,"pair":token+"/EUR","pair_key":token+"EUR",
                   "prezzo_eur":float((i+1)*10)}
            for i,token in enumerate(tokens)}
        fixture.report["posizioni"]=[
            {"token":token,"quantita":"1","prezzo_eur":float((i+1)*10),
             "valore_eur":float((i+1)*10),"pl_non_realizzato_eur":None,
             "decisione":"ESAME"} for i,token in enumerate(tokens)]
        fixture.report["totale_stimato_eur"]=550.0
        fixture.report["totale_parziale"]=False
        fixture.report["stato_totale"]="COMPLETO"
        fixture.snapshot["schede_v02"]=[
            {"token":"ZEC","coppia_analisi":"ZEC/EUR","categoria":"confronto",
             "esito":"DA_VERIFICARE"}]
        fixture.dossier["candidati"]=[
            {"token":"ZEC","coppia_analisi":"ZEC/EUR",
             "flusso_spot_kraken":{"stato":"NON_DISPONIBILE"},
             "fondamentali_coingecko":{"stato":"NON_VERIFICATO"}}]
        fixture.dossier["grafici_4h"]={}
        btc_frames={label:{"stato":"AGGIORNATO",
                           "figure_candlestick":{"stato":"AGGIORNATO",
                                                "trend_precedente":"SALITA"}}
                    for label in ("4H","1D")}
        four={"posizioni":[
            dict({"token":token,"coppia":token+"/EUR","pair_key":token+"EUR"},
                 **({"timeframe":btc_frames} if token=="BTC" else {}))
            for token in tokens]}
        zec_search={"coins":[
            {"id":"zcash","symbol":"zec","name":"Zcash"},
            {"id":"binance-peg-zcash-token","symbol":"zec","name":"Pegged Zcash"}]}
        zec_markets={
            "zcash":{"tickers":[
                {"market":{"identifier":"kraken"},"base":"ZEC","target":"EUR",
                 "is_stale":False,"is_anomaly":False}]},
            "binance-peg-zcash-token":{"tickers":[]}}
        proof=e.resolve_public("ZEC","ZEC/EUR",zec_search,zec_markets,T)
        self.assertEqual(proof["stato"],"RISOLTO")
        proof["pair"]="ZEC/EUR"
        previous={"schema":e.VERSION,"acquisito_utc":iso,
                  "identita_dinamiche":[{"token":"ZEC","coppia":"ZEC/EUR",
                                         "risoluzione":proof}]}
        release_metadata={
            "bitcoin/bitcoin":{"html_url":
                "https://github.com/bitcoin/bitcoin/releases/tag/v32.1",
                "tag_name":"v32.1","published_at":"2026-10-28T14:23:53Z",
                "name":"Bitcoin Core 32.1"},
            "anza-xyz/agave":{"html_url":
                "https://github.com/anza-xyz/agave/releases/tag/v4.4.1",
                "tag_name":"v4.4.1","published_at":"2026-11-05T18:33:50Z",
                "name":"Release v4.4.1"}}
        def upstream(url, timeout=12):
            if "/releases/latest" in url:
                repo=url.split("/repos/")[1].split("/releases/")[0]
                return json.dumps(release_metadata[repo]).encode()
            if "/search?" in url or "/tickers?" in url:
                raise AssertionError("ZEC identity was already independently resolved")
            coin=url.split("/coins/")[1].split("?")[0]
            if coin=="zcash":
                raise OSError("ZEC source unavailable in this controlled sample")
            token=next((token for token in tokens if e.PROJECTS[token][0]==coin),None)
            if token is None:
                raise OSError("No attributable source")
            ident=self.ident(token)
            return json.dumps(self.market(ident, max_supply=(
                None if token=="SOL" else 21000000))).encode()
        source={"feed":[],
                "coingecko_global":{
                    "fonte":"https://api.coingecko.com/api/v3/global",
                    "aggiornato_sorgente_utc":T.timestamp(),
                    "var_capitalizzazione_24h_pct":1.2,
                    "capitalizzazione_totale_usd":1000000,
                    "volume_24h_usd":80000}}
        with mock.patch.object(producer.desk,"request",side_effect=upstream), \
             mock.patch.object(producer.time,"sleep"):
            economics=producer.economic_evidence(
                source,fixture.portfolio,four,[
                    {"token":"ZEC","coppia_analisi":"ZEC/EUR",
                     "kraken_pair_key":"ZECEUR"}],T,
                asset_pairs=pairs,previous=previous)
        self.assertLessEqual(economics["richieste_effettuate"],9)
        self.assertEqual(len(economics["posizioni"]),10)
        self.assertEqual(len(economics["candidati"]),1)
        self.assertEqual(economics["regime"]["stato"],"RIALZISTA")
        bytoken={row["token"]:row for row in economics["posizioni"]}
        self.assertEqual(bytoken["BTC"]["evento"]["tag"],"v32.1")
        self.assertEqual(bytoken["SOL"]["evento"]["tag"],"v4.4.1")
        self.assertEqual(bytoken["BTC"]["evento"]["stato"],"VERIFICATO")
        self.assertEqual(bytoken["SOL"]["evento"]["stato"],"VERIFICATO")
        self.assertEqual(bytoken["SOL"]["politica_monetaria_primaria"]["stato"],
                         "CONSULTABILE_NON_ACQUISITO")
        self.assertEqual(economics["candidati"][0]["identita"]["coingecko_id"],
                         "zcash")
        self.assertNotEqual(economics["candidati"][0]["fondamentali"]["stato"],
                            "VERIFICATO")
        fixture.dossier["evidenze_economiche"]=economics
        fixture.dump()
        packet=wallet_packet.build(fixture.root,now=T)
        self.assertEqual(packet["patrimonio"]["n_posizioni"],10)
        self.assertEqual(packet["patrimonio"]["stato_totale"],"COMPLETO")
        self.assertEqual(len(packet["evidenze_multifonte"]["economia"]["posizioni"]),10)
        self.assertEqual(packet["evidenze_multifonte"]["economia"]["candidati"][0]
                         ["identita"]["coingecko_id"],"zcash")
        bundle={"schema":bridge.SCHEMA_BUNDLE,"packet":packet,
                "packet_sha256":bridge.digest(packet),"preparato_utc":iso}
        at_gpt=bridge.read_context(json.loads(json.dumps(bundle)),now=T)
        self.assertEqual(at_gpt["n_posizioni"],10)
        rows=at_gpt["evidenze_economiche_alla_lettura"]
        self.assertEqual(len(rows["posizioni"]),10)
        self.assertEqual(len(rows["candidati"]),1)
        self.assertEqual(rows["posizioni"][tokens.index("BTC")]["evento"]["tag"],"v32.1")
        self.assertEqual(rows["posizioni"][tokens.index("SOL")]["evento"]["tag"],"v4.4.1")
        self.assertIsNone(rows["candidati"][0]["fondamentali"]["prossimo_unlock_utc"])
        self.assertEqual(rows["candidati"][0]["fondamentali"]["stato"],
                         "NON_ACQUISITO_PER_BUDGET" if
                         economics["candidati"][0]["fondamentali"]["stato"]==
                         "NON_ACQUISITO_PER_BUDGET" else
                         economics["candidati"][0]["fondamentali"]["stato"])
        old=bridge.read_context(bundle,now=T+dt.timedelta(days=3))
        self.assertNotEqual(old["mercato"]["stato"],"RECENTE")
        self.assertEqual(old["evidenze_economiche_alla_lettura"]["regime"]
                         ["qualita"],"SCADUTO")
        changed=copy.deepcopy(bundle)
        changed["packet"]["evidenze_multifonte"]["economia"]["candidati"][0]["token"]="BTC"
        changed["packet_sha256"]=bridge.digest(changed["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(changed,now=T)

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
        ambiguous["zcash-lookalike"]["tickers"][0].update(
            is_stale=False, is_anomaly=False)
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
            {"market": {"identifier": "kraken"}, "base": "ZEC", "target": "EUR",
             "is_stale": False, "is_anomaly": False}]
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
                untrusted = copy.deepcopy(resolution)
                del untrusted["prova_mercato"]["is_stale"]
                self.assertFalse(e._dynamic_valid(alias, "XDG/EUR", untrusted))
                self.assertEqual(e.identify(alias, "XDG/EUR", "XDGEUR",
                                 catalog=catalog, discovered=untrusted)["stato"],
                                 "NON_VERIFICATO")
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
            legacy = copy.deepcopy(first)
            for record in legacy["identita_dinamiche"]:
                if record["token"] == "DOGE":
                    del record["risoluzione"]["prova_mercato"]["is_anomaly"]
            rediscovered = dossier_trade.economic_evidence(
                {"feed": []}, wallet, four, [], T + dt.timedelta(minutes=2),
                asset_pairs=pairs, previous=legacy)
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
        self.assertEqual(rediscovered["richieste_identificazione"], 3)
        self.assertEqual(sum(url.endswith("/search?query=DOGE") for url in seen), 2)
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
        legacy_packet = copy.deepcopy(second)
        next(row for row in legacy_packet["posizioni"]
             if row["token"] == "DOGE")["identita"]["prova_mercato"].pop("is_stale")
        with self.assertRaises(ValueError):
            e.at_read(legacy_packet, positions, [], T + dt.timedelta(minutes=1))

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


class PrimaryEconomicProducerTests(unittest.TestCase):
    """Live-provider-shaped public fixtures; no wallet/network or paid API."""

    def setUp(self):
        import datetime as dt
        self.now = dt.datetime(2026, 11, 15, 12, 0, tzinfo=dt.timezone.utc)
        self.ids = [
            {"stato": "IDENTITA_VERIFICATA_DA_CATALOGO",
             "token_progetto": "BTC", "token": "BTC",
             "coingecko_id": "bitcoin", "progetto": "Bitcoin",
             "repository_primario": "bitcoin/bitcoin"},
            {"stato": "IDENTITA_VERIFICATA_DA_CATALOGO",
             "token_progetto": "NEAR", "token": "NEAR",
             "coingecko_id": "near", "progetto": "NEAR Protocol",
             "repository_primario": "near/nearcore"},
            {"stato": "IDENTITA_VERIFICATA_DA_CATALOGO",
             "token_progetto": "SOL", "token": "SOL",
             "coingecko_id": "solana", "progetto": "Solana",
             "repository_primario": "anza-xyz/agave"},
            {"stato": "IDENTITA_VERIFICATA_DA_CATALOGO",
             "token_progetto": "SUI", "token": "SUI",
             "coingecko_id": "sui", "progetto": "Sui",
             "repository_primario": "MystenLabs/sui"}]
        self.catalog = {
            identity["token_progetto"]: {
                "id": identity["coingecko_id"],
                "name": identity["progetto"],
                "emission_primary": "SOLANA_RPC_GOVERNOR"
                if identity["token"] == "SOL" else None}
            for identity in self.ids}
        self.macro_csv = (
            b"TIME_PERIOD,OBS_VALUE\n2026-11-01,2.15\n2026-11-14,2.25\n")

    def _request(self, url, payload=None):
        if url == "https://api.mainnet.solana.com":
            self.assertEqual(payload["method"], "getInflationGovernor")
            return {"jsonrpc": "2.0",
                    "result": {"initial": .15, "terminal": .015,
                               "taper": .15, "foundation": .05,
                               "foundationTerm": 7}}
        if url.startswith("https://api.github.com/repos/"):
            return []
        raise AssertionError("unexpected URL: " + url)

    def _collect(self, ids=None, old=None, when=None, fetch=None, registry=None):
        import kdd_primary_economics as primary
        return primary.collect(
            when or self.now, ids or self.ids, old,
            fetch_json=fetch or self._request,
            fetch_csv=lambda url: self.macro_csv,
            catalog=registry or self.catalog)

    def test_rotation_four_projects_and_retained_primary_history(self):
        a = self._collect()
        b = self._collect(old=a, when=self.now+__import__('datetime').timedelta(minutes=20))
        c = self._collect(old=b, when=self.now+__import__('datetime').timedelta(minutes=40))
        first = [x["coingecko_id"] for x in a["progetti"] if x["stato"]!="RINVIATO_BUDGET"]
        second = [x["coingecko_id"] for x in b["progetti"] if x["stato"]!="RINVIATO_BUDGET"]
        third = [x["coingecko_id"] for x in c["progetti"] if x["stato"]!="RINVIATO_BUDGET"]
        self.assertEqual(first, ["bitcoin","near"])
        self.assertEqual(second, ["solana","sui"])
        self.assertEqual(third, first)
        retained = {x["coingecko_id"]: x for x in c["storico"]}
        self.assertEqual(retained["solana"]["politica_emissioni"]["stato"], "OSSERVATO")
        self.assertLessEqual(max(x["richieste_effettuate"] for x in (a,b,c)), 8)
        self.assertEqual(len(c["progetti"]), 4)

    def test_solana_issued_policy_is_not_unlock(self):
        out = self._collect(ids=[self.ids[2]])
        p = out["progetti"][0]
        self.assertEqual(p["politica_emissioni"]["stato"], "OSSERVATO")
        self.assertEqual(p["politica_emissioni"]["valori"]["terminal"], .015)
        self.assertNotEqual(p["calendario"]["stato"], "OSSERVATO")
        self.assertEqual(p["calendario"]["eventi"], [])

    def test_primary_schedule_requires_exact_project_and_publisher(self):
        import kdd_primary_economics as primary
        identity = self.ids[2]
        source = "https://raw.githubusercontent.com/anza-xyz/agave/main/tokenomics/vesting.json"
        payload = {"schema": "kdd-primary-vesting-v001",
                   "coingecko_id": "solana", "source_url": source,
                   "published_at": "2026-11-01T12:00:00Z",
                   "events": [{"kind": "UNLOCK_PROGRAMMATO",
                               "scheduled_utc": "2027-01-02T12:00:00Z",
                               "quantity_tokens": 100}]}
        accepted = primary.parse_calendar(identity,payload,source,self.now)
        self.assertEqual(accepted["stato"], "OSSERVATO")
        self.assertEqual(accepted["eventi"][0]["vendita"], "NON_ATTESTATA")
        rejected = primary.parse_calendar(identity,dict(payload,coingecko_id="another"),source,self.now)
        self.assertEqual(rejected["stato"], "NON_VERIFICATO")
        rejected2 = primary.parse_calendar(identity,dict(payload,source_url="https://other.example"),source,self.now)
        self.assertEqual(rejected2["stato"], "NON_VERIFICATO")

    def test_source_must_be_registered_not_passed_as_arbitrary_url(self):
        def reject_bad(url, payload=None):
            self.assertNotIn("evil.example",url)
            return self._request(url,payload)
        registry = dict(self.catalog)
        registry["SOL"] = dict(registry["SOL"], schedule_primary={
            "path": "../evil.json"})
        o = self._collect(ids=[self.ids[2]],fetch=reject_bad,registry=registry)
        self.assertEqual(o["progetti"][0]["calendario"]["stato"],"NON_VERIFICATO")

    def test_primary_monthly_circulation_forecast_has_no_fake_unlock(self):
        import datetime
        import kdd_primary_economics as primary
        url = "https://sui-circulation.suiexplorer.com/api/sui_circulation"
        registry = dict(self.catalog)
        registry["SUI"] = dict(registry["SUI"],
            circulation_schedule_primary={
                "type": "MONTHLY_CIRCULATION_PROJECTION",
                "url": url, "max_supply_tokens": 10_000_000_000})
        def public(url_requested,payload=None):
            if url_requested == url:
                return [{"year":2026,"month":11,
                         "circulatingSupplyValue":4_139_043_544.13,
                         "circulatingSupplyPercentage":.413904354413},
                        {"year":2026,"month":12,
                         "circulatingSupplyValue":4_159_640_598.62,
                         "circulatingSupplyPercentage":.415964059862},
                        {"year":2027,"month":1,
                         "circulatingSupplyValue":4_180_107_445.11,
                         "circulatingSupplyPercentage":.418010744511}]
            return self._request(url_requested,payload)
        raw = self._collect(ids=[self.ids[3]],fetch=public,registry=registry)
        record=raw["progetti"][0]["proiezione_circolazione"]
        self.assertEqual(record["stato"],"OSSERVATO")
        self.assertEqual(len(record["eventi"]),3)
        self.assertEqual(record["eventi"][1]["vendita"],"NON_ATTESTATA")
        self.assertEqual(record["eventi"][1]["immissione_effettiva"],"NON_ATTESTATA")
        self.assertNotIn("UNLOCK_PROGRAMMATO",str(record))
        observed = primary.at_read(raw,[self.ids[3]],self.now,catalog=registry)
        self.assertEqual(observed["progetti"][0]["proiezione_circolazione"]["stato"],"OSSERVATO")
        with self.assertRaises(ValueError):
            primary.at_read(raw,[self.ids[3]],self.now,catalog=self.catalog)

    def test_monthly_supply_malformed_or_wrong_cap_fails_closed(self):
        import kdd_primary_economics as primary
        endpoint="https://sui-circulation.suiexplorer.com/api/sui_circulation"
        doc=[{"year":2026,"month":11,"circulatingSupplyValue":4_000_000_000,
              "circulatingSupplyPercentage":.4},
             {"year":2026,"month":12,"circulatingSupplyValue":3_900_000_000,
              "circulatingSupplyPercentage":.39}]
        o=primary.parse_monthly_projection(self.ids[3],doc,endpoint,self.now,
                                            maximum=10_000_000_000)
        self.assertEqual(o["stato"],"NON_VERIFICATO")
        bigger=[dict(x,circulatingSupplyValue=12_000_000_000) for x in doc]
        b=primary.parse_monthly_projection(self.ids[3],bigger,endpoint,self.now,
                                            maximum=10_000_000_000)
        self.assertEqual(b["stato"],"NON_VERIFICATO")

    def test_verified_proposal_is_not_effective_governance(self):
        import kdd_primary_economics as primary
        issue = {"html_url": "https://github.com/bitcoin/bitcoin/issues/123",
                 "created_at": "2026-11-11T00:00:00Z", "title": "Protocol review",
                 "labels": [{"name": "governance"}]}
        found = primary.parse_issues(self.ids[0],[issue],self.now)
        self.assertEqual(len(found),1)
        self.assertIsNone(found[0]["evento_utc"])
        self.assertEqual(found[0]["esito_proposta"],"NON_ATTESTATO")
        bad = dict(issue,html_url="https://github.com/other/repo/issues/123")
        self.assertEqual(primary.parse_issues(self.ids[0],[bad],self.now),[])
        self.assertEqual(primary.parse_issues(self.ids[0],[dict(issue,labels=[])],self.now),[])

    def test_macro_values_are_observed_not_consensus(self):
        import kdd_primary_economics as primary
        out = primary.parse_ecb_csv(self.macro_csv, "FM/D.U2.EUR.4F.KR.MRR_FR.LEV",
                                    "PERCENTUALE_ANNUA",self.now)
        self.assertEqual(out["valore"],2.25)
        self.assertEqual(out["precedente"]["valore"],2.15)
        self.assertIsNone(out["pubblicato_utc"])
        self.assertNotIn("consenso",out)
        with self.assertRaises(ValueError):
            primary.parse_ecb_csv(b"TIME_PERIOD,OBS_VALUE\n2028-01-01,9\n",
                                   "FM/D.U2.EUR.4F.KR.MRR_FR.LEV",
                                   "PERCENTUALE_ANNUA",self.now)

    def test_hicp_and_money_growth_monthly_negative_values_are_dated(self):
        import kdd_primary_economics as primary
        doc = b"TIME_PERIOD,OBS_VALUE\n2026-09,1.9\n2026-10,2.1\n"
        result=primary.parse_ecb_csv(doc,"HICP/M.U2.N.000000.4D0.ANR",
                                     "INFLAZIONE_AA_PCT",self.now)
        self.assertEqual(result["periodo_dato"],"2026-10-01")
        self.assertEqual(result["valore"],2.1)
        m3 = b"TIME_PERIOD,OBS_VALUE\n2026-08,-0.5\n2026-09,-0.2\n"
        money=primary.parse_ecb_csv(m3,"BSI/M.U2.Y.V.M30.X.I.U2.2300.Z01.A",
                                    "M3_CRESCITA_AA_PCT",self.now)
        self.assertEqual(money["valore"],-.2)
        self.assertEqual(money["stato"],"OSSERVATO")
        self.assertNotIn("previsione",money)

    def test_provider_failure_never_becomes_zero(self):
        import kdd_primary_economics as primary
        def blocked(url,payload=None):raise OSError("HTTP 429 rate limit")
        o = self._collect(ids=[self.ids[2]],fetch=blocked)
        self.assertEqual(o["progetti"][0]["politica_emissioni"]["stato"],
                         "NON_DISPONIBILE")
        self.assertEqual(o["progetti"][0]["calendario"]["eventi"],[])
        self.assertNotIn("valore",o["progetti"][0]["politica_emissioni"])
        self.assertLessEqual(o["richieste_effettuate"],8)

    def test_new_roster_is_dynamic_and_rejects_ticker_only(self):
        unknown = {"token":"ABC", "coingecko_id":"fake",
                   "stato":"NON_VERIFICATO"}
        out = self._collect(ids=[self.ids[1],unknown])
        self.assertEqual([x["coingecko_id"] for x in out["progetti"]],["near"])
        extra = {"stato":"IDENTITA_VERIFICATA_DA_CATALOGO",
                 "token":"XYZ", "token_progetto":"XYZ",
                 "coingecko_id":"new-coin", "progetto":"New Project",
                 "repository_primario":None}
        out2 = self._collect(ids=[extra])
        self.assertEqual(out2["progetti"][0]["coingecko_id"],"new-coin")
        self.assertEqual(out2["progetti"][0]["calendario"]["stato"],"NON_VERIFICATO")

    def test_gpt_reader_refuses_forged_project_and_expires_evidence(self):
        import copy,datetime
        import kdd_primary_economics as primary
        out=self._collect(ids=[self.ids[2]])
        ok=primary.at_read(out,[self.ids[2]],self.now)
        self.assertEqual(len(ok["progetti"]),1)
        stale=primary.at_read(out,[self.ids[2]],self.now+datetime.timedelta(days=8))
        self.assertEqual(stale["progetti"][0]["stato_alla_lettura"],"SCADUTO")
        forged=copy.deepcopy(out)
        forged["progetti"][0]["coingecko_id"]="different-coin"
        with self.assertRaises(ValueError):
            primary.at_read(forged,[self.ids[2]],self.now)

    def test_regime_contradiction_does_not_become_trade_signal(self):
        import kdd_economics as econ
        base={"stato":"RIALZISTA","qualita":"PARZIALE","contrari":[]}
        derivatives={"cvd":{"ultimo_punto_provvisorio":False,
                            "ultimo_punto_utc":self.now.isoformat(),
                            "ultimo_cvd":10.0,"cvd_4h_fa":50.0}}
        extended=econ.regime_integrated(base,derivatives,{},None,self.now)
        self.assertEqual(extended["stato"],"RIALZISTA")
        self.assertEqual(extended["qualita"],"CONFLITTO_DA_RIESAMINARE")
        self.assertNotIn("ordine",extended)
        older=econ.regime_integrated(base,{}, {},{"regime":extended},
                                      self.now+__import__('datetime').timedelta(hours=2))
        self.assertEqual(len(older["storico_regimi"]),1)


if __name__=="__main__":
    unittest.main()
