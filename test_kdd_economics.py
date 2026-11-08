"""Synthetic economic evidence tests: no private wallet, no network."""
import copy
import datetime as dt
import unittest
import kdd_economics as e

T=dt.datetime(2026,11,8,13,30,tzinfo=dt.timezone.utc)


class EconomicEvidenceTests(unittest.TestCase):
    def ident(self, token="BTC"):
        return e.identify(token,token+"/EUR",token+"EUR",catalog_verified=True)

    def market(self, ident=None, max_supply=21000000):
        ident=ident or self.ident()
        return {"id":ident["coingecko_id"],"symbol":ident["token"].lower(),
                "name":ident["progetto"],"market_data":{
                    "last_updated":T.isoformat(),"market_cap":{"usd":100},
                    "fully_diluted_valuation":{"usd":200},
                    "circulating_supply":10,"total_supply":20,
                    "max_supply":max_supply}}

    def test_identity_requires_verified_catalog_pair_and_curated_mapping(self):
        self.assertEqual(self.ident()["stato"],"IDENTITA_VERIFICATA_DA_CATALOGO")
        self.assertEqual(e.identify("BTC","XBT/EUR","XXBTZEUR",
                                    catalog_verified=True)["coingecko_id"],"bitcoin")
        for ident in (
            e.identify("BTC","BTC/EUR","BTCEUR",catalog_verified=False),
            e.identify("BTC","ETH/EUR","BTCEUR",catalog_verified=True),
            e.identify("BTC","BTC/EUR",None,catalog_verified=True),
            e.identify("FAKE","FAKE/EUR","FAKEEUR",catalog_verified=True),
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
        with mock.patch.object(producer.desk,"request",side_effect=fake), \
             mock.patch.object(producer.time,"sleep"):
            result=producer.economic_evidence({"feed":[]},portfolio,four,candidate,T)
        self.assertEqual(len(result["posizioni"]),10)
        self.assertEqual(len(result["candidati"]),1)
        self.assertEqual(result["candidati"][0]["fondamentali"]["stato"],"VERIFICATO")
        self.assertEqual(result["posizioni"][0]["fondamentali"]["stato"],"VERIFICATO")
        self.assertEqual(result["posizioni"][9]["identita"]["stato"],"NON_VERIFICATO")
        self.assertLessEqual(result["richieste_effettuate"],9)

    def test_missing_legacy_economics_does_not_create_facts(self):
        source,positions,shortlist=self.sample()
        source["posizioni"][0]["fondamentali"]["stato"]="NON_VERIFICATO"
        self.assertEqual(e.at_read(source,positions,shortlist,T)["posizioni"][0]
                         ["fondamentali"]["stato"],"NON_VERIFICATO")


if __name__=="__main__":
    unittest.main()
